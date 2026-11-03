# -*- mode: python ; coding: utf-8 -*-
# «Прослушка переменных» — ОДИН файл dist\GVox-Listen.exe.
# Собрать: build_listen.bat (сам поставит модули и скачает ffmpeg) или
#     pyinstaller listen.spec --noconfirm --clean   (ffmpeg.exe и ffprobe.exe — рядом с listen_app.py)
import os
from PyInstaller.utils.hooks import collect_all

binaries = [(f, '.') for f in ('ffmpeg.exe', 'ffprobe.exe') if os.path.exists(f)]
missing = [f for f in ('ffmpeg.exe', 'ffprobe.exe') if not os.path.exists(f)]
if missing:
    print(f"[listen.spec] ВНИМАНИЕ: нет рядом с listen_app.py: {', '.join(missing)} — "
          f"запустите build_listen.bat, он скачает их сам.")

# Файлы, которые PyInstaller сам не видит: окно (pywebview) и драйвер синтеза (playwright).
datas, hiddenimports = [('frontend', 'frontend')], []
for pkg in ('webview', 'playwright'):
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
    excludes=['tkinter', 'matplotlib', 'IPython', 'pytest', 'faster_whisper', 'ctranslate2', 'onnxruntime'],
    noarchive=False,
)
pyz = PYZ(a.pure)

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
