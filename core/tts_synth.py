"""4 этап: суммы голосом диктора — клонирование по эталону через внутренний
сервис синтеза, затем режим «Суммы».

Как это работает:
  1. Эталон — запись диктора с суммой (например «один миллион сто одна
     тысяча один тенге») и её текст словами.
  2. Список сумм строится по логике режима «Суммы»: у каждого яруса свой
     диапазон (миллионы 1–100, сотни 100–900, тысячи 1–99, тенге 1–100), на
     каждом шаге все ярусы берут следующее значение, дошедший до потолка —
     остаётся на последнем: 1 101 001, 2 202 002, … Текст — словами (RU / KZ).
  3. Робот открывает сервис (Chrome за краем экрана, как в G2Synth), вкладка
     «Клонирование»: язык, файл эталона, текст эталона, текст суммы →
     «Синтезировать» → скачивает результат.
     Гибрид (по умолчанию): слова «миллион», «тысяча», «тенге» — живые: вы
     сами выделяете их на дорожке эталона (и доп. записей); на сервис уходят только числа
     («два», «двести две», «два»), потом всё склеивается в одну сумму.
  4. Вы слушаете; не понравилось — пересинтез; понравилось — «Одобрить»:
     тишина по краям обрезается, файл ложится в «Синтез_суммы_RU/» (или _KZ).
  5. «Перейти в режим «Суммы»» — режим открывается сразу на этой папке.

Браузер и страница живут в одном отдельном потоке (так требует Playwright),
запросы к сервису идут строго по очереди."""

import collections
import os
import struct
import shutil
import subprocess
import tempfile
import threading
import wave
import time

import webview
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

from core.num_words import kz_words, ru_words
from utils.audio_player import _read_audio, resample
from utils.wav_io import _write_wav, wav_kind, wav_layout, wav_slice

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
SYNTH_TIMEOUT_S = 180                      # ждать результат синтеза не дольше
SYNTH_DIR = 'Синтез_суммы'          # + _RU / _KZ: у каждого языка своя папка (режим «Суммы» — по одному языку)
SYNTH_VARIANTS = '_варианты'
SYNTH_ETALON = '_эталон'
SYNTH_WORDS = '_слова'                      # живые слова из эталона: миллион.wav, тысячи.wav…
SYNTH_TAIL = {'ru': 'хорошо', 'kz': 'жақсы'}   # слово-запас: сервис срезает конец записи
SYNTH_PREFETCH = 2                         # пока слушаете — столько следующих уже синтезируется

# Живые слова (гибрид). В русском у слова три формы — каждую нужно услышать
# в какой-нибудь записи; нет формы — это слово уйдёт в синтез вместе с числом.
UNIT_FORMS = {
    'ru': ['миллион', 'миллиона', 'миллионов', 'тысяча', 'тысячи', 'тысяч', 'тенге'],
    'kz': ['миллион', 'мың', 'теңге'],
}
_UNIT_ALIAS = {'ru': {'теңге': 'тенге', 'милион': 'миллион', 'милиона': 'миллиона', 'милионов': 'миллионов'},
               'kz': {'тенге': 'теңге', 'мын': 'мың', 'милион': 'миллион'}}
GLUE_XFADE_MS = 12          # число → живое слово: стык без паузы, с короткой перекрёстной склейкой
GLUE_GAP_MS = 70            # живое слово → следующее число (если в эталоне не измерили своё)

# Ярусы режима «Суммы» (как в variables_handler): логика 1 и 2.
_TIER_VALUES = {
    'millions': list(range(1, 101)),
    'hundreds': list(range(100, 1000, 100)),
    'hundred_thousands': list(range(100, 1000, 100)),
    'thousands': list(range(1, 100)),
    'tenge': list(range(1, 101)),
}
SYNTH_LOGICS = {
    1: ['millions', 'hundreds', 'thousands', 'tenge'],          # 1 101 001, 2 202 002…
    2: ['millions', 'hundred_thousands', 'tenge'],              # 1 100 001, 2 200 002…
}

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


def synth_sums(logic):
    """Список сумм по логике режима «Суммы»: [(n, {ярус: значение})]."""
    tiers = SYNTH_LOGICS.get(int(logic), SYNTH_LOGICS[1])
    rows = max(len(_TIER_VALUES[t]) for t in tiers)
    out = []
    for k in range(rows):
        parts = {t: _TIER_VALUES[t][min(k, len(_TIER_VALUES[t]) - 1)] for t in tiers}
        group = parts.get('hundreds', 0) + parts.get('hundred_thousands', 0) + parts.get('thousands', 0)
        n = parts.get('millions', 0) * 1_000_000 + group * 1000 + parts.get('tenge', 0)
        out.append((n, parts))
    return out


def synth_text(n, lang):
    return f"{kz_words(n)} теңге" if lang == 'kz' else f"{ru_words(n)} тенге"


def unit_form(word, lang):
    """Слово → форма «миллион/тысячи/тенге…» или None (это число)."""
    w = word.lower().replace('ё', 'е').strip(' .,!?;:«»"\'()-—')
    w = _UNIT_ALIAS.get(lang, {}).get(w, w)
    return w if w in UNIT_FORMS.get(lang, ()) else None


def split_sum_text(text, lang):
    """«два миллиона двести две тысячи два тенге» →
    [('num','два'), ('unit','миллиона'), ('num','двести две'), ('unit','тысячи'), ('num','два'), ('unit','тенге')]"""
    out = []
    for w in str(text).split():
        f = unit_form(w, lang)
        if f:
            out.append(('unit', f))
        elif out and out[-1][0] == 'num':
            out[-1] = ('num', out[-1][1] + ' ' + w)
        else:
            out.append(('num', w))
    return out


def synth_plan(text, lang, bank):
    """Что синтезировать, а что взять живым: [(kind, текст)], kind — 'synth'
    или 'live'. Формы, которой нет в живых словах, синтезируем вместе с числом."""
    plan = []
    for kind, t in split_sum_text(text, lang):
        if kind == 'unit' and t in bank:
            plan.append(['live', t])
        elif plan and plan[-1][0] == 'synth':
            plan[-1][1] += ' ' + t
        else:
            plan.append(['synth', t])
    return plan


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


def write_like(dst, x, rate, like):
    """float-звук → WAV ровно в формате файла like (частота, каналы,
    разрядность, float/int) — чтобы склейка на дорожке шла байт в байт."""
    import numpy as np
    lay = wav_layout(like)
    kind = wav_kind(like)
    if not lay or not kind:
        raise RuntimeError("Не понял формат записи дубля.")
    fmt, _pos, _size, block, out_rate = lay
    ch = struct.unpack('<H', fmt[2:4])[0] if len(fmt) >= 4 else 1
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if rate != out_rate:
        x = resample(x, rate, out_rate)
    x = x.mean(axis=1, keepdims=True) if x.shape[1] != ch else x
    if x.shape[1] != ch:
        x = np.repeat(x[:, :1], ch, axis=1)
    peak = float(np.abs(x).max()) if x.size else 0.0
    if peak > 0.98:
        x = x * (0.98 / peak)
    flt, bits = kind
    if flt == 'float':
        data = x.astype('<f4' if bits == 32 else '<f8').tobytes()
    elif bits == 8:
        data = np.clip(np.round(x * 127 + 128), 0, 255).astype(np.uint8).tobytes()
    elif bits == 16:
        data = np.round(x * 32767).astype('<i2').tobytes()
    elif bits == 24:
        v = np.round(x * 8388607).astype('<i4').reshape(-1)
        data = np.stack([v & 255, (v >> 8) & 255, (v >> 16) & 255], axis=1).astype(np.uint8).tobytes()
    else:
        data = np.round(x * 2147483647.0).astype('<i4').tobytes()
    _write_wav(dst, fmt, data)
    return int(len(x) * 1000 / out_rate)


def _mono(path):
    """(float32 моно, частота)."""
    x, rate = _read_audio(path)
    return (x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]).astype('float32'), rate


def _frames_rms(x, rate, ms=5):
    import numpy as np
    n = max(1, int(rate * ms / 1000))
    k = len(x) // n
    if not k:
        return np.zeros(0), n
    return np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(axis=1) + 1e-12), n


def _pink(n, seed=None):
    """Розовый шум (как «шипение» комнаты/микрофона, без резкого верха)."""
    import numpy as np
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(n)
    f = np.fft.rfft(w)
    k = np.arange(len(f))
    k[0] = 1
    y = np.fft.irfft(f / np.sqrt(k), n=n)
    return (y / (np.sqrt((y ** 2).mean()) + 1e-12)).astype('float32')


def room_noise(ref_path, rate, n, seed=None):
    """Фон «как в записи»: тихие места образца (между словами, до и после
    речи) — шум комнаты и микрофона — склеиваются и подкладываются под
    синтез нужной длины. Тихих мест мало — розовый шум того же уровня.
    None — в образце нет шума (цифровая тишина)."""
    import numpy as np
    try:
        x, r = _mono(ref_path)
    except Exception:
        return None
    e, hop = _frames_rms(x, r, 20)
    if len(e) < 5:
        return None
    floor = float(np.percentile(e, 10))
    if floor <= 10 ** (-85 / 20):
        return None
    quiet = e <= floor * 2.0
    parts, k = [], 0
    while k < len(e):
        if quiet[k]:
            j = k
            while j < len(e) and quiet[j]:
                j += 1
            if j - k >= 4:                                    # от 80 мс, без краёв речи
                parts.append(x[(k + 1) * hop:(j - 1) * hop])
            k = j
        else:
            k += 1
    fade = max(1, int(r * 0.010))
    bed = np.zeros(0, dtype='float32')
    for p in parts:
        if len(p) <= 2 * fade:
            continue
        if len(bed) >= fade:
            t = np.linspace(0, np.pi / 2, fade, dtype='float32')
            bed = np.concatenate([bed[:-fade], bed[-fade:] * np.cos(t) + p[:fade] * np.sin(t), p[fade:]])
        else:
            bed = p.astype('float32')
    if len(bed) < 0.25 * r:
        bed = _pink(r, seed) * floor                      # тишины мало — синтетический фон того же уровня
    if r != rate:
        bed = resample(bed[:, None], r, rate)[:, 0]
    rng = np.random.default_rng(seed)
    out = np.zeros(n, dtype='float32')
    xf = max(1, min(int(rate * 0.030), len(bed) // 4))
    pos, first = 0, True
    while pos < n:
        start = int(rng.integers(0, max(1, len(bed) // 2))) if first else 0
        chunk = bed[start:]
        m = min(len(chunk), n - pos)
        seg = chunk[:m].copy()
        if not first and m > xf and pos >= xf:            # стык повторов — плавно
            t = np.linspace(0, 1, xf, dtype='float32')
            out[pos - xf:pos] = out[pos - xf:pos] * (1 - t) + seg[:xf] * t
            out[pos:pos + m - xf] = seg[xf:]
            pos += m - xf
        else:
            out[pos:pos + m] = seg
            pos += m
        first = False
    return out


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


class TtsSynthMixin:

    # ---------------- состояние ----------------

    def _synth(self):
        """Состояние синтеза. У каждого языка свои эталон, текст эталона и
        одобренные суммы (sy["per"][lang]); sy["items"] — список текущего языка."""
        st = self._tts()
        sy = st.get("synth")
        if not sy:
            sy = st["synth"] = {"lang": st.get("lang", "ru"), "logic": 1, "items": [], "per": {}}
        sy.setdefault("per", {})
        if "etalon" in sy:                                       # старый формат — один эталон на всё
            sy["per"].setdefault(sy.get("lang", "ru"), {"etalon": sy.pop("etalon"),
                                                         "etalon_text": sy.pop("etalon_text", ''), "store": {}})
        for lg in ('ru', 'kz'):
            sy["per"].setdefault(lg, {"etalon": None, "etalon_text": '', "store": {}})
            sy["per"][lg].setdefault("words", {})                # живые слова: форма → {file, src, gap}
        sy.setdefault("hybrid", True)
        if not sy["items"]:
            self._synth_build(sy)
        return sy

    @staticmethod
    def _synth_lang(sy):
        return sy["per"][sy["lang"]]

    # ---------------- фон комнаты под синтезом ----------------

    def _synth_noise_cfg(self):
        sy = self._synth()
        return sy.setdefault("noise", {"on": True, "db": 0})

    def tts_synth_noise(self, on=None, db=None):
        """Фон под синтезом: on — включён, db — громче/тише фона образца."""
        with self._synth_lock():
            cfg = self._synth_noise_cfg()
            if on is not None:
                cfg["on"] = bool(on)
            if db is not None:
                cfg["db"] = max(-12, min(12, int(db)))
        self._tts_save()
        return dict(cfg)

    def _add_noise(self, x, rate, ref):
        """Подложить под синтез фон из образца голоса (если включено)."""
        cfg = self._synth_noise_cfg()
        if not cfg.get("on") or not ref or not os.path.exists(ref) or not len(x):
            return x
        bed = room_noise(ref, rate, len(x))
        if bed is None:
            return x
        if x.ndim > 1:
            bed = bed[:, None]
        return x + bed * float(10 ** (cfg.get("db", 0) / 20))

    def _noise_file(self, path, ref):
        """То же для готового файла синтеза (перезаписывает его, WAV 16 бит)."""
        cfg = self._synth_noise_cfg()
        if not cfg.get("on"):
            return
        x, rate = _mono(path)
        y = self._add_noise(x, rate, ref)
        if y is not x:
            _write_pcm16(path, y, rate)

    def _synth_lock(self):
        lock = getattr(self, '_synth_lk', None)
        if lock is None:
            lock = self._synth_lk = threading.RLock()
        return lock

    def _synth_build(self, sy):
        """Список сумм текущего языка и логики. Уже сделанное (варианты,
        одобренные) хранится по языку и числу — переключения его не теряют."""
        for it in sy.get("items", []):                           # запомнить, что было
            lg = it.get("lang", sy["lang"])
            if lg in sy["per"]:
                sy["per"][lg]["store"][str(it["n"])] = {k: it.get(k) for k in
                                                        ("text", "status", "variant", "file", "tries", "error", "plan")}
        cur = self._synth_lang(sy)
        items = []
        for k, (n, parts) in enumerate(synth_sums(sy.get("logic", 1))):
            it = {"k": k, "n": n, "parts": parts, "lang": sy["lang"], "text": synth_text(n, sy["lang"]),
                  "status": "idle", "variant": None, "file": None, "tries": 0, "error": None}
            old = cur["store"].get(str(n))
            if old:
                it.update({k2: v for k2, v in old.items() if v is not None})
                if it["status"] in ("queued", "working"):              # не доделано — с нуля
                    it["status"] = "ready" if it.get("variant") else "idle"
            items.append(it)
        sy["items"] = items
        if not cur.get("etalon_text") and items:
            cur["etalon_text"] = items[0]["text"]

    def _synth_dir(self, *sub, lang=None):
        wd = self._tts().get("work_dir")
        if not wd:
            return None
        lg = lang or (self._tts().get("synth") or {}).get("lang", "ru")
        return os.path.join(wd, f"{SYNTH_DIR}_{lg.upper()}", *sub)

    def tts_synth_state(self):
        with self._synth_lock():
            sy = self._synth()
            items = [{**{k: it.get(k) for k in ("k", "n", "text", "status", "error", "tries", "parts", "plan")},
                      "has_variant": bool(it.get("variant") and os.path.exists(it["variant"])),
                      "has_file": bool(it.get("file") and os.path.exists(it["file"]))} for it in sy["items"]]
            w = getattr(self, '_synth_worker', None)
            cur = self._synth_lang(sy)
            return {"etalon": os.path.basename(cur["etalon"]) if cur.get("etalon") else None,
                    "etalon_ok": bool(cur.get("etalon") and os.path.exists(cur["etalon"])),
                    "etalon_text": cur.get("etalon_text", ''), "lang": sy["lang"], "logic": sy.get("logic", 1),
                    "items": items, "has_project": bool(self._tts().get("work_dir")),
                    "approved": sum(1 for it in sy["items"] if it["status"] == "approved"),
                    "queue": len(w.jobs) + (1 if w and w.current is not None else 0) if w else 0,
                    "folder": self._synth_dir(), "hybrid": sy.get("hybrid", True),
                    "noise": dict(sy.get("noise") or {"on": True, "db": 0}),
                    "words": self._synth_words_info(sy)}

    def _synth_words_info(self, sy):
        """Нужные формы слов (по текстам сумм) и какие из них уже есть живыми."""
        cur = self._synth_lang(sy)
        need = set()
        for it in sy["items"]:
            need.update(t for kind, t in split_sum_text(it["text"], sy["lang"]) if kind == 'unit')
        bank = cur.get("words", {})
        out = []
        for f in UNIT_FORMS[sy["lang"]]:
            w = bank.get(f)
            ok = bool(w and os.path.exists(w.get("file", '')))
            if f in need or ok:
                out.append({"form": f, "ok": ok, "src": w.get("src") if ok else None, "need": f in need})
        return out

    def _synth_push(self, k=None, message=None, error=None):
        self._tts_push({"stage": "synth", "k": k, "message": message, "error": error})

    # ---------------- настройки ----------------

    def tts_synth_pick_etalon(self):
        """Эталон — запись диктора с суммой. Копируем в проект, чтобы не потерялся."""
        st = self._tts()
        if not st.get("work_dir"):
            picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not picked:
                return {"error": "cancel"}
            self._tts_attach_folder(picked if isinstance(picked, str) else picked[0])
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        self._synth()
        dst_dir = self._synth_dir(SYNTH_ETALON)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        with self._synth_lock():
            self._synth_lang(self._synth())["etalon"] = dst
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_setup(self, lang=None, logic=None, etalon_text=None, hybrid=None):
        """Язык, логика сумм, текст эталона. Смена языка/логики — новый список
        (одобренные с тем же числом и языком остаются)."""
        with self._synth_lock():
            sy = self._synth()
            rebuild = (lang in ('ru', 'kz') and lang != sy["lang"]) or \
                (logic in (1, 2, '1', '2') and int(logic) != sy.get("logic", 1))
            if rebuild:
                self.tts_synth_stop()
                self._synth_build(sy)                            # сохранить сделанное по прежнему языку
                if lang in ('ru', 'kz'):
                    sy["lang"] = lang
                if logic in (1, 2, '1', '2'):
                    sy["logic"] = int(logic)
                sy["items"] = []                                 # пересобрать под новый язык/логику
                self._synth_build(sy)
            if etalon_text is not None:
                self._synth_lang(sy)["etalon_text"] = str(etalon_text).strip()
            if hybrid is not None:
                sy["hybrid"] = bool(hybrid)
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_set_text(self, k, text):
        with self._synth_lock():
            sy = self._synth()
            if 0 <= k < len(sy["items"]):
                sy["items"][k]["text"] = str(text).strip() or synth_text(sy["items"][k]["n"], sy["lang"])
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_play_etalon(self):
        cur = self._synth_lang(self._synth())
        if not cur.get("etalon") or not os.path.exists(cur["etalon"]):
            return {"error": "Эталон не выбран."}
        self.player.play(cur["etalon"])
        return {"playing": True, "duration": len(AudioSegment.from_file(cur["etalon"])) / 1000.0}

    # ---------------- синтез ----------------

    def _synth_worker_get(self):
        w = getattr(self, '_synth_worker', None)
        if w is None or not w.is_alive():
            w = self._synth_worker = _SynthWorker(self)
            w.start()
        return w

    def tts_synth_run(self, k, front=True):
        """Синтезировать (или пересинтезировать) сумму k."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not os.path.exists(cur["etalon"]):
                return {"error": "Сначала выберите эталон — запись диктора с суммой."}
            if not cur.get("etalon_text"):
                return {"error": "Впишите текст эталона — что именно сказано в записи."}
            if not (0 <= k < len(sy["items"])):
                return {"error": "Нет такой суммы."}
            it = sy["items"][k]
            if self._synth_worker_get().add(k, front=front):
                it["status"], it["error"] = "queued", None
        self._synth_push(k)
        return self.tts_synth_state()

    def tts_synth_run_all(self):
        """Поставить в очередь все суммы, у которых ещё нет варианта."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not cur.get("etalon_text"):
                return {"error": "Сначала эталон и его текст."}
            w = self._synth_worker_get()
            for it in sy["items"]:
                if it["status"] in ("idle", "error") and w.add(it["k"]):
                    it["status"], it["error"] = "queued", None
        self._synth_push()
        return self.tts_synth_state()

    def tts_synth_stop(self):
        w = getattr(self, '_synth_worker', None)
        with self._synth_lock():
            sy = self._tts().get("synth") or {"items": []}
            for k in (w.clear() if w else []):
                if 0 <= k < len(sy["items"]) and sy["items"][k]["status"] == "queued":
                    sy["items"][k]["status"] = "ready" if sy["items"][k].get("variant") else "idle"
        self._synth_push()
        return self.tts_synth_state()

    def _synth_prefetch(self, after):
        """Пока вы слушаете — следующие суммы уже синтезируются."""
        sy = self._synth()
        w = self._synth_worker_get()
        n = 0
        for it in sy["items"][after + 1:]:
            if n >= SYNTH_PREFETCH:
                break
            if it["status"] in ("idle",) and w.add(it["k"]):
                it["status"] = "queued"
                n += 1
            elif it["status"] in ("queued", "working", "ready"):
                n += 1

    def _synth_job(self, k, worker):
        """Одна сумма: в гибриде — каждое число отдельным запросом и склейка
        с живыми словами; без гибрида — вся фраза одним запросом."""
        with self._synth_lock():
            sy = self._synth()
            it = sy["items"][k]
            it["status"], it["error"] = "working", None
            cur = self._synth_lang(sy)
            etalon, etalon_text, lang, text = cur["etalon"], cur["etalon_text"], sy["lang"], it["text"]
            bank = {f: dict(w) for f, w in cur.get("words", {}).items()
                    if os.path.exists(w.get("file", ''))} if sy.get("hybrid", True) else {}
            vdir = self._synth_dir(SYNTH_VARIANTS, lang=lang)
            tries = it.get("tries", 0) + 1
        self._synth_push(k)
        os.makedirs(vdir, exist_ok=True)
        plan = synth_plan(text, lang, bank)
        dst = os.path.join(vdir, f"{k + 1:04d}_v{tries}.wav")
        if not any(kind == 'live' for kind, _t in plan):
            plan = [['synth', text]]
            self._synth_request(worker, etalon, etalon_text, lang, text, dst)
            self._noise_file(dst, etalon)
        else:
            parts = []
            for i, (kind, t) in enumerate(plan):
                if kind == 'live':
                    parts.append(('live', bank[t]["file"], bank[t].get("gap")))
                else:
                    piece = os.path.join(vdir, f"{k + 1:04d}_v{tries}_{i + 1}.wav")
                    self._synth_request(worker, etalon, etalon_text, lang, t, piece)
                    self._noise_file(piece, etalon)
                    parts.append(('synth', piece, None))
            self._synth_glue(parts, dst)
        with self._synth_lock():
            sy = self._synth()
            if sy["lang"] != lang or k >= len(sy["items"]) or sy["items"][k]["text"] != text:
                # пока синтезировали — сменили язык/логику: вариант сохраним в его язык
                sy["per"][lang]["store"].setdefault(str(it["n"]), {}).update(
                    {"variant": dst, "status": "ready", "tries": tries, "text": text, "plan": plan})
                self._tts_save()
                return
            it = sy["items"][k]
            it.update({"variant": dst, "status": "ready", "tries": tries, "error": None, "plan": plan})
        self._tts_save()
        self._synth_push(k, message=f"Готово: {it['n']:,}".replace(',', ' '))

    def _synth_request(self, worker, etalon, etalon_text, lang, text, dst):
        """Шаги на сайте (в потоке браузера): один текст → WAV в dst."""
        page = worker.page_ready()
        sel = SYNTH_SEL
        page.select_option(sel["lang"], index=SYNTH_LANG_INDEX.get(lang, 0))
        page.set_input_files(sel["etalon_file"], etalon)
        page.fill(sel["etalon_text"], etalon_text)
        page.fill(sel["text"], text)
        raw = os.path.splitext(dst)[0] + '.download'
        synth_collect(page, sel["submit"], raw)
        try:
            clean_wav(raw, dst)
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass

    # ---------------- гибрид: живые слова ----------------

    @staticmethod
    def _trim_voice(x, rate, lead=15, tail=30):
        """Срезать тишину по краям синтезированного куска — почти вплотную."""
        import numpy as np
        e, n = _frames_rms(x, rate)
        if not len(e):
            return x
        db = 20 * np.log10(e)
        thr = max(-50.0, float(db.max()) - 35.0)
        on = np.nonzero(db > thr)[0]
        if not len(on):
            return x
        a = max(0, on[0] * n - int(rate * lead / 1000))
        b = min(len(x), (on[-1] + 1) * n + int(rate * tail / 1000))
        return x[a:b] if b - a > rate * 0.04 else x

    @staticmethod
    def _rms_voice(x, rate):
        """Громкость голоса (без пауз) — для выравнивания кусков между собой."""
        import numpy as np
        e, _n = _frames_rms(x, rate, 20)
        if not len(e):
            return 0.0
        loud = e[e > e.max() * 0.1]
        return float(np.sqrt((loud ** 2).mean())) if len(loud) else 0.0

    @classmethod
    def _synth_glue(cls, parts, dst):
        """Склейка: синтезированные числа + живые слова. Без перекодирования
        «на глаз»: частоту пересчитываем качественно (иначе — металл и
        «робот»), числа подгоняем по громкости к живому голосу."""
        import numpy as np
        loaded = []
        for kind, path, gap in parts:
            x, rate = _mono(path)
            loaded.append([kind, x, rate, gap])
        live = [p for p in loaded if p[0] == 'live']
        rate = (live[0] if live else loaded[0])[2]
        for p in loaded:
            if p[2] != rate:
                p[1] = resample(p[1][:, None], p[2], rate)[:, 0]
            if p[0] == 'synth':
                p[1] = cls._trim_voice(p[1], rate)
        target = np.mean([cls._rms_voice(p[1], rate) for p in live]) if live else 0.0
        if target > 0:
            for p in loaded:
                if p[0] == 'synth':
                    r = cls._rms_voice(p[1], rate)
                    if r > 0:
                        p[1] = p[1] * float(np.clip(target / r, 0.25, 4.0))
        sil = lambda ms: np.zeros(int(rate * ms / 1000), dtype=np.float32)
        out, prev = sil(60), None
        for kind, x, _r, gap in loaded:
            if prev is not None and prev[0] == 'synth' and kind == 'live':
                n = int(min(rate * GLUE_XFADE_MS / 1000, len(x) // 4, len(out) // 4))
                if n > 1:                             # перекрёстная склейка равной мощности
                    t = np.linspace(0, np.pi / 2, n, dtype=np.float32)
                    mix = out[-n:] * np.cos(t) + x[:n] * np.sin(t)
                    out = np.concatenate([out[:-n], mix, x[n:]])
                else:
                    out = np.concatenate([out, x])
            else:
                if prev is not None:
                    pause = prev[1] if prev[0] == 'live' and prev[1] is not None else GLUE_GAP_MS
                    out = np.concatenate([out, sil(pause)])
                out = np.concatenate([out, x])
            prev = (kind, gap)
        _write_pcm16(dst, np.concatenate([out, sil(90)]), rate)

    @staticmethod
    def _gap_after(x, rate, b_ms):
        """Пауза диктора после слова: до начала следующего звука (не дальше 250 мс)."""
        import numpy as np
        e, n = _frames_rms(x, rate)
        if not len(e):
            return None
        thr = e.max() * 10 ** (-30 / 20)
        i0 = int(b_ms * rate / 1000) // n
        win = e[i0:i0 + int(450 / 5)] > thr
        quiet = np.nonzero(~win)[0]                  # сначала дослушать хвост самого слова
        if not len(quiet):
            return None
        nxt = np.nonzero(win[quiet[0]:])[0]
        if not len(nxt):
            return None
        return int(max(20, min(250, (quiet[0] + nxt[0]) * 5)))

    @staticmethod
    def _word_cut(seg, s_ms, e_ms):
        """Уточнить края слова по тишине рядом с отметками распознавания:
        Whisper ошибается на десятки миллисекунд — режем в самом тихом месте."""
        def rms(a):
            return seg[a:a + 5].rms if a + 5 <= len(seg) else 0

        def quiet_near(lo, hi, aim):
            lo, hi = max(0, int(lo)), min(len(seg) - 5, int(hi))
            if hi <= lo:
                return int(aim)
            vals = [(rms(a), a) for a in range(lo, hi, 5)]
            floor = min(v for v, _a in vals)
            calm = [a for v, a in vals if v <= floor * 1.6 + 2]
            return min(calm, key=lambda a: abs(a - aim))
        a = quiet_near(s_ms - 110, s_ms + 30, s_ms)
        b = quiet_near(e_ms - 30, e_ms + 140, e_ms)
        return a, max(b, a + 60)

    # ---------------- ручная разметка живых слов ----------------

    def tts_synth_marker_open(self, extra=False):
        """Открыть дорожку записи для ручной разметки: эталон или (extra)
        другая запись диктора, где есть нужные формы слов."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            lang = sy["lang"]
        if extra:
            picked = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
            if not picked:
                return {"error": "cancel"}
            src = picked if isinstance(picked, str) else picked[0]
            rec_dir = self._synth_dir(SYNTH_WORDS, '_записи', lang=lang)
            os.makedirs(rec_dir, exist_ok=True)
            path = os.path.join(rec_dir, os.path.basename(src))
            if os.path.abspath(src) != os.path.abspath(path):
                shutil.copy2(src, path)                  # чтобы не потерялась
        else:
            path = cur.get("etalon")
            if not path or not os.path.exists(path):
                return {"error": "Сначала выберите эталон."}
        return self._synth_marker_load(path, lang)

    def tts_synth_marker_reopen(self, src):
        """Открыть запись, из которой уже размечено слово (по имени файла)."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            for w in cur.get("words", {}).values():
                if w.get("src") == src and os.path.exists(w.get("src_path", '')):
                    return self._synth_marker_load(w["src_path"], sy["lang"])
            if cur.get("etalon") and os.path.basename(cur["etalon"]) == src:
                return self._synth_marker_load(cur["etalon"], sy["lang"])
        return {"error": "Запись не найдена."}

    def _synth_marker_load(self, path, lang):
        import numpy as np
        x, rate = _mono(path)
        cols = 1400
        n = max(1, len(x) // cols)
        k = len(x) // n
        blk = np.abs(x[:k * n]).reshape(k, n).max(axis=1) if k else np.zeros(0)
        top = float(blk.max()) if len(blk) else 0.0
        peaks = [round(float(v) / top, 3) for v in blk] if top > 0 else [0.0] * len(blk)
        self._synth_mark = {"path": path, "lang": lang}
        return {"name": os.path.basename(path), "dur": int(len(x) * 1000 / rate), "peaks": peaks,
                "forms": UNIT_FORMS[lang], "marks": self._synth_marks(path), "state": self.tts_synth_state()}

    def _synth_marks(self, path):
        cur = self._synth_lang(self._synth())
        return [{"form": f, "a": w["a"], "b": w["b"]} for f, w in cur.get("words", {}).items()
                if w.get("src_path") == path and w.get("a") is not None]

    def tts_synth_marker_play(self, a_ms, b_ms=None):
        """Прослушать выделенный кусок дорожки (или с a_ms до конца)."""
        mk = getattr(self, '_synth_mark', None)
        if not mk:
            return {"error": "Дорожка не открыта."}
        x, rate = _read_audio(mk["path"])
        a = max(0, int(a_ms * rate / 1000))
        b = len(x) if b_ms is None else min(len(x), int(b_ms * rate / 1000))
        if b - a < rate * 0.02:
            return {"error": "Слишком короткий кусок."}
        self._synth_mark_n = getattr(self, '_synth_mark_n', 0) + 1
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_mark_{os.getpid()}_{self._synth_mark_n % 4}.wav")
        _write_pcm16(tmp, x[a:b], rate)
        self.player.play(tmp)
        return {"playing": True, "duration": (b - a) / rate}

    def tts_synth_marker_save(self, form, a_ms, b_ms):
        """Выделенный кусок — это слово form: вырезаем (мягкие края) в «_слова/»."""
        import numpy as np
        mk = getattr(self, '_synth_mark', None)
        if not mk:
            return {"error": "Дорожка не открыта."}
        lang = mk["lang"]
        if form not in UNIT_FORMS[lang]:
            return {"error": "Нет такого слова."}
        a_ms, b_ms = sorted((float(a_ms), float(b_ms)))
        if b_ms - a_ms < 60:
            return {"error": "Выделите слово целиком (сейчас меньше 60 мс)."}
        x, rate = _read_audio(mk["path"])
        a, b = int(a_ms * rate / 1000), min(len(x), int(b_ms * rate / 1000))
        piece = x[a:b].copy()
        fi, fo = int(rate * 0.005), int(rate * 0.010)              # без щелчков на краях
        piece[:fi] *= np.linspace(0, 1, fi, dtype=np.float32)[:, None]
        piece[-fo:] *= np.linspace(1, 0, fo, dtype=np.float32)[:, None]
        wdir = self._synth_dir(SYNTH_WORDS, lang=lang)
        os.makedirs(wdir, exist_ok=True)
        out = os.path.join(wdir, f"{form}.wav")
        _write_pcm16(out, piece, rate)
        mono = x.mean(axis=1) if x.shape[1] > 1 else x[:, 0]
        with self._synth_lock():
            self._synth()["per"][lang]["words"][form] = {
                "file": out, "src": os.path.basename(mk["path"]), "src_path": mk["path"],
                "a": int(a_ms), "b": int(b_ms), "gap": self._gap_after(mono, rate, b_ms)}
        self._tts_save()
        return {"marks": self._synth_marks(mk["path"]), "state": self.tts_synth_state()}

    def tts_synth_marker_remove(self, form):
        mk = getattr(self, '_synth_mark', None)
        self.tts_synth_word_remove(form)
        return {"marks": self._synth_marks(mk["path"]) if mk else [], "state": self.tts_synth_state()}

    def tts_synth_marker_auto(self):
        """Подсказка: где слова, по распознаванию (Whisper). Ничего не
        сохраняет — вы проверяете и подтверждаете сами."""
        mk = getattr(self, '_synth_mark', None)
        if not mk:
            return {"error": "Дорожка не открыта."}
        lang = mk["lang"]
        model, err = self._auto_check_model(lang)
        if err:
            return {"error": err}
        cur = self._synth_lang(self._synth())
        hint = cur.get("etalon_text", '') if mk["path"] == cur.get("etalon") else ''
        samples, ms, _peak = self._asr_load(mk["path"])
        words = self._tts_transcribe_pack(model, [{"index": 0, "audio": samples, "ms": ms}],
                                          'kk' if lang == 'kz' else 'ru',
                                          hotwords=(hint + ' ' + ' '.join(UNIT_FORMS[lang])).strip())[0]
        seg = AudioSegment.from_file(mk["path"])
        out = []
        for w, s0, e0 in words:
            f = unit_form(w, lang)
            if f:
                a, b = self._word_cut(seg, s0 * 1000, e0 * 1000)
                out.append({"form": f, "a": a, "b": b})
        if not out:
            return {"error": "Не нашёл слов автоматически — выделите их мышью."}
        return {"suggest": out}

    def tts_synth_word_play(self, form):
        w = self._synth_lang(self._synth()).get("words", {}).get(form)
        if not w or not os.path.exists(w.get("file", '')):
            return {"error": "Этого слова пока нет."}
        self.player.play(w["file"])
        return {"playing": True}

    def tts_synth_word_remove(self, form):
        """Убрать живое слово — эта форма снова пойдёт в синтез."""
        with self._synth_lock():
            self._synth_lang(self._synth()).get("words", {}).pop(form, None)
        self._tts_save()
        return self.tts_synth_state()

    def _synth_failed(self, k, error):
        with self._synth_lock():
            sy = self._tts().get("synth") or {"items": []}
            if 0 <= k < len(sy["items"]):
                it = sy["items"][k]
                it["status"] = "ready" if it.get("variant") else "error"
                it["error"] = error
        self._tts_save()
        self._synth_push(k, error=error)

    # ---------------- прослушка и одобрение ----------------

    def tts_synth_play(self, k, final=False):
        sy = self._synth()
        if not (0 <= k < len(sy["items"])):
            return {"error": "Нет такой суммы."}
        it = sy["items"][k]
        path = it.get("file") if final else (it.get("variant") or it.get("file"))
        if not path or not os.path.exists(path):
            return {"error": "Эта сумма ещё не синтезирована."}
        self.player.play(path)
        return {"playing": True, "duration": len(AudioSegment.from_file(path)) / 1000.0}

    @staticmethod
    def _synth_trim(src, dst):
        """Обрезать тишину по краям (с запасом), байт в байт."""
        seg = AudioSegment.from_file(src)
        if not len(seg) or seg.max_dBFS == float('-inf'):
            shutil.copy2(src, dst)
            return
        thr = max(-55.0, seg.max_dBFS - 40.0)
        a = detect_leading_silence(seg, silence_threshold=thr, chunk_size=10)
        b = len(seg) - detect_leading_silence(seg.reverse(), silence_threshold=thr, chunk_size=10)
        a, b = max(0, a - 60), min(len(seg), b + 90)
        if b - a < 100 or not wav_slice(src, dst, a, b):
            shutil.copy2(src, dst)

    def tts_synth_approve(self, k):
        """Вариант звучит верно → в «Синтез_суммы_RU/» (_KZ) (тишина по краям обрезана),
        и сразу синтезируются следующие."""
        with self._synth_lock():
            sy = self._synth()
            if not (0 <= k < len(sy["items"])):
                return {"error": "Нет такой суммы."}
            it = sy["items"][k]
            if not it.get("variant") or not os.path.exists(it["variant"]):
                return {"error": "Сначала синтезируйте эту сумму."}
            folder = self._synth_dir()
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, f"{k + 1:04d}_{it['n']}.wav")
            self._synth_trim(it["variant"], dst)
            it["file"], it["status"] = dst, "approved"
            self._synth_prefetch(k)
        self._tts_save()
        self._synth_push(k)
        return self.tts_synth_state()

    def tts_synth_etalon_as_first(self):
        """Эталон и есть первая сумма — берём его как одобренный №1."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not sy["items"]:
                return {"error": "Сначала выберите эталон."}
            it = sy["items"][0]
            folder = self._synth_dir()
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, f"{1:04d}_{it['n']}.wav")
            self._synth_trim(cur["etalon"], dst)
            it.update({"variant": cur["etalon"], "file": dst, "status": "approved", "error": None})
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_unapprove(self, k):
        with self._synth_lock():
            sy = self._synth()
            if 0 <= k < len(sy["items"]):
                it = sy["items"][k]
                if it.get("file") and os.path.exists(it["file"]):
                    try:
                        self._tts_trash(it["file"])
                    except Exception:
                        pass
                it["file"] = None
                it["status"] = "ready" if it.get("variant") else "idle"
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_sums_folder(self):
        """Папка одобренных сумм — для режима «Суммы»."""
        folder = self._synth_dir()
        if not folder or not os.path.isdir(folder) or not any(
                f.lower().endswith('.wav') for f in os.listdir(folder)):
            return {"error": "Пока нет ни одной одобренной суммы."}
        self.tts_synth_stop()
        return {"folder": folder}

    # ---------------- синтез в записи ----------------
    # «Синтез фразы»: фраза с суфлёра целиком; образец голоса — прошлая
    # записанная фраза (её звук и текст), иначе эталон «Синтеза сумм».
    # «Синтез…» в «Сборке»: пересинтез с выбранного слова, начиная на пару
    # слов раньше (перекрытие для склейки) — вторым клипом на дорожке.
    # Сервис срезает конец записи — поэтому после текста добавляем
    # слово-запас (SYNTH_TAIL): его вы срезаете в «Сборке».

    def _synth_is_fake(self, k):
        return bool(k.get("synth_ref")) or k.get("heard") == "(синтез)"

    def _synth_prev_ref(self, lang, exclude=None):
        """Прошлая записанная (живая) фраза на этом языке: (звук, текст, имя)."""
        st = self._tts()
        wd = st.get("work_dir")
        if not wd:
            return None
        for strict in (True, False):                      # сначала сохранённые, потом любые привязанные
            for k in reversed(st["takes"]):
                uid = k.get("unit")
                if k is exclude or uid is None or uid >= len(st["units"]) or self._synth_is_fake(k):
                    continue
                if strict and not k.get("approved"):
                    continue
                if not strict and k.get("status") not in ("ok", "manual"):
                    continue
                if self._tts_unit_lang(uid) != lang:
                    continue
                path = os.path.join(wd, k["file"])
                if os.path.exists(path) and k.get("ms", 0) >= 700:
                    u = st["units"][uid]
                    return path, u["text"], f"прошлая фраза «{u['name']}»"
        return None

    def _synth_etalon_ref(self, lang):
        cur = self._synth()["per"].get(lang) or {}
        if cur.get("etalon") and os.path.exists(cur["etalon"]) and cur.get("etalon_text"):
            return cur["etalon"], cur["etalon_text"], 'эталон «Синтеза сумм»'
        return None

    def _take_synth_ref(self, lang, t=None, start=0, words=None, mode='auto'):
        """Образец голоса. mode: 'take' — этот дубль (живой, сказанное до start),
        'prev' — прошлая записанная фраза, 'etalon' — эталон, 'auto' — по порядку."""
        st = self._tts()
        wd = st.get("work_dir")
        if t is not None and t.get("synth_ref") and mode in ('auto', 'take', 'same'):
            r = t["synth_ref"]                             # дубль сам синтезирован — тот же образец
            if os.path.exists(r["path"]):
                return r["path"], r["text"], r.get("name") or 'тот же образец'
        if mode == 'take' and t is not None and start > 0 and wd and not self._synth_is_fake(t):
            path = os.path.join(wd, t["file"])
            if os.path.exists(path):
                return path, ' '.join(words[:start]), 'этот дубль'
        order = {'etalon': ('etalon', 'prev')}.get(mode, ('prev', 'etalon'))
        for o in order:
            r = self._synth_prev_ref(lang, exclude=t) if o == 'prev' else self._synth_etalon_ref(lang)
            if r:
                return r
        raise RuntimeError("Нет образца голоса на этом языке: запишите хотя бы одну фразу "
                           "или выберите эталон во вкладке «Синтез сумм».")

    @staticmethod
    def _synth_with_tail(text, lang, tail=True):
        """Слово-запас в конце: сервис обрезает конец записи — режется запас."""
        return f"{text.rstrip()}  {SYNTH_TAIL.get(lang, SYNTH_TAIL['ru'])}" if tail else text

    def tts_take_synth_info(self, i):
        """Что показать в панели пересинтеза: слова, язык, какие образцы есть."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        if t.get("unit") is None:
            return {"error": "Дубль не привязан к фразе — сначала выберите фразу (F)."}
        u = st["units"][t["unit"]]
        words = str(u["text"]).split()
        lang = self._tts_unit_lang(t["unit"])
        fake = self._synth_is_fake(t)
        if fake:
            start = max(1, len(words) // 2) if len(words) > 1 else 0
        else:
            # Где, примерно, кончилась живая запись: ~14 знаков в секунду речи.
            said = int(max(0, t.get("ms", 0) - 300) / 1000 * 14)
            start, n = 0, 0
            for k, w in enumerate(words):
                if n + len(w) / 2 > said:
                    break
                n += len(w) + 1
                start = k + 1
            start = max(1, min(len(words) - 1, start)) if len(words) > 1 else 0
        refs = []
        if t.get("synth_ref") and os.path.exists(t["synth_ref"]["path"]):
            refs.append({"mode": "same", "label": t["synth_ref"].get("name") or 'тот же образец'})
        if not fake:
            refs.append({"mode": "take", "label": 'этот дубль'})
        prev = self._synth_prev_ref(lang, exclude=t)
        if prev and not (t.get("synth_ref") and prev[2] == t["synth_ref"].get("name")):
            refs.append({"mode": "prev", "label": prev[2]})
        if self._synth_etalon_ref(lang):
            refs.append({"mode": "etalon", "label": 'эталон «Синтеза сумм»'})
        return {"words": words, "lang": lang, "start": start, "fake": fake, "refs": refs,
                "tail_word": SYNTH_TAIL.get(lang, SYNTH_TAIL['ru']), "noise": dict(self._synth_noise_cfg()),
                "busy": bool(getattr(self, '_take_synth_busy', None))}

    def tts_take_synth(self, i, start, overlap=2, text=None, mode='auto', tail=True):
        """Пересинтез с слова start (с перекрытием overlap слов до него) —
        вторым клипом на дорожку дубля i. start=0 — вся фраза заново."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        if getattr(self, '_take_synth_busy', None):
            return {"error": "Синтез уже идёт — подождите."}
        t = st["takes"][i]
        if t.get("unit") is None:
            return {"error": "Дубль не привязан к фразе."}
        words = str(st["units"][t["unit"]]["text"]).split()
        start = max(0, min(int(start), len(words)))
        lang = self._tts_unit_lang(t["unit"])
        text = (text or '').strip() or ' '.join(words[max(0, start - int(overlap or 0)):])
        if not text:
            return {"error": "Нечего синтезировать."}
        try:
            ref, ref_text, ref_name = self._take_synth_ref(lang, t, start, words, mode)
        except RuntimeError as e:
            return {"error": str(e)}
        key = t["file"]
        self._take_synth_busy = key
        body = self._synth_with_tail(text, lang, tail)

        def job(worker):
            try:
                self._take_synth_job(worker, key, ref, ref_text, lang, body)
            except Exception as e:
                worker._close()
                self._tts_push({"stage": "take_synth", "file": key, "error": str(e)})
            finally:
                self._take_synth_busy = None
        self._synth_worker_get().add(job, front=True)
        return {"queued": True, "text": body, "ref": ref_name, "lang": lang}

    def _take_synth_job(self, worker, key, ref, ref_text, lang, text):
        import numpy as np
        st = self._tts()
        sdir = os.path.join(st["work_dir"], 'Чанки', '_синтез')
        os.makedirs(sdir, exist_ok=True)
        n = len([f for f in os.listdir(sdir) if f.endswith('.wav')]) + 1
        base = os.path.splitext(os.path.basename(key))[0]
        got = os.path.join(sdir, f"{base}_синтез{n}_сервис.wav")
        self._synth_request(worker, ref, ref_text, lang, text, got)
        t = next((k for k in st["takes"] if k["file"] == key), None)
        if t is None:
            raise RuntimeError("Пока синтезировали, дубль удалили.")
        clips = self._tts_clips(t)
        like = clips[-1]["raw"]
        x, rate = _mono(got)
        x = self._trim_voice(x, rate, lead=20, tail=60)
        # громкость — как у звука в этом дубле
        take_path = os.path.join(st["work_dir"], t["file"])
        if os.path.exists(take_path):
            y, yr = _mono(take_path)
            r_take, r_syn = self._rms_voice(y, yr), self._rms_voice(x, rate)
            if r_take > 0 and r_syn > 0:
                x = x * float(np.clip(r_take / r_syn, 0.25, 4.0))
        x = self._add_noise(x, rate, ref)                  # фон комнаты — как в образце
        dst = os.path.join(sdir, f"{base}_синтез{n}.wav")
        length = write_like(dst, x, rate, like)
        try:
            os.remove(got)
        except OSError:
            pass
        end = 0
        for c in clips:
            end = max(end, int(c["pos"]) + sum(b - a for a, b in self._clip_ranges(c)))
        if not t.get("clips_orig"):
            t["clips_orig"] = [dict(c) for c in clips]
        clips.append({"raw": dst, "a": 0, "b": length, "cuts": [], "pos": end + 40})
        self._tts_orig(t)
        self._tts_render_clips(t, clips)
        t["clips"] = clips
        t.pop("edit", None)
        t["listened"] = False
        t.setdefault("synth", []).append({"file": dst, "text": text})
        self._tts_save()
        self._tts_push({"stage": "take_synth", "file": key, "state": self.tts_state(),
                        "message": f"Пересинтез «{text[:40]}{'…' if len(text) > 40 else ''}» — вторым клипом. "
                                   f"Сдвиньте его на место, срежьте перекрытие и слово-запас в конце."})

    def tts_prompt_synth(self, text=None, tail=True, mode='auto'):
        """Фразу на суфлёре целиком — синтезом. Образец — прошлая записанная
        фраза (или эталон). Кусочки фразы с переменными — каждый своим дублем."""
        st = self._tts()
        if getattr(self, '_take_synth_busy', None):
            return {"error": "Синтез уже идёт — подождите."}
        if not st.get("work_dir"):
            return {"error": "Сначала выберите папку проекта (начните запись или откройте проект)."}
        items = self._tts_prompt_items()
        pos = st.get("prompt_pos", 0)
        ids = items[pos] if 0 <= pos < len(items) else []
        if not ids:
            return {"error": "На суфлёре нет фразы."}
        good = self._tts_good_units()
        need = [i for i in ids if i not in good and not os.path.exists(self._tts_target(st["units"][i]))] or ids
        jobs = []
        for uid in need:
            lang = self._tts_unit_lang(uid)
            try:
                ref, ref_text, ref_name = self._take_synth_ref(lang, mode=mode)
            except RuntimeError as e:
                return {"error": str(e)}
            body = (text if (text and len(need) == 1) else st["units"][uid]["text"]).strip()
            jobs.append((uid, lang, ref, ref_text, ref_name, self._synth_with_tail(body, lang, tail)))
        self._take_synth_busy = 'prompt'

        def job(worker):
            try:
                for j in jobs:
                    self._prompt_synth_one(worker, *j, pos)
            except Exception as e:
                worker._close()
                self._tts_push({"stage": "take_synth", "file": None, "error": str(e)})
            finally:
                self._take_synth_busy = None
        self._synth_worker_get().add(job, front=True)
        return {"queued": True, "count": len(jobs), "ref": jobs[0][4]}

    def _prompt_synth_one(self, worker, uid, lang, ref, ref_text, ref_name, body, pos):
        st = self._tts()
        sdir = os.path.join(st["work_dir"], 'Чанки', '_синтез')
        os.makedirs(sdir, exist_ok=True)
        n = max([k.get("chunk", 0) for k in st["takes"]] + [0]) + 1
        got = os.path.join(sdir, f"{n:04d}_фраза_сервис.wav")
        self._synth_request(worker, ref, ref_text, lang, body, got)
        x, rate = _mono(got)
        x = self._trim_voice(x, rate, lead=40, tail=80)
        x = self._add_noise(x, rate, ref)                  # фон комнаты — как в образце
        raw = os.path.join(sdir, f"{n:04d}_фраза.wav")
        _write_pcm16(raw, x, rate)
        try:
            os.remove(got)
        except OSError:
            pass
        length = int(len(x) * 1000 / rate)
        name = f"{n:04d}.wav"
        # образец копируем к себе: пересинтез берёт тот же голос, даже если тот дубль удалят
        keep = os.path.join(sdir, f"{n:04d}_образец{os.path.splitext(ref)[1] or '.wav'}")
        shutil.copy2(ref, keep)
        take = {"file": os.path.join('Чанки', name), "start_ms": 0, "ms": length, "orig": [0, length],
                "raw": raw, "heard": "(синтез)", "listened": False, "chunk": n, "unit": uid,
                "score": 1.0, "status": "manual", "synth": [{"file": raw, "text": body}],
                "synth_ref": {"path": keep, "text": ref_text, "name": ref_name}}
        shutil.copy2(raw, os.path.join(st["work_dir"], take["file"]))
        st["takes"].append(take)
        st["index"] = len(st["takes"]) - 1
        self._tts_save()
        self._tts_push({"stage": "take_synth", "file": take["file"], "new": True, "state": self.tts_state(),
                        "message": f"Синтез «{st['units'][uid]['name']}» (образец — {ref_name}). Срежьте слово-запас "
                                   f"в конце; артефакт в середине — «Синтез…» с нужного слова."})
