"""GTime: командный режим — учётки и данные в общей папке, вход, обзор команды для администратора."""
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

from test_shift_timer import Clock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import app as shift_app        # noqa: E402
import report                  # noqa: E402
import tasks                   # noqa: E402
import team                    # noqa: E402


def make_user_api(tmp_path, name, team_dir, clock=None):
    """Отдельный GTime одного сотрудника (свои журнал и задачи), общая — только папка команды."""
    c = clock or Clock(d=17, h=9)
    base = tmp_path / name
    base.mkdir(exist_ok=True)
    tr = c.tracker(str(base / 'h.json'))
    api = shift_app.Api(str(base / 's.json'), table=str(base / 'T.xlsx'), tracker=tr, store=tasks.TaskStore(str(base / 'tasks.json'), clock=lambda: c.wall))
    api._reports = str(base / 'reports')
    api._team_sync = lambda force=False: api._team_sync_now() if api._user else None          # в тестах — сразу и в этом же потоке
    api.save_settings({"team_dir": str(team_dir)})
    return c, api


def test_password_hashing_and_login_rules():
    h = team.hash_password('Секрет123')
    assert h["hash"] != 'Секрет123' and len(h["salt"]) == 32 and h["iter"] >= 100000
    acc = {"login": 'a', **h}
    assert team.check_password(acc, 'Секрет123') and not team.check_password(acc, 'секрет123') and not team.check_password({"login": 'a'}, 'x')
    assert team.hash_password('Секрет123')["hash"] != h["hash"]                 # соль у каждой учётки своя
    assert team.norm_login('  Gizat ') == 'gizat' and team.norm_login('Айгерим_1') == 'айгерим_1'
    for bad in ('', 'a', 'a b', '../x', 'x' * 40, 'a/b'):
        with pytest.raises(team.TeamError):
            team.norm_login(bad)


def test_accounts_verify_lockout_and_last_admin(tmp_path):
    now = [datetime(2026, 11, 17, 9, 0)]
    st = team.TeamStore(str(tmp_path), clock=lambda: now[0])
    with pytest.raises(team.TeamError, match='Сетевая папка недоступна'):
        team.TeamStore(str(tmp_path / 'нет такой')).list()
    assert st.list() == [] and not st.has_admin()
    st.create('Admin', 'Админ', 'adminpass', role='admin', must_change=False)
    st.create('Gizat', 'Гизат', 'Gizat')                                          # стартовый пароль = логин (допустим для первого входа)
    with pytest.raises(team.TeamError, match='уже есть'):
        st.create('gizat', 'x', 'yyyyyy')
    with pytest.raises(team.TeamError):
        st.create('new', 'x', 'ab')                                               # короче 3 знаков
    a = st.verify('GIZAT', 'Gizat')
    assert a["login"] == 'gizat' and a["must_change"] is True and a["role"] == 'user' and 'hash' not in a
    acc_file = json.load(open(tmp_path / 'GTime_team' / 'accounts' / 'gizat.json', encoding='utf-8'))
    assert 'Gizat' not in json.dumps(acc_file).replace('Гизат', '')                 # пароля в файле нет
    for i in range(team.MAX_FAILS):
        with pytest.raises(team.TeamError, match='Неверный'):
            st.verify('gizat', 'не тот')
    with pytest.raises(team.TeamError, match='Подождите'):
        st.verify('gizat', 'Gizat')                                              # пауза после серии ошибок — даже с верным паролем
    now[0] += timedelta(seconds=team.LOCK_S + 1)
    assert st.verify('gizat', 'Gizat')["login"] == 'gizat'
    with pytest.raises(team.TeamError, match='Неверный'):
        st.verify('нет_такого', 'x')
    st.change_password('gizat', 'Gizat', 'НовыйПароль1')
    assert st.verify('gizat', 'НовыйПароль1')["must_change"] is False
    for bad in ('short', 'GIZAT', 'НовыйПароль1'):
        with pytest.raises(team.TeamError):
            st.change_password('gizat', 'НовыйПароль1', bad)
    with pytest.raises(team.TeamError, match='Текущий'):
        st.change_password('gizat', 'не тот', 'ДругойПароль1')
    st.set_active('gizat', False)
    with pytest.raises(team.TeamError, match='отключена'):
        st.verify('gizat', 'НовыйПароль1')
    with pytest.raises(team.TeamError, match='последнего'):
        st.set_active('admin', False)
    with pytest.raises(team.TeamError, match='последнего'):
        st.set_role('admin', 'user')
    st.reset_password('gizat', 'Reset1')
    st.set_active('gizat', True)
    assert st.verify('gizat', 'Reset1')["must_change"] is True


def test_first_admin_login_forced_password_change_and_sync(tmp_path):
    shared = tmp_path / 'сетевая'
    shared.mkdir()
    c, adm = make_user_api(tmp_path, 'adm', shared)
    s = adm.team_status()
    assert s["enabled"] and s["reachable"] and s["need_admin"] and s["user"] is None
    assert "не короче" in adm.team_setup_admin('boss', 'Руководитель', 'abc')["error"]
    assert "совпадать" in adm.team_setup_admin('bossbo', 'Руководитель', 'BossBo')["error"]
    r = adm.team_setup_admin('Boss', 'Руководитель', 'Boss-2026')
    assert r["ok"] and r["user"]["role"] == 'admin' and not r["need_admin"] and adm._s["team_login"] == 'boss'
    assert "уже есть" in adm.team_setup_admin('x1', 'x', 'xxxxxx')["error"]
    assert adm.team_account_create('gizat', 'Гизат', 'Gizat')["ok"]
    c2, usr = make_user_api(tmp_path, 'usr', shared, Clock(d=17, h=9))
    assert usr.team_login('gizat', 'плохой')["error"] == 'Неверный логин или пароль.'
    r = usr.team_login('gizat', 'Gizat')
    assert r["ok"] and r["user"]["must_change"] is True and usr._s["team_login"] == ''          # со стартовым паролем «запомнить» не включаем
    assert "Текущий" in usr.team_change_password('x', 'НовыйПароль1')["error"]
    r = usr.team_change_password('Gizat', 'НовыйПароль1')
    assert r["ok"] and r["user"]["must_change"] is False and usr._s["team_login"] == 'gizat'
    assert os.path.exists(shared / 'GTime_team' / 'data' / 'gizat.json')


def test_snapshot_contains_days_tasks_and_state(tmp_path):
    shared = tmp_path / 'net'
    shared.mkdir()
    c, adm = make_user_api(tmp_path, 'adm', shared)
    adm.team_setup_admin('boss', 'Босс', 'Boss-2026')
    c2, u = make_user_api(tmp_path, 'u', shared)
    adm.team_account_create('aida', 'Аида', 'Aida')
    u.team_login('aida', 'Aida')
    u._t.tick()
    c2.wall += 600
    u._t.tick()
    tid = u.task_add("Срезка фраз")["tasks"][0]["id"]
    u.task_tags(tid, ['Срезка'])
    u.task_comment(tid, 'секретный комментарий')
    u._team_sync_now()
    snap = json.load(open(shared / 'GTime_team' / 'data' / 'aida.json', encoding='utf-8'))
    assert snap["login"] == 'aida' and snap["state"] == 'work' and snap["today"] == '2026-11-17' and snap["days"]["2026-11-17"]["arrival"] == '09:00:00'
    assert snap["tasks"][0]["comment"] == 'секретный комментарий' and snap["tasks"][0]["tags"] == ['Срезка']
    assert u.team_status()["sync"]["ok"] is True
    c2.locked = True
    u._t.tick()
    u._team_sync_now()
    assert json.load(open(shared / 'GTime_team' / 'data' / 'aida.json', encoding='utf-8'))["state"] == 'locked'
    u.team_logout()                                                              # выход — статус «ушёл», дальше не пишем
    assert json.load(open(shared / 'GTime_team' / 'data' / 'aida.json', encoding='utf-8'))["state"] == 'left'
    assert u.team_status()["user"] is None and u._s["team_login"] == ''


def test_remember_login_auto_signin_and_disabled_account(tmp_path):
    shared = tmp_path / 'net'
    shared.mkdir()
    c, adm = make_user_api(tmp_path, 'adm', shared)
    adm.team_setup_admin('boss', 'Босс', 'Boss-2026')
    adm.team_account_create('aida', 'Аида', 'Aida')
    c2, u = make_user_api(tmp_path, 'u', shared)
    u.team_login('aida', 'Aida')
    u.team_change_password('Aida', 'Новый-пароль1')
    c3, u2 = make_user_api(tmp_path, 'u', shared)                                # перезапуск программы: логин запомнен
    assert u2._s["team_login"] == 'aida' and u2.team_status()["user"]["login"] == 'aida'
    adm.team_account_active('aida', False)
    u2._team_sync_now()                                                          # при следующей отправке отключённого выкидывает
    assert u2._user is None
    c4, u3 = make_user_api(tmp_path, 'u', shared)
    assert u3.team_status()["user"] is None and 'отключена' in u3.team_login('aida', 'Новый-пароль1')["error"]


def test_admin_overview_user_card_and_account_management(tmp_path):
    shared = tmp_path / 'net'
    shared.mkdir()
    c, adm = make_user_api(tmp_path, 'adm', shared, Clock(d=17, h=8, mi=30))
    adm.team_setup_admin('boss', 'Босс', 'Boss-2026')
    adm.team_account_create('aida', 'Аида', 'Aida')
    adm.team_account_create('berik', 'Берик', 'Berik')
    adm.team_account_create('ghost', 'Тот, кто не входил', 'Ghost')
    cu, aida = make_user_api(tmp_path, 'aida', shared, Clock(d=17, h=9, mi=4))
    aida.team_login('aida', 'Aida')
    aida._t.tick()
    for _ in range(300):
        cu.wall += 1
        cu.m += 1
    aida._t.tick()
    tid = aida.task_add("Прослушка и разметка таблицы")["tasks"][0]["id"]
    aida.task_tags(tid, ['Прослушка и разметка'])
    aida.task_wait(tid, 'Данияр')
    aida.task_comment(tid, 'ждём ответ')
    aida.sub_add(tid, 'шаг 1')
    aida._team_sync_now()
    cb, ber = make_user_api(tmp_path, 'berik', shared, Clock(d=17, h=10, mi=15))
    ber.team_login('berik', 'Berik')
    ber._t.tick()
    ber._team_sync_now()
    # данные сняты «сейчас» по часам админа — подгоняем время обновления, чтобы не было «нет связи»
    for lg in ('aida', 'berik'):
        p = shared / 'GTime_team' / 'data' / f'{lg}.json'
        d = json.load(open(p, encoding='utf-8'))
        d["updated"] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    adm._today_iso = lambda: '2026-11-17'
    ov = adm.team_overview()
    by = {r["login"]: r for r in ov["rows"]}
    assert by['aida']["arrival"] == '09:04:00' and by['aida']["state"] == 'work' and by['aida']["tasks_open"] == 1
    assert by['berik']["arrival"] == '10:15:00' and by['ghost']["state"] == 'nodata' and by['boss']["role"] == 'admin'
    past = adm.team_overview('2026-11-16')
    assert {r["login"]: r["state"] for r in past["rows"]}["aida"] == 'absent'                     # в тот день не приходила
    snap = json.load(open(shared / 'GTime_team' / 'data' / 'aida.json', encoding='utf-8'))
    snap["updated"] = (datetime.now() - timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%M:%S')
    json.dump(snap, open(shared / 'GTime_team' / 'data' / 'aida.json', 'w', encoding='utf-8'), ensure_ascii=False)
    assert {r["login"]: r["state"] for r in adm.team_overview()["rows"]}["aida"] == 'offline'     # давно не было связи
    card = adm.team_user('aida', 'week', '2026-11-17')
    t = card["tasks"][0]
    assert card["summary"]["start"] == '2026-11-16' and t["text"] == "Прослушка и разметка таблицы" and t["waiting_who"] == 'Данияр' and t["comment"] == 'ждём ответ'
    assert t["subs"] == [{"text": "шаг 1", "done": False}] and t["tags"] == ['Прослушка и разметка'] and any(d["arrival"] == '09:04:00' for d in card["days"])
    assert adm.team_user('ghost')["nodata"] is True and "Учётки нет" in adm.team_user('нет')["error"]
    r = adm.team_report('week', '2026-11-17')
    assert os.path.exists(r["path"]) and r["people"] == 3 and r["path"].endswith('Отчёт_команды_неделя_2026-11-16.xlsx')
    import openpyxl
    wb = openpyxl.load_workbook(r["path"])
    assert wb.sheetnames == ['Сводка', 'Приход и уход', 'Задачи']
    names = [row[0].value for row in wb['Сводка'].iter_rows(min_row=5)]
    assert 'Аида' in names and 'Берик' in names
    assert any(row[4].value == "Прослушка и разметка таблицы" and row[0].value == 'Аида' for row in wb['Задачи'].iter_rows(min_row=2))
    # учётки
    assert adm.team_account_active('boss', False)["error"] == 'Себя отключить нельзя.'
    assert adm.team_account_role('boss', 'user')["error"] == 'Снять роль администратора у себя нельзя.'
    assert adm.team_account_role('berik', 'admin')["ok"] and adm.team_account_reset('berik', 'Новый1')["ok"] and adm.team_account_name('berik', 'Берик Т.')["ok"]
    lst = {a["login"]: a for a in adm.team_accounts()["accounts"]}
    assert lst['berik']["role"] == 'admin' and lst['berik']["name"] == 'Берик Т.' and lst['berik']["must_change"] is True


def test_non_admin_cannot_use_admin_api_and_folder_errors(tmp_path):
    shared = tmp_path / 'net'
    shared.mkdir()
    c, adm = make_user_api(tmp_path, 'adm', shared)
    adm.team_setup_admin('boss', 'Босс', 'Boss-2026')
    adm.team_account_create('aida', 'Аида', 'Aida')
    cu, u = make_user_api(tmp_path, 'u', shared)
    assert u.team_overview()["error"] == 'Только для администратора.'                       # не вошли
    u.team_login('aida', 'Aida')
    for call in (lambda: u.team_overview(), lambda: u.team_accounts(), lambda: u.team_user('boss'), lambda: u.team_report(),
                 lambda: u.team_account_create('x1', 'x', 'xxxx'), lambda: u.team_account_reset('boss', 'hack')):
        assert call()["error"] == 'Только для администратора.'
    assert "не найдена" in u.team_set_dir(str(tmp_path / 'нет'))["error"]
    ok = u.team_set_dir(str(shared))
    assert ok["reachable"] and ok["user"] is not None                                       # тот же путь — вход сохраняется
    other = tmp_path / 'other'
    other.mkdir()
    st = u.team_set_dir(str(other))
    assert st["user"] is None and st["need_admin"] is True and u._s["team_login"] == ''     # другая папка — другая команда, надо входить заново
    gone = tmp_path / 'gone'
    gone.mkdir()
    u.team_set_dir(str(gone))
    gone.rmdir()
    s = u.team_status()
    assert s["enabled"] and not s["reachable"]                                              # сеть пропала: учёт работает, снимок не уходит
    u._user = {"login": 'aida', "name": 'Аида', "role": 'user', "must_change": False}
    u._team_sync_now()
    assert u._sync_state["ok"] is False and 'недоступна' in u._sync_state["error"]
    assert u.team_set_dir('')["enabled"] is False                                           # отключить командный режим


def test_team_script_loads_before_main_so_init_is_not_missed():
    html = open(os.path.join(ROOT, 'shift_timer', 'ui', 'main.html'), encoding='utf-8').read()
    assert html.index('team.js') < html.index('main.js')                # main.js запускает teamInit() сразу, как только готов pywebview
    for needed in ('lock', 'v-team', 'dlgEmp', 'dlgAcc', 'dlgPass', 'tabTeam'):
        assert f'id="{needed}"' in html
    js = open(os.path.join(ROOT, 'shift_timer', 'ui', 'main.js'), encoding='utf-8').read()
    assert 'teamInit' in js and 'teamStart' in js
