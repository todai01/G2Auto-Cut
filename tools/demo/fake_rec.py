# «Микрофон» для роликов: вместо звука с микрофона — синтетическая «речь»
# фразы суфлёра в момент нажатия Space. Дальше — настоящая логика GVox
# (поток разбора, «Без распознавания», дубли, лента, суфлёр).
import os, time, threading, math
import numpy as np
from pydub import AudioSegment
from harness import FAKE, DIALOG, speech, write, R
from core.tts_flow import TTS_CHUNKS_DIR


class FakeRec:
    def __init__(self, path):
        self.path, self.rate, self.running = path, R, True
        self.t0 = time.time()
        self.buf = np.zeros(0, dtype=np.float32)
        self.device_name, self.error, self.overflows = 'Микрофон (демо)', None, 0
        self.mic_off, self.mon, self._mon_name, self._mon_device = False, None, None, None
        self.mon_lock, self.mon_buf = threading.Lock(), np.zeros(0)
        self.speaking = None                             # (начало, отсчёты) — сейчас «говорим»
        self.lock = threading.Lock()

    @property
    def ana_ms(self):
        return int((time.time() - self.t0) * 1000)

    @property
    def frames(self):
        return int((time.time() - self.t0) * self.rate)

    @property
    def level_db(self):
        if self.speaking and time.time() < self.speaking:
            return -14 + 6 * math.sin(time.time() * 9)
        return -52 + 2 * math.sin(time.time() * 3)

    def _grow(self, n):
        if len(self.buf) < n:
            self.buf = np.concatenate([self.buf, 0.002 * np.random.default_rng(len(self.buf)).standard_normal(n - len(self.buf)).astype(np.float32)])

    def say(self, text, at_ms):
        y = speech(text, decl=1.5)
        a = int(at_ms * self.rate / 1000)
        with self.lock:
            self._grow(a + len(y))
            self.buf[a:a + len(y)] += y
            write(self.path, self.buf)
        self.speaking = time.time() + len(y) / self.rate
        return len(y) * 1000 // self.rate

    def ana_segment(self, a_ms, b_ms):
        with self.lock:
            self._grow(int(b_ms * self.rate / 1000) + 1)
            write(self.path, self.buf)
            x = self.buf[int(a_ms * self.rate / 1000):int(b_ms * self.rate / 1000)]
        return AudioSegment((np.clip(x, -1, 1) * 32767).astype('<i2').tobytes(), frame_rate=self.rate, sample_width=2, channels=1)

    def stop(self):
        self.running = False

    def set_monitor(self, *a, **k):
        return None


def install(a, folder=None):
    """Подменить запись: tts_rec_start → FakeRec + настоящий поток разбора."""
    def rec_start(device=None):
        st = a._tts()
        if getattr(a, '_tts_rec', None):
            return {"error": "Запись уже идёт."}
        note = None
        if not st.get("work_dir"):
            picked = DIALOG.pop(0) if DIALOG else folder
            note = a._tts_attach_folder(picked if isinstance(picked, str) else picked[0])
            st = a._tts()
        os.makedirs(os.path.join(st["work_dir"], 'Записи'), exist_ok=True)
        os.makedirs(os.path.join(st["work_dir"], TTS_CHUNKS_DIR), exist_ok=True)
        rec = FakeRec(os.path.join(st["work_dir"], 'Записи', time.strftime('Запись_%Y-%m-%d_%H-%M-%S.wav')))
        write(rec.path, np.zeros(R // 10, dtype=np.float32))
        a._tts_rec = rec
        a._tts_live_lock = threading.RLock()
        a._tts_q_lock = threading.Lock()
        a._tts_no_asr = True
        a._tts_live = {"model": None, "models": {}, "done_ms": 0, "from_ms": 0, "busy": False, "added": 0,
                       "restarts": 0, "expected": a._tts_live_expected(), "queue": [], "hold": None,
                       "gen": 0, "fast": True, "no_asr": True}
        a._tts_prompt_fix()
        a._tts_save()
        threading.Thread(target=a._tts_live_loop, daemon=True).start()
        return {"status": "ok", "device": rec.device_name, "rate": rec.rate, "monitor": None, "monitor_error": None,
                "restored": note, "state": a.tts_state() if note else None}
    FAKE['tts_rec_start'] = rec_start
    FAKE['tts_rec_devices'] = lambda: {"devices": [{"id": 1, "name": "Микрофон (демо)", "default": True}],
                                       "outputs": [{"id": 2, "name": "Наушники (демо)", "default": True}]}
    FAKE['tts_monitor'] = lambda *x: {"on": False, "name": None}
    FAKE['tts_live_no_asr'] = lambda on: {"no_asr": True}
    FAKE['tts_live_fast'] = lambda on: {"fast": True}


def prompt_text(a):
    st = a._tts()
    items = a._tts_prompt_items()
    pos = st.get("prompt_pos", 0)
    ids = items[pos] if 0 <= pos < len(items) else []
    return ' '.join(st["units"][i]["text"] for i in ids)


def read_line(r, a, extra_ms=250, cancel=False):
    """Зажать Space, «прочитать» фразу суфлёра, отпустить (cancel — сбиться и Backspace)."""
    rec = a._tts_rec
    r.pg.evaluate("__tutKeyShow('Space — держу')")
    r.pg.keyboard.down('Space')
    text = prompt_text(a)
    ms = rec.say(' '.join(text.split()[:2]) if cancel else text, rec.ana_ms + 120)
    r.wait(ms + extra_ms)
    if cancel:
        r.pg.evaluate("__tutKeyShow('Backspace')")
        r.pg.keyboard.press('Backspace')
        r.wait(700)
    r.pg.keyboard.up('Space')
    r.pg.evaluate("__tutKeyShow('')")
