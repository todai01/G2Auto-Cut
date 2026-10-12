"""4 этап: суммы голосом диктора — клонирование по эталону через внутренний
сервис синтеза, затем режим «Суммы».

Как это работает:
  1. Эталон — запись диктора с суммой (например «один миллион сто одна
     тысяча один тенге») и её текст словами.
  2. Список сумм строится по логике режима «Суммы»: у каждого яруса свой
     диапазон (миллионы 1–100, сотни 100–900, тысячи 1–99, тенге 1–100), на
     каждом шаге все ярусы берут следующее значение, дошедший до потолка —
     остаётся на последнем: 1 101 001, 2 202 002, … Текст — словами (RU / KZ).
  3. Робот открывает сервис (Chrome за краем экрана, как в G2Synth), вкладка
     «Клонирование»: язык, файл эталона, текст эталона, текст суммы →
     «Синтезировать» → скачивает результат.
     Гибрид (по умолчанию): слова «миллион», «тысяча», «тенге» — живые, их
     вырезаем из эталона (и из доп. записей); на сервис уходят только числа
     («два», «двести две», «два»), потом всё склеивается в одну сумму.
  4. Вы слушаете; не понравилось — пересинтез; понравилось — «Одобрить»:
     тишина по краям обрезается, файл ложится в «Синтез_суммы_RU/» (или _KZ).
  5. «Перейти в режим «Суммы»» — режим открывается сразу на этой папке.

Браузер и страница живут в одном отдельном потоке (так требует Playwright),
запросы к сервису идут строго по очереди."""

import collections
import os
import shutil
import threading
import time

import webview
from pydub import AudioSegment
from pydub.silence import detect_leading_silence

from core.num_words import kz_words, ru_words
from utils.wav_io import wav_layout, wav_slice

SYNTH_URL = 'http://ia-app5-lp3:3124/'
# Шаги на сайте — селекторы из вашей инструкции. Сайт поменяется — правим здесь.
SYNTH_SEL = {
    "clone_tab": "body > main > nav > button:nth-child(2)",
    "lang": "body > main > section.panel.active > form > label:nth-child(1) > select",
    "etalon_file": "body > main > section.panel.active > form > label:nth-child(2) > input[type=file]",
    "etalon_text": "body > main > section.panel.active > form > label:nth-child(3) > input[type=text]",
    "text": "body > main > section.panel.active > form > label:nth-child(4) > textarea",
    "submit": "body > main > section.panel.active > form > button",
}
SYNTH_LANG_INDEX = {'ru': 0, 'kz': 1}     # option:nth-child(1) — русский, (2) — казахский
SYNTH_TIMEOUT_S = 180                      # ждать результат синтеза не дольше
SYNTH_DIR = 'Синтез_суммы'          # + _RU / _KZ: у каждого языка своя папка (режим «Суммы» — по одному языку)
SYNTH_VARIANTS = '_варианты'
SYNTH_ETALON = '_эталон'
SYNTH_WORDS = '_слова'                      # живые слова из эталона: миллион.wav, тысячи.wav…
SYNTH_PREFETCH = 2                         # пока слушаете — столько следующих уже синтезируется

# Живые слова (гибрид). В русском у слова три формы — каждую нужно услышать
# в какой-нибудь записи; нет формы — это слово уйдёт в синтез вместе с числом.
UNIT_FORMS = {
    'ru': ['миллион', 'миллиона', 'миллионов', 'тысяча', 'тысячи', 'тысяч', 'тенге'],
    'kz': ['миллион', 'мың', 'теңге'],
}
_UNIT_ALIAS = {'ru': {'теңге': 'тенге', 'милион': 'миллион', 'милиона': 'миллиона', 'милионов': 'миллионов'},
               'kz': {'тенге': 'теңге', 'мын': 'мың', 'милион': 'миллион'}}
GLUE_XFADE_MS = 12          # число → живое слово: стык без паузы, с короткой перекрёстной склейкой
GLUE_GAP_MS = 70            # живое слово → следующее число (если в эталоне не измерили своё)

# Ярусы режима «Суммы» (как в variables_handler): логика 1 и 2.
_TIER_VALUES = {
    'millions': list(range(1, 101)),
    'hundreds': list(range(100, 1000, 100)),
    'hundred_thousands': list(range(100, 1000, 100)),
    'thousands': list(range(1, 100)),
    'tenge': list(range(1, 101)),
}
SYNTH_LOGICS = {
    1: ['millions', 'hundreds', 'thousands', 'tenge'],          # 1 101 001, 2 202 002…
    2: ['millions', 'hundred_thousands', 'tenge'],              # 1 100 001, 2 200 002…
}

# Скачать звук из <audio> на странице (если сервис отдаёт плеер, а не ссылку).
_JS_FETCH_B64 = """async (src) => {
    const r = await fetch(src); const b = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
}"""
# Что сейчас лежит в результате: ссылка на скачивание и/или плеер.
_JS_RESULT = """() => {
    const p = document.querySelector('section.panel.active') || document;
    const a = p.querySelector('#download, a[download]') || document.querySelector('#download, a[download]');
    const au = p.querySelector('audio') || document.querySelector('audio');
    return [a ? (a.href || '') : '', au ? (au.currentSrc || au.src || '') : ''];
}"""


def synth_sums(logic):
    """Список сумм по логике режима «Суммы»: [(n, {ярус: значение})]."""
    tiers = SYNTH_LOGICS.get(int(logic), SYNTH_LOGICS[1])
    rows = max(len(_TIER_VALUES[t]) for t in tiers)
    out = []
    for k in range(rows):
        parts = {t: _TIER_VALUES[t][min(k, len(_TIER_VALUES[t]) - 1)] for t in tiers}
        group = parts.get('hundreds', 0) + parts.get('hundred_thousands', 0) + parts.get('thousands', 0)
        n = parts.get('millions', 0) * 1_000_000 + group * 1000 + parts.get('tenge', 0)
        out.append((n, parts))
    return out


def synth_text(n, lang):
    return f"{kz_words(n)} теңге" if lang == 'kz' else f"{ru_words(n)} тенге"


def unit_form(word, lang):
    """Слово → форма «миллион/тысячи/тенге…» или None (это число)."""
    w = word.lower().replace('ё', 'е').strip(' .,!?;:«»"\'()-—')
    w = _UNIT_ALIAS.get(lang, {}).get(w, w)
    return w if w in UNIT_FORMS.get(lang, ()) else None


def split_sum_text(text, lang):
    """«два миллиона двести две тысячи два тенге» →
    [('num','два'), ('unit','миллиона'), ('num','двести две'), ('unit','тысячи'), ('num','два'), ('unit','тенге')]"""
    out = []
    for w in str(text).split():
        f = unit_form(w, lang)
        if f:
            out.append(('unit', f))
        elif out and out[-1][0] == 'num':
            out[-1] = ('num', out[-1][1] + ' ' + w)
        else:
            out.append(('num', w))
    return out


def synth_plan(text, lang, bank):
    """Что синтезировать, а что взять живым: [(kind, текст)], kind — 'synth'
    или 'live'. Формы, которой нет в живых словах, синтезируем вместе с числом."""
    plan = []
    for kind, t in split_sum_text(text, lang):
        if kind == 'unit' and t in bank:
            plan.append(['live', t])
        elif plan and plan[-1][0] == 'synth':
            plan[-1][1] += ' ' + t
        else:
            plan.append(['synth', t])
    return plan


class _SynthWorker(threading.Thread):
    """Очередь заданий на синтез и один браузер с открытым сервисом."""

    def __init__(self, owner):
        super().__init__(daemon=True)
        self.owner = owner
        self.jobs = collections.deque()
        self.cv = threading.Condition()
        self.pw = self.browser = self.page = None
        self.current = None
        self.stop_now = False

    # ---- очередь ----
    def add(self, k, front=False):
        with self.cv:
            if k == self.current or k in self.jobs:
                if front and k in self.jobs:
                    self.jobs.remove(k)
                    self.jobs.appendleft(k)
                return False
            (self.jobs.appendleft if front else self.jobs.append)(k)
            self.cv.notify()
            return True

    def clear(self):
        with self.cv:
            dropped = list(self.jobs)
            self.jobs.clear()
            return dropped

    def run(self):
        while True:
            with self.cv:
                while not self.jobs:
                    self.cv.wait()
                k = self.jobs.popleft()
                self.current = k
            try:
                self.owner._synth_job(k, self)
            except Exception as e:                   # браузер упал и т.п. — начнём заново
                self._close()
                self.owner._synth_failed(k, str(e))
            finally:
                with self.cv:
                    self.current = None

    # ---- браузер ----
    def _close(self):
        for obj in (self.browser, self.pw):
            try:
                if obj is self.pw and obj is not None:
                    obj.stop()
                elif obj is not None:
                    obj.close()
            except Exception:
                pass
        self.pw = self.browser = self.page = None

    def page_ready(self):
        if self.page is not None:
            try:
                self.page.title()
                return self.page
            except Exception:
                self._close()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("Для синтеза нужен модуль Playwright. В командной строке выполните:\n"
                               "pip install playwright")
        self.pw = sync_playwright().start()
        args = ["--window-position=-32000,-32000", "--window-size=1600,1000", "--mute-audio"]
        last = None
        exe = os.environ.get('GVOX_BROWSER')               # свой путь к браузеру, если задан
        for channel in (("exe",) if exe else ()) + ("chrome", "msedge", None):   # Chrome / Edge, иначе свой
            try:
                kw = {"headless": False, "args": args}
                if channel == "exe":
                    kw["executable_path"] = exe
                elif channel:
                    kw["channel"] = channel
                self.browser = self.pw.chromium.launch(**kw)
                break
            except Exception as e:
                last = e
        if self.browser is None:
            self._close()
            raise RuntimeError(f"Не удалось открыть браузер (Chrome / Edge): {last}")
        self.page = self.browser.new_page(accept_downloads=True)
        try:
            self.page.goto(SYNTH_URL, timeout=30000)
            self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            self._close()
            raise RuntimeError(f"Сервис синтеза не открылся ({SYNTH_URL}). Проверьте, что он доступен из этой сети.")
        self.page.click(SYNTH_SEL["clone_tab"])
        self.page.wait_for_timeout(400)
        return self.page


class TtsSynthMixin:

    # ---------------- состояние ----------------

    def _synth(self):
        """Состояние синтеза. У каждого языка свои эталон, текст эталона и
        одобренные суммы (sy["per"][lang]); sy["items"] — список текущего языка."""
        st = self._tts()
        sy = st.get("synth")
        if not sy:
            sy = st["synth"] = {"lang": st.get("lang", "ru"), "logic": 1, "items": [], "per": {}}
        sy.setdefault("per", {})
        if "etalon" in sy:                                       # старый формат — один эталон на всё
            sy["per"].setdefault(sy.get("lang", "ru"), {"etalon": sy.pop("etalon"),
                                                         "etalon_text": sy.pop("etalon_text", ''), "store": {}})
        for lg in ('ru', 'kz'):
            sy["per"].setdefault(lg, {"etalon": None, "etalon_text": '', "store": {}})
            sy["per"][lg].setdefault("words", {})                # живые слова: форма → {file, src, gap}
        sy.setdefault("hybrid", True)
        if not sy["items"]:
            self._synth_build(sy)
        return sy

    @staticmethod
    def _synth_lang(sy):
        return sy["per"][sy["lang"]]

    def _synth_lock(self):
        lock = getattr(self, '_synth_lk', None)
        if lock is None:
            lock = self._synth_lk = threading.RLock()
        return lock

    def _synth_build(self, sy):
        """Список сумм текущего языка и логики. Уже сделанное (варианты,
        одобренные) хранится по языку и числу — переключения его не теряют."""
        for it in sy.get("items", []):                           # запомнить, что было
            lg = it.get("lang", sy["lang"])
            if lg in sy["per"]:
                sy["per"][lg]["store"][str(it["n"])] = {k: it.get(k) for k in
                                                        ("text", "status", "variant", "file", "tries", "error", "plan")}
        cur = self._synth_lang(sy)
        items = []
        for k, (n, parts) in enumerate(synth_sums(sy.get("logic", 1))):
            it = {"k": k, "n": n, "parts": parts, "lang": sy["lang"], "text": synth_text(n, sy["lang"]),
                  "status": "idle", "variant": None, "file": None, "tries": 0, "error": None}
            old = cur["store"].get(str(n))
            if old:
                it.update({k2: v for k2, v in old.items() if v is not None})
                if it["status"] in ("queued", "working"):              # не доделано — с нуля
                    it["status"] = "ready" if it.get("variant") else "idle"
            items.append(it)
        sy["items"] = items
        if not cur.get("etalon_text") and items:
            cur["etalon_text"] = items[0]["text"]

    def _synth_dir(self, *sub, lang=None):
        wd = self._tts().get("work_dir")
        if not wd:
            return None
        lg = lang or (self._tts().get("synth") or {}).get("lang", "ru")
        return os.path.join(wd, f"{SYNTH_DIR}_{lg.upper()}", *sub)

    def tts_synth_state(self):
        with self._synth_lock():
            sy = self._synth()
            items = [{**{k: it.get(k) for k in ("k", "n", "text", "status", "error", "tries", "parts", "plan")},
                      "has_variant": bool(it.get("variant") and os.path.exists(it["variant"])),
                      "has_file": bool(it.get("file") and os.path.exists(it["file"]))} for it in sy["items"]]
            w = getattr(self, '_synth_worker', None)
            cur = self._synth_lang(sy)
            return {"etalon": os.path.basename(cur["etalon"]) if cur.get("etalon") else None,
                    "etalon_ok": bool(cur.get("etalon") and os.path.exists(cur["etalon"])),
                    "etalon_text": cur.get("etalon_text", ''), "lang": sy["lang"], "logic": sy.get("logic", 1),
                    "items": items, "has_project": bool(self._tts().get("work_dir")),
                    "approved": sum(1 for it in sy["items"] if it["status"] == "approved"),
                    "queue": len(w.jobs) + (1 if w and w.current is not None else 0) if w else 0,
                    "folder": self._synth_dir(), "hybrid": sy.get("hybrid", True),
                    "words": self._synth_words_info(sy), "words_busy": bool(getattr(self, '_synth_words_busy', False))}

    def _synth_words_info(self, sy):
        """Нужные формы слов (по текстам сумм) и какие из них уже есть живыми."""
        cur = self._synth_lang(sy)
        need = set()
        for it in sy["items"]:
            need.update(t for kind, t in split_sum_text(it["text"], sy["lang"]) if kind == 'unit')
        bank = cur.get("words", {})
        out = []
        for f in UNIT_FORMS[sy["lang"]]:
            w = bank.get(f)
            ok = bool(w and os.path.exists(w.get("file", '')))
            if f in need or ok:
                out.append({"form": f, "ok": ok, "src": w.get("src") if ok else None, "need": f in need})
        return out

    def _synth_push(self, k=None, message=None, error=None):
        self._tts_push({"stage": "synth", "k": k, "message": message, "error": error})

    # ---------------- настройки ----------------

    def tts_synth_pick_etalon(self):
        """Эталон — запись диктора с суммой. Копируем в проект, чтобы не потерялся."""
        st = self._tts()
        if not st.get("work_dir"):
            picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not picked:
                return {"error": "cancel"}
            self._tts_attach_folder(picked if isinstance(picked, str) else picked[0])
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        self._synth()
        dst_dir = self._synth_dir(SYNTH_ETALON)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        with self._synth_lock():
            self._synth_lang(self._synth())["etalon"] = dst
        self._tts_save()
        self.tts_synth_words_find()                       # сразу ищем в нём живые слова
        return self.tts_synth_state()

    def tts_synth_setup(self, lang=None, logic=None, etalon_text=None, hybrid=None):
        """Язык, логика сумм, текст эталона. Смена языка/логики — новый список
        (одобренные с тем же числом и языком остаются)."""
        with self._synth_lock():
            sy = self._synth()
            rebuild = (lang in ('ru', 'kz') and lang != sy["lang"]) or \
                (logic in (1, 2, '1', '2') and int(logic) != sy.get("logic", 1))
            if rebuild:
                self.tts_synth_stop()
                self._synth_build(sy)                            # сохранить сделанное по прежнему языку
                if lang in ('ru', 'kz'):
                    sy["lang"] = lang
                if logic in (1, 2, '1', '2'):
                    sy["logic"] = int(logic)
                sy["items"] = []                                 # пересобрать под новый язык/логику
                self._synth_build(sy)
            if etalon_text is not None:
                self._synth_lang(sy)["etalon_text"] = str(etalon_text).strip()
            if hybrid is not None:
                sy["hybrid"] = bool(hybrid)
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_set_text(self, k, text):
        with self._synth_lock():
            sy = self._synth()
            if 0 <= k < len(sy["items"]):
                sy["items"][k]["text"] = str(text).strip() or synth_text(sy["items"][k]["n"], sy["lang"])
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_play_etalon(self):
        cur = self._synth_lang(self._synth())
        if not cur.get("etalon") or not os.path.exists(cur["etalon"]):
            return {"error": "Эталон не выбран."}
        self.player.play(cur["etalon"])
        return {"playing": True, "duration": len(AudioSegment.from_file(cur["etalon"])) / 1000.0}

    # ---------------- синтез ----------------

    def _synth_worker_get(self):
        w = getattr(self, '_synth_worker', None)
        if w is None or not w.is_alive():
            w = self._synth_worker = _SynthWorker(self)
            w.start()
        return w

    def tts_synth_run(self, k, front=True):
        """Синтезировать (или пересинтезировать) сумму k."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not os.path.exists(cur["etalon"]):
                return {"error": "Сначала выберите эталон — запись диктора с суммой."}
            if not cur.get("etalon_text"):
                return {"error": "Впишите текст эталона — что именно сказано в записи."}
            if not (0 <= k < len(sy["items"])):
                return {"error": "Нет такой суммы."}
            it = sy["items"][k]
            if self._synth_worker_get().add(k, front=front):
                it["status"], it["error"] = "queued", None
        self._synth_push(k)
        return self.tts_synth_state()

    def tts_synth_run_all(self):
        """Поставить в очередь все суммы, у которых ещё нет варианта."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not cur.get("etalon_text"):
                return {"error": "Сначала эталон и его текст."}
            w = self._synth_worker_get()
            for it in sy["items"]:
                if it["status"] in ("idle", "error") and w.add(it["k"]):
                    it["status"], it["error"] = "queued", None
        self._synth_push()
        return self.tts_synth_state()

    def tts_synth_stop(self):
        w = getattr(self, '_synth_worker', None)
        with self._synth_lock():
            sy = self._tts().get("synth") or {"items": []}
            for k in (w.clear() if w else []):
                if 0 <= k < len(sy["items"]) and sy["items"][k]["status"] == "queued":
                    sy["items"][k]["status"] = "ready" if sy["items"][k].get("variant") else "idle"
        self._synth_push()
        return self.tts_synth_state()

    def _synth_prefetch(self, after):
        """Пока вы слушаете — следующие суммы уже синтезируются."""
        sy = self._synth()
        w = self._synth_worker_get()
        n = 0
        for it in sy["items"][after + 1:]:
            if n >= SYNTH_PREFETCH:
                break
            if it["status"] in ("idle",) and w.add(it["k"]):
                it["status"] = "queued"
                n += 1
            elif it["status"] in ("queued", "working", "ready"):
                n += 1

    def _synth_job(self, k, worker):
        """Одна сумма: в гибриде — каждое число отдельным запросом и склейка
        с живыми словами; без гибрида — вся фраза одним запросом."""
        with self._synth_lock():
            sy = self._synth()
            it = sy["items"][k]
            it["status"], it["error"] = "working", None
            cur = self._synth_lang(sy)
            etalon, etalon_text, lang, text = cur["etalon"], cur["etalon_text"], sy["lang"], it["text"]
            bank = {f: dict(w) for f, w in cur.get("words", {}).items()
                    if os.path.exists(w.get("file", ''))} if sy.get("hybrid", True) else {}
            vdir = self._synth_dir(SYNTH_VARIANTS, lang=lang)
            tries = it.get("tries", 0) + 1
        self._synth_push(k)
        os.makedirs(vdir, exist_ok=True)
        plan = synth_plan(text, lang, bank)
        dst = os.path.join(vdir, f"{k + 1:04d}_v{tries}.wav")
        if not any(kind == 'live' for kind, _t in plan):
            plan = [['synth', text]]
            self._synth_request(worker, etalon, etalon_text, lang, text, dst)
        else:
            parts = []
            for i, (kind, t) in enumerate(plan):
                if kind == 'live':
                    parts.append(('live', bank[t]["file"], bank[t].get("gap")))
                else:
                    piece = os.path.join(vdir, f"{k + 1:04d}_v{tries}_{i + 1}.wav")
                    self._synth_request(worker, etalon, etalon_text, lang, t, piece)
                    parts.append(('synth', piece, None))
            self._synth_glue(parts, dst)
        with self._synth_lock():
            sy = self._synth()
            if sy["lang"] != lang or k >= len(sy["items"]) or sy["items"][k]["text"] != text:
                # пока синтезировали — сменили язык/логику: вариант сохраним в его язык
                sy["per"][lang]["store"].setdefault(str(it["n"]), {}).update(
                    {"variant": dst, "status": "ready", "tries": tries, "text": text, "plan": plan})
                self._tts_save()
                return
            it = sy["items"][k]
            it.update({"variant": dst, "status": "ready", "tries": tries, "error": None, "plan": plan})
        self._tts_save()
        self._synth_push(k, message=f"Готово: {it['n']:,}".replace(',', ' '))

    def _synth_request(self, worker, etalon, etalon_text, lang, text, dst):
        """Шаги на сайте (в потоке браузера): один текст → WAV в dst."""
        page = worker.page_ready()
        sel = SYNTH_SEL
        page.select_option(sel["lang"], index=SYNTH_LANG_INDEX.get(lang, 0))
        page.set_input_files(sel["etalon_file"], etalon)
        page.fill(sel["etalon_text"], etalon_text)
        page.fill(sel["text"], text)
        before = page.evaluate(_JS_RESULT)
        downloads = []

        def handler(d):                      # сервис мог сразу отдать файл на скачивание
            downloads.append(d)
        page.on("download", handler)
        raw = os.path.splitext(dst)[0] + '.download'
        try:
            page.click(sel["submit"])
            t_end = time.time() + SYNTH_TIMEOUT_S
            now = before
            while time.time() < t_end:
                page.wait_for_timeout(300)
                if downloads:
                    break
                now = page.evaluate(_JS_RESULT)
                if (now[0] and now[0] != before[0]) or (now[1] and now[1] != before[1]):
                    break
            else:
                raise RuntimeError("Сервис не вернул результат за 3 минуты.")
            if downloads:
                downloads[0].save_as(raw)
            elif now[0] and now[0] != before[0]:
                with page.expect_download(timeout=60000) as dl:
                    page.locator('section.panel.active #download, section.panel.active a[download], #download').first.click()
                dl.value.save_as(raw)
            else:
                import base64
                data = base64.b64decode(page.evaluate(_JS_FETCH_B64, now[1]))
                with open(raw, 'wb') as f:
                    f.write(data)
        finally:
            try:
                page.remove_listener("download", handler)
            except Exception:
                pass
        if wav_layout(raw):
            os.replace(raw, dst)                     # WAV — как есть, без перекодирования
        else:
            try:
                AudioSegment.from_file(raw).export(dst, format="wav")
            finally:
                try:
                    os.remove(raw)
                except OSError:
                    pass

    # ---------------- гибрид: живые слова ----------------

    @staticmethod
    def _seg_trim(seg, lead=15, tail=30):
        """Срезать тишину по краям синтезированного куска — почти вплотную."""
        if not len(seg) or seg.max_dBFS == float('-inf'):
            return seg
        thr = max(-50.0, seg.max_dBFS - 35.0)
        a = detect_leading_silence(seg, silence_threshold=thr, chunk_size=5)
        b = len(seg) - detect_leading_silence(seg.reverse(), silence_threshold=thr, chunk_size=5)
        if b - a < 40:
            return seg
        return seg[max(0, a - lead):min(len(seg), b + tail)]

    @classmethod
    def _synth_glue(cls, parts, dst):
        """Склейка: синтезированные числа + живые слова. Числа приводим к
        формату и громкости живых слов (голос диктора — эталон)."""
        segs = [(kind, AudioSegment.from_file(path), gap) for kind, path, gap in parts]
        live = [sg for kind, sg, _g in segs if kind == 'live' and len(sg) and sg.dBFS != float('-inf')]
        ref = live[0] if live else segs[0][1]
        target = sum(sg.dBFS for sg in live) / len(live) if live else None
        out, prev = None, None
        for kind, sg, gap in segs:
            sg = sg.set_frame_rate(ref.frame_rate).set_channels(ref.channels).set_sample_width(ref.sample_width)
            if kind == 'synth':
                sg = cls._seg_trim(sg)
                if target is not None and sg.dBFS != float('-inf'):
                    sg = sg.apply_gain(max(-12.0, min(12.0, target - sg.dBFS)))
            if out is None:
                out = AudioSegment.silent(60, frame_rate=ref.frame_rate) + sg
            elif prev[0] == 'synth' and kind == 'live':
                out = out.append(sg, crossfade=max(1, min(GLUE_XFADE_MS, len(sg) // 4, len(out) // 4)))
            else:
                pause = prev[1] if prev[0] == 'live' and prev[1] is not None else GLUE_GAP_MS
                out += AudioSegment.silent(int(pause), frame_rate=ref.frame_rate) + sg
            prev = (kind, gap)
        out += AudioSegment.silent(90, frame_rate=ref.frame_rate)
        out.export(dst, format="wav")

    @staticmethod
    def _word_cut(seg, s_ms, e_ms):
        """Уточнить края слова по тишине рядом с отметками распознавания:
        Whisper ошибается на десятки миллисекунд — режем в самом тихом месте."""
        def rms(a):
            return seg[a:a + 5].rms if a + 5 <= len(seg) else 0

        def quiet_near(lo, hi, aim):
            lo, hi = max(0, int(lo)), min(len(seg) - 5, int(hi))
            if hi <= lo:
                return int(aim)
            vals = [(rms(a), a) for a in range(lo, hi, 5)]
            floor = min(v for v, _a in vals)
            calm = [a for v, a in vals if v <= floor * 1.6 + 2]
            return min(calm, key=lambda a: abs(a - aim))
        a = quiet_near(s_ms - 110, s_ms + 30, s_ms)
        b = quiet_near(e_ms - 30, e_ms + 140, e_ms)
        return a, max(b, a + 60)

    def tts_synth_words_find(self, extra=False):
        """Найти живые слова: в эталоне или (extra) в любой другой записи
        диктора, где сказаны нужные формы («миллиона», «тысяч»…). Распознавание
        (Whisper) идёт в фоне — по готовности придёт событие."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            lang = sy["lang"]
            if getattr(self, '_synth_words_busy', False):
                return {"error": "Уже ищу слова — подождите."}
            if extra:
                picked = webview.windows[0].create_file_dialog(
                    webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
                if not picked:
                    return {"error": "cancel"}
                path, hint = (picked if isinstance(picked, str) else picked[0]), ''
            else:
                path, hint = cur.get("etalon"), cur.get("etalon_text", '')
                if not path or not os.path.exists(path):
                    return {"error": "Сначала выберите эталон."}
            self._synth_words_busy = True
        threading.Thread(target=self._synth_words_run, args=(path, hint, lang), daemon=True).start()
        self._synth_push(message="Ищу живые слова в записи…")
        return self.tts_synth_state()

    def _synth_words_run(self, path, hint, lang):
        try:
            found = self._synth_words_extract(path, hint, lang)
            if found:
                msg = "Живые слова: " + ", ".join(found)
            else:
                msg = None
                self._synth_push(error="В записи не нашёл ни «миллион», ни «тысяч», ни «тенге». "
                                       "Проверьте язык и текст эталона.")
        except Exception as e:
            msg = None
            self._synth_push(error=f"Не удалось найти слова: {e}")
        finally:
            self._synth_words_busy = False
        self._tts_save()
        self._synth_push(message=msg)

    def _synth_words_extract(self, path, hint, lang):
        """Распознать запись, вырезать «миллион/тысяча/тенге» в «_слова/»."""
        model, err = self._auto_check_model(lang)
        if err:
            raise RuntimeError(err)
        samples, ms, _peak = self._asr_load(path)
        forms = ' '.join(UNIT_FORMS[lang])
        words = self._tts_transcribe_pack(model, [{"index": 0, "audio": samples, "ms": ms}],
                                          'kk' if lang == 'kz' else 'ru',
                                          hotwords=(hint + ' ' + forms).strip())[0]
        seg = AudioSegment.from_file(path)
        wdir = self._synth_dir(SYNTH_WORDS, lang=lang)
        os.makedirs(wdir, exist_ok=True)
        found = []
        for i, (w, s, e) in enumerate(words):
            f = unit_form(w, lang)
            if not f:
                continue
            a, b = self._word_cut(seg, s * 1000, e * 1000)
            gap = None
            if i + 1 < len(words):                     # пауза после слова, как у диктора
                gap = max(20, min(250, int(words[i + 1][1] * 1000 - b)))
            out = os.path.join(wdir, f"{f}.wav")
            seg[a:b].fade_in(5).fade_out(10).export(out, format="wav")
            with self._synth_lock():
                self._synth()["per"][lang]["words"][f] = {"file": out, "src": os.path.basename(path), "gap": gap}
            if f not in found:
                found.append(f)
        return found

    def tts_synth_word_play(self, form):
        w = self._synth_lang(self._synth()).get("words", {}).get(form)
        if not w or not os.path.exists(w.get("file", '')):
            return {"error": "Этого слова пока нет."}
        self.player.play(w["file"])
        return {"playing": True}

    def tts_synth_word_remove(self, form):
        """Убрать живое слово — эта форма снова пойдёт в синтез."""
        with self._synth_lock():
            self._synth_lang(self._synth()).get("words", {}).pop(form, None)
        self._tts_save()
        return self.tts_synth_state()

    def _synth_failed(self, k, error):
        with self._synth_lock():
            sy = self._tts().get("synth") or {"items": []}
            if 0 <= k < len(sy["items"]):
                it = sy["items"][k]
                it["status"] = "ready" if it.get("variant") else "error"
                it["error"] = error
        self._tts_save()
        self._synth_push(k, error=error)

    # ---------------- прослушка и одобрение ----------------

    def tts_synth_play(self, k, final=False):
        sy = self._synth()
        if not (0 <= k < len(sy["items"])):
            return {"error": "Нет такой суммы."}
        it = sy["items"][k]
        path = it.get("file") if final else (it.get("variant") or it.get("file"))
        if not path or not os.path.exists(path):
            return {"error": "Эта сумма ещё не синтезирована."}
        self.player.play(path)
        return {"playing": True, "duration": len(AudioSegment.from_file(path)) / 1000.0}

    @staticmethod
    def _synth_trim(src, dst):
        """Обрезать тишину по краям (с запасом), байт в байт."""
        seg = AudioSegment.from_file(src)
        if not len(seg) or seg.max_dBFS == float('-inf'):
            shutil.copy2(src, dst)
            return
        thr = max(-55.0, seg.max_dBFS - 40.0)
        a = detect_leading_silence(seg, silence_threshold=thr, chunk_size=10)
        b = len(seg) - detect_leading_silence(seg.reverse(), silence_threshold=thr, chunk_size=10)
        a, b = max(0, a - 60), min(len(seg), b + 90)
        if b - a < 100 or not wav_slice(src, dst, a, b):
            shutil.copy2(src, dst)

    def tts_synth_approve(self, k):
        """Вариант звучит верно → в «Синтез_суммы_RU/» (_KZ) (тишина по краям обрезана),
        и сразу синтезируются следующие."""
        with self._synth_lock():
            sy = self._synth()
            if not (0 <= k < len(sy["items"])):
                return {"error": "Нет такой суммы."}
            it = sy["items"][k]
            if not it.get("variant") or not os.path.exists(it["variant"]):
                return {"error": "Сначала синтезируйте эту сумму."}
            folder = self._synth_dir()
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, f"{k + 1:04d}_{it['n']}.wav")
            self._synth_trim(it["variant"], dst)
            it["file"], it["status"] = dst, "approved"
            self._synth_prefetch(k)
        self._tts_save()
        self._synth_push(k)
        return self.tts_synth_state()

    def tts_synth_etalon_as_first(self):
        """Эталон и есть первая сумма — берём его как одобренный №1."""
        with self._synth_lock():
            sy = self._synth()
            cur = self._synth_lang(sy)
            if not cur.get("etalon") or not sy["items"]:
                return {"error": "Сначала выберите эталон."}
            it = sy["items"][0]
            folder = self._synth_dir()
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, f"{1:04d}_{it['n']}.wav")
            self._synth_trim(cur["etalon"], dst)
            it.update({"variant": cur["etalon"], "file": dst, "status": "approved", "error": None})
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_unapprove(self, k):
        with self._synth_lock():
            sy = self._synth()
            if 0 <= k < len(sy["items"]):
                it = sy["items"][k]
                if it.get("file") and os.path.exists(it["file"]):
                    try:
                        self._tts_trash(it["file"])
                    except Exception:
                        pass
                it["file"] = None
                it["status"] = "ready" if it.get("variant") else "idle"
        self._tts_save()
        return self.tts_synth_state()

    def tts_synth_sums_folder(self):
        """Папка одобренных сумм — для режима «Суммы»."""
        folder = self._synth_dir()
        if not folder or not os.path.isdir(folder) or not any(
                f.lower().endswith('.wav') for f in os.listdir(folder)):
            return {"error": "Пока нет ни одной одобренной суммы."}
        self.tts_synth_stop()
        return {"folder": folder}
