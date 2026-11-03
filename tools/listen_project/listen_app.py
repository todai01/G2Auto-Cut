"""GVox · Прослушка переменных — отдельная программа (только этот режим).

Окно — frontend/listen_app.html, логика — core/listen_mode.py.
Собрать .exe: build_listen.bat (или python build_listen.py)."""
import sys

# Первым: на Windows служебные консольные программы (ffmpeg) — без мигающих окон.
from utils.app_boot import _selftest, _startup, _unblock_downloaded, resource_path

import webview

from core.edit_basics import EditBasicsMixin
from core.listen_mode import ListenMixin
from utils.audio_player import AudioPlayer


class ListenApi(ListenMixin, EditBasicsMixin):
    """Всё, что окно прослушки зовёт как pywebview.api.<имя>."""

    def __init__(self):
        self.player = AudioPlayer()


if __name__ == '__main__':
    _unblock_downloaded()
    if '--selftest' in sys.argv:
        sys.exit(_selftest(page='frontend/listen_app.html', full=False))
    api = ListenApi()
    window = webview.create_window('GVox | Прослушка переменных', resource_path('frontend/listen_app.html'),
                                   js_api=api, width=1600, height=980)
    webview.start(_startup, window)
