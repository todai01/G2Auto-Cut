"""«Прослушка переменных»: готовая папка с записями значений (имена и т.п.),
начальная и конечная фраза, таблица названий. Для строки таблицы ищем запись
по имени (не по порядку), слушаем её между концом начала и началом
продолжения — как в суфлёре, правим (края, вырез, громкость, темп) и при
необходимости синтезируем заново через сервис синтеза (готовый голос).

Правка пишется в исходный файл; исходник — один раз в «_до_правок/» рядом
(как в аудите), его можно вернуть."""
import json
import os
import re
import shutil
import tempfile
import threading
from collections import OrderedDict

import webview
from pydub import AudioSegment

from core.tts_synth import _SynthWorker, clean_wav, synth_collect, SYNTH_PRESET_SEL, SYNTH_LANG_INDEX

LISTEN_EXTS = ('.wav', '.mp3', '.ogg', '.flac', '.m4a')
LISTEN_SKIP_DIRS = {'_до_правок', '_синтез'}
LISTEN_SYNTH_DIR = '_синтез'
LISTEN_LANG_DIRS = {'ru': 'ru', 'rus': 'ru', 'рус': 'ru', 'русский': 'ru',
                    'kz': 'kz', 'kk': 'kz', 'kaz': 'kz', 'каз': 'kz', 'қаз': 'kz', 'казахский': 'kz'}
LISTEN_HEADER_WORDS = {'имя', 'имена', 'name', 'names', 'переменная', 'переменные', 'значение', 'значения',
                       'фио', 'название', 'названия'}


def listen_norm(name):
    """Имя для поиска: без регистра, ё=е, без пробелов/знаков/расширения."""
    s = os.path.splitext(str(name or '').strip())[0] if re.search(r'\.(wav|mp3|ogg|flac|m4a)$', str(name or ''), re.I) \
        else str(name or '').strip()
    return re.sub(r'[\W_]+', '', s.lower().replace('ё', 'е'))


def listen_lang_of(path, base):
    """Язык по подпапке внутри base: …/ru/… → ru, …/kz/… → kz; иначе None."""
    try:
        parts = os.path.relpath(path, base).split(os.sep)[:-1]
    except ValueError:
        return None
    for d in parts:
        if d.lower() in LISTEN_LANG_DIRS:
            return LISTEN_LANG_DIRS[d.lower()]
    return None


class ListenMixin:
    LISTEN_CTX_MS = 2500          # сколько конца начала и начала продолжения звучит рядом с переменной
    LISTEN_CACHE = 24             # сколько декодированных записей / волн держать в памяти

    def _ls(self):
        ls = getattr(self, '_listen', None)
        if ls is None:
            ls = self._listen = {"folder": None, "index": {}, "start": None, "end": None, "table": None,
                                 "rows": [], "pos": 0, "lang": "ru", "short": True, "synth": {},
                                 "phr_folder": None, "phrases": [], "pick": {"ru": {}, "kz": {}}, "lang_dirs": {}}
        return ls

    # ---------------- папка, фразы, таблица ----------------
    def _listen_scan(self):
        ls = self._ls()
        index, lang_dirs = {}, {}
        for root, dirs, files in os.walk(ls["folder"] or ''):
            dirs[:] = [d for d in dirs if d not in LISTEN_SKIP_DIRS]
            if os.path.basename(root).lower() in LISTEN_LANG_DIRS:
                lang_dirs.setdefault(LISTEN_LANG_DIRS[os.path.basename(root).lower()], root)
            for f in sorted(files):
                if f.lower().endswith(LISTEN_EXTS):
                    index.setdefault(listen_norm(f), []).append(os.path.join(root, f))
        ls["index"], ls["lang_dirs"] = index, lang_dirs
        self._listen_match()

    def _listen_match(self):
        ls = self._ls()
        for r in ls["rows"]:
            hits = ls["index"].get(listen_norm(r["name"]), [])
            if ls["lang_dirs"]:                                # папка разделена на ru / kz — только свой язык
                hits = [h for h in hits if listen_lang_of(h, ls["folder"]) in (ls["lang"], None)]
            r["path"], r["dups"] = (hits[0] if hits else None), max(0, len(hits) - 1)

    def listen_pick_folder(self):
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        ls = self._ls()
        ls["folder"] = picked if isinstance(picked, str) else picked[0]
        self._listen_scan()
        if not ls["index"]:
            return {"error": "В этой папке нет аудиофайлов (.wav, .mp3…).", "state": self.listen_state()}
        return self.listen_state()

    # Начало и конец — из папки кусочков («Фразы_Переменные», внутри ru / kz):
    # пара своя для каждого языка, тумблер RU / KZ переключает и её.
    def listen_pick_phrases(self):
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        ls = self._ls()
        base = picked if isinstance(picked, str) else picked[0]
        items = []
        for root, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if d not in LISTEN_SKIP_DIRS)
            for f in sorted(files):
                if f.lower().endswith(LISTEN_EXTS):
                    p = os.path.join(root, f)
                    items.append({"path": p, "name": os.path.splitext(f)[0],
                                  "rel": os.path.relpath(p, base).replace(os.sep, '/'), "lang": listen_lang_of(p, base)})
        if not items:
            return {"error": "В этой папке нет аудиофайлов (.wav, .mp3…).", "state": self.listen_state()}
        ls["phr_folder"], ls["phrases"] = base, items
        keep = {p["path"] for p in items}
        for lang in ls["pick"]:
            ls["pick"][lang] = {w: v for w, v in ls["pick"][lang].items() if v in keep}
        self._listen_apply_pick()
        return self.listen_state()

    def listen_set_phrase(self, which, path, lang=None):
        """Отметить кусочек как начало / конец (path=None — снять) для языка lang."""
        ls = self._ls()
        lang = lang if lang in ('ru', 'kz') else ls["lang"]
        if which not in ('start', 'end'):
            return {"error": "Не то поле."}
        if path:
            for w in ('start', 'end'):                         # один кусок — не и начало, и конец
                if ls["pick"][lang].get(w) == path:
                    ls["pick"][lang].pop(w)
            ls["pick"][lang][which] = path
        else:
            ls["pick"][lang].pop(which, None)
        self._listen_apply_pick()
        return self.listen_state()

    def listen_phrase_play(self, path):
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        self.player.stop()
        self.player.play(path)
        return {"playing": True, "duration": len(AudioSegment.from_file(path)) / 1000.0}

    def _listen_apply_pick(self):
        ls = self._ls()
        cur = ls["pick"].get(ls["lang"], {})
        ls["start"], ls["end"] = cur.get("start"), cur.get("end")

    def listen_pick_table(self):
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Excel (*.xlsx)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        try:
            names, col = self._listen_read_table(path)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу: {e}"}
        if not names:
            return {"error": "В таблице не нашлось названий."}
        ls = self._ls()
        ls["table"] = path
        ls["rows"] = [{"name": n, "path": None, "dups": 0} for n in names]
        ls["pos"] = 0
        ls["synth"] = {}
        self._listen_match()
        return {**self.listen_state(), "column": col}

    def _listen_read_table(self, path):
        """Названия из таблицы: колонка, где больше всего совпадений с папкой
        (если папки ещё нет — первая заполненная). Шапку («Имя», «<name>») пропускаем."""
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        index = self._ls()["index"]
        best = None
        for ws in wb.worksheets:
            cols = {}
            for row in ws.iter_rows(values_only=True):
                for c, v in enumerate(row):
                    if v is not None and str(v).strip():
                        cols.setdefault(c, []).append(str(v).strip())
            for c, vals in cols.items():
                if vals and (vals[0].lower().strip('<> ') in LISTEN_HEADER_WORDS or re.fullmatch(r'<.*>', vals[0])):
                    vals = vals[1:]
                score = (sum(1 for v in vals if listen_norm(v) in index), len(vals))
                if vals and (best is None or score > best[0]):
                    best = (score, vals, f"{ws.title} · колонка {chr(65 + c) if c < 26 else c + 1}")
        wb.close()
        return (best[1], best[2]) if best else ([], None)

    # ---------------- кэш: декодированный звук и волны (ключ — путь + время + размер) ----------------
    def _listen_cache_get(self, kind, key, make):
        cache = getattr(self, '_listen_cache', None)
        if cache is None:
            cache = self._listen_cache = OrderedDict()
            self._listen_cache_lock = threading.Lock()
        k = (kind,) + key
        with self._listen_cache_lock:
            if k in cache:
                cache.move_to_end(k)
                return cache[k]
        val = make()
        with self._listen_cache_lock:
            cache[k] = val
            while len(cache) > self.LISTEN_CACHE:
                cache.popitem(last=False)
        return val

    @staticmethod
    def _listen_stamp(*paths):
        out = []
        for p in paths:
            try:
                st = os.stat(p)
                out.append((p, st.st_mtime_ns, st.st_size))
            except (OSError, TypeError):
                out.append((p, None, None))
        return tuple(out)

    def _listen_seg(self, path):
        return self._listen_cache_get('seg', self._listen_stamp(path), lambda: AudioSegment.from_file(path))

    def _listen_prefetch(self, k):
        """Следующая строка — заранее: звук и волна уже в кэше, когда до неё дойдут."""
        ls = self._ls()
        if not (0 <= k < len(ls["rows"])) or not ls["rows"][k]["path"]:
            return
        path = ls["rows"][k]["path"]

        def run():
            try:
                self._listen_seg(path)
                self.listen_edit_load(path)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()

    def _listen_row(self, k):
        ls = self._ls()
        r = ls["rows"][k]
        return {"name": r["name"], "file": os.path.basename(r["path"]) if r["path"] else None, "path": r["path"],
                "dups": r["dups"], "edited": bool(r["path"]) and os.path.exists(self._audit_backup(r["path"])),
                "synth": ls["synth"].get(k, {}).get("status")}

    def listen_go(self, pos, play=True):
        """Переход на строку одним вызовом: сразу играет цепочку, отдаёт волну
        правки и только эту строку (не всё состояние)."""
        ls = self._ls()
        if not ls["rows"]:
            return {"error": "Таблица не загружена."}
        ls["pos"] = k = max(0, min(int(pos), len(ls["rows"]) - 1))
        ls["go"] = gen = ls.get("go", 0) + 1
        path = ls["rows"][k]["path"]
        out = {"pos": k, "row": self._listen_row(k)}
        if play:
            out["play"] = self.listen_play({"path": path} if path else None, _gen=gen)
        if path:
            out["edit"] = self.listen_edit_load(path)
        self._listen_prefetch(k + 1)
        return out

    def listen_state(self):
        ls = self._ls()
        rows = ls["rows"]
        nm = lambda p: os.path.basename(p) if p else None
        return {
            "folder": ls["folder"], "folder_name": nm(ls["folder"]), "files": sum(len(v) for v in ls["index"].values()),
            "start": nm(ls["start"]), "end": nm(ls["end"]), "start_path": ls["start"], "end_path": ls["end"],
            "table": nm(ls["table"]), "pos": min(ls["pos"], max(0, len(rows) - 1)), "lang": ls["lang"],
            "short": ls["short"], "ctx_ms": self.LISTEN_CTX_MS,
            "phr_folder_name": nm(ls["phr_folder"]), "phrases": ls["phrases"], "pick": ls["pick"],
            "split": bool(ls["lang_dirs"]),
            "rows": [self._listen_row(k) for k in range(len(rows))],
            "found": sum(1 for r in rows if r["path"]),
        }

    def listen_set(self, pos=None, lang=None, short=None):
        ls = self._ls()
        if pos is not None and ls["rows"]:
            ls["pos"] = max(0, min(int(pos), len(ls["rows"]) - 1))
        if lang in ('ru', 'kz') and lang != ls["lang"]:
            ls["lang"] = lang
            self._listen_apply_pick()
            self._listen_match()
        if short is not None:
            ls["short"] = bool(short)
        return self.listen_state()

    # ---------------- правка файла: куски + громкость + темп ----------------
    @staticmethod
    def _listen_meta(path):
        return os.path.join(os.path.dirname(path), '_до_правок', os.path.basename(path) + '.listen.json')

    def listen_edit_load(self, path):
        """Волна для правки (в координатах исходника) и сохранённая правка."""
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        backup = self._audit_backup(path)
        key = self._listen_stamp(path, backup, backup + '.json')
        r = self._listen_cache_get('edit', key, lambda: self.audit_edit_load(path))
        if r.get("error"):
            return r
        r = dict(r)
        r.update(gain=0.0, tempo=1.0)
        try:
            with open(self._listen_meta(path), 'r', encoding='utf-8') as f:
                m = json.load(f)
            if all(0 <= a < b <= r["dur"] for a, b in m.get("ranges") or []) and m.get("ranges"):
                r.update(ranges=m["ranges"], gain=float(m.get("gain", 0)), tempo=float(m.get("tempo", 1)))
        except (OSError, ValueError, TypeError):
            pass
        return r

    def _listen_render(self, path, ranges=None, gain=0.0, tempo=1.0, src=None):
        """Звук файла с правкой → AudioSegment (исходник — «до правок», если правился)."""
        src = src or self._audit_src(path)
        seg = AudioSegment.from_file(src)
        if ranges:
            parts = [seg[int(a):int(b)] for a, b in ranges if int(b) > int(a)]
            if parts:
                seg = sum(parts[1:], parts[0])
        gain, tempo = float(gain or 0), float(tempo or 1)
        if abs(gain) > 0.05:
            seg = seg.apply_gain(gain)
        if abs(tempo - 1) > 0.005:
            tmp_in = os.path.join(tempfile.gettempdir(), f"gvox_listen_t_{os.getpid()}_{threading.get_ident()}.wav")
            tmp_out = tmp_in.replace('.wav', '_o.wav')
            seg.export(tmp_in, format='wav')
            AudioSegment.from_file(tmp_in).export(tmp_out, format='wav', parameters=['-filter:a', f'atempo={tempo:.4f}'])
            seg = AudioSegment.from_file(tmp_out)
        return seg

    def _listen_part(self, part):
        """Кусок цепочки: {path, ranges?, gain?, tempo?} — правка ещё может быть не сохранена."""
        p = part.get("path")
        if not p or not os.path.exists(p):
            return None
        if part.get("ranges") is None and not part.get("gain") and not part.get("tempo"):
            return self._listen_seg(p)                           # без правки — файл как есть (из кэша)
        return self._listen_render(p, part.get("ranges"), part.get("gain", 0), part.get("tempo", 1))

    def listen_play(self, var=None, start=None, end=None, only=None, _gen=None):
        """Конец начала + переменная + начало продолжения (кратко — по LISTEN_CTX_MS),
        или один кусок (only). Возвращает длительность и где начинается каждый кусок."""
        self.player.stop()
        ls = self._ls()
        start = start or ({"path": ls["start"]} if ls["start"] else None)
        end = end or ({"path": ls["end"]} if ls["end"] else None)
        chain = [("start", start), ("var", var), ("end", end)]
        if only:
            chain = [c for c in chain if c[0] == only]
        segs, marks = [], []
        ctx = self.LISTEN_CTX_MS
        for kind, part in chain:
            seg = self._listen_part(part) if part else None
            if seg is None:
                continue
            if not only and ls["short"]:
                if kind == "start" and len(seg) > ctx:
                    seg = seg[-ctx:]
                elif kind == "end" and len(seg) > ctx:
                    seg = seg[:ctx]
            segs.append(seg)
            marks.append({"kind": kind, "ms": len(seg)})
        if not segs:
            return {"error": "Нечего играть — нет записи."}
        rate = max(s.frame_rate for s in segs)
        ch = max(s.channels for s in segs)
        out = AudioSegment.empty().set_frame_rate(rate)
        for s in segs:
            out += s.set_frame_rate(rate).set_channels(ch).set_sample_width(2)
        if _gen is not None and ls.get("go") != _gen:
            return {"error": "skip"}                          # уже перешли на другую строку
        dst = os.path.join(tempfile.gettempdir(), f"gvox_listen_{os.getpid()}.wav")
        out.export(dst, format='wav')
        if _gen is not None and ls.get("go") != _gen:
            return {"error": "skip"}
        self.player.play(dst)
        return {"playing": True, "duration": len(out) / 1000.0, "marks": marks}

    def listen_stop(self):
        self.player.stop()
        return {"ok": True}

    def listen_edit_save(self, path, ranges, gain=0.0, tempo=1.0):
        """Записать правку (от исходника — без накопления), исходник — в «_до_правок/»."""
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        self.player.stop()
        backup = self._audit_backup(path)
        try:
            if not os.path.exists(backup):
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                shutil.copy2(path, backup)
            seg = self._listen_render(path, ranges, gain, tempo, src=backup)
            fmt = os.path.splitext(path)[1].lstrip('.').lower() or 'wav'
            tmp = os.path.join(tempfile.gettempdir(), f"gvox_listen_save_{os.getpid()}.{fmt}")
            src0 = AudioSegment.from_file(backup)                 # формат — как у исходника
            seg.set_frame_rate(src0.frame_rate).set_channels(src0.channels).set_sample_width(src0.sample_width) \
               .export(tmp, format='mp4' if fmt == 'm4a' else fmt)
            shutil.move(tmp, path)
            with open(self._listen_meta(path), 'w', encoding='utf-8') as f:
                json.dump({"ranges": [[int(a), int(b)] for a, b in ranges], "gain": float(gain), "tempo": float(tempo)}, f)
        except PermissionError:
            return {"error": "Файл занят (открыт в другой программе) — закройте и повторите."}
        except Exception as e:
            return {"error": f"Не удалось сохранить: {e}"}
        return {"ok": True, "ms": len(seg), "state": self.listen_state()}

    def listen_edit_restore(self, path):
        try:
            os.remove(self._listen_meta(path))
        except OSError:
            pass
        r = self.audit_edit_restore(path)
        if r.get("error"):
            return r
        return {**self.listen_edit_load(path), "state": self.listen_state()}

    # ---------------- синтез (готовый голос сервиса) ----------------
    def _listen_worker(self):
        w = getattr(self, '_listen_synth_worker', None)
        if w is None or not w.is_alive():
            w = self._listen_synth_worker = _SynthWorker(self)
            w.tab = 'preset'
            w.start()
        return w

    def _listen_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"listenEvent({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    def listen_synth(self, k, text, lang=None):
        ls = self._ls()
        if not (0 <= int(k) < len(ls["rows"])):
            return {"error": "Нет такой строки."}
        k, text = int(k), str(text or '').strip()
        if not text:
            return {"error": "Пустой текст."}
        lang = lang if lang in ('ru', 'kz') else ls["lang"]
        row = ls["rows"][k]
        out_dir = os.path.join(ls["folder"] or tempfile.gettempdir(), LISTEN_SYNTH_DIR)
        os.makedirs(out_dir, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|]+', '_', row["name"]).strip() or f'строка_{k + 1}'
        dst = os.path.join(out_dir, f"{safe}.wav")
        ls["synth"][k] = {"status": "busy", "file": dst, "text": text, "lang": lang}

        def job(worker):
            try:
                page = worker.page_ready()
                sel = SYNTH_PRESET_SEL
                page.select_option(sel["voice"], index=sel["voice_index"])
                page.select_option(sel["lang"], index=SYNTH_LANG_INDEX.get(lang, 0))
                page.fill(sel["text"], text)
                raw = os.path.splitext(dst)[0] + '.download'
                synth_collect(page, sel["submit"], raw)
                try:
                    clean_wav(raw, dst)
                finally:
                    try:
                        os.remove(raw)
                    except OSError:
                        pass
                self._listen_level(dst, row["path"] or ls["start"])
                ls["synth"][k]["status"] = "ready"
                self._listen_push({"stage": "synth", "k": k, "ok": True, "state": self.listen_state()})
            except Exception as e:
                ls["synth"][k]["status"] = "error"
                self._listen_push({"stage": "synth", "k": k, "ok": False, "error": str(e), "state": self.listen_state()})
        self._listen_worker().add(job)
        return {"queued": True, "state": self.listen_state()}

    def _listen_level(self, dst, ref):
        """Синтез — к громкости и формату соседа (прежняя запись переменной или начало фразы)."""
        try:
            seg = AudioSegment.from_file(dst)
            if ref and os.path.exists(ref):
                r = AudioSegment.from_file(ref)
                a, b = self._loudness(seg), self._loudness(r)
                if a is not None and b is not None:
                    seg = seg.apply_gain(max(-15.0, min(15.0, b - a)))
                seg = seg.set_frame_rate(r.frame_rate).set_channels(r.channels).set_sample_width(r.sample_width)
            seg.export(dst, format='wav')
        except Exception:
            pass

    def listen_synth_play(self, k):
        s = self._ls()["synth"].get(int(k))
        if not s or s.get("status") != "ready":
            return {"error": "Синтеза для этой строки ещё нет."}
        return self.listen_play(var={"path": s["file"]})

    def listen_synth_take(self, k):
        """Синтез → вместо записи переменной (прежняя запись — в «_до_правок/»)."""
        ls = self._ls()
        k = int(k)
        s = ls["synth"].get(k)
        if not s or s.get("status") != "ready" or not os.path.exists(s["file"]):
            return {"error": "Синтеза для этой строки ещё нет."}
        self.player.stop()
        row = ls["rows"][k]
        path = row["path"]
        if not path:
            safe = re.sub(r'[\\/:*?"<>|]+', '_', row["name"]).strip() or f'строка_{k + 1}'
            path = os.path.join(ls["lang_dirs"].get(s.get("lang") or ls["lang"]) or ls["folder"] or os.path.dirname(s["file"]),
                                f"{safe}.wav")
        elif not os.path.exists(self._audit_backup(path)):
            os.makedirs(os.path.dirname(self._audit_backup(path)), exist_ok=True)
            shutil.copy2(path, self._audit_backup(path))
        if os.path.splitext(path)[1].lower() == '.wav':
            shutil.copy2(s["file"], path)
        else:
            AudioSegment.from_file(s["file"]).export(path, format=os.path.splitext(path)[1].lstrip('.').lower())
        for meta in (self._listen_meta(path), self._audit_backup(path) + '.json'):
            try:
                os.remove(meta)
            except OSError:
                pass
        ls["synth"].pop(k, None)
        self._listen_scan()
        return {"ok": True, "state": self.listen_state()}

    def listen_synth_drop(self, k):
        s = self._ls()["synth"].pop(int(k), None)
        if s:
            try:
                os.remove(s["file"])
            except OSError:
                pass
        return self.listen_state()
