---
name: tutorial-video
description: Переснять ролики обучения GVox (frontend/tutorial/*.webm) после изменения интерфейса или добавить новый урок. Использовать, когда меняется экран, который показан в уроке, или пользователь просит урок.
---

# Ролики обучения

Уроки описаны в `frontend/tutorial.js` (`TUTORIAL`: id, название, шаги, `open`). Ролик урока —
`frontend/tutorial/<id>.webm` (VP9, 1280×720) + превью `<id>.jpg`.

Сценарии — `tools/demo/clips/`:

| файл | ролики |
|---|---|
| c_menu.py | menu |
| c_studio.py | studio_new, studio_record, studio_assembly |
| c_sums.py | studio_sums |
| c_ready.py | studio_ready |
| c_audit.py | audit, audit_final |
| c_ctor.py | constructor |
| c_vars.py | vars_ready, vars_batch |
| c_listen.py | listen (синтез — на `tools/demo/mock_synth.html`, запускать через `xvfb-run -a`) |
| c_cut.py | cut_wav |
| c_utils.py | rename_match, pptx, converter, clone, strip |

## Переснять
```bash
python tools/demo/clips/c_utils.py pptx converter     # только названные ролики
python tools/demo/clips/c_studio.py                    # все ролики файла
```
Долгие (1–3 мин на ролик) — запускать в фоне. Стенд: настоящий интерфейс + Api на демо-данных,
кадры — CDP screencast, сборка — системный ffmpeg (Playwright-запись не нужна).

## Новый урок
1. Сценарий в `tools/demo/clips/` по образцу: `with Rec('<id>', a) as r:` → подготовка →
   `r.start()` → `r.cap(...)` (подпись), `r.click(sel)`, `r.key('Enter', 'Enter')`, `r.drag(...)`.
   `r.top = 'top' | 'mid'` — где подпись, чтобы не закрывала важное.
2. Урок в `TUTORIAL` (`tutorial.js`), шаги — те же, что в подписях. При нужде — F1-привязка в `tutContextTopic`.
3. Проверить: каждый ролик грузится (длительность > 0, превью есть) и посмотреть кадры:
   `ffmpeg -i ролик.webm -vf "fps=1/4,scale=640:-1,tile=3x3" кадры.png` → Read.

## Подводные камни
- Пути в роликах подменяются на `D:/GVox_демо/…` (`harness.nice`) — реальные пути не показывать.
- Перед кликом по пункту, который сам открывает окно выбора файла, сначала `DIALOG.append`.
- Клик по ленте дублей может не сработать при перерисовке — наведите и вызовите `ttsRailClick(i)`.
- Не называть JS-функции стенда так же, как функции приложения (`__tutCap`, `__tutKeyShow`).
- Не ждать фоновые процессы через `pgrep -f имя.py` — он находит и саму ожидающую команду.
