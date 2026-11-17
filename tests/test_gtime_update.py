"""GTime: обновление через папку команды, самоустановка в одну папку, один экземпляр."""
import json
import os
import sys
import time

import pytest

from test_gtime_team import make_user_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import updater  # noqa: E402


def fake_exe(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(content)
    return str(path)


def test_publish_check_and_manifest(tmp_path):
    team = tmp_path / 'net'
    team.mkdir()
    exe = fake_exe(tmp_path / 'build' / 'GTime.exe', b'MZ-new-build-13' * 100)
    with pytest.raises(updater.UpdateError, match='нет номера'):
        updater.publish(str(team), exe, version='1.1', build=0)
    with pytest.raises(updater.UpdateError, match='недоступна'):
        updater.publish(str(tmp_path / 'нет'), exe, version='1.1', build=13)
    with pytest.raises(updater.UpdateError, match='Не найден'):
        updater.publish(str(team), str(tmp_path / 'нет.exe'), version='1.1', build=13)
    m = updater.publish(str(team), exe, version='1.1', build=13, notes='  Теги и отчёт  ')
    assert m["version"] == '1.1' and m["build"] == 13 and m["notes"] == 'Теги и отчёт' and m["size"] == len(b'MZ-new-build-13' * 100) and len(m["sha256"]) == 64
    folder = team / 'GTime_team' / 'update'
    assert (folder / 'GTime.exe').read_bytes() == open(exe, 'rb').read() and not list(folder.glob('*.tmp'))
    assert updater.read_remote(str(team))["version"] == '1.1'
    with pytest.raises(updater.UpdateError, match='более новая'):
        updater.publish(str(team), exe, version='1.0', build=99)              # старую версию поверх новой не кладём, сколько бы ни было сборок
    assert updater.publish(str(team), exe, version='1.1', build=13)["build"] == 13       # ту же — можно (перезалить)
    assert updater.publish(str(team), exe, version='1.1', build=14)["build"] == 14       # та же версия, сборка новее — тоже
    # проверка клиента
    c = updater.check(str(team), version='1.0', build=12)
    assert c["available"] and c["remote"]["version"] == '1.1'
    assert updater.check(str(team), version='1.0', build=99)["available"]                  # версия важнее номера сборки
    assert not updater.check(str(team), version='1.1', build=14)["available"] and not updater.check(str(team), version='1.1', build=20)["available"]
    assert updater.check(str(team), version='1.1', build=13)["available"]                  # та же версия, но сборка старее
    assert not updater.check(str(team), version='2.0', build=1)["available"]
    with pytest.raises(updater.UpdateError, match='не выбрана'):
        updater.check('', version='1.0', build=1)
    with pytest.raises(updater.UpdateError, match='недоступна'):
        updater.check(str(tmp_path / 'нет'), version='1.0', build=1)
    (folder / 'GTime.exe').unlink()                                           # манифест есть, файла нет — обновления нет
    assert not updater.check(str(team), version='1.0', build=1)["available"]
    for bad in ('{ не json', '{"version": "", "sha256": "' + 'a' * 64 + '"}', '{"version": "abc", "sha256": "' + 'a' * 64 + '"}', '[]'):
        (folder / 'version.json').write_text(bad, encoding='utf-8')
        assert updater.read_remote(str(team)) is None                         # битый манифест не ломает


def test_apply_update_swaps_running_exe_and_launches_new(tmp_path):
    team = tmp_path / 'net'
    team.mkdir()
    new = fake_exe(tmp_path / 'build' / 'GTime.exe', b'NEW' * 1000)
    updater.publish(str(team), new, version='1.2', build=14)
    cur = fake_exe(tmp_path / 'app' / 'GTime.exe', b'OLD' * 1000)
    launched = []
    v = updater.apply_update(str(team), cur, launch=lambda exe, args: launched.append((exe, args)), extra_args=['--minimized'])
    assert v == '1.2' and open(cur, 'rb').read() == b'NEW' * 1000 and open(cur + '.old', 'rb').read() == b'OLD' * 1000
    assert launched == [(cur, ['--replace', '--minimized'])] and not os.path.exists(cur + '.new')
    assert (tmp_path / 'app' / 'version.txt').read_text() == '1.2 14'
    updater.cleanup_old(cur)
    assert not os.path.exists(cur + '.old')
    # повреждённый файл в папке: ничего не меняется
    (team / 'GTime_team' / 'update' / 'GTime.exe').write_bytes(b'BROKEN')
    cur2 = fake_exe(tmp_path / 'app2' / 'GTime.exe', b'KEEP')
    with pytest.raises(updater.UpdateError, match='контрольная сумма'):
        updater.apply_update(str(team), cur2, launch=lambda *a: launched.append('x'))
    assert open(cur2, 'rb').read() == b'KEEP' and not os.path.exists(cur2 + '.new') and not os.path.exists(cur2 + '.old') and launched[-1] != 'x'
    with pytest.raises(updater.UpdateError, match='нет новой сборки'):
        updater.apply_update(str(tmp_path / 'пусто'), cur2, launch=lambda *a: None)


def test_swap_rolls_back_when_new_file_cannot_be_placed(tmp_path):
    target = fake_exe(tmp_path / 'GTime.exe', b'OLD')
    with pytest.raises(OSError):
        updater._swap_in(str(tmp_path / 'нет_такого.new'), target)
    assert open(target, 'rb').read() == b'OLD' and not os.path.exists(target + '.old')       # прежний файл на месте


def test_self_install_into_one_folder(tmp_path):
    inst = tmp_path / 'Local' / 'GTime' / 'GTime.exe'
    me = fake_exe(tmp_path / 'Downloads' / 'GTime.exe', b'BUILD15')
    L = []
    launch = lambda exe, args: L.append((exe, args))
    assert updater.ensure_installed(['GTime.exe', '--minimized'], exe_path=me, target=str(inst), launch=launch, frozen=True, build=15, version='1.0') is True
    assert inst.read_bytes() == b'BUILD15' and (inst.parent / 'version.txt').read_text() == '1.0 15' and os.path.exists(me)   # установили, исходник не тронут
    assert L == [(str(inst), ['--replace', '--minimized'])]
    # там уже стоит такая же или новее: свою копию не трогаем, запускаем установленную
    L.clear()
    me2 = fake_exe(tmp_path / 'Desktop' / 'GTime.exe', b'BUILD14')
    assert updater.ensure_installed(['GTime.exe'], exe_path=me2, target=str(inst), launch=launch, frozen=True, build=14, version='1.0') is True
    assert inst.read_bytes() == b'BUILD15' and L == [(str(inst), [])]
    # новее установленной: заменяем, старая — в .old
    L.clear()
    me3 = fake_exe(tmp_path / 'Downloads2' / 'GTime.exe', b'BUILD16')
    assert updater.ensure_installed(['GTime.exe'], exe_path=me3, target=str(inst), launch=launch, frozen=True, build=16, version='1.1') is True
    assert inst.read_bytes() == b'BUILD16' and (inst.parent / 'GTime.exe.old').read_bytes() == b'BUILD15' and L == [(str(inst), ['--replace'])]
    assert (inst.parent / 'version.txt').read_text() == '1.1 16'
    # уже работаем из нужного места / не exe / отказ — ничего не делаем
    L.clear()
    assert updater.ensure_installed(['x'], exe_path=str(inst), target=str(inst), launch=launch, frozen=True, build=16, version='1.1') is False
    assert updater.ensure_installed(['x'], exe_path=me, target=str(inst), launch=launch, frozen=False, build=99) is False
    assert updater.ensure_installed(['x', '--no-install'], exe_path=me, target=str(inst), launch=launch, frozen=True, build=99) is False
    assert L == [] and inst.read_bytes() == b'BUILD16'
    blocked = tmp_path / 'file_not_dir'
    blocked.write_text('x')
    assert updater.ensure_installed(['x'], exe_path=me, target=str(blocked / 'GTime.exe'), launch=launch, frozen=True, build=99) is False   # нет прав / нельзя создать папку


def test_single_instance_helpers_are_safe_off_windows():
    if sys.platform != 'win32':
        assert updater.instance_acquire() is True and updater.instance_signal('show') is False and updater.instance_watch(lambda: 0, lambda: 0) is None


def make(tmp_path, monkeypatch, build=12, name='u', version='1.0'):
    team = tmp_path / 'net'
    team.mkdir(exist_ok=True)
    c, api = make_user_api(tmp_path, name, team)
    monkeypatch.setattr(updater, 'BUILD', build)
    monkeypatch.setattr(updater, 'VERSION', version)
    api._frozen = lambda: True
    return team, api


def test_api_status_check_and_notice(tmp_path, monkeypatch):
    team, api = make(tmp_path, monkeypatch, build=12)
    st = api.update_status()
    assert st["version"] == '1.0' and st["build"] == 12 and st["frozen"] and st["remote"] is None and st["available"] is False
    notes = []
    api._t.on_notice = lambda n: notes.append((n["kind"], n["text"]))
    exe = fake_exe(tmp_path / 'b' / 'GTime.exe', b'NEWEXE')
    updater.publish(str(team), exe, version='1.1', build=13, notes='Теги')
    st = api.update_check()                                                    # кнопка «Проверить» уведомление не шлёт
    assert st["available"] and st["remote"]["version"] == '1.1' and st["remote"]["notes"] == 'Теги' and notes == []
    api._update_check_now()                                                    # фоновая проверка — один раз на версию
    api._update_check_now()
    assert notes == [("update", "Доступна новая версия GTime (1.1) — обновите в главном окне")]
    api.save_settings({"team_dir": ''})
    assert 'не выбрана' in api.update_check()["error"] and api.update_status()["available"] is False


def test_api_background_check_only_for_built_exe_with_folder(tmp_path, monkeypatch):
    team, api = make(tmp_path, monkeypatch, build=12)
    calls = []
    api._update_check_now = lambda notify=True: (calls.append(1), setattr(api, '_upd_busy', False))
    api._upd_next = time.monotonic() - 1
    api._frozen = lambda: False
    api._update_maybe()
    assert calls == []                                                         # из исходников не проверяем
    api._frozen = lambda: True
    api._update_maybe()
    time.sleep(0.2)
    assert calls == [1] and api._upd_next > time.monotonic() + 3000            # проверили и отложили на час
    api._update_maybe()
    time.sleep(0.1)
    assert calls == [1]
    monkeypatch.setattr(updater, 'BUILD', 0)
    api._upd_next = time.monotonic() - 1
    api._update_maybe()
    time.sleep(0.1)
    assert calls == [1]                                                        # без номера сборки — тоже нет


def test_api_apply_update_replaces_exe_and_closes(tmp_path, monkeypatch):
    team, api = make(tmp_path, monkeypatch, build=12)
    updater.publish(str(team), fake_exe(tmp_path / 'b' / 'GTime.exe', b'NEWEXE'), version='1.1', build=13)
    cur = fake_exe(tmp_path / 'app' / 'GTime.exe', b'OLDEXE')
    api._exe_path = lambda: cur
    launched, closed = [], []
    api._relaunch = lambda exe, args: launched.append((exe, args))
    api.close_app = lambda: closed.append(1)
    r = api.update_apply()
    assert r == {"ok": True, "version": '1.1'} and open(cur, 'rb').read() == b'NEWEXE' and launched == [(cur, ['--replace'])]
    time.sleep(1.0)
    assert closed == [1]                                                       # старый экземпляр закрывается после запуска нового
    api2_team, api2 = make(tmp_path, monkeypatch, build=13, name='u2', version='1.1')
    assert "Новой версии нет" in api2.update_apply()["error"]
    api2._frozen = lambda: False
    assert "собранном" in api2.update_apply()["error"]


def test_api_publish_requires_admin_and_built_exe(tmp_path, monkeypatch):
    team, api = make(tmp_path, monkeypatch, build=13, version='1.1')
    exe = fake_exe(tmp_path / 'b' / 'GTime.exe', b'EXE13')
    api._exe_path = lambda: exe
    assert "администратора" in api.update_publish()["error"]
    api._user = {"login": 'aida', "name": 'Аида', "role": 'user', "must_change": False}
    assert "администратора" in api.update_publish()["error"]
    api._user = {"login": 'boss', "name": 'Босс', "role": 'admin', "must_change": False}
    r = api.update_publish('Новая сборка')
    assert r["ok"] and r["version"] == '1.1' and updater.read_remote(str(team))["notes"] == 'Новая сборка'
    assert api.update_status()["remote"]["version"] == '1.1' and api.update_status()["available"] is False
    monkeypatch.setattr(updater, 'VERSION', '1.0')
    assert "более новая" in api.update_publish()["error"]
    monkeypatch.setattr(updater, 'BUILD', 0)
    assert "номер сборки" in api.update_publish()["error"]
    api._frozen = lambda: False
    assert "собранный" in api.update_publish()["error"]


def test_version_file_workflow_and_ui_hooks():
    ver = open(os.path.join(ROOT, 'shift_timer', 'version.py'), encoding='utf-8').read()
    assert ver.strip().endswith('BUILD = 0') and 'VERSION = "1.0"' in ver
    wf = open(os.path.join(ROOT, '.github', 'workflows', 'build-shift-timer.yml'), encoding='utf-8').read()
    assert 'version.py' in wf and wf.index('version.py') < wf.index('pyinstaller --noconfirm')    # номер сборки вшивается до pyinstaller
    html = open(os.path.join(ROOT, 'shift_timer', 'ui', 'main.html'), encoding='utf-8').read()
    assert html.index('update.js') < html.index('main.js') and 'id="updBar"' in html and 'id="updPub"' in html
    assert 'updateInit' in open(os.path.join(ROOT, 'shift_timer', 'ui', 'main.js'), encoding='utf-8').read()
    app = open(os.path.join(ROOT, 'shift_timer', 'app.py'), encoding='utf-8').read()
    assert app.index('ensure_installed') < app.index('instance_acquire') < app.index('api = Api()')     # сначала переезд, потом один экземпляр


def test_version_parsing_and_ordering():
    p = updater.parse_version
    assert p('1.0') == (1, 0, 0) and p('1.10.2') == (1, 10, 2) and p('v2') == (2, 0, 0) and p('') == (0, 0, 0) and p(None) == (0, 0, 0) and p('1.2.3.4') == (1, 2, 3)
    assert updater.newer('1.10', 1, '1.9', 99)                 # по числам, а не по тексту
    assert updater.newer('2.0', 1, '1.9.9', 500) and not updater.newer('1.0', 500, '1.1', 1)
    assert updater.newer('1.1', 14, '1.1', 13) and not updater.newer('1.1', 13, '1.1', 13) and not updater.newer('1.0.0', 5, '1.0', 5)
