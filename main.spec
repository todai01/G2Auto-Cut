# -*- mode: python ; coding: utf-8 -*-
# Сборка GVox «всё включено» — коллегам ничего не нужно доустанавливать.
#
# Проще всего — одной командой (в папке проекта, в обычной cmd):
#     build_exe.bat
# Она сама поставит модули, скачает ffmpeg и модели распознавания и соберёт.
#
# Результат — ПАПКА dist\GVox\ (не один файл): внутри GVox.exe, служебная
# _internal\ и модели whisper-model\ (+ whisper-model-kz\). Раздаётся папка
# целиком (или zip). Одним файлом не собираем: модели весят сотни мегабайт,
# и одиночный .exe распаковывал бы их во временную папку при каждом запуске.
#
# Вручную: pyinstaller main.spec --noconfirm --clean  (модели потом
# положить рядом с dist\GVox\GVox.exe — это делает build_exe.py).
import os
from PyInstaller.utils.hooks import collect_all

_ffmpeg_binaries = [(f, '.') for f in ('ffmpeg.exe', 'ffprobe.exe') if os.path.exists(f)]
_missing_ffmpeg = [f for f in ('ffmpeg.exe', 'ffprobe.exe') if not os.path.exists(f)]
if _missing_ffmpeg:
    print(f"[main.spec] ВНИМАНИЕ: не найдены рядом с main.py: {', '.join(_missing_ffmpeg)} — "
          f"соберётся без них, но нарезка/конвертация в собранном .exe может не работать. "
          f"Запустите build_exe.bat — он скачает их сам.")

# Модули с файлами, которые PyInstaller сам не видит: распознавание речи
# (faster-whisper + ctranslate2 + токенизатор + VAD-модель + декодер av),
# запись с микрофона (PortAudio), синтез (драйвер playwright).
datas, binaries, hiddenimports = [('frontend', 'frontend')], list(_ffmpeg_binaries), []
for pkg in ('faster_whisper', 'ctranslate2', 'tokenizers', 'onnxruntime', 'av',
            'sounddevice', '_sounddevice_data', 'playwright', 'webview', 'pptx'):
    try:
        d, b, h = collect_all(pkg)
    except Exception as e:
        print(f"[main.spec] {pkg}: не установлен — пропускаю ({e})")
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GVox',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.exists('icon.ico') else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GVox',
)
