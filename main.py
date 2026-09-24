import os
import time
import webview
import sys
from pydub import AudioSegment

# 🧠 Основная логика (миксины из папки core)
from core.variables_handler import VariablesMixin
from core.phrase_handler import PhrasesMixin
from core.project_handler import ProjectMixin
from core.audacity_montage import MontageMixin
from core.converter import ConverterMixin
from core.constructor_handler import ConstructorMixin
from core.filename_match_handler import FilenameMatchMixin
from core.table_to_pptx_handler import TableToPptxMixin
from core import project_state

# 🛠 Вспомогательные утилиты (из папки utils)
from utils.audacity_client import AudacityClient
from utils.audio_player import AudioPlayer
from utils.file_utils import FileUtils
from utils.ffmpeg_setup import ensure_ffmpeg

# Папка, где реально лежит main.py — а не «текущая рабочая папка» (cwd),
# которая зависит от того, откуда программу запустили.
APP_DIR = os.path.dirname(os.path.abspath(__file__))


class Api(VariablesMixin, PhrasesMixin, ProjectMixin, MontageMixin, ConverterMixin, ConstructorMixin, FilenameMatchMixin, TableToPptxMixin):
    def __init__(self):
        super().__init__()

        self.phrases_data = []
        self.chunks_data = []
        self.phrase_index = 0
        self.chunk_index = 0
        self.work_dir = ""

        self.raw_audio_full = None
        self.current_mode = 'Chunks'
        self.state_memory = {'Chunks': [0, 0], 'Переменные': [0, 0], 'Проверенные': [0, 0]}

        self.excel_name = ""
        self.project_name = ""
        self.variables = {'date': None, 'name': None, 'amount': None}
        self.last_montage_sequence = []

        self.audacity = AudacityClient()
        self.player = AudioPlayer()

    def sync_and_play(self):
        """Синхронизирует зум в Audacity и запускает воспроизведение"""
        self._sync_audacity_selection()
        return self.play_audio()

    def play_audio(self, toggle=False):
        """Логика воспроизведения: приоритет отдается сохраненным (Проверенным) файлам"""

        # Останавливаем, если уже играет и запрошен toggle
        if toggle and self.player.is_playing:
            self.player.stop()
            return {"playing": False, "duration": 0}

        file_to_play = None

        # 0. РЕЖИМ «СУММЫ»: проигрываем всю накопленную цепочку целиком —
        # уже сохранённые ярусы + тот, над которым сейчас работаем — без
        # пауз между ними, а не только то, что видно на экране сейчас.
        # Работает и поверх обычной нарезки, и внутри конвейера «Готовые
        # переменные», поэтому проверяем это раньше остальных режимов.
        if getattr(self, 'sum_manual_active', False):
            segments = self._sum_full_preview_segments()
            if not segments:
                return {"playing": False, "duration": 0}
            try:
                self.player.stop()
                combined = None
                markers = []
                cursor = 0.0
                for seg in segments:
                    clip = AudioSegment.from_file(seg['path']).set_frame_rate(8000)
                    dur = len(clip) / 1000.0
                    if seg['label']:
                        markers.append({"label": seg['label'], "start": cursor, "end": cursor + dur})
                    combined = clip if combined is None else combined + clip
                    cursor += dur
                # Имя временного файла — с меткой времени, а не одно и то же
                # каждый раз: если предыдущее воспроизведение (Windows,
                # winsound) не успело до конца отпустить файл, перезапись
                # того же имени обрывала звук на середине первого яруса.
                temp_path = os.path.join(self.work_dir, f"temp_sum_preview_{int(time.time() * 1000)}.wav")
                combined.export(temp_path, format="wav")
                duration = FileUtils.get_exact_audio_duration(temp_path)
                self.player.play(temp_path)
                return {"playing": True, "duration": duration, "segments": markers, "source": "chain"}
            except Exception as e:
                print(f"Ошибка склейки превью (Суммы): {e}")
                return {"playing": False, "duration": 0}

        # 1. ЛОГИКА ДЛЯ РЕЖИМА ПЕРЕМЕННЫХ (VarBatch)
        if self.current_mode == 'VarBatch':
            active_cat = self.cascade_ordered_cats[self.cascade_active_cat_idx]
            active_idx = self.cascade_ptrs[active_cat]
            if active_idx >= len(self.cascade_files[active_cat]):
                return {"playing": False, "duration": 0}
            active_file = self.cascade_files[active_cat][active_idx]

            # «Суммы»: своя склейка — start + уже сохранённые референсы
            # с других ярусов (в порядке Миллионы→Сотни→Тысячи→Тенге) +
            # активный ярус + end, а не просто start+фраза+end.
            if active_cat in getattr(self, 'sum_category_names', set()):
                meta = self.sum_meta[active_cat][active_idx]
                tier_dir = self.sum_tier_dirs[active_cat][meta['tier']]
                file_to_play = active_file
                if hasattr(self, 'cascade_checked_files') and active_file in self.cascade_checked_files:
                    save_name = os.path.basename(active_file)
                    saved_path = os.path.join(self.work_dir, 'Проверенные', active_cat, tier_dir, save_name)
                    if os.path.exists(saved_path):
                        file_to_play = saved_path

                if not os.path.exists(file_to_play):
                    return {"playing": False, "duration": 0}

                try:
                    segments = self._sum_ordered_segments(active_cat, file_to_play, active_idx)
                    self.player.stop()
                    combined = None
                    for _, path in segments:
                        seg = AudioSegment.from_file(path).set_frame_rate(8000)
                        combined = seg if combined is None else combined + seg
                    if combined is not None:
                        temp_path = os.path.join(self.work_dir, "temp_var_preview.wav")
                        combined.export(temp_path, format="wav")
                        file_to_play = temp_path
                except Exception as e:
                    print(f"Ошибка склейки превью (Суммы): {e}")

                duration = FileUtils.get_exact_audio_duration(file_to_play)
                self.player.play(file_to_play)
                return {"playing": True, "duration": duration, "source": "chain"}

            file_to_play = active_file  # По умолчанию берем черновик

            # Если файл уже "Проверен" (сохранен), ищем его финальное имя
            if hasattr(self, 'cascade_checked_files') and active_file in self.cascade_checked_files:
                curr_phrase_idx = getattr(self, 'phrase_index', 0)
                save_name = os.path.basename(active_file)
                if getattr(self, 'phrases_data', None) and curr_phrase_idx < len(self.phrases_data):
                    excel_filename = self.phrases_data[curr_phrase_idx].get("filename")
                    if excel_filename:
                        save_name = str(excel_filename) if str(excel_filename).lower().endswith(
                            '.wav') else f"{excel_filename}.wav"

                target_dir = os.path.join(self.work_dir,
                                          'Проверенные') if active_cat == "Имена (Плоский список)" else os.path.join(
                    self.work_dir, 'Проверенные', active_cat)
                saved_path = os.path.abspath(os.path.join(target_dir, save_name)).replace('\\', '/')
                if os.path.exists(saved_path):
                    file_to_play = saved_path

            if not os.path.exists(file_to_play):
                return {"playing": False, "duration": 0}

            # Источник для подсветки на экране: «saved» — уже сохранённая,
            # проверенная версия, «draft» — черновик прямо из дублей, ещё
            # не сохранённый. Раньше отличить на слух/на экране было нечем —
            # обе подсвечивались одинаково жёлтым.
            play_source = "saved" if file_to_play != active_file else "draft"

            # === МАГИЯ БЕСШОВНОЙ СКЛЕЙКИ START + PHRASE + END НА ЛЕТУ ===
            # end может отсутствовать (режим «только start») — тогда просто
            # не приклеиваем его, а не отказываемся от склейки целиком.
            has_start = bool(getattr(self, 'var_start_phrase', None)) and os.path.exists(self.var_start_phrase)
            has_end = bool(getattr(self, 'var_end_phrase', None)) and os.path.exists(self.var_end_phrase)
            try:
                if has_start or has_end:
                    # Тормозим плеер перед генерацией новой склейки
                    self.player.stop()

                    # Приводим все куски к одной частоте (8000 Гц) перед склейкой.
                    # Раньше это не делалось: start.wav часто уже был 8000 Гц (создан
                    # программой), а сама фраза — в частоте исходной записи (обычно
                    # 44100/48000 Гц). При склейке кусков с разной частотой без
                    # приведения к одной середина трека звучала искажённо.
                    combined = AudioSegment.from_file(file_to_play).set_frame_rate(8000)
                    if has_start:
                        combined = AudioSegment.from_file(self.var_start_phrase).set_frame_rate(8000) + combined
                    if has_end:
                        combined = combined + AudioSegment.from_file(self.var_end_phrase).set_frame_rate(8000)

                    temp_path = os.path.join(self.work_dir, "temp_var_preview.wav")
                    combined.export(temp_path, format="wav")

                    # Перенаправляем плеер на наш склеенный идеальный файл
                    file_to_play = temp_path
            except Exception as e:
                print(f"Ошибка склейки превью: {e}")
                pass

            duration = FileUtils.get_exact_audio_duration(file_to_play)
            self.player.play(file_to_play)
            return {"playing": True, "duration": duration, "source": play_source}

        # 2. ЛОГИКА ДЛЯ ОСНОВНЫХ РЕЖИМОВ (Chunks, Проверенные и т.д.)
        if not self.chunks_data or self.chunk_index >= len(self.chunks_data):
            return {"playing": False, "duration": 0}

        item = self.chunks_data[self.chunk_index]
        source_path = item['filepath']
        current_chunk_name = item['filename']

        file_to_play = source_path  # Сырой файл по умолчанию

        # Определяем идеальное имя для поиска в готовых папках (из Excel)
        check_name = current_chunk_name
        if self.phrases_data and self.phrase_index < len(self.phrases_data):
            custom = self.phrases_data[self.phrase_index].get("filename")
            if custom:
                check_name = custom if custom.lower().endswith('.wav') else f"{custom}.wav"

        # Ищем сохраненный файл по приоритетам (Проверенные -> Переменные)
        if self.work_dir:
            checked_path = os.path.join(self.work_dir, 'Проверенные', check_name)
            var_path = os.path.join(self.work_dir, 'Переменные', check_name)

            # Если файл есть в Проверенных - играем его!
            if os.path.exists(checked_path):
                file_to_play = checked_path
            # Иначе если он есть в Переменных - играем его
            elif os.path.exists(var_path):
                file_to_play = var_path

        # Источник для подсветки на экране (см. пометку выше в VarBatch):
        # «saved» — нашли уже сохранённую версию, «draft» — играем сырой
        # дубль как есть.
        play_source = "saved" if file_to_play != source_path else "draft"

        # Если файл так и не готов, и мы в режиме "Chunks" - вырезаем динамический кусок (черновик)
        if file_to_play == source_path and self.current_mode == 'Chunks' and 'start' in item and 'end' in item and self.raw_audio_full is not None:
            try:
                start_ms, end_ms = int(item['start'] * 1000), int(item['end'] * 1000)
                temp_audio = self.raw_audio_full[start_ms:end_ms].set_frame_rate(8000)
                temp_path = os.path.join(self.work_dir, "temp_play.wav")
                temp_audio.export(temp_path, format="wav")
                file_to_play = temp_path
            except:
                pass

        if not os.path.exists(file_to_play):
            return {"playing": False, "duration": 0}

        duration = FileUtils.get_exact_audio_duration(file_to_play)
        self.player.play(file_to_play)
        return {"playing": True, "duration": duration, "source": play_source}

    def play_specific_file(self, filepath):
        """Проигрывание конкретного файла (используется для переменных).
        Всегда уже сохранённый/проверенный файл — вызывается только когда
        state.completed_filepath есть."""
        self.player.stop()
        if filepath and os.path.exists(filepath):
            duration = FileUtils.get_exact_audio_duration(filepath)
            self.player.play(filepath)
            return {"playing": True, "duration": duration, "source": "saved"}
        return {"playing": False, "duration": 0}

    def stop_audio(self):
        """Остановка плеера"""
        self.player.stop()
        return {"playing": False, "duration": 0}

    @staticmethod
    def _count_audio(folder):
        """Сколько аудиофайлов лежит в папке (вместе с подпапками)."""
        if not folder or not os.path.exists(folder):
            return 0
        return sum(len([f for f in files if f.lower().endswith(('.wav', '.mp3'))])
                   for _, _, files in os.walk(folder))

    def get_ui_state(self):
        """Сборка состояния приложения для фронтенда (JS)"""

        # НОВОВВЕДЕНИЕ: Полная блокировка стандартного UI во время работы конвейера.
        # Это предотвратит любую попытку бекенда сбросить экран переменных на стандартный.
        if getattr(self, 'current_mode', '') == 'VarBatch':
            state = self._get_var_batch_ui_state()
            # Режим «Суммы» работает и внутри конвейера — панель должна
            # обновляться и здесь, иначе счётчики застывают.
            if getattr(self, 'sum_manual_active', False) and isinstance(state, dict):
                state["sum_mode"] = self.get_sum_manual_state()
            return state

        # «Готово» — это файлы в «Проверенных». Папка Good — наследие
        # двухступенчатого отбора, которого в программе больше нет.
        done_dir = os.path.join(self.work_dir, 'Проверенные') if self.work_dir else ""
        var_dir = os.path.join(self.work_dir, 'Переменные') if self.work_dir else ""

        state = {
            "mode": self.current_mode,
            "screen": "main",
            "phrase_text": "Загрузите Excel" if not self.phrases_data else "Все фразы удалены",
            "phrase_counter": f"0 / {len(self.phrases_data)}",
            "custom_filename": "",
            "chunk_name": "Загрузите аудио",
            "chunk_counter": f"0 / {len(self.chunks_data)}",
            "has_audio": False, "is_done": False, "is_var": False, "is_checked": False,
            "raw_chunk_name": "", "filepath": "", "completed_filepath": None,
            "excel_loaded": bool(self.phrases_data),
            "stats": {
                "total": len(self.phrases_data),
                "good": self._count_audio(done_dir),
                "var": self._count_audio(var_dir),
                "checked": sum(1 for p in self.phrases_data if p.get("checked", False)),
                "excel_name": getattr(self, 'excel_name', ""),
                "project_name": getattr(self, 'project_name', "")
            }
        }

        # Привязка текста из Excel
        if self.phrases_data and self.phrase_index < len(self.phrases_data):
            state["phrase_text"] = self.phrases_data[self.phrase_index]["text"]
            state["phrase_counter"] = f"{self.phrase_index + 1} / {len(self.phrases_data)}"
            state["custom_filename"] = self.phrases_data[self.phrase_index]["filename"]
            state["is_checked"] = self.phrases_data[self.phrase_index].get("checked", False)

        # Привязка текущего аудиофайла
        if self.chunks_data and self.chunk_index < len(self.chunks_data):
            current_chunk = self.chunks_data[self.chunk_index]['filename']
            state["filepath"] = self.chunks_data[self.chunk_index]['filepath']
            state["chunk_name"] = current_chunk
            state["raw_chunk_name"] = current_chunk.replace('.wav', '').replace('.mp3', '')
            state["chunk_counter"] = f"{self.chunk_index + 1} / {len(self.chunks_data)}"
            state["has_audio"] = True

            # Синхронизация имени чанка с Excel-базой в отсортированных папках
            if self.current_mode in ['Переменные', 'Проверенные'] and self.phrases_data:
                name_no_ext = current_chunk.replace('.wav', '').replace('.mp3', '')
                for i, p in enumerate(self.phrases_data):
                    if p["filename"] == name_no_ext or f"фраза_{i + 1:04d}" == name_no_ext:
                        state["phrase_text"] = p["text"]
                        state["custom_filename"] = p["filename"]
                        state["phrase_counter"] = f"{i + 1} / {len(self.phrases_data)}"
                        state["is_checked"] = p.get("checked", False)
                        state["raw_chunk_name"] = f"фраза_{i + 1:04d}"
                        self.phrase_index = i
                        break

            # Проверка готовности файла
            check_name = f"{state['custom_filename']}.wav" if state['custom_filename'] and not state[
                'custom_filename'].lower().endswith('.wav') else (state['custom_filename'] or current_chunk)

            var_path = os.path.join(self.work_dir, 'Переменные', check_name)
            checked_path = os.path.join(self.work_dir, 'Проверенные', check_name)

            state["completed_filepath"] = None

            if os.path.exists(checked_path):
                state["completed_filepath"] = checked_path
                state["is_checked"] = True
                state["is_done"] = True
            elif os.path.exists(var_path):
                state["is_var"] = True
                state["completed_filepath"] = var_path

        # Лента дублей: статусы соседних дублей для полоски под счётчиком
        state["strip"] = self._build_chunk_strip()

        # Режим «Суммы»: счётчики ярусов и то, куда уйдёт текущая строка
        if getattr(self, 'sum_manual_active', False):
            state["sum_mode"] = self.get_sum_manual_state()

        # Автосохранение: снимок проекта пишется на диск при каждом обновлении
        # экрана, поэтому закрытие программы больше не стирает прогресс.
        project_state.save(self)

        # ВАЖНО: состояние возвращается всегда, даже если аудио ещё не загружено.
        # Раньше return стоял внутри блока "если есть чанки", и после загрузки
        # одного только Excel фронтенд получал пустой ответ (None) и ничего не обновлял.
        return state

    def to_view(self):
        """Единая точка получения состояния экрана.

        Раньше фронтенд должен был знать, что для обычного режима нужен
        get_ui_state(), а для режима переменных — свой отдельный сборщик.
        Внутри всё та же логика (она пока не трогалась, чтобы ничего не
        сломать), но теперь есть одно имя, за которым можно спрятать оба
        сборщика и любые будущие. Поле "screen" в ответе говорит, какой
        именно экран пришёл: "main" или "varbatch"."""
        return self.get_ui_state()

    # Регистр действий основного рабочего экрана для dispatch(). Каждая
    # запись — это имя действия и функция, которая достаёт аргументы из
    # payload и вызывает уже существующий, проверенный метод. Сами методы
    # (navigate_chunk, process_action и т.д.) не меняются ни на строку —
    # dispatch() лишь даёт им одну общую дверь.
    _MAIN_SCREEN_ACTIONS = {
        "navigate":    lambda api, p: api.navigate_chunk(p.get("direction", 1), p.get("auto_play", True)),
        "jump":        lambda api, p: api.jump_to_chunk(p.get("index", 0)),
        "save":        lambda api, p: api.process_action(p.get("kind"), p.get("add_silence", False)),
        "play":        lambda api, p: api.play_audio(p.get("toggle", False)),
        "play_sync":   lambda api, p: api.sync_and_play(),
        "stop":        lambda api, p: api.stop_audio(),
        "switch_mode": lambda api, p: api._switch_mode(p.get("mode")),
    }

    # Папки проекта, между которыми переключается основной экран. Отдельная
    # точка, а не условия внутри dispatch(), чтобы регистр действий выше
    # оставался плоским и читаемым.
    _MODE_SWITCHERS = {
        "chunks":  lambda api: api.load_main_mode(),
        "checked": lambda api: api.load_checked_mode(),
    }

    def _switch_mode(self, mode):
        fn = self._MODE_SWITCHERS.get(mode)
        if fn is None:
            return {"error": f"Неизвестный режим: {mode}"}
        return fn(self)

    def dispatch(self, action, payload=None):
        """Единая точка входа для действий основного экрана: навигация по
        дублям, сохранение (Проверено/В переменные), воспроизведение.

        Это дополнительный слой поверх существующих методов — они и сами
        по себе продолжают работать, ничего не удалено. Фронтенд можно
        переводить на dispatch() постепенно, кнопка за кнопкой, вместо
        одной рискованной правки сразу везде."""
        payload = payload or {}
        handler = self._MAIN_SCREEN_ACTIONS.get(action)
        if handler is None:
            return {"error": f"Неизвестное действие: {action}"}
        return handler(self, payload)


def resource_path(relative_path):
    """
    Помогает .exe файлу найти папку frontend во временной директории Windows.
    Без этой функции будет белый экран.
    """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def _startup(window):
    """Выполняется уже после того, как окно поднялось — можно показывать
    прогресс через тот же progressContainer, что и вырезка/конвертация.

    Собранный .exe (PyInstaller) везёт ffmpeg.exe/ffprobe.exe прямо внутри
    себя — скачивать тут нечего, коллеги без интернета/за блокировками
    получают рабочий софт из коробки. Автоскачивание нужно только когда
    запускают main.py напрямую (не из собранного .exe) и файлов рядом ещё
    нет — например, на компьютере разработчика при первой настройке."""
    if getattr(sys, 'frozen', False):
        AudioSegment.converter = resource_path("ffmpeg.exe")
        AudioSegment.ffprobe = resource_path("ffprobe.exe")
        return

    def report(percent, text):
        try:
            window.evaluate_js(
                f"document.getElementById('progressContainer').style.display='block';"
                f"updateProgress({percent}, {text!r});"
            )
        except Exception:
            pass

    ok = ensure_ffmpeg(APP_DIR, on_progress=report)

    try:
        window.evaluate_js("document.getElementById('progressContainer').style.display='none';")
    except Exception:
        pass

    if not ok:
        try:
            window.evaluate_js(
                "showBeautifulAlert('⚠️ <b>Не удалось скачать ffmpeg автоматически</b>"
                "<br><br>Проверьте интернет-соединение или положите ffmpeg.exe и "
                "ffprobe.exe в папку программы вручную (рядом с main.py) и перезапустите.');"
            )
        except Exception:
            pass

    AudioSegment.converter = os.path.join(APP_DIR, "ffmpeg.exe")
    AudioSegment.ffprobe = os.path.join(APP_DIR, "ffprobe.exe")


if __name__ == '__main__':
    api = Api()

    html_path = resource_path('frontend/index.html')

    window = webview.create_window('G2Studio | Автосрезка', html_path, js_api=api, width=1600, height=980)
    # Если Audacity был вживлён в окно софта, при закрытии его нужно вернуть
    # обратно отдельным окном — иначе он останется «сиротой» без родителя.
    window.events.closing += lambda: api.unembed_audacity()
    webview.start(_startup, window)