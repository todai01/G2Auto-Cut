---
name: demo-check
description: Проверить изменение GVox без Windows — на демо-проекте: логику через настоящий Api в Python, интерфейс через Playwright (скриншот, ошибки JS). Использовать после любой правки core/* или frontend/* перед коммитом.
---

# Проверка на демо-проекте

Windows, pywebview, Audacity и микрофона здесь нет. `tools/demo/` подставляет заглушки и
даёт настоящий `Api` из `main.py` на демо-таблице (`tools/demo/_work/demo.xlsx`, RU: фразы,
суммы, даты). Демо-данные — в `tools/demo/_work/` (в git не идут).

## 1. Синтаксис — всегда
```bash
node --check frontend/script.js && node --check frontend/tutorial.js
python -m py_compile main.py core/*.py
```

## 2. Логика — Python-скрипт в scratchpad
```python
import sys; sys.path.insert(0, '/home/user/G2Auto-Cut/tools/demo')
from harness import build_project      # Api из main.py + демо-проект Студии
a, st, U, wd = build_project()          # st = состояние Студии, U = units, wd = папка проекта
a._tts_ensure_value_units()             # строки сумм/дат
a.tts_prompt_mode('sum_ru'); print(a.tts_prompt_info())
```
Воспроизводите сценарий пользователя по шагам и печатайте то, что он видел бы
(что предлагает суфлёр, какие файлы легли, что покажет аудит). Для багов — сначала
воспроизвести, потом чинить, потом показать «до / после».

## 3. Интерфейс
```bash
python tools/demo/check.py studio [--mode sum_ru] [--js "ttsOpenUnits('all')"] [--shot out.png]
python tools/demo/check.py menu | constructor | audit
```
Посмотрите скриншот (Read) и строку «ошибки JS». Для своего сценария — `harness.Rec`
(курсор, клики, клавиши); примеры — `tools/demo/clips/c_*.py`. Окна выбора файлов:
`harness.DIALOG.append([путь])` перед действием. Подмена метода: `harness.FAKE['имя'] = fn`.
Запись с микрофона — `fake_rec.install(a)` + `fake_rec.read_line(r, a)`.

## 4. Отчёт пользователю
Что проверено и как (демо, песочница); что не проверено (Windows, реальная таблица KZ,
Audacity, микрофон) — прямо так и сказать.
