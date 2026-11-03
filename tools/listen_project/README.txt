GVox · Прослушка переменных — отдельный проект (только этот режим)

ЗАПУСК В PYCHARM
1. File → Open → эта папка.
2. Интерпретатор: Python 3.11 (Settings → Project → Python Interpreter → Add → Virtualenv).
3. В Terminal PyCharm:
       pip install -r requirements.txt pyinstaller
4. Проверка: правой кнопкой по listen_app.py → Run 'listen_app'.
   При первом запуске рядом скачаются ffmpeg.exe и ffprobe.exe (нужен интернет),
   либо положите их рядом с listen_app.py сами.

СБОРКА EXE (один файл)
   В Terminal PyCharm:  python build_listen.py
   Результат: dist\GVox-Listen.exe — его и отправляйте (можно переименовать).
   Вручную (ffmpeg.exe и ffprobe.exe уже рядом):  pyinstaller listen.spec --noconfirm --clean

ЧТО ВНУТРИ
   listen_app.py               — вход программы
   core/listen_mode.py         — прослушка: папки, таблица, правка, сохранение, синтез
   core/voice_trim.py          — автосрезка по голосу (вдох, шум по краям)
   core/edit_basics.py         — исходник «до правок», волна, громкость
   core/synth_browser.py       — синтез через сервис в браузере (Edge / Chrome)
   utils/                      — проигрыватель, WAV, ffmpeg, запуск окна
   frontend/listen_app.html    — окно; listen.js — прослушка; ui_base.js — окна и уведомления;
                                 listen_boot.js — стартовый экран; style.css — оформление

СИНТЕЗ
   При первом синтезе программа спросит, каким голосом синтезировать — список берётся
   с сервиса синтеза. Поменять голос — кнопка «голос: … ✎» в строке синтеза.
   Адрес сервиса — SYNTH_URL в core/synth_browser.py.
