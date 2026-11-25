"""«Сборка сумм» (core/sum_build.py) и начальные фразы из записи фраз — только синтетика (тоны вместо речи)."""
import glob
import hashlib
import json
import os
import shutil

import openpyxl

from core.raw_sums import RS_PHR_DIR, rs_phrase_table, rs_run, rs_start_texts, rs_read_table
from core.sum_build import SB_CFG, SB_OUT, sb_rows, sb_variants
from test_raw_sums import _sums_api, tone_track, write_wav16


def md5(p):
    with open(p, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def _table(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in [['Начало', 'миллионы', 'сотни', 'тысячи', None, 'тенге'],
                ['Сумма к оплате', 'один миллион', 'сто', 'одна', 'тысяча', 'одна тенге'],
                ['Сумма к оплате', 'два миллиона', 'двести', 'две', 'тысячи', 'два тенге'],
                ['Сумма к оплате', 'три миллиона', 'триста', 'три', 'тысячи', 'три тенге']]:
        ws.append(row)
    p = str(tmp_path / 'таблица.xlsx')
    wb.save(p)
    return p


def _snap(out):
    return {os.path.relpath(p, out): md5(p) for p in glob.glob(os.path.join(out, '**', '*.wav'), recursive=True)
            if not os.path.relpath(p, out).startswith(SB_OUT)}


def test_rows_and_variants(tmp_path):
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    rows = sb_rows(rs_read_table(xl))
    assert [r["text"] for r in rows][0] == 'один миллион сто одна тысяча одна тенге'
    assert rows[0]["start"] == 'сумма к оплате' and rows[0]["logic"] == 1
    assert [c["rel"] for c in rows[0]["cells"]] == ['1 - 100 млн/1.wav', '100 - 900/100.wav', '1 - 99 тыс/1.wav', '1 - 100 тенге/1.wav']
    out = st["out"]
    os.makedirs(os.path.join(out, '_запасные', '100 - 900'))
    for k in (2, 1):
        shutil.copy2(os.path.join(out, '100 - 900', '100.wav'), os.path.join(out, '_запасные', '100 - 900', f'100 — попытка {k}.wav'))
    v = sb_variants(out, '100 - 900/100.wav')
    assert [x["label"] for x in v] == ['основной', 'попытка 1', 'попытка 2']


def test_build_choose_spare_tune_export_keeps_sources(tmp_path):
    """Выбор запасного, правки, авто-настройка, готовые файлы: исходные куски не меняются,
    «_готово» — в той же раскладке; настройки переживают перезапуск («сборка.json»)."""
    import harness
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    out = st["out"]
    os.makedirs(os.path.join(out, '_запасные', '100 - 900'))
    spare = os.path.join(out, '_запасные', '100 - 900', '100 — попытка 1.wav')
    write_wav16(spare, tone_track([(0.05, 0.25)]))
    before = _snap(out)
    s = a.sb_load(out, xl)
    assert not s.get("error") and len(s["rows"]) == 3 and s["starts"] == [{"text": 'сумма к оплате', "file": None}]
    rid = s["rows"][0]["id"]
    row = a.sb_row(rid)
    assert [x["kind"] for x in row["segs"]] == ['piece'] * 4
    r = a.sb_set(rid, '100 - 900/100.wav', 'var', '_запасные/100 - 900/100 — попытка 1.wav')
    assert r["segs"][1]["var"].endswith('попытка 1.wav')
    assert a.sb_set(rid, '100 - 900/100.wav', 'var', '../../чужой.wav').get("error")
    a.sb_set(rid, '1 - 100 млн/1.wav', 'tail', 30)
    a.sb_set(rid, '1 - 100 млн/1.wav', 'gain', -2)
    p = a.sb_play(rid)
    assert p["playing"] and p["ms"] > 0
    auto = a.sb_auto()["auto"]
    assert auto["target"] is not None and set(auto["gaps"]) >= {'million', 'hundred', 'thousand'}
    assert all(40 <= v <= 500 for v in auto["gaps"].values())
    e = a.sb_export()
    assert e["pieces"] == 12
    assert os.path.exists(os.path.join(out, SB_OUT, '100 - 900', '100.wav'))
    assert _snap(out) == before                          # куски разбора и запасные — байт в байт
    a.sb_mark(rid, 'ok')
    # перезапуск: всё из «сборка.json»
    a2 = harness.Api()
    s2 = a2.sb_load(out)                                 # таблица — из сборка.json
    assert not s2.get("error") and s2["rows"][0]["mark"] == 'ok' and s2["auto"]
    r2 = a2.sb_row(rid)
    assert r2["segs"][1]["var"].endswith('попытка 1.wav') and r2["segs"][0]["tail"] == 30 and r2["segs"][0]["gain"] == -2.0
    cfg = json.load(open(os.path.join(out, SB_CFG), encoding='utf-8'))
    assert cfg["table"] == xl


def test_start_phrases_cut_from_phrase_recording_and_night(tmp_path):
    """Запись фраз → «_фразы_переменные/Фразы/<текст>.wav»; ночной проход подставляет их как начальные фразы,
    делает авто-настройку и готовые файлы (с «Фразы_Переменные»)."""
    import harness
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    out = st["out"]
    texts = rs_start_texts(rs_read_table(xl))
    assert texts == ['сумма к оплате']
    words_t, rec, t = [], [], 0.5
    for take in range(2):                                  # прочитано дважды — основной последний
        for w in ['сумма', 'к', 'оплате']:
            rec.append((w, t, t + 0.3, 1.0))
            words_t.append((t, t + 0.3))
            t += 0.45
        t += 1.2
    wav = tmp_path / 'фразы.wav'
    write_wav16(str(wav), tone_track(words_t))
    res = rs_run(None, str(wav), rs_phrase_table(texts), os.path.join(out, RS_PHR_DIR), rec_words=rec)
    got = os.path.join(out, RS_PHR_DIR, 'Фразы', 'сумма к оплате.wav')
    assert os.path.exists(got) and any(pc["role"] == 'main' for pc in res["pieces"])
    a2 = harness.Api()
    r = a2.sb_night(out, xl)
    assert r["pieces"] == 12 and r["ctx"] == 1
    assert os.path.exists(os.path.join(out, SB_OUT, 'Фразы_Переменные', 'сумма к оплате.wav'))
    row = a2.sb_row(a2.sb_state()["rows"][0]["id"])
    assert row["segs"][0]["kind"] == 'start'


def test_open_from_rsum_window_and_pick_table(tmp_path):
    """Окно разбора: прежняя папка кусков находится сама, «Сборка сумм» открывается без модели;
    папка без «сборка.json» — таблицу спрашивает."""
    import harness
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    a2 = harness.Api()
    harness.DIALOG.append([st["audio"]])
    assert a2.rsum_pick_audio()["ready"] > 0
    a2.rsum_load_table(xl)
    s = a2.sb_open_rsum()
    assert not s.get("error") and len(s["rows"]) == 3
    assert getattr(a2, '_rsum_model_obj', None) is None
    os.remove(os.path.join(st["out"], SB_CFG))
    a3 = harness.Api()
    harness.DIALOG.append([st["out"]])
    harness.DIALOG.append([xl])
    s3 = a3.sb_pick()
    assert not s3.get("error") and len(s3["rows"]) == 3


def test_worker_cuts_phrases_only(tmp_path, monkeypatch):
    """Куски уже есть — процесс режет только начальные фразы (в «_фразы_переменные»), суммы не трогает."""
    import core.raw_sums as R
    from types import SimpleNamespace as NS

    class Fake:
        def transcribe(self, audio, **kw):
            return [NS(text='', words=[])], None
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    before = _snap(st["out"])
    monkeypatch.setattr(R, '_rs_load_model', lambda path, threads: Fake())
    job = {"wav": st["audio"], "table": xl, "out": st["out"], "model": 'x', "threads": 2, "cache": None, "part": None,
           "reuse": True, "phr_wav": st["audio"], "only_phrases": True,
           "state": str(tmp_path / 'state.json'), "stop": str(tmp_path / 'stop')}
    (tmp_path / 'job.json').write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    assert R.rs_worker_main(str(tmp_path / 'job.json')) == 0
    state = json.loads((tmp_path / 'state.json').read_text(encoding='utf-8'))
    assert state["done"] and not state["error"] and state["info"]["phr"]["of"] == 1
    assert _snap(st["out"]) == before


def test_start_end_files_from_rsum_window(tmp_path):
    """«Начало…» / «Конец…» в окне разбора: свои файлы — в «Сборку сумм» для всех строк и в готовые файлы;
    при следующем выборе записи подтягиваются из «сборка.json»."""
    import harness
    a, st = _sums_api(tmp_path)
    xl = _table(tmp_path)
    s_f, e_f = tmp_path / 'start.wav', tmp_path / 'end.wav'
    write_wav16(str(s_f), tone_track([(0.1, 0.6)]))
    write_wav16(str(e_f), tone_track([(0.1, 0.4)]))
    a2 = harness.Api()
    harness.DIALOG.append([st["audio"]])
    a2.rsum_pick_audio()
    a2.rsum_load_table(xl)
    harness.DIALOG.append([str(s_f)])
    a2.rsum_pick_ctx('start')
    harness.DIALOG.append([str(e_f)])
    r = a2.rsum_pick_ctx('end')
    assert r["ctx_start"] == str(s_f) and r["ctx_end"] == str(e_f)
    s = a2.sb_open_rsum()
    assert s["start_any"] == 'start.wav' and s["end"] == 'end.wav'
    kinds = [x["kind"] for x in a2.sb_row(s["rows"][0]["id"])["segs"]]
    assert kinds[0] == 'start' and kinds[-1] == 'end'
    e = a2.sb_export()
    assert e["ctx"] == 2 and os.path.exists(os.path.join(st["out"], SB_OUT, 'Фразы_Переменные', 'end.wav'))
    a3 = harness.Api()
    harness.DIALOG.append([st["audio"]])
    r3 = a3.rsum_pick_audio()
    assert r3["ctx_start"] == str(s_f) and r3["ctx_end"] == str(e_f)
