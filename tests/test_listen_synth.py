"""Прослушка, синтез имён: свой образец с транскрипцией, «?» в конце, громкость по начальной фразе,
срезка тишины и вдохов, все без записи разом и «Стоп». Сервис синтеза не нужен: очередь — заглушка."""
import os

import numpy as np
import pytest
from pydub import AudioSegment

from conftest import md5, snapshot, wav


class FakeWorker:
    def __init__(self):
        self.jobs, self.current = [], None

    def add(self, job, front=False):
        self.jobs.append(job)
        return True

    def clear(self):
        j, self.jobs = self.jobs, []
        return j

    def is_alive(self):
        return True


@pytest.fixture
def lw(listen, monkeypatch, tmp_path):
    w = FakeWorker()
    monkeypatch.setattr(listen, '_listen_synth_worker', w, raising=False)
    monkeypatch.setattr(type(listen), 'LISTEN_SAMPLE_FILE', str(tmp_path / 'sample.json'))
    listen.__dict__.pop('_listen_smp', None)
    listen.listen_set(None, 'uni')                                       # имена без цифр (Kia, Mazda) — вид «УНИВ»
    return listen, w


def idx(api, name):
    return next(i for i, r in enumerate(api.listen_state()["rows"]) if r["name"] == name)


def test_sample_voice_and_qmark(lw, tmp_path):
    a, w = lw
    assert a.listen_set_voice(-2).get("error")                          # образца ещё нет
    smp = wav(str(tmp_path / 'образец.wav'), 'меня зовут гизат')
    assert a.listen_set_sample(smp, '').get("error")                    # без транскрипции — нельзя
    st = a.listen_set_sample(smp, '  Меня зовут   Гизат ')
    assert st["voice"]["index"] == -2 and st["sample"] == {"name": 'образец.wav', "text": 'Меня зовут Гизат'}
    a.listen_set_qmark(True)
    k = idx(a, 'Mazda')
    r = a.listen_synth(k, 'Гизат', 'ru', take=True)
    assert r.get("queued") and len(w.jobs) == 1
    assert a._ls()["synth"][k]["text"] == 'Гизат?'
    a.listen_synth(idx(a, 'Kia'), 'Гизат.', 'ru')                     # точка в конце — заменяется вопросом
    assert a._ls()["synth"][idx(a, 'Kia')]["text"] == 'Гизат?'
    a.__dict__.pop('_listen_smp', None)                                  # образец переживает перезапуск
    assert a.listen_state()["sample"]["text"] == 'Меня зовут Гизат'


def test_level_trims_silence_and_matches_start(lw, tmp_path):
    a, w = lw
    rate = 16000
    t = np.arange(int(0.5 * rate)) / rate
    voice = 0.05 * np.sin(2 * np.pi * 180 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
    breath = 0.01 * np.random.RandomState(1).randn(int(0.2 * rate))
    x = np.concatenate([np.zeros(int(0.6 * rate)), breath, np.zeros(int(0.3 * rate)), voice, np.zeros(int(0.8 * rate))])
    seg = AudioSegment((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes(), frame_rate=rate, sample_width=2, channels=1)
    dst = str(tmp_path / 'синтез.wav')
    seg.export(dst, format='wav')
    start = AudioSegment((np.clip(0.4 * np.sin(2 * np.pi * 200 * t), -1, 1) * 32767).astype('<i2').tobytes(),
                         frame_rate=8000, sample_width=2, channels=1)
    sp = str(tmp_path / 'start.wav')
    start.export(sp, format='wav')
    a._listen_level(dst, sp)
    out = AudioSegment.from_file(dst)
    assert len(out) < len(seg) - 1200                                   # тишина и вдох по краям срезаны
    assert 450 <= len(out) <= 750
    assert out.frame_rate == 8000                                       # формат — как у начальной фразы
    assert abs(a._loudness(out) - a._loudness(start)) < 2.5            # громкость — как у начальной фразы


def test_synth_all_and_stop(lw):
    a, w = lw
    a.listen_set_voice(0, 'голос 1')
    st = a.listen_state()
    missing = [r for r in st["rows"] if not r["path"]]
    r = a.listen_synth_all('ru')
    assert r["queued"] == len(missing) == len(w.jobs) > 0
    assert r["state"]["synth_busy"] == len(missing)
    assert a.listen_synth_all('ru')["queued"] == 0                     # уже в очереди — второй раз не ставит
    s = a.listen_synth_stop()
    assert s["dropped"] == len(missing) and s["state"]["synth_busy"] == 0 and not w.jobs


def test_table_only_no_recordings(api, dialog, tmp_path, monkeypatch):
    """Только таблица имён и пустая папка результата: имена без записи, синтез (очередь) и «Взять» кладут файл в папку."""
    import openpyxl
    w = FakeWorker()
    monkeypatch.setattr(api, '_listen_synth_worker', w, raising=False)
    xl = tmp_path / 'имена.xlsx'
    wb = openpyxl.Workbook()
    wb.active.append(['Имя'])
    for n in ['Гизат', 'Айгерим', 'Нурлан']:
        wb.active.append([n])
    wb.save(xl)
    out = tmp_path / 'результат'
    out.mkdir()
    api.listen_mode('var')
    dialog(str(xl), str(out))
    assert api.listen_pick_table()["rows"][0]["name"] == 'Гизат'      # таблица — до папки, записей нет
    st = api.listen_pick_output()
    assert not st.get("error") and st["folder"] == str(out) and st["found"] == 0 and st["qmark"] is True
    assert [r["name"] for r in st["rows"]] == ['Гизат', 'Айгерим', 'Нурлан'] and not any(r["path"] for r in st["rows"])
    api.listen_set_voice(0, 'голос 1')
    r = api.listen_synth(1, 'Айгерим', 'ru', take=True)
    assert r.get("queued") and api._ls()["synth"][1]["text"] == 'Айгерим?'
    # сервис «ответил»: готовый файл → «Взять» кладёт его в папку результата как запись строки
    from pydub import AudioSegment
    f = api._ls()["synth"][1]["file"]
    os.makedirs(os.path.dirname(f), exist_ok=True)
    AudioSegment.silent(600, frame_rate=8000).export(f, format='wav')
    api._ls()["synth"][1]["status"] = 'ready'
    t = api.listen_synth_take(1)
    assert t.get("ok") and os.path.exists(str(out / 'Айгерим.wav'))
    rows = {x["name"]: x for x in api.listen_state()["rows"]}
    assert rows['Айгерим']["path"] and not rows['Гизат']["path"]
