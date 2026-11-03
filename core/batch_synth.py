"""Синтез по таблице — отдельная утилита.

Excel (первая строка — заголовки: <firstname>, <surname>, <patronymic>…) →
каждое значение синтезируется готовым голосом сервиса по очереди: строка 1
слева направо, потом строка 2 и т. д. Сколько строк и с какой — спрашиваем.

Сервис не любит нагрузку: запросы идут строго по одному, между ними пауза;
ошибка — повтор с ожиданием, три значения подряд не вышли — очередь встаёт
на паузу (сервис, видимо, лёг). Файлы: рядом с таблицей,
«Синтез_<таблица>/<столбец>/<значение>.wav»; уже готовые не трогаем, одно и то
же значение в столбце синтезируется один раз."""
import json
import os
import re
import threading
import time

import webview

from core.tts_flow import clean_name
from core.tts_synth import (_SynthWorker, SYNTH_LANGS, SYNTH_PRESET_SEL, SYNTH_PRESET_VOICES, clean_wav,
                            preset_pick, synth_collect)

BSYNTH_DIR = 'Синтез_'                 # + имя таблицы
BSYNTH_VOICE = 7                        # #preset-voice > option:nth-child(8)
BSYNTH_LANG = 2                         # #preset-lang > option:nth-child(3) — турецкий
BSYNTH_DELAY_S = 4                      # пауза между запросами
BSYNTH_RETRY_S = (10, 30)               # ошибка — повтор через столько секунд
BSYNTH_FAIL_STOP = 3                    # подряд не вышло — пауза очереди


def tr_title(text, turkish=True):
    """«GÜNAYDIN AVCİ» → «Günaydın Avci»: в каждом слове заглавная только первая буква.
    Турецкие пары: I ↔ ı, İ ↔ i (обычные upper/lower их путают: «İ».lower() — «i̇»)."""
    def low(w):
        return (w.replace('I', 'ı').replace('İ', 'i') if turkish else w).lower()

    def up(c):
        return {'i': 'İ', 'ı': 'I'}.get(c, c.upper()) if turkish else c.upper()

    def word(m):
        w = low(m.group(0))
        return up(w[0]) + w[1:]
    return re.sub(r"[^\W\d_]+", word, str(text))


class BatchSynthMixin:

    def _bs(self):
        bs = self.__dict__.get('_bsynth')
        if bs is None:
            bs = self._bsynth = {"path": None, "sheet": None, "sheets": [], "cols": [], "rows": [], "items": [],
                                 "pos": 0, "run": False, "pause": False, "stop": False, "msg": '', "voice_name": '',
                                 "started": None, "spent": 0.0, "n_synth": 0, "out_dir": None}
        return bs

    # ---- таблица ----
    def bsynth_pick_excel(self):
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                  file_types=('Excel (*.xlsx;*.xlsm)', 'Все файлы (*.*)'))
        if not f:
            return None
        return self.bsynth_load(f[0] if isinstance(f, (list, tuple)) else f)

    def bsynth_load(self, path, sheet=None):
        bs = self._bs()
        if bs["run"]:
            return {"error": "Идёт синтез — сначала остановите его."}
        import openpyxl
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:
            return {"error": f"Не удалось открыть таблицу: {e}"}
        try:
            sheets = []
            for ws in wb.worksheets:
                rows = [["" if v is None else str(v).strip() for v in r] for r in ws.iter_rows(values_only=True)]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                head = rows[0]
                cols = [k for k, h in enumerate(head) if h]
                body = [[r[k] if k < len(r) else '' for k in cols] for r in rows[1:]]
                body = [r for r in body if any(r)]
                sheets.append({"title": ws.title, "cols": [head[k] for k in cols], "rows": body})
        finally:
            wb.close()
        if not sheets:
            return {"error": "В таблице нет данных."}
        sh = next((s for s in sheets if s["title"] == sheet), None) or max(sheets, key=lambda s: len(s["rows"]))
        bs.update(path=path, sheet=sh["title"], sheets=[s["title"] for s in sheets], cols=sh["cols"], rows=sh["rows"],
                  items=[], pos=0, msg='')
        bs["out_dir"] = os.path.join(os.path.dirname(path), BSYNTH_DIR + os.path.splitext(os.path.basename(path))[0])
        return self.bsynth_state()

    @staticmethod
    def _bs_col_dir(col):
        return clean_name(re.sub(r'[<>]', '', col)) or 'столбец'

    def _bs_file(self, col, value):
        bs = self._bs()
        return os.path.join(bs["out_dir"], self._bs_col_dir(col), f"{clean_name(value) or 'пусто'}.wav")

    # ---- очередь ----
    def bsynth_start(self, start_row=1, count=None, delay_s=BSYNTH_DELAY_S, voice=BSYNTH_VOICE, lang=BSYNTH_LANG):
        """Синтезировать строки start_row … start_row+count-1 (с 1, как в таблице без шапки)."""
        bs = self._bs()
        if bs["run"]:
            return {"error": "Синтез уже идёт."}
        if not bs["rows"]:
            return {"error": "Сначала выберите таблицу."}
        a = max(1, int(start_row or 1)) - 1
        n = len(bs["rows"]) - a if not count else max(1, int(count))
        items, seen = [], {}
        rep = {col: {"col": col, "rows": 0, "empty": 0, "repeats": {}} for col in bs["cols"]}
        for r in range(a, min(len(bs["rows"]), a + n)):
            for c, col in enumerate(bs["cols"]):
                v = bs["rows"][r][c]
                rep[col]["rows"] += 1
                if not v:
                    rep[col]["empty"] += 1
                    continue
                f = self._bs_file(col, v)
                key = os.path.normcase(f).upper()          # Windows не различает регистр имён (и ı = I)
                if key in seen:                            # то же значение в столбце — один файл
                    first = seen[key]
                    rep[col]["repeats"].setdefault(first["value"], [first["row"]]).append(r + 1)
                    continue
                items.append({"row": r + 1, "col": col, "value": v, "file": f, "text": tr_title(v, int(lang) == BSYNTH_LANG),
                              "status": "done" if os.path.exists(f) else "wait", "error": ''})
                seen[key] = items[-1]
        if not items:
            return {"error": "В выбранных строках нет значений."}
        bs["report"] = list(rep.values())
        bs.update(items=items, pos=0, run=True, pause=False, stop=False, msg='', started=time.time(), spent=0.0,
                  n_synth=0, delay=max(1.0, float(delay_s or BSYNTH_DELAY_S)), voice=int(voice), lang=int(lang))
        threading.Thread(target=self._bs_loop, daemon=True).start()
        return self.bsynth_state()

    def bsynth_pause(self, on=True):
        bs = self._bs()
        bs["pause"] = bool(on)
        if not on:
            bs["msg"] = ''
        self._bs_push()
        return self.bsynth_state()

    def bsynth_stop(self):
        bs = self._bs()
        bs["stop"], bs["pause"] = True, False
        self._bs_push()
        return self.bsynth_state()

    def bsynth_retry_failed(self):
        bs = self._bs()
        if bs["run"]:
            return {"error": "Синтез ещё идёт."}
        failed = [it for it in bs["items"] if it["status"] == "error"]
        if not failed:
            return {"error": "Ошибок нет."}
        for it in failed:
            it["status"], it["error"] = "wait", ''
        bs.update(run=True, pause=False, stop=False, msg='', pos=0)
        threading.Thread(target=self._bs_loop, daemon=True).start()
        return self.bsynth_state()

    def bsynth_open_folder(self):
        d = self._bs().get("out_dir")
        if d and os.path.isdir(d):
            os.startfile(d)
        return {"ok": bool(d)}

    def bsynth_state(self):
        bs = self._bs()
        items = bs["items"]
        cnt = {s: sum(1 for it in items if it["status"] == s) for s in ("done", "ok", "error", "wait", "busy")}
        cur = next((it for it in items if it["status"] == "busy"), None)
        left = cnt["wait"] + cnt["busy"]
        avg = bs["spent"] / bs["n_synth"] if bs["n_synth"] else None
        return {"path": bs["path"], "sheet": bs["sheet"], "sheets": bs["sheets"], "cols": bs["cols"],
                "total_rows": len(bs["rows"]), "preview": bs["rows"][:3], "out_dir": bs["out_dir"],
                "run": bs["run"], "pause": bs["pause"], "msg": bs["msg"], "voice_name": bs["voice_name"],
                "total": len(items), "done": cnt["done"] + cnt["ok"], "made": cnt["ok"], "skipped": cnt["done"],
                "errors": cnt["error"], "left": left, "current": cur,
                "eta_s": round(left * (avg + bs.get("delay", BSYNTH_DELAY_S))) if avg is not None and left else None,
                "recent": [it for it in items if it["status"] in ("ok", "error")][-6:],
                "report": self._bs_report() if items else None,
                "failed": [it for it in items if it["status"] == "error"][:30],
                "voices": [{"index": i, "label": l} for i, l in SYNTH_PRESET_VOICES],
                "langs": [{"index": i, "label": l} for i, l in SYNTH_LANGS],
                "defaults": {"voice": BSYNTH_VOICE, "lang": BSYNTH_LANG, "delay": BSYNTH_DELAY_S}}

    def _bs_report(self):
        """По столбцам: строк → файлов; повторы и пустые ячейки — почему файлов меньше, чем строк."""
        bs = self._bs()
        out = []
        for r in bs.get("report") or []:
            mine = [it for it in bs["items"] if it["col"] == r["col"]]
            have = sum(1 for it in mine if os.path.exists(it["file"]))
            reps = sorted(r["repeats"].items(), key=lambda kv: -len(kv[1]))
            out.append({"col": r["col"], "rows": r["rows"], "empty": r["empty"], "files": len(mine), "have": have,
                        "repeat_n": sum(len(v) - 1 for _k, v in reps),
                        "repeats": [{"value": k, "rows": v} for k, v in reps[:40]]})
        return out

    def _bs_push(self):
        try:
            webview.windows[0].evaluate_js(f"bsynthEvent({json.dumps(self.bsynth_state(), ensure_ascii=False)})")
        except Exception:
            pass

    # ---- работа: строго по одному, с паузами ----
    def _bs_wait(self, seconds):
        """Пауза между запросами; на «паузе» — ждём; «стоп» — выходим (False)."""
        bs = self._bs()
        t_end = time.time() + seconds
        while time.time() < t_end or bs["pause"]:
            if bs["stop"]:
                return False
            time.sleep(0.2)
        return not bs["stop"]

    def _bs_loop(self):
        bs = self._bs()
        worker = _SynthWorker(self)                      # только браузер; поток — этот
        worker.tab = 'preset'
        fails = 0
        try:
            first = True
            for it in bs["items"]:
                if it["status"] != "wait":
                    continue
                if not first and not self._bs_wait(bs["delay"]):
                    break
                if bs["stop"] or not self._bs_wait(0):
                    break
                first = False
                it["status"] = "busy"
                self._bs_push()
                ok = False
                for attempt in range(len(BSYNTH_RETRY_S) + 1):
                    t0 = time.time()
                    try:
                        self._bs_one(worker, it)
                        bs["spent"] += time.time() - t0
                        bs["n_synth"] += 1
                        ok = True
                        break
                    except Exception as e:
                        it["error"] = str(e)
                        worker._close()                    # браузер — заново
                        if attempt < len(BSYNTH_RETRY_S):
                            bs["msg"] = f"Ошибка, повтор через {BSYNTH_RETRY_S[attempt]} с: {e}"
                            self._bs_push()
                            if not self._bs_wait(BSYNTH_RETRY_S[attempt]):
                                break
                if bs["stop"] and not ok:
                    it["status"] = "wait"
                    break
                it["status"] = "ok" if ok else "error"
                bs["msg"] = ''
                fails = 0 if ok else fails + 1
                if fails >= BSYNTH_FAIL_STOP:
                    bs["pause"] = True
                    bs["msg"] = (f"{fails} значения подряд не синтезировались — очередь на паузе. "
                                 f"Проверьте сервис и нажмите «Продолжить».")
                    fails = 0
                self._bs_push()
        finally:
            worker._close()
            for it in bs["items"]:
                if it["status"] == "busy":
                    it["status"] = "wait"
            bs["run"] = False
            if bs["stop"]:
                bs["msg"] = "Остановлено."
            self._bs_push()

    def _bs_one(self, worker, it):
        bs = self._bs()
        page = worker.page_ready()
        sel = SYNTH_PRESET_SEL
        voice = lambda: preset_pick(page, sel["voice"], bs["voice"])
        # Сервис сбрасывает голос после «Синтезировать» и при догрузке списка —
        # язык и голос перед каждым значением, голос — ещё раз сразу после нажатия.
        page.fill(sel["text"], it.get("text") or it["value"])      # «BERİTAN» → «Beritan» (tr_title)
        preset_pick(page, sel["lang"], bs["lang"])
        bs["voice_name"] = voice() or bs["voice_name"]
        os.makedirs(os.path.dirname(it["file"]), exist_ok=True)
        raw = os.path.splitext(it["file"])[0] + '.download'
        try:
            synth_collect(page, sel["submit"], raw, after_click=voice)
            clean_wav(raw, it["file"])
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass
