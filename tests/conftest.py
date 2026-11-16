"""Автотесты GVox — без Windows: заглушки webview / звука из tools/demo, настоящий Api из main.py.

    python -m pytest tests -q

Данные создаются во временной папке теста; реальные проекты не трогаются."""
import hashlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'demo'))
sys.path.insert(0, ROOT)

import harness                                    # noqa: E402  (заглушки ставятся при импорте)
from demo_env import speech, write                # noqa: E402


def md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def wav(path, text='проверка', k=1.0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write(path, speech(text, decl=1) * k)
    return path


def snapshot(folder):
    """Все файлы папки (с подпапками) → {относительный путь: md5}."""
    out = {}
    for root, _d, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, folder).replace(os.sep, '/')] = md5(p)
    return out


@pytest.fixture
def api():
    harness.DIALOG.clear()
    return harness.Api()


@pytest.fixture
def dialog():
    """Ответы окон выбора файла/папки по очереди: dialog(path1, path2…)."""
    def put(*paths):
        harness.DIALOG.extend([[p] for p in paths])
    yield put
    harness.DIALOG.clear()


@pytest.fixture
def marks(tmp_path):
    """Папка марок: ru_mark / kz_mark (у каждой своя запись), uni_mark — общие; таблица RU | KZ."""
    import openpyxl
    m = tmp_path / 'Марки'
    for d, names in (('ru_mark', ['AUDI 80', 'AUDI 100', 'BMW X5', 'Lada']), ('kz_mark', ['AUDI 80', 'AUDI 100', 'Lada']),
                     ('uni_mark', ['Kia'])):
        for n in names:
            wav(str(m / d / f'{n}.wav'), f'{n} {d}')
    xl = tmp_path / 'марки.xlsx'
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['<ru_mark>', '<kz_mark>'])
    for n in ['AUDI 80', 'AUDI 100', 'BMW X5', 'Lada', 'Kia', 'Mazda']:
        ws.append([n, n])
    wb.save(xl)
    return str(m), str(xl)


@pytest.fixture
def listen(api, dialog, marks):
    folder, xl = marks
    dialog(folder, xl)
    api.listen_pick_folder()
    api.listen_pick_table()
    return api


@pytest.fixture
def studio(tmp_path, monkeypatch):
    """Демо-проект Студии во временной папке: (api, st, units, папка проекта)."""
    import demo_env
    monkeypatch.setattr(demo_env, 'D', str(tmp_path))
    monkeypatch.setattr(demo_env, 'XL', str(tmp_path / 'demo.xlsx'))
    harness.DIALOG.clear()
    yield harness.build_project()
    harness.DIALOG.clear()
