# -*- mode: python ; coding: utf-8 -*-
# Отдельная программа «Прослушка переменных» — ОДИН файл dist\GVox-Listen.exe.
# Собрать: build_listen.bat (сам поставит модули и скачает ffmpeg).
# Без распознавания речи (whisper) — прослушке он не нужен.
import os
from PyInstaller.utils.hooks import collect_all

_ffmpeg_binaries = [(f, '.') for f in ('ffmpeg.exe', 'ffprobe.exe') if os.path.exists(f)]
_missing_ffmpeg = [f for f in ('ffmpeg.exe', 'ffprobe.exe') if not os.path.exists(f)]
if _missing_ffmpeg:
    print(f"[listen.spec] ВНИМАНИЕ: не найдены рядом с main.py: {', '.join(_missing_ffmpeg)} — "
          f"соберётся без них, но нарезка/конвертация в собранном .exe может не работать. "
          f"Запустите build_listen.bat — он скачает их сам.")

# Модули с файлами, которые PyInstaller сам не видит: распознавание речи
# (faster-whisper + ctranslate2 + токенизатор + VAD-модель + декодер av),
# запись с микрофона (PortAudio), синтез (драйвер playwright).
# GVOX_NO_ASR=1 (build_exe.bat --no-asr) — облегчённая сборка без распознавания
# речи: без faster-whisper/ctranslate2/onnxruntime и без моделей.
NO_ASR = True                                       # прослушке распознавание не нужно
ASR_PKGS = ('faster_whisper', 'ctranslate2', 'tokenizers', 'onnxruntime', 'av', 'huggingface_hub')
datas, binaries, hiddenimports = [('frontend', 'frontend')], list(_ffmpeg_binaries), []
for pkg in (() if NO_ASR else ASR_PKGS) + ('sounddevice', '_sounddevice_data', 'playwright', 'webview'):
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:
        print(f"[listen.spec] {pkg}: не установлен — пропускаю ({e})")
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['listen_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'whisper'] + (list(ASR_PKGS) if NO_ASR else []),
    noarchive=False,
)
pyz = PYZ(a.pure)

# Один файл GVox-Listen.exe — удобно отправить. Моделей нет, поэтому распаковка
# во временную папку при запуске — пара секунд.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='GVox-Listen',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.exists('icon.ico') else None,
)
