"""«В Audacity» из «Разбора записи сумм» — без Audacity: команды пишутся в список, звук — синтетика."""
import glob
import os
import wave

from core.rsum_audacity import AUD_DESK, aud_plan, aud_render
from test_raw_sums import _sums_api, md5, tone_track, write_wav16


class FakeAudacity:
    """Отвечает как Audacity на GetInfo; Import2 / NewLabelTrack добавляют дорожку."""
    def __init__(self):
        self.cmds, self.tracks = [], 0

    def send_command(self, cmd, auto_start=False, timeout=20):
        self.cmds.append(cmd)
        if cmd.startswith('GetInfo: Type=Tracks'):
            return '[' + ','.join('{}' for _ in range(self.tracks)) + ']'
        if cmd.startswith('Import2:') or cmd == 'NewLabelTrack:':
            self.tracks += 1
        if cmd == 'RemoveTracks:':
            self.tracks = 0
        if cmd.startswith('SaveProject2:'):
            p = cmd.split('Filename="', 1)[1].rstrip('"')
            open(p, 'wb').close()
        return 'BatchCommand finished: OK'


def test_plan_order_and_desk(tmp_path):
    a, st = _sums_api(tmp_path)
    out = st["out"]
    write_wav16(os.path.join(out, '1 - 100 тенге', '0.wav'), tone_track([(0.05, 0.3)]))
    s, e = tmp_path / 's.wav', tmp_path / 'e.wav'
    write_wav16(str(s), tone_track([(0.1, 0.5)]), sr=16000)
    write_wav16(str(e), tone_track([(0.1, 0.4)]))
    plan = aud_plan(out, str(s), str(e))
    assert [t["name"] for t in plan] == ['Сборка', '1 - 100 млн', '100 - 900', '1 - 99 тыс', '1 - 100 тенге']
    assert [l for l, _p in plan[-1]["pieces"]] == ['1', '2', '3', '0']        # ноль — в конце
    path, spots, rate = aud_render(plan[0], str(tmp_path), 8000)
    assert rate == 8000 and [l for l, *_ in spots] == ['start', 'end']
    assert abs((spots[1][1] - spots[0][2]) - AUD_DESK) < 0.01                 # свободное место на «Сборке»
    with wave.open(path) as w:
        assert w.getframerate() == 8000 and w.getnchannels() == 1


def test_to_audacity_builds_tracks_and_keeps_pieces(tmp_path, monkeypatch):
    a, st = _sums_api(tmp_path)
    out = st["out"]
    s = tmp_path / 's.wav'
    write_wav16(str(s), tone_track([(0.1, 0.5)]))
    st["ctx_start"] = str(s)
    before = {p: md5(p) for p in glob.glob(os.path.join(out, '**', '*.wav'), recursive=True)}
    fake = FakeAudacity()
    a.audacity = fake
    monkeypatch.setattr(a, '_ensure_audacity_ready', lambda: True, raising=False)
    monkeypatch.setattr(a, '_block_if_audacity_ambiguous', lambda: False, raising=False)
    r = a.rsum_to_audacity()
    assert r.get("ok"), r
    assert [t["name"] for t in r["tracks"]] == ['Сборка', '1 - 100 млн', '100 - 900', '1 - 99 тыс', '1 - 100 тенге']
    assert [t["n"] for t in r["tracks"]] == [1, 3, 3, 3, 3]
    names = [c for c in fake.cmds if c.startswith('SetTrack:')]
    assert names[0] == 'SetTrack: Track=0 Name="Сборка"' and names[2] == 'SetTrack: Track=2 Name="1 - 100 млн"'
    assert sum(c == 'SplitDelete:' for c in fake.cmds) == 0 + 2 * 4                # паузы между кусками классов
    labels = [c for c in fake.cmds if c.startswith('SetLabel:')]
    assert len(labels) == 13 and labels[-1] == 'SetLabel: Label=12 Text="3"'
    assert r["project"] and os.path.exists(r["project"]) and r["project"].endswith('.aup3')
    assert {p: md5(p) for p in before} == before                                 # куски не тронуты


def test_to_audacity_without_pieces(tmp_path):
    import harness
    a = harness.Api()
    a._rsum()["out"] = str(tmp_path)
    assert a.rsum_to_audacity().get("error")
