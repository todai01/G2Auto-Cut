import os
import time
import webview
import pyautogui
from pydub import AudioSegment
from pydub.silence import detect_nonsilent


class ProjectMixin:
    """Модуль управления файлами проекта, нарезкой аудио и загрузкой папок."""

    def load_raw_audio(self, min_silence, silence_thresh, keep_silence):
        file_types = ('Audio Files (*.wav)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return self.get_ui_state()

        raw_filepath = filename[0]
        self.work_dir = os.path.dirname(raw_filepath)
        self.project_name = os.path.basename(self.work_dir)
        chunks_dir = os.path.join(self.work_dir, 'Chunks')

        for folder in ['Chunks', 'Good', 'Trash', 'Переменные', 'Проверенные']:
            os.makedirs(os.path.join(self.work_dir, folder), exist_ok=True)

        audio = AudioSegment.from_file(raw_filepath)
        self.raw_audio_full = audio
        nonsilent_ranges = detect_nonsilent(audio, min_silence_len=int(min_silence), silence_thresh=int(silence_thresh))

        for f in os.listdir(chunks_dir):
            if os.path.isfile(os.path.join(chunks_dir, f)):
                os.remove(os.path.join(chunks_dir, f))

        labels_path = os.path.join(self.work_dir, 'labels.txt')
        with open(labels_path, 'w', encoding='utf-8') as label_file:
            for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
                start_adjusted = max(0, start_ms - keep_silence)
                end_adjusted = min(len(audio), end_ms + keep_silence)
                start_sec, end_sec = start_adjusted / 1000.0, end_adjusted / 1000.0
                chunk_name_no_ext = f"фраза_{i + 1:04d}"
                label_file.write(f"{start_sec}\t{end_sec}\t{chunk_name_no_ext}\n")
                audio[start_adjusted:end_adjusted].export(os.path.join(chunks_dir, f"{chunk_name_no_ext}.wav"),
                                                          format="wav")

                percent = int(((i + 1) / len(nonsilent_ranges)) * 100)
                try:
                    webview.windows[0].evaluate_js(
                        f"updateProgress({percent}, 'Нарезка: {i + 1} из {len(nonsilent_ranges)}');")
                except:
                    pass

        # --- БЕЗОПАСНАЯ ИНТЕГРАЦИЯ С AUDACITY ---
        try:
            webview.windows[0].evaluate_js("updateProgress(100, 'Запуск Audacity (подождите пару секунд)...');")
        except:
            pass

        try:
            self.audacity.send_command('New:', auto_start=True)
            time.sleep(2.5)  # Даем Audacity больше времени на "холодный" старт

            # Умное ожидание загрузки Audacity: стучимся к нему, пока не ответит
            for _ in range(15):
                resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
                if resp and '[' in resp:
                    break
                time.sleep(0.5)

            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(raw_filepath).replace(chr(92), "/")}"')
            time.sleep(1.0)
            self.audacity.send_command('NewMonoTrack:')
            time.sleep(0.5)
            self.audacity.send_command(f'ImportLabels: Filename="{os.path.abspath(labels_path).replace(chr(92), "/")}"')
        except Exception as e:
            try:
                webview.windows[0].evaluate_js(
                    f"showBeautifulAlert('⚠️ <b>Аудио нарезано, но Audacity не ответил!</b><br><br>Чанки успешно сохранены в папку, но собрать проект в Audacity автоматически не удалось.<br>Ошибка: {e}');")
            except:
                pass
        # -----------------------------------------------------

        self.current_mode = 'Chunks'
        self.state_memory = {'Chunks': [0, 0], 'Good': [0, 0], 'Переменные': [0, 0], 'Проверенные': [0, 0]}
        return self._scan_and_load_folder(chunks_dir, 'Chunks')

    def load_chunks_folder(self):
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return self.get_ui_state()

        selected_path = folder[0]
        self.work_dir = os.path.dirname(selected_path) if os.path.basename(selected_path).lower() in ['chunks', 'good',
                                                                                                      'переменные',
                                                                                                      'trash',
                                                                                                      'проверенные'] else selected_path
        self.project_name = os.path.basename(self.work_dir)

        has_tracks = False
        response = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON', auto_start=True)
        if response and 'name' in response.lower():
            has_tracks = True

        if has_tracks:
            use_existing = webview.windows[0].create_confirmation_dialog('Audacity',
                                                                         'Обнаружен открытый проект в Audacity. Использовать его (ОК) или создать новый (Отмена)?')
            if use_existing:
                webview.windows[0].evaluate_js(
                    "alert('Пожалуйста, укажите ИСХОДНЫЙ WAV-файл (только для памяти точного среза).');")
                raw_file = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                                 file_types=('Audio Files (*.wav)', 'All files (*.*)'))
                if raw_file:
                    self.raw_audio_full = AudioSegment.from_file(raw_file[0])
                return self._scan_and_load_folder(os.path.join(self.work_dir, 'Chunks'), 'Chunks')

        webview.windows[0].evaluate_js("alert('Пожалуйста, выберите ИСХОДНЫЙ WAV-файл для памяти Audacity.');")
        raw_file = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                         file_types=('Audio Files (*.wav)', 'All files (*.*)'))
        if raw_file:
            self.raw_audio_full = AudioSegment.from_file(raw_file[0])
            self.audacity.send_command('New:', auto_start=True)
            time.sleep(1)
            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(raw_file[0]).replace(chr(92), "/")}"')
            time.sleep(0.5)
            self.audacity.send_command('NewMonoTrack:')
            time.sleep(0.2)
            labels_path = os.path.join(self.work_dir, 'labels.txt')
            if os.path.exists(labels_path):
                self.audacity.send_command(
                    f'ImportLabels: Filename="{os.path.abspath(labels_path).replace(chr(92), "/")}"')

        return self._scan_and_load_folder(os.path.join(self.work_dir, 'Chunks'), 'Chunks')

    def load_results_mode(self):
        return self._scan_and_load_folder(os.path.join(self.work_dir, 'Good'),
                                          'Good') if self.work_dir else self.get_ui_state()

    def load_main_mode(self):
        return self._scan_and_load_folder(os.path.join(self.work_dir, 'Chunks'),
                                          'Chunks') if self.work_dir else self.get_ui_state()

    def load_checked_mode(self):
        return self._scan_and_load_folder(os.path.join(self.work_dir, 'Проверенные'),
                                          'Проверенные') if self.work_dir else self.get_ui_state()

    def _scan_and_load_folder(self, target_folder, mode_name):
        self.state_memory[self.current_mode] = [self.chunk_index, self.phrase_index]
        self.current_mode = mode_name

        for sub in ['Good', 'Trash', 'Переменные', 'Проверенные']:
            os.makedirs(os.path.join(self.work_dir, sub), exist_ok=True)

        timings = {}
        labels_path = os.path.join(self.work_dir, 'labels.txt')
        if os.path.exists(labels_path):
            with open(labels_path, 'r', encoding='utf-8') as f:
                for line in f:
                    p = line.strip().split('\t')
                    if len(p) >= 3: timings[p[2]] = {'start': float(p[0]), 'end': float(p[1])}

        self.chunks_data = []
        if os.path.exists(target_folder):
            collected_files = []
            for root, dirs, files in os.walk(target_folder):
                for filename in files:
                    if filename.lower().endswith(('.wav', '.mp3')):
                        collected_files.append((filename, os.path.join(root, filename)))

            collected_files.sort(key=lambda x: x[0])

            for filename, filepath in collected_files:
                info = {"filename": filename, "filepath": filepath}
                name_no_ext = filename.replace('.wav', '').replace('.mp3', '')
                if name_no_ext in timings:
                    info['start'], info['end'] = timings[name_no_ext]['start'], timings[name_no_ext]['end']
                self.chunks_data.append(info)

        if mode_name in ['Good', 'Переменные', 'Проверенные'] and self.phrases_data:
            def sort_key(chunk):
                name = chunk['filename'].replace('.wav', '')
                for i, p in enumerate(self.phrases_data):
                    if name == (p["filename"] if p["filename"] else f"фраза_{i + 1:04d}"): return i
                return 999999

            self.chunks_data.sort(key=sort_key)

        saved = self.state_memory.get(mode_name, [0, 0])
        self.chunk_index = min(saved[0], max(0, len(self.chunks_data) - 1)) if self.chunks_data else 0
        self.phrase_index = saved[1]
        self._sync_audacity_selection()
        return self.get_ui_state()

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

    def audit_project_files(self):
        if not self.phrases_data:
            return {"error": "Сначала загрузите Excel-файл с текстами (Шаг 1)!"}

        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        scan_dir = folder[0]
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
                    if f_low not in found_files:
                        found_files[f_low] = []
                    found_files[f_low].append(full_p)

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

        return {
            "scan_dir": scan_dir,
            "total_excel": valid_excel_count,
            "total_disk": len(all_disk_files),
            "missing_count": len(missing_list),
            "duplicates_count": len(duplicates_list),
            "missing": missing_list,
            "duplicates": duplicates_list
        }

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
