"""Учёт рабочего времени: сколько отработано активного времени за день.

Время идёт, пока экран разблокирован, и стоит, когда Windows заблокирован (Win+L, блокировка по таймеру,
отключённый удалённый сеанс) или компьютер спал. Каждый день — одна запись: приход, уход, отработано, норма.
Хранилище — history.json (атомарная запись); для Excel — export_xlsx().
"""
import json
import os
import re
import sys
import threading
import time
from datetime import date, datetime

REST = 180.0              # перерыв (блокировка / сон) от 3 минут обнуляет «долгую работу подряд»
NOTICE_SECONDS = 10.0     # сколько уведомление «висит» в данных для окон
CAP = 5.0                 # шаг дольше (сон / зависание) в отработанное не засчитывается
SAVE_EVERY = 15.0         # как часто сбрасывать на диск, секунд
WEEK = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']


def is_locked():
    """True — рабочий стол заблокирован. Заблокированный Windows переключает ввод на защищённый рабочий стол,
    и OpenInputDesktop для обычной программы заканчивается отказом. Вне Windows — всегда False."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        u.OpenInputDesktop.restype = wintypes.HANDLE
        u.SwitchDesktop.argtypes = [wintypes.HANDLE]
        u.SwitchDesktop.restype = wintypes.BOOL
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        h = u.OpenInputDesktop(0, False, 0x0100)         # DESKTOP_SWITCHDESKTOP
        if not h:
            return True
        ok = u.SwitchDesktop(h)
        u.CloseDesktop(h)
        return not ok
    except Exception:
        return False                                     # не смогли определить — считаем, что работаем


def hms(dt):
    return dt.strftime('%H:%M:%S')


def to_sec(text):
    """'09:30' / '09:30:15' → секунды от полуночи (или None)."""
    m = re.fullmatch(r'\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*', str(text or ''))
    if not m:
        return None
    h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s if h < 24 and mi < 60 and s < 60 else None


def iso_dt(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S')


def parse_dt(text):
    try:
        return datetime.strptime(str(text), '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None


def plural(n, one, few, many):
    n = abs(int(n))
    return one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def hours_left_text(k):
    return f"{plural(k, 'Остался', 'Осталось', 'Осталось')} {k} {plural(k, 'час', 'часа', 'часов')}"


def streak_text(sec):
    m = int(sec // 60)
    if m < 60:
        return f"{m} мин"
    return f"{m // 60} ч" + (f" {m % 60} мин" if m % 60 else "")


def hm_text(sec):
    sec = max(0, int(sec))
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def _new_day(norm_s):
    return {"arrival": None, "leave": None, "worked": 0.0, "norm": int(norm_s), "events": [], "notified": [], "no_break": False}


class Tracker:
    def __init__(self, path, norm_s=8 * 3600, clock=time.time, mono=time.monotonic, locked=is_locked):
        self.path, self.norm_s = path, int(norm_s)
        self._clock, self._mono, self._locked = clock, mono, locked
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.days = self._load()
        self.locked = False
        self._last = mono()
        self._saved_at = self._last
        self._open_ev = None                             # незакрытая блокировка (ссылка на запись в days[...]["events"])
        self._active_day = None                          # день и момент последнего «живого» тика (для времени ухода в блок)
        self._active_at = None
        self._alive = None
        self.opts = {"hours": True, "brk": True, "brk_min": 60}      # напоминания (настройки приложения)
        self.streak = 0.0                                # секунд непрерывной работы (без перерыва от REST)
        self._next_break = 3600.0
        self._rest = 0.0                                 # сколько идёт текущая блокировка / сон
        self.notice = None                               # {"id", "kind", "text", "until"} — последнее уведомление
        self._nid = 0
        self.on_notice = None                            # вызывается при новом уведомлении
        self.on_tick = None                              # вызывается после каждого тика (run)

    # ---------- уведомления ----------
    def set_notify(self, hours, brk, brk_min):
        with self._lock:
            self.opts = {"hours": bool(hours), "brk": bool(brk), "brk_min": int(brk_min)}
            step = self.opts["brk_min"] * 60
            self._next_break = (int(self.streak // step) + 1) * step

    def _fire(self, kind, text, m):
        self._nid += 1
        self.notice = {"id": self._nid, "kind": kind, "text": text, "until": m + NOTICE_SECONDS}
        if self.on_notice:
            try:
                self.on_notice(self.notice)
            except Exception:
                pass

    def _notify(self, day, dt, m):
        """Каждый ровный час до нормы («Осталось 7 часов» …), «норма выполнена» и напоминание о перерыве после долгой работы."""
        worked, norm = day["worked"], day["norm"]
        if self.opts["hours"] and worked > 0:
            left = norm - worked
            for k in range((norm - 1) // 3600, 0, -1):               # 7, 6, … 1 при норме 8 ч (сам «8» — начало дня)
                if left <= k * 3600 and k not in day["notified"]:
                    day["notified"].append(k)
                    if left > k * 3600 - 120:                         # свежее пересечение; после перезапуска старые молча помечаются
                        self._fire("hour", hours_left_text(k), m)
            if left <= 0 and 0 not in day["notified"]:
                day["notified"].append(0)
                if -left < 120:
                    self._fire("done", "Норма выполнена — можно заканчивать", m)
        if self.opts["brk"] and not day.get("no_break") and self.streak >= self._next_break:
            step = self.opts["brk_min"] * 60
            self._next_break = (int(self.streak // step) + 1) * step
            self._fire("break", f"Вы работаете уже {streak_text(self.streak)} подряд — сделайте небольшой перерыв", m)

    # ---------- диск ----------
    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            raw = data.get("days", {})
            alive = parse_dt(data.get("alive"))
        except (OSError, ValueError, AttributeError):
            return {}
        out = {}
        for k, d in (raw.items() if isinstance(raw, dict) else []):
            try:
                date.fromisoformat(k)
                evs = []
                for e in d.get("events") or []:
                    lock, unlock = parse_dt(e.get("lock")), parse_dt(e.get("unlock"))
                    if lock is None:
                        continue
                    if unlock is None:                   # программу выключили при блокировке (выключение, сбой) — до последнего «живого» момента
                        unlock = alive if alive and alive >= lock else lock
                    evs.append({"lock": iso_dt(lock), "unlock": iso_dt(unlock), "kind": e.get("kind") if e.get("kind") in ("lock", "sleep") else "lock"})
                out[k] = {"arrival": d.get("arrival") if to_sec(d.get("arrival")) is not None else None,
                          "leave": d.get("leave") if to_sec(d.get("leave")) is not None else None,
                          "worked": max(0.0, float(d.get("worked", 0))), "norm": int(d.get("norm", self.norm_s)), "events": evs,
                          "notified": [int(x) for x in d.get("notified", []) if isinstance(x, int)], "no_break": d.get("no_break") is True}
            except (ValueError, TypeError, AttributeError):
                continue
        return out

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({"alive": self._alive, "days": self.days}, f, ensure_ascii=False, indent=1)
                os.replace(tmp, self.path)               # не оставляем полузаписанный файл
            except OSError:
                pass
            self._saved_at = self._mono()

    # ---------- ход времени ----------
    def tick(self):
        with self._lock:
            now, m = self._clock(), self._mono()
            dt, self._last = max(0.0, m - self._last), m
            t = datetime.fromtimestamp(now)
            was = self.locked
            self.locked = bool(self._locked())
            self._alive = iso_dt(t)
            if self.locked:
                self._rest += dt
                if self._rest >= REST:
                    self.streak, self._next_break = 0.0, self.opts["brk_min"] * 60.0
                if not was and self._active_day in self.days:
                    # ушли в блокировку: время — последний момент, когда видели работу (после сна — не момент пробуждения)
                    ev = {"lock": iso_dt(self._active_at or t), "unlock": None, "kind": "lock"}
                    self.days[self._active_day]["events"].append(ev)
                    self._open_ev = ev
            else:
                iso = t.date().isoformat()
                day = self.days.setdefault(iso, _new_day(self.norm_s))
                if day["arrival"] is None:
                    day["arrival"] = hms(t)
                if was:
                    if self._open_ev is not None:
                        self._open_ev["unlock"] = iso_dt(t)      # разблокировали
                        self._open_ev = None
                elif dt > CAP and self._active_at is not None:
                    day["events"].append({"lock": iso_dt(self._active_at), "unlock": iso_dt(t), "kind": "sleep"})   # сон без блокировки
                if dt > CAP or was:
                    self._rest += dt if dt > CAP and not was else 0.0
                    if self._rest >= REST:               # долгий перерыв — «работа подряд» начинается заново
                        self.streak, self._next_break = 0.0, self.opts["brk_min"] * 60.0
                    self._rest = 0.0
                if dt <= CAP and not was:
                    day["worked"] += dt                  # после блокировки / сна первый шаг не засчитываем
                    self.streak += dt
                    self._notify(day, dt, m)
                day["leave"] = hms(t)
                self._active_day, self._active_at = iso, t
            if self.locked != was or m - self._saved_at >= SAVE_EVERY:
                self.save()                              # смена состояния — сразу на диск; и раз в SAVE_EVERY (в том числе при блокировке: метка «жива»)

    def run(self, stop=None):
        stop = stop or self._stop
        while not stop.wait(1.0):
            try:
                self.tick()
                if self.on_tick:
                    self.on_tick()
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        self.save()

    def set_norm(self, norm_s):
        with self._lock:
            self.norm_s = int(norm_s)
            today = datetime.fromtimestamp(self._clock()).date().isoformat()
            if today in self.days:
                self.days[today]["norm"] = self.norm_s
            self.save()

    # ---------- данные для окон ----------
    @staticmethod
    def _break(d):
        a, l = to_sec(d.get("arrival")), to_sec(d.get("leave"))
        return max(0, (l - a) - d["worked"]) if a is not None and l is not None and l >= a else 0

    def snapshot(self):
        with self._lock:
            now = datetime.fromtimestamp(self._clock())
            d = self.days.get(now.date().isoformat()) or _new_day(self.norm_s)
            return {"date": now.date().isoformat(), "arrival": d["arrival"], "leave": d["leave"], "worked_s": d["worked"],
                    "norm_s": d["norm"], "break_s": self._break(d), "locked": self.locked, "events_n": len(d["events"]),
                    "notice": {k: self.notice[k] for k in ("id", "kind", "text")} if self.notice and self._mono() < self.notice["until"] else None}

    def _events(self, d, now):
        out = []
        for e in d["events"]:
            a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
            out.append({"lock": e["lock"], "unlock": e["unlock"], "kind": e["kind"],
                        "dur_s": int(((b or now) - a).total_seconds()) if a else 0})
        return out

    def history(self):
        with self._lock:
            nowdt = datetime.fromtimestamp(self._clock())
            today = nowdt.date()
            rows = []
            for k in sorted(self.days, reverse=True):
                d = self.days[k]
                dd = date.fromisoformat(k)
                rows.append({"date": k, "weekday": WEEK[dd.weekday()], "arrival": d["arrival"], "leave": d["leave"],
                             "worked_s": d["worked"], "norm_s": d["norm"], "break_s": self._break(d),
                             "delta_s": d["worked"] - d["norm"], "today": dd == today,
                             "events": self._events(d, nowdt)})
            month = [r for r in rows if r["date"][:7] == today.isoformat()[:7]]
            return {"rows": rows, "month": {"days": len(month), "worked_s": sum(r["worked_s"] for r in month),
                                              "norm_s": sum(r["norm_s"] for r in month),
                                              "delta_s": sum(r["delta_s"] for r in month)}}

    # ---------- ручные правки ----------
    def edit_day(self, iso, arrival, leave, worked):
        """Исправить / добавить день. arrival, leave, worked — «ЧЧ:ММ». Возвращает {"ok"} или {"error"}."""
        with self._lock:
            try:
                date.fromisoformat(str(iso))
            except ValueError:
                return {"error": "Неверная дата."}
            a, l, w = to_sec(arrival), to_sec(leave), to_sec(worked)
            if a is None or l is None or w is None:
                return {"error": "Время — в формате ЧЧ:ММ."}
            today = datetime.fromtimestamp(self._clock()).date().isoformat()
            if iso == today and iso in self.days and self.days[iso]["leave"]:
                l = to_sec(self.days[iso]["leave"])      # «уход» за сегодня обновляется сам
            if l < a:
                return {"error": "Уход раньше прихода."}
            if w > l - a:
                return {"error": "Отработано больше, чем между приходом и уходом."}
            d = self.days.setdefault(iso, _new_day(self.norm_s))
            d["arrival"], d["worked"] = hm_text(a) + ':00', float(w)
            d["leave"] = self.days[iso]["leave"] if iso == today and d["leave"] else hm_text(l) + ':00'
            self.save()
            return {"ok": True}

    def skip_break(self, all_day=False):
        """Перерыв не обязателен. all_day — до конца сегодняшнего дня о перерыве больше не напоминать
        (обычное «Пропустить» только закрывает плашку, следующее напоминание — через обычный интервал)."""
        with self._lock:
            if all_day:
                day = self.days.setdefault(datetime.fromtimestamp(self._clock()).date().isoformat(), _new_day(self.norm_s))
                day["no_break"] = True
                self.save()
            return {"ok": True}

    def suggest_worked(self, arrival):
        """Сколько отработано на сейчас, если сегодня пришли в arrival («ЧЧ:ММ»): от прихода до этого момента минус
        известные блокировки и сон. Время, когда приложение было закрыто, считается рабочим — его можно поправить руками."""
        with self._lock:
            a = to_sec(arrival)
            now = datetime.fromtimestamp(self._clock())
            if a is None:
                return None
            now_s = now.hour * 3600 + now.minute * 60 + now.second
            if a > now_s:
                return None
            day = self.days.get(now.date().isoformat())
            start = datetime.combine(now.date(), datetime.min.time()).replace(hour=a // 3600, minute=a % 3600 // 60)
            rest = 0
            for e in (day["events"] if day else []):
                lo, hi = parse_dt(e["lock"]), parse_dt(e["unlock"]) or now
                lo = max(lo, start)
                if hi > lo:
                    rest += (hi - lo).total_seconds()
            return int(max(0, now_s - a - rest))

    def delete_day(self, iso):
        with self._lock:
            if self.days.pop(str(iso), None) is not None:
                self.save()
            return {"ok": True}

    # ---------- таблица Excel ----------
    def export_xlsx(self, path):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        with self._lock:
            ks = sorted(self.days)
            snap = {k: dict(self.days[k]) for k in ks}
        wb = Workbook()
        ws = wb.active
        ws.title = 'Учёт времени'
        head = ['Дата', 'День', 'Приход', 'Уход', 'Отработано', 'Перерывы', 'Норма', 'Разница, мин']
        ws.append(head)
        for k in ks:
            d = snap[k]
            dd = date.fromisoformat(k)
            a, l = to_sec(d["arrival"]), to_sec(d["leave"])
            ws.append([dd, WEEK[dd.weekday()],
                       datetime.min.time().replace(hour=a // 3600, minute=a % 3600 // 60) if a is not None else None,
                       datetime.min.time().replace(hour=l // 3600, minute=l % 3600 // 60) if l is not None else None,
                       d["worked"] / 86400, self._break(d) / 86400, d["norm"] / 86400, round((d["worked"] - d["norm"]) / 60)])
        n = len(ks)
        ws.append(['Итого', None, None, None, f'=SUM(E2:E{n + 1})', f'=SUM(F2:F{n + 1})', f'=SUM(G2:G{n + 1})', f'=SUM(H2:H{n + 1})'])
        line = Side(style='thin', color='D0D5DD')
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='3B6CF6')
            c.alignment = Alignment(horizontal='center', vertical='center')
        for r in range(2, n + 3):
            ws.cell(r, 1).number_format = 'DD.MM.YYYY'
            for col in (3, 4):
                ws.cell(r, col).number_format = 'HH:MM'
            for col in (5, 6, 7):
                ws.cell(r, col).number_format = '[h]:mm'
            ws.cell(r, 8).number_format = '+0;-0;0'
            for col in range(1, 9):
                ws.cell(r, col).border = Border(bottom=line)
                ws.cell(r, col).alignment = Alignment(horizontal='center')
        for c in ws[n + 2]:
            c.font = Font(bold=True)
        for i, w in enumerate([13, 7, 10, 10, 13, 12, 10, 14], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = 'A2'
        ev = wb.create_sheet('Блокировки')
        ev.append(['День', 'Тип', 'Заблокирован', 'Разблокирован', 'Длительность'])
        for k in ks:
            for e in snap[k]["events"]:
                a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
                ev.append([date.fromisoformat(k), 'пауза' if e["kind"] == "sleep" else 'блокировка', a, b,
                           (b - a).total_seconds() / 86400 if a and b else None])
        for c in ev[1]:
            c.font, c.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='3B6CF6')
            c.alignment = Alignment(horizontal='center', vertical='center')
        for r in range(2, ev.max_row + 1):
            ev.cell(r, 1).number_format = 'DD.MM.YYYY'
            ev.cell(r, 3).number_format = ev.cell(r, 4).number_format = 'DD.MM.YYYY HH:MM:SS'
            ev.cell(r, 5).number_format = '[h]:mm:ss'
            for col in range(1, 6):
                ev.cell(r, col).alignment = Alignment(horizontal='center')
        for i, w in enumerate([13, 13, 21, 21, 14], 1):
            ev.column_dimensions[get_column_letter(i)].width = w
        ev.freeze_panes = 'A2'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wb.save(path)
        return path
