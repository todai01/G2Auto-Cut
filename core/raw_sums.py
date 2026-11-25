"""«Разбор сырой записи сумм»: один длинный дубль, прочитанный по таблице, → куски по ярусам.

Таблица свободная (без тегов Студии): строка 1 — заголовки, дальше каждая строка блока столбцов
(блоки разделены пустым столбцом) — одна произносимая фраза, каждая непустая ячейка — ярус
(«С суммой задолженности | один миллион | пятьдесят одна тысяча | сто | одна тенге»: ячейка
«тысяча» сама по себе — конец яруса слева).
Блоки читаются по очереди, строки — сверху вниз.

Резка по тишине тут не работает (диктор читает почти без пауз, ошибается и повторяет), поэтому:
  1. распознавание всей записи (faster-whisper, числа он пишет цифрами — spell_digits);
  2. выравнивание распознанных слов с ожидаемыми фразами (как diff, но фразу можно начать заново,
     бросить на середине, повторить; последняя полная попытка — основная, прочие — запасные);
  3. границы ярусов — принудительным выравниванием ожидаемого текста на окне попытки
     (whisper find_alignment), затем «прилипание» к ближайшему минимуму громкости, края куска —
     до ближайшей тишины с запасом;
  4. проверка: распознанное на месте ячейки и внутри границ куска сверяется с текстом ячейки;
     не совпало — кусок неуверенный (красный).

Результат — папка кусков `<запись>_куски/<столбец заголовок>/<текст>.wav` (вырезаны байт в байт из
исходника), `_запасные/`, `_фразы/` (основная попытка целиком), `разбор.xlsx` и `_проверка.xlsx`
(A — текст, B — файл: для «Прослушки фраз»)."""
import difflib
import hashlib
import json
import os
import re
import threading
import time

# ---------------------------------------------------------------- словарь чисел
RS_NUM_LEX = (
    'ноль один одна два две три четыре пять шесть семь восемь девять десять одиннадцать двенадцать '
    'тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать '
    'тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто сто двести триста четыреста '
    'пятьсот шестьсот семьсот восемьсот девятьсот тысяча тысячи тысяч миллион миллиона миллионов тенге'
).split()
_LEX_SET = set(RS_NUM_LEX)
RS_GLUE_LEFT = {'тысяча', 'тысячи', 'тысяч'}   # такая ячейка не ярус, а конец яруса слева

# цены выравнивания (больше — лучше)
RS_INS = -0.6        # лишнее распознанное слово внутри попытки (запинка)
RS_DEL = -0.6        # пропущенное ожидаемое слово внутри попытки
RS_JUNK = -0.3       # слово между попытками (разговор, «так, ещё раз»)
RS_START = -0.5      # начать попытку
RS_SKIP_ROW = -0.8   # за каждую пропущенную строку при переходе вперёд
RS_BACK = -2.0       # вернуться к более ранней строке
RS_CUT = -0.25       # за каждое недочитанное слово, если попытку бросили (или начали с середины)
RS_BEAM = 14.0       # отсечение слабых вариантов

RS_OK_SIM = 0.6      # кусок, распознанный отдельно, похож на текст ячейки — уверенный
RS_ALIGN_MAX = 28.0  # окно принудительного выравнивания (whisper — 30 с)
RS_FRAME = 0.01      # шаг огибающей громкости, с
RS_GAP_SPLIT = 0.9   # пауза между словами соседних кусков дольше — режем по краям слов, не посередине


def rs_norm(w):
    """Слово для сравнения: без регистра, ё=е, только буквы и цифры."""
    return re.sub(r'[^0-9a-zа-яәғқңөұүһі]+', '', str(w or '').lower().replace('ё', 'е'))


def _lev(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _num_class(w):
    i = RS_NUM_LEX.index(w)
    if w == 'ноль':
        return 'z'
    if i <= 10:
        return 'u'          # один…девять (и одна, две), десять — как единицы
    if i <= 19:
        return 'u'          # одиннадцать…девятнадцать
    if i <= 27:
        return 't'          # двадцать…девяносто
    if i <= 36:
        return 'h'          # сто…девятьсот
    return 'tg' if w == 'тенге' else 's'


_NEXT_OK = {None: 'zuths', 'h': 'uts', 't': 'us', 'u': 's', 'z': '', 's': 'uths'}


def _segment_numbers(s):
    """Строка букв без пробелов → слова словаря чисел с наименьшим числом правок
    («пятнадцатьмиллионов» → пятнадцать миллионов, «деввять» → девять). Слова должны идти в порядке
    числа (сотни → десятки → единицы → тысяч/миллионов): «семь десять» — дорого. (слова, правок) или None."""
    n = len(s)
    best = {(0, None): (0.0, 0, [])}
    for i in range(n):
        for (pos, last), (cost, ed, ws) in list(best.items()):
            if pos != i:
                continue
            for w in RS_NUM_LEX:
                for L in range(max(1, len(w) - 2), len(w) + 3):
                    if i + L > n:
                        break
                    d = _lev(s[i:i + L], w)
                    if d > (1 if len(w) < 7 else 2):
                        continue
                    c = _num_class(w)
                    bad = 0 if c == 'tg' or c in _NEXT_OK.get(last, '') else 2
                    key = (i + L, c)
                    cand = (cost + d + bad, ed + d, ws + [w])
                    if key not in best or cand[0] < best[key][0]:
                        best[key] = cand
    ends = [v for (pos, _), v in best.items() if pos == n]
    if not ends:
        return None
    cost, ed, ws = min(ends, key=lambda v: v[0])
    return ws, ed


def rs_canon(text):
    """Текст ячейки → слова. Числовая ячейка чинится по словарю (опечатки, слипшиеся и
    разорванные слова), остальное (начальная фраза) — как есть, только без регистра и знаков."""
    words = [rs_norm(w) for w in str(text or '').split()]
    words = [w for w in words if w]
    if not words:
        return []
    if all(w in _LEX_SET for w in words):
        return words
    seg = _segment_numbers(''.join(words))
    if seg and seg[1] <= max(1, len(''.join(words)) // 6):
        return seg[0]
    return words


_RS_VAL = {w: v for v, ws in (
    (0, 'ноль'), (1, 'один одна'), (2, 'два две'), (3, 'три'), (4, 'четыре'), (5, 'пять'), (6, 'шесть'), (7, 'семь'),
    (8, 'восемь'), (9, 'девять'), (10, 'десять'), (11, 'одиннадцать'), (12, 'двенадцать'), (13, 'тринадцать'),
    (14, 'четырнадцать'), (15, 'пятнадцать'), (16, 'шестнадцать'), (17, 'семнадцать'), (18, 'восемнадцать'),
    (19, 'девятнадцать'), (20, 'двадцать'), (30, 'тридцать'), (40, 'сорок'), (50, 'пятьдесят'), (60, 'шестьдесят'),
    (70, 'семьдесят'), (80, 'восемьдесят'), (90, 'девяносто'), (100, 'сто'), (200, 'двести'), (300, 'триста'),
    (400, 'четыреста'), (500, 'пятьсот'), (600, 'шестьсот'), (700, 'семьсот'), (800, 'восемьсот'), (900, 'девятьсот'))
    for w in ws.split()}
RS_CATS = ('million', 'hundred_thousand', 'hundred', 'thousand', 'tenge')          # классы сумм как в Студии
# папки классов — как ярусы сумм в Студии (TtsFlowMixin.SUM_TIER_DIRS); имя файла — число:
# «один миллион» → 1, «пятьдесят одна тысяча» → 51, «сто» → 100, «сто тысяч» → 100, «одна тенге» → 1
RS_CAT_DIRS = {'million': '1 - 100 млн', 'hundred_thousand': '100 - 900 тыс', 'hundred': '100 - 900',
               'thousand': '1 - 99 тыс', 'tenge': '1 - 100 тенге'}
RS_LOGICS = {1: ('million', 'hundred', 'thousand', 'tenge'), 2: ('million', 'hundred_thousand', 'tenge')}
RS_CAT_SHORT = {'million': 'млн', 'hundred_thousand': 'тыс', 'hundred': '', 'thousand': 'тыс', 'tenge': 'тенге'}


def _rs_num(words):
    """Слова до 999 → число (None — не число)."""
    if not words or any(w not in _RS_VAL for w in words):
        return None
    return sum(_RS_VAL[w] for w in words)


def rs_cell_cat(words):
    """Ячейка → (класс суммы, число) как в Студии или None: «пятьдесят одна тысяча» → ('thousand', 51),
    «сто тысяч» → ('hundred_thousand', 100), «сто» → ('hundred', 100), «одна тенге» → ('tenge', 1),
    «миллион» → ('million', 1). Начальная фраза, «тенге» без числа — None."""
    if not words:
        return None
    last, head = words[-1], words[:-1]
    if last == 'тенге':
        n = _rs_num(head)
        return ('tenge', n) if n is not None else None
    if last.startswith('миллион'):
        n = _rs_num(head) if head else 1
        return ('million', n) if n else None
    if last.startswith('тысяч'):
        n = _rs_num(head) if head else 1
        if not n:
            return None
        if n % 100 == 0:
            return ('hundred_thousand', n)
        return ('thousand', n)
    n = _rs_num(words)
    if n and n % 100 == 0 and n <= 900:
        return ('hundred', n)
    return None


def _is_label(text):
    """Заголовок внутри таблицы («100-900 к», «Дополнительно»): цифры — точно заголовок."""
    return bool(re.search(r'\d', str(text)))


def _col_letter(c):
    s = ''
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def rs_read_grid(grid):
    """Сетка значений (строки списков) → {"phrases": [...], "tiers": {столбец: заголовок}, "skipped": [...]}.
    Фраза: {"id", "block", "row" (с 1), "cells": [{"col", "tier", "text", "words"}], "words": [...], "cell_of": [...]}."""
    cell = lambda r, c: str(grid[r][c]).strip() if c < len(grid[r]) and grid[r][c] is not None else ''
    ncol = max((len(r) for r in grid), default=0)
    used = [c for c in range(ncol) if any(cell(r, c) for r in range(1, len(grid)))]
    blocks, cur = [], []
    for c in used:
        if cur and c != cur[-1] + 1:
            blocks.append(cur)
            cur = []
        cur.append(c)
    if cur:
        blocks.append(cur)
    head = {c: cell(0, c) if grid else '' for c in range(ncol)}
    tiers = {}
    phrases, skipped = [], []
    for b, cols in enumerate(blocks):
        cur_head = dict(head)
        for r in range(1, len(grid)):
            vals = [(c, cell(r, c)) for c in cols if cell(r, c)]
            if not vals:
                continue
            cells = []
            for c, v in vals:
                if _is_label(v):
                    cur_head[c] = v                     # заголовок посреди таблицы — для ячеек ниже
                    continue
                words = rs_canon(v)
                if not words:
                    continue
                if cells and all(w in RS_GLUE_LEFT for w in words):
                    # «тысяча / тысячи / тысяч» отдельной ячейкой — часть куска слева: «пятьдесят одна тысяча»
                    cells[-1]["words"] = cells[-1]["words"] + words
                    cells[-1]["text"] = ' '.join(cells[-1]["words"])
                    cells[-1]["cat"] = rs_cell_cat(cells[-1]["words"])
                    continue
                tier = f'{_col_letter(c)} {cur_head.get(c) or ""}'.strip()
                tiers[_col_letter(c)] = tier
                cells.append({"col": _col_letter(c), "tier": tier, "text": ' '.join(words), "words": words,
                              "num": all(w in _LEX_SET for w in words), "cat": rs_cell_cat(words)})
            if len(cells) < 2:
                if cells:
                    skipped.append({"row": r + 1, "block": b, "text": ' | '.join(x["text"] for x in cells)})
                continue
            words, cell_of = [], []
            for k, x in enumerate(cells):
                words += x["words"]
                cell_of += [k] * len(x["words"])
            phrases.append({"id": len(phrases), "block": b, "row": r + 1, "cells": cells,
                            "words": words, "cell_of": cell_of})
    return {"phrases": phrases, "tiers": tiers, "skipped": skipped}


def rs_read_table(path):
    """Excel → rs_read_grid по листу с наибольшим числом фраз."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    best = None
    try:
        for ws in wb.worksheets:
            grid = [list(r) for r in ws.iter_rows(values_only=True)]
            res = rs_read_grid(grid)
            res["sheet"] = ws.title
            if best is None or len(res["phrases"]) > len(best["phrases"]):
                best = res
    finally:
        wb.close()
    return best or {"phrases": [], "tiers": {}, "skipped": [], "sheet": None}


# ---------------------------------------------------------------- распознанные слова
def rs_rec_words(words):
    """[(слово, начало, конец, вероятность)] от whisper → нормализованные, числа словами.
    «млн» → «миллионов». Вероятность сохраняется."""
    from core.tts_live import spell_digits
    raw = [[w, s, e] for w, s, e, *_ in words]
    probs = {i: (p[3] if len(p) > 3 else 1.0) for i, p in enumerate(words)}
    try:
        sp = spell_digits(raw, 'ru')
    except Exception:
        sp = raw
    out = []
    for w in sp:
        for part in str(w[0]).split():
            n = rs_norm(part)
            if n == 'млн':
                n = 'миллионов'
            if n:
                out.append((n, float(w[1]), float(w[2])))
    return out


_SIM_CACHE = {}


def rs_sim(a, b):
    key = (a, b)
    v = _SIM_CACHE.get(key)
    if v is None:
        v = 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()
        if len(_SIM_CACHE) > 200000:
            _SIM_CACHE.clear()
        _SIM_CACHE[key] = v
    return v


def _match_score(a, b):
    return 2.0 * rs_sim(a, b) - 1.0


def rs_align(rec, phrases, beam=RS_BEAM):
    """Выравнивание распознанных слов rec [(слово, нач, кон)] с фразами (в порядке чтения).
    Состояния: (r, j) — в попытке фразы r прочитано j слов; ('J', r) — между попытками, последней была r.
    Попытку можно начать с любой фразы (вперёд дешевле, назад дорого), бросить или начать не с начала
    (штраф RS_CUT за слово). Возвращает попытки по времени:
    [{"r", "i0", "i1", "pairs": [(i, j)], "j0", "j1", "matched", "complete", "score"}]."""
    R = len(phrases)
    L = [len(p["words"]) for p in phrases]
    J = lambda r: ('J', r)

    def start_cost(prev_r, r):
        if prev_r < 0:
            d = r
            return RS_START + RS_SKIP_ROW * d
        if r >= prev_r:
            return RS_START + RS_SKIP_ROW * max(0, r - prev_r - 1)
        return RS_START + RS_BACK

    def closure(col, back, t):
        """ε-переходы в столбце t: конец попытки → J, J → начало попытки, пропуск слов внутри."""
        for st, sc in list(col.items()):                             # конец (в т. ч. брошенная)
            if st[0] == 'J':
                continue
            r, j = st
            v = sc + RS_CUT * (L[r] - j) if j < L[r] else sc
            if j == 0:
                continue
            k = J(r)
            if v > col.get(k, -1e18):
                col[k], back[(t, k)] = v, (t, st, 'end')
        best = max(col.values()) if col else 0
        for st, sc in list(col.items()):                             # начало новой попытки
            if st[0] != 'J' or sc < best - beam:
                continue
            pr = st[1]
            for r in range(R):
                base = sc + start_cost(pr, r)
                if base < best - beam:
                    continue
                for j in range(L[r]):
                    v = base + RS_CUT * j
                    if v < best - beam:
                        break
                    k = (r, j)
                    if v > col.get(k, -1e18):
                        col[k], back[(t, k)] = v, (t, st, 'start')
        for st in sorted([s for s in col if s[0] != 'J'], key=lambda s: (s[0], s[1])):   # пропуск ожидаемого
            r, j = st
            sc = col[st]
            while j < L[r]:
                sc += RS_DEL
                k = (r, j + 1)
                if sc <= col.get(k, -1e18):
                    break
                col[k], back[(t, k)] = sc, (t, (r, j), 'del')
                j += 1

    back = {}
    col = {J(-1): 0.0}
    closure(col, back, 0)
    for i, (w, _, _) in enumerate(rec):
        t = i + 1
        new = {}
        best = max(col.values())
        for st, sc in col.items():
            if sc < best - beam:
                continue
            if st[0] == 'J':
                v = sc + RS_JUNK
                if v > new.get(st, -1e18):
                    new[st], back[(t, st)] = v, (i, st, 'junk')
                continue
            r, j = st
            if j < L[r]:
                v = sc + _match_score(w, phrases[r]["words"][j])
                k = (r, j + 1)
                if v > new.get(k, -1e18):
                    new[k], back[(t, k)] = v, (i, st, 'match')
            v = sc + RS_INS
            if v > new.get(st, -1e18):
                new[st], back[(t, st)] = v, (i, st, 'ins')
        closure(new, back, t)
        col = new
    # финал — лучшее состояние «между попытками»
    end = max((s for s in col if s[0] == 'J'), key=lambda s: col[s], default=None)
    if end is None:
        return []
    ops, t, st = [], len(rec), end
    while (t, st) in back:
        pt, pst, op = back[(t, st)]
        ops.append((t, st, op, pst))
        if op in ('end', 'start', 'del'):
            st = pst                       # тот же столбец
        else:
            t, st = pt, pst
    ops.reverse()
    attempts, cur = [], None
    for t, st, op, pst in ops:
        if op == 'start':
            cur = {"r": st[0], "pairs": [], "ins": [], "j_start": st[1]}
        elif op == 'match' and cur is not None:
            cur["pairs"].append((t - 1, pst[1]))
        elif op == 'ins' and cur is not None:
            cur["ins"].append(t - 1)
        elif op == 'end' and cur is not None:
            if cur["pairs"]:
                attempts.append(cur)
            cur = None
    out = []
    for a in attempts:
        r = a["r"]
        good = [(i, j) for i, j in a["pairs"] if rs_sim(rec[i][0], phrases[r]["words"][j]) >= 0.5]
        if not good:
            continue
        js = [j for _, j in good]
        cell_of = phrases[r]["cell_of"]
        ncell = cell_of[-1] + 1
        # полная: есть первая и последняя ячейка, и прочитано почти всё («с суммой» ↔ «сумма» — не беда)
        out.append({"r": r, "pairs": a["pairs"], "good": good, "ins": a["ins"],
                    "i0": a["pairs"][0][0], "i1": a["pairs"][-1][0],
                    "j0": min(js), "j1": max(js), "matched": len(good),
                    "complete": cell_of[min(js)] == 0 and cell_of[max(js)] == ncell - 1
                    and max(js) == L[r] - 1 and len(good) >= max(1, L[r] - 2)})
    return out


def rs_cell_heard(rec, phrase, attempt):
    """Что распознано на месте каждой ячейки попытки: {k: (слова, сходство 0..1)}.
    Сходство — по буквам всей ячейки («с суммой задолженности» ≈ «сумма задолженности»)."""
    heard = {}
    for i, j in attempt["pairs"]:
        heard.setdefault(phrase["cell_of"][j], []).append(rec[i][0])
    for i in attempt.get("ins", []):                   # лишнее слово внутри — к ближайшей ячейке слева
        js = [j for ii, j in attempt["pairs"] if ii < i]
        if js:
            heard.setdefault(phrase["cell_of"][js[-1]], []).append(rec[i][0])
    out = {}
    for k, c in enumerate(phrase["cells"]):
        h = heard.get(k, [])
        out[k] = (' '.join(h), rs_text_sim(h, c["words"]))
    return out


def rs_choose(attempts, phrases):
    """Для каждой фразы — основная попытка (последняя полная, иначе самая полная из последних) и запасные."""
    by = {}
    for k, a in enumerate(attempts):
        by.setdefault(a["r"], []).append(k)
    res = {}
    for r, ks in by.items():
        full = [k for k in ks if attempts[k]["complete"]]
        main = full[-1] if full else max(ks, key=lambda k: (attempts[k]["matched"], k))
        res[r] = {"main": main, "spare": [k for k in ks if k != main]}
    return res


# ---------------------------------------------------------------- громкость и границы
def rs_envelope(x, sr):
    """Огибающая громкости, дБ на каждые 10 мс (сглажена на 50 мс), и порог тишины."""
    import numpy as np
    f = max(1, int(sr * RS_FRAME))
    n = len(x) // f
    if n == 0:
        return np.zeros(0), -60.0
    rms = np.sqrt((x[:n * f].reshape(n, f).astype('float64') ** 2).mean(1)) + 1e-9
    db = 20 * np.log10(rms)
    db = np.convolve(db, np.ones(5) / 5, 'same')
    lo, hi = np.percentile(db, 10), np.percentile(db, 95)
    thr = max(lo + 15, hi - 38)
    return db, float(thr)


def rs_snap(db, thr, t, radius=0.25, right=None):
    """Граница между словами: ближайший минимум громкости в [t - radius, t + right] (тишина — середина паузы)."""
    import numpy as np
    n = len(db)
    i = int(round(t / RS_FRAME))
    right = radius if right is None else right
    a, b = max(0, i - int(radius / RS_FRAME)), min(n, i + int(right / RS_FRAME) + 1)
    if a >= b:
        return t
    seg = db[a:b]
    quiet = np.where(seg < thr)[0]
    if len(quiet):
        # участки тишины: берём ближайший к t, режем посередине
        runs, s = [], quiet[0]
        for p, q in zip(quiet, list(quiet[1:]) + [None]):
            if q is None or q != p + 1:
                runs.append((s, p))
                s = q
        mid = min(((s + e) / 2 for s, e in runs), key=lambda m: abs(a + m - i))
        return (a + mid) * RS_FRAME
    k = int(np.argmin(seg + 0.05 * np.abs(np.arange(a, b) - i)))
    return (a + k) * RS_FRAME


def rs_longest_pause(db, thr, lo, hi, min_len=0.08):
    """Середина самой длинной паузы (≥ min_len) в [lo, hi] или None."""
    a, b = max(0, int(lo / RS_FRAME)), min(len(db), int(hi / RS_FRAME))
    best, s = None, None
    for i in range(a, b + 1):
        q = i < b and db[i] < thr
        if q and s is None:
            s = i
        elif not q and s is not None:
            if (i - s) * RS_FRAME >= min_len and (best is None or i - s > best[1] - best[0]):
                best = (s, i)
            s = None
    return None if best is None else (best[0] + best[1]) / 2 * RS_FRAME


def rs_voice_start(db, thr, t, lo, pad=0.06):
    """Начало куска: от t назад (не раньше lo) — до тишины, потом запас pad."""
    i, a = int(t / RS_FRAME), max(0, int(lo / RS_FRAME))
    while i > a and db[i - 1] >= thr:
        i -= 1
    return max(lo, i * RS_FRAME - pad)


def rs_voice_end(db, thr, t, hi, pad=0.1):
    """Конец куска: от t вперёд (не дальше hi) — до тишины, потом запас pad."""
    n = len(db)
    i, b = int(t / RS_FRAME), min(n, int(hi / RS_FRAME))
    while i < b and db[i] >= thr:
        i += 1
    return min(hi, i * RS_FRAME + pad)


def rs_first_onset(db, thr, lo, hi, min_gap=0.12):
    """Начало речи попытки: конец самой длинной паузы в [lo, hi] (DTW whisper тянет первое слово
    на всю тишину перед ним). Нет пауз — lo."""
    a, b = max(0, int(lo / RS_FRAME)), min(len(db), int(hi / RS_FRAME))
    best, s = None, None
    for i in range(a, b + 1):
        q = i < b and db[i] < thr
        if q and s is None:
            s = i
        elif not q and s is not None:
            if (i - s) * RS_FRAME >= min_gap and (best is None or i - s >= best[1] - best[0]):
                best = (s, i)
            s = None
    if best is None:
        return lo
    return best[1] * RS_FRAME


def rs_cells_bounds(phrase, word_times, j0, db, thr, lo, hi):
    """Слова попытки с временем (j0.., [(нач, кон)]) → куски ячеек [(k ячейки, нач, кон)].
    Внутренние границы — rs_snap; первая — начало речи, последняя — до тишины."""
    cell_of = phrase["cell_of"]
    spans, wl, wf, ls = {}, {}, {}, {}
    for d, (s, e) in enumerate(word_times):
        k = cell_of[j0 + d]
        if k in spans:
            spans[k][1] = e
        else:
            spans[k] = [s, e]
            wf[k] = e - s                       # длина первого слова куска
        wl[k] = e - s                           # длина последнего слова куска
        ls[k] = s                               # начало последнего слова куска
    ks = sorted(spans)
    ends, starts = [], []              # конец куска k и начало куска k+1 (обычно одна и та же точка)
    for a, b in zip(ks, ks[1:]):
        gap = spans[b][0] - spans[a][1]
        if gap > RS_GAP_SPLIT:
            # между словами долгая пауза — там, скорее всего, пропущенный повтор: режем по краям слов
            e = rs_voice_end(db, thr, spans[a][1], min(spans[b][0], spans[a][1] + 0.5))
            s = max(e, rs_voice_start(db, thr, spans[b][0], max(e, spans[b][0] - 0.5)))
            ends.append(e)
            starts.append(s)
            continue
        c = None
        if not phrase["cells"][a].get("num", True) and phrase["cells"][b].get("num", True):
            # начальная фраза → первое число: начальная не сохраняется, поэтому режем в самой длинной паузе между её
            # последним словом и началом числа — хвост «…сти» не уйдёт в кусок с числом (время слов бывает неточным)
            c = rs_longest_pause(db, thr, ls[a] + 0.1, max(ls[a] + 0.1, spans[b][0] + wf[b] / 2), min_len=0.12)
        if c is None:
            # «прилипание» не глубже 40 % крайнего слова с каждой стороны и не назад за прошлую границу
            left = max(0.03, min(0.25, 0.4 * wl[a]))
            right = max(0.03, min(0.25, 0.4 * wf[b]))
            c = rs_snap(db, thr, (spans[a][1] + spans[b][0]) / 2, left, right)
        if starts and c < starts[-1] + 0.1:
            c = max(starts[-1] + 0.1, (spans[a][1] + spans[b][0]) / 2)
        ends.append(c)
        starts.append(c)
    first_s = spans[ks[0]][0]
    first_e = spans[ks[0]][1]
    start = rs_first_onset(db, thr, lo, max(lo, first_e - 0.15))
    start = rs_voice_start(db, thr, max(start, min(first_s, first_e)), lo) if start <= lo else max(lo, start - 0.06)
    i, lim = int(start / RS_FRAME) + 6, int(min(first_e, ends[0] if ends else first_e) / RS_FRAME)
    while i < lim and i < len(db) and db[i] < thr:          # тишина в начале куска — до голоса, с запасом
        i += 1
    start = max(start, i * RS_FRAME - 0.06)
    end = rs_voice_end(db, thr, spans[ks[-1]][1], hi)
    lefts, rights = [start] + starts, ends + [end]
    out = []
    for n, k in enumerate(ks):
        s, e = lefts[n], rights[n]
        if e - s < 0.08:
            e = s + 0.08
        out.append((k, s, e))
    return out


def rs_safe_name(s):
    return re.sub(r'[\\/:*?"<>|\n\r\t]+', '_', str(s)).strip(' .') or '_'


# ---------------------------------------------------------------- звук и модель
def rs_load_audio(path):
    """Звук как float32 моно и частота. WAV читается напрямую (любая разрядность, float), прочее — pydub."""
    import numpy as np
    from utils.wav_io import wav_layout, wav_kind
    lay = wav_layout(path)
    if lay:
        fmt, pos, size, block, rate = lay
        import struct
        ch = struct.unpack('<H', fmt[2:4])[0] or 1
        kind, bits = wav_kind(path)
        with open(path, 'rb') as f:
            f.seek(pos)
            raw = f.read(size - size % max(1, block))
        if kind == 'float':
            x = np.frombuffer(raw, '<f4' if bits == 32 else '<f8').astype(np.float32)
        elif bits == 8:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif bits == 24:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
            v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            x = v.astype(np.float32) / (1 << 23)
        else:
            dt = {16: '<i2', 32: '<i4'}.get(bits, '<i2')
            x = np.frombuffer(raw, dt).astype(np.float32) / float(2 ** (bits - 1))
        x = x.reshape(-1, ch).mean(1) if ch > 1 else x
        return x.astype(np.float32), int(rate)
    from pydub import AudioSegment
    seg = AudioSegment.from_file(path).set_channels(1).set_sample_width(2)
    x = np.frombuffer(seg.raw_data, '<i2').astype(np.float32) / 32768
    return x, seg.frame_rate


def rs_to16k(x, sr):
    import numpy as np
    from utils.wav_io import resample_audio
    if sr == 16000:
        return x.astype(np.float32)
    return resample_audio(x.reshape(-1, 1), sr, 16000)[:, 0].astype(np.float32)


RS_PROMPT = ('Сумма задолженности, сумма задолженности... ой, прошу прощения. '
             'Сумма задолженности два миллиона пятьдесят две тысячи двести два тенге.')
RS_WIN_MIN, RS_WIN_MAX, RS_WIN_GAP = 4.0, 12.0, 0.25
_HALLU = ('субтитр', 'продолжение следует', 'спасибо за просмотр', 'dimatorzok', 'редактор', 'подписывайтесь')


def rs_windows(db, thr, dur):
    """Окна распознавания 4–12 с, границы — посреди пауз ≥ 0,25 с. В коротком окне whisper пишет
    дословно (оговорки, повторы); на длинном куске он их «причёсывает» и склеивает числа."""
    n = len(db)
    gaps, s = [], None
    for i in range(n + 1):
        v = i < n and db[i] < thr
        if v and s is None:
            s = i
        elif not v and s is not None:
            if (i - s) * RS_FRAME >= RS_WIN_GAP:
                gaps.append((s + i) / 2 * RS_FRAME)
            s = None
    cuts = [0.0]
    for c in gaps:
        if c - cuts[-1] >= RS_WIN_MIN and dur - c >= 1.0:
            cuts.append(c)
    cuts.append(dur)
    win = []
    for a, b in zip(cuts, cuts[1:]):
        while b - a > RS_WIN_MAX + 2:              # пауз нет — режем ровно (редко)
            win.append((a, a + RS_WIN_MAX))
            a += RS_WIN_MAX
        win.append((a, b))
    return win


RS_PACK_MAX, RS_PACK_GAP = 27.0, 1.0
RS_WORD_MAX = 1.6    # слово дольше и с лишним голосом внутри — подозрительное (см. rs_transcribe)


def rs_packs(win, max_len=RS_PACK_MAX, gap=RS_PACK_GAP):
    """Окна 4–12 с → пачки для одного прохода модели (она всегда считает 30 с): окна подряд,
    между ними 1 с тишины. Каждое окно по-прежнему отдельная «фраза» — whisper пишет дословно,
    а модель работает в 3–4 раза реже."""
    packs, cur, size = [], [], 0.0
    for a, b in win:
        need = (b - a) + (gap if cur else 0.0)
        if cur and size + need > max_len:
            packs.append(cur)
            cur, size, need = [], 0.0, b - a
        cur.append((a, b))
        size += need
    if cur:
        packs.append(cur)
    return packs


def rs_clock(sec):
    sec = int(max(0, sec))
    return f'{sec // 60}:{sec % 60:02d}'


def _rs_words_of(segs, conv):
    out = []
    for x in segs:
        if any(h in x.text.lower() for h in _HALLU):
            continue
        for w in (x.words or []):
            r = conv(float(w.start), float(w.end))
            if r:
                out.append((w.word.strip(), r[0], r[1], float(w.probability)))
    return out


def _rs_asr(model, audio):
    return model.transcribe(audio, language='ru', word_timestamps=True, beam_size=5, condition_on_previous_text=False,
                            vad_filter=False, no_speech_threshold=None, initial_prompt=RS_PROMPT)[0]


def _rs_pack_words(model, a16, db, thr, pk, dur, note=None):
    """Одна пачка: склеить окна через 1 с тишины, распознать, перевести время слов в время записи;
    окно с «резиновым» словом, где спрятана речь, — заново отдельно. (Сжимать паузы внутри окна пробовали —
    модель от этого считает дольше и теряет оборванные попытки.)"""
    import numpy as np
    parts, offs, pos = [], [], 0.0
    for a, b in pk:
        if parts:
            parts.append(np.zeros(int(RS_PACK_GAP * 16000), np.float32))
            pos += RS_PACK_GAP
        seg = a16[int(a * 16000):int(b * 16000)]
        offs.append((pos, pos + len(seg) / 16000, a))
        parts.append(seg)
        pos += len(seg) / 16000

    def conv(ws, we):
        mid = (ws + we) / 2
        p0, p1, a_ = min(offs, key=lambda q: 0 if q[0] <= mid < q[1] else min(abs(mid - q[0]), abs(mid - q[1])))
        s_, e_ = a_ + min(max(0.0, ws - p0), p1 - p0), a_ + min(max(0.0, we - p0), p1 - p0)
        return (s_, e_) if e_ - s_ >= 0.03 else None    # нулевые — «досказанная» подсказка
    got = _rs_words_of(_rs_asr(model, np.concatenate(parts)), conv)

    def hides_speech(w):
        # «резиновое» слово: длинное И внутри голоса больше, чем нужно на это слово (паузу модель тоже
        # приписывает слову — из-за одной паузы окно не перепроверяем)
        if w[2] - w[1] <= RS_WORD_MAX:
            return False
        ia, ib = int(w[1] / RS_FRAME), int(w[2] / RS_FRAME)
        voiced = float((db[ia:ib] >= thr).sum()) * RS_FRAME
        vow = sum(rs_norm(w[0]).count(v) for v in 'аеёиоуыэюя')
        return voiced > 0.8 + 0.32 * max(1, vow)
    for a, b in pk:
        if not any(hides_speech(w) and a <= (w[1] + w[2]) / 2 < b for w in got):
            continue
        if note:
            note(f'перепроверяю окно {rs_clock(a)}–{rs_clock(b)}: в растянутом слове спрятана речь', a)
        wa, wb = max(0.0, a - 1.5), min(dur, b + 1.5)
        new = _rs_words_of(_rs_asr(model, a16[int(wa * 16000):int(wb * 16000)]),
                           lambda ws, we: (wa + ws, wa + we) if a <= wa + (ws + we) / 2 < b and we - ws >= 0.03 else None)
        if new:
            got = [w for w in got if not (a <= (w[1] + w[2]) / 2 < b)] + new
    got.sort(key=lambda w: w[1])
    return got


def _rs_part_load(path, packs):
    """Готовые пачки прошлого (прерванного) распознавания: {номер: слова}, только если окна те же."""
    done = {}
    if not path or not os.path.exists(path):
        return done
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue                                   # недописанная строка (выключили на полуслове)
                n = d.get("n")
                if isinstance(n, int) and 0 <= n < len(packs) and \
                        [[round(a, 3), round(b, 3)] for a, b in packs[n]] == d.get("win"):
                    done[n] = [tuple(w) for w in d.get("words", [])]
    except OSError:
        pass
    return done


def rs_transcribe(model, a16, progress=None, stop=None, db=None, thr=None, on_pack=None, workers=1, part=None):
    """Вся запись → слова [(слово, нач, кон, вероятность)]. Окна по паузам (rs_windows) склеены в пачки через тишину
    (rs_packs); время слов — время записи.
    workers > 1 — пачки считаются параллельно (у модели должно быть столько же num_workers).
    on_pack(info) — после каждой пачки (слова на сейчас, позиция, текст); words=None — только сообщение."""
    from concurrent.futures import ThreadPoolExecutor
    dur = len(a16) / 16000
    if db is None:
        db, thr = rs_envelope(a16, 16000)
    win = rs_windows(db, thr, dur)
    packs = rs_packs(win)
    out = []
    done = _rs_part_load(part, packs)          # part — файл «по пачкам»: распознавание продолжается с места остановки
    if done and on_pack:
        on_pack({"pack": len(done), "packs": len(packs), "pos": packs[max(done)][-1][1], "dur": dur, "words": None,
                 "text": f'продолжаю: уже распознано {len(done)} пачек из {len(packs)}', "resumed": len(done)})

    def job(nk):
        n, pk = nk
        if n in done:
            return done[n]

        def note(text, pos):
            if on_pack:
                on_pack({"pack": n + 1, "packs": len(packs), "pos": pos, "dur": dur, "words": None, "text": text})
        return None if (stop and stop()) else _rs_pack_words(model, a16, db, thr, pk, dur, note)
    pf = open(part, 'a', encoding='utf-8') if part else None
    try:
        with ThreadPoolExecutor(max_workers=max(1, int(workers))) as ex:
            for n, got in enumerate(ex.map(job, enumerate(packs))):
                if got is None:
                    break
                if pf and n not in done:
                    pf.write(json.dumps({"n": n, "win": [[round(a, 3), round(b, 3)] for a, b in packs[n]],
                                         "words": [list(w[:4]) for w in got]}, ensure_ascii=False) + '\n')
                    pf.flush()
                out += got
                pos = packs[n][-1][1]
                if progress:
                    progress(min(1.0, pos / max(dur, 1e-6)))
                if on_pack:
                    on_pack({"pack": n + 1, "packs": len(packs), "pos": pos, "dur": dur, "words": out,
                             "text": ' '.join(w[0] for w in got)})
                if stop and stop():
                    break
    finally:
        if pf:
            pf.close()
    return [w[:4] for w in out]


def rs_merge_windows(words):
    """Слова из перекрывающихся окон: одно и то же место есть в двух окнах — оставляем слово,
    которое дальше от края своего окна (у края whisper ошибается и теряет слова)."""
    words = sorted((w for w in words if w[2] - w[1] >= 0.03), key=lambda w: w[1])   # нулевые — «досказанная» подсказка
    kept = []
    for w in words:
        clash = [k for k in range(max(0, len(kept) - 6), len(kept))
                 if min(kept[k][2], w[2]) - max(kept[k][1], w[1]) > 0.4 * max(0.02, min(kept[k][2] - kept[k][1], w[2] - w[1]))]
        if not clash:
            kept.append(w)
            continue
        if all(w[4] > kept[k][4] for k in clash):
            for k in reversed(clash):
                del kept[k]
            kept.append(w)
            kept.sort(key=lambda v: v[1])
    return [w[:4] for w in kept]


def rs_force_align(model, a16, t0, t1, words):
    """Принудительное выравнивание текста words на окне [t0, t1] (≤ 30 с): [(нач, кон, вероятность)] или None."""
    import numpy as np
    from faster_whisper.tokenizer import Tokenizer
    tok = Tokenizer(model.hf_tokenizer, True, task='transcribe', language='ru')
    seg = a16[int(t0 * 16000):int(t1 * 16000)]
    if len(seg) < 1600 or not words:
        return None
    feat = model.feature_extractor(seg)
    n = feat.shape[-1]
    full = 3000
    feat = np.pad(feat, ((0, 0), (0, max(0, full - n))))[:, :full]
    enc = model.encode(feat)
    toks = tok.encode(' ' + ' '.join(words))
    res = model.find_alignment(tok, [toks], enc, min(n, full))
    res = res[0] if res else []
    if len(res) != len(words):
        return None
    return [(t0 + float(w['start']), t0 + float(w['end']), float(w['probability'])) for w in res]


def rs_text_sim(heard, words):
    """Сходство распознанного куска с текстом ячейки (по буквам, без пробелов)."""
    a, b = ''.join(heard), ''.join(words)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- весь разбор
def rs_piece_rel(pc):
    """Где лежит основной кусок: класс суммы — «1 - 99 тыс/51.wav» (как ищут «Прослушка» и Студия),
    иначе — по столбцу таблицы «<столбец заголовок>/<текст>.wav»."""
    if pc.get("cat"):
        cat, n = pc["cat"]
        return os.path.join(RS_CAT_DIRS[cat], f'{n}.wav')
    return os.path.join(rs_safe_name(pc["tier"]), rs_safe_name(pc["text"]) + '.wav')


RS_SETTLE = 25.0     # фраза «готова» к нарезке, когда распознавание ушло дальше её конца на столько секунд
RS_LIVE_STEP = 45.0  # во время распознавания нарезка — не чаще, чем раз в столько секунд записи


class RsCutter:
    """Нарезка по ходу распознавания: process() режет фразы, которые уже закончились (распознавание ушло
    дальше, диктор читает следующие строки), и сразу пишет куски в папку — их можно слушать, не дожидаясь
    конца. Фраза, у которой после повторного выравнивания поменялись попытки, режется заново (свои же файлы
    этого разбора перезаписываются). finish() — итог и отчёты."""

    def __init__(self, model, wav_path, table, out_dir, a16, db, thr, log=None, stop=None):
        self.model, self.wav, self.out = model, wav_path, out_dir
        self.phrases = table["phrases"]
        self.a16, self.db, self.thr = a16, db, thr
        self.dur = len(a16) / 16000
        self.log = log or (lambda d: None)
        self.stop = stop or (lambda: False)
        self.sig = {}          # r → чем резали (времена попыток)
        self.cands = {}        # r → куски фразы (все, в т. ч. не сохраняемые)
        self.phr = {}          # r → целая основная фраза
        self.keep = {}         # (столбец, текст) → кусок, который сохранён основным
        self.written = {}      # r → файлы этого разбора от фразы r
        self.n_fa = 0
        self.fa_cache = {}     # (окно, текст) → время слов от повторного прохода модели
        self.fa_later = set()  # фразы, нарезанные по ходу без уточнения границ — уточнить в конце
        self.live = False
        self.workers = 1
        self.rec, self.attempts, self.choice = [], [], {}
        os.makedirs(out_dir, exist_ok=True)

    # ---- одна попытка → куски
    def _cut_attempt(self, r, k, role, plan_only=False):
        """Попытка → куски. plan_only — только узнать, нужен ли повторный проход модели (окно и текст),
        чтобы process() сделал такие проходы параллельно (это самое долгое в нарезке)."""
        rec, db, thr, dur = self.rec, self.db, self.thr, self.dur
        a, p = self.attempts[k], self.phrases[r]
        i0, i1 = a["i0"], a["i1"]
        lo = max(rec[i0 - 1][2] if i0 > 0 else 0.0, rec[i0][1] - 0.5, 0.0)
        hi = min(dur, rec[i1][2] + 1.2)
        if i1 + 1 < len(rec):
            hi = min(hi, max(rec[i1][2] + 0.6, rec[i1 + 1][1] + 0.2))
        hi = rs_voice_end(db, thr, hi, min(dur, hi + 1.0), pad=0.05)   # не обрываем окно посреди слова
        j0, j1 = a["j0"], a["j1"]
        guessed = set()
        L = len(p["words"])
        if role == 'main' and j1 < L - 1:
            # распознавание потеряло конец фразы, а звук до следующей попытки есть — дотягиваем
            nxt = rec[i1 + 1][1] if i1 + 1 < len(rec) else dur
            ia, ib = int(rec[i1][2] / RS_FRAME), int(nxt / RS_FRAME)
            voiced = float((db[ia:ib] >= thr).sum()) * RS_FRAME if ib > ia else 0.0
            if voiced >= 0.25 * (L - 1 - j1):
                guessed |= set(range(j1 + 1, L))
                j1 = L - 1
                hi = rs_voice_end(db, thr, min(dur, max(hi, nxt + 0.2)), min(dur, nxt + 1.0), pad=0.05)
        words = p["words"][j0:j1 + 1]
        got = {j: (rec[i][1], rec[i][2]) for i, j in a["good"] if rs_sim(rec[i][0], p["words"][j]) >= 0.8}
        anyt = {j: (rec[i][1], rec[i][2]) for i, j in a["pairs"]}
        num0 = next((j for j, k in enumerate(p["cell_of"]) if p["cells"][k].get("num")), 0)   # начало чисел
        ins_inside = [i for i in a.get("ins", []) if i0 < i < i1 and i > min((ii for ii, j in a["pairs"] if j >= num0), default=i1)]
        # второй проход модели (30 с её работы на фразу) — только где он правит границы: в числах слово
        # услышано не тем / запинка / слова нет / время схлопнулось. Расхождение в начальной фразе («сумма» вместо
        # «суммой», «к платье») — не повод: у слова есть время, а сама фраза не сохраняется.
        clean = (not guessed and not ins_inside
                 and all((j in got) if j >= num0 else (j in anyt) for j in range(j0, j1 + 1))
                 and all(anyt[j][1] - anyt[j][0] >= 0.08 for j in range(j0, j1 + 1)))
        gpi = [rec[i][1] for i, _ in a["pairs"]]
        restart = any(b_ - a_ > 3.0 for a_, b_ in zip(gpi, gpi[1:]))   # долгий провал внутри — пропущенный повтор
        times, weak = None, False
        need_fa = role == 'main' and not clean and not restart and self.model is not None and hi - lo <= RS_ALIGN_MAX
        if need_fa and self.live:                       # по ходу распознавания модель не отвлекаем — уточним в конце
            self.fa_later.add(r)
            need_fa = False
        fa_key = (round(lo, 3), round(hi, 3), tuple(words))
        if plan_only:
            return fa_key if need_fa else None
        if need_fa:
            if fa_key in self.fa_cache:
                times = self.fa_cache[fa_key]
            else:
                try:
                    times = rs_force_align(self.model, self.a16, lo, hi, words)
                    self.n_fa += 1
                except Exception:
                    times = None
        if not times:                                   # время распознанных слов
            weak = role == 'main' and not clean
            gp = {j: (rec[i][1], rec[i][2]) for i, j in a["pairs"]}
            times, last = [], lo
            for j in range(j0, j1 + 1):
                s_, e_ = gp.get(j, (last, last))
                times.append((s_, e_, 0.0))
                last = e_
        gg = {j: (rec[i][1], rec[i][2]) for i, j in a["good"]}
        times = [(gg[j0 + d][0], gg[j0 + d][1], 0.0) if e - s_ < 0.1 and (j0 + d) in gg else (s_, e, pr)
                 for d, (s_, e, pr) in enumerate(times)]   # слово сжалось в ноль — время из распознавания
        bounds = rs_cells_bounds(p, [(s_, e) for s_, e, _ in times], j0, db, thr, lo, hi)
        guessed_cells = {p["cell_of"][j] for j in guessed}
        heard = rs_cell_heard(rec, p, a)
        if role == 'main':
            fs, fe = bounds[0][1], bounds[-1][2]
            fname = rs_safe_name(f'стр {p["row"]} (блок {p["block"] + 1})') + '.wav'
            self.phr[r] = {"r": r, "row": p["row"], "block": p["block"], "start": round(fs, 3), "end": round(fe, 3),
                           "file": os.path.join('_фразы', fname), "complete": a["complete"],
                           "spares": len(self.choice[r]["spare"])}
        out = []
        for kc, s_, e in bounds:
            c = p["cells"][kc]
            h_text, h_sim = heard.get(kc, ('', 0.0))
            pc = {"r": r, "kc": kc, "row": p["row"], "block": p["block"], "col": c["col"], "tier": c["tier"],
                  "text": c["text"], "num": c.get("num", True), "file": None, "cat": c.get("cat"),
                  "start": round(s_, 3), "end": round(e, 3),
                  "role": role, "heard": h_text, "sim": round(h_sim, 2), "weak": weak,
                  "complete": a["complete"] or bool(guessed), "guess": kc in guessed_cells}
            self._judge(pc)
            out.append(pc)
        return out

    def _judge(self, pc):
        ia, ib = int(pc["start"] / RS_FRAME), int(pc["end"] / RS_FRAME)
        voiced = float((self.db[ia:ib] >= self.thr).sum()) * RS_FRAME
        vow = sum(pc["text"].count(v) for v in 'аеёиоуыэюя')
        long_ = voiced > 0.6 + 0.32 * max(1, vow)      # голоса больше, чем нужно на эти слова — внутри лишнее
        got_w = [w for w, s_, e in self.rec if pc["start"] <= (s_ + e) / 2 < pc["end"]]
        pc["check"] = ' '.join(got_w)
        pc["check_sim"] = round(rs_text_sim(got_w, pc["text"].split()), 2)
        why = []
        if pc["sim"] < 0.8 and not pc["guess"]:
            why.append(f'распознано «{pc["heard"] or "—"}»')
        if pc["check_sim"] < RS_OK_SIM:
            why.append(f'в границах куска: «{pc["check"] or "—"}»')
        if pc["guess"]:
            why.append('не распознано — граница по звуку, проверить')
        if long_:
            why.append('кусок длиннее обычного — внутри, похоже, повтор или лишнее')
        if pc["weak"]:
            why.append('границы приблизительные')
        if not pc["complete"] and pc["role"] == 'main':
            why.append('фраза дочитана не полностью')
        pc["why"] = '; '.join(why)
        pc["ok"] = not why

    # ---- файлы
    def _write(self, rel, s_, e):
        from utils.wav_io import slice_or_export
        os.makedirs(os.path.dirname(os.path.join(self.out, rel)), exist_ok=True)
        slice_or_export(self.wav, os.path.join(self.out, rel), s_ * 1000, e * 1000)

    def _drop_files(self, r):
        """Свои файлы фразы r (резали заново) — убрать; основной кусок, который сохранён от другой фразы, не трогаем."""
        for rel in self.written.pop(r, []):
            if any(pc["file"] == rel and pc["r"] != r for pc in self.keep.values()):
                continue
            try:
                os.remove(os.path.join(self.out, rel))
            except OSError:
                pass
        for key in [k for k, pc in self.keep.items() if pc["r"] == r]:
            del self.keep[key]

    def _save_phrase(self, r):
        """Сохранить куски фразы r: только числа; значение столбца — один раз (первое уверенное прочтение);
        запасные — только у сохранённого значения и только уверенные."""
        files = self.written.setdefault(r, [])
        ph = self.phr.get(r)
        if ph:
            self._write(ph["file"], ph["start"], ph["end"])
            files.append(ph["file"])
        chosen = set()
        for pc in self.cands[r]:
            if pc["role"] != 'main' or not pc["num"]:
                continue
            key = tuple(pc["cat"]) if pc.get("cat") else (pc["col"], pc["text"])
            old = self.keep.get(key)
            if old is None or (pc["ok"] and not old["ok"]):
                if old is not None:                       # лучшее прочтение позже — прежнее и его запасные убираем
                    self._forget(old)
                pc["file"] = rs_piece_rel(pc)
                self._write(pc["file"], pc["start"], pc["end"])
                files.append(pc["file"])
                self.keep[key] = pc
                chosen.add(pc["kc"])
        n_sp = {}
        for pc in self.cands[r]:
            if pc["role"] != 'spare' or pc["kc"] not in chosen or not pc["ok"] or not pc["num"]:
                continue
            n_sp[pc["kc"]] = n_sp.get(pc["kc"], 0) + 1
            d_, n_ = os.path.split(rs_piece_rel(pc))
            pc["file"] = os.path.join('_запасные', d_, f'{os.path.splitext(n_)[0]} — попытка {n_sp[pc["kc"]]}.wav')
            self._write(pc["file"], pc["start"], pc["end"])
            files.append(pc["file"])

    def _forget(self, old):
        r = old["r"]
        for pc in self.cands.get(r, []):
            if pc["kc"] == old["kc"] and pc["file"]:
                if pc["role"] == 'spare':
                    try:
                        os.remove(os.path.join(self.out, pc["file"]))
                    except OSError:
                        pass
                if pc["file"] in self.written.get(r, []):
                    self.written[r].remove(pc["file"])
                pc["file"] = None

    # ---- проход
    def process(self, rec_words, upto=None, final=False):
        """Выровнять всё распознанное и нарезать «готовые» фразы. upto — докуда дошло распознавание."""
        self.rec = rs_rec_words(rec_words)
        self.attempts = rs_align(self.rec, self.phrases)
        self.choice = rs_choose(self.attempts, self.phrases)
        rec = self.rec
        ends = {r: max(rec[self.attempts[k]["i1"]][2] for k in [ch["main"]] + ch["spare"]) for r, ch in self.choice.items()}
        todo = []
        for r, ch in sorted(self.choice.items()):
            if not final and not (upto is not None and ends[r] < upto - RS_SETTLE
                                  and any(e > ends[r] for rr, e in ends.items() if rr != r)):
                continue
            ks = [ch["main"]] + ch["spare"]
            sig = tuple((round(rec[self.attempts[k]["i0"]][1], 2), round(rec[self.attempts[k]["i1"]][2], 2)) for k in ks)
            if self.sig.get(r) != sig or (final and r in self.fa_later):
                todo.append((r, sig))
        self.live = not final
        if final:
            self.fa_later.clear()
            self._prefetch_fa(todo)
        for n, (r, sig) in enumerate(todo):
            if self.stop():
                return False
            p = self.phrases[r]
            self.log({"cut": {"n": n + 1, "of": len(todo), "row": p["row"], "block": p["block"] + 1,
                              "text": ' '.join(c["text"] for c in p["cells"])}})
            ch = self.choice[r]
            if r in self.sig:
                self._drop_files(r)
            cands = self._cut_attempt(r, ch["main"], 'main')
            for k in ch["spare"]:
                cands += self._cut_attempt(r, k, 'spare')
            self.cands[r] = cands
            self._save_phrase(r)
            self.sig[r] = sig
        if final:                                         # фразы, которые при последнем выравнивании пропали
            for r in [r for r in list(self.sig) if r not in self.choice]:
                self._drop_files(r)
                self.sig.pop(r, None)
                self.cands.pop(r, None)
                self.phr.pop(r, None)
        self.log({"live": self.stats()})
        return True

    def _prefetch_fa(self, todo):
        """Повторные проходы модели для всех фраз пачки — параллельно (self.workers), результат — в fa_cache."""
        if self.model is None:
            return
        reqs = []
        for r, _sig in todo:
            ch = self.choice[r]
            key = self._cut_attempt(r, ch["main"], 'main', plan_only=True)
            if key and key not in self.fa_cache and key not in reqs:
                reqs.append(key)
        if not reqs:
            return
        from concurrent.futures import ThreadPoolExecutor

        def one(key):
            if self.stop():
                return key, None
            try:
                return key, rs_force_align(self.model, self.a16, key[0], key[1], list(key[2]))
            except Exception:
                return key, None
        done = 0
        with ThreadPoolExecutor(max_workers=max(1, self.workers)) as ex:
            for key, times in ex.map(one, reqs):
                done += 1
                self.n_fa += 1
                self.fa_cache[key] = times
                self.log({"fa": {"n": done, "of": len(reqs)}})

    def stats(self):
        main = [pc for pc in self.keep.values()]
        return {"found": len(self.choice), "phrases": len(self.phrases), "done": len(self.sig),
                "pieces": len(main), "bad": sum(1 for pc in main if not pc["ok"]),
                "spares": sum(1 for r in self.cands for pc in self.cands[r] if pc["role"] == 'spare' and pc["file"])}

    def finish(self, rec_words):
        pieces = [pc for r in sorted(self.cands) for pc in self.cands[r] if pc["file"]]
        missing = [{"row": p["row"], "block": p["block"], "text": ' | '.join(c["text"] for c in p["cells"])}
                   for p in self.phrases if p["id"] not in self.choice]
        main_num = [pc for r in self.cands for pc in self.cands[r] if pc["role"] == 'main' and pc["num"]]
        res = {"pieces": pieces, "phrases": [self.phr[r] for r in sorted(self.phr)], "missing": missing,
               "rec": rec_words, "attempts": len(self.attempts), "dur": round(self.dur, 1), "aligned": self.n_fa,
               "skipped_repeats": sum(1 for pc in main_num if not pc["file"])}
        rs_write_reports(self.out, res)
        return res


def rs_run(model, wav_path, table, out_dir, log=None, stop=None, rec_words=None, workers=1, part=None):
    """Разбор записи: распознать → выровнять → нарезать. Куски пишутся в out_dir по ходу распознавания.
    log(dict) — ход работы: {"stage", "pct"} и подробности {"asr": …}, {"cut": …}, {"live": …}.
    rec_words — готовое распознавание (повторный разбор без распознавания).
    Возвращает итог {"pieces": [...], "phrases": [...], "missing": [...], "rec": [...]} или None (остановлено)."""
    log = log or (lambda d: None)
    stop = stop or (lambda: False)
    x, sr = rs_load_audio(wav_path)
    a16 = rs_to16k(x, sr)
    db, thr = rs_envelope(a16, 16000)
    cut = RsCutter(model, wav_path, table, out_dir, a16, db, thr, log, stop)
    cut.workers = max(1, int(workers))
    if rec_words is None:
        log({"stage": "asr", "pct": 0})
        last = {"pos": 0.0}

        def on_pack(info):
            log({"stage": "asr", "pct": round(info["pos"] * 100 / max(info["dur"], 1e-6)),
                 "asr": {k: info[k] for k in ("pack", "packs", "pos", "dur", "text")},
                 **({"resumed": info["resumed"]} if info.get("resumed") else {})})
            if info["words"] is None:
                return
            if info["pos"] - last["pos"] >= RS_LIVE_STEP and info["pos"] < info["dur"]:
                last["pos"] = info["pos"]
                cut.process(info["words"], upto=info["pos"])
        rec_words = rs_transcribe(model, a16, None, stop, db, thr, on_pack, workers, part)
    if stop():
        return None
    log({"stage": "cut", "pct": 0})
    if not cut.process(rec_words, final=True):
        return None
    res = cut.finish(rec_words)
    log({"stage": "done", "pct": 100})
    return res


def rs_write_reports(out_dir, res):
    """разбор.xlsx (всё), <ярус>/_проверка.xlsx (A — текст, B — файл: «Прослушка фраз»), разбор.json."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    red = PatternFill('solid', fgColor='F8D7DA')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Куски'
    ws.append(['Блок', 'Строка', 'Ярус', 'Текст', 'Файл', 'Начало, с', 'Конец, с', 'Основной', 'Распознано',
               'В границах куска', 'Статус'])
    for c in ws[1]:
        c.font = Font(bold=True)
    for pc in res["pieces"]:
        ws.append([pc["block"] + 1, pc["row"], pc["tier"], pc["text"], pc["file"], pc["start"], pc["end"],
                   'да' if pc["role"] == 'main' else 'запасной', pc["heard"], pc["check"] or '',
                   'ок' if pc["ok"] else pc["why"]])
        if not pc["ok"]:
            for c in ws[ws.max_row]:
                c.fill = red
    if res["missing"]:
        ws2 = wb.create_sheet('Не найдено')
        ws2.append(['Блок', 'Строка', 'Фраза'])
        for m in res["missing"]:
            ws2.append([m["block"] + 1, m["row"], m["text"]])
    wb.save(os.path.join(out_dir, 'разбор.xlsx'))
    by_tier = {}
    for pc in res["pieces"]:
        if pc["role"] == 'main':
            by_tier.setdefault(os.path.dirname(pc["file"]), []).append(pc)
    for d, lst in by_tier.items():                    # в папке яруса: «Прослушка фраз» — эта папка и эта таблица
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Проверка'
        for pc in lst:
            name = os.path.splitext(os.path.basename(pc["file"]))[0]
            ws.append([('⚠ ' if not pc["ok"] else '') + pc["text"] + (f' — {pc["why"]}' if pc["why"] else ''), name])
        wb.save(os.path.join(out_dir, d, '_проверка.xlsx'))
    keep = {k: v for k, v in res.items() if k != 'rec'}
    with open(os.path.join(out_dir, 'разбор.json'), 'w', encoding='utf-8') as f:
        json.dump(keep, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, '.распознавание.json'), 'w', encoding='utf-8') as f:
        json.dump(res["rec"], f, ensure_ascii=False)


# ---------------------------------------------------------------- отдельный процесс разбора
def rs_apply_log(state, d, now=None):
    """Ход работы (log из rs_run) → state {"stage", "pct", "stage_t", "info"} — общее для процесса и окна."""
    now = now or time.time()
    info = state.setdefault("info", {})
    if "stage" in d:
        if d["stage"] != state.get("stage"):
            state["stage_t"] = now
            if d["stage"] == 'asr':
                info["asr_t0"] = now
            if d["stage"] == 'cut':
                info["asr_s"] = round(now - info.get("asr_t0", now))
        state["stage"], state["pct"] = d["stage"], d.get("pct", 0)
    for k in ("asr", "cut", "live", "fa", "resumed"):
        if k in d:
            info[k] = d[k]
    if "cut" in d and state.get("stage") == 'cut':
        state["pct"] = round(d["cut"]["n"] * 100 / max(1, d["cut"]["of"]))


def _rs_load_model(path, threads):
    from faster_whisper import WhisperModel
    from core.auto_check import fix_feature_size
    m = WhisperModel(path, device='cpu', compute_type='int8', cpu_threads=int(threads), num_workers=1)
    fix_feature_size(m)
    return m


def rs_worker_main(job_path):
    """Разбор в отдельном процессе (GVox.exe --rsum-worker <job.json>): окно не ждёт, у процесса пониженный приоритет —
    Студия и прослушка не заикаются. Ход — в файл state (окно его читает), стоп — файл stop (дописывается пачка).
    Распознавание пишется по пачкам (part): после остановки / закрытия программы продолжается с того же места."""
    import traceback
    with open(job_path, 'r', encoding='utf-8') as f:
        job = json.load(f)
    state = {"stage": 'model', "pct": 0, "stage_t": time.time(), "info": {}, "done": False, "error": None,
             "pid": os.getpid()}
    last = [0.0]

    def write(force=False):
        if not force and time.time() - last[0] < 0.4:
            return
        last[0] = time.time()
        try:
            with open(job["state"] + '.tmp', 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False)
            os.replace(job["state"] + '.tmp', job["state"])
        except OSError:
            pass
    stop = lambda: os.path.exists(job["stop"])
    write(True)
    try:
        t0 = time.time()
        model = _rs_load_model(job["model"], job["threads"])
        state["info"]["model_s"] = round(time.time() - t0, 1)
        table = rs_read_table(job["table"])
        rec = None
        if job.get("reuse") and job.get("cache") and os.path.exists(job["cache"]):
            with open(job["cache"], 'r', encoding='utf-8') as f:
                rec = [tuple(w) for w in json.load(f)]
        state["info"]["cached"] = rec is not None
        part = job.get("part")
        if part and not job.get("reuse") and os.path.exists(part):
            os.remove(part)                                    # «заново» — прежние пачки не берём

        def log(d):
            rs_apply_log(state, d)
            write()
        res = rs_run(model, job["wav"], table, job["out"], log, stop, rec, 1, part)
        if res is None:
            state["stopped"] = True
        else:
            if rec is None and job.get("cache"):
                os.makedirs(os.path.dirname(job["cache"]), exist_ok=True)
                with open(job["cache"] + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(res["rec"], f, ensure_ascii=False)
                os.replace(job["cache"] + '.tmp', job["cache"])
                if part and os.path.exists(part):
                    os.remove(part)
            state["done"] = True
    except Exception as e:
        state["error"] = f'{e}'
        state["trace"] = traceback.format_exc()[-3000:]
    write(True)
    return 0


def rs_find_sum_dirs(folder, depth=3):
    """Папки классов сумм в выбранной папке (и до depth уровней ниже): как после разбора («1 - 100 млн», «1 - 99 тыс»…)
    или как в проекте Студии («Значения/sum_ru/million_ru»…). Казахские (_kz) не берём. {класс: папка}."""
    names = {v.lower(): k for k, v in RS_CAT_DIRS.items()}
    names.update({f'{k}_ru': k for k in RS_CAT_DIRS})
    names.update({k: k for k in RS_CAT_DIRS})
    found = {}

    def walk(d, lvl):
        try:
            subs = sorted(e for e in os.listdir(d) if os.path.isdir(os.path.join(d, e)))
        except OSError:
            return
        for e in subs:
            if e.startswith('_') or e.startswith('.'):
                continue                                      # _запасные, _до_правок, служебные
            cat = names.get(e.lower())
            if cat and cat not in found:
                found[cat] = os.path.join(d, e)
            elif lvl < depth:
                walk(os.path.join(d, e), lvl + 1)
    walk(folder, 1)
    return found


def rs_sum_files(dirs):
    """{класс: {число: путь}} — файлы «<число>.wav» в папках классов."""
    out = {}
    for cat, d in dirs.items():
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for f in names:
            m = re.fullmatch(r'(\d+)\.wav', f, re.I)
            if m:
                out.setdefault(cat, {})[int(m.group(1))] = os.path.join(d, f)
    return out


# ---------------------------------------------------------------- окно GVox
RS_CACHE_DIR = os.path.join(os.path.expanduser('~'), '.gvox', 'rsum_cache')


def rs_out_dir(wav_path):
    """Папка кусков рядом с записью; занята — «_2», «_3»… (ничего не перезаписываем)."""
    base = os.path.splitext(wav_path)[0] + '_куски'
    out, n = base, 1
    while os.path.exists(out) and os.listdir(out):
        n += 1
        out = f'{base}_{n}'
    return out


def rs_prev_out(wav_path):
    """Готовая папка кусков этой записи (после прежнего разбора; её могли уже рассортировать руками):
    «<запись>_куски», «_куски_2»… — самая свежая, где есть куски по классам сумм. Нет — None."""
    if not wav_path:
        return None
    base = os.path.splitext(wav_path)[0] + '_куски'
    best = None
    for n in range(1, 100):
        d = base if n == 1 else f'{base}_{n}'
        if not os.path.isdir(d):
            if n > 1:
                break
            continue
        if any(rs_sum_files(rs_find_sum_dirs(d)).values()):
            t = os.path.getmtime(d)
            if best is None or t >= best[0]:
                best = (t, d)
    return best[1] if best else None


def _rs_cache_file(wav_path):
    try:
        st = os.stat(wav_path)
        key = f'{os.path.abspath(wav_path)}|{st.st_size}|{int(st.st_mtime)}'
    except OSError:
        return None
    return os.path.join(RS_CACHE_DIR, hashlib.md5(key.encode('utf-8')).hexdigest() + '.json')


class RawSumsMixin:
    """pywebview API окна «Разбор записи сумм» (rsum_*)."""

    def _rsum(self):
        st = getattr(self, '_rsum_st', None)
        if st is None:
            st = self._rsum_st = {"audio": None, "table": None, "tdata": None, "run": False, "stage": None,
                                  "pct": 0, "msg": '', "out": None, "result": None, "stop": False,
                                  "need_model": False, "started": None, "stage_t": None, "ended": None, "info": {}}
        return st

    def rsum_state(self):
        st = self._rsum()
        t = st["tdata"]
        table = None
        if t:
            table = {"path": st["table"], "sheet": t.get("sheet"), "phrases": len(t["phrases"]),
                     "blocks": len({p["block"] for p in t["phrases"]}),
                     "tiers": sorted(set(c["tier"] for p in t["phrases"] for c in p["cells"])),
                     "skipped": t["skipped"][:20],
                     "preview": [{"row": p["row"], "block": p["block"] + 1, "cells": [c["text"] for c in p["cells"]]}
                                 for p in t["phrases"][:3]]}
        res = st["result"]
        summary = None
        if res:
            main = [p for p in res["pieces"] if p["role"] == 'main']
            bad = [p for p in main if not p["ok"]]
            summary = {"pieces": len(main), "spares": len(res["pieces"]) - len(main), "bad": len(bad),
                       "repeats": res.get("skipped_repeats", 0),
                       "cats": {c: len(v) for c, v in self._rsum_cat_files().items()},
                       "phrases": len(res["phrases"]), "missing": res["missing"][:200],
                       "missing_n": len(res["missing"]), "dur": res.get("dur"),
                       "bad_list": [{"file": p["file"], "text": p["text"], "row": p["row"], "block": p["block"] + 1,
                                     "tier": p["tier"], "why": p["why"]} for p in bad]}
        now = time.time()
        elapsed = round((st.get("ended") or now) - st["started"]) if st.get("started") else None
        info = dict(st.get("info") or {})
        eta = None
        asr = info.get("asr")
        if st["run"] and st["stage"] == 'asr' and asr and info.get("asr_t0") and asr["pos"] > 20:
            spent = now - info["asr_t0"]
            speed = asr["pos"] / max(spent, 1e-6)               # секунд записи за секунду работы
            info["speed"] = round(speed, 2)
            eta = round((asr["dur"] - asr["pos"]) / speed + 0.08 * asr["dur"] / max(speed, 0.2))   # + нарезка остатка
        elif st["run"] and st["stage"] == 'cut' and info.get("cut") and st.get("stage_t"):
            c = info["cut"]
            spent = now - st["stage_t"]
            if c["n"] >= 3:
                eta = round(spent * (c["of"] - c["n"]) / c["n"])
        info.pop("asr_t0", None)
        return {"audio": st["audio"], "table": table, "run": st["run"], "stage": st["stage"], "pct": st["pct"],
                "msg": st["msg"], "out": st["out"], "summary": summary, "need_model": st.get("need_model", False),
                "elapsed": elapsed, "eta": eta, "stopping": bool(st["run"] and st["stop"]), "info": info,
                "cats": {c: len(v) for c, v in self._rsum_cat_files().items()} if st["out"] else {},
                "cached": bool(st["audio"] and _rs_cache_file(st["audio"]) and os.path.exists(_rs_cache_file(st["audio"]))),
                "partial": bool(st["audio"] and _rs_cache_file(st["audio"]) and os.path.exists(_rs_cache_file(st["audio"]) + '.part')),
                "studio_ok": self._rsum_studio_sheet() is not None,
                "ready": sum(len(v) for v in self._rsum_cat_files().values()) if st["out"] and not st["run"] else 0}

    def rsum_pick_audio(self):
        import webview
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Звук (*.wav;*.mp3;*.flac;*.ogg;*.m4a)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        st = self._rsum()
        st["audio"] = picked if isinstance(picked, str) else picked[0]
        st["result"], st["out"], st["msg"] = None, rs_prev_out(st["audio"]), ''
        return self.rsum_state()

    def rsum_pick_out(self):
        """Указать готовую папку кусков вручную (её перенесли / переименовали): папки классов
        «1 - 100 млн»… или «million_ru»… — внутри, до 3 уровней."""
        import webview
        st = self._rsum()
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER,
                                                       directory=os.path.dirname(st["audio"] or st["table"] or '') or '')
        if not picked:
            return {"error": "cancel"}
        folder = picked if isinstance(picked, str) else picked[0]
        if not any(rs_sum_files(rs_find_sum_dirs(folder)).values()):
            return {"error": "В этой папке нет кусков сумм: нужны папки «1 - 100 млн», «100 - 900», «1 - 99 тыс», "
                             "«100 - 900 тыс», «1 - 100 тенге» с файлами-числами (как после разбора)."}
        if st["run"]:
            return {"error": "Идёт разбор."}
        st["out"], st["result"] = folder, None
        return self.rsum_state()

    def rsum_pick_table(self):
        import webview
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel (*.xlsx)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        return self.rsum_load_table(picked if isinstance(picked, str) else picked[0])

    def rsum_load_table(self, path):
        st = self._rsum()
        try:
            t = rs_read_table(path)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу: {e}"}
        if not t["phrases"]:
            return {"error": "В таблице не нашлось фраз: нужна строка заголовков и строки, где в блоке столбцов "
                             "заполнено хотя бы две ячейки."}
        st["table"], st["tdata"] = path, t
        st["result"], st["out"], st["msg"] = None, rs_prev_out(st["audio"]) if st["audio"] else None, ''
        return self.rsum_state()

    def rsum_start(self, reuse_asr=True, mode='bg', to_studio=False):
        """mode: 'bg' — фон (ядер на 2 меньше, приоритет ниже: Студия и прослушка не заикаются), 'max' — все ядра.
        to_studio — готовые куски по ходу копировать в открытый проект Студии."""
        st = self._rsum()
        st["mode"] = 'max' if mode == 'max' else 'bg'
        st["to_studio"] = bool(to_studio)
        st["par"] = 1
        if st["run"]:
            return {"error": "Разбор уже идёт."}
        if not st["audio"] or not os.path.exists(st["audio"]):
            return {"error": "Выберите запись."}
        if not st["tdata"]:
            return {"error": "Выберите таблицу."}
        # модель грузится в потоке (первый раз — десятки секунд): окно сразу видит «Загрузка модели»
        st.update(run=True, stop=False, stage='model', pct=0, msg='', result=None, need_model=False,
                  out=rs_out_dir(st["audio"]), started=time.time(), stage_t=time.time(), ended=None, info={})
        threading.Thread(target=self._rsum_boot, args=(bool(reuse_asr),), daemon=True).start()
        return self.rsum_state()

    @staticmethod
    def _rsum_split(par=1):
        """Ядра → (пачек сразу, потоков на пачку). По умолчанию одна пачка на все физические ядра: на Windows с
        процессором без быстрых int8-инструкций три пачки сразу оказались в разы медленнее (×0,14 против ×0,4).
        par 2–3 — параллельно (в песочнице было на 10–60 % быстрее); выбирается в окне."""
        cores = os.cpu_count() or 2
        phys = cores // 2 if cores >= 8 else cores
        workers = max(1, min(int(par or 1), phys))
        return workers, max(1, phys // workers)

    def _rsum_model(self, par=1):
        """Своя копия large-v3-turbo с несколькими потоками (модель KZ в Студии — однопоточная, её не трогаем).
        Модели в папке нет — как раньше: общий слот KZ (скачать / указать папку)."""
        path = self._auto_check_model_path('kz')
        if not path:
            m, err = self._auto_check_model('kz')
            if m is not None:
                self._rsum_workers = 1
            return m, err
        workers, threads = self._rsum_split(par)
        key = (path, workers, threads)
        if getattr(self, '_rsum_model_key', None) == key and getattr(self, '_rsum_model_obj', None) is not None:
            return self._rsum_model_obj, None
        from faster_whisper import WhisperModel
        from core.auto_check import fix_feature_size
        try:
            m = WhisperModel(path, device='cpu', compute_type='int8', cpu_threads=threads, num_workers=workers)
        except Exception as e:
            return None, f"Не удалось загрузить модель из папки «{path}».\n\n{e}"
        fix_feature_size(m)
        self._rsum_model_obj, self._rsum_model_key, self._rsum_workers = m, key, workers
        return m, None

    @staticmethod
    def _rsum_threads(mode):
        """Потоков модели: физические ядра (гиперпотоки ей не помогают); «фон» — на 2 меньше, для Студии."""
        cores = os.cpu_count() or 2
        phys = cores // 2 if cores >= 8 else cores
        return phys if mode == 'max' else max(2, phys - 2)

    def _rsum_boot(self, reuse_asr):
        st = self._rsum()
        path = self._auto_check_model_path('kz')
        if path:                                       # модель на диске — разбор отдельным фоновым процессом
            try:
                self._rsum_bg(path, reuse_asr)
            except Exception as e:
                st["msg"] = f'Ошибка: {e}'
            finally:
                st["run"] = False
                st["ended"] = time.time()
            return
        try:
            model, err = self._rsum_model(st.get("par", 1))   # large-v3-turbo: на 8 кГц small путает числа
        except Exception as e:
            model, err = None, str(e)
        if err is not None:
            from core.auto_check import NEED_MODEL
            st["need_model"] = err is NEED_MODEL
            st["msg"] = '' if err is NEED_MODEL else str(err)
            st["run"] = False
            return
        if st["stop"]:
            st["msg"], st["run"] = 'Остановлено.', False
            return
        self._rsum_worker(model, reuse_asr)

    def _rsum_worker(self, model, reuse_asr):
        st = self._rsum()
        cache = _rs_cache_file(st["audio"])
        rec = None
        if reuse_asr and cache and os.path.exists(cache):
            try:
                with open(cache, 'r', encoding='utf-8') as f:
                    rec = [tuple(w) for w in json.load(f)]
            except Exception:
                rec = None
        info = st["info"]
        info["model_s"] = round(time.time() - st["started"], 1)
        info["cached"] = rec is not None

        def log(d):
            if "stage" in d:
                if d["stage"] != st["stage"]:
                    st["stage_t"] = time.time()
                    if d["stage"] == 'asr':
                        info["asr_t0"] = time.time()
                    if d["stage"] == 'cut':
                        info["asr_s"] = round(time.time() - info.get("asr_t0", time.time()))
                st["stage"], st["pct"] = d["stage"], d.get("pct", 0)
            for k in ("asr", "cut", "live", "fa"):
                if k in d:
                    info[k] = d[k]
            if "cut" in d and st["stage"] == 'cut':
                st["pct"] = round(d["cut"]["n"] * 100 / max(1, d["cut"]["of"]))

        try:
            info["workers"] = getattr(self, '_rsum_workers', 1)
            res = rs_run(model, st["audio"], st["tdata"], st["out"], log=log, stop=lambda: st["stop"], rec_words=rec,
                         workers=info["workers"])
            if res is None:
                st["msg"] = 'Остановлено. Готовые куски остались в папке.'
                return
            if rec is None and cache:
                os.makedirs(RS_CACHE_DIR, exist_ok=True)
                with open(cache + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(res["rec"], f, ensure_ascii=False)
                os.replace(cache + '.tmp', cache)
            st["result"] = res
        except Exception as e:
            st["msg"] = f'Ошибка: {e}'
        finally:
            st["run"] = False
            st["ended"] = time.time()

    def _rsum_cmd(self, job):
        import sys
        if getattr(sys, 'frozen', False):
            return [sys.executable, '--rsum-worker', job]
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # из исходников — только модуль разбора (весь main.py с окном и Audacity процессу не нужен)
        return [sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from core.raw_sums import rs_worker_main; '
                'sys.exit(rs_worker_main(sys.argv[2]))', root, job]

    def _rsum_bg(self, model_path, reuse_asr):
        """Разбор отдельным процессом (rs_worker_main): окно читает его ход из файла, стоп — файлом."""
        import subprocess
        import tempfile
        import uuid
        st = self._rsum()
        jd = os.path.join(tempfile.gettempdir(), 'gvox_rsum_jobs', uuid.uuid4().hex[:12])
        os.makedirs(jd, exist_ok=True)
        cache = _rs_cache_file(st["audio"])
        threads = self._rsum_threads(st.get("mode"))
        job = {"wav": st["audio"], "table": st["table"], "out": st["out"], "model": model_path, "threads": threads,
               "cache": cache, "part": (cache + '.part') if cache else None, "reuse": bool(reuse_asr),
               "state": os.path.join(jd, 'state.json'), "stop": os.path.join(jd, 'stop')}
        with open(os.path.join(jd, 'job.json'), 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
        if cache:
            os.makedirs(os.path.dirname(cache), exist_ok=True)
        flags = 0
        if os.name == 'nt':
            flags = 0x08000000 | (0x00004000 if st.get("mode") != 'max' else 0)   # без окна; фон — BELOW_NORMAL
        logf = open(os.path.join(jd, 'worker.log'), 'w', encoding='utf-8')
        proc = subprocess.Popen(self._rsum_cmd(os.path.join(jd, 'job.json')), stdout=logf, stderr=logf,
                                stdin=subprocess.DEVNULL, creationflags=flags)
        st["proc"] = proc
        st["info"].update(threads=threads, bg=st.get("mode") != 'max', workers=1)
        stop_t, last_studio, state = None, 0.0, {}
        try:
            while True:
                alive = proc.poll() is None
                try:
                    with open(job["state"], 'r', encoding='utf-8') as f:
                        state = json.load(f)
                except (OSError, ValueError):
                    pass
                if state:
                    st["stage"], st["pct"] = state.get("stage") or st["stage"], state.get("pct", st["pct"])
                    st["stage_t"] = state.get("stage_t") or st["stage_t"]
                    keep = {k: st["info"][k] for k in ("threads", "bg", "workers", "studio") if k in st["info"]}
                    st["info"] = {**state.get("info", {}), **keep}
                if st["stop"] and stop_t is None:
                    open(job["stop"], 'w').close()                 # дописать текущую пачку и выйти
                    stop_t = time.time()
                if stop_t and alive and time.time() - stop_t > 60:
                    proc.terminate()
                if st.get("to_studio") and time.time() - last_studio > 5:
                    last_studio = time.time()
                    self._rsum_studio_tick()
                if not alive:
                    break
                time.sleep(0.5)
        finally:
            logf.close()
            st.pop("proc", None)
        if st.get("to_studio"):
            self._rsum_studio_tick()
        if state.get("done"):
            try:
                with open(os.path.join(st["out"], 'разбор.json'), 'r', encoding='utf-8') as f:
                    st["result"] = json.load(f)
            except (OSError, ValueError) as e:
                st["msg"] = f'Разбор закончен, но отчёт не прочитался: {e}'
        elif state.get("error"):
            st["msg"] = f'Ошибка: {state["error"]}'
        elif state.get("stopped") or st["stop"]:
            st["msg"] = 'Остановлено. Распознанное сохранено — «Разобрать» продолжит с этого места.'
        else:
            try:
                with open(os.path.join(jd, 'worker.log'), 'r', encoding='utf-8', errors='replace') as f:
                    tail = f.read()[-600:]
            except OSError:
                tail = ''
            st["msg"] = 'Процесс разбора закрылся неожиданно. Распознанное сохранено — «Разобрать» продолжит.' + \
                        (f'\n{tail}' if tail else '')

    def _rsum_studio_tick(self):
        """«Сразу в проект Студии»: новые куски — в проект; Студия перечитывает значения."""
        try:
            r = self.rsum_to_studio(auto=True)
        except Exception:
            return
        if r.get("error"):
            self._rsum()["info"]["studio_err"] = r["error"]
            return
        n = r.get("copied", 0) + r.get("updated", 0)
        info = self._rsum()["info"]
        info["studio"] = info.get("studio", 0) + n
        if n:
            self.__dict__.pop('_tts_claims_cache', None)
            try:
                import webview
                webview.windows[0].evaluate_js(f"rsumStudioFill({int(n)})")
            except Exception:
                pass

    def rsum_stop(self):
        self._rsum()["stop"] = True
        return {"ok": True}

    def rsum_play(self, rel):
        st = self._rsum()
        p = os.path.normpath(os.path.join(st["out"] or '', str(rel)))
        if not st["out"] or not p.startswith(os.path.normpath(st["out"])) or not os.path.exists(p):
            return {"playing": False}
        self.player.stop()
        self.player.play(p)
        return {"playing": True}

    def rsum_open_folder(self):
        st = self._rsum()
        p = st["out"] if st["out"] and os.path.isdir(st["out"]) else (os.path.dirname(st["audio"]) if st["audio"] else None)
        if not p:
            return {"error": "Папки ещё нет."}
        try:
            if os.name == 'nt':
                os.startfile(p)
            else:
                import subprocess
                subprocess.Popen(['xdg-open', p])
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}

    # ---- куски как суммы: в проект Студии и «Прослушка сумм» ----
    def _rsum_cat_files(self):
        """{класс: {число: путь}} — основные куски разбора по классам сумм."""
        st = self._rsum()
        if not st.get("out") or not os.path.isdir(st["out"]):
            return {}
        return rs_sum_files(rs_find_sum_dirs(st["out"]))

    def _rsum_studio_sheet(self):
        tt = self._tts() if hasattr(self, '_tts') else {}
        if not tt.get("work_dir"):
            return None
        return next((k for k, sh in (tt.get("var_sheets") or {}).items() if self._tts_is_sum_sheet(sh)
                     and not any(re.search(r'_(kz|kk)$', c["key"]) for c in sh["categories"])), None)

    def rsum_to_studio(self, auto=False):
        """Копии кусков в открытый проект Студии: «Значения/<лист сумм RU>/<класс>/<значение>.wav» —
        имя как значение в таблице проекта. Что в проекте уже есть — не трогаем; исключение — файл, который
        скопировал сам разбор и с тех пор его никто не менял (кусок перерезали — обновляем). Учёт — «.в_проект.json»."""
        import shutil
        files = self._rsum_cat_files()
        if not files:
            return {"error": "Кусков по классам сумм пока нет."}
        tt = self._tts() if hasattr(self, '_tts') else {}
        wd, sheets = tt.get("work_dir"), tt.get("var_sheets") or {}
        sheet = next((k for k, sh in sheets.items() if self._tts_is_sum_sheet(sh)
                      and not any(re.search(r'_(kz|kk)$', c["key"]) for c in sh["categories"])), None)
        if not wd or not sheet:
            return {"error": "Откройте в Студии проект, в таблице которого есть лист сумм RU (<sum_ru> с <million_ru>, <tenge_ru>…)."}
        copied, exist, nowhere, updated = 0, 0, 0, 0
        st = self._rsum()
        man_path = os.path.join(st["out"] or '', '.в_проект.json')
        try:
            with open(man_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            manifest = {}

        def md5(p):
            with open(p, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        for c in sheets[sheet]["categories"]:
            base = re.sub(r'_(ru|kz|kk)$', '', c["key"])
            have = files.get(base) or {}
            idx = {}
            for v in c["values"]:
                dg = re.sub(r'\D', '', str(v))
                if dg:
                    idx.setdefault(int(dg), v)
            for n, src in have.items():
                if n not in idx:
                    nowhere += 1
                    continue
                dst = self._tts_value_file(sheet, c["key"], idx[n])
                src_md5 = md5(src)
                if os.path.exists(dst):
                    mine = manifest.get(dst)
                    if mine and mine != src_md5 and md5(dst) == mine:     # наша копия, кусок перерезали — обновить
                        shutil.copy2(src, dst + '.tmp')
                        os.replace(dst + '.tmp', dst)
                        manifest[dst] = src_md5
                        updated += 1
                    else:
                        exist += 1
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst + '.tmp')
                os.replace(dst + '.tmp', dst)
                manifest[dst] = src_md5
                copied += 1
        used = {re.sub(r'_(ru|kz|kk)$', '', c["key"]) for c in sheets[sheet]["categories"]}
        nowhere += sum(len(v) for k, v in files.items() if k not in used)
        if copied or updated:
            try:
                with open(man_path + '.tmp', 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, ensure_ascii=False)
                os.replace(man_path + '.tmp', man_path)
            except OSError:
                pass
        rail = self.tts_rail_sums(sheet, jump=not auto) if hasattr(self, 'tts_rail_sums') else {}
        return {"ok": True, "sheet": sheet, "copied": copied, "exist": exist, "nowhere": nowhere, "updated": updated,
                "rows": rail.get("rows", 0), "partial": rail.get("partial", 0), "lack": rail.get("lack") or {}, "dir": os.path.join(wd, 'Значения', sheet)}

    def rsum_open_studio(self):
        """«Открыть в Студии»: всё готово одной кнопкой. Открытый проект Студии с этой таблицей или с листом сумм —
        работаем в нём; иначе (другой проект — он сохраняется как есть и закрывается) — проект «<запись>_Студия»
        рядом с записью: таблица разбора, куски — в «Значения/…» (что уже есть — не трогаем). Возвращает tts_state."""
        st = self._rsum()
        if not st.get("table") or not os.path.exists(st["table"]):
            return {"error": "Выберите таблицу."}
        if st["run"] is False and not self._rsum_cat_files():
            return {"need_out": True, "error": "Кусков пока нет: разберите запись или укажите готовую папку кусков."}
        if getattr(self, '_tts_rec', None):
            return {"error": "В Студии идёт запись — сначала остановите её (R)."}
        tt = self._tts()
        same = bool(tt.get("excel_path")) and os.path.normcase(os.path.abspath(tt["excel_path"])) == \
            os.path.normcase(os.path.abspath(st["table"]))
        if not (tt.get("work_dir") and os.path.isdir(tt["work_dir"]) and (same or self._rsum_studio_sheet())):
            base = st.get("audio") or st["table"]
            root = os.path.join(os.path.dirname(base), rs_safe_name(os.path.splitext(os.path.basename(base))[0]) + '_Студия')
            os.makedirs(root, exist_ok=True)
            if tt.get("work_dir") and os.path.normcase(os.path.abspath(tt["work_dir"])) != os.path.normcase(root):
                r = self.tts_reset()                       # прежний проект сохраняется на диске как есть
                if r.get("error"):
                    return r
            self._tts_attach_folder(root)                  # там уже был проект — подтягиваем его
            r = self.tts_load_excel(st["table"])
            if r.get("error"):
                return r
            if r.get("choose_sheet"):
                pend = getattr(self, '_tts_pending', None)
                sheet = next((x["title"] for x in r["choose_sheet"] if x.get("title") == "(только переменные)"),
                             r["choose_sheet"][0]["title"])
                r = self.tts_load_excel(st["table"], sheet)
                if r.get("error"):
                    return r
        copied = None
        if st.get("out") and os.path.isdir(st["out"]) and self._rsum_cat_files():
            copied = self.rsum_to_studio()
        self.__dict__.pop('_tts_claims_cache', None)
        self._tts_save()
        res = self.tts_state()
        res["rsum_open"] = {"dir": self._tts().get("work_dir"),
                            "copied": (copied or {}).get("copied", 0), "exist": (copied or {}).get("exist", 0),
                            "updated": (copied or {}).get("updated", 0), "rows": (copied or {}).get("rows", 0), "sheet": self._rsum_studio_sheet(),
                            "partial": (copied or {}).get("partial", 0), "lack": (copied or {}).get("lack") or {},
                            "takes": len(self._tts()["takes"])}
        return res

    def rsum_listen(self, logic, cat):
        """«Прослушка сумм» из окна разбора — по папке разбора."""
        st = self._rsum()
        dirs = rs_find_sum_dirs(st["out"]) if st.get("out") and os.path.isdir(st["out"]) else {}
        return self._sums_listen(st["out"], dirs, logic, cat)

    # ---- «Прослушка сумм»: готовая папка → значения класса в сумме (логика 1 / 2), правка как обычно ----
    def listen_sums_pick(self):
        """Выбрать готовую папку с кусками сумм (папка разбора или проект Студии / «Значения»)."""
        import webview
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        folder = picked if isinstance(picked, str) else picked[0]
        dirs = rs_find_sum_dirs(folder)
        files = rs_sum_files(dirs)
        if not files:
            return {"error": "В этой папке нет кусков сумм: нужны папки классов с файлами-числами — "
                             "«1 - 100 млн», «100 - 900», «1 - 99 тыс», «100 - 900 тыс», «1 - 100 тенге» (как после разбора) "
                             "или «million_ru», «thousand_ru»… (Значения проекта Студии)."}
        self._lsums = {"folder": folder, "dirs": dirs}
        return {"folder": folder, "cats": {c: len(v) for c, v in files.items()}}

    def listen_sums_open(self, logic=1, cat=None):
        """Открыть класс выбранной папки в «Прослушке». cat=None — первый класс логики, где есть куски."""
        ss = getattr(self, '_lsums', None)
        if not ss:
            return {"error": "Сначала выберите папку с кусками сумм."}
        logic = 2 if int(logic or 1) == 2 else 1
        files = rs_sum_files(ss["dirs"])
        if cat not in RS_LOGICS[logic] or not files.get(cat):
            cat = next((c for c in RS_LOGICS[logic] if files.get(c)), None)
        if not cat:
            return {"error": f"Для логики {logic} в папке нет кусков."}
        return self._sums_listen(ss["folder"], ss["dirs"], logic, cat)

    def _sums_listen(self, folder, dirs, logic, cat):
        """Значения класса cat звучат в сумме логики logic — между кусками остальных классов (для них берётся
        меньшее значение: «один миллион», «сто», «одна тенге»). Открывается обычный экран «Прослушки» (сборка
        переменной): правка, «Сохранить», «_до_правок» — как всегда; склейка начала и конца — во временной папке."""
        import tempfile
        from pydub import AudioSegment
        logic = 2 if int(logic) == 2 else 1
        tiers = RS_LOGICS[logic]
        if cat not in tiers:
            return {"error": "Этого класса нет в выбранной логике."}
        files = rs_sum_files(dirs)
        if not files.get(cat):
            return {"error": f"Кусков «{RS_CAT_DIRS[cat]}» пока нет."}
        k = tiers.index(cat)
        ctx_dir = os.path.join(tempfile.gettempdir(), 'gvox_rsum_ctx',
                               hashlib.md5(f'{folder}|{logic}|{cat}'.encode('utf-8')).hexdigest()[:12])
        os.makedirs(ctx_dir, exist_ok=True)
        for f in os.listdir(ctx_dir):                      # прошлый контекст этого класса — заново
            try:
                os.remove(os.path.join(ctx_dir, f))
            except OSError:
                pass

        def build(part, which):
            segs, label = [], []
            for t in part:
                have = files.get(t) or {}
                if not have:
                    continue
                n = min(have, key=lambda v: (v == 0, v))      # «ноль тенге» — не контекст: берём «одна тенге»
                segs.append(AudioSegment.from_file(have[n]))
                label.append(f'{n} {RS_CAT_SHORT[t]}'.strip())
            if not segs:
                return None
            path = os.path.join(ctx_dir, f'{which} ({", ".join(label)}).wav')
            sum(segs[1:], segs[0]).export(path, format='wav')
            return path
        start, end = build(tiers[:k], 'начало'), build(tiers[k + 1:], 'конец')
        if not start and not end:
            return {"error": "Для суммы не хватает кусков других классов."}
        r = self.listen_setup_assembly(ctx_dir, start, end, dirs[cat])
        if isinstance(r, dict) and not r.get("error"):
            info = {"logic": logic, "cat": cat, "cat_name": RS_CAT_DIRS[cat], "folder": folder,
                    "folder_name": os.path.basename(os.path.normpath(folder)),
                    "cats": {c: len(v) for c, v in files.items()},
                    "start": os.path.splitext(os.path.basename(start))[0] if start else None,
                    "end": os.path.splitext(os.path.basename(end))[0] if end else None}
            self._lsums = {"folder": folder, "dirs": dirs}
            self._ls()["sums"] = info
            r["sums"] = info
            r["rsum"] = {"logic": logic, "cat": RS_CAT_DIRS[cat], "start": info["start"], "end": info["end"]}
        return r
