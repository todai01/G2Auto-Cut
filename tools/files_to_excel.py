"""Названия файлов из папки → Excel: один столбец сверху вниз, без расширения.

    python tools/files_to_excel.py <папка> [таблица.xlsx] [--sub] [--header ИМЯ] [--suffix _ru _kz]

  папка         где лежат файлы (по умолчанию — текущая)
  таблица.xlsx  куда сохранить (по умолчанию — <имя папки>.xlsx рядом с папкой)
  --sub         брать и вложенные папки
  --header ИМЯ  первой строкой — заголовок столбца (например <mark>)
  --suffix ...  дополнительно убрать эти окончания в конце имени (например _ru _kz)

Порядок — как в проводнике: «2» раньше «10»."""
import argparse
import os
import re
import sys


def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder', nargs='?', default='.')
    ap.add_argument('out', nargs='?')
    ap.add_argument('--sub', action='store_true')
    ap.add_argument('--header')
    ap.add_argument('--suffix', nargs='*', default=[])
    a = ap.parse_args()
    folder = os.path.abspath(a.folder)
    if not os.path.isdir(folder):
        sys.exit(f'Папка не найдена: {folder}')
    names = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(('_', '.'))) if a.sub else []
        for f in files:
            if f.startswith(('.', '~$')):
                continue
            stem = os.path.splitext(f)[0]
            for suf in a.suffix:
                if suf and stem.lower().endswith(suf.lower()) and len(stem) > len(suf):
                    stem = stem[:-len(suf)]
            names.append(stem.strip())
    names = sorted((n for n in names if n), key=natural)
    if not names:
        sys.exit('В папке нет файлов.')
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    if a.header:
        ws.append([a.header])
    for n in names:
        ws.append([n])
    ws.column_dimensions['A'].width = max(14, min(60, max(len(n) for n in names) + 2))
    out = a.out or os.path.join(os.path.dirname(folder), os.path.basename(folder.rstrip('/\\')) + '.xlsx')
    wb.save(out)
    print(f'Готово: {len(names)} названий → {out}')


if __name__ == '__main__':
    main()
