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

# Условие перехода на «Миллионы + Сотни тысяч + Тенге»: строка, где
# «Миллионы» и «Сотни» одновременно дошли до 100, а «Тенге» — тоже 100
# («Тысячи» на этой строке в реальных таблицах обычно уже пустые —
# в условие их поэтому не включаем).
SUM_TIER_CAP = {'millions': 100, 'hundreds': 100, 'tenge': 100}

# Фиксированный шаблон размеров — один и тот же на каждом слайде, никакого
# автоподбора PowerPoint (он ненадёжно пересчитывался у пользователя и либо
# оставлял текст огромным и наползающим, либо ломал слова переносом).
FONT_NORMAL = 24   # всё, что идёт до сумм (start, марка, год, "start 2"...)
FONT_SUM = 28      # колонки-суммы (миллионы/сотни/тысячи/тенге)
FONT_PAUSE = 20    # подпись «Пауза»
FONT_CAPTION = 14  # транскрипция — мелкая серая подпись НАД маркой

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
        """lang — «ru» или «kz»: РУ и КАЗ ведутся как два независимых
        набора данных (своя таблица, свои колонки — структура и порядок
        колонок у них разные), переключаются тумблером в интерфейсе."""
        filename = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
        if not filename:
            return {"error": "cancel"}
        path = filename[0]

        try:
            wb = openpyxl.load_workbook(path, data_only=True)
            sheet = wb.active
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу.\n\n{os.path.basename(path)}\n\n"
                              f"Поддерживается только формат .xlsx. Подробности: {e}"}

        rows_iter = sheet.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return {"error": "Таблица пустая."}

        headers = [self._table_pptx_cell_text(c) for c in header_row]
        while headers and not headers[-1]:
            headers.pop()
        if not headers:
            return {"error": "В первой строке таблицы нет заголовков колонок."}

        ncols = len(headers)
        data_rows = []
        for row in rows_iter:
            cells = list(row[:ncols]) + [None] * max(0, ncols - len(row))
            values = [self._table_pptx_cell_text(c) for c in cells]
            if not any(values):
                continue
            data_rows.append(values)

        if not data_rows:
            return {"error": "В таблице не нашлось ни одной строки с данными (кроме заголовков)."}

        brand_idx, transcript_idx = self._table_pptx_find_brand_pair(headers)
        tier_cols = {}
        for i, h in enumerate(headers):
            tier = self._table_pptx_classify_tier(h)
            if tier and tier not in tier_cols:
                tier_cols[tier] = i
        sum_flags = [i in tier_cols.values() for i in range(len(headers))]
        logic2_cycle = self._table_pptx_collect_hundred_thousands_cycle(data_rows, tier_cols)
        logic2_available = bool(logic2_cycle) and all(t in tier_cols for t in ('millions', 'hundreds', 'tenge'))
        # «start 2» («со стоимостью») — второй столбец с «служебной» связкой
        # (в отличие от самого первого «start», который остаётся всегда).
        # После того как круг «Сотни тысяч» исчерпан, эта колонка тоже
        # убирается со слайда — остаются только start, марка и год.
        extra_start_idxs = [i for i, h in enumerate(headers)
                             if i > 0 and re.fullmatch(r'start\s*\d+', h.lower().strip())]

        # «Протягиваем вниз» пустые ячейки — в таких таблицах часто пишут
        # значение только один раз, а дальше оставляют пусто, подразумевая
        # «то же самое, что выше» (как в Excel при объединении ячеек).
        # Касается всех обычных колонок (start, год, start 2 и т.п.) —
        # не колонок-сумм (там пустая ячейка и правда значит «пропустить»,
        # см. _table_pptx_collect_hundred_thousands_cycle) и не марки с
        # транскрипцией (те должны быть каждый раз свои).
        no_fill = set(tier_cols.values())
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
            "headers": headers,
            "rows": data_rows,
            "brand_idx": brand_idx,
            "transcript_idx": transcript_idx,
            "sum_flags": sum_flags,
            "tier_cols": tier_cols,
            "extra_start_idxs": extra_start_idxs,
        }

        return {
            "lang": lang,
            "file": os.path.basename(path),
            "rows": len(data_rows),
            "columns": headers,
            "brand_pair": [headers[brand_idx], headers[transcript_idx]] if brand_idx is not None else None,
            "sum_columns": [headers[i] for i in tier_cols.values()],
            "logic2_available": logic2_available,
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
        """Определяет ярус колонки-суммы по слову в заголовке — та же
        логика, что и для обычного «Режима сумм» на основном экране:
        «млн»/«миллион» → Миллионы, «тенге» → Тенге, «тыс»/«мың»/«мын»
        (казахский вариант того же яруса) + число ≥100 в заголовке →
        Сотни тысяч (100-900 тыс.), без такого числа → Тысячи, голый
        числовой диапазон без слов («100 - 900») → Сотни."""
        low = header.lower().replace('ё', 'е')
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
    def _table_pptx_first_number(text):
        m = re.search(r'\d+', text or '')
        return int(m.group()) if m else None

    @staticmethod
    def _table_pptx_format_tier_value(tier, text):
        """Ячейка «Сотни тысяч» в Excel часто хранит голое число (100), а
        «тыс» на экране появляется только через формат ячейки (custom
        number format) — сам текст этого не содержит, openpyxl видит
        только число. Чтобы на слайде не выпадало голое «100» без
        объяснения, что это, дописываем «тыс», если в тексте такого слова
        ещё нет вообще (ни «тыс», ни «мың»/«мын»)."""
        if tier != 'hundred_thousands':
            return text
        low = (text or '').lower().replace('ё', 'е')
        if any(k in low for k in ('тыс', 'мың', 'мын')):
            return text
        return f"{text} тыс".strip()

    def _table_pptx_row_hits_switch(self, row, tier_cols):
        """Строка, на которой пора переключаться на «Миллионы + Сотни
        тысяч + Тенге» — «Миллионы» и «Сотни» одновременно дошли до 100, а
        «Тенге» тоже 100. Проверяем именно число в ячейке, а не точный
        текст (там бывают разные окончания: «млн», «млн-а», «млн-ов»)."""
        for t in ('millions', 'hundreds', 'tenge'):
            idx = tier_cols.get(t)
            if idx is None or idx >= len(row) or self._table_pptx_first_number(row[idx]) != SUM_TIER_CAP[t]:
                return False
        return True

    def _table_pptx_collect_hundred_thousands_cycle(self, rows, tier_cols):
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
                cycle.append(self._table_pptx_format_tier_value('hundred_thousands', row[idx]))
        return cycle

    def _table_pptx_build_logic2_context(self, rows, tier_cols):
        millions_idx = tier_cols.get('millions')
        tenge_idx = tier_cols.get('tenge')
        fixed_millions = rows[0][millions_idx] if rows and millions_idx is not None and millions_idx < len(rows[0]) else None
        fixed_tenge = rows[0][tenge_idx] if rows and tenge_idx is not None and tenge_idx < len(rows[0]) else None
        return {
            "cycle": self._table_pptx_collect_hundred_thousands_cycle(rows, tier_cols),
            "cycle_pos": 0,
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
        logic2_ctx = self._table_pptx_build_logic2_context(rows, tier_cols)

        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H
        blank_layout = prs.slide_layouts[6]

        try:
            for row in rows:
                self._table_pptx_build_slide(prs, blank_layout, row, brand_idx, transcript_idx, tier_cols, logic2_ctx)
            prs.save(path)
        except Exception as e:
            return {"error": f"Не удалось собрать презентацию.\n\n{e}"}

        return {"status": "ok", "path": path, "slides": len(rows)}

    @staticmethod
    def _text_width_emu(text, font_pt):
        chars = max(len(text or ''), 1)
        return int(chars * font_pt * AVG_CHAR_WIDTH_PT * EMU_PER_PT)

    def _table_pptx_build_slide(self, prs, layout, row, brand_idx, transcript_idx, tier_cols, logic2_ctx):
        tier_indices = set(tier_cols.values())
        first_tier_idx = min(tier_indices) if tier_indices else None

        # Переключение на «Миллионы + Сотни тысяч + Тенге» — одноразовое и
        # дальше держится до конца таблицы (sticky): как только строка
        # хоть раз попала под условие, все следующие строки (даже те, где
        # своих сумм в ячейках уже нет вообще — обычно так и есть) идут по
        # этому же сценарию, а не проверяются заново.
        if not logic2_ctx['triggered'] and logic2_ctx['cycle'] and self._table_pptx_row_hits_switch(row, tier_cols):
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
                            text = self._table_pptx_format_tier_value(tier, row[idx])
                            segments.append({"text": text, "font": FONT_SUM})
                continue
            if brand_idx is not None and i == brand_idx:
                sub = row[transcript_idx] if transcript_idx < len(row) else ''
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
                        self._text_width_emu(seg.get('caption'), FONT_CAPTION))
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
                self._table_pptx_add_pause_marker(slide, pause_x, top, BOX_H, scale)
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
            r1.font.size = Pt(max(FONT_CAPTION * scale, 6))
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

    @staticmethod
    def _table_pptx_add_pause_marker(slide, x, top, height, scale):
        label_w = Inches(0.9)
        label_h = Inches(0.4)
        label = slide.shapes.add_textbox(x - label_w // 2, top - label_h - Inches(0.06), label_w, label_h)
        tf = label.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = 'Пауза'
        r.font.size = Pt(max(FONT_PAUSE * scale, 6))
        r.font.bold = True
        r.font.color.rgb = PAUSE_COLOR

        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, top, x, top + height)
        line.line.color.rgb = PAUSE_COLOR
        line.line.width = Pt(3)
