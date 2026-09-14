import os
import re
import shutil
import openpyxl
import webview
from openpyxl.utils import get_column_letter
from utils.file_utils import FileUtils

# Символы, запрещённые в именах файлов Windows
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')

# Сколько строк показываем в превью как образец
SAMPLE_ROWS = 3


def clean_filename(text):
    """Превращает текст ячейки в безопасное имя файла."""
    name = BAD_NAME_CHARS.sub(' ', str(text)).strip()
    name = re.sub(r'\s+', ' ', name)
    name = name.rstrip('. ')
    return name[:100]


def norm_key(text):
    """Ключ для поиска повторов: регистр и лишние пробелы не важны."""
    return re.sub(r'\s+', ' ', str(text)).strip().lower()


class PhrasesMixin:
    """Модуль работы с базой фраз (Excel) и их навигацией."""

    # ==================================================================
    #  ЧТЕНИЕ ТАБЛИЦЫ: ВЫБОР ФАЙЛА, РАЗБОР КОЛОНОК, ЗАГРУЗКА
    # ==================================================================

    def pick_excel(self):
        """Шаг 1: выбор файла. Разбор идёт отдельным вызовом."""
        file_types = ('Excel files (*.xlsx)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return {"error": "cancel"}

        self.pending_excel_path = filename[0]
        return {"name": os.path.basename(filename[0])}

    def _open_pending_sheet(self):
        path = getattr(self, 'pending_excel_path', None)
        if not path or not os.path.exists(path):
            return None, None, {"error": "Файл не выбран. Нажмите «Загрузить текст (Excel)» ещё раз."}
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e:
            return None, None, {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(path)}\n\n"
                                         f"Поддерживается только формат .xlsx. Если файл в старом формате .xls, "
                                         f"пересохраните его как .xlsx.\n\nПодробности: {e}"}
        return wb, wb.active, None

    @staticmethod
    def _guess_header_row(rows):
        """Есть ли в таблице строка заголовков. 0 — значит нет, данные с первой строки.

        Сетка категорий (как в файлах с суммами) — это много колонок, и почти у
        каждой сверху подпись. Классический формат «текст + имя файла» — две
        колонки без подписей, и там первая строка это уже данные."""
        if not rows:
            return 0

        width = max(len(r) for r in rows)
        filled_cols = [c for c in range(width)
                       if any(c < len(r) and r[c] is not None and str(r[c]).strip() for r in rows)]
        if len(filled_cols) < 3:
            return 0

        first = rows[0]
        headered = sum(1 for c in filled_cols
                       if c < len(first) and first[c] is not None and str(first[c]).strip())
        return 1 if headered >= len(filled_cols) - 1 else 0

    def analyze_excel(self, header_row=None):
        """Шаг 2: смотрим, какие колонки есть в таблице, и показываем образцы."""
        wb, sheet, err = self._open_pending_sheet()
        if err:
            return err

        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return {"error": "Лист пустой."}

        # None означает «определи сам»; 0 — заголовков нет
        header_row = self._guess_header_row(rows) if header_row is None else max(0, int(header_row))

        width = max(len(r) for r in rows)
        head = rows[header_row - 1] if header_row >= 1 and len(rows) >= header_row else ()
        data_rows = rows[header_row:]

        columns = []
        for c in range(width):
            values = [r[c] for r in data_rows
                      if c < len(r) and r[c] is not None and str(r[c]).strip() != ""]
            if not values:
                continue

            header = head[c] if c < len(head) and head[c] is not None else ""
            unique = len({norm_key(v) for v in values})

            columns.append({
                "index": c,
                "letter": get_column_letter(c + 1),
                "header": str(header).strip(),
                "filled": len(values),
                "unique": unique,
                "duplicates": len(values) - unique,
                "samples": [str(v).strip()[:60] for v in values[:SAMPLE_ROWS]]
            })

        if not columns:
            return {"error": f"Ниже строки {header_row} нет ни одной заполненной ячейки. "
                             f"Проверьте номер строки с заголовками."}

        if header_row >= 1:
            # Сетка категорий: берём все колонки с подписью сверху
            grid = [c for c in columns if c["header"] and c["filled"] >= 2]
            suggested = [c["index"] for c in grid] or [columns[0]["index"]]
            naming = "cell"
        else:
            # Классический формат: текст в первой колонке, имя файла — в соседней справа
            suggested = [columns[0]["index"]]
            naming = "right" if len(columns) > 1 and columns[1]["index"] == columns[0]["index"] + 1 else "cell"

        return {
            "name": os.path.basename(self.pending_excel_path),
            "sheet": sheet.title,
            "total_rows": len(rows),
            "header_row": header_row,
            "columns": columns,
            "suggested": suggested,
            "suggested_naming": naming
        }

    def _collect_cells(self, sheet, indexes, header_row):
        """Читает ячейки в порядке: слева направо по строке, затем вниз."""
        rows = list(sheet.iter_rows(values_only=True))
        head = rows[header_row - 1] if header_row >= 1 and len(rows) >= header_row else ()
        out = []

        for r in rows[header_row:]:
            for c in indexes:
                if c >= len(r):
                    continue
                value = r[c]
                if value is None or str(value).strip() == "":
                    continue
                header = head[c] if c < len(head) and head[c] is not None else ""
                out.append({"col": c, "header": str(header).strip(),
                            "text": str(value).strip(), "row": r})
        return out

    def preview_excel_selection(self, indexes, naming, skip_dupes, header_row=0):
        """Сколько фраз получится при таких галочках — считается до загрузки."""
        wb, sheet, err = self._open_pending_sheet()
        if err:
            return err

        cells = self._collect_cells(sheet, [int(i) for i in indexes], max(0, int(header_row)))
        total = len(cells)
        unique = len({norm_key(c["text"]) for c in cells})

        return {
            "total": total,
            "unique": unique,
            "duplicates": total - unique,
            "result": unique if skip_dupes else total,
            "examples": [self._build_name(c, i, naming, sheet, header_row)
                         for i, c in enumerate(cells[:4])]
        }

    def _build_name(self, cell, order, naming, sheet=None, header_row=0):
        """Имя файла по выбранному правилу."""
        if naming == "header":
            return clean_filename(f"{cell['header']}_{order + 1:02d}") if cell['header'] \
                else f"фраза_{order + 1:04d}"
        if naming == "order":
            return f"фраза_{order + 1:04d}"
        if naming == "right":
            row = cell["row"]
            nxt = cell["col"] + 1
            if nxt < len(row) and row[nxt] is not None and str(row[nxt]).strip():
                return clean_filename(row[nxt])
            return f"фраза_{order + 1:04d}"
        return clean_filename(cell["text"])  # naming == "cell"

    def load_excel_selection(self, indexes, naming="cell", skip_dupes=True, header_row=0):
        """Шаг 3: собираем базу фраз из отмеченных колонок."""
        wb, sheet, err = self._open_pending_sheet()
        if err:
            return err

        header_row = max(0, int(header_row))
        cells = self._collect_cells(sheet, [int(i) for i in indexes], header_row)
        if not cells:
            return {"error": "В отмеченных колонках нет ни одной заполненной ячейки."}

        parsed = []
        seen = set()
        skipped = 0

        for i, cell in enumerate(cells):
            key = norm_key(cell["text"])
            if skip_dupes and key in seen:
                skipped += 1
                continue
            seen.add(key)
            parsed.append({
                "text": cell["text"],
                "filename": self._build_name(cell, len(parsed), naming, sheet, header_row),
                "category": cell["header"]
            })

        if not parsed:
            return {"error": "Не удалось собрать ни одной фразы."}

        self.excel_name = os.path.basename(self.pending_excel_path)
        self.phrases_data = parsed
        self.phrase_index = 0

        state = self.get_ui_state()
        if isinstance(state, dict):
            state["load_report"] = {"loaded": len(parsed), "skipped": skipped}
        return state

    # ==================================================================

    def load_excel(self):
        file_types = ('Excel files (*.xlsx)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return {"error": "cancel"}

        path = filename[0]

        # Раньше любая ошибка чтения таблицы просто обрывала работу без единого
        # сообщения: кнопка не подсвечивалась, а список фраз оставался пустым,
        # из-за чего следующие шаги жаловались на незагруженный Excel.
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(path)}\n\n"
                             f"Поддерживается только формат .xlsx. "
                             f"Если файл в старом формате .xls, пересохраните его как .xlsx.\n\n"
                             f"Подробности: {e}"}

        sheet = wb.active
        parsed = []
        for row in sheet.iter_rows(values_only=True):
            if not row:
                continue
            text = row[0]
            if text is None or str(text).strip() == "":
                continue
            name = row[1] if len(row) > 1 and row[1] is not None else ""
            parsed.append({"text": str(text).strip(), "filename": str(name).strip()})

        if not parsed:
            return {"error": f"В таблице {os.path.basename(path)} не нашлось ни одной фразы.\n\n"
                             f"Текст фраз должен быть в первом столбце (A), "
                             f"а имя файла — во втором (B)."}

        self.excel_name = os.path.basename(path)
        self.phrases_data = parsed
        self.phrase_index = 0
        return self.get_ui_state()

    def get_missing_phrases(self):
        """Фразы, для которых ещё нет готового файла.

        Смотрим в «Проверенные» — единственную конечную папку. Good доглядываем
        ради проектов, начатых до отказа от двойного отбора."""
        if not self.phrases_data: return []

        good_files = set()
        for folder in ('Проверенные', 'Good'):
            path = os.path.join(self.work_dir, folder) if self.work_dir else ""
            if not path or not os.path.exists(path):
                continue
            for r, d, files in os.walk(path):
                for f in files:
                    good_files.add(f.lower())

        missing = []
        for i, p in enumerate(self.phrases_data):
            expected = p["filename"] if p["filename"] else f"фраза_{i + 1:04d}"
            expected_wav = (expected if expected.lower().endswith('.wav') else f"{expected}.wav").lower()
            if expected_wav not in good_files:
                missing.append({"index": i, "text": p["text"], "filename": expected})
        return missing

    def jump_to_phrase(self, index):
        if self.phrases_data and 0 <= index < len(self.phrases_data):
            self.phrase_index = index
        return self.get_ui_state()

    def search_phrase(self, query):
        if not self.phrases_data or not query:
            return self.get_ui_state()

        query = query.lower()
        start_idx = self.phrase_index + 1

        for i in range(len(self.phrases_data)):
            idx = (start_idx + i) % len(self.phrases_data)
            text = self.phrases_data[idx]["text"].lower()
            filename = (self.phrases_data[idx]["filename"] or "").lower()

            if query in text or query in filename:
                self.phrase_index = idx
                self._sync_audacity_selection()
                break

        return self.get_ui_state()

    def navigate_phrase(self, direction):
        if not self.phrases_data:
            return self.get_ui_state()

        self.phrase_index = max(0, min(self.phrase_index + direction, len(self.phrases_data) - 1))
        return self.get_ui_state()

    def delete_current_phrase(self):
        if self.phrases_data and 0 <= self.phrase_index < len(self.phrases_data):
            self.phrases_data.pop(self.phrase_index)
            if self.phrase_index >= len(self.phrases_data):
                self.phrase_index = max(0, len(self.phrases_data) - 1)
        return self.get_ui_state()

    def toggle_phrase_checked(self):
        # НОВОВВЕДЕНИЕ: Защита. Игнорируем логику Excel, если мы в конвейере.
        if getattr(self, 'current_mode', '') == 'VarBatch':
            return self._get_var_batch_ui_state()

        if self.phrases_data and 0 <= self.phrase_index < len(self.phrases_data):
            current_status = self.phrases_data[self.phrase_index].get("checked", False)
            new_status = not current_status
            self.phrases_data[self.phrase_index]["checked"] = new_status

            if self.work_dir:
                checked_dir = os.path.join(self.work_dir, 'Проверенные')
                os.makedirs(checked_dir, exist_ok=True)

                expected = self.phrases_data[self.phrase_index]["filename"]
                if not expected:
                    expected = f"фраза_{self.phrase_index + 1:04d}"
                if not expected.lower().endswith('.wav'):
                    expected += '.wav'

                target_path = os.path.join(checked_dir, expected)

                if new_status:
                    good_path = os.path.join(self.work_dir, 'Good', expected)
                    var_path = os.path.join(self.work_dir, 'Переменные', expected)

                    source_path = good_path if os.path.exists(good_path) else (
                        var_path if os.path.exists(var_path) else None)

                    if source_path:
                        shutil.copy(source_path, target_path)
                else:
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                        except:
                            pass

        return self.get_ui_state()
