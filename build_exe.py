"""Сборка GVox «всё включено» одной командой (см. build_exe.bat).

1. Ставит модули (requirements.txt + pyinstaller + huggingface_hub).
2. Скачивает ffmpeg.exe / ffprobe.exe, если их нет рядом с main.py.
3. Скачивает модели распознавания: whisper-model (RU, ~0,5 ГБ) и
   whisper-model-kz (KZ, ~1,6 ГБ; пропустить — ключ --no-kz). Уже лежащие
   рядом с main.py папки моделей не качаются заново.
4. Собирает dist\\GVox\\ (pyinstaller main.spec) и кладёт модели рядом с GVox.exe.
5. Запускает самопроверку (GVox.exe --selftest) — отчёт в GVox_проверка.txt.

Ключи: --no-kz — без казахской модели, --zip — ещё и dist\\GVox.zip.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = [('whisper-model', 'Systran/faster-whisper-small'),
          ('whisper-model-kz', 'mobiuslabsgmbh/faster-whisper-large-v3-turbo')]
MODEL_FILES = ['config.json', 'model.bin', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json']


def step(text):
    print('\n' + '=' * 70 + '\n' + text + '\n' + '=' * 70, flush=True)


def run(cmd):
    print('>', ' '.join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=HERE)


def is_model(path):
    return os.path.isfile(os.path.join(path, 'model.bin')) and os.path.isfile(os.path.join(path, 'config.json'))


def main():
    no_kz = '--no-kz' in sys.argv
    os.chdir(HERE)

    step('1/5  Модули Python')
    run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'])
    run([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', 'pyinstaller', 'huggingface_hub'])

    step('2/5  ffmpeg')
    sys.path.insert(0, HERE)
    from utils.ffmpeg_setup import ensure_ffmpeg
    if not ensure_ffmpeg(HERE, on_progress=lambda p, t: print(f'\r  {t}', end='', flush=True)):
        sys.exit('\nНе удалось скачать ffmpeg. Положите ffmpeg.exe и ffprobe.exe рядом с main.py и запустите снова.')
    print('\n  ffmpeg.exe и ffprobe.exe на месте')

    step('3/5  Модели распознавания речи')
    from huggingface_hub import snapshot_download
    for folder, repo in MODELS:
        if no_kz and folder.endswith('-kz'):
            print(f'  {folder}: пропускаю (--no-kz)')
            continue
        dst = os.path.join(HERE, folder)
        if is_model(dst):
            print(f'  {folder}: уже есть')
            continue
        print(f'  {folder}: скачиваю {repo} (один раз)…', flush=True)
        snapshot_download(repo_id=repo, local_dir=dst, allow_patterns=MODEL_FILES)
        if not is_model(dst):
            sys.exit(f'Модель {repo} не скачалась. Скачайте файлы {", ".join(MODEL_FILES[:4])} '
                     f'со страницы huggingface.co/{repo} в папку {dst} и запустите снова.')

    step('4/5  Сборка (pyinstaller)')
    run([sys.executable, '-m', 'PyInstaller', 'main.spec', '--noconfirm', '--clean'])
    out = os.path.join(HERE, 'dist', 'GVox')
    for folder, _repo in MODELS:
        src = os.path.join(HERE, folder)
        if is_model(src):
            dst = os.path.join(out, folder)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.cache', '.huggingface'))
            print(f'  {folder} → dist\\GVox\\{folder}')

    # .NET (окно программы) не грузит DLL из «интернетной» папки, даже если
    # метку Zone.Identifier где-то не сняли, — разрешаем явно.
    with open(os.path.join(out, 'GVox.exe.config'), 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<configuration>\n  <runtime>\n'
                '    <loadFromRemoteSources enabled="true"/>\n  </runtime>\n</configuration>\n')

    step('5/5  Самопроверка собранной программы')
    exe = os.path.join(out, 'GVox.exe' if os.name == 'nt' else 'GVox')
    code = subprocess.call([exe, '--selftest'], cwd=out)
    report = os.path.join(out, 'GVox_проверка.txt')
    if os.path.exists(report):
        print(open(report, encoding='utf-8').read())
    if '--zip' in sys.argv:
        print('  упаковываю dist\\GVox.zip…', flush=True)
        shutil.make_archive(os.path.join(HERE, 'dist', 'GVox'), 'zip', os.path.join(HERE, 'dist'), 'GVox')
    print('\nГотово: папка dist\\GVox — раздавайте её целиком, запуск — GVox.exe.'
          + ('' if code == 0 else '\nВНИМАНИЕ: самопроверка нашла проблемы (см. выше).'))
    return code


if __name__ == '__main__':
    sys.exit(main())
