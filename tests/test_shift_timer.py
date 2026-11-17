"""Мини-приложение «Конец смены» (shift_timer/): настройки и расчёт времени (JS — через node)."""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'shift_timer'))
import app as shift_app                                    # noqa: E402


def test_clean_fixes_garbage():
    assert shift_app.clean(None) == shift_app.DEFAULTS
    s = shift_app.clean({"start": "9:05", "end": " 18:30 ", "seconds": False, "theme": "dark", "mini_pos": [10.7, -5]})
    assert (s["start"], s["end"], s["seconds"], s["theme"], s["mini_pos"]) == ("09:05", "18:30", False, "dark", [10, -5])
    bad = shift_app.clean({"start": "25:00", "end": "12:61", "seconds": "yes", "theme": "pink", "mini_pos": [1]})
    assert bad == shift_app.DEFAULTS


def test_save_and_load_roundtrip(tmp_path):
    f = str(tmp_path / 'ShiftTimer' / 'settings.json')
    api = shift_app.Api(f)
    assert api.get_settings() == shift_app.DEFAULTS            # файла нет — значения по умолчанию
    s = api.save_settings({"end": "17:15", "seconds": False, "theme": "light", "bogus": 1})
    assert s["end"] == "17:15" and s["seconds"] is False and "bogus" not in s
    again = shift_app.Api(f).get_settings()                    # после перезапуска
    assert again == s
    assert not os.path.exists(f + '.tmp')


def test_broken_settings_file_does_not_crash(tmp_path):
    f = tmp_path / 's.json'
    f.write_text('{ не json', encoding='utf-8')
    assert shift_app.load_settings(str(f)) == shift_app.DEFAULTS
    f.write_text('[1, 2]', encoding='utf-8')
    assert shift_app.load_settings(str(f)) == shift_app.DEFAULTS


def test_invalid_patch_keeps_previous(tmp_path):
    api = shift_app.Api(str(tmp_path / 's.json'))
    api.save_settings({"end": "17:00"})
    assert api.save_settings({"end": "banana"})["end"] == "18:00"   # неверное значение → по умолчанию, не падаем
    assert api.save_settings("мусор")["end"] == "18:00"


class FakeWin:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, js):
        self.calls.append(('js', js))

    def show(self):
        self.calls.append(('show',))

    def hide(self):
        self.calls.append(('hide',))


def test_mini_visibility_and_push(tmp_path):
    api = shift_app.Api(str(tmp_path / 's.json'))
    api._main, api._mini = FakeWin(), FakeWin()
    api.save_settings({"mini_visible": True})
    assert ('show',) in api._mini.calls and any(c[0] == 'js' and '"mini_visible": true' in c[1] for c in api._main.calls)
    api.save_settings({"mini_visible": False})
    assert ('hide',) in api._mini.calls
    n = len(api._mini.calls)
    api.save_settings({"theme": "dark"})                       # тема окно мини не показывает / не прячет
    assert [c for c in api._mini.calls[n:] if c[0] in ('show', 'hide')] == []
    assert any(c[0] == 'js' and '"theme": "dark"' in c[1] for c in api._mini.calls[n:])


def test_selftest_without_webview_reports_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, 'webview', None)          # как будто модуля нет
    assert shift_app.selftest() == 1


@pytest.mark.skipif(not shutil.which('node'), reason='нет node')
def test_js_logic():
    r = subprocess.run(['node', os.path.join(ROOT, 'tests', 'shift_logic.test.js')], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'OK' in r.stdout
