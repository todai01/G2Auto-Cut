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

    def table_pptx_pick_excel(self):
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
        sum_flags = [self._table_pptx_is_sum_header(h) for h in headers]

        self.table_pptx_path = path
        self.table_pptx_headers = headers
        self.table_pptx_rows = data_rows
        self.table_pptx_brand_idx = brand_idx
        self.table_pptx_transcript_idx = transcript_idx
        self.table_pptx_sum_flags = sum_flags

        return {
            "file": os.path.basename(path),
            "rows": len(data_rows),
            "columns": headers,
            "brand_pair": [headers[brand_idx], headers[transcript_idx]] if brand_idx is not None else None,
            "sum_columns": [h for h, is_sum in zip(headers, sum_flags) if is_sum],
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
    def _table_pptx_is_sum_header(header):
        """Колонка-«сумма» — миллионы/сотни/тысячи/тенге: узнаём по слову
        в заголовке, а если слова нет (просто «100 - 900») — по тому, что
        весь заголовок это числовой диапазон."""
        low = header.lower().replace('ё', 'е')
        if any(k in low for k in ('млн', 'миллион', 'тыс', 'тенге', 'kzt', '₸')):
            return True
        return bool(re.fullmatch(r'\d+\s*-\s*\d+', header.strip()))

    def table_pptx_export(self):
        headers = getattr(self, 'table_pptx_headers', None)
        rows = getattr(self, 'table_pptx_rows', None)
        if not headers or not rows:
            return {"error": "Сначала загрузите Excel с таблицей."}

        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.SAVE, save_filename='Слайды.pptx', file_types=('PowerPoint files (*.pptx)',))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if not path.lower().endswith('.pptx'):
            path += '.pptx'

        brand_idx = getattr(self, 'table_pptx_brand_idx', None)
        transcript_idx = getattr(self, 'table_pptx_transcript_idx', None)
        sum_flags = getattr(self, 'table_pptx_sum_flags', [False] * len(headers))

        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H
        blank_layout = prs.slide_layouts[6]

        try:
            for row in rows:
                self._table_pptx_build_slide(prs, blank_layout, row, brand_idx, transcript_idx, sum_flags)
            prs.save(path)
        except Exception as e:
            return {"error": f"Не удалось собрать презентацию.\n\n{e}"}

        return {"status": "ok", "path": path, "slides": len(rows)}

    @staticmethod
    def _text_width_emu(text, font_pt):
        chars = max(len(text or ''), 1)
        return int(chars * font_pt * AVG_CHAR_WIDTH_PT * EMU_PER_PT)

    def _table_pptx_build_slide(self, prs, layout, row, brand_idx, transcript_idx, sum_flags):
        segments = []
        skip = {transcript_idx} if brand_idx is not None else set()
        for i, val in enumerate(row):
            if i in skip:
                continue
            is_sum = bool(sum_flags[i]) if i < len(sum_flags) else False
            main_font = FONT_SUM if is_sum else FONT_NORMAL
            if brand_idx is not None and i == brand_idx:
                sub = row[transcript_idx] if transcript_idx < len(row) else ''
                segments.append({"brand": val, "caption": sub, "font": main_font})
            else:
                segments.append({"text": val, "font": main_font})

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

        top = (prs.slide_height - BOX_H) // 2
        left = MARGIN
        for i, (seg, width) in enumerate(zip(segments, widths)):
            self._table_pptx_add_segment_box(slide, seg, left, top, width, BOX_H, scale)
            left += width
            if i < n - 1:
                pause_x = left + gap // 2
                self._table_pptx_add_pause_marker(slide, pause_x, top, BOX_H, scale)
                left += gap

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
