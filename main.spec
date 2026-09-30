# -*- mode: python ; coding: utf-8 -*-
import os
# Собирает G2Studio в один .exe-файл для раздачи коллегам — не нужен
# Python/PyCharm/git, просто двойной клик. ffmpeg.exe и ffprobe.exe везутся
# прямо внутри .exe, поэтому софт работает даже без интернета и без
# исключений в корпоративных блокировках.
#
# Как собрать (один раз, на своей машине, в PyCharm или обычной cmd):
#   1. Убедись, что ffmpeg.exe и ffprobe.exe лежат рядом с main.py
#      (как для обычного запуска).
#   2. pip install pyinstaller
#   3. pyinstaller main.spec
#   4. Готовый файл появится в dist\G2Studio.exe — вот его и раздаёшь
#      коллегам, больше ничего не нужно.

_ffmpeg_binaries = [(f, '.') for f in ('ffmpeg.exe', 'ffprobe.exe') if os.path.exists(f)]
_missing_ffmpeg = [f for f in ('ffmpeg.exe', 'ffprobe.exe') if not os.path.exists(f)]
if _missing_ffmpeg:
    print(f"[main.spec] ВНИМАНИЕ: не найдены рядом с main.py: {', '.join(_missing_ffmpeg)} — "
          f"соберётся без них, но нарезка/конвертация в собранном .exe может не работать.")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_ffmpeg_binaries,
    datas=[('frontend', 'frontend')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='G2Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico' if os.path.exists('icon.ico') else None,
)
