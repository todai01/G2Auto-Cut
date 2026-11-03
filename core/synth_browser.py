"""Синтез через внутренний сервис в браузере (Playwright): открыть страницу,
выбрать голос и язык, вставить текст, «Синтезировать», скачать результат.

Общее для Студии (суммы, синтез фраз), «Прослушки» и «Синтеза по таблице».
Браузер и страница живут в одном отдельном потоке (_SynthWorker) — так
требует Playwright; запросы к сервису идут строго по очереди."""
import collections
import os
import subprocess
import threading
import time
import wave

from pydub import AudioSegment

from utils.audio_player import _read_audio
from utils.wav_io import wav_layout

SYNTH_URL = os.environ.get('GVOX_SYNTH_URL') or 'http://ia-app5-lp3:3124/'


# Шаги на сайте — селекторы из вашей инструкции. Сайт поменяется — правим здесь.
SYNTH_SEL = {
    "clone_tab": "body > main > nav > button:nth-child(2)",
    "lang": "body > main > section.panel.active > form > label:nth-child(1) > select",
    "etalon_file": "body > main > section.panel.active > form > label:nth-child(2) > input[type=file]",
    "etalon_text": "body > main > section.panel.active > form > label:nth-child(3) > input[type=text]",
    "text": "body > main > section.panel.active > form > label:nth-child(4) > textarea",
    "submit": "body > main > section.panel.active > form > button",
}


# Готовый голос (без эталона) — «Прослушка переменных».
SYNTH_PRESET_SEL = {
    "tab": "body > main > nav > button:nth-child(1)",      # если вкладка не открыта сама
    "voice": "#preset-voice", "voice_index": 3,             # option:nth-child(4)
    "lang": "#preset-lang",
    "text": "body > main > section.panel.active > form > label:nth-child(3) > textarea",
    "submit": "body > main > section.panel.active > form > button",
}


SYNTH_LANG_INDEX = {'ru': 0, 'kz': 1}     # option:nth-child(1) — русский, (2) — казахский


# Готовые голоса и языки сервиса (номер в списке с 0: option:nth-child(номер + 1)).
SYNTH_PRESET_VOICES = [(3, 'Голос 4 — основной'), (7, 'Голос 8 — турецкий')]


SYNTH_LANGS = [(0, 'Русский'), (1, 'Казахский'), (2, 'Турецкий')]


SYNTH_TIMEOUT_S = 180                      # ждать результат синтеза не дольше


# Скачать звук из <audio> на странице (если сервис отдаёт плеер, а не ссылку).
_JS_FETCH_B64 = """async (src) => {
    const r = await fetch(src); const b = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
}"""


# Что сейчас лежит в результате: ссылка на скачивание и/или плеер.
_JS_RESULT = """() => {
    const p = document.querySelector('section.panel.active') || document;
    const a = p.querySelector('#download, a[download]') || document.querySelector('#download, a[download]');
    const au = p.querySelector('audio') || document.querySelector('audio');
    return [a ? (a.href || '') : '', au ? (au.currentSrc || au.src || '') : ''];
}"""


# Следим за страницей: любой новый / обновлённый результат (плеер, ссылка) — даже
# если сервис отдаёт его по той же ссылке, что и в прошлый раз.
_JS_ARM = """() => {
    window.__gvoxNew = 0;
    if (window.__gvoxObs) window.__gvoxObs.disconnect();
    const sel = 'audio, source, a[download], #download';
    const hit = n => n && n.nodeType === 1 && (n.matches(sel) || !!n.querySelector(sel));
    const o = new MutationObserver(ms => { if (ms.some(m => m.type === 'attributes' ? hit(m.target) : [...m.addedNodes].some(hit))) window.__gvoxNew = 1; });
    o.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['src', 'href'] });
    window.__gvoxObs = o;
}"""


def preset_pick(page, select_sel, index, tries=4):
    """Выбрать в списке вариант № index+1 (option:nth-child) и убедиться, что выбор
    остался: страница может догрузить / перерисовать список и сбросить его."""
    opt = f'{select_sel} > option:nth-child({index + 1})'
    page.wait_for_selector(opt, state='attached', timeout=20000)      # список голосов уже загружен
    for _ in range(tries):
        val = page.eval_on_selector(opt, 'o => o.value')
        page.select_option(select_sel, value=val) if val else page.select_option(select_sel, index=index)
        page.wait_for_timeout(250)
        ok = page.eval_on_selector(select_sel, '(e, i) => e.selectedIndex === i', index)
        if ok:
            return page.eval_on_selector(opt, 'o => o.textContent.trim()')
    raise RuntimeError("Сервис синтеза сбрасывает выбор голоса — не удалось выставить нужный.")


def synth_collect(page, submit_sel, raw, after_click=None):
    """Нажать «Синтезировать» и сохранить результат в raw: сервис отдаёт файл на
    скачивание, ссылку на него или плеер <audio>. after_click — что сделать сразу
    после нажатия, до скачивания (например, заново выбрать сброшенный голос)."""
    before = page.evaluate(_JS_RESULT)
    downloads = []

    def handler(d):                      # сервис мог сразу отдать файл на скачивание
        downloads.append(d)
    page.on("download", handler)
    try:
        page.evaluate(_JS_ARM)
        page.click(submit_sel)
        if after_click:
            after_click()
        t_end = time.time() + SYNTH_TIMEOUT_S
        now = before
        while time.time() < t_end:
            page.wait_for_timeout(300)
            if downloads:
                break
            now = page.evaluate(_JS_RESULT)
            if (now[0] and now[0] != before[0]) or (now[1] and now[1] != before[1]):
                break
            if (now[0] or now[1]) and page.evaluate("() => window.__gvoxNew"):
                page.wait_for_timeout(300)                     # дать сервису дописать ссылку
                now = page.evaluate(_JS_RESULT)
                break
        else:
            raise RuntimeError("Сервис не вернул результат за 3 минуты.")
        fresh_audio = now[1] and now[1] != before[1] and not (now[0] and now[0] != before[0])
        if downloads:
            downloads[0].save_as(raw)
        elif now[0] and not fresh_audio:
            with page.expect_download(timeout=60000) as dl:
                page.locator('section.panel.active #download, section.panel.active a[download], #download').first.click()
            dl.value.save_as(raw)
        else:
            import base64
            data = base64.b64decode(page.evaluate(_JS_FETCH_B64, now[1]))
            with open(raw, 'wb') as f:
                f.write(data)
    finally:
        try:
            page.remove_listener("download", handler)
        except Exception:
            pass


def _write_pcm16(dst, x, rate):
    """float [-1..1] (кадры или кадры×каналы) → обычный WAV 16 бит."""
    import numpy as np
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak > 0.98:                                   # без перегруза
        x = x * (0.98 / peak)
    pcm = np.round(x * 32767).astype('<i2')
    with wave.open(dst, 'wb') as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


def clean_wav(src, dst):
    """Ответ сервиса → обычный WAV 16 бит без «сюрпризов». Сервисы синтеза
    часто отдают WAV «потоком» (размер в заголовке 0 или FFFFFFFF), float
    32 бит или MP3 — такой файл проигрыватель Windows читает с ошибками:
    треск, обрывы, «робот». Декодирует ffmpeg; нет его — читаем сами."""
    ff = getattr(AudioSegment, 'converter', None) or 'ffmpeg'
    try:
        subprocess.run([ff, '-y', '-v', 'error', '-i', src, '-c:a', 'pcm_s16le', dst], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=60)
        if wav_layout(dst) and os.path.getsize(dst) > 100:
            return
    except Exception:
        pass
    x, rate = _read_audio(src)
    _write_pcm16(dst, x, rate)


class _SynthWorker(threading.Thread):
    """Очередь заданий на синтез и один браузер с открытым сервисом."""

    def __init__(self, owner):
        super().__init__(daemon=True)
        self.owner = owner
        self.jobs = collections.deque()
        self.cv = threading.Condition()
        self.pw = self.browser = self.page = None
        self.current = None
        self.stop_now = False

    # ---- очередь ----
    def add(self, k, front=False):
        with self.cv:
            if k == self.current or k in self.jobs:
                if front and k in self.jobs:
                    self.jobs.remove(k)
                    self.jobs.appendleft(k)
                return False
            (self.jobs.appendleft if front else self.jobs.append)(k)
            self.cv.notify()
            return True

    def clear(self):
        with self.cv:
            dropped = list(self.jobs)
            self.jobs.clear()
            return dropped

    def run(self):
        while True:
            with self.cv:
                while not self.jobs:
                    self.cv.wait()
                k = self.jobs.popleft()
                self.current = k
            try:
                if callable(k):
                    k(self)                          # разовое задание (синтез для дубля)
                else:
                    self.owner._synth_job(k, self)
            except Exception as e:                   # браузер упал и т.п. — начнём заново
                self._close()
                if not callable(k):
                    self.owner._synth_failed(k, str(e))
            finally:
                with self.cv:
                    self.current = None

    # ---- браузер ----
    def _close(self):
        for obj in (self.browser, self.pw):
            try:
                if obj is self.pw and obj is not None:
                    obj.stop()
                elif obj is not None:
                    obj.close()
            except Exception:
                pass
        self.pw = self.browser = self.page = None

    def page_ready(self):
        if self.page is not None:
            try:
                self.page.title()
                return self.page
            except Exception:
                self._close()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Для синтеза нужен модуль Playwright. В командной строке выполните:\n"
                               "pip install playwright")
        self.pw = sync_playwright().start()
        args = ["--window-position=-32000,-32000", "--window-size=1600,1000", "--mute-audio"]
        last = None
        exe = os.environ.get('GVOX_BROWSER')               # свой путь к браузеру, если задан
        for channel in (("exe",) if exe else ()) + ("chrome", "msedge", None):   # Chrome / Edge, иначе свой
            try:
                kw = {"headless": False, "args": args}
                if channel == "exe":
                    kw["executable_path"] = exe
                elif channel:
                    kw["channel"] = channel
                self.browser = self.pw.chromium.launch(**kw)
                break
            except Exception as e:
                last = e
        if self.browser is None:
            self._close()
            raise RuntimeError(f"Не удалось открыть браузер (Chrome / Edge): {last}")
        self.page = self.browser.new_page(accept_downloads=True)
        try:
            self.page.goto(SYNTH_URL, timeout=30000)
            self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            self._close()
            raise RuntimeError(f"Сервис синтеза не открылся ({SYNTH_URL}). Проверьте, что он доступен из этой сети.")
        if getattr(self, 'tab', 'clone') == 'preset':          # готовый голос: вкладка, где есть #preset-voice
            active = 'section.panel.active ' + SYNTH_PRESET_SEL["voice"]
            if not self.page.locator(active).count():
                self.page.click(SYNTH_PRESET_SEL["tab"])
                self.page.wait_for_selector(active, state="visible", timeout=10000)
        else:
            self.page.click(SYNTH_SEL["clone_tab"])
        self.page.wait_for_timeout(400)
        return self.page
