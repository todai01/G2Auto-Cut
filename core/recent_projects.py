"""Список недавних проектов для стартового экрана.

В отличие от project_state.py (снимок одного конкретного проекта,
лежащий внутри его же папки), этот список не привязан ни к одному
проекту — он живёт в постоянном месте у пользователя и просто
запоминает, какие папки открывались последними."""

import json
import os
import time

RECENTS_DIR = os.path.join(os.path.expanduser('~'), '.g2autocut')
RECENTS_PATH = os.path.join(RECENTS_DIR, 'recent_projects.json')
MAX_RECENTS = 8


def _read():
    if not os.path.exists(RECENTS_PATH):
        return []
    try:
        with open(RECENTS_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def touch(work_dir, project_name):
    """Отмечает проект как недавно открытый. Любая ошибка проглатывается —
    это вспомогательный список, а не критичная для работы часть."""
    if not work_dir:
        return
    try:
        os.makedirs(RECENTS_DIR, exist_ok=True)
        items = [it for it in _read() if it.get('path') != work_dir]
        items.insert(0, {
            "path": work_dir,
            "name": project_name or os.path.basename(work_dir),
            "updated_at": time.time()
        })
        with open(RECENTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(items[:MAX_RECENTS], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def list_recent():
    """Отдаёт недавние проекты, чьи папки ещё реально существуют на диске —
    удалённые или перемещённые папки просто не показываем."""
    return [it for it in _read() if it.get('path') and os.path.isdir(it['path'])]
