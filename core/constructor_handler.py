import os
import re
import time
import json
import webview
from pydub import AudioSegment
from utils.file_utils import FileUtils
from core.variables_handler import SUM_TIER_ORDER, SUM_TIER_LABELS, _numeric_sort_key


class ConstructorMixin:
    """«Конструктор переменных» — отдельный инструмент, не привязанный к
    очереди Excel/дублей: листаешь рулетками уже сохранённые значения по
    каждому ярусу «Суммы» и вручную собираешь любую комбинацию — послушать
    целиком или отправить на точечную правку в Audacity. Начинаем с
    «Суммы»; та же идея потом ляжет и на другие категории переменных."""

    def constructor_open_from_sum_mode(self):
        """Быстрый вход из уже запущенного режима «Суммы»: папка, старт и
        энд уже загружены этим режимом — просто переиспользуем их вместо
        того, чтобы заново спрашивать через диалоги выбора файлов."""
        cat_name = next(iter(getattr(self, 'sum_category_names', set()) or []), None)
        tier_files = getattr(self, 'sum_tier_files', {}).get(cat_name) if cat_name else None
        if not cat_name or not tier_files:
            return {"error": "Режим «Суммы» ещё не запущен в этом проекте — сначала включите его галочкой."}

        self.constructor_root = os.path.join(self.work_dir, cat_name)
        self.constructor_tier_files = {tier: list(tier_files.get(tier, [])) for tier in SUM_TIER_ORDER}
        self.constructor_start_file = getattr(self, 'var_start_phrase', None)
        self.constructor_end_file = getattr(self, 'var_end_phrase', None)

        return self._constructor_state()

    @staticmethod
    def _constructor_detect_lang_dir(name):
        """«Суммы RU» / «Суммы KZ» — отдельные подпапки для двух языков,
        каждая со своим полным набором ярусов внутри. Слово RU/KZ ищем как
        отдельное слово в названии (границы «_»/«-»/пробел), не как
        подстроку — чтобы не зацепить случайное совпадение."""
        parts = re.split(r'[_\-\s]+', name.lower())
        if 'ru' in parts:
            return 'ru'
        if 'kz' in parts:
            return 'kz'
        return None

    @staticmethod
    def _constructor_autodetect_tier_dirs(base_dir):
        """Ищет 5 ярусов внутри папки по словам-маркерам в названии
        подпапки — так же, как основной режим «Суммы» ищет их в своей
        папке (см. _build_sum_sequence в variables_handler.py), а не по
        точному совпадению целой строки. Из-за этого не важно, как именно
        написан ярус тысяч — «1 - 99 тыс» или «1 - 99 мың» (казахский) —
        и не ломается, если название на диске чуть отличается от
        эталонного (лишний пробел, дефис и т.п.)."""
        try:
            subdirs = [d for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d))]
        except OSError:
            return {}

        assigned = {}
        remaining = list(subdirs)

        def claim(tier, name):
            assigned[tier] = name
            remaining.remove(name)

        match = next((d for d in remaining if 'млн' in d.lower() or 'миллион' in d.lower()), None)
        if match:
            claim('millions', match)

        match = next((d for d in remaining if any(k in d.lower() for k in ('тенге', 'kzt', '₸'))), None)
        if match:
            claim('tenge', match)

        # «тыс» — русское слово тысяч, «мың» — казахское. Число в названии
        # отличает «Сотни тысяч» (100 и больше) от обычных «Тысяч».
        for d in [d for d in remaining if any(k in d.lower() for k in ('тыс', 'мың', 'мын'))]:
            nums = re.findall(r'\d+', d)
            tier = 'hundred_thousands' if nums and int(nums[0]) >= 100 else 'thousands'
            if tier not in assigned:
                claim(tier, d)

        if 'hundreds' not in assigned and len(remaining) == 1:
            claim('hundreds', remaining[0])

        return {tier: os.path.join(base_dir, name) for tier, name in assigned.items()}

    def _constructor_scan_tiers(self, base_dir, lang=None):
        dirs = self._constructor_autodetect_tier_dirs(base_dir)
        tiers = {}
        for tier in SUM_TIER_ORDER:
            sub = dirs.get(tier)
            files = []
            if sub and os.path.isdir(sub):
                files = [os.path.join(sub, f) for f in os.listdir(sub)
                         if os.path.isfile(os.path.join(sub, f)) and f.lower().endswith(('.wav', '.mp3'))]
                files.sort(key=_numeric_sort_key)
            tiers[tier] = files
        return tiers

    def constructor_pick_sum_folder(self):
        """Шаг 1: папка «Суммы». Поддерживает два формата — либо яруса
        лежат прямо в выбранной папке (как раньше), либо в ней есть
        подпапки «Суммы RU» и «Суммы KZ» (по слову RU/KZ в названии), а уже
        внутри них — яруса каждого языка отдельно. Во втором случае в
        интерфейсе появляется переключатель RU/KZ (см. constructor_set_lang)."""
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        root = folder[0]
        try:
            subdirs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
        except Exception as e:
            return {"error": f"Ошибка чтения папки: {e}"}

        lang_dirs = {}
        for d in subdirs:
            lang = self._constructor_detect_lang_dir(d)
            if lang and lang not in lang_dirs:
                lang_dirs[lang] = os.path.join(root, d)

        if not lang_dirs:
            lang_dirs = {'ru': root}

        lang = 'ru' if 'ru' in lang_dirs else next(iter(lang_dirs))
        tiers = self._constructor_scan_tiers(lang_dirs[lang], lang)

        if not any(tiers.values()):
            return {"error": "В этой папке не нашлось ни одного яруса «Суммы» — ни впрямую, ни внутри "
                              "подпапок «Суммы RU» / «Суммы KZ» (1 - 100 млн, 100 - 900, 1 - 99 тыс/мың, "
                              "1 - 100 тенге, 100 - 900 тыс/мың)."}

        self.constructor_root = root
        self.constructor_lang_dirs = lang_dirs
        self.constructor_lang = lang
        self.constructor_tier_files = tiers
        if not hasattr(self, 'constructor_start_file'):
            self.constructor_start_file = None
        if not hasattr(self, 'constructor_end_file'):
            self.constructor_end_file = None

        return self._constructor_state()

    def constructor_set_lang(self, lang):
        """Переключатель RU/KZ — перечитывает те же 5 ярусов, но уже из
        другой языковой подпапки, найденной при выборе папки."""
        lang_dirs = getattr(self, 'constructor_lang_dirs', None) or {}
        if lang not in lang_dirs:
            return {"error": f"Папка «Суммы {lang.upper()}» не найдена в выбранной папке."}

        self.constructor_lang = lang
        self.constructor_tier_files = self._constructor_scan_tiers(lang_dirs[lang], lang)
        return self._constructor_state()

    def constructor_pick_start(self):
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                    file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not f:
            return {"error": "cancel"}
        self.constructor_start_file = f[0]
        return self._constructor_state()

    def constructor_pick_end(self):
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                    file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not f:
            return {"error": "cancel"}
        self.constructor_end_file = f[0]
        return self._constructor_state()

    def _constructor_state(self):
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        lang_dirs = getattr(self, 'constructor_lang_dirs', None) or {}
        return {
            "root": getattr(self, 'constructor_root', None),
            "lang": getattr(self, 'constructor_lang', 'ru'),
            "lang_available": [l for l in ('ru', 'kz') if l in lang_dirs],
            "start": os.path.basename(self.constructor_start_file) if getattr(self, 'constructor_start_file', None) else None,
            "end": os.path.basename(self.constructor_end_file) if getattr(self, 'constructor_end_file', None) else None,
            "tiers": {
                tier: {
                    "label": SUM_TIER_LABELS[tier],
                    "items": [os.path.splitext(os.path.basename(p))[0] for p in tiers.get(tier, [])],
                }
                for tier in SUM_TIER_ORDER
            },
        }

    def _constructor_ordered_segments(self, indices):
        """Порядок сборки для прослушки/правки — строго как колонки в
        загруженной таблице-словаре (var_template_columns), если она
        есть: связки (start, start_2...) на своих местах между
        категориями, доп.категории (mark/year/...) звучат для
        естественного контекста вокруг суммы, но НЕ сохраняются через
        constructor_save/sum_stage2_save — они уже готовы как есть после
        сырой сортировки, обрезка по таймингу им не нужна (в отличие от
        многозначных сумм). Без словаря (старый чистый «Конструктор» по
        папке «Суммы» без Excel) — прежний порядок: start, 5 ярусов
        Суммы, end.

        Возвращает список (key, filepath, saveable) — saveable=True
        только у тех сегментов, что действительно можно сохранить
        обратно (ярусы Суммы)."""
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        columns = getattr(self, 'var_template_columns', None)

        if not columns:
            segments = []
            if getattr(self, 'constructor_start_file', None) and os.path.exists(self.constructor_start_file):
                segments.append(('start', self.constructor_start_file, False))
            for tier in SUM_TIER_ORDER:
                files = tiers.get(tier, [])
                idx = (indices or {}).get(tier)
                if files and isinstance(idx, int) and 0 <= idx < len(files):
                    segments.append((tier, files[idx], True))
            if getattr(self, 'constructor_end_file', None) and os.path.exists(self.constructor_end_file):
                segments.append(('end', self.constructor_end_file, False))
            return segments

        connectors_by_key = {c['key']: c.get('path') for c in getattr(self, 'var_connectors', [])}
        segments = []
        for col in columns:
            if col['type'] == 'connector':
                path = connectors_by_key.get(col['key'])
                if path and os.path.exists(path):
                    segments.append((col['key'], path, False))
            else:
                key = col['key']
                files = tiers.get(key, [])
                idx = (indices or {}).get(key)
                if files and isinstance(idx, int) and 0 <= idx < len(files):
                    segments.append((key, files[idx], col['type'] == 'sum'))
        return segments

    def constructor_play(self, indices):
        """«Играть»: вся сборка по порядку таблицы одной сплошной склейкой."""
        segments = self._constructor_ordered_segments(indices)
        if not segments:
            return {"playing": False, "duration": 0, "error": "Нечего проигрывать — выберите значения на рулетках."}

        try:
            self.player.stop()
            combined = None
            for _key, path, _saveable in segments:
                seg = AudioSegment.from_file(path).set_frame_rate(8000)
                combined = seg if combined is None else combined + seg
            temp_path = os.path.join(self.constructor_root, f"temp_constructor_preview_{int(time.time() * 1000)}.wav")
            combined.export(temp_path, format="wav")
            duration = FileUtils.get_exact_audio_duration(temp_path)
            self.player.play(temp_path)
            return {"playing": True, "duration": duration}
        except Exception as e:
            return {"playing": False, "duration": 0, "error": f"Не удалось проиграть: {e}"}

    def constructor_send_to_audacity(self, indices):
        """«Обновить сумму»: та же сборка, что и «Играть», но кладётся на
        стол Audacity отдельными клипами для ручной правки, а не для
        прослушивания."""
        segments = self._constructor_ordered_segments(indices)
        if not any(saveable for _key, _path, saveable in segments):
            return {"error": "Выберите хотя бы одно значение яруса Суммы на рулетке — остальные категории "
                              "только звучат вокруг него для контекста, сохраняется через эту сборку "
                              "только сумма."}

        if self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы продолжить."}
        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        layout = []
        active_paths = {}
        cursor = 0.0
        for key, path, saveable in segments:
            cursor += self._import_clip_to_track0(path, cursor)
            layout.append(key)
            if saveable:
                active_paths[key] = path

        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start=0 End={cursor + 5.0} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        self.audacity.send_command('SetProject: Rate=8000')

        self.is_in_audacity = True
        self._constructor_clip_layout = layout
        self._constructor_active_paths = active_paths

        windows = self.get_audacity_windows()
        if windows:
            self._force_foreground(windows[0]['hwnd'])

        webview.windows[0].evaluate_js(
            "showToast('Сумма отправлена в Audacity — поправьте и нажмите «Сохранить»');")
        return {"status": "ok"}

    def constructor_save(self):
        """«Сохранить»: экспортирует каждый скорректированный кусок обратно
        поверх исходного файла с рулетки — только по явному нажатию,
        ничего не переписывается само по себе при простой правке в Audacity."""
        layout = getattr(self, '_constructor_clip_layout', None)
        active_paths = getattr(self, '_constructor_active_paths', None)
        if not layout or not active_paths:
            return {"error": "Сначала нажмите «Обновить сумму», чтобы отправить её в Audacity."}

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

        saved = 0
        for tag, clip in zip(layout, track_0_clips):
            path = active_paths.get(tag)
            if not path:
                continue
            c_start, c_end = clip.get('start', 0.0), clip.get('end', 0.0)
            self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={c_start} End={c_end} RelativeTo=ProjectStart')
            self.audacity.send_command(f'Export2: Filename="{path}" NumChannels=1')
            time.sleep(0.1)
            saved += 1

        webview.windows[0].evaluate_js(f"showToast('💾 Сохранено кусков: {saved}');")
        return {"status": "ok", "saved": saved}
