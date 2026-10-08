"""TTS-процесс: одна запись целых фраз → нарезка → автопроверка по таблице →
прослушка и апрув.

Таблица («ТТС RU.xlsx»):
  • лист фраз — шапка с <phrase>, <name_phrase>, флагами <start>/<start_2>/<end>
    и колонками переменных (<sum_ru>, <date_ru>…), где 1 = переменная здесь;
  • листы переменных с тем же именем, что колонка (<sum_ru>, <date_ru>):
    каждая колонка листа — категория значений (<million_ru>, <day_ru>…).

Строки с флагами складываются в «цепочку» — одна произнесённая фраза,
разрезанная переменными: start → [сумма] → start_2 → [дата] → end. Такую
фразу диктор читает целиком (с примером значения), поэтому для сверки и
сохранения она — один «юнит». Готовый дубль цепочки уходит в
«Фразы_Переменные», обычной фразы — в «Проверенные». Сохраняем только
после того, как дубль прослушан: автопроверка ошибается."""

import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import openpyxl
import webview
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core import recent_projects
from core.auto_check import (ASR_RATE, NEED_MODEL, NOISE_MAX_DBFS, NOISE_MIN_MS,
                             SPEECH_MIN_SCORE, similarity)
from core.ui_dialogs import ui_confirm

TTS_STATE_FILE = 'tts_project.json'
TTS_CHUNKS_DIR = 'Чанки'
TTS_DONE_DIR = 'Проверенные'
TTS_VAR_DIR = 'Фразы_Переменные'
TTS_TRASH_DIR = '_Корзина'
TTS_CUT_PAD_MS = 150
TTS_OK_SCORE = 0.80       # дубль «зелёный» — совпал с текстом
TTS_OK_MARGIN = 0.10      # …и заметно лучше второго варианта
TTS_TIE = 0.03            # почти равные варианты — решает порядок записи
TTS_LISTEN_SHARE = 0.8    # «прослушан» = отыграл хотя бы 80% длины

FLAG_COLS = ('start', 'start_2', 'end')
BAD_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _tag(v):
    """'<sum_ru>' → 'sum_ru'; не тег — None."""
    s = str(v or '').strip()
    m = re.fullmatch(r'<\s*([^<>]+?)\s*>', s)
    return m.group(1).strip().lower() if m else None


def _flag(v):
    return v not in (None, '', 0, '0') and str(v).strip() not in ('', '0')


def _lang_of(name):
    low = (name or '').lower()
    if re.search(r'(^|[_\s-])(kz|kk|kaz)([_\s>-]|$)', low):
        return 'kz'
    return 'ru'


def var_label(key):
    k = (key or '').lower()
    base = re.sub(r'_(ru|kz|kk)$', '', k)
    names = {'sum': 'Сумма', 'date': 'Дата', 'million': 'Миллионы', 'hundred_thousand': 'Сотни тысяч',
             'thousand': 'Тысячи', 'hundred': 'Сотни', 'tenge': 'Тенге', 'day': 'День', 'month': 'Месяц',
             'year': 'Год', 'name': 'Имя', 'time': 'Время'}
    label = names.get(base, base or k)
    lang = re.search(r'_(ru|kz|kk)$', k)
    return f"{label} {lang.group(1).upper()}" if lang and label != k else label


def clean_name(text):
    name = BAD_NAME.sub(' ', str(text)).strip()
    return re.sub(r'\s+', ' ', name).rstrip('. ')[:120]


def _common_name(names):
    """ru_da_1_1, ru_da_1_2, ru_da_1_3 → ru_da_1."""
    names = [n for n in names if n]
    if not names:
        return ''
    if len(names) == 1:
        return names[0]
    pref = os.path.commonprefix(names)
    pref = re.sub(r'[_\-\s]+\d*$', '', pref) if not pref.endswith(('_', '-', ' ')) else pref.rstrip('_- ')
    return pref or names[0]


def parse_tts_workbook(path):
    """Разбирает таблицу. {phrase_sheets: [...], var_sheets: {...}}."""
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets, var_sheets = [], {}
    for ws in wb.worksheets:
        rows = [r for r in ws.iter_rows(values_only=True)]
        if not rows:
            continue
        head_idx = None
        for i, r in enumerate(rows[:10]):
            if any(_tag(c) == 'phrase' for c in r):
                head_idx = i
                break
        if head_idx is not None:
            sheets.append(_parse_phrase_sheet(ws.title, rows, head_idx))
            continue
        head = rows[0]
        cols = [(c, _tag(h)) for c, h in enumerate(head) if _tag(h)]
        if not cols:
            continue
        cats = []
        for c, key in cols:
            seen, values = set(), []
            for r in rows[1:]:
                v = r[c] if c < len(r) else None
                if v is None or str(v).strip() == '':
                    continue
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                s = str(v).strip()
                if s not in seen:          # повторы-«заглушки» (100 после 900) не нужны
                    seen.add(s)
                    values.append(s)
            cats.append({"key": key, "label": var_label(key), "values": values})
        var_sheets[_tag(ws.title) or ws.title.strip().lower()] = {
            "title": ws.title, "label": var_label(_tag(ws.title) or ws.title), "categories": cats}
    wb.close()
    return {"phrase_sheets": sheets, "var_sheets": var_sheets}


def _parse_phrase_sheet(title, rows, head_idx):
    head = rows[head_idx]
    col = {}
    for c, h in enumerate(head):
        t = _tag(h)
        if t:
            col.setdefault(t, c)
    text_c, name_c = col.get('phrase'), col.get('name_phrase')
    var_cols = [(t, c) for t, c in col.items() if t not in ('phrase', 'name_phrase') + FLAG_COLS]

    def cell(r, c):
        return r[c] if c is not None and c < len(r) else None

    lines = []
    for i, r in enumerate(rows[head_idx + 1:], start=head_idx + 2):
        text = str(cell(r, text_c) or '').strip()
        name = clean_name(cell(r, name_c) or '')
        role = next((f for f in FLAG_COLS if _flag(cell(r, col.get(f)))), None)
        vars_ = [t for t, c in var_cols if _flag(cell(r, c))]
        if not text and not name and not role:
            continue
        lines.append({"row": i, "text": text, "name": name or f"фраза_{i:04d}", "role": role, "vars": vars_})

    # Юниты: обычная фраза или цепочка start [start_2…] [end].
    units, chain = [], None

    def close():
        nonlocal chain
        if chain:
            units.append(_make_chain(chain, len(units)))
        chain = None

    for ln in lines:
        if ln["role"] == 'start':
            close()
            chain = [ln]
        elif ln["role"] in ('start_2', 'end') and chain:
            chain.append(ln)
            if ln["role"] == 'end':
                close()
        elif ln["role"] in ('start_2', 'end'):
            chain = [ln]          # цепочка без start — всё равно фраза с переменной
            if ln["role"] == 'end':
                close()
        else:
            close()
            units.append({"id": len(units), "kind": "phrase", "name": ln["name"], "text": ln["text"],
                          "parts": [ln], "rows": [ln["row"]]})
    close()
    for u in units:
        if not u["text"]:
            u["text"] = u["name"]
    return {"title": title, "lang": _lang_of(title), "units": units,
            "var_keys": [t for t, _ in var_cols]}


def _make_chain(parts, uid):
    """Слоты: текст и переменная после него. У start/start_2 переменная —
    следующая; у end отмеченная колонка — та, что перед ним (уже учтена)."""
    slots = []
    for k, p in enumerate(parts):
        var = None
        if p["role"] in ('start', 'start_2'):
            var = p["vars"][0] if p["vars"] else None
            if var is None and k + 1 < len(parts) and parts[k + 1]["vars"]:
                var = parts[k + 1]["vars"][0]
        slots.append({"row": p["row"], "name": p["name"], "role": p["role"], "text": p["text"], "var": var})
    display = []
    for s in slots:
        if s["text"]:
            display.append(s["text"])
        if s["var"]:
            display.append(f"[{var_label(s['var'])}]")
    return {"id": uid, "kind": "chain", "name": _common_name([p["name"] for p in parts]),
            "text": ' '.join(display), "parts": slots, "rows": [p["row"] for p in parts],
            "vars": [s["var"] for s in slots if s["var"]]}


def unit_score(heard, unit):
    """Цепочку читают с примером значения внутри — сверяем каждую текстовую
    часть отдельно (она — «окно» в услышанном) и берём среднее."""
    if unit["kind"] == "phrase":
        return similarity(heard, unit["text"])
    parts = [p["text"] for p in unit["parts"] if p["text"]]
    if not parts:
        return 0.0
    return sum(similarity(heard, t) for t in parts) / len(parts)


def match_takes(heards, units):
    """Каждому дублю — лучший юнит. Почти равные варианты (одинаковые
    тексты) решаем порядком: диктор читает таблицу сверху вниз."""
    out, expected = [], 0
    for heard in heards:
        if not heard:
            out.append({"unit": None, "score": 0.0, "status": "noise"})
            continue
        scored = sorted(((unit_score(heard, u), u["id"]) for u in units), reverse=True)
        best = scored[0][0]
        close_ = [uid for s, uid in scored if best - s <= TTS_TIE]
        uid = min(close_, key=lambda x: (x < expected, abs(x - expected)))
        # Второй вариант — с другим текстом (дубли одной фразы не мешают уверенности).
        text = units[uid]["text"]
        second = next((s for s, i in scored if units[i]["text"] != text), 0.0)
        if best < SPEECH_MIN_SCORE:
            out.append({"unit": None, "score": round(best, 3), "status": "none"})
            continue
        ok = best >= TTS_OK_SCORE and best - second >= TTS_OK_MARGIN
        out.append({"unit": uid, "score": round(best, 3), "status": "ok" if ok else "doubt"})
        expected = uid + 1
    return out


class TtsFlowMixin:

    # ---------------- состояние ----------------

    def _tts(self):
        st = getattr(self, 'tts', None)
        if st is None:
            st = self.tts = {"excel_path": None, "sheet": None, "lang": "ru", "units": [], "var_sheets": {},
                             "work_dir": None, "raw_path": None, "takes": [], "index": 0}
        return st

    def _tts_save(self):
        st = self._tts()
        wd = st.get("work_dir")
        if not wd or not os.path.isdir(wd):
            return
        try:
            with open(os.path.join(wd, TTS_STATE_FILE), 'w', encoding='utf-8') as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        recent_projects.touch(wd, os.path.basename(wd))

    def _tts_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"ttsProgress({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    def _tts_target(self, unit):
        folder = TTS_VAR_DIR if unit["kind"] == "chain" else TTS_DONE_DIR
        return os.path.join(self._tts()["work_dir"], folder, f"{unit['name']}.wav")

    def tts_state(self):
        st = self._tts()
        units = st["units"]
        wd = st.get("work_dir")
        saved = {u["id"]: bool(wd) and os.path.exists(self._tts_target(u)) for u in units}
        takes_by_unit = {}
        for i, t in enumerate(st["takes"]):
            if t.get("unit") is not None:
                takes_by_unit.setdefault(t["unit"], []).append(i)
        takes = []
        for i, t in enumerate(st["takes"]):
            u = units[t["unit"]] if t.get("unit") is not None and t["unit"] < len(units) else None
            same = takes_by_unit.get(t.get("unit"), [])
            takes.append({**t, "i": i, "name": u["name"] if u else None, "kind": u["kind"] if u else None,
                          "unit_saved": saved.get(t.get("unit"), False),
                          "take_no": same.index(i) + 1 if i in same else 0, "take_total": len(same)})
        chains = [u for u in units if u["kind"] == "chain"]
        return {
            "loaded": bool(units), "has_takes": bool(st["takes"]),
            "excel_name": os.path.basename(st["excel_path"] or ''), "sheet": st.get("sheet"),
            "lang": st.get("lang", "ru"), "project": os.path.basename(wd) if wd else '',
            "units": [{**u, "saved": saved[u["id"]], "takes": takes_by_unit.get(u["id"], [])} for u in units],
            "takes": takes, "index": min(st.get("index", 0), max(0, len(takes) - 1)),
            "var_sheets": {k: {"label": v["label"],
                               "categories": [{"key": c["key"], "label": c["label"], "count": len(c["values"])}
                                              for c in v["categories"]]}
                           for k, v in st["var_sheets"].items()},
            "stats": {"units": len(units), "saved": sum(saved.values()),
                      "chains": len(chains), "chains_saved": sum(1 for u in chains if saved[u["id"]]),
                      "missing": sum(1 for u in units if not saved[u["id"]] and u["id"] not in takes_by_unit),
                      "doubt": sum(1 for t in st["takes"] if t.get("status") == "doubt"
                                   and not saved.get(t.get("unit"), False))},
        }

    # ---------------- загрузка ----------------

    def tts_pick_excel(self):
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel files (*.xlsx)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        return self.tts_load_excel(path)

    def tts_load_excel(self, path, sheet=None):
        try:
            parsed = parse_tts_workbook(path)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу «{os.path.basename(path)}».\n\n{e}"}
        sheets = parsed["phrase_sheets"]
        if not sheets:
            return {"error": "В таблице нет листа фраз: нужна шапка с колонкой <phrase>."}
        if sheet is None and len(sheets) > 1:
            self._tts_pending = (path, parsed)
            return {"choose_sheet": [{"title": s["title"], "lang": s["lang"], "units": len(s["units"])}
                                     for s in sheets]}
        chosen = next((s for s in sheets if s["title"] == sheet), sheets[0])
        st = self._tts()
        if st["takes"] and st.get("excel_path") and os.path.abspath(st["excel_path"]) != os.path.abspath(path):
            st["takes"] = []      # другая таблица — старая привязка дублей неверна
        st.update({"excel_path": path, "sheet": chosen["title"], "lang": chosen["lang"],
                   "units": chosen["units"],
                   "var_sheets": {k: v for k, v in parsed["var_sheets"].items()
                                  if k in chosen["var_keys"] or not chosen["var_keys"]}})
        st["index"] = 0
        self._tts_save()
        return self.tts_state()

    def tts_choose_sheet(self, title):
        pend = getattr(self, '_tts_pending', None)
        if not pend:
            return {"error": "Таблица не выбрана."}
        return self.tts_load_excel(pend[0], title)

    def tts_open_project(self, path):
        """Продолжить TTS-проект (tts_project.json в папке)."""
        try:
            with open(os.path.join(path, TTS_STATE_FILE), 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {"error": "Не нашёл сохранённый TTS-проект в этой папке."}
        self.tts = None
        st = self._tts()
        st.update(data)
        st["work_dir"] = path
        return self.tts_state()

    @staticmethod
    def tts_is_project(path):
        return bool(path) and os.path.exists(os.path.join(path, TTS_STATE_FILE))

    def tts_pick_recording(self):
        st = self._tts()
        if not st["units"]:
            return {"error": "Сначала загрузите таблицу."}
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if st["takes"] and not ui_confirm("Запись уже нарезана и проверена. Нарезать заново?<br><br>"
                                          "Сохранённые фразы останутся на месте.", "Нарезать заново", "Отмена"):
            return {"error": "cancel"}
        threading.Thread(target=self._tts_process, args=(path,), daemon=True).start()
        return {"status": "started"}

    # ---------------- нарезка + распознавание ----------------

    def _tts_process(self, path):
        lock = getattr(self, '_auto_check_lock', None)
        if lock is None:
            lock = self._auto_check_lock = threading.Lock()
        if not lock.acquire(blocking=False):
            self._tts_push({"stage": "error", "error": "Распознавание уже идёт."})
            return
        try:
            self._auto_check_stop = False
            res = self._tts_cut_and_check(path)
        except Exception as e:
            res = {"error": f"Не удалось обработать запись: {e}"}
        finally:
            lock.release()
        if res.get("error"):
            self._tts_push({"stage": "error", **res})
        else:
            self._tts_push({"stage": "done", "state": self.tts_state()})

    def _tts_cut_and_check(self, path):
        st = self._tts()
        self._tts_push({"stage": "cut", "done": 0, "total": 0})
        audio = AudioSegment.from_file(path)
        levels = self._frame_levels(audio)
        if not levels:
            return {"error": "Запись пустая или слишком короткая."}
        _, _, _, thresh, pause, _ = self._suggest_cut_settings(levels, len(st["units"]))
        ranges = detect_nonsilent(audio, min_silence_len=int(pause), silence_thresh=int(thresh))
        if not ranges:
            return {"error": "В записи не нашлось речи."}

        work_dir = os.path.dirname(path)
        chunks_dir = os.path.join(work_dir, TTS_CHUNKS_DIR)
        os.makedirs(chunks_dir, exist_ok=True)
        for f in os.listdir(chunks_dir):
            if re.fullmatch(r'\d{4}\.wav', f):
                try:
                    os.remove(os.path.join(chunks_dir, f))
                except OSError:
                    pass
        pieces = []
        for i, (a, b) in enumerate(ranges):
            piece = audio[max(0, a - TTS_CUT_PAD_MS):min(len(audio), b + TTS_CUT_PAD_MS)]
            name = f"{i + 1:04d}.wav"
            piece.export(os.path.join(chunks_dir, name), format="wav")
            pieces.append((name, piece, a))
            if i % 20 == 0:
                self._tts_push({"stage": "cut", "done": i + 1, "total": len(ranges)})

        self._tts_push({"stage": "model", "done": 0, "total": 0})
        model, err = self._auto_check_model()
        if err is NEED_MODEL:
            return {"error": "need_model"}
        if err:
            return {"error": err}

        heards = self._tts_transcribe([p[1] for p in pieces], 'kk' if st["lang"] == 'kz' else 'ru', model)
        matches = match_takes(heards, st["units"])
        st.update({"work_dir": work_dir, "raw_path": path, "index": 0, "takes": [
            {"file": os.path.join(TTS_CHUNKS_DIR, name), "start_ms": a, "ms": len(piece),
             "heard": heards[k], "listened": False, **matches[k]}
            for k, (name, piece, a) in enumerate(pieces)]})
        st["index"] = self._tts_next(-1)
        self._tts_save()
        return {"status": "ok"}

    def _tts_transcribe(self, segs, language, model):
        total = len(segs)
        heard = [''] * total
        state = {"done": 0}
        lock = threading.Lock()

        def finish(k, text):
            with lock:
                heard[k] = text
                state["done"] += 1
                d = state["done"]
            if d % 5 == 0 or d == total:
                self._tts_push({"stage": "asr", "done": d, "total": total})

        items = []
        for k, seg in enumerate(segs):
            samples, ms, peak = self._audit_asr_samples(seg)
            if ms < NOISE_MIN_MS or peak < NOISE_MAX_DBFS:
                finish(k, '')
            else:
                items.append({"index": k, "audio": samples, "ms": ms})

        def run(pack):
            if getattr(self, '_auto_check_stop', False):
                return
            try:
                out = self._asr_transcribe_pack(model, pack, language)
            except Exception:
                out = [''] * len(pack)
            for it, h in zip(pack, out):
                finish(it['index'], '' if self._asr_is_noise(h) else h)

        with ThreadPoolExecutor(max_workers=getattr(self, '_asr_workers', 1)) as ex:
            list(ex.map(run, self._asr_packs(items)))
        return heard

    def tts_stop(self):
        self._auto_check_stop = True
        return {"status": "ok"}

    # ---------------- прослушка и апрув ----------------

    def _tts_mark_listened(self):
        p = getattr(self, '_tts_playing', None)
        if not p:
            return
        i, started, dur = p
        takes = self._tts()["takes"]
        if i < len(takes) and time.time() - started >= dur * TTS_LISTEN_SHARE:
            takes[i]["listened"] = True
        self._tts_playing = None

    def tts_play(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if not (0 <= i < len(st["takes"])):
            return {"playing": False}
        path = os.path.join(st["work_dir"], st["takes"][i]["file"])
        if not os.path.exists(path):
            return {"playing": False, "error": "Файл дубля пропал с диска."}
        st["index"] = i
        dur = st["takes"][i].get("ms", 0) / 1000.0
        self.player.play(path)
        self._tts_playing = (i, time.time(), dur)
        return {"playing": True, "duration": dur}

    def tts_stop_audio(self):
        self._tts_mark_listened()
        self.player.stop()
        return {"playing": False}

    def tts_select(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if 0 <= i < len(st["takes"]):
            st["index"] = i
        return self.tts_state()

    def _tts_next(self, after):
        """Следующий дубль, который ещё нужно прослушать: привязан к фразе,
        а фраза не сохранена. Сначала — вперёд по записи, потом с начала."""
        st = self._tts()
        takes = st["takes"]
        n = len(takes)
        saved = {}
        for k in list(range(after + 1, n)) + list(range(0, after + 1)):
            t = takes[k]
            uid = t.get("unit")
            if uid is None or t.get("rejected"):
                continue
            if uid not in saved:
                saved[uid] = os.path.exists(self._tts_target(st["units"][uid])) if st.get("work_dir") else False
            if not saved[uid]:
                return k
        return max(0, min(after, n - 1))

    def tts_approve(self, i):
        st = self._tts()
        self._tts_mark_listened()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        if t.get("unit") is None:
            return {"error": "Дубль не привязан к фразе — выберите фразу."}
        if not t.get("listened"):
            return {"need_listen": True}
        unit = st["units"][t["unit"]]
        target = self._tts_target(unit)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if os.path.exists(target):
            self._tts_trash(target)
        shutil.copy2(os.path.join(st["work_dir"], t["file"]), target)
        for other in st["takes"]:
            if other.get("unit") == t["unit"]:
                other["approved"] = False
        t["approved"] = True
        t["rejected"] = False
        st["index"] = self._tts_next(i)
        self._tts_save()
        return {**self.tts_state(), "saved_kind": unit["kind"], "saved_name": unit["name"]}

    def tts_reject(self, i):
        """«Плохой дубль» — убрать из очереди (файл чанка остаётся)."""
        st = self._tts()
        if 0 <= i < len(st["takes"]):
            st["takes"][i]["rejected"] = not st["takes"][i].get("rejected")
            if st["takes"][i]["rejected"]:
                st["index"] = self._tts_next(i)
            self._tts_save()
        return self.tts_state()

    def tts_unapprove(self, unit_id):
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return self.tts_state()
        target = self._tts_target(st["units"][unit_id])
        if os.path.exists(target):
            self._tts_trash(target)
        for t in st["takes"]:
            if t.get("unit") == unit_id:
                t["approved"] = False
        self._tts_save()
        return self.tts_state()

    def tts_assign(self, i, unit_id):
        """Ручная привязка дубля к другой фразе (если автопроверка ошиблась)."""
        st = self._tts()
        if 0 <= i < len(st["takes"]):
            t = st["takes"][i]
            if unit_id is None or unit_id < 0:
                t.update({"unit": None, "status": "none", "score": 0.0})
            elif unit_id < len(st["units"]):
                score = unit_score(t.get("heard") or '', st["units"][unit_id]) if t.get("heard") else 0.0
                t.update({"unit": unit_id, "score": round(score, 3), "status": "manual"})
            t["approved"] = False
            self._tts_save()
        return self.tts_state()

    def tts_play_unit(self, unit_id):
        """Прослушать уже сохранённую фразу (карточка «Переменные», список)."""
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return {"playing": False}
        target = self._tts_target(st["units"][unit_id])
        if not os.path.exists(target):
            return {"playing": False}
        self._tts_mark_listened()
        self.player.play(target)
        return {"playing": True, "duration": len(AudioSegment.from_file(target)) / 1000.0}

    def _tts_trash(self, path):
        trash = os.path.join(self._tts()["work_dir"], TTS_TRASH_DIR)
        os.makedirs(trash, exist_ok=True)
        base, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(trash, f"{base}{ext}")
        n = 2
        while os.path.exists(dest):
            dest = os.path.join(trash, f"{base} ({n}){ext}")
            n += 1
        shutil.move(path, dest)

    def tts_open_folder(self, which):
        st = self._tts()
        if not st.get("work_dir"):
            return {"error": "Проект ещё не создан."}
        folder = os.path.join(st["work_dir"], TTS_VAR_DIR if which == 'var' else TTS_DONE_DIR)
        os.makedirs(folder, exist_ok=True)
        try:
            os.startfile(folder)
        except Exception as e:
            return {"error": str(e)}
        return {"status": "ok"}
