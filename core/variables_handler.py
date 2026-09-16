import os
import shutil
import json
import time
import re
import ctypes
import webview
from utils.file_utils import FileUtils
from pydub import AudioSegment, silence

# --- «Суммы»: особая логика каскада (Миллионы → Сотни → Тысячи → Тенге) ---
# Папка «Суммы» внутри «Готовых переменных» собирается не как обычный плоский
# список файлов, а как 4 яруса, которые проходятся по очереди «по одному шагу
# за раз» (как счётчик с несколькими разрядами): сначала Миллионы[0], потом
# Сотни[0], Тысячи[0], Тенге[0], потом снова Миллионы[1] и так далее. Когда
# ярус исчерпан (дошёл до последнего файла в своей папке) — он замораживается
# навсегда на последнем значении и больше не участвует в очереди.
SUM_TIER_ORDER = ['millions', 'hundreds', 'thousands', 'tenge']
SUM_TIER_LABELS = {
    'millions': 'Миллионы',
    'hundreds': 'Сотни (100-900)',
    'thousands': 'Тысячи',
    'tenge': 'Тенге',
}
# Ярусы с однозначным словом в названии подпапки проверяем в первую очередь;
# «Сотни» ключевым словом не ищем — слишком легко случайно совпасть с другим
# ярусом (например, «1 - 100 тенге» тоже содержит «100») — вместо этого им
# становится та подпапка, что осталась неопознанной после трёх остальных.
SUM_SPECIFIC_TIER_KEYWORDS = {
    'tenge': ['тенге', 'kzt', '₸'],
    'millions': ['миллион', 'млн'],
    'thousands': ['тысяч', 'тыс'],
}


# Папки, которые «Режим Суммы» создаёт сам по мере работы (см. ниже,
# методы sum_send_to_audacity/sum_manual_save) — в отличие от старого сценария
# выше, здесь не требуется никакой готовой папки «Суммы» на диске заранее.
SUM_TIER_DEFAULT_DIR = {
    'millions': '1 - 100 млн',
    'hundreds': '100 - 900',
    'thousands': '1 - 99 тыс',
    'tenge': '1 - 100 тенге',
}
SUM_TIER_CAP = {'millions': 100, 'hundreds': 900, 'thousands': 99, 'tenge': 100}


def _numeric_sort_key(filepath):
    """Безопасная сортировка файлов по числу в названии (дубль 2 раньше дубля 10)."""
    basename = os.path.basename(filepath)
    nums = re.findall(r'\d+', basename)
    return (0, int(nums[0]), basename) if nums else (1, 0, basename)


class VariablesMixin:

    def send_to_audacity(self):
        """Отправляет 3 клипа в Audacity для ручного редактирования и ПРИНУДИТЕЛЬНО разворачивает его"""
        if getattr(self, 'current_mode', '') != 'VarBatch':
            return self.get_ui_state()

        if self._block_if_audacity_ambiguous():
            return self._get_var_batch_ui_state()

        if not self._ensure_audacity_ready():
            webview.windows[0].evaluate_js(
                "showBeautifulAlert('⚠️ <b>Audacity не отвечает</b><br><br>Программа попробовала запустить его сама, "
                "но он не ответил. Откройте Audacity вручную и нажмите кнопку ещё раз.');")
            return self._get_var_batch_ui_state()

        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        if active_cat in getattr(self, 'sum_category_names', set()):
            return self._sum_send_to_audacity(active_cat)

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
        if getattr(self, 'is_in_audacity', False) and not self._block_if_audacity_ambiguous():
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
        self._pending_only_start = False

        return self._try_finish_premade_pending()

    def _try_finish_premade_pending(self):
        """Проверяет, нашлись ли уже эталонные файлы (start/end) для
        отложенной загрузки «Готовых переменных». Если да — запускает
        сборку каскада; если нет — сообщает фронтенду, каких файлов не
        хватает, чтобы тот предложил выбрать их или создать заново.

        Если включён режим «только start» (у пользователя нет записи
        окончания фразы), end можно не искать вовсе — дальше по коду
        отсутствующий end просто не подставляется никуда."""
        in_dir = getattr(self, '_pending_premade_dir', None)
        if not in_dir:
            return {"error": "Сессия загрузки истекла, начните заново."}

        start_f = getattr(self, '_pending_start_file', None)
        end_f = getattr(self, '_pending_end_file', None)
        only_start = getattr(self, '_pending_only_start', False)

        if start_f and (end_f or only_start):
            return self._finish_premade_load(in_dir, start_f, end_f or "")

        missing = [name for name, f in (('start', start_f), ('end', end_f)) if not f and not (only_start and name == 'end')]
        return {"missing_start_end": True, "missing": missing}

    def set_only_start_mode(self, value):
        """Пользователь отметил чекбокс «Только start, без end» — обычно
        когда есть запись только начальной фразы, а окончания попросту нет."""
        self._pending_only_start = bool(value)
        return self._try_finish_premade_pending()

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

        only_start = getattr(self, '_pending_only_start', False)
        wanted = ('start',) if only_start else ('start', 'end')
        needed = [name for name in wanted if not getattr(self, f'_pending_{name}_file', None)]

        try:
            resp = self.audacity.send_command('New:', auto_start=True)
            if not resp:
                return {"error": "Audacity не ответил при запуске. Возможно, ему нужно больше времени, "
                                  "чтобы открыться на медленном компьютере — попробуйте ещё раз."}

            for _ in range(15):
                resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
                if resp and '[' in resp:
                    break
                time.sleep(0.5)
            else:
                return {"error": "Audacity запустился, но не отвечает на команды. Проверьте, что он "
                                  "действительно открылся, и попробуйте ещё раз."}

            import_resp = self.audacity.send_command(
                f'Import2: Filename="{os.path.abspath(raw_file[0]).replace(chr(92), "/")}"')
            if not import_resp:
                return {"error": "Не удалось загрузить запись в Audacity. Проверьте, что он открылся, "
                                  "и попробуйте ещё раз."}
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

        sort_key = _numeric_sort_key

        # 5. ИНТЕЛЛЕКТУАЛЬНЫЙ РЕЖИМ "ИМЕНА": Если подпапок нет, читаем плоский список файлов
        if not subdirs:
            cat_name = "Имена (Плоский список)"
            self.cascade_ordered_cats.append(cat_name)

            # Исключаем эталонные файлы, чтобы они не попали в конвейер как имена.
            # end может отсутствовать (режим «только start») — тогда его просто нет в списке.
            reference_paths = {os.path.abspath(start_f)}
            if end_f:
                reference_paths.add(os.path.abspath(end_f))

            files = []
            for f in os.listdir(self.work_dir):
                if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')):
                    full_p = os.path.abspath(os.path.join(self.work_dir, f))
                    if full_p not in reference_paths:
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

                # «Суммы» — особая папка: внутри не файлы, а 4 подпапки-яруса
                # (Миллионы/Сотни/Тысячи/Тенге), которые собираются в
                # последовательность счётчика, а не берутся плоским списком.
                if cat_name.strip().lower() == 'суммы':
                    seq, err = self._build_sum_sequence(cat_dir)
                    if err:
                        return {"error": err}
                    self.cascade_files[cat_name] = seq['files']
                    if not hasattr(self, 'sum_category_names'):
                        self.sum_category_names = set()
                    if not hasattr(self, 'sum_meta'):
                        self.sum_meta = {}
                    if not hasattr(self, 'sum_tier_dirs'):
                        self.sum_tier_dirs = {}
                    if not hasattr(self, 'sum_tier_files'):
                        self.sum_tier_files = {}
                    self.sum_category_names.add(cat_name)
                    self.sum_meta[cat_name] = seq['meta']
                    self.sum_tier_dirs[cat_name] = seq['tier_dirs']
                    self.sum_tier_files[cat_name] = seq['tier_files']
                    continue

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

        # У «Суммы» своя, независимая от Excel логика прогресса (проверяем
        # реально сохранённые файлы по ярусам) — считаем и подставляем её
        # отдельно, поверх того, что нашла обычная функция выше.
        for cat_name in list(getattr(self, 'sum_category_names', set())):
            if cat_name not in self.cascade_ordered_cats:
                continue
            sum_done = self._sum_resume_ptr(cat_name)
            if sum_done:
                self.cascade_ptrs[cat_name] = sum_done
                if not hasattr(self, 'cascade_checked_files'):
                    self.cascade_checked_files = set()
                self.cascade_checked_files.update(self.cascade_files[cat_name][:sum_done])
                resumed = (resumed or 0) + sum_done

        msg = "✅ <b>Готовая папка загружена.</b><br><br>Нажмите ОК, чтобы открыть конвейер!"
        if resumed:
            msg = f"✅ <b>Готовая папка загружена.</b><br><br>Уже сделано: <b>{resumed}</b>. Продолжаем с этого места — нажмите ОК!"

        # Отправляем команду в UI и инициализируем новый проект Audacity
        webview.windows[0].evaluate_js(f"showBeautifulAlert('{msg}');")

        # Просто переходим к загрузке!
        return self.load_next_var_batch()

    # ==================================================================
    #  «СУММЫ»: Миллионы → Сотни → Тысячи → Тенге по одному шагу за раз
    # ==================================================================

    def _build_sum_sequence(self, sum_dir):
        """Читает 4 подпапки-яруса внутри «Суммы» и строит из них плоскую
        очередь шагов в порядке «счётчика»: по одному файлу с каждого яруса
        по кругу, пока не закончатся файлы во всех ярусах. Ярус, у которого
        файлы закончились раньше других, просто выпадает из круга и дальше
        его последнее значение используется как готовое (не пересчитывается)."""
        try:
            subdirs = [d for d in os.listdir(sum_dir) if os.path.isdir(os.path.join(sum_dir, d))]
        except Exception as e:
            return None, f"Ошибка чтения папки «Суммы»: {e}"

        assigned = {}
        remaining_dirs = list(subdirs)
        for tier, keywords in SUM_SPECIFIC_TIER_KEYWORDS.items():
            match = next((d for d in remaining_dirs if any(k in d.lower() for k in keywords)), None)
            if match:
                assigned[tier] = match
                remaining_dirs.remove(match)

        if 'hundreds' not in assigned:
            if len(remaining_dirs) == 1:
                assigned['hundreds'] = remaining_dirs[0]
            elif len(remaining_dirs) > 1:
                return None, ("Не удалось однозначно определить подпапку «Сотни (100-900)» в «Суммы» — "
                              "лишние подпапки: " + ', '.join(remaining_dirs) +
                              ". Оставьте по одной подпапке на каждый ярус.")

        missing = [t for t in SUM_TIER_ORDER if t not in assigned]
        if missing:
            names = ', '.join(SUM_TIER_LABELS[t] for t in missing)
            return None, (f"В папке «Суммы» не нашлись подпапки для яруса(-ов): {names}. "
                           f"Название подпапки должно содержать слово «миллион», «тысяч» или «тенге» "
                           f"(подпапка без такого слова считается «Сотни»).")

        tier_files, tier_dirs = {}, {}
        for tier, subdir_name in assigned.items():
            d = os.path.join(sum_dir, subdir_name)
            files = [os.path.join(d, f) for f in os.listdir(d)
                    if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac'))]
            files.sort(key=_numeric_sort_key)
            if not files:
                return None, f"В подпапке «{subdir_name}» ({SUM_TIER_LABELS[tier]}) нет аудиофайлов."
            tier_files[tier] = [os.path.abspath(f).replace('\\', '/') for f in files]
            tier_dirs[tier] = subdir_name

        consumed = {t: 0 for t in SUM_TIER_ORDER}
        frozen = {t: False for t in SUM_TIER_ORDER}
        sequence_files, sequence_meta = [], []

        while not all(frozen.values()):
            progressed = False
            for tier in SUM_TIER_ORDER:
                if frozen[tier]:
                    continue
                idx = consumed[tier]
                sequence_files.append(tier_files[tier][idx])
                sequence_meta.append({'tier': tier, 'refs': dict(consumed)})
                consumed[tier] += 1
                progressed = True
                if consumed[tier] >= len(tier_files[tier]):
                    frozen[tier] = True
            if not progressed:
                break

        return {'files': sequence_files, 'meta': sequence_meta,
                'tier_files': tier_files, 'tier_dirs': tier_dirs}, None

    def _sum_resume_ptr(self, cat_name):
        """Считает подряд идущие с начала очереди «Суммы» шаги, чьи файлы
        уже реально лежат в Проверенные — чтобы при повторном открытии
        проекта не начинать эту категорию заново."""
        files = self.cascade_files.get(cat_name, [])
        meta = self.sum_meta.get(cat_name, [])
        tier_dirs = self.sum_tier_dirs.get(cat_name, {})
        done = 0
        for f, m in zip(files, meta):
            save_name = re.sub(r'[<>:"/\\|?*]', '', os.path.basename(f))
            check_path = os.path.join(self.work_dir, 'Проверенные', cat_name, tier_dirs.get(m['tier'], ''), save_name)
            if os.path.exists(check_path):
                done += 1
            else:
                break
        return done

    def _sum_ref_files(self, cat_name, virtual_idx):
        """Для шага virtual_idx: какой ярус сейчас активный и какие уже
        сохранённые референсы с других ярусов нужно подставить рядом с ним
        (ярус, за который ещё не сохранили ни одного значения, пропускается)."""
        meta = self.sum_meta[cat_name][virtual_idx]
        active_tier = meta['tier']
        refs = meta['refs']
        tier_dirs = self.sum_tier_dirs[cat_name]
        tier_files = self.sum_tier_files[cat_name]

        result = []
        for tier in SUM_TIER_ORDER:
            if tier == active_tier:
                continue
            count = refs.get(tier, 0)
            if count <= 0:
                continue
            saved_basename = re.sub(r'[<>:"/\\|?*]', '', os.path.basename(tier_files[tier][count - 1]))
            saved_path = os.path.join(self.work_dir, 'Проверенные', cat_name, tier_dirs[tier], saved_basename)
            result.append((tier, saved_path))
        return result, active_tier

    def _sum_ordered_segments(self, cat_name, active_file, virtual_idx):
        """Полный порядок кусков для сборки в Audacity и для склейки
        превью: start, затем ярусы в фиксированном порядке (Миллионы →
        Сотни → Тысячи → Тенге) — либо уже сохранённый референс, либо
        активный ярус на этом шаге; отсутствующие ярусы пропускаются."""
        refs, active_tier = self._sum_ref_files(cat_name, virtual_idx)
        ref_by_tier = dict(refs)

        segments = []
        if getattr(self, 'var_start_phrase', None) and os.path.exists(self.var_start_phrase):
            segments.append(('start', self.var_start_phrase))
        for tier in SUM_TIER_ORDER:
            if tier == active_tier:
                segments.append(('active', active_file))
            else:
                ref_path = ref_by_tier.get(tier)
                if ref_path and os.path.exists(ref_path):
                    segments.append(('ref', ref_path))
        if getattr(self, 'var_end_phrase', None) and os.path.exists(self.var_end_phrase):
            segments.append(('end', self.var_end_phrase))
        return segments

    def _sum_build_and_send(self, cat_name, active_file, virtual_idx, toast_msg):
        """Собирает всю цепочку (start + референсы + активный ярус + end) на
        монтажном столе Audacity, запоминая, где начинается активный кусок —
        это нужно потом, при сохранении, чтобы экспортировать именно его,
        а не соседние референсы."""
        segments = self._sum_ordered_segments(cat_name, active_file, virtual_idx)

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        cursor = 0.0
        active_clip_start = None
        for kind, path in segments:
            seg_len = self._import_clip_to_track0(path, cursor)
            if kind == 'active':
                active_clip_start = cursor
            cursor += seg_len

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={cursor + 5.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True
        self._sum_active_clip_start = active_clip_start

        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        webview.windows[0].evaluate_js(f"showToast('{toast_msg}');")
        return self._get_var_batch_ui_state()

    def _sum_send_to_audacity(self, cat_name):
        virtual_idx = self.cascade_ptrs[cat_name]
        active_file = self.cascade_files[cat_name][virtual_idx]
        return self._sum_build_and_send(cat_name, active_file, virtual_idx,
                                        '✂️ Аудио отправлено на хирургический стол Audacity')

    def _sum_load_checked_to_audacity(self, cat_name):
        virtual_idx = self.cascade_ptrs[cat_name]
        active_file = self.cascade_files[cat_name][virtual_idx]
        meta = self.sum_meta[cat_name][virtual_idx]
        tier_dir = self.sum_tier_dirs[cat_name][meta['tier']]
        save_name = re.sub(r'[<>:"/\\|?*]', '', os.path.basename(active_file))
        target_dir = os.path.join(self.work_dir, 'Проверенные', cat_name, tier_dir)
        checked_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')

        if not os.path.exists(checked_path):
            webview.windows[0].evaluate_js(
                f"showBeautifulAlert('⚠️ <b>Файл не найден!</b><br><br>В папке Проверенные нет файла: <b>{save_name}</b>');")
            return self._get_var_batch_ui_state()

        if self._block_if_audacity_ambiguous():
            return self._get_var_batch_ui_state()

        return self._sum_build_and_send(cat_name, checked_path, virtual_idx,
                                        '🔄 Файл загружен в Audacity для правки')

    def _sum_save_var_batch(self, cat_name, normalize_chunks=False):
        """Сохраняет ТОЛЬКО активный (текущий) кусок — не всю склейку — в
        Проверенные/Суммы/<ярус>/, затем сдвигает очередь на следующий шаг."""
        import shutil
        virtual_idx = self.cascade_ptrs[cat_name]
        total = len(self.cascade_files[cat_name])
        if virtual_idx >= total:
            return self._get_var_batch_ui_state()

        active_file = self.cascade_files[cat_name][virtual_idx]
        meta = self.sum_meta[cat_name][virtual_idx]
        tier_dir = self.sum_tier_dirs[cat_name][meta['tier']]

        save_name = re.sub(r'[<>:"/\\|?*]', '', os.path.basename(active_file))
        target_dir = os.path.join(self.work_dir, 'Проверенные', cat_name, tier_dir)
        os.makedirs(target_dir, exist_ok=True)
        safe_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')

        if os.path.exists(safe_path):
            try: os.remove(safe_path)
            except: pass

        if getattr(self, 'is_in_audacity', False):
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

            if not track_0_clips:
                webview.windows[0].evaluate_js("showBeautifulAlert('⚠️ <b>Ошибка!</b><br>Фраза на дорожке не найдена (удалена или склеена).');")
                return self._get_var_batch_ui_state()

            # Клипов теперь может быть больше трёх (start + рефы + активный +
            # end) — ищем активный не по фиксированному индексу, а по времени
            # начала, которое запомнили при сборке на столе.
            target_start = getattr(self, '_sum_active_clip_start', None)
            phrase_clip = None
            if target_start is not None:
                for c in track_0_clips:
                    if abs(c.get('start', -999) - target_start) < 0.05:
                        phrase_clip = c
                        break
            if phrase_clip is None:
                phrase_clip = track_0_clips[min(1, len(track_0_clips) - 1)]

            c_start, c_end = phrase_clip.get('start', 0.0), phrase_clip.get('end', 0.0)
            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')
            time.sleep(0.1)

            if not self._block_if_audacity_ambiguous():
                self.audacity.send_command('SelectAll:')
                self.audacity.send_command('RemoveTracks:')
            self.is_in_audacity = False

            hwnd = ctypes.windll.user32.FindWindowW(None, "G2Studio | Автосрезка")
            if hwnd:
                self._force_foreground(hwnd)
        else:
            shutil.copy(active_file, safe_path)

        if not hasattr(self, 'cascade_checked_files'):
            self.cascade_checked_files = set()
        self.cascade_checked_files.add(active_file)

        if normalize_chunks and os.path.exists(safe_path):
            self._normalize_all_chunks(safe_path)

        self.cascade_ptrs[cat_name] += 1
        new_idx = self.cascade_ptrs[cat_name]

        if new_idx >= total:
            next_cat_idx = self.cascade_active_cat_idx + 1
            if next_cat_idx >= len(self.cascade_ordered_cats):
                webview.windows[0].evaluate_js("showBeautifulAlert('🎉 <b>Поздравляем!</b><br><br>Весь каскад успешно пройден!');")
                self.current_mode = 'Проверенные'
                return self.get_ui_state()
            self.cascade_active_cat_idx = next_cat_idx
            webview.windows[0].evaluate_js(f"showToast('Категория изменена на: {self.cascade_ordered_cats[next_cat_idx]}');")

        return self._get_var_batch_ui_state()

    def _sum_get_ui_state(self, cat_name):
        virtual_idx = self.cascade_ptrs[cat_name]
        total = len(self.cascade_files[cat_name])
        display_idx = min(virtual_idx, total - 1)
        active_file = self.cascade_files[cat_name][display_idx]
        meta = self.sum_meta[cat_name][display_idx]
        tier = meta['tier']
        tier_label = SUM_TIER_LABELS[tier]
        tier_dir = self.sum_tier_dirs[cat_name][tier]
        active_name = os.path.basename(active_file)

        if not hasattr(self, 'cascade_checked_files'):
            self.cascade_checked_files = set()
        is_checked = active_file in self.cascade_checked_files

        save_name = re.sub(r'[<>:"/\\|?*]', '', active_name)
        target_dir = os.path.join(self.work_dir, 'Проверенные', cat_name, tier_dir)
        is_done = os.path.exists(os.path.join(target_dir, save_name))

        done_count = min(virtual_idx, total)

        return {
            "mode": "VarBatch",
            "screen": "varbatch",
            "var_batch_name": active_name,
            "var_batch_cat": f"{cat_name}: {tier_label}",
            "phrase_text": f"Сумма — ярус «{tier_label}»",
            "phrase_counter": f"{done_count + 1} / {total}",
            "custom_filename": save_name.replace('.wav', ''),
            "chunk_name": active_name,
            "chunk_counter": f"{done_count + 1} / {total}",
            "has_audio": True,
            "is_done": is_done,
            "is_var": True,
            "is_checked": is_checked,
            "folder_name": "Проверенные" if is_done else "Переменные",
            "raw_chunk_name": active_name, "filepath": active_file,
            "stats": {"total": total, "good": done_count, "var": 0, "checked": 0}
        }

    def load_checked_var_to_audacity(self):
        """Загружает уже готовый файл из папки 'Проверенные' на хирургический стол Audacity"""
        if not getattr(self, 'cascade_ordered_cats', None):
            return {"error": "Конвейер не запущен"}

        active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
        if active_cat in getattr(self, 'sum_category_names', set()):
            return self._sum_load_checked_to_audacity(active_cat)

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

        if self._block_if_audacity_ambiguous():
            return self._get_var_batch_ui_state()

        if not self._ensure_audacity_ready():
            webview.windows[0].evaluate_js(
                "showBeautifulAlert('⚠️ <b>Audacity не отвечает</b><br><br>Откройте его вручную и повторите.');")
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
        if active_cat in getattr(self, 'sum_category_names', set()):
            return self._sum_get_ui_state(active_cat)

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

        # Даже если пользователь выбрал конкретное окно из списка — пайп
        # управления Audacity всё равно один на всю систему, и команды
        # могут уйти не в то окно, что выбрано визуально. Безопаснее
        # отказаться, чем читать/удалять содержимое чужого проекта.
        if self._block_if_audacity_ambiguous():
            return {"error": "cancel"}

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

        if self._block_if_audacity_ambiguous():
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
        if active_cat in getattr(self, 'sum_category_names', set()):
            return self._sum_save_var_batch(active_cat, normalize_chunks)

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

            # Очищаем Audacity, мы закончили с ручным редактированием —
            # но только если уверены, что это то самое окно: если параллельно
            # открылось ещё одно окно Audacity, лучше оставить дорожки как
            # есть, чем случайно стереть чужой проект.
            if not self._block_if_audacity_ambiguous():
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

        if self._block_if_audacity_ambiguous():
            return {"error": "cancel"}

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

            if not self._block_if_audacity_ambiguous():
                self.audacity.send_command('SelectAll:')
                self.audacity.send_command('RemoveTracks:')

            self.batch_norm_files = []
            return {"status": "success"}
        except Exception as e:
            return {"error": f"Ошибка нормализации: {str(e)}"}

    # ==================================================================
    #  «РЕЖИМ СУММЫ» (ручной): работает поверх обычной нарезки Chunks —
    #  никакой готовой папки «Суммы» заранее не нужно, программа сама
    #  создаёт папки ярусов по мере сохранения.
    # ==================================================================

    def _sum_manual_tier_root(self):
        return os.path.join(self.work_dir, 'Проверенные', 'Суммы')

    def _sum_manual_tier_dir(self, tier):
        return SUM_TIER_DEFAULT_DIR[tier]

    def _detect_sum_tier(self, text):
        """Определяет ярус по тому, что стоит после числа в тексте Excel:
        «1 млн» → Миллионы, «5 тыс» → Тысячи, «20 тенге» → Тенге,
        просто «300» без единицы → Сотни. Если единиц несколько, берём
        первую по старшинству (млн → тыс → тенге)."""
        low = (text or '').lower().replace('ё', 'е')
        if 'млн' in low or 'миллион' in low:
            return 'millions'
        if 'тыс' in low:
            return 'thousands'
        # «тг» ловим и без пробела («100тг»), но не внутри слова («отгрузка»)
        if 'тенге' in low or re.search(r'тг(?![а-яa-z])', low):
            return 'tenge'
        return 'hundreds'

    def _sum_in_cascade(self):
        return getattr(self, 'current_mode', '') == 'VarBatch' and getattr(self, 'cascade_ordered_cats', None)

    def _sum_current_source(self):
        """Кусок, с которым пользователь работает прямо сейчас. Режим «Суммы»
        одинаково работает и в обычной нарезке (очередь Chunks), и внутри
        конвейера «Готовые переменные» (активный файл каскада) — берём тот
        источник, который открыт на экране.

        Возвращает (путь, имя файла, текст ошибки)."""
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            files = self.cascade_files.get(cat, [])
            idx = self.cascade_ptrs.get(cat, 0)
            if not files:
                return None, None, f"В категории «{cat}» нет файлов."
            if idx >= len(files):
                return None, None, (f"Категория «{cat}» пройдена до конца ({len(files)} из {len(files)}). "
                                     f"Вернитесь назад клавишей A или переключите категорию.")
            return files[idx], os.path.basename(files[idx]), None

        if not getattr(self, 'chunks_data', None):
            return None, None, ("Дубли не загружены. Нарежьте сырой WAV или откройте готовую папку с дублями.")
        if self.chunk_index >= len(self.chunks_data):
            return None, None, (f"Вы в конце списка дублей ({len(self.chunks_data)} из {len(self.chunks_data)}). "
                                 f"Вернитесь назад клавишей A.")
        item = self.chunks_data[self.chunk_index]
        return item['filepath'], item['filename'], None

    def _sum_advance_pointer(self):
        """После сохранения двигаем оба конвейера — и текст Excel, и аудио."""
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            self.cascade_ptrs[cat] = self.cascade_ptrs.get(cat, 0) + 1
        else:
            self.chunk_index += 1
        if getattr(self, 'phrases_data', None):
            self.phrase_index += 1

    def _current_sum_phrase(self):
        idx = getattr(self, 'phrase_index', 0)
        if getattr(self, 'phrases_data', None) and idx < len(self.phrases_data):
            return self.phrases_data[idx]
        return None

    def _current_sum_save_name(self, fallback_name):
        """Имя файла берём из Excel (как в обычном режиме), а если его
        нет — оставляем имя самого дубля."""
        save_name = fallback_name
        phrase = self._current_sum_phrase()
        custom = (phrase or {}).get('filename')
        if custom:
            custom = str(custom)
            save_name = custom if custom.lower().endswith('.wav') else f"{custom}.wav"
        return re.sub(r'[<>:"/\\|?*]', '', save_name)

    def get_sum_manual_state(self):
        counts = getattr(self, 'sum_manual_counts', None) or {t: 0 for t in SUM_TIER_ORDER}
        phrase = self._current_sum_phrase()
        tier = self._detect_sum_tier(phrase.get('text')) if phrase else None
        return {
            "active": getattr(self, 'sum_manual_active', False),
            "counts": {SUM_TIER_LABELS[t]: counts.get(t, 0) for t in SUM_TIER_ORDER},
            "detected_tier": SUM_TIER_LABELS.get(tier),
            "detected_dir": SUM_TIER_DEFAULT_DIR.get(tier),
            "detected_from": (phrase or {}).get('text', ''),
        }

    def toggle_sum_mode(self, active):
        self.sum_manual_active = bool(active)
        if self.sum_manual_active:
            if not hasattr(self, 'sum_manual_counts'):
                self.sum_manual_counts = {}
            if not hasattr(self, 'sum_manual_last_file'):
                self.sum_manual_last_file = {}
            root = self._sum_manual_tier_root()
            os.makedirs(root, exist_ok=True)  # создаём «Суммы» сразу, не дожидаясь первого сохранения
            for tier in SUM_TIER_ORDER:
                d = os.path.join(root, self._sum_manual_tier_dir(tier))
                os.makedirs(d, exist_ok=True)
                files = [os.path.join(d, f) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
                self.sum_manual_counts[tier] = len(files)
                if files:
                    # Продолжаем прошлую работу: последний изменённый файл
                    # считаем последним сохранённым значением этого яруса.
                    files.sort(key=os.path.getmtime)
                    self.sum_manual_last_file[tier] = files[-1]
            self.sum_manual_current_tier = None
        return self.get_sum_manual_state()

    def sum_send_to_audacity(self):
        """Кнопка C в режиме «Суммы». Ярус определяется сам — по тексту
        текущей строки Excel («1 млн» → Миллионы и т.д.). На стол Audacity
        уходит: start + последние сохранённые значения ДРУГИХ ярусов (если
        они уже есть) + текущий дубль + end."""
        active_file, _, err = self._sum_current_source()
        if err:
            return {"error": err}

        phrase = self._current_sum_phrase()
        if not phrase:
            return {"error": "Сначала загрузите Excel — именно по его тексту программа понимает, "
                              "миллионы это, тысячи, тенге или сотни."}

        tier = self._detect_sum_tier(phrase.get('text'))

        if self._block_if_audacity_ambiguous():
            return self.get_ui_state()

        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        self.sum_manual_current_tier = tier

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        cursor = 0.0
        if getattr(self, 'var_start_phrase', None) and os.path.exists(self.var_start_phrase):
            cursor += self._import_clip_to_track0(self.var_start_phrase, cursor)

        active_clip_start = None
        last_file = getattr(self, 'sum_manual_last_file', {})
        for t in SUM_TIER_ORDER:
            if t == tier:
                active_clip_start = cursor
                cursor += self._import_clip_to_track0(active_file, cursor)
            else:
                ref = last_file.get(t)
                if ref and os.path.exists(ref):
                    cursor += self._import_clip_to_track0(ref, cursor)

        if getattr(self, 'var_end_phrase', None) and os.path.exists(self.var_end_phrase):
            self._import_clip_to_track0(self.var_end_phrase, cursor)
            cursor += FileUtils.get_exact_audio_duration(self.var_end_phrase)

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={cursor + 5.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True
        self._sum_active_clip_start = active_clip_start

        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        webview.windows[0].evaluate_js(f"showToast('✂️ Ярус «{SUM_TIER_LABELS[tier]}» отправлен в Audacity');")
        return self.get_ui_state()

    def sum_manual_save(self, normalize_chunks=False):
        """Сохраняет ТОЛЬКО текущий кусок. Куда именно — программа решает
        сама, разобрав текст строки Excel: «1 млн» уйдёт в папку миллионов,
        «5 тыс» — в тысячи, «20 тенге» — в тенге, просто «300» — в сотни.
        Папка создаётся сама, если её ещё нет."""
        import shutil
        active_file, source_name, err = self._sum_current_source()
        if err:
            return {"error": err}

        phrase = self._current_sum_phrase()
        if not phrase:
            return {"error": "Сначала загрузите Excel — именно по его тексту программа понимает, "
                              "миллионы это, тысячи, тенге или сотни."}

        tier = self._detect_sum_tier(phrase.get('text'))

        target_dir = os.path.join(self._sum_manual_tier_root(), self._sum_manual_tier_dir(tier))
        os.makedirs(target_dir, exist_ok=True)

        save_name = self._current_sum_save_name(source_name)
        safe_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')
        if os.path.exists(safe_path):
            try: os.remove(safe_path)
            except: pass

        if getattr(self, 'is_in_audacity', False):
            resp_clips = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
            try:
                c_data = json.loads(resp_clips[resp_clips.find('['):resp_clips.rfind(']') + 1])
                track_0_clips = []
                for t in c_data:
                    if t.get('track', -1) == 0:
                        track_0_clips.extend(t.get('clips', [t]))
                track_0_clips.sort(key=lambda x: x.get('start', 0))
            except:
                return self.get_ui_state()

            if not track_0_clips:
                webview.windows[0].evaluate_js("showBeautifulAlert('⚠️ <b>Ошибка!</b><br>Кусок на дорожке не найден (удалён или склеен).');")
                return self.get_ui_state()

            # Клипов на дорожке может быть больше двух (start + рефы других
            # ярусов + активный + end) — ищем активный по времени начала,
            # которое запомнили при сборке, а не по фиксированному индексу.
            target_start = getattr(self, '_sum_active_clip_start', None)
            phrase_clip = None
            if target_start is not None:
                for c in track_0_clips:
                    if abs(c.get('start', -999) - target_start) < 0.05:
                        phrase_clip = c
                        break
            if phrase_clip is None:
                phrase_clip = track_0_clips[min(1, len(track_0_clips) - 1)]

            c_start, c_end = phrase_clip.get('start', 0.0), phrase_clip.get('end', 0.0)
            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')
            time.sleep(0.1)

            if not self._block_if_audacity_ambiguous():
                self.audacity.send_command('SelectAll:')
                self.audacity.send_command('RemoveTracks:')
            self.is_in_audacity = False

            hwnd = ctypes.windll.user32.FindWindowW(None, "G2Studio | Автосрезка")
            if hwnd:
                self._force_foreground(hwnd)
        else:
            shutil.copy(active_file, safe_path)

        if normalize_chunks and os.path.exists(safe_path):
            self._normalize_all_chunks(safe_path)

        if not hasattr(self, 'sum_manual_counts'):
            self.sum_manual_counts = {t: 0 for t in SUM_TIER_ORDER}
        if not hasattr(self, 'sum_manual_last_file'):
            self.sum_manual_last_file = {}
        self.sum_manual_counts[tier] = self.sum_manual_counts.get(tier, 0) + 1
        self.sum_manual_last_file[tier] = safe_path

        # Потолок теперь только предупреждает, а не запрещает: ярус выбирается
        # не вручную, а по тексту Excel, и жёсткий запрет просто остановил бы
        # работу на лишней строке, не дав обходного пути.
        cap = SUM_TIER_CAP.get(tier)
        if cap and self.sum_manual_counts[tier] >= cap:
            webview.windows[0].evaluate_js(
                f"showToast('⚠️ Ярус «{SUM_TIER_LABELS[tier]}» дошёл до потолка ({cap}) — проверьте, всё ли верно в таблице.');")

        self.sum_manual_current_tier = None
        self._sum_advance_pointer()

        return self.get_ui_state()

    def save_sum_leftover(self):
        """Если автонарезка слепила несколько цифр в один дубль («2 тысячи
        сто одна тенге») — выделите в Audacity оставшуюся часть (ту, что не
        сохранили как активный кусок) и нажмите эту кнопку. Она экспортирует
        текущее выделение и ставит его следующим дублем в очередь, чтобы
        не потерять при последующей очистке стола."""
        if not getattr(self, 'is_in_audacity', False):
            return {"error": "Сначала отправьте дубль в Audacity кнопкой C."}

        leftover_dir = os.path.join(self.work_dir, '_Остатки')
        os.makedirs(leftover_dir, exist_ok=True)
        name = f'остаток_{int(time.time() * 1000)}.wav'
        target_path = os.path.abspath(os.path.join(leftover_dir, name)).replace('\\', '/')

        resp = self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')
        if not resp or not os.path.exists(target_path):
            return {"error": "Не удалось сохранить остаток — убедитесь, что в Audacity выделен нужный участок, и повторите."}

        # Ставим остаток следующим в ту очередь, которая сейчас открыта
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            self.cascade_files.setdefault(cat, []).insert(self.cascade_ptrs.get(cat, 0) + 1, target_path)
        else:
            self.chunks_data.insert(self.chunk_index + 1, {'filepath': target_path, 'filename': name})

        webview.windows[0].evaluate_js("showToast('💾 Остаток сохранён и добавлен в очередь следующим дублем');")
        return self.get_ui_state()
