"""GVox · Прослушка переменных — отдельная программа: только этот режим.

Тот же код и интерфейс, что у GVox, но окно открывается сразу на «Прослушке»
(frontend/listen_app.html → index.html?app=listen): без меню, студии и утилит.
Сборка одним .exe — build_listen.bat (listen.spec), без распознавания речи."""
import sys

import webview

from main import Api, _selftest, _startup, _unblock_downloaded, resource_path

if __name__ == '__main__':
    _unblock_downloaded()
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    api = Api()
    window = webview.create_window('GVox | Прослушка переменных', resource_path('frontend/listen_app.html'),
                                   js_api=api, width=1600, height=980)
    webview.start(_startup, window)
