import os
import re
import webview
import openpyxl
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_CONNECTOR

PAUSE_COLOR = RGBColor(0xC0, 0x00, 0x00)
TEXT_COLOR = RGBColor(0x00, 0x00, 0x00)
CAPTION_COLOR = RGBColor(0x60, 0x60, 0x60)

# Подпись метки паузы — по языковому слоту интерфейса (RU/KZ/TR), в котором
# собирается презентация. Для любого другого/незнакомого слота остаёмся на
# русском варианте по умолчанию.
PAUSE_LABELS = {
    'ru': 'Пауза',
    'kz': 'Үзіліс',
    'tr': 'Duraklama',
}

# Заголовки в новом формате "<ключ_язык>" (например <million_tr>,
# <yüz_bin_tr>, <tl_tr> — так ведутся турецкие и подобные таблицы «Суммы»,
# где в заголовке используется голый смысловой ключ на латинице, а не
# русское/казахское слово). Ключ сопоставляется напрямую, без завязки на
# конкретный язык — работает для любого языкового суффикса (_tr/_ru/_kz/...).
_TIER_TAG_KEYS = {
    'millions': {'million', 'миллион'},
    'hundred_thousands': {'hundred_thousand', 'yüz_bin', 'yuz_bin', 'yuzbin'},
    'hundreds': {'hundred', 'yüz', 'yuz'},
    'thousands': {'thousand', 'bin'},
    'tenge': {'tenge', 'tl', 'lira'},
}
_LANG_SUFFIX_RE = re.compile(r'_(tr|ru|kz|kg|uz)$')

# Фиксированный шаблон размеров — один и тот же на каждом слайде, никакого
# автоподбора PowerPoint (он ненадёжно пересчитывался у пользователя и либо
# оставлял текст огромным и наползающим, либо ломал слова переносом).
FONT_NORMAL = 24   # всё, что идёт до сумм (start, марка, год, "start 2"...)
FONT_SUM = 28      # колонки-суммы (миллионы/сотни/тысячи/тенге)
FONT_PAUSE = 24    # подпись «Пауза»
FONT_CAPTION = 14  # транскрипция — мелкая серая подпись НАД маркой

# Когда после «Сотни тысяч» на слайде остаётся только марка — места на
# слайде намного больше, чем у обычного ряда из 8+ блоков, так что можно
# взять размер покрупнее, а не тот же 24pt, что и у остальных блоков.
FONT_NORMAL_SOLO_BRAND = 40
FONT_CAPTION_SOLO_BRAND = 20

SLIDE_W = Emu(int(13.333 * 914400))
SLIDE_H = Emu(int(7.5 * 914400))
BOX_H = Inches(1.15)
MARGIN = Inches(0.25)
GAP = Inches(0.28)  # запас под линию + подпись «Пауза» между блоками
PAD = Inches(0.05)  # внутренний отступ текста в блоке с каждой стороны

# Грубая оценка ширины текста в EMU: реальных метрик шрифта у python-pptx
# нет (он не рендерит), поэтому ширина строки прикидывается по числу
# символов и размеру шрифта — с запасом, чтобы текст не обрезался.
AVG_CHAR_WIDTH_PT = 0.62
EMU_PER_PT = 12700


class TableToPptxMixin:
    """«Таблица → PowerPoint» — построчный экспорт: каждая строка Excel
    становится отдельным слайдом, каждая ячейка — своим блоком текста на
    слайде, а между блоками — метка «Пауза» (вертикальная красная черта),
    чтобы при нарезке аудио были чёткие границы между категориями. Колонка
    «транскрипция» ставится мелкой серой подписью НАД колонкой «марка» —
    одним блоком, без паузы между ними, раз это одно и то же значение,
    просто записанное двумя способами. Блоки не растягиваются на всю
    ширину слайда, а сдвинуты компактно друг к другу — по фактической
    ширине текста, а не поровну."""

    def table_pptx_pick_excel(self, lang='ru'):
        """lang — слот интерфейса («ru»/«kz»/«tr»...): каждый ведётся как
        независимый набор данных (своя таблица, свои колонки), переключаются
        тумблером в интерфейсе. Если в книге несколько листов, файл только
        открывается и анализируется — какой именно лист анализировать,
        выбирает пользователь отдельным шагом (table_pptx_pick_sheet),
        т.к. один .xlsx нередко везёт параллельно несколько представлений
        одних и тех же данных (например, текстовая и числовая запись сумм)."""
        filename = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
        if not filename:
            return {"error": "cancel"}
        path = filename[0]

        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(path)}\n\n"
                              f"Поддерживается только формат .xlsx. Подробности: {e}"}

        if not hasattr(self, 'table_pptx_pending'):
            self.table_pptx_pending = {}
        self.table_pptx_pending[lang] = path

        if len(wb.sheetnames) > 1:
            return {"status": "choose_sheet", "lang": lang, "file": os.path.basename(path),
                     "sheets": wb.sheetnames}

        return self._table_pptx_load_sheet(lang, path, wb[wb.sheetnames[0]])

    def table_pptx_pick_sheet(self, lang, sheet_name):
        """Второй шаг после table_pptx_pick_excel, когда в книге несколько
        листов — грузит данные именно из выбранного листа."""
        path = getattr(self, 'table_pptx_pending', {}).get(lang)
        if not path or not os.path.exists(path):
            return {"error": "Сессия выбора файла истекла — выберите Excel заново."}
        try:
            wb = openpyxl.load_workbook(path, data_only=True)
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\nПодробности: {e}"}
        if sheet_name not in wb.sheetnames:
            return {"error": "Такого листа нет в этой таблице — выберите Excel заново."}
        return self._table_pptx_load_sheet(lang, path, wb[sheet_name])

    def _table_pptx_load_sheet(self, lang, path, sheet):
        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return {"error": "Выбранный лист пустой."}

        headers = [self._table_pptx_cell_text(c) for c in header_row]
        while headers and not headers[-1]:
            headers.pop()
        if not headers:
            return {"error": "В первой строке листа нет заголовков колонок."}

        ncols = len(headers)
        data_rows = []
        for row in rows_iter:
            cells = list(row[:ncols]) + [None] * max(0, ncols - len(row))
            values = [self._table_pptx_cell_text(c) for c in cells]
            if not any(values):
                continue
            data_rows.append(values)

        if not data_rows:
            return {"error": "На выбранном листе не нашлось ни одной строки с данными (кроме заголовков)."}

        brand_idx, transcript_idx = self._table_pptx_find_brand_pair(headers)
        tier_cols = {}
        for i, h in enumerate(headers):
            tier = self._table_pptx_classify_tier(h)
            if tier and tier not in tier_cols:
                tier_cols[tier] = i
        tier_lang = self._table_pptx_detect_tier_lang(headers, tier_cols)
        sum_flags = [i in tier_cols.values() for i in range(len(headers))]
        logic2_cycle = self._table_pptx_collect_hundred_thousands_cycle(data_rows, tier_cols, tier_lang)
        # Переключение срабатывает ровно там, где найдена строка с «нулём»
        # в «Тенге»/tl (см. _table_pptx_find_trigger_idx) — никаких других
        # условий (какие именно колонки есть в таблице и т.п.) не требуется.
        logic2_available = bool(logic2_cycle) and self._table_pptx_find_trigger_idx(data_rows, tier_cols) is not None
        # «start 2» («со стоимостью») — второй столбец с «служебной» связкой
        # (в отличие от самого первого «start», который остаётся всегда).
        # После того как круг «Сотни тысяч» исчерпан, эта колонка тоже
        # убирается со слайда — остаются только start, марка и год.
        extra_start_idxs = [i for i, h in enumerate(headers)
                             if i > 0 and re.fullmatch(r'start\s*\d+', h.lower().strip())]

        # Колонка без заголовка (пустая ячейка в шапке) — не настоящее
        # поле таблицы, а случайная заметка автора в одной из ячеек ниже
        # (так бывает при копировании примеров прямо в рабочую таблицу).
        # Без подписи её нечем объяснить на слайде, поэтому она целиком
        # исключается — не показывается и не участвует в «протягивании»
        # вниз, чтобы одна случайная запись не расползлась по всем слайдам.
        blank_idxs = {i for i, h in enumerate(headers) if not h.strip()}

        # «Протягиваем вниз» пустые ячейки — в таких таблицах часто пишут
        # значение только один раз, а дальше оставляют пусто, подразумевая
        # «то же самое, что выше» (как в Excel при объединении ячеек).
        # Касается всех обычных колонок (start, год, start 2 и т.п.) —
        # не колонок-сумм (там пустая ячейка и правда значит «пропустить»,
        # см. _table_pptx_collect_hundred_thousands_cycle), не марки с
        # транскрипцией (те должны быть каждый раз свои) и не безымянных
        # колонок (см. выше).
        no_fill = set(tier_cols.values()) | blank_idxs
        if brand_idx is not None:
            no_fill.add(brand_idx)
        if transcript_idx is not None:
            no_fill.add(transcript_idx)
        last_seen = {}
        for row in data_rows:
            for i in range(len(row)):
                if i in no_fill:
                    continue
                if row[i]:
                    last_seen[i] = row[i]
                elif i in last_seen:
                    row[i] = last_seen[i]

        if not hasattr(self, 'table_pptx_data'):
            self.table_pptx_data = {}
        self.table_pptx_data[lang] = {
            "path": path,
            "sheet": sheet.title,
            "headers": headers,
            "rows": data_rows,
            "brand_idx": brand_idx,
            "transcript_idx": transcript_idx,
            "sum_flags": sum_flags,
            "tier_cols": tier_cols,
            "tier_lang": tier_lang,
            "extra_start_idxs": extra_start_idxs,
            "blank_idxs": blank_idxs,
        }

        return {
            "lang": lang,
            "file": os.path.basename(path),
            "sheet": sheet.title,
            "rows": len(data_rows),
            "columns": headers,
            "brand_pair": [headers[brand_idx], headers[transcript_idx]] if brand_idx is not None else None,
            "sum_columns": [headers[i] for i in tier_cols.values()],
            "logic2_available": logic2_available,
            "ignored_columns": [headers[i] or '(без заголовка)' for i in sorted(blank_idxs)],
        }

    @staticmethod
    def _table_pptx_cell_text(value):
        """Ячейка с формулой (как «100-900», которая явно посчитана по
        соседней колонке с миллионами) приходит из openpyxl числом
        (100.0), а не текстом — обычный str() тогда даёт «100.0». Целые
        числа показываем без «.0», дробные — как есть."""
        if value is None:
            return ''
        if isinstance(value, float):
            if value.is_integer():
                return str(int(value))
            return str(value)
        return str(value).strip()

    @staticmethod
    def _table_pptx_find_brand_pair(headers):
        """Ищет пару колонок «марка» → «транскрипция» по словам в
        заголовке, а не по фиксированной позиции — так работает в любой
        таблице независимо от порядка колонок. Пара должна идти подряд:
        марка, сразу за ней транскрипция."""
        low = [h.lower().replace('ё', 'е') for h in headers]
        for i, h in enumerate(low):
            if 'марк' in h and i + 1 < len(low) and 'транскрип' in low[i + 1]:
                return i, i + 1
        return None, None

    @staticmethod
    def _table_pptx_classify_tier(header):
        """Определяет ярус колонки-суммы по слову в заголовке.

        Сначала пробуем как тег вида "<ключ_язык>" (например <million_tr>,
        <yüz_bin_tr>, <tl_tr>) — снимаем скобки и языковой суффикс
        (_tr/_ru/_kz/...) и сравниваем голый ключ со словарём известных
        ярусов _TIER_TAG_KEYS, независимо от того, какой это язык.

        Если тег не распознан — старая логика для русских/казахских
        заголовков произвольного вида: «млн»/«миллион» → Миллионы,
        «тенге» → Тенге, «тыс»/«мың»/«мын» (казахский вариант того же
        яруса) + число ≥100 в заголовке → Сотни тысяч (100-900 тыс.), без
        такого числа → Тысячи, голый числовой диапазон без слов
        («100 - 900») → Сотни."""
        low = header.lower().replace('ё', 'е')

        tag_key = _LANG_SUFFIX_RE.sub('', low.strip().strip('<>'))
        for tier, keys in _TIER_TAG_KEYS.items():
            if tag_key in keys:
                return tier

        if 'млн' in low or 'миллион' in low:
            return 'millions'
        if any(k in low for k in ('тенге', 'kzt', '₸')):
            return 'tenge'
        if any(k in low for k in ('тыс', 'мың', 'мын')):
            nums = re.findall(r'\d+', header)
            return 'hundred_thousands' if nums and int(nums[0]) >= 100 else 'thousands'
        if re.fullmatch(r'\d+\s*-\s*\d+', header.strip()):
            return 'hundreds'
        return None

    @staticmethod
    def _table_pptx_detect_tier_lang(headers, tier_cols):
        """Язык заголовков яруса (по суффиксу _tr/_ru/_kz/...) — определяем,
        только если ВСЕ найденные колонки-суммы согласны между собой
        (единый суффикс); при free-form заголовках без суффикса (старые
        русские/казахские таблицы) возвращает None — тогда форматирование
        значений ведёт себя как раньше, без изменений."""
        suffixes = set()
        for idx in tier_cols.values():
            m = _LANG_SUFFIX_RE.search(headers[idx].lower().strip().rstrip('>'))
            if not m:
                return None
            suffixes.add(m.group(1))
        return suffixes.pop() if len(suffixes) == 1 else None

    @staticmethod
    def _table_pptx_first_number(text):
        m = re.search(r'\d+', text or '')
        return int(m.group()) if m else None

    @staticmethod
    def _table_pptx_format_tier_value(tier, text, tier_lang=None):
        """Ячейка «Сотни тысяч» в Excel часто хранит голое число (100), а
        «тыс» на экране появляется только через формат ячейки (custom
        number format) — сам текст этого не содержит, openpyxl видит
        только число. Чтобы на слайде не выпадало голое «100» без
        объяснения, что это, дописываем «тыс», если в тексте такого слова
        ещё нет вообще (ни «тыс», ни «мың»/«мын»).

        Для таблиц с заголовками-тегами на другом языке (tier_lang, напр.
        «tr») текст в ячейке обычно УЖЕ полностью записан словами («iki
        yüz bin», а не голое число) — в этом случае ничего не дописываем,
        чтобы не получить абракадабру вида «iki yüz bin тыс». Дописываем
        «тыс» только для действительно голого числа (без единого слова) —
        и то лишь когда язык яруса не распознан как не-русский."""
        if tier != 'hundred_thousands':
            return text
        low = (text or '').lower().replace('ё', 'е')
        if any(k in low for k in ('тыс', 'мың', 'мын')):
            return text
        if tier_lang and tier_lang != 'ru':
            return text
        return f"{text} тыс".strip()

    @staticmethod
    def _table_pptx_is_zero_tenge(text):
        """«Ноль» на любом из языков таблицы — «ноль тенге», «sıfır tl»,
        «sıfır lira», а также цифрой: «0 tl», «0 lira», «0 тенге». Проверяем
        и по слову, и по отдельно стоящей цифре 0 (не части большего числа
        вроде «100» или «10»), не привязываясь к конкретному слову валюты,
        чтобы работать с любым языком."""
        low = (text or '').lower().replace('ё', 'е')
        if any(w in low for w in ('sıfır', 'sifir', 'ноль', 'нуль', 'zero')):
            return True
        return bool(re.search(r'(?<!\d)0(?!\d)', low))

    def _table_pptx_find_trigger_idx(self, rows, tier_cols):
        """Индекс строки, с которой начинается переключение на «Миллионы +
        Сотни тысяч (по кругу) + Тенге» — это строка, где ярус «Тенге»/tl
        явно помечен как «ноль» («ноль тенге», «sıfır tl»/«sıfır lira»).
        Именно эта строка становится первым «комбинированным» слайдом —
        дальше «Миллионы» и «Тенге» держатся на значении из самой первой
        строки таблицы (не на «нуле» — ноль это только сигнал переключения,
        а не то, что нужно показать на слайде), а крутится только «Сотни
        тысяч»."""
        idx = tier_cols.get('tenge')
        if idx is None:
            return None
        for i, row in enumerate(rows):
            if idx < len(row) and self._table_pptx_is_zero_tenge(row[idx]):
                return i
        return None

    def _table_pptx_collect_hundred_thousands_cycle(self, rows, tier_cols, tier_lang=None):
        """Собирает уже записанные значения яруса «Сотни тысяч» (обычно
        это всего 9 строк — «100 тыс»...«900 тыс», записанные один раз в
        начале таблицы) — после переключения они используются по очереди,
        один раз каждое, а не читаются из собственных (обычно пустых)
        ячеек строки. Когда список исчерпан (использовали «900 тыс») —
        суммы на слайдах пропадают совсем, без зацикливания заново."""
        idx = tier_cols.get('hundred_thousands')
        if idx is None:
            return []
        cycle = []
        for row in rows:
            if idx < len(row) and self._table_pptx_first_number(row[idx]) is not None:
                cycle.append(self._table_pptx_format_tier_value('hundred_thousands', row[idx], tier_lang))
        return cycle

    def _table_pptx_build_logic2_context(self, rows, tier_cols, tier_lang=None):
        millions_idx = tier_cols.get('millions')
        tenge_idx = tier_cols.get('tenge')
        fixed_millions = rows[0][millions_idx] if rows and millions_idx is not None and millions_idx < len(rows[0]) else None
        fixed_tenge = rows[0][tenge_idx] if rows and tenge_idx is not None and tenge_idx < len(rows[0]) else None
        return {
            "cycle": self._table_pptx_collect_hundred_thousands_cycle(rows, tier_cols, tier_lang),
            "cycle_pos": 0,
            "trigger_idx": self._table_pptx_find_trigger_idx(rows, tier_cols),
            "triggered": False,
            "exhausted": False,
            "fixed_millions": fixed_millions,
            "fixed_tenge": fixed_tenge,
        }

    def table_pptx_export(self, lang='ru'):
        data = getattr(self, 'table_pptx_data', {}).get(lang)
        if not data:
            return {"error": f"Сначала загрузите Excel для языка «{lang.upper()}»."}
        rows = data['rows']

        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename=f'Слайды {lang.upper()}.pptx', file_types=('PowerPoint files (*.pptx)',))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if not path.lower().endswith('.pptx'):
            path += '.pptx'

        brand_idx = data['brand_idx']
        transcript_idx = data['transcript_idx']
        tier_cols = data['tier_cols']
        tier_lang = data.get('tier_lang')
        blank_idxs = data.get('blank_idxs') or set()
        logic2_ctx = self._table_pptx_build_logic2_context(rows, tier_cols, tier_lang)

        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H
        blank_layout = prs.slide_layouts[6]

        pause_label = PAUSE_LABELS.get(lang, PAUSE_LABELS['ru'])

        try:
            for row_idx, row in enumerate(rows):
                self._table_pptx_build_slide(prs, blank_layout, row, row_idx, brand_idx, transcript_idx, tier_cols,
                                              logic2_ctx, tier_lang, blank_idxs, pause_label)
            prs.save(path)
        except Exception as e:
            return {"error": f"Не удалось собрать презентацию.\n\n{e}"}

        return {"status": "ok", "path": path, "slides": len(rows)}

    @staticmethod
    def _text_width_emu(text, font_pt):
        chars = max(len(text or ''), 1)
        return int(chars * font_pt * AVG_CHAR_WIDTH_PT * EMU_PER_PT)

    def _table_pptx_build_slide(self, prs, layout, row, row_idx, brand_idx, transcript_idx, tier_cols, logic2_ctx,
                                 tier_lang=None, blank_idxs=None, pause_label=None):
        blank_idxs = blank_idxs or set()
        pause_label = pause_label or PAUSE_LABELS['ru']
        tier_indices = set(tier_cols.values())
        first_tier_idx = min(tier_indices) if tier_indices else None

        # Переключение на «Миллионы + Сотни тысяч + Тенге» — одноразовое и
        # дальше держится до конца таблицы (sticky): срабатывает ровно на
        # строке trigger_idx (последняя строка, где у «Тенге»/tl ещё есть
        # значение), а дальше идёт по этому же сценарию без повторных проверок.
        if not logic2_ctx['triggered'] and logic2_ctx['cycle'] and logic2_ctx['trigger_idx'] is not None \
                and row_idx == logic2_ctx['trigger_idx']:
            logic2_ctx['triggered'] = True
        use_logic2 = logic2_ctx['triggered'] and not logic2_ctx['exhausted']

        segments = []
        if logic2_ctx['exhausted']:
            # Круг «Сотни тысяч» исчерпан (использовали «900 тыс») — на
            # слайде больше ничего лишнего, только марка (+ транскрипция
            # над ней одним блоком).
            skip = set(range(len(row)))
            if brand_idx is not None:
                skip.discard(brand_idx)
        else:
            skip = {transcript_idx} if brand_idx is not None else set()
        skip |= blank_idxs
        for i, val in enumerate(row):
            if i in skip:
                continue
            if i in tier_indices:
                if i != first_tier_idx or logic2_ctx['exhausted']:
                    continue  # весь блок сумм собирается один раз, в позиции первого яруса
                if use_logic2:
                    cycle = logic2_ctx['cycle']
                    if logic2_ctx['cycle_pos'] < len(cycle):
                        ht_value = cycle[logic2_ctx['cycle_pos']]
                        logic2_ctx['cycle_pos'] += 1
                        for text in (logic2_ctx['fixed_millions'], ht_value, logic2_ctx['fixed_tenge']):
                            if text:
                                segments.append({"text": text, "font": FONT_SUM})
                        if logic2_ctx['cycle_pos'] >= len(cycle):
                            logic2_ctx['exhausted'] = True
                else:
                    for tier in ('millions', 'hundreds', 'thousands', 'tenge'):
                        idx = tier_cols.get(tier)
                        if idx is not None and idx < len(row):
                            text = self._table_pptx_format_tier_value(tier, row[idx], tier_lang)
                            segments.append({"text": text, "font": FONT_SUM})
                continue
            if brand_idx is not None and i == brand_idx:
                sub = row[transcript_idx] if transcript_idx < len(row) else ''
                if logic2_ctx['exhausted']:
                    segments.append({"brand": val, "caption": sub,
                                      "font": FONT_NORMAL_SOLO_BRAND, "caption_font": FONT_CAPTION_SOLO_BRAND})
                else:
                    segments.append({"brand": val, "caption": sub, "font": FONT_NORMAL})
            else:
                segments.append({"text": val, "font": FONT_NORMAL})

        # Пустая ячейка — без своего блока и без паузы вообще: раньше
        # пустое место оставалось «слотом» с паузой, а несколько пустых
        # подряд превращались в кучу наползающих друг на друга подписей
        # «Пауза» без всякого толку. Свободное место, что осталось после
        # удаления пустых, уходит на центрирование того, что реально есть.
        segments = [s for s in segments if self._table_pptx_segment_has_content(s)]

        slide = prs.slides.add_slide(layout)
        bg = slide.background
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        n = len(segments)
        if n == 0:
            return

        # Ширина каждого блока — по факту содержимого (плюс отступы), а не
        # поровну на всех: короткие слова занимают меньше места, весь ряд
        # получается компактнее, и на его размер можно накинуть шрифт крупнее.
        widths = []
        for seg in segments:
            if 'brand' in seg:
                w = max(self._text_width_emu(seg.get('brand'), seg['font']),
                        self._text_width_emu(seg.get('caption'), seg.get('caption_font', FONT_CAPTION)))
            else:
                w = self._text_width_emu(seg.get('text'), seg['font'])
            widths.append(w + 2 * PAD)

        usable_w = prs.slide_width - 2 * MARGIN
        total_w = sum(widths) + GAP * (n - 1)

        # Если такой ряд не влезает по ширине даже без пауз — сжимаем все
        # блоки (и отступы между ними) одним общим коэффициентом, сохраняя
        # пропорции шаблона (24/28/20/14), а не обрезая текст.
        scale = min(1.0, usable_w / total_w) if total_w > 0 else 1.0
        if scale < 1.0:
            widths = [int(w * scale) for w in widths]
            gap = int(GAP * scale)
        else:
            gap = GAP

        total_w_final = sum(widths) + gap * (n - 1)
        top = (prs.slide_height - BOX_H) // 2
        left = MARGIN + max(0, (usable_w - total_w_final) // 2)
        for i, (seg, width) in enumerate(zip(segments, widths)):
            self._table_pptx_add_segment_box(slide, seg, left, top, width, BOX_H, scale)
            left += width
            if i < n - 1:
                pause_x = left + gap // 2
                self._table_pptx_add_pause_marker(slide, pause_x, top, BOX_H, scale, pause_label)
                left += gap

    @staticmethod
    def _table_pptx_segment_has_content(seg):
        if 'brand' in seg:
            return bool((seg.get('brand') or '').strip()) or bool((seg.get('caption') or '').strip())
        return bool((seg.get('text') or '').strip())

    @staticmethod
    def _table_pptx_add_segment_box(slide, seg, left, top, width, height, scale):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_left = 0
        tf.margin_right = 0

        if 'brand' in seg:
            p1 = tf.paragraphs[0]
            p1.alignment = PP_ALIGN.CENTER
            r1 = p1.add_run()
            r1.text = seg.get('caption') or ''
            r1.font.size = Pt(max(seg.get('caption_font', FONT_CAPTION) * scale, 6))
            r1.font.bold = False
            r1.font.color.rgb = CAPTION_COLOR

            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            r2 = p2.add_run()
            r2.text = seg.get('brand') or ''
            r2.font.size = Pt(max(seg['font'] * scale, 6))
            r2.font.bold = True
            r2.font.color.rgb = TEXT_COLOR
        else:
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = seg.get('text') or ''
            r.font.size = Pt(max(seg['font'] * scale, 6))
            r.font.bold = True
            r.font.color.rgb = TEXT_COLOR

    def _table_pptx_add_pause_marker(self, slide, x, top, height, scale, pause_label=None):
        pause_label = pause_label or PAUSE_LABELS['ru']
        label_w = Inches(1.05)
        label_h = Inches(0.4)

        # Ширина метки остаётся фиксированной (иначе соседние метки начинают
        # наезжать друг на друга при узких блоках) — вместо этого шрифт
        # подписи подстраивается под длину слова: «Пауза»/«Үзіліс» влезают
        # без изменений, а более длинное «Duraklama» становится чуть мельче.
        natural_w = self._text_width_emu(pause_label, FONT_PAUSE)
        label_scale = min(1.0, (label_w - Inches(0.1)) / natural_w) if natural_w > 0 else 1.0

        label = slide.shapes.add_textbox(x - label_w // 2, top - label_h - Inches(0.06), label_w, label_h)
        tf = label.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = pause_label
        r.font.size = Pt(max(FONT_PAUSE * scale * label_scale, 6))
        r.font.bold = True
        r.font.color.rgb = PAUSE_COLOR

        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, top, x, top + height)
        line.line.color.rgb = PAUSE_COLOR
        line.line.width = Pt(3)
