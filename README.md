# G2Auto-Cut

Десктопное приложение для автоматической нарезки и монтажа озвучки (G2Studio).

## Архитектура

- `main.py` — точка входа. Поднимает окно **pywebview**, отдаёт во фронтенд класс `Api`,
  собранный из миксинов, и управляет воспроизведением превью.
- `core/` — основная логика:
  - `phrase_handler.py` — работа с фразами из Excel;
  - `project_handler.py` — загрузка аудио, нарезка на чанки, режимы папок;
  - `audacity_montage.py` — монтаж и сохранение через Audacity;
  - `variables_handler.py` — режим переменных (VarBatch) и пакетная обработка.
- `utils/` — вспомогательное:
  - `audacity_client.py` — связь с Audacity через именованные каналы Windows
    (`ToSrvPipe` / `FromSrvPipe`);
  - `audio_player.py` — воспроизведение через `winsound`;
  - `file_utils.py` — пути и длительность WAV.
- `frontend/` — интерфейс (`index.html`, `script.js`, `style.css`). JS вызывает Python
  через `pywebview.api.*` и перерисовывает экран по состоянию из `get_ui_state()`.

## Рабочие папки проекта

`Chunks` → `Good` / `Переменные` → `Проверенные`.
При воспроизведении всегда выбирается самый «готовый» вариант файла.

## Зависимости

Python: `pywebview`, `pydub`, `openpyxl`, `pywin32`.
Внешние: `ffmpeg.exe`, `ffprobe.exe` рядом с `main.py`, установленный Audacity
с включённым mod-script-pipe. Платформа — Windows.
