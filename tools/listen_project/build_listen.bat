@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM Сборка «Прослушки переменных»: dist\GVox-Listen.exe (один файл)
python build_listen.py %*
pause
