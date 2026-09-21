import os
import re
import shutil
import openpyxl
import webview

AUDIO_EXTS = ('.wav', '.mp3', '.ogg', '.flac')
LANG_CODES = ('ru', 'kz')
OTHER_LANG_DIR = 'Прочее'
BAD_NAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


class FilenameMatchMixin:
    """«Сопоставить названия по Excel» — отдельная утилита: в папке лежат
    аудиофайлы с укороченными именами («da_1_1»), а в Excel — список их
    полных «боевых» названий («gizat_ru_da_1_1»). Программа находит короткое
    имя как хвост полного (по границе «_», чтобы «da_1_1» не подошло под
    «xda_1_1»), переименовывает файл под полное имя и раскладывает по
    подпапкам языка — судя по отдельному слову «ru»/«kz» внутри полного
    имени. Файлы без пары или с несколькими совпадениями не трогаются
    вообще — их список показывается пользователю, чтобы проверить руками."""

    def rename_match_pick_folder(self):
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}
        root = folder[0]
        files = [f for f in os.listdir(root)
                 if os.path.isfile(os.path.join(root, f)) and f.lower().endswith(AUDIO_EXTS)]
        if not files:
            return {"error": "В этой папке не нашлось аудиофайлов (.wav/.mp3/.ogg/.flac)."}

        self.rename_match_folder = root
        return {"folder": root, "count": len(files)}

    def rename_match_pick_excel(self):
        filename = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
        if not filename:
            return {"error": "cancel"}
        path = filename[0]

        try:
            wb = openpyxl.load_workbook(path, data_only=True)
            sheet = wb.active
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(path)}\n\n"
                              f"Поддерживается только формат .xlsx. Подробности: {e}"}

        names = []
        for row in sheet.iter_rows(values_only=True):
            for cell in row:
                if cell is not None and str(cell).strip():
                    names.append(str(cell).strip())
                break  # берём первую (левую) заполненную колонку строки — список полных названий, без доп. колонок

        if not names:
            return {"error": "В таблице не нашлось ни одного названия — заполните первую колонку списком "
                              "полных имён файлов."}

        self.rename_match_excel_path = path
        self.rename_match_full_names = names
        return {"file": os.path.basename(path), "count": len(names)}

    @staticmethod
    def _rename_match_detect_lang(full_name):
        parts = re.split(r'[_\-\s]+', full_name.lower())
        for code in LANG_CODES:
            if code in parts:
                return code
        return None

    def rename_match_run(self):
        root = getattr(self, 'rename_match_folder', None)
        full_names = getattr(self, 'rename_match_full_names', None)
        if not root or not os.path.isdir(root):
            return {"error": "Сначала выберите папку с аудиофайлами."}
        if not full_names:
            return {"error": "Сначала загрузите Excel со списком полных названий."}

        files = [f for f in os.listdir(root)
                 if os.path.isfile(os.path.join(root, f)) and f.lower().endswith(AUDIO_EXTS)]
        if not files:
            return {"error": "В папке не осталось аудиофайлов — возможно, она изменилась. Выберите папку заново."}

        # Без повторов, но сохраняя порядок — если одно и то же полное имя
        # написано в Excel дважды, это не «два разных совпадения».
        # В Excel название иногда пишут вместе с расширением
        # («gizat_ru_da_1_1.wav») — убираем его перед поиском, иначе
        # совпадение с da_1_1 не находится (в конце-то «.wav», а не сам
        # ярус). Расширение самого сохранённого файла отдельно — оно всегда
        # от исходного аудио, не от текста в Excel.
        unique_full = list(dict.fromkeys(re.sub(r'\.wav$', '', n, flags=re.IGNORECASE) for n in full_names))

        renamed, unmatched, ambiguous = [], [], []
        claimed = {}  # полное имя -> какой короткий файл уже его занял

        for fname in files:
            short, ext = os.path.splitext(fname)
            pattern = re.compile(r'(^|_)' + re.escape(short) + r'$', re.IGNORECASE)
            matches = [full for full in unique_full if pattern.search(full)]

            if not matches:
                unmatched.append(fname)
                continue
            if len(matches) > 1:
                ambiguous.append({"file": fname, "reason": f"нашлось {len(matches)} совпадений в Excel",
                                   "matches": matches})
                continue

            full = matches[0]
            if full in claimed:
                ambiguous.append({"file": fname,
                                   "reason": f"это же полное имя уже занял файл «{claimed[full]}»",
                                   "matches": [full]})
                continue

            lang = self._rename_match_detect_lang(full) or OTHER_LANG_DIR
            safe_full = BAD_NAME_CHARS.sub(' ', full).strip()
            target_dir = os.path.join(root, lang)
            target_path = os.path.join(target_dir, safe_full + ext)

            if os.path.exists(target_path):
                ambiguous.append({"file": fname,
                                   "reason": "файл с таким итоговым именем уже есть в папке назначения",
                                   "matches": [full]})
                continue

            os.makedirs(target_dir, exist_ok=True)
            shutil.move(os.path.join(root, fname), target_path)
            claimed[full] = fname
            renamed.append({"from": fname, "to": f"{lang}/{safe_full}{ext}"})

        return {
            "status": "ok",
            "renamed": renamed, "unmatched": unmatched, "ambiguous": ambiguous,
            "renamed_count": len(renamed), "unmatched_count": len(unmatched), "ambiguous_count": len(ambiguous),
        }
