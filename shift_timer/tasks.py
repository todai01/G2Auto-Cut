"""Задачи на день: пишете список, отмечаете галочкой. Невыполненные переходят на следующий день.

Хранилище — tasks.json рядом с журналом (атомарная запись). Часы подменяются в тестах.
"""
import json
import os
import threading
import time
from datetime import date, datetime

MAX_TEXT = 200
MAX_PER_DAY = 200


class TaskStore:
    def __init__(self, path, clock=time.time):
        self.path, self._clock = path, clock
        self._lock = threading.RLock()
        self.days = self._load()                         # {"2026-11-17": [{"id", "text", "done", "carried", "moved"}]}
        self._next = max([t["id"] for ts in self.days.values() for t in ts] + [0]) + 1

    # ---------- диск ----------
    def _load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                raw = json.load(f).get("days", {})
        except (OSError, ValueError, AttributeError):
            return {}
        out = {}
        for k, items in (raw.items() if isinstance(raw, dict) else []):
            try:
                date.fromisoformat(k)
            except ValueError:
                continue
            ts = []
            for t in items if isinstance(items, list) else []:
                if isinstance(t, dict) and isinstance(t.get("id"), int) and isinstance(t.get("text"), str) and t["text"].strip():
                    ts.append({"id": t["id"], "text": t["text"].strip()[:MAX_TEXT], "done": t.get("done") is True,
                               "carried": t.get("carried") is True, "moved": t.get("moved") is True})
            out[k] = ts
        return out

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({"days": self.days}, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)                   # не оставляем полузаписанный файл
        except OSError:
            pass

    # ---------- сегодняшний список ----------
    def _today_key(self):
        return datetime.fromtimestamp(self._clock()).date().isoformat()

    def _today(self):
        """Список на сегодня. Первый раз за день: невыполненные задачи прошлых дней переезжают сюда (в «вчера» остаются пометкой moved)."""
        key = self._today_key()
        if key not in self.days:
            carry = []
            for k in sorted(self.days):
                if k < key:
                    for t in self.days[k]:
                        if not t["done"] and not t["moved"]:
                            t["moved"] = True
                            carry.append({"id": t["id"], "text": t["text"], "done": False, "carried": True, "moved": False})
            self.days[key] = carry
            if carry:
                self._save()
        return self.days[key]

    def _view(self):
        ts = self._today()
        return {"tasks": [dict(t) for t in ts], "total": len(ts), "done": sum(1 for t in ts if t["done"])}

    def get(self):
        with self._lock:
            return self._view()

    def counts(self):
        with self._lock:
            ts = self._today()
            return {"total": len(ts), "done": sum(1 for t in ts if t["done"])}

    def add(self, text):
        with self._lock:
            text = str(text or '').strip()[:MAX_TEXT]
            ts = self._today()
            if text and len(ts) < MAX_PER_DAY:
                ts.append({"id": self._next, "text": text, "done": False, "carried": False, "moved": False})
                self._next += 1
                self._save()
            return self._view()

    def _find(self, tid):
        return next((t for t in self._today() if t["id"] == tid), None)

    def toggle(self, tid, done=None):
        with self._lock:
            t = self._find(tid)
            if t:
                t["done"] = (not t["done"]) if done is None else bool(done)
                self._save()
            return self._view()

    def edit(self, tid, text):
        with self._lock:
            t, text = self._find(tid), str(text or '').strip()[:MAX_TEXT]
            if t and text:
                t["text"] = text
                self._save()
            return self._view()

    def delete(self, tid):
        with self._lock:
            ts = self._today()
            n = len(ts)
            ts[:] = [t for t in ts if t["id"] != tid]
            if len(ts) != n:
                self._save()
            return self._view()

    def all_rows(self):
        """Все задачи по дням (для листа «Задачи» в Excel): день, текст, статус, пришла ли со вчера."""
        with self._lock:
            rows = []
            for k in sorted(self.days):
                for t in self.days[k]:
                    status = 'выполнена' if t["done"] else 'перенесена на следующий день' if t["moved"] else 'не выполнена'
                    rows.append({"date": k, "text": t["text"], "status": status, "carried": t["carried"]})
            return rows

    def clear_done(self):
        with self._lock:
            ts = self._today()
            ts[:] = [t for t in ts if not t["done"]]
            self._save()
            return self._view()
