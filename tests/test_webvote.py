"""«Выбор вариантов» (webvote): аккаунты, сессии, выбор, блокировки, звук, выгрузка — на синтетике, настоящий HTTP-сервер на свободном порту."""
import json
import os
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest
from pydub import AudioSegment

from webvote.server import serve


def _wav(path, ms=700, f=180, rate=16000):
    t = np.arange(int(ms * rate / 1000)) / rate
    x = 0.2 * np.sin(2 * np.pi * f * t)
    x = np.concatenate([np.zeros(int(0.15 * rate)), x, np.zeros(int(0.2 * rate))])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    AudioSegment((x * 32767).astype('<i2').tobytes(), frame_rate=rate, sample_width=2, channels=1).export(path, format='wav')


@pytest.fixture
def web(tmp_path):
    root = tmp_path / 'res'
    names = ['Гизат', 'Айгерим', 'Нуржан']
    for v in (1, 2, 3):
        for i, n in enumerate(names):
            _wav(str(root / f'вариант_{v}' / f'{n}.wav'), ms=500 + 100 * v + 20 * i, f=150 + 20 * v)
    _wav(str(root / '_контекст' / 'start.wav'), ms=400, f=300)
    _wav(str(root / '_контекст' / 'end.wav'), ms=400, f=250)
    (root / 'имена.json').write_text(json.dumps({"names": names, "stems": names, "variants": 3, "voice": 'тест'}, ensure_ascii=False), encoding='utf-8')
    srv = serve(str(root), '127.0.0.1', 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    port = srv.server_address[1]

    class C:
        base = f'http://127.0.0.1:{port}'
        app = srv.app
        root_dir = str(root)

        def __init__(self):
            self.cookie = None

        def call(self, path, data=None, raw=False, headers=None):
            h = {"X-Requested-With": "webvote", **(headers or {})}
            if self.cookie:
                h["Cookie"] = self.cookie
            body = None
            if data is not None:
                body = json.dumps(data).encode()
                h["Content-Type"] = 'application/json'
            req = urllib.request.Request(self.base + path, data=body, headers=h, method='POST' if data is not None else 'GET')
            try:
                with urllib.request.urlopen(req) as r:
                    sc = r.headers.get('Set-Cookie')
                    if sc and 'Max-Age=0' not in sc:
                        self.cookie = sc.split(';')[0]
                    b = r.read()
                    return (r.status, b) if raw else (r.status, json.loads(b))
            except urllib.error.HTTPError as e:
                b = e.read()
                return (e.code, b) if raw else (e.code, json.loads(b))

    yield C
    srv.shutdown()


def admin(web):
    c = web()
    assert c.call('/api/me')[1]["setup"] is True
    st, r = c.call('/api/setup', {"login": 'boss', "name": 'Босс', "password": 'secret1'})
    assert st == 200 and r["user"]["role"] == 'admin'
    return c


def worker(web, boss, login='anna', pw='temp123'):
    st, r = boss.call('/api/users', {"login": login, "name": login.title(), "password": pw})
    assert st == 200 and r["user"]["must_change"] is True
    c = web()
    assert c.call('/api/login', {"login": login, "password": pw})[0] == 200
    assert c.call('/api/list')[0] == 403                                        # пока не сменил временный пароль
    assert c.call('/api/password', {"old": pw, "new": 'mine-pass'})[0] == 200
    return c


def test_setup_once_and_login(web):
    c = admin(web)
    assert c.call('/api/me')[1]["user"]["login"] == 'boss'
    assert web().call('/api/setup', {"login": 'x', "password": 'secret1'})[0] == 409
    assert web().call('/api/list')[0] == 401
    bad = web()
    assert bad.call('/api/login', {"login": 'boss', "password": 'wrong'})[0] == 401


def test_csrf_header_required(web):
    c = web()
    req = urllib.request.Request(c.base + '/api/login', data=b'{}', method='POST')
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403


def test_throttle_after_five_fails(web):
    admin(web)
    c = web()
    codes = [c.call('/api/login', {"login": 'boss', "password": 'bad'})[0] for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_passwords_hashed_and_policy(web):
    boss = admin(web)
    assert boss.call('/api/users', {"login": 'u1', "password": '123'})[0] == 400
    assert boss.call('/api/users', {"login": 'u1', "password": 'u1'})[0] == 400
    assert boss.call('/api/users', {"login": 'u1', "password": 'abcdef'})[0] == 200
    assert boss.call('/api/users', {"login": 'U1', "password": 'abcdef'})[0] == 409
    row = web.app.store.one("SELECT * FROM users WHERE login='u1'")
    assert b'abcdef' not in bytes(row["hash"]) and len(row["salt"]) == 16


def test_last_admin_and_self_protected(web):
    boss = admin(web)
    me = boss.call('/api/me')[1]["user"]["id"]
    assert boss.call(f'/api/users/{me}', {"role": 'user'})[0] == 409
    assert boss.call(f'/api/users/{me}', {"active": False})[0] == 409
    u = boss.call('/api/users', {"login": 'u2', "password": 'abcdef', "role": 'admin'})[1]["user"]
    assert boss.call(f'/api/users/{u["id"]}', {"role": 'user'})[0] == 200


def test_user_cannot_use_admin_api(web):
    boss = admin(web)
    w = worker(web, boss)
    assert w.call('/api/users')[0] == 403
    assert w.call('/api/admin/export', {})[0] == 403


def test_disable_kills_session(web):
    boss = admin(web)
    w = worker(web, boss)
    uid = w.call('/api/me')[1]["user"]["id"]
    assert w.call('/api/list')[0] == 200
    boss.call(f'/api/users/{uid}', {"active": False})
    assert w.call('/api/list')[0] == 401


def test_choose_flow_and_next(web):
    boss = admin(web)
    st, card = boss.call('/api/name/0')
    assert st == 200 and card["name"] == 'Гизат' and [v["v"] for v in card["variants"]] == [1, 2, 3]
    assert all(v["peaks"] and v["auto"][1] > v["auto"][0] for v in card["variants"])
    assert boss.call('/api/choose', {"idx": 0, "v": 2, "a": 100, "b": 600})[0] == 200
    lst = boss.call('/api/list')[1]
    assert lst["done"] == 1 and lst["rows"][0][2] == 'done' and lst["rows"][0][3] == 2
    assert boss.call('/api/next?from=-1')[1]["idx"] == 1
    assert boss.call('/api/choose', {"idx": 1, "v": 9})[0] == 404
    assert boss.call('/api/unchoose', {"idx": 0})[0] == 200
    assert boss.call('/api/list')[1]["done"] == 0


def test_lock_and_ownership(web):
    boss = admin(web)
    w = worker(web, boss)
    assert boss.call('/api/name/1')[1]["busy"] is None
    card = w.call('/api/name/1')[1]
    assert card["busy"]                                                        # занято админом
    assert w.call('/api/choose', {"idx": 1, "v": 1})[0] == 409
    assert w.call('/api/next?from=0')[1]["idx"] == 2                           # занятое пропускается
    boss.call('/api/release', {"idx": 1})
    assert w.call('/api/name/1')[1]["busy"] is None
    assert w.call('/api/choose', {"idx": 1, "v": 3})[0] == 200
    w2 = worker(web, boss, 'bob')
    assert w2.call('/api/choose', {"idx": 1, "v": 1})[0] == 403                # чужой выбор менять нельзя
    assert boss.call('/api/choose', {"idx": 1, "v": 1})[0] == 200              # админ может


def test_flag_and_unflag(web):
    boss = admin(web)
    assert boss.call('/api/flag', {"idx": 2, "on": True, "comment": 'шум'})[0] == 200
    r = boss.call('/api/list')[1]
    assert r["rows"][2][2] == 'flag' and r["flag"] == 1
    assert boss.call('/api/next?from=1')[1]["idx"] == 0                        # помеченное не предлагается
    boss.call('/api/flag', {"idx": 2, "on": False})
    assert boss.call('/api/list')[1]["rows"][2][2] == 'new'


def test_audio_take_range_and_chain(web):
    boss = admin(web)
    st, full = boss.call('/audio/take?idx=0&v=1', raw=True)
    assert st == 200 and full[:4] == b'RIFF'
    st, part = boss.call('/audio/take?idx=0&v=1', raw=True, headers={"Range": 'bytes=0-99'})
    assert st == 206 and len(part) == 100
    st, ch = boss.call('/audio/chain?idx=0&v=1', raw=True)
    st2, ch2 = boss.call('/audio/chain?idx=0&v=1&a=150&b=400&ctx=0', raw=True)
    assert st == 200 and st2 == 200 and len(ch) > len(ch2) > 0
    assert boss.call('/audio/take?idx=0&v=7', raw=True)[0] == 404
    assert web().call('/audio/take?idx=0&v=1', raw=True)[0] == 401


def test_path_traversal_blocked(web):
    c = web()
    assert c.call('/../server.py', raw=True)[0] == 404
    assert c.call('/%2e%2e/db.py', raw=True)[0] == 404


def test_export_full_and_trimmed(web):
    boss = admin(web)
    boss.call('/api/choose', {"idx": 0, "v": 1})
    boss.call('/api/choose', {"idx": 1, "v": 3, "a": 200, "b": 500})
    boss.call('/api/flag', {"idx": 2, "on": True, "comment": 'плохо'})
    r = boss.call('/api/admin/export', {})[1]
    assert r["done"] == 2 and not r["errors"]
    out = os.path.join(web.root_dir, 'Итог')
    full = AudioSegment.from_file(os.path.join(out, 'Гизат.wav'))
    src = AudioSegment.from_file(os.path.join(web.root_dir, 'вариант_1', 'Гизат.wav'))
    assert len(full) == len(src)
    cut = AudioSegment.from_file(os.path.join(out, 'Айгерим.wav'))
    assert abs(len(cut) - 300) < 5
    assert not os.path.exists(os.path.join(out, 'Нуржан.wav'))
    rep = open(os.path.join(out, '_отчёт.csv'), encoding='utf-8-sig').read()
    assert 'плохо' in rep and 'Айгерим' in rep
    assert not any(f.endswith('.part') or '.part.' in f for f in os.listdir(out))
    s = boss.call('/api/admin/stats')[1]
    assert s["done"] == 2 and s["flag"] == 1 and s["votes"]["1"] == 1


def test_password_change_invalidates_old_sessions(web):
    boss = admin(web)
    old = web()
    old.call('/api/login', {"login": 'boss', "password": 'secret1'})
    assert old.call('/api/list')[0] == 200
    assert boss.call('/api/password', {"old": 'secret1', "new": 'other-pass'})[0] == 200
    assert old.call('/api/list')[0] == 401
    assert boss.call('/api/list')[0] == 200
