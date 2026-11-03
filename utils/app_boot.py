"""Запуск окна программы: ffmpeg рядом, без мигающих консолей на Windows,
файлы из скачанного архива, самопроверка (--selftest). Общее для GVox
(main.py) и отдельной «Прослушки» (listen_app.py)."""
import os
import subprocess
import sys

from pydub import AudioSegment

from utils.ffmpeg_setup import ensure_ffmpeg

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # папка программы (где main.py)


def _no_console_windows():
    """Windows: служебные консольные программы (ffmpeg/ffprobe — их зовёт
    pydub при каждом экспорте и прослушке, драйвер синтеза и т.п.) не
    показывают чёрное окно на долю секунды. Флаг CREATE_NO_WINDOW ставится
    всем запускам, где вызывающий сам флагов не задал; на окна обычных
    программ (Audacity) он не влияет — касается только консольных."""
    if os.name != 'nt' or getattr(subprocess.Popen.__init__, '_gvox_nowin', False):
        return
    orig = subprocess.Popen.__init__

    def init(self, *args, **kwargs):
        if len(args) < 13 and not kwargs.get('creationflags'):
            kwargs['creationflags'] = 0x08000000          # CREATE_NO_WINDOW
        orig(self, *args, **kwargs)
    init._gvox_nowin = True
    subprocess.Popen.__init__ = init


_no_console_windows()


def resource_path(relative_path):
    """
    Помогает .exe файлу найти папку frontend во временной директории Windows.
    Без этой функции будет белый экран.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _startup(window):
    """Выполняется уже после того, как окно поднялось — можно показывать
    прогресс через тот же progressContainer, что и вырезка/конвертация.

    Собранный .exe (PyInstaller) везёт ffmpeg.exe/ffprobe.exe прямо внутри
    себя — скачивать тут нечего, коллеги без интернета/за блокировками
    получают рабочий софт из коробки. Автоскачивание нужно только когда
    запускают main.py напрямую (не из собранного .exe) и файлов рядом ещё
    нет — например, на компьютере разработчика при первой настройке."""
    if getattr(sys, 'frozen', False):
        AudioSegment.converter = resource_path("ffmpeg.exe")
        AudioSegment.ffprobe = resource_path("ffprobe.exe")
        _ffmpeg_on_path(resource_path(""))
        return

    def report(percent, text):
        try:
            window.evaluate_js(
                f"document.getElementById('progressContainer').style.display='block';"
                f"updateProgress({percent}, {text!r});"
            )
        except Exception:
            pass

    ok = ensure_ffmpeg(APP_DIR, on_progress=report)

    try:
        window.evaluate_js("document.getElementById('progressContainer').style.display='none';")
    except Exception:
        pass

    if not ok:
        try:
            window.evaluate_js(
                "showBeautifulAlert('⚠️ <b>Не удалось скачать ffmpeg автоматически</b>"
                "<br><br>Проверьте интернет-соединение или положите ffmpeg.exe и "
                "ffprobe.exe в папку программы вручную (рядом с main.py) и перезапустите.');"
            )
        except Exception:
            pass

    AudioSegment.converter = os.path.join(APP_DIR, "ffmpeg.exe")
    AudioSegment.ffprobe = os.path.join(APP_DIR, "ffprobe.exe")
    _ffmpeg_on_path(APP_DIR)


def _unblock_downloaded():
    """Скачанный из интернета zip Windows помечает (Zone.Identifier), и
    после распаковки метка у каждого файла. .NET (окно программы —
    pythonnet) такие DLL не грузит: «Failed to resolve
    Python.Runtime.Loader.Initialize». Снимаем метку со своих файлов сами —
    один раз, пока она есть."""
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        return
    base = resource_path("")
    probe = os.path.join(base, 'pythonnet', 'runtime', 'Python.Runtime.dll')
    if not os.path.exists(probe + ':Zone.Identifier'):
        return
    for root in (base, os.path.dirname(sys.executable)):
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(('.dll', '.pyd', '.exe', '.config')):
                    try:
                        os.remove(os.path.join(dirpath, f) + ':Zone.Identifier')
                    except OSError:
                        pass


def _ffmpeg_on_path(folder):
    """pydub ищет ffprobe (а местами и ffmpeg) по PATH, а не по своим
    настройкам, — папку с ними ставим первой в PATH этого процесса."""
    folder = os.path.abspath(folder)
    if folder not in os.environ.get('PATH', '').split(os.pathsep):
        os.environ['PATH'] = folder + os.pathsep + os.environ.get('PATH', '')


def _selftest(page='frontend/index.html', full=True):
    """GVox.exe --selftest: проверить, что всё нужное на месте, — без окна.
    Отчёт — в «GVox_проверка.txt» рядом с программой (и в консоль)."""
    import subprocess
    import traceback
    frozen = getattr(sys, 'frozen', False)
    base = os.path.dirname(sys.executable) if frozen else APP_DIR
    ff_dir = resource_path("") if frozen else APP_DIR
    _ffmpeg_on_path(ff_dir)
    lines, ok_all = [], True

    def check(name, fn):
        nonlocal ok_all
        try:
            info = fn()
            lines.append(f"[OK]   {name}{': ' + info if info else ''}")
        except Exception as e:
            ok_all = False
            lines.append(f"[FAIL] {name}: {e}")
            lines.append('       ' + traceback.format_exc().strip().splitlines()[-1])

    def ff(exe):
        path = os.path.join(ff_dir, exe + ('.exe' if os.name == 'nt' else ''))
        if not os.path.exists(path):
            path = exe
        out = subprocess.run([path, '-version'], capture_output=True, text=True, timeout=20).stdout
        return out.splitlines()[0] if out else '?'
    check("ffmpeg", lambda: ff('ffmpeg'))
    check("ffprobe", lambda: ff('ffprobe'))
    check("интерфейс (frontend)", lambda: '' if os.path.exists(resource_path(page)) else 1 / 0)
    for mod in ('numpy', 'pydub', 'openpyxl', 'webview') + (('pptx',) if full else ()):
        check(f"модуль {mod}", lambda m=mod: __import__(m) and '')
    if full:
        check("запись с микрофона (sounddevice)",
              lambda: f"устройств ввода: {sum(1 for d in __import__('sounddevice').query_devices() if d['max_input_channels'] > 0)}")

    def asr(dirname):
        from faster_whisper import WhisperModel
        import numpy as np
        path = os.path.join(base, dirname)
        if not os.path.isfile(os.path.join(path, 'model.bin')):
            raise RuntimeError(f"нет папки модели «{path}»")
        m = WhisperModel(path, device='cpu', compute_type='int8', cpu_threads=2)
        segs, _ = m.transcribe(np.zeros(16000, dtype=np.float32), language='ru')
        list(segs)
        return path
    if os.name == 'nt':
        check("окно программы (.NET / pythonnet)", lambda: __import__('clr') and '')
        check("ffmpeg и др. — без всплывающих окон консоли",
              lambda: '' if getattr(subprocess.Popen.__init__, '_gvox_nowin', False) else 1 / 0)
    try:
        __import__('faster_whisper')
        has_asr = True
    except ImportError:
        has_asr = False
    if not full:
        pass                                                  # «Прослушке» распознавание не нужно
    elif not has_asr and frozen and not os.path.isdir(os.path.join(base, 'whisper-model')):
        lines.append("[--]   распознавание речи: не входит в эту сборку (облегчённая, без whisper) — "
                     "запись в режиме «Без распознавания»")
    else:
        check("модуль распознавания (faster-whisper, ctranslate2, VAD)",
              lambda: __import__('faster_whisper') and __import__('ctranslate2') and __import__('onnxruntime') and '')
        check("распознавание речи RU (whisper-model)", lambda: asr('whisper-model'))
    if full and has_asr and os.path.isdir(os.path.join(base, 'whisper-model-kz')):
        check("распознавание речи KZ (whisper-model-kz)", lambda: asr('whisper-model-kz'))

    def pw():
        from playwright._impl._driver import compute_driver_executable
        drv = compute_driver_executable()
        drv = drv[0] if isinstance(drv, tuple) else drv
        if not os.path.exists(drv):
            raise RuntimeError(f"нет драйвера {drv}")
        return "драйвер на месте (браузер — установленный Edge/Chrome)"
    check("синтез (playwright)", pw)
    report = "Проверка GVox\n" + "\n".join(lines) + ("\n\nВсё готово к работе." if ok_all else "\n\nЕсть проблемы — см. [FAIL].")
    try:
        with open(os.path.join(base, 'GVox_проверка.txt'), 'w', encoding='utf-8') as f:
            f.write(report)
    except OSError:
        pass
    try:
        print(report)
    except Exception:
        pass
    return 0 if ok_all else 1
