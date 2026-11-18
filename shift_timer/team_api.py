"""Командный режим в Api: вход по учётке, отправка своих данных в сетевую папку, обзор команды для администратора.

Подмешивается в `app.Api` (методы без «_» видны из JS как pywebview.api.<имя>). Все методы возвращают словарь:
{"error": текст} при неудаче — исключения наружу не выходят.
"""
import json
import os
import tempfile
import threading
import time
from datetime import date, datetime, timedelta

import report
import tasks
import team
import timetrack

SYNC_EVERY = 30                                          # секунд между отправками снимка
STALE_S = 180                                            # снимок старше — считаем «нет связи»


def _safe(fn):
    """Ошибки командного режима — в {"error"}, чтобы JS показал понятный текст."""
    def wrap(self, *a, **kw):
        try:
            return fn(self, *a, **kw)
        except team.TeamError as e:
            return {"error": str(e)}
        except OSError as e:
            return {"error": f"Сетевая папка недоступна: {e.strerror or e}"}
    wrap.__name__ = fn.__name__
    wrap.__doc__ = fn.__doc__
    return wrap


def _iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%S')


class TeamMixin:
    def _team_init(self):
        self._user = None                                # {"login","name","role","must_change"} вошедшего
        self._team_store = None
        self._team_store_dir = None
        self._sync_at = 0.0
        self._sync_busy = False
        self._sync_state = {"ok": None, "at": None, "error": ""}
        self._auto_tried = False

    # ---------- хранилище и состояние ----------
    def _store(self):
        root = self._s.get("team_dir") or ''
        if not root:
            return None
        if self._team_store is None or self._team_store_dir != root:
            self._team_store, self._team_store_dir = team.TeamStore(root), root
        return self._team_store

    def _admin(self):
        if not self._user or self._user["role"] != 'admin':
            raise team.TeamError('Только для администратора.')
        st = self._store()
        if st is None:
            raise team.TeamError('Сетевая папка не выбрана.')
        return st

    def _viewer(self):
        """Просмотр команды (таблица, карточки, отчёт): администратор и супервайзер."""
        if not self._user or self._user["role"] not in ('admin', 'mentor'):
            raise team.TeamError('Только для администратора и супервайзера.')
        st = self._store()
        if st is None:
            raise team.TeamError('Сетевая папка не выбрана.')
        return st

    def _login_as(self, acct, remember=None):
        self._user = {"login": acct["login"], "name": acct["name"], "role": acct["role"], "must_change": acct["must_change"]}
        if remember is not None:
            self.save_settings({"team_login": acct["login"] if remember else ''})
        self._sync_at = 0.0
        self._team_sync(force=True)

    def team_status(self):
        st = self._store()
        d = {"enabled": st is not None, "dir": self._s.get("team_dir") or '', "reachable": bool(st and st.available()), "user": self._user,
             "need_admin": False, "sync": dict(self._sync_state)}
        if d["reachable"]:
            try:
                if self._user is None and not self._auto_tried and self._s.get("team_login"):
                    self._auto_tried = True
                    a = st.get(self._s["team_login"])
                    if a and a.get("active", True) is True and a.get("must_change") is not True:
                        self._login_as(st._public(a))
                        d["user"] = self._user
                d["need_admin"] = not st.has_admin()
            except (team.TeamError, OSError):
                d["reachable"] = False
        return d

    # ---------- подключение и вход ----------
    def _dialog_dir(self):
        return self._dialog('FOLDER')

    @_safe
    def team_pick_dir(self):
        p = self._dialog_dir()
        return {"cancelled": True} if not p else self.team_set_dir(p)

    @_safe
    def team_set_dir(self, path):
        path = str(path or '').strip().strip('"')
        if path and not os.path.isdir(path):
            return {"error": "Папка не найдена или нет доступа."}
        if path != (self._s.get("team_dir") or ''):
            self._user = None
            self._auto_tried = True
            self.save_settings({"team_dir": path, "team_login": ''})
        return self.team_status()

    @_safe
    def team_setup_admin(self, login, name, password):
        """Первый вход в пустую папку: создать администратора."""
        st = self._store()
        if st is None or not st.available():
            raise team.TeamError('Сетевая папка недоступна.')
        if st.has_admin():
            raise team.TeamError('Администратор уже есть — войдите под своей учёткой.')
        st._check_new(team.norm_login(login), password)
        acct = st.create(login, name, password, role='admin', must_change=False)
        self._login_as(acct, remember=True)
        return {"ok": True, **self.team_status()}

    @_safe
    def team_login(self, login, password, remember=True):
        st = self._store()
        if st is None:
            raise team.TeamError('Сетевая папка не выбрана.')
        acct = st.verify(login, password)
        self._login_as(acct, remember=bool(remember) and not acct["must_change"])
        return {"ok": True, **self.team_status()}

    @_safe
    def team_change_password(self, old, new):
        if not self._user:
            raise team.TeamError('Сначала войдите.')
        st = self._store()
        st.change_password(self._user["login"], old, new)
        self._user["must_change"] = False
        self.save_settings({"team_login": self._user["login"]})
        return {"ok": True, **self.team_status()}

    def team_logout(self):
        if self._user:
            self._team_sync_now(final=True)
        self._user = None
        self._auto_tried = True
        self.save_settings({"team_login": ''})
        return self.team_status()

    # ---------- отправка своих данных ----------
    def _team_snapshot(self, final=False):
        u = self._user
        snap = self._t.snapshot()
        with self._t._lock:
            days = json.loads(json.dumps({k: self._t.days[k] for k in sorted(self._t.days)[-120:]}))
            marks = dict(self._t.marks)
        with self._tasks._lock:
            items = json.loads(json.dumps(self._tasks.items[-1000:]))
        state = 'left' if final else 'locked' if snap["locked"] else 'lunch' if snap["lunch"]["on"] else 'work'
        return {"v": 1, "login": u["login"], "name": u["name"], "role": u["role"], "updated": _iso(datetime.now()), "today": snap["date"],
                "state": state, "norm_s": snap["norm_s"], "days": days, "marks": marks, "tasks": items}

    def _team_sync(self, force=False):
        """Из тика: не чаще раза в SYNC_EVERY секунд, в отдельном потоке (сеть не должна тормозить учёт)."""
        if not self._user or self._sync_busy or (not force and time.monotonic() - self._sync_at < SYNC_EVERY):
            return
        self._sync_at, self._sync_busy = time.monotonic(), True
        threading.Thread(target=self._team_sync_now, daemon=True).start()

    def _team_sync_now(self, final=False):
        st = self._store()
        try:
            if self._user is None or st is None:
                return
            a = st.get(self._user["login"])
            if not a or a.get("active", True) is not True:           # учётку удалили или отключили
                self._user = None
                self._push_team()
                return
            st.write_snapshot(self._user["login"], self._team_snapshot(final))
            self._sync_state = {"ok": True, "at": _iso(datetime.now()), "error": ""}
        except (team.TeamError, OSError) as e:
            self._sync_state = {"ok": False, "at": self._sync_state.get("at"), "error": str(e)}
        finally:
            self._sync_busy = False

    def _push_team(self):
        for w in (self._main,):
            if w is not None:
                try:
                    w.evaluate_js("window.teamChanged && window.teamChanged()")
                except Exception:
                    pass

    # ---------- чужие данные как «обычный» журнал ----------
    @staticmethod
    def _remote(snap):
        """Снимок сотрудника → Tracker и TaskStore только для чтения (те же сводки, календарь и отчёты, что и у себя)."""
        tmp = os.path.join(tempfile.gettempdir(), 'gtime_remote_unused.json')
        tr = timetrack.Tracker(tmp, int(snap.get("norm_s") or 8 * 3600))
        days = {}
        for k, d in (snap.get("days") or {}).items():
            try:
                date.fromisoformat(k)
                days[k] = {"arrival": d.get("arrival") if timetrack.to_sec(d.get("arrival")) is not None else None,
                           "leave": d.get("leave") if timetrack.to_sec(d.get("leave")) is not None else None,
                           "worked": max(0.0, float(d.get("worked", 0))), "norm": int(d.get("norm", tr.norm_s)),
                           "events": [e for e in (d.get("events") or []) if isinstance(e, dict) and e.get("lock") and e.get("kind") in ("lock", "sleep", "lunch")],
                           "notified": [], "no_break": False}
            except (ValueError, TypeError, AttributeError):
                continue
        tr.days = days
        tr.marks = {k: v for k, v in (snap.get("marks") or {}).items() if v in timetrack.MARKS}
        st = tasks.TaskStore(tmp + '.tasks')
        st.items = [n for n in (st._norm(t) for t in (snap.get("tasks") or [])) if n]
        return tr, st

    @staticmethod
    def _summary_for(tr, st, kind, iso):
        kind = 'month' if kind == 'month' else 'week'
        a, b = report.period(kind, iso)
        s = tr.summary(a, b)
        rows = st.rows_between(a, b)
        s["kind"], s["label"] = kind, report.label(kind, a, b)
        s["tasks"] = {"created": sum(1 for r in rows if a <= r["created"].date() <= b),
                      "done": sum(1 for r in rows if r["done"] and r["finished"] and a <= r["finished"].date() <= b),
                      "work": sum(1 for r in rows if not r["done"]),
                      "by_tag": {g: {"n": v["n"], "done": v["done"], "sec": v["sec"]} for g, v in report.tag_stats(rows).items() if v["n"]}}
        return s, rows

    # ---------- администратор ----------
    @_safe
    def team_overview(self, iso=None):
        """Таблица команды за день: кто во сколько пришёл, кто сейчас в работе, на обеде, в блокировке."""
        st = self._viewer()
        today = self._today_iso()
        iso = iso or today
        now = datetime.now()
        rows = []
        for a in st.list():
            snap = st.read_snapshot(a["login"])
            row = {**a, "arrival": None, "leave": None, "worked_s": 0, "norm_s": 0, "mark": '', "state": 'nodata', "updated": None, "tasks_open": 0, "tasks_done": 0}
            if snap:
                days, marks = snap.get("days") or {}, snap.get("marks") or {}
                d = days.get(iso) or {}
                dd = date.fromisoformat(iso)
                row.update(arrival=d.get("arrival"), leave=d.get("leave"), worked_s=float(d.get("worked", 0) or 0), mark=marks.get(iso, ''), updated=snap.get("updated"))
                row["norm_s"] = 0 if (row["mark"] or dd.weekday() >= 5) else int(d.get("norm") or snap.get("norm_s") or 8 * 3600)
                items = [t for t in snap.get("tasks") or [] if isinstance(t, dict) and not t.get("hidden")]
                row["tasks_open"] = sum(1 for t in items if not t.get("done"))
                row["tasks_done"] = sum(1 for t in items if t.get("done") and str(t.get("finished") or '').startswith(iso))
                upd = None
                try:
                    upd = datetime.fromisoformat(snap.get("updated") or '')
                except ValueError:
                    pass
                if iso == today:
                    if row["mark"]:
                        row["state"] = 'mark'
                    elif not row["arrival"]:
                        row["state"] = 'weekend' if dd.weekday() >= 5 else 'absent'
                    elif snap.get("state") == 'left':
                        row["state"] = 'left'
                    elif upd is None or (now - upd).total_seconds() > STALE_S:
                        row["state"] = 'offline'
                    else:
                        row["state"] = snap.get("state") or 'work'
                else:
                    row["state"] = 'mark' if row["mark"] else 'came' if row["arrival"] else 'weekend' if dd.weekday() >= 5 else 'absent'
            rows.append(row)
        rows.sort(key=lambda r: (not r["active"], r["name"].lower()))
        return {"date": iso, "today": today, "rows": rows}

    @_safe
    def team_user(self, login, kind='week', iso=None):
        """Карточка сотрудника: сводка недели / месяца, дни месяца и задачи периода (с комментариями и подзадачами)."""
        st = self._viewer()
        a = st.get(login)
        snap = st.read_snapshot(login) if a else None
        if not a:
            raise team.TeamError('Учётки нет.')
        if not snap:
            return {"login": a["login"], "name": a.get("name"), "nodata": True}
        tr, store = self._remote(snap)
        iso = iso or self._today_iso()
        s, rows = self._summary_for(tr, store, kind, iso)
        by_day = [{"date": d["date"], "weekday": d["weekday"], "arrival": d["arrival"], "leave": d["leave"], "worked_s": d["worked_s"], "norm_s": d["norm_s"],
                   "mark": d["mark"], "weekend": d["weekend"], "future": d["future"]} for d in s.pop("by_day")]
        out_rows = []
        for r in sorted(rows, key=lambda r: (r["done"], r["created"])):
            out_rows.append({"id": r["id"], "text": r["text"], "done": r["done"], "created": _iso(r["created"]), "finished": _iso(r["finished"]) if r["finished"] else None,
                             "state": r["state"], "elapsed_s": r["elapsed_s"], "period_s": r["period_s"], "tags": r["tags"], "wait_s": r["wait_s"], "waiting_who": r["waiting_who"],
                             "subs": [{"text": t, "done": d} for t, d in r["subs"]], "comment": r["comment"], "files": r["files"]})
        return {"login": a["login"], "name": a.get("name"), "updated": snap.get("updated"), "summary": s, "days": by_day, "tasks": out_rows}

    @_safe
    def team_accounts(self):
        return {"accounts": self._admin().list(), "me": self._user["login"]}

    @_safe
    def team_account_create(self, login, name, password, role='user'):
        st = self._admin()
        st.create(login, name, password, role=role, must_change=True)
        return {"ok": True, "accounts": st.list(), "me": self._user["login"]}

    @_safe
    def team_account_reset(self, login, password):
        st = self._admin()
        st.reset_password(login, password, must_change=True)
        return {"ok": True, "accounts": st.list(), "me": self._user["login"]}

    @_safe
    def team_account_active(self, login, on):
        st = self._admin()
        if not on and team.norm_login(login) == self._user["login"]:
            raise team.TeamError('Себя отключить нельзя.')
        st.set_active(login, bool(on))
        return {"ok": True, "accounts": st.list(), "me": self._user["login"]}

    @_safe
    def team_account_role(self, login, role):
        st = self._admin()
        if team.norm_login(login) == self._user["login"] and role != 'admin':
            raise team.TeamError('Снять роль администратора у себя нельзя.')
        st.set_role(login, role)
        return {"ok": True, "accounts": st.list(), "me": self._user["login"]}

    @_safe
    def team_account_name(self, login, name):
        st = self._admin()
        st.set_name(login, name)
        return {"ok": True, "accounts": st.list(), "me": self._user["login"]}

    @_safe
    def team_report(self, kind='week', iso=None):
        """Отчёт команды одним Excel: сводка по людям, приход и уход по дням, задачи всех."""
        st = self._viewer()
        kind = 'month' if kind == 'month' else 'week'
        a, b = report.period(kind, iso or self._today_iso())
        members = []
        for acc in st.list():
            snap = st.read_snapshot(acc["login"]) if acc["active"] else None
            if not snap:
                continue
            tr, store = self._remote(snap)
            members.append({"name": acc["name"], "login": acc["login"], "summary": tr.summary(a, b), "rows": store.rows_between(a, b)})
        if not members:
            raise team.TeamError('Данных сотрудников пока нет.')
        path = os.path.join(self._reports or self._reports_dir(), f'Отчёт_команды_{"неделя" if kind == "week" else "месяц"}_{a.isoformat()}.xlsx')
        try:
            report.export_team(path, kind, a, b, members)
        except PermissionError:
            return {"error": "Файл отчёта открыт в Excel — закройте его и повторите."}
        try:
            os.startfile(path)                           # только Windows
        except (AttributeError, OSError):
            pass
        return {"path": path, "people": len(members)}
