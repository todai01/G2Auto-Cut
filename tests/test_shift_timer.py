"""Мини-приложение «Конец смены» (shift_timer/): учёт активного времени, журнал, Excel, настройки (JS — через node)."""
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
    assert rows[0][:5] == ['Дата', 'День', 'Приход', 'Уход', 'Отработано']
    assert rows[1][0].date().isoformat() == '2026-11-10' and rows[1][1] == 'вт'
    assert rows[1][4] == timedelta(hours=8) and rows[1][7] == 0      # [h]:mm читается как timedelta
    assert rows[2][7] == -60                               # 7 ч при норме 8 ч → −60 мин
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
    return c, shift_app.Api(str(tmp_path / 's.json'), table=str(tmp_path / 'T' / 'Учёт.xlsx'), tracker=tr)


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
