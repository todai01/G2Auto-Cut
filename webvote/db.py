"""Аккаунты, сессии и выбор вариантов — SQLite (стандартная библиотека), один файл рядом с данными."""
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time

ROLES = ('user', 'admin')
SESSION_TTL = 12 * 3600               # сессия живёт 12 часов с последнего действия
LOCK_TTL = 120                        # «имя занято» — столько секунд без обновления
PBKDF2_ROUNDS = 200_000
MIN_PASSWORD = 6
LOGIN_FAILS, LOGIN_PAUSE = 5, 30      # 5 неверных паролей подряд — пауза 30 с (на логин + адрес)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, login TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL DEFAULT 'user', salt BLOB NOT NULL, hash BLOB NOT NULL, must_change INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, last_login REAL);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash BLOB PRIMARY KEY, user_id INTEGER NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, ip TEXT);
CREATE TABLE IF NOT EXISTS choices(
  idx INTEGER PRIMARY KEY, variant INTEGER, a INTEGER, b INTEGER, user_id INTEGER, ts REAL,
  flag INTEGER NOT NULL DEFAULT 0, comment TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS locks(idx INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY, ts REAL NOT NULL, user_id INTEGER, action TEXT NOT NULL, idx INTEGER, data TEXT);
"""


class AuthError(Exception):
    """Понятная пользователю причина отказа (показывается как есть)."""

    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.code = code


def _hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ROUNDS)


class Store:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.fails = {}                          # (логин, адрес) → [число, до какого времени пауза]
        with self.lock:
            self.db.executescript(SCHEMA)
            self.db.execute("PRAGMA journal_mode=WAL")

    def q(self, sql, *args):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def one(self, sql, *args):
        r = self.q(sql, *args)
        return r[0] if r else None

    def run(self, sql, *args):
        with self.lock:
            return self.db.execute(sql, args)

    def log(self, user_id, action, idx=None, data=None):
        self.run("INSERT INTO log(ts,user_id,action,idx,data) VALUES(?,?,?,?,?)", time.time(), user_id, action, idx, data)

    # ---------- пользователи ----------
    @staticmethod
    def check_password(login, password):
        if len(password or '') < MIN_PASSWORD:
            raise AuthError(f"Пароль — от {MIN_PASSWORD} знаков.")
        if password.strip().lower() == (login or '').strip().lower():
            raise AuthError("Пароль не должен совпадать с логином.")

    def users_count(self):
        return self.one("SELECT COUNT(*) c FROM users")["c"]

    def public(self, u):
        return {"id": u["id"], "login": u["login"], "name": u["name"] or u["login"], "role": u["role"],
                "must_change": bool(u["must_change"]), "active": bool(u["active"]),
                "last_login": u["last_login"]}

    def create_user(self, login, name, password, role='user', must_change=True):
        login = (login or '').strip()
        if not login or len(login) > 40 or any(c.isspace() for c in login):
            raise AuthError("Логин — без пробелов, до 40 знаков.")
        if role not in ROLES:
            raise AuthError("Неизвестная роль.")
        self.check_password(login, password)
        if self.one("SELECT 1 FROM users WHERE login=?", login):
            raise AuthError("Такой логин уже есть.", 409)
        salt = secrets.token_bytes(16)
        cur = self.run("INSERT INTO users(login,name,role,salt,hash,must_change,created) VALUES(?,?,?,?,?,?,?)",
                       login, (name or '').strip()[:80], role, salt, _hash(password, salt), int(must_change), time.time())
        return self.one("SELECT * FROM users WHERE id=?", cur.lastrowid)

    def set_password(self, user_id, password, must_change=False):
        u = self.one("SELECT * FROM users WHERE id=?", user_id)
        self.check_password(u["login"], password)
        salt = secrets.token_bytes(16)
        self.run("UPDATE users SET salt=?, hash=?, must_change=? WHERE id=?", salt, _hash(password, salt), int(must_change), user_id)
        self.run("DELETE FROM sessions WHERE user_id=?", user_id)           # старые сессии — прочь

    def admins_left(self, without=None):
        return self.one("SELECT COUNT(*) c FROM users WHERE role='admin' AND active=1 AND id IS NOT ?", without)["c"]

    def update_user(self, actor_id, user_id, **kw):
        u = self.one("SELECT * FROM users WHERE id=?", user_id)
        if not u:
            raise AuthError("Нет такого пользователя.", 404)
        role = kw.get("role", u["role"])
        active = int(kw.get("active", u["active"]))
        if role not in ROLES:
            raise AuthError("Неизвестная роль.")
        if (role != 'admin' or not active) and u["role"] == 'admin' and u["active"] and self.admins_left(user_id) == 0:
            raise AuthError("Нельзя отключить или разжаловать последнего администратора.", 409)
        if user_id == actor_id and (role != u["role"] or not active):
            raise AuthError("Себя разжаловать или отключить нельзя.", 409)
        self.run("UPDATE users SET role=?, active=?, name=? WHERE id=?", role, active,
                 (kw.get("name", u["name"]) or '').strip()[:80], user_id)
        if not active:
            self.run("DELETE FROM sessions WHERE user_id=?", user_id)
        if kw.get("password"):
            self.set_password(user_id, kw["password"], must_change=True)
        return self.one("SELECT * FROM users WHERE id=?", user_id)

    # ---------- вход ----------
    def login(self, login, password, ip=''):
        key = ((login or '').strip().lower(), ip)
        f = self.fails.get(key)
        if f and f[1] > time.time():
            raise AuthError(f"Слишком много попыток. Подождите {int(f[1] - time.time()) + 1} с.", 429)
        u = self.one("SELECT * FROM users WHERE login=?", (login or '').strip())
        ok = False
        if u and u["active"]:
            ok = hmac.compare_digest(_hash(password or '', u["salt"]), u["hash"])
        else:
            _hash(password or '', b'0' * 16)                                # одинаковое время ответа
        if not ok:
            n = (f[0] if f else 0) + 1
            self.fails[key] = [n, time.time() + LOGIN_PAUSE if n >= LOGIN_FAILS else 0]
            if n >= LOGIN_FAILS:
                self.fails[key][0] = 0
            raise AuthError("Неверный логин или пароль.", 401)
        self.fails.pop(key, None)
        token = secrets.token_urlsafe(32)
        now = time.time()
        self.run("INSERT INTO sessions(token_hash,user_id,created,expires,ip) VALUES(?,?,?,?,?)",
                 hashlib.sha256(token.encode()).digest(), u["id"], now, now + SESSION_TTL, ip)
        self.run("UPDATE users SET last_login=? WHERE id=?", now, u["id"])
        self.run("DELETE FROM sessions WHERE expires<?", now)
        self.log(u["id"], 'login')
        return token, u

    def user_by_token(self, token):
        if not token:
            return None
        h = hashlib.sha256(token.encode()).digest()
        s = self.one("SELECT * FROM sessions WHERE token_hash=?", h)
        if not s or s["expires"] < time.time():
            return None
        u = self.one("SELECT * FROM users WHERE id=?", s["user_id"])
        if not u or not u["active"]:
            return None
        if s["expires"] - time.time() < SESSION_TTL - 300:                  # скользящая сессия
            self.run("UPDATE sessions SET expires=? WHERE token_hash=?", time.time() + SESSION_TTL, h)
        return u

    def logout(self, token):
        if token:
            self.run("DELETE FROM sessions WHERE token_hash=?", hashlib.sha256(token.encode()).digest())

    # ---------- выбор вариантов ----------
    def lock_state(self, idx, user_id):
        """Кто сейчас на этом имени (не считая user_id): (id, имя) или None."""
        r = self.one("SELECT l.user_id, u.name, u.login FROM locks l JOIN users u ON u.id=l.user_id WHERE l.idx=? AND l.ts>? AND l.user_id!=?",
                     idx, time.time() - LOCK_TTL, user_id)
        return (r["user_id"], r["name"] or r["login"]) if r else None

    def touch_lock(self, idx, user_id):
        other = self.lock_state(idx, user_id)
        if other:
            return other
        self.run("DELETE FROM locks WHERE user_id=? AND idx!=?", user_id, idx)       # у человека — одно имя за раз
        self.run("INSERT INTO locks(idx,user_id,ts) VALUES(?,?,?) ON CONFLICT(idx) DO UPDATE SET user_id=excluded.user_id, ts=excluded.ts",
                 idx, user_id, time.time())
        return None

    def release_lock(self, idx, user_id):
        self.run("DELETE FROM locks WHERE idx=? AND user_id=?", idx, user_id)

    def choose(self, user, idx, variant, a, b):
        other = self.lock_state(idx, user["id"])
        if other:
            raise AuthError(f"Это имя сейчас слушает {other[1]}.", 409)
        cur = self.one("SELECT * FROM choices WHERE idx=?", idx)
        if cur and cur["variant"] and cur["user_id"] not in (None, user["id"]) and user["role"] != 'admin':
            raise AuthError("Это имя уже выбрал другой сотрудник — менять может администратор.", 403)
        flag = cur["flag"] if cur else 0
        self.run("INSERT INTO choices(idx,variant,a,b,user_id,ts,flag,comment) VALUES(?,?,?,?,?,?,0,'') "
                 "ON CONFLICT(idx) DO UPDATE SET variant=excluded.variant, a=excluded.a, b=excluded.b, user_id=excluded.user_id, ts=excluded.ts, flag=0, comment=''",
                 idx, variant, a, b, user["id"], time.time())
        self.release_lock(idx, user["id"])
        self.log(user["id"], 'choose', idx, f"{variant}:{a}:{b}" + (" (снята пометка)" if flag else ""))

    def unchoose(self, user, idx):
        cur = self.one("SELECT * FROM choices WHERE idx=?", idx)
        if cur and cur["user_id"] not in (None, user["id"]) and user["role"] != 'admin':
            raise AuthError("Выбор другого сотрудника снимает только администратор.", 403)
        self.run("DELETE FROM choices WHERE idx=?", idx)
        self.log(user["id"], 'unchoose', idx)

    def set_flag(self, user, idx, on, comment=''):
        cur = self.one("SELECT * FROM choices WHERE idx=?", idx)
        if on:
            self.run("INSERT INTO choices(idx,variant,a,b,user_id,ts,flag,comment) VALUES(?,NULL,NULL,NULL,?,?,1,?) "
                     "ON CONFLICT(idx) DO UPDATE SET flag=1, comment=excluded.comment, user_id=excluded.user_id, ts=excluded.ts",
                     idx, user["id"], time.time(), (comment or '')[:300])
        elif cur:
            if cur["variant"]:
                self.run("UPDATE choices SET flag=0, comment='' WHERE idx=?", idx)
            else:
                self.run("DELETE FROM choices WHERE idx=?", idx)
        self.release_lock(idx, user["id"])
        self.log(user["id"], 'flag' if on else 'unflag', idx, comment or None)
