"""Конец смены — мини-приложение: ставите время конца рабочего дня, видите, сколько осталось.

Главное окно + маленькое окошко без рамки Windows (поверх окон, тянется мышью).
Настройки — %APPDATA%\\ShiftTimer\\settings.json. Интерфейс — папка ui (HTML), окна — pywebview.

    python shift_timer/app.py            # запуск
    ShiftTimer.exe --selftest            # проверка без окон: отчёт в %TEMP%\\ShiftTimer_selftest.txt
"""
import json
import os
import re
import sys
import tempfile
import threading

APP_NAME = 'ShiftTimer'
TITLE = 'Конец смены'
DEFAULTS = {"start": "09:00", "end": "18:00", "seconds": True, "theme": "auto",
            "mini_visible": False, "mini_on_top": True, "mini_pos": None}
MAIN_SIZE = (380, 640)
MINI_SIZE = (204, 86)


def resource(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def settings_file():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, APP_NAME, 'settings.json')


def clean(raw):
    """Любой мусор из файла / из окна → корректные настройки (остальное — по умолчанию)."""
    s = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return s
    for k in ('start', 'end'):
        m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})\s*', str(raw.get(k, '')))
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            s[k] = f"{int(m.group(1)):02d}:{m.group(2)}"
    for k in ('seconds', 'mini_visible', 'mini_on_top'):
        if isinstance(raw.get(k), bool):
            s[k] = raw[k]
    if raw.get('theme') in ('light', 'dark', 'auto'):
        s['theme'] = raw['theme']
    p = raw.get('mini_pos')
    if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p):
        s['mini_pos'] = [int(p[0]), int(p[1])]
    return s


def load_settings(path=None):
    try:
        with open(path or settings_file(), 'r', encoding='utf-8') as f:
            return clean(json.load(f))
    except (OSError, ValueError):
        return dict(DEFAULTS)


def write_settings(s, path=None):
    path = path or settings_file()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)                            # не оставляем полузаписанный файл
    except OSError:
        pass


class Api:
    """Методы без «_» видны из JS как pywebview.api.<имя>."""

    def __init__(self, path=None):
        self._path = path
        self._s = load_settings(path)
        self._main = None
        self._mini = None
        self._pos_timer = None

    # ---- настройки ----
    def get_settings(self):
        return self._s

    def save_settings(self, patch):
        new = clean({**self._s, **(patch if isinstance(patch, dict) else {})})
        old, self._s = self._s, new
        write_settings(new, self._path)
        self._push()
        if old["mini_visible"] != new["mini_visible"] or old["mini_on_top"] != new["mini_on_top"]:
            self._apply_mini(old["mini_on_top"] != new["mini_on_top"])
        return new

    def _push(self):
        js = f"window.applySettings && window.applySettings({json.dumps(self._s, ensure_ascii=False)})"
        for w in (self._main, self._mini):
            if w is not None:
                try:
                    w.evaluate_js(js)
                except Exception:
                    pass

    # ---- окна ----
    def minimize(self):
        if self._main:
            self._main.minimize()

    def open_main(self):
        if self._main:
            try:
                self._main.restore()
                self._main.show()
            except Exception:
                pass

    def close_app(self):
        for w in (self._mini, self._main):
            if w is not None:
                try:
                    w.destroy()
                except Exception:
                    pass

    def _apply_mini(self, on_top_changed=False):
        w = self._mini
        if w is None:
            return
        try:
            if self._s["mini_visible"]:
                if on_top_changed:
                    w.on_top = self._s["mini_on_top"]
                w.show()
                w.on_top = self._s["mini_on_top"]
            else:
                w.hide()
        except Exception:
            pass                                          # не все версии pywebview умеют менять «поверх окон» на лету

    def _moved(self, x, y):
        if self._pos_timer:
            self._pos_timer.cancel()
        def done():
            self._s["mini_pos"] = [int(x), int(y)]
            write_settings(self._s, self._path)
        self._pos_timer = threading.Timer(0.5, done)      # пока тянут — не пишем файл на каждый пиксель
        self._pos_timer.daemon = True
        self._pos_timer.start()


def _window(webview, **kw):
    try:
        return webview.create_window(shadow=True, **kw)
    except TypeError:
        return webview.create_window(**kw)                # старый pywebview без параметра shadow


def mini_start_pos(webview, saved):
    if saved and saved[0] > -200 and saved[1] > -200:
        return saved
    try:
        scr = webview.screens[0]
        return [scr.width - MINI_SIZE[0] - 24, scr.height - MINI_SIZE[1] - 72]
    except Exception:
        return [60, 60]


def run():
    import webview
    api = Api()
    s = api.get_settings()
    bg = '#0e1116'
    api._main = _window(webview, title=TITLE, url=resource('ui/main.html'), js_api=api, width=MAIN_SIZE[0], height=MAIN_SIZE[1],
                        resizable=False, frameless=True, easy_drag=False, text_select=False, background_color=bg)
    x, y = mini_start_pos(webview, s["mini_pos"])
    api._mini = _window(webview, title=TITLE + ' — мини', url=resource('ui/mini.html'), js_api=api,
                        width=MINI_SIZE[0], height=MINI_SIZE[1], x=x, y=y, resizable=False, frameless=True, easy_drag=False,
                        on_top=s["mini_on_top"], hidden=not s["mini_visible"], text_select=False, background_color=bg)
    try:
        api._mini.events.moved += api._moved
    except Exception:
        pass
    api._main.events.closed += api.close_app              # закрыли главное — уходит и мини, иначе процесс не завершится
    webview.start()


def selftest():
    lines, ok = [], True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        lines.append(f"{'OK ' if cond else 'FAIL'} {name}")
    for f in ('main.html', 'mini.html', 'style.css', 'common.js', 'main.js', 'mini.js', 'shift.js'):
        check(f'ui/{f}', os.path.isfile(resource('ui/' + f)))
    try:
        import webview
        check('webview ' + str(getattr(webview, '__version__', '?')), True)
    except Exception as e:
        check(f'webview: {e}', False)
    tmp = os.path.join(tempfile.mkdtemp(), 'settings.json')
    write_settings(clean({"start": "8:30", "end": "17:45", "seconds": False, "theme": "dark"}), tmp)
    r = load_settings(tmp)
    check('настройки: запись и чтение', r["start"] == "08:30" and r["end"] == "17:45" and r["seconds"] is False and r["theme"] == "dark")
    check('настройки: мусор → по умолчанию', clean({"start": "99:99", "theme": 5}) == DEFAULTS)
    out = os.path.join(tempfile.gettempdir(), f'{APP_NAME}_selftest.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    run()
