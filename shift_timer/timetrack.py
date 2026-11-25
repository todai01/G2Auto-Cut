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
from datetime import date, datetime, timedelta
from tasks import fmt_dur

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


TASK_STATUS = {"new": 'не начата', "running": 'в работе', "paused": 'на паузе', "done": 'выполнена'}
MARKS = {"vacation": "отпуск", "sick": "больничный", "dayoff": "выходной"}


def _new_day(norm_s):
    return {"arrival": None, "leave": None, "worked": 0.0, "norm": int(norm_s), "events": [], "notified": [], "no_break": False}


class Tracker:
    def __init__(self, path, norm_s=8 * 3600, clock=time.time, mono=time.monotonic, locked=is_locked):
        self.path, self.norm_s = path, int(norm_s)
        self._clock, self._mono, self._locked = clock, mono, locked
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.days = self._load()
        self.marks = self._load_marks()                  # отметки дней: {"2026-12-01": "vacation" | "sick" | "dayoff"}
        self.locked = False
        self._last = mono()
        self._saved_at = self._last
        self.lunch_len_s = 3600                          # длительность обеда (настройка)
        self._open_lunch = self._find_open_lunch()       # идущий обед: событие kind="lunch" без unlock (переживает перезапуск)
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

    def notify(self, kind, text):
        """Показать своё уведомление (мини-окно, звук) — например «Доступна новая версия»."""
        with self._lock:
            self._fire(kind, text, self._mono())

    def leave_left(self, day, now=None):
        """Сколько секунд до ухода: приход + норма + обед (фиксированные настенные часы, от отработанного и блокировок не зависят).
        Нет прихода — None."""
        a = to_sec(day.get("arrival"))
        if a is None:
            return None
        now = now or datetime.fromtimestamp(self._clock())
        return a + day["norm"] + self.lunch_len_s - (now.hour * 3600 + now.minute * 60 + now.second)

    def _notify(self, day, dt, m):
        """Каждый ровный час до ухода («Осталось 8 часов» … «Остался 1 час»: уход = приход + норма + обед), «время ухода»,
        «норма выполнена» (по отработанному) и напоминание о перерыве после долгой работы."""
        worked, norm = day["worked"], day["norm"]
        left = self.leave_left(day)
        if self.opts["hours"] and left is not None:
            for k in range((norm + self.lunch_len_s - 1) // 3600, 0, -1):        # 8, 7, … 1 при норме 8 ч и обеде 1 ч
                if left <= k * 3600 and k not in day["notified"]:
                    day["notified"].append(k)
                    if left > k * 3600 - 120:                         # свежее пересечение; после перезапуска старые молча помечаются
                        self._fire("hour", hours_left_text(k), m)
            if left <= 0 and -1 not in day["notified"]:
                day["notified"].append(-1)
                if -left < 120:
                    self._fire("done", "Время ухода — можно идти домой", m)
        if self.opts["hours"] and worked > 0 and worked >= norm and 0 not in day["notified"]:
            day["notified"].append(0)
            if worked - norm < 120:
                self._fire("done", "Норма выполнена", m)
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
                    kind = e.get("kind") if e.get("kind") in ("lock", "sleep", "lunch", "studio") else "lock"
                    if unlock is None and kind == "lunch" and lock.date() == datetime.fromtimestamp(self._clock()).date():
                        evs.append({"lock": iso_dt(lock), "unlock": None, "kind": "lunch"})      # обед идёт — таймер переживает перезапуск
                        continue
                    if unlock is None:                   # программу выключили при блокировке (выключение, сбой) — до последнего «живого» момента
                        unlock = alive if alive and alive >= lock else lock
                        if kind == "lunch":
                            unlock = min(unlock, lock + timedelta(hours=1))
                    evs.append({"lock": iso_dt(lock), "unlock": iso_dt(unlock), "kind": kind})
                out[k] = {"arrival": d.get("arrival") if to_sec(d.get("arrival")) is not None else None,
                          "leave": d.get("leave") if to_sec(d.get("leave")) is not None else None,
                          "worked": max(0.0, float(d.get("worked", 0))), "norm": int(d.get("norm", self.norm_s)), "events": evs,
                          "notified": [int(x) for x in d.get("notified", []) if isinstance(x, int)], "no_break": d.get("no_break") is True}
            except (ValueError, TypeError, AttributeError):
                continue
        for d in out.values():
            self._strip_inside_lunch(d)                  # в старых журналах обед и блокировка на одно и то же время — оставляем обед
        return out

    def _load_marks(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f).get("marks", {})
        except (OSError, ValueError, AttributeError):
            return {}
        out = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            try:
                date.fromisoformat(k)
            except ValueError:
                continue
            if v in MARKS:
                out[k] = v
        return out

    def reload(self):
        """Перечитать журнал с диска (после восстановления из копии)."""
        with self._lock:
            self.days = self._load()
            self.marks = self._load_marks()
            self._open_lunch = self._find_open_lunch()
            self._open_ev, self._active_day, self._active_at = None, None, None

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump({"alive": self._alive, "days": self.days, "marks": self.marks}, f, ensure_ascii=False, indent=1)
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
                if self._open_lunch is not None:
                    self._open_ev = None                 # идёт обед: блокировка — часть обеда, отдельным событием её не пишем
                elif not was and self._active_day in self.days:
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
                elif dt > CAP and self._active_at is not None and self._open_lunch is None:
                    day["events"].append({"lock": iso_dt(self._active_at), "unlock": iso_dt(t), "kind": "sleep"})   # пауза без блокировки (на обеде не пишем)
                if dt > CAP or was:
                    self._rest += dt if dt > CAP and not was else 0.0
                    if self._rest >= REST:               # долгий перерыв — «работа подряд» начинается заново
                        self.streak, self._next_break = 0.0, self.opts["brk_min"] * 60.0
                    self._rest = 0.0
                lunch = self._open_lunch
                if lunch is not None:                    # обед закончился, а вы за компьютером — работа продолжается сама
                    st = parse_dt(lunch["lock"])
                    if st and (t - st).total_seconds() >= self.lunch_len_s:
                        self._end_lunch(t, m, auto=True)
                        lunch = None
                if dt <= CAP and not was and lunch is None:
                    day["worked"] += dt                  # после блокировки / сна первый шаг не засчитываем; на обеде время стоит
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

    # ---------- обед: отдельный таймер ----------
    def _find_open_lunch(self):
        for d in self.days.values():
            for e in d["events"]:
                if e["kind"] == "lunch" and e["unlock"] is None:
                    return e
        return None

    def set_lunch(self, seconds):
        with self._lock:
            self.lunch_len_s = max(60, int(seconds))

    def start_lunch(self):
        """Обед: рабочее время встаёт, идёт свой таймер (по настенным часам — и при блокировке, и во сне)."""
        with self._lock:
            if self._open_lunch is None:
                t = datetime.fromtimestamp(self._clock())
                day = self.days.setdefault(t.date().isoformat(), _new_day(self.norm_s))
                ev = {"lock": iso_dt(t), "unlock": None, "kind": "lunch"}
                day["events"].append(ev)
                self._open_lunch = ev
                self.streak, self._next_break = 0.0, self.opts["brk_min"] * 60.0
                self.save()
            return {"ok": True}

    def end_lunch(self):
        with self._lock:
            if self._open_lunch is not None:
                self._end_lunch(datetime.fromtimestamp(self._clock()), self._mono(), auto=False)
            return {"ok": True}

    @staticmethod
    def _strip_inside_lunch(day, tol=3):
        """Убрать блокировки и паузы, целиком лежащие внутри обеда: это то же время (на допуск tol секунд)."""
        lun = [(parse_dt(e["lock"]), parse_dt(e["unlock"]) or datetime.max) for e in day["events"] if e["kind"] == "lunch"]
        if not lun:
            return
        t = timedelta(seconds=tol)

        def inside(e):
            a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
            return e["kind"] != "lunch" and a and b and any(a >= la - t and b <= lb + t for la, lb in lun if la)
        day["events"][:] = [e for e in day["events"] if not inside(e)]

    def _end_lunch(self, t, m, auto):
        self._open_lunch["unlock"] = iso_dt(t)
        self._open_lunch = None
        for d in self.days.values():
            self._strip_inside_lunch(d)
        self.streak, self._next_break = 0.0, self.opts["brk_min"] * 60.0
        if auto:
            self._fire("lunch", "Обед закончился — время пошло", m)
        self.save()

    def _lunch_s(self, d, now):
        """Сколько обеда в дне (идущий — до сейчас)."""
        total = 0.0
        for e in d["events"]:
            if e["kind"] == "lunch":
                a, b = parse_dt(e["lock"]), parse_dt(e["unlock"]) or now
                if a:
                    total += max(0.0, (b - a).total_seconds())
        return total

    @staticmethod
    def _studio_s(d):
        """Сколько времени в дне отмечено как «студия» (ушли на запись): это не перерыв."""
        total = 0.0
        for e in d["events"]:
            if e["kind"] == "studio":
                a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
                if a and b:
                    total += max(0.0, (b - a).total_seconds())
        return total

    # ---------- данные для окон ----------
    def _break(self, d):
        """Перерывы без обеда и студии: от прихода до ухода минус отработанное, обед и студия."""
        a, l = to_sec(d.get("arrival")), to_sec(d.get("leave"))
        if a is None or l is None or l < a:
            return 0
        return max(0, (l - a) - d["worked"] - self._lunch_s(d, datetime.fromtimestamp(self._clock())) - self._studio_s(d))

    def snapshot(self):
        with self._lock:
            now = datetime.fromtimestamp(self._clock())
            d = self.days.get(now.date().isoformat()) or _new_day(self.norm_s)
            return {"date": now.date().isoformat(), "arrival": d["arrival"], "leave": d["leave"], "worked_s": d["worked"],
                    "norm_s": d["norm"], "break_s": self._break(d), "locked": self.locked, "events_n": sum(1 for e in d["events"] if e["kind"] not in ("lunch", "studio")),
                    "notice": {k: self.notice[k] for k in ("id", "kind", "text")} if self.notice and self._mono() < self.notice["until"] else None,
                    "lunch": self._lunch_info(d, now)}

    def _events(self, d, now):
        out = []
        for i, e in enumerate(d["events"]):
            a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
            out.append({"i": i, "lock": e["lock"], "unlock": e["unlock"], "kind": e["kind"],
                        "dur_s": int(((b or now) - a).total_seconds()) if a else 0})
        return out

    def _lunch_info(self, d, now):
        on = self._open_lunch is not None and self._open_lunch in d["events"]
        done = self._lunch_s(d, now)
        elapsed = 0.0
        if on:
            st = parse_dt(self._open_lunch["lock"])
            elapsed = max(0.0, (now - st).total_seconds()) if st else 0.0
        plan = max(0.0, self.lunch_len_s - (elapsed if on else done))     # сколько обеда ещё впереди (для прогноза ухода)
        return {"on": on, "len_s": self.lunch_len_s, "elapsed_s": elapsed, "done_s": done, "plan_s": plan}

    def history(self):
        with self._lock:
            nowdt = datetime.fromtimestamp(self._clock())
            today = nowdt.date()
            rows = []
            for k in sorted(self.days, reverse=True):
                d = self.days[k]
                dd = date.fromisoformat(k)
                rows.append({"date": k, "weekday": WEEK[dd.weekday()], "mark": self.marks.get(k, ""), "arrival": d["arrival"], "leave": d["leave"],
                             "worked_s": d["worked"], "norm_s": d["norm"], "break_s": self._break(d),
                             "delta_s": d["worked"] - d["norm"], "today": dd == today,
                             "events": self._events(d, nowdt)})
            month = [r for r in rows if r["date"][:7] == today.isoformat()[:7]]
            return {"rows": rows, "month": {"days": len(month), "worked_s": sum(r["worked_s"] for r in month),
                                              "norm_s": sum(r["norm_s"] for r in month),
                                              "delta_s": sum(r["delta_s"] for r in month)}}

    # ---------- отметки дней, сводки, календарь (график 5/2: суббота и воскресенье — выходные) ----------
    def set_mark(self, start, end, kind):
        """Отметить день или период: «vacation» (отпуск), «sick» (больничный), «dayoff» (выходной); kind = '' снимает отметку.
        Норма таких дней — 0 (не недоработка). Возвращает {"ok", "n"} или {"error"}."""
        with self._lock:
            try:
                a = date.fromisoformat(str(start))
                b = date.fromisoformat(str(end or start))
            except ValueError:
                return {"error": "Неверная дата."}
            if kind and kind not in MARKS:
                return {"error": "Неизвестная отметка."}
            if b < a:
                return {"error": "Конец периода раньше начала."}
            if (b - a).days > 366:
                return {"error": "Период длиннее года."}
            n = 0
            for i in range((b - a).days + 1):
                k = (a + timedelta(days=i)).isoformat()
                if kind:
                    self.marks[k] = kind
                else:
                    self.marks.pop(k, None)
                n += 1
            self.save()
            return {"ok": True, "n": n}

    def day_norm(self, iso):
        """Норма дня в секундах: выходные (сб, вс) и отмеченные дни — 0; обычный будний день — норма дня (или текущая)."""
        dd = date.fromisoformat(iso)
        if self.marks.get(iso) or dd.weekday() >= 5:
            return 0
        d = self.days.get(iso)
        return d["norm"] if d else self.norm_s

    def summary(self, start, end):
        """Сводка за период [start, end] (даты). Норма считается до сегодняшнего дня; сегодняшний день недоработки не даёт,
        пока не закончен (норма сегодня = не больше уже отработанного). Возвращает словарь для экрана и отчёта."""
        with self._lock:
            today = datetime.fromtimestamp(self._clock()).date()
            worked = norm = plan = 0.0
            workdays = done_days = 0
            cnt = {"vacation": 0, "sick": 0, "dayoff": 0}
            arr, lea, by_day = [], [], []
            dd = start
            while dd <= end:
                iso = dd.isoformat()
                rec, mark = self.days.get(iso), self.marks.get(iso, "")
                full = self.day_norm(iso)
                w = rec["worked"] if rec else 0.0
                n = 0.0
                if dd <= today:
                    n = min(full, w) if dd == today else full
                worked += w if dd <= today else 0.0
                norm += n
                plan += full
                if dd.weekday() < 5:
                    if mark:
                        cnt[mark] += 1
                    else:
                        workdays += 1
                        done_days += 1 if dd <= today else 0
                if rec and rec["arrival"] and to_sec(rec["arrival"]) is not None and w > 0:
                    arr.append(to_sec(rec["arrival"]))
                    if rec["leave"] and dd < today and to_sec(rec["leave"]) is not None:
                        lea.append(to_sec(rec["leave"]))
                by_day.append({"date": iso, "weekday": WEEK[dd.weekday()], "arrival": rec["arrival"] if rec else None, "leave": rec["leave"] if rec else None,
                               "worked_s": w, "norm_s": n, "delta_s": w - n if dd <= today else 0, "mark": mark, "weekend": dd.weekday() >= 5,
                               "break_s": self._break(rec) if rec else 0, "future": dd > today})
                dd += timedelta(days=1)
            avg = lambda xs: hm_text(sum(xs) / len(xs)) + ':00' if xs else None
            return {"start": start.isoformat(), "end": end.isoformat(), "worked_s": worked, "norm_s": norm, "plan_s": plan, "delta_s": worked - norm,
                    "workdays": workdays, "workdays_done": done_days, "vacation": cnt["vacation"], "sick": cnt["sick"], "dayoff": cnt["dayoff"],
                    "days_worked": len(arr), "avg_arrival": avg(arr), "avg_leave": avg(lea), "by_day": by_day}

    def calendar(self, year, month):
        """Месяц для календаря: по каждому дню — отработано, норма, отметка; плюс сводка месяца."""
        with self._lock:
            try:
                first = date(int(year), int(month), 1)
            except (ValueError, TypeError):
                return {"error": "Неверный месяц."}
            last = (date(first.year + (first.month == 12), first.month % 12 + 1, 1)) - timedelta(days=1)
            s = self.summary(first, last)
            days = []
            for r in s["by_day"]:
                rec = self.days.get(r["date"])
                days.append({"date": r["date"], "wd": date.fromisoformat(r["date"]).weekday(), "worked_s": r["worked_s"], "norm_s": r["norm_s"],
                             "delta_s": r["delta_s"], "arrival": r["arrival"], "leave": r["leave"], "mark": r["mark"], "record": bool(rec and rec["worked"] > 0),
                             "today": r["date"] == datetime.fromtimestamp(self._clock()).date().isoformat(), "future": r["future"]})
            return {"year": first.year, "month": first.month, "days": days, "summary": {k: v for k, v in s.items() if k != "by_day"}}

    def day_info(self, iso):
        """Всё о дне для карточки в журнале (без задач — их добавляет Api)."""
        with self._lock:
            try:
                dd = date.fromisoformat(str(iso))
            except ValueError:
                return {"error": "Неверная дата."}
            now = datetime.fromtimestamp(self._clock())
            d = self.days.get(iso)
            full = self.day_norm(iso)
            today = dd == now.date()
            w = d["worked"] if d else 0.0
            return {"date": iso, "weekday": WEEK[dd.weekday()], "weekend": dd.weekday() >= 5, "mark": self.marks.get(iso, ""), "record": d is not None,
                    "arrival": d["arrival"] if d else None, "leave": d["leave"] if d else None, "worked_s": w, "norm_s": full,
                    "delta_s": 0 if dd > now.date() or (today and w < full) else w - full, "break_s": self._break(d) if d else 0,
                    "lunch_s": self._lunch_s(d, now) if d else 0, "studio_s": self._studio_s(d) if d else 0, "today": today, "future": dd > now.date(),
                    "events": self._events(d, now) if d else []}

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

    def set_event_kind(self, iso, idx, kind):
        """Исправить тип уже закончившегося события: блокировка / пауза → «обед» (забыли нажать «Обед») или «студия» (ушли на запись) и обратно.
        На рабочее время это не влияет (блокировка и так не считается работой) — меняется, что видно в «Обед» и «Перерывы»."""
        with self._lock:
            if kind not in ("lock", "sleep", "lunch", "studio"):
                return {"error": "Неизвестный тип."}
            day = self.days.get(str(iso))
            if day is None or not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(day["events"]):
                return {"error": "Такого события нет."}
            ev = day["events"][idx]
            if ev["unlock"] is None:
                return {"error": "Это событие ещё идёт — дождитесь его окончания."}
            ev["kind"] = kind
            self._strip_inside_lunch(day)
            self.save()
            return {"ok": True}

    def delete_day(self, iso):
        with self._lock:
            if self.days.pop(str(iso), None) is not None:
                self.save()
            return {"ok": True}

    # ---------- таблица Excel ----------
    def export_xlsx(self, path, task_rows=None):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter
        with self._lock:
            ks = sorted(self.days)
            snap = {k: dict(self.days[k]) for k in ks}
        nowdt = datetime.fromtimestamp(self._clock())
        wb = Workbook()
        ws = wb.active
        ws.title = 'Учёт времени'
        head = ['Дата', 'День', 'Приход', 'Уход', 'Отработано', 'Перерывы', 'Обед', 'Норма', 'Разница, мин']
        ws.append(head)
        for k in ks:
            d = snap[k]
            dd = date.fromisoformat(k)
            a, l = to_sec(d["arrival"]), to_sec(d["leave"])
            ws.append([dd, WEEK[dd.weekday()],
                       datetime.min.time().replace(hour=a // 3600, minute=a % 3600 // 60) if a is not None else None,
                       datetime.min.time().replace(hour=l // 3600, minute=l % 3600 // 60) if l is not None else None,
                       d["worked"] / 86400, self._break(d) / 86400, self._lunch_s(d, nowdt) / 86400, d["norm"] / 86400,
                       round((d["worked"] - d["norm"]) / 60)])
        n = len(ks)
        ws.append(['Итого', None, None, None, f'=SUM(E2:E{n + 1})', f'=SUM(F2:F{n + 1})', f'=SUM(G2:G{n + 1})', f'=SUM(H2:H{n + 1})', f'=SUM(I2:I{n + 1})'])
        line = Side(style='thin', color='D0D5DD')
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='3B6CF6')
            c.alignment = Alignment(horizontal='center', vertical='center')
        for r in range(2, n + 3):
            ws.cell(r, 1).number_format = 'DD.MM.YYYY'
            for col in (3, 4):
                ws.cell(r, col).number_format = 'HH:MM'
            for col in (5, 6, 7, 8):
                ws.cell(r, col).number_format = '[h]:mm'
            ws.cell(r, 9).number_format = '+0;-0;0'
            for col in range(1, 10):
                ws.cell(r, col).border = Border(bottom=line)
                ws.cell(r, col).alignment = Alignment(horizontal='center')
        for c in ws[n + 2]:
            c.font = Font(bold=True)
        for i, w in enumerate([13, 7, 10, 10, 13, 12, 10, 10, 14], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = 'A2'
        ev = wb.create_sheet('Блокировки')
        ev.append(['День', 'Тип', 'Заблокирован', 'Разблокирован', 'Длительность'])
        for k in ks:
            for e in snap[k]["events"]:
                a, b = parse_dt(e["lock"]), parse_dt(e["unlock"])
                ev.append([date.fromisoformat(k), {'sleep': 'пауза', 'lunch': 'обед', 'studio': 'студия'}.get(e["kind"], 'блокировка'), a, b,
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
        if task_rows is not None:                        # лист «Задачи»: когда создана, начата, выполнена и сколько ушло
            tk = wb.create_sheet('Задачи')
            heads = ['Создана', 'Начата', 'Выполнена', 'Статус', 'Задача', 'Ушло, ч:мм', 'Ушло', 'Подзадачи', 'Комментарий', 'Файлы', 'Теги', 'Ждали ответа', 'Сейчас ждём']
            tk.append(heads)
            for c in tk[1]:
                c.font, c.fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='3B6CF6')
                c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            for r in task_rows:
                sub = '\n'.join(('✓ ' if d else '○ ') + t for t, d in r["subs"])
                el = r["elapsed_s"]
                tk.append([r["created"], r["started"], r["finished"], TASK_STATUS.get(r.get("state"), 'в работе') if not r.get("waiting_who") or r["done"] else 'ждём ответа', r["text"],
                           timedelta(seconds=el) if el is not None else None, fmt_dur(el) if el is not None else '', sub,
                           r["comment"], '\n'.join(r["files"]), ', '.join(r.get("tags") or []),
                           timedelta(seconds=r["wait_s"]) if r.get("wait_s") else None, r.get("waiting_who") or ''])
                row = tk.max_row
                for col in (1, 2, 3):
                    tk.cell(row, col).number_format = 'DD.MM.YYYY HH:MM'
                tk.cell(row, 6).number_format = '[h]:mm'
                tk.cell(row, 12).number_format = '[h]:mm'
                tk.cell(row, 4).font = Font(color='16A34A' if r["done"] else 'D97706', bold=True)
                for col in range(1, 14):
                    tk.cell(row, col).alignment = Alignment(wrap_text=col in (5, 8, 9, 10, 11), vertical='top',
                                                            horizontal='left' if col in (5, 8, 9, 10, 11) else 'center')
            for i, w in enumerate([17, 17, 17, 12, 46, 12, 16, 32, 40, 28, 22, 13, 16], 1):
                tk.column_dimensions[get_column_letter(i)].width = w
            tk.freeze_panes = 'A2'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        wb.save(path)
        return path
