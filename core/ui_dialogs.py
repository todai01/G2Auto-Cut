"""Сообщения и вопросы пользователю — в стиле самой программы, а не
системными окнами Windows (alert / create_confirmation_dialog)."""

import json
import time

import webview


def _js(code):
    try:
        return webview.windows[0].evaluate_js(code)
    except Exception:
        return None


def ui_alert(message):
    """Сообщение в окне программы (не блокирует Python)."""
    _js(f"showBeautifulAlert({json.dumps(message, ensure_ascii=False)})")


def ui_toast(message):
    """Короткая подсказка внизу экрана (не блокирует Python)."""
    _js(f"showToast({json.dumps(message, ensure_ascii=False)})")


def ui_confirm(message, ok='ОК', cancel='Отмена', timeout_s=600):
    """Вопрос с двумя кнопками в окне программы. Ждёт ответа пользователя:
    True — «ok», False — «cancel», крестик или Escape."""
    _js("window.__gvoxConfirm = null; showBeautifulConfirm("
        f"{json.dumps(message, ensure_ascii=False)}, {json.dumps(ok, ensure_ascii=False)}, "
        f"{json.dumps(cancel, ensure_ascii=False)}).then(r => {{ window.__gvoxConfirm = r ? 1 : 0; }}); 0")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = _js("window.__gvoxConfirm")
        if r in (0, 1):
            return bool(r)
        time.sleep(0.1)
    return False
