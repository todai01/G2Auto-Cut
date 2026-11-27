"""HTTP-сервер «Выбор вариантов»: JSON API + звук + статика. Стандартная библиотека, без зависимостей."""
import json
import mimetypes
import os
import re
import ssl
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .audio import Catalog
from .db import AuthError, Store, SESSION_TTL

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
COOKIE = 'gv_session'
MAX_BODY = 64 * 1024
TITLE = 'Выбор вариантов'


class App:
    def __init__(self, data_dir, secure=False):
        self.catalog = Catalog(data_dir)
        self.store = Store(os.path.join(self.catalog.root, '_веб', 'webvote.sqlite3'))
        self.secure = secure
        self.export_lock = threading.Lock()

    # ---------- списки ----------
    def listing(self, me):
        names = self.catalog.names
        rows = {r["idx"]: r for r in self.store.q("SELECT c.*, u.name un, u.login ul FROM choices c LEFT JOIN users u ON u.id=c.user_id")}
        now = time.time() - 120
        busy = {r["idx"]: (r["name"] or r["login"]) for r in self.store.q(
            "SELECT l.idx, u.name, u.login FROM locks l JOIN users u ON u.id=l.user_id WHERE l.ts>? AND l.user_id!=?", now, me["id"])}
        out, done, flag = [], 0, 0
        for i, nm in enumerate(names):
            r = rows.get(i)
            st = 'new'
            if r and r["variant"]:
                st, done = 'done', done + 1
            elif r and r["flag"]:
                st = 'flag'
            if r and r["flag"] and r["variant"]:
                flag += 1
            elif st == 'flag':
                flag += 1
            row = [i, nm, st, r["variant"] if r and r["variant"] else 0, (r["un"] or r["ul"]) if r and (r["variant"] or r["flag"]) else '',
                   busy.get(i, '')]
            out.append(row)
        return {"rows": out, "total": len(names), "done": done, "flag": flag}

    def next_idx(self, me, start):
        n = len(self.catalog.names)
        rows = {r["idx"]: r for r in self.store.q("SELECT idx, variant, flag, user_id FROM choices")}
        busy = {r["idx"] for r in self.store.q("SELECT idx FROM locks WHERE ts>? AND user_id!=?", time.time() - 120, me["id"])}
        for step in range(1, n + 1):
            i = (start + step) % n
            r = rows.get(i)
            if (r and (r["variant"] or r["flag"])) or i in busy:
                continue
            return i
        return None

    def name_card(self, me, idx):
        c = self.catalog
        if not 0 <= idx < len(c.names):
            raise AuthError("Нет такого имени.", 404)
        vs = []
        for v in c.have(idx):
            try:
                vs.append({"v": v, **c.info(idx, v)})
            except Exception as e:
                vs.append({"v": v, "error": str(e), "dur": 0, "peaks": [], "auto": [0, 0]})
        r = self.store.one("SELECT c.*, u.name un, u.login ul FROM choices c LEFT JOIN users u ON u.id=c.user_id WHERE idx=?", idx)
        other = self.store.touch_lock(idx, me["id"])
        choice = None
        if r:
            choice = {"v": r["variant"], "a": r["a"], "b": r["b"], "by": r["un"] or r["ul"], "mine": r["user_id"] == me["id"],
                      "flag": bool(r["flag"]), "comment": r["comment"], "ts": r["ts"]}
        return {"idx": idx, "name": c.names[idx], "total": len(c.names), "variants": vs, "choice": choice,
                "busy": other[1] if other else None, "ctx": bool(c.ctx_path('start') or c.ctx_path('end'))}

    def stats(self):
        total = len(self.catalog.names)
        r = self.store.q("SELECT u.id, u.login, u.name, COUNT(c.idx) n, MAX(c.ts) last FROM users u "
                         "LEFT JOIN choices c ON c.user_id=u.id AND c.variant IS NOT NULL GROUP BY u.id ORDER BY n DESC")
        done = self.store.one("SELECT COUNT(*) c FROM choices WHERE variant IS NOT NULL")["c"]
        flag = self.store.one("SELECT COUNT(*) c FROM choices WHERE flag=1")["c"]
        votes = {v: self.store.one("SELECT COUNT(*) c FROM choices WHERE variant=?", v)["c"] for v in self.catalog.variants}
        return {"total": total, "done": done, "flag": flag, "votes": votes,
                "users": [{"id": x["id"], "login": x["login"], "name": x["name"] or x["login"], "n": x["n"], "last": x["last"]} for x in r]}

    def export(self, me):
        rows = []
        for r in self.store.q("SELECT c.*, u.name un, u.login ul FROM choices c LEFT JOIN users u ON u.id=c.user_id"):
            rows.append({"idx": r["idx"], "variant": r["variant"], "a": r["a"], "b": r["b"], "user": r["un"] or r["ul"],
                         "ts": time.strftime('%Y-%m-%d %H:%M', time.localtime(r["ts"])) if r["ts"] else '', "flag": r["flag"], "comment": r["comment"]})
        with self.export_lock:
            res = self.catalog.export(rows)
        self.store.log(me["id"], 'export', None, str(res["done"]))
        return res


def make_handler(app):
    class H(BaseHTTPRequestHandler):
        server_version = 'GVoxVote'
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        # ---- вспомогательное ----
        def ip(self):
            return self.client_address[0]

        def token(self):
            try:
                c = cookies.SimpleCookie(self.headers.get('Cookie', ''))
                return c[COOKIE].value if COOKIE in c else None
            except Exception:
                return None

        def user(self):
            return app.store.user_by_token(self.token())

        def send(self, code, body=b'', ctype='application/json; charset=utf-8', headers=None):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def json(self, obj, code=200, headers=None):
            self.send(code, json.dumps(obj, ensure_ascii=False).encode('utf-8'), headers=headers)

        def fail(self, e):
            self.json({"error": str(e)}, getattr(e, 'code', 400))

        def body(self):
            n = int(self.headers.get('Content-Length') or 0)
            if n > MAX_BODY:
                raise AuthError("Слишком большой запрос.", 413)
            raw = self.rfile.read(n) if n else b''
            try:
                return json.loads(raw.decode('utf-8')) if raw else {}
            except Exception:
                raise AuthError("Запрос не разобран.")

        def set_cookie(self, token):
            parts = [f'{COOKIE}={token}', 'Path=/', 'HttpOnly', 'SameSite=Strict', f'Max-Age={SESSION_TTL}']
            if app.secure:
                parts.append('Secure')
            return {"Set-Cookie": '; '.join(parts)}

        def clear_cookie(self):
            return {"Set-Cookie": f'{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'}

        # ---- маршрутизация ----
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            try:
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                p = u.path
                if p == '/api/me':
                    me = self.user()
                    return self.json({"title": TITLE, "setup": app.store.users_count() == 0, "user": app.store.public(me) if me else None,
                                      "total": len(app.catalog.names), "variants": app.catalog.variants,
                                      "voice": app.catalog.meta.get("voice")})
                if p.startswith('/api/') or p.startswith('/audio/'):
                    me = self.user()
                    if not me:
                        return self.json({"error": "Нужен вход."}, 401)
                    if me["must_change"] and p != '/api/me':
                        return self.json({"error": "Смените временный пароль.", "must_change": True}, 403)
                    return self.get_api(me, p, q)
                return self.static(p)
            except AuthError as e:
                self.fail(e)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                self.json({"error": f"Ошибка сервера: {e}"}, 500)

        def get_api(self, me, p, q):
            if p == '/api/list':
                return self.json(app.listing(me))
            if p == '/api/next':
                return self.json({"idx": app.next_idx(me, int(q.get("from", -1)))})
            m = re.fullmatch(r'/api/name/(\d+)', p)
            if m:
                return self.json(app.name_card(me, int(m.group(1))))
            if p == '/audio/take':
                i, v = int(q["idx"]), int(q["v"])
                path = app.catalog.path(i, v)
                if v not in app.catalog.variants or not os.path.isfile(path):
                    raise AuthError("Нет файла.", 404)
                with open(path, 'rb') as f:
                    return self.audio(f.read())
            if p == '/audio/chain':
                i, v = int(q["idx"]), int(q["v"])
                if v not in app.catalog.variants or not os.path.isfile(app.catalog.path(i, v)):
                    raise AuthError("Нет файла.", 404)
                a = int(q["a"]) if q.get("a") not in (None, '') else None
                b = int(q["b"]) if q.get("b") not in (None, '') else None
                data, off, ln = app.catalog.chain(i, v, a, b, with_ctx=q.get("ctx", '1') != '0')
                return self.audio(data, {"X-Name-Offset": str(off), "X-Name-Length": str(ln), "Access-Control-Expose-Headers": 'X-Name-Offset, X-Name-Length'})
            if p == '/api/users':
                self.need_admin(me)
                return self.json({"users": [app.store.public(x) for x in app.store.q("SELECT * FROM users ORDER BY login")]})
            if p == '/api/admin/stats':
                self.need_admin(me)
                return self.json(app.stats())
            raise AuthError("Нет такого адреса.", 404)

        def need_admin(self, me):
            if me["role"] != 'admin':
                raise AuthError("Только для администратора.", 403)

        def audio(self, data, extra=None):
            rng = self.headers.get('Range')
            m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng or '')
            size = len(data)
            if m and (m.group(1) or m.group(2)):
                a = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
                b = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
                b = min(b, size - 1)
                if a > b:
                    return self.send(416, b'', 'audio/wav', {"Content-Range": f'bytes */{size}'})
                return self.send(206, data[a:b + 1], 'audio/wav', {"Content-Range": f'bytes {a}-{b}/{size}', "Accept-Ranges": 'bytes', **(extra or {})})
            return self.send(200, data, 'audio/wav', {"Accept-Ranges": 'bytes', **(extra or {})})

        def static(self, p):
            if p in ('', '/'):
                p = '/index.html'
            rel = os.path.normpath(p.lstrip('/'))
            full = os.path.abspath(os.path.join(STATIC, rel))
            if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
                return self.send(404, 'Не найдено'.encode('utf-8'), 'text/plain; charset=utf-8')
            ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
            if ctype.startswith('text/') or ctype in ('application/javascript', 'image/svg+xml'):
                ctype += '; charset=utf-8' if 'charset' not in ctype else ''
            with open(full, 'rb') as f:
                self.send(200, f.read(), ctype)

        def do_POST(self):
            try:
                if self.headers.get('X-Requested-With') != 'webvote':
                    raise AuthError("Запрос отклонён.", 403)
                p = urlparse(self.path).path
                d = self.body()
                return self.post_api(p, d)
            except AuthError as e:
                self.fail(e)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (KeyError, ValueError, TypeError) as e:
                self.json({"error": f"Неверные данные: {e}"}, 400)
            except Exception as e:
                self.json({"error": f"Ошибка сервера: {e}"}, 500)

        def post_api(self, p, d):
            st = app.store
            if p == '/api/setup':
                if st.users_count():
                    raise AuthError("Администратор уже создан.", 409)
                st.create_user(d["login"], d.get("name", ''), d["password"], 'admin', must_change=False)
                token, u = st.login(d["login"], d["password"], self.ip())
                return self.json({"user": st.public(u)}, headers=self.set_cookie(token))
            if p == '/api/login':
                token, u = st.login(d.get("login"), d.get("password"), self.ip())
                return self.json({"user": st.public(u)}, headers=self.set_cookie(token))
            me = self.user()
            if not me:
                return self.json({"error": "Нужен вход."}, 401)
            if p == '/api/logout':
                st.logout(self.token())
                return self.json({"ok": True}, headers=self.clear_cookie())
            if p == '/api/password':
                from .db import _hash
                import hmac
                if not hmac.compare_digest(_hash(d.get("old", ''), me["salt"]), me["hash"]):
                    raise AuthError("Текущий пароль неверен.", 403)
                if d.get("new") == d.get("old"):
                    raise AuthError("Новый пароль должен отличаться от прежнего.")
                st.set_password(me["id"], d["new"], must_change=False)
                token, u = st.login(me["login"], d["new"], self.ip())
                return self.json({"user": st.public(u)}, headers=self.set_cookie(token))
            if me["must_change"]:
                return self.json({"error": "Смените временный пароль.", "must_change": True}, 403)
            if p == '/api/choose':
                i, v = int(d["idx"]), int(d["v"])
                if not 0 <= i < len(app.catalog.names) or v not in app.catalog.have(i):
                    raise AuthError("Такого варианта нет.", 404)
                a = int(d["a"]) if d.get("a") is not None else None
                b = int(d["b"]) if d.get("b") is not None else None
                if a is not None and b is not None and (a < 0 or b - a < 50):
                    raise AuthError("Слишком короткий участок.")
                st.choose(me, i, v, a, b)
                return self.json({"ok": True})
            if p == '/api/unchoose':
                st.unchoose(me, int(d["idx"]))
                return self.json({"ok": True})
            if p == '/api/flag':
                st.set_flag(me, int(d["idx"]), bool(d.get("on", True)), d.get("comment", ''))
                return self.json({"ok": True})
            if p == '/api/heartbeat':
                other = st.touch_lock(int(d["idx"]), me["id"])
                return self.json({"busy": other[1] if other else None})
            if p == '/api/release':
                st.release_lock(int(d["idx"]), me["id"])
                return self.json({"ok": True})
            if p == '/api/users':
                self.need_admin(me)
                u = st.create_user(d["login"], d.get("name", ''), d["password"], d.get("role", 'user'), must_change=True)
                st.log(me["id"], 'user_create', None, u["login"])
                return self.json({"user": st.public(u)})
            m = re.fullmatch(r'/api/users/(\d+)', p)
            if m:
                self.need_admin(me)
                kw = {k: d[k] for k in ("role", "active", "name", "password") if k in d}
                u = st.update_user(me["id"], int(m.group(1)), **kw)
                st.log(me["id"], 'user_update', None, f'{u["login"]}:{",".join(kw)}')
                return self.json({"user": st.public(u)})
            if p == '/api/admin/export':
                self.need_admin(me)
                return self.json(app.export(me))
            raise AuthError("Нет такого адреса.", 404)

    return H


def serve(data_dir, host='127.0.0.1', port=8080, cert=None, key=None):
    app = App(data_dir, secure=bool(cert))
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    srv.daemon_threads = True
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.app = app
    return srv
