import os
import shutil
import json
import time
import re
import ctypes
import webview
from utils.file_utils import FileUtils
from utils.wav_io import export_like
from pydub import AudioSegment, silence
from core import project_state

# Папки-«служебные» имена: если пользователь выбрал одну из них саму,
# рабочей папкой проекта берём её родителя, а не её саму — иначе
# «Суммы_сырые»/«Проверенные» создавались бы вложенными друг в друга.
_STAGE1_SCAN_EXCLUDE = {'chunks', 'переменные', 'проверенные', 'суммы_сырые'}

# --- «Суммы»: особая логика каскада (Миллионы → Сотни тысяч → Сотни →
#     Тысячи → Тенге) ---
# Папка «Суммы» внутри «Готовых переменных» собирается не как обычный плоский
# список файлов, а как яруса, которые проходятся по очереди «по одному шагу
# за раз» (как счётчик с несколькими разрядами): сначала Миллионы[0], потом
# Сотни тысяч[0], Сотни[0], Тысячи[0], Тенге[0], потом снова Миллионы[1] и
# так далее. Когда ярус исчерпан (дошёл до последнего файла в своей папке) —
# он замораживается навсегда на последнем значении и больше не участвует в
# очереди. Именно на этом и держится переход «после потолка»: как только
# «Сотни (100-900)» и «Тысячи (1-99 тыс.)» упираются в свой потолок и
# замораживаются, в очереди сами по себе остаются только Миллионы, Сотни
# тысяч и Тенге — например «100 миллионов, 900, 99 тысяч, 100 тенге» на
# первом этапе, а дальше «100 миллионов, 100 тысяч, 100 тенге», «200 тысяч»,
# «300 тысяч» и т.д. на втором.
SUM_TIER_ORDER = ['millions', 'hundred_thousands', 'hundreds', 'thousands', 'tenge']
SUM_TIER_LABELS = {
    'millions': 'Миллионы',
    'hundred_thousands': 'Сотни тысяч (100-900 тыс.)',
    'hundreds': 'Сотни (100-900)',
    'thousands': 'Тысячи (1-99 тыс.)',
    'tenge': 'Тенге',
}
# Ярусы с однозначным словом в названии подпапки проверяем в первую очередь;
# «Сотни» ключевым словом не ищем — слишком легко случайно совпасть с другим
# ярусом (например, «1 - 100 тенге» тоже содержит «100») — вместо этого им
# становится та подпапка, что осталась неопознанной после остальных.
# «Тысячи» здесь нет — у «1-99 тыс.» и «100-900 тыс.» одно и то же ключевое
# слово «тыс», их различает не слово, а число в названии папки/тексте
# (см. _thousands_subtier).
SUM_SPECIFIC_TIER_KEYWORDS = {
    'tenge': ['тенге', 'kzt', '₸'],
    'millions': ['миллион', 'млн'],
}


# Папки, которые «Режим Суммы» создаёт сам по мере работы (см. ниже,
# методы sum_send_to_audacity/sum_manual_save) — в отличие от старого сценария
# выше, здесь не требуется никакой готовой папки «Суммы» на диске заранее.
SUM_TIER_DEFAULT_DIR = {
    'millions': '1 - 100 млн',
    'hundred_thousands': '100 - 900 тыс',
    'hundreds': '100 - 900',
    'thousands': '1 - 99 тыс',
    'tenge': '1 - 100 тенге',
}
SUM_TIER_CAP = {'millions': 100, 'hundred_thousands': 900, 'hundreds': 900, 'thousands': 99, 'tenge': 100}

# Ровно две логики звучания суммы — переключаются кнопкой в интерфейсе,
# программа между ними больше не выбирает сама (ни по тексту Excel, ни по
# тому, дошли ли «Сотни»/«Тысячи» до потолка). Ярус, которого нет в списке
# активной логики, просто не участвует — ни в сборке звука, ни в счётчиках.
SUM_LOGIC_1_TIERS = ['millions', 'hundreds', 'thousands', 'tenge']
SUM_LOGIC_2_TIERS = ['millions', 'hundred_thousands', 'tenge']

# Слово яруса, которое дописываем обратно к «голому» числу на экране
# (сам файл на диске остаётся без слов — см. _sum_bare_digits_name).
# «Сотни» — без слова: в тексте Excel эта сумма и раньше была голым
# числом, дописывать нечего.
SUM_TIER_WORD = {
    'millions': 'млн',
    'hundred_thousands': 'тыс',
    'hundreds': '',
    'thousands': 'тыс',
    'tenge': 'тенге',
}


def _thousands_subtier(text):
    """«Тысячи» разбиты на два яруса с одним и тем же словом в названии —
    различаем их по числу: «100» и больше — это «Сотни тысяч» (100-900 тыс.,
    новый ярус для крупных сумм), «1-99» — обычные «Тысячи». Число ищем в
    любом тексте, где уже подтверждено слово «тыс» (текст Excel или название
    подпапки)."""
    nums = re.findall(r'\d+', text or '')
    if nums and int(nums[0]) >= 100:
        return 'hundred_thousands'
    return 'thousands'


def _numeric_sort_key(filepath):
    """Безопасная сортировка файлов по числу в названии (дубль 2 раньше дубля 10)."""
    basename = os.path.basename(filepath)
    nums = re.findall(r'\d+', basename)
    return (0, int(nums[0]), basename) if nums else (1, 0, basename)


# --- «Словарь переменных»: загружаемая таблица вроде RU.xlsx, где первая
#     строка — заголовки колонок. <tag> в заголовке — это категория
#     переменной (сортируем сырьё в неё, потом собираем эталон рулеткой),
#     обычное слово без скобок (start, start_2, start_3...) — связка,
#     фиксированная фраза-«клей» между переменными, ей нужен один
#     озвученный аудиофайл на весь проект. Порядок колонок слева направо —
#     это и есть порядок склейки финального файла.
#
# Пять «сумменных» тегов узнаём по имени и заворачиваем в уже отлаженную
# каскадную систему (SUM_TIER_ORDER/Логика 1-2) без изменений — там
# принципиально другая механика (потолки, чередование, сборка на слух).
# Любой другой <tag> (например <mark>, <year>, <day>, <month>) — новая
# самостоятельная категория: копится всё, что в неё отправили, без
# потолка и без выбора логики, участвует в тех же рулетках.
_SUM_TAG_PATTERNS = [
    ('hundred_thousand', 'hundred_thousands'),
    ('thousand', 'thousands'),
    ('hundred', 'hundreds'),
    ('million', 'millions'),
    ('tenge', 'tenge'),
]

# Человеческие подписи для уже известных доп.категорий — остальные
# показываем просто по ключу из таблицы (<company> -> "company").
_VAR_EXTRA_LABELS = {
    'mark': 'Марка',
    'year': 'Год',
    'day': 'День',
    'month': 'Месяц',
}

_VAR_TAG_RE = re.compile(r'^<(.+)>$')


def _match_sum_tag(tag_key):
    low = tag_key.lower()
    for pattern, internal in _SUM_TAG_PATTERNS:
        if pattern in low:
            return internal
    return None


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
                    export_like(normalized_audio, filepath, filepath)

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
        """Альтернативный режим: загрузка уже готовой папки с переменными.

        Excel не обязателен: если его нет, имена файлов при сохранении
        берутся из самих файлов на диске (см. _get_var_batch_ui_state и
        остальной код каскада — везде phrases_data проверяется через
        getattr и просто пропускается, если Excel не загружен)."""
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

        # Раньше тут был свой отдельный запуск Audacity с одной попыткой
        # 'New:' и фиксированным таймаутом — на медленном компьютере
        # холодный старт (особенно первый запуск после перезагрузки) не
        # укладывался в него, и команда уходила в пустоту без импорта.
        # _ensure_audacity_ready() — тот же проверенный запуск с долгим
        # опросом (до ~30 секунд), что используют остальные кнопки
        # «Отправить в Audacity» по всей программе.
        if self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы продолжить."}
        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        try:
            self.audacity.send_command('New:')

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

                # «Суммы» — особая папка: внутри не файлы, а подпапки-яруса
                # (Миллионы/Сотни тысяч/Сотни/Тысячи/Тенге), которые
                # собираются в последовательность счётчика, а не берутся
                # плоским списком.
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
        """Читает подпапки-яруса внутри «Суммы» и строит из них плоскую
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

        # Обе «тысячные» подпапки содержат слово «тыс» — различаем их по
        # числу в названии (см. _thousands_subtier): «100 - 900 тыс» это
        # Сотни тысяч, «1 - 99 тыс» это обычные Тысячи.
        for d in [d for d in remaining_dirs if 'тыс' in d.lower()]:
            tier = _thousands_subtier(d)
            if tier not in assigned:
                assigned[tier] = d
                remaining_dirs.remove(d)

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
                           f"Название подпапки должно содержать слово «миллион» или «тенге», для тысяч — "
                           f"слово «тыс» и число (до 99 — «Тысячи», от 100 — «Сотни тысяч») "
                           f"(подпапка без всего этого считается «Сотни»).")

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

            hwnd = self._get_own_hwnd()
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
            hwnd = self._get_own_hwnd()
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

    # ==================================================================
    #  «СЛОВАРЬ ПЕРЕМЕННЫХ»: разбор загруженной таблицы (см. константы
    #  _SUM_TAG_PATTERNS/_VAR_EXTRA_LABELS выше) на категории и связки.
    # ==================================================================

    def load_var_template(self):
        """Загружает таблицу-словарь переменных (первая строка — заголовки:
        <tag> = категория, обычное слово = связка). Пять сумменных тегов
        уходят в существующую систему SUM_TIER_ORDER как есть, остальные
        становятся новыми категориями (self.var_extra_tags), связки —
        слотами под один аудиофайл каждая (self.var_connectors)."""
        file_types = ('Excel files (*.xlsx)', 'All files (*.*)')
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not picked:
            return {"error": "cancel"}

        import openpyxl
        try:
            wb = openpyxl.load_workbook(picked[0], data_only=True)
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(picked[0])}\n\n"
                             f"Поддерживается только формат .xlsx.\n\nПодробности: {e}"}

        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return {"error": "Таблица пустая."}

        header = rows[0]
        data_rows = rows[1:]

        columns = []
        extra_tags = []
        connectors = []
        seen_tags = set()
        extra_tag_col = {}  # tag_key -> номер колонки (для сбора списка значений ниже)
        sum_tag_col = {}    # то же самое, но для 5 ярусов Суммы — у них в
                             # таблице тоже есть готовый список значений
                             # (1-100 млн, 100-900 тыс и т.д.)

        transcript_cols = []  # (ключ категории, номер колонки) — транскрипции кириллицей
        last_tag_key = None
        for col_idx, cell in enumerate(header):
            text = str(cell).strip() if cell is not None else ''
            if not text:
                continue
            # Колонка транскрипции («<mark_транскрипция>» или просто
            # «Транскрипция» сразу после колонки категории) — не связка и не
            # категория: это то, как значение звучит, для автопроверки.
            if re.search(r'транскрип|transcri', text, re.I):
                inner = text.strip('<> ')
                base = re.sub(r'[_\s]*(транскрип\w*|transcri\w*)$', '', inner, flags=re.I).strip()
                base_key = (_match_sum_tag(base) or base) if base else last_tag_key
                if base_key:
                    transcript_cols.append((base_key, col_idx))
                continue
            m = _VAR_TAG_RE.match(text)
            if m:
                tag_key = m.group(1).strip()
                sum_internal = _match_sum_tag(tag_key)
                last_tag_key = sum_internal or tag_key
                if sum_internal:
                    columns.append({"type": "sum", "key": sum_internal, "tag": tag_key, "col_idx": col_idx})
                    sum_tag_col.setdefault(sum_internal, col_idx)
                else:
                    columns.append({"type": "tag", "key": tag_key, "col_idx": col_idx})
                    if tag_key not in seen_tags:
                        seen_tags.add(tag_key)
                        extra_tags.append({"key": tag_key, "label": _VAR_EXTRA_LABELS.get(tag_key, tag_key)})
                        extra_tag_col[tag_key] = col_idx
            else:
                # Связка (start/start_2/...) — подпись берём из первой
                # непустой ячейки данных под этой колонкой (сама колонка
                # в шапке называется просто "start"/"start_2", это не то,
                # что нужно озвучивать).
                label = text
                for r in data_rows:
                    if col_idx < len(r) and r[col_idx] not in (None, ''):
                        label = str(r[col_idx]).strip()
                        break
                columns.append({"type": "connector", "key": text, "col_idx": col_idx})
                connectors.append({"key": text, "label": label, "path": None})

        if not columns:
            return {"error": "Не нашёл ни одной подписанной колонки в первой строке таблицы."}

        # Список значений на каждую категорию — доп. и ярусы Суммы одинаково
        # — в порядке появления в таблице, без повторов. Автоматически
        # присваиваем их сырым дублям по порядку отправки (см.
        # sum_stage1_send), вместо того чтобы спрашивать у юзера, какое
        # именно значение он услышал.
        extra_tag_values = {}
        for tag_key, col_idx in {**extra_tag_col, **sum_tag_col}.items():
            seen_vals = set()
            values = []
            for r in data_rows:
                if col_idx < len(r) and r[col_idx] not in (None, ''):
                    v = str(r[col_idx]).strip()
                    if v not in seen_vals:
                        seen_vals.add(v)
                        values.append(v)
            extra_tag_values[tag_key] = values

        # Сами строки таблицы, категория -> значение — для восстановления
        # КОНКРЕТНОЙ строки целиком (марка+год+суммы вместе, как реально
        # написано в этой одной строке), а не только списка уникальных
        # значений по каждой колонке отдельно (тот не хранит, какое
        # значение с каким было в паре). Строка без значений вообще
        # (пустая разделительная строка в Excel) пропускается.
        template_rows = []
        for r in data_rows:
            row_map = {}
            for col in columns:
                if col['type'] == 'connector':
                    continue
                idx = col['col_idx']
                if idx < len(r) and r[idx] not in (None, ''):
                    row_map[col['key']] = str(r[idx]).strip()
            if row_map:
                template_rows.append(row_map)

        self.var_template_columns = columns
        self.var_extra_tags = extra_tags
        self.var_extra_tag_values = extra_tag_values
        self.var_connectors = connectors
        self.var_template_rows = template_rows
        self.var_template_path = picked[0]
        self.sum_stage2_row_idx = 0

        transcripts = {}
        for base_key, t_idx in transcript_cols:
            v_idx = extra_tag_col.get(base_key, sum_tag_col.get(base_key))
            if v_idx is None:
                continue
            for r in data_rows:
                v = r[v_idx] if v_idx < len(r) else None
                t = r[t_idx] if t_idx < len(r) else None
                if v not in (None, '') and t not in (None, ''):
                    transcripts.setdefault(base_key, {})[str(v).strip()] = str(t).strip()
        self.var_transcripts = transcripts

        found = self._var_find_connector_files([os.path.dirname(picked[0])])
        return {
            "file_name": os.path.basename(picked[0]),
            "columns": [{"type": c["type"], "key": c.get("tag", c["key"])} for c in columns],
            "extra_tags": extra_tags,
            "connectors": connectors,
            "connector_suggestions": self._var_connector_suggestions_payload(found),
            "transcripts": {self._category_label(k): len(v) for k, v in transcripts.items()},
        }

    @staticmethod
    def _var_norm_name(text):
        return re.sub(r'[\s_\-]+', ' ', (text or '').lower().replace('ё', 'е')).strip()

    def _var_find_connector_files(self, folders):
        """Ищет готовые файлы для ещё не заполненных связок: файл, чьё имя
        совпадает с ключом колонки («start.wav», «start_2.wav», «end.wav»)
        или с её текстом («на автомобиль.wav»). Смотрим саму папку и её
        подпапки на один уровень; файлы верхнего уровня важнее."""
        missing = [c for c in (getattr(self, 'var_connectors', None) or [])
                   if not c.get('path') or not os.path.exists(c['path'])]
        if not missing:
            return {}
        by_name = {}
        for folder in dict.fromkeys(folders):
            if not folder or not os.path.isdir(folder):
                continue
            for root, dirs, files in os.walk(folder):
                if os.path.relpath(root, folder) != '.':
                    dirs[:] = []
                for f in sorted(files):
                    if f.lower().endswith(('.wav', '.mp3')):
                        by_name.setdefault(self._var_norm_name(os.path.splitext(f)[0]), os.path.join(root, f))
        found = {}
        for c in missing:
            for cand in (c['key'], c.get('label')):
                n = self._var_norm_name(cand)
                if n and n in by_name:
                    found[c['key']] = by_name[n]
                    break
        return found

    def _var_connector_suggestions_payload(self, found):
        self._var_connector_suggestions = found
        if not found:
            return []
        labels = {c['key']: c.get('label') or c['key'] for c in (getattr(self, 'var_connectors', None) or [])}
        return [{"key": k, "label": labels.get(k, k), "file": os.path.basename(p), "path": p}
                for k, p in found.items()]

    def apply_var_connector_suggestions(self, accept):
        """Ответ юзера на «Нашёл файлы связок — подставить?»."""
        found = getattr(self, '_var_connector_suggestions', None) or {}
        self._var_connector_suggestions = {}
        if accept and found:
            for c in (getattr(self, 'var_connectors', None) or []):
                if c['key'] in found:
                    c['path'] = found[c['key']]
            # Файлы связок, лежащие среди дублей, — не дубли: убираем из ленты.
            norm = lambda p: os.path.normcase(os.path.abspath(p))
            used = {norm(p) for p in found.values()}
            chunks = getattr(self, 'chunks_data', None) or []
            if any(norm(ch['filepath']) in used for ch in chunks):
                current = chunks[self.chunk_index]['filepath'] if self.chunk_index < len(chunks) else None
                self.chunks_data = [ch for ch in chunks if norm(ch['filepath']) not in used]
                idx = next((i for i, ch in enumerate(self.chunks_data) if ch['filepath'] == current), 0)
                self.chunk_index = min(idx, max(0, len(self.chunks_data) - 1))
        state = self.get_ui_state()
        state["connectors"] = getattr(self, 'var_connectors', [])
        return state

    def set_var_connector_audio(self, key):
        """Выбор озвученного файла для одной связки (например «на автомобиль»)."""
        file_types = ('Audio files (*.wav;*.mp3)', 'All files (*.*)')
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, file_types=file_types)
        if not picked:
            return {"error": "cancel"}
        for c in getattr(self, 'var_connectors', []):
            if c['key'] == key:
                c['path'] = picked[0]
                break
        return {"connectors": getattr(self, 'var_connectors', [])}

    def create_var_connectors_from_recording(self):
        """Тот же способ, что уже работает для start/end (см.
        create_start_end_from_recording): открываем полную исходную запись
        в Audacity, пользователь сам расставляет метки (Ctrl+B) — по одной
        на каждую связку, имя метки должно точно совпадать с её ключом
        (start/start_2/start_3 — как в шапке таблицы). Один заход в
        Audacity сразу на все связки, а не по одной."""
        needed = [c['key'] for c in getattr(self, 'var_connectors', [])]
        if not needed:
            return {"error": "В таблице нет связок для озвучки."}

        raw_file = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                          file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not raw_file:
            return {"error": "cancel"}

        if self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы продолжить."}
        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        try:
            self.audacity.send_command('New:')
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

        self._pending_var_conn_out_dir = os.path.join(os.path.dirname(raw_file[0]), 'Переменные_связки')
        return {"status": "waiting_labels", "needed": needed}

    def finish_var_connectors_from_recording(self):
        """Пользователь расставил метки — читаем их и экспортируем каждую
        в отдельный файл (Переменные_связки/<ключ>.wav рядом с исходной
        записью), назначая путь связке."""
        needed = [c['key'] for c in getattr(self, 'var_connectors', [])]
        out_dir = getattr(self, '_pending_var_conn_out_dir', None)
        if not out_dir:
            return {"error": "Сессия истекла — нажмите «Найти метками» заново."}

        resp = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        labels = {}
        try:
            s, e = resp.find('['), resp.rfind(']')
            data = json.loads(resp[s:e + 1])
            for track in data:
                for label in track[1]:
                    text = str(label[2]).strip()
                    labels[text] = (float(label[0]), float(label[1]))
        except Exception:
            return {"error": "Не удалось прочитать метки из Audacity.", "status": "waiting_labels", "needed": needed}

        # Раньше нехватка хоть одной метки блокировала всё целиком — теперь
        # экспортируем всё, что нашлось, а по недостающим даём выбор:
        # либо продолжить без них (загрузить потом отдельным файлом через
        # обычную кнопку «Загрузить»), либо вернуться в Audacity и
        # доставить метку, нажав эту же кнопку ещё раз.
        found = [name for name in needed if name in labels]
        still_missing = [name for name in needed if name not in labels]

        if found:
            os.makedirs(out_dir, exist_ok=True)
        for name in found:
            t0, t1 = labels[name]
            target_path = os.path.abspath(os.path.join(out_dir, f'{name}.wav')).replace('\\', '/')
            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={t0} End={t1} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')
            for c in self.var_connectors:
                if c['key'] == name:
                    c['path'] = target_path.replace('/', os.sep)

        return {"connectors": self.var_connectors, "missing": still_missing}

    def get_var_template_state(self):
        return {
            "extra_tags": getattr(self, 'var_extra_tags', []),
            "connectors": getattr(self, 'var_connectors', []),
        }

    # ==================================================================
    #  «РЕЖИМ СУММЫ» (ручной): работает поверх обычной нарезки Chunks —
    #  никакой готовой папки «Суммы» заранее не нужно, программа сама
    #  создаёт папки ярусов по мере сохранения.
    # ==================================================================

    def _sum_manual_tier_root(self):
        return os.path.join(self.work_dir, 'Проверенные', 'Суммы')

    def _sum_manual_tier_dir(self, tier):
        # Доп.категории из словаря переменных (mark/year/...) не входят в
        # SUM_TIER_DEFAULT_DIR — для них папку называем просто по ключу.
        return SUM_TIER_DEFAULT_DIR.get(tier, tier)

    def _sum_tier_capped(self, tier, counts=None):
        """Ярус дошёл до потолка (см. SUM_TIER_CAP) и больше не растёт —
        например «Сотни (100-900)» и «Тысячи (1-99 тыс.)» после перехода
        сумм за миллион. Такой ярус не должен попадать в новую сборку
        (ни справочным клипом в Audacity, ни как «сосед» для автоправки),
        иначе туда лез бы устаревший файл из старой, уже закрытой суммы."""
        if counts is None:
            counts = getattr(self, 'sum_manual_counts', None) or {}
        cap = SUM_TIER_CAP.get(tier)
        return cap is not None and counts.get(tier, 0) >= cap

    def _sum_last_saved_file(self, tier):
        """Последний сохранённый файл яруса — берёт из кэша в памяти
        (sum_manual_last_file), а если там пусто (например, галочка «Режим
        «Суммы»» была включена ещё до того, как в папке яруса появились
        файлы, и с тех пор кэш не обновлялся) — подстраховкой смотрит
        прямо на диск, в саму папку яруса. Так уже сохранённые ярусы всегда
        попадают в предпрослушку и на стол Audacity, даже если кэш в
        памяти отстал от реальных файлов на диске."""
        cached = getattr(self, 'sum_manual_last_file', {}).get(tier)
        if cached and os.path.exists(cached):
            return cached
        d = os.path.join(self._sum_manual_tier_root(), self._sum_manual_tier_dir(tier))
        try:
            files = [os.path.join(d, f) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
        except OSError:
            return None
        if not files:
            return None
        files.sort(key=os.path.getmtime)
        latest = files[-1]
        if not hasattr(self, 'sum_manual_last_file'):
            self.sum_manual_last_file = {}
        self.sum_manual_last_file[tier] = latest
        return latest

    def _sum_active_logic_tiers(self):
        return SUM_LOGIC_2_TIERS if getattr(self, 'sum_manual_stage2', False) else SUM_LOGIC_1_TIERS

    def _var_extra_tag_keys(self):
        return [t['key'] for t in getattr(self, 'var_extra_tags', [])]

    def _var_extra_tag_label(self, key):
        for t in getattr(self, 'var_extra_tags', []):
            if t['key'] == key:
                return t['label']
        return key

    def _all_category_keys(self):
        """Все категории, для которых вообще может существовать сырая
        папка — 5 ярусов Суммы (независимо от выбранной логики, чтобы
        переключение Логика 1/2 не теряло уже отсортированное) плюс
        доп.категории из загруженного словаря переменных."""
        return SUM_TIER_ORDER + self._var_extra_tag_keys()

    def _active_category_keys(self):
        """Категории, которые сейчас показываем на экране сортировки и по
        которым идёт каскад финальной сборки (sum_stage2_*) — строго в
        том порядке, в каком колонки идут в самой загруженной таблице
        (марка → год → суммы, как в RU.xlsx), а не «сначала суммы, потом
        доп.категории», как было раньше. Без словаря (чистый режим
        «Суммы» без Excel) — все пять ярусов по порядку.

        Логик 1/2 здесь больше нет: видны все категории, а что попадёт в
        сборку, решает строка таблицы."""
        columns = getattr(self, 'var_template_columns', None)
        if not columns:
            return list(SUM_TIER_ORDER)

        order, seen = [], set()
        for col in columns:
            if col['type'] == 'connector':
                continue
            key = col['key']
            if key in seen:
                continue
            order.append(key)
            seen.add(key)
        return order

    def _category_label(self, key):
        if key in SUM_TIER_LABELS:
            return SUM_TIER_LABELS[key]
        return self._var_extra_tag_label(key)

    @staticmethod
    def _var_safe_value(value):
        return re.sub(r'[<>:"/\\|?*]', ' ', value).strip()

    def _var_value_name_base(self, tier, value):
        """Имя файла (без расширения), под которым значение лежит в
        Проверенных — то же правило, что и в _sum_stage2_resolve_value."""
        clean = re.sub(r'[<>:"/\\|?*]', '', value).strip()
        base = re.sub(r'\D', '', clean) if tier in SUM_TIER_ORDER else clean
        return (base or clean).lower()

    def _var_expected_value(self, tier):
        """Значение из таблицы, которое получит следующий отправленный в
        категорию дубль, и его номер в списке.

        Раньше это было «N-е значение, где N — сколько файлов уже лежит в
        сырой папке», и любой лишний/удалённый/уже сохранённый в эталон
        файл сдвигал всю очередь. Теперь — первое значение, начиная с
        курсора категории, для которого ещё НЕТ записи ни в сырой папке,
        ни в Проверенных. Удалили бракованную запись — её значение снова
        «не записано» и ожидается заново; курсор можно переставить на
        любое место списка (sum_set_expected_value). Если записано всё —
        отдаём значение под курсором (перезапись дублем)."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(tier) or []
        if not values:
            return None, None
        raw = {self._sum_raw_value_from_path(p)
               for p in (getattr(self, 'constructor_tier_files', None) or {}).get(tier, [])}
        checked_dir = os.path.join(self._sum_manual_tier_root(), self._sum_manual_tier_dir(tier))
        try:
            checked = {os.path.splitext(f)[0].lower() for f in os.listdir(checked_dir)}
        except OSError:
            checked = set()

        start = (getattr(self, 'var_expected_cursor', None) or {}).get(tier, 0) % len(values)
        for off in range(len(values)):
            i = (start + off) % len(values)
            v = values[i]
            if self._var_safe_value(v) in raw or self._var_value_name_base(tier, v) in checked:
                continue
            return v, i
        return values[start], start

    def _var_set_cursor(self, tier, idx):
        if not hasattr(self, 'var_expected_cursor') or self.var_expected_cursor is None:
            self.var_expected_cursor = {}
        self.var_expected_cursor[tier] = idx

    def _var_rewind_cursor_to(self, tier, raw_path):
        """После удаления записи — ожидаем снова именно её значение."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(tier) or []
        removed = self._sum_raw_value_from_path(raw_path)
        for i, v in enumerate(values):
            if self._var_safe_value(v) == removed:
                self._var_set_cursor(tier, i)
                return

    def sum_set_expected_value(self, tier, value):
        """Юзер сам выбрал, с какого значения таблицы продолжать запись в
        этой категории (например, начать с середины списка). Заодно
        переключает сборку эталона на первую строку с этим значением."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(tier) or []
        if value not in values:
            return {"error": f"В таблице нет значения «{value}» для этой категории."}
        self._var_set_cursor(tier, values.index(value))
        rows = getattr(self, 'var_template_rows', None) or []
        for i, r in enumerate(rows):
            if r.get(tier) == value:
                self.sum_stage2_row_idx = i
                break
        return self.get_ui_state()

    def sum_remove_raw(self, tier, raw_path):
        """Убрать запись из категории. Если это последняя отправка — тот
        же откат, что и «Отменить» (дубль возвращается в очередь). Иначе
        просто удаляет бракованный сырой файл. В обоих случаях его
        значение снова становится ожидаемым — список не «уезжает»."""
        last = getattr(self, 'sum_stage1_last_send', None)
        if last and last.get('raw_path') == raw_path:
            return self.sum_stage1_undo()

        files = (getattr(self, 'constructor_tier_files', None) or {}).get(tier, [])
        if raw_path not in files:
            return {"error": "Эта запись уже убрана из категории."}
        try:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        except OSError as e:
            return {"error": f"Не удалось удалить файл: {e}"}
        files.remove(raw_path)
        self._sum_forget_source(raw_path)
        self._var_rewind_cursor_to(tier, raw_path)

        value = self._sum_raw_value_from_path(raw_path)
        msg = f"🗑 Убрано из «{self._category_label(tier)}»: {value} — жду его заново"
        msg_js = msg.replace('\\', '\\\\').replace("'", "\\'")
        webview.windows[0].evaluate_js(f"showToast('{msg_js}');")
        return self.get_ui_state()

    def sum_unassign(self, tier, path):
        """«×» на метке дубля: отменить то, что из него записано. Сырое —
        как «брак» (sum_remove_raw). Эталон в Проверенных — файл уходит в
        «_Корзина» проекта (можно вернуть руками), значение снова ожидается,
        а сборка переходит на строку с этим значением, чтобы переделать."""
        files = (getattr(self, 'constructor_tier_files', None) or {}).get(tier, [])
        if path in files:
            return self.sum_remove_raw(tier, path)
        if not path or not os.path.exists(path):
            # Метка ссылается на уже удалённый сырой файл — ищем его эталон.
            found, saveable = self._sum_stage2_resolve_value(tier, self._sum_raw_value_from_path(path or ''))
            self._sum_forget_source(path)
            if not found or saveable:
                return self.get_ui_state()
            path = found
        trash = os.path.join(self.work_dir, '_Корзина')
        os.makedirs(trash, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(trash, f"{stem}_{int(time.time())}{ext}")
        try:
            shutil.move(path, dest)
        except OSError as e:
            return {"error": f"Не удалось убрать эталон: {e}"}
        self._sum_forget_source(path)
        counts = getattr(self, 'sum_stage2_counts', None) or {}
        if counts.get(tier):
            counts[tier] -= 1
        if (getattr(self, 'sum_manual_last_file', None) or {}).get(tier) == path:
            self.sum_manual_last_file.pop(tier, None)
        self._var_rewind_cursor_to(tier, path)
        value = self._sum_raw_value_from_path(path)
        for i, r in enumerate(getattr(self, 'var_template_rows', None) or []):
            if self._var_safe_value(str(r.get(tier) or '')) == value:
                self.sum_stage2_row_idx = i
                self._sum_row_pinned = i
                break
        msg = f"🗑 Эталон «{value}» убран из Проверенных (лежит в _Корзина) — жду его заново"
        webview.windows[0].evaluate_js(f"showToast({json.dumps(msg, ensure_ascii=False)});")
        return self.get_ui_state()

    def _sum_asr_match(self, tier, value):
        """Автонавигация: дубль, в котором автопроверка услышала именно это
        значение (ещё не разобранный), — лучший по совпадению."""
        if not value:
            return None
        results = getattr(self, 'sum_asr_results', None) or {}
        if not results:
            return None
        files, _ = self._sum_source_files()
        pos = {p: i for i, p in enumerate(files)}
        assigned = self._sum_assigned_sources()
        best = None
        for p, r in results.items():
            if not r or r.get('tier') != tier or r.get('best') != value or p not in pos or p in assigned:
                continue
            if best is None or (r.get('score') or 0) > best['score']:
                best = {"index": pos[p], "name": os.path.splitext(os.path.basename(p))[0],
                        "score": r.get('score') or 0, "confident": bool(r.get('confident'))}
        return best

    def _sum_tier_excluded(self, tier, counts=None):
        """Ярус пропускаем при сборке звучания суммы (и при поиске «соседа»
        для подрезки) ровно в одном случае — если он не входит в выбранную
        логику («Логика 1»: Миллионы+Сотни+Тысячи+Тенге, «Логика 2»:
        Миллионы+Сотни тысяч+Тенге). Потолок (900/99/100) — это только
        предупреждение при сохранении (см. sum_manual_save), сборку звука
        он больше не трогает: ярус, который уже накопил 100+ сохранений с
        прошлых сессий, всё равно продолжает звучать своим последним
        значением, пока входит в активную логику."""
        return tier not in self._sum_active_logic_tiers()

    def _sum_next_cycle_tier(self):
        """Следующий ярус по очереди активной логики (Логика 1:
        Миллионы→Сотни→Тысячи→Тенге, Логика 2: Миллионы→Сотни тысяч→Тенге),
        как счётчик — не завязан на текст Excel вообще."""
        active = self._sum_active_logic_tiers()
        idx = getattr(self, 'sum_manual_cycle_idx', 0) % len(active)
        return active[idx]

    def _sum_advance_cycle(self, tier):
        """Сдвигает очередь на шаг ВПЕРЁД от того яруса, который только что
        сохранили — даже если ярус определился по слову в тексте, а не по
        самой очереди. Так очередь сама подстраивается под ручную правку."""
        active = self._sum_active_logic_tiers()
        if tier in active:
            self.sum_manual_cycle_idx = (active.index(tier) + 1) % len(active)

    def _detect_sum_tier(self, text):
        """Определяет ярус текущей строки. Если в тексте Excel явно
        написано слово единицы — «1 млн» → Миллионы, «5 тыс» → Тысячи,
        «100 тыс» → Сотни тысяч (100-900 тыс.), «20 тенге» → Тенге —
        используем его. Слов в тексте может не быть вовсе (голые числа —
        именно так теперь ведут Excel): тогда ярус берём по очереди —
        какой шаг активной логики сейчас идёт по счёту (Миллионы, затем
        следующий ярус и т.д.), а не гадаем по числу."""
        low = (text or '').lower().replace('ё', 'е')
        if 'млн' in low or 'миллион' in low:
            return 'millions'
        if 'тыс' in low:
            return _thousands_subtier(low)
        # «тг» ловим и без пробела («100тг»), но не внутри слова («отгрузка»)
        if 'тенге' in low or re.search(r'тг(?![а-яa-z])', low):
            return 'tenge'
        return self._sum_next_cycle_tier()

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

    @staticmethod
    def _sum_bare_digits_name(name):
        """Имя файла для папки яруса «Суммы»: только цифры + расширение —
        то же самое, что делает утилита «Очистить названия файлов», но
        сразу при сохранении, а не отдельным шагом после."""
        stem, ext = os.path.splitext(name)
        digits = re.sub(r'\D', '', stem)
        return f"{digits}{ext}" if digits else name

    def _sum_display_label(self, tier, filepath):
        """Текст для экрана по уже сохранённому файлу яруса. Файл на диске
        хранится «голым» числом (см. _sum_bare_digits_name) — здесь слово
        яруса («млн», «тыс», «тенге») дописывается обратно по тому, в какой
        папке лежит файл, а не по самому числу. Старые файлы, сохранённые
        ещё до этого изменения (имя не только из цифр), показываем как
        есть — трогать их не нужно."""
        stem = os.path.splitext(os.path.basename(filepath))[0]
        if stem.isdigit():
            word = SUM_TIER_WORD.get(tier, '')
            return f"{stem} {word}".strip() if word else stem
        return stem

    def _sum_full_preview_segments(self):
        """Для проигрывания в режиме «Суммы»: не только то, что открыто на
        экране, а вся цепочка целиком — start + уже сохранённые ярусы (в
        порядке Миллионы→Сотни→Тысячи→Тенге) + текущий, ещё не сохранённый,
        ярус + end. Каждый сегмент несёт подпись для экрана: у уже
        сохранённых ярусов это их имя файла (= исходный текст Excel), у
        текущего — текст строки Excel прямо сейчас. start/end подписи не
        получают — экран во время них не переключается."""
        segments = []
        if getattr(self, 'var_start_phrase', None) and os.path.exists(self.var_start_phrase):
            segments.append({'label': None, 'path': self.var_start_phrase})

        phrase = self._current_sum_phrase()
        tier = self._detect_sum_tier(phrase.get('text')) if phrase else None
        active_file, _, err = self._sum_current_source()

        for t in SUM_TIER_ORDER:
            if t == tier and not err and active_file:
                label = (phrase.get('text') if phrase else '').strip() or SUM_TIER_LABELS[t]
                segments.append({'label': label, 'path': active_file})
            elif not self._sum_tier_excluded(t):
                ref = self._sum_last_saved_file(t)
                if ref and os.path.exists(ref):
                    label = self._sum_display_label(t, ref)
                    segments.append({'label': label, 'path': ref})

        if getattr(self, 'var_end_phrase', None) and os.path.exists(self.var_end_phrase):
            segments.append({'label': None, 'path': self.var_end_phrase})

        return segments

    def get_sum_manual_state(self):
        files, ptr = self._sum_source_files()
        if files and 0 <= ptr < len(files):
            self.sum_last_dub = os.path.basename(files[ptr])
        counts = getattr(self, 'sum_manual_counts', None) or {t: 0 for t in SUM_TIER_ORDER}
        last_file = getattr(self, 'sum_manual_last_file', {})
        phrase = self._current_sum_phrase()
        tier = self._detect_sum_tier(phrase.get('text')) if phrase else None
        # Ярусы АКТИВНОЙ логики Суммы + доп.категории из словаря переменных
        # (mark/year/...), если он загружен — у них нет понятия «логика»,
        # участвуют всегда, наравне с ярусами.
        active_tiers = self._active_category_keys()

        # Для карточки статистики (клик по счётчикам): по каждому ярусу
        # ВЫБРАННОЙ логики — сколько сохранено, сколько осталось до потолка
        # и на каком числе юзер остановился в последний раз (берём из имени
        # сохранённого файла — это и есть исходный текст из Excel). Ярусы
        # другой логики не показываем — они сейчас не участвуют в работе.
        stats = []
        for t in active_tiers:
            done = counts.get(t, 0)
            cap = SUM_TIER_CAP.get(t)
            last_path = last_file.get(t)
            last_label = self._sum_display_label(t, last_path) if last_path else None
            stats.append({
                "tier": self._category_label(t),
                "dir": SUM_TIER_DEFAULT_DIR.get(t, t),
                "done": done,
                "cap": cap,
                "remaining": max(0, cap - done) if cap else None,
                "last": last_label,
            })

        # «Готово» — общий счётчик поверх всех ярусов сразу (одна строка
        # вместо разбивки по каждому), сколько всего сумм уже собрано и
        # сохранено из общего числа строк Excel.
        done_total = sum(counts.get(t, 0) for t in active_tiers)
        excel_total = len(getattr(self, 'phrases_data', None) or [])

        result = {
            "active": getattr(self, 'sum_manual_active', False),
            "stage2": getattr(self, 'sum_manual_stage2', False),
            "done_total": done_total,
            "excel_total": excel_total,
            "active_tiers": [{"key": t, "label": self._category_label(t)} for t in active_tiers],
            "counts": {self._category_label(t): counts.get(t, 0) for t in active_tiers},
            "detected_tier": SUM_TIER_LABELS.get(tier),
            "detected_dir": SUM_TIER_DEFAULT_DIR.get(tier),
            "detected_from": (phrase or {}).get('text', ''),
            "stats": stats,
            "reels": self._sum_stage2_state(),
            "dubs": self._sum_dub_cards(),
        }
        return result

    def toggle_sum_stage2(self, active):
        """Кнопка «Логика 2»: Миллионы + Сотни тысяч + Тенге, без «Сотни» и
        «Тысячи» — включается вручную, а не по достижению потолка (900/99),
        потому что до конца доходить не обязательно. Имя sum_manual_stage2
        осталось историческим — это переключатель ЛОГИКИ (какой набор
        ярусов участвует), не отдельный экран/этап."""
        self.sum_manual_stage2 = bool(active)
        return self.get_sum_manual_state()

    def toggle_sum_mode(self, active):
        self.sum_manual_active = bool(active)
        if self.sum_manual_active:
            if not hasattr(self, 'sum_manual_counts'):
                self.sum_manual_counts = {}
            if not hasattr(self, 'sum_manual_last_file'):
                self.sum_manual_last_file = {}
            root = self._sum_manual_tier_root()
            os.makedirs(root, exist_ok=True)  # создаём «Суммы» сразу, не дожидаясь первого сохранения
            for tier in self._all_category_keys():
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
            self._sum_reels_refresh()
        return self.get_sum_manual_state()

    # ==================================================================
    #  РЕЖИМ «СУММЫ» — единый экран: слушаете дубли (A/D), на суммах
    #  клавишами ←/→ выбираете категорию и ↑ отправляете в неё дубль КАК
    #  ЕСТЬ (без правки, без имени из Excel — sum_stage1_send); ошиблись —
    #  ↓ отменяет последнюю отправку (sum_stage1_undo). Одновременно на
    #  экране видны рулетки по каждой категории (те же значения, что
    #  скопились через ↑) — из них в любой момент собирается эталон
    #  (start + по одному значению с каждого яруса + end) и сохраняется
    #  под именем из Excel кнопками «Отправить в Audacity»/«Сохранить»
    #  (sum_stage2_save) — переиспользует готовую механику Конструктора
    #  (constructor_play/constructor_send_to_audacity/рулетки).
    #  Раньше это были два отдельных «Этапа» — теперь один экран сразу.
    # ==================================================================

    def _sum_stage1_raw_root(self):
        return os.path.join(self.work_dir, 'Суммы_сырые')

    def _sum_stage1_raw_dir(self, tier):
        return os.path.join(self._sum_stage1_raw_root(), self._sum_manual_tier_dir(tier))

    def _sum_reels_refresh(self):
        """Перечитывает сырые папки категорий в рулетки (constructor_tier_files
        и соседние поля) — вызывается при включении режима и заново не
        нужна после каждой отправки/отмены, те сами точечно правят список."""
        tiers = {}
        for tier in self._all_category_keys():
            d = self._sum_stage1_raw_dir(tier)
            files = []
            if os.path.isdir(d):
                files = [os.path.join(d, f) for f in os.listdir(d)
                         if os.path.isfile(os.path.join(d, f)) and f.lower().endswith(('.wav', '.mp3'))]
                files.sort(key=os.path.getmtime)
            tiers[tier] = files

        self.constructor_root = self._sum_stage1_raw_root()
        self.constructor_tier_files = tiers
        self.constructor_start_file = getattr(self, 'var_start_phrase', None)
        self.constructor_end_file = getattr(self, 'var_end_phrase', None)

        if not hasattr(self, 'sum_stage2_active_idx'):
            self.sum_stage2_active_idx = 0
        if not hasattr(self, 'sum_stage2_counts'):
            self.sum_stage2_counts = {}
        if not hasattr(self, 'sum_stage2_frozen_idx'):
            self.sum_stage2_frozen_idx = {}

    def sum_load_folder(self):
        """Вход в режим «Суммы» прямо с главного меню: выбираем папку с уже
        нарезанными дублями (например «Chunks» после автосрезки, или
        просто папка с WAV-файлами) — никакой связи с Audacity тут не
        нужно, и, в отличие от старой «Готовой папки с переменными»,
        start/end не спрашиваем. Если в этой же папке проекта уже есть
        «Суммы_сырые» с прошлого раза (докладывали дубли в прошлой
        сессии) — рулетки подхватят её автоматически."""
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        selected_path = folder[0]
        self.work_dir = (os.path.dirname(selected_path)
                          if os.path.basename(selected_path).lower() in _STAGE1_SCAN_EXCLUDE
                          else selected_path)
        self.project_name = os.path.basename(self.work_dir)
        self.sum_last_dub = None
        project_state.apply(self, project_state.load(self.work_dir))

        # Через словарь переменных имена/текст файлов берём из него (и из
        # будущего списка реальных записей — см. var_connectors/var_extra_tags),
        # не из общего phrases_data. Если project_state восстановил его
        # из старого прогона (или прошлого теста в этой же папке) —
        # «Сохранится как»/«Ожидает выгрузки» показывали бы устаревший
        # текст (например, текст связки «на автомобиль» вместо реального
        # имени дубля). Раз словарь загружен — эта старая привязка к
        # Excel явно не должна работать.
        if getattr(self, 'var_connectors', None) or getattr(self, 'var_extra_tags', None):
            self.phrases_data = []
            self.phrase_index = 0

        files = [f for f in os.listdir(selected_path)
                 if os.path.isfile(os.path.join(selected_path, f)) and f.lower().endswith(('.wav', '.mp3'))]
        if not files:
            return {"error": "В выбранной папке нет аудиофайлов."}
        files.sort(key=_numeric_sort_key)

        # Файлы, уже назначенные связками (start/end…), — не дубли.
        connector_paths = {os.path.normcase(os.path.abspath(c['path']))
                           for c in (getattr(self, 'var_connectors', None) or []) if c.get('path')}
        files = [f for f in files
                 if os.path.normcase(os.path.abspath(os.path.join(selected_path, f))) not in connector_paths]
        self.chunks_data = [{"filepath": os.path.join(selected_path, f), "filename": f} for f in files]
        # Продолжаем с того дубля, на котором остановились (по имени файла).
        last = getattr(self, 'sum_last_dub', None)
        self.chunk_index = next((i for i, f in enumerate(files) if f == last), 0)
        self.current_mode = 'Chunks'
        self.raw_audio_full = None

        self.toggle_sum_mode(True)
        if self.chunk_index:
            self._sum_toast(f'↪ Продолжаем с {files[self.chunk_index]}')

        # Связки словаря, которые ещё не озвучены, — вдруг их файлы лежат в
        # этой папке или в папке проекта. Подставим только после «Да».
        found = self._var_find_connector_files([selected_path, self.work_dir])
        state = self.get_ui_state()
        state["connector_suggestions"] = self._var_connector_suggestions_payload(found)
        return state

    def _sum_toast(self, msg, ms=None):
        msg_js = msg.replace('\\', '\\\\').replace("'", "\\'")
        extra = f", {int(ms)}" if ms else ""
        webview.windows[0].evaluate_js(f"showToast('{msg_js}'{extra});")

    # ==================================================================
    #  ПЕРЕТАСКИВАНИЕ: любой дубль из ленты (не только текущий) можно
    #  бросить в категорию или отправить вместе с другими в Audacity.
    # ==================================================================

    def _sum_source_files(self):
        """Список дублей, которые сейчас разбираются, и номер текущего —
        и для обычной нарезки (Chunks), и для конвейера готовых переменных."""
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            return list(self.cascade_files.get(cat, [])), self.cascade_ptrs.get(cat, 0)
        chunks = getattr(self, 'chunks_data', None) or []
        return [c['filepath'] for c in chunks], getattr(self, 'chunk_index', 0)

    def _sum_set_pointer(self, idx):
        files, old = self._sum_source_files()
        idx = max(0, min(idx, len(files)))
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            self.cascade_ptrs[cat] = idx
        else:
            self.chunk_index = min(idx, max(0, len(files) - 1))
        if getattr(self, 'phrases_data', None):
            self.phrase_index = max(0, self.phrase_index + (idx - old))

    def _sum_assigned_sources(self):
        """Исходный дубль -> список категорий, куда из него уже что-то
        записано (по sum_raw_sources: сырой файл -> исходный дубль)."""
        out = {}
        for raw, info in (getattr(self, 'sum_raw_sources', None) or {}).items():
            out.setdefault(info['source'], []).append(info['tier'])
        return out

    def _sum_remember_source(self, raw_path, source, tier):
        if not isinstance(getattr(self, 'sum_raw_sources', None), dict):
            self.sum_raw_sources = {}
        self.sum_raw_sources[raw_path] = {"source": source, "tier": tier}

    def _sum_forget_source(self, raw_path):
        (getattr(self, 'sum_raw_sources', None) or {}).pop(raw_path, None)

    def _sum_after_consumed(self, indices):
        """Текущий дубль среди разобранных — переводим указатель на
        следующий ещё не разобранный после них. Иначе не трогаем."""
        files, ptr = self._sum_source_files()
        if ptr not in indices:
            return
        assigned = self._sum_assigned_sources()
        nxt = max(indices) + 1
        while nxt < len(files) and files[nxt] in assigned:
            nxt += 1
        self._sum_set_pointer(nxt)

    def _sum_copy_to_category(self, tier, source_path):
        """Копирует дубль в сырую папку категории под ожидаемым значением
        таблицы (см. _var_expected_value). Возвращает (путь, значение)."""
        target_dir = self._sum_stage1_raw_dir(tier)
        os.makedirs(target_dir, exist_ok=True)
        if not hasattr(self, 'constructor_tier_files'):
            self.constructor_tier_files = {}
        source_name = os.path.basename(source_path)
        ext = os.path.splitext(source_name)[1] or '.wav'
        value, value_idx = self._var_expected_value(tier)
        if value is not None:
            self._var_set_cursor(tier, value_idx + 1)
            save_name = f"{time.time_ns() // 1000}_сырая_{self._var_safe_value(value)}{ext}"
        else:
            save_name = f"{time.time_ns() // 1000}_{source_name}"
        target_path = os.path.join(target_dir, save_name)
        shutil.copy(source_path, target_path)
        self.constructor_tier_files.setdefault(tier, []).append(target_path)
        self._sum_remember_source(target_path, source_path, tier)
        return target_path, value

    def sum_stage1_send(self, tier):
        """Клавиша Z: текущий дубль уходит как есть в сырую папку категории."""
        if tier not in self._all_category_keys():
            return {"error": f"Неизвестная категория: {tier}"}
        active_file, _, err = self._sum_current_source()
        if err:
            return {"error": err}
        _, ptr = self._sum_source_files()
        return self.sum_send_dubs(tier, [ptr])

    def sum_send_dubs(self, tier, indices):
        """Перетащили один или несколько дублей из ленты в категорию.
        Каждый получает следующее ожидаемое значение таблицы по порядку."""
        if tier not in self._all_category_keys():
            return {"error": f"Неизвестная категория: {tier}"}
        files, ptr = self._sum_source_files()
        indices = sorted({int(i) for i in (indices or []) if 0 <= int(i) < len(files)})
        if not indices:
            return {"error": "Не выбран ни один дубль."}

        sent = []
        for i in indices:
            target, value = self._sum_copy_to_category(tier, files[i])
            sent.append((target, value))

        # «Отменить» (X) откатывает только одиночную отправку — вместе с
        # указателем очереди, если он из-за неё сдвинулся.
        self.sum_stage1_last_send = ({"tier": tier, "raw_path": sent[0][0], "ptr_before": ptr}
                                     if len(sent) == 1 else None)
        self._sum_after_consumed(indices)

        label = self._category_label(tier)
        values = [v for _, v in sent if v is not None]
        if len(sent) == 1:
            self._sum_toast(f'➜ «{label}»: {values[0]}' if values else f'➜ Отправлено в «{label}»')
        else:
            self._sum_toast(f'➜ «{label}»: {len(sent)} дублей' + (f' ({values[0]} … {values[-1]})' if values else ''))
        return self.get_ui_state()

    def sum_focus_dub(self, index):
        """Сделать дубль из ленты текущим (то же, что листать A/D)."""
        self._sum_set_pointer(int(index))
        return self.get_ui_state()

    def sum_dubs_to_audacity(self, indices):
        """Один или несколько дублей — подряд на одну дорожку Audacity
        (с секундой тишины между ними), чтобы поправить и разметить метками
        «значение_категория» (B) или вырезать выделение в категорию (N)."""
        files, _ = self._sum_source_files()
        indices = sorted({int(i) for i in (indices or []) if 0 <= int(i) < len(files)})
        if not indices:
            return {"error": "Не выбран ни один дубль."}

        if self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы продолжить."}
        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')
        t = 0.0
        segments = []
        for i in indices:
            dur = self._import_clip_to_track0(files[i], t)
            segments.append({"start": t, "end": t + dur, "source": files[i], "index": i})
            t += dur + 1.0

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={t + 1.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True
        self._sum_split_pending = {"source": files[indices[0]], "name": os.path.basename(files[indices[0]]),
                                   "segments": segments, "indices": indices}

        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        what = 'Дубль' if len(indices) == 1 else f'{len(indices)} дублей'
        self._sum_toast(f'✂️ {what} в Audacity — выделите кусок и N, или метки «4_тыс» и B')
        return self.get_ui_state()

    def sum_send_current_dub_to_audacity(self):
        """Клавиша V: текущий дубль целиком в Audacity."""
        _, _, err = self._sum_current_source()
        if err:
            return {"error": err}
        _, ptr = self._sum_source_files()
        return self.sum_dubs_to_audacity([ptr])

    def _sum_dub_cards(self, before=8, count=60):
        """Окно ленты карточек: вокруг текущего дубля, либо там, куда юзер
        сам долистал колесом (пока текущий дубль не сменился)."""
        files, ptr = self._sum_source_files()
        if not files:
            return None
        assigned = self._sum_assigned_sources()
        assigned_values, assigned_recs = {}, {}
        checked_root = os.path.normcase(os.path.abspath(self._sum_manual_tier_root())) if getattr(self, 'work_dir', None) else None
        for raw, info in (getattr(self, 'sum_raw_sources', None) or {}).items():
            value = self._sum_raw_value_from_path(raw)
            assigned_values.setdefault(info['source'], []).append(value)
            is_checked = bool(checked_root) and os.path.normcase(os.path.abspath(raw)).startswith(checked_root)
            assigned_recs.setdefault(info['source'], []).append(
                {"value": value, "path": raw, "tier": info['tier'], "checked": is_checked})
        view = getattr(self, '_sum_dub_view', None)
        if view and view.get('ptr') == ptr:
            start = view['start']
        else:
            self._sum_dub_view = None
            start = min(ptr, len(files) - 1) - before
        start = max(0, min(start, len(files) - count))
        end = min(len(files), start + count)
        items = []
        for i in range(start, end):
            path = files[i]
            tiers = assigned.get(path, [])
            items.append({
                "index": i,
                "name": os.path.splitext(os.path.basename(path))[0],
                "path": path,
                "current": i == ptr,
                "tiers": [self._category_label(t) for t in tiers],
                "tier_keys": tiers,
                "values": assigned_values.get(path, []),
                # Что из дубля уже записано (сырое или эталон) — с путём для «×».
                "assigned": assigned_recs.get(path, []),
                "asr": (getattr(self, 'sum_asr_results', None) or {}).get(path),
            })
        return {"items": items, "total": len(files), "current": ptr, "from": start}

    def sum_dub_cards_at(self, start):
        """Колесо мыши довело ленту до края — следующий/предыдущий кусок."""
        _, ptr = self._sum_source_files()
        self._sum_dub_view = {"start": max(0, int(start)), "ptr": ptr}
        return self._sum_dub_cards()

    def sum_stage1_undo(self):
        """Клавиша ↓: убирает файл, отправленный последним нажатием
        категории, из сырой папки (и из рулетки) и возвращает очередь
        дублей на шаг назад — сам дубль никуда не делся (копия, а не
        перемещение), поэтому достаточно сдвинуть указатель обратно."""
        last = getattr(self, 'sum_stage1_last_send', None)
        if not last:
            return {"error": "Отменять нечего."}

        try:
            if os.path.exists(last['raw_path']):
                os.remove(last['raw_path'])
        except OSError as e:
            return {"error": f"Не удалось убрать файл из категории: {e}"}

        files = self.constructor_tier_files.get(last['tier'], [])
        if last['raw_path'] in files:
            files.remove(last['raw_path'])

        self._sum_forget_source(last['raw_path'])
        if 'ptr_before' in last:
            self._sum_set_pointer(last['ptr_before'])
        elif self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            self.cascade_ptrs[cat] = max(0, self.cascade_ptrs.get(cat, 0) - 1)
        else:
            self.chunk_index = max(0, self.chunk_index - 1)
            if getattr(self, 'phrases_data', None) and self.phrase_index > 0:
                self.phrase_index -= 1

        tier = last['tier']
        self._var_rewind_cursor_to(tier, last['raw_path'])
        self.sum_stage1_last_send = None
        webview.windows[0].evaluate_js(f"showToast('↩️ Отменено: убрано из «{self._category_label(tier)}»');")
        return self.get_ui_state()

    # ==================================================================
    #  РАЗДЕЛЕНИЕ СЛИПШЕГОСЯ ДУБЛЯ: иногда автосрезка не разрезала фразу,
    #  в которой диктор произнёс сразу две переменные подряд без паузы
    #  между ними (например «4 тысячи» и «4 тенге» слитно). Обычная
    #  отправка (sum_stage1_send) тут не подходит — дубль целиком ушёл бы
    #  только в одну категорию. Вместо этого: текущий дубль целиком, БЕЗ
    #  правки, открывается в Audacity — юзер сам расставляет метки
    #  (Ctrl+B) на каждом куске с именем вида «4_тыс» (значение и слово
    #  категории через «_»), затем одной кнопкой все размеченные участки
    #  разъезжаются по своим сырым папкам, как будто были отправлены
    #  sum_stage1_send по отдельности.
    # ==================================================================

    def _resolve_label_category(self, word):
        """Слово из метки («тыс», «тенге», «марка»...) -> внутренний ключ
        категории. Для ярусов Суммы используем то же различение тысяч по
        числу, что и _detect_sum_tier/_thousands_subtier (число уже есть
        в самой метке, например «150_тыс» -> Сотни тысяч, «4_тыс» ->
        Тысячи), «сотни» без числа-подсказки распознаём по отдельному
        слову, раз в обычном тексте Excel у этого яруса вообще нет слова.
        Доп.категории словаря (mark/year/...) ищем и по ключу колонки, и
        по её человеческой подписи — что юзеру удобнее написать в метке."""
        low = (word or '').lower().replace('ё', 'е')
        if 'млн' in low or 'миллион' in low:
            return 'millions'
        if 'тыс' in low:
            return _thousands_subtier(low)
        if 'тенге' in low or re.search(r'тг(?![а-яa-z])', low):
            return 'tenge'
        if 'сотн' in low or 'сотен' in low:
            return 'hundreds'
        for key in self._var_extra_tag_keys():
            if key.lower() in low or self._var_extra_tag_label(key).lower() in low:
                return key
        return None

    @staticmethod
    def _sum_segment_source(pending, t):
        """Из какого дубля взят кусок на дорожке Audacity (по времени)."""
        segs = pending.get('segments') or []
        for seg in segs:
            if seg['start'] - 0.5 <= t <= seg['end'] + 0.5:
                return seg['source']
        return pending.get('source')

    def sum_collect_dub_labels(self):
        """Клавиша B: читает метки, расставленные на дубле, отправленном
        sum_send_current_dub_to_audacity, экспортирует каждый размеченный
        участок в сырую папку соответствующей категории — ровно так же,
        как если бы каждый кусок был отправлен по отдельности клавишей Z,
        включая короткое имя «сырая_<значение>». Требуем, чтобы КАЖДАЯ
        метка распозналась, прежде чем экспортировать хоть одну — иначе
        нераспознанный кусок потерялся бы молча."""
        pending = getattr(self, '_sum_split_pending', None)
        if not pending:
            return {"error": "Сначала отправьте дубль кнопкой «Дубль в Audacity»."}

        resp = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        labels = []
        try:
            s, e = resp.find('['), resp.rfind(']')
            data = json.loads(resp[s:e + 1])
            for track in data:
                for label in track[1]:
                    labels.append((float(label[0]), float(label[1]), str(label[2]).strip()))
        except Exception:
            return {"error": "Не удалось прочитать метки из Audacity."}

        if not labels:
            return {"error": "На дорожке нет меток. Выделите участок, нажмите Ctrl+B, впишите имя вида "
                              "«4_тыс» и снова нажмите эту кнопку."}

        resolved, unresolved = [], []
        for t0, t1, text in labels:
            if '_' not in text:
                unresolved.append(text)
                continue
            value, word = text.split('_', 1)
            value = value.strip()
            tier = self._resolve_label_category(word)
            if not value or not tier:
                unresolved.append(text)
                continue
            resolved.append((t0, t1, tier, value))

        if unresolved:
            return {"error": "Не распознал категорию в метке(-ах): " + ', '.join(unresolved) +
                              ". Формат — «значение_категория», например «4_тыс» или «4_тенге». "
                              "Переименуйте метку(-и) в Audacity (Ctrl+B на ней) и нажмите ещё раз."}

        if not hasattr(self, 'constructor_tier_files'):
            self.constructor_tier_files = {}
        ext = os.path.splitext(pending['name'])[1] or '.wav'
        exported = []
        for t0, t1, tier, value in resolved:
            target_dir = self._sum_stage1_raw_dir(tier)
            os.makedirs(target_dir, exist_ok=True)
            safe_value = re.sub(r'[<>:"/\\|?*]', ' ', value).strip()
            save_name = f"{int(time.time() * 1000)}_сырая_{safe_value}{ext}"
            target_path = os.path.join(target_dir, save_name)

            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={t0} End={t1} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')

            self.constructor_tier_files.setdefault(tier, []).append(target_path)
            self._sum_remember_source(target_path, self._sum_segment_source(pending, (t0 + t1) / 2), tier)
            exported.append(f'{self._category_label(tier)}: {value}')

        self._sum_split_pending = None
        self.sum_stage1_last_send = None  # разделённый дубль не откатывается обычной «Отменить»
        if pending.get('indices'):
            self._sum_after_consumed(pending['indices'])
        else:
            self._sum_advance_pointer()

        summary = ', '.join(exported)
        webview.windows[0].evaluate_js(f"showToast('✂️ Разделено и сохранено: {summary}');")
        return self.get_ui_state()

    def sum_send_selection_to_category(self, tier):
        """Вызывается из sum_fix_split, когда дубль уже открыт в Audacity
        (после V) — вырезали
        лишнее (например «на автомобиль » перед самой маркой) и оставили
        выделенным только нужный кусок. Не нужно ни ставить метку, ни
        писать её текст руками — берём ТЕКУЩЕЕ ВЫДЕЛЕНИЕ как есть и
        сохраняем его в сырую папку выбранной ↑/↓ категории, присвоив то
        же значение, что показано юзеру как «Ожидаю дальше» (то, которое
        обычная Z присвоила бы следующему по очереди дублю — см.
        _var_next_tag_value/expected_next в _sum_stage2_state). Дубль в
        Audacity остаётся открытым — можно вырезать из него ещё один
        кусок под другую категорию, не открывая заново."""
        pending = getattr(self, '_sum_split_pending', None)
        if not pending or not getattr(self, 'is_in_audacity', False):
            return {"error": "Сначала отправьте дубль в Audacity кнопкой «Дубль в Audacity» (V)."}
        if tier not in self._all_category_keys():
            return {"error": f"Неизвестная категория: {tier}"}

        if not hasattr(self, 'constructor_tier_files'):
            self.constructor_tier_files = {}
        value, value_idx = self._var_expected_value(tier)
        if value is None:
            return {"error": "Для этой категории нет списка значений в загруженной таблице."}

        target_dir = self._sum_stage1_raw_dir(tier)
        os.makedirs(target_dir, exist_ok=True)
        ext = os.path.splitext(pending['name'])[1] or '.wav'
        save_name = f"{int(time.time() * 1000)}_сырая_{self._var_safe_value(value)}{ext}"
        target_path = os.path.join(target_dir, save_name)

        resp = self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')
        if not resp or not os.path.exists(target_path):
            return {"error": "Не удалось сохранить — убедитесь, что в Audacity выделен нужный участок, и повторите."}

        self.constructor_tier_files.setdefault(tier, []).append(target_path)
        self._var_set_cursor(tier, value_idx + 1)
        segs = pending.get('segments') or []
        if len(segs) <= 1:
            self._sum_remember_source(target_path, pending['source'], tier)

        # Следующее ожидаемое значение ЭТОЙ ЖЕ категории — сразу после
        # сохранения, чтобы юзер видел на мини-алерте, что искать дальше,
        # не дожидаясь перерисовки всего экрана.
        next_expected, _ = self._var_expected_value(tier)
        label = self._category_label(tier)
        msg = f"✅ Сохранено в «{label}»: {value}"
        if next_expected:
            msg += f" · Дальше жду: {next_expected}"

        msg_js = msg.replace('\\', '\\\\').replace("'", "\\'")
        webview.windows[0].evaluate_js(f"showToast('{msg_js}', 3200);")
        return self.get_ui_state()

    def _sum_stage2_active_tier(self):
        """Только для «чистого» режима Суммы БЕЗ загруженной таблицы —
        там нет строк, категория просто растёт до потолка/пустой сырой
        папки, потом эстафета уходит следующей по порядку. Со словарём
        сборка идёт по строкам целиком (_sum_stage2_current_row), этот
        метод там не используется."""
        active = self._active_category_keys()
        if not active:
            return SUM_TIER_ORDER[0]
        idx = getattr(self, 'sum_stage2_active_idx', 0) % len(active)
        return active[idx]

    def _sum_stage2_advance(self):
        """Только для «чистого» режима Суммы без таблицы — см.
        _sum_stage2_active_tier."""
        active_tier = self._sum_stage2_active_tier()
        remaining = len(self.constructor_tier_files.get(active_tier, []))
        if remaining == 0:
            active = self._active_category_keys()
            if active_tier in active:
                self.sum_stage2_active_idx = (active.index(active_tier) + 1) % len(active)

    def _sum_stage2_current_row(self):
        """Строка таблицы-словаря, которую сейчас собираем целиком —
        {категория: значение}. Без загруженной таблицы — пустая (тогда
        работает старый каскад по категориям, см. _sum_stage2_active_tier)."""
        rows = getattr(self, 'var_template_rows', None) or []
        if not rows:
            return {}
        idx = getattr(self, 'sum_stage2_row_idx', 0)
        idx = max(0, min(idx, len(rows) - 1))
        return rows[idx]

    def _sum_stage2_resolve_value(self, tier, value):
        """Ищет аудио под конкретное значение категории (взятое из строки
        таблицы): сперва уже готовое в Проверенные (тогда просто
        переиспользуем — этот звук уже кому-то присвоен, резать заново не
        нужно), иначе сырое, ещё не сохранённое. Возвращает (путь,
        saveable) — saveable=True только у сырого, только его нужно
        экспортировать при «Сохранить эталон»; (None, False), если для
        этого значения вообще нет ни готовой, ни сырой записи."""
        if not value:
            return None, False
        target_dir = os.path.join(self._sum_manual_tier_root(), self._sum_manual_tier_dir(tier))
        clean_value = re.sub(r'[<>:"/\\|?*]', '', value).strip()
        name_base = re.sub(r'\D', '', clean_value) if tier in SUM_TIER_ORDER else clean_value
        name_base = name_base or clean_value
        for ext in ('.wav', '.mp3'):
            p = os.path.join(target_dir, f"{name_base}{ext}")
            if os.path.exists(p):
                return p, False
        for p in self.constructor_tier_files.get(tier, []):
            if self._sum_raw_value_from_path(p) == value:
                return p, True
        return None, False

    def _sum_stage2_advance_row(self):
        """После сохранения — следующая строка таблицы, пропуская те, что
        уже полностью готовы (все их категории — уже сохранённые файлы,
        нечего там делать), чтобы не листать вручную то, что и так готово."""
        rows = getattr(self, 'var_template_rows', None) or []
        if not rows:
            return
        self.sum_stage2_row_idx = self._sum_first_open_row((getattr(self, 'sum_stage2_row_idx', 0) + 1) % len(rows))

    def _sum_row_done(self, row):
        """Все значения строки уже лежат в Проверенных — делать нечего."""
        for col in getattr(self, 'var_template_columns', None) or []:
            if col['type'] == 'connector':
                continue
            value = row.get(col['key'])
            if not value:
                continue
            path, saveable = self._sum_stage2_resolve_value(col['key'], value)
            if saveable or not path:
                return False
        return True

    def _sum_first_open_row(self, start):
        """Первая незаконченная строка, начиная с start (по кругу)."""
        rows = getattr(self, 'var_template_rows', None) or []
        total = len(rows)
        for off in range(total):
            idx = (start + off) % total
            if not self._sum_row_done(rows[idx]):
                return idx
        return start % total if total else 0

    def _sum_skip_done_row(self):
        """Текущая строка уже готова целиком — сразу на следующую
        незаконченную. Кроме строки, которую юзер выбрал сам."""
        rows = getattr(self, 'var_template_rows', None) or []
        if not rows:
            return
        idx = max(0, min(getattr(self, 'sum_stage2_row_idx', 0), len(rows) - 1))
        if idx == getattr(self, '_sum_row_pinned', None) or not self._sum_row_done(rows[idx]):
            return
        self.sum_stage2_row_idx = self._sum_first_open_row(idx)
        self._sum_row_pinned = None

    def sum_stage2_jump_to_value(self, tier, value):
        """Юзер выбрал значение категории из ПОЛНОГО списка таблицы (не
        только то, что уже разложено по сырым дублям) — ищем первую
        строку с этим значением в этой колонке (начиная с текущей, по
        кругу) и переключаемся на неё ЦЕЛИКОМ: марка, год, суммы —
        дальше всё берётся из ЭТОЙ ЖЕ строки, а не независимо друг от
        друга."""
        rows = getattr(self, 'var_template_rows', None) or []
        if not rows:
            return {"error": "Таблица-словарь не загружена."}
        value = (value or '').strip()
        if not value:
            return self.get_ui_state()

        total = len(rows)
        start = getattr(self, 'sum_stage2_row_idx', 0)
        for offset in range(total):
            idx = (start + offset) % total
            if rows[idx].get(tier) == value:
                self.sum_stage2_row_idx = idx
                self._sum_row_pinned = idx
                return self.get_ui_state()
        return {"error": f"В таблице нет строки со значением «{value}» в этой категории."}

    def _sum_stage2_state(self):
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        columns = getattr(self, 'var_template_columns', None)
        counts = getattr(self, 'sum_stage2_counts', {}) or {}

        def display_name(path):
            # "<таймстамп>_<исходное имя дубля>.wav" -> "исходное имя дубля"
            stem = os.path.splitext(os.path.basename(path))[0]
            return stem.split('_', 1)[1] if '_' in stem else stem

        if not columns:
            # «Чистый» режим Суммы без таблицы — старый каскад по
            # категориям, без понятия строки.
            active_tier = self._sum_stage2_active_tier()
            active_logic = self._active_category_keys()
            frozen_idx = getattr(self, 'sum_stage2_frozen_idx', {}) or {}
            default_indices = {t: (0 if t == active_tier else frozen_idx.get(t, 0)) for t in active_logic}
            return {
                "active_tier": self._category_label(active_tier),
                "active_tier_key": active_tier,
                "default_indices": default_indices,
                "row_idx": None,
                "rows_total": 0,
                "row_values": {},
                "start": os.path.basename(self.constructor_start_file) if self.constructor_start_file else None,
                "end": os.path.basename(self.constructor_end_file) if self.constructor_end_file else None,
                "tiers": {
                    t: {
                        "label": self._category_label(t),
                        "items": [display_name(p) for p in tiers.get(t, [])],
                        "paths": list(tiers.get(t, [])),
                        "name_choices": [],
                        "saved": counts.get(t, 0),
                        "cap": SUM_TIER_CAP.get(t),
                        "active": t == active_tier,
                    }
                    for t in active_logic
                },
            }

        # РЕЖИМ СО СЛОВАРЁМ: собираем ОДНУ КОНКРЕТНУЮ СТРОКУ таблицы
        # целиком (марка+год+суммы вместе, как они реально стоят в этой
        # строке) — см. _sum_stage2_current_row/sum_stage2_jump_to_value.
        self._sum_skip_done_row()
        row = self._sum_stage2_current_row()
        rows_total = len(getattr(self, 'var_template_rows', None) or [])
        active_logic = self._active_category_keys()
        all_choices = getattr(self, 'var_extra_tag_values', {}) or {}

        def pending(t):
            # В списке категории — только ещё сырые записи: значение,
            # которое уже лежит в Проверенных, не показываем (файл не трогаем).
            out = []
            for p in tiers.get(t, []):
                found, saveable = self._sum_stage2_resolve_value(t, self._sum_raw_value_from_path(p))
                if saveable or not found:
                    out.append(p)
            return out
        shown = {t: pending(t) for t in active_logic}

        tiers_out = {}
        for t in active_logic:
            value = row.get(t)
            path, saveable = self._sum_stage2_resolve_value(t, value)
            # То самое значение, что sum_stage1_send присвоит СЛЕДУЮЩЕМУ
            # отправленному в эту категорию дублю (см. _var_expected_value).
            expected_next, expected_idx = self._var_expected_value(t)
            values_all = all_choices.get(t, []) or []
            last_send = getattr(self, 'sum_stage1_last_send', None) or {}
            tiers_out[t] = {
                "label": self._category_label(t),
                "items": [display_name(p) for p in shown[t]],
                # Пути рядом с именами — чтобы фронтенд мог проиграть
                # конкретное сырое значение при листании ←/→, а не
                # только показать его название (play_specific_file).
                "paths": shown[t],
                # Полный список значений ЭТОЙ колонки из самой таблицы —
                # не только то, что уже разложено по сырым дублям — юзер
                # выбирает из него, на какую строку переключиться целиком
                # (sum_stage2_jump_to_value).
                "name_choices": list(all_choices.get(t, [])),
                "saved": counts.get(t, 0),
                "cap": SUM_TIER_CAP.get(t),
                # «active» тут значит «для этой строки ещё нет готового
                # файла — требует сохранения», не «сейчас едет» (такого
                # понятия в режиме строк больше нет).
                "active": bool(saveable),
                "row_value": value,
                "row_ready": path is not None,
                "expected_next": expected_next,
                "expected_idx": expected_idx,
                "asr_match": self._sum_asr_match(t, expected_next),
                "values_total": len(values_all),
                "last_send_path": last_send.get('raw_path') if last_send.get('tier') == t else None,
            }

        # Курсор внутри категории по умолчанию — на ПОСЛЕДНЕМ (самом
        # свежем, раз items отсортирован по mtime — см. _sum_reels_refresh)
        # сыром значении, а не на первом: обычно интересует именно то, что
        # только что добавили, а не самое старое в очереди.
        default_indices = {t: max(0, len(shown[t]) - 1) for t in active_logic}

        return {
            "active_tier": None,
            "active_tier_key": None,
            "default_indices": default_indices,
            "row_idx": getattr(self, 'sum_stage2_row_idx', 0),
            "rows_total": rows_total,
            "row_values": dict(row),
            "start": os.path.basename(self.constructor_start_file) if self.constructor_start_file else None,
            "end": os.path.basename(self.constructor_end_file) if self.constructor_end_file else None,
            "tiers": tiers_out,
        }

    @staticmethod
    def _sum_raw_value_from_path(path):
        """«<таймстамп>_сырая_<значение>.wav» -> «<значение>» — то самое
        значение, что присвоила sum_stage1_send, без служебных частей
        имени. Старый формат без префикса «сырая_» (до этого изменения)
        отдаёт как есть, без обрезки."""
        stem = os.path.splitext(os.path.basename(path))[0]
        if '_' in stem:
            stem = stem.split('_', 1)[1]
        if stem.startswith('сырая_'):
            stem = stem[len('сырая_'):]
        return stem

    def _sum_checked_target(self, tier, raw_path, name_override=None):
        """Куда в Проверенные ляжет эталон этого сырого файла: имя — само
        значение категории («AUDI 80.wav»), для ярусов Суммы — цифры («95.wav»)."""
        target_dir = os.path.join(self._sum_manual_tier_root(), self._sum_manual_tier_dir(tier))
        os.makedirs(target_dir, exist_ok=True)
        ext = os.path.splitext(raw_path)[1] or '.wav'
        raw_value = name_override if name_override else self._sum_raw_value_from_path(raw_path)
        clean_value = re.sub(r'[<>:"/\\|?*]', '', raw_value).strip()
        if tier in SUM_TIER_ORDER:
            digits = re.sub(r'\D', '', clean_value)
            save_name = f"{digits}{ext}" if digits else f"{clean_value}{ext}"
        else:
            save_name = f"{clean_value}{ext}" if clean_value else os.path.basename(raw_path)
        target_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')
        return target_path, save_name

    def _sum_stage2_save_one(self, tier, raw_path, clip, name_override=None):
        """Экспортирует один кусок (по его клипу на дорожке) в Проверенные
        нужной категории, убирает исходник из сырой очереди и обновляет
        кэш «последнего сохранённого». Имя файла обычно берём из самого
        сырого файла (то, что ему присвоила сырая сортировка — оно и
        совпадает со значением строки таблицы, раз мы его для этого
        значения и искали, см. _sum_stage2_resolve_value); name_override
        остаётся как ручной способ переопределить имя при прямом вызове."""
        target_path, save_name = self._sum_checked_target(tier, raw_path, name_override)
        if os.path.exists(target_path):
            try: os.remove(target_path)
            except OSError: pass

        c_start, c_end = clip.get('start', 0.0), clip.get('end', 0.0)
        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
        self.audacity.send_command(f'Export2: Filename="{target_path}" NumChannels=1')
        time.sleep(0.1)

        # Сырой источник — использован, больше не нужен.
        try:
            os.remove(raw_path)
        except OSError:
            pass
        if raw_path in self.constructor_tier_files.get(tier, []):
            self.constructor_tier_files[tier].remove(raw_path)

        if not hasattr(self, 'sum_manual_last_file'):
            self.sum_manual_last_file = {}
        self.sum_manual_last_file[tier] = target_path

        return save_name

    def sum_stage2_save(self):
        """Фиксирует эталон, собранный на столе Audacity. Со словарём —
        это одна строка таблицы целиком: экспортирует все категории этой
        строки, у которых ещё не было готового файла (те, что уже были
        готовы, просто переиспользовались как контекст — их не трогаем),
        и переходит на следующую строку (_sum_stage2_advance_row). Без
        словаря — прежнее поведение: только активная категория каскада.
        Имя итогового файла — само значение категории («AUDI 80.wav»,
        «95.wav», «4.wav»), Excel не нужен."""
        layout = getattr(self, '_constructor_clip_layout', None)
        active_paths = getattr(self, '_constructor_active_paths', None)
        if not layout:
            return {"error": "Сначала нажмите «Отправить в Audacity»."}

        columns = getattr(self, 'var_template_columns', None)
        active_tier = None if columns else self._sum_stage2_active_tier()
        if active_tier is not None and active_tier not in (active_paths or {}):
            return {"error": f"В сборке нет категории «{self._category_label(active_tier)}» — отправьте в "
                              f"Audacity заново."}

        resp_clips = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
        try:
            c_data = json.loads(resp_clips[resp_clips.find('['):resp_clips.rfind(']') + 1])
            track_0_clips = []
            for t in c_data:
                if t.get('track', -1) == 0:
                    track_0_clips.extend(t.get('clips', [t]))
            track_0_clips.sort(key=lambda x: x.get('start', 0))
        except Exception:
            return {"error": "Не удалось прочитать дорожку из Audacity."}

        if len(track_0_clips) != len(layout):
            return {"error": "Число кусков на дорожке не совпадает с тем, что отправляли — "
                              "не разрезали и не склеивали ли лишнего?"}

        clip_by_tag = {}
        for tag, clip in zip(layout, track_0_clips):
            clip_by_tag.setdefault(tag, clip)

        saved_names = {}
        for tier, raw_path in (active_paths or {}).items():
            clip = clip_by_tag.get(tier)
            if clip is None:
                continue
            saved_names[tier] = self._sum_stage2_save_one(tier, raw_path, clip)

        if active_tier is not None and active_tier not in saved_names and active_tier in (active_paths or {}):
            return {"error": f"Категория «{self._category_label(active_tier)}» не найдена в сборке на дорожке."}

        counts = getattr(self, 'sum_stage2_counts', None) or {}
        for tier in saved_names:
            counts[tier] = counts.get(tier, 0) + 1
        self.sum_stage2_counts = counts

        if columns:
            self._sum_stage2_advance_row()
        else:
            self._sum_stage2_advance()

        self._constructor_clip_layout = None
        self._constructor_active_paths = None

        if not self._block_if_audacity_ambiguous():
            self.audacity.send_command('SelectAll:')
            self.audacity.send_command('RemoveTracks:')
        self.is_in_audacity = False

        if saved_names:
            summary = ', '.join(f'{self._category_label(t)} → {n}' for t, n in saved_names.items())
            webview.windows[0].evaluate_js(f"showToast('💾 Сохранено: {summary}');")
        else:
            webview.windows[0].evaluate_js("showToast('Эта строка уже была полностью готова — перешли к следующей.');")
        return self.get_ui_state()

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

        # Запоминаем, какой ярус лёг в каждый клип по порядку — при сохранении
        # так сопоставляем клипы с дорожки Audacity с ярусами напрямую, а не
        # только по времени начала. Это же позволяет найти клип СОСЕДНЕГО
        # яруса, если пользователь его чуть подрезал, чтобы красиво состыковать
        # с текущим.
        clip_layout = []

        cursor = 0.0
        if getattr(self, 'var_start_phrase', None) and os.path.exists(self.var_start_phrase):
            cursor += self._import_clip_to_track0(self.var_start_phrase, cursor)
            clip_layout.append('start')

        active_clip_start = None
        for t in SUM_TIER_ORDER:
            if t == tier:
                active_clip_start = cursor
                cursor += self._import_clip_to_track0(active_file, cursor)
                clip_layout.append(t)
            elif not self._sum_tier_excluded(t):
                ref = self._sum_last_saved_file(t)
                if ref and os.path.exists(ref):
                    cursor += self._import_clip_to_track0(ref, cursor)
                    clip_layout.append(t)

        if getattr(self, 'var_end_phrase', None) and os.path.exists(self.var_end_phrase):
            self._import_clip_to_track0(self.var_end_phrase, cursor)
            cursor += FileUtils.get_exact_audio_duration(self.var_end_phrase)
            clip_layout.append('end')

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={cursor + 5.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True
        self._sum_active_clip_start = active_clip_start
        self._sum_clip_layout = clip_layout

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

        save_name = self._sum_bare_digits_name(self._current_sum_save_name(source_name))
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
            # ярусов + активный + end) — сопоставляем их с ярусами по порядку
            # вставки (clip_layout), который совпадает с порядком по времени,
            # пока пользователь не удалял и не разрезал клипы. Если раскладка
            # недоступна или число клипов не совпало (склеили/удалили что-то
            # руками) — подстраховка: ищем активный по времени начала, которое
            # запомнили при сборке.
            clip_layout = getattr(self, '_sum_clip_layout', None)
            clip_map = {}
            if clip_layout and len(clip_layout) == len(track_0_clips):
                clip_map = dict(zip(clip_layout, track_0_clips))

            phrase_clip = clip_map.get(tier)
            if phrase_clip is None:
                target_start = getattr(self, '_sum_active_clip_start', None)
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

            # Сосед по цепочке: если пользователь заодно чуть подрезал уже
            # сохранённый предыдущий ярус (чтобы он лучше стыковался с
            # текущим), переэкспортируем его тоже — прямо поверх старого
            # файла, без создания нового и без изменения счётчика. «Сосед»
            # ищем не строго на 1 позицию назад, а пропуская ярусы, которых
            # ещё не было (0 сохранений) или которые уже упёрлись в потолок —
            # иначе, например, после перехода сумм за миллион «Тенге» считал
            # бы соседом устаревшие, уже закрытые «Тысячи», а не актуальный
            # новый ярус «Сотни тысяч».
            tier_idx = SUM_TIER_ORDER.index(tier)
            counts_now = getattr(self, 'sum_manual_counts', None) or {}
            prev_tier = next((SUM_TIER_ORDER[i] for i in range(tier_idx - 1, -1, -1)
                               if counts_now.get(SUM_TIER_ORDER[i], 0) > 0
                               and not self._sum_tier_excluded(SUM_TIER_ORDER[i], counts_now)), None)
            if prev_tier:
                prev_clip = clip_map.get(prev_tier)
                prev_path = getattr(self, 'sum_manual_last_file', {}).get(prev_tier)
                if prev_clip and prev_path and os.path.exists(prev_path):
                    p_start, p_end = prev_clip.get('start', 0.0), prev_clip.get('end', 0.0)
                    self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
                    self.audacity.send_command(f'SelectTime: Start={p_start} End={p_end} RelativeTo=ProjectStart')
                    self.audacity.send_command(f'Export2: Filename="{prev_path}" NumChannels=1')
                    time.sleep(0.1)
                    webview.windows[0].evaluate_js(
                        f"showToast('🔁 Ярус «{SUM_TIER_LABELS[prev_tier]}» тоже обновлён (подрезка учтена)');")

            if not self._block_if_audacity_ambiguous():
                self.audacity.send_command('SelectAll:')
                self.audacity.send_command('RemoveTracks:')
            self.is_in_audacity = False

            hwnd = self._get_own_hwnd()
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
        self._sum_advance_cycle(tier)

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

    def _sum_queue_paths(self):
        """(список путей очереди, текущий индекс) — общая абстракция что для
        обычной нарезки (chunks_data — список словарей), что для конвейера
        «Готовые переменные» (cascade_files — список путей)."""
        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            return self.cascade_files.get(cat, []), self.cascade_ptrs.get(cat, 0)
        return [item['filepath'] for item in getattr(self, 'chunks_data', [])], self.chunk_index

    def sum_merge_with_next(self):
        """Обратный случай «Сохранить остаток»: автонарезка иногда режет
        ОДНО число на два отдельных дубля (например «55 тыс.» распалась на
        «50» и «5 тыс.» из-за паузы внутри фразы). Склеивает текущий дубль
        со следующим по очереди в один файл — прямо на диске, до отправки
        в Audacity."""
        paths, idx = self._sum_queue_paths()
        if idx >= len(paths) - 1:
            return {"error": "После текущего дубля нет следующего — склеивать не с чем."}

        path_a, path_b = paths[idx], paths[idx + 1]
        if not os.path.exists(path_a) or not os.path.exists(path_b):
            return {"error": "Один из файлов для склейки не найден на диске."}

        try:
            merged = AudioSegment.from_file(path_a).set_frame_rate(8000) + \
                     AudioSegment.from_file(path_b).set_frame_rate(8000)
            export_like(merged, path_a, path_a)
        except Exception as e:
            return {"error": f"Не удалось склеить файлы: {e}"}

        try:
            os.remove(path_b)
        except OSError:
            pass

        if self._sum_in_cascade():
            cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            del self.cascade_files[cat][idx + 1]
        else:
            del self.chunks_data[idx + 1]

        webview.windows[0].evaluate_js("showToast('🔗 Дубли склеены в один кусок');")
        return self.get_ui_state()

    def sum_fix_split(self, tier):
        """Одна кнопка вместо «Остаток»/«Склеить» — обе чинят одну и ту же
        проблему (автосрезка неправильно разбила цифры), только с разных
        сторон, и какую из них нужно применять, однозначно видно по
        состоянию: дубль уже открыт в Audacity (is_in_audacity, отправлен
        клавишей V) — значит сейчас выделяют нужный кусок на столе и его
        нужно сохранить под ожидаемым именем в выбранную ↑/↓ категорию
        (см. sum_send_selection_to_category); дубль ещё не отправляли —
        значит правят на уровне очереди дублей, склеивая текущий со
        следующим (sum_merge_with_next), чтобы услышать их одной фразой."""
        if getattr(self, 'is_in_audacity', False):
            return self.sum_send_selection_to_category(tier)
        return self.sum_merge_with_next()
