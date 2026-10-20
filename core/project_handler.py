import os
import re
import math
import time
import webview
import pyautogui
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core import project_state, recent_projects
from core.ui_dialogs import ui_confirm, ui_toast
from utils.wav_io import slice_or_export
from core.variables_handler import SUM_TIER_ORDER, SUM_TIER_DEFAULT_DIR, VALUES_DIR

try:
    import audioop  # быстрый расчёт громкости; удалён из Python 3.13
except ImportError:
    audioop = None

# Длина окна, которым мы замеряем громкость записи
FRAME_MS = 20

# Варианты длины паузы, которые перебирает автоподбор
PAUSE_CANDIDATES = [120, 150, 200, 250, 300, 400, 500, 650, 800, 1000]

# Папки, которые НЕ являются очередью дублей — их не нужно засчитывать при
# сканировании «Chunks», даже если они (из-за старого проекта или ручной
# перекладки файлов) оказались вложены прямо внутрь Chunks. «_Остатки» сюда
# намеренно не входит: это неразобранные куски, они и должны возвращаться
# в очередь.
_SCAN_EXCLUDE_SUBDIRS = {'chunks', 'переменные', 'проверенные'}


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

    def select_raw_audio_path(self, path):
        """Как pick_raw_audio, но без диалога выбора — путь уже известен
        (например, файл только что вышел из конвертера MP4)."""
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден на диске."}
        self.pending_raw_path = path
        self.pending_levels = None
        return {"name": os.path.basename(path)}

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
        target = len(self.phrases_data) if getattr(self, 'phrases_data', None) else 0
        noise_db, speech_db, spread, sug_thresh, sug_pause, predicted = self._suggest_cut_settings(levels, target)

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

    def load_raw_audio(self, min_silence, silence_thresh, keep_silence, filepath=None):
        # Файл уже выбран на этапе автоподбора — второй раз не спрашиваем
        raw_filepath = filepath or getattr(self, 'pending_raw_path', None)

        if not raw_filepath or not os.path.exists(raw_filepath):
            file_types = ('Audio Files (*.wav)', 'All files (*.*)')
            filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
            if not filename:
                return self.get_ui_state()
            raw_filepath = filename[0]
        raw_dir = os.path.dirname(raw_filepath)
        # Если сырой файл лежит прямо в папке «Chunks»/«Переменные»/«Проверенные»
        # (например, её же выбрали местом для записи) — рабочей папкой берём
        # родителя, иначе Проверенные/_Остатки создались бы ВНУТРИ Chunks и
        # засоряли бы её очередь при следующем открытии проекта.
        self.work_dir = os.path.dirname(raw_dir) if os.path.basename(raw_dir).lower() in _SCAN_EXCLUDE_SUBDIRS else raw_dir
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

        # Чистим старые дубли перед новой нарезкой, но не трогаем start/end —
        # если в эту же папку раньше уже клали эталоны для «Готовых
        # переменных», повторная нарезка не должна их стирать.
        AUDIO_EXT = ('.wav', '.mp3', '.ogg', '.flac')
        for f in os.listdir(chunks_dir):
            full_path = os.path.join(chunks_dir, f)
            if not os.path.isfile(full_path):
                continue
            clean_f = f.strip().lower()
            if clean_f.startswith(('start', 'end')) and clean_f.endswith(AUDIO_EXT):
                continue
            os.remove(full_path)

        labels_path = os.path.join(self.work_dir, 'labels.txt')
        with open(labels_path, 'w', encoding='utf-8') as label_file:
            for i, (start_ms, end_ms) in enumerate(nonsilent_ranges):
                start_adjusted = max(0, start_ms - keep_silence)
                end_adjusted = min(len(audio), end_ms + keep_silence)
                start_sec, end_sec = start_adjusted / 1000.0, end_adjusted / 1000.0
                chunk_name_no_ext = f"фраза_{i + 1:04d}"
                label_file.write(f"{start_sec}\t{end_sec}\t{chunk_name_no_ext}\n")
                # Байт в байт из исходника — без перекодирования.
                slice_or_export(raw_filepath, os.path.join(chunks_dir, f"{chunk_name_no_ext}.wav"),
                                start_adjusted, end_adjusted, audio)

                percent = int(((i + 1) / len(nonsilent_ranges)) * 100)
                try:
                    webview.windows[0].evaluate_js(
                        f"updateProgress({percent}, 'Нарезка: {i + 1} из {len(nonsilent_ranges)}');")
                except:
                    pass

        # Нарезка — это фундамент, он нужен в любом режиме. А вот что делать
        # дальше (открывать Audacity с метками или сразу собирать каскад
        # переменных) — решает пользователь на следующем экране, а не
        # программа за него. Здесь только запоминаем, куда резали.
        self._pending_chunks_dir = chunks_dir
        self._pending_raw_filepath = raw_filepath
        self._pending_labels_path = labels_path
        return {"await_mode_choice": True}

    def choose_mode_after_cut(self, mode):
        """Второй шаг после нарезки: пользователь выбрал, в каком режиме
        продолжать работать с только что нарезанными чанками."""
        chunks_dir = getattr(self, '_pending_chunks_dir', None)
        raw_filepath = getattr(self, '_pending_raw_filepath', None)
        labels_path = getattr(self, '_pending_labels_path', None)
        if not chunks_dir:
            return self.get_ui_state()

        if mode == 'premade':
            # Этому режиму Audacity с метками не нужен вообще — каскад
            # читает файлы прямо из папки Chunks и попросит start/end сам.
            return self.load_premade_variables_folder(None, chunks_dir)

        # --- ОБЫЧНЫЙ РЕЖИМ: БЕЗОПАСНАЯ ИНТЕГРАЦИЯ С AUDACITY ---
        try:
            webview.windows[0].evaluate_js("updateProgress(0, 'Запуск Audacity (подождите пару секунд)...');")
        except:
            pass

        try:
            self.audacity.send_command('New:', auto_start=True)

            # Умное ожидание загрузки Audacity: стучимся к нему, пока не ответит.
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

    def get_recent_projects(self):
        """Список недавних проектов для стартового экрана."""
        return recent_projects.list_recent()

    def clear_recent_projects(self):
        """Очистить список недавних проектов — только список, папки целы."""
        recent_projects.clear()
        return {"status": "ok"}

    def open_recent_project(self, path):
        """Быстрое продолжение недавнего проекта в один клик: без диалогов
        про Audacity — просто восстанавливаем состояние и открываем список
        дублей на том месте, где остановились."""
        if not path or not os.path.isdir(path):
            return {"error": "Папка проекта больше не найдена на диске."}

        if self.tts_is_project(path):
            return {**self.tts_open_project(path), "tts": True}

        self.work_dir = path
        self.project_name = os.path.basename(path)
        project_state.apply(self, project_state.load(path))

        # Режим VarBatch нельзя восстановить с одного диска — каскад
        # собирается заново из открытого Audacity или выбранной папки.
        # Открываем обычный список дублей как безопасный старт.
        mode = self.current_mode if self.current_mode in ('Chunks', 'Переменные', 'Проверенные') else 'Chunks'
        self.current_mode = mode

        # project_state.apply() выше уже восстановил точную позицию
        # (chunk_index/phrase_index) из сохранённого снимка — но
        # _scan_and_load_folder() ниже сама берёт позицию из state_memory,
        # а не из них, и там для текущего режима могло остаться старое
        # значение (state_memory обновляется только при переключении между
        # режимами, а не на каждом шаге). Без этой строчки только что
        # восстановленная позиция тут же затиралась дефолтной.
        self.state_memory[mode] = [self.chunk_index, self.phrase_index]

        return self._scan_and_load_folder(os.path.join(path, mode), mode)

    def load_chunks_folder(self):
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return self.get_ui_state()

        selected_path = folder[0]
        self.work_dir = os.path.dirname(selected_path) if os.path.basename(selected_path).lower() in \
            _SCAN_EXCLUDE_SUBDIRS else selected_path
        self.project_name = os.path.basename(self.work_dir)

        # Восстанавливаем сохранённый снимок проекта (тексты из Excel, номер
        # текущего дубля, режим) — если он раньше сохранялся в эту папку.
        project_state.apply(self, project_state.load(self.work_dir))

        has_tracks = False
        response = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON', auto_start=True)
        if response and 'name' in response.lower():
            has_tracks = True

        if has_tracks:
            use_existing = ui_confirm('ℹ️ <b>В Audacity уже открыт проект</b><br><br>Использовать его или создать новый?',
                                      ok='Использовать', cancel='Новый проект')
            if use_existing:
                ui_toast('Укажите ИСХОДНЫЙ WAV-файл — он нужен только для точного среза')
                raw_file = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                                 file_types=('Audio Files (*.wav)', 'All files (*.*)'))
                if raw_file:
                    self.raw_audio_full = AudioSegment.from_file(raw_file[0])
                return self._scan_and_load_folder(os.path.join(self.work_dir, 'Chunks'), 'Chunks')

        ui_toast('Выберите ИСХОДНЫЙ WAV-файл для памяти Audacity')
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
                # Если «Проверенные»/«Переменные» когда-то оказались вложены
                # прямо в эту папку (например, из старого проекта, где
                # рабочей папкой по ошибке стала сама Chunks) — не спускаемся
                # в них: это уже обработанные дубли, а не очередь.
                if root == target_folder:
                    dirs[:] = [d for d in dirs if d.lower() not in _SCAN_EXCLUDE_SUBDIRS]
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

        if mode_name in ['Переменные', 'Проверенные'] and self.phrases_data:
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

    def _audit_scan_folder(self, scan_dir):
        """Рекурсивно собирает все .wav/.mp3 в папке (кроме «мусорных»
        подпапок trash) — общая часть обоих видов аудита."""
        found_files = {}
        all_disk_files = set()
        for root_dir, _, files in os.walk(scan_dir):
            if 'trash' in root_dir.lower() or '_до_правок' in root_dir.lower():
                continue                                      # корзина и исходники правок из аудита
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
        сперва спрашивает, что сверять: весь проект (фразы + все переменные),
        только фразы Excel, все переменные или одну категорию; потом
        открывает папку на сканирование. category: 'excel' | 'all' |
        'vars' | ключ категории."""
        if category is None:
            st = getattr(self, 'tts', None) or {}
            xl = st.get("excel_path")
            return {
                "status": "choose_category",
                "categories": self._audit_available_categories(),
                "has_excel": bool(self.phrases_data),
                "studio": {"loaded": bool(xl and os.path.exists(xl)), "name": os.path.basename(xl) if xl else None,
                           "path": xl, "mtime": time.strftime('%d.%m.%Y %H:%M', time.localtime(os.path.getmtime(xl)))
                           if xl and os.path.exists(xl) else None},
            }
        if category in ('studio', 'studio_pick'):
            return self._audit_studio_start(force_pick=category == 'studio_pick')

        cats = [c["key"] for c in self._audit_available_categories()]
        if category == 'all':
            parts = (['excel'] if self.phrases_data else []) + cats
        elif category == 'vars':
            parts = cats
        elif category and category != 'excel':
            parts = [category]
        else:
            parts = ['excel']
        if 'excel' in parts and not self.phrases_data:
            return {"error": "Сначала загрузите Excel-файл с текстами (Шаг 1)!"}
        if not parts:
            return {"error": "Для этой категории в словаре переменных нет ни одного значения."}

        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}
        return self._audit_run(folder[0], parts, category or 'excel')

    # ---- аудит по таблице Студии записи: все листы (фразы, суммы, даты…) ----
    # Ожидаемые файлы — ровно те пути, куда их сохраняет Студия записи
    # (Проверенные/<имя>.wav, Значения/sum_ru/<ярус>_ru/<цифры>.wav,
    # Значения/<лист>/<категория>/<значение>.wav). Ищем во всех папках внутри
    # выбранной; совпадение — по «хвосту» пути, поэтому «5.wav» миллионов и
    # «5.wav» дня месяца не путаются, а выбрать можно корень проекта,
    # «Проверенные» или папку выше.
    def _audit_studio_start(self, force_pick=False):
        st = getattr(self, 'tts', None) or {}
        xl = st.get("excel_path")
        if force_pick or not (xl and os.path.exists(xl)):
            picked = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN, directory=os.path.dirname(xl) if xl else '',
                file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
            if not picked:
                return {"error": "cancel"}
            xl = picked if isinstance(picked, str) else picked[0]
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}
        return self._audit_studio(folder[0], xl)

    def _audit_studio_expected(self, excel_path):
        """[(rel_path, section, group_id, group_title, text, row)] по всем листам таблицы."""
        from core.tts_flow import parse_tts_workbook, text_lang
        parsed = parse_tts_workbook(excel_path)
        sheets = parsed["phrase_sheets"] or [{"title": "", "lang": "ru", "units": [], "chains": []}]
        saved = getattr(self, 'tts', None)
        saved_caches = {k: self.__dict__.get(k) for k in ('_tts_claims_cache',)}
        out, seen = [], set()
        try:
            for sh in sheets:
                # временное состояние без папки — пути выходят относительными
                self.tts = {"v": 0, "excel_path": excel_path, "sheet": sh.get("title"), "lang": sh.get("lang", "ru"),
                            "units": [dict(u) for u in sh.get("units", [])], "chains": sh.get("chains", []),
                            "var_sheets": parsed["var_sheets"], "work_dir": '', "takes": [], "index": 0}
                self._tts_ensure_value_units()
                st = self.tts
                for u in st["units"]:
                    if u.get("tiers"):
                        label = ((st["var_sheets"].get(u["sheet"]) or {}).get("label") or u["sheet"])
                        for t in u["tiers"]:
                            rel = os.path.normpath(self._tts_tier_path(u, t))
                            if rel.lower() in seen:
                                continue
                            seen.add(rel.lower())
                            out.append((rel, f"Переменные · {label}", f"var_{u['sheet']}_{t['cat']}",
                                        t.get("label") or t["cat"], t.get("text") or str(t["value"]), None))
                    elif u["kind"] != "value":
                        rel = os.path.normpath(self._tts_target(u))
                        if rel.lower() in seen:
                            continue
                        seen.add(rel.lower())
                        lang = text_lang(u.get("text")) or u.get("lang") or sh.get("lang") or 'ru'
                        lang = 'kz' if lang in ('kz', 'kk') else ('ru' if lang == 'ru' else 'other')
                        # цельные фразы и фразы с переменными (кусочки до/после суммы, даты, значения из ячейки)
                        with_var = u.get("kind") == "piece" or bool(u.get("role"))
                        text = u.get("text", '')
                        if re.fullmatch(r'фраза_\d{4}', str(u.get("name") or '')):    # название в таблице пустое
                            text = f"[в таблице нет названия — строка {u.get('row')}] {text}"
                        out.append((rel, "Фразы · С переменными" if with_var else "Фразы · Цельные",
                                    f"ph_var_{lang}" if with_var else f"ph_{lang}", self._AUDIT_LANG_TITLE[lang],
                                    text, u.get("row")))
        finally:
            self.tts = saved
            for k, v in saved_caches.items():
                if v is None:
                    self.__dict__.pop(k, None)
                else:
                    self.__dict__[k] = v
        return out

    def _audit_studio(self, scan_dir, excel_path):
        try:
            expected = self._audit_studio_expected(excel_path)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу «{os.path.basename(excel_path)}»: {e}"}
        if not expected:
            return {"error": "В таблице не нашлось ни фраз, ни переменных для записи."}
        # Выбрали папку внутри проекта («Проверенные», «Значения», «Фразы_Переменные») —
        # соседние папки проекта тоже нужны: смотрим весь проект.
        widened = None
        proj_dirs = {'проверенные', 'значения', 'фразыпеременные'}
        here = self._audit_norm_dir(os.path.basename(os.path.normpath(scan_dir)))
        parent = os.path.dirname(os.path.normpath(scan_dir))
        if here in proj_dirs and parent and os.path.isdir(parent):
            try:
                if any(self._audit_norm_dir(d) in proj_dirs - {here} for d in os.listdir(parent)):
                    widened, scan_dir = scan_dir, parent
            except OSError:
                pass
        found_files, _all = self._audit_scan_folder(scan_dir)
        cands = {}                                         # имя → [(путь, части пути от выбранной папки)]
        for f_low, paths in found_files.items():
            for pth in paths:
                rel = os.path.relpath(pth, scan_dir)
                cands.setdefault(f_low, []).append((pth, tuple(rel.lower().replace('\\', '/').split('/'))))
        st = getattr(self, 'tts', None) or {}
        root = st.get("work_dir") if st.get("excel_path") and os.path.abspath(st["excel_path"]) == os.path.abspath(excel_path) else None
        groups, order = {}, []
        missing_list, duplicates_list, files = [], [], []
        for k, (rel, section, gid, title, text, row) in enumerate(expected):
            E = tuple(rel.lower().replace('\\', '/').split('/'))
            name = E[-1]
            strict = [(p, C) for p, C in cands.get(name, []) if E[-len(C):] == C or C[-len(E):] == E]
            hits = strict or ([(p, C) for p, C in cands.get(name, [])] if gid.startswith('ph_') else [])
            if strict and root is None:                    # где корень проекта относительно выбранной папки
                p, C = strict[0]
                if len(C) <= len(E):
                    up = scan_dir
                    for _ in range(len(E) - len(C)):
                        up = os.path.dirname(os.path.normpath(up))
                    root = up
                else:
                    root = os.path.join(scan_dir, *os.path.relpath(p, scan_dir).replace('\\', '/').split('/')[:len(C) - len(E)])
            g = groups.get(gid)
            if g is None:
                g = groups[gid] = {"id": gid, "section": section, "title": title, "total": 0, "found": 0,
                                   "missing": 0, "duplicates": 0, "_rel_dir": os.path.dirname(rel), "_dirs": []}
                order.append(gid)
            g["total"] += 1
            if hits:
                g["found"] += 1
                g["_dirs"].append(os.path.dirname(hits[0][0]))
                files.append({"filename": os.path.basename(hits[0][0]), "path": hits[0][0], "text": text, "group": gid, "rel": rel})
                if len(strict) > 1:
                    g["duplicates"] += 1
                    duplicates_list.append({"filename": name, "count": len(strict), "paths": [p for p, _ in strict], "group": gid})
            else:
                g["missing"] += 1
                missing_list.append({"index": row if isinstance(row, int) else k + 1, "filename": os.path.basename(rel),
                                     "text": text, "group": gid, "_rel_dir": os.path.dirname(rel)})
        if root is None:
            root = os.path.dirname(os.path.normpath(scan_dir)) if self._audit_norm_dir(os.path.basename(os.path.normpath(scan_dir))) == 'проверенные' else scan_dir
        for m in missing_list:                             # куда сохранять каждый недостающий
            m["dir"] = os.path.join(root, m.pop("_rel_dir"))
        out_groups = []
        for gid in order:
            g = groups.pop(gid)
            dirs = g.pop("_dirs")
            rel_dir = g.pop("_rel_dir")
            g["rel_dir"] = rel_dir                         # папка категории так, как её назвала бы Студия
            if gid.startswith('ph_') and dirs:
                g["target"] = max(set(dirs), key=dirs.count)
            else:
                g["target"] = os.path.join(root, rel_dir)
            if not gid.startswith('ph_') and g["found"]:
                g["folder"] = g["target"]
            out_groups.append(g)
        # Файлы, которых нет в таблице: в тех папках, где лежат ожидаемые записи
        # (иначе в список попали бы черновики из «Записи», «Чанки» и т.п.).
        used = {os.path.normcase(f["path"]) for f in files}
        for d in duplicates_list:
            used.update(os.path.normcase(p) for p in d["paths"])
        # Лишние — во всех папках, кроме служебных (черновики записи, нарезка, кэш…)
        service = {'записи', 'чанки', 'кэш', 'суммысырые', 'фон', 'клон', 'trashаудит'}
        def is_service(pth):
            parts = os.path.relpath(os.path.dirname(pth), scan_dir).split(os.sep)
            return any(self._audit_norm_dir(x) in service or 'trash' in x.lower() for x in parts if x != '.')
        extra = []
        for f_low, paths in found_files.items():
            for pth in paths:
                if os.path.normcase(pth) not in used and not is_service(pth):
                    extra.append({"filename": os.path.basename(pth), "path": pth,
                                  "folder": os.path.relpath(os.path.dirname(pth), scan_dir)})
        extra.sort(key=lambda e: (e["folder"].lower(), e["filename"].lower()))
        # что просмотрено: папки (первые два уровня) и сколько в них записей
        seen_dirs = {}
        for paths in found_files.values():
            for pth in paths:
                rel = os.path.relpath(os.path.dirname(pth), scan_dir)
                key = '.' if rel == '.' else os.sep.join(rel.split(os.sep)[:2])
                seen_dirs[key] = seen_dirs.get(key, 0) + 1
        scanned = [{"folder": k if k != '.' else '(корень)', "files": v} for k, v in sorted(seen_dirs.items(), key=lambda kv: kv[0].lower())]
        studio_xl = st.get("excel_path")
        note = None
        if studio_xl and os.path.abspath(studio_xl) != os.path.abspath(excel_path):
            note = (f"Студия записи сейчас работает с другой таблицей — «{os.path.basename(studio_xl)}». "
                    f"Чтобы записывать по этой, загрузите её в Студии (кнопка «Таблица»).")
        self._audit_last = {"category": "studio", "missing": {m["text"] for m in missing_list}}
        files = self._audit_attach_phrases(files)
        self._audit_res = res = {
            "category": None, "category_label": None, "mode": "studio", "parts": ["studio"], "studio_excel": excel_path,
            "groups": out_groups, "can_export": False, "scan_dir": scan_dir,
            "total_excel": len(expected), "total_disk": len(files),
            "missing_count": len(missing_list), "duplicates_count": len(duplicates_list),
            "missing": missing_list, "duplicates": duplicates_list, "files": files, "can_edit": False,
            "studio_name": os.path.basename(excel_path), "extra": extra, "studio_note": note,
            "scanned": scanned, "widened": widened,
            "studio_mtime": time.strftime('%d.%m.%Y %H:%M', time.localtime(os.path.getmtime(excel_path))),
        }
        return res

    # ---- аудит по группам: Фразы (по языкам) и Переменные (по категориям) ----
    _AUDIT_KZ_LETTERS = set('әғқңөұүһіӘҒҚҢӨҰҮҺІ')

    @classmethod
    def _audit_lang(cls, name, text, header=''):
        """Язык фразы: по названию/колонке (…_kz, RU_…), иначе по буквам текста."""
        tag = f"{name} {header}".lower()
        if re.search(r'(^|[^a-zа-я])(kz|kaz|қаз|каз)([^a-zа-я]|$)', tag):
            return 'kz'
        if re.search(r'(^|[^a-zа-я])(ru|rus|рус)([^a-zа-я]|$)', tag):
            return 'ru'
        txt = str(text or '')
        if any(ch in cls._AUDIT_KZ_LETTERS for ch in txt):
            return 'kz'
        if re.search(r'[а-яё]', txt.lower()):
            return 'ru'
        return 'other' if txt.strip() else 'ru'

    _AUDIT_LANG_TITLE = {'ru': 'Русский', 'kz': 'Қазақша', 'other': 'Другие'}

    @staticmethod
    def _audit_norm_dir(name):
        return re.sub(r'[\s\-–—_.]+', '', str(name or '').lower())

    def _audit_values_base(self, base):
        """Папка листа сумм в едином формате от выбранной: «…/Значения/sum_ru»."""
        sheet = f"sum_{self._values_lang()}"
        name = self._audit_norm_dir(os.path.basename(os.path.normpath(base)))
        if name == self._audit_norm_dir(sheet):
            return base
        if name == self._audit_norm_dir(VALUES_DIR):
            return os.path.join(base, sheet)
        if name == 'проверенные':                         # выбрали «Проверенные» — «Значения» рядом
            base = os.path.dirname(os.path.normpath(base))
        return os.path.join(base, VALUES_DIR, sheet)

    def _audit_cat_dirs(self, category):
        """Как может называться папка категории: «million_ru» (единый формат),
        старое «1 - 100 млн», ключ, подпись."""
        names = {self._sum_manual_tier_dir(category), SUM_TIER_DEFAULT_DIR.get(category), category,
                 self._category_label(category)}
        return {self._audit_norm_dir(n) for n in names if n}

    def _audit_scope(self, scan_dir, category, all_cats):
        """Папка, где лежат файлы категории: сама выбранная папка, если это
        она, иначе её подпапка с именем категории. Не нашлась — вся папка,
        кроме папок других категорий (иначе «1.wav» миллионов и «1.wav»
        тенге выглядят дублями друг друга)."""
        mine = self._audit_cat_dirs(category)
        if self._audit_norm_dir(os.path.basename(os.path.normpath(scan_dir))) in mine:
            return scan_dir, set()
        hits = []
        for root_dir, dirs, _f in os.walk(scan_dir):
            for d in dirs:
                if self._audit_norm_dir(d) in mine:
                    hits.append(os.path.join(root_dir, d))
        if hits:
            hits.sort(key=lambda h: (h.count(os.sep), h))
            return hits[0], set()
        others = set()
        for c in all_cats:
            if c != category:
                others |= self._audit_cat_dirs(c)
        if self._audit_norm_dir(os.path.basename(os.path.normpath(scan_dir))) in others:
            return None, others                            # выбрана папка другой категории — здесь искать нечего
        return scan_dir, others

    @staticmethod
    def _audit_in(path, root, skip_dirs):
        if root is None:
            return False
        rel = os.path.relpath(os.path.dirname(path), root)
        if rel.startswith('..'):
            return False
        if skip_dirs and rel != '.':
            for part in rel.split(os.sep):
                if ProjectMixin._audit_norm_dir(part) in skip_dirs:
                    return False
        return True

    def _audit_run(self, scan_dir, parts, mode):
        found_files, all_disk_files = self._audit_scan_folder(scan_dir)
        entries = [(f_low, pth) for f_low, paths in found_files.items() for pth in paths]
        cats = [c for c in parts if c != 'excel']
        groups, missing_list, duplicates_list, files = [], [], [], []
        valid_total = 0

        def add_group(gid, section, title, total, found_n, miss, dups):
            groups.append({"id": gid, "section": section, "title": title, "total": total,
                           "found": found_n, "missing": miss, "duplicates": dups})

        if 'excel' in parts:
            by_lang = {}
            want = {}
            for i, p in enumerate(self.phrases_data):
                fn = str(p.get("filename") or '').strip()
                if not fn:
                    continue
                valid_total += 1
                exp = (fn if fn.lower().endswith('.wav') else f"{fn}.wav").lower()
                lang = self._audit_lang(fn, p.get("text"), p.get("category") or '')
                gid = f"ph_{lang}"
                g = by_lang.setdefault(gid, {"total": 0, "found": 0, "miss": 0, "dups": 0, "lang": lang})
                g["total"] += 1
                want[exp] = gid
                if exp not in all_disk_files:
                    missing_list.append({"index": i + 1, "filename": exp, "text": p.get("text", ""), "group": gid})
                    g["miss"] += 1
                else:
                    g["found"] += 1
                    files.append({"i": i, "filename": os.path.basename(found_files[exp][0]),
                                  "path": found_files[exp][0], "text": p.get("text", ""), "group": gid})
            for exp, gid in want.items():                       # дубли — только среди нужных названий
                paths = found_files.get(exp) or []
                if len(paths) > 1:
                    duplicates_list.append({"filename": exp, "count": len(paths), "paths": paths, "group": gid})
                    by_lang[gid]["dups"] += 1
            for lang in ('ru', 'kz', 'other'):
                g = by_lang.get(f"ph_{lang}")
                if g:
                    add_group(f"ph_{lang}", "Фразы", self._AUDIT_LANG_TITLE[lang], g["total"], g["found"], g["miss"], g["dups"])
                    # недостающее — туда же, где лежит большинство записей этого языка
                    dirs = [os.path.dirname(f["path"]) for f in files if f["group"] == f"ph_{lang}"]
                    groups[-1]["target"] = max(set(dirs), key=dirs.count) if dirs else scan_dir

        values_by_key = getattr(self, 'var_extra_tag_values', None) or {}
        all_cats = self._all_category_keys()
        for cat in cats:
            values = values_by_key.get(cat) or []
            if not values:
                continue
            root, skip = self._audit_scope(scan_dir, cat, all_cats)
            scoped = {}
            for f_low, pth in entries:
                if self._audit_in(pth, root, skip):
                    scoped.setdefault(f_low, []).append(pth)
            gid = f"var_{cat}"
            section = "Переменные · Суммы" if cat in SUM_TIER_ORDER else "Переменные"
            miss_n = found_n = 0
            names = set()
            for i, value in enumerate(values):
                name_base = self._var_value_name_base(cat, value)
                names.add(name_base)
                have = sorted({f"{name_base}.wav", f"{name_base}.mp3"} & set(scoped))
                valid_total += 1
                if have:
                    found_n += 1
                    path = scoped[have[0]][0]
                    files.append({"filename": os.path.basename(path), "path": path, "text": value, "group": gid})
                else:
                    miss_n += 1
                    missing_list.append({"index": i + 1, "filename": f"{name_base}.wav", "text": value, "group": gid})
            dups = 0
            for f_low, paths in scoped.items():
                if len(paths) > 1 and re.sub(r'\.(wav|mp3)$', '', f_low) in names:
                    dups += 1
                    duplicates_list.append({"filename": f_low, "count": len(paths), "paths": paths, "group": gid})
            add_group(gid, section, self._category_label(cat), len(values), found_n, miss_n, dups)
            groups[-1]["folder"] = root if root and not skip else None
            if groups[-1]["folder"]:
                groups[-1]["target"] = root
            else:                                          # своей папки нет — создадим в едином формате
                base = scan_dir if root else os.path.dirname(os.path.normpath(scan_dir))
                groups[-1]["target"] = os.path.join(self._audit_values_base(base), self._sum_manual_tier_dir(cat))

        single = parts[0] if len(parts) == 1 else None
        self._audit_last = {"category": single or mode, "missing": {m["text"] for m in missing_list}}
        files = self._audit_attach_phrases(files)
        pm = getattr(self, '_audit_pmap', None) or {}
        for m in missing_list:                                 # недостающее — с текстом фразы
            if str(m.get("group", '')).startswith('ph_'):
                hit = pm.get(re.sub(r'\.(wav|mp3)$', '', m["filename"].lower()))
                m["phrase"] = hit["text"] if hit else None
        if single == 'excel':
            can_export = bool(missing_list and self._excel_source_ok())
        elif single:
            template = getattr(self, 'var_template_path', None)
            can_export = bool(missing_list and template and os.path.exists(template))
        else:
            can_export = False
        self._audit_res = res = {
            "category": single if single and single != 'excel' else None,
            "category_label": self._category_label(single) if single and single != 'excel' else None,
            "mode": mode,
            "parts": parts,
            "groups": groups,
            "can_export": can_export,
            "scan_dir": scan_dir,
            "total_excel": valid_total,
            "total_disk": len(files),
            "missing_count": len(missing_list),
            "duplicates_count": len(duplicates_list),
            "missing": missing_list,
            "duplicates": duplicates_list,
            "files": files,
            "can_edit": self._excel_source_ok(),
        }
        return res

    # ---------------- текст фразы для записи по её названию ----------------

    def _audit_phrase_map(self):
        """Название файла → текст фразы и ячейка таблицы, где он лежит.
        Ищем в загруженной таблице (и в таблице экрана записи): строка, где
        стоит название, а текст — в колонке <phrase…> (без тегов — самая
        длинная фраза в этой строке)."""
        import openpyxl
        from core.tts_flow import _tag, _text_tag
        paths = []
        for pth in (getattr(self, 'excel_path', None), (getattr(self, 'tts', None) or {}).get("excel_path")):
            if pth and os.path.exists(pth) and pth not in paths:
                paths.append(pth)
        out = {}
        for pth in paths:
            try:
                wb = openpyxl.load_workbook(pth, read_only=True, data_only=True)
            except Exception:
                continue
            for ws in wb.worksheets:
                text_col = None
                for r, row in enumerate(ws.iter_rows(values_only=True), start=1):
                    cells = list(row)
                    tags = [_tag(v) for v in cells]
                    if any(_text_tag(t) for t in tags if t):
                        text_col = next(c for c, t in enumerate(tags) if t and _text_tag(t))
                        continue
                    strs = [str(v).strip() if v not in (None, '') else '' for v in cells]
                    for c, v in enumerate(strs):
                        if not v or ' ' in v or len(v) > 120:
                            continue                           # название — одним «словом»
                        key = re.sub(r'\.(wav|mp3)$', '', v.lower())
                        if key in out:
                            continue
                        tc = text_col if text_col is not None and text_col != c and text_col < len(strs) \
                            and strs[text_col] else None
                        if tc is None:
                            cands = [(len(t), k) for k, t in enumerate(strs) if k != c and t and ' ' in t]
                            tc = max(cands)[1] if cands else None
                        if tc is not None:
                            out[key] = {"text": strs[tc], "path": pth, "sheet": ws.title, "row": r, "col": tc + 1}
            wb.close()
        return out

    def _audit_attach_phrases(self, files, fresh=True):
        """К каждой записи — текст её фразы (если нашли по названию)."""
        pm = getattr(self, '_audit_pmap', None)
        if fresh or pm is None:
            try:
                pm = self._audit_pmap = self._audit_phrase_map()
            except Exception:
                pm = self._audit_pmap = {}
        for f in files:
            key = re.sub(r'\.(wav|mp3)$', '', f["filename"].lower())
            hit = pm.get(key)
            f["phrase"] = hit["text"] if hit else None
        return files

    def audit_phrase_fix(self, filename, text):
        """Исправить текст фразы записи — в той ячейке таблицы, где он лежит
        (резервная копия таблицы — один раз), и в программе."""
        import shutil
        import openpyxl
        key = re.sub(r'\.(wav|mp3)$', '', str(filename).lower())
        hit = (getattr(self, '_audit_pmap', None) or {}).get(key)
        text = str(text or '').strip()
        if not hit:
            return {"error": "Не нашёл, где в таблице текст этой фразы."}
        if not text:
            return {"error": "Пустой текст — оставил как было."}
        if text == hit["text"]:
            return {"ok": True, "text": text}
        pth = hit["path"]
        base, ext = os.path.splitext(pth)
        try:
            if not os.path.exists(f"{base}.до_правок{ext}"):
                shutil.copy2(pth, f"{base}.до_правок{ext}")
            wb = openpyxl.load_workbook(pth)
            wb[hit["sheet"]].cell(row=hit["row"], column=hit["col"]).value = text
            wb.save(pth)
        except PermissionError:
            return {"error": "Таблица открыта в Excel — закройте её и повторите."}
        except Exception as e:
            return {"error": f"Не удалось записать в таблицу: {e}"}
        old = hit["text"]
        hit["text"] = text
        for p in getattr(self, 'phrases_data', None) or []:      # и в программе
            if str(p.get("text") or '').strip() == old:
                p["text"] = text
        st = getattr(self, 'tts', None)
        if st:
            for u in st.get("units") or []:
                if str(u.get("name") or '').lower() == key:
                    u["text"] = text
            try:
                self._tts_save()
            except Exception:
                pass
        return {"ok": True, "text": text, "excel_saved": True}

    def audit_text_fix(self, i, text):
        """Поправить текст фразы из аудита: в программе и в исходной таблице
        Excel (ячейка с прежним текстом в отмеченных колонках). Перед первой
        правкой — резервная копия таблицы рядом: «<имя>.до_правок.xlsx»."""
        i = int(i)
        if not (0 <= i < len(self.phrases_data or [])):
            return {"error": "Нет такой фразы."}
        text = str(text or '').strip()
        if not text:
            return {"error": "Пустой текст — оставил как было."}
        old = str(self.phrases_data[i].get("text") or '').strip()
        if text == old:
            return {"ok": True, "text": text}
        excel_saved = False
        if self._excel_source_ok():
            import shutil
            import openpyxl
            path = self.excel_path
            base, ext = os.path.splitext(path)
            backup = f"{base}.до_правок{ext}"
            try:
                if not os.path.exists(backup):
                    shutil.copy2(path, backup)
                wb = openpyxl.load_workbook(path)
                ws = wb.active
                first = int(getattr(self, 'excel_header_row', 0) or 0) + 1
                for r in range(first, ws.max_row + 1):
                    for c in self.excel_cols:
                        cell = ws.cell(row=r, column=c + 1)
                        if cell.value not in (None, '') and str(cell.value).strip() == old:
                            cell.value = text
                            excel_saved = True
                            break
                    if excel_saved:
                        break
                if excel_saved:
                    wb.save(path)
            except PermissionError:
                return {"error": "Таблица открыта в Excel — закройте её и повторите."}
            except Exception as e:
                return {"error": f"Не удалось записать в таблицу: {e}"}
        self.phrases_data[i]["text"] = text
        return {"ok": True, "text": text, "excel_saved": excel_saved}

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
