import os
import shutil
import openpyxl
import webview
from utils.file_utils import FileUtils


class PhrasesMixin:
    """Модуль работы с базой фраз (Excel) и их навигацией."""

    def load_excel(self):
        file_types = ('Excel files (*.xlsx)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return self.get_ui_state()

        self.excel_name = os.path.basename(filename[0])
        wb = openpyxl.load_workbook(filename[0])
        sheet = wb.active

        self.phrases_data = [{"text": str(row[0]), "filename": str(row[1]) if len(row) > 1 and row[1] else ""} for row
                             in sheet.iter_rows(values_only=True) if row[0]]
        self.phrase_index = 0
        return self.get_ui_state()

    def get_missing_phrases(self):
        if not self.phrases_data: return []
        good_dir = os.path.join(self.work_dir, 'Good') if self.work_dir else ""
        good_files = set()

        if os.path.exists(good_dir):
            for r, d, files in os.walk(good_dir):
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
                    good_path = FileUtils.get_sorted_path(os.path.join(self.work_dir, 'Good'), expected)
                    var_path = FileUtils.get_sorted_path(os.path.join(self.work_dir, 'Переменные'), expected)

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
