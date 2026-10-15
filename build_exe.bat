@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Сборка GVox «всё включено». Ключи: --no-kz (без казахской модели), --zip (ещё и архив)
python build_exe.py %*
pause
