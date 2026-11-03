"""Сборка отдельной программы «Прослушка переменных» одним файлом (см. build_listen.bat).

1. Ставит модули (requirements.txt без распознавания речи + pyinstaller).
2. Скачивает ffmpeg.exe / ffprobe.exe, если их нет рядом с main.py.
3. Собирает dist\\GVox-Listen.exe (pyinstaller listen.spec).
4. Самопроверка (GVox-Listen.exe --selftest) — отчёт в dist\\GVox_проверка.txt.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def step(text):
    print('\n' + '=' * 70 + '\n' + text + '\n' + '=' * 70, flush=True)


def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=HERE)


def main():
    os.chdir(HERE)
    step('1/4  Модули Python (без распознавания речи)')
    run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
    reqs = [l.strip() for l in open(os.path.join(HERE, 'requirements.txt'), encoding='utf-8')
            if l.strip() and not l.lstrip().startswith('#') and not l.strip().lower().startswith('faster-whisper')]
    run([sys.executable, '-m', 'pip', 'install', *reqs, 'pyinstaller'])

    step('2/4  ffmpeg')
    sys.path.insert(0, HERE)
    from utils.ffmpeg_setup import ensure_ffmpeg
    if not ensure_ffmpeg(HERE, on_progress=lambda p, t: print(f'\r  {t}', end='', flush=True)):
        sys.exit('\nНе удалось скачать ffmpeg. Положите ffmpeg.exe и ffprobe.exe рядом с main.py и запустите снова.')

    step('3/4  Сборка одним файлом (pyinstaller listen.spec)')
    run([sys.executable, '-m', 'PyInstaller', 'listen.spec', '--noconfirm', '--clean'])

    step('4/4  Самопроверка')
    out = os.path.join(HERE, 'dist')
    exe = os.path.join(out, 'GVox-Listen.exe' if os.name == 'nt' else 'GVox-Listen')
    code = subprocess.call([exe, '--selftest'], cwd=out)
    report = os.path.join(out, 'GVox_проверка.txt')
    if os.path.exists(report):
        print(open(report, encoding='utf-8').read())
        os.remove(report)
    print('\nГотово: dist\\GVox-Listen.exe — один файл, его и отправляйте.'
          + ('' if code == 0 else '\nВНИМАНИЕ: самопроверка нашла проблемы (см. выше).'))
    return code


if __name__ == '__main__':
    sys.exit(main())
