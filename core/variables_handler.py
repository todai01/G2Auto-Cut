import os
import shutil
import json
import time
import re
import ctypes
import webview
from utils.file_utils import FileUtils
from pydub import AudioSegment, silence


class VariablesMixin:

    def send_to_audacity(self):
        """Отправляет 3 клипа в Audacity для ручного редактирования и ПРИНУДИТЕЛЬНО разворачивает его"""
        if getattr(self, 'current_mode', '') != 'VarBatch':
            return self.get_ui_state()

        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        active_idx = self.cascade_ptrs[active_cat]
        active_file = self.cascade_files[active_cat][active_idx]

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        # 1. Загружаем старт
        start_len = self._import_clip_to_track0(self.var_start_phrase, 0.0)

        # 2. Загружаем первую фразу
        phrase_len = self._import_clip_to_track0(active_file, start_len)

        # 3. Загружаем end на безопасном расстоянии (длина фразы * 2)
        end_paste_time = start_len + (phrase_len * 2)
        self._import_clip_to_track0(self.var_end_phrase, end_paste_time)

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={end_paste_time + 5.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')

        # 👇 ПРИНУДИТЕЛЬНО 8000 Гц
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True

        # --- ПЕРЕХВАТ ФОКУСА AUDACITY ---
        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        webview.windows[0].evaluate_js("showToast('✂️ Аудио отправлено на хирургический стол Audacity');")
        return self._get_var_batch_ui_state()

    def _import_clip_to_track0(self, path, paste_time):
        """Вспомогательный метод: чисто импортирует клип, измеряет его и ставит на нужную секунду"""
        if not os.path.exists(path): return 0.0

        resp_tracks = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        t_before = len(json.loads(resp_tracks[resp_tracks.find('['):resp_tracks.rfind(']') + 1])) if resp_tracks else 1

        self.audacity.send_command('SelectNone:')
        self.audacity.send_command('SelectTime: Start=0 End=0 RelativeTo=ProjectStart')
        self.audacity.send_command(f'Import2: Filename="{os.path.abspath(path).replace(chr(92), "/")}"')

        imported_track_idx = t_before
        for _ in range(15):
            time.sleep(0.1)  # Немного увеличили время ожидания для стабильности
            resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
            try:
                t_data = json.loads(resp[resp.find('['):resp.rfind(']') + 1])
                if len(t_data) > t_before:
                    imported_track_idx = len(t_data) - 1
                    break
            except: pass

        c_start, c_end = 0.0, FileUtils.get_exact_audio_duration(path)
        resp_clips = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
        try:
            c_data = json.loads(resp_clips[resp_clips.find('['):resp_clips.rfind(']') + 1])
            for t in c_data:
                if t.get('track', -1) == imported_track_idx:
                    clips = t.get('clips', [t])
                    if clips:
                        clips.sort(key=lambda x: x.get('start', 0))
                        c_start, c_end = clips[0].get('start', 0.0), clips[-1].get('end', c_end)
                        break
        except: pass

        self.audacity.send_command('SelectNone:')
        self.audacity.send_command(f'SelectTracks: Track={imported_track_idx} Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
        self.audacity.send_command('Cut:')

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={paste_time} End={paste_time} RelativeTo=ProjectStart')
        self.audacity.send_command('Paste:')

        self.audacity.send_command(f'SelectTracks: Track={imported_track_idx} Mode=Set')
        self.audacity.send_command('RemoveTracks:')

        c_name = os.path.basename(path).replace('.wav', '')
        self.audacity.send_command(f'SetClip: Name="{c_name}"')
        return c_end - c_start

    def _normalize_all_chunks(self, reference_file_path):
        """Анализирует громкость эталона и подгоняет ВСЕ оставшиеся файлы в конвейере переменных"""
        try:
            webview.windows[0].evaluate_js(
                "updateProgress(0, 'Анализ эталонной громкости...'); document.getElementById('progressContainer').style.display='block';")

            # 1. Замеряем громкость твоего идеального, только что сохраненного файла
            ref_audio = AudioSegment.from_file(reference_file_path)
            target_dbfs = ref_audio.dBFS

            # ИСПРАВЛЕНИЕ: Берем файлы напрямую из очереди конвейера, а не из жесткой папки Chunks!
            if not hasattr(self, 'cascade_files') or not self.cascade_files:
                return

            # Собираем плоский список всех файлов, которые загружены в текущий проект
            all_files_to_process = []
            for cat in self.cascade_ordered_cats:
                all_files_to_process.extend(self.cascade_files[cat])

            total = len(all_files_to_process)
            if total == 0:
                return

            # 2. Проходимся по всем файлам в очереди и выравниваем их
            for i, filepath in enumerate(all_files_to_process):
                if not os.path.exists(filepath):
                    continue

                chunk_audio = AudioSegment.from_file(filepath)

                # Защита от тишины (чтобы не пытался сделать фоновый шум громким)
                if chunk_audio.dBFS > -80.0:
                    change_in_dbfs = target_dbfs - chunk_audio.dBFS
                    normalized_audio = chunk_audio.apply_gain(change_in_dbfs)

                    # Перезаписываем исходный файл новой, нормализованной версией
                    normalized_audio.export(filepath, format="wav")

                if i % 5 == 0:
                    pct = int((i / total) * 100)
                    webview.windows[0].evaluate_js(f"updateProgress({pct}, 'Нормализация громкости: {i}/{total}...');")

            webview.windows[0].evaluate_js(
                "document.getElementById('progressContainer').style.display='none'; showToast('✅ Все переменные выровнены по громкости эталона!');")
        except Exception as e:
            print(f"Ошибка нормализации: {e}")
            webview.windows[0].evaluate_js("document.getElementById('progressContainer').style.display='none';")

    def strip_words_from_filenames(self):
        """Утилита: переименовывает файлы в выбранной папке, оставляя только цифры."""
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return

        target_dir = folder[0]
        renamed_count = 0

        try:
            # Сканируем главную папку и все её подпапки
            for root, dirs, files in os.walk(target_dir):
                for file in files:
                    if file.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                        name, ext = os.path.splitext(file)

                        # Извлекаем все цифры из названия
                        digits_only = re.sub(r'\D', '', name)

                        # Если цифры есть, и название файла содержит что-то кроме цифр (буквы, пробелы)
                        if digits_only and digits_only != name:
                            old_path = os.path.join(root, file)
                            new_path = os.path.join(root, f"{digits_only}{ext}")

                            # Переименовываем с защитой от дубликатов
                            if not os.path.exists(new_path):
                                os.rename(old_path, new_path)
                                renamed_count += 1
                            else:
                                counter = 1
                                while os.path.exists(os.path.join(root, f"{digits_only}_{counter}{ext}")):
                                    counter += 1
                                os.rename(old_path, os.path.join(root, f"{digits_only}_{counter}{ext}"))
                                renamed_count += 1

            webview.windows[0].evaluate_js(
                f"showBeautifulAlert('✅ <b>Очистка завершена!</b><br><br>Переименовано файлов: <b>{renamed_count}</b>.<br>Все текстовые приписки (миллион, тысяч и т.д.) удалены.');")

        except Exception as e:
            webview.windows[0].evaluate_js(f"showBeautifulAlert('❌ <b>Ошибка:</b><br><br>{e}');")

    def navigate_var_chunk_ui(self, direction):
        """Быстрое перелистывание индексов переменных (только для UI)"""
        if not getattr(self, 'cascade_ordered_cats', None):
            return None

        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        max_idx = len(self.cascade_files[active_cat]) - 1

        self.cascade_ptrs[active_cat] += direction

        # Ограничители (чтобы не уйти за пределы списка)
        if self.cascade_ptrs[active_cat] < 0:
            self.cascade_ptrs[active_cat] = 0
        elif self.cascade_ptrs[active_cat] > max_idx:
            self.cascade_ptrs[active_cat] = max_idx

        return self._get_var_batch_ui_state()

    def sync_var_chunk_audacity(self):
        """Если перелистываем вручную, просто сбрасываем состояние Audacity"""
        if getattr(self, 'is_in_audacity', False):
            self.audacity.send_command('SelectAll:')
            self.audacity.send_command('RemoveTracks:')
            self.is_in_audacity = False

        return self._get_var_batch_ui_state()

    def navigate_var_category(self, direction):
        """Ручное переключение между категориями (Миллионы -> Сотни -> Тысячи)"""
        if not getattr(self, 'cascade_ordered_cats', None):
            return {"error": "Конвейер не запущен"}

        max_cat_idx = len(self.cascade_ordered_cats) - 1
        new_idx = self.cascade_active_cat_idx + direction

        # Ограничители, чтобы не выйти за пределы списка категорий
        if new_idx < 0:
            new_idx = 0
        elif new_idx > max_cat_idx:
            new_idx = max_cat_idx

        if new_idx == self.cascade_active_cat_idx:
            return self._get_var_batch_ui_state()  # Категория не изменилась

        # Обновляем активный индекс
        self.cascade_active_cat_idx = new_idx
        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]

        # Очищаем рабочий стол (Track 1), так как тайминг для новой категории будет другой
        self.audacity.send_command('SelectTracks: Track=1 Mode=Set')
        self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
        self.audacity.send_command('Delete:')

        # Снимаем все выделения, чтобы не сбивать пользовательский масштаб
        self.audacity.send_command('SelectNone:')

        # Выводим красивую инструкцию пользователю
        webview.windows[0].evaluate_js(
            f"showBeautifulAlert('🔄 <b>Категория изменена на: {active_cat}</b><br><br>Перетащите первый клип этой категории с ВЕРХНЕЙ дорожки на НИЖНЮЮ (Track 1) и подгоните тайминг.');"
        )

        return self._get_var_batch_ui_state()

    def pick_file(self):
        """Вызов окна выбора файла из JS"""
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN)
        return f[0] if f else None

    def _find_reference_file(self, folder, name_prefix):
        """Ищет файл start.* или end.* в корневой папке (игнорируя пробелы)"""
        try:
            for f in os.listdir(folder):
                clean_f = f.strip().lower() # Убираем случайные пробелы
                if clean_f.startswith(name_prefix.lower()) and clean_f.endswith(('.wav', '.mp3', '.ogg', '.flac')):
                    return os.path.join(folder, f)
        except Exception:
            pass
        return None

    def pick_folder(self):
        """Вызов окна выбора папки из JS"""
        d = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        return d[0] if d else None

    def load_premade_variables_folder(self, target_hwnd, in_dir):
        """Альтернативный режим: загрузка уже готовой папки с переменными (поддержка Имен и Excel)"""

        # 1. ТРЕБОВАНИЕ EXCEL: Блокируем запуск, если нет таблицы
        if not getattr(self, 'phrases_data', None):
            return {
                "error": "Сначала загрузите Excel-файл с текстами (Шаг 1), чтобы программа понимала, какое имя сейчас обрабатывается!"}

        if target_hwnd:
            self.set_active_window(target_hwnd)

        # Автоматически ищем start.wav и end.wav
        self._pending_premade_dir = in_dir
        self._pending_start_file = self._find_reference_file(in_dir, "start")
        self._pending_end_file = self._find_reference_file(in_dir, "end")

        return self._try_finish_premade_pending()

    def _try_finish_premade_pending(self):
        """Проверяет, нашлись ли уже оба эталонных файла (start/end) для
        отложенной загрузки «Готовых переменных». Если да — запускает
        сборку каскада; если нет — сообщает фронтенду, каких файлов не
        хватает, чтобы тот предложил выбрать их или создать заново."""
        in_dir = getattr(self, '_pending_premade_dir', None)
        if not in_dir:
            return {"error": "Сессия загрузки истекла, начните заново."}

        start_f = getattr(self, '_pending_start_file', None)
        end_f = getattr(self, '_pending_end_file', None)

        if start_f and end_f:
            return self._finish_premade_load(in_dir, start_f, end_f)

        missing = [name for name, f in (('start', start_f), ('end', end_f)) if not f]
        return {"missing_start_end": True, "missing": missing}

    def pick_start_end_file(self, which):
        """Пользователь выбирает файл start/end вручную с диска."""
        if which not in ('start', 'end'):
            return {"error": "Неизвестный файл."}
        if not getattr(self, '_pending_premade_dir', None):
            return {"error": "Сессия загрузки истекла, начните заново."}

        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                  file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not f:
            return {"error": "cancel"}

        setattr(self, f'_pending_{which}_file', f[0])
        return self._try_finish_premade_pending()

    def create_start_end_from_recording(self):
        """Второй способ получить start/end: открыть исходную запись в
        Audacity и подождать, пока пользователь сам отметит на ней
        меткой «start» и меткой «end» нужные участки."""
        in_dir = getattr(self, '_pending_premade_dir', None)
        if not in_dir:
            return {"error": "Сессия загрузки истекла, начните заново."}

        raw_file = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                          file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not raw_file:
            return {"error": "cancel"}

        needed = [name for name in ('start', 'end') if not getattr(self, f'_pending_{name}_file', None)]

        try:
            self.audacity.send_command('New:', auto_start=True)
            for _ in range(15):
                resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
                if resp and '[' in resp:
                    break
                time.sleep(0.5)
            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(raw_file[0]).replace(chr(92), "/")}"')
        except Exception as e:
            return {"error": f"Не удалось открыть запись в Audacity: {e}"}

        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        self._pending_create_missing = needed
        return {"status": "waiting_labels", "missing": needed}

    def finish_create_start_end(self):
        """Пользователь отметил участки метками в Audacity — читаем их и
        экспортируем как обычные start.wav/end.wav в целевую папку."""
        in_dir = getattr(self, '_pending_premade_dir', None)
        needed = getattr(self, '_pending_create_missing', None) or ['start', 'end']
        if not in_dir:
            return {"error": "Сессия загрузки истекла, начните заново."}

        resp = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        labels = {}
        try:
            s, e = resp.find('['), resp.rfind(']')
            data = json.loads(resp[s:e + 1])
            for track in data:
                for label in track[1]:
                    text = str(label[2]).strip().lower()
                    labels[text] = (float(label[0]), float(label[1]))
        except Exception:
            return {"error": "Не удалось прочитать метки из Audacity.", "status": "waiting_labels", "missing": needed}

        still_missing = [name for name in needed if name not in labels]
        if still_missing:
            return {
                "error": f"Не найдены метки: {', '.join(still_missing)}. Выделите нужный участок, "
                         f"нажмите Ctrl+B, впишите название «{still_missing[0]}» и нажмите ОК в Audacity — "
                         f"затем снова нажмите эту кнопку.",
                "status": "waiting_labels", "missing": needed
            }

        for name in needed:
            t0, t1 = labels[name]
            target_path = os.path.abspath(os.path.join(in_dir, f'{name}.wav')).replace('\\', '/')
            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={t0} End={t1} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')
            setattr(self, f'_pending_{name}_file', target_path.replace('/', os.sep))

        return self._try_finish_premade_pending()

    def _finish_premade_load(self, in_dir, start_f, end_f):
        """Собирает каскад «Готовых переменных», когда оба эталонных файла
        (start/end) уже известны — найдены на диске, выбраны вручную или
        только что созданы из меток в Audacity."""
        self.work_dir = in_dir
        self.var_start_phrase = start_f
        self.var_end_phrase = end_f

        # 4. Сканируем папку
        self.cascade_ordered_cats = []
        self.cascade_files = {}

        # «Проверенные»/«Переменные» — собственные служебные папки программы,
        # а не категории, которые задал пользователь. Раньше их наличие
        # заставляло программу считать их единственной категорией и вообще
        # не смотреть на файлы, лежащие прямо в выбранной папке.
        OWN_OUTPUT_FOLDERS = {'проверенные', 'переменные'}
        try:
            subdirs = [d for d in os.listdir(self.work_dir)
                      if os.path.isdir(os.path.join(self.work_dir, d)) and d.lower() not in OWN_OUTPUT_FOLDERS]
            subdirs.sort()  # Сортируем по алфавиту
        except Exception as e:
            return {"error": f"Ошибка чтения папки: {e}"}

        def sort_key(filepath):
            # БЕЗОПАСНАЯ СОРТИРОВКА: Извлекаем числа из названия файла.
            basename = os.path.basename(filepath)
            nums = re.findall(r'\d+', basename)
            return (0, int(nums[0]), basename) if nums else (1, 0, basename)

        # 5. ИНТЕЛЛЕКТУАЛЬНЫЙ РЕЖИМ "ИМЕНА": Если подпапок нет, читаем плоский список файлов
        if not subdirs:
            cat_name = "Имена (Плоский список)"
            self.cascade_ordered_cats.append(cat_name)

            files = []
            for f in os.listdir(self.work_dir):
                if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                    full_p = os.path.abspath(os.path.join(self.work_dir, f))
                    # Исключаем эталонные файлы, чтобы они не попали в конвейер как имена
                    if full_p not in [os.path.abspath(start_f), os.path.abspath(end_f)]:
                        files.append(full_p)

            files.sort(key=sort_key)
            if files:
                self.cascade_files[cat_name] = [f.replace('\\', '/') for f in files]

        # 6. СТАНДАРТНЫЙ РЕЖИМ (Каскад сумм): Если есть подпапки
        else:
            for subdir in subdirs:
                if subdir not in self.cascade_ordered_cats:
                    self.cascade_ordered_cats.append(subdir)

            for cat_name in self.cascade_ordered_cats:
                cat_dir = os.path.join(self.work_dir, cat_name)
                files = [
                    os.path.join(cat_dir, f) for f in os.listdir(cat_dir)
                    if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac'))
                ]
                files.sort(key=sort_key)

                if files:
                    self.cascade_files[cat_name] = [os.path.abspath(f).replace('\\', '/') for f in files]

        # ЖЕСТКАЯ ОЧИСТКА: Удаляем категории, в которых вообще нет файлов
        self.cascade_ordered_cats = [cat for cat in self.cascade_ordered_cats if self.cascade_files.get(cat)]

        if not self.cascade_ordered_cats:
            return {"error": "В выбранной папке (или подпапках) не найдено подходящих аудиофайлов!"}

        # 7. Инициализация конвейера
        self.cascade_ptrs = {cat: 0 for cat in self.cascade_ordered_cats}
        self.cascade_active_cat_idx = 0
        self.current_mode = 'VarBatch'
        self.is_cascade_initialized = False

        # Если в «Проверенные» уже есть готовые файлы (продолжаем прошлую
        # работу, а не начинаем с нуля) — выставляем счётчик на первую
        # ещё не сделанную фразу вместо начала списка.
        resumed = self._resume_cascade_progress()

        msg = "✅ <b>Готовая папка загружена.</b><br><br>Нажмите ОК, чтобы открыть конвейер!"
        if resumed:
            msg = f"✅ <b>Готовая папка загружена.</b><br><br>Уже сделано: <b>{resumed}</b>. Продолжаем с этого места — нажмите ОК!"

        # Отправляем команду в UI и инициализируем новый проект Audacity
        webview.windows[0].evaluate_js(f"showBeautifulAlert('{msg}');")

        # Просто переходим к загрузке!
        return self.load_next_var_batch()

    def load_checked_var_to_audacity(self):
        """Загружает уже готовый файл из папки 'Проверенные' на хирургический стол Audacity"""
        if not getattr(self, 'cascade_ordered_cats', None):
            return {"error": "Конвейер не запущен"}

        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        active_idx = self.cascade_ptrs[active_cat]
        active_file = self.cascade_files[active_cat][active_idx]

        # 1. Определяем правильное имя файла (с приоритетом из Excel)
        curr_phrase_idx = getattr(self, 'phrase_index', 0)
        save_name = os.path.basename(active_file)

        if getattr(self, 'phrases_data', None) and curr_phrase_idx < len(self.phrases_data):
            excel_filename = self.phrases_data[curr_phrase_idx].get("filename")
            if excel_filename:
                save_name = str(excel_filename) if str(excel_filename).lower().endswith(
                    '.wav') else f"{excel_filename}.wav"

        save_name = re.sub(r'[<>:"/\\|?*]', '', save_name)

        # 2. Ищем файл в папке "Проверенные"
        if active_cat == "Имена (Плоский список)":
            target_dir = os.path.join(self.work_dir, 'Проверенные')
        else:
            target_dir = os.path.join(self.work_dir, 'Проверенные', active_cat)

        checked_file_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')

        if not os.path.exists(checked_file_path):
            webview.windows[0].evaluate_js(
                f"showBeautifulAlert('⚠️ <b>Файл не найден!</b><br><br>В папке Проверенные нет файла: <b>{save_name}</b>');")
            return self._get_var_batch_ui_state()

        # 3. ПОЛНОСТЬЮ ПЕРЕСОБИРАЕМ СТОЛ (Как в send_to_audacity)
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        start_len = self._import_clip_to_track0(self.var_start_phrase, 0.0)
        phrase_len = self._import_clip_to_track0(checked_file_path, start_len)
        end_paste_time = start_len + (phrase_len * 2)
        self._import_clip_to_track0(self.var_end_phrase, end_paste_time)

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(
            f'SelectTime: Start={start_len} End={start_len + phrase_len} RelativeTo=ProjectStart')

        # 👇 ПРИНУДИТЕЛЬНО 8000 Гц
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True

        # --- ПЕРЕХВАТ ФОКУСА AUDACITY ---
        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        webview.windows[0].evaluate_js("showToast('🔄 Файл загружен в Audacity для правки');")
        return self._get_var_batch_ui_state()

    def _get_var_batch_ui_state(self):
        """Вспомогательный метод для обновления UI в режиме каскада"""
        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        active_idx = self.cascade_ptrs[active_cat]
        active_file = self.cascade_files[active_cat][active_idx]
        active_name = os.path.basename(active_file)

        if not hasattr(self, 'cascade_checked_files'):
            self.cascade_checked_files = set()

        cat_checked_count = sum(1 for f in self.cascade_files[active_cat] if f in self.cascade_checked_files)
        is_checked = active_file in self.cascade_checked_files

        # --- ИНТЕГРАЦИЯ EXCEL (НЕЗАВИСИМАЯ) ---
        display_phrase_text = f"Активная категория: {active_cat}"
        custom_filename = active_name
        phrase_counter = "-"

        curr_phrase_idx = getattr(self, 'phrase_index', 0)

        if getattr(self, 'phrases_data', None) and curr_phrase_idx < len(self.phrases_data):
            excel_row = self.phrases_data[curr_phrase_idx]
            display_phrase_text = excel_row.get("text", display_phrase_text)
            if excel_row.get("filename"):
                custom_filename = excel_row["filename"]
            phrase_counter = f"{curr_phrase_idx + 1} / {len(self.phrases_data)}"

        # Проверяем наличие файла в папке "Проверенные" для зеленой подсветки
        check_name = custom_filename if custom_filename.lower().endswith('.wav') else f"{custom_filename}.wav"
        if active_cat == "Имена (Плоский список)":
            target_dir = os.path.join(self.work_dir, 'Проверенные')
        else:
            target_dir = os.path.join(self.work_dir, 'Проверенные', active_cat)

        is_done = False
        if os.path.exists(os.path.join(target_dir, check_name)):
            is_done = True

        return {
            "mode": "VarBatch",
            "screen": "varbatch",
            "var_batch_name": active_name,
            "var_batch_cat": active_cat,
            "phrase_text": display_phrase_text,
            "phrase_counter": phrase_counter,
            "custom_filename": custom_filename,
            "chunk_name": active_name,
            "chunk_counter": f"{active_idx + 1} / {len(self.cascade_files[active_cat])}",
            "has_audio": True,
            "is_done": is_done,  # Зажигаем зеленый цвет, если файл готов!
            "is_var": True,
            "is_checked": is_checked,
            "folder_name": "Проверенные" if is_done else "Переменные",
            "raw_chunk_name": active_name, "filepath": active_file,
            "stats": {"total": len(self.cascade_files[active_cat]), "good": cat_checked_count, "var": 0, "checked": 0}
        }

    def _replace_clip_in_place(self, slot_idx, new_file_path):
        """Интеллектуальная точечная замена клипа с сохранением пауз"""
        self.audacity.send_command('SelectNone:')
        m_idx = self._get_montage_track_idx()

        response = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
        try:
            tracks_data = json.loads(response[response.find('['):response.rfind(']') + 1])
        except:
            return False

        montage_clips = []
        for t in tracks_data:
            if t.get('track') == m_idx:
                if 'clips' in t:
                    montage_clips.extend(t['clips'])
                else:
                    montage_clips.append(t)
        montage_clips.sort(key=lambda x: x['start'])

        if slot_idx >= len(montage_clips):
            return False

        target_clip = montage_clips[slot_idx]
        start_sec, end_sec = target_clip['start'], target_clip['end']

        self.audacity.send_command(f'Import2: Filename="{os.path.abspath(new_file_path).replace(chr(92), "/")}"')
        time.sleep(0.4)

        resp_tracks = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        t_data = json.loads(resp_tracks[resp_tracks.find('['):resp_tracks.rfind(']') + 1])
        imported_track_idx = len(t_data) - 1

        self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={start_sec} End={end_sec} RelativeTo=ProjectStart')
        self.audacity.send_command('Delete:')

        self.audacity.send_command(f'SelectTracks: Track={imported_track_idx} Mode=Set')
        self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
        self.audacity.send_command('Copy:')

        self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={start_sec} End={start_sec} RelativeTo=ProjectStart')
        self.audacity.send_command('Paste:')

        clip_base_name = os.path.basename(new_file_path).replace('.wav', '')
        self.audacity.send_command(f'SetClip: Name="{clip_base_name}"')

        self.audacity.send_command(f'SelectTracks: Track={imported_track_idx} Mode=Set')
        self.audacity.send_command('RemoveTracks:')

        dur = FileUtils.get_exact_audio_duration(new_file_path)
        self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={start_sec} End={start_sec + dur} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        return True

    def init_variables_batch_mode(self, target_hwnd, out_dir, is_ready_export=False, sort_by_name=False):
        """Парсит Audacity, читает метки, соблюдает очередность папок и чинит баг с числами"""

        if not is_ready_export:
            # Ищем start.wav и end.wav ТОЛЬКО если нам нужна подгонка
            start_f = self._find_reference_file(out_dir, "start")
            end_f = self._find_reference_file(out_dir, "end")

            if not start_f or not end_f:
                return {
                    "error": f"В выбранной папке не найдены файлы 'start' и/или 'end'!\nУбедитесь, что они лежат прямо в папке:\n{out_dir}"
                }

            self.var_start_phrase = start_f
            self.var_end_phrase = end_f

        self.work_dir = out_dir

        if target_hwnd:
            self.set_active_window(target_hwnd)

        # 1. Читаем структуру дорожек
        resp_tracks = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        track_names = {}
        ordered_cats_raw = []
        try:
            tracks_info = json.loads(resp_tracks[resp_tracks.find('['):resp_tracks.rfind(']') + 1])
            for idx, t in enumerate(tracks_info):
                if t.get('kind') == 'wave':
                    t_idx = t.get('track', idx)
                    t_name = t.get('name', f'Дорожка_{t_idx}').strip()
                    track_names[t_idx] = t_name
                    ordered_cats_raw.append(t_name)
        except:
            return {"error": "Не удалось прочитать структуру дорожек."}

        # 2. НОВОВВЕДЕНИЕ: Читаем МЕТКИ (Labels) для умной сортировки и защиты от слепоты Audacity
        labels_info = {}
        resp_labels = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        if resp_labels:
            try:
                start_l, end_l = resp_labels.find('['), resp_labels.rfind(']')
                if start_l != -1 and end_l != -1:
                    l_data = json.loads(resp_labels[start_l:end_l + 1])
                    for track in l_data:
                        for label in track[1]:
                            l_time = float(label[0])
                            l_text = str(label[2]).strip()
                            labels_info[l_time] = l_text
            except:
                pass

        # 3. Читаем клипы
        response = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
        try:
            clips_data = json.loads(response[response.find('['):response.rfind(']') + 1])
        except:
            return {"error": "Не удалось прочитать клипы."}

        categories = {}
        for item in clips_data:
            if 'clips' in item and isinstance(item['clips'], list):
                t_idx = item.get('track', 0)
                raw_name = track_names.get(t_idx, f'Дорожка_{t_idx}')
                safe_track_name = "".join(c for c in raw_name if c not in r'<>:"/\|?*') or "Без имени"
                if safe_track_name not in categories:
                    categories[safe_track_name] = []
                for c in item['clips']:
                    c['track'] = t_idx
                    categories[safe_track_name].append(c)
            elif 'start' in item and 'end' in item:
                t_idx = item.get('track', 0)
                raw_name = track_names.get(t_idx, f'Дорожка_{t_idx}')
                safe_track_name = "".join(c for c in raw_name if c not in r'<>:"/\|?*') or "Без имени"
                if safe_track_name not in categories:
                    categories[safe_track_name] = []
                categories[safe_track_name].append(item)

        if not categories:
            return {"error": "В проекте нет аудиоклипов!"}

        self.cascade_ordered_cats = []
        for raw_name in ordered_cats_raw:
            safe_name = "".join(c for c in raw_name if c not in r'<>:"/\|?*').strip() or "Без имени"
            if safe_name in categories and safe_name not in self.cascade_ordered_cats:
                self.cascade_ordered_cats.append(safe_name)

        self.cascade_files = {}

        self.audacity.send_command('NewMonoTrack:')
        resp_tr = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        try:
            t_data = json.loads(resp_tr[resp_tr.find('['):resp_tr.rfind(']') + 1])
            temp_track_idx = len(t_data) - 1
            audio_tracks = [tr.get('track', i) for i, tr in enumerate(t_data) if tr.get('kind') == 'wave']
        except:
            temp_track_idx = 2
            audio_tracks = [0, 1, 2]

        for t_idx in audio_tracks:
            if t_idx != temp_track_idx:
                self.audacity.send_command(f'SelectTracks: Track={t_idx} Mode=Set')
                self.audacity.send_command('MuteTracks:')

        used_names_global = set()

        total_clips = sum(len(categories[cat]) for cat in self.cascade_ordered_cats)
        processed_clips = 0

        for cat_name in self.cascade_ordered_cats:
            clips = categories[cat_name]

            # 4. ПРИВЯЗЫВАЕМ МЕТКИ К КЛИПАМ ПО ТАЙМИНГУ (Погрешность 0.2 сек)
            for c in clips:
                c_start = c.get('start', 0)
                matched_label = ""
                for l_time, l_text in labels_info.items():
                    if abs(l_time - c_start) < 0.2:
                        matched_label = l_text
                        break
                c['label_text'] = matched_label

            # 5. ИНТЕЛЛЕКТУАЛЬНАЯ СОРТИРОВКА
            if sort_by_name:
                def name_sort_key(clip):
                    # Пробуем взять цифры из названия клипа. Если пусто - берем из метки!
                    text = clip.get('name', '') or clip.get('label_text', '')
                    nums = re.findall(r'\d+', text)
                    return int(nums[0]) if nums else 999999

                clips.sort(key=name_sort_key)
            else:
                clips.sort(key=lambda x: x.get('start', 0))

            cat_dir = os.path.join(self.work_dir, cat_name)
            os.makedirs(cat_dir, exist_ok=True)
            self.cascade_files[cat_name] = []

            cat_suffix = re.sub(r'[0-9\-\_]', '', cat_name).strip()

            for clip_idx, c in enumerate(clips, start=1):
                start_sec, end_sec = c['start'], c['end']

                # 6. ВЫТАСКИВАЕМ ИМЯ ДЛЯ ФАЙЛА НА ДИСКЕ
                c_name = c.get('name', '') or c.get('label_text', '')
                c_name = c_name.strip()
                c_name = re.sub(r'\.\d+$', '', c_name)
                num_only = re.sub(r'\D', '', c_name)

                if not num_only:
                    num_only = str(clip_idx)

                if cat_suffix:
                    clean_c_name = f"{num_only} {cat_suffix}"
                else:
                    clean_c_name = num_only

                final_name = clean_c_name
                counter = 1
                while final_name.lower() in used_names_global:
                    final_name = f"{clean_c_name}_{counter}"
                    counter += 1
                used_names_global.add(final_name.lower())

                target_path = os.path.join(cat_dir, final_name + '.wav')
                safe_path = os.path.abspath(target_path).replace('\\', '/')

                self.audacity.send_command(f'SelectTracks: Track={c.get("track", 0)} Mode=Set')
                self.audacity.send_command(f'SelectTime: Start={start_sec} End={end_sec} RelativeTo=ProjectStart')
                self.audacity.send_command('Copy:')

                self.audacity.send_command(f'SelectTracks: Track={temp_track_idx} Mode=Set')
                self.audacity.send_command('SelectTime: Start=0 End=0 RelativeTo=ProjectStart')
                self.audacity.send_command('Paste:')

                self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')

                self.audacity.send_command(f'SelectTracks: Track={temp_track_idx} Mode=Set')
                self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
                self.audacity.send_command('Delete:')

                self.cascade_files[cat_name].append(target_path)

                processed_clips += 1
                if processed_clips % 2 == 0:
                    percent = int((processed_clips / total_clips) * 100)
                    try:
                        webview.windows[0].evaluate_js(
                            f"updateProgress({percent}, 'Экспорт: {processed_clips} из {total_clips}...');")
                    except:
                        pass
                time.sleep(0.01)

        self.audacity.send_command(f'SelectTracks: Track={temp_track_idx} Mode=Set')
        self.audacity.send_command('RemoveTracks:')
        for t_idx in audio_tracks:
            if t_idx != temp_track_idx:
                self.audacity.send_command(f'SelectTracks: Track={t_idx} Mode=Set')
                self.audacity.send_command('UnmuteTracks:')

        if is_ready_export:
            webview.windows[0].evaluate_js(
                "showBeautifulAlert('✅ <b>Экспорт успешно завершен!</b><br><br>Все переменные нарезаны и разложены по папкам.');")
            return self.get_ui_state()
        else:
            self.cascade_ptrs = {cat: 0 for cat in self.cascade_ordered_cats}
            self.cascade_active_cat_idx = 0
            self.current_mode = 'VarBatch'
            self.is_cascade_initialized = False
            self._resume_cascade_progress()

            webview.windows[0].evaluate_js(
                "showBeautifulAlert('✅ <b>Переменные выгружены</b> (фулл-цифры сохранены).<br><br>Нажмите ОК, чтобы открыть конвейер!');")

            # Просто переходим к загрузке!
            return self.load_next_var_batch()

    def _resume_cascade_progress(self):
        """Если в «Проверенные» уже лежат готовые файлы (продолжение
        прошлой работы, а не старт с нуля) — переставляет указатель
        каскада и текущую фразу на первую ещё не сделанную позицию.

        Возвращает число уже готовых фраз (0, если продолжать нечего)."""
        if not getattr(self, 'phrases_data', None) or not getattr(self, 'cascade_ordered_cats', None):
            return 0

        checked_dir = os.path.join(self.work_dir, 'Проверенные')
        if not os.path.isdir(checked_dir):
            return 0

        existing = {f.lower() for f in os.listdir(checked_dir) if os.path.isfile(os.path.join(checked_dir, f))}
        if not existing:
            return 0

        # Считаем подряд идущие готовые фразы с самого начала списка —
        # именно в этом порядке их сохраняет save_var_batch.
        done_count = 0
        for i, p in enumerate(self.phrases_data):
            expected = p.get("filename") or f"фраза_{i + 1:04d}"
            expected_wav = (expected if expected.lower().endswith('.wav') else f"{expected}.wav").lower()
            if expected_wav in existing:
                done_count += 1
            else:
                break

        if done_count == 0:
            return 0

        self.phrase_index = min(done_count, len(self.phrases_data) - 1)

        # Отмечаем уже сохранённые дубли как «проверенные» и в памяти —
        # иначе после переоткрытия проекта воспроизведение (Пробел) играло
        # бы черновик вместо сохранённой версии, пока дубль не пересохранят.
        if not hasattr(self, 'cascade_checked_files'):
            self.cascade_checked_files = set()

        remaining = done_count
        for cat_idx, cat in enumerate(self.cascade_ordered_cats):
            files = self.cascade_files.get(cat, [])
            cat_len = len(files)
            if remaining < cat_len:
                self.cascade_checked_files.update(files[:remaining])
                self.cascade_active_cat_idx = cat_idx
                self.cascade_ptrs[cat] = remaining
                return done_count
            self.cascade_checked_files.update(files)
            remaining -= cat_len

        # Все категории уже пройдены — остаёмся на последней позиции последней
        last_cat = self.cascade_ordered_cats[-1]
        self.cascade_active_cat_idx = len(self.cascade_ordered_cats) - 1
        self.cascade_ptrs[last_cat] = max(0, len(self.cascade_files.get(last_cat, [])) - 1)
        return done_count

    def load_next_var_batch(self):
        """Супербыстрый старт. Только инициализация, без Audacity."""
        if getattr(self, 'is_cascade_initialized', False):
            return self._get_var_batch_ui_state()

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')

        self.is_cascade_initialized = True
        self.is_in_audacity = False

        webview.windows[0].evaluate_js(
            "showBeautifulAlert('⚡ <b>Супер-Конвейер запущен!</b><br><br>Слушайте склейку (Start+Имя+End) прямо в плеере (Пробел).<br>Если звучит отлично — жмите <b>Z</b> (моментально сохранится).<br>Если нужно подрезать — жмите <b>Отправить в Audacity (C)</b>.');"
        )
        return self._get_var_batch_ui_state()

    def save_var_batch(self, normalize_chunks=False):
        """Умное сохранение: либо моментальное копирование Pydub, либо экспорт из Audacity с возвратом фокуса"""
        import shutil
        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        active_idx = self.cascade_ptrs[active_cat]

        if active_idx >= len(self.cascade_files[active_cat]):
            return self._get_var_batch_ui_state()

        active_file = self.cascade_files[active_cat][active_idx]

        # --- ФОРМИРОВАНИЕ ПУТИ ---
        curr_phrase_idx = getattr(self, 'phrase_index', 0)
        save_name = os.path.basename(active_file)
        if getattr(self, 'phrases_data', None) and curr_phrase_idx < len(self.phrases_data):
            excel_filename = self.phrases_data[curr_phrase_idx].get("filename")
            if excel_filename:
                save_name = str(excel_filename) if str(excel_filename).lower().endswith('.wav') else f"{excel_filename}.wav"

        save_name = re.sub(r'[<>:"/\\|?*]', '', save_name)
        target_dir = os.path.join(self.work_dir, 'Проверенные') if active_cat == "Имена (Плоский список)" else os.path.join(self.work_dir, 'Проверенные', active_cat)
        os.makedirs(target_dir, exist_ok=True)
        safe_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')

        if os.path.exists(safe_path):
            try: os.remove(safe_path)
            except: pass

        # --- ЛОГИКА СОХРАНЕНИЯ (СУПЕР-УСКОРЕНИЕ) ---
        if getattr(self, 'is_in_audacity', False):
            # РЕЖИМ AUDACITY: Пользователь редактировал руками
            resp_clips = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
            try:
                c_data = json.loads(resp_clips[resp_clips.find('['):resp_clips.rfind(']') + 1])
                track_0_clips = []
                for t in c_data:
                    if t.get('track', -1) == 0:
                        track_0_clips.extend(t.get('clips', [t]))
                track_0_clips.sort(key=lambda x: x.get('start', 0))
            except:
                return self._get_var_batch_ui_state()

            if len(track_0_clips) < 2:
                webview.windows[0].evaluate_js("showBeautifulAlert('⚠️ <b>Ошибка!</b><br>Фраза на дорожке не найдена (удалена или склеена).');")
                return self._get_var_batch_ui_state()

            # Фраза ВСЕГДА будет вторым клипом (индекс 1)
            phrase_clip = track_0_clips[1]
            c_start, c_end = phrase_clip.get('start', 0.0), phrase_clip.get('end', 0.0)

            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')
            time.sleep(0.1)

            # Очищаем Audacity, мы закончили с ручным редактированием
            self.audacity.send_command('SelectAll:')
            self.audacity.send_command('RemoveTracks:')
            self.is_in_audacity = False

            # --- ВОЗВРАТ ФОКУСА В НАШУ ПРОГРАММУ ---
            hwnd = ctypes.windll.user32.FindWindowW(None, "G2Studio | Автосрезка")
            if hwnd:
                self._force_foreground(hwnd)
        else:
            # СУПЕРБЫСТРЫЙ РЕЖИМ: Audacity не нужен, просто копируем файл!
            shutil.copy(active_file, safe_path)

        if not hasattr(self, 'cascade_checked_files'):
            self.cascade_checked_files = set()
        self.cascade_checked_files.add(active_file)

        # --- НОРМАЛИЗАЦИЯ (Если нажата нужная кнопка) ---
        if normalize_chunks and os.path.exists(safe_path):
            self._normalize_all_chunks(safe_path)

        # --- ПЕРЕХОД К СЛЕДУЮЩЕМУ ---
        self.cascade_ptrs[active_cat] += 1
        if getattr(self, 'phrases_data', None):
            self.phrase_index += 1

        new_idx = self.cascade_ptrs[active_cat]
        next_cat_idx = self.cascade_active_cat_idx

        if new_idx >= len(self.cascade_files[active_cat]):
            next_cat_idx += 1
            new_idx = 0

        if next_cat_idx >= len(self.cascade_ordered_cats):
            webview.windows[0].evaluate_js("showBeautifulAlert('🎉 <b>Поздравляем!</b><br><br>Весь каскад успешно пройден!');")
            self.current_mode = 'Проверенные'
            return self.get_ui_state()

        if next_cat_idx != self.cascade_active_cat_idx:
            self.cascade_active_cat_idx = next_cat_idx
            webview.windows[0].evaluate_js(f"showToast('Категория изменена на: {self.cascade_ordered_cats[next_cat_idx]}');")

        # Следующий загружается просто в UI (Без вызова Audacity)
        return self._get_var_batch_ui_state()

    def build_scene_with_var(self, parts_paths, var_type, var_at_start=False):
        valid_paths = [p for p in parts_paths if p]
        var_path = self.variables.get(var_type)
        if not valid_paths or not var_path:
            return False

        seq = []
        if var_at_start:
            seq.append({'type': 'var', 'path': var_path})
            for path in valid_paths:
                seq.append({'type': 'part', 'path': path})
        else:
            for i, path in enumerate(valid_paths):
                seq.append({'type': 'part', 'path': path})
                if i == 0:
                    seq.append({'type': 'var', 'path': var_path})

        self.last_montage_sequence = seq

        self.audacity.send_command('SelectNone:')
        response = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        max_end_project = 0.0
        if response:
            try:
                start_idx, end_idx = response.find('['), response.rfind(']')
                if start_idx != -1 and end_idx != -1:
                    json_data = json.loads(response[start_idx:end_idx + 1])
                    for track in json_data:
                        for label in track[1]:
                            end_time = float(label[1])
                            if end_time > max_end_project:
                                max_end_project = end_time
            except:
                pass

        insert_time = max_end_project + 15.0
        current_paste = insert_time

        for item in seq:
            path = item['path']
            if not os.path.exists(path):
                continue

            dur = FileUtils.get_exact_audio_duration(path)
            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(path).replace(chr(92), "/")}"')
            time.sleep(0.3)
            self._move_imported_track_to_paste(current_paste)
            current_paste += dur + 0.1

        m_idx = self._get_montage_track_idx()
        self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={insert_time} End={current_paste} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')

        return True

    def load_var_file(self, var_type):
        """Загружает файл переменной в память слота"""
        file_types = ('Audio Files (*.wav;*.mp3)', 'All files (*.*)')
        filename = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not filename:
            return None

        self.variables[var_type] = filename[0]
        return {"var_type": var_type, "filename": os.path.basename(filename[0])}

    def load_variables_mode(self):
        return self._scan_and_load_folder(os.path.join(self.work_dir, 'Переменные'),
                                          'Переменные') if self.work_dir else self.get_ui_state()
    def prepare_batch_normalization(self):
        """ШАГ 1: Запрашивает папку, находит файлы и закидывает первый в Audacity как эталон"""
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        target_dir = folder[0]
        files = []
        for root, _, filenames in os.walk(target_dir):
            for f in filenames:
                if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                    files.append(os.path.join(root, f))

        if not files:
            return {"error": "В выбранной папке нет аудиофайлов!"}

        first_file = files[0]
        self.batch_norm_files = files
        self.batch_norm_first_file = first_file

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')
        self.audacity.send_command(f'Import2: Filename="{os.path.abspath(first_file).replace(chr(92), "/")}"')
        time.sleep(0.5)
        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('ZoomSel:')

        # Перехватываем фокус на Audacity
        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        return {"status": "ready", "total": len(files), "filename": os.path.basename(first_file)}

    def apply_batch_normalization(self):
        """ШАГ 2: Экспортирует эталон из Audacity, замеряет громкость и подгоняет под нее всю папку"""
        if not hasattr(self, 'batch_norm_files') or not self.batch_norm_files:
            return {"error": "Нет файлов для обработки"}

        temp_path = os.path.join(os.path.dirname(self.batch_norm_first_file), "temp_ref_norm.wav")
        safe_temp_path = os.path.abspath(temp_path).replace('\\', '/')

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command(f'Export2: Filename="{safe_temp_path}" NumChannels=1')
        time.sleep(0.6)

        if not os.path.exists(temp_path):
            return {"error": "Не удалось экспортировать эталон из Audacity."}

        try:
            ref_audio = AudioSegment.from_file(temp_path)
            target_dbfs = ref_audio.dBFS

            # Перезаписываем первый (эталонный) файл его же улучшенной копией из Audacity
            ref_audio.export(self.batch_norm_first_file, format="wav")

            total = len(self.batch_norm_files)
            for i, filepath in enumerate(self.batch_norm_files):
                if filepath == self.batch_norm_first_file:
                    continue  # Его мы уже перезаписали выше

                if not os.path.exists(filepath):
                    continue

                chunk_audio = AudioSegment.from_file(filepath)
                # Игнорируем абсолютную тишину, чтобы не выкрутить фоновый шум на максимум
                if chunk_audio.dBFS > -80.0:
                    change_in_dbfs = target_dbfs - chunk_audio.dBFS
                    normalized_audio = chunk_audio.apply_gain(change_in_dbfs)
                    normalized_audio.export(filepath, format="wav")

                if i % 5 == 0:
                    pct = int((i / total) * 100)
                    try:
                        webview.windows[0].evaluate_js(
                            f"updateProgress({pct}, 'Нормализация громкости: {i}/{total}...');")
                    except:
                        pass

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

            self.audacity.send_command('SelectAll:')
            self.audacity.send_command('RemoveTracks:')

            self.batch_norm_files = []
            return {"status": "success"}
        except Exception as e:
            return {"error": f"Ошибка нормализации: {str(e)}"}
