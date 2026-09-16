# -*- mode: python ; coding: utf-8 -*-
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

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('ffmpeg.exe', '.'), ('ffprobe.exe', '.')],
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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
