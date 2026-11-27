"""GTime: самоустановка в одну папку, один экземпляр, версии."""
import json
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import updater  # noqa: E402


def fake_exe(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(content)
    return str(path)


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


def test_version_file_workflow_and_ui_hooks():
    ver = open(os.path.join(ROOT, 'shift_timer', 'version.py'), encoding='utf-8').read()
    assert ver.strip().endswith('BUILD = 0') and 'VERSION = "' in ver
    wf = open(os.path.join(ROOT, '.github', 'workflows', 'build-shift-timer.yml'), encoding='utf-8').read()
    assert 'version.py' in wf and wf.index('version.py') < wf.index('pyinstaller --noconfirm')    # номер сборки вшивается до pyinstaller
    app = open(os.path.join(ROOT, 'shift_timer', 'app.py'), encoding='utf-8').read()
    assert app.index('ensure_installed') < app.index('instance_acquire') < app.index('api = Api()')     # сначала переезд, потом один экземпляр


def test_no_team_mode_or_shared_folder_left():
    """Командного режима и обновления через сетевую папку в программе нет."""
    base = os.path.join(ROOT, 'shift_timer')
    for gone in ('team.py', 'team_api.py', 'update_api.py', os.path.join('ui', 'team.js'), os.path.join('ui', 'update.js')):
        assert not os.path.exists(os.path.join(base, gone)), gone
    for f in ('app.py', 'updater.py', 'report.py', os.path.join('ui', 'main.html'), os.path.join('ui', 'main.js')):
        text = open(os.path.join(base, f), encoding='utf-8').read()
        for word in ('team_dir', 'GTime_team', 'team_login', 'export_team', 'teamInit', 'id="lock"', 'update_publish'):
            assert word not in text, (f, word)


def test_version_parsing_and_ordering():
    p = updater.parse_version
    assert p('1.0') == (1, 0, 0) and p('1.10.2') == (1, 10, 2) and p('v2') == (2, 0, 0) and p('') == (0, 0, 0) and p(None) == (0, 0, 0) and p('1.2.3.4') == (1, 2, 3)
    assert updater.newer('1.10', 1, '1.9', 99)                 # по числам, а не по тексту
    assert updater.newer('2.0', 1, '1.9.9', 500) and not updater.newer('1.0', 500, '1.1', 1)
    assert updater.newer('1.1', 14, '1.1', 13) and not updater.newer('1.1', 13, '1.1', 13) and not updater.newer('1.0.0', 5, '1.0', 5)
