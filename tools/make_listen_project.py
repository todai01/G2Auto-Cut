"""Собрать отдельный проект «Прослушка переменных» — только нужные файлы.

    python tools/make_listen_project.py [папка]      (по умолчанию dist/GVox-Listen)

Берёт из GVox файлы прослушки (core/listen_mode.py и то, от чего он зависит),
окно прослушки — куски index.html между метками <!-- @listen-app:… --> и
шаблоны из tools/listen_project/ (вход, сборка exe, README). Так отдельная
программа всегда совпадает с прослушкой в GVox."""
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'tools', 'listen_project')
FILES = [
    'core/listen_mode.py', 'core/voice_trim.py', 'core/edit_basics.py', 'core/synth_browser.py',
    'utils/audio_player.py', 'utils/wav_io.py', 'utils/ffmpeg_setup.py', 'utils/app_boot.py',
    'frontend/style.css', 'frontend/ui_base.js', 'frontend/listen.js',
]
TEMPLATES = {'listen_app.py': 'listen_app.py', 'listen.spec': 'listen.spec', 'build_listen.py': 'build_listen.py',
             'build_listen.bat': 'build_listen.bat', 'requirements.txt': 'requirements.txt', 'README.txt': 'README.txt',
             'listen_boot.js': 'frontend/listen_boot.js'}


def block(html, name):
    m = re.search(rf'[ \t]*<!-- @listen-app:{name} -->\n(.*?)[ \t]*<!-- /@listen-app:{name} -->', html, re.S)
    if not m:
        sys.exit(f'В index.html нет меток @listen-app:{name}')
    return m.group(1)


def main(out):
    if os.path.exists(out):
        shutil.rmtree(out)
    for rel in FILES:
        os.makedirs(os.path.dirname(os.path.join(out, rel)), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, rel), os.path.join(out, rel))
    for src, dst in TEMPLATES.items():
        shutil.copy2(os.path.join(TPL, src), os.path.join(out, dst))
    html = open(os.path.join(ROOT, 'frontend', 'index.html'), encoding='utf-8').read()
    screen = block(html, 'screen')
    screen = re.sub(r'\n[ \t]*<button[^\n]*openTutorial\([^\n]*</button>', '', screen)       # уроков здесь нет
    screen = screen.replace('&#8592;&nbsp; Главное меню', '&#8592;&nbsp; В начало')
    page = open(os.path.join(TPL, 'listen_app.html'), encoding='utf-8').read()
    page = (page.replace('<!--@base-->', block(html, 'base')).replace('<!--@screen-->', screen)
                .replace('<!--@phr-->', block(html, 'phr')))
    with open(os.path.join(out, 'frontend', 'listen_app.html'), 'w', encoding='utf-8') as f:
        f.write(page)
    n = sum(len(fs) for _r, _d, fs in os.walk(out))
    print(f'Готово: {out} — файлов {n}')


if __name__ == '__main__':
    main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'dist', 'GVox-Listen')))
