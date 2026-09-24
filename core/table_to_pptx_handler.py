import os
import webview
import openpyxl
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_CONNECTOR

PAUSE_COLOR = RGBColor(0xC0, 0x00, 0x00)
TEXT_COLOR = RGBColor(0x00, 0x00, 0x00)
BRAND_COLOR = RGBColor(0x60, 0x60, 0x60)

SLIDE_W = Emu(int(13.333 * 914400))
SLIDE_H = Emu(int(7.5 * 914400))
BOX_H = Inches(2.6)
MARGIN = Inches(0.3)
GAP = Inches(0.16)
MIN_BOX_W = Inches(0.5)


class TableToPptxMixin:
    """«Таблица → PowerPoint» — построчный экспорт: каждая строка Excel
    становится отдельным слайдом, каждая ячейка — своим блоком текста на
    слайде, а между блоками — метка «Пауза» (вертикальная красная черта),
    чтобы при нарезке аудио были чёткие границы между категориями. Колонка
    «марка» ставится подписью над колонкой «транскрипция» — одним блоком,
    без паузы между ними, раз это одно и то же значение, просто записанное
    двумя способами."""

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

        headers = [str(c).strip() if c is not None else '' for c in header_row]
        while headers and not headers[-1]:
            headers.pop()
        if not headers:
            return {"error": "В первой строке таблицы нет заголовков колонок."}

        ncols = len(headers)
        data_rows = []
        for row in rows_iter:
            cells = list(row[:ncols]) + [None] * max(0, ncols - len(row))
            values = [str(c).strip() if c is not None else '' for c in cells]
            if not any(values):
                continue
            data_rows.append(values)

        if not data_rows:
            return {"error": "В таблице не нашлось ни одной строки с данными (кроме заголовков)."}

        brand_idx, transcript_idx = self._table_pptx_find_brand_pair(headers)

        self.table_pptx_path = path
        self.table_pptx_headers = headers
        self.table_pptx_rows = data_rows
        self.table_pptx_brand_idx = brand_idx
        self.table_pptx_transcript_idx = transcript_idx

        return {
            "file": os.path.basename(path),
            "rows": len(data_rows),
            "columns": headers,
            "brand_pair": [headers[brand_idx], headers[transcript_idx]] if brand_idx is not None else None,
        }

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

        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H
        blank_layout = prs.slide_layouts[6]

        try:
            for row in rows:
                self._table_pptx_build_slide(prs, blank_layout, row, brand_idx, transcript_idx)
            prs.save(path)
        except Exception as e:
            return {"error": f"Не удалось собрать презентацию.\n\n{e}"}

        return {"status": "ok", "path": path, "slides": len(rows)}

    def _table_pptx_build_slide(self, prs, layout, row, brand_idx, transcript_idx):
        segments = []
        skip = {transcript_idx} if brand_idx is not None else set()
        for i, val in enumerate(row):
            if i in skip:
                continue
            if brand_idx is not None and i == brand_idx:
                sub = row[transcript_idx] if transcript_idx < len(row) else ''
                segments.append({"brand": val, "sub": sub})
            else:
                segments.append({"text": val})

        slide = prs.slides.add_slide(layout)
        bg = slide.background
        bg.fill.solid()
        bg.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        n = len(segments)
        if n == 0:
            return

        usable_w = prs.slide_width - 2 * MARGIN
        seg_w = usable_w // n
        top = (prs.slide_height - BOX_H) // 2
        box_w = max(seg_w - GAP, MIN_BOX_W)

        for i, seg in enumerate(segments):
            left = MARGIN + i * seg_w
            self._table_pptx_add_segment_box(slide, seg, left, top, box_w, BOX_H)
            if i < n - 1:
                pause_x = left + seg_w - GAP // 2
                self._table_pptx_add_pause_marker(slide, pause_x, top, BOX_H)

    @staticmethod
    def _table_pptx_add_segment_box(slide, seg, left, top, width, height):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        # word_wrap выключен нарочно: при переносе слов PowerPoint сжимает
        # шрифт вертикально, чтобы влезло много строк — получаются рваные
        # переносы («мобиль» → «моб»/«иль») и мелкий текст. Без переноса
        # автоподбор сжимает шрифт горизонтально, пока строка не влезет
        # целиком в одну строку — крупнее и читается одним словом.
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE

        if 'brand' in seg:
            p1 = tf.paragraphs[0]
            p1.alignment = PP_ALIGN.CENTER
            r1 = p1.add_run()
            r1.text = seg.get('brand') or ''
            r1.font.size = Pt(24)
            r1.font.bold = False
            r1.font.color.rgb = BRAND_COLOR

            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            r2 = p2.add_run()
            r2.text = seg.get('sub') or ''
            r2.font.size = Pt(44)
            r2.font.bold = True
            r2.font.color.rgb = TEXT_COLOR
        else:
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = seg.get('text') or ''
            r.font.size = Pt(44)
            r.font.bold = True
            r.font.color.rgb = TEXT_COLOR

    @staticmethod
    def _table_pptx_add_pause_marker(slide, x, top, height):
        label_w = Inches(1.1)
        label_h = Inches(0.4)
        label = slide.shapes.add_textbox(x - label_w // 2, top - label_h - Inches(0.06), label_w, label_h)
        tf = label.text_frame
        tf.word_wrap = False
        tf.auto_size = MSO_AUTO_SIZE.NONE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = 'Пауза'
        r.font.size = Pt(16)
        r.font.bold = True
        r.font.color.rgb = PAUSE_COLOR

        line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x, top, x, top + height)
        line.line.color.rgb = PAUSE_COLOR
        line.line.width = Pt(3)
