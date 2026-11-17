"""Переименовать аудиофайлы 1, 2, 3 … n по таблице Excel: содержимое 1-й ячейки → файл «1», 2-й → «2» и т. д.

Запуск без параметров — спросит Excel-файл и папку с аудио окнами выбора, покажет, что во что превратится,
и переименует только после вашего «да»:

    python rename_by_excel.py

Параметры (все необязательные):
    --excel  таблица.xlsx     какой Excel взять
    --folder папка            где лежат аудиофайлы
    --column A                столбец с названиями (по умолчанию A; можно номер: 1)
    --sheet  Лист1            лист (по умолчанию — первый)
    --header                  первая строка — заголовок, её пропустить (если шапка вида <mark> — пропускается сама)
    --dry-run                 только показать, ничего не менять
    --yes                     не спрашивать подтверждения
    --undo                    вернуть прежние названия (по записи _отмена_переименования.json в папке)

Что делает с названиями: убирает символы, которые Windows не разрешает в имени файла (\\ / : * ? " < > |),
одинаковые названия различает « (2)», « (3)». Расширение файла (.wav, .mp3 …) остаётся. Пустая ячейка — файл не трогается.
Ничего не перезаписывает: если такое имя уже занято чужим файлом, этот файл пропускается и об этом сказано.
Перед переименованием записывает, что во что, — чтобы можно было вернуть командой --undo.
"""
import argparse
import json
import os
import re
import sys

AUDIO = ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.wma', '.opus')
UNDO_FILE = '_отмена_переименования.json'
BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
MAX_LEN = 150


def clean_name(text):
    """Текст ячейки → безопасное имя файла (без расширения). Пустая строка — нельзя использовать."""
    if text is None:
        return ''
    if isinstance(text, float) and text.is_integer():
        text = int(text)                                  # 5.0 из Excel → «5»
    s = BAD.sub('_', str(text)).strip().strip('.').strip()
    s = re.sub(r'\s+', ' ', s)
    if s.upper() in RESERVED:
        s = '_' + s
    return s[:MAX_LEN].rstrip('. ')


def read_names(path, column='A', sheet=None, header=False):
    """Столбец Excel → список ячеек сверху вниз (None — пустая). Возвращает (список, пропущенная_шапка)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    col = int(column) if str(column).isdigit() else openpyxl.utils.column_index_from_string(str(column).upper())
    vals = [r[0] if r else None for r in ws.iter_rows(min_col=col, max_col=col, values_only=True)]
    wb.close()
    while vals and (vals[-1] is None or str(vals[-1]).strip() == ''):
        vals.pop()                                        # пустой хвост таблицы не нужен
    skipped = None
    if vals and (header or re.fullmatch(r'<.*>', str(vals[0]).strip())):
        skipped = vals.pop(0)
    return vals, skipped


def numbered_files(folder):
    """{номер: имя файла} для файлов, где имя без расширения — целое число (1.wav, 02.mp3 …)."""
    out, dup = {}, []
    for f in os.listdir(folder):
        stem, ext = os.path.splitext(f)
        if ext.lower() in AUDIO and stem.isdigit() and os.path.isfile(os.path.join(folder, f)):
            n = int(stem)
            if n in out:
                dup.append(f)                             # «1.wav» и «01.wav» одновременно — неоднозначно
            else:
                out[n] = f
    return out, dup


def build_plan(folder, cells):
    """Что во что переименовать. Возвращает (план, предупреждения): план — [(старое, новое)] по номерам."""
    files, dup = numbered_files(folder)
    warns = [f'«{f}»: файл с таким же номером уже есть — пропускаю' for f in dup]
    plan, used = [], set()
    present = {f.lower() for f in os.listdir(folder)}
    for n in sorted(files):
        src = files[n]
        if n > len(cells):
            warns.append(f'«{src}»: в таблице нет строки №{n} — не трогаю')
            continue
        base = clean_name(cells[n - 1])
        if not base:
            warns.append(f'«{src}»: ячейка №{n} пустая — не трогаю')
            continue
        ext = os.path.splitext(src)[1]
        name, k = base + ext, 2
        while name.lower() in used:                       # одинаковый текст в двух ячейках
            name, k = f'{base} ({k}){ext}', k + 1
        if name.lower() != src.lower() and name.lower() in present and name.lower() not in {files[m].lower() for m in files}:
            warns.append(f'«{src}» → «{name}»: такое имя уже занято другим файлом — пропускаю')
            continue
        used.add(name.lower())
        plan.append((src, name))
    for n in range(1, len(cells) + 1):
        if n not in files and clean_name(cells[n - 1]):
            warns.append(f'строка №{n} («{clean_name(cells[n - 1])}»): файла «{n}» нет в папке')
    return plan, warns


def rename_batch(folder, pairs):
    """Переименовать [(старое, новое)] через временные имена (обмены вроде 1→2, 2→1 не затирают друг друга).
    Сбой на любом шаге — всё возвращается как было. Возвращает список реально сделанных пар."""
    todo = [(a, b) for a, b in pairs if a != b]
    done, tmp = [], []
    try:
        for i, (a, b) in enumerate(todo):
            t = f'~tmp{os.getpid()}_{i}{os.path.splitext(a)[1]}'
            os.replace(os.path.join(folder, a), os.path.join(folder, t))
            tmp.append((a, t, b))
        for a, t, b in tmp:
            if os.path.exists(os.path.join(folder, b)):
                raise OSError(f'«{b}» уже существует')
            os.replace(os.path.join(folder, t), os.path.join(folder, b))
            done.append((a, b))
    except OSError as e:
        for a, b in reversed(done):
            os.replace(os.path.join(folder, b), os.path.join(folder, a))
        for a, t, b in tmp:
            if os.path.exists(os.path.join(folder, t)):
                os.replace(os.path.join(folder, t), os.path.join(folder, a))
        raise RuntimeError(f'Не удалось переименовать: {e}. Всё возвращено как было.')
    return done


def apply_plan(folder, plan):
    """Переименовать по плану и записать в папку, что во что, — для --undo."""
    done = rename_batch(folder, plan)
    if done:
        path = os.path.join(folder, UNDO_FILE)
        try:
            old = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else []
        except (OSError, ValueError):
            old = []
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(old + [{"from": a, "to": b} for a, b in done], f, ensure_ascii=False, indent=1)
    return len(done)


def undo(folder):
    """Вернуть прежние названия по записи в папке. Файлы, которых уже нет под новым именем, пропускаются."""
    path = os.path.join(folder, UNDO_FILE)
    if not os.path.exists(path):
        raise RuntimeError('В этой папке нет записи о переименовании.')
    items = json.load(open(path, encoding='utf-8'))
    back = [(i["to"], i["from"]) for i in reversed(items) if os.path.exists(os.path.join(folder, i["to"]))]
    n = len(rename_batch(folder, back)) if back else 0
    os.remove(path)
    return n


# ---------------- интерфейс ----------------
def ask_path(kind, title, filetypes=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        p = filedialog.askopenfilename(title=title, filetypes=filetypes) if kind == 'file' else filedialog.askdirectory(title=title)
        root.destroy()
        return p or None
    except Exception:
        return input(f'{title}: ').strip().strip('"') or None


def show(plan, warns, limit=20):
    print(f'\nБудет переименовано: {sum(1 for a, b in plan if a != b)} из {len(plan)}')
    for a, b in plan[:limit]:
        print(f'  {a:>12}  →  {b}')
    if len(plan) > limit:
        print(f'  … и ещё {len(plan) - limit}')
    if warns:
        print(f'\nПредупреждения ({len(warns)}):')
        for w in warns[:30]:
            print('  •', w)
        if len(warns) > 30:
            print(f'  … и ещё {len(warns) - 30}')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--excel')
    ap.add_argument('--folder')
    ap.add_argument('--column', default='A')
    ap.add_argument('--sheet')
    ap.add_argument('--header', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--undo', action='store_true')
    a = ap.parse_args(argv)

    folder = a.folder or ask_path('dir', 'Папка с аудиофайлами 1, 2, 3 …')
    if not folder or not os.path.isdir(folder):
        sys.exit('Папка не выбрана.')
    if a.undo:
        print(f'Возвращено прежних названий: {undo(folder)}')
        return 0
    excel = a.excel or ask_path('file', 'Excel-файл с названиями', [('Excel', '*.xlsx *.xlsm'), ('Все файлы', '*.*')])
    if not excel or not os.path.isfile(excel):
        sys.exit('Excel-файл не выбран.')
    cells, skipped = read_names(excel, a.column, a.sheet, a.header)
    if skipped is not None:
        print(f'Первая строка («{skipped}») — заголовок, пропускаю.')
    if not cells:
        sys.exit('В выбранном столбце таблицы нет названий.')
    plan, warns = build_plan(folder, cells)
    show(plan, warns)
    if not plan:
        sys.exit('\nНечего переименовывать.')
    if a.dry_run:
        print('\n(Режим просмотра — ничего не изменено.)')
        return 0
    if not a.yes and input('\nПереименовать? (да / нет): ').strip().lower() not in ('да', 'д', 'y', 'yes'):
        print('Отменено, ничего не изменено.')
        return 0
    n = apply_plan(folder, plan)
    print(f'\nГотово: переименовано {n}. Вернуть как было: python rename_by_excel.py --undo --folder "{folder}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
