"""GTime: сводки (график 5/2), отметки дней, календарь, теги и «жду ответа», отчёт одним файлом, резервная копия."""
import base64
import json
import os
import sys
import zipfile
from datetime import date, datetime, timedelta

import pytest

from test_shift_timer import Clock, make_api, make_store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import app as shift_app        # noqa: E402
import backup                  # noqa: E402
import report                  # noqa: E402
import tasks                   # noqa: E402

H = 3600


def friday_tracker(tmp_path):
    c = Clock(d=13, h=9)                                              # 2026-11-13 — пятница
    assert date(2026, 11, 13).weekday() == 4
    tr = c.tracker(str(tmp_path / 'h.json'))
    return c, tr


def test_week_summary_follows_5_2_with_vacation(tmp_path):
    c, tr = friday_tracker(tmp_path)
    for iso, w in (('2026-11-09', '08:00'), ('2026-11-10', '07:00'), ('2026-11-12', '08:30')):
        assert tr.edit_day(iso, '09:00', '18:30', w)["ok"]
    assert tr.set_mark('2026-11-11', None, 'vacation')["ok"]
    s = tr.summary(date(2026, 11, 9), date(2026, 11, 15))
    assert s["workdays"] == 4 and s["workdays_done"] == 4 and s["vacation"] == 1       # среда — отпуск, в норму не входит
    assert s["worked_s"] == 23.5 * H and s["norm_s"] == 24 * H and s["delta_s"] == -0.5 * H   # сегодняшний день (пт) недоработки пока не даёт
    assert s["plan_s"] == 32 * H                                                      # на всю неделю: 4 рабочих дня × 8 ч
    assert s["avg_arrival"] == '09:00:00' and s["days_worked"] == 3
    by = {d["date"]: d for d in s["by_day"]}
    assert by['2026-11-11']["norm_s"] == 0 and by['2026-11-11']["mark"] == 'vacation' and by['2026-11-14']["weekend"] and by['2026-11-14']["norm_s"] == 0


def test_weekend_work_is_overtime_and_future_days_not_counted(tmp_path):
    c = Clock(d=16, h=9)                                             # понедельник
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.edit_day('2026-11-14', '10:00', '14:00', '03:00')               # суббота
    s = tr.summary(date(2026, 11, 9), date(2026, 11, 15))
    assert s["worked_s"] == 3 * H and s["delta_s"] == 3 * H - 5 * 8 * H
    nxt = tr.summary(date(2026, 11, 16), date(2026, 11, 22))           # неделя только началась
    assert nxt["norm_s"] == 0 and nxt["delta_s"] == 0 and nxt["plan_s"] == 40 * H and nxt["workdays_done"] == 1


def test_today_over_norm_counts_as_overtime(tmp_path):
    c, tr = friday_tracker(tmp_path)
    tr.days['2026-11-13'] = {"arrival": '09:00:00', "leave": '19:00:00', "worked": 9 * H, "norm": 8 * H, "events": [], "notified": [], "no_break": False}
    s = tr.summary(date(2026, 11, 13), date(2026, 11, 13))
    assert s["norm_s"] == 8 * H and s["delta_s"] == H


def test_marks_ranges_clear_persist_and_reload(tmp_path):
    c, tr = friday_tracker(tmp_path)
    assert tr.set_mark('2026-12-01', '2026-12-14', 'vacation') == {"ok": True, "n": 14}
    assert tr.set_mark('2026-12-05', None, 'sick')["ok"] and tr.marks['2026-12-05'] == 'sick'
    assert tr.set_mark('2026-12-02', '2026-12-03', '')["ok"] and '2026-12-02' not in tr.marks
    assert "Неверная" in tr.set_mark('плохо', None, 'sick')["error"] and "раньше" in tr.set_mark('2026-12-05', '2026-12-01', 'sick')["error"]
    assert "Неизвестная" in tr.set_mark('2026-12-05', None, 'отгул')["error"] and "года" in tr.set_mark('2026-01-01', '2028-01-01', 'dayoff')["error"]
    tr2 = c.tracker(str(tmp_path / 'h.json'))                          # переживает перезапуск
    assert tr2.marks == tr.marks and tr2.day_norm('2026-12-01') == 0 and tr2.day_norm('2026-12-15') == 8 * H and tr2.day_norm('2026-12-19') == 0
    tr.marks['2099-01-01'] = 'sick'
    tr.save()
    tr.marks.clear()
    tr.reload()
    assert '2099-01-01' in tr.marks                                     # reload читает с диска


def test_calendar_and_day_info(tmp_path):
    c, tr = friday_tracker(tmp_path)
    tr.edit_day('2026-11-10', '09:00', '18:00', '08:00')
    tr.set_mark('2026-11-11', None, 'sick')
    cal = tr.calendar(2026, 11)
    assert len(cal["days"]) == 30 and cal["days"][0]["wd"] == 6         # 1 ноября 2026 — воскресенье
    d = {x["date"]: x for x in cal["days"]}
    assert d['2026-11-10']["record"] and d['2026-11-10']["worked_s"] == 8 * H and d['2026-11-11']["mark"] == 'sick' and d['2026-11-13']["today"]
    assert d['2026-11-20']["future"] and cal["summary"]["sick"] == 1 and "error" in tr.calendar(2026, 13)
    i = tr.day_info('2026-11-10')
    assert i["record"] and i["weekday"] == 'вт' and i["delta_s"] == 0 and i["arrival"] == '09:00:00'
    j = tr.day_info('2026-11-11')
    assert j["mark"] == 'sick' and not j["record"] and j["norm_s"] == 0
    assert tr.day_info('2026-11-14')["weekend"] and "error" in tr.day_info('x')


def test_task_tags_and_waiting(tmp_path):
    c, st = make_store(tmp_path)
    tid = st.add("Озвучка")["tasks"][0]["id"]
    v = st.set_tags(tid, ['Синтез', 'Запись', 'Левый', 'Срезка'])
    assert v["tasks"][0]["tags"] == ['Срезка', 'Запись', 'Синтез']       # только свои теги, в порядке списка
    assert tasks.TAGS == ['Срезка', 'Запись', 'Доработка', 'Ожидание', 'Прослушка и разметка', 'Синтез']
    c.wall += 600
    v = st.wait_start(tid, '  Данияр  ')
    t = v["tasks"][0]
    assert t["waiting"]["who"] == 'Данияр' and t["wait_s"] == 0
    c.wall += 86400 + 3600
    t = st.get()["tasks"][0]
    assert t["waiting"]["elapsed_s"] == 86400 + 3600 and t["wait_s"] == 86400 + 3600
    st.wait_start(tid, 'Айгерим')                                       # уже ждём — меняется только имя, время идёт с прежнего момента
    assert st.get()["tasks"][0]["waiting"]["who"] == 'Айгерим' and st.get()["tasks"][0]["waiting"]["elapsed_s"] == 86400 + 3600
    c.wall += 60
    t = st.wait_end(tid)["tasks"][0]
    assert t["waiting"] is None and t["wait_s"] == 86400 + 3660
    c.wall += 5000
    assert st.get()["tasks"][0]["wait_s"] == 86400 + 3660               # ответ получен — ожидание не растёт
    st.wait_start(tid, 'Данияр')
    c.wall += 120
    t = st.toggle(tid)["tasks"][0]                                      # выполнили, пока ждали — ожидание закрылось
    assert t["waiting"] is None and t["wait_s"] == 86400 + 3660 + 120
    assert st.wait_start(tid, 'x')["tasks"][0]["waiting"] is None        # у выполненной ждать нечего
    st2 = make_store(tmp_path, c)[1]
    t2 = st2.get()["tasks"][0]
    assert t2["tags"] == ['Срезка', 'Запись', 'Синтез'] and t2["wait_s"] == 86400 + 3660 + 120 and len(t2["waits"]) == 2


def test_tasks_on_day_counts_and_period_rows(tmp_path):
    c, st = make_store(tmp_path, Clock(d=10, h=10))
    a = st.add("долгая")["tasks"][0]["id"]
    st.start(a)
    b = [t["id"] for t in st.add("быстрая")["tasks"] if t["text"] == "быстрая"][0]
    st.start(b)
    c.wall += 3600
    st.toggle(b)                                                         # «быстрая» выполнена в 11:00
    c.wall += 86400 * 2                                                  # 12 ноября
    st.toggle(a)                                                         # «долгая» выполнена 12-го
    d10 = {t["text"]: t for t in st.tasks_on_day('2026-11-10')}
    assert d10["долгая"]["role"] == ["создана"] and d10["быстрая"]["role"] == ["создана", "выполнена"] and d10["быстрая"]["day_s"] == 3600
    d11 = st.tasks_on_day('2026-11-11')
    assert [t["role"] for t in d11] == [["в работе"]] and d11[0]["day_s"] == 86400                  # шла весь день
    assert [t["role"] for t in st.tasks_on_day('2026-11-12') if t["text"] == "долгая"] == [["выполнена"]]
    assert st.tasks_on_day('плохо') == [] and st.tasks_on_day('2026-11-20') == []
    cnt = st.counts_by_day('2026-11')
    assert cnt['2026-11-10'] == {"created": 2, "done": 1} and cnt['2026-11-12'] == {"created": 0, "done": 1}
    rows = st.rows_between(date(2026, 11, 11), date(2026, 11, 11))
    assert [r["text"] for r in rows] == ["долгая"] and rows[0]["period_s"] == 86400
    assert len(st.rows_between(date(2026, 11, 1), date(2026, 11, 30))) == 2 and st.rows_between(date(2026, 10, 1), date(2026, 10, 31)) == []


def test_report_week_one_file(tmp_path):
    import openpyxl
    c = Clock(d=13, h=9)
    tr = c.tracker(str(tmp_path / 'h.json'))
    tr.edit_day('2026-11-09', '09:00', '18:30', '08:00')
    tr.edit_day('2026-11-10', '09:30', '18:00', '07:00')
    tr.set_mark('2026-11-12', None, 'sick')
    _, st = make_store(tmp_path, Clock(d=9, h=9))
    a = st.add("Срезка фраз по таблице")["tasks"][0]["id"]
    st.set_tags(a, ['Срезка', 'Прослушка и разметка'])
    st._clock = lambda: Clock(d=10, h=12).wall
    st.toggle(a)
    b = st.add("Ждём озвучку")["tasks"][0]["id"]
    st.set_tags(b, ['Ожидание'])
    st.wait_start(b, 'Данияр')
    st.add("без тега")
    st._clock = lambda: Clock(d=13, h=9).wall
    a0, b0 = report.period('week', '2026-11-12')
    assert (a0.isoformat(), b0.isoformat()) == ('2026-11-09', '2026-11-15') and report.period('month', '2026-02-10')[1] == date(2026, 2, 28)
    p = report.export_report(str(tmp_path / 'r' / 'o.xlsx'), 'week', tr.summary(a0, b0), st.rows_between(a0, b0))
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ['Сводка', 'Задачи', 'По тегам']
    ws = wb['Сводка']
    assert ws['A1'].value == 'Отчёт за неделю' and '09.11.2026 — 15.11.2026' in ws['A2'].value and 'график 5/2' in ws['A2'].value
    kv = {ws.cell(r, 1).value: ws.cell(r, 2).value for r in range(4, 16)}
    assert kv['Отработано'] == timedelta(hours=15) and kv['Рабочих дней по графику'] == 4 and kv['Больничный, дней'] == 1 and kv['Задач создано'] == 3 and kv['Задач выполнено'] == 1
    days = [[x.value for x in r] for r in ws.iter_rows(min_row=18, max_row=25)]
    assert [d[1] for d in days[:7]] == ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'] and days[3][7] == 'больничный' and days[5][7] == 'выходной день'
    assert days[7][4] == '=SUM(E18:E24)'
    tk = [[x.value for x in r] for r in wb['Задачи'].iter_rows()]
    assert tk[0][:5] == ['Создана', 'Выполнена', 'Статус', 'Задача', 'Теги'] and tk[1][4] == 'Срезка, Прослушка и разметка' and tk[1][2] == 'выполнена'
    assert tk[2][2] == 'ждём ответа' and tk[2][8] == 'Данияр' and not tk[3][4]
    tg = {r[0].value: [x.value for x in r] for r in wb['По тегам'].iter_rows(min_row=2)}
    assert tg['Срезка'][1] == 1 and tg['Срезка'][2] == 1 and tg['Ожидание'][1] == 1 and tg['Без тега'][1] == 1 and 'Синтез' not in tg


def test_backup_roundtrip_and_safety(tmp_path):
    src = tmp_path / 'data'
    (src / 'task_files' / '1').mkdir(parents=True)
    (src / 'history.json').write_text('{"days": {}}', encoding='utf-8')
    (src / 'tasks.json').write_text('{"tasks": []}', encoding='utf-8')
    (src / 'settings.json').write_text('{"norm": "07:00"}', encoding='utf-8')
    (src / 'task_files' / '1' / 'скрин.png').write_bytes(b'png')
    paths = {"history.json": str(src / 'history.json'), "tasks.json": str(src / 'tasks.json'), "settings.json": str(src / 'settings.json'), "task_files": str(src / 'task_files')}
    r = backup.make_backup(paths, str(tmp_path / 'out' / 'копия.zip'))
    assert r["files"] == 1 and os.path.exists(r["path"]) and not os.path.exists(r["path"] + '.tmp')
    with zipfile.ZipFile(r["path"]) as z:
        assert set(z.namelist()) == {'history.json', 'tasks.json', 'settings.json', 'task_files/1/скрин.png', 'manifest.json'}
    (src / 'settings.json').write_text('{"norm": "09:00"}', encoding='utf-8')      # после копии данные изменились
    (src / 'task_files' / '1' / 'скрин.png').write_bytes(b'new')
    (src / 'task_files' / '2').mkdir()
    (src / 'task_files' / '2' / 'лишний.txt').write_text('x', encoding='utf-8')
    res = backup.restore_backup(r["path"], paths, str(src / 'backups'))
    assert json.load(open(src / 'settings.json', encoding='utf-8'))["norm"] == "07:00"
    assert (src / 'task_files' / '1' / 'скрин.png').read_bytes() == b'png' and not (src / 'task_files' / '2').exists()
    assert os.path.exists(res["safety"]) and 'до_восстановления' in res["safety"]
    with zipfile.ZipFile(res["safety"]) as z:                                       # прежние данные сохранены
        assert json.loads(z.read('settings.json'))["norm"] == "09:00" and z.read('task_files/1/скрин.png') == b'new'


def test_restore_rejects_bad_archives_and_changes_nothing(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    (d / 'history.json').write_text('{"days": {}}', encoding='utf-8')
    paths = {"history.json": str(d / 'history.json'), "tasks.json": str(d / 'tasks.json'), "settings.json": str(d / 's.json'), "task_files": str(d / 'tf')}
    (tmp_path / 'not.zip').write_text('просто текст', encoding='utf-8')
    with pytest.raises(RuntimeError, match='не архив'):
        backup.restore_backup(str(tmp_path / 'not.zip'), paths, str(d / 'b'))
    with zipfile.ZipFile(tmp_path / 'foreign.zip', 'w') as z:
        z.writestr('history.json', '{}')
    with pytest.raises(RuntimeError, match='метки'):
        backup.restore_backup(str(tmp_path / 'foreign.zip'), paths, str(d / 'b'))
    with zipfile.ZipFile(tmp_path / 'evil.zip', 'w') as z:
        z.writestr('manifest.json', json.dumps({"app": "GTime"}))
        z.writestr('history.json', '{}')
        z.writestr('../../evil.txt', 'x')
    with pytest.raises(RuntimeError, match='небезопасные'):
        backup.restore_backup(str(tmp_path / 'evil.zip'), paths, str(d / 'b'))
    with zipfile.ZipFile(tmp_path / 'badjson.zip', 'w') as z:
        z.writestr('manifest.json', json.dumps({"app": "GTime"}))
        z.writestr('history.json', '{ не json')
    with pytest.raises(RuntimeError, match='Прежние данные возвращены'):
        backup.restore_backup(str(tmp_path / 'badjson.zip'), paths, str(d / 'b'))
    assert (d / 'history.json').read_text(encoding='utf-8') == '{"days": {}}' and not (tmp_path / 'evil.txt').exists()


def test_api_summary_calendar_marks_day_and_report(tmp_path):
    c, api = make_api(tmp_path)
    api._reports = str(tmp_path / 'reports')
    api._t.edit_day('2026-11-16', '09:00', '18:00', '08:00')
    assert api.set_mark('2026-11-17', '2026-11-18', 'dayoff')["n"] == 2
    tid = api.task_add("Задача дня")["tasks"][0]["id"]
    api.task_tags(tid, ['Синтез'])
    api.task_wait(tid, 'Айгерим')
    s = api.get_summary('week')
    assert s["kind"] == 'week' and s["start"] == '2026-11-16' and s["dayoff"] == 2 and s["tasks"]["created"] == 1 and s["tasks"]["by_tag"]["Синтез"]["n"] == 1
    assert api.get_summary('month')["start"] == '2026-11-01' and api.get_summary('что-то')["kind"] == 'week'
    cal = api.get_calendar(2026, 11)
    d = {x["date"]: x for x in cal["days"]}
    assert d['2026-11-17']["mark"] == 'dayoff' and d['2026-11-17']["tasks_created"] == 1 and d['2026-11-16']["tasks_created"] == 0
    info = api.get_day_info('2026-11-17')
    assert info["mark"] == 'dayoff' and [t["text"] for t in info["tasks"]] == ["Задача дня"] and info["tasks"][0]["waiting_who"] == 'Айгерим'
    r = api.report_save('week')
    assert os.path.exists(r["path"]) and r["path"].endswith('Отчёт_неделя_2026-11-16.xlsx')
    assert api.report_save('month')["path"].endswith('Отчёт_месяц_2026-11-01.xlsx')


def test_api_backup_save_and_restore_reloads_everything(tmp_path):
    c, api = make_api(tmp_path)
    api._t.edit_day('2026-11-10', '09:00', '18:00', '08:00')
    tid = api.task_add("до копии")["tasks"][0]["id"]
    api._pick_files = lambda: []
    api.task_attach_data(tid, 'а.png', base64.b64encode(b'img').decode())
    zp = str(tmp_path / 'бэкап')
    api._pick_save_zip = lambda name: zp                              # без .zip — добавится
    assert api.backup_save()["ok"] and os.path.exists(zp + '.zip')
    api._pick_save_zip = lambda name: None
    assert api.backup_save() == {"cancelled": True}
    api._t.delete_day('2026-11-10')                                    # после копии много что поменялось
    api.task_delete(tid)
    api.task_add("после копии")
    api._pick_open_zip = lambda: None
    assert api.backup_restore() == {"cancelled": True}
    api._pick_open_zip = lambda: zp + '.zip'
    r = api.backup_restore()
    assert r["ok"] and os.path.exists(r["safety"])
    assert [t["text"] for t in api.tasks_get()["tasks"]] == ["до копии"] and api.tasks_get()["tasks"][0]["files"] == ['а.png']
    assert '2026-11-10' in api._t.days and api._t.days['2026-11-10']["worked"] == 8 * 3600       # журнал вернулся без перезапуска
    (tmp_path / 'bad.zip').write_text('x', encoding='utf-8')
    api._pick_open_zip = lambda: str(tmp_path / 'bad.zip')
    assert "не архив" in api.backup_restore()["error"] and [t["text"] for t in api.tasks_get()["tasks"]] == ["до копии"]


def test_drop_paths_and_open_folder(tmp_path, monkeypatch):
    c, api = make_api(tmp_path)
    tid = api.task_add("материалы")["tasks"][0]["id"]
    f = tmp_path / 'голос.wav'
    f.write_bytes(b'wav')
    r = api.task_attach_paths(tid, [str(f), str(tmp_path / 'нет.txt')])
    assert r["added"] == 1 and len(r["skipped"]) == 1 and f.exists() and r["tasks"][0]["files"] == ['голос.wav']
    assert api.task_attach_paths(tid, "не список")["added"] == 0
    opened = []
    monkeypatch.setattr(os, 'startfile', lambda p: opened.append(p), raising=False)
    res = api.task_open_folder(tid)
    assert res["ok"] and opened == [os.path.join(api._tasks.files_dir, str(tid))] and os.path.isdir(opened[0])
    assert "не найдена" in api.task_open_folder(999)["error"]


def test_click_on_mini_toggles_main_window(tmp_path):
    from test_shift_timer import FakeWin

    class Win(FakeWin):
        def restore(self):
            self.calls.append(('restore',))

        def minimize(self):
            self.calls.append(('minimize',))

    c, api = make_api(tmp_path)
    api._main = Win()
    api._tray = object()                                              # есть значок в трее — прячем, а не сворачиваем
    api._main_shown = False                                           # программу запустили в фоне
    assert api.toggle_main() == {"shown": True} and ('show',) in api._main.calls and ('restore',) in api._main.calls   # первый клик — открыть
    api._main.calls.clear()
    assert api.toggle_main() == {"shown": False} and api._main.calls == [('hide',)]                               # второй — скрыть, мини остаётся
    api._tray = None
    api.open_main()
    api._main.calls.clear()
    assert api.toggle_main() == {"shown": False} and api._main.calls == [('minimize',)]                          # без трея — свернуть
    assert api.main_visible(True) == {"shown": True} and api.toggle_main() == {"shown": False}                   # окно само сообщило, что видно
    api.minimize()
    assert api._main_shown is False


def test_mini_js_has_click_to_toggle():
    src = open(os.path.join(ROOT, 'shift_timer', 'ui', 'mini.js'), encoding='utf-8').read()
    assert "toggle_main" in src and "SKIP" in src and "moved" in src       # клик по окну, кроме кнопок; перетаскивание — не клик
    assert 'main_visible' in open(os.path.join(ROOT, 'shift_timer', 'ui', 'main.js'), encoding='utf-8').read()


def test_mini_window_has_no_taskbar_button_hook(tmp_path, monkeypatch):
    import time as _t
    from test_shift_timer import FakeWin
    c, api = make_api_for_taskbar(tmp_path)
    calls = []
    monkeypatch.setattr(shift_app, 'hide_taskbar_button', lambda title: calls.append(title) or True)
    api._mini = FakeWin()
    api._s["mini_visible"] = True
    api._apply_mini()                                                          # показали мини-окно — значок в панели задач убирается
    _t.sleep(0.8)
    assert calls == [shift_app.MINI_TITLE] and shift_app.MINI_TITLE == 'GTime — мини' and shift_app.TITLE == 'GTime'
    api._s["mini_visible"] = False
    api._notice({"id": 1, "kind": "hour", "text": "x"})                        # и когда окно показывается ради уведомления
    _t.sleep(0.5)
    assert calls.count(shift_app.MINI_TITLE) == 2
    if sys.platform != 'win32':
        monkeypatch.undo()
        assert shift_app.hide_taskbar_button('любой') is False                 # не Windows — безопасно ничего не делает


def make_api_for_taskbar(tmp_path):
    from test_shift_timer import make_api
    return make_api(tmp_path)
