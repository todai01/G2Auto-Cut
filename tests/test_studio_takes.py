"""Студия: дубли не пропадают — смена таблицы, резервная копия tts_project.json, «Вернуть дубли» из «Чанки»."""
import json
import os
import shutil

import harness


def _disk_takes(wd):
    with open(os.path.join(wd, 'tts_project.json'), encoding='utf-8') as f:
        return json.load(f)["takes"]


def test_other_table_keeps_takes(studio, tmp_path):
    a, st, U, wd = studio
    n = len(st["takes"])
    moved = tmp_path / 'перенесли' / 'demo.xlsx'
    moved.parent.mkdir()
    shutil.copy(st["excel_path"], moved)                               # та же таблица в другой папке
    names = [U[t["unit"]]["name"] for t in st["takes"]]
    a.tts_load_excel(str(moved))
    st = a._tts()
    assert len(st["takes"]) == n and len(_disk_takes(wd)) == n
    assert [st["units"][t["unit"]]["name"] for t in st["takes"]] == names


def test_restore_from_backup(studio):
    a, st, U, wd = studio
    names = [U[t["unit"]]["name"] for t in st["takes"]]
    n = len(names)
    st["takes"] = []                                                   # дубли пропали
    a._tts_save()
    assert _disk_takes(wd) == []
    backups = [f for f in os.listdir(os.path.join(wd, '_Кэш')) if f.startswith('tts_project_до_')]
    assert len(backups) == 1
    assert a.tts_state()["free_chunks"] == n
    r = a.tts_restore_takes()
    assert r["backup"] == n and r["added"] == 0
    st = a._tts()
    assert sorted(st["units"][t["unit"]]["name"] for t in st["takes"]) == sorted(names)   # с привязкой к фразам
    assert len(_disk_takes(wd)) == n and a.tts_state()["free_chunks"] == 0


def test_restore_from_chunks_without_backup(studio):
    a, st, U, wd = studio
    n = len(st["takes"])
    data = json.load(open(os.path.join(wd, 'tts_project.json'), encoding='utf-8'))
    data["takes"] = []
    json.dump(data, open(os.path.join(wd, 'tts_project.json'), 'w', encoding='utf-8'))   # обнулили «снаружи», копии нет
    b = harness.Api()
    b.tts_open_project(wd)
    assert b.tts_state()["takes"] == []
    r = b.tts_restore_takes()
    assert r["added"] == n and r["backup"] == 0
    takes = b._tts()["takes"]
    assert all(t["unit"] is None and os.path.exists(os.path.join(wd, t["file"])) for t in takes)
    assert [t["chunk"] for t in takes] == sorted(t["chunk"] for t in takes)
    assert b.tts_restore_takes().get("error")                           # второй раз — нечего возвращать
    assert len(_disk_takes(wd)) == n


def test_single_delete_makes_no_backup(studio):
    a, st, U, wd = studio
    a.tts_take_delete(0)
    d = os.path.join(wd, '_Кэш')
    assert not os.path.isdir(d) or not [f for f in os.listdir(d) if f.startswith('tts_project_до_')]


class _AudExport:
    """Audacity-заглушка: Export2 пишет заданный звук (как будто там срезали лишнее)."""
    def __init__(self):
        self.next = None

    def send_command(self, cmd, auto_start=False, timeout=20):
        if cmd.startswith('Export2:') and self.next is not None:
            self.next.export(cmd.split('Filename="', 1)[1].split('"', 1)[0], format='wav')
        return '[]' if cmd.startswith('GetInfo') else 'OK'


def test_audacity_round_trip_twice_wave_follows(studio, monkeypatch):
    """Дубль в Audacity и обратно дважды: волна «Сборки» (исходник клипа) — от последней правки, не от первой."""
    from pydub import AudioSegment
    a, st, U, wd = studio
    monkeypatch.setattr(a, '_ensure_audacity_ready', lambda: True, raising=False)
    aud = _AudExport()
    a.audacity = aud
    i = 0
    src = AudioSegment.from_file(os.path.join(wd, st["takes"][i]["file"]))
    raws = []
    for cut_to in (len(src) - 300, len(src) - 900):                    # каждый раз срезали лишнее
        assert a.tts_send_to_audacity(i).get("status") == 'ok'
        aud.next = src[:cut_to]
        assert not a.tts_take_from_audacity(i).get("error")
        clips = a.tts_clips_load(i)["clips"]
        assert len(clips) == 1 and abs((clips[0]["b"] - clips[0]["a"]) - cut_to) <= 5
        raws.append(clips[0]["raw"])
        assert abs(len(AudioSegment.from_file(os.path.join(wd, st["takes"][i]["file"]))) - cut_to) <= 5
    assert raws[0] != raws[1] and all(os.path.exists(r) for r in raws)
