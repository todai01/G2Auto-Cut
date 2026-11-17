"""Задачи: одна задача живёт, пока её не выполнят (а не по дням), и считает, сколько времени на неё ушло.

У задачи: время создания, время начала (с него идёт секундомер), время выполнения (час и минута), комментарий, подзадачи
и вложенные файлы. Выполненные скрываются в списке после полуночи, но остаются в Excel («Задачи»).
Хранилище — tasks.json рядом с журналом (атомарная запись); файлы — папка task_files/<id>/. Часы подменяются в тестах.
"""
import json
import os
import shutil
import threading
import time
from datetime import date, datetime

MAX_TEXT = 200
MAX_PER_DAY = 200                                        # не больше столько задач за раз в списке (невыполненные + сегодняшние)
MAX_COMMENT = 8000
MAX_SUBS = 50
MAX_FILES = 25
MAX_FILE_MB = 200
FMT = '%Y-%m-%dT%H:%M:%S'


def _dt(s):
    try:
        return datetime.fromisoformat(s) if isinstance(s, str) else None
    except ValueError:
        return None


def _iso(d):
    return d.strftime(FMT)


def fmt_dur(sec):
    """Сколько прошло: до суток — «10:30:12», дальше — «1 д 10 ч 30 мин» (нулевые части пропускаются: «1 д 5 мин»)."""
    sec = int(max(0, sec))
    if sec < 86400:
        return f'{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}'
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return ' '.join([f'{d} д'] + ([f'{h} ч'] if h else []) + ([f'{m} мин'] if m else []))


def _clean_name(name):
    name = os.path.basename(str(name or '')).strip().strip('.')
    return ''.join('_' if c in '\\/:*?"<>|' or ord(c) < 32 else c for c in name)[:120] or 'файл'


class TaskStore:
    def __init__(self, path, clock=time.time, files_dir=None):
        self.path, self._clock = path, clock
        self.files_dir = files_dir or os.path.join(os.path.dirname(path) or '.', 'task_files')
        self._lock = threading.RLock()
        self.items = self._load()
        self._next = max([t["id"] for t in self.items] + [0]) + 1

    # ---------- диск ----------
    @staticmethod
    def _norm(t, legacy=False):
        """Одна задача из файла → полная запись с проверенными полями (или None, если это не задача)."""
        if not (isinstance(t, dict) and isinstance(t.get("id"), int) and isinstance(t.get("text"), str) and t["text"].strip()):
            return None
        created = _dt(t.get("created"))
        if created is None:
            return None
        started = _dt(t.get("started")) or created
        done = t.get("done") is True
        finished = _dt(t.get("finished")) if done else None
        if done and finished is None:
            finished = started
        subs = []
        for s in t.get("subs") if isinstance(t.get("subs"), list) else []:
            if isinstance(s, dict) and isinstance(s.get("id"), int) and isinstance(s.get("text"), str) and s["text"].strip():
                subs.append({"id": s["id"], "text": s["text"].strip()[:MAX_TEXT], "done": s.get("done") is True})
        files = [f for f in (t.get("files") if isinstance(t.get("files"), list) else []) if isinstance(f, str) and f]
        return {"id": t["id"], "text": t["text"].strip()[:MAX_TEXT], "created": _iso(created), "started": _iso(started),
                "finished": _iso(finished) if finished else None, "done": done, "hidden": t.get("hidden") is True,
                "comment": str(t.get("comment") or '')[:MAX_COMMENT], "subs": subs, "files": files,
                "legacy": legacy or t.get("legacy") is True}

    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(raw, dict):
            return []
        if isinstance(raw.get("tasks"), list):
            out, seen = [], set()
            for t in raw["tasks"]:
                n = self._norm(t)
                if n and n["id"] not in seen:
                    seen.add(n["id"])
                    out.append(n)
            return out
        return self._migrate(raw.get("days"))

    def _migrate(self, days):
        """Старый формат (списки по дням, «со вчера»): каждая задача — одна запись, создана в первый день, где встретилась."""
        if not isinstance(days, dict):
            return []
        by_id = {}
        for k in sorted(days):
            try:
                day = date.fromisoformat(k)
            except ValueError:
                continue
            for t in days[k] if isinstance(days[k], list) else []:
                if not (isinstance(t, dict) and isinstance(t.get("id"), int) and isinstance(t.get("text"), str) and t["text"].strip()):
                    continue
                cur = by_id.get(t["id"])
                if cur is None:
                    by_id[t["id"]] = {"id": t["id"], "text": t["text"], "created": f'{day.isoformat()}T09:00:00', "done": t.get("done") is True}
                elif not t.get("moved"):
                    cur["done"], cur["text"] = t.get("done") is True, t["text"]
        out = [self._norm(t, legacy=True) for t in by_id.values()]
        return [t for t in out if t]

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({"v": 2, "tasks": self.items}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)                   # не оставляем полузаписанный файл
        except OSError:
            pass

    # ---------- показ ----------
    def _now(self):
        return datetime.fromtimestamp(self._clock()).replace(microsecond=0)

    def _visible(self, t):
        """В списке: невыполненные всегда; выполненные — только в день выполнения (после полуночи скрываются)."""
        if t["hidden"]:
            return False
        if not t["done"]:
            return True
        fin = _dt(t["finished"])
        return fin is not None and fin.date() == self._now().date()

    def _elapsed(self, t, now=None):
        start = _dt(t["started"])
        end = _dt(t["finished"]) if t["done"] else (now or self._now())
        return max(0, int((end - start).total_seconds())) if start and end else 0

    def _out(self, t, now):
        d = dict(t)
        d["subs"] = [dict(s) for s in t["subs"]]
        d["files"] = list(t["files"])
        d["elapsed_s"] = self._elapsed(t, now)
        d["running"] = not t["done"]
        return d

    def _view(self):
        now = self._now()
        ts = [t for t in self.items if self._visible(t)]
        ts.sort(key=lambda t: (t["done"], t["created"]))
        return {"tasks": [self._out(t, now) for t in ts[:MAX_PER_DAY]], "total": len(ts), "done": sum(1 for t in ts if t["done"])}

    def get(self):
        with self._lock:
            return self._view()

    def counts(self):
        with self._lock:
            ts = [t for t in self.items if self._visible(t)]
            return {"total": len(ts), "done": sum(1 for t in ts if t["done"])}

    # ---------- действия ----------
    def _find(self, tid):
        return next((t for t in self.items if t["id"] == tid), None)

    def add(self, text):
        with self._lock:
            text = str(text or '').strip()[:MAX_TEXT]
            if text and sum(1 for t in self.items if self._visible(t)) < MAX_PER_DAY:
                now = _iso(self._now())
                self.items.append({"id": self._next, "text": text, "created": now, "started": now, "finished": None, "done": False,
                                   "hidden": False, "comment": "", "subs": [], "files": [], "legacy": False})
                self._next += 1
                self._save()
            return self._view()

    def toggle(self, tid, done=None):
        """Галочка «Выполнено»: фиксирует час и минуту выполнения; снять — задача снова в работе (секундомер идёт дальше)."""
        with self._lock:
            t = self._find(tid)
            if t:
                want = (not t["done"]) if done is None else bool(done)
                if want != t["done"]:
                    t["done"] = want
                    t["finished"] = _iso(self._now()) if want else None
                    t["legacy"] = False if want else t["legacy"]
                    self._save()
            return self._view()

    def edit(self, tid, text):
        with self._lock:
            t, text = self._find(tid), str(text or '').strip()[:MAX_TEXT]
            if t and text:
                t["text"] = text
                self._save()
            return self._view()

    def set_times(self, tid, created, started=None, finished=None):
        """Правка времён: когда создана, с какого времени идёт, когда закончена (минуты — «ГГГГ-ММ-ДДTЧЧ:ММ»).
        Возвращает {"ok": True, ...вид} или {"error": текст}."""
        with self._lock:
            t = self._find(tid)
            if not t:
                return {"error": "Задача не найдена."}
            c, s = _dt(created), _dt(started) if started else None
            f = _dt(finished) if finished else None
            if c is None:
                return {"error": "Укажите, когда задача создана."}
            if started and s is None or finished and f is None:
                return {"error": "Время — в формате ДД.ММ.ГГГГ ЧЧ:ММ."}
            s = s or c
            now = self._now()
            if t["done"] and f is None:
                return {"error": "Укажите, когда задача выполнена (или снимите галочку)."}
            if not t["done"]:
                f = None
            for name, v in (("Создана", c), ("Начата", s), ("Выполнена", f)):
                if v and v > now.replace(second=59):
                    return {"error": f"{name}: это время ещё не наступило."}
            if f and f < s:
                return {"error": "Выполнена раньше, чем начата."}
            t["created"], t["started"] = _iso(c), _iso(s)
            t["finished"] = _iso(f) if f else None
            t["legacy"] = False
            self._save()
            return {"ok": True, **self._view()}

    def set_comment(self, tid, text):
        with self._lock:
            t = self._find(tid)
            if t:
                t["comment"] = str(text or '')[:MAX_COMMENT]
                self._save()
            return self._view()

    def delete(self, tid):
        with self._lock:
            n = len(self.items)
            self.items = [t for t in self.items if t["id"] != tid]
            if len(self.items) != n:
                shutil.rmtree(self._dir(tid), ignore_errors=True)
                self._save()
            return self._view()

    def clear_done(self):
        """«Убрать выполненные»: скрыть из списка (в Excel остаются)."""
        with self._lock:
            for t in self.items:
                if t["done"]:
                    t["hidden"] = True
            self._save()
            return self._view()

    # ---------- подзадачи ----------
    def sub_add(self, tid, text):
        with self._lock:
            t, text = self._find(tid), str(text or '').strip()[:MAX_TEXT]
            if t and text and len(t["subs"]) < MAX_SUBS:
                t["subs"].append({"id": max([s["id"] for s in t["subs"]] + [0]) + 1, "text": text, "done": False})
                self._save()
            return self._view()

    def sub_toggle(self, tid, sid):
        with self._lock:
            t = self._find(tid)
            s = next((s for s in t["subs"] if s["id"] == sid), None) if t else None
            if s:
                s["done"] = not s["done"]
                self._save()
            return self._view()

    def sub_delete(self, tid, sid):
        with self._lock:
            t = self._find(tid)
            if t:
                n = len(t["subs"])
                t["subs"] = [s for s in t["subs"] if s["id"] != sid]
                if len(t["subs"]) != n:
                    self._save()
            return self._view()

    # ---------- файлы ----------
    def _dir(self, tid):
        return os.path.join(self.files_dir, str(int(tid)))

    def attach(self, tid, paths):
        """Копии файлов — в папку задачи (оригиналы не трогаем). Одинаковое имя — «имя (2).ext». Возвращает {"added": N, "skipped": [...], ...вид}."""
        with self._lock:
            t = self._find(tid)
            added, skipped = 0, []
            for p in paths if t else []:
                try:
                    if not os.path.isfile(p):
                        skipped.append(f'{os.path.basename(str(p))}: не файл')
                        continue
                    if len(t["files"]) >= MAX_FILES:
                        skipped.append(f'{os.path.basename(p)}: не больше {MAX_FILES} файлов')
                        continue
                    if os.path.getsize(p) > MAX_FILE_MB * 1024 * 1024:
                        skipped.append(f'{os.path.basename(p)}: больше {MAX_FILE_MB} МБ')
                        continue
                    os.makedirs(self._dir(tid), exist_ok=True)
                    stem, ext = os.path.splitext(_clean_name(p))
                    name, k = stem + ext, 2
                    while name.lower() in {f.lower() for f in t["files"]} or os.path.exists(os.path.join(self._dir(tid), name)):
                        name, k = f'{stem} ({k}){ext}', k + 1
                    shutil.copy2(p, os.path.join(self._dir(tid), name))
                    t["files"].append(name)
                    added += 1
                except OSError as e:
                    skipped.append(f'{os.path.basename(str(p))}: {e.strerror or e}')
            if added:
                self._save()
            return {"added": added, "skipped": skipped, **self._view()}

    def attach_bytes(self, tid, name, data):
        """Вложение из памяти (скриншот из буфера обмена): байты → файл с этим именем → обычное прикрепление."""
        import tempfile
        if not isinstance(data, (bytes, bytearray)) or not data:
            return {"added": 0, "skipped": ["пустой файл"], **self.get()}
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, _clean_name(name))
            with open(p, 'wb') as f:
                f.write(data)
            return self.attach(tid, [p])

    def file_path(self, tid, name):
        """Полный путь вложения (только то, что записано у задачи), иначе None."""
        with self._lock:
            t = self._find(tid)
            if not t or name not in t["files"]:
                return None
            p = os.path.join(self._dir(tid), name)
            return p if os.path.isfile(p) else None

    def remove_file(self, tid, name):
        with self._lock:
            t = self._find(tid)
            if t and name in t["files"]:
                t["files"].remove(name)
                try:
                    os.remove(os.path.join(self._dir(tid), name))
                except OSError:
                    pass
                self._save()
            return self._view()

    # ---------- Excel ----------
    def all_rows(self):
        """Все задачи (в том числе скрытые) для листа «Задачи»: когда создана / начата / выполнена, сколько ушло, подзадачи, комментарий."""
        with self._lock:
            now = self._now()
            rows = []
            for t in sorted(self.items, key=lambda t: (t["created"], t["id"])):
                legacy = t["legacy"]
                rows.append({"created": _dt(t["created"]), "started": _dt(t["started"]), "finished": None if legacy else _dt(t["finished"]),
                             "done": t["done"], "text": t["text"], "elapsed_s": None if legacy and t["done"] else self._elapsed(t, now),
                             "subs": [(s["text"], s["done"]) for s in t["subs"]], "comment": t["comment"], "files": list(t["files"]),
                             "legacy": legacy})
            return rows
