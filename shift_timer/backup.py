"""Резервная копия GTime одним архивом: журнал, задачи с файлами, настройки. И восстановление из неё (перенос на другой компьютер).

Файлы копии: history.json, tasks.json, settings.json, task_files/<номер задачи>/<файл>, manifest.json.
Восстановление ничего не трогает, пока архив не проверен; перед заменой прежние данные сохраняются в «до_восстановления_….zip».
"""
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime

KNOWN = ('history.json', 'tasks.json', 'settings.json')
MAX_TOTAL = 4 * 1024 ** 3                                # не распаковываем архивы больше 4 ГБ
FILE_RE = re.compile(r'^task_files/(\d+)/([^/\\]+)$')


def make_backup(paths, dest, now=None):
    """paths — {"history.json": путь, "tasks.json": путь, "settings.json": путь, "task_files": папка}. Пишет zip в dest."""
    now = now or datetime.now()
    os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
    tmp = dest + '.tmp'
    n_files = 0
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in KNOWN:
            p = paths.get(name)
            if p and os.path.isfile(p):
                z.write(p, name)
        root = paths.get("task_files")
        if root and os.path.isdir(root):
            for tid in sorted(os.listdir(root)):
                d = os.path.join(root, tid)
                if tid.isdigit() and os.path.isdir(d):
                    for f in sorted(os.listdir(d)):
                        if os.path.isfile(os.path.join(d, f)):
                            z.write(os.path.join(d, f), f'task_files/{tid}/{f}')
                            n_files += 1
        z.writestr('manifest.json', json.dumps({"app": "GTime", "version": 1, "created": now.strftime('%Y-%m-%dT%H:%M:%S'), "files": n_files}, ensure_ascii=False))
    os.replace(tmp, dest)
    return {"path": dest, "files": n_files, "size": os.path.getsize(dest)}


def inspect(zip_path):
    """Проверить архив, ничего не распаковывая: (список допустимых имён, manifest) или RuntimeError с понятным текстом."""
    try:
        z = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError):
        raise RuntimeError('Это не архив GTime (файл повреждён или не zip).')
    with z:
        names, total = [], 0
        manifest = None
        for i in z.infolist():
            n = i.filename
            if i.is_dir():
                continue
            if n == 'manifest.json':
                try:
                    manifest = json.loads(z.read(n).decode('utf-8'))
                except (ValueError, UnicodeDecodeError):
                    manifest = None
                continue
            if n in KNOWN or FILE_RE.match(n):
                names.append(n)
                total += i.file_size
            elif n.startswith('/') or '..' in n.split('/') or ':' in n:
                raise RuntimeError('В архиве небезопасные пути — восстановление отменено.')
        if not manifest or manifest.get("app") != 'GTime':
            raise RuntimeError('Это не копия GTime (нет метки программы).')
        if not any(n in KNOWN for n in names):
            raise RuntimeError('В архиве нет журнала, задач и настроек.')
        if total > MAX_TOTAL:
            raise RuntimeError('Архив слишком большой.')
        return names, manifest


def restore_backup(zip_path, paths, safety_dir):
    """Заменить данные содержимым копии. Возвращает {"restored": [...], "safety": путь}. Сбой посередине — всё возвращается как было."""
    names, manifest = inspect(zip_path)
    os.makedirs(safety_dir, exist_ok=True)
    safety = os.path.join(safety_dir, f'до_восстановления_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.zip')
    make_backup(paths, safety)
    tmp = tempfile.mkdtemp(prefix='gtime_restore_')
    try:
        with zipfile.ZipFile(zip_path) as z:
            for n in names:
                dst = os.path.join(tmp, *n.split('/'))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(n) as src, open(dst, 'wb') as out:
                    shutil.copyfileobj(src, out)
        for n in names:
            if n in KNOWN:
                json.load(open(os.path.join(tmp, n), encoding='utf-8'))      # битый json не ставим
        _swap(tmp, names, paths)
    except Exception as e:
        try:
            _swap_from_zip(safety, paths)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f'Не удалось восстановить: {e}. Прежние данные возвращены.')
    shutil.rmtree(tmp, ignore_errors=True)
    return {"restored": [n for n in names if n in KNOWN] + (['task_files'] if any(n.startswith('task_files/') for n in names) else []),
            "safety": safety, "created": manifest.get("created")}


def _swap(tmp, names, paths):
    for n in names:
        if n in KNOWN and paths.get(n):
            os.makedirs(os.path.dirname(paths[n]) or '.', exist_ok=True)
            os.replace(os.path.join(tmp, n), paths[n])
    root = paths.get("task_files")
    if root and (any(n.startswith('task_files/') for n in names) or 'tasks.json' in names):      # задачи из копии — и файлы только её
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root, exist_ok=True)
        for n in names:
            m = FILE_RE.match(n)
            if m:
                dst = os.path.join(root, m.group(1), m.group(2))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(os.path.join(tmp, *n.split('/')), dst)


def _swap_from_zip(zip_path, paths):
    t = tempfile.mkdtemp(prefix='gtime_back_')
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(t)
        names = [n for n in KNOWN if os.path.isfile(os.path.join(t, n))]
        files = []
        for tid in (os.listdir(os.path.join(t, 'task_files')) if os.path.isdir(os.path.join(t, 'task_files')) else []):
            for f in os.listdir(os.path.join(t, 'task_files', tid)):
                files.append(f'task_files/{tid}/{f}')
        _swap(t, names + files, paths)
        if paths.get("task_files") and not files:
            shutil.rmtree(paths["task_files"], ignore_errors=True)
    finally:
        shutil.rmtree(t, ignore_errors=True)
