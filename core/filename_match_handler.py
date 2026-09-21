import os
import re
import shutil
import openpyxl
import webview
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

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

    def rename_match_run(self, langs=None):
        """langs — список языков, которым ограничить поиск («ru», «kz»)
        или пусто/None — без ограничения (как раньше). Строки из Excel не
        из выбранного языка (или без метки языка вовсе) в пул кандидатов
        не попадают, будто их в таблице нет — так файл, у которого
        «настоящее» совпадение другого языка, просто не найдётся, а не
        подхватится по ошибке."""
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
        unique_full_all = list(dict.fromkeys(re.sub(r'\.wav$', '', n, flags=re.IGNORECASE) for n in full_names))

        lang_filter = set(langs) if langs else None
        unique_full = ([full for full in unique_full_all if self._rename_match_detect_lang(full) in lang_filter]
                        if lang_filter else unique_full_all)

        renamed, unmatched, ambiguous, rows = [], [], [], []
        claimed = {}  # полное имя -> какой короткий файл уже его занял

        for fname in files:
            short, ext = os.path.splitext(fname)
            pattern = re.compile(r'(^|_)' + re.escape(short) + r'$', re.IGNORECASE)
            matches = [full for full in unique_full if pattern.search(full)]

            if not matches:
                # Подробная причина: если ограничили языком и совпадение всё
                # же ЕСТЬ в полном (нефильтрованном) списке — значит дело
                # именно в фильтре, а не в том, что строки в Excel вообще
                # нет. Это и есть та самая «подробность», которую не видно,
                # если просто сказать «не нашлось».
                matches_unfiltered = ([full for full in unique_full_all if pattern.search(full)]
                                       if lang_filter else [])
                if matches_unfiltered:
                    found_langs = sorted({self._rename_match_detect_lang(f) or OTHER_LANG_DIR
                                           for f in matches_unfiltered})
                    detail = (f"совпадение есть в Excel, но его язык ({'/'.join(found_langs)}) "
                              f"не входит в выбранный фильтр «Искать только»")
                else:
                    detail = "в Excel не нашлось ни одной строки, заканчивающейся на это короткое имя"
                unmatched.append({"file": fname, "detail": detail})
                rows.append({"status": "Не найдено", "file": fname, "short": short,
                              "detail": detail, "matches": '; '.join(matches_unfiltered)})
                continue

            if len(matches) > 1:
                detail = f"нашлось {len(matches)} совпадений в Excel сразу — непонятно, какое верное"
                ambiguous.append({"file": fname, "reason": detail, "matches": matches})
                rows.append({"status": "Неоднозначно", "file": fname, "short": short,
                              "detail": detail, "matches": '; '.join(matches)})
                continue

            full = matches[0]
            if full in claimed:
                detail = f"это же полное имя уже занял файл «{claimed[full]}»"
                ambiguous.append({"file": fname, "reason": detail, "matches": [full]})
                rows.append({"status": "Неоднозначно", "file": fname, "short": short,
                              "detail": detail, "matches": full})
                continue

            lang = self._rename_match_detect_lang(full) or OTHER_LANG_DIR
            safe_full = BAD_NAME_CHARS.sub(' ', full).strip()
            target_dir = os.path.join(root, lang)
            target_path = os.path.join(target_dir, safe_full + ext)

            if os.path.exists(target_path):
                detail = "файл с таким итоговым именем уже есть в папке назначения"
                ambiguous.append({"file": fname, "reason": detail, "matches": [full]})
                rows.append({"status": "Неоднозначно", "file": fname, "short": short,
                              "detail": detail, "matches": full})
                continue

            os.makedirs(target_dir, exist_ok=True)
            shutil.move(os.path.join(root, fname), target_path)
            claimed[full] = fname
            result_path = f"{lang}/{safe_full}{ext}"
            renamed.append({"from": fname, "to": result_path})
            rows.append({"status": "Переименовано", "file": fname, "short": short,
                          "detail": result_path, "matches": full})

        result = {
            "status": "ok",
            "renamed": renamed, "unmatched": unmatched, "ambiguous": ambiguous,
            "renamed_count": len(renamed), "unmatched_count": len(unmatched), "ambiguous_count": len(ambiguous),
            "rows": rows,
        }
        self.rename_match_last_report = result
        return result

    def rename_match_export_report(self):
        """Полный отчёт последнего запуска в Excel — по строке на каждый
        файл: что с ним стало и почему, плюс со всеми совпадениями,
        которые для него нашлись (или почти нашлись)."""
        report = getattr(self, 'rename_match_last_report', None)
        if not report or not report.get('rows'):
            return {"error": "Сначала запустите «Сопоставить и разложить» — экспортировать пока нечего."}

        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename='Отчёт сопоставления.xlsx',
            file_types=('Excel files (*.xlsx)',))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Отчёт'
        headers = ['Статус', 'Файл', 'Короткое имя', 'Результат / причина', 'Совпадения в Excel']
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)

        for row in report['rows']:
            ws.append([row['status'], row['file'], row.get('short', ''),
                       row.get('detail', ''), row.get('matches', '')])

        for col_idx, header in enumerate(headers, start=1):
            letter = get_column_letter(col_idx)
            values = [str(ws.cell(row=r, column=col_idx).value or '') for r in range(1, ws.max_row + 1)]
            ws.column_dimensions[letter].width = min(60, max(len(v) for v in values) + 2)

        try:
            wb.save(path)
        except Exception as e:
            return {"error": f"Не удалось сохранить отчёт.\n\n{e}"}

        return {"status": "ok", "path": path}
