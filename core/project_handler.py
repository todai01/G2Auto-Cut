import os
import re
import math
import webview
import pyautogui

from core import project_state, recent_projects
from core.variables_handler import SUM_TIER_ORDER

try:
    import audioop  # быстрый расчёт громкости; удалён из Python 3.13
except ImportError:
    audioop = None

# Длина окна, которым мы замеряем громкость записи
FRAME_MS = 20

# Варианты длины паузы, которые перебирает автоподбор
PAUSE_CANDIDATES = [120, 150, 200, 250, 300, 400, 500, 650, 800, 1000]


class ProjectMixin:
    """Модуль управления файлами проекта, нарезкой аудио и загрузкой папок."""

    # ==================================================================
    #  АВТОПОДБОР НАСТРОЕК НАРЕЗКИ
    # ==================================================================

    def _frame_levels(self, audio):
        """Громкость записи по коротким окнам, в дБ. Это основа всех замеров."""
        mono = audio.set_channels(1)
        samples_per_frame = max(1, int(mono.frame_rate * FRAME_MS / 1000))
        floor_db = -100.0

        if audioop is not None:
            width = mono.sample_width
            data = mono.raw_data
            chunk_bytes = samples_per_frame * width
            max_amp = float(mono.max_possible_amplitude)
            levels = []
            for i in range(0, len(data) - chunk_bytes + 1, chunk_bytes):
                rms = audioop.rms(data[i:i + chunk_bytes], width)
                levels.append(20 * math.log10(rms / max_amp) if rms > 0 else floor_db)
            return levels

        # Запасной путь, если audioop недоступен: медленнее, но работает везде
        levels = []
        for i in range(0, len(mono), FRAME_MS):
            d = mono[i:i + FRAME_MS].dBFS
            levels.append(floor_db if d == float('-inf') or d != d else d)
        return levels

    @staticmethod
    def _count_ranges(levels, thresh, min_silence_ms):
        """Сколько кусков получится при таких настройках. Быстрая оценка по окнам."""
        min_frames = max(1, int(round(min_silence_ms / FRAME_MS)))
        count = 0
        in_speech = False
        silence_run = 0
        for lv in levels:
            if lv < thresh:
                silence_run += 1
                if in_speech and silence_run >= min_frames:
                    in_speech = False
            else:
                if not in_speech:
                    count += 1
                    in_speech = True
                silence_run = 0
        return count

    @staticmethod
    def _percentile(sorted_values, share):
        if not sorted_values:
            return -60.0
        idx = min(len(sorted_values) - 1, max(0, int(len(sorted_values) * share)))
        return sorted_values[idx]

    def _suggest_cut_settings(self, levels, target):
        """Замеряем фон и речь и подбираем порог + паузу так, чтобы число
        кусков было ближе всего к target (0 — просто осмысленное дробление).
        Возвращает (фон, речь, разброс, порог, пауза, ожидаемое число кусков)."""
        ordered = sorted(levels)

        noise_db = round(self._percentile(ordered, 0.10), 1)   # уровень фона
        speech_db = round(self._percentile(ordered, 0.90), 1)  # уровень речи
        spread = speech_db - noise_db

        # Порог ставим чуть выше фона, но заведомо ниже речи
        raw_thresh = noise_db + max(3.0, min(12.0, spread * 0.25))
        low_limit, high_limit = -70, -12
        base_thresh = int(round(max(low_limit, min(high_limit, min(raw_thresh, speech_db - 8)))))

        # Перебираем пары «порог + пауза» и ищем ближайшую к числу фраз из Excel
        thresh_options = sorted({int(round(max(low_limit, min(high_limit, base_thresh + d))))
                                 for d in (-4, -2, 0, 2, 4, 6)})
        best = None
        for th in thresh_options:
            for pause in PAUSE_CANDIDATES:
                n = self._count_ranges(levels, th, pause)
                if n < 1:
                    continue
                if target:
                    score = (abs(n - target), abs(th - base_thresh), -pause)
                else:
                    # Без Excel: хотим осмысленное дробление, а не один кусок
                    score = (0 if n >= 8 else 8 - n, abs(th - base_thresh), -pause)
                if best is None or score < best[0]:
                    best = (score, th, pause, n)

        if best is None:
            sug_thresh, sug_pause, predicted = base_thresh, 400, 1
        else:
            _, sug_thresh, sug_pause, predicted = best
        return noise_db, speech_db, spread, sug_thresh, sug_pause, predicted

    # ==================================================================
    #  ЛЕНТА ДУБЛЕЙ
    # ==================================================================

    def _build_chunk_strip(self, radius=30):
        """Статусы дублей вокруг текущего: что уже разложено, а что ещё нет.

        Берём окно, а не весь список: при 900 дублях проверять каждый файл на
        каждое нажатие клавиши — лишняя работа для диска."""
        if not self.chunks_data or not self.work_dir:
            return None

        total = len(self.chunks_data)
        cur = min(max(0, self.chunk_index), total - 1)
        start = max(0, cur - radius)
        end = min(total, cur + radius + 1)

        # Дубли и фразы шагают парой; смещение берём из текущей позиции,
        # чтобы лента показывала ровно ту же связку, что и основной экран.
        offset = self.phrase_index - self.chunk_index

        checked_dir = os.path.join(self.work_dir, 'Проверенные')
        var_dir = os.path.join(self.work_dir, 'Переменные')

        items = []
        for i in range(start, end):
            chunk_file = self.chunks_data[i]['filename']
            name = chunk_file

            p = i + offset
            if self.phrases_data and 0 <= p < len(self.phrases_data):
                custom = self.phrases_data[p].get('filename')
                if custom:
                    custom = str(custom)
                    name = custom if custom.lower().endswith('.wav') else f"{custom}.wav"

            if os.path.exists(os.path.join(checked_dir, name)):
                status = 'checked'
            elif os.path.exists(os.path.join(var_dir, name)):
                status = 'var'
            else:
                status = 'none'

            items.append({"index": i, "num": i + 1, "name": name,
                          "status": status, "current": i == cur})

        return {"items": items, "total": total, "from": start + 1, "to": end}

    # ==================================================================

    def get_recent_projects(self):
        """Список недавних проектов для стартового экрана."""
        return recent_projects.list_recent()

    def clear_recent_projects(self):
        """Очистить список недавних проектов — только список, папки целы."""
        recent_projects.clear()
        return {"status": "ok"}

    def open_recent_project(self, path):
        """Открыть недавний проект в один клик. Одним кликом открываются
        только TTS-проекты; проекты режима проверки дублей больше не
        поддерживаются."""
        if not path or not os.path.isdir(path):
            return {"error": "Папка проекта больше не найдена на диске."}

        if self.tts_is_project(path):
            return {**self.tts_open_project(path), "tts": True}

        return {"error": "Это проект режима проверки дублей, который убран из программы. "
                         "Для переменных откройте «Пакетную сборку» или «Готовую папку с переменными» в меню."}

    def navigate_chunk(self, direction, auto_play=True):
        if not self.chunks_data:
            return self.get_ui_state()
        self.chunk_index = max(0, min(self.chunk_index + direction, len(self.chunks_data) - 1))
        self._sync_audacity_selection()
        return self.get_ui_state()

    def jump_to_chunk(self, index):
        if self.chunks_data and 0 <= index < len(self.chunks_data):
            self.chunk_index = index
            self._sync_audacity_selection()
        return self.get_ui_state()

    def _audit_scan_folder(self, scan_dir):
        """Рекурсивно собирает все .wav/.mp3 в папке (кроме «мусорных»
        подпапок trash) — общая часть обоих видов аудита."""
        found_files = {}
        all_disk_files = set()
        for root_dir, _, files in os.walk(scan_dir):
            if 'trash' in root_dir.lower():
                continue
            for file in files:
                if file.lower().endswith(('.wav', '.mp3')):
                    f_low = file.lower()
                    full_p = os.path.join(root_dir, file)
                    all_disk_files.add(f_low)
                    found_files.setdefault(f_low, []).append(full_p)
        return found_files, all_disk_files

    def _audit_available_categories(self):
        """Категории словаря переменных, по которым можно свериться с
        папкой — только те, для которых в загруженном словаре реально
        есть хоть одно значение (без словаря — пустой список, тогда
        аудит ведёт себя как раньше, по основной таблице Excel)."""
        values_by_key = getattr(self, 'var_extra_tag_values', None) or {}
        return [{"key": k, "label": self._category_label(k)}
                for k in self._all_category_keys() if values_by_key.get(k)]

    def audit_project_files(self, category=None):
        """Без выбранной категории и при загруженном словаре переменных —
        сперва спрашивает, по какой категории сверяться (Excel-список
        дублей «Шага 1» или одна из категорий словаря — марка/год/ярусы
        Суммы и т.п.), а уже потом открывает папку на сканирование."""
        if category is None:
            categories = self._audit_available_categories()
            if categories:
                return {
                    "status": "choose_category",
                    "categories": categories,
                    "has_excel": bool(self.phrases_data),
                }
            if self.phrases_data:
                # Только Excel — сразу спрашиваем, готовы ли чанки.
                return {"status": "choose_chunks", "category": "excel", "label": "Текст из Excel"}

        if category and category != 'excel':
            return self._audit_by_category(category)

        if not self.phrases_data:
            return {"error": "Сначала загрузите Excel-файл с текстами (Шаг 1)!"}

        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        scan_dir = folder[0]
        found_files, all_disk_files = self._audit_scan_folder(scan_dir)

        missing_list = []
        duplicates_list = []

        valid_excel_count = 0
        for i, p in enumerate(self.phrases_data):
            custom_filename = p.get("filename")
            if not custom_filename or not str(custom_filename).strip():
                continue

            valid_excel_count += 1
            expected_wav = (str(custom_filename).strip() if str(custom_filename).strip().lower().endswith(
                '.wav') else f"{str(custom_filename).strip()}.wav").lower()

            if expected_wav not in all_disk_files:
                missing_list.append({
                    "index": i + 1,
                    "filename": expected_wav,
                    "text": p.get("text", "")
                })

        for f_low, paths in found_files.items():
            if len(paths) > 1:
                duplicates_list.append({
                    "filename": f_low,
                    "count": len(paths),
                    "paths": paths
                })

        self._audit_last = {"category": "excel", "missing": {m["text"] for m in missing_list}}

        return {
            "can_export": bool(missing_list and self._excel_source_ok()),
            "scan_dir": scan_dir,
            "total_excel": valid_excel_count,
            "total_disk": len(all_disk_files),
            "missing_count": len(missing_list),
            "duplicates_count": len(duplicates_list),
            "missing": missing_list,
            "duplicates": duplicates_list
        }

    def _audit_by_category(self, category):
        """Сверяет с папкой не основной Excel, а список значений ОДНОЙ
        категории словаря переменных (марка/год/ярус Суммы и т.п.) — то
        же имя файла, что ждёт сохранение эталона в этой категории (см.
        _sum_stage2_resolve_value): для ярусов Суммы это голые цифры
        значения, для остальных категорий — само значение, очищенное от
        запрещённых в именах файлов символов."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(category) or []
        if not values:
            return {"error": "Для этой категории в словаре переменных нет ни одного значения."}

        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        scan_dir = folder[0]
        found_files, all_disk_files = self._audit_scan_folder(scan_dir)

        missing_list = []
        for i, value in enumerate(values):
            clean_value = re.sub(r'[<>:"/\\|?*]', '', value).strip()
            name_base = re.sub(r'\D', '', clean_value) if category in SUM_TIER_ORDER else clean_value
            name_base = (name_base or clean_value).lower()
            expected = {f"{name_base}.wav", f"{name_base}.mp3"}
            if not expected & all_disk_files:
                missing_list.append({
                    "index": i + 1,
                    "filename": f"{name_base}.wav",
                    "text": value
                })

        duplicates_list = [{"filename": f, "count": len(paths), "paths": paths}
                            for f, paths in found_files.items() if len(paths) > 1]

        # Для выгрузки «таблицы недостающих» (audit_export_missing).
        self._audit_last = {"category": category, "missing": {m["text"] for m in missing_list}}
        template = getattr(self, 'var_template_path', None)

        return {
            "category": category,
            "can_export": bool(missing_list and template and os.path.exists(template)),
            "category_label": self._category_label(category),
            "scan_dir": scan_dir,
            "total_excel": len(values),
            "total_disk": len(all_disk_files),
            "missing_count": len(missing_list),
            "duplicates_count": len(duplicates_list),
            "missing": missing_list,
            "duplicates": duplicates_list
        }

    def _excel_source_ok(self):
        p = getattr(self, 'excel_path', None)
        return bool(p and os.path.exists(p) and getattr(self, 'excel_cols', None))

    def _audit_export_excel(self, missing):
        """Копия исходного Excel (шапка, колонки, оформление) только со
        строками, где есть ещё не записанная фраза."""
        import openpyxl
        path = self.excel_path
        try:
            wb = openpyxl.load_workbook(path)
        except Exception as e:
            return None, {"error": f"Не удалось открыть исходную таблицу: {e}"}
        ws = wb.active
        cols = [c + 1 for c in self.excel_cols]
        first = int(getattr(self, 'excel_header_row', 0) or 0) + 1
        drop = []
        for r in range(first, ws.max_row + 1):
            keep = False
            for c in cols:
                v = ws.cell(row=r, column=c).value
                if v not in (None, '') and str(v).strip() in missing:
                    keep = True
                    break
            if not keep:
                drop.append(r)
        kept = ws.max_row - (first - 1) - len(drop)
        while drop:
            end = drop.pop()
            start = end
            while drop and drop[-1] == start - 1:
                start = drop.pop()
            ws.delete_rows(start, end - start + 1)
        return (wb, kept), None

    def audit_export_missing(self):
        """Таблица в том же формате, что загруженный словарь (та же шапка,
        те же колонки и оформление), но только со строками, где значение
        проверенной категории не нашлось в папке — её сразу можно
        загрузить как словарь и записывать только недостающее."""
        last = getattr(self, '_audit_last', None)
        if not last or not last.get("missing"):
            return {"error": "Сначала запустите аудит — выгружать пока нечего."}
        if last.get("category") == "excel":
            if not self._excel_source_ok():
                return {"error": "Не нашёл исходный Excel — загрузите текст (Шаг 1) заново."}
            res, err = self._audit_export_excel(last["missing"])
            if err:
                return err
            wb, kept = res
            src = self.excel_path
            stem = os.path.splitext(os.path.basename(src))[0]
            picked = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE, directory=os.path.dirname(src),
                save_filename=f'{stem} — недостающие.xlsx', file_types=('Excel files (*.xlsx)',))
            if not picked:
                return {"error": "cancel"}
            out = picked if isinstance(picked, str) else picked[0]
            if not out.lower().endswith('.xlsx'):
                out += '.xlsx'
            try:
                wb.save(out)
            except Exception as e:
                return {"error": f"Не удалось сохранить таблицу (может, она открыта в Excel?): {e}"}
            return {"saved": out, "rows": kept}
        template = getattr(self, 'var_template_path', None)
        if not template or not os.path.exists(template):
            return {"error": "Не нашёл исходную таблицу-словарь — загрузите её заново."}

        import openpyxl
        try:
            wb = openpyxl.load_workbook(template)
        except Exception as e:
            return {"error": f"Не удалось открыть исходную таблицу: {e}"}
        ws = wb.active

        # Колонка категории — по шапке <тег>, как при загрузке словаря.
        col_idx = None
        for col in getattr(self, 'var_template_columns', None) or []:
            if col['key'] == last["category"] and col['type'] != 'connector':
                col_idx = col['col_idx'] + 1
                break
        if col_idx is None:
            return {"error": "В таблице нет колонки этой категории."}

        missing = last["missing"]
        drop = []
        for r in range(2, ws.max_row + 1):
            v = ws.cell(row=r, column=col_idx).value
            if v in (None, '') or str(v).strip() not in missing:
                drop.append(r)
        # Удаляем подряд идущие блоки снизу вверх — быстро и без сдвига номеров.
        kept = ws.max_row - 1 - len(drop)
        while drop:
            end = drop.pop()
            start = end
            while drop and drop[-1] == start - 1:
                start = drop.pop()
            ws.delete_rows(start, end - start + 1)

        stem = os.path.splitext(os.path.basename(template))[0]
        label = self._category_label(last["category"])
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, directory=os.path.dirname(template),
            save_filename=f'{stem} — недостающие ({label}).xlsx',
            file_types=('Excel files (*.xlsx)',))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if not path.lower().endswith('.xlsx'):
            path += '.xlsx'
        try:
            wb.save(path)
        except Exception as e:
            return {"error": f"Не удалось сохранить таблицу (может, она открыта в Excel?): {e}"}
        return {"saved": path, "rows": kept}

    def clear_loaded(self, what):
        """«×» на карточке главного меню: сбросить загруженное, чтобы
        загрузить заново. what='excel' — таблицу с текстом; иначе — проект
        (нарезку/папку чанков). Прогресс проекта перед этим сохраняется."""
        if what == 'excel':
            self.phrases_data = []
            self.excel_name = None
            self.excel_path = None
            self.excel_cols = None
            self.phrase_index = 0
            if getattr(self, 'work_dir', ''):
                project_state.save(self)
        else:
            if getattr(self, 'work_dir', ''):
                project_state.save(self)
            self.work_dir = ""
            self.project_name = ""
            self.chunks_data = []
            self.chunk_index = 0
            self.raw_audio_full = None
            self.pending_raw_path = None
            self.current_mode = 'Chunks'
            self.sum_manual_active = False
        return {"status": "ok"}

    def _sync_audacity_selection(self):
        """Синхронизирует выделение текущего дубля (чанка) в Audacity и приближает его."""
        try:
            if not getattr(self, 'chunks_data', None) or getattr(self, 'chunk_index', 0) >= len(self.chunks_data):
                return

            item = self.chunks_data[self.chunk_index]
            if 'start' in item and 'end' in item:
                start_sec = item['start']
                end_sec = item['end']

                if hasattr(self, 'audacity'):
                    self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
                    self.audacity.send_command(f'SelectTime: Start={start_sec} End={end_sec} RelativeTo=ProjectStart')
                    self.audacity.send_command('ZoomSel:')
                    self.audacity.send_command('SetProject: Rate=8000')
        except Exception:
            pass
