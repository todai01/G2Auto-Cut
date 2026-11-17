"""Командный режим без сервера: учётки и данные сотрудников лежат в общей сетевой папке.

<папка команды>/GTime_team/accounts/<логин>.json — учётка (роль, соль и хэш пароля, активна ли, надо ли сменить пароль);
<папка команды>/GTime_team/data/<логин>.json — снимок данных сотрудника (дни, задачи, состояние) — его раз в минуту пишет GTime.
У каждого сотрудника свои файлы — записи разных людей не мешают друг другу (общих файлов нет).

Честно о защите: папка общая, поэтому пароль и роли защищают от случайного, а не от умысла (любой, кто видит папку,
может открыть чужой файл в Проводнике). Настоящее разграничение — права Windows на папки data и accounts.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime

SUB = 'GTime_team'
ITER = 200_000
LOGIN_RE = re.compile(r'^[\w][\w.\-]{1,31}$', re.UNICODE)
MIN_PASSWORD = 6
MAX_FAILS, LOCK_S = 5, 30                                    # после 5 неверных паролей подряд — пауза 30 с


ROLES = ('user', 'mentor', 'admin')                      # сотрудник · куратор (видит команду и отчёты) · администратор-разработчик (всё, включая учётки и обновления)


class TeamError(Exception):
    """Понятная пользователю ошибка (текст можно показывать как есть)."""


def norm_login(login):
    s = str(login or '').strip().lower()
    if not LOGIN_RE.match(s):
        raise TeamError('Логин — от 2 до 32 знаков: буквы, цифры, точка, дефис, подчёркивание.')
    return s


def hash_password(password, salt=None, iterations=ITER):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), bytes.fromhex(salt), iterations).hex()
    return {"salt": salt, "hash": h, "iter": iterations}


def check_password(account, password):
    try:
        h = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), bytes.fromhex(account["salt"]), int(account.get("iter") or ITER)).hex()
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(h, str(account.get("hash") or ''))


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


class TeamStore:
    def __init__(self, root, clock=None):
        self.root = root
        self._now = clock or datetime.now
        self.acc_dir = os.path.join(root, SUB, 'accounts') if root else ''
        self.data_dir = os.path.join(root, SUB, 'data') if root else ''
        self._fails = {}                                     # {логин: (число ошибок, время блокировки)}

    # ---------- доступность ----------
    def available(self):
        return bool(self.root) and os.path.isdir(self.root)

    def _need(self):
        if not self.available():
            raise TeamError('Сетевая папка недоступна. Проверьте подключение и путь в «Настройках».')

    # ---------- учётки ----------
    @staticmethod
    def _public(a):
        return {"login": a["login"], "name": a.get("name") or a["login"], "role": a.get("role", "user"),
                "active": a.get("active", True) is True, "must_change": a.get("must_change") is True, "created": a.get("created")}

    def get(self, login):
        self._need()
        a = _read_json(os.path.join(self.acc_dir, norm_login(login) + '.json'))
        return a if a and a.get("login") else None

    def list(self):
        self._need()
        out = []
        for f in sorted(os.listdir(self.acc_dir)) if os.path.isdir(self.acc_dir) else []:
            if f.endswith('.json'):
                a = _read_json(os.path.join(self.acc_dir, f))
                if a and a.get("login"):
                    out.append(self._public(a))
        return out

    def has_admin(self):
        return any(a["role"] == "admin" and a["active"] for a in self.list())

    def _save(self, a):
        _write_json(os.path.join(self.acc_dir, a["login"] + '.json'), a)

    def create(self, login, name, password, role='user', must_change=True):
        self._need()
        login = norm_login(login)
        if len(str(password or '')) < 3:
            raise TeamError('Пароль — не короче 3 знаков.')
        if self.get(login):
            raise TeamError('Такой логин уже есть.')
        a = {"login": login, "name": str(name or '').strip()[:60] or login, "role": role if role in ROLES else 'user', "active": True,
             "must_change": bool(must_change), "created": self._now().strftime('%Y-%m-%dT%H:%M:%S'), **hash_password(password)}
        self._save(a)
        return self._public(a)

    def verify(self, login, password):
        """Вход. Возвращает открытые данные учётки или TeamError (неверный пароль, учётка отключена, пауза после ошибок)."""
        self._need()
        login = norm_login(login)
        n, until = self._fails.get(login, (0, None))
        if until and self._now() < until:
            raise TeamError(f'Слишком много неверных паролей. Подождите {max(1, int((until - self._now()).total_seconds()))} с.')
        a = self.get(login)
        if not a or not check_password(a, password):
            n += 1
            self._fails[login] = (0, self._now() + _delta(LOCK_S)) if n >= MAX_FAILS else (n, None)
            raise TeamError('Неверный логин или пароль.')
        if a.get("active", True) is not True:
            raise TeamError('Учётка отключена администратором.')
        self._fails.pop(login, None)
        return self._public(a)

    def change_password(self, login, old, new):
        a = self.get(login)
        if not a or not check_password(a, old):
            raise TeamError('Текущий пароль неверный.')
        self._check_new(a["login"], new, old)
        a.update(hash_password(new), must_change=False)
        self._save(a)

    @staticmethod
    def _check_new(login, new, old=None):
        new = str(new or '')
        if len(new) < MIN_PASSWORD:
            raise TeamError(f'Новый пароль — не короче {MIN_PASSWORD} знаков.')
        if new.lower() == login or (old is not None and new == old):
            raise TeamError('Новый пароль не должен совпадать с логином и со старым паролем.')

    def reset_password(self, login, password, must_change=True):
        """Админ задаёт новый (стартовый) пароль; сотрудник сменит его при входе."""
        a = self.get(login)
        if not a:
            raise TeamError('Учётки нет.')
        if len(str(password or '')) < 3:
            raise TeamError('Пароль — не короче 3 знаков.')
        a.update(hash_password(password), must_change=bool(must_change))
        self._save(a)

    def set_name(self, login, name):
        a = self.get(login)
        if a and str(name or '').strip():
            a["name"] = str(name).strip()[:60]
            self._save(a)

    def set_active(self, login, on):
        a = self.get(login)
        if not a:
            raise TeamError('Учётки нет.')
        if not on and a["role"] == 'admin' and sum(1 for x in self.list() if x["role"] == 'admin' and x["active"]) <= 1:
            raise TeamError('Нельзя отключить последнего администратора.')
        a["active"] = bool(on)
        self._save(a)

    def set_role(self, login, role):
        a = self.get(login)
        if not a:
            raise TeamError('Учётки нет.')
        role = role if role in ROLES else 'user'
        if role != 'admin' and a["role"] == 'admin' and sum(1 for x in self.list() if x["role"] == 'admin' and x["active"]) <= 1:
            raise TeamError('Нельзя снять роль у последнего администратора.')
        a["role"] = role
        self._save(a)

    # ---------- данные сотрудников ----------
    def write_snapshot(self, login, snap):
        self._need()
        _write_json(os.path.join(self.data_dir, norm_login(login) + '.json'), snap)

    def read_snapshot(self, login):
        self._need()
        return _read_json(os.path.join(self.data_dir, norm_login(login) + '.json'))


def _delta(sec):
    from datetime import timedelta
    return timedelta(seconds=sec)
