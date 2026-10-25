# Стенд для записи обучающих роликов GVox: настоящий Api из main.py на
# демо-проекте, диалоги/плеер/Audacity — заглушки, поверх экрана — курсор
# и подписи шагов. Ролик пишет Playwright (webm), потом ffmpeg → VP9.
import os, sys, types, json, time, shutil, subprocess, threading
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
VID = os.path.join(HERE, '_work')                  # демо-данные роликов (в git не идут)
os.makedirs(VID, exist_ok=True)
sys.path.insert(0, HERE)
for m in ('win32gui', 'win32con', 'win32api', 'win32process', 'pywinauto', 'comtypes'):
    sys.modules.setdefault(m, types.ModuleType(m))
import demo_env                                    # ставит заглушки webview/sounddevice и делает demo.xlsx
from demo_env import speech, write, R
import webview
import main

APP = os.path.join(ROOT, 'frontend', 'index.html')
OUT = os.path.join(ROOT, 'frontend', 'tutorial')
RAW = os.path.join(VID, '_frames')
W, H = 1600, 900
CHROMIUM = os.environ.get('GVOX_CHROMIUM', '/opt/pw-browsers/chromium')


def nice(text):
    """Пути демо-данных в ролике — как у пользователя: D:/GVox_демо/…"""
    return text.replace(VID, 'D:/GVox_демо')


def ugly(args):
    return json.loads(json.dumps(args, ensure_ascii=False).replace('D:/GVox_демо', VID))


class Player:
    is_playing = False
    def play(self, p): self.is_playing = True
    def stop(self): self.is_playing = False
    def pause(self): self.is_playing = False
    def set_device(self, d): pass
    def __getattr__(self, n): return lambda *a, **k: None


class Api(main.Api):
    def __init__(self):
        super().__init__()
        self.player = Player()


DIALOG = []                                         # ответы диалогов выбора по очереди
JSQ = []                                            # evaluate_js из Python — выполнит страница
RECENT = []                                         # «Недавние проекты» для ролика (по умолчанию — пусто)
FAKE = {}                                           # подмена отдельных методов Api: имя → функция


def dialog(*_a, **_k):
    return DIALOG.pop(0) if DIALOG else None


webview.windows = [types.SimpleNamespace(create_file_dialog=dialog, evaluate_js=lambda code: JSQ.append(code),
                                         set_title=lambda *a: None, minimize=lambda: None, restore=lambda: None,
                                         toggle_fullscreen=lambda: None, destroy=lambda: None)]


def build_project():
    """Демо-проект Студии (как demo_env.build, но настоящий Api)."""
    demo_env.A = Api
    a, st, U, wd = demo_env.build()
    a._tts_push = lambda p: JSQ.append(f"ttsProgress({json.dumps(json.loads(json.dumps(p, default=str)), ensure_ascii=False)})")
    return a, st, U, wd


OVERLAY_JS = r"""
(() => {
  if (document.getElementById('tutCursor')) return;
  const css = document.createElement('style');
  css.textContent = `
   #tutCursor{position:fixed;z-index:2147483647;left:0;top:0;width:22px;height:22px;pointer-events:none;transform:translate(-3px,-2px);
     transition:transform .06s linear;filter:drop-shadow(0 2px 3px rgba(0,0,0,.6))}
   .tut-ripple{position:fixed;z-index:2147483646;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;pointer-events:none;
     border:2px solid #f5b544;animation:tutRip .5s ease-out forwards}
   @keyframes tutRip{from{opacity:1;transform:scale(.3)}to{opacity:0;transform:scale(1.6)}}
   #tutCap.is-top{bottom:auto;top:22px} #tutCap.is-mid{bottom:150px}
   #tutCap{position:fixed;z-index:2147483645;left:50%;bottom:26px;transform:translateX(-50%);max-width:1100px;pointer-events:none;
     padding:12px 22px;border-radius:14px;background:rgba(10,12,18,.92);border:1px solid rgba(245,181,68,.55);color:#fff;
     font:600 20px/1.35 Inter,system-ui,sans-serif;box-shadow:0 10px 40px rgba(0,0,0,.55);opacity:0;transition:opacity .25s}
   #tutCap.is-on{opacity:1} #tutCap b{color:#f5b544}
   #tutKey{position:fixed;z-index:2147483645;right:28px;top:24px;padding:8px 14px;border-radius:10px;background:rgba(10,12,18,.92);
     border:1px solid rgba(255,255,255,.25);color:#fff;font:700 18px/1 'JetBrains Mono',monospace;opacity:0;transition:opacity .2s}
   #tutKey.is-on{opacity:1}`;
  document.head.appendChild(css);
  const c = document.createElement('div'); c.id = 'tutCursor';
  c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M3 2l7 19 2.6-7.4L20 11z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  const cap = document.createElement('div'); cap.id = 'tutCap'; document.body.appendChild(cap);
  const key = document.createElement('div'); key.id = 'tutKey'; document.body.appendChild(key);
  document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', e => { const r = document.createElement('div'); r.className = 'tut-ripple';
    r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; document.body.appendChild(r); setTimeout(() => r.remove(), 600); }, true);
  window.__tutCap = (html, top) => { cap.innerHTML = html || ''; cap.classList.toggle('is-on', !!html); cap.classList.toggle('is-top', top === true || top === 'top'); cap.classList.toggle('is-mid', top === 'mid'); };
  window.__tutKeyShow = (txt) => { key.textContent = txt || ''; key.classList.toggle('is-on', !!txt); };
})();
"""


ONLY = [x for x in sys.argv[1:] if not x.startswith('-')]


def want(name):
    return not ONLY or name in ONLY


class Rec:
    def __init__(self, name, a=None):
        self.name, self.a, self.mx, self.my = name, a, W / 2, H / 2

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.b = self._pw.chromium.launch(**({'executable_path': CHROMIUM} if os.path.exists(CHROMIUM) else {}))
        self.vdir = os.path.join(RAW, self.name)
        shutil.rmtree(self.vdir, ignore_errors=True)
        os.makedirs(self.vdir)
        self.ctx = self.b.new_context(viewport={'width': W, 'height': H})
        self.t_ctx = time.time()
        self.pg = self.ctx.new_page()
        DIALOG[:] = [d for d in DIALOG if getattr(d, '_keep', True)]
        self.frames = []                              # (время, файл) — кадры экрана по мере изменений
        self.cdp = self.ctx.new_cdp_session(self.pg)

        def on_frame(ev):
            import base64
            fn = os.path.join(self.vdir, f"{len(self.frames):05d}.jpg")
            with open(fn, 'wb') as f:
                f.write(base64.b64decode(ev['data']))
            self.frames.append((time.time(), fn))
            try:
                self.cdp.send('Page.screencastFrameAck', {'sessionId': ev['sessionId']})
            except Exception:
                pass
        self.cdp.on('Page.screencastFrame', on_frame)
        self.errs = []
        self.pg.on('pageerror', lambda e: self.errs.append(str(e)))
        a = self.a

        def api(n, args):
            if n == '__flush':
                js = [nice(c) for c in JSQ]
                JSQ.clear()
                return {"r": None, "js": js}
            if n == 'get_recent_projects':
                return {"r": RECENT, "js": []}
            args = ugly(args)
            f = FAKE.get(n) or (getattr(a, n, None) if a else None)
            try:
                r = f(*args) if f else None
            except Exception as e:
                r = {"error": str(e)}
            js = [nice(c) for c in JSQ]
            JSQ.clear()
            return {"r": json.loads(nice(json.dumps(r, default=str, ensure_ascii=False))), "js": js}
        self.pg.expose_function('pyapi', api)
        self.pg.add_init_script("""localStorage.clear(); localStorage.setItem('gvox_seen_intro', '1');
            window.pywebview = {api: new Proxy({}, {get: (t, n) => async (...x) => {
                let o = await window.pyapi(n, x);
                setTimeout(() => (o.js || []).forEach(c => { try { (0, eval)(c); } catch (e) { console.error(e); } }), 0);
                return o.r; }})};
            setInterval(() => window.pywebview.api.__flush(), 300);""")
        self.pg.goto('file://' + APP)
        self.pg.wait_for_timeout(1500)
        self.pg.evaluate("resumePromptAnswered = true; document.getElementById('resumeProjectOverlay').style.display = 'none'")
        self.pg.add_style_tag(content='.toast{font-size:16px!important}')
        self.pg.evaluate(OVERLAY_JS)
        self.pg.mouse.move(self.mx, self.my)
        return self

    def start(self):
        """С этого места — ролик (всё до него — подготовка)."""
        del JSQ[:]
        self.pg.wait_for_timeout(200)
        self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 90, 'maxWidth': W, 'maxHeight': H, 'everyNthFrame': 1})
        self.t0 = time.time()

    # ---- действия ----
    top = False                                       # подписи сверху (где внизу важное)

    def cap(self, html, ms=0, top=None):
        self.pg.evaluate("([h, t]) => __tutCap(h, t)", [html, self.top if top is None else top])
        if ms:
            self.wait(ms)

    def key(self, label, code, ms=700):
        self.pg.evaluate("t => __tutKeyShow(t)", label)
        self.wait(250)
        self.pg.keyboard.press(code)
        self.wait(ms)
        self.pg.evaluate("__tutKeyShow('')")

    def wait(self, ms):
        self.pg.wait_for_timeout(ms)

    def move(self, sel, ms=650, dx=0.5, dy=0.5):
        loc = self.pg.locator(sel + ' >> visible=true').first
        loc.wait_for(state='visible', timeout=8000)
        loc.evaluate("e => e.scrollIntoView({block: 'nearest', inline: 'nearest'})")
        self.wait(250)
        bb = loc.bounding_box()
        x, y = bb['x'] + bb['width'] * dx, bb['y'] + bb['height'] * dy
        steps = max(8, int(ms / 16))
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            self.pg.mouse.move(self.mx + (x - self.mx) * e, self.my + (y - self.my) * e)
            self.pg.wait_for_timeout(ms / steps)
        self.mx, self.my = x, y
        return loc

    def click(self, sel, ms=650, after=700, **kw):
        self.move(sel, ms, **kw)
        self.wait(150)
        self.pg.mouse.down(); self.wait(60); self.pg.mouse.up()
        self.wait(after)

    def glide(self, x, y, ms=600):
        steps = max(8, int(ms / 16))
        for i in range(1, steps + 1):
            t = i / steps
            e = t * t * (3 - 2 * t)
            self.pg.mouse.move(self.mx + (x - self.mx) * e, self.my + (y - self.my) * e)
            self.pg.wait_for_timeout(ms / steps)
        self.mx, self.my = x, y

    def drag(self, x0, y0, x1, y1, ms=900):
        self.glide(x0, y0, 500)
        self.wait(200)
        self.pg.mouse.down()
        self.glide(x1, y1, ms)
        self.wait(120)
        self.pg.mouse.up()
        self.wait(500)

    def js(self, code, after=0):
        r = self.pg.evaluate(code)
        if after:
            self.wait(after)
        return r

    def __exit__(self, *exc):
        self.wait(400)
        t_end = time.time()
        try:
            self.cdp.send('Page.stopScreencast')
        except Exception:
            pass
        self.ctx.close(); self.b.close(); self._pw.stop()
        if exc[0] is None and hasattr(self, 't0') and self.frames:   # без start() — просто проверка, без ролика
            encode(self.frames, self.name, self.t0, t_end, self.vdir)
        if self.errs:
            print(f'[{self.name}] ошибки JS:', self.errs)
        return False


POSTER_AT = {}


def encode(frames, name, t0, t_end, vdir):
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f'{name}.webm')
    fr = [(t, f) for t, f in frames if t >= t0 - 0.5] or frames[-1:]
    lst = os.path.join(vdir, 'list.txt')
    with open(lst, 'w') as o:                         # кадр держится до следующего изменения экрана
        for k, (t, f) in enumerate(fr):
            nxt = fr[k + 1][0] if k + 1 < len(fr) else t_end
            o.write(f"file '{f}'\nduration {max(0.001, nxt - max(t, t0)):.3f}\n")
        o.write(f"file '{fr[-1][1]}'\n")
    src = lst
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', src, '-vf', 'scale=1280:720:flags=lanczos,fps=25,format=yuv420p',
                    '-c:v', 'libvpx-vp9', '-crf', '40', '-b:v', '0', '-row-mt', '1', '-deadline', 'good', '-cpu-used', '4',
                    '-an', dst], check=True)
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', dst],
                         capture_output=True, text=True).stdout.strip()
    poster = os.path.join(OUT, f'{name}.jpg')                # превью — из середины, где уже есть что показать
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', f'{float(out or 5) * POSTER_AT.get(name, 0.45):.2f}', '-i', dst,
                    '-frames:v', '1', '-vf', 'scale=384:216', '-q:v', '5', poster], check=True)
    print(f'[{name}] {float(out or 0):.1f} с, {os.path.getsize(dst) // 1024} КБ')
