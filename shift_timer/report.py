"""Отчёт за неделю или месяц одним Excel-файлом — показать руководителю: часы по дням, задачи и сколько ушло на каждую.

Листы: «Сводка» (итоги и таблица по дням, график 5/2), «Задачи» (что делали, теги, сколько ушло, ожидание), «По тегам».
Данные приходят готовыми (`Tracker.summary`, `TaskStore.rows_between`) — здесь только оформление.
"""
import os
from datetime import date, timedelta

from tasks import TAGS, fmt_dur

STATUS = {"new": 'не начата', "running": 'в работе', "paused": 'на паузе', "done": 'выполнена'}
MARK_NAMES = {"vacation": "отпуск", "sick": "больничный", "dayoff": "выходной"}
MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']


def _d(iso):
    return date.fromisoformat(iso)


def label(kind, start, end):
    f = lambda d: f'{d.day:02d}.{d.month:02d}.{d.year}'
    return f'{"Неделя" if kind == "week" else "Месяц"}: {f(start)} — {f(end)}'


def period(kind, iso):
    """Границы недели (пн–вс) или месяца, в которые попадает день iso."""
    d = _d(iso)
    if kind == 'week':
        a = d - timedelta(days=d.weekday())
        return a, a + timedelta(days=6)
    a = d.replace(day=1)
    return a, date(a.year + (a.month == 12), a.month % 12 + 1, 1) - timedelta(days=1)


def tag_stats(rows):
    """По тегам: сколько задач, выполнено, времени за период и ожидания. Задача с несколькими тегами идёт в каждый."""
    out = {t: {"n": 0, "done": 0, "sec": 0, "wait": 0} for t in TAGS}
    out["Без тега"] = {"n": 0, "done": 0, "sec": 0, "wait": 0}
    for r in rows:
        for g in (r["tags"] or ["Без тега"]):
            o = out[g]
            o["n"] += 1
            o["done"] += 1 if r["done"] else 0
            o["sec"] += r["period_s"] or 0
            o["wait"] += r["wait_s"] or 0
    return out


def export_report(path, kind, summary, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    head_fill, head_font = PatternFill('solid', fgColor='3B6CF6'), Font(bold=True, color='FFFFFF')
    grey, line = PatternFill('solid', fgColor='F1F3F8'), Side(style='thin', color='D0D5E2')
    start, end = _d(summary["start"]), _d(summary["end"])

    def header(ws, row, titles):
        for i, t in enumerate(titles, 1):
            c = ws.cell(row, i, t)
            c.font, c.fill = head_font, head_fill
            c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    def widths(ws, ws_w):
        for i, w in enumerate(ws_w, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    wb = Workbook()
    ws = wb.active
    ws.title = 'Сводка'
    ws['A1'] = 'Отчёт за неделю' if kind == 'week' else 'Отчёт за месяц'
    ws['A1'].font = Font(bold=True, size=16)
    ws['A2'] = label(kind, start, end) + '  ·  график 5/2'
    ws['A2'].font = Font(color='6B7280')
    done = sum(1 for r in rows if r["done"] and r["finished"] and start <= r["finished"].date() <= end)
    made = sum(1 for r in rows if start <= r["created"].date() <= end)
    work = sum(1 for r in rows if not r["done"])
    items = [('Отработано', timedelta(seconds=summary["worked_s"]), '[h]:mm'), ('Норма (до сегодня)', timedelta(seconds=summary["norm_s"]), '[h]:mm'),
             ('Баланс (переработка / недоработка)', timedelta(seconds=abs(summary["delta_s"])), '[h]:mm'),
             ('Рабочих дней по графику', summary["workdays"], '0'), ('Отпуск, дней', summary["vacation"], '0'), ('Больничный, дней', summary["sick"], '0'),
             ('Выходной (отгул), дней', summary["dayoff"], '0'), ('Средний приход', (summary["avg_arrival"] or '—')[:5], '@'),
             ('Средний уход', (summary["avg_leave"] or '—')[:5], '@'), ('Задач создано', made, '0'), ('Задач выполнено', done, '0'), ('Задач в работе', work, '0')]
    r = 4
    for name, val, fmt in items:
        ws.cell(r, 1, name).fill = grey
        c = ws.cell(r, 2, val)
        c.number_format, c.alignment = fmt, Alignment(horizontal='right')
        c.font = Font(bold=True)
        if name.startswith('Баланс'):
            ws.cell(r, 3, 'переработка' if summary["delta_s"] > 0 else 'недоработка' if summary["delta_s"] < 0 else 'в норме').font = Font(
                color='16A34A' if summary["delta_s"] >= 0 else 'D97706', bold=True)
        r += 1
    r += 1
    header(ws, r, ['Дата', 'День', 'Приход', 'Уход', 'Отработано', 'Норма', '±, мин', 'Отметка', 'Перерывы'])
    first = r + 1
    for d in summary["by_day"]:
        r += 1
        dd = _d(d["date"])
        mark = MARK_NAMES.get(d["mark"], 'выходной день' if d["weekend"] else '')
        ws.cell(r, 1, dd).number_format = 'DD.MM.YYYY'
        ws.cell(r, 2, d["weekday"])
        ws.cell(r, 3, (d["arrival"] or '')[:5] if not d["future"] else '')
        ws.cell(r, 4, (d["leave"] or '')[:5] if not d["future"] else '')
        ws.cell(r, 5, timedelta(seconds=d["worked_s"])).number_format = '[h]:mm'
        ws.cell(r, 6, timedelta(seconds=d["norm_s"])).number_format = '[h]:mm'
        ws.cell(r, 7, round(d["delta_s"] / 60))
        ws.cell(r, 8, mark)
        ws.cell(r, 9, timedelta(seconds=d["break_s"])).number_format = '[h]:mm'
        for col in range(1, 10):
            c = ws.cell(r, col)
            c.alignment = Alignment(horizontal='center')
            c.border = Border(bottom=line)
            if d["weekend"] or d["mark"]:
                c.fill = grey
    r += 1
    ws.cell(r, 1, 'Итого').font = Font(bold=True)
    for col, fmt in ((5, '[h]:mm'), (6, '[h]:mm'), (7, '0'), (9, '[h]:mm')):
        L = get_column_letter(col)
        c = ws.cell(r, col, f'=SUM({L}{first}:{L}{r - 1})')
        c.number_format, c.font, c.alignment = fmt, Font(bold=True), Alignment(horizontal='center')
    widths(ws, [34, 12, 10, 10, 13, 11, 10, 16, 12])
    ws.freeze_panes = 'A4'

    tk = wb.create_sheet('Задачи')
    header(tk, 1, ['Создана', 'Выполнена', 'Статус', 'Задача', 'Теги', 'Ушло всего', 'Ушло за период', 'Ждали ответа', 'Сейчас ждём', 'Подзадачи', 'Комментарий'])
    for r2, x in enumerate(rows, 2):
        status = STATUS.get(x.get("state"), 'в работе') if not x["waiting_who"] or x["done"] else 'ждём ответа'
        sub = '\n'.join(('✓ ' if dn else '○ ') + t for t, dn in x["subs"])
        vals = [x["created"], x["finished"], status, x["text"], ', '.join(x["tags"]),
                timedelta(seconds=x["elapsed_s"]) if x["elapsed_s"] is not None else None, timedelta(seconds=x["period_s"] or 0),
                timedelta(seconds=x["wait_s"]) if x["wait_s"] else None, x["waiting_who"], sub, x["comment"]]
        for col, v in enumerate(vals, 1):
            c = tk.cell(r2, col, v)
            c.alignment = Alignment(wrap_text=col in (4, 5, 10, 11), vertical='top', horizontal='left' if col in (4, 5, 10, 11) else 'center')
            if col in (1, 2):
                c.number_format = 'DD.MM.YYYY HH:MM'
            if col in (6, 7, 8):
                c.number_format = '[h]:mm'
        tk.cell(r2, 3).font = Font(bold=True, color='16A34A' if x["done"] else 'D97706')
    n = len(rows) + 1
    if rows:
        tk.cell(n + 1, 4, 'Итого за период').font = Font(bold=True)
        c = tk.cell(n + 1, 7, f'=SUM(G2:G{n})')
        c.number_format, c.font, c.alignment = '[h]:mm', Font(bold=True), Alignment(horizontal='center')
        tk.cell(n + 3, 4, 'Время идёт по часам: параллельные задачи считаются каждая отдельно, ожидание ответа входит в «ушло».').font = Font(italic=True, color='6B7280')
    widths(tk, [17, 17, 13, 46, 22, 13, 14, 13, 16, 30, 40])
    tk.freeze_panes = 'A2'

    tg = wb.create_sheet('По тегам')
    header(tg, 1, ['Тег', 'Задач', 'Выполнено', 'Ушло за период', 'Ждали ответа'])
    for r3, (g, v) in enumerate(((g, v) for g, v in tag_stats(rows).items() if v["n"]), 2):
        for col, val in enumerate([g, v["n"], v["done"], timedelta(seconds=v["sec"]), timedelta(seconds=v["wait"])], 1):
            c = tg.cell(r3, col, val)
            c.alignment = Alignment(horizontal='left' if col == 1 else 'center')
            if col >= 4:
                c.number_format = '[h]:mm'
    widths(tg, [26, 10, 12, 16, 14])

    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    wb.save(path)
    return path
