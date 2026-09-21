import os
import time
import json
import webview
from pydub import AudioSegment
from utils.file_utils import FileUtils
from core.variables_handler import SUM_TIER_ORDER, SUM_TIER_LABELS, SUM_TIER_DEFAULT_DIR, _numeric_sort_key


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

    def constructor_pick_sum_folder(self):
        """Шаг 1: папка «Суммы» — та же, что режим «Суммы» создаёт сам,
        с подпапками-ярусами внутри (по одной на каждый ярус из
        SUM_TIER_ORDER). Яруса без своей подпапки остаются
        просто пустыми рулетками, а не ошибкой."""
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"error": "cancel"}

        root = folder[0]
        tiers = {}
        for tier in SUM_TIER_ORDER:
            sub = os.path.join(root, SUM_TIER_DEFAULT_DIR[tier])
            files = []
            if os.path.isdir(sub):
                files = [os.path.join(sub, f) for f in os.listdir(sub)
                         if os.path.isfile(os.path.join(sub, f)) and f.lower().endswith(('.wav', '.mp3'))]
                files.sort(key=_numeric_sort_key)
            tiers[tier] = files

        if not any(tiers.values()):
            return {"error": "В этой папке не нашлось ни одного яруса «Суммы» "
                              "(1 - 100 млн, 100 - 900, 1 - 99 тыс, 1 - 100 тенге)."}

        self.constructor_root = root
        self.constructor_tier_files = tiers
        if not hasattr(self, 'constructor_start_file'):
            self.constructor_start_file = None
        if not hasattr(self, 'constructor_end_file'):
            self.constructor_end_file = None

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

    def constructor_skip_end(self):
        """Записи может не быть окончания — тот же случай «только start»,
        что и в остальном софте."""
        self.constructor_end_file = None
        return self._constructor_state()

    def _constructor_state(self):
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        return {
            "root": getattr(self, 'constructor_root', None),
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

    def _constructor_selected_paths(self, indices):
        """indices: {tier: int} -> {tier: filepath}, только для реально
        существующих позиций (рулетка могла отдать индекс мимо списка)."""
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        result = {}
        for tier in SUM_TIER_ORDER:
            files = tiers.get(tier, [])
            idx = (indices or {}).get(tier)
            if files and isinstance(idx, int) and 0 <= idx < len(files):
                result[tier] = files[idx]
        return result

    def constructor_play(self, indices):
        """«Играть»: start + выбранные на рулетках значения по всем ярусам
        (Миллионы→Сотни→Тысячи→Тенге) + end — одной сплошной склейкой."""
        selected = self._constructor_selected_paths(indices)
        segments = []
        if getattr(self, 'constructor_start_file', None) and os.path.exists(self.constructor_start_file):
            segments.append(self.constructor_start_file)
        for tier in SUM_TIER_ORDER:
            path = selected.get(tier)
            if path and os.path.exists(path):
                segments.append(path)
        if getattr(self, 'constructor_end_file', None) and os.path.exists(self.constructor_end_file):
            segments.append(self.constructor_end_file)

        if not segments:
            return {"playing": False, "duration": 0, "error": "Нечего проигрывать — выберите значения на рулетках."}

        try:
            self.player.stop()
            combined = None
            for path in segments:
                seg = AudioSegment.from_file(path).set_frame_rate(8000)
                combined = seg if combined is None else combined + seg
            temp_path = os.path.join(self.constructor_root, "temp_constructor_preview.wav")
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
        selected = self._constructor_selected_paths(indices)
        if not selected:
            return {"error": "Выберите хотя бы одно значение на рулетках."}

        if self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы продолжить."}
        if not self._ensure_audacity_ready():
            return {"error": "Не удалось запустить Audacity. Откройте его вручную и нажмите кнопку ещё раз."}

        self.audacity.send_command('SelectAll:')
        self.audacity.send_command('RemoveTracks:')
        self.audacity.send_command('NewMonoTrack:')

        layout = []
        cursor = 0.0
        if getattr(self, 'constructor_start_file', None) and os.path.exists(self.constructor_start_file):
            cursor += self._import_clip_to_track0(self.constructor_start_file, cursor)
            layout.append('start')

        active_paths = {}
        for tier in SUM_TIER_ORDER:
            path = selected.get(tier)
            if path and os.path.exists(path):
                cursor += self._import_clip_to_track0(path, cursor)
                layout.append(tier)
                active_paths[tier] = path

        if getattr(self, 'constructor_end_file', None) and os.path.exists(self.constructor_end_file):
            self._import_clip_to_track0(self.constructor_end_file, cursor)
            cursor += FileUtils.get_exact_audio_duration(self.constructor_end_file)
            layout.append('end')

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
