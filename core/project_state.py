"""Единый контейнер состояния проекта: сохраняет и восстанавливает работу
между запусками программы. Раньше всё (тексты из Excel, номер текущего
дубля, режим экрана) жило только в памяти — закрыл окно, и всё пропало.
Теперь это же состояние пишется в project.json рядом с папкой проекта."""

import json
import os

# Поля объекта Api, которые входят в сохранённый снимок проекта.
STATE_FIELDS = [
    'phrases_data', 'excel_name', 'project_name', 'variables',
    'current_mode', 'state_memory', 'chunk_index', 'phrase_index',
]

STATE_FILENAME = 'project.json'


def snapshot(api):
    """Собирает текущее состояние проекта в обычный словарь для сохранения."""
    return {field: getattr(api, field, None) for field in STATE_FIELDS}


def save(api):
    """Пишет project.json в папку проекта. Любая ошибка проглатывается —
    сохранение прогресса никогда не должно мешать основной работе."""
    work_dir = getattr(api, 'work_dir', None)
    if not work_dir or not os.path.isdir(work_dir):
        return
    try:
        path = os.path.join(work_dir, STATE_FILENAME)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snapshot(api), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load(work_dir):
    """Читает project.json из папки проекта. Возвращает None, если файла
    нет или он повреждён — тогда проект просто открывается как обычно,
    без восстановления."""
    if not work_dir:
        return None
    path = os.path.join(work_dir, STATE_FILENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def apply(api, data):
    """Переносит сохранённый словарь обратно в поля Api."""
    if not data:
        return
    for field in STATE_FIELDS:
        if field in data and data[field] is not None:
            setattr(api, field, data[field])
