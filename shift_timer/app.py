"""Конец смены — мини-приложение: сколько отработано активного времени и сколько осталось до нормы.

Время идёт, пока Windows разблокирован, и стоит на блокировке. Журнал по дням (приход, уход, отработано, моменты
блокировки и разблокировки) — в приложении и в Excel. Живёт в фоне: значок в трее, автозапуск при входе в Windows. Главное окно + маленькое окошко без рамки Windows (поверх окон, тянется мышью).
Настройки — %APPDATA%\\ShiftTimer\\settings.json, журнал — history.json там же. Интерфейс — папка ui (HTML), окна — pywebview.

    python shift_timer/app.py            # запуск
    ShiftTimer.exe --selftest            # проверка без окон: отчёт в %TEMP%\\ShiftTimer_selftest.txt
    ShiftTimer.exe --minimized           # запуск в фоне, значок в трее (так стартует из автозапуска)
"""
import json
import os
import re
import sys
import tempfile
import threading

import timetrack

APP_NAME = 'ShiftTimer'
TITLE = 'Конец смены'
DEFAULTS = {"norm": "08:00", "seconds": True, "theme": "auto", "autostart": True,
            "mini_visible": False, "mini_on_top": True, "mini_pos": None}
MAIN_SIZE = (380, 690)
MINI_SIZE = (204, 100)


def resource(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def data_dir():
    return os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), APP_NAME)


def settings_file():
    return os.path.join(data_dir(), 'settings.json')


def history_file():
    return os.path.join(data_dir(), 'history.json')


def table_file():
    return os.path.join(os.path.expanduser('~'), 'Documents', APP_NAME, 'Учёт_времени.xlsx')


def norm_seconds(norm):
    return (timetrack.to_sec(norm) or 8 * 3600)


def clean(raw):
    """Любой мусор из файла / из окна → корректные настройки (остальное — по умолчанию)."""
    s = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return s
    sec = timetrack.to_sec(raw.get('norm'))
    if sec is not None and 15 * 60 <= sec < 24 * 3600:
        s['norm'] = timetrack.hm_text(sec)
    for k in ('seconds', 'mini_visible', 'mini_on_top', 'autostart'):
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


def set_autostart(on):
    """Запуск при входе в Windows (раздел Run текущего пользователя). Только для собранного exe."""
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}" --minimized')
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


class Api:
    """Методы без «_» видны из JS как pywebview.api.<имя>."""

    def __init__(self, path=None, history=None, table=None, tracker=None):
        self._path = path
        self._s = load_settings(path)
        self._table = table
        self._t = tracker or timetrack.Tracker(history or history_file(), norm_seconds(self._s["norm"]))
        self._t.set_norm(norm_seconds(self._s["norm"]))
        self._main = None
        self._mini = None
        self._tray = None
        self._pos_timer = None

    # ---- настройки ----
    def get_settings(self):
        return self._s

    def save_settings(self, patch):
        new = clean({**self._s, **(patch if isinstance(patch, dict) else {})})
        old, self._s = self._s, new
        write_settings(new, self._path)
        if old["norm"] != new["norm"]:
            self._t.set_norm(norm_seconds(new["norm"]))
        if old["autostart"] != new["autostart"]:
            set_autostart(new["autostart"])
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

    # ---- учёт времени ----
    def get_day(self):
        return self._t.snapshot()

    def get_history(self):
        return self._t.history()

    def edit_day(self, iso, arrival, leave, worked):
        return self._t.edit_day(iso, arrival, leave, worked)

    def delete_day(self, iso):
        return self._t.delete_day(iso)

    def open_table(self):
        """Обновить Excel-таблицу из журнала и открыть её."""
        path = self._table or table_file()
        try:
            self._t.export_xlsx(path)
        except PermissionError:
            return {"error": "Файл таблицы открыт в Excel — закройте его и повторите."}
        except Exception as e:
            return {"error": f"Не удалось записать таблицу: {e}"}
        try:
            os.startfile(path)                           # только Windows
        except Exception:
            pass
        return {"path": path}

    # ---- окна ----
    def minimize(self):
        if self._main:
            self._main.minimize()

    def open_main(self):
        if self._main:
            try:
                self._main.show()
                self._main.restore()
            except Exception:
                pass

    def can_tray(self):
        return self._tray is not None

    def hide_main(self):
        """Убрать окно в фон: значок остаётся в трее, учёт времени идёт."""
        if self._main and self._tray is not None:
            try:
                self._main.hide()
            except Exception:
                self._main.minimize()
        elif self._main:
            self._main.minimize()

    def toggle_mini(self):
        self.save_settings({"mini_visible": not self._s["mini_visible"]})

    def close_app(self):
        self._t.stop()                                   # журнал — на диск до закрытия окон
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
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


def start_tray(api):
    """Значок у часов: двойной клик — открыть, меню — мини-окно и выход. Нет pystray / не вышло — None (будет обычное сворачивание)."""
    try:
        import pystray
        from PIL import Image
        img = Image.open(resource('icon.ico'))
        menu = pystray.Menu(
            pystray.MenuItem('Открыть', lambda icon, item: api.open_main(), default=True),
            pystray.MenuItem('Мини-окно', lambda icon, item: api.toggle_mini(), checked=lambda item: api.get_settings()["mini_visible"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Выйти (учёт остановится)', lambda icon, item: api.close_app()))
        icon = pystray.Icon(APP_NAME, img, TITLE, menu)
        icon.run_detached()
        return icon
    except Exception:
        return None


def run():
    import webview
    api = Api()
    s = api.get_settings()
    set_autostart(s["autostart"])                        # путь к exe в автозапуске всегда актуальный
    api._tray = start_tray(api)
    background = '--minimized' in sys.argv
    bg = '#0e1116'
    api._main = _window(webview, title=TITLE, url=resource('ui/main.html'), js_api=api, width=MAIN_SIZE[0], height=MAIN_SIZE[1],
                        resizable=False, frameless=True, easy_drag=False, text_select=False, background_color=bg,
                        hidden=background and api._tray is not None, minimized=background and api._tray is None)
    x, y = mini_start_pos(webview, s["mini_pos"])
    api._mini = _window(webview, title=TITLE + ' — мини', url=resource('ui/mini.html'), js_api=api,
                        width=MINI_SIZE[0], height=MINI_SIZE[1], x=x, y=y, resizable=False, frameless=True, easy_drag=False,
                        on_top=s["mini_on_top"], hidden=not s["mini_visible"], text_select=False, background_color=bg)
    try:
        api._mini.events.moved += api._moved
    except Exception:
        pass
    api._main.events.closed += api.close_app              # закрыли главное — уходит и мини, иначе процесс не завершится
    threading.Thread(target=api._t.run, daemon=True).start()   # секундный учёт времени
    webview.start()
    api._t.stop()


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
    tmpd = tempfile.mkdtemp()
    p = os.path.join(tmpd, 'settings.json')
    write_settings(clean({"norm": "7:30", "seconds": False, "theme": "dark"}), p)
    r = load_settings(p)
    check('настройки: запись и чтение', r["norm"] == "07:30" and r["seconds"] is False and r["theme"] == "dark")
    check('настройки: мусор → по умолчанию', clean({"norm": "99:99", "theme": 5}) == DEFAULTS)
    t = timetrack.Tracker(os.path.join(tmpd, 'h.json'))
    t.tick()
    check('журнал: день создаётся', len(t.history()["rows"]) == 1)
    try:
        t.export_xlsx(os.path.join(tmpd, 't.xlsx'))
        check('таблица Excel', os.path.getsize(os.path.join(tmpd, 't.xlsx')) > 1000)
    except Exception as e:
        check(f'таблица Excel: {e}', False)
    check('блокировка: функция отвечает', timetrack.is_locked() in (True, False))
    try:
        import pystray
        from PIL import Image
        Image.open(resource('icon.ico'))
        check('значок в трее: pystray + иконка', bool(pystray))
    except Exception as e:
        check(f'значок в трее: {e}', False)
    out = os.path.join(tempfile.gettempdir(), f'{APP_NAME}_selftest.txt')
    with open(out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return 0 if ok else 1


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    run()
