"""Прослушка: операции с файлами записей — ничего не теряется и не перезаписывается молча."""
import os
import types

import pytest

from conftest import md5, snapshot, wav


def rows(api):
    return {r["name"]: r for r in api.listen_state()["rows"]}


def idx(api, name):
    return next(i for i, r in enumerate(api.listen_state()["rows"]) if r["name"] == name)


def no_tmp(folder):
    return [p for p in snapshot(folder) if '.tmp_' in p or p.endswith('.swap')]


# ---------- виды и счётчик ----------
def test_views_and_totals(listen):
    assert list(rows(listen)) == ['AUDI 80', 'AUDI 100', 'BMW X5', 'Lada']
    listen.listen_set(lang='kz')
    r = rows(listen)
    assert r['BMW X5']["path"] is None and r['AUDI 80']["path"].replace(os.sep, '/').endswith('kz_mark/AUDI 80.wav')
    listen.listen_set(lang='uni')
    assert list(rows(listen)) == ['Kia', 'Mazda']
    t = listen.listen_totals()
    assert t["ru"] == [0, 4, 4] and t["kz"] == [0, 3, 4] and t["uni"] == [0, 1, 2] and t["all"] == [0, 8, 10]


def test_lang_toggle_keeps_row(listen):
    listen.listen_go(idx(listen, 'Lada'), play=False)
    listen.listen_set(lang='kz')
    st = listen.listen_state()
    assert st["rows"][st["pos"]]["name"] == 'Lada'


def test_number_names(api, dialog, tmp_path):
    import openpyxl
    wav(str(tmp_path / 'v' / 'ru' / '1.wav'))
    wav(str(tmp_path / 'v' / 'kz' / '1.wav'))
    xl = tmp_path / 't.xlsx'
    wb = openpyxl.Workbook()
    wb.active.append(['<late_ru>', '<late_kz>'])
    wb.active.append(['одно опоздание', 'бір рет'])
    wb.save(xl)
    dialog(str(tmp_path / 'v' / 'ru'), str(xl))                 # выбрали саму папку ru — берётся родитель
    api.listen_pick_folder()
    api.listen_pick_table()
    r = api.listen_state()["rows"][0]
    assert r["name"] == 'одно опоздание' and r["path"].replace(os.sep, '/').endswith('v/ru/1.wav')
    api.listen_set(lang='kz')
    r = api.listen_state()["rows"][0]
    assert r["name"] == 'бір рет' and r["path"].replace(os.sep, '/').endswith('v/kz/1.wav')


# ---------- «⇄ не та запись» ----------
def test_swap_exchanges_with_backups(listen, marks):
    folder = marks[0]
    ru = os.path.join(folder, 'ru_mark')
    wav(os.path.join(ru, '_до_правок', 'AUDI 80.wav'), 'исходник восемьдесят')
    a, b = md5(os.path.join(ru, 'AUDI 80.wav')), md5(os.path.join(ru, 'AUDI 100.wav'))
    bk = md5(os.path.join(ru, '_до_правок', 'AUDI 80.wav'))
    before = len(snapshot(folder))
    r = listen.listen_swap(idx(listen, 'AUDI 80'), idx(listen, 'AUDI 100'))
    assert r.get("ok"), r
    assert md5(os.path.join(ru, 'AUDI 100.wav')) == a and md5(os.path.join(ru, 'AUDI 80.wav')) == b
    assert md5(os.path.join(ru, '_до_правок', 'AUDI 100.wav')) == bk
    assert not os.path.exists(os.path.join(ru, '_до_правок', 'AUDI 80.wav'))
    assert len(snapshot(folder)) == before and not no_tmp(folder)
    assert md5(os.path.join(folder, 'kz_mark', 'AUDI 80.wav')) != a       # другой язык не тронут


def test_swap_attach_to_empty_row(listen, marks):
    ru = os.path.join(marks[0], 'ru_mark')
    os.remove(os.path.join(ru, 'Lada.wav'))
    listen._listen_scan()
    a = md5(os.path.join(ru, 'AUDI 80.wav'))
    r = listen.listen_swap(idx(listen, 'AUDI 80'), idx(listen, 'Lada'))
    assert r.get("ok"), r
    assert md5(os.path.join(ru, 'Lada.wav')) == a and not os.path.exists(os.path.join(ru, 'AUDI 80.wav'))
    assert rows(listen)['AUDI 80']["path"] is None


def test_swap_refuses_to_overwrite_stale_backup(listen, marks):
    folder = marks[0]
    ru = os.path.join(folder, 'ru_mark')
    os.remove(os.path.join(ru, 'Lada.wav'))
    wav(os.path.join(ru, '_до_правок', 'Lada.wav'), 'старый исходник')    # осталось от прежней записи
    wav(os.path.join(ru, '_до_правок', 'AUDI 80.wav'), 'исходник')
    listen._listen_scan()
    before = snapshot(folder)
    r = listen.listen_swap(idx(listen, 'AUDI 80'), idx(listen, 'Lada'))
    assert "error" in r and 'Lada.wav' in r["error"]
    assert snapshot(folder) == before                                   # ничего не тронуто


def test_swap_rolls_back_on_failure(listen, marks, monkeypatch):
    folder = marks[0]
    ru = os.path.join(folder, 'ru_mark')
    wav(os.path.join(ru, '_до_правок', 'AUDI 80.wav'), 'исходник')
    before = snapshot(folder)
    real, calls = os.replace, []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 3:                                             # сбой посередине (файл занят)
            raise PermissionError('занят')
        return real(src, dst)
    monkeypatch.setattr(os, 'replace', flaky)
    r = listen.listen_swap(idx(listen, 'AUDI 80'), idx(listen, 'AUDI 100'))
    monkeypatch.setattr(os, 'replace', real)
    assert "error" in r and 'возвращено' in r["error"]
    assert snapshot(folder) == before


def test_move_batch_chain_allowed(tmp_path):
    from core.listen_mode import ListenMixin
    a, b = wav(str(tmp_path / 'a.wav'), 'а'), wav(str(tmp_path / 'b.wav'), 'бэ')
    ma, mb = md5(a), md5(b)
    t = str(tmp_path / 'a.tmp')
    assert ListenMixin._listen_move_batch([(a, t), (b, a), (t, b)]) is None   # место освобождает более ранний шаг
    assert md5(a) == mb and md5(b) == ma and not os.path.exists(t)
    assert ListenMixin._listen_move_batch([(a, b)]) is not None               # прямое перезаписывание — нельзя
    assert md5(a) == mb and md5(b) == ma


# ---------- универсалы ----------
def test_uni_move_from_both_languages(listen, marks):
    folder = marks[0]
    ru, kz, uni = (os.path.join(folder, d) for d in ('ru_mark', 'kz_mark', 'uni_mark'))
    wav(os.path.join(ru, '_до_правок', 'Lada.wav'), 'исходник лада')
    m_ru, m_kz, m_bk = md5(os.path.join(ru, 'Lada.wav')), md5(os.path.join(kz, 'Lada.wav')), md5(os.path.join(ru, '_до_правок', 'Lada.wav'))
    total = len(snapshot(folder))
    info = listen.listen_uni_info()
    assert info["n"] == 2 and info["ru"] == 1 and info["kz"] == 1 and info["dups"] == 1
    r = listen.listen_uni_move()
    assert r["moved"] == 2 and not r["failed"]
    assert md5(os.path.join(uni, 'Lada.wav')) == m_ru
    assert md5(os.path.join(uni, '_дубли_kz', 'Lada.wav')) == m_kz
    assert md5(os.path.join(uni, '_до_правок', 'Lada.wav')) == m_bk
    assert not os.path.exists(os.path.join(ru, 'Lada.wav')) and not os.path.exists(os.path.join(kz, 'Lada.wav'))
    assert len(snapshot(folder)) == total                               # ни один файл не пропал
    listen.listen_set(lang='uni')
    assert rows(listen)['Lada']["path"].replace(os.sep, '/').endswith('uni_mark/Lada.wav')   # «_дубли_kz» не сканируется
    assert listen.listen_uni_info()["n"] == 0


def test_uni_move_keeps_existing(listen, marks):
    folder = marks[0]
    uni = os.path.join(folder, 'uni_mark')
    wav(os.path.join(uni, '_до_правок', 'Lada.wav'), 'чужой исходник')    # в общей папке уже лежит исходник с этим именем
    keep = md5(os.path.join(uni, '_до_правок', 'Lada.wav'))
    wav(os.path.join(folder, 'ru_mark', '_до_правок', 'Lada.wav'), 'свой исходник')
    r = listen.listen_uni_move()
    assert r["failed"] and md5(os.path.join(uni, '_до_правок', 'Lada.wav')) == keep
    assert os.path.exists(os.path.join(folder, 'ru_mark', 'Lada.wav'))  # не перенесённое — на месте


# ---------- запись поверх: правка, синтез, Audacity ----------
def test_edit_save_atomic_and_keeps_source(listen, marks):
    folder = marks[0]
    p = rows(listen)['AUDI 80']["path"]
    orig = md5(p)
    assert listen.listen_edit_save(p, [[100, 600]]).get("ok")
    bk = os.path.join(os.path.dirname(p), '_до_правок', 'AUDI 80.wav')
    assert md5(bk) == orig and md5(p) != orig
    first = md5(p)
    assert listen.listen_edit_save(p, [[0, 300]], gain=-3).get("ok")      # правка — от исходника, без накопления
    assert md5(bk) == orig and md5(p) != first
    assert not no_tmp(folder)


def test_put_audio_failure_leaves_file(listen):
    p = rows(listen)['AUDI 80']["path"]
    orig = md5(p)

    def broken(tmp):
        open(tmp, 'wb').write(b'half')
        raise OSError('диск')
    with pytest.raises(OSError):
        listen._listen_put_audio(p, broken)
    assert md5(p) == orig and not no_tmp(os.path.dirname(p))


def _synth(listen, k, tmp_path, text):
    f = wav(str(tmp_path / f'synth_{text}.wav'), text)
    listen._ls()["synth"][k] = {"status": "ready", "file": f, "lang": "ru"}
    return md5(f)


def test_synth_take_twice_keeps_original(listen, tmp_path):
    k = idx(listen, 'AUDI 80')
    p = rows(listen)['AUDI 80']["path"]
    d = os.path.join(os.path.dirname(p), '_до_правок')
    orig = md5(p)
    s1 = _synth(listen, k, tmp_path, 'первый')
    assert listen.listen_synth_take(k).get("ok")
    assert md5(p) == s1 and md5(os.path.join(d, 'AUDI 80_до_синтеза.wav')) == orig
    listen.listen_edit_save(p, [[0, 400]])                            # правка синтеза: исходник — синтез
    s2 = _synth(listen, k, tmp_path, 'второй')
    assert listen.listen_synth_take(k).get("ok")
    assert md5(p) == s2
    assert md5(os.path.join(d, 'AUDI 80_до_синтеза.wav')) == orig        # самый первый — не затёрт
    assert md5(os.path.join(d, 'AUDI 80_до_синтеза_2.wav')) == s1        # промежуточный — рядом


def test_synth_take_new_file_for_missing_row(listen, marks, tmp_path):
    listen.listen_set(lang='kz')
    k = idx(listen, 'BMW X5')
    s = _synth(listen, k, tmp_path, 'бмв')
    listen._ls()["synth"][k]["lang"] = 'kz'
    r = listen.listen_synth_take(k)
    assert r.get("ok") and md5(os.path.join(marks[0], 'kz_mark', 'BMW X5.wav')) == s


class FakeAudacity:
    def __init__(self, src):
        self.src = src

    def send_command(self, cmd):
        if cmd.startswith('Export2:'):
            out = cmd.split('Filename="')[1].split('"')[0]
            import shutil
            shutil.copyfile(self.src, out)


def test_from_audacity_twice_keeps_original(listen, tmp_path, monkeypatch):
    p = rows(listen)['AUDI 80']["path"]
    d = os.path.join(os.path.dirname(p), '_до_правок')
    orig = md5(p)
    monkeypatch.setattr(listen, '_ensure_audacity_ready', lambda: True, raising=False)
    outs = []
    for n in (1, 2):
        src = wav(str(tmp_path / f'aud{n}.wav'), f'правка {n}')
        listen.audacity = FakeAudacity(src)
        assert listen.listen_to_audacity({"path": p}).get("ok")
        r = listen.listen_from_audacity(p)
        assert r.get("ok"), r
        outs.append(md5(p))
    assert md5(os.path.join(d, 'AUDI 80_до_audacity.wav')) == orig
    assert outs[0] != outs[1] and outs[0] != orig
    assert not no_tmp(os.path.dirname(p))


def test_from_audacity_other_record_refused(listen):
    p = rows(listen)['AUDI 80']["path"]
    listen._listen_aud = rows(listen)['AUDI 100']["path"]
    orig = md5(p)
    assert "error" in listen.listen_from_audacity(p) and md5(p) == orig


# ---------- проигрывание цепочки ----------
def _chain_api(listen, tmp_path):
    """Играет в стаб-плеере; возвращает (api, список сыгранных файлов)."""
    played = []
    listen.player.play = lambda p: played.append((p, open(p, 'rb').read()))
    listen.player.stop = lambda: None
    return listen, played


def test_play_unique_files_and_latest_wins(listen, tmp_path):
    import threading
    from pydub import AudioSegment
    api, played = _chain_api(listen, tmp_path)
    p = rows(api)['AUDI 80']["path"]
    res = []

    def go():
        res.append(api.listen_play({"path": p}, None, None, None))
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert any(r.get("playing") for r in res)
    for _p, data in played:                                  # каждый запуск — целый читаемый файл
        assert data[:4] == b'RIFF'
    names = [pp for pp, _ in played]
    assert len(set(names)) == len(names)                     # файлы разные — не пишут друг в друга
    assert all(r.get("playing") or r.get("error") == 'skip' for r in res)


def test_play_seek(listen, tmp_path):
    from pydub import AudioSegment
    api, played = _chain_api(listen, tmp_path)
    p = rows(api)['AUDI 80']["path"]
    full = api.listen_play({"path": p}, None, None, 'var')
    r = api.listen_play({"path": p}, None, None, 'var', None, 'var', 300)
    assert r["from"] == 300 and abs(r["duration"] - full["duration"]) < 0.01
    got = AudioSegment.from_file(played[-1][0])
    assert abs(len(got) - (full["duration"] * 1000 - 300)) < 30
    big = api.listen_play({"path": p}, None, None, 'var', None, 'var', 10 ** 6)   # за краем — не тишина, а конец
    assert 0 < len(AudioSegment.from_file(played[-1][0])) <= 60


def test_play_mixed_formats(listen, tmp_path):
    """Начало и конец другой частоты / каналов / разрядности — цепочка собирается целой, не рваной."""
    from pydub import AudioSegment
    api, played = _chain_api(listen, tmp_path)
    p = rows(api)['AUDI 80']["path"]
    base = AudioSegment.from_file(p)
    a = str(tmp_path / 'st.wav')
    b = str(tmp_path / 'en.wav')
    base.set_frame_rate(16000).set_channels(2).set_sample_width(3).export(a, format='wav')
    base.set_frame_rate(48000).set_sample_width(4).export(b, format='wav')
    r = api.listen_play({"path": p}, {"path": a}, {"path": b}, None)
    got = AudioSegment.from_file(played[-1][0])
    want = sum(m["ms"] for m in r["marks"])
    assert abs(len(got) - want) < 40 and got.channels == 2 and got.sample_width == 2
    assert got.rms > 0
