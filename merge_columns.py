import os
import pandas as pd

# Спрашиваем у пользователя файл (кавычки при перетаскивании файла убираем)
src = input("Введите путь к Excel-файлу: ").strip().strip('"').strip("'")
if not os.path.isfile(src):
    raise SystemExit(f"Файл не найден: {src}")

base, ext = os.path.splitext(src)
dst = f"{base}_merged.xlsx"

df = pd.read_excel(src, header=None, dtype=str)

# Объединяем 1-й и 2-й столбцы: "AUDI E-TRON SPORTBACK"
merged = (df[0].fillna("").str.strip() + " " + df[1].fillna("").str.strip()).str.strip()

# Убираем пустые и дубли, сохраняя порядок
merged = merged[merged != ""].drop_duplicates()

merged.to_frame().to_excel(dst, header=False, index=False)
print(f"Готово: {len(merged)} уникальных строк -> {dst}")
