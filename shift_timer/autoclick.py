"""Автокликер GTime: скрытая функция (окно открывается тройным щелчком по слову «Система» в настройках).

Кликает мышью в текущей позиции курсора или в заданной точке экрана с заданным интервалом.
Остановка: F6 (старт / стоп) и Esc — глобально, работает и когда окно GTime свёрнуто.
Только Windows (user32); на других системах кнопки не работают, настройки сохраняются."""
import threading
import time

INTERVAL_MIN, INTERVAL_MAX = 10, 3_600_000           # мс между кликами
DELAY_MAX = 60                                       # секунд до первого клика
LIMIT_MAX = 1_000_000
BUTTONS = ("left", "right", "middle")
VK_ESC, VK_F6 = 0x1B, 0x75
DEFAULT_CFG = {"interval_ms": 1000, "button": "left", "double": False, "mode": "cursor", "x": 0, "y": 0, "limit": 0, "delay_s": 3}


def _int(v, lo, hi, default):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    return max(lo, min(hi, int(v)))


def clean_cfg(raw):
    """Любой мусор → корректные настройки (остальное — по умолчанию)."""
    c = dict(DEFAULT_CFG)
    if not isinstance(raw, dict):
        return c
    c["interval_ms"] = _int(raw.get("interval_ms"), INTERVAL_MIN, INTERVAL_MAX, c["interval_ms"])
    c["button"] = raw["button"] if raw.get("button") in BUTTONS else c["button"]
    c["double"] = raw["double"] if isinstance(raw.get("double"), bool) else c["double"]
    c["mode"] = raw["mode"] if raw.get("mode") in ("cursor", "point") else c["mode"]
    c["x"] = _int(raw.get("x"), -32768, 32767, 0)
    c["y"] = _int(raw.get("y"), -32768, 32767, 0)
    c["limit"] = _int(raw.get("limit"), 0, LIMIT_MAX, 0)               # 0 — без ограничения
    c["delay_s"] = _int(raw.get("delay_s"), 0, DELAY_MAX, c["delay_s"])
    return c


class WinInput:
    """Мышь и клавиатура через user32 (ctypes)."""
    _DOWN = {"left": 0x0002, "right": 0x0008, "middle": 0x0020}
    _UP = {"left": 0x0004, "right": 0x0010, "middle": 0x0040}

    def __init__(self):
        import ctypes
        self._u = ctypes.windll.user32
        self._ct = ctypes

    def pos(self):
        from ctypes import wintypes
        p = wintypes.POINT()
        self._u.GetCursorPos(self._ct.byref(p))
        return p.x, p.y

    def move(self, x, y):
        self._u.SetCursorPos(int(x), int(y))

    def click(self, button):
        self._u.mouse_event(self._DOWN[button], 0, 0, 0, 0)
        self._u.mouse_event(self._UP[button], 0, 0, 0, 0)

    def key_down(self, vk):
        return bool(self._u.GetAsyncKeyState(vk) & 0x8000)


class Clicker:
    def __init__(self, backend=None, locked=None):
        self._b = backend
        self._locked = locked                           # () -> bool: экран заблокирован — кликать нельзя
        self._cfg = dict(DEFAULT_CFG)
        self._stop = threading.Event()
        self._th = None
        self._lock = threading.Lock()
        self._st = {"running": False, "count": 0, "phase": "", "error": ""}
        self._hk = None

    def backend(self):
        if self._b is None:
            self._b = WinInput()
        return self._b

    def supported(self):
        try:
            self.backend()
            return True
        except (ImportError, AttributeError, OSError):
            return False

    def state(self):
        with self._lock:
            return dict(self._st)

    def pick(self):
        """Где сейчас курсор — для «Указать точку»."""
        try:
            x, y = self.backend().pos()
            return {"x": x, "y": y}
        except (ImportError, AttributeError, OSError):
            return {"error": "Работает только в Windows."}

    def start(self, cfg):
        cfg = clean_cfg(cfg)
        with self._lock:
            if self._th is not None and self._th.is_alive():
                return {"error": "Уже запущен."}
        if not self.supported():
            return {"error": "Работает только в Windows."}
        self._cfg = cfg
        self._stop.clear()
        with self._lock:
            self._st = {"running": True, "count": 0, "phase": "wait" if cfg["delay_s"] else "run", "error": ""}
            self._th = threading.Thread(target=self._run, args=(cfg,), daemon=True)
            self._th.start()
        return {"ok": True}

    def stop(self):
        self._stop.set()
        th = self._th
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(2.0)
        return {"ok": True}

    def toggle(self):
        return self.stop() if self.state()["running"] else self.start(self._cfg)

    def _finish(self, err=""):
        with self._lock:
            self._st.update(running=False, phase="", error=err)

    def _run(self, cfg):
        try:
            if cfg["delay_s"] and self._stop.wait(cfg["delay_s"]):
                return self._finish()
            with self._lock:
                self._st["phase"] = "run"
            b, gap, n, last_check = self.backend(), cfg["interval_ms"] / 1000.0, 0, time.monotonic()
            while not self._stop.is_set():
                if self._locked and time.monotonic() - last_check >= 1.0:
                    last_check = time.monotonic()
                    if self._locked():
                        return self._finish("Экран заблокирован — остановлено.")
                if cfg["mode"] == "point":
                    b.move(cfg["x"], cfg["y"])
                for _ in range(2 if cfg["double"] else 1):
                    b.click(cfg["button"])
                n += 1
                with self._lock:
                    self._st["count"] = n
                if cfg["limit"] and n >= cfg["limit"]:
                    break
                if self._stop.wait(gap):
                    break
            self._finish()
        except Exception as e:                           # любая ошибка ввода не должна оставить «запущено»
            self._finish(f"Ошибка: {e}")

    # ---------- горячие клавиши: F6 старт / стоп, Esc стоп (опрос 30 раз в секунду) ----------
    def start_hotkeys(self):
        if self._hk is not None or not self.supported():
            return
        self._hk = threading.Thread(target=self._poll_keys, daemon=True)
        self._hk.start()

    def _poll_keys(self):
        b, f6, esc = self.backend(), False, False
        while True:
            time.sleep(0.033)
            try:
                d6, de = b.key_down(VK_F6), b.key_down(VK_ESC)
            except Exception:
                return
            if d6 and not f6:
                self.toggle()
            if de and not esc and self.state()["running"]:
                self.stop()
            f6, esc = d6, de
