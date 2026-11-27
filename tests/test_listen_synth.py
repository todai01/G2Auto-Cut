"""Прослушка, синтез имён: свой образец с транскрипцией, «?» в конце, громкость по начальной фразе,
срезка тишины и вдохов, все без записи разом и «Стоп». Сервис синтеза не нужен: очередь — заглушка."""
import json
import os

import numpy as np
import pytest
from pydub import AudioSegment

from conftest import md5, snapshot, wav


class FakeWorker:
    def __init__(self):
        self.jobs, self.current = [], None

    def add(self, job, front=False):
        (self.jobs.insert if front else (lambda i, j: self.jobs.append(j)))(0, job)
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


def _tone(rate, ms, f=180, amp=0.05):
    t = np.arange(int(ms * rate / 1000)) / rate
    return amp * np.sin(2 * np.pi * f * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))


def _seg(x, rate):
    return AudioSegment((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes(), frame_rate=rate, sample_width=2, channels=1)


def test_level_keeps_full_audio_and_matches_start(lw, tmp_path):
    """Файл синтеза остаётся ПОЛНЫМ по длине (ничего не режем), громкость и формат — как у начальной фразы."""
    a, w = lw
    rate = 16000
    x = np.concatenate([np.zeros(int(0.6 * rate)), _tone(rate, 500), np.zeros(int(0.8 * rate))])
    seg = _seg(x, rate)
    dst = str(tmp_path / 'синтез.wav')
    seg.export(dst, format='wav')
    start = _seg(_tone(8000, 500, 200, 0.15), 8000)
    sp = str(tmp_path / 'start.wav')
    start.export(sp, format='wav')
    a._listen_level(dst, sp)
    out = AudioSegment.from_file(dst)
    assert abs(len(out) - len(seg)) <= 5                                # длительность — как пришла от сервиса
    assert out.frame_rate == 8000
    assert abs(a._loudness(out) - a._loudness(start)) < 2.5


def test_auto_cut_keeps_unvoiced_stop_at_end(tmp_path):
    """«Гизат»: тон, затвор (пауза), взрыв «т» — автосрезка не считает его шумом и не обрывает на «Гиза»."""
    from core.voice_trim import voice_span
    rate = 16000
    burst = 0.004 * np.random.RandomState(3).randn(int(0.07 * rate))
    x = np.concatenate([np.zeros(int(0.5 * rate)), _tone(rate, 450), np.zeros(int(0.09 * rate)), burst, np.zeros(int(0.8 * rate))])
    v0, v1, _ = voice_span(x, rate)
    end_burst = int((0.5 + 0.45 + 0.09 + 0.07) * 1000)
    assert v1 >= end_burst - 30, (v0, v1, end_burst)                    # граница — после взрыва, не на конце тона
    long_gap = np.concatenate([np.zeros(int(0.5 * rate)), _tone(rate, 450), np.zeros(int(0.45 * rate)), burst, np.zeros(int(0.8 * rate))])
    assert voice_span(long_gap, rate)[1] < int((0.5 + 0.45 + 0.3) * 1000)   # а шум после долгой паузы (вдох) — по-прежнему не слово


def test_autosynth_current_and_next(api, dialog, tmp_path, monkeypatch):
    """Автосинтез: текущее имя (впереди очереди) и два следующих без записи ставятся в очередь сами; на строке с записью — нет."""
    import openpyxl
    w = FakeWorker()
    monkeypatch.setattr(api, '_listen_synth_worker', w, raising=False)
    xl = tmp_path / 'имена.xlsx'
    wb = openpyxl.Workbook()
    for n in ['Гизат', 'Айгерим', 'Нурлан', 'Ерлан', 'Асем']:
        wb.active.append([n])
    wb.save(xl)
    out = tmp_path / 'результат'
    out.mkdir()
    api.listen_mode('var')
    dialog(str(xl), str(out))
    api.listen_pick_table()
    st = api.listen_pick_output()
    assert st["autosynth"] is True
    assert api.listen_autosynth_kick()["synth_busy"] == 0               # голос не выбран — ничего не уходит
    api.listen_set_voice(0, 'голос 1')
    api.listen_go(0, play=False)
    assert sorted(j.k for j in w.jobs) == [0, 1, 2] and api.listen_state()["synth_busy"] == 3
    api.listen_go(1, play=False)                                        # уже в очереди — второй раз не ставит; добавляется 3-я
    assert sorted(j.k for j in w.jobs) == [0, 1, 2, 3]
    api.listen_set_autosynth(False)
    api.listen_go(4, play=False)
    assert 4 not in [j.k for j in w.jobs]


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


class _Page:
    def page_ready(self):
        return None


def _table_session(api, dialog, tmp_path, names=('Гизат', 'Айгерим', 'Нурлан')):
    import openpyxl
    xl = tmp_path / 'имена.xlsx'
    wb = openpyxl.Workbook()
    for n in names:
        wb.active.append([n])
    wb.save(xl)
    out = tmp_path / 'результат'
    out.mkdir(exist_ok=True)
    api.listen_mode('var')
    dialog(str(xl), str(out))
    api.listen_pick_table()
    api.listen_pick_output()
    return out


def test_three_variants_folders_resume_and_stop(api, dialog, tmp_path, monkeypatch):
    """Каждое имя — N раз в «вариант_1…N»; рядом имена.json и _контекст со start; повтор докачивает только недостающее; Стоп."""
    w = FakeWorker()
    monkeypatch.setattr(api, '_listen_synth_worker', w, raising=False)
    calls = []

    def fake_page(page, v, etalon, etalon_text, text, lang, raw):
        calls.append(text)
        _seg(_tone(16000, 400, 150 + 20 * len(calls)), 16000).export(raw, format='wav')
        return 'тест'
    monkeypatch.setattr(api, '_listen_synth_page', fake_page)
    out = _table_session(api, dialog, tmp_path)
    start = wav_path = str(tmp_path / 'start.wav')
    _seg(_tone(8000, 600, 200, 0.15), 8000).export(start, format='wav')
    api._ls()["start"] = start
    assert api.listen_variants_start(3).get("error")                         # голос не выбран
    api.listen_set_voice(0, 'голос 1')
    r = api.listen_variants_start(3)
    assert r.get("ok") and r["state"]["variants"]["total"] == 9 and r["state"]["variants"]["running"]
    for j in list(w.jobs):
        w.jobs.remove(j)
        j(_Page())
    for v in (1, 2, 3):
        for nm in ('Гизат', 'Айгерим', 'Нурлан'):
            assert (out / f'вариант_{v}' / f'{nm}.wav').exists()
    assert len(calls) == 9 and all(t == 'Гизат?' for t in calls[:3])        # «?» — у каждого прогона
    ctx = json.loads((out / 'имена.json').read_text(encoding='utf-8'))
    assert ctx["names"] == ['Гизат', 'Айгерим', 'Нурлан'] and ctx["variants"] == 3 and (out / '_контекст' / 'start.wav').exists()
    vs = api.listen_state()["variants"]
    assert vs["done"] == 9 and not vs["running"] and not vs["errors_n"]
    files = {p: os.path.getsize(p) for p in map(str, out.rglob('*.wav'))}
    assert not [p for p in files if p.endswith('.part.wav') or p.endswith('.download')]
    # повтор: пропал один вариант — докачивается только он
    (out / 'вариант_2' / 'Айгерим.wav').unlink()
    calls.clear()
    assert api.listen_variants_start(3)["state"]["variants"]["total"] == 9
    for j in list(w.jobs):
        w.jobs.remove(j)
        j(_Page())
    assert len(calls) == 1 and (out / 'вариант_2' / 'Айгерим.wav').exists()
    # Стоп: ничего не синтезируется, готовое остаётся
    for f in list((out / 'вариант_3').glob('*.wav')):
        f.unlink()
    api.listen_variants_start(3)
    api.listen_variants_stop()
    calls.clear()
    for j in list(w.jobs):
        j(_Page())
    assert not calls and (out / 'вариант_1' / 'Гизат.wav').exists()


def test_variants_error_is_recorded_and_continues(api, dialog, tmp_path, monkeypatch):
    w = FakeWorker()
    monkeypatch.setattr(api, '_listen_synth_worker', w, raising=False)
    n = {"c": 0}

    def flaky(page, v, etalon, etalon_text, text, lang, raw):
        n["c"] += 1
        if n["c"] == 2:
            raise RuntimeError('сервис не ответил')
        _seg(_tone(16000, 300), 16000).export(raw, format='wav')
        return 'тест'
    monkeypatch.setattr(api, '_listen_synth_page', flaky)
    out = _table_session(api, dialog, tmp_path, names=('Гизат',))
    api.listen_set_voice(0, 'голос 1')
    api.listen_variants_start(3)
    for j in list(w.jobs):
        j(_Page())
    vs = api.listen_state()["variants"]
    assert vs["done"] == 2 and vs["errors_n"] == 1 and vs["errors"][0]["v"] == 2
    assert (out / 'вариант_1' / 'Гизат.wav').exists() and not (out / 'вариант_2' / 'Гизат.wav').exists() and (out / 'вариант_3' / 'Гизат.wav').exists()
