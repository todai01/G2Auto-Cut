import os
import math
import time
import webview
import pyautogui
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core import project_state

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

    def pick_raw_audio(self):
        """Шаг 1: пользователь выбирает файл. Тяжёлый анализ идёт отдельно,
        чтобы интерфейс успел показать полосу прогресса."""
        file_types = ('Audio Files (*.wav)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return {"error": "cancel"}

        self.pending_raw_path = filename[0]
        self.pending_levels = None
        return {"name": os.path.basename(filename[0])}

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

    def analyze_picked_audio(self):
        """Шаг 2: замеряем фон и речь, подбираем настройки под число фраз из Excel."""
        path = getattr(self, 'pending_raw_path', None)
        if not path or not os.path.exists(path):
            return {"error": "Файл не выбран. Нажмите «Резать сырой WAV» ещё раз."}

        try:
            audio = AudioSegment.from_file(path)
        except Exception as e:
            return {"error": f"Не удалось открыть аудиофайл.\n\n{os.path.basename(path)}\n\nПодробности: {e}"}

        levels = self._frame_levels(audio)
        if not levels:
            return {"error": "Запись пустая или слишком короткая для анализа."}

        self.pending_levels = levels
        ordered = sorted(levels)

        noise_db = round(self._percentile(ordered, 0.10), 1)   # уровень фона
        speech_db = round(self._percentile(ordered, 0.90), 1)  # уровень речи
        spread = speech_db - noise_db

        # Порог ставим чуть выше фона, но заведомо ниже речи
        raw_thresh = noise_db + max(3.0, min(12.0, spread * 0.25))
        low_limit, high_limit = -70, -12
        base_thresh = int(round(max(low_limit, min(high_limit, min(raw_thresh, speech_db - 8)))))

        target = len(self.phrases_data) if getattr(self, 'phrases_data', None) else 0

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

        sug_pad = 150 if sug_pause < 300 else 200

        # Несколько соседних вариантов, чтобы было видно, как меняется дробление
        variants = []
        for pause in (150, 250, 400, 600, 900):
            variants.append({"pause": pause, "chunks": self._count_ranges(levels, sug_thresh, pause)})

        return {
            "name": os.path.basename(path),
            "duration_sec": round(len(audio) / 1000.0, 1),
            "noise_db": noise_db,
            "speech_db": speech_db,
            "spread": round(spread, 1),
            "target_phrases": target,
            "suggested": {"pause": sug_pause, "sens": sug_thresh, "pad": sug_pad},
            "predicted_chunks": predicted,
            "variants": variants
        }

    def predict_cut(self, min_silence, silence_thresh):
        """Пересчёт числа кусков, когда пользователь правит цифры руками."""
        levels = getattr(self, 'pending_levels', None)
        if not levels:
            return {"chunks": None}
        return {"chunks": self._count_ranges(levels, int(silence_thresh), int(min_silence))}

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
        # Good остаётся только ради проектов, начатых до отказа от двойного отбора
        good_dir = os.path.join(self.work_dir, 'Good')

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

            if os.path.exists(os.path.join(checked_dir, name)) or \
                    os.path.exists(os.path.join(good_dir, name)):
                status = 'checked'
            elif os.path.exists(os.path.join(var_dir, name)):
                status = 'var'
            else:
                status = 'none'

            items.append({"index": i, "num": i + 1, "name": name,
                          "status": status, "current": i == cur})

        return {"items": items, "total": total, "from": start + 1, "to": end}

    # ==================================================================

    def load_raw_audio(self, min_silence, silence_thresh, keep_silence, filepath=None):
        # Файл уже выбран на этапе автоподбора — второй раз не спрашиваем
        raw_filepath = filepath or getattr(self, 'pending_raw_path', None)

        if not raw_filepath or not os.path.exists(raw_filepath):
            file_types = ('Audio Files (*.wav)', 'All files (*.*)')
            filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
            if not filename:
                return self.get_ui_state()
            raw_filepath = filename[0]
        self.work_dir = os.path.dirname(raw_filepath)
        self.project_name = os.path.basename(self.work_dir)

        # Если в этой папке уже есть сохранённый проект — подтягиваем тексты
        # из Excel, чтобы не загружать их заново после повторной нарезки.
        project_state.apply(self, project_state.load(self.work_dir))

        chunks_dir = os.path.join(self.work_dir, 'Chunks')

        for folder in ['Chunks', 'Переменные', 'Проверенные']:
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

            # Умное ожидание загрузки Audacity: стучимся к нему, пока не ответит.
            # Раньше перед этим циклом ещё стояла слепая пауза в 2.5с — она не
            # нужна, потому что первая же попытка в цикле делает то же самое
            # ожидание, просто с проверкой результата, а не наугад.
            resp = ""
            for _ in range(15):
                resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
                if resp and '[' in resp:
                    break
                time.sleep(0.5)

            tracks_before = resp.count('"kind"')
            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(raw_filepath).replace(chr(92), "/")}"')

            # Ждём, пока импортированная дорожка реально появится в проекте,
            # вместо слепой паузы в 1с на любой скорости диска и файла.
            for _ in range(10):
                resp2 = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
                if resp2 and resp2.count('"kind"') > tracks_before:
                    break
                time.sleep(0.2)

            self.audacity.send_command('NewMonoTrack:')
            time.sleep(0.2)
            self.audacity.send_command(f'ImportLabels: Filename="{os.path.abspath(labels_path).replace(chr(92), "/")}"')
        except Exception as e:
            try:
                webview.windows[0].evaluate_js(
                    f"showBeautifulAlert('⚠️ <b>Аудио нарезано, но Audacity не ответил!</b><br><br>Чанки успешно сохранены в папку, но собрать проект в Audacity автоматически не удалось.<br>Ошибка: {e}');")
            except:
                pass
        # -----------------------------------------------------

        self.current_mode = 'Chunks'
        self.state_memory = {'Chunks': [0, 0], 'Переменные': [0, 0], 'Проверенные': [0, 0]}
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

        # Восстанавливаем сохранённый снимок проекта (тексты из Excel, номер
        # текущего дубля, режим) — если он раньше сохранялся в эту папку.
        project_state.apply(self, project_state.load(self.work_dir))

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

        for sub in ['Переменные', 'Проверенные']:
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
