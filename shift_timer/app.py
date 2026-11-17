"""GTime — мини-приложение: сколько отработано активного времени и сколько осталось до нормы.

Время идёт, пока Windows разблокирован, и стоит на блокировке. Журнал по дням (приход, уход, отработано, моменты
блокировки и разблокировки) — в приложении и в Excel. Живёт в фоне: значок в трее, автозапуск при входе в Windows. Главное окно + маленькое окошко без рамки Windows (поверх окон, тянется мышью).
Настройки — %APPDATA%\\GTime\\settings.json, журнал — history.json там же. Интерфейс — папка ui (HTML), окна — pywebview.

    python shift_timer/app.py            # запуск
    GTime.exe --selftest                  # проверка без окон: отчёт в %TEMP%\\GTime_selftest.txt
    GTime.exe --minimized                 # запуск в фоне, значок в трее (так стартует из автозапуска)
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

import chime
import tasks
import timetrack

APP_NAME = 'GTime'
OLD_APP_NAME = 'ShiftTimer'        # прежнее название: оттуда переносим журнал и настройки
TITLE = 'GTime'
DEFAULTS = {"norm": "08:00", "seconds": True, "theme": "auto", "autostart": True,
            "notify_hours": True, "notify_break": True, "break_min": 60, "sound": True, "volume": "mid", "lunch_min": 60, "mini_tasks": False,
            "mini_visible": False, "mini_on_top": True, "mini_pos": None}
MAIN_SIZE = (520, 700)            # не «телефонная» узкая колонка: шире и чуть выше
MINI_SIZE = (204, 100)
MINI_WIDE = 340                  # ширина мини-окна с развёрнутым списком задач (свёрнутое — MINI_SIZE[0])
MINI_MAX_H = 520                 # выше мини-окно не растёт (список задач дальше прокручивается)


def resource(rel):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def data_dir():
    return os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), APP_NAME)


def migrate_old_data(base=None):
    """Приложение раньше называлось ShiftTimer: журнал и настройки из его папки копируем в новую (старую не трогаем)."""
    import shutil
    base = base or os.environ.get('APPDATA') or os.path.expanduser('~')
    old, new = os.path.join(base, OLD_APP_NAME), os.path.join(base, APP_NAME)
    moved = []
    for f in ('history.json', 'settings.json'):
        src, dst = os.path.join(old, f), os.path.join(new, f)
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                os.makedirs(new, exist_ok=True)
                shutil.copy2(src, dst)
                moved.append(f)
            except OSError:
                pass
    return moved


def settings_file():
    return os.path.join(data_dir(), 'settings.json')


def tasks_file():
    return os.path.join(data_dir(), 'tasks.json')


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
    for k in ('seconds', 'mini_visible', 'mini_on_top', 'autostart', 'notify_hours', 'notify_break', 'sound', 'mini_tasks'):
        if isinstance(raw.get(k), bool):
            s[k] = raw[k]
    lm = raw.get('lunch_min')
    if isinstance(lm, int) and not isinstance(lm, bool) and 10 <= lm <= 180:
        s['lunch_min'] = lm
    bm = raw.get('break_min')
    if isinstance(bm, int) and not isinstance(bm, bool) and 15 <= bm <= 240:
        s['break_min'] = bm
    if raw.get('volume') in chime.LEVELS:
        s['volume'] = raw['volume']
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
            try:
                winreg.DeleteValue(k, OLD_APP_NAME)         # автозапуск старого ShiftTimer.exe не нужен
            except FileNotFoundError:
                pass
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

    def __init__(self, path=None, history=None, table=None, tracker=None, store=None):
        self._path = path
        self._s = load_settings(path)
        self._table = table
        self._tasks = store or tasks.TaskStore(tasks_file())
        self._screen_h = None
        self._screen_w = None
        self._t = tracker or timetrack.Tracker(history or history_file(), norm_seconds(self._s["norm"]))
        self._t.set_norm(norm_seconds(self._s["norm"]))
        self._apply_notify()
        self._t.set_lunch(self._s["lunch_min"] * 60)
        self._t.on_notice = self._notice
        self._t.on_tick = self._after_tick
        self._temp_mini_until = 0.0
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
        if new["sound"] and (old["volume"] != new["volume"] or not old["sound"]):
            chime.play_async(new["volume"])              # образец: сразу слышно, какая громкость выбрана
        if old["lunch_min"] != new["lunch_min"]:
            self._t.set_lunch(new["lunch_min"] * 60)
        if any(old[k] != new[k] for k in ("notify_hours", "notify_break", "break_min")):
            self._apply_notify()
        if old["autostart"] != new["autostart"]:
            set_autostart(new["autostart"])
        self._push()
        if old["mini_visible"] != new["mini_visible"] or old["mini_on_top"] != new["mini_on_top"]:
            self._apply_mini(old["mini_on_top"] != new["mini_on_top"])
        return new

    def _apply_notify(self):
        self._t.set_notify(self._s["notify_hours"], self._s["notify_break"], self._s["break_min"])

    def _notice(self, n):
        """Новое уведомление: мини-окно его покажет (JS забирает из get_day). Окно скрыто — покажем его на время уведомления."""
        if self._s["sound"]:
            chime.play_async(self._s["volume"])         # две тихие ноты
        w = self._mini
        if w is not None and not self._s["mini_visible"]:
            try:
                w.show()
                self._temp_mini_until = time.time() + timetrack.NOTICE_SECONDS + 1
            except Exception:
                pass

    def _after_tick(self):
        if self._temp_mini_until and time.time() > self._temp_mini_until:
            self._temp_mini_until = 0.0
            if not self._s["mini_visible"] and self._mini is not None:
                try:
                    self._mini.hide()
                except Exception:
                    pass

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
        d = self._t.snapshot()
        d["tasks"] = self._tasks.counts()                # сколько задач и сколько выполнено — для значка в мини-окне
        return d

    def get_history(self):
        return self._t.history()

    def edit_day(self, iso, arrival, leave, worked):
        return self._t.edit_day(iso, arrival, leave, worked)

    def delete_day(self, iso):
        return self._t.delete_day(iso)

    def event_kind(self, iso, idx, kind):
        return self._t.set_event_kind(iso, idx, kind)

    def suggest_worked(self, arrival):
        return self._t.suggest_worked(arrival)

    # ---- задачи на день ----
    def tasks_get(self):
        return self._tasks.get()

    def task_add(self, text):
        return self._tasks.add(text)

    def task_toggle(self, tid, done=None):
        return self._tasks.toggle(tid, done)

    def task_edit(self, tid, text):
        return self._tasks.edit(tid, text)

    def task_delete(self, tid):
        return self._tasks.delete(tid)

    def tasks_clear_done(self):
        return self._tasks.clear_done()

    def mini_resize(self, height, wide=False):
        """Мини-окно с задачами выше и шире обычного: растёт вправо и вниз, а у краёв экрана сдвигается, чтобы не уйти за него.
        wide=False — обычная ширина (список свёрнут)."""
        w = self._mini
        try:
            h = max(MINI_SIZE[1], min(MINI_MAX_H, int(height)))
        except (TypeError, ValueError):
            return {"error": "bad height"}
        width = MINI_WIDE if wide else MINI_SIZE[0]
        if w is not None:
            try:
                x, y = getattr(w, 'x', None), getattr(w, 'y', None)
                nx, ny = x, y
                if self._screen_h and isinstance(y, int) and y + h > self._screen_h - 40:
                    ny = max(0, self._screen_h - 40 - h)
                if self._screen_w and isinstance(x, int) and x + width > self._screen_w - 8:
                    nx = max(0, self._screen_w - 8 - width)
                if (nx, ny) != (x, y):
                    w.move(nx if nx is not None else 0, ny if ny is not None else 0)
                w.resize(width, h)
            except Exception:
                pass
        return {"height": h, "width": width}

    def lunch_toggle(self):
        """Кнопка «Обед»: начать обед или закончить идущий. Возвращает {"on": идёт ли обед}."""
        self._t.end_lunch() if self._t.snapshot()["lunch"]["on"] else self._t.start_lunch()
        return {"on": self._t.snapshot()["lunch"]["on"]}

    def skip_break(self, all_day=False):
        return self._t.skip_break(bool(all_day))

    def open_table(self):
        """Обновить Excel-таблицу из журнала и открыть её."""
        path = self._table or table_file()
        try:
            self._t.export_xlsx(path, self._tasks.all_rows())
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
            pystray.MenuItem(lambda item: 'Закончить обед' if api.get_day()["lunch"]["on"] else 'Обед', lambda icon, item: api.lunch_toggle()),
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
    migrate_old_data()
    api = Api()
    s = api.get_settings()
    set_autostart(s["autostart"])                        # путь к exe в автозапуске всегда актуальный
    api._tray = start_tray(api)
    background = '--minimized' in sys.argv
    bg = '#0e1116'
    api._main = _window(webview, title=TITLE, url=resource('ui/main.html'), js_api=api, width=MAIN_SIZE[0], height=MAIN_SIZE[1],
                        resizable=False, frameless=True, easy_drag=False, text_select=False, background_color=bg,
                        hidden=background and api._tray is not None, minimized=background and api._tray is None)
    try:
        api._screen_h = webview.screens[0].height
        api._screen_w = webview.screens[0].width
    except Exception:
        pass
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
    check('звук: нота строится', len(chime.make_wav(duration=0.2)) > 1000)
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
