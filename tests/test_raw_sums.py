"""Разбор сырой записи сумм (core/raw_sums.py) — только синтетика: выдуманная таблица, тоны вместо речи.
Модель распознавания не нужна: распознанные слова подаются готовыми, выравнивание без модели — по ним."""
import hashlib
import os
import struct

import numpy as np
import openpyxl

from core.raw_sums import (rs_align, rs_canon, rs_cells_bounds, rs_choose, rs_envelope, rs_merge_windows,
                           rs_out_dir, rs_read_grid, rs_read_table, rs_run)


def md5(p):
    with open(p, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def write_wav16(path, x, sr=8000):
    data = (np.clip(x, -1, 1) * 32767).astype('<i2').tobytes()
    fmt = struct.pack('<HHIIHH', 1, 1, sr, sr * 2, 2, 16)
    body = b'WAVE' + b'fmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', len(data)) + data
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', len(body)) + body)


def test_canon_fixes_typos():
    assert rs_canon('двесте') == ['двести']
    assert rs_canon('пятнадцат ьмиллионов') == ['пятнадцать', 'миллионов']
    assert rs_canon('шестьдесят деввять миллионов') == ['шестьдесят', 'девять', 'миллионов']
    assert rs_canon('семьдесять семь миллионов') == ['семьдесят', 'семь', 'миллионов']
    assert rs_canon(' С суммой задолженности') == ['с', 'суммой', 'задолженности']   # не число — как есть


GRID = [
    ['Начало', 'миллионы', 'тысячи', None, 'тенге', None, 'Начало', 'сотни', 'тенге'],
    ['Сумма к оплате', 'один миллион', 'две', 'тысячи', 'одна тенге', None, 'Сумма к оплате', 'сто', 'двадцать тенге'],
    ['Сумма к оплате', 'два миллиона', 'три', 'тысячи', 'два тенге', None, 'Сумма к оплате', None, None],
    ['Сумма к оплате', 'три миллиона', 'пять', 'тысяч', 'три тенге', None, None, '100-900 к', None],
    [None, None, None, None, None, None, 'Сумма к оплате', 'сто тысяч', 'пятьдесят одна тенге'],
]


def test_read_grid_blocks_labels_order():
    t = rs_read_grid(GRID)
    ph = t["phrases"]
    assert [(p["block"], p["row"]) for p in ph] == [(0, 2), (0, 3), (0, 4), (1, 2), (1, 5)]
    assert [c["text"] for c in ph[0]["cells"]] == ['сумма к оплате', 'один миллион', 'две тысячи', 'одна тенге']
    assert ph[0]["cells"][2]["tier"] == 'C тысячи'          # «тысячи» отдельной ячейкой — часть яруса слева
    assert ph[4]["cells"][1]["tier"] == 'H 100-900 к'           # заголовок посреди таблицы — для ячеек ниже
    assert [s["row"] for s in t["skipped"]] == [3]              # одна ячейка — не фраза


def rec_of(text, t0=0.0, step=0.5):
    out = []
    for w in text.split():
        out.append((w, t0, t0 + step * 0.8))
        t0 += step
    return out, t0


def test_align_repeats_last_full_is_main():
    ph = rs_read_grid(GRID)["phrases"]
    seq = ['сумма к оплате один миллион две тысячи одна тенге',
           'сумма к оплате два миллиона три',                     # оборвал
           'ой ещё раз',                                          # разговор
           'сумма к оплате два миллиона три тысячи два тенге',    # повтор целиком
           'сумма к оплате три миллиона пять тысяч три тенге']
    rec, t = [], 0.0
    for s in seq:
        r, t = rec_of(s, t)
        rec += r
        t += 1.0
    at = rs_align(rec, ph)
    assert [a["r"] for a in at] == [0, 1, 1, 2]
    ch = rs_choose(at, ph)
    assert ch[1]["main"] == 2 and ch[1]["spare"] == [1]
    assert at[1]["complete"] is False and at[2]["complete"] is True
    assert 3 not in ch and 4 not in ch                          # второй блок не читали


def test_align_handles_digits_and_typos_in_recognition():
    from core.raw_sums import rs_rec_words
    ph = rs_read_grid(GRID)["phrases"]
    rec = rs_rec_words([('Сумма', 0, .4, 1), ('к', .4, .5, 1), ('оплате', .5, .9, 1), ('1', 1, 1.2, 1),
                        ('миллион', 1.2, 1.6, 1), ('2', 1.7, 1.9, 1), ('тысячи', 1.9, 2.3, 1),
                        ('одна', 2.4, 2.6, 1), ('тинге.', 2.6, 3.0, 1)])
    at = rs_align(rec, ph)
    assert len(at) == 1 and at[0]["r"] == 0 and at[0]["complete"]


def test_merge_windows_drops_zero_and_edge_duplicates():
    w = [('сто', 1.0, 1.4, .9, 0.2), ('сто', 1.05, 1.42, .9, 3.0),   # то же слово из двух окон — центральнее
         ('тенге', 1.5, 1.5, .9, 3.0)]                               # нулевой длины — выдумка
    assert rs_merge_windows(w) == [('сто', 1.05, 1.42, .9)]


def tone_track(words_t, sr=8000, dur=None):
    """Тон на месте каждого слова, тишина между словами."""
    dur = dur or (words_t[-1][1] + 0.6)
    x = np.zeros(int(dur * sr), np.float32) + np.random.RandomState(1).randn(int(dur * sr)).astype(np.float32) * 1e-4
    for s, e in words_t:
        n = np.arange(int(s * sr), int(e * sr))
        x[n] += 0.4 * np.sin(2 * np.pi * 220 * n / sr)
    return x


def test_cells_bounds_cut_in_silence():
    ph = rs_read_grid(GRID)["phrases"][0]          # 4 яруса, 9 слов
    words_t, t = [], 0.5
    for w in ph["words"]:
        words_t.append((t, t + 0.35))
        t += 0.55
    x = tone_track(words_t)
    db, thr = rs_envelope(x, 8000)
    b = rs_cells_bounds(ph, words_t, 0, db, thr, 0.0, len(x) / 8000)
    assert [k for k, _, _ in b] == [0, 1, 2, 3]
    # каждая граница — в паузе между словами соседних ячеек
    for (k1, s1, e1), (k2, s2, e2) in zip(b, b[1:]):
        last = max(i for i, c in enumerate(ph["cell_of"]) if c == k1)
        assert words_t[last][1] <= e1 <= words_t[last + 1][0]
        assert e1 == s2
    assert b[0][1] < words_t[0][0] and b[-1][2] > words_t[-1][1]


def test_run_writes_pieces_without_touching_source(tmp_path):
    grid = GRID
    xl = tmp_path / 'таблица.xlsx'
    wb = openpyxl.Workbook()
    for row in grid:
        wb.active.append(row)
    wb.save(xl)
    table = rs_read_table(str(xl))
    # запись: фраза 1 целиком, фраза 2 дважды (первая оборвана)
    seq = [(0, 'сумма к оплате один миллион две тысячи одна тенге'), (1, 'сумма к оплате два миллиона'),
           (1, 'сумма к оплате два миллиона три тысячи два тенге')]
    rec, words_t, t = [], [], 0.5
    for _, s in seq:
        for w in s.split():
            rec.append((w, t, t + 0.35, 1.0))
            words_t.append((t, t + 0.35))
            t += 0.55
        t += 1.0
    wav = tmp_path / 'запись.wav'
    write_wav16(str(wav), tone_track(words_t))
    before = md5(str(wav))
    out = rs_out_dir(str(wav))
    res = rs_run(None, str(wav), table, out, rec_words=rec)      # без модели: границы по распознанным словам
    assert md5(str(wav)) == before                               # исходник не тронут
    main = [p for p in res["pieces"] if p["role"] == 'main']
    # начальная фраза «сумма к оплате» не сохраняется: 2 фразы × 3 числовых яруса
    assert len(main) == 6 and not any('оплате' in p["text"] for p in res["pieces"])
    assert len([p for p in res["pieces"] if p["role"] == 'spare']) == 1      # «два миллиона» из оборванной
    for p in res["pieces"]:
        assert os.path.getsize(os.path.join(out, p["file"])) > 44
    assert os.path.exists(os.path.join(out, '1 - 100 млн', '1.wav'))              # классы сумм, имя — число
    assert os.path.exists(os.path.join(out, '1 - 99 тыс', '2.wav'))
    assert os.path.exists(os.path.join(out, '1 - 100 тенге', '1.wav'))
    assert os.path.exists(os.path.join(out, '_запасные', '1 - 100 млн', '2 — попытка 1.wav'))
    assert not os.path.exists(os.path.join(out, 'A Начало'))
    for f in ('разбор.xlsx', 'разбор.json', os.path.join('1 - 100 млн', '_проверка.xlsx')):
        assert os.path.exists(os.path.join(out, f))
    assert {m["row"] for m in res["missing"]} == {4, 2, 5}       # не прочитано — в списке «не найдено»
    # повторный разбор не перезаписывает прежнюю папку
    snap = {f: md5(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs}
    out2 = rs_out_dir(str(wav))
    assert out2 != out and out2.endswith('_куски_2')
    rs_run(None, str(wav), table, out2, rec_words=rec)
    assert snap == {f: md5(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs}


def test_start_answers_at_once_while_model_loads(tmp_path):
    """«Разобрать» отвечает сразу: модель грузится в потоке, окно видит этап «model» и время."""
    import time
    from harness import Api
    xl = tmp_path / 'таблица.xlsx'
    wb = openpyxl.Workbook()
    for row in GRID:
        wb.active.append(row)
    wb.save(xl)
    wav = tmp_path / 'запись.wav'
    write_wav16(str(wav), np.zeros(8000, np.float32))
    a = Api()
    assert not a.rsum_load_table(str(xl)).get("error")
    a._rsum()["audio"] = str(wav)
    a._auto_check_model = lambda lang=None: (time.sleep(0.5), (None, 'нет модели'))[1]
    t = time.time()
    s = a.rsum_start()
    assert time.time() - t < 0.3 and s["run"] and s["stage"] == 'model' and s["elapsed"] is not None
    for _ in range(50):
        if not a.rsum_state()["run"]:
            break
        time.sleep(0.05)
    s = a.rsum_state()
    assert not s["run"] and s["msg"] == 'нет модели'


def test_repeated_value_in_column_saved_once(tmp_path):
    """«сто» в столбце сотен после «девятьсот» — вспомогательное: сохраняется одно, без копий и запасных."""
    grid = [['Начало', 'миллионы', 'сотни', 'тенге'],
            ['Сумма к оплате', 'один миллион', 'сто', 'одна тенге'],
            ['Сумма к оплате', 'два миллиона', 'сто', 'два тенге'],
            ['Сумма к оплате', 'три миллиона', 'сто', 'три тенге']]
    table = rs_read_grid(grid)
    rec, words_t, t = [], [], 0.5
    for p in table["phrases"]:
        for w in p["words"]:
            rec.append((w, t, t + 0.35, 1.0))
            words_t.append((t, t + 0.35))
            t += 0.55
        t += 1.0
    wav = tmp_path / 'запись.wav'
    write_wav16(str(wav), tone_track(words_t))
    out = rs_out_dir(str(wav))
    res = rs_run(None, str(wav), table, out, rec_words=rec)
    files = sorted(p["file"] for p in res["pieces"])
    assert [f for f in files if f.startswith('100 - 900')] == [os.path.join('100 - 900', '100.wav')]
    assert len(files) == 7 and res["skipped_repeats"] == 2
    assert sorted(os.listdir(os.path.join(out, '100 - 900'))) == ['100.wav', '_проверка.xlsx']

def test_live_cutting_same_files_as_single_pass(tmp_path):
    """Нарезка по ходу распознавания (куски сразу в папке) даёт ровно те же файлы, что разовая в конце:
    ничего лишнего не остаётся, ничего не пропадает; фразы с повтором после «готовности» режутся заново."""
    from core.raw_sums import RsCutter, rs_envelope
    table = rs_read_grid(GRID)
    seq = ['сумма к оплате один миллион две тысячи одна тенге', 'сумма к оплате два миллиона',
           'сумма к оплате два миллиона три тысячи два тенге', 'сумма к оплате три миллиона пять тысяч три тенге']
    rec, words_t, t = [], [], 0.5
    for s in seq:
        for w in s.split():
            rec.append((w, t, t + 0.35, 1.0))
            words_t.append((t, t + 0.35))
            t += 0.55
        t += 12.0                                  # длинные паузы — чтобы фразы «созревали» по ходу
    wav = tmp_path / 'запись.wav'
    x = tone_track(words_t)
    write_wav16(str(wav), x)

    def files(d):
        return sorted(os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs if f.endswith('.wav'))
    a16 = rs_to16k_for_test(x)
    db, thr = rs_envelope(a16, 16000)
    live = RsCutter(None, str(wav), table, str(tmp_path / 'live'), a16, db, thr)
    seen = []
    for k in range(1, len(rec) + 1):                # слова приходят по одному, как из распознавания
        live.process(rec[:k], upto=rec[k - 1][2])
        seen.append(len(files(str(tmp_path / 'live'))))
    assert max(seen[:-5]) > 0                         # куски появились задолго до конца
    live.process(rec, final=True)
    live.finish(rec)
    single = rs_run(None, str(wav), table, str(tmp_path / 'one'), rec_words=rec)
    assert files(str(tmp_path / 'live')) == files(str(tmp_path / 'one'))
    assert len(single["pieces"]) == len([f for f in files(str(tmp_path / 'one')) if not f.startswith('_фразы')])


def rs_to16k_for_test(x):
    from core.raw_sums import rs_to16k
    return rs_to16k(x, 8000)


def test_cell_cat_like_studio():
    from core.raw_sums import rs_cell_cat
    assert rs_cell_cat('пятьдесят одна тысяча'.split()) == ('thousand', 51)
    assert rs_cell_cat('сто тысяч'.split()) == ('hundred_thousand', 100)
    assert rs_cell_cat(['сто']) == ('hundred', 100)
    assert rs_cell_cat('пятьдесят пять миллионов'.split()) == ('million', 55)
    assert rs_cell_cat(['миллион']) == ('million', 1)
    assert rs_cell_cat('ноль тенге'.split()) == ('tenge', 0)
    assert rs_cell_cat(['тенге']) is None and rs_cell_cat('сумма к оплате'.split()) is None


def _sums_api(tmp_path):
    """Api с готовым разбором: 3 суммы (логика 1: миллионы, сотни, тысячи, тенге)."""
    from harness import Api
    grid = [['Начало', 'миллионы', 'сотни', 'тысячи', None, 'тенге'],
            ['Сумма к оплате', 'один миллион', 'сто', 'одна', 'тысяча', 'одна тенге'],
            ['Сумма к оплате', 'два миллиона', 'двести', 'две', 'тысячи', 'два тенге'],
            ['Сумма к оплате', 'три миллиона', 'триста', 'три', 'тысячи', 'три тенге']]
    table = rs_read_grid(grid)
    rec, words_t, t = [], [], 0.5
    for p in table["phrases"]:
        for w in p["words"]:
            rec.append((w, t, t + 0.35, 1.0))
            words_t.append((t, t + 0.35))
            t += 0.55
        t += 1.0
    wav = tmp_path / 'запись.wav'
    write_wav16(str(wav), tone_track(words_t))
    a = Api()
    st = a._rsum()
    st["audio"], st["out"] = str(wav), rs_out_dir(str(wav))
    st["result"] = rs_run(None, str(wav), table, st["out"], rec_words=rec)
    return a, st


def test_to_studio_copies_without_overwriting(tmp_path):
    a, st = _sums_api(tmp_path)
    wd = tmp_path / 'проект'
    tt = a._tts()
    tt["work_dir"] = str(wd)
    tt["var_sheets"] = {'sum_ru': {"categories": [
        {"key": 'million_ru', "label": 'м', "values": ['1', '2', '3']},
        {"key": 'hundred_ru', "label": 'с', "values": ['100', '200', '300']},
        {"key": 'thousand_ru', "label": 'т', "values": ['1', '2']},
        {"key": 'tenge_ru', "label": 'тг', "values": ['1', '2', '3']}]}}
    mine = wd / 'Значения' / 'sum_ru' / 'million_ru' / '2.wav'      # уже записанное в проекте
    os.makedirs(mine.parent)
    mine.write_bytes(b'RIFF-my-own-take')
    before = {f: md5(os.path.join(r, f)) for r, _, fs in os.walk(st["out"]) for f in fs}
    r = a.rsum_to_studio()
    assert r["copied"] == 10 and r["exist"] == 1 and r["nowhere"] == 1      # тысяча 3 — в таблице проекта нет
    assert mine.read_bytes() == b'RIFF-my-own-take'                         # своё не тронуто
    assert md5(str(wd / 'Значения' / 'sum_ru' / 'thousand_ru' / '1.wav')) == md5(os.path.join(st["out"], '1 - 99 тыс', '1.wav'))
    after = {f: md5(os.path.join(r_, f)) for r_, _, fs in os.walk(st["out"]) for f in fs if f != '.в_проект.json'}
    assert before == after                                                   # разбор не тронут
    r2 = a.rsum_to_studio()                                                  # повтор — ничего нового
    assert r2["copied"] == 0 and r2["exist"] == 11 and r2["updated"] == 0
    # кусок перерезали (новый файл в разборе) — наша прежняя копия в проекте обновляется…
    src = os.path.join(st["out"], '1 - 100 тенге', '1.wav')
    with open(src, 'ab') as f:
        f.write(b'\0\0')
    # …а файл, который в проекте кто-то правил, — нет
    edited = wd / 'Значения' / 'sum_ru' / 'tenge_ru' / '2.wav'
    with open(os.path.join(st["out"], '1 - 100 тенге', '2.wav'), 'ab') as f:
        f.write(b'\0\0')
    edited.write_bytes(b'RIFF-edited-by-hand')
    r3 = a.rsum_to_studio()
    assert r3["updated"] == 1
    assert md5(str(wd / 'Значения' / 'sum_ru' / 'tenge_ru' / '1.wav')) == md5(src)
    assert edited.read_bytes() == b'RIFF-edited-by-hand' and mine.read_bytes() == b'RIFF-my-own-take'


def test_listen_sums_opens_assembly_with_context(tmp_path):
    a, st = _sums_api(tmp_path)
    r = a.rsum_listen(1, 'thousand')
    assert not r.get("error"), r
    assert r["rsum"]["start"].startswith('начало (1 млн, 100') and r["rsum"]["end"].startswith('конец (1 тенге')
    assert [row["name"] for row in r["rows"]][:3] == ['1', '2', '3']
    ctx = os.path.dirname(a._ls()["pick"]["ru"]["start"])
    assert not ctx.startswith(st["out"])                                    # контекст — во временной папке
    assert a.rsum_listen(2, 'hundred').get("error")                         # во 2-й логике сотен нет


def test_transcribe_parallel_same_words_in_order():
    """Пачки параллельно (workers=3) — те же слова, в том же порядке и с тем же временем, что по одной."""
    import threading
    import time as _t
    from types import SimpleNamespace as NS
    from core.raw_sums import rs_transcribe, rs_envelope

    class FakeModel:
        """«Распознаёт» каждый звучащий кусок пачки словом «сто», время — по громкости (как настоящая)."""
        def transcribe(self, audio, **kw):
            _t.sleep(0.01 * (threading.get_ident() % 3))     # потоки заканчивают вразнобой
            db, thr = rs_envelope(audio, 16000)
            words, s = [], None
            for i, v in enumerate(list(db >= thr) + [False]):
                if v and s is None:
                    s = i
                elif not v and s is not None:
                    words.append(NS(word=' сто', start=s * 0.01, end=i * 0.01, probability=0.9))
                    s = None
            return [NS(text=' '.join(w.word for w in words), words=words)], None
    words_t, t = [], 0.5
    for k in range(40):
        words_t.append((t, t + 0.4))
        t += 0.7 + (1.2 if k % 5 == 4 else 0)
    from core.raw_sums import rs_to16k
    a16 = rs_to16k(tone_track(words_t), 8000)
    one = rs_transcribe(FakeModel(), a16, workers=1)
    par = rs_transcribe(FakeModel(), a16, workers=3)
    assert len(one) == 40 and [w[:3] for w in one] == [w[:3] for w in par]
    assert all(abs(w[1] - s) < 0.08 for w, (s, e) in zip(one, words_t))      # время — время записи


def test_transcribe_resumes_from_part_file(tmp_path):
    """Распознавание прервали — по файлу пачек продолжается с того же места: готовые пачки модель не считает заново,
    итог тот же, что без перерыва."""
    from types import SimpleNamespace as NS
    from core.raw_sums import rs_transcribe, rs_envelope, rs_to16k

    class Counting:
        calls = 0

        def transcribe(self, audio, **kw):
            Counting.calls += 1
            db, thr = rs_envelope(audio, 16000)
            words, s = [], None
            for i, v in enumerate(list(db >= thr) + [False]):
                if v and s is None:
                    s = i
                elif not v and s is not None:
                    words.append(NS(word=' сто', start=s * 0.01, end=i * 0.01, probability=0.9))
                    s = None
            return [NS(text=' '.join(w.word for w in words), words=words)], None
    words_t, t = [], 0.5
    for k in range(60):
        words_t.append((t, t + 0.4))
        t += 0.7 + (1.2 if k % 5 == 4 else 0)
    a16 = rs_to16k(tone_track(words_t), 8000)
    full = rs_transcribe(Counting(), a16)
    n_full, Counting.calls = Counting.calls, 0
    part = str(tmp_path / 'rec.part')
    seen = []

    def stop():
        return len(seen) >= 2                           # остановили после двух пачек
    rs_transcribe(Counting(), a16, stop=stop, on_pack=lambda i: i["words"] is not None and seen.append(1), part=part)
    first = Counting.calls
    with open(part, 'a', encoding='utf-8') as f:
        f.write('{"n": 9, "win": [[0')                   # недописанная строка (выключили компьютер) — не мешает
    Counting.calls = 0
    resumed = rs_transcribe(Counting(), a16, part=part)
    assert [w[:3] for w in resumed] == [w[:3] for w in full]
    assert Counting.calls == n_full - 2 and first >= 2


def test_worker_main_runs_and_resumes(tmp_path, monkeypatch):
    """Отдельный процесс разбора (здесь — в этом же процессе): пишет ход в state, куски в папку, распознавание в кэш."""
    import json as _json
    import core.raw_sums as R
    from types import SimpleNamespace as NS

    class Fake:
        def transcribe(self, audio, **kw):
            return [NS(text='', words=[])], None
    a, st = _sums_api(tmp_path)
    xl = tmp_path / 't.xlsx'
    wb = openpyxl.Workbook()
    for row in [['Начало', 'миллионы', 'тенге'], ['Сумма к оплате', 'один миллион', 'одна тенге']]:
        wb.active.append(row)
    wb.save(xl)
    monkeypatch.setattr(R, '_rs_load_model', lambda path, threads: Fake())
    job = {"wav": st["audio"], "table": str(xl), "out": str(tmp_path / 'out'), "model": 'x', "threads": 2,
           "cache": str(tmp_path / 'c.json'), "part": str(tmp_path / 'c.json.part'), "reuse": True,
           "state": str(tmp_path / 'state.json'), "stop": str(tmp_path / 'stop')}
    (tmp_path / 'job.json').write_text(_json.dumps(job, ensure_ascii=False), encoding='utf-8')
    assert R.rs_worker_main(str(tmp_path / 'job.json')) == 0
    state = _json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state["done"] and not state["error"] and state["stage"] == 'done'
    assert os.path.exists(job["cache"]) and not os.path.exists(job["part"])
    assert os.path.exists(os.path.join(job["out"], 'разбор.json'))


def _free_table(path):
    """Свободная таблица сумм (синтетика) — как в «Разборе записи сумм»."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Сумма к оплате', '1-50 миллионов', '51-100 к', None, '100-900', '1-50 тенге', None, None,
               'Сумма к оплате', '100-900'])
    rows = [('один миллион', 'пятьдесят одна', 'тысяча', 'сто', 'одна тенге', 'двадцать тенге'),
            ('два миллиона', 'пятьдесят две', 'тысячи', 'двесте', 'два тенге', 'двадцать одна тенге'),
            ('три миллиона', 'пятьдесят три', 'тысячи', 'триста', 'три тенге', 'двадцать два тенге')]
    for m, t, tw, h, tg, t2 in rows:
        ws.append([' С суммой задолженности', m, t, tw, h, tg, None, None, 'Сумма к оплате', h, t2])
    ws.append([None] * 8 + ['Сумма к оплате', 'сто тысяч', 'пятьдесят одна тенге'])
    wb.save(path)
    return str(path)


def test_studio_reads_free_sums_table(tmp_path):
    """Студия понимает свободную таблицу сумм: лист <sum_ru> с классами Студии и числами, «только переменные»,
    суммы по логикам 1 и 2, эталоны — Значения/sum_ru/<класс>/<число>.wav (туда же кладёт «В проект Студии»)."""
    from harness import Api
    from core.tts_flow import parse_tts_workbook
    xl = _free_table(tmp_path / 'суммы.xlsx')
    p = parse_tts_workbook(xl)
    sh = p["var_sheets"]["sum_ru"]
    got = {c["key"]: c["values"] for c in sh["categories"]}
    assert got == {'million_ru': ['1', '2', '3'], 'hundred_thousand_ru': ['100'], 'hundred_ru': ['100', '200', '300'],
                   'thousand_ru': ['51', '52', '53'], 'tenge_ru': ['1', '2', '3', '20', '21', '22', '51']}
    a = Api()
    st = a._tts()
    st["work_dir"] = str(tmp_path / 'проект')
    os.makedirs(st["work_dir"])
    r = a.tts_load_excel(xl)
    assert not r.get("error"), r
    assert r["free_sums"]["phrases"] == ['с суммой задолженности', 'сумма к оплате']
    assert a._tts()["vars_only"] and a._tts_is_sum_sheet(a._tts()["var_sheets"]["sum_ru"])
    sh = a._tts()["var_sheets"]["sum_ru"]
    assert a._tts_sum_rows(sh, 1)[:2] == [1_151_001, 2_252_002]          # 1 млн + (100 + 51) тыс + 1
    assert a._tts_sum_rows(sh, 2)[0] == 1_100_001
    assert a._tts_value_file('sum_ru', 'thousand_ru', '51').endswith(os.path.join('Значения', 'sum_ru', 'thousand_ru', '51.wav'))
