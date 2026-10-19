"""TTS-процесс: одна запись целых фраз → нарезка → автопроверка по таблице →
прослушка и апрув.

Таблица («ТТС RU.xlsx»):
  • лист фраз — шапка с <phrase>, <name_phrase>, флагами <start>/<start_2>/<end>
    и колонками переменных (<sum_ru>, <date_ru>…), где 1 = переменная здесь;
  • листы переменных с тем же именем, что колонка (<sum_ru>, <date_ru>):
    каждая колонка листа — категория значений (<million_ru>, <day_ru>…).

Строки с флагами — кусочки одной фразы, разрезанной переменными:
start → [сумма] → start_2 → [дата] → end. Каждый кусочек сохраняется
отдельным файлом под своим именем в «Фразы_Переменные», обычная фраза —
в «Проверенные».

Запись не обязана резаться по паузам: фразы часто слипаются. Поэтому
распознанные слова всей записи идут сплошным потоком, и фразы таблицы
ищутся в нём по тексту; оговорки, повторы и значения переменных между
ними пропускаются. Разрез — в тишине между словами. Что сохранять, решает
человек (Enter): автопроверка ошибается, но слушать дубль до конца не обязательно."""

import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import openpyxl
import webview
import numpy as np
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core import recent_projects
from core.auto_check import (ASR_RATE, NEED_MODEL, NOISE_MAX_DBFS, NOISE_MIN_MS,
                             SPEECH_MIN_SCORE, PACK_GAP_SEC, _lat_to_cyr, _norm, _ratio,
                             fix_feature_size, mels_from_error, similarity)
from core.num_words import synth_text
from core.ui_dialogs import ui_confirm
from utils.wav_io import export_like, fix_wav_header, wav_concat, wav_layout, wav_render, wav_slice

TTS_STATE_FILE = 'tts_project.json'
TTS_RECORDS_DIR = 'Записи'
# Папки внутри проекта: выбрали одну из них — проект на уровень выше.
TTS_INNER_DIRS = (TTS_RECORDS_DIR, 'Чанки', 'Проверенные', 'Фразы_Переменные', '_Корзина')
TTS_STATE_VERSION = 3     # 3: фразы ищутся в сплошном потоке слов, а не по паузам
TTS_CHUNKS_DIR = 'Чанки'
TTS_DONE_DIR = 'Проверенные'
TTS_VAR_DIR = 'Фразы_Переменные'
TTS_TRASH_DIR = '_Корзина'
TTS_UNDO_DIR = '.gvox_undo'        # удалённые дубли — до Ctrl+Z (служебная, чистится при открытии)
TTS_VALUES_DIR = 'Значения'   # готовые значения переменных: Значения/<лист>/<категория>/<значение>.wav
TTS_CUT_PAD_MS = 150
TTS_OK_SCORE = 0.80       # дубль «зелёный» — совпал с текстом
TTS_OK_MARGIN = 0.10      # …и заметно лучше второго варианта
TTS_TIE = 0.03            # почти равные варианты — решает порядок записи
TTS_LISTEN_SHARE = 0.8    # «прослушан» = отыграл хотя бы 80% длины
OUT_RATE = 8000           # готовые файлы — 8 кГц, 16 бит, моно (формат IVR)
OUT_SPEECH_DB = -18.0     # уровень речи готовых файлов: одинаковый у всех, «не тихо и не громко»
OUT_PEAK_DB = -1.0        # пики не выше — без перегруза
OUT_GAIN_LIMIT_DB = 30.0  # больше не поднимаем (если это тишина/шум)
TAKE_GAIN_DB = (-12.0, 12.0)   # громкость дубля в «Сборке»: ± к выровненному уровню
TAKE_TEMPO = (0.70, 1.40)      # темп: быстрее/медленнее без смены высоты голоса (ffmpeg atempo)
EDIT_CONTEXT_MS = 1500    # запас записи вокруг дубля в «Сборке» — край можно вытянуть
EDIT_BUCKET_MS = 10       # шаг волны

FLAG_COLS = ('start', 'start_2', 'end')
BAD_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _tag(v):
    """'<sum_ru>' → 'sum_ru'; не тег — None."""
    s = str(v or '').strip()
    m = re.fullmatch(r'<\s*([^<>]+?)\s*>', s)
    return m.group(1).strip().lower() if m else None


def _flag(v):
    return v not in (None, '', 0, '0') and str(v).strip() not in ('', '0')


def _inline_values(v):
    """Ячейка колонки переменной со значениями прямо в ней («к ограниченной
    категории» / «к ограниченному бренду» / … — по строке на значение), а не
    просто отметка 1/x/+. Возвращает список значений или None."""
    s = str(v or '').strip()
    if not re.search(r'[A-Za-zА-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]{2}', s) or s.lower() in ('да', 'yes', 'var'):
        return None
    out, seen = [], set()
    for x in re.split(r'[\n\r;]+', s):
        x = re.sub(r'\s+', ' ', x).strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out or None


def _lang_of(name):
    low = (name or '').lower()
    if re.search(r'(^|[_\s-])(kz|kk|kaz)([_\s>-]|$)', low):
        return 'kz'
    return 'ru'


def var_label(key):
    k = (key or '').lower()
    base = re.sub(r'_(ru|kz|kk)$', '', k)
    names = {'sum': 'Сумма', 'date': 'Дата', 'million': 'Миллионы', 'hundred_thousand': 'Сотни тысяч',
             'thousand': 'Тысячи', 'hundred': 'Сотни', 'tenge': 'Тенге', 'day': 'День', 'month': 'Месяц',
             'year': 'Год', 'name': 'Имя', 'time': 'Время'}
    label = names.get(base, base or k)
    lang = re.search(r'_(ru|kz|kk)$', k)
    return f"{label} {lang.group(1).upper()}" if lang and label != k else label


def clean_name(text):
    name = BAD_NAME.sub(' ', str(text)).strip()
    return re.sub(r'\s+', ' ', name).rstrip('. ')[:120]


def _common_name(names):
    """ru_da_1_1, ru_da_1_2, ru_da_1_3 → ru_da_1."""
    names = [n for n in names if n]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    pref = os.path.commonprefix(names)
    pref = re.sub(r'[_\-\s]+\d*$', '', pref) if not pref.endswith(('_', '-', ' ')) else pref.rstrip('_- ')
    return pref or names[0]


def _text_tag(t):
    """<phrase>, <full_phrase_ru>, <phrase_kz> — колонка с текстом фраз."""
    return bool(t) and re.fullmatch(r'(full_)?phrase(_(ru|kz|kk))?', t) is not None


def _name_tag(t):
    """<name_phrase>, <name_phrase_ru>, <name_full_phrase_kz> — колонка с именем файла."""
    return bool(t) and re.fullmatch(r'name_(full_)?phrase(_(ru|kz|kk))?', t) is not None


def parse_tts_workbook(path):
    """Разбирает таблицу. {phrase_sheets: [...], var_sheets: {...}}."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets, var_sheets = [], {}
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        head_idx = None
        for i, r in enumerate(rows[:10]):
            if any(_text_tag(_tag(c)) for c in r):
                head_idx = i
                break
        if head_idx is not None:
            sheets.append(_parse_phrase_sheet(ws.title, rows, head_idx))
            continue
        head = rows[0]
        cols = [(c, _tag(h)) for c, h in enumerate(head) if _tag(h)]
        if not cols:
            continue
        cats = []
        seen_by = {key: set() for _c, key in cols}
        order = []                         # порядок чтения: строка за строкой, слева направо
        for c, key in cols:
            seen, values = set(), []
            for r in rows[1:]:
                v = r[c] if c < len(r) else None
                if v is None or str(v).strip() == '':
                    continue
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                s = str(v).strip()
                if s not in seen:          # повторы-«заглушки» (100 после 900) не нужны
                    seen.add(s)
                    values.append(s)
            cats.append({"key": key, "label": var_label(key), "values": values})
        for ri, r in enumerate(rows[1:], start=2):
            for c, key in cols:
                v = r[c] if c < len(r) else None
                if v is None or str(v).strip() == '':
                    continue
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                s = str(v).strip()
                if s not in seen_by[key]:
                    seen_by[key].add(s)
                    order.append([key, s, ri])
        var_sheets[_tag(ws.title) or ws.title.strip().lower()] = {
            "title": ws.title, "label": var_label(_tag(ws.title) or ws.title), "categories": cats, "order": order}
    wb.close()
    return {"phrase_sheets": sheets, "var_sheets": var_sheets}


def _lang_mark(v):
    """Строка-переключатель языка: «<full_phrase_kz>», «full_phrase_ru»,
    «<name_full_phrase_kz>» (со скобками или без) → тег; иначе None."""
    s = str(v or '').strip().lower()
    s = s[1:-1].strip() if s.startswith('<') and s.endswith('>') else s
    return s if re.fullmatch(r'(name_)?(full_)?phrase_(ru|kz|kk)', s) else None


_KZ_LETTERS = re.compile(r'[әғқңөұүһі]', re.I)


def text_lang(text):
    """Язык по самому тексту: казахские буквы → 'kz'; длинный текст без них →
    'ru'; короткий без них («Рахмет») — не понять, None."""
    t = str(text or '')
    if _KZ_LETTERS.search(t):
        return 'kz'
    if re.search(r'[а-яё]', t, re.I) and len(t.split()) >= 4:
        return 'ru'
    return None


def _parse_phrase_sheet(title, rows, head_idx):
    head = rows[head_idx]
    col = {}
    for c, h in enumerate(head):
        t = _tag(h)
        if t:
            col.setdefault(t, c)
    text_t = next((t for t in col if _text_tag(t)), None)
    name_t = next((t for t in col if _name_tag(t)), None)
    text_c, name_c = col.get(text_t), col.get(name_t)
    var_cols = [(t, c) for t, c in col.items() if t not in (text_t, name_t) + FLAG_COLS]
    lang_m = re.search(r'_(ru|kz|kk)$', text_t or '')
    lang = ('kz' if lang_m.group(1) in ('kz', 'kk') else 'ru') if lang_m else _lang_of(title)

    def cell(r, c):
        return r[c] if c is not None and c < len(r) else None

    lines = []
    cur_lang = None                   # строка-метка <full_phrase_kz> / <…_ru> — дальше фразы на этом языке
    for i, r in enumerate(rows[head_idx + 1:], start=head_idx + 2):
        text = str(cell(r, text_c) or '').strip()
        mark = _lang_mark(text) or _lang_mark(cell(r, name_c))
        ml = re.search(r'_(ru|kz|kk)$', mark or '')
        if ml:
            cur_lang = 'kz' if ml.group(1) in ('kz', 'kk') else 'ru'
            continue
        name = clean_name(cell(r, name_c) or '')
        role = next((f for f in FLAG_COLS if _flag(cell(r, col.get(f)))), None)
        vars_ = [t for t, c in var_cols if _flag(cell(r, c))]
        inline = next(({"key": t, "values": vals} for t, c in var_cols
                       for vals in [_inline_values(cell(r, c))] if vals), None)
        if not text and not name and not role:
            continue
        lines.append({"row": i, "text": text, "name": name or f"фраза_{i:04d}", "role": role, "vars": vars_,
                      "lang": cur_lang, "inline": inline})
    units, chains = build_units(lines)
    # Колонки разметки (1-based, как в Excel) — чтобы дописывать отметки в таблицу.
    mark_cols = {t: c + 1 for t, c in col.items() if t in FLAG_COLS or t in dict(var_cols)}
    return {"title": title, "lang": lang, "units": units, "chains": chains, "lines": lines,
            "var_keys": [t for t, _ in var_cols], "mark_cols": mark_cols, "head_row": head_idx + 1}


def build_units(lines):
    """Строки таблицы → юниты и цепочки.
    Юнит — каждая строка: сохраняется отдельным файлом под своим именем.
    Строки с флагами связываем в «цепочку» start → start_2 → end — это
    кусочки одной фразы. Цепочка нужна для «Сборки», суфлёра и для разрезки
    дубля, где фраза прочитана целиком (с примером значения внутри)."""
    units, chains, cur = [], [], None

    def close():
        nonlocal cur
        if cur:
            chains.append(cur)
        cur = None

    for ln in lines:
        uid = len(units)
        units.append({"id": uid, "kind": "piece" if ln["role"] else "phrase", "name": ln["name"],
                      "text": ln["text"] or ln["name"], "role": ln["role"], "row": ln["row"],
                      "vars": list(ln["vars"]), "var_before": None, "var_after": None, "chain": None,
                      "lang": ln.get("lang"), "inline": ln.get("inline")})
        if ln["role"] == 'start' or (ln["role"] and cur is None):
            close()
            cur = {"id": len(chains), "parts": [uid]}
        elif ln["role"]:
            cur["parts"].append(uid)
        else:
            close()
        if ln["role"] == 'end':
            close()
    close()

    # У start/start_2 отмеченная переменная идёт после кусочка, у end — перед ним.
    for ch in chains:
        parts = [units[i] for i in ch["parts"]]
        for k, u in enumerate(parts):
            u["chain"] = ch["id"]
            if u["role"] in ('start', 'start_2'):
                nxt = parts[k + 1] if k + 1 < len(parts) else None
                var = u["vars"][0] if u["vars"] else (nxt["vars"][0] if nxt and nxt["vars"] else None)
                u["var_after"] = var
                if nxt:
                    nxt["var_before"] = var
            elif u["role"] == 'end' and not u["var_before"] and u["vars"]:
                u["var_before"] = u["vars"][0]
        ch["name"] = _common_name([u["name"] for u in parts])
        ch["vars"] = [u["var_after"] for u in parts if u["var_after"]]

    # Значения переменной прямо в ячейке (колонка <var>): каждое — свой кусочек
    # «…/Фразы_Переменные/<цепочка>/<значение>.wav». Читаются по очереди:
    # start + значение + пара слов end, а у последнего значения — end целиком.
    for ch in chains:
        parts = [units[i] for i in ch["parts"]]
        host = next((u for u in parts if u.get("inline")), None)
        if not host:
            continue
        for u in parts:                                   # пометки-«слоты» тут не нужны: значения видны сами
            u["var_after"] = u["var_before"] = None
        vals = []
        for v in host["inline"]["values"]:
            uid = len(units)
            units.append({"id": uid, "kind": "piece", "name": clean_name(v) or f"значение_{len(vals) + 1}",
                          "text": v, "role": "var", "row": host["row"], "vars": [], "var_before": None,
                          "var_after": None, "chain": ch["id"], "lang": host.get("lang"), "inline": None,
                          "subdir": clean_name(ch["name"]) or "переменная", "var_key": host["inline"]["key"]})
            vals.append(uid)
        ch["values"] = vals
        ch["inline_at"] = host["id"]
        ch["inline_after"] = host["role"] in ('start', 'start_2')   # у start значение после, у end — перед
        ch["vars"] = []
    return units, chains


FIND_SCORE = 0.75         # окно слов засчитываем как фразу из таблицы
FIND_SCORE_SHORT = 0.90   # …а для фраз из 1–2 слов — только почти дословно
LONGER_TIE = 0.05         # почти равные окна — берём то, что длиннее (целая фраза, а не её начало)
LEAD_S = 0.40             # сколько тишины оставлять перед/после фразы (макс.)


def end_word_ok(window_words, target):
    """Фраза из 3+ слов засчитывается, только если сказан её конец:
    «вам сейчас удобно…» — ещё не «Вам сейчас удобно говорить?»."""
    tw = target.split()
    if len(tw) < 3 or not window_words:
        return True
    last = window_words[-1]
    return last[:4] == tw[-1][:4] or _ratio(last, tw[-1]) >= 0.6


def _first_word_ok(word, first):
    return bool(word) and bool(first) and (word[:3] == first[:3] or _ratio(word, first) >= 0.6)


def align_stream(words, units, expected=0):
    """Ищет фразы таблицы в сплошном потоке распознанных слов — не важно,
    как запись разрезалась по паузам (фразы часто слипаются в один кусок).
    words: [(слово, начало_с, конец_с)] по всей записи.
    → [{unit, score, status, i, j}] по порядку: слова [i, j) — эта фраза.
    Слова между находками (оговорки, «нет», значения переменных) пропускаются."""
    wn = [_lat_to_cyr(_norm(w[0])) for w in words]
    targets = []
    for u in units:
        t = _lat_to_cyr(_norm(u["text"]))
        if t:
            targets.append((u["id"], t, len(t.split()), t.split()[0]))
    found, i = [], 0
    while i < len(wn):
        cands = []
        for uid, t, n, first in targets:
            if not _first_word_ok(wn[i], first):
                continue
            best = (0.0, i + 1)
            for size in range(max(1, n - 2), n + 3):
                j = i + size
                if j > len(wn):
                    break
                if not end_word_ok(wn[i:j], t):
                    continue
                sc = _ratio(' '.join(wn[i:j]), t)
                if sc > best[0] + 1e-9:
                    best = (sc, j)
            need = FIND_SCORE_SHORT if n <= 2 else FIND_SCORE
            if best[0] >= need:
                cands.append((best[0], best[1], uid, n))
        if not cands:
            i += 1
            continue
        top = max(c[0] for c in cands)
        near = [c for c in cands if top - c[0] <= LONGER_TIE]
        longest = max(c[3] for c in near)
        near = [c for c in near if c[3] == longest]
        # Одинаковые тексты в разных строках — решает порядок чтения таблицы.
        sc, j, uid, _ = min(near, key=lambda c: (-round(c[0], 2), c[2] < expected, abs(c[2] - expected)))
        found.append({"unit": uid, "score": round(sc, 3), "i": i, "j": j,
                      "status": "ok" if sc >= 0.85 else "doubt"})
        expected = uid + 1
        i = j
    return found


class TtsFlowMixin:

    # ---------------- состояние ----------------

    def _tts(self):
        st = getattr(self, 'tts', None)
        if st is None:
            st = self.tts = {"v": TTS_STATE_VERSION, "excel_path": None, "sheet": None, "lang": "ru",
                             "units": [], "chains": [], "var_sheets": {},
                             "work_dir": None, "raw_path": None, "takes": [], "index": 0}
        return st

    def tts_reset(self):
        """«Новый проект»: закрыть текущий TTS-проект (всё сохранено на диске —
        его можно открыть снова) и начать с чистого листа, без перезапуска."""
        if getattr(self, '_tts_rec', None):
            return {"error": "Сначала остановите запись (R)."}
        try:
            self.player.stop()
        except Exception:
            pass
        self._tts_save()                                 # последнее состояние — в проект на диске
        self.tts = None
        for k in ('_tts_del_stack', '_tts_claims_cache', '_tts_lvl_cache', '_tts_bg_cache', '_tts_audacity_take',
                  '_tts_playing', '_tts_raw_len', '_tts_reuse_cache', '_tts_live', '_tts_mem', '_tts_mem_bytes',
                  '_tts_disk_cache', '_tts_pre_want'):
            self.__dict__.pop(k, None)
        return self.tts_state()

    def _tts_save(self):
        self._tts_claims_cache = {}                      # файлы/дубли поменялись — пересчитать
        st = self._tts()
        wd = st.get("work_dir")
        if not wd or not os.path.isdir(wd):
            return
        try:
            with open(os.path.join(wd, TTS_STATE_FILE), 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        self._tts_disk_flush()
        recent_projects.touch(wd, os.path.basename(wd))

    def _tts_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"ttsProgress({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    def _tts_target(self, unit):
        if unit.get("tiers"):                        # строка переменных — файлы ярусов
            paths = [self._tts_tier_path(unit, t) for t in unit["tiers"]]
            return next((p for p in paths if not os.path.exists(p)), paths[-1])
        if unit["kind"] == "value":                  # значение переменной — в «Значения/<лист>/<категория>/»
            return self._tts_value_file(unit["sheet"], unit["cat"], unit["value"])
        folder = TTS_VAR_DIR if unit["kind"] == "piece" else TTS_DONE_DIR
        if unit.get("subdir"):                       # значение переменной из ячейки — в папку своей фразы
            return os.path.join(self._tts()["work_dir"], folder, unit["subdir"], f"{unit['name']}.wav")
        return os.path.join(self._tts()["work_dir"], folder, f"{unit['name']}.wav")

    # ---------------- одинаковые фразы под разными названиями ----------------
    # Текст тот же (без учёта регистра, ё/е и знаков внутри), тот же вид
    # (фраза / кусочек) и та же концовка: вопрос «?» звучит иначе, чем
    # утверждение, — такие не склеиваем. Записали одну — файл ложится и под
    # остальные названия. Копии помним (twin_copies: копия → источник), чтобы
    # обновлять их вместе с источником и не трогать записанные отдельно.

    @staticmethod
    def _tts_text_key(u):
        t = str(u.get("text") or '').lower().replace('ё', 'е')
        q = '?' if t.rstrip().endswith('?') else ''
        words = re.findall(r"[\w'-]+", t)
        if not words:
            return None
        return (u.get("kind"), u.get("var_before") or '', u.get("var_after") or '', ' '.join(words) + q)

    def _tts_twin_groups(self):
        groups = {}
        for u in self._tts()["units"]:
            k = self._tts_text_key(u)
            if k and not u.get("tiers"):
                groups.setdefault(k, []).append(u["id"])
        return [ids for ids in groups.values() if len(ids) > 1]

    def _tts_twins(self, uid):
        st = self._tts()
        k = self._tts_text_key(st["units"][uid])
        if st["units"][uid].get("tiers"):
            return []
        return [u["id"] for u in st["units"] if u["id"] != uid and k and not u.get("tiers") and self._tts_text_key(u) == k]

    def _tts_twin_spread(self, uid):
        """Сохранённую фразу — под названия всех её «близнецов» (кроме тех, что
        записаны отдельно). Возвращает названия, куда легла копия."""
        st = self._tts()
        if not st.get("work_dir"):
            return []
        copies = st.setdefault("twin_copies", {})
        src_u = st["units"][uid]
        copies.pop(src_u["name"], None)                  # сама фраза — уже не копия
        src = self._tts_target(src_u)
        if not os.path.exists(src):
            return []
        out = []
        for tid in self._tts_twins(uid):
            tu = st["units"][tid]
            dst = self._tts_target(tu)
            if os.path.exists(dst) and tu["name"] not in copies:
                continue                                 # записана отдельно — не трогаем
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copies[tu["name"]] = src_u["name"]
            out.append(tu["name"])
        return out

    def _tts_twin_copies_of(self, uid):
        """Пути копий, сделанных из этой фразы."""
        st = self._tts()
        name = st["units"][uid]["name"]
        by_name = {u["name"]: u for u in st["units"]}
        return [(n, self._tts_target(by_name[n])) for n, srcn in (st.get("twin_copies") or {}).items()
                if srcn == name and n in by_name]

    # ---------------- «Из записанного»: собрать фразу из уже записанных ----------------
    # Новая фраза разбирается на куски, которые уже звучат в сохранённых
    # фразах (из разных фраз, в начале, середине и конце), и то, что нужно
    # дописать. Целое предложение берётся даже коротким («Спасибо!»), если и
    # в записанной фразе оно отдельное предложение (там пауза — режется
    # чисто); обрывок внутри предложения — от 3 слов. Из вариантов
    # выбирается тот, где записанного больше, а стыков меньше.

    REUSE_MIN = 0.4           # сколько текста фразы должно уже быть записано
    REUSE_MIN_RUN = 3         # обрывок (не целое предложение) — от стольких слов
    REUSE_SEAM = 6            # «цена» одного стыка, в знаках
    REUSE_MARGIN_MS = 150     # запас при оценке, где в записи нужные слова

    @staticmethod
    def _tts_wnorm(w):
        return re.sub(r"[^\w'-]", '', str(w).lower().replace('ё', 'е')).strip("'-")

    @classmethod
    def _tts_words(cls, text):
        """Слова текста: [(норм. слово, исходный токен, № токена, конец предложения?)]."""
        raw = str(text or '').split()
        out = []
        for i, w in enumerate(raw):
            n = cls._tts_wnorm(w)
            if n:
                out.append((n, w, i, bool(re.search(r'[.!?…]["»)]*$', w))))
            elif out and re.search(r'[.!?…]', w):
                out[-1] = out[-1][:3] + (True,)
        if out:
            out[-1] = out[-1][:3] + (True,)
        return out, raw

    def _tts_reuse_index(self):
        """Сохранённые фразы по словам: язык → слово → [(фраза, позиция)]."""
        st = self._tts()
        wd = st.get("work_dir")
        idx, words = {}, {}
        if not wd:
            return idx, words
        for u in st["units"]:
            if u["kind"] in ("piece", "value") or not os.path.exists(self._tts_target(u)):
                continue
            ws, _raw = self._tts_words(u["text"])
            words[u["id"]] = ws
            d = idx.setdefault(self._tts_unit_lang(u["id"]), {})
            for j, w in enumerate(ws):
                d.setdefault(w[0], []).append((u["id"], j))
        return idx, words

    def _tts_reuse_for(self, uid, index=None):
        """Как собрать фразу из записанного: куски «есть» и «дописать»."""
        st = self._tts()
        u = st["units"][uid]
        if u["kind"] in ("piece", "value") or (st.get("work_dir") and os.path.exists(self._tts_target(u))):
            return None
        idx, xwords = index or self._tts_reuse_index()
        d = idx.get(self._tts_unit_lang(uid)) or {}
        Y, raw = self._tts_words(u["text"])
        m = len(Y)
        if m < 2 or not d:
            return None
        ylen = [len(w[0]) for w in Y]
        total = sum(ylen)
        ystart = [k == 0 or Y[k - 1][3] for k in range(m)]
        # кандидаты: (начало в Y, длина, фраза-источник, начало в ней, целое предложение?)
        cands = [[] for _ in range(m)]
        for i in range(m):
            for x, j in d.get(Y[i][0], []):
                if x == uid:
                    continue
                X = xwords[x]
                k = 0
                while i + k < m and j + k < len(X) and X[j + k][0] == Y[i + k][0]:
                    k += 1
                if k == m and len(X) == m:
                    continue                                   # тот же текст — это «одинаковые»
                xstart = j == 0 or X[j - 1][3]
                lens = {k}
                lens.update(L for L in range(1, k) if Y[i + L - 1][3])     # обрезать по концу предложения
                for L in lens:
                    whole = (ystart[i] and Y[i + L - 1][3] and xstart and X[j + L - 1][3])
                    if L >= self.REUSE_MIN_RUN or whole:
                        cands[i].append((L, x, j, whole))
        # лучшая раскладка: больше записанного, меньше стыков
        best = [(-1e9, None)] * (m + 1)
        best[0] = (0.0, None)
        for i in range(m):
            sc, _ = best[i]
            if sc <= -1e9:
                continue
            if sc > best[i + 1][0]:
                best[i + 1] = (sc, (i, None))                  # слово i — дописать
            for L, x, j, whole in cands[i]:
                v = sc + sum(ylen[i:i + L]) - self.REUSE_SEAM + (2 if whole else 0)
                if v > best[i + L][0]:
                    best[i + L] = (v, (i, (L, x, j, whole)))
        segs, k = [], m
        while k > 0:
            i, c = best[k][1]
            segs.append((i, c))
            k = i
        segs.reverse()
        pieces = []
        for i, c in segs:
            if c is None:
                if pieces and pieces[-1]["kind"] == "rec":
                    pieces[-1]["y1"] = i + 1
                else:
                    pieces.append({"kind": "rec", "y0": i, "y1": i + 1})
            else:
                L, x, j, whole = c
                pieces.append({"kind": "have", "y0": i, "y1": i + L, "src": x, "src_name": st["units"][x]["name"],
                               "x0": j, "x1": j + L, "whole": whole})
        cov = sum(sum(ylen[p["y0"]:p["y1"]]) for p in pieces if p["kind"] == "have") / total if total else 0
        if cov < self.REUSE_MIN or not any(p["kind"] == "have" for p in pieces):
            return None
        for p in pieces:                                       # индексы → токены исходного текста
            p["k0"] = Y[p["y0"]][2]
            p["k1"] = Y[p["y1"] - 1][2] + 1
        # токены-«хвосты» (тире, знаки отдельным словом) — к соседнему куску
        for a_, b_ in zip(pieces, pieces[1:]):
            b_["k0"] = a_["k1"]
        pieces[0]["k0"] = 0
        pieces[-1]["k1"] = len(raw)
        for p in pieces:
            p["text"] = ' '.join(raw[p["k0"]:p["k1"]])
        rec = [p for p in pieces if p["kind"] == "rec"]
        srcs = []
        for p in pieces:
            if p["kind"] == "have" and p["src_name"] not in srcs:
                srcs.append(p["src_name"])
        return {"unit": uid, "pct": round(cov * 100), "pieces": pieces, "srcs": srcs,
                "src_name": srcs[0], "rest": ' … '.join(p["text"] for p in rec),
                "skip": u["name"] in (st.get("reuse_skip") or [])}

    def tts_reuse_list(self):
        """Все фразы, которые можно собрать из записанного (с номером на суфлёре)."""
        index = self._tts_reuse_index()
        out = []
        items = self._tts_prompt_items() if hasattr(self, '_tts_prompt_items') else [[u["id"]] for u in self._tts()["units"]]
        for p, ids in enumerate(items):
            if len(ids) != 1:
                continue
            r = self._tts_reuse_for(ids[0], index)
            if r:
                out.append({**r, "pos": p, "name": self._tts()["units"][ids[0]]["name"],
                            "text": self._tts()["units"][ids[0]]["text"]})
        out.sort(key=lambda r: -r["pct"])
        return {"items": out}

    def _tts_reuse_count(self, saved):
        sig = (len(self._tts()["units"]), tuple(k for k, v in saved.items() if v))
        cache = getattr(self, '_tts_reuse_cache', None)
        if not cache or cache[0] != sig:
            cache = self._tts_reuse_cache = (sig, len(self.tts_reuse_list()["items"]))
        return cache[1]

    def tts_reuse_skip(self, uid, skip=True):
        """«Читать целиком» — для этой фразы не подставлять записанное."""
        st = self._tts()
        name = st["units"][uid]["name"]
        lst = st.setdefault("reuse_skip", [])
        if skip and name not in lst:
            lst.append(name)
        if not skip and name in lst:
            lst.remove(name)
        self._tts_save()
        return {"ok": True}

    def _tts_reuse_source(self, src_uid, like):
        """Звук записанной фразы: клипы её дубля (байт в байт) или сохранённый файл."""
        st = self._tts()
        src_u = st["units"][src_uid]
        take = next((k for k in reversed(st["takes"]) if k.get("unit") == src_uid and k.get("approved")), None)
        if take is not None:
            clips = self._tts_clips(take)
            if all(os.path.exists(c["raw"]) for c in clips):
                return clips
        from core.tts_synth import write_like
        from utils.audio_player import _read_audio
        x, rate = _read_audio(self._tts_target(src_u))
        rdir = os.path.join(st["work_dir"], TTS_CHUNKS_DIR, '_повтор')
        os.makedirs(rdir, exist_ok=True)
        path = os.path.join(rdir, f"{src_u['name']}.wav")
        ln = write_like(path, x, rate, like)
        return [{"raw": path, "a": 0, "b": ln, "cuts": [], "pos": 0}]

    def _tts_char_span(self, words, w0, w1):
        """Доля текста до слова w0 и до конца слова w1-1 (для оценки времени)."""
        lens = [len(w[1]) + 1 for w in words]
        tot = sum(lens) or 1
        return sum(lens[:w0]) / tot, sum(lens[:w1]) / tot

    def _tts_reuse_clips(self, rem_clips, plan):
        """Дорожка по раскладке: куски записанных фраз (оценка по доле текста,
        с запасом — край подровняете) и новые куски из этой записи."""
        st = self._tts()
        M = self.REUSE_MARGIN_MS
        like = rem_clips[0]["raw"]
        out, pos = [], 0
        _idx, xwords = self._tts_reuse_index()
        recs = [p for p in plan["pieces"] if p["kind"] == "rec"]
        rec_chars = [len(p["text"]) + 1 for p in recs]
        rtot = sum(rec_chars) or 1
        r_a, r_b = int(rem_clips[0]["a"]), int(rem_clips[-1]["b"])
        r_done = 0
        for p in plan["pieces"]:
            if p["kind"] == "have":
                src = self._tts_reuse_source(p["src"], like)
                X = xwords.get(p["src"]) or []
                cut = []
                if len(src) == 1 and X and not (p["x0"] == 0 and p["x1"] == len(X)):
                    c = dict(src[0], cuts=[list(x) for x in src[0].get("cuts", [])])
                    a0, b0 = int(c["a"]), int(c["b"])
                    f0, f1 = self._tts_char_span(X, p["x0"], p["x1"])
                    c["a"] = max(a0, int(a0 + f0 * (b0 - a0)) - (M if p["x0"] > 0 else 0))
                    c["b"] = min(b0, int(a0 + f1 * (b0 - a0)) + (M if p["x1"] < len(X) else 0))
                    cut = [c]
                else:
                    cut = [dict(c, cuts=[list(x) for x in c.get("cuts", [])]) for c in src]
            else:
                share = rec_chars[recs.index(p)]
                f0, f1 = r_done / rtot, (r_done + share) / rtot
                r_done += share
                if len(recs) == 1:
                    cut = [dict(c) for c in rem_clips]
                else:
                    c = dict(rem_clips[0], cuts=[])
                    c["a"] = max(r_a, int(r_a + f0 * (r_b - r_a)) - (M if f0 > 0 else 0))
                    c["b"] = min(r_b, int(r_a + f1 * (r_b - r_a)) + (M if f1 < 1 else 0))
                    cut = [c]
            p0 = min(int(c["pos"]) for c in cut)
            span = max(int(c["pos"]) + sum(b - a for a, b in self._clip_ranges(c)) for c in cut) - p0
            for c in cut:
                out.append(dict(c, pos=int(c["pos"]) - p0 + pos))
            pos += span + 60
        return out

    def tts_reuse_build(self, uid):
        """Фраза целиком есть в записанном — собрать дубль без новой записи."""
        st = self._tts()
        plan = self._tts_reuse_for(uid)
        if not plan or plan["rest"]:
            return {"error": "Эту фразу нельзя собрать только из записанного."}
        first = next(p for p in plan["pieces"] if p["kind"] == "have")
        take0 = next((k for k in reversed(st["takes"]) if k.get("unit") == first["src"] and k.get("approved")), None)
        like = self._tts_clips(take0)[0]["raw"] if take0 else self._tts_target(st["units"][first["src"]])
        dummy = [{"raw": like, "a": 0, "b": 1, "cuts": [], "pos": 0}]
        clips = self._tts_reuse_clips(dummy, plan)
        n = max([t.get("chunk", 0) for t in st["takes"]] + [0]) + 1
        take = {"file": os.path.join(TTS_CHUNKS_DIR, f"{n:04d}.wav"), "start_ms": 0, "ms": 0, "orig": [0, 0],
                "raw": clips[0]["raw"], "heard": "(из записанного)", "listened": False, "chunk": n, "unit": uid,
                "score": 1.0, "status": "manual",
                "reuse": {"srcs": plan["srcs"], "rec": 0, "pieces": len(plan["pieces"])}}
        os.makedirs(os.path.join(st["work_dir"], TTS_CHUNKS_DIR), exist_ok=True)
        self._tts_render_clips(take, clips)
        take["clips"] = clips
        take["clips_orig"] = [dict(c) for c in clips]
        st["takes"].append(take)
        st["index"] = len(st["takes"]) - 1
        self._tts_save()
        return {**self.tts_state(), "built": st["units"][uid]["name"]}

    def tts_twins_info(self):
        """Группы одинаковых фраз: что записано, что можно заполнить копией."""
        st = self._tts()
        copies = st.get("twin_copies") or {}
        wd = st.get("work_dir")
        out, fill = [], 0
        for ids in self._tts_twin_groups():
            rows = []
            for i in ids:
                u = st["units"][i]
                saved = bool(wd) and os.path.exists(self._tts_target(u))
                rows.append({"id": i, "name": u["name"], "saved": saved, "copy_of": copies.get(u["name"]) if saved else None})
            has_src = any(r["saved"] and not r["copy_of"] for r in rows)
            missing = sum(1 for r in rows if not r["saved"])
            if has_src:
                fill += missing
            out.append({"text": st["units"][ids[0]]["text"], "units": rows, "can_fill": missing if has_src else 0})
        return {"groups": out, "fill": fill}

    def tts_twins_apply(self):
        """Разложить уже записанные фразы под названия их «близнецов»."""
        st = self._tts()
        if not st.get("work_dir"):
            return {"error": "Проект ещё не создан."}
        copies = st.setdefault("twin_copies", {})
        done = []
        for ids in self._tts_twin_groups():
            srcs = [i for i in ids if os.path.exists(self._tts_target(st["units"][i]))
                    and st["units"][i]["name"] not in copies]
            if not srcs:
                continue
            # источник — тот, что сохранён из дубля (одобренный), иначе первый записанный
            approved = {t.get("unit") for t in st["takes"] if t.get("approved")}
            src = next((i for i in srcs if i in approved), srcs[0])
            done += self._tts_twin_spread(src)
        self._tts_save()
        return {**self.tts_state(), "filled": len(done), "filled_names": done[:30]}

    def tts_state(self):
        st = self._tts()
        if any(t.get("rejected") for t in st["takes"]):
            self._tts_purge_rejected()
        units = st["units"]
        wd = st.get("work_dir")
        saved = {u["id"]: bool(wd) and os.path.exists(self._tts_target(u)) for u in units}
        main_units = [u for u in units if u["kind"] != "value"]       # значения переменных — свой счёт
        rows_now = [u for u in units if u.get("tiers") and u.get("logic") in (None, st.get("sum_logic", 1))]
        takes_by_unit = {}
        for i, t in enumerate(st["takes"]):
            if t.get("unit") is not None:
                takes_by_unit.setdefault(t["unit"], []).append(i)
        takes = []
        for i, t in enumerate(st["takes"]):
            u = units[t["unit"]] if t.get("unit") is not None and t["unit"] < len(units) else None
            same = takes_by_unit.get(t.get("unit"), [])
            takes.append({**t, "i": i, "name": u["name"] if u else None, "kind": u["kind"] if u else None,
                          "unit_saved": saved.get(t.get("unit"), False),
                          "take_no": same.index(i) + 1 if i in same else 0, "take_total": len(same)})
        pieces = [u for u in units if u["kind"] == "piece"]
        return {
            "loaded": bool(units), "has_takes": bool(st["takes"]),
            "excel_name": os.path.basename(st["excel_path"] or ''), "sheet": st.get("sheet"),
            "lang": st.get("lang", "ru"), "lang_auto": bool(units) and len(self._tts_langs()) > 1,
            "project": os.path.basename(wd) if wd else '',
            "units": [{**u, "saved": saved[u["id"]], "takes": takes_by_unit.get(u["id"], [])} for u in units],
            "chains": st.get("chains", []),
            "var_cols": [{"key": k, "label": var_label(k)} for k in (st.get("var_cols") or [])],
            "marks_pending": len(st.get("marks_dirty") or []),
            "takes": takes, "index": min(st.get("index", 0), max(0, len(takes) - 1)),
            "var_sheets": {k: {"label": v["label"],
                               "categories": [{"key": c["key"], "label": c["label"], "count": len(c["values"])}
                                              for c in v["categories"]]}
                           for k, v in st["var_sheets"].items()},
            "twins_fill": self.tts_twins_info()["fill"] if units else 0,
            "reuse_n": self._tts_reuse_count(saved) if units else 0,
            "prompt_mode": st.get("prompt_mode", "phrases"), "sum_logic": st.get("sum_logic", 1),
            "stats": {"units": len(main_units), "saved": sum(saved[u["id"]] for u in main_units),
                      "values": len(rows_now),
                      "values_saved": sum(saved[u["id"]] for u in rows_now),
                      "pieces": len(pieces), "pieces_saved": sum(1 for u in pieces if saved[u["id"]]),
                      "chains": len(st.get("chains", [])),
                      "missing": sum(1 for u in main_units if not saved[u["id"]] and u["id"] not in takes_by_unit),
                      "doubt": sum(1 for t in st["takes"] if t.get("status") == "doubt"
                                   and not saved.get(t.get("unit"), False))},
        }

    # ---------------- загрузка ----------------

    def tts_pick_excel(self):
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        return self.tts_load_excel(path)

    def tts_load_excel(self, path, sheet=None):
        try:
            parsed = parse_tts_workbook(path)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу «{os.path.basename(path)}».\n\n{e}"}
        sheets = parsed["phrase_sheets"]
        if not sheets:
            return {"error": "В таблице нет листа фраз: нужна шапка с колонкой <phrase> (или <full_phrase_ru>)."}
        if sheet is None and len(sheets) > 1:
            self._tts_pending = (path, parsed)
            return {"choose_sheet": [{"title": s["title"], "lang": s["lang"], "units": len(s["units"])}
                                     for s in sheets]}
        chosen = next((s for s in sheets if s["title"] == sheet), sheets[0])
        st = self._tts()
        old = st["units"]
        rebind = False
        if st["takes"] and st.get("excel_path") and os.path.abspath(st["excel_path"]) != os.path.abspath(path):
            st["takes"] = []      # другая таблица — старая привязка дублей неверна
        elif st["takes"] and st["units"]:
            rebind = True
        st.update({"excel_path": path, "sheet": chosen["title"], "lang": chosen["lang"],
                   "units": chosen["units"], "chains": chosen["chains"], "v": TTS_STATE_VERSION,
                   "lines": chosen["lines"], "mark_cols": chosen["mark_cols"], "var_cols": chosen["var_keys"],
                   "head_row": chosen["head_row"], "marks_dirty": [],
                   "var_sheets": {k: v for k, v in parsed["var_sheets"].items()
                                  if k in chosen["var_keys"] or not chosen["var_keys"]}})
        self._tts_ensure_value_units()               # значения переменных — тоже «фразы» для записи
        if rebind:
            # Та же таблица перечитана — номера фраз могли сдвинуться (строки-метки
            # <…_kz> больше не фразы, добавили строки): дубли — к той же строке Excel.
            by_row = {(u["row"], u["name"]): u["id"] for u in st["units"]}
            by_name = {}
            for u in st["units"]:
                if u["kind"] != "value":
                    by_name.setdefault(u["name"], u["id"])
            for t in st["takes"]:
                uid = t.get("unit")
                if uid is None or uid >= len(old):
                    continue
                ou = old[uid]
                t["unit"] = by_row.get((ou.get("row"), ou["name"]),
                                       None if ou.get("kind") == "value" else by_name.get(ou["name"]))
        st["index"] = 0
        self._tts_save()
        return self.tts_state()

    def tts_choose_sheet(self, title):
        pend = getattr(self, '_tts_pending', None)
        if not pend:
            return {"error": "Таблица не выбрана."}
        return self.tts_load_excel(pend[0], title)

    def _tts_unit_lang(self, uid):
        """Язык фразы: из метки <…_kz>/<…_ru> над ней в таблице, иначе — языка листа."""
        st = self._tts()
        u = st["units"][uid] if uid is not None and 0 <= uid < len(st["units"]) else None
        if not u:
            return st.get("lang", "ru")
        # Что на экране у диктора: казахские буквы — казахская модель, иначе
        # метка <…_kz>/<…_ru> над фразой, иначе язык листа.
        return text_lang(u.get("text")) or u.get("lang") or st.get("lang", "ru")

    def _tts_langs(self):
        st = self._tts()
        return sorted({self._tts_unit_lang(u["id"]) for u in st["units"]}) or [st.get("lang", "ru")]

    def tts_set_lang(self, lang):
        """Язык распознавания: RU или KZ (если по названию листа угадал не так)."""
        if getattr(self, '_tts_rec', None):
            return {"error": "Сначала остановите запись (R)."}
        st = self._tts()
        st["lang"] = 'kz' if lang == 'kz' else 'ru'
        self._tts_save()
        return self.tts_state()

    @staticmethod
    def tts_project_root(folder):
        """Папка проекта по любой выбранной: «Записи», «Чанки», «Проверенные»… —
        это папки внутри проекта, сам проект на уровень выше."""
        folder = os.path.normpath(folder) if folder else folder
        if not folder:
            return folder
        if os.path.exists(os.path.join(folder, TTS_STATE_FILE)):
            return folder
        if os.path.basename(folder) in TTS_INNER_DIRS:
            return os.path.dirname(folder)
        return folder

    def _tts_attach_folder(self, folder):
        """Работать в этой папке. Если там уже была работа (tts_project.json) —
        подтягиваем её: дубли, сохранённое, где остановился суфлёр. Таблица —
        та, что загружена сейчас, если это та же таблица. Возвращает сообщение
        для экрана или None (папка новая)."""
        st = self._tts()
        root = self.tts_project_root(folder)
        if not os.path.exists(os.path.join(root, TTS_STATE_FILE)):
            st["work_dir"] = root
            return None
        if st.get("work_dir") and os.path.normpath(st["work_dir"]) == root:
            return None                                   # уже работаем здесь
        self._tts_del_stack = []                          # другой проект — старые удалённые не вернуть
        shutil.rmtree(os.path.join(root, TTS_UNDO_DIR), ignore_errors=True)
        cur_excel, cur_sheet = st.get("excel_path"), st.get("sheet")
        res = self.tts_open_project(root)
        if res.get("error"):
            st = self._tts()
            st["work_dir"] = root
            return None
        st = self._tts()
        note = ''
        if cur_excel and os.path.exists(cur_excel):
            prev = st.get("excel_path")
            same = not prev or os.path.basename(prev).lower() == os.path.basename(cur_excel).lower()
            if same:
                # Та же таблица (могла переехать или измениться) — перечитываем
                # её, дубли остаются у своих строк.
                st["excel_path"] = cur_excel
                self.tts_load_excel(cur_excel, cur_sheet or st.get("sheet"))
            else:
                note = f" В этой папке работа по таблице «{os.path.basename(prev)}» — открыл её."
        st = self._tts()
        n = len([t for t in st["takes"] if not t.get("rejected")])
        saved = sum(1 for u in st["units"] if os.path.exists(self._tts_target(u)))
        self._tts_save()
        return f"Продолжаю прежнюю работу: дублей {n}, сохранено фраз {saved}.{note}"

    def tts_pick_project(self):
        """«Продолжить работу»: выбрать папку проекта (или «Записи» в ней)."""
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        folder = picked if isinstance(picked, str) else picked[0]
        root = self.tts_project_root(folder)
        if not os.path.exists(os.path.join(root, TTS_STATE_FILE)):
            return {"error": "В этой папке нет прежней работы TTS (нет файла tts_project.json). "
                             "Выберите папку проекта или папку «Записи» внутри неё."}
        msg = self._tts_attach_folder(root)
        return {**self.tts_state(), "message": msg}

    def tts_open_project(self, path):
        """Продолжить TTS-проект (tts_project.json в папке)."""
        try:
            with open(os.path.join(path, TTS_STATE_FILE), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {"error": "Не нашёл сохранённый TTS-проект в этой папке."}
        self.tts = None
        st = self._tts()
        old = data.get("v") != TTS_STATE_VERSION
        st.update(data)
        st["work_dir"] = path
        # Папку проекта перенесли (другой диск, другой компьютер) — исходные
        # записи ищем в её «Записи» по имени файла.
        def relink(raw):
            if not raw or os.path.exists(raw):
                return raw
            alt = os.path.join(path, TTS_RECORDS_DIR, os.path.basename(raw.replace('\\', '/')))
            return alt if os.path.exists(alt) else raw
        for t in st["takes"]:
            t["raw"] = relink(t.get("raw"))
            for c in t.get("clips") or []:
                c["raw"] = relink(c.get("raw"))
            for c in t.get("clips_orig") or []:
                c["raw"] = relink(c.get("raw"))
        st["raw_path"] = relink(st.get("raw_path"))
        # Запись могла оборваться (закрыли программу во время записи).
        for raw in {t.get("raw") for t in st["takes"]} | {st.get("raw_path")}:
            if raw and os.path.exists(raw):
                fix_wav_header(raw)
        if old:
            # Проект старого формата (цепочка = один файл): перечитываем
            # таблицу, а дубли нужно нарезать заново — привязка другая.
            st["takes"], st["index"] = [], 0
            if st.get("excel_path") and os.path.exists(st["excel_path"]):
                res = self.tts_load_excel(st["excel_path"], st.get("sheet"))
                if res.get("error"):
                    return res
            st["v"] = TTS_STATE_VERSION
            self._tts_save()
        return self.tts_state()

    @staticmethod
    def tts_is_project(path):
        return bool(path) and os.path.exists(os.path.join(path, TTS_STATE_FILE))

    def tts_pick_recording(self):
        st = self._tts()
        if not st["units"]:
            return {"error": "Сначала загрузите таблицу."}
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if getattr(self, '_tts_rec', None):
            return {"error": "Сейчас идёт запись с микрофона — сначала остановите её."}
        # Запись лежит в «Записи» проекта — работаем в самом проекте и сначала
        # подтягиваем прежнюю работу (чтобы не затереть её дубли молча).
        note = self._tts_attach_folder(os.path.dirname(path))
        st = self._tts()
        if st["takes"] and not ui_confirm("Запись уже нарезана и проверена. Нарезать заново?<br><br>"
                                          "Сохранённые фразы останутся на месте.", "Нарезать заново", "Отмена"):
            # Отказались — но прежнюю работу из этой папки всё равно показываем.
            return {"error": "cancel", "state": self.tts_state() if note else None, "message": note}
        threading.Thread(target=self._tts_process, args=(path,), daemon=True).start()
        return {"status": "started"}

    # ---------------- нарезка + распознавание ----------------

    def _tts_process(self, path):
        lock = getattr(self, '_auto_check_lock', None)
        if lock is None:
            lock = self._auto_check_lock = threading.Lock()
        if not lock.acquire(blocking=False):
            self._tts_push({"stage": "error", "error": "Распознавание уже идёт."})
            return
        try:
            self._auto_check_stop = False
            res = self._tts_cut_and_check(path)
        except Exception as e:
            res = {"error": f"Не удалось обработать запись: {e}"}
        finally:
            lock.release()
        if res.get("error"):
            self._tts_push({"stage": "error", **res})
        else:
            self._tts_push({"stage": "done", "state": self.tts_state()})

    def _tts_cut_and_check(self, path):
        st = self._tts()
        self._tts_push({"stage": "cut", "done": 0, "total": 0})
        audio = AudioSegment.from_file(path)
        levels = self._frame_levels(audio)
        if not levels:
            return {"error": "Запись пустая или слишком короткая."}
        _, _, _, thresh, pause, _ = self._suggest_cut_settings(levels, len(st["units"]))
        ranges = detect_nonsilent(audio, min_silence_len=int(pause), silence_thresh=int(thresh))
        if not ranges:
            return {"error": "В записи не нашлось речи."}

        work_dir = st.get("work_dir") or self.tts_project_root(os.path.dirname(path))
        chunks_dir = os.path.join(work_dir, TTS_CHUNKS_DIR)
        os.makedirs(chunks_dir, exist_ok=True)
        for f in os.listdir(chunks_dir):
            if re.fullmatch(r'\d{4}(_\d+)?\.wav', f):
                try:
                    os.remove(os.path.join(chunks_dir, f))
                except OSError:
                    pass
        pieces = []
        for i, (a, b) in enumerate(ranges):
            piece = audio[max(0, a - TTS_CUT_PAD_MS):min(len(audio), b + TTS_CUT_PAD_MS)]
            pieces.append((f"{i + 1:04d}", piece, a))
            if i % 20 == 0:
                self._tts_push({"stage": "cut", "done": i + 1, "total": len(ranges)})

        self._tts_push({"stage": "model", "done": 0, "total": 0})
        model, err = self._auto_check_model(st["lang"])
        if err is NEED_MODEL:
            return {"error": "need_model_kz" if st["lang"] == 'kz' else "need_model"}
        if err:
            return {"error": err}

        heards, words = self._tts_transcribe([p[1] for p in pieces], 'kk' if st["lang"] == 'kz' else 'ru', model)
        takes = self._tts_build_takes(audio, pieces, words, st["units"], chunks_dir, path)
        st.update({"work_dir": work_dir, "raw_path": path, "index": 0, "takes": takes})
        st["index"] = self._tts_next(-1)
        self._tts_save()
        return {"status": "ok"}

    def _tts_build_takes(self, audio, pieces, words, units, chunks_dir, raw_path):
        """Сплошной поток слов всей записи → фразы таблицы → по файлу на
        каждую найденную фразу (разрез — в тишине между словами)."""
        stream = []
        for k, (name, piece, a) in enumerate(pieces):
            off = max(0, a - TTS_CUT_PAD_MS) / 1000.0
            stream += [(w, off + ws, off + we, k) for w, ws, we in words[k]]
        spans = self._tts_spans(stream, align_stream(stream, units))
        return self._tts_cut_spans(audio, 0, stream, spans, raw_path, chunks_dir, 1)

    @staticmethod
    def _tts_spans(stream, found):
        """Найденные фразы + неопознанная речь (≥4 слов подряд — вдруг это
        фраза, которую распознавание исказило; привяжете вручную)."""
        spans = []
        used = [False] * len(stream)
        for f in found:
            i, j = f["i"], f["j"]
            for x in range(i, j):
                used[x] = True
            spans.append((i, j, {"unit": f["unit"], "score": f["score"], "status": f["status"]}))
        x = 0
        while x < len(stream):
            if used[x]:
                x += 1
                continue
            y = x
            while y < len(stream) and not used[y] and stream[y][3] == stream[x][3]:
                y += 1
            if y - x >= 4:
                spans.append((x, y, {"unit": None, "score": 0.0, "status": "none"}))
            x = y
        spans.sort(key=lambda sp: sp[0])
        return spans

    def _tts_cut_spans(self, audio, offset_ms, stream, spans, raw_path, chunks_dir, first_n, push=True):
        """Вырезает каждую фразу из исходника байт в байт. audio — анализный
        звук, начинающийся с offset_ms записи (для поиска тишины); время слов
        в stream — от начала записи."""
        takes = []
        end_s = (offset_ms + len(audio)) / 1000.0
        rel = lambda sec: sec - offset_ms / 1000.0
        for n, (i, j, info) in enumerate(spans):
            first_s, last_e = stream[i][1], stream[j - 1][2]
            prev_e = stream[i - 1][2] if i > 0 else offset_ms / 1000.0
            next_s = stream[j][1] if j < len(stream) else end_s
            lo = offset_ms + self._tts_quiet_point(audio, *self._tts_edge_window(
                rel(max(prev_e, first_s - LEAD_S)), rel(first_s + 0.03)))
            hi = offset_ms + self._tts_quiet_point(audio, *self._tts_edge_window(
                rel(last_e - 0.03), rel(min(next_s, last_e + LEAD_S))))
            if hi - lo < 150:
                lo, hi = int(first_s * 1000), int(last_e * 1000) + 60
            name = f"{first_n + n:04d}.wav"
            # Копия байт из исходника — без перекодирования, качество не трогаем.
            if not wav_slice(raw_path, os.path.join(chunks_dir, name), lo, hi):
                audio[lo - offset_ms:hi - offset_ms].export(os.path.join(chunks_dir, name), format="wav")
            takes.append({"file": os.path.join(TTS_CHUNKS_DIR, name), "start_ms": lo, "ms": hi - lo, "orig": [lo, hi],
                          "raw": raw_path, "heard": ''.join(w[0] for w in stream[i:j]).strip(), "listened": False,
                          "chunk": first_n + n, **info})
            if push and n % 20 == 0:
                self._tts_push({"stage": "save", "done": n + 1, "total": len(spans)})
        return takes

    @staticmethod
    def _tts_edge_window(a, b):
        """Время слов у распознавания неточное (±50 мс): паузу между словами
        в 50–100 мс оно может «съесть». Узкое окно расширяем вокруг середины."""
        if b - a < 0.16:
            c = (a + b) / 2
            return c - 0.10, c + 0.10
        return a, b

    @staticmethod
    def _tts_quiet_point(seg, lo_s, hi_s):
        """Самое тихое место (мс) в окне — туда и ставим разрез."""
        lo, hi = max(0, int(lo_s * 1000)), min(len(seg), int(hi_s * 1000))
        if hi - lo < 20:
            return max(0, min(len(seg), int((lo_s + hi_s) * 500)))
        frames = [(t, seg[t:t + 10].rms) for t in range(lo, hi - 10 + 1, 5)]
        floor = min(r for _, r in frames)
        quiet = floor * 1.5 + 30
        # Середина самой длинной тихой полосы — не край паузы, а её центр.
        best, run = (0, frames[0][0]), None
        for t, r in frames:
            if r <= quiet:
                run = run or t
                if t - run >= best[0]:
                    best = (t - run, run)
            else:
                run = None
        return best[1] + (best[0] + 10) // 2

    def _tts_transcribe_pack(self, model, pack, language, live=False, hotwords=None):
        """Как _asr_transcribe_pack, но со временем слов внутри каждого дубля:
        [(слово, начало_с, конец_с)] — по ним режем цепочку на кусочки.
        live — запись с микрофона: чувствительнее к тихим коротким словам
        (команды), hotwords — подсказка модели, какие слова ждать."""
        import numpy as np
        gap = np.zeros(int(PACK_GAP_SEC * ASR_RATE), dtype=np.float32)
        parts, spans, t = [], [], 0.0
        for k, it in enumerate(pack):
            if k:
                parts.append(gap)
                t += PACK_GAP_SEC
            parts.append(it['audio'])
            d = len(it['audio']) / ASR_RATE
            spans.append((t, t + d))
            t += d
        audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
        # Тихая запись (некоторые гарнитуры) распознаётся хуже — поднимаем по
        # уровню голоса, а не по одному пику (щелчок не должен мешать).
        if len(audio):
            ref = float(np.percentile(np.abs(audio), 99.5))
            if 1e-4 < ref < 0.35:
                audio = np.clip(audio * min(40.0, 0.5 / ref), -1.0, 1.0)
        opts = dict(language=None if language == 'auto' else language, beam_size=1, best_of=1,
                    word_timestamps=True, vad_filter=True, condition_on_previous_text=False)
        if live:
            opts["vad_parameters"] = {"threshold": 0.3, "min_speech_duration_ms": 80, "min_silence_duration_ms": 300}
        if hotwords:
            opts["hotwords"] = hotwords
        def run():
            try:
                return model.transcribe(audio, **opts)
            except TypeError:                      # старая faster-whisper — без hotwords
                opts.pop("hotwords", None)
                return model.transcribe(audio, **opts)
        try:
            segments, _info = run()
            segments = list(segments)
        except Exception as e:
            # Модель ждёт другое число мел-полос (нет preprocessor_config.json) — чиним и ещё раз.
            if not fix_feature_size(model, mels_from_error(e)):
                raise
            segments, _info = run()
        no_speech, logprob = (0.85, -1.0) if live else (0.6, -0.7)
        words = [[] for _ in pack]
        for seg in segments:
            if getattr(seg, 'no_speech_prob', 0) > no_speech and getattr(seg, 'avg_logprob', 0) < logprob:
                continue
            for w in (seg.words or []):
                mid = (w.start + w.end) / 2
                for k, (a, b) in enumerate(spans):
                    if a - 0.3 <= mid <= b + 0.3:
                        words[k].append((w.word, max(0.0, w.start - a), max(0.0, w.end - a)))
                        break
        return words

    def _tts_transcribe(self, segs, language, model):
        """[текст дубля], [[(слово, начало, конец)]]."""
        total = len(segs)
        heard = [''] * total
        words_out = [[] for _ in range(total)]
        state = {"done": 0}
        lock = threading.Lock()

        def finish(k, text, words=None):
            with lock:
                heard[k] = text
                words_out[k] = words or []
                state["done"] += 1
                d = state["done"]
            if d % 5 == 0 or d == total:
                self._tts_push({"stage": "asr", "done": d, "total": total})

        items = []
        for k, seg in enumerate(segs):
            samples, ms, peak = self._audit_asr_samples(seg)
            if ms < NOISE_MIN_MS or peak < NOISE_MAX_DBFS:
                finish(k, '')
            else:
                items.append({"index": k, "audio": samples, "ms": ms})

        def run(pack):
            if getattr(self, '_auto_check_stop', False):
                return
            try:
                out = self._tts_transcribe_pack(model, pack, language)
            except Exception:
                out = [[] for _ in pack]
            for it, ws in zip(pack, out):
                h = ''.join(w[0] for w in ws).strip()
                if self._asr_is_noise(h):
                    finish(it['index'], '')
                else:
                    finish(it['index'], h, ws)

        with ThreadPoolExecutor(max_workers=getattr(self, '_asr_workers', 1)) as ex:
            list(ex.map(run, self._asr_packs(items)))
        return heard, words_out

    def tts_stop(self):
        self._auto_check_stop = True
        return {"status": "ok"}

    # ---------------- прослушка и апрув ----------------

    def _tts_mark_listened(self):
        p = getattr(self, '_tts_playing', None)
        if not p:
            return
        i, started, dur = p
        takes = self._tts()["takes"]
        if i < len(takes) and time.time() - started >= dur * TTS_LISTEN_SHARE:
            takes[i]["listened"] = True
        self._tts_playing = None

    def tts_play(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if not (0 <= i < len(st["takes"])):
            return {"playing": False}
        path = os.path.join(st["work_dir"], st["takes"][i]["file"])
        if not os.path.exists(path):
            return {"playing": False, "error": "Файл дубля пропал с диска."}
        st["index"] = i
        gain, tempo = self._tts_sound(st["takes"][i])
        dur = st["takes"][i].get("ms", 0) / 1000.0 / tempo
        # Слушаете ровно то, что сохранится: громкость выровнена, темп, 8 кГц.
        try:
            path = self._tts_preview(path, gain, tempo)
        except Exception:
            pass
        self.player.play(path)
        self._tts_playing = (i, time.time(), dur)
        return {"playing": True, "duration": dur, "tempo": tempo}

    def tts_stop_audio(self):
        self._tts_mark_listened()
        self.player.stop()
        return {"playing": False}

    def tts_select(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if 0 <= i < len(st["takes"]):
            st["index"] = i
        return self.tts_state()

    def _tts_next(self, after):
        """Следующий дубль, который ещё нужно прослушать: привязан к фразе,
        а фраза не сохранена. Сначала — вперёд по записи, потом с начала.
        Из повторов одной фразы предлагаем последний (диктор переговаривает
        после ошибки); забракуете его — следующим пойдёт предыдущий."""
        st = self._tts()
        takes = st["takes"]
        n = len(takes)
        last = {}
        for k, t in enumerate(takes):
            if t.get("unit") is not None and not t.get("rejected"):
                last[t["unit"]] = k
        saved = {}
        for k in list(range(after + 1, n)) + list(range(0, after + 1)):
            t = takes[k]
            uid = t.get("unit")
            if uid is None or t.get("rejected") or last.get(uid) != k:
                continue
            if uid not in saved:
                saved[uid] = os.path.exists(self._tts_target(st["units"][uid])) if st.get("work_dir") else False
            if not saved[uid]:
                return k
        return max(0, min(after, n - 1))

    def tts_approve(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        if t.get("unit") is None:
            return {"error": "Дубль не привязан к фразе — выберите фразу."}
        # Сохранять можно и без прослушивания — вы сами решаете, что дубль верный.
        unit = st["units"][t["unit"]]
        tiers_out = None
        if unit.get("tiers"):                          # строка переменных — каждый ярус своим эталоном
            written, skipped = self._tts_tier_save(t, unit)
            tiers_out = {"written": [os.path.relpath(p, st["work_dir"]) for p in written], "skipped": skipped}
        else:
            target = self._tts_target(unit)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                self._tts_trash(target)
            self._tts_render_final(os.path.join(st["work_dir"], t["file"]), target, *self._tts_sound(t))
        for other in st["takes"]:
            if other.get("unit") == t["unit"]:
                other["approved"] = False
        t["approved"] = True
        t["rejected"] = False
        twins = self._tts_twin_spread(t["unit"])
        st["index"] = self._tts_next(i)
        self._tts_save()
        return {**self.tts_state(), "saved_kind": unit["kind"], "saved_name": unit["name"], "twins": twins,
                "tiers_saved": tiers_out}

    def tts_reject(self, i):
        """Прежняя «Плохой дубль» — теперь удаление (Ctrl+Z возвращает)."""
        return self.tts_take_delete(i)

    def tts_take_delete(self, i):
        """Удалить дубль с дорожки. Если фраза была сохранена именно из него —
        сохранённый файл тоже уходит: фразу можно записать заново. Суфлёр
        возвращается к этой фразе. Ctrl+Z — вернуть всё как было."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return self.tts_state()
        t = st["takes"][i]
        wd = st.get("work_dir")
        rec = {"take": dict(t), "i": i, "index": st.get("index", 0), "prompt_pos": st.get("prompt_pos"),
               "moves": []}
        stash = os.path.join(wd, TTS_UNDO_DIR) if wd else None

        def hide(path):
            if not stash or not path or not os.path.exists(path):
                return
            os.makedirs(stash, exist_ok=True)
            self._tts_undo_n = getattr(self, '_tts_undo_n', 0) + 1
            dst = os.path.join(stash, f"{self._tts_undo_n:05d}_{os.path.basename(path)}")
            shutil.move(path, dst)
            rec["moves"].append((path, dst))
        if wd and t.get("file") and not any(o is not t and o.get("file") == t["file"] for o in st["takes"]):
            hide(os.path.join(wd, t["file"]))
        if wd and t.get("tier_files"):                 # ярусы, сохранённые из этого дубля
            for p in t["tier_files"]:
                hide(p)
        elif wd and t.get("approved") and t.get("unit") is not None and t["unit"] < len(st["units"]):
            hide(self._tts_target(st["units"][t["unit"]]))
            copies = st.setdefault("twin_copies", {})
            rec["twin_copies"] = {}
            for n, path in self._tts_twin_copies_of(t["unit"]):     # копии под другими названиями — тоже
                hide(path)
                rec["twin_copies"][n] = copies.pop(n)
        del st["takes"][i]
        st["index"] = max(0, min(i, len(st["takes"]) - 1))
        if t.get("unit") is not None and hasattr(self, '_tts_prompt_items'):
            pos = next((k for k, ids in enumerate(self._tts_prompt_items()) if t["unit"] in ids), None)
            if pos is not None:
                self._tts_prompt_fix(start=pos)       # суфлёр — обратно к этой фразе
        stack = self.__dict__.setdefault('_tts_del_stack', [])
        stack.append(rec)
        del stack[:-100]
        self._tts_save()
        u = st["units"][t["unit"]]["name"] if t.get("unit") is not None and t["unit"] < len(st["units"]) else None
        return {**self.tts_state(), "deleted": u or 'дубль', "can_undo": True}

    def tts_take_undo_delete(self):
        """Ctrl+Z: вернуть последний удалённый дубль (и сохранённую из него фразу)."""
        st = self._tts()
        stack = getattr(self, '_tts_del_stack', None)
        if not stack:
            return {**self.tts_state(), "error": "Нечего возвращать."}
        rec = stack.pop()
        for orig, dst in reversed(rec["moves"]):
            if os.path.exists(dst) and not os.path.exists(orig):
                os.makedirs(os.path.dirname(orig), exist_ok=True)
                shutil.move(dst, orig)
        st.setdefault("twin_copies", {}).update(rec.get("twin_copies") or {})
        i = max(0, min(rec["i"], len(st["takes"])))
        st["takes"].insert(i, rec["take"])
        st["index"] = i
        if rec.get("prompt_pos") is not None:
            st["prompt_pos"] = rec["prompt_pos"]
        self._tts_save()
        t = rec["take"]
        u = st["units"][t["unit"]]["name"] if t.get("unit") is not None and t["unit"] < len(st["units"]) else None
        return {**self.tts_state(), "restored": u or 'дубль', "can_undo": bool(stack)}

    def _tts_purge_rejected(self):
        """Старые «зачёркнутые» дубли (прежняя «Плохой дубль») — убрать с
        дорожки: файлы в «_Корзина», сохранённая из них фраза тоже."""
        st = self._tts()
        bad = [t for t in st["takes"] if t.get("rejected")]
        if not bad:
            return
        wd = st.get("work_dir")
        for t in bad:
            try:
                if wd and t.get("file") and os.path.exists(os.path.join(wd, t["file"])):
                    self._tts_trash(os.path.join(wd, t["file"]))
                for p in t.get("tier_files") or []:
                    if os.path.exists(p):
                        self._tts_trash(p)
                if wd and t.get("approved") and not t.get("tier_files") and t.get("unit") is not None \
                        and t["unit"] < len(st["units"]) and not st["units"][t["unit"]].get("tiers"):
                    target = self._tts_target(st["units"][t["unit"]])
                    if os.path.exists(target):
                        self._tts_trash(target)
            except OSError:
                pass
        cur = st["takes"][st["index"]] if st["takes"] and st.get("index", 0) < len(st["takes"]) else None
        st["takes"] = [t for t in st["takes"] if not t.get("rejected")]
        st["index"] = st["takes"].index(cur) if cur in st["takes"] else max(0, min(st.get("index", 0), len(st["takes"]) - 1))
        self._tts_save()

    def tts_unapprove(self, unit_id):
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return self.tts_state()
        if st["units"][unit_id].get("tiers"):          # строка: убираем ярусы, сохранённые из её дублей
            for t in st["takes"]:
                if t.get("unit") == unit_id:
                    for p in t.pop("tier_files", None) or []:
                        if os.path.exists(p):
                            self._tts_trash(p)
                    t["approved"] = False
            self._tts_save()
            return self.tts_state()
        target = self._tts_target(st["units"][unit_id])
        if os.path.exists(target):
            self._tts_trash(target)
        copies = st.get("twin_copies") or {}
        if st["units"][unit_id]["name"] in copies:
            copies.pop(st["units"][unit_id]["name"], None)        # убрали копию — только её
        else:
            for n, path in self._tts_twin_copies_of(unit_id):     # убрали источник — и его копии
                if os.path.exists(path):
                    self._tts_trash(path)
                copies.pop(n, None)
        for t in st["takes"]:
            if t.get("unit") == unit_id:
                t["approved"] = False
        self._tts_save()
        return self.tts_state()

    def tts_assign(self, i, unit_id):
        """Ручная привязка дубля к другой фразе (если автопроверка ошиблась)."""
        st = self._tts()
        if 0 <= i < len(st["takes"]):
            t = st["takes"][i]
            if unit_id is None or unit_id < 0:
                t.update({"unit": None, "status": "none", "score": 0.0})
            elif unit_id < len(st["units"]):
                score = similarity(t.get("heard") or '', st["units"][unit_id]["text"]) if t.get("heard") else 0.0
                t.update({"unit": unit_id, "score": round(score, 3), "status": "manual"})
            t["approved"] = False
            self._tts_save()
        return self.tts_state()

    def tts_play_unit(self, unit_id):
        """Прослушать уже сохранённую фразу (карточка «Переменные», список)."""
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return {"playing": False}
        target = self._tts_target(st["units"][unit_id])
        if not os.path.exists(target):
            return {"playing": False}
        self._tts_mark_listened()
        self.player.play(target)
        return {"playing": True, "duration": len(AudioSegment.from_file(target)) / 1000.0}

    def _tts_trash(self, path):
        trash = os.path.join(self._tts()["work_dir"], TTS_TRASH_DIR)
        os.makedirs(trash, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(trash, f"{base}{ext}")
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(trash, f"{base} ({n}){ext}")
            n += 1
        shutil.move(path, dest)

    def tts_open_folder(self, which):
        st = self._tts()
        if not st.get("work_dir"):
            return {"error": "Проект ещё не создан."}
        folder = os.path.join(st["work_dir"], TTS_VAR_DIR if which == 'var' else TTS_DONE_DIR)
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            return {"error": str(e)}
        return {"status": "ok"}

    # ---------------- «Сборка»: монтаж дубля прямо в программе ----------------
    # Дубль показывается вместе с запасом записи вокруг (EDIT_CONTEXT_MS):
    # если автонарезка срезала слово, край можно просто вытянуть наружу.
    # Все правки собираются из исходной записи байт в байт.

    def _tts_raw(self, t):
        """Исходная запись дубля (у живой записи их может быть несколько)."""
        return (t or {}).get("raw") or self._tts().get("raw_path")

    @staticmethod
    def _tts_orig(t):
        """Границы дубля, как его нарезала программа (до правок)."""
        if not t.get("orig"):
            t["orig"] = [t["start_ms"], t["start_ms"] + t["ms"]]
        return t["orig"]

    def _tts_take_ranges(self, t, a=None, b=None, cuts=None):
        """Абсолютные куски исходника (мс), из которых состоит дубль."""
        ed = t.get("edit") or {}
        orig = self._tts_orig(t)
        a = ed.get("a", orig[0]) if a is None else a
        b = ed.get("b", orig[1]) if b is None else b
        cuts = ed.get("cuts", []) if cuts is None else cuts
        ranges, cur = [], a
        for c0, c1 in sorted((max(a, c0), min(b, c1)) for c0, c1 in cuts):
            if c1 <= c0:
                continue
            if c0 > cur:
                ranges.append((cur, c0))
            cur = max(cur, c1)
        if b > cur:
            ranges.append((cur, b))
        return ranges

    def tts_editor_load(self, i):
        st = self._tts()
        t = st["takes"][i] if 0 <= i < len(st["takes"]) else None
        raw = self._tts_raw(t) if t else None
        if not raw or not os.path.exists(raw):
            return {"error": "Нет исходной записи для этого дубля."}
        ed = t.get("edit") or {}
        orig = self._tts_orig(t)
        a, b = ed.get("a", orig[0]), ed.get("b", orig[1])
        total = getattr(self, '_tts_raw_len', None)
        if not total or total[0] != raw or getattr(self, '_tts_rec', None):
            lay = wav_layout(raw)
            length = int(lay[2] / lay[3] * 1000 / lay[4]) if lay else len(AudioSegment.from_file(raw))
            total = self._tts_raw_len = (raw, length)
        lo, hi = max(0, a - EDIT_CONTEXT_MS), min(total[1], b + EDIT_CONTEXT_MS)
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_ctx_{os.getpid()}.wav")
        if wav_slice(raw, tmp, lo, hi):
            seg = AudioSegment.from_file(tmp)
        else:
            seg = AudioSegment.from_file(raw)[lo:hi]
        seg = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        samples = seg.get_array_of_samples()
        per = 16000 * EDIT_BUCKET_MS // 1000
        peaks = [max(abs(min(samples[k:k + per])), max(samples[k:k + per])) / 32768
                 for k in range(0, len(samples), per)]
        # Волна в масштабе (тихая запись не должна выглядеть плоской линией).
        top = max(peaks) if peaks else 0
        k_ = min(40.0, 0.9 / top) if top > 1e-4 else 1.0
        peaks = [round(min(1.0, x * k_), 3) for x in peaks]
        return {"i": i, "lo": lo, "hi": hi, "a": a, "b": b, "cuts": ed.get("cuts", []),
                "orig": orig, "audacity": bool(t.get("audacity")), "peaks": peaks, "bucket": EDIT_BUCKET_MS}

    def tts_editor_apply(self, i, a, b, cuts):
        """Записать правку в файл дубля (из исходника, байт в байт)."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        self._tts_orig(t)
        a, b = int(a), int(b)
        cuts = [[int(c0), int(c1)] for c0, c1 in (cuts or []) if int(c1) > int(c0)]
        if b - a < 100:
            return {"error": "Слишком короткий кусок."}
        ranges = self._tts_take_ranges(t, a, b, cuts)
        dst = os.path.join(st["work_dir"], t["file"])
        if not wav_concat(self._tts_raw(t), dst, ranges):
            src = AudioSegment.from_file(self._tts_raw(t))
            out = sum((src[s:e] for s, e in ranges[1:]), src[ranges[0][0]:ranges[0][1]])
            out.export(dst, format="wav")
        t["edit"] = {"a": a, "b": b, "cuts": cuts}
        t["ms"] = sum(e - s for s, e in ranges)
        t["listened"] = False
        t.pop("audacity", None)
        self._tts_save()
        return self.tts_state()

    def tts_editor_reset(self, i):
        """Вернуть дубль как его нарезала программа."""
        st = self._tts()
        if 0 <= i < len(st["takes"]):
            return self._tts_reset_file(i)
        return self.tts_state()

    def _tts_reset_file(self, i):
        st = self._tts()
        t = st["takes"][i]
        if t.get("clips_orig"):
            # Фраза из кусочков — вернуть клипы, как их разложила программа.
            t["clips"] = [dict(c) for c in t["clips_orig"]]
            self._tts_render_clips(t, t["clips"])
            t["listened"] = False
            t.pop("edit", None)
            t.pop("audacity", None)
            self._tts_save()
            return self.tts_state()
        t.pop("clips", None)
        orig = self._tts_orig(t)
        wav_slice(self._tts_raw(t), os.path.join(st["work_dir"], t["file"]), orig[0], orig[1])
        t["ms"] = orig[1] - orig[0]
        t["listened"] = False
        t.pop("edit", None)
        t.pop("audacity", None)
        self._tts_save()
        return self.tts_state()

    # ---------------- дорожка: клипы (склейка вручную) ----------------
    # Дубль = клипы на дорожке. Клип — кусок исходной записи [a, b] без
    # вырезов cuts, стоящий на дорожке с позиции pos. Клипы идут по порядку;
    # промежуток — тишина; если клип наезжает на предыдущий, хвост
    # предыдущего не звучит. Обычный дубль — один клип.

    def _tts_clips(self, t):
        if t.get("clips"):
            return [dict(c, cuts=[list(x) for x in c.get("cuts", [])]) for c in t["clips"]]
        ed = t.get("edit") or {}
        orig = self._tts_orig(t)
        return [{"raw": self._tts_raw(t), "a": ed.get("a", orig[0]), "b": ed.get("b", orig[1]),
                 "cuts": [list(x) for x in ed.get("cuts", [])], "pos": 0}]

    @staticmethod
    def _clip_ranges(c):
        a, b = int(c["a"]), int(c["b"])
        ranges, cur = [], a
        for c0, c1 in sorted((max(a, int(x)), min(b, int(y))) for x, y in c.get("cuts", [])):
            if c1 <= c0:
                continue
            if c0 > cur:
                ranges.append((cur, c0))
            cur = max(cur, c1)
        if b > cur:
            ranges.append((cur, b))
        return ranges

    def _tts_timeline(self, clips):
        """Клипы → куски для сборки файла [("audio", raw, a, b) | ("silence", ms)]."""
        order = sorted(clips, key=lambda c: c["pos"])
        if not order:
            return []
        base = order[0]["pos"]
        pieces, cursor = [], base
        for k, c in enumerate(order):
            start = c["pos"]
            limit = order[k + 1]["pos"] if k + 1 < len(order) else None
            if start > cursor:
                pieces.append(("silence", start - cursor))
                cursor = start
            room = None if limit is None else max(0, limit - cursor)
            for r0, r1 in self._clip_ranges(c):
                if start < cursor:                       # начало клипа под предыдущим — пропускаем
                    skip = min(r1 - r0, cursor - start)
                    r0, start = r0 + skip, start + skip
                    if r0 >= r1:
                        continue
                ln = r1 - r0
                if room is not None:
                    ln = min(ln, room)
                    room -= ln
                if ln > 0:
                    pieces.append(("audio", c["raw"], r0, r0 + ln))
                    cursor += ln
                    start += ln
                if room is not None and room <= 0:
                    break
        return pieces

    def _tts_render_clips(self, t, clips):
        st = self._tts()
        pieces = self._tts_timeline(clips)
        dst = os.path.join(st["work_dir"], t["file"])
        if not pieces or not wav_render(dst, pieces):
            out = None
            for p in pieces:
                seg = (AudioSegment.from_file(p[1])[p[2]:p[3]] if p[0] == "audio"
                       else AudioSegment.silent(p[1]))
                out = seg if out is None else out + seg
            if out is None:
                raise RuntimeError("пустая дорожка")
            out.export(dst, format="wav")
        t["ms"] = int(sum((p[3] - p[2]) if p[0] == "audio" else p[1] for p in pieces))

    def _tts_raw_length(self, raw):
        lay = wav_layout(raw)
        return int(lay[2] / lay[3] * 1000 / lay[4]) if lay else len(AudioSegment.from_file(raw))

    def tts_clips_load(self, i):
        """Дорожка дубля: клипы с волной (и запасом записи вокруг — край можно вытянуть)."""
        st = self._tts()
        t = st["takes"][i] if 0 <= i < len(st["takes"]) else None
        if not t:
            return {"error": "Нет такого дубля."}
        clips = self._tts_clips(t)
        import tempfile
        out, top = [], 0.0
        for c in clips:
            raw = c["raw"]
            if not raw or not os.path.exists(raw):
                return {"error": "Нет исходной записи для этого дубля."}
            total = self._tts_raw_length(raw)
            lo, hi = max(0, int(c["a"]) - EDIT_CONTEXT_MS), min(total, int(c["b"]) + EDIT_CONTEXT_MS)
            tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_ctx_{os.getpid()}.wav")
            seg = AudioSegment.from_file(tmp) if wav_slice(raw, tmp, lo, hi) else AudioSegment.from_file(raw)[lo:hi]
            seg = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2)
            smp = seg.get_array_of_samples()
            per = 16000 * EDIT_BUCKET_MS // 1000
            peaks = [max(abs(min(smp[k:k + per])), max(smp[k:k + per])) / 32768 for k in range(0, len(smp), per)]
            top = max([top] + peaks)
            out.append(dict(c, lo=lo, hi=hi, peaks=peaks))
        k_ = min(40.0, 0.9 / top) if top > 1e-4 else 1.0         # тихая запись — не плоская линия
        for c in out:
            c["peaks"] = [round(min(1.0, x * k_), 3) for x in c["peaks"]]
        return {"i": i, "clips": out, "bucket": EDIT_BUCKET_MS, "audacity": bool(t.get("audacity")),
                "orig": self._tts_orig(t)}

    def tts_clips_apply(self, i, clips):
        """Записать дорожку в файл дубля (из исходной записи байт в байт).
        Правленый дубль нужно прослушать заново — только потом сохранить."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        allowed = {c["raw"] for c in self._tts_clips(t)} | {self._tts_raw(t)}
        clean = []
        for c in clips or []:
            if c.get("raw") not in allowed:
                return {"error": "Клип не из записи этого дубля."}
            a, b = int(c["a"]), int(c["b"])
            if b - a < 30:
                continue
            clean.append({"raw": c["raw"], "a": a, "b": b, "pos": max(0, int(c.get("pos", 0))),
                          "cuts": [[int(x), int(y)] for x, y in c.get("cuts", []) if int(y) > int(x)]})
        if not clean:
            return {"error": "На дорожке не осталось звука."}
        self._tts_orig(t)
        if not t.get("clips_orig"):
            t["clips_orig"] = self._tts_clips(t)
        self._tts_render_clips(t, clean)
        t["clips"] = clean
        t.pop("edit", None)
        t["listened"] = False
        t.pop("audacity", None)
        self._tts_save()
        return self.tts_state()

    def tts_play_from(self, i, ms):
        """Прослушать дубль с места на дорожке (как сохранится: выровнено, 8 кГц)."""
        st = self._tts()
        self._tts_mark_listened()
        if not (0 <= i < len(st["takes"])):
            return {"playing": False}
        t = st["takes"][i]
        path = os.path.join(st["work_dir"], t["file"])
        if not os.path.exists(path):
            return {"playing": False, "error": "Файл дубля пропал с диска."}
        gain, tempo = self._tts_sound(t)
        prev = self._tts_preview(path, gain, tempo)
        ms = max(0, int(ms))
        total = t.get("ms", 0)
        if ms >= total - 50:
            ms = 0
        # ms — место на дорожке (время записи); в файле с другим темпом оно раньше/позже.
        at = int(ms / tempo)
        import tempfile
        # Свой файл на каждый клик (по кругу из 4): не переписываем тот, что
        # ещё играет или читается.
        self._tts_from_n = (getattr(self, '_tts_from_n', 0) + 1) % 4
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_from_{os.getpid()}_{self._tts_from_n}.wav")
        play = tmp if at > 0 and wav_slice(prev, tmp, at, total / tempo + 1000) else prev
        st["index"] = i
        dur = (total - ms) / 1000.0 / tempo
        self.player.play(play)
        # «Прослушано» засчитываем, только если слушали с начала.
        self._tts_playing = (i, time.time(), dur) if ms < 300 else None
        return {"playing": True, "duration": dur, "from": ms, "tempo": tempo}

    # ---------------- Audacity ----------------

    AUD_FRAG_GAP = 0.3        # пауза между фрагментами на дорожке Audacity, с

    def tts_send_to_audacity(self, i):
        """Дубль — в Audacity (чистый проект, один трек, масштаб по дублю).
        Дубль из нескольких кусков («из записанного» + новая запись) — каждый
        кусок отдельным клипом на одной дорожке, по порядку, с паузой: там их
        удобно двигать, подрезать и склеивать; «Сохранить из Audacity» —
        забрать дорожку целиком и сохранить фразу."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        if not self._ensure_audacity_ready():
            return {"error": "Audacity не отвечает. Откройте его вручную и нажмите ещё раз."}
        t = st["takes"][i]
        clips = sorted(self._tts_clips(t), key=lambda c: c["pos"])
        if len(clips) > 1:
            return self._tts_send_fragments(i, t, clips)
        path = os.path.abspath(os.path.join(st["work_dir"], st["takes"][i]["file"])).replace('\\', '/')
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command(f'Import2: Filename="{path}"')
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SelectNone:')
        self._tts_audacity_take = i
        return {"status": "ok"}

    def _tts_send_fragments(self, i, t, clips):
        import tempfile
        tmpd = os.path.join(tempfile.gettempdir(), f"gvox_frag_{os.getpid()}")
        shutil.rmtree(tmpd, ignore_errors=True)
        os.makedirs(tmpd, exist_ok=True)
        own = t.get("raw")
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')
        pos, names = 0.0, []
        for k, c in enumerate(clips):
            kind = 'новое' if own and os.path.abspath(c["raw"]) == os.path.abspath(own) and t.get("reuse", {}).get("rec") \
                else ('записано' if t.get("reuse") else 'кусок')
            path = os.path.join(tmpd, f"{k + 1:02d}_{kind}.wav")
            pieces = self._tts_timeline([dict(c, pos=0)])
            if not wav_render(path, pieces):
                seg = AudioSegment.empty()
                for p in pieces:
                    seg += AudioSegment.from_file(p[1])[p[2]:p[3]] if p[0] == "audio" else AudioSegment.silent(p[1])
                seg.export(path, format="wav")
            ln = self._import_clip_to_track0(path, pos)
            names.append(os.path.basename(path)[:-4])
            pos += (ln or 0) + self.AUD_FRAG_GAP
        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={pos + 0.5} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SelectNone:')
        self._tts_audacity_take = i
        return {"status": "ok", "fragments": names}

    def tts_save_from_audacity(self, i):
        """«Сохранить из Audacity»: забрать дорожку (как склеили там) в дубль
        и сразу сохранить фразу."""
        r = self.tts_take_from_audacity(i)
        if r.get("error"):
            return r
        return self.tts_approve(i)

    def tts_take_from_audacity(self, i):
        """Забрать правку из Audacity в файл дубля — в формате исходной записи."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        if getattr(self, '_tts_audacity_take', None) != i:
            return {"error": "В Audacity сейчас другой дубль — сначала отправьте этот."}
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_aud_{os.getpid()}.wav").replace('\\', '/')
        if os.path.exists(tmp):
            os.remove(tmp)
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command(f'Export2: Filename="{tmp}" NumChannels=1')
        for _ in range(30):
            if os.path.exists(tmp) and os.path.getsize(tmp) > 44:
                break
            time.sleep(0.1)
        else:
            return {"error": "Audacity не сохранил файл."}
        time.sleep(0.2)
        t = st["takes"][i]
        dst = os.path.join(st["work_dir"], t["file"])
        seg = AudioSegment.from_file(tmp)
        like = self._tts_clips(t)[0]["raw"] if t.get("clips") else self._tts_raw(t)
        export_like(seg, dst, like)
        if t.get("clips"):                   # склеено в Audacity — исходник дубля теперь эта склейка
            src = os.path.join(st["work_dir"], TTS_RECORDS_DIR, f"Audacity_{t.get('chunk', i)}_{int(time.time())}.wav")
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.copy2(dst, src)
            for k in ("clips", "clips_orig", "stitched", "edit"):
                t.pop(k, None)
            t["raw"], t["orig"], t["start_ms"] = src, [0, len(seg)], 0
        t["ms"] = len(seg)
        t["listened"] = False
        t["audacity"] = True
        self._tts_save()
        return self.tts_state()

    # ---------------- экран «Переменные» ----------------
    # Значения переменных лежат в «Значения/<лист>/<категория>/<значение>.wav»
    # (лист — <sum_ru>, категория — <million_ru> и т.д.). У каждого значения —
    # текст для синтеза («пять миллионов»), его можно поправить руками.

    def _tts_value_dir(self, sheet, cat):
        return os.path.join(self._tts()["work_dir"] or '', TTS_VALUES_DIR, sheet, cat)

    def _tts_value_file(self, sheet, cat, value):
        return os.path.join(self._tts_value_dir(sheet, cat), f"{clean_name(value)}.wav")

    def _tts_value_text(self, sheet, cat, value):
        custom = (self._tts().get("var_texts") or {}).get(f"{sheet}|{cat}|{value}")
        return custom or synth_text(cat, value), bool(custom)

    # ---------------- запись значений переменных голосом ----------------
    # Каждое значение листа переменных — «фраза» для суфлёра (kind 'value'):
    # текст — как на экране «Переменные» («пять миллионов», «первого»),
    # файл — «Значения/<лист>/<категория>/<значение>.wav». Порядок — как в
    # таблице: строка за строкой, в строке слева направо.

    # Лист сумм читается целыми суммами (как в «Синтезе сумм»): строка k —
    # каждый ярус берёт своё k-е значение (дошедший до конца — остаётся на
    # последнем). Логика 1: миллионы + сотни + тысячи + тенге (1 101 001),
    # логика 2: миллионы + сотни тысяч + тенге (1 100 001). Сохраняются
    # ярусы — см. «Конвейер» ниже.
    SUM_LOGICS = {1: ('million', 'hundred', 'thousand', 'tenge'), 2: ('million', 'hundred_thousand', 'tenge')}

    @staticmethod
    def _tts_is_sum_sheet(sh):
        bases = {re.sub(r'_(ru|kz|kk)$', '', c["key"]) for c in sh["categories"]}
        return {'million', 'tenge'} <= bases

    def _tts_sum_row_parts(self, sh, logic):
        """Строки суммы по ярусам: [{ярус: (ключ категории, значение из таблицы, число)}]."""
        tiers = self.SUM_LOGICS.get(int(logic), self.SUM_LOGICS[1])
        by_base = {re.sub(r'_(ru|kz|kk)$', '', c["key"]): c for c in sh["categories"]}
        cols = []
        for t in tiers:
            c = by_base.get(t)
            vals = [(re.sub(r'\D', '', v), int(re.sub(r'\D', '', v))) for v in (c or {}).get("values", [])
                    if re.sub(r'\D', '', v)]
            if vals:
                cols.append((t, c["key"], vals))
        if not cols:
            return []
        return [{t: (ck, *v[min(k, len(v) - 1)]) for t, ck, v in cols}
                for k in range(max(len(v) for _t, _c, v in cols))]

    @staticmethod
    def _tts_sum_number(parts):
        g = lambda t: parts[t][2] if t in parts else 0
        return g('million') * 1_000_000 + (g('hundred') + g('hundred_thousand') + g('thousand')) * 1000 + g('tenge')

    def _tts_sum_rows(self, sh, logic):
        return [self._tts_sum_number(p) for p in self._tts_sum_row_parts(sh, logic)]

    def _tts_sum_dir(self, key):
        lm = re.search(r'_(ru|kz|kk)$', key)
        lg = ('KZ' if lm.group(1) in ('kz', 'kk') else 'RU') if lm else 'RU'
        return os.path.join(self._tts()["work_dir"] or '', f"Запись_суммы_{lg}")

    def tts_sum_logic(self, logic):
        st = self._tts()
        st["sum_logic"] = 2 if int(logic) == 2 else 1
        self._tts_ensure_value_units()
        if hasattr(self, '_tts_prompt_fix'):
            self._tts_prompt_fix(0)
        self._tts_save()
        return {"prompt": self.tts_prompt_info() if hasattr(self, 'tts_prompt_info') else None,
                "state": self.tts_state()}

    # Конвейер «один раз — и готово»: читается строка целиком («один миллион
    # сто одна тысяча один тенге», «первого января»), в «Сборке» дубль сам
    # размечается на ярусы, Enter сохраняет каждый ярус сразу финальным
    # эталоном — суммы в «Проверенные/Суммы/<ярус>/» (их берёт режим
    # «Суммы»), даты — в «Значения/<лист>/<категория>/». Целиком строка не
    # сохраняется. Уже готовые ярусы не перезаписываются, строка, где готово
    # всё, — пропускается.
    SUM_TIER_DIRS = {'million': '1 - 100 млн', 'hundred_thousand': '100 - 900 тыс', 'hundred': '100 - 900',
                     'thousand': '1 - 99 тыс', 'tenge': '1 - 100 тенге'}
    SUM_TIER_LABELS = {'million': 'Миллионы', 'hundred_thousand': 'Сотни тысяч', 'hundred': 'Сотни',
                       'thousand': 'Тысячи', 'tenge': 'Тенге'}

    def _tts_sum_piece(self, tier, n, lang):
        from core.num_words import kz_words, ru_words
        w = kz_words if lang == 'kz' else ru_words
        mult = {'million': 1_000_000, 'hundred_thousand': 1000, 'thousand': 1000}.get(tier, 1)
        text = w(n * mult)
        return f"{text} {'теңге' if lang == 'kz' else 'тенге'}" if tier == 'tenge' else text

    def _tts_tier_path(self, unit, tier):
        """Эталон яруса — в едином формате «Значения/<лист>/<категория>/<значение>.wav»
        (суммы тоже: «Значения/sum_ru/million_ru/5.wav»)."""
        if str(unit.get("cat", '')).startswith('sum_l'):
            return self._tts_value_file(unit["sheet"], tier["cat"], self._tts_sum_raw_value(unit["sheet"], tier["cat"], tier["value"]))
        return self._tts_value_file(unit["sheet"], tier["cat"], tier["value"])

    def _tts_sum_raw_value(self, sheet, cat, digits):
        """Значение суммы — как в таблице (имя файла то же, что на экране «Переменные»)."""
        sh = (self._tts().get("var_sheets") or {}).get(sheet) or {}
        c = next((c for c in sh.get("categories", []) if c["key"] == cat), None)
        return next((v for v in (c or {}).get("values", []) if re.sub(r'\D', '', str(v)) == str(digits)), digits)

    def _tts_old_sum_path(self, unit, tier):
        """Где эталон лежал раньше: «Проверенные/Суммы/<ярус по-русски>/<цифры>.wav»."""
        return os.path.join(self._tts()["work_dir"] or '', TTS_DONE_DIR, 'Суммы',
                            self.SUM_TIER_DIRS.get(tier["tier"], tier["tier"]), f"{tier['value']}.wav")

    def _tts_migrate_values(self):
        """Перенос эталонов сумм из старого формата в «Значения/…» (один раз на проект)."""
        st = self._tts()
        wd = st.get("work_dir")
        if not wd or st.get("values_layout") == 2:
            return 0
        moved = {}
        for u in st["units"]:
            if not (u.get("tiers") and str(u.get("cat", '')).startswith('sum_l')):
                continue
            for t in u["tiers"]:
                old, new = self._tts_old_sum_path(u, t), self._tts_tier_path(u, t)
                if old in moved or not os.path.exists(old) or os.path.exists(new):
                    continue
                try:
                    os.makedirs(os.path.dirname(new), exist_ok=True)
                    shutil.move(old, new)
                    moved[old] = new
                except OSError:
                    pass
        sheet = next((k for k in (st.get("var_sheets") or {}) if str(k).lower().startswith('sum_')), None)
        if hasattr(self, '_values_migrate'):              # остальное из «Проверенные/Суммы» — по названиям папок
            moved.update(self._values_migrate(wd, sheet))
        if moved:
            for t in st.get("takes") or []:
                if t.get("tier_files"):
                    t["tier_files"] = [moved.get(p, p) for p in t["tier_files"]]
        st["values_layout"] = 2
        self._tts_save()
        return len(moved)

    def _tts_row_units(self, sheet=None):
        return [u for u in self._tts()["units"] if u.get("tiers") and (sheet is None or u.get("sheet") == sheet)]

    def _tts_ensure_value_units(self):
        st = self._tts()
        have = {(u.get("sheet"), u.get("cat"), u.get("value")): u for u in st["units"] if u["kind"] == "value"}
        changed = False

        def put(key, cat, value, fields):
            nonlocal changed
            u = have.get((key, cat, value))
            if u:
                for f in ("text", "tiers", "name", "row"):
                    if u.get(f) != fields[f]:
                        u[f] = fields[f]
                        changed = True
                return
            st["units"].append({"id": len(st["units"]), "kind": "value", "role": None, "vars": [],
                                "var_before": None, "var_after": None, "chain": None, "sheet": key,
                                "cat": cat, "value": value, **fields})
            have[(key, cat, value)] = st["units"][-1]
            changed = True
        for key, sh in (st.get("var_sheets") or {}).items():
            lm = re.search(r'_(ru|kz|kk)$', key)
            lang = ('kz' if lm.group(1) in ('kz', 'kk') else 'ru') if lm else None
            if self._tts_is_sum_sheet(sh):
                for logic in (1, 2):
                    for k, parts in enumerate(self._tts_sum_row_parts(sh, logic)):
                        n = self._tts_sum_number(parts)
                        tiers = [{"tier": t, "cat": ck, "value": raw, "label": self.SUM_TIER_LABELS.get(t, t),
                                  "text": self._tts_sum_piece(t, num, lang)}
                                 for t in self.SUM_LOGICS[logic] if t in parts for ck, raw, num in [parts[t]]]
                        put(key, f"sum_l{logic}", str(n),
                            {"name": f"{k + 1:04d}_{n}", "text": ' '.join(x["text"] for x in tiers),
                             "row": f"{key}:sum{logic}:{k}", "tiers": tiers, "lang": lang, "logic": logic,
                             "cat_label": f"Сумма · логика {logic}"})
                continue
            order = sh.get("order") or [[c["key"], v, 0] for c in sh["categories"] for v in c["values"]]
            for cat, v, row in order:              # отдельные значения (экран «Переменные», старые дубли)
                text = self._tts_value_text(key, cat, v)[0]
                put(key, cat, v, {"name": clean_name(v), "text": text, "row": f"{key}:{row}:{cat}", "tiers": None,
                                  "lang": lang, "cat_label": var_label(cat)})
            cats = [c for c in sh["categories"] if c["values"]]
            for k in range(max((len(c["values"]) for c in cats), default=0)):
                tiers = []
                for c in cats:
                    v = c["values"][min(k, len(c["values"]) - 1)]
                    tiers.append({"tier": c["key"], "cat": c["key"], "value": v, "label": var_label(c["key"]),
                                  "text": self._tts_value_text(key, c["key"], v)[0]})
                put(key, "rows", str(k), {"name": f"{k + 1:04d}_" + '_'.join(clean_name(x["value"]) for x in tiers),
                                          "text": ' '.join(x["text"] for x in tiers), "row": f"{key}:rows:{k}",
                                          "tiers": tiers, "lang": lang, "cat_label": "Строка таблицы"})
        if changed:
            self._tts_save()
        if st.get("work_dir") and st.get("values_layout") != 2:
            self._tts_migrate_values()

    def _tts_tier_claims(self, sheet, logic):
        """Какая строка «отвечает» за каждый ещё не готовый эталон яруса —
        первая по порядку, где он встречается. Остальные строки с тем же
        значением его не дают — читать их незачем (например, в логике 2
        после логики 1 нужны только строки с новыми «сотнями тысяч»)."""
        cache = self.__dict__.setdefault('_tts_claims_cache', {})
        key = (sheet, logic)
        if key not in cache:
            claims, missing = {}, {}
            for u in self._tts_row_units(sheet):
                if u.get("logic") != logic:
                    continue
                miss = [p for p in (self._tts_tier_path(u, t) for t in u["tiers"]) if not os.path.exists(p)]
                missing[u["id"]] = miss
                for p in miss:
                    claims.setdefault(p, u["id"])
            cache[key] = (claims, missing)
        return cache[key]

    def _tts_tier_row_needed(self, u):
        claims, missing = self._tts_tier_claims(u.get("sheet"), u.get("logic"))
        return any(claims.get(p) == u["id"] for p in missing.get(u["id"], ()))

    def _tts_tiers_done(self, sheet):
        """Сколько эталонов ярусов листа уже готово (уникальные файлы)."""
        paths = {self._tts_tier_path(u, t) for u in self._tts_row_units(sheet)
                 if not (u.get("logic") and u["logic"] != self._tts().get("sum_logic", 1)) for t in u["tiers"]}
        return sum(1 for p in paths if os.path.exists(p)), len(paths)

    # ---- разметка ярусов в дубле строки ----
    TIER_FRAME_MS = 10
    TIER_SNAP_MS = 120        # граница ищет самую тихую точку в ± стольких мс
    TIER_PAD_MS = 60          # тишины по краям каждого яруса

    def _tts_take_frames(self, t):
        """RMS дубля по кадрам 10 мс + длина в мс."""
        path = os.path.join(self._tts()["work_dir"], t["file"])
        if not os.path.exists(path):
            raise FileNotFoundError(f"Файл дубля не найден: {t['file']} — перезапишите строку или удалите дубль (Del).")
        return self._tts_cached(('frames',) + self._file_sig(path), lambda: self._tts_file_rms(path, cache=False))

    def _tts_tier_auto(self, unit, rms, length):
        """Границы ярусов: ожидаемое место — по доле букв внутри звучащей
        части; граница ставится в ближайшую паузу (по порядку, без пропусков
        назад), нет паузы рядом — в самую тихую точку."""
        tiers = unit["tiers"]
        if len(tiers) < 2 or not len(rms):
            return []
        f = self.TIER_FRAME_MS
        thr = max(float(rms.max()) * 0.08, 1e-4)
        voiced = np.nonzero(rms > thr)[0]
        v0, v1 = (int(voiced[0]) * f, int(voiced[-1] + 1) * f) if len(voiced) else (0, length)
        chars = [max(1, len(re.sub(r'\W', '', x["text"]))) for x in tiers]
        total, acc, guess = sum(chars), 0, []
        for c in chars[:-1]:
            acc += c
            guess.append(v0 + (v1 - v0) * acc / total)
        # паузы внутри речи: тихие отрезки от 40 мс
        quiet = rms <= thr
        pauses, k = [], int(voiced[0]) if len(voiced) else 0
        end = int(voiced[-1]) if len(voiced) else len(rms) - 1
        while k <= end:
            if quiet[k]:
                j = k
                while j <= end and quiet[j]:
                    j += 1
                if (j - k) * f >= 40:
                    pauses.append((k + j) * f / 2)
                k = j
            else:
                k += 1
        # по порядку: каждой границе — своя пауза или «нет паузы» (штраф)
        n, m, miss = len(guess), len(pauses), max(250.0, (v1 - v0) * 0.25)
        # выравнивание как у строк: пауза пропущена / граница без паузы / граница в паузе
        best = [[0.0] * (m + 1) for _ in range(n + 1)]
        how = [[None] * (m + 1) for _ in range(n + 1)]
        for gi in range(n + 1):
            for pj in range(m + 1):
                if gi == 0 and pj == 0:
                    continue
                opts = []
                if pj > 0:
                    opts.append((best[gi][pj - 1], 'skip'))
                if gi > 0:
                    opts.append((best[gi - 1][pj] + miss, 'miss'))
                if gi > 0 and pj > 0:
                    opts.append((best[gi - 1][pj - 1] + abs(pauses[pj - 1] - guess[gi - 1]), 'use'))
                best[gi][pj], how[gi][pj] = min(opts, key=lambda o: o[0])
        chosen, gi, pj = [None] * n, n, m
        while gi > 0:
            op = how[gi][pj]
            if op == 'skip':
                pj -= 1
                continue
            if op == 'use':
                chosen[gi - 1] = pauses[pj - 1]
                pj -= 1
            gi -= 1
        cuts = []
        for gi, c in enumerate(chosen):
            if c is None:
                lo = max(int((guess[gi] - self.TIER_SNAP_MS) / f), (cuts[-1] // f + 3) if cuts else 1)
                hi = min(int((guess[gi] + self.TIER_SNAP_MS) / f), len(rms) - 2)
                kk = lo + int(np.argmin(rms[lo:hi + 1])) if hi >= lo else int(guess[gi] / f)
                c = kk * f + f // 2
            cuts.append(int(max(c, cuts[-1] + 3 * f) if cuts else c))
        return cuts

    # ---- клипы ярусов ----
    # У каждого яруса: a–b (мс в дубле), pre — пауза перед ним (заполняется
    # фоном фразы), tempo — свой темп, gain — своя громкость (± к выровненной).
    # Шаблон листа (первая сохранённая строка или «Шаблон из этой строки»):
    # сколько тишины оставлять до/после голоса, паузы, темп, громкость —
    # следующие строки режутся по нему сами.
    TIER_TEMPO = (0.80, 1.25)
    TIER_GAIN = (-9.0, 9.0)

    def _tts_tier_tpl_key(self, unit):
        return f"{unit.get('sheet')}:{unit.get('logic') or 0}"

    def _tts_tier_tpl(self, unit):
        return (self._tts().get("tier_tpl") or {}).get(self._tts_tier_tpl_key(unit))

    def _tts_voice_span(self, rms, a, b, thr):
        f = self.TIER_FRAME_MS
        v = np.nonzero(rms[a // f:max(a // f + 1, b // f)] > thr)[0]
        return (a + int(v[0]) * f, min(b, a + int(v[-1] + 1) * f)) if len(v) else (a, b)

    def _tts_tier_clips(self, t, unit):
        """Клипы ярусов дубля. Сначала — сами: границы в паузы, края — по
        голосу (с запасом тишины из шаблона, нет шаблона — TIER_PAD_MS)."""
        rms, length = self._tts_take_frames(t)
        n = len(unit["tiers"])
        clips = t.get("tier_clips")
        if clips and len(clips) == n and t.get("tier_len") == length:
            return clips, length, rms
        cuts = self._tts_tier_auto(unit, rms, length)
        bounds = [0] + list(cuts) + [length]
        thr = max(float(rms.max()) * 0.05, 1e-4) if len(rms) else 1
        spans = [self._tts_voice_span(rms, bounds[k], bounds[k + 1], thr) for k in range(n)]
        tpl = self._tts_tier_tpl(unit)
        clips = []
        for k, x in enumerate(unit["tiers"]):
            p = (tpl or {}).get("tiers", {}).get(x["tier"]) or {}
            lead, tail = p.get("lead", self.TIER_PAD_MS), p.get("tail", self.TIER_PAD_MS)
            v0, v1 = spans[k]
            lo = spans[k - 1][1] if k > 0 else 0                      # не залезать в голос соседа
            hi = spans[k + 1][0] if k < n - 1 else length
            a, b = max(lo, v0 - lead), min(hi, v1 + tail)
            clips.append({"a": int(a), "b": int(max(b, a + 40)), "pre": int(p.get("pre", 0)), "post": int(p.get("post", 0)),
                          "tempo": float(p.get("tempo", 1.0)), "gain": float(p.get("gain", 0.0))})
        t["tier_clips"], t["tier_len"] = clips, length
        t["tier_by_tpl"] = bool(tpl)
        t.pop("tier_cuts", None)
        return clips, length, rms

    def tts_tier_template(self, i):
        """«Шаблон из этой строки»: тайминг, паузы, темп, громкость ярусов
        этого дубля — для следующих строк листа."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])) or st["takes"][i].get("unit") is None:
            return {"tiers": None}
        t = st["takes"][i]
        unit = st["units"][t["unit"]]
        if not unit.get("tiers"):
            return {"tiers": None}
        self._tts_tier_tpl_from(t, unit)
        self._tts_save()
        return self.tts_tier_marks(i)

    def _tts_tier_tpl_from(self, t, unit):
        clips, _length, rms = self._tts_tier_clips(t, unit)
        thr = max(float(rms.max()) * 0.05, 1e-4) if len(rms) else 1
        tiers = {}
        for x, c in zip(unit["tiers"], clips):
            v0, v1 = self._tts_voice_span(rms, c["a"], c["b"], thr)
            tiers[x["tier"]] = {"lead": max(0, v0 - c["a"]), "tail": max(0, c["b"] - v1), "pre": c.get("pre", 0),
                                "post": c.get("post", 0),
                                "tempo": c.get("tempo", 1.0), "gain": c.get("gain", 0.0)}
        tpls = self._tts().setdefault("tier_tpl", {})
        old = tpls.get(self._tts_tier_tpl_key(unit)) or {}
        tpls[self._tts_tier_tpl_key(unit)] = {"from": unit["name"], "tiers": tiers, "auto": bool(old.get("auto"))}

    def tts_tier_template_reset(self, i):
        """Разметить этот дубль заново (по шаблону, если он есть)."""
        st = self._tts()
        if 0 <= i < len(st["takes"]):
            st["takes"][i].pop("tier_clips", None)
            self._tts_save()
        return self.tts_tier_marks(i)

    def tts_tier_auto(self, on):
        """«Сохранять по шаблону сразу»: записали строку — ярусы сохранились сами."""
        st = self._tts()
        mode = st.get("prompt_mode", "phrases")
        unit = next((u for u in self._tts_row_units(mode) if u.get("logic") in (None, st.get("sum_logic", 1))), None)
        if not unit:
            return {"error": "Сначала выберите лист переменных."}
        tpl = self._tts_tier_tpl(unit)
        if not tpl:
            return {"error": "Сначала сохраните одну строку — она станет шаблоном."}
        tpl["auto"] = bool(on)
        self._tts_save()
        return {"auto": tpl["auto"], "prompt": self.tts_prompt_info() if hasattr(self, 'tts_prompt_info') else None}

    def _tts_tier_autosave(self, t):
        """Новый дубль строки при включённом «по шаблону сразу» — сохранить ярусы."""
        st = self._tts()
        unit = st["units"][t["unit"]] if t.get("unit") is not None else None
        if not unit or not unit.get("tiers") or not st.get("work_dir"):
            return None
        tpl = self._tts_tier_tpl(unit)
        if not tpl or not tpl.get("auto"):
            return None
        try:
            written, skipped = self._tts_tier_save(t, unit)
        except Exception:
            return None
        for other in st["takes"]:
            if other.get("unit") == t["unit"] and other is not t:
                other["approved"] = False
        t["approved"], t["auto_tier"] = True, True
        return written

    # ---- начало/продолжение фразы рядом с ярусами ----
    TIER_CTX_MS = 2500        # сколько начала/продолжения фразы показывать и играть рядом

    # ---- кэш: прочитанные файлы, громкость, готовые ярусы ----
    # Ключ — всё, от чего зависит звук (файл и время его изменения, границы,
    # паузы, темп, громкость, шум, фон): изменилось что-то одно — пересчитается
    # только это, остальное берётся готовым. В памяти — не больше TTS_CACHE_MB,
    # громкость файлов — ещё и на диске (_Кэш/), чтобы после перезапуска не
    # мерить заново. Папку _Кэш можно удалить в любой момент.
    TTS_CACHE_MB = 200
    TTS_CACHE_DIR = '_Кэш'

    @staticmethod
    def _file_sig(path):
        s = os.stat(path)
        return (os.path.abspath(path), s.st_mtime_ns, s.st_size)

    def _tts_cached(self, key, make):
        """LRU в памяти: make() — только если такого ещё не считали."""
        import collections
        lock = self.__dict__.setdefault('_tts_mem_lock', threading.RLock())
        with lock:
            mem = self.__dict__.setdefault('_tts_mem', collections.OrderedDict())
            if key in mem:
                mem.move_to_end(key)
                return mem[key][0]
        val = make()
        size = self._tts_nbytes(val)
        with lock:
            mem[key] = (val, size)
            total = self.__dict__.get('_tts_mem_bytes', 0) + size
            while total > self.TTS_CACHE_MB * 2 ** 20 and len(mem) > 1:
                _k, (_v, sz) = mem.popitem(last=False)
                total -= sz
            self._tts_mem_bytes = total
        return val

    @staticmethod
    def _tts_nbytes(v):
        if isinstance(v, AudioSegment):
            return len(v.raw_data)
        if isinstance(v, np.ndarray):
            return v.nbytes
        if isinstance(v, (tuple, list)):
            return sum(TtsFlowMixin._tts_nbytes(x) for x in v)
        return 64

    def _tts_seg(self, path):
        """Файл → моно AudioSegment (читается один раз, пока файл не изменится)."""
        return self._tts_cached(('seg',) + self._file_sig(path), lambda: AudioSegment.from_file(path).set_channels(1))

    def _tts_disk(self):
        """Замеры громкости на диске: {ключ: дБ}."""
        wd = self._tts().get("work_dir")
        d = self.__dict__.get('_tts_disk_cache')
        if d is None or d.get("wd") != wd:
            data = {}
            try:
                with open(os.path.join(wd, self.TTS_CACHE_DIR, 'громкость.json'), encoding='utf-8') as f:
                    data = json.load(f)
            except (OSError, ValueError, TypeError):
                pass
            d = self._tts_disk_cache = {"wd": wd, "data": data if isinstance(data, dict) else {}, "dirty": False}
        return d

    def _tts_disk_key(self, path, extra):
        _p, mt, sz = self._file_sig(path)
        wd = self._tts().get("work_dir") or ''
        try:
            rel = os.path.relpath(path, wd)
        except ValueError:
            rel = path
        return f"{rel}|{mt}|{sz}|{extra}"

    def _tts_disk_level(self, path, extra, make):
        d = self._tts_disk()
        key = self._tts_disk_key(path, extra)
        if key not in d["data"]:
            d["data"][key] = make()
            d["dirty"] = True
        return d["data"][key]

    def _tts_disk_flush(self):
        d = self.__dict__.get('_tts_disk_cache')
        if not d or not d.get("dirty") or not d.get("wd") or not os.path.isdir(d["wd"]):
            return
        try:
            folder = os.path.join(d["wd"], self.TTS_CACHE_DIR)
            os.makedirs(folder, exist_ok=True)
            tmp = os.path.join(folder, 'громкость.json.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d["data"], f, ensure_ascii=False)
            os.replace(tmp, os.path.join(folder, 'громкость.json'))
            d["dirty"] = False
        except OSError:
            pass

    def _tts_timed(self, name, fn):
        """Сколько заняла операция — в _Кэш/замеры.txt (от 30 мс), чтобы
        видеть, что на самом деле тормозит на этом компьютере."""
        t0 = time.perf_counter()
        try:
            return fn()
        finally:
            ms = (time.perf_counter() - t0) * 1000
            wd = self._tts().get("work_dir") if getattr(self, 'tts', None) else None
            if ms >= 30 and wd and os.path.isdir(wd):
                try:
                    folder = os.path.join(wd, self.TTS_CACHE_DIR)
                    os.makedirs(folder, exist_ok=True)
                    with open(os.path.join(folder, 'замеры.txt'), 'a', encoding='utf-8') as f:
                        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{name}\t{ms:.0f} мс\n")
                except OSError:
                    pass

    def _tts_tier_ctx(self, unit):
        """Выбранная фраза вокруг суммы: (файл начала, True, имя), (файл конца, False, имя)."""
        ch, _p, _n = self._tts_tier_chain(unit)
        if not ch:
            return None, None
        return ((ch["start_path"], True, ch["start_name"]) if ch["start_path"] else None,
                (ch["end_path"], False, ch["end_from"] or ch["end_name"]) if ch["end_path"] else None)

    def _tts_tier_opts(self):
        return {"noise": True, "level": True, **(self._tts().get("tier_opts") or {})}

    # ---- громкость «на слух» (как LUFS: K-фильтр + отсечка тишины) ----
    # Сумма должна звучать так же, как фраза в месте стыка: в конце фразы
    # голос обычно тише, чем в её начале, — поэтому меряем не всю фразу, а
    # полторы секунды голоса у самого стыка (конец начала, начало продолжения),
    # медиана по всем фразам с этой переменной. Вся строка получает одну
    # поправку — ярусы между собой звучат как записаны.
    TIER_JOIN_MS = 1500

    @staticmethod
    def _k_weight(x, rate):
        """K-фильтр (как в LUFS): полка +4 дБ выше 1,5 кГц и срез ниже 38 Гц.
        Для замера громкости хватает АЧХ — применяем её в спектре (быстро)."""
        import math
        n = len(x)
        f = np.fft.rfftfreq(n, 1 / rate)
        z = np.exp(-1j * 2 * np.pi * f / rate)

        def resp(b, a):
            return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))
        w0 = 2 * math.pi * 1500 / rate
        A, c = 10 ** (4 / 40), math.cos(w0)
        sa = 2 * math.sqrt(A) * math.sin(w0) / (2 / math.sqrt(2))
        h = resp((A * ((A + 1) + (A - 1) * c + sa), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sa)),
                 ((A + 1) - (A - 1) * c + sa, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sa))
        w0 = 2 * math.pi * 38 / rate
        al, c = math.sin(w0) / (2 * 0.5), math.cos(w0)
        h = h * resp(((1 + c) / 2, -(1 + c), (1 + c) / 2), (1 + al, -2 * c, 1 - al))
        return np.fft.irfft(np.fft.rfft(x) * h, n)

    @classmethod
    def _loudness(cls, seg):
        """Громкость голоса на слух, дБ (LUFS-подобно); None — тишина."""
        seg = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        x = np.frombuffer(seg.raw_data, dtype='<i2').astype(np.float64) / 32768
        if len(x) < 1600:
            return None
        y = cls._k_weight(x, 16000)
        blk, hop = 1600, 400                                        # окна 100 мс, шаг 25 мс
        ms = np.array([np.mean(y[k:k + blk] ** 2) for k in range(0, len(y) - blk + 1, hop)])
        ms = ms[ms > 10 ** ((-70 + 0.691) / 10)]
        if not len(ms):
            return None
        ms = ms[ms > np.mean(ms) * 10 ** (-10 / 10)]                # без пауз и хвостов
        return round(-0.691 + 10 * np.log10(np.mean(ms)), 1) if len(ms) else None

    def _tts_join_loud(self, path, tail):
        """Громкость голоса у стыка: последние (tail) / первые полторы секунды речи."""
        cache = self.__dict__.setdefault('_tts_lvl_cache', {})
        key = (path, os.path.getmtime(path), tail)
        if key not in cache:
            cache[key] = self._tts_disk_level(path, f"join{int(bool(tail))}", lambda: self._tts_join_loud_calc(path, tail))
        return cache[key]

    def _tts_join_loud_calc(self, path, tail):
        """Громкость голоса у стыка — сам замер (без кэша)."""
        seg = self._tts_seg(path).set_sample_width(2)
        xs = np.frombuffer(seg.raw_data, dtype='<i2').astype(np.float32) / 32768
        fr = max(1, seg.frame_rate // 100)                       # кадры 10 мс
        e = np.sqrt((xs[:len(xs) // fr * fr].reshape(-1, fr) ** 2).mean(axis=1)) if len(xs) >= fr else np.zeros(0)
        v = np.nonzero(e > max(float(e.max()) * 0.1, 1e-4))[0] if len(e) else []
        if len(v):
            v0, v1 = int(v[0]) * 10, int(v[-1] + 1) * 10
            seg = seg[max(v0, v1 - self.TIER_JOIN_MS):v1] if tail else seg[v0:min(v1, v0 + self.TIER_JOIN_MS)]
        return self._loudness(seg)

    def _tts_ctx_level(self, unit):
        """Целевая громкость ярусов листа: медиана громкости у стыков всех
        записанных фраз с этой переменной."""
        lv = []
        for ch in self._tts_var_chains(unit.get("sheet")):
            for path, tail in ((ch["start_path"], True), (ch["own_end_path"], False)):
                if path:
                    v = self._tts_join_loud(path, tail)
                    if v is not None:
                        lv.append(v)
        return round(float(np.median(lv)), 1) if lv else None

    def _tts_row_loud(self, t, unit):
        """Громкость голоса всей строки дубля (все клипы ярусов подряд)."""
        clips, _l, _r = self._tts_tier_clips(t, unit)
        path = os.path.join(self._tts()["work_dir"], t["file"])
        key = ('row', path, os.path.getmtime(path), tuple((c["a"], c["b"]) for c in clips))
        cache = self.__dict__.setdefault('_tts_lvl_cache', {})
        if key not in cache:
            def calc():
                src = self._tts_seg(path)
                seg = AudioSegment.empty().set_frame_rate(src.frame_rate)
                for c in clips:
                    seg += src[c["a"]:c["b"]]
                return self._loudness(seg)
            cache[key] = self._tts_disk_level(path, "row" + ",".join(f"{c['a']}-{c['b']}" for c in clips), calc)
        return cache[key]

    # ---- фразы с этой переменной: по очереди, с началом и концом ----
    def _tts_var_chains(self, sheet):
        """Все фразы, где стоит переменная листа: начало (кусочек перед ней) и
        продолжение. Нет своего записанного продолжения — берётся из
        ближайшей прошлой готовой фразы (нет прошлых — из следующей)."""
        st = self._tts()
        wd = st.get("work_dir")
        saved = lambda u: bool(u and wd and os.path.exists(self._tts_target(u)))
        out = []
        for ch in st.get("chains") or []:
            parts = [st["units"][i] for i in ch["parts"]]
            for k, u in enumerate(parts):
                if u.get("var_after") != sheet:
                    continue
                nxt = parts[k + 1] if k + 1 < len(parts) else None
                out.append({"chain": ch["id"], "name": ch.get("name") or u["name"], "start": u["id"], "start_name": u["name"],
                            "start_text": u["text"], "start_path": self._tts_target(u) if saved(u) else None,
                            "end": nxt["id"] if nxt else None, "end_name": nxt["name"] if nxt else None,
                            "end_text": nxt["text"] if nxt else '', "own_end_path": self._tts_target(nxt) if saved(nxt) else None})
        last = None
        for c in out:                                      # конец — из прошлой готовой фразы
            if c["own_end_path"]:
                last = c
            c["end_path"], c["end_from"] = (c["own_end_path"], None) if c["own_end_path"] else \
                ((last["own_end_path"], last["end_name"]) if last else (None, None))
        nxt_ready = None
        for c in reversed(out):                            # прошлых нет — из следующей
            if c["own_end_path"]:
                nxt_ready = c
            elif not c["end_path"] and nxt_ready:
                c["end_path"], c["end_from"] = nxt_ready["own_end_path"], nxt_ready["end_name"]
        return out

    def _tts_tier_chain(self, unit):
        chains = self._tts_var_chains(unit.get("sheet"))
        if not chains:
            return None, 0, 0
        pos_by = self._tts().setdefault("tier_ctx_pos", {})
        pos = pos_by.get(unit.get("sheet"))
        if pos is None:                                    # сначала — первая фраза, где записано начало
            pos = next((k for k, c in enumerate(chains) if c["start_path"]), 0)
        pos = max(0, min(int(pos), len(chains) - 1))
        return chains[pos], pos, len(chains)

    def tts_tier_ctx_nav(self, i, delta=0, pos=None):
        """◀ ▶ — следующая/прошлая фраза с этой переменной вокруг суммы."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])) or st["takes"][i].get("unit") is None:
            return {"tiers": None}
        unit = st["units"][st["takes"][i]["unit"]]
        _c, cur, n = self._tts_tier_chain(unit)
        if n:
            st.setdefault("tier_ctx_pos", {})[unit["sheet"]] = (int(pos) if pos is not None else cur + int(delta)) % n
            self._tts_save()
        return self.tts_tier_marks(i)

    def _tts_unit_take(self, uid):
        """Дубль, из которого сохранена фраза (для правки громкости/темпа)."""
        st = self._tts()
        return next((k for k in range(len(st["takes"]) - 1, -1, -1)
                     if st["takes"][k].get("unit") == uid and st["takes"][k].get("approved")), None)

    def tts_tier_ctx_sound(self, i, which, gain_db=None, tempo=None):
        """Громкость/темп начала или продолжения фразы прямо отсюда:
        меняется её дубль, сохранённый файл пересобирается."""
        st = self._tts()
        t = st["takes"][i] if 0 <= i < len(st["takes"]) else None
        if not t or t.get("unit") is None:
            return {"tiers": None}
        ch, _p, _n = self._tts_tier_chain(st["units"][t["unit"]])
        uid = (ch or {}).get("start" if which == "start" else "end")
        k = self._tts_unit_take(uid) if uid is not None else None
        if k is None:
            return {**self.tts_tier_marks(i), "error": "Эта фраза сохранена не из дубля — правьте её в «Фразах»."}
        g0, t0 = self._tts_sound(st["takes"][k])
        r = self.tts_take_sound(k, g0 if gain_db is None else gain_db, t0 if tempo is None else tempo)
        if r.get("error"):
            return {**self.tts_tier_marks(i), "error": r["error"]}
        return self.tts_tier_marks(i)

    def _tts_tier_resave_all(self):
        """Пересохранить все готовые ярусы листа (новая громкость/фон)."""
        st = self._tts()
        mode = st.get("prompt_mode", "phrases")
        n = 0
        for t in st["takes"]:
            u = st["units"][t["unit"]] if t.get("unit") is not None else None
            if u and u.get("tiers") and u.get("sheet") == mode and t.get("tier_files"):
                try:
                    out, _s = self._tts_tier_save(t, u, resave=True)
                    n += len(out)
                except Exception:
                    pass
        self._tts_save()
        return {"resaved": n}

    def tts_tier_resave_all(self):
        return self._tts_timed('ярусы: пересохранить все', self._tts_tier_resave_all)

    def tts_tier_marks(self, i):
        """Для «Сборки»: дубль строки (волна) и ярусы клипами (см. _tts_tier_marks).
        Любая беда (пропал файл и т.п.) — сообщением, а не падением."""
        try:
            r = self._tts_timed('ярусы: открыть строку', lambda: self._tts_tier_marks(i))
        except Exception as e:
            return {"tiers": None, "error": str(e)}
        self._tts_disk_flush()
        if r.get("tiers"):
            self._tts_prerender_kick(i)
        return r

    # ---- предрасчёт: пока вы смотрите на строку, ярусы готовятся в фоне ----
    TTS_PRERENDER_DELAY = 0.3     # подождать: маркер тянут — считать после того, как отпустили

    def _tts_prerender_kick(self, i):
        self._tts_pre_want = i
        th = self.__dict__.get('_tts_pre_thread')
        if th is None or not th.is_alive():
            th = self._tts_pre_thread = threading.Thread(target=self._tts_prerender_loop, daemon=True)
            th.start()

    def _tts_prerender_loop(self):
        while True:
            time.sleep(self.TTS_PRERENDER_DELAY)
            i = self.__dict__.pop('_tts_pre_want', None)
            if i is None:
                return
            if getattr(self, '_tts_rec', None):            # идёт запись — не отнимать у неё процессор
                continue
            try:
                self._tts_prerender(i)
            except Exception:
                pass                                       # не вышло — посчитается по кнопке, как раньше

    def _tts_prerender(self, i):
        st = self._tts()
        t = st["takes"][i]
        unit = st["units"][t["unit"]]
        n = len(unit.get("tiers") or [])
        clips = t.get("tier_clips")
        if not n or not clips or len(clips) != n or not t.get("tier_len"):
            return                                         # границы ещё не выставлены — не трогаем проект из фона
        write = t.get("tier_write") or {}
        mine = set(t.get("tier_files") or [])
        for j, x in enumerate(unit["tiers"]):
            if '_tts_pre_want' in self.__dict__ or self.tts is not st:   # перешли к другой строке / новый проект
                return
            path = self._tts_tier_path(unit, x)
            if os.path.exists(path) and path not in mine and not write.get(str(j)):
                self._tts_seg(path)
            else:
                self._tts_tier_audio(t, unit, j)
        for c in self._tts_tier_ctx(unit):
            if c:
                self._tts_seg(c[0])

    def _tts_tier_marks(self, i):
        """Для «Сборки»: дубль строки (волна) и ярусы клипами — где взят каждый
        и как они встанут друг за другом (с началом и продолжением фразы)."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])) or st["takes"][i].get("unit") is None:
            return {"tiers": None}
        t = st["takes"][i]
        unit = st["units"][t["unit"]]
        if not unit.get("tiers") or not st.get("work_dir"):
            return {"tiers": None}
        try:
            clips, length, rms = self._tts_tier_clips(t, unit)
        except Exception as e:
            return {"tiers": None, "error": str(e)}
        f = self.TIER_FRAME_MS
        write = t.get("tier_write") or {}
        mine = set(t.get("tier_files") or [])
        out = []
        for k, x in enumerate(unit["tiers"]):
            path = self._tts_tier_path(unit, x)
            c = clips[k]
            item = {"k": k, "label": x["label"], "value": x["value"], "text": x["text"], "a": c["a"], "b": c["b"],
                    "pre": c.get("pre", 0), "post": c.get("post", 0), "tempo": c.get("tempo", 1.0), "gain": c.get("gain", 0.0),
                    "exists": os.path.exists(path) and path not in mine,
                    "mine": path in mine, "write": bool(write.get(str(k)))}
            if item["exists"] and not item["write"]:      # в сборке — готовый файл, как он есть
                try:
                    r, ln = self._tts_file_rms(path)
                    item.update(file_len=ln, file_peaks=self._tts_peaks(r))
                except Exception:
                    pass
            item["peaks"] = self._tts_peaks(rms[c["a"] // f:max(c["a"] // f + 1, c["b"] // f)])
            out.append(item)
        ctx = {}
        for key, c in zip(("start", "end"), self._tts_tier_ctx(unit)):
            if c:
                r, ln = self._tts_file_rms(c[0], self.TIER_CTX_MS, tail=c[1])
                ctx[key] = {"name": c[2], "len": ln, "peaks": self._tts_peaks(r)}
        ch, cpos, cn = self._tts_tier_chain(unit)
        phrase = None
        if ch:
            sk, ek = self._tts_unit_take(ch["start"]), (self._tts_unit_take(ch["end"]) if ch["end"] is not None else None)
            phrase = {"pos": cpos, "total": cn, "name": ch["name"], "start_name": ch["start_name"], "start_text": ch["start_text"],
                      "end_name": ch["end_name"], "end_text": ch["end_text"], "end_from": ch["end_from"],
                      "start_saved": bool(ch["start_path"]), "end_saved": bool(ch["end_path"]),
                      "start_take": sk, "end_take": ek if not ch["end_from"] else None,
                      "start_sound": self._tts_sound(st["takes"][sk]) if sk is not None else None,
                      "end_sound": self._tts_sound(st["takes"][ek]) if ek is not None and not ch["end_from"] else None}
        level = self._tts_ctx_level(unit) if ctx else None
        row_l = self._tts_row_loud(t, unit) if level is not None else None
        tpl = self._tts_tier_tpl(unit)
        return {"i": i, "tiers": out, "length": length, "peaks": self._tts_peaks(rms), "frame": f,
                "row": unit["text"], "ctx": ctx, "take_tempo": self._tts_sound(t)[1],
                "opts": self._tts_tier_opts(), "ctx_level": level, "row_level": row_l, "phrase": phrase,
                "bg": self.tts_tier_bg_state(),
                "resave_n": sum(len(x.get("tier_files") or []) for x in st["takes"] if x.get("unit") is not None
                                and st["units"][x["unit"]].get("sheet") == unit.get("sheet")),
                "tpl": {"from": tpl["from"], "auto": bool(tpl.get("auto")), "used": bool(t.get("tier_by_tpl"))} if tpl else None}

    def tts_tier_set(self, i, clips=None, write=None, opts=None):
        """Подвинули край клипа / паузу / темп / громкость яруса, «перезаписать»,
        «фон как во фразе», «громкость как у фразы»."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"tiers": None}
        t = st["takes"][i]
        if clips is not None:
            L = int(t.get("tier_len") or 10 ** 9)
            fixed = []
            for c in clips:
                a = max(0, min(L - 20, int(c["a"])))
                fixed.append({"a": a, "b": max(a + 20, min(L, int(c["b"]))),
                              "pre": max(0, min(3000, int(c.get("pre") or 0))),
                              "post": max(0, min(3000, int(c.get("post") or 0))),
                              "tempo": round(max(self.TIER_TEMPO[0], min(self.TIER_TEMPO[1], float(c.get("tempo") or 1))), 3),
                              "gain": round(max(self.TIER_GAIN[0], min(self.TIER_GAIN[1], float(c.get("gain") or 0))), 1)})
            t["tier_clips"] = fixed
        if write is not None:
            t["tier_write"] = {str(k): bool(v) for k, v in dict(write).items()}
        if opts is not None:
            st["tier_opts"] = {**self._tts_tier_opts(), **{k: bool(v) for k, v in dict(opts).items() if k in ("noise", "level")}}
        self._tts_save()
        return self.tts_tier_marks(i)              # там же — предрасчёт изменённого

    def _tts_tier_assembly(self, t, unit, k=None, ctx_ms=None):
        """Сборка как прозвучит: начало фразы + ярусы (готовые — из файлов) +
        продолжение. k — только один ярус; ctx_ms — сколько конца начала и
        начала продолжения взять (стык). Возвращает (файл, длина мс)."""
        ctx_ms = int(ctx_ms or self.TIER_CTX_MS)
        segs = []
        start = end = None
        if k is None:
            start, end = self._tts_tier_ctx(unit)
        write = t.get("tier_write") or {}
        mine = set(t.get("tier_files") or [])
        for j, x in enumerate(unit["tiers"]):
            if k is not None and j != k:
                continue
            path = self._tts_tier_path(unit, x)
            if os.path.exists(path) and path not in mine and not write.get(str(j)):
                segs.append(self._tts_seg(path))
            else:
                segs.append(self._tts_pcm_seg(*self._tts_tier_audio(t, unit, j)))
        if start:
            sg = self._tts_seg(start[0])
            segs.insert(0, sg[-ctx_ms:] if len(sg) > ctx_ms else sg)
        if end:
            segs.append(self._tts_seg(end[0])[:ctx_ms])
        rate = max(sg.frame_rate for sg in segs)
        out = AudioSegment.empty().set_frame_rate(rate)
        for sg in segs:
            out += sg.set_frame_rate(rate).set_channels(1).set_sample_width(2)
        return out

    @staticmethod
    def _tts_pcm_seg(x, rate):
        """float → AudioSegment 16 бит — байт в байт как в сохранённом файле (_write_pcm16)."""
        peak = float(np.abs(x).max()) if len(x) else 0.0
        if peak > 0.98:
            x = x * (0.98 / peak)
        pcm = np.round(np.asarray(x, dtype=np.float32) * 32767).astype('<i2')
        return AudioSegment(pcm.tobytes(), frame_rate=rate, sample_width=2, channels=1)

    def tts_tier_play(self, i, k=None, from_ms=None, ctx_ms=None):
        """Послушать ярус (k) или всю сборку (k=None) с места from_ms (мс по
        дорожке «Сборка») — ровно как сохранится и склеится. ctx_ms — стык:
        только столько конца начала фразы и начала продолжения."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"playing": False}
        t = st["takes"][i]
        unit = st["units"][t["unit"]]
        try:
            import tempfile
            out = self._tts_timed('сборка для прослушки', lambda: self._tts_tier_assembly(
                t, unit, None if k is None or int(k) < 0 else int(k), ctx_ms))
            ln = len(out)
            off = max(0, min(ln - 50, int(from_ms or 0)))
            dst = os.path.join(tempfile.gettempdir(), f"gvox_tier_play_{os.getpid()}.wav")
            (out[off:] if off else out).export(dst, format="wav")      # [0:] обрезал бы хвост до целых мс
        except Exception as e:
            return {"playing": False, "error": str(e)}
        self._tts_disk_flush()
        self._tts_mark_listened()
        self.player.play(dst)
        return {"playing": True, "duration": (ln - off) / 1000.0, "from": off, "length": ln}

    def _tts_tier_render(self, t, unit, k, dst):
        """Ярус → эталон (файл)."""
        from core.tts_synth import _write_pcm16
        x, rate = self._tts_tier_audio(t, unit, k)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _write_pcm16(dst, x, rate)

    def _tts_tier_audio(self, t, unit, k):
        """Ярус как прозвучит: (float32, частота). Посчитан раз — берётся из
        кэша, пока не поменялось ничего, от чего зависит звук."""
        clips, _length, _rms = self._tts_tier_clips(t, unit)
        c = clips[k]
        opts = self._tts_tier_opts()
        level = self._tts_ctx_level(unit) if opts["level"] else None
        row = self._tts_row_loud(t, unit) if level is not None else None
        start, end = self._tts_tier_ctx(unit)
        ref = (start or end or (None,))[0]
        bg = self._tts_bg()
        take = os.path.join(self._tts()["work_dir"], t["file"])
        key = ('tier',) + self._file_sig(take) + (
            tuple(sorted((n, v) for n, v in c.items())), self._tts_sound(t), tuple(sorted(opts.items())), level, row,
            self._file_sig(ref) if opts["noise"] and ref else None, k, unit.get('name'), OUT_RATE,
            (self._file_sig(bg["path"]), bg.get("db", self.TIER_BG_DB)) if bg and bg.get("on") else None)
        lock = self.__dict__.setdefault('_tts_render_lock', threading.Lock())
        with lock:                                         # фон и кнопка — не считают одно и то же дважды
            return self._tts_cached(key, lambda: self._tts_tier_audio_calc(t, unit, c, k, level, row, ref, opts))

    def _tts_tier_audio_calc(self, t, unit, c, k, level, row, ref, opts):
        """Сам расчёт яруса: кусок дубля, громкость (как у фразы ± своя), темп
        (дубля × свой), паузы и фон — как в начале/продолжении фразы."""
        import tempfile
        from core.tts_synth import _mono, room_noise
        gain, tempo = self._tts_sound(t)
        seg = self._tts_seg(os.path.join(self._tts()["work_dir"], t["file"]))[c["a"]:c["b"]]
        if level is not None and row is not None:          # вся строка — к громкости фразы у стыка
            base = level - row
        else:
            seg, base = self._tts_normalized(seg), 0.0
        seg = self._tts_gain_limited(seg, gain + float(c.get("gain") or 0) + base)
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tier_src_{os.getpid()}_{threading.get_ident()}.wav")
        self._tts_export_8k(seg, tmp, tempo * float(c.get("tempo") or 1.0))
        x, rate = _mono(tmp)
        pre = int(rate * int(c.get("pre") or 0) / 1000)
        post = int(rate * int(c.get("post") or 0) / 1000)           # пауза после яруса (перед продолжением)
        x = np.concatenate([np.zeros(pre, dtype=np.float32), x, np.zeros(post, dtype=np.float32)])
        if opts["noise"] and ref:
            bed = room_noise(ref, rate, len(x), seed=k)
            if bed is not None:
                fr = max(1, rate // 100)                              # кадры 10 мс
                body = x[pre:len(x) - post]
                e = np.sqrt((body[:len(body) // fr * fr].reshape(-1, fr) ** 2).mean(axis=1)) if len(body) >= fr else np.zeros(0)
                bf = np.sqrt((bed[:len(bed) // fr * fr].reshape(-1, fr) ** 2).mean(axis=1))
                own = float(np.percentile(e, 10)) if len(e) else 0.0
                room = float(np.median(bf)) if len(bf) else 0.0
                # под голосом — сколько не хватает до фона фразы; в паузе — фон целиком
                k_body = float(np.sqrt(max(0.0, 1 - (own / room) ** 2))) if room > 0 else 0.0
                w = np.full(len(x), k_body, dtype=np.float32)
                if pre:
                    w[:pre] = 1.0
                    xf = min(pre, max(1, rate // 50))
                    w[pre - xf:pre] = np.linspace(1.0, k_body, xf, dtype=np.float32)
                if post:
                    w[len(x) - post:] = 1.0
                    xf = min(post, max(1, rate // 50))
                    w[len(x) - post:len(x) - post + xf] = np.linspace(k_body, 1.0, xf, dtype=np.float32)
                x = x + bed[:len(x)] * w
        x = self._tts_add_bg(x, rate, f"{unit.get('name')}:{k}")
        x.setflags(write=False)                            # общий для кэша — не менять на месте
        return x, rate

    # ---- фон из файла (например, 15 с шума офиса) под переменные ----
    TIER_BG_DB = -24          # по умолчанию фон на столько дБ тише голоса
    TIER_BG_DIR = '_Фон'

    def _tts_bg(self):
        bg = self._tts().get("tier_bg") or {}
        wd = self._tts().get("work_dir")
        if not bg.get("file") or not wd:
            return None
        path = os.path.join(wd, bg["file"])
        return dict(bg, path=path) if os.path.exists(path) else None

    def tts_tier_bg_pick(self):
        """Загрузить фон (любой звук: mp3/wav/…): копия — в «_Фон/» проекта."""
        st = self._tts()
        if not st.get("work_dir"):
            return {"error": "Сначала откройте проект."}
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                  file_types=('Аудио (*.wav;*.mp3;*.flac;*.ogg;*.m4a)', 'Все файлы (*.*)'))
        if not f:
            return {"bg": self.tts_tier_bg_state()}
        return self.tts_tier_bg_load(f[0])

    def tts_tier_bg_load(self, src):
        st = self._tts()
        try:
            seg = AudioSegment.from_file(src).set_channels(1).set_sample_width(2)
        except Exception as e:
            return {"error": f"Не читается: {e}"}
        if len(seg) < 1000:
            return {"error": "Фон слишком короткий — нужна хотя бы секунда."}
        name = clean_name(os.path.splitext(os.path.basename(src))[0]) or 'фон'
        rel = os.path.join(self.TIER_BG_DIR, f"{name}.wav")
        dst = os.path.join(st["work_dir"], rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        seg.export(dst, format="wav")
        old = st.get("tier_bg") or {}
        st["tier_bg"] = {"file": rel, "name": name, "on": True, "db": old.get("db", self.TIER_BG_DB),
                         "sec": round(len(seg) / 1000, 1)}
        self.__dict__.pop('_tts_bg_cache', None)
        self._tts_save()
        return {"bg": self.tts_tier_bg_state()}

    def tts_tier_bg_set(self, on=None, db=None):
        st = self._tts()
        bg = st.get("tier_bg")
        if not bg:
            return {"bg": None}
        if on is not None:
            bg["on"] = bool(on)
        if db is not None:
            bg["db"] = int(max(-45, min(-3, int(db))))
        self._tts_save()
        return {"bg": self.tts_tier_bg_state()}

    def tts_tier_bg_state(self):
        bg = self._tts_bg()
        return {k: bg[k] for k in ("name", "on", "db", "sec")} if bg else None

    def _tts_add_bg(self, x, rate, key):
        """Подмешать фон: кусок записи (у каждого яруса — свой, по ключу),
        по кругу с перекрытием, на bg.db дБ тише голоса яруса."""
        bg = self._tts_bg()
        if not bg or not bg.get("on") or not len(x):
            return x
        import zlib
        from utils.audio_player import resample
        cache = self.__dict__.setdefault('_tts_bg_cache', {})
        ck = (bg["path"], os.path.getmtime(bg["path"]), rate)
        if ck not in cache:
            seg = AudioSegment.from_file(bg["path"]).set_channels(1).set_sample_width(2)
            b = np.frombuffer(seg.raw_data, dtype='<i2').astype(np.float32) / 32768
            if seg.frame_rate != rate:
                b = resample(b[:, None], seg.frame_rate, rate)[:, 0]
            cache.clear()
            cache[ck] = b.astype(np.float32)
        b = cache[ck]
        n, xf = len(x), max(1, int(rate * 0.05))
        start = zlib.crc32(key.encode('utf-8')) % max(1, len(b) - xf)
        out, pos, cur = np.zeros(n, dtype=np.float32), 0, start
        while pos < n:                                      # по кругу; стык — перекрытие xf
            piece = b[cur:cur + (n - pos)].copy()
            take = len(piece)
            if pos:
                ov = min(xf, take)
                piece[:ov] *= np.linspace(0, 1, ov, dtype=np.float32)
                out[pos:pos + ov] *= np.linspace(1, 0, ov, dtype=np.float32)
            out[pos:pos + take] += piece
            if pos + take >= n or take <= xf:
                break
            pos, cur = pos + take - xf, 0
        fr = max(1, rate // 100)
        e = np.sqrt((x[:n // fr * fr].reshape(-1, fr) ** 2).mean(axis=1)) if n >= fr else np.zeros(0)
        voice = float(np.percentile(e, 90)) if len(e) else 0.0
        bed = float(np.sqrt(np.mean(out ** 2))) if len(out) else 0.0
        if voice <= 1e-5 or bed <= 1e-6:
            return x
        out *= voice * 10 ** (float(bg.get("db", self.TIER_BG_DB)) / 20) / bed
        f = min(n // 2, max(1, int(rate * 0.015)))          # без щелчков на краях файла
        out[:f] *= np.linspace(0, 1, f, dtype=np.float32)
        out[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        return x + out

    @staticmethod
    def _tts_peaks(rms):
        top = float(np.max(rms)) if len(rms) else 0
        return [round(min(1.0, float(v) / top), 3) if top > 1e-6 else 0 for v in rms]

    def _tts_file_rms(self, path, keep_ms=None, tail=False, cache=True):
        """RMS файла по кадрам 10 мс (keep_ms — только начало/конец файла)."""
        if cache:
            return self._tts_cached(('rms', keep_ms, bool(tail)) + self._file_sig(path),
                                    lambda: self._tts_file_rms(path, keep_ms, tail, cache=False))
        seg = self._tts_seg(path).set_sample_width(2)
        if keep_ms and len(seg) > keep_ms:
            seg = seg[-keep_ms:] if tail else seg[:keep_ms]
        x = np.frombuffer(seg.raw_data, dtype='<i2').astype(np.float32) / 32768
        per = max(1, seg.frame_rate * self.TIER_FRAME_MS // 1000)
        n = len(x) // per
        return (np.sqrt((x[:n * per].reshape(n, per) ** 2).mean(axis=1)) if n else np.zeros(0)), len(seg)

    def _tts_tier_save(self, t, unit, resave=False):
        """Сохранить ярусы дубля финальными эталонами. Готовые (не из этого
        дубля) — не трогаем, если не отмечено «перезаписать»."""
        write = t.get("tier_write") or {}
        mine = set(t.get("tier_files") or [])
        out, skipped = [], []
        for k, x in enumerate(unit["tiers"]):
            path = self._tts_tier_path(unit, x)
            if os.path.exists(path) and path not in mine and not write.get(str(k)):
                skipped.append(x["label"])
                continue
            if resave and path not in mine:
                continue
            if os.path.exists(path):
                self._tts_trash(path)
            self._tts_tier_render(t, unit, k, path)
            out.append(path)
        t["tier_files"] = sorted(set(out) | (mine if resave else set()))
        t["tier_write"] = {}
        if not self._tts_tier_tpl(unit):                # первая сохранённая строка — шаблон листа
            self._tts_tier_tpl_from(t, unit)
        return out, skipped

    def _tts_value_context(self, sheet):
        """Начало и продолжение фразы вокруг переменной этого листа: цепочка,
        где после переменной не стоит то же «тенге» (сумма читается целиком)."""
        st = self._tts()
        best = None
        for ch in st.get("chains") or []:
            parts = [st["units"][i] for i in ch["parts"]]
            for k, u in enumerate(parts):
                if u.get("var_after") != sheet:
                    continue
                nxt = parts[k + 1] if k + 1 < len(parts) else None
                first = (str(nxt["text"]).split() or [''])[0].lower() if nxt else ''
                score = 0 if first.startswith(('тенге', 'теңге')) else 1
                if best is None or score > best[0]:
                    best = (score, u, nxt)
        if not best:
            return None
        _s, a, b = best
        wd = self._tts().get("work_dir")
        sv = lambda u: bool(u and wd and os.path.exists(self._tts_target(u)))
        aw, bw = str(a["text"]).split(), str(b["text"]).split() if b else []
        return {"before": ('… ' if len(aw) > 7 else '') + ' '.join(aw[-7:]), "after": ' '.join(bw[:7]) + (' …' if len(bw) > 7 else ''),
                "start": a["id"], "end": b["id"] if b else None, "start_name": a["name"], "end_name": b["name"] if b else None,
                "start_saved": sv(a), "end_saved": sv(b)}

    def tts_value_context_play(self, which, take_i=None):
        """Послушать в контексте: 'start' — сохранённое начало фразы (перед
        записью суммы), 'whole' — начало + этот дубль + продолжение."""
        import tempfile
        st = self._tts()
        mode = st.get("prompt_mode", "phrases")
        if take_i is not None and 0 <= take_i < len(st["takes"]) and st["takes"][take_i].get("unit") is not None:
            mode = st["units"][st["takes"][take_i]["unit"]].get("sheet") or mode
        ctx = self._tts_value_context(mode)
        if not ctx:
            return {"error": "Эта переменная не стоит ни в одной фразе таблицы."}
        a, b = st["units"][ctx["start"]], (st["units"][ctx["end"]] if ctx["end"] is not None else None)
        if not ctx["start_saved"]:
            return {"error": f"Начало фразы «{a['name']}» ещё не сохранено — запишите его в «Фразах»."}
        segs = [AudioSegment.from_file(self._tts_target(a))]
        if which == 'whole':
            if take_i is None or not (0 <= take_i < len(st["takes"])):
                return {"error": "Нет дубля."}
            t = st["takes"][take_i]
            mid = self._tts_normalized(AudioSegment.from_file(os.path.join(st["work_dir"], t["file"])))
            segs.append(mid)
            if b is not None and ctx["end_saved"]:
                segs.append(AudioSegment.from_file(self._tts_target(b)))
        rate = segs[0].frame_rate
        out = None
        for sg in segs:
            sg = sg.set_frame_rate(rate).set_channels(1)
            out = sg if out is None else out + AudioSegment.silent(120, frame_rate=rate) + sg
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_ctx_{os.getpid()}.wav")
        out.export(tmp, format="wav")
        self.player.play(tmp)
        return {"playing": True, "duration": len(out) / 1000.0, "end_missing": which == 'whole' and b is not None and not ctx["end_saved"]}

    def tts_prompt_mode(self, mode):
        """Что читать на суфлёре: 'phrases' — фразы таблицы, или ключ листа
        переменных ('sum_ru', 'date_ru') — его значения по порядку строк.
        У каждого режима своя позиция суфлёра."""
        st = self._tts()
        if mode != 'phrases' and mode not in (st.get("var_sheets") or {}):
            return {"error": "Нет такого листа переменных."}
        self._tts_ensure_value_units()
        cur = st.get("prompt_mode", "phrases")
        pos_by = st.setdefault("prompt_pos_by_mode", {})
        pos_by[cur] = st.get("prompt_pos", 0)
        st["prompt_mode"] = mode
        st["prompt_pos"] = pos_by.get(mode, 0)
        if hasattr(self, '_tts_prompt_fix'):
            self._tts_prompt_fix()
        self._tts_save()
        return {"prompt": self.tts_prompt_info() if hasattr(self, 'tts_prompt_info') else None,
                "state": self.tts_state()}

    def tts_vars_state(self):
        st = self._tts()
        has_dir = bool(st.get("work_dir"))
        sheets = []
        for key, sh in st["var_sheets"].items():
            cats = []
            for c in sh["categories"]:
                values = []
                for v in c["values"]:
                    text, custom = self._tts_value_text(key, c["key"], v)
                    values.append({"value": v, "text": text, "custom": custom,
                                   "ready": has_dir and os.path.exists(self._tts_value_file(key, c["key"], v))})
                cats.append({"key": c["key"], "label": c["label"], "values": values,
                             "ready": sum(1 for x in values if x["ready"])})
            sheets.append({"key": key, "label": sh["label"], "categories": cats})
        chains = []
        for ch in st.get("chains", []):
            parts = [st["units"][i] for i in ch["parts"]]
            chains.append({"id": ch["id"], "name": ch["name"], "vars": ch.get("vars", []),
                           "parts": [{"id": u["id"], "name": u["name"], "role": u["role"], "text": u["text"],
                                      "var_after": u.get("var_after"), "var_before": u.get("var_before"),
                                      "saved": has_dir and os.path.exists(self._tts_target(u))} for u in parts]})
        return {"sheets": sheets, "chains": chains, "has_project": has_dir}

    def tts_var_set_text(self, sheet, cat, value, text):
        st = self._tts()
        texts = st.setdefault("var_texts", {})
        key = f"{sheet}|{cat}|{value}"
        text = (text or '').strip()
        if text and text != synth_text(cat, value):
            texts[key] = text
        else:
            texts.pop(key, None)
        self._tts_save()
        return {"text": self._tts_value_text(sheet, cat, value)[0]}

    def tts_var_play(self, sheet, cat, value):
        path = self._tts_value_file(sheet, cat, value)
        if not os.path.exists(path):
            return {"playing": False}
        self._tts_mark_listened()
        self.player.play(path)
        return {"playing": True, "duration": len(AudioSegment.from_file(path)) / 1000.0}

    def tts_var_open_folder(self, sheet, cat):
        if not self._tts().get("work_dir"):
            return {"error": "Сначала загрузите запись — от неё зависит папка проекта."}
        folder = self._tts_value_dir(sheet, cat)
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            return {"error": str(e)}
        return {"status": "ok"}

    @staticmethod
    def _tts_norm_value(text):
        return re.sub(r'\s+', ' ', str(text).lower().replace('ё', 'е')).strip()

    def tts_var_import(self, sheet, cat):
        """Разложить уже готовые файлы значений: имя файла — само значение
        («5.wav»), его текст («пять миллионов.wav») или содержит число
        («million_5.wav»). Копируем байт в байт."""
        st = self._tts()
        if not st.get("work_dir"):
            return {"error": "Сначала загрузите запись — от неё зависит папка проекта."}
        sh = st["var_sheets"].get(sheet)
        c = next((c for c in (sh or {}).get("categories", []) if c["key"] == cat), None)
        if not c:
            return {"error": "Нет такой категории."}
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        folder = picked if isinstance(picked, str) else picked[0]
        by_name = {}
        for v in c["values"]:
            by_name.setdefault(self._tts_norm_value(v), v)
            by_name.setdefault(self._tts_norm_value(self._tts_value_text(sheet, cat, v)[0]), v)
        digits = {re.sub(r'\D', '', v): v for v in c["values"] if re.fullmatch(r'\d+', v)}
        matched, unknown = 0, []
        os.makedirs(self._tts_value_dir(sheet, cat), exist_ok=True)
        for f in sorted(os.listdir(folder)):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in ('.wav', '.mp3'):
                continue
            v = by_name.get(self._tts_norm_value(stem))
            if v is None:
                nums = re.findall(r'\d+', stem)
                v = digits.get(nums[-1].lstrip('0') or '0') if len(nums) == 1 else None
            if v is None:
                unknown.append(f)
                continue
            src = os.path.join(folder, f)
            if ext.lower() == '.wav':
                shutil.copy2(src, self._tts_value_file(sheet, cat, v))
            else:
                AudioSegment.from_file(src).export(self._tts_value_file(sheet, cat, v), format="wav")
            matched += 1
        return {"matched": matched, "unknown": unknown[:30], "unknown_count": len(unknown),
                "state": self.tts_vars_state()}

    @staticmethod
    def _tts_speech_db(seg):
        """Громкость речи: 90-й перцентиль громкости 50-мс окон (тишина не в счёт)."""
        levels = sorted(seg[k:k + 50].dBFS for k in range(0, max(1, len(seg) - 50), 50)
                        if seg[k:k + 50].rms > 0)
        if not levels:
            return None
        return round(levels[int(len(levels) * 0.9) - 1 if len(levels) > 1 else 0], 1)

    @classmethod
    def _tts_normalized(cls, seg):
        """Выровнять громкость: речь — на OUT_SPEECH_DB, пики — не выше OUT_PEAK_DB."""
        seg = seg.set_channels(1)
        level = cls._tts_speech_db(seg)
        if level is None or seg.max_dBFS == float('-inf'):
            return seg
        gain = OUT_SPEECH_DB - level
        gain = min(gain, OUT_PEAK_DB - seg.max_dBFS, OUT_GAIN_LIMIT_DB)
        return seg.apply_gain(gain) if abs(gain) > 0.1 else seg

    @staticmethod
    def _tts_export_8k(seg, dst, tempo=1.0):
        """WAV 8 кГц / 16 бит / моно. Частоту пересчитывает ffmpeg (с фильтром,
        без призвуков); нет ffmpeg — запасной путь pydub. tempo — темп без
        смены высоты голоса (фильтр atempo: растягивает время, а не частоту)."""
        change = abs(tempo - 1.0) > 0.004
        params = (["-af", f"atempo={tempo:.3f}"] if change else []) + \
            ["-ar", str(OUT_RATE), "-ac", "1", "-acodec", "pcm_s16le"]
        try:
            seg.export(dst, format="wav", parameters=params)
            if os.path.exists(dst) and os.path.getsize(dst) > 44:
                return
        except Exception:
            pass
        if change:
            raise RuntimeError("Чтобы менять темп, нужен ffmpeg — без него темп не применить.")
        seg.set_frame_rate(OUT_RATE).set_sample_width(2).set_channels(1).export(dst, format="wav")

    @staticmethod
    def _tts_gain_limited(seg, db):
        """Громче/тише на db. Пики, которые вылезли бы выше OUT_PEAK_DB, мягко
        прижимаются (без треска перегруза) — так «+6 дБ» правда звучит громче,
        даже если запись уже была выровнена до потолка."""
        import numpy as np
        if abs(db) < 0.05:
            return seg
        w = seg.sample_width
        dt = {1: np.int8, 2: '<i2', 4: '<i4'}.get(w)
        if dt is None:
            return seg.apply_gain(db)
        full = float(1 << (8 * w - 1))
        x = np.frombuffer(seg.raw_data, dtype=dt).astype(np.float64) / full * (10 ** (db / 20))
        ceil = 10 ** (OUT_PEAK_DB / 20)
        knee = ceil * 0.7
        a = np.abs(x)
        over = a > knee
        if over.any():
            a[over] = knee + (ceil - knee) * np.tanh((a[over] - knee) / (ceil - knee))
            x = np.sign(x) * a
        y = np.clip(np.round(x * full), -full, full - 1).astype(dt)
        return seg._spawn(y.tobytes())

    def _tts_render_final(self, src, dst, gain_db=0.0, tempo=1.0):
        """Дубль → готовый файл: громкость выровнена (± ваша поправка), темп, 8 кГц."""
        seg = self._tts_normalized(AudioSegment.from_file(src))
        seg = self._tts_gain_limited(seg, gain_db)
        self._tts_export_8k(seg, dst, tempo)

    @staticmethod
    def _tts_sound(t):
        """(громкость дБ, темп) дубля — настройки из «Сборки»."""
        return float((t or {}).get("gain_db") or 0.0), float((t or {}).get("tempo") or 1.0)

    def _tts_preview(self, src, gain_db=0.0, tempo=1.0):
        """Готовая к сохранению версия дубля для прослушки (кэш во временной папке):
        ровно то, что сохранится — с громкостью и темпом из «Сборки»."""
        import hashlib
        import tempfile
        st_ = os.stat(src)
        key = hashlib.md5(f"{os.path.abspath(src)}|{st_.st_mtime_ns}|{st_.st_size}|{gain_db:.2f}|{tempo:.3f}"
                          .encode()).hexdigest()[:16]
        dst = os.path.join(tempfile.gettempdir(), f"gvox_tts_prev_{key}.wav")
        if not os.path.exists(dst):
            self._tts_render_final(src, dst, gain_db, tempo)
        return dst

    def tts_take_sound(self, i, gain_db=0.0, tempo=1.0):
        """Громкость и темп дубля (из «Сборки»). Темп — без смены высоты голоса.
        Дубль уже сохранён — сохранённый файл сразу пересобирается."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        g = round(max(TAKE_GAIN_DB[0], min(TAKE_GAIN_DB[1], float(gain_db or 0))), 1)
        k = round(max(TAKE_TEMPO[0], min(TAKE_TEMPO[1], float(tempo or 1))), 3)
        t["gain_db"], t["tempo"] = g, k
        resaved = False
        if t.get("approved") and t.get("unit") is not None and st.get("work_dir"):
            src = os.path.join(st["work_dir"], t["file"])
            target = self._tts_target(st["units"][t["unit"]])
            try:
                if st["units"][t["unit"]].get("tiers"):
                    self._tts_tier_save(t, st["units"][t["unit"]], resave=True)
                    self._tts_save()
                    return {**self.tts_state(), "resaved": True}
                self._tts_render_final(src, target, g, k)
                self._tts_twin_spread(t["unit"])          # одинаковые фразы — с теми же настройками
                resaved = True
            except Exception as e:
                self._tts_save()
                return {**self.tts_state(), "error": str(e)}
        self._tts_save()
        return {**self.tts_state(), "resaved": resaved}

    def _tts_sample_files(self, var_key):
        """Пример значения переменной для прослушки сборки: первые готовые
        значения двух последних категорий листа (сумма — тысячи + тенге,
        дата — день + месяц)."""
        sh = self._tts()["var_sheets"].get(var_key)
        if not sh:
            return []
        files = []
        for c in sh["categories"]:
            f = next((self._tts_value_file(var_key, c["key"], v) for v in c["values"]
                      if os.path.exists(self._tts_value_file(var_key, c["key"], v))), None)
            if f:
                files.append(f)
        return files[-2:]

    def tts_chain_info(self, chain_id):
        """Кусочки цепочки с громкостью речи — чтобы на слух и на глаз было
        видно, что они из одной записи и стыкуются со значениями."""
        st = self._tts()
        ch = next((c for c in st.get("chains", []) if c["id"] == chain_id), None)
        if not ch:
            return {"error": "Нет такой фразы."}
        parts = []
        for uid in ch["parts"]:
            u = st["units"][uid]
            path = self._tts_target(u) if st.get("work_dir") else ''
            db = self._tts_speech_db(AudioSegment.from_file(path)) if path and os.path.exists(path) else None
            parts.append({"id": uid, "db": db})
        samples = {v: [os.path.basename(f) for f in self._tts_sample_files(v)] for v in ch.get("vars", [])}
        dbs = [p["db"] for p in parts if p["db"] is not None]
        return {"id": chain_id, "parts": parts, "samples": samples,
                "spread": round(max(dbs) - min(dbs), 1) if len(dbs) > 1 else 0.0}

    def tts_chain_play(self, chain_id):
        """Сборка фразы целиком: кусочки + пример значения на месте каждой
        переменной (пока значений нет — короткая пауза). Только для прослушки."""
        st = self._tts()
        ch = next((c for c in st.get("chains", []) if c["id"] == chain_id), None)
        if not ch or not st.get("work_dir"):
            return {"playing": False, "error": "Нет такой фразы."}
        segs, rate = [], None
        for k, uid in enumerate(ch["parts"]):
            u = st["units"][uid]
            if k == 0 and u.get("var_before"):
                segs.append(('var', u["var_before"]))
            path = self._tts_target(u)
            segs.append(('file', path) if os.path.exists(path) else ('gap', 600))
            if u.get("var_after"):
                segs.append(('var', u["var_after"]))
        out = None
        for kind, x in segs:
            if kind == 'file':
                parts = [AudioSegment.from_file(x)]
            elif kind == 'var':
                parts = [AudioSegment.from_file(f) for f in self._tts_sample_files(x)] or [None]
            else:
                parts = [None]
            for p in parts:
                if p is None:
                    p = AudioSegment.silent(400 if kind == 'var' else x, frame_rate=rate or 16000)
                rate = rate or p.frame_rate
                p = p.set_frame_rate(rate).set_channels(1)
                out = p if out is None else out + p
        if out is None:
            return {"playing": False}
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_chain_{os.getpid()}.wav")
        out.export(tmp, format="wav")
        self._tts_mark_listened()
        self.player.play(tmp)
        return {"playing": True, "duration": len(out) / 1000.0}

    # ---------------- разметка таблицы: start / start_2 / end и переменные ----------------
    # Отмечается прямо во время записи (суфлёр, клавиши 1/2/3/0 и 4, 5…).
    # Отметки сразу перестраивают цепочки, хранятся в проекте и дописываются
    # в саму таблицу 1-ками (перед первой записью — резервная копия).

    def _tts_ensure_lines(self):
        st = self._tts()
        if st.get("lines") and st.get("mark_cols"):
            return True
        path = st.get("excel_path")
        if not path or not os.path.exists(path):
            return False
        parsed = parse_tts_workbook(path)
        sh = next((s for s in parsed["phrase_sheets"] if s["title"] == st.get("sheet")), None)
        if not sh:
            return False
        st.update({"lines": sh["lines"], "mark_cols": sh["mark_cols"], "var_cols": sh["var_keys"],
                   "head_row": sh["head_row"]})
        st.setdefault("marks_dirty", [])
        return True

    def _tts_rebuild_units(self):
        """Цепочки заново из строк; суфлёр остаётся на той же фразе, уже
        сохранённые файлы переезжают, если фраза стала кусочком (или наоборот)."""
        st = self._tts()
        old = {u["id"]: self._tts_target(u) for u in st["units"]} if st.get("work_dir") else {}
        anchor = None
        if hasattr(self, '_tts_prompt_items'):
            items = self._tts_prompt_items()
            pos = st.get("prompt_pos", 0)
            anchor = items[pos][-1] if 0 <= pos < len(items) else None
        st["units"], st["chains"] = build_units(st["lines"])
        for u in st["units"]:
            src = old.get(u["id"])
            if src and os.path.exists(src):
                dst = self._tts_target(u)
                if dst != src:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if os.path.exists(dst):
                        self._tts_trash(dst)
                    shutil.move(src, dst)
        if anchor is not None and hasattr(self, '_tts_prompt_items'):
            items = self._tts_prompt_items()
            st["prompt_pos"] = next((k for k, ids in enumerate(items) if anchor in ids), st.get("prompt_pos", 0))

    def tts_set_mark(self, unit_id, what, value=None):
        """what='role' — value: 'start' | 'start_2' | 'end' | None (снять);
        what='var' — value: ключ колонки (<sum_ru> → 'sum_ru'), отметка переключается."""
        st = self._tts()
        if not self._tts_ensure_lines():
            return {"error": "Не нашёл файл таблицы — разметку некуда записать."}
        if not (0 <= unit_id < len(st["lines"])):
            return {"error": "Нет такой строки."}
        ln = st["lines"][unit_id]
        if what == 'role':
            ln["role"] = value if value in FLAG_COLS else None
        elif what == 'var' and value in (st.get("var_cols") or []):
            ln["vars"] = [v for v in ln["vars"] if v != value] if value in ln["vars"] else ln["vars"] + [value]
        else:
            return {"error": "Неизвестная отметка."}
        if ln["row"] not in st.setdefault("marks_dirty", []):
            st["marks_dirty"].append(ln["row"])
        self._tts_rebuild_units()
        self._tts_save()
        threading.Thread(target=self._tts_marks_write_bg, daemon=True).start()
        out = {"state": self.tts_state()}
        if hasattr(self, 'tts_prompt_info'):
            out["prompt"] = self.tts_prompt_info()
        return out

    def _tts_marks_write_bg(self):
        lock = getattr(self, '_tts_marks_lock', None)
        if lock is None:
            lock = self._tts_marks_lock = threading.Lock()
        with lock:
            res = self.tts_marks_write()
        self._tts_push({"stage": "marks", **res})

    def tts_marks_write(self):
        """Дописать отметки в таблицу. Файл открыт в Excel — отметки ждут в проекте."""
        st = self._tts()
        dirty = list(st.get("marks_dirty") or [])
        if not dirty:
            return {"saved": True, "pending": 0}
        path = st.get("excel_path")
        if not path or not os.path.exists(path):
            return {"saved": False, "pending": len(dirty), "error": "Файл таблицы не найден."}
        backup = os.path.splitext(path)[0] + '_до_разметки.xlsx'
        try:
            if not os.path.exists(backup):
                shutil.copy2(path, backup)
            wb = openpyxl.load_workbook(path)
            ws = wb[st["sheet"]]
            cols = st.get("mark_cols") or {}
            by_row = {ln["row"]: ln for ln in st["lines"]}
            for row in dirty:
                ln = by_row.get(row)
                if not ln:
                    continue
                for f in FLAG_COLS:
                    if f in cols:
                        ws.cell(row=row, column=cols[f]).value = 1 if ln["role"] == f else None
                for v in st.get("var_cols") or []:
                    if v in cols:
                        ws.cell(row=row, column=cols[v]).value = 1 if v in ln["vars"] else None
            wb.save(path)
        except PermissionError:
            return {"saved": False, "pending": len(dirty),
                    "error": "Таблица открыта в Excel — закройте её, отметки допишутся сами."}
        except Exception as e:
            return {"saved": False, "pending": len(dirty), "error": f"Не удалось записать в таблицу: {e}"}
        st["marks_dirty"] = [r for r in st.get("marks_dirty", []) if r not in dirty]
        self._tts_save()
        return {"saved": True, "pending": len(st["marks_dirty"]), "backup": os.path.basename(backup)}
