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
    assert len(main) == 8 and len([p for p in res["pieces"] if p["role"] == 'spare']) == 2
    assert os.path.exists(os.path.join(out, 'C тысячи', 'две тысячи.wav'))
    for p in res["pieces"]:
        assert os.path.getsize(os.path.join(out, p["file"])) > 44
    assert os.path.exists(os.path.join(out, 'B миллионы', 'один миллион.wav'))
    assert os.path.exists(os.path.join(out, '_запасные', 'B миллионы', 'два миллиона — попытка 1.wav'))
    for f in ('разбор.xlsx', '_проверка.xlsx', 'разбор.json'):
        assert os.path.exists(os.path.join(out, f))
    assert {m["row"] for m in res["missing"]} == {4, 2, 5}       # не прочитано — в списке «не найдено»
    # повторный разбор не перезаписывает прежнюю папку
    snap = {f: md5(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs}
    out2 = rs_out_dir(str(wav))
    assert out2 != out and out2.endswith('_куски_2')
    rs_run(None, str(wav), table, out2, rec_words=rec)
    assert snap == {f: md5(os.path.join(r, f)) for r, _, fs in os.walk(out) for f in fs}
