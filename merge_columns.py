import sys
import pandas as pd

# Использование: python merge_columns.py input.xlsx [output.xlsx]
src = sys.argv[1] if len(sys.argv) > 1 else "input.xlsx"
dst = sys.argv[2] if len(sys.argv) > 2 else "output.xlsx"

df = pd.read_excel(src, header=None, dtype=str)

# Объединяем 1-й и 2-й столбцы: "AUDI E-TRON SPORTBACK"
merged = (df[0].fillna("").str.strip() + " " + df[1].fillna("").str.strip()).str.strip()

# Убираем пустые и дубли, сохраняя порядок
merged = merged[merged != ""].drop_duplicates()

merged.to_frame().to_excel(dst, header=False, index=False)
print(f"Готово: {len(merged)} уникальных строк -> {dst}")
