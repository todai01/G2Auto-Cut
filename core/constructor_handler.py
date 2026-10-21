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
        self.constructor_sheets, self.constructor_kind, self.constructor_phrases = [], 'sum', []
        self.constructor_order, self.constructor_labels = list(SUM_TIER_ORDER), dict(SUM_TIER_LABELS)
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

        from core.variables_handler import sum_tier_from_dirname
        for d in list(remaining):                          # новый формат: million_ru, thousand_ru…
            t = sum_tier_from_dirname(d)
            if t and t not in assigned:
                claim(t, d)

        match = None if 'millions' in assigned else next((d for d in remaining if 'млн' in d.lower() or 'миллион' in d.lower()), None)
        if match:
            claim('millions', match)

        match = None if 'tenge' in assigned else next((d for d in remaining if any(k in d.lower() for k in ('тенге', 'kzt', '₸'))), None)
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

    # ---- папка «Значения» (единый формат Студии): Значения/<лист>/<категория>/<значение>.wav ----
    CTOR_CAT_ORDER = ('day', 'month', 'year')
    CTOR_CAT_LABELS = {'day': 'День', 'month': 'Месяц', 'year': 'Год'}

    @staticmethod
    def _ctor_norm(name):
        return re.sub(r'[\s\-–—_.]+', '', str(name or '').lower())

    def _constructor_values_root(self, root):
        """Папка «Значения» от выбранной: сама «Значения», папка проекта с ней
        или лист внутри неё («Значения/sum_kz»). → (корень, лист или None)."""
        root = os.path.normpath(root)
        if self._ctor_norm(os.path.basename(root)) == 'значения':
            return root, None
        inner = next((os.path.join(root, d) for d in self._ctor_listdirs(root) if self._ctor_norm(d) == 'значения'), None)
        if inner:
            return inner, None
        parent = os.path.dirname(root)
        if self._ctor_norm(os.path.basename(parent)) == 'значения':
            return parent, os.path.basename(root)
        return None, None

    @staticmethod
    def _ctor_listdirs(path):
        try:
            return sorted(d for d in os.listdir(path) if os.path.isdir(os.path.join(path, d)))
        except OSError:
            return []

    @staticmethod
    def _ctor_audio(path):
        try:
            return [os.path.join(path, f) for f in os.listdir(path)
                    if os.path.isfile(os.path.join(path, f)) and f.lower().endswith(('.wav', '.mp3'))]
        except OSError:
            return []

    def _constructor_values_sheets(self, vroot):
        """Листы «Значения»: суммы (ярусы) и остальные (категории как есть)."""
        sheets = []
        for d in self._ctor_listdirs(vroot):
            path = os.path.join(vroot, d)
            cats = [c for c in self._ctor_listdirs(path) if self._ctor_audio(os.path.join(path, c))]
            if not cats:
                continue
            from core.variables_handler import sum_tier_from_dirname
            kind = 'sum' if any(sum_tier_from_dirname(c) for c in cats) else 'other'
            lm = re.search(r'_(ru|kz|kk)$', d.lower())
            lang = ('KZ' if lm.group(1) in ('kz', 'kk') else 'RU') if lm else ''
            base = re.sub(r'_(ru|kz|kk)$', '', d.lower())
            title = {'sum': 'Сумма', 'date': 'Дата'}.get(base, d)
            sheets.append({"key": d, "label": f"{title} {lang}".strip(), "kind": kind, "path": path})
        return sheets

    def _constructor_load_sheet(self, sheet):
        """Рулетки листа: сумма — 5 ярусов как раньше; другой лист — его категории."""
        self.constructor_sheet = sheet["key"]
        self.constructor_kind = sheet["kind"]
        self.constructor_phrases = self._constructor_phrases()
        if self.constructor_phrases:
            pos = next((k for k, x in enumerate(self.constructor_phrases) if x["start_path"]), 0)
            self.constructor_phrase_pos = pos
            self._constructor_apply_phrase()
        if sheet["kind"] == 'sum':
            self.constructor_tier_files = self._constructor_scan_tiers(sheet["path"])
            self.constructor_order = list(SUM_TIER_ORDER)
            self.constructor_labels = dict(SUM_TIER_LABELS)
            return
        from core.num_words import month_abbr
        cats = [c for c in self._ctor_listdirs(sheet["path"]) if self._ctor_audio(os.path.join(sheet["path"], c))]
        base = lambda c: re.sub(r'_(ru|kz|kk)$', '', c.lower())
        cats.sort(key=lambda c: (self.CTOR_CAT_ORDER.index(base(c)) if base(c) in self.CTOR_CAT_ORDER else 99, c.lower()))
        files, labels = {}, {}
        for c in cats:
            fs = self._ctor_audio(os.path.join(sheet["path"], c))
            if base(c) == 'month':                         # январь…декабрь по порядку, а не по алфавиту
                order = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
                fs.sort(key=lambda p: (order.index(month_abbr(os.path.splitext(os.path.basename(p))[0]))
                                       if month_abbr(os.path.splitext(os.path.basename(p))[0]) else 99, p.lower()))
            else:
                fs.sort(key=_numeric_sort_key)
            files[c] = fs
            labels[c] = self.CTOR_CAT_LABELS.get(base(c), c)
        self.constructor_tier_files = files
        self.constructor_order = cats
        self.constructor_labels = labels

    # ---- фразы вокруг переменной: start / start_2 / end — коротко, для сверки с боевыми ----
    CTOR_CTX_MS = 2500        # кратко: конец начала и начало продолжения — по столько

    def _constructor_phrases(self):
        """Фразы проекта, где стоит переменная открытого листа: кусочек перед ней
        и после (start → значение → start_2 / end). Из проекта Студии (если
        открыт этот же) или из его tts_project.json."""
        from core.tts_flow import TTS_STATE_FILE, TTS_VAR_DIR
        sheet = getattr(self, 'constructor_sheet', None)
        vroot = getattr(self, 'constructor_root', None)
        if not sheet or not vroot or not getattr(self, 'constructor_sheets', None):
            return []
        proj = os.path.dirname(os.path.normpath(vroot))
        st = getattr(self, 'tts', None) or {}
        if not (st.get("work_dir") and os.path.normcase(os.path.abspath(st["work_dir"])) == os.path.normcase(os.path.abspath(proj))):
            try:
                with open(os.path.join(proj, TTS_STATE_FILE), 'r', encoding='utf-8') as f:
                    st = json.load(f)
            except (OSError, ValueError):
                return []
        units = st.get("units") or []

        def path(u):
            if not u:
                return None
            p = os.path.join(proj, TTS_VAR_DIR, *([u["subdir"]] if u.get("subdir") else []), f"{u['name']}.wav")
            return p if os.path.exists(p) else None
        out = []
        for ch in st.get("chains") or []:
            parts = [units[i] for i in ch.get("parts", []) if i < len(units)]
            for k, u in enumerate(parts):
                if u.get("var_after") != sheet:
                    continue
                nxt = parts[k + 1] if k + 1 < len(parts) else None
                out.append({"name": ch.get("name") or u["name"],
                            "start_name": u["name"], "start_text": u.get("text", ''), "start_path": path(u),
                            "end_name": nxt["name"] if nxt else None, "end_text": (nxt or {}).get("text", ''),
                            "end_path": path(nxt), "start_role": 'start' if k == 0 else f'start_{k + 1}',
                            "end_role": (f'start_{k + 2}' if k + 2 < len(parts) else 'end') if nxt else None})
        return out

    def _constructor_apply_phrase(self):
        """Выбранная фраза → start / end конструктора."""
        ph = getattr(self, 'constructor_phrases', None) or []
        if not ph:
            return
        k = max(0, min(int(getattr(self, 'constructor_phrase_pos', 0) or 0), len(ph) - 1))
        self.constructor_phrase_pos = k
        self.constructor_start_file = ph[k]["start_path"]
        self.constructor_end_file = ph[k]["end_path"]

    def constructor_phrase_nav(self, delta=0, pos=None):
        ph = getattr(self, 'constructor_phrases', None) or []
        if not ph:
            return self._constructor_state()
        cur = getattr(self, 'constructor_phrase_pos', 0) or 0
        self.constructor_phrase_pos = (int(pos) if pos is not None else cur + int(delta)) % len(ph)
        self._constructor_apply_phrase()
        return self._constructor_state()

    def constructor_set_short(self, on):
        self.constructor_short = bool(on)
        return self._constructor_state()

    def _constructor_short_file(self, path, tail):
        """Кратко: только конец начала (tail) или начало продолжения — во временный файл."""
        import tempfile
        seg = AudioSegment.from_file(path)
        ms = self.CTOR_CTX_MS
        part = (seg[-ms:] if tail else seg[:ms]) if len(seg) > ms else seg
        dst = os.path.join(tempfile.gettempdir(), f"gvox_ctor_{'start' if tail else 'end'}_{os.getpid()}.wav")
        part.export(dst, format="wav")
        return dst

    def constructor_set_sheet(self, key):
        sheet = next((x for x in getattr(self, 'constructor_sheets', None) or [] if x["key"] == key), None)
        if not sheet:
            return {"error": f"Лист «{key}» не найден в папке «Значения»."}
        self._constructor_load_sheet(sheet)
        return self._constructor_state()

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
        vroot, want = self._constructor_values_root(root)
        sheets = self._constructor_values_sheets(vroot) if vroot else []
        if sheets:                                         # «Значения»: листы сумм и дат
            self.constructor_root = vroot
            self.constructor_sheets = sheets
            self.constructor_lang_dirs = {}
            sheet = next((x for x in sheets if x["key"] == want), None) or next((x for x in sheets if x["kind"] == 'sum'), sheets[0])
            self.constructor_short = getattr(self, 'constructor_short', True)
            self._constructor_load_sheet(sheet)
            self.constructor_lang = 'kz' if sheet["key"].lower().endswith(('_kz', '_kk')) else 'ru'
            if not hasattr(self, 'constructor_start_file'):
                self.constructor_start_file = None
            if not hasattr(self, 'constructor_end_file'):
                self.constructor_end_file = None
            return self._constructor_state()
        self.constructor_sheets, self.constructor_phrases = [], []
        self.constructor_kind = 'sum'
        self.constructor_order = list(SUM_TIER_ORDER)
        self.constructor_labels = dict(SUM_TIER_LABELS)
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
        order = getattr(self, 'constructor_order', None) or list(SUM_TIER_ORDER)
        labels = getattr(self, 'constructor_labels', None) or SUM_TIER_LABELS
        sheets = getattr(self, 'constructor_sheets', None) or []
        return {
            "root": getattr(self, 'constructor_root', None),
            "lang": getattr(self, 'constructor_lang', 'ru'),
            "lang_available": [l for l in ('ru', 'kz') if l in lang_dirs],
            "sheets": [{k: x[k] for k in ("key", "label", "kind")} for x in sheets],
            "sheet": getattr(self, 'constructor_sheet', None) if sheets else None,
            "kind": getattr(self, 'constructor_kind', 'sum'),
            "order": order,
            "phrases": [{**{k: x[k] for k in ("name", "start_name", "start_text", "end_name", "end_text", "start_role", "end_role")},
                         "start_ok": bool(x["start_path"]), "end_ok": bool(x["end_path"])}
                        for x in (getattr(self, 'constructor_phrases', None) or [])],
            "phrase_pos": getattr(self, 'constructor_phrase_pos', 0),
            "short": bool(getattr(self, 'constructor_short', False)),
            "short_ms": self.CTOR_CTX_MS,
            "start": os.path.basename(self.constructor_start_file) if getattr(self, 'constructor_start_file', None) else None,
            "end": os.path.basename(self.constructor_end_file) if getattr(self, 'constructor_end_file', None) else None,
            "tiers": {
                tier: {
                    "label": labels.get(tier, tier),
                    "items": [os.path.splitext(os.path.basename(p))[0] for p in tiers.get(tier, [])],
                }
                for tier in order
            },
        }

    def _constructor_ordered_segments(self, indices):
        """Порядок сборки для прослушки/правки — строго как колонки в
        загруженной таблице-словаре (var_template_columns), если она
        есть: связки (start, start_2...) на своих местах между
        категориями.

        Со словарём собираем ОДНУ КОНКРЕТНУЮ СТРОКУ таблицы целиком
        (_sum_stage2_current_row) — марка, год, суммы берутся ИЗ ОДНОЙ И
        ТОЙ ЖЕ строки, а не независимо друг от друга: для каждой
        категории ищем аудио под её значение в этой строке — либо уже
        готовое (переиспользуем как есть), либо сырое, ещё не
        сохранённое (_sum_stage2_resolve_value). indices тут не
        используются — какая строка сейчас активна, решает
        sum_stage2_jump_to_value/_sum_stage2_advance_row.

        Без словаря (старый чистый «Конструктор» по папке «Суммы» без
        Excel, ручной выбор на рулетках) — прежнее поведение по indices.

        Возвращает список (key, filepath, saveable) — saveable=True у
        всего, что нужно экспортировать при «Сохранить эталон» (сырое,
        ещё не сохранённое для этого значения), False — у связок и у
        уже готовых значений."""
        tiers = getattr(self, 'constructor_tier_files', {}) or {}
        columns = getattr(self, 'var_template_columns', None)

        if not columns:
            segments = []
            short = bool(getattr(self, 'constructor_short', False)) and bool(getattr(self, 'constructor_sheets', None))
            if getattr(self, 'constructor_start_file', None) and os.path.exists(self.constructor_start_file):
                segments.append(('start', self._constructor_short_file(self.constructor_start_file, True)
                                 if short else self.constructor_start_file, False))
            for tier in getattr(self, 'constructor_order', None) or SUM_TIER_ORDER:
                files = tiers.get(tier, [])
                idx = (indices or {}).get(tier)
                if files and isinstance(idx, int) and 0 <= idx < len(files):
                    segments.append((tier, files[idx], True))
            if getattr(self, 'constructor_end_file', None) and os.path.exists(self.constructor_end_file):
                segments.append(('end', self._constructor_short_file(self.constructor_end_file, False)
                                 if short else self.constructor_end_file, False))
            return segments

        connectors_by_key = {c['key']: c.get('path') for c in getattr(self, 'var_connectors', [])}
        row = self._sum_stage2_current_row()
        segments = []
        missing = []
        for col in columns:
            if col['type'] == 'connector':
                path = connectors_by_key.get(col['key'])
                if path and os.path.exists(path):
                    segments.append((col['key'], path, False))
                continue

            key = col['key']
            value = row.get(key)
            path, saveable = self._sum_stage2_resolve_value(key, value)
            if path:
                segments.append((key, path, saveable))
            elif value:
                missing.append(f"{self._category_label(key)}: {value}")
        self.sum_stage2_missing = missing
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
            import tempfile                                # не в папку с эталонами — аудит её читает
            temp_path = os.path.join(tempfile.gettempdir(), f"gvox_constructor_preview_{int(time.time() * 1000)}.wav")
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
        if not segments:
            missing = getattr(self, 'sum_stage2_missing', None)
            if missing:
                return {"error": "Нет аудио для этой строки таблицы: " + ', '.join(missing) +
                                  ". Досортируйте сырьё для этих значений или переключитесь на другую строку."}
            return {"error": "Нет ни одного значения для сборки — проверьте, что сырая сортировка что-то накопила."}

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
