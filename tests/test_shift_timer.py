"""Мини-приложение GTime (shift_timer/): учёт активного времени, журнал, Excel, настройки (JS — через node)."""
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import app as shift_app                                    # noqa: E402
import chime                                               # noqa: E402
import tasks                                               # noqa: E402
import timetrack                                           # noqa: E402


class Clock:
    """Управляемые часы: wall — настенное время, mono — монотонное; locked — экран заблокирован."""

    def __init__(self, y=2026, mo=11, d=17, h=9, mi=0, s=0):
        self.wall = datetime(y, mo, d, h, mi, s).timestamp()
        self.m = 1000.0
        self.locked = False

    def advance(self, sec, steps=None):
        """Пройти sec секунд шагами по 1 с (как секундный цикл)."""
        for _ in range(steps or int(sec)):
            self.wall += 1
            self.m += 1
            yield

    def tracker(self, path, norm=8 * 3600):
        return timetrack.Tracker(path, norm, clock=lambda: self.wall, mono=lambda: self.m, locked=lambda: self.locked)


def run(clock, tr, sec):
    for _ in clock.advance(sec):
        tr.tick()


def test_counts_only_unlocked_time(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 3600)                                       # час работы
    c.locked = True
    run(c, tr, 1800)                                       # полчаса блокировки
    c.locked = False
    run(c, tr, 600)                                        # ещё 10 минут
    s = tr.snapshot()
    assert abs(s["worked_s"] - (3600 + 600)) <= 2          # блокировка не вошла; потеряна максимум секунда на разблокировке
    assert s["arrival"] == "09:00:00" and s["leave"] == "10:40:00"
    assert 1790 <= s["break_s"] <= 1810                    # перерыв = блокировка
    assert s["locked"] is False


def test_lock_state_visible_and_time_frozen(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 100)
    c.locked = True
    run(c, tr, 5)
    frozen = tr.snapshot()["worked_s"]
    assert tr.snapshot()["locked"] is True
    run(c, tr, 600)
    assert tr.snapshot()["worked_s"] == frozen             # пока заблокировано — не растёт


def test_sleep_gap_is_not_work(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 60)
    c.wall += 7200
    c.m += 7200                                            # компьютер спал два часа, тик один
    tr.tick()
    assert tr.snapshot()["worked_s"] < 70                  # два часа сна не засчитаны


def test_arrival_is_first_unlocked_moment(tmp_path):
    c = Clock(h=8, mi=0)
    c.locked = True                                        # приложение стартовало до входа в систему
    tr = c.tracker(str(tmp_path / 'h.json'))
    run(c, tr, 1800)
    assert tr.snapshot()["arrival"] is None and tr.history()["rows"] == []
    c.locked = False
    run(c, tr, 10)
    assert tr.snapshot()["arrival"] == "08:30:01"


def test_midnight_starts_new_day(tmp_path):
    c = Clock(h=23, mi=59, s=30)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 90)
    rows = tr.history()["rows"]
    assert [r["date"] for r in rows] == ['2026-11-18', '2026-11-17']
    assert rows[1]["worked_s"] > 25 and rows[0]["worked_s"] > 55


def test_persistence_and_restart_same_day(tmp_path):
    f = str(tmp_path / 'sub' / 'h.json')
    c = Clock()
    tr = c.tracker(f)
    tr.tick()
    run(c, tr, 1200)
    tr.stop()
    c.wall += 600
    c.m += 600                                             # приложение было закрыто 10 минут
    tr2 = c.tracker(f)
    tr2.tick()
    run(c, tr2, 60)
    s = tr2.snapshot()
    assert abs(s["worked_s"] - 1260) <= 3                  # продолжили тот же день, закрытые 10 минут не посчитаны
    assert s["arrival"] == "09:00:00"
    assert not os.path.exists(f + '.tmp')


def test_broken_history_file_is_ignored(tmp_path):
    f = tmp_path / 'h.json'
    f.write_text('{ не json', encoding='utf-8')
    assert Clock().tracker(str(f)).history()["rows"] == []
    f.write_text('{"days": {"2026-11-01": {"arrival": "09:00:00", "leave": "bad", "worked": "x"}, "junk": 1}}', encoding='utf-8')
    assert Clock().tracker(str(f)).history()["rows"] == []


def test_norm_and_remaining_math(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=2 * 3600)
    tr.tick()
    run(c, tr, 600)
    s = tr.snapshot()
    assert s["norm_s"] == 7200
    tr.set_norm(3 * 3600)                                  # норму сменили — сегодняшний день следует за ней
    assert tr.snapshot()["norm_s"] == 10800
    h = tr.history()
    assert h["month"]["norm_s"] == 10800 and h["rows"][0]["delta_s"] < 0


def test_edit_add_delete_day(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    assert tr.edit_day('2026-11-10', '09:05', '18:20', '08:00') == {"ok": True}
    r = next(x for x in tr.history()["rows"] if x["date"] == '2026-11-10')
    assert (r["arrival"], r["leave"], r["worked_s"], r["weekday"]) == ('09:05:00', '18:20:00', 28800.0, 'вт')
    assert r["break_s"] == 9 * 3600 + 15 * 60 - 28800
    assert 'Уход раньше' in tr.edit_day('2026-11-10', '18:00', '09:00', '01:00')["error"]
    assert 'больше' in tr.edit_day('2026-11-10', '09:00', '10:00', '02:00')["error"]
    assert 'формате' in tr.edit_day('2026-11-10', 'xx', '10:00', '01:00')["error"]
    assert 'дата' in tr.edit_day('вчера', '09:00', '10:00', '01:00')["error"].lower()
    tr.delete_day('2026-11-10')
    assert tr.history()["rows"] == []


def test_edit_today_keeps_live_leave(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 3600)
    assert tr.edit_day('2026-11-17', '08:30', '09:00', '01:15') == {"ok": True}   # «уход» за сегодня правка не трогает
    s = tr.snapshot()
    assert s["arrival"] == "08:30:00" and s["leave"] == "10:00:00" and s["worked_s"] == 4500


def test_excel_export(tmp_path):
    import openpyxl
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.edit_day('2026-11-10', '09:05', '18:20', '08:00')
    tr.edit_day('2026-11-11', '10:00', '17:30', '07:00')
    p = tr.export_xlsx(str(tmp_path / 'out' / 'Учёт_времени.xlsx'))
    ws = openpyxl.load_workbook(p).active
    rows = [[c.value for c in r] for r in ws.iter_rows()]
    assert rows[0] == ['Дата', 'День', 'Приход', 'Уход', 'Отработано', 'Перерывы', 'Обед', 'Норма', 'Разница, мин']
    assert rows[1][0].date().isoformat() == '2026-11-10' and rows[1][1] == 'вт'
    assert rows[1][4] == timedelta(hours=8) and rows[1][8] == 0      # [h]:mm читается как timedelta; колонки: … Перерывы, Обед, Норма, Разница
    assert rows[2][8] == -60                               # 7 ч при норме 8 ч → −60 мин
    assert rows[3][0] == 'Итого' and rows[3][4] == '=SUM(E2:E3)'


def test_is_locked_is_safe_off_windows():
    if sys.platform != 'win32':
        assert timetrack.is_locked() is False


def test_clean_settings():
    assert shift_app.clean(None) == shift_app.DEFAULTS
    s = shift_app.clean({"norm": "7:30", "seconds": False, "theme": "dark", "mini_pos": [10.7, -5], "autostart": True})
    assert (s["norm"], s["seconds"], s["theme"], s["mini_pos"], s["autostart"]) == ("07:30", False, "dark", [10, -5], True)
    assert shift_app.clean({"norm": "00:05", "theme": "pink", "seconds": "yes", "mini_pos": [1]}) == shift_app.DEFAULTS
    assert shift_app.clean({"norm": "24:00"}) ["norm"] == "08:00"


def make_api(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    return c, shift_app.Api(str(tmp_path / 's.json'), table=str(tmp_path / 'T' / 'Учёт.xlsx'), tracker=tr,
                            store=tasks.TaskStore(str(tmp_path / 'tasks.json'), clock=lambda: c.wall))


def test_api_settings_roundtrip_and_norm_sync(tmp_path):
    c, api = make_api(tmp_path)
    api._t.tick()
    s = api.save_settings({"norm": "07:00", "seconds": False, "theme": "light", "bogus": 1})
    assert s["norm"] == "07:00" and s["seconds"] is False and "bogus" not in s
    assert api.get_day()["norm_s"] == 7 * 3600
    assert shift_app.load_settings(str(tmp_path / 's.json')) == s
    assert api.save_settings({"norm": "banana"})["norm"] == "08:00"       # неверное значение → по умолчанию, не падаем
    assert api.save_settings("мусор")["norm"] == "08:00"


class FakeWin:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, js):
        self.calls.append(('js', js))

    def show(self):
        self.calls.append(('show',))

    def hide(self):
        self.calls.append(('hide',))

    def destroy(self):
        self.calls.append(('destroy',))

    def resize(self, w, h):
        self.calls.append(('resize', w, h))

    def move(self, x, y):
        self.calls.append(('move', x, y))


def test_mini_visibility_and_push(tmp_path):
    c, api = make_api(tmp_path)
    api._main, api._mini = FakeWin(), FakeWin()
    api.save_settings({"mini_visible": True})
    assert ('show',) in api._mini.calls and any(x[0] == 'js' and '"mini_visible": true' in x[1] for x in api._main.calls)
    api.save_settings({"mini_visible": False})
    assert ('hide',) in api._mini.calls
    n = len(api._mini.calls)
    api.save_settings({"theme": "dark"})
    assert [x for x in api._mini.calls[n:] if x[0] in ('show', 'hide')] == []


def test_close_app_saves_journal_and_closes_windows(tmp_path):
    c, api = make_api(tmp_path)
    api._main, api._mini = FakeWin(), FakeWin()
    api._t.tick()
    api.close_app()
    assert os.path.exists(str(tmp_path / 'h.json'))
    assert ('destroy',) in api._main.calls and ('destroy',) in api._mini.calls


def test_hide_to_tray_or_minimize(tmp_path):
    class W(FakeWin):
        def minimize(self):
            self.calls.append(('minimize',))
    c, api = make_api(tmp_path)
    api._main = W()
    assert api.can_tray() is False
    api.hide_main()                                        # трея нет — просто сворачиваем, окно не пропадает насовсем
    assert api._main.calls == [('minimize',)]
    api._tray = type('T', (), {'stop': lambda self: None})()
    assert api.can_tray() is True
    api.hide_main()
    assert ('hide',) in api._main.calls
    api.open_main()
    assert ('show',) in api._main.calls


def test_autostart_on_by_default(tmp_path):
    assert shift_app.DEFAULTS["autostart"] is True
    assert shift_app.set_autostart(True) is False or sys.platform == 'win32'    # вне Windows / не exe реестр не трогаем


def test_open_table_creates_file(tmp_path):
    c, api = make_api(tmp_path)
    api.edit_day('2026-11-10', '09:00', '18:00', '08:00')
    r = api.open_table()
    assert r["path"].endswith('Учёт.xlsx') and os.path.getsize(r["path"]) > 1000


def test_selftest_without_webview_reports_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, 'webview', None)
    assert shift_app.selftest() == 1


# ---------- события блокировки / разблокировки ----------
def hm(iso):
    return iso[11:19]


def test_lock_and_unlock_times_are_recorded(tmp_path):
    c = Clock(h=9, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 3600)                                       # 09:00 → 10:00 работа
    c.locked = True
    run(c, tr, 900)                                        # 10:00 → 10:15 блокировка
    c.locked = False
    run(c, tr, 60)
    ev = tr.history()["rows"][0]["events"]
    assert len(ev) == 1 and ev[0]["kind"] == "lock"
    assert hm(ev[0]["lock"]) in ("09:59:59", "10:00:00") and hm(ev[0]["unlock"]) == "10:15:01"
    assert 895 <= ev[0]["dur_s"] <= 905
    assert tr.snapshot()["events_n"] == 1


def test_open_lock_counts_duration_until_now(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 60)
    c.locked = True
    run(c, tr, 300)
    ev = tr.history()["rows"][0]["events"][0]
    assert ev["unlock"] is None and 295 <= ev["dur_s"] <= 305


def test_many_locks_in_a_day(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    for _ in range(3):
        run(c, tr, 600)
        c.locked = True
        run(c, tr, 120)
        c.locked = False
    run(c, tr, 10)
    assert len(tr.history()["rows"][0]["events"]) == 3


def test_morning_unlock_after_night_lock_starts_new_day(tmp_path):
    """Вечером заблокировали, всю ночь заблокировано, утром разблокировали: уход вчера, приход сегодня, время пошло."""
    c = Clock(h=17, mi=59, s=0)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 60)                                         # до 18:00
    c.locked = True
    c.wall += 15 * 3600 + 3600                             # ночь (в блокировке, тики редкие — компьютер мог спать)
    c.m += 15 * 3600 + 3600
    tr.tick()                                              # 10:00 следующего дня, ещё заблокировано
    c.locked = False
    tr.tick()
    run(c, tr, 600)
    rows = tr.history()["rows"]
    assert [r["date"] for r in rows] == ['2026-11-18', '2026-11-17']
    assert rows[0]["arrival"] == "10:00:00" and rows[0]["worked_s"] >= 590          # утром время пошло с разблокировки
    assert rows[1]["leave"] in ("17:59:59", "18:00:00") and rows[1]["worked_s"] < 70    # вчера — только до блокировки
    ev = rows[1]["events"]                                                           # блокировка записана вчерашним днём, разблокировка — завтрашней датой
    assert len(ev) == 1 and ev[0]["lock"][:10] == '2026-11-17' and ev[0]["unlock"][:10] == '2026-11-18'


def test_sleep_without_lock_is_an_event(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 120)
    c.wall += 5400
    c.m += 5400                                            # крышку закрыли на полтора часа, блокировки не было
    tr.tick()
    ev = tr.history()["rows"][0]["events"]
    assert len(ev) == 1 and ev[0]["kind"] == "sleep" and 5390 <= ev[0]["dur_s"] <= 5410


def test_lock_after_sleep_starts_at_last_active_moment(tmp_path):
    c = Clock(h=12, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 100)                                        # 12:01:40 — последний живой тик
    c.wall += 7200
    c.m += 7200                                            # сон, после пробуждения — экран входа (заблокировано)
    c.locked = True
    tr.tick()
    c.wall += 30
    c.m += 30
    c.locked = False
    tr.tick()
    ev = tr.history()["rows"][0]["events"]
    assert len(ev) == 1 and ev[0]["kind"] == "lock"
    assert hm(ev[0]["lock"]) == "12:01:40"                 # а не момент пробуждения


def test_shutdown_while_locked_closes_event_at_last_alive(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock(h=17, mi=0)
    tr = c.tracker(f)
    tr.tick()
    run(c, tr, 60)
    c.locked = True
    run(c, tr, 1200)                                       # заблокировали в 17:01, тики идут — файл обновляется
    tr.save()                                              # (в жизни — раз в 15 с)
    # компьютер выключили без корректного закрытия: unlock в файле нет
    tr2 = Clock(y=2026, mo=11, d=18, h=9).tracker(f)
    ev = tr2.history()["rows"][0]["events"][0]
    assert ev["unlock"] is not None and hm(ev["unlock"]) == "17:21:00"             # закрыто по метке «жива»
    assert 1195 <= ev["dur_s"] <= 1205


def test_events_survive_restart_and_edit(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock()
    tr = c.tracker(f)
    tr.tick()
    run(c, tr, 100)
    c.locked = True
    run(c, tr, 100)
    c.locked = False
    run(c, tr, 10)
    tr.stop()
    tr2 = c.tracker(f)
    assert len(tr2.history()["rows"][0]["events"]) == 1
    tr2.edit_day('2026-11-17', '08:50', '09:00', '00:01')                           # правка дня события не стирает
    assert len(tr2.history()["rows"][0]["events"]) == 1


def test_excel_events_sheet(tmp_path):
    import openpyxl
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 100)
    c.locked = True
    run(c, tr, 600)
    c.locked = False
    run(c, tr, 5)
    wb = openpyxl.load_workbook(tr.export_xlsx(str(tmp_path / 'o.xlsx')))
    ws = wb['Блокировки']
    rows = [[x.value for x in r] for r in ws.iter_rows()]
    assert rows[0] == ['День', 'Тип', 'Заблокирован', 'Разблокирован', 'Длительность']
    assert rows[1][1] == 'блокировка' and rows[1][3] > rows[1][2] and abs(rows[1][4].total_seconds() - 600) <= 5


# ---------- уведомления: ровные часы и перерыв ----------
class Notes:
    """Собирает уведомления tracker-а по порядку."""
    def __init__(self, tr):
        self.items = []
        tr.on_notice = lambda n: self.items.append((n["kind"], n["text"]))


def test_hour_notices_each_full_hour(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=3 * 3600)
    tr.set_notify(True, False, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 3 * 3600 + 30)
    assert n.items == [("hour", "Осталось 2 часа"), ("hour", "Остался 1 час"), ("done", "Норма выполнена — можно заканчивать")]


def test_hour_notice_wording():
    assert timetrack.hours_left_text(7) == "Осталось 7 часов" and timetrack.hours_left_text(5) == "Осталось 5 часов"
    assert timetrack.hours_left_text(2) == "Осталось 2 часа" and timetrack.hours_left_text(4) == "Осталось 4 часа"
    assert timetrack.hours_left_text(1) == "Остался 1 час" and timetrack.hours_left_text(11) == "Осталось 11 часов"
    assert timetrack.hours_left_text(21) == "Остался 21 час" and timetrack.hours_left_text(6) == "Осталось 6 часов"


def test_eight_hour_norm_gives_7_to_1(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock()
    tr = c.tracker(f, norm=8 * 3600)
    tr.set_notify(True, False, 60)
    n = Notes(tr)
    tr.tick()
    for _ in range(8 * 3600 + 10):                         # весь день одним прогоном
        c.wall += 1; c.m += 1
        tr.tick()
    texts = [t for k, t in n.items if k == "hour"]
    assert texts == ["Осталось 7 часов", "Осталось 6 часов", "Осталось 5 часов", "Осталось 4 часа", "Осталось 3 часа", "Осталось 2 часа", "Остался 1 час"]


def test_old_hours_are_silent_after_restart_and_not_repeated(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock()
    tr = c.tracker(f, norm=3 * 3600)
    tr.set_notify(True, False, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 3700)                                       # 2 часа уже объявлены
    assert len(n.items) == 1
    tr.stop()
    tr2 = c.tracker(f, norm=3 * 3600)
    tr2.set_notify(True, False, 60)
    n2 = Notes(tr2)
    tr2.tick()
    run(c, tr2, 400)
    assert n2.items == []                                  # после перезапуска «Осталось 2 часа» не повторяется
    tr2.stop()
    # день записан без пометок (старый файл) — и работа уже за границей часа: молча, а не залпом
    import json as _j
    data = _j.load(open(f, encoding='utf-8'))
    data["days"]["2026-11-17"]["notified"] = []
    _j.dump(data, open(f, 'w', encoding='utf-8'))
    tr3 = c.tracker(f, norm=3 * 3600)
    tr3.set_notify(True, False, 60)
    n3 = Notes(tr3)
    tr3.tick()
    run(c, tr3, 10)
    assert n3.items == []


def test_notifications_can_be_switched_off(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=2 * 3600)
    tr.set_notify(False, False, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 2 * 3600 + 10)
    assert n.items == []


def test_break_reminder_after_long_work_and_repeats(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=20 * 3600)
    tr.set_notify(False, True, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 59 * 60)
    assert n.items == []
    run(c, tr, 120)
    assert n.items == [("break", "Вы работаете уже 1 ч подряд — сделайте небольшой перерыв")]
    run(c, tr, 59 * 60)
    assert len(n.items) == 2 and "2 ч" in n.items[1][1]                # и снова через час


def test_long_lock_resets_work_streak_short_lock_does_not(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=20 * 3600)
    tr.set_notify(False, True, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 40 * 60)
    c.locked = True
    run(c, tr, 60)                                         # минута блокировки — не перерыв
    c.locked = False
    run(c, tr, 21 * 60)
    assert len(n.items) == 1                               # 40 + 21 мин непрерывно (блок < 3 мин не считается перерывом)
    c.locked = True
    run(c, tr, 5 * 60)                                     # 5 минут — настоящий перерыв
    c.locked = False
    run(c, tr, 50 * 60)
    assert len(n.items) == 1                               # счёт пошёл заново, 50 мин ещё не час
    run(c, tr, 11 * 60)
    assert len(n.items) == 2


def test_sleep_resets_streak(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=20 * 3600)
    tr.set_notify(False, True, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 50 * 60)
    c.wall += 1200
    c.m += 1200                                            # сон 20 минут
    tr.tick()
    run(c, tr, 30 * 60)
    assert n.items == []                                   # 30 мин после сна, а не 80


def test_notice_visible_in_snapshot_for_ten_seconds(tmp_path):
    c = Clock()
    tr = c.tracker(str(tmp_path / 'h.json'), norm=2 * 3600)
    tr.set_notify(True, False, 60)
    tr.tick()
    run(c, tr, 3600)
    s = tr.snapshot()
    assert s["notice"] and s["notice"]["kind"] == "hour" and s["notice"]["text"] == "Остался 1 час"
    nid = s["notice"]["id"]
    run(c, tr, 11)
    assert tr.snapshot()["notice"] is None
    run(c, tr, 3600)
    assert tr.snapshot()["notice"] is None or tr.snapshot()["notice"]["id"] > nid


def test_api_notice_shows_hidden_mini_then_hides(tmp_path, monkeypatch):
    c, api = make_api(tmp_path)
    api._mini = FakeWin()
    api._notice({"id": 1, "kind": "hour", "text": "Осталось 7 часов"})
    assert ('show',) in api._mini.calls                    # мини было скрыто — показали на время уведомления
    api._mini.calls.clear()
    api._after_tick()
    assert api._mini.calls == []                           # ещё рано
    api._temp_mini_until = 1.0
    api._after_tick()
    assert ('hide',) in api._mini.calls
    api.save_settings({"mini_visible": True})              # мини включено пользователем — не прячем и не трогаем
    api._mini.calls.clear()
    api._notice({"id": 2, "kind": "break", "text": "x"})
    api._temp_mini_until = 1.0
    api._after_tick()
    assert api._mini.calls == []


def test_notify_settings_roundtrip(tmp_path):
    c, api = make_api(tmp_path)
    s = api.save_settings({"notify_hours": False, "notify_break": True, "break_min": 45})
    assert (s["notify_hours"], s["notify_break"], s["break_min"]) == (False, True, 45)
    assert api._t.opts == {"hours": False, "brk": True, "brk_min": 45}
    assert api.save_settings({"break_min": 5})["break_min"] == 60 and api.save_settings({"break_min": "x"})["break_min"] == 60
    assert shift_app.DEFAULTS["notify_hours"] and shift_app.DEFAULTS["notify_break"] and shift_app.DEFAULTS["break_min"] == 60


# ---------- «пришёл в 9, открыл приложение в 11» ----------
def test_set_arrival_and_worked_by_hand_then_time_continues(tmp_path):
    c = Clock(h=11, mi=0)                                   # приложение открыли в 11:00, а пришли в 9:00
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 300)                                         # 11:05
    assert tr.snapshot()["arrival"] == "11:00:00"
    assert tr.edit_day('2026-11-17', '09:00', '11:05', '02:05') == {"ok": True}      # пришёл в 9, отработано уже 2:05
    s = tr.snapshot()
    assert s["arrival"] == "09:00:00" and s["worked_s"] == 125 * 60
    run(c, tr, 600)                                         # время продолжает идти от введённого
    s = tr.snapshot()
    assert 125 * 60 + 595 <= s["worked_s"] <= 125 * 60 + 605 and s["arrival"] == "09:00:00"
    assert s["leave"] == "11:15:00"


def test_manual_arrival_survives_next_ticks_and_restart(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock(h=11, mi=0)
    tr = c.tracker(f)
    tr.tick()
    run(c, tr, 60)
    tr.edit_day('2026-11-17', '08:45', '11:01', '02:00')
    run(c, tr, 30)
    tr.stop()
    tr2 = c.tracker(f)
    tr2.tick()
    s = tr2.snapshot()
    assert s["arrival"] == "08:45:00" and s["worked_s"] >= 7200      # приход не затирается ни тиком, ни перезапуском


def test_suggest_worked_subtracts_locks(tmp_path):
    c = Clock(h=11, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.tick()
    run(c, tr, 600)                                         # 11:10
    c.locked = True
    run(c, tr, 600)                                         # 11:10 → 11:20 блокировка
    c.locked = False
    run(c, tr, 600)                                         # 11:30
    assert tr.suggest_worked('09:00') in range(150 * 60 - 12 * 60 - 5, 150 * 60 - 8 * 60 + 5)    # 2:30 от прихода минус ~10 мин блока
    assert tr.suggest_worked('11:00') in range(20 * 60 - 5, 20 * 60 + 5)                         # с 11:00: 30 мин − блок 10 мин
    assert tr.suggest_worked('12:00') is None                                                    # приход в будущем — нельзя
    assert tr.suggest_worked('xx') is None


def test_api_suggest_and_edit_today_roundtrip(tmp_path):
    c, api = make_api(tmp_path)
    c.wall = datetime(2026, 11, 17, 11, 0, 0).timestamp()          # приложение открыли в 11:00
    api._t.tick()
    run(c, api._t, 300)                                            # 11:05
    sec = api.suggest_worked('09:00')
    assert sec == 125 * 60                                         # с 9:00 до 11:05 — блокировок не было
    h, m = divmod(sec // 60, 60)
    assert api.edit_day('2026-11-17', '09:00', '11:05', f'{h:02d}:{m:02d}')["ok"] is True
    d = api.get_day()
    assert d["arrival"] == "09:00:00" and d["worked_s"] == 7500
    assert api.suggest_worked('13:00') is None                      # приход позже, чем сейчас


# ---------- перерыв не обязателен: пропустить ----------
def test_skip_break_for_the_day_stops_break_reminders_only(tmp_path):
    f = str(tmp_path / 'h.json')
    c = Clock()
    tr = c.tracker(f, norm=3 * 3600)
    tr.set_notify(True, True, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 61 * 60)
    assert [k for k, _ in n.items if k == "break"] == ["break"]
    tr.skip_break(True)                                    # «Не сегодня»
    run(c, tr, 2 * 3600)
    assert [k for k, _ in n.items if k == "break"] == ["break"]            # новых напоминаний о перерыве нет
    assert any(k == "hour" for k, _ in n.items) and any(k == "done" for k, _ in n.items)    # часы и «норма» работают
    tr.stop()
    tr2 = c.tracker(f, norm=3 * 3600)                      # перезапуск в тот же день — выбор сохранён
    tr2.set_notify(False, True, 60)
    n2 = Notes(tr2)
    tr2.tick()
    run(c, tr2, 2 * 3600)
    assert n2.items == []


def test_skip_break_resets_next_day(tmp_path):
    c = Clock(h=22, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'), norm=20 * 3600)
    tr.set_notify(False, True, 60)
    when = []
    tr.on_notice = lambda n: when.append(datetime.fromtimestamp(c.wall).date().isoformat())
    tr.tick()
    tr.skip_break(True)
    run(c, tr, 3 * 3600)                                   # 22:00 → 01:00: на границе суток работа без перерыва продолжается
    assert when and set(when) == {'2026-11-18'}            # в день «Не сегодня» (17.11) тишина, на следующий день напоминания снова


def test_plain_skip_changes_nothing_and_api_works(tmp_path):
    c, api = make_api(tmp_path)
    assert api.skip_break(False) == {"ok": True}
    assert api.skip_break(True) == {"ok": True}
    assert api._t.days[api._t.snapshot()["date"]]["no_break"] is True


# ---------- обед: отдельный таймер ----------
def lunch_tracker(tmp_path, c, name='h.json', norm=8 * 3600):
    tr = c.tracker(str(tmp_path / name), norm=norm)
    tr.set_lunch(3600)
    tr.set_notify(False, False, 60)
    return tr


def test_lunch_pauses_work_and_timer_runs(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 600)
    w0 = tr.snapshot()["worked_s"]
    tr.start_lunch()
    run(c, tr, 1200)                                       # 20 минут обеда у компьютера
    s = tr.snapshot()
    assert s["lunch"]["on"] and abs(s["lunch"]["elapsed_s"] - 1200) <= 2
    assert s["worked_s"] == w0                             # рабочее время на обеде стоит
    assert abs(s["lunch"]["plan_s"] - 2400) <= 2           # до конца обеда ещё 40 минут (для прогноза ухода)


def test_lunch_timer_runs_through_lock_and_resumes_work(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 60)
    tr.start_lunch()
    c.locked = True
    run(c, tr, 1800)                                       # пол-часа обеда при заблокированном экране
    assert abs(tr.snapshot()["lunch"]["elapsed_s"] - 1800) <= 2 and tr.snapshot()["lunch"]["on"]
    c.locked = False
    run(c, tr, 5)
    assert tr.snapshot()["lunch"]["on"]                    # вернулись раньше часа — обед идёт, пока не нажмёте
    w = tr.snapshot()["worked_s"]
    run(c, tr, 60)
    assert tr.snapshot()["worked_s"] == w                  # и время работы всё ещё стоит
    tr.end_lunch()                                         # нажали «Закончить обед»
    run(c, tr, 120)
    s = tr.snapshot()
    assert not s["lunch"]["on"] and s["worked_s"] >= w + 115    # дальше — как обычно
    ev = [e for e in tr.history()["rows"][0]["events"] if e["kind"] == "lunch"]
    assert len(ev) == 1 and 1860 <= ev[0]["dur_s"] <= 1870     # 30 мин у заблокированного экрана + ещё минута после возвращения


def test_lunch_ends_by_itself_when_time_is_up_and_you_are_back(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    notes = Notes(tr)
    tr.tick()
    run(c, tr, 30)
    tr.start_lunch()
    c.locked = True
    run(c, tr, 3700)                                       # час обеда прошёл при блокировке
    assert tr.snapshot()["lunch"]["on"] and notes.items == []      # пока заблокировано — ждём возвращения
    c.locked = False
    run(c, tr, 3)
    s = tr.snapshot()
    assert not s["lunch"]["on"] and notes.items == [("lunch", "Обед закончился — время пошло")]
    w = s["worked_s"]
    run(c, tr, 60)
    assert tr.snapshot()["worked_s"] >= w + 55             # после обеда время пошло само


def test_lunch_at_desk_ends_after_the_hour(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    notes = Notes(tr)
    tr.tick()
    tr.start_lunch()
    run(c, tr, 3598)
    assert tr.snapshot()["lunch"]["on"]
    run(c, tr, 5)
    assert not tr.snapshot()["lunch"]["on"] and len(notes.items) == 1


def test_lunch_not_counted_as_break_and_in_history(tmp_path):
    c = Clock(h=9, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 3600)                                       # 09:00 → 10:00 работа
    tr.start_lunch()
    run(c, tr, 1800)
    tr.end_lunch()
    run(c, tr, 600)
    s = tr.snapshot()
    assert s["break_s"] < 10                               # «перерывы» — без обеда
    r = tr.history()["rows"][0]
    assert any(e["kind"] == "lunch" and abs(e["dur_s"] - 1800) <= 2 for e in r["events"])
    assert abs(s["lunch"]["done_s"] - 1800) <= 2 and abs(s["lunch"]["plan_s"] - 1800) <= 2     # час обеда: 30 мин уже было, 30 ещё впереди


def test_lunch_survives_restart_and_stale_lunch_is_closed(tmp_path):
    f = 'h.json'
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c, f)
    tr.tick()
    tr.start_lunch()
    run(c, tr, 600)
    tr.stop()
    tr2 = lunch_tracker(tmp_path, c, f)                    # перезапустили приложение посреди обеда
    tr2.tick()
    s = tr2.snapshot()
    assert s["lunch"]["on"] and 595 <= s["lunch"]["elapsed_s"] <= 610
    tr2.stop()
    c.wall += 2 * 86400
    c.m += 2 * 86400                                       # открыли через два дня — вчерашний обед не должен висеть
    tr3 = lunch_tracker(tmp_path, c, f)
    assert tr3.snapshot()["lunch"]["on"] is False
    old = tr3.history()["rows"][-1]["events"]
    assert [e["kind"] for e in old] == ["lunch"] and old[0]["unlock"] is not None and old[0]["dur_s"] <= 3600


def test_lunch_double_start_and_end_are_safe(tmp_path):
    c = Clock()
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    tr.end_lunch()                                         # обеда нет — ничего не ломается
    tr.start_lunch()
    tr.start_lunch()
    assert sum(1 for e in tr.history()["rows"][0]["events"] if e["kind"] == "lunch") == 1
    tr.end_lunch()
    tr.end_lunch()
    assert tr.snapshot()["lunch"]["on"] is False


def test_lunch_resets_work_streak(tmp_path):
    c = Clock(h=9, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'), norm=20 * 3600)
    tr.set_lunch(1800)
    tr.set_notify(False, True, 60)
    n = Notes(tr)
    tr.tick()
    run(c, tr, 50 * 60)
    tr.start_lunch()
    run(c, tr, 1800 + 3)                                   # обед 30 мин и конец
    run(c, tr, 50 * 60)                                    # ещё 50 минут работы
    assert [k for k, _ in n.items if k == "break"] == []   # час подряд не набрался: обед — перерыв
    run(c, tr, 11 * 60)
    assert [k for k, _ in n.items if k == "break"] == ["break"]


def test_lunch_excel_column_and_type(tmp_path):
    import openpyxl
    c = Clock(h=9, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 600)
    tr.start_lunch()
    run(c, tr, 1200)
    tr.end_lunch()
    run(c, tr, 5)
    wb = openpyxl.load_workbook(tr.export_xlsx(str(tmp_path / 'o.xlsx')))
    rows = [[x.value for x in r] for r in wb['Учёт времени'].iter_rows()]
    assert rows[1][6] == timedelta(seconds=rows[1][6].total_seconds()) and abs(rows[1][6].total_seconds() - 1200) <= 2
    ev = [[x.value for x in r] for r in wb['Блокировки'].iter_rows()]
    assert ev[1][1] == 'обед'


def test_api_lunch_and_setting(tmp_path):
    c, api = make_api(tmp_path)
    api._t.tick()
    s = api.save_settings({"lunch_min": 45})
    assert s["lunch_min"] == 45 and api._t.lunch_len_s == 45 * 60
    assert shift_app.DEFAULTS["lunch_min"] == 60
    assert api.save_settings({"lunch_min": 5})["lunch_min"] == 60 and api.save_settings({"lunch_min": "x"})["lunch_min"] == 60
    assert api.lunch_toggle()["on"] is True and api.get_day()["lunch"]["on"] is True
    assert api.lunch_toggle()["on"] is False and api.get_day()["lunch"]["on"] is False


# ---------- переименование ShiftTimer → GTime ----------
def test_app_name_and_data_migration(tmp_path):
    assert shift_app.APP_NAME == 'GTime' and shift_app.TITLE == 'GTime'
    old = tmp_path / 'ShiftTimer'
    old.mkdir()
    (old / 'history.json').write_text('{"days": {"2026-11-10": {"arrival": "09:00:00", "leave": "18:00:00", "worked": 28800, "norm": 28800}}}', encoding='utf-8')
    (old / 'settings.json').write_text('{"norm": "07:30", "theme": "dark"}', encoding='utf-8')
    assert sorted(shift_app.migrate_old_data(str(tmp_path))) == ['history.json', 'settings.json']
    new = tmp_path / 'GTime'
    assert shift_app.load_settings(str(new / 'settings.json'))["norm"] == "07:30"
    assert Clock().tracker(str(new / 'history.json')).history()["rows"][0]["worked_s"] == 28800     # журнал на месте
    assert (old / 'history.json').exists()                                                         # старую папку не трогаем
    (new / 'history.json').write_text('{"days": {}}', encoding='utf-8')                            # уже есть своё — не затираем
    assert shift_app.migrate_old_data(str(tmp_path)) == []
    assert Clock().tracker(str(new / 'history.json')).history()["rows"] == []


def test_migration_without_old_folder_is_noop(tmp_path):
    assert shift_app.migrate_old_data(str(tmp_path)) == [] and not (tmp_path / 'GTime').exists()


def test_ui_uses_new_name():
    ui = os.path.join(ROOT, 'shift_timer', 'ui')
    for f in ('main.html', 'mini.html'):
        text = open(os.path.join(ui, f), encoding='utf-8').read()
        assert 'GTime' in text and 'Конец смены' not in text


# ---------- задачи ----------
def make_store(tmp_path, c=None, name='tasks.json'):
    c = c or Clock()
    return c, tasks.TaskStore(str(tmp_path / name), clock=lambda: c.wall)


def test_tasks_add_toggle_edit_delete(tmp_path):
    c, st = make_store(tmp_path)
    assert st.get() == {"tasks": [], "total": 0, "done": 0}
    st.add("  Позвонить клиенту  ")
    v = st.add("Отчёт за неделю")
    assert [t["text"] for t in v["tasks"]] == ["Позвонить клиенту", "Отчёт за неделю"] and v["total"] == 2 and v["done"] == 0
    a, b = v["tasks"][0]["id"], v["tasks"][1]["id"]
    assert a != b
    v = st.toggle(a)
    assert v["done"] == 1 and v["tasks"][-1]["done"] is True            # выполненные уходят вниз списка
    assert st.toggle(a)["done"] == 0                                    # повторное нажатие снимает галочку
    assert st.toggle(a, True)["done"] == 1 and st.toggle(a, True)["done"] == 1
    assert st.edit(b, "Отчёт за месяц")["tasks"][0]["text"] == "Отчёт за месяц"
    assert st.edit(b, "   ")["tasks"][0]["text"] == "Отчёт за месяц"        # пустой текст не принимается
    assert st.delete(a)["total"] == 1 and st.delete(999)["total"] == 1       # несуществующую — молча
    assert st.counts() == {"total": 1, "done": 0}


def test_tasks_validation(tmp_path):
    c, st = make_store(tmp_path)
    assert st.add("")["total"] == 0 and st.add("   ")["total"] == 0 and st.add(None)["total"] == 0
    assert len(st.add("x" * 500)["tasks"][0]["text"]) == tasks.MAX_TEXT
    for i in range(tasks.MAX_PER_DAY + 20):
        st.add(f"задача {i}")
    assert st.get()["total"] == tasks.MAX_PER_DAY
    assert st.toggle("не число")["total"] == tasks.MAX_PER_DAY             # мусор вместо id не ломает


def test_tasks_persist_and_ids_not_reused(tmp_path):
    c, st = make_store(tmp_path)
    st.add("раз")
    last = st.add("два")["tasks"][-1]["id"]
    st.toggle(last)
    st.delete(st.get()["tasks"][0]["id"])
    c2, st2 = make_store(tmp_path, c)
    v = st2.get()
    assert [t["text"] for t in v["tasks"]] == ["два"] and v["tasks"][0]["done"] is True      # после перезапуска всё на месте
    assert max(t["id"] for t in st2.add("три")["tasks"]) > last                                          # номера не повторяются
    assert not os.path.exists(str(tmp_path / 'tasks.json.tmp'))


def test_task_timer_created_started_and_finish_minute(tmp_path):
    c, st = make_store(tmp_path)
    t = st.add("Ответ от коллеги")["tasks"][0]
    assert t["created"] == t["started"] == "2026-11-17T09:00:00" and t["elapsed_s"] == 0 and t["running"]
    c.wall += 3725                                                        # 1 ч 2 мин 5 с
    assert st.get()["tasks"][0]["elapsed_s"] == 3725
    v = st.toggle(t["id"])                                                # «Выполнено» фиксирует час и минуту
    d = v["tasks"][0]
    assert d["finished"] == "2026-11-17T10:02:05" and d["elapsed_s"] == 3725 and not d["running"]
    c.wall += 600
    assert st.get()["tasks"][0]["elapsed_s"] == 3725                      # выполненная — секундомер стоит
    v = st.toggle(t["id"])                                                # вернули в работу — идёт дальше от начала
    assert v["tasks"][0]["finished"] is None and v["tasks"][0]["elapsed_s"] == 3725 + 600


def test_task_runs_for_days_not_carried_copies(tmp_path):
    c, st = make_store(tmp_path)
    st.add("ждём согласование")
    c.wall += 86400 + 10 * 3600 + 30 * 60                                 # через 1 день 10 ч 30 мин
    v = st.get()
    assert v["total"] == 1 and v["tasks"][0]["elapsed_s"] == 86400 + 37800 and v["tasks"][0]["created"].startswith("2026-11-17")
    assert tasks.fmt_dur(v["tasks"][0]["elapsed_s"]) == "1 д 10 ч 30 мин"
    assert len(st.items) == 1                                             # одна запись, а не копия на каждый день


def test_fmt_dur():
    f = tasks.fmt_dur
    assert f(0) == "0:00:00" and f(65) == "0:01:05" and f(3600 * 23 + 59 * 60 + 59) == "23:59:59"
    assert f(86400) == "1 д" and f(86400 + 60) == "1 д 1 мин" and f(86400 + 3600 * 10 + 1800) == "1 д 10 ч 30 мин" and f(3 * 86400 + 7200) == "3 д 2 ч"


def test_done_tasks_hide_after_midnight_but_stay_in_excel_rows(tmp_path):
    c, st = make_store(tmp_path)
    st.add("сделано")
    st.add("в работе")
    st.toggle(st.get()["tasks"][0]["id"])
    assert st.counts() == {"total": 2, "done": 1}
    c.wall += 86400                                                       # наступил следующий день
    v = st.get()
    assert [t["text"] for t in v["tasks"]] == ["в работе"] and v["done"] == 0 and st.counts() == {"total": 1, "done": 0}
    assert {r["text"]: r["done"] for r in st.all_rows()} == {"сделано": True, "в работе": False}


def test_tasks_clear_done_hides_but_keeps_for_excel(tmp_path):
    c, st = make_store(tmp_path)
    st.add("a")
    st.add("b")
    st.toggle(st.get()["tasks"][0]["id"])
    assert [t["text"] for t in st.clear_done()["tasks"]] == ["b"]
    assert len(st.all_rows()) == 2
    (tmp_path / 'bad.json').write_text('{ не json', encoding='utf-8')
    assert make_store(tmp_path, None, 'bad.json')[1].get()["total"] == 0


def test_task_set_times_flexible_and_validated(tmp_path):
    c, st = make_store(tmp_path, Clock(h=15, mi=0))
    tid = st.add("отчёт")["tasks"][0]["id"]
    r = st.set_times(tid, "2026-11-15T10:00", "2026-11-16T09:30")           # создана позавчера, начата вчера
    assert r["ok"] and r["tasks"][0]["created"] == "2026-11-15T10:00:00"
    assert st.get()["tasks"][0]["elapsed_s"] == int((datetime(2026, 11, 17, 15) - datetime(2026, 11, 16, 9, 30)).total_seconds())
    st.toggle(tid)
    r = st.set_times(tid, "2026-11-15T10:00", "2026-11-16T09:30", "2026-11-16T11:45")        # заняла с 09:30 до 11:45
    assert r["ok"] and r["tasks"] == []                                   # выполнена «вчера» — в списке уже не видна
    row = st.all_rows()[0]
    assert row["elapsed_s"] == 2 * 3600 + 15 * 60 and row["finished"] == datetime(2026, 11, 16, 11, 45)
    assert "раньше" in st.set_times(tid, "2026-11-15T10:00", "2026-11-16T09:30", "2026-11-16T09:00")["error"]
    assert "не наступило" in st.set_times(tid, "2026-11-15T10:00", "2026-11-16T09:30", "2026-11-18T09:00")["error"]
    assert "формате" in st.set_times(tid, "2026-11-15T10:00", "плохо", "2026-11-16T11:00")["error"]
    assert "создана" in st.set_times(tid, "", "", "")["error"]
    assert "выполнена" in st.set_times(tid, "2026-11-15T10:00", "2026-11-16T09:30", "")["error"]
    assert "не найдена" in st.set_times(999, "2026-11-15T10:00")["error"]
    assert st.all_rows()[0]["elapsed_s"] == 2 * 3600 + 15 * 60                              # ошибки ничего не испортили


def test_task_comment_subtasks(tmp_path):
    c, st = make_store(tmp_path)
    tid = st.add("запись")["tasks"][0]["id"]
    assert st.set_comment(tid, "ждём Данияра")["tasks"][0]["comment"] == "ждём Данияра"
    st.sub_add(tid, "согласовать текст")
    v = st.sub_add(tid, "  отправить  ")
    subs = v["tasks"][0]["subs"]
    assert [s["text"] for s in subs] == ["согласовать текст", "отправить"] and not st.sub_add(tid, "  ")["tasks"][0]["subs"][2:]
    assert st.sub_toggle(tid, subs[0]["id"])["tasks"][0]["subs"][0]["done"] is True
    assert [s["id"] for s in st.sub_delete(tid, subs[0]["id"])["tasks"][0]["subs"]] == [subs[1]["id"]]
    c2, st2 = make_store(tmp_path, c)
    d = st2.get()["tasks"][0]
    assert d["comment"] == "ждём Данияра" and [s["text"] for s in d["subs"]] == ["отправить"]


def test_task_files_attach_open_remove_delete(tmp_path):
    c, st = make_store(tmp_path)
    tid = st.add("материалы")["tasks"][0]["id"]
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'фото.jpg').write_bytes(b'jpg')
    (src / 'голос.wav').write_bytes(b'wav')
    r = st.attach(tid, [str(src / 'фото.jpg'), str(src / 'голос.wav'), str(src / 'нет.xlsx')])
    assert r["added"] == 2 and len(r["skipped"]) == 1 and r["tasks"][0]["files"] == ['фото.jpg', 'голос.wav']
    assert (src / 'фото.jpg').exists()                                    # оригинал не тронут
    r = st.attach(tid, [str(src / 'фото.jpg')])                           # то же имя — не перезаписываем
    assert r["tasks"][0]["files"][-1] == 'фото (2).jpg' and open(st.file_path(tid, 'фото.jpg'), 'rb').read() == b'jpg'
    assert st.file_path(tid, '../../tasks.json') is None and st.file_path(tid, 'нет') is None
    st.remove_file(tid, 'голос.wav')
    assert not os.path.exists(os.path.join(st.files_dir, str(tid), 'голос.wav')) and 'голос.wav' not in st.get()["tasks"][0]["files"]
    st.delete(tid)
    assert not os.path.exists(os.path.join(st.files_dir, str(tid)))       # удалили задачу — и её файлы


def test_old_tasks_file_is_migrated(tmp_path):
    import json
    old = {"days": {"2026-11-15": [{"id": 1, "text": "не успел", "done": False, "carried": False, "moved": True},
                                   {"id": 2, "text": "сделано", "done": True, "carried": False, "moved": False}],
                    "2026-11-16": [{"id": 1, "text": "не успел", "done": False, "carried": True, "moved": False}]}}
    (tmp_path / 'tasks.json').write_text(json.dumps(old, ensure_ascii=False), encoding='utf-8')
    c, st = make_store(tmp_path)
    v = st.get()
    assert [t["text"] for t in v["tasks"]] == ["не успел"]                # выполненная давно скрыта; невыполненная одна, без дублей
    assert v["tasks"][0]["created"] == "2026-11-15T09:00:00" and v["tasks"][0]["elapsed_s"] == 2 * 86400
    assert len(st.all_rows()) == 2 and max(t["id"] for t in st.add("новая")["tasks"]) == 3
    st2 = make_store(tmp_path, c)[1]
    assert len(st2.items) == 3 and json.load(open(tmp_path / 'tasks.json', encoding='utf-8'))["v"] == 2


def test_api_tasks_and_counts_in_day(tmp_path):
    c, api = make_api(tmp_path)
    api._t.tick()
    assert api.get_day()["tasks"] == {"total": 0, "done": 0}
    api.task_add("Позвонить")
    v = api.task_add("Отчёт")
    ids = [t["id"] for t in v["tasks"]]
    api.task_toggle(ids[0])
    assert api.get_day()["tasks"] == {"total": 2, "done": 1}              # значок «1/2» в мини-окне
    assert api.tasks_get()["done"] == 1
    api.task_edit(ids[1], "Отчёт за неделю")
    assert api.tasks_get()["tasks"][0]["text"] == "Отчёт за неделю"
    assert api.task_comment(ids[1], "коммент")["tasks"][0]["comment"] == "коммент"
    assert api.task_times(ids[1], "2026-11-16T09:00", "2026-11-16T10:00")["ok"]
    assert api.sub_add(ids[1], "шаг")["tasks"][0]["subs"][0]["text"] == "шаг"
    sid = api.tasks_get()["tasks"][0]["subs"][0]["id"]
    assert api.sub_toggle(ids[1], sid)["tasks"][0]["subs"][0]["done"] and api.sub_delete(ids[1], sid)["tasks"][0]["subs"] == []
    f = tmp_path / 'a.xlsx'
    f.write_bytes(b'x')
    api._pick_files = lambda: [str(f)]
    r = api.task_attach(ids[1])
    assert r["added"] == 1 and api.task_file_open(ids[1], 'нет.txt')["error"]
    api._pick_files = lambda: []
    assert api.task_attach(ids[1])["added"] == 0                          # закрыли окно выбора — ничего не меняется
    assert api.task_file_remove(ids[1], 'a.xlsx')["tasks"][0]["files"] == []
    assert api.tasks_clear_done()["total"] == 1
    assert api.task_delete(ids[1])["total"] == 0


def test_mini_resize_clamps_and_keeps_window_on_screen(tmp_path):
    c, api = make_api(tmp_path)
    api._mini = FakeWin()
    api._mini.x, api._mini.y = 1500, 100
    assert api.mini_resize(300) == {"height": 300, "width": 204} and api._mini.calls == [('resize', 204, 300)]
    api._mini.calls.clear()
    assert api.mini_resize(10)["height"] == 100 and api.mini_resize(9999)["height"] == 520      # не меньше обычного и не выше предела
    assert api.mini_resize("мусор") == {"error": "bad height"}
    api._mini.calls.clear()
    api._screen_h = 1080
    api._mini.y = 900                                                     # окно у нижнего края
    api.mini_resize(300)
    assert api._mini.calls[0] == ('move', 1500, 740) and api._mini.calls[1] == ('resize', 204, 300)   # поднялось, чтобы поместиться
    assert shift_app.MINI_WIDE > 204 and shift_app.MINI_WIDE <= 480
    assert shift_app.DEFAULTS["mini_tasks"] is False
    assert api.save_settings({"mini_tasks": True})["mini_tasks"] is True


# ---------- «это был обед»: поправить блокировку задним числом ----------
def _day_with_lock(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 600)
    c.locked = True
    run(c, tr, 1800)                                       # 12:10 → 12:40 заблокировано: на самом деле обедал
    c.locked = False
    run(c, tr, 60)
    return c, tr


def test_mark_lock_as_lunch_moves_it_from_breaks_to_lunch(tmp_path):
    c, tr = _day_with_lock(tmp_path)
    before = tr.snapshot()
    assert before["break_s"] >= 1790 and before["lunch"]["done_s"] == 0
    worked = before["worked_s"]
    ev = tr.history()["rows"][0]["events"]
    assert len(ev) == 1 and ev[0]["i"] == 0 and ev[0]["kind"] == "lock"
    assert tr.set_event_kind('2026-11-17', 0, 'lunch') == {"ok": True}
    after = tr.snapshot()
    assert after["break_s"] < 10 and abs(after["lunch"]["done_s"] - 1800) <= 5      # блок стал обедом: в «Перерывах» его нет
    assert abs(after["lunch"]["plan_s"] - 1800) <= 5                                # и прогноз ухода учитывает, что полчаса обеда уже было
    assert after["worked_s"] == worked                                              # рабочее время не изменилось
    assert tr.history()["rows"][0]["events"][0]["kind"] == "lunch"
    assert tr.set_event_kind('2026-11-17', 0, 'lock') == {"ok": True}               # и обратно
    assert tr.snapshot()["break_s"] >= 1790


def test_mark_event_validation_and_persistence(tmp_path):
    c, tr = _day_with_lock(tmp_path)
    assert "Такого" in tr.set_event_kind('2026-11-17', 5, 'lunch')["error"]
    assert "Такого" in tr.set_event_kind('2026-01-01', 0, 'lunch')["error"]
    assert "Такого" in tr.set_event_kind('2026-11-17', True, 'lunch')["error"]
    assert "Неизвестный" in tr.set_event_kind('2026-11-17', 0, 'rest')["error"]
    c.locked = True
    run(c, tr, 30)                                         # новая блокировка ещё идёт
    n = len(tr.history()["rows"][0]["events"])
    assert "ещё идёт" in tr.set_event_kind('2026-11-17', n - 1, 'lunch')["error"]
    c.locked = False
    run(c, tr, 3)
    tr.set_event_kind('2026-11-17', 0, 'lunch')
    tr.stop()
    tr2 = lunch_tracker(tmp_path, c)
    assert tr2.history()["rows"][0]["events"][0]["kind"] == "lunch"                # выбор сохраняется


def test_marked_lunch_in_excel_and_api(tmp_path):
    import openpyxl
    c, tr = _day_with_lock(tmp_path)
    tr.set_event_kind('2026-11-17', 0, 'lunch')
    wb = openpyxl.load_workbook(tr.export_xlsx(str(tmp_path / 'o.xlsx')))
    assert [x.value for x in wb['Блокировки'][2]][1] == 'обед'
    rows = [[x.value for x in r] for r in wb['Учёт времени'].iter_rows()]
    assert abs(rows[1][6].total_seconds() - 1800) <= 5 and rows[1][5].total_seconds() < 10     # «Обед» ≈ 30 мин, «Перерывы» ≈ 0
    c2, api = make_api(tmp_path)
    api._t = tr
    assert api.event_kind('2026-11-17', 0, 'lock') == {"ok": True} and api.get_history()["rows"][0]["events"][0]["kind"] == "lock"


def test_mini_resize_wide_grows_right_and_stays_on_screen(tmp_path):
    c, api = make_api(tmp_path)
    api._mini = FakeWin()
    api._mini.x, api._mini.y = 100, 100
    r = api.mini_resize(300, True)
    assert r == {"height": 300, "width": shift_app.MINI_WIDE} and api._mini.calls == [('resize', shift_app.MINI_WIDE, 300)]     # с задачами — шире
    api._mini.calls.clear()
    api._screen_w = 1920
    api._mini.x = 1800                                                                                                         # окно у правого края
    api.mini_resize(300, True)
    assert api._mini.calls[0] == ('move', 1920 - 8 - shift_app.MINI_WIDE, 100) and api._mini.calls[1] == ('resize', shift_app.MINI_WIDE, 300)
    api._mini.calls.clear()
    api._mini.x = 1500
    api.mini_resize(100, False)                                                                                                # свернули — снова узкое
    assert api._mini.calls == [('resize', 204, 100)]


@pytest.mark.skipif(not shutil.which('node'), reason='нет node')
def test_js_logic():
    r = subprocess.run(['node', os.path.join(ROOT, 'tests', 'shift_logic.test.js')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout


# ---------- тихий звук ----------
def _samples(data):
    import io
    import struct
    import wave
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, chime.RATE)
        raw = w.readframes(w.getnframes())
    return struct.unpack('<%dh' % (len(raw) // 2), raw)


def test_chime_is_quiet_and_fades_to_silence():
    x = _samples(chime.make_wav())
    assert abs(len(x) / chime.RATE - chime.DURATION) < 0.01
    peak = max(abs(v) for v in x) / 32767
    assert 0.1 < peak <= 0.3                                 # слышно, но тихо (не больше половины максимума)
    assert max(abs(v) for v in x[:20]) < 600                 # начало плавное — без щелчка
    assert max(abs(v) for v in x[-200:]) < 40                # конец — тишина, не обрыв

    def env(a, b):                                           # огибающая на куске
        return max(abs(v) for v in x[int(a * chime.RATE):int(b * chime.RATE)])
    assert env(1.1, 1.4) > env(1.7, 2.0) > env(2.3, 2.6) > env(2.7, 2.9)     # после второй ноты — монотонное затухание
    assert env(0.0, 0.01) < env(0.05, 0.3) / 2               # плавное нарастание


def test_chime_is_low_note_then_high_note():
    """Сначала звучит низкая нота (523 Гц), потом высокая (784 Гц), и они не звучат вместе с самого начала."""
    import cmath
    import math
    x = _samples(chime.make_wav())

    def power(f, a, b):
        i0 = int(a * chime.RATE)
        seg = x[i0:i0 + 2048]
        return abs(sum(v * cmath.exp(-2j * math.pi * f * i / chime.RATE) for i, v in enumerate(seg)))
    low, high = chime.NOTES[0][0], chime.NOTES[1][0]
    assert high > low * 1.4
    assert power(low, 0.15, 0.2) > 4 * power(high, 0.15, 0.2)          # вначале — только низкая
    assert power(high, 1.0, 1.1) > 1.3 * power(low, 1.0, 1.1)          # затем доминирует высокая
    assert power(high, 0.9, 1.0) > 5 * power(659.25, 0.9, 1.0)         # и это именно две ноты, не «что-то между»


def test_chime_silent_off_windows():
    if sys.platform != 'win32':
        assert chime.play_async() is False


def test_sound_setting_controls_playing(tmp_path, monkeypatch):
    c, api = make_api(tmp_path)
    played = []
    monkeypatch.setattr(chime, 'play_async', lambda level='mid': played.append(level) or True)
    api._notice({"id": 1, "kind": "hour", "text": "x"})
    assert played == ["mid"] and shift_app.DEFAULTS["sound"] is True and shift_app.DEFAULTS["volume"] == "mid"
    api.save_settings({"sound": False})
    played.clear()
    api._notice({"id": 2, "kind": "hour", "text": "x"})
    assert played == []                                      # звук выключен — тишина


def test_volume_levels(tmp_path, monkeypatch):
    def peak(level):
        return max(abs(v) for v in _samples(chime.make_wav(level=level))) / 32767
    lo, mid, hi = peak("low"), peak("mid"), peak("high")
    assert lo < mid < hi and abs(hi / mid - 2) < 0.05 and abs(mid / lo - 2) < 0.05
    assert hi < 0.6                                          # даже «высокая» без искажений и не оглушает
    assert peak("bogus") == mid                              # неизвестная ступень — средняя
    c, api = make_api(tmp_path)
    played = []
    monkeypatch.setattr(chime, 'play_async', lambda level='mid': played.append(level) or True)
    api.save_settings({"volume": "high"})
    assert played == ["high"]                                # при смене громкости играет образец
    api._notice({"id": 3, "kind": "break", "text": "x"})
    assert played == ["high", "high"]                        # и уведомления — выбранной громкости
    played.clear()
    api.save_settings({"sound": False, "volume": "low"})
    assert played == []                                      # звук выключен — образца нет
    assert api.save_settings({"volume": "очень"})["volume"] == "mid"    # мусор → по умолчанию


def test_lunch_with_lock_has_no_duplicate_block(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    tr.tick()
    run(c, tr, 60)
    tr.start_lunch()
    c.locked = True
    run(c, tr, 1800)
    c.locked = False
    run(c, tr, 5)
    tr.end_lunch()
    run(c, tr, 60)
    kinds = [e["kind"] for e in tr.history()["rows"][0]["events"]]
    assert kinds == ["lunch"]                              # блокировка внутри обеда отдельной строкой не пишется
    assert tr.snapshot()["events_n"] == 0                  # и в «Блокировки и паузы» обед не входит
    c.locked = True                                        # блокировка после обеда — обычная
    run(c, tr, 30)
    assert [e["kind"] for e in tr.history()["rows"][0]["events"]] == ["lunch", "lock"]


def test_old_journal_duplicate_inside_lunch_is_cleaned(tmp_path):
    c = Clock(h=12, mi=0)
    tr = lunch_tracker(tmp_path, c)
    d = {"events": [
        {"lock": "2026-11-10T12:10:00", "unlock": "2026-11-10T12:50:00", "kind": "lunch"},
        {"lock": "2026-11-10T12:10:02", "unlock": "2026-11-10T12:49:58", "kind": "lock"},
        {"lock": "2026-11-10T13:30:00", "unlock": "2026-11-10T13:31:00", "kind": "lock"}]}
    type(tr)._strip_inside_lunch(d)
    assert [(e["kind"], e["lock"][-8:]) for e in d["events"]] == [("lunch", "12:10:00"), ("lock", "13:30:00")]


def test_excel_tasks_sheet(tmp_path):
    import openpyxl
    c = Clock(h=9, mi=0)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.edit_day('2026-11-10', '09:05', '18:20', '08:00')
    ts = tasks.TaskStore(str(tmp_path / 't.json'), clock=lambda: c.wall)
    a = ts.add("Сверить таблицу")["tasks"][0]["id"]
    ts.add("Ждём ответ")
    ts.sub_add(a, "шаг 1")
    ts.set_comment(a, "детали")
    c.wall += 90 * 60 + 20
    ts.toggle(a)
    c.wall += 86400 + 3600 * 3 + 600
    p = tr.export_xlsx(str(tmp_path / 'o.xlsx'), ts.all_rows())
    wb = openpyxl.load_workbook(p)
    vals = [[x.value for x in r] for r in wb['Задачи'].iter_rows()]
    assert vals[0] == ['Создана', 'Начата', 'Выполнена', 'Статус', 'Задача', 'Ушло, ч:мм', 'Ушло', 'Подзадачи', 'Комментарий', 'Файлы', 'Теги', 'Ждали ответа', 'Сейчас ждём']
    done, work = vals[1], vals[2]
    assert done[0] == datetime(2026, 11, 17, 9, 0) and done[2] == datetime(2026, 11, 17, 10, 30, 20) and done[3] == 'выполнена'   # час и минута выполнения
    assert done[5] == timedelta(minutes=90, seconds=20) and done[6] == '1:30:20' and done[7] == '○ шаг 1' and done[8] == 'детали'
    assert work[3] == 'в работе' and work[2] is None and work[6] == '1 д 4 ч 40 мин'                                                # ждём уже больше суток


def test_main_window_size_fits_screen():
    f = shift_app.main_size
    assert f() == shift_app.MAIN_SIZE and f(1920, 1080) == shift_app.MAIN_SIZE
    w, h = f(1366, 768)                                                    # ноутбук: не выше экрана с запасом под панель задач
    assert h <= 768 - 90 and w <= 1366 - 60 and (w, h) >= shift_app.MAIN_MIN
    assert f(300, 300) == shift_app.MAIN_MIN                               # совсем маленький экран — не меньше минимума


def test_paste_files_and_images_into_task(tmp_path, monkeypatch):
    import base64
    c, api = make_api(tmp_path)
    tid = api.task_add("материалы")["tasks"][0]["id"]
    png = b'\x89PNG\r\n\x1a\nfake'
    r = api.task_attach_data(tid, "Снимок 2026-11-17 14-05-12.png", base64.b64encode(png).decode())      # скриншот из буфера
    assert r["added"] == 1 and r["tasks"][0]["files"] == ["Снимок 2026-11-17 14-05-12.png"]
    assert open(api._tasks.file_path(tid, "Снимок 2026-11-17 14-05-12.png"), 'rb').read() == png
    r = api.task_attach_data(tid, "Снимок 2026-11-17 14-05-12.png", base64.b64encode(b'second').decode())   # то же имя — не перезаписывается
    assert r["tasks"][0]["files"][-1] == "Снимок 2026-11-17 14-05-12 (2).png" and open(api._tasks.file_path(tid, "Снимок 2026-11-17 14-05-12.png"), 'rb').read() == png
    assert api.task_attach_data(tid, "x.png", "")["added"] == 0              # пустое не добавляется
    assert api.task_attach_data(tid, "../../evil.txt", base64.b64encode(b'x').decode())["tasks"][0]["files"][-1] == "evil.txt"   # путь из имени отбрасывается
    f = tmp_path / 'отчёт.xlsx'
    f.write_bytes(b'xl')
    monkeypatch.setattr(shift_app, 'clipboard_files', lambda: [str(f), str(tmp_path)])                      # файл и папка из Проводника
    r = api.task_paste(tid)
    assert r["added"] == 1 and "отчёт.xlsx" in r["tasks"][0]["files"] and len(r["skipped"]) == 1 and f.exists()
    monkeypatch.setattr(shift_app, 'clipboard_files', lambda: [])
    assert api.task_paste(tid)["added"] == 0                                 # в буфере нет файлов — тогда пробуем картинку из браузера
    assert shift_app.clipboard_files() == [] or sys.platform == 'win32'      # не Windows — безопасно пусто
