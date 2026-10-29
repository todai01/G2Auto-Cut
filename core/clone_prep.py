"""Подготовка к клону голоса — отдельная утилита.

1. Папка с аудиофайлами (с подпапками) → один WAV: файлы подряд, между
   ними пауза тишины. Рядом — тайминги: где в общем WAV начинается и
   кончается каждый файл (Клон_исходник.json).
   Отдельно по языкам: файлы с меткой ru / kz (подпапка или слово в имени)
   — два WAV со своими таймингами (Клон_исходник_ru.wav / _kz.wav).
2. Общий WAV прогоняете через клон (сколько угодно голосов) и
   возвращаете сюда готовые клоны. Каждый клон режется по таймингам
   исходника: файлы получают те же имена и ту же раскладку по папкам.

Клон может чуть сдвинуть или растянуть звук (задержка в начале, другая
длина) — это ищется само: общий сдвиг и растяжение — по всей записи,
каждый файл ещё подравнивается по своим паузам (± CLONE_LOCAL_MS).
"""
import datetime
import json
import os
import re

import numpy as np
import webview

from utils.audio_player import _read_audio, resample

CLONE_EXTS = ('.wav', '.mp3', '.ogg', '.flac', '.m4a', '.aac', '.opus', '.wma')
CLONE_DIR = '_Клон'                    # служебная папка внутри выбранной
CLONE_WAV = 'Клон_исходник.wav'
CLONE_JSON = 'Клон_исходник.json'
CLONE_LEAD_MS = 500                    # тишина в начале общего WAV
CLONE_FRAME_MS = 10
CLONE_GLOBAL_MS = 4000                 # общий сдвиг клона ищется в ± стольких мс
CLONE_LOCAL_MS = 200                   # каждый файл подравнивается в ± стольких мс
CLONE_LANG_DIRS = {'ru': 'ru', 'rus': 'ru', 'рус': 'ru', 'kz': 'kz', 'kk': 'kz', 'kaz': 'kz', 'каз': 'kz', 'қаз': 'kz'}
CLONE_NOLANG = 'без_языка'
CLONE_NOLANG_WORDS = {'без', 'безязыка', 'без_языка', 'nolang', 'other', 'прочее', 'none'}
CLONE_FINAL = 'Клоны_финал'


def _clone_lang(rel):
    """Язык файла: подпапка ru / kz или отдельное слово ru / kz в имени (…_ru_…); иначе None."""
    parts = rel.replace('\\', '/').split('/')
    for d in parts[:-1]:
        if d.lower() in CLONE_LANG_DIRS:
            return CLONE_LANG_DIRS[d.lower()]
    for w in re.split(r'[_\-\s.()\[\]]+', os.path.splitext(parts[-1])[0].lower()):
        if w in CLONE_LANG_DIRS:
            return CLONE_LANG_DIRS[w]
    return None


def _clone_cat(name):
    """Категория клона по имени файла: ru / kz / без_языка; не понять — None."""
    lang = _clone_lang(name)
    if lang:
        return lang
    low = os.path.splitext(os.path.basename(name))[0].lower()
    if 'без_языка' in low or 'без языка' in low:
        return CLONE_NOLANG
    words = set(re.split(r'[_\-\s.()\[\]]+', low))
    return CLONE_NOLANG if words & CLONE_NOLANG_WORDS else None


def _natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


def _mono(path):
    x, rate = _read_audio(path)
    x = x.mean(axis=1) if x.ndim > 1 and x.shape[1] > 1 else x.reshape(-1)
    return x.astype(np.float32), int(rate)


def _write16(dst, x, rate):
    import wave
    pcm = np.round(np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0) * 32767).astype('<i2')
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    with wave.open(dst, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


def _env(x, rate):
    """Громкость по кадрам 10 мс, дБ."""
    n = max(1, rate * CLONE_FRAME_MS // 1000)
    k = len(x) // n
    if not k:
        return np.zeros(0)
    e = np.sqrt((x[:k * n].reshape(k, n) ** 2).mean(axis=1))
    return 20 * np.log10(e + 1e-6)


def _voice(env):
    """Где голос: громче тихого фона на 15 дБ (порог — от самой записи)."""
    if not len(env):
        return env.astype(bool)
    floor = np.percentile(env, 10)
    top = np.percentile(env, 95)
    thr = max(floor + 15, top - 40)
    return env > thr


def _best_lag(a, b, max_lag):
    """Сдвиг b относительно a (в кадрах), при котором голос совпадает лучше всего."""
    a = a.astype(np.float32) - a.mean() if len(a) else a
    b = b.astype(np.float32) - b.mean() if len(b) else b
    best, best_lag = -np.inf, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            n = min(len(a), len(b) - lag)
            if n <= 0:
                continue
            v = float(np.dot(a[:n], b[lag:lag + n]))
        else:
            n = min(len(a) + lag, len(b))
            if n <= 0:
                continue
            v = float(np.dot(a[-lag:-lag + n], b[:n]))
        if v > best:
            best, best_lag = v, lag
    return best_lag


def _best_pos(sv, win, expect):
    """Где в окне голос совпадает с голосом файла лучше всего (кадр начала);
    при равенстве — ближе к ожидаемому месту."""
    a = sv.astype(np.float32) * 2 - 1
    w = win.astype(np.float32) * 2 - 1
    n = len(a)
    scores = np.array([float(np.dot(a, w[p:p + n])) for p in range(len(w) - n + 1)])
    scores -= np.abs(np.arange(len(scores)) - expect) * 0.01
    return int(np.argmax(scores))


class ClonePrepMixin:

    # ---------------- 1. собрать один WAV ----------------

    def clone_pick_folder(self):
        d = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not d:
            return None
        return self.clone_scan(d[0])

    def clone_scan(self, folder):
        """Что лежит в папке: аудиофайлы (с подпапками, без служебной «_Клон»)."""
        files = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = sorted((d for d in dirs if not d.startswith(CLONE_DIR)), key=_natural)
            for n in sorted(names, key=_natural):
                if n.lower().endswith(CLONE_EXTS):
                    files.append(os.path.relpath(os.path.join(root, n), folder))
        self._clone_folder = folder
        self._clone_files = files
        out = os.path.join(folder, CLONE_DIR)
        prev = [os.path.join(out, f) for f in sorted(os.listdir(out))
                if f.startswith(os.path.splitext(CLONE_JSON)[0]) and f.endswith('.json')] if os.path.isdir(out) else []
        langs = {}
        for f in files:
            k = _clone_lang(f) or CLONE_NOLANG
            langs[k] = langs.get(k, 0) + 1
        return {"folder": folder, "count": len(files), "files": files[:12],
                "subdirs": len({os.path.dirname(f) for f in files if os.path.dirname(f)}),
                "langs": langs, "prev": max(prev, key=os.path.getmtime) if prev else None}

    def clone_build(self, gap_ms=1000, rate=0, split=False):
        """Все файлы — в один WAV (моно, 16 бит) с паузой gap_ms между ними.
        rate 0 — частота самого «высокого» файла. Тайминги — в JSON рядом.
        split — отдельный WAV на каждый язык (ru / kz, без метки — «без_языка»)."""
        folder = getattr(self, '_clone_folder', None)
        files = getattr(self, '_clone_files', None)
        if not folder or not files:
            return {"error": "Сначала выберите папку с аудиофайлами."}
        gap_ms = max(200, min(5000, int(gap_ms or 1000)))
        loaded, errors = [], []
        for rel in files:
            try:
                x, r = _mono(os.path.join(folder, rel))
                loaded.append((rel, x, r))
            except Exception as e:
                errors.append(f"{rel}: {e}")
        if not loaded:
            return {"error": "Не удалось прочитать ни одного файла.", "errors": errors}
        out_rate = int(rate) if rate else max(r for _n, _x, r in loaded)
        out_dir = os.path.join(folder, CLONE_DIR)
        os.makedirs(out_dir, exist_ok=True)
        groups = {}
        for item in loaded:
            groups.setdefault((_clone_lang(item[0]) or CLONE_NOLANG) if split else None, []).append(item)
        set_id = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        parts = []
        for lang in sorted(groups, key=lambda k: {'ru': 0, 'kz': 1, CLONE_NOLANG: 2}.get(k, 3)):
            parts.append(self._clone_write(out_dir, groups[lang], out_rate, gap_ms, folder, lang, set_id if split else None))
        self._clone_jsons = [p["json"] for p in parts]
        self._clone_json = parts[0]["json"]
        first = parts[0]
        return {"wav": first["wav"], "json": first["json"], "count": sum(p["count"] for p in parts), "rate": out_rate,
                "total_s": round(sum(p["total_s"] for p in parts), 1), "parts": parts if split else None, "errors": errors}

    def _clone_write(self, out_dir, loaded, out_rate, gap_ms, folder, lang, set_id):
        """Один WAV + тайминги для группы файлов (lang — язык группы или None)."""
        suffix = f"_{lang}" if lang else ''
        gap = np.zeros(out_rate * gap_ms // 1000, dtype=np.float32)
        parts = [np.zeros(out_rate * CLONE_LEAD_MS // 1000, dtype=np.float32)]
        pos = len(parts[0])
        items = []
        for rel, x, r in loaded:
            y = resample(x[:, None], r, out_rate)[:, 0] if r != out_rate else x
            items.append({"name": rel, "start": pos, "len": len(y), "rate": r,
                          "start_ms": round(pos * 1000 / out_rate, 1), "dur_ms": round(len(y) * 1000 / out_rate, 1)})
            parts += [y, gap]
            pos += len(y) + len(gap)
        whole = np.concatenate(parts)
        stem_w, ext_w = os.path.splitext(CLONE_WAV)
        stem_j, ext_j = os.path.splitext(CLONE_JSON)
        wav = os.path.join(out_dir, stem_w + suffix + ext_w)
        _write16(wav, whole, out_rate)
        meta = {"version": 1, "created": datetime.datetime.now().isoformat(timespec='seconds'),
                "source_folder": folder, "wav": os.path.basename(wav), "rate": out_rate, "gap_ms": gap_ms,
                "lead_ms": CLONE_LEAD_MS, "samples": len(whole), "total_ms": round(len(whole) * 1000 / out_rate, 1),
                "lang": lang, "set": set_id, "files": items}
        js = os.path.join(out_dir, stem_j + suffix + ext_j)
        with open(js, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        return {"lang": lang, "wav": wav, "json": js, "count": len(items), "total_s": round(len(whole) / out_rate, 1)}

    # ---------------- 2. нарезать клоны ----------------

    def clone_pick_json(self):
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                  file_types=('Тайминги (*.json)', 'Все файлы (*.*)'))
        if not f:
            return None
        return self.clone_load_json(f[0])

    def clone_load_json(self, path):
        try:
            with open(path, encoding='utf-8') as fh:
                meta = json.load(fh)
            assert meta.get("files")
        except Exception:
            return {"error": "Это не файл таймингов клона."}
        self._clone_json = path
        self._clone_jsons = [path]
        parts = [{"lang": meta.get("lang"), "count": len(meta["files"]), "total_s": round(meta["total_ms"] / 1000, 1)}]
        if meta.get("set"):                                   # сборка по языкам — подхватить соседние тайминги
            base = os.path.dirname(path)
            for f in sorted(os.listdir(base)):
                p = os.path.join(base, f)
                if p == path or not f.endswith('.json'):
                    continue
                try:
                    with open(p, encoding='utf-8') as fh:
                        m = json.load(fh)
                except Exception:
                    continue
                if m.get("set") == meta["set"] and m.get("files"):
                    self._clone_jsons.append(p)
                    parts.append({"lang": m.get("lang"), "count": len(m["files"]), "total_s": round(m["total_ms"] / 1000, 1)})
        return {"json": path, "count": sum(p["count"] for p in parts), "total_s": round(sum(p["total_s"] for p in parts), 1),
                "parts": parts if len(parts) > 1 else None, "source_folder": meta.get("source_folder")}

    def clone_pick_clones(self):
        f = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                                  file_types=('Аудио (*.wav;*.mp3;*.flac;*.ogg;*.m4a)', 'Все файлы (*.*)'))
        if not f:
            return None
        self._clone_inputs = list(f)
        return {"clones": [os.path.basename(p) for p in self._clone_inputs]}

    def clone_set_clones(self, paths):
        self._clone_inputs = list(paths)
        return {"clones": [os.path.basename(p) for p in self._clone_inputs]}

    def _clone_align(self, meta, src_voice, x, rate):
        """Общий сдвиг (мс) и растяжение клона относительно исходника. Длина
        файла клона не в счёт (сервисы дописывают тишину в конце): сдвиг
        ищется по голосу в начале записи и в конце — их разница и есть
        растяжение."""
        cv = _voice(_env(x, rate))
        sv = src_voice
        if sv is None:                                       # исходника нет — голос там, где файлы
            sv = np.zeros(int(meta["total_ms"] / CLONE_FRAME_MS), dtype=bool)
            for it in meta["files"]:
                a = int(it["start_ms"] / CLONE_FRAME_MS)
                sv[a:a + int(it["dur_ms"] / CLONE_FRAME_MS)] = True
        n = len(sv)
        W = max(50, min(n // 3, 3000))                       # окно до 30 с
        G = CLONE_GLOBAL_MS // CLONE_FRAME_MS
        off1 = _best_pos(sv[:W], cv[:W + G], 0) if len(cv) > W else 0
        if n - W <= W:                                       # запись короткая — без растяжения
            return off1 * CLONE_FRAME_MS, 1.0, cv
        spread = max(G, int(n * 0.06))                       # растяжение до ±6%
        c0 = max(0, n - W + off1 - spread)
        win = cv[c0:n - W + off1 + spread + W]
        if len(win) <= W:
            return off1 * CLONE_FRAME_MS, 1.0, cv
        off2 = c0 + _best_pos(sv[-W:], win, n - W + off1 - c0) - (n - W)
        scale = 1 + (off2 - off1) / (n - W)
        if abs(scale - 1) < 0.003:                           # меньше 0.3% — шум оценки, не растяжение
            return off1 * CLONE_FRAME_MS, 1.0, cv
        # сдвиг найден по окну — это сдвиг его середины; к нулю — без растяжения окна
        off0 = off1 - (scale - 1) * (W / 2)
        return off0 * CLONE_FRAME_MS, scale, cv

    def clone_cut(self, out_rate_mode='source'):
        """Каждый клон → папка «<имя клона>» рядом с таймингами: файлы с теми
        же именами и подпапками. out_rate_mode 'source' — частота как у
        исходного файла, 'clone' — как у клона."""
        jsons = [j for j in (getattr(self, '_clone_jsons', None) or [getattr(self, '_clone_json', None)]) if j and os.path.exists(j)]
        clones = getattr(self, '_clone_inputs', None) or []
        if not jsons:
            return {"error": "Нет таймингов — соберите WAV (шаг 1) или выберите файл таймингов."}
        if not clones:
            return {"error": "Выберите файлы клонов."}
        metas = []
        for js in jsons:
            with open(js, encoding='utf-8') as fh:
                metas.append((js, json.load(fh)))
        voices = {}

        def src_voice_of(js, meta):
            if js not in voices:
                src_wav = os.path.join(os.path.dirname(js), meta.get("wav") or CLONE_WAV)
                voices[js] = None
                if os.path.exists(src_wav):
                    try:
                        sx, sr = _mono(src_wav)
                        voices[js] = _voice(_env(sx, sr))
                    except Exception:
                        pass
            return voices[js]
        report = []
        for cpath in clones:
            name = os.path.splitext(os.path.basename(cpath))[0]
            try:
                x, rate = _mono(cpath)
            except Exception as e:
                report.append({"clone": name, "error": f"не читается: {e}"})
                continue
            js, meta, how = self._clone_pick_meta(metas, name, len(x) * 1000 / rate)
            base = os.path.dirname(js)
            src_voice = src_voice_of(js, meta)
            off_ms, scale, cv = self._clone_align(meta, src_voice, x, rate)
            out_dir = os.path.join(base, name)
            done, moved, warn = self._clone_cut_one(meta, src_voice, x, rate, off_ms, scale, cv, out_dir, out_rate_mode,
                                                    lambda n: os.path.splitext(n)[0] + '.wav')
            report.append({"clone": name, "folder": out_dir, "files": done, "offset_ms": round(off_ms),
                           "lang": meta.get("lang"), "by": how,
                           "scale": round(scale, 4), "fix_max_ms": round(max(moved), 0) if moved else 0,
                           "warnings": warn[:8]})
        return {"report": report, "json": jsons[0]}


    def _clone_cut_one(self, meta, src_voice, x, rate, off_ms, scale, cv, out_dir, out_rate_mode, dst_of):
        """Один клон по таймингам meta → файлы в out_dir (имя — dst_of(имя из таймингов)).
        Возвращает (сколько файлов, подравнивания мс, предупреждения)."""
        fr = CLONE_FRAME_MS
        moved, done, warn = [], 0, []
        for it in meta["files"]:
            st = off_ms + it["start_ms"] * scale
            dur = it["dur_ms"] * scale
            # подровнять по паузам: голос файла в исходнике ↔ в клоне рядом
            if src_voice is not None:
                a0 = int(it["start_ms"] / fr)
                sv = src_voice[a0:a0 + max(1, int(it["dur_ms"] / fr))]
                if scale != 1.0 and len(sv):
                    idx = np.minimum((np.arange(max(1, int(len(sv) * scale))) / scale).astype(int), len(sv) - 1)
                    sv = sv[idx]
                L = CLONE_LOCAL_MS // fr
                w0 = max(0, int(st / fr) - L)
                win = cv[w0:w0 + len(sv) + 2 * L]
                if sv.any() and len(win) > len(sv):
                    p = _best_pos(sv, win, int(st / fr) - w0)
                    corr = (w0 + p) * fr - st
                    if fr < abs(corr) <= CLONE_LOCAL_MS + fr:     # сдвиг меньше кадра — не трогаем
                        st += corr
                        moved.append(abs(corr))
            a = max(0, int(round(st * rate / 1000)))
            b = min(len(x), a + int(round(dur * rate / 1000)))
            seg = x[a:b]
            if len(seg) < int(dur * rate / 1000) * 0.9:
                warn.append(f"{it['name']}: клон кончился раньше")
            if not len(seg):
                continue
            r_out = it.get("rate", rate) if out_rate_mode == 'source' else rate
            if r_out != rate:
                seg = resample(seg[:, None], rate, r_out)[:, 0]
            f = max(1, int(r_out * 0.003))                  # без щелчка на краях
            if len(seg) > 2 * f:
                seg = seg.copy()
                seg[:f] *= np.linspace(0, 1, f, dtype=np.float32)
                seg[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
            dst = os.path.join(out_dir, dst_of(it["name"]))
            _write16(dst, seg, r_out)
            done += 1
        if abs(scale - 1) > 0.03:
            warn.insert(0, f"длина клона отличается от исходника на {abs(scale - 1) * 100:.1f}% — проверьте на слух")
        return done, moved, warn

    # ---------------- 2'. тайминги из папки, клоны — по папкам голосов ----------------

    def clone_pick_timings(self):
        d = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not d:
            return None
        return self.clone_load_timings(d[0] if isinstance(d, (list, tuple)) else d)

    def clone_load_timings(self, folder):
        """Все тайминги из папки (или её «_Клон»): последняя сборка — ru, kz, без языка."""
        cands = []
        for base in (folder, os.path.join(folder, CLONE_DIR)):
            if not os.path.isdir(base):
                continue
            for f in sorted(os.listdir(base)):
                if not f.lower().endswith('.json'):
                    continue
                p = os.path.join(base, f)
                try:
                    with open(p, encoding='utf-8') as fh:
                        m = json.load(fh)
                except Exception:
                    continue
                if isinstance(m, dict) and m.get("files") and m.get("total_ms"):
                    cands.append((p, m))
        if not cands:
            return {"error": "В этой папке нет таймингов (Клон_исходник….json) — выберите папку, где они лежат."}
        groups = {}
        for p, m in cands:
            groups.setdefault(m.get("set") or p, []).append((p, m))
        best = max(groups.values(), key=lambda g: max(os.path.getmtime(p) for p, _m in g))
        order = {'ru': 0, 'kz': 1, CLONE_NOLANG: 2}
        best.sort(key=lambda pm: order.get(pm[1].get("lang"), 3))
        self._clone_jsons = [p for p, _m in best]
        self._clone_json = self._clone_jsons[0]
        self._clone_timings_dir = os.path.dirname(self._clone_json)
        parts = [{"lang": m.get("lang"), "count": len(m["files"]), "total_s": round(m["total_ms"] / 1000, 1),
                  "json": os.path.basename(p)} for p, m in best]
        return {"folder": self._clone_timings_dir, "json": self._clone_json, "parts": parts,
                "count": sum(p["count"] for p in parts), "total_s": round(sum(p["total_s"] for p in parts), 1)}

    def clone_pick_voice_folder(self):
        """Папка одного голоса: в ней клоны цельных записей (ru / kz / без языка)."""
        d = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not d:
            return None
        folder = d[0] if isinstance(d, (list, tuple)) else d
        files = self._clone_voice_files(folder)
        return {"folder": folder, "name": os.path.basename(os.path.normpath(folder)),
                "files": [{"name": os.path.basename(f), "cat": _clone_cat(f)} for f in files]}

    @staticmethod
    def _clone_voice_files(folder):
        top = [os.path.join(folder, f) for f in sorted(os.listdir(folder), key=_natural)
               if f.lower().endswith(CLONE_EXTS) and os.path.isfile(os.path.join(folder, f))]
        if top:
            return top
        out = []
        for root, dirs, names in os.walk(folder):
            dirs[:] = sorted((d for d in dirs if not d.startswith(CLONE_DIR) and d != CLONE_FINAL), key=_natural)
            out += [os.path.join(root, n) for n in sorted(names, key=_natural) if n.lower().endswith(CLONE_EXTS)]
        return out

    def clone_cut_voices(self, folders, out_rate_mode='source'):
        """Каждая папка голоса → «Клоны_финал/<голос>/ru | kz | без_языка/…»: клоны
        цельных записей сопоставляются с таймингами (по метке в имени, иначе по
        длительности) и режутся на файлы с исходными именами."""
        jsons = [j for j in (getattr(self, '_clone_jsons', None) or []) if os.path.exists(j)]
        if not jsons:
            return {"error": "Сначала выберите папку с таймингами."}
        if not folders:
            return {"error": "Выберите папки с клонами."}
        metas = []
        for js in jsons:
            with open(js, encoding='utf-8') as fh:
                metas.append((js, json.load(fh)))
        tdir = getattr(self, '_clone_timings_dir', None) or os.path.dirname(jsons[0])
        final, n = os.path.join(tdir, CLONE_FINAL), 2
        while os.path.exists(final):
            final, n = os.path.join(tdir, f"{CLONE_FINAL}_{n}"), n + 1
        voices = {}

        def src_voice_of(js, meta):
            if js not in voices:
                voices[js] = None
                src_wav = os.path.join(os.path.dirname(js), meta.get("wav") or CLONE_WAV)
                if os.path.exists(src_wav):
                    try:
                        sx, sr = _mono(src_wav)
                        voices[js] = _voice(_env(sx, sr))
                    except Exception:
                        pass
            return voices[js]

        def dst_of(lang):
            def f(rel):
                parts = rel.replace('\\', '/').split('/')
                if len(parts) > 1 and parts[0].lower() in CLONE_LANG_DIRS:
                    parts = parts[1:]                         # ru/Гизат.wav → Гизат.wav (папка языка — своя)
                parts[-1] = os.path.splitext(parts[-1])[0] + '.wav'
                return os.path.join(*([lang] if lang else []), *parts)
            return f

        report, used_names = [], set()
        for folder in folders:
            vname = os.path.basename(os.path.normpath(folder)) or 'голос'
            base_name, k = vname, 2
            while vname in used_names:
                vname, k = f"{base_name}_{k}", k + 1
            used_names.add(vname)
            out_dir = os.path.join(final, vname)
            loaded, warns = [], []
            for p in self._clone_voice_files(folder):
                try:
                    x, rate = _mono(p)
                    loaded.append((p, x, rate))
                except Exception as e:
                    warns.append(f"{os.path.basename(p)}: не читается ({e})")
            pairs = self._clone_match(metas, loaded)
            cats = []
            for (p, x, rate), (js, meta), how in pairs:
                src_voice = src_voice_of(js, meta)
                off_ms, scale, cv = self._clone_align(meta, src_voice, x, rate)
                lang = meta.get("lang") or (CLONE_NOLANG if len(metas) > 1 else None)
                done, moved, warn = self._clone_cut_one(meta, src_voice, x, rate, off_ms, scale, cv, out_dir,
                                                        out_rate_mode, dst_of(lang))
                if abs(scale - 1) > 0.03:
                    warn.insert(0, f"длина клона отличается от исходника на {abs(scale - 1) * 100:.1f}% — проверьте на слух")
                cats.append({"lang": lang, "clone": os.path.basename(p), "by": how, "files": done,
                             "offset_ms": round(off_ms), "scale": round(scale, 4),
                             "fix_max_ms": round(max(moved), 0) if moved else 0, "warnings": warn[:6]})
            got = {id(m) for (_p, _x, _r), (_j, m), _h in pairs}
            for js, m in metas:
                if id(m) not in got:
                    warns.append(f"нет клона для «{m.get('lang') or 'записи'}» ({len(m['files'])} файлов)")
            for p, _x, _r in loaded:
                if all(p != pp for (pp, _a, _b), _m, _h in pairs):
                    warns.append(f"{os.path.basename(p)}: лишний файл — не понял, к какой записи")
            report.append({"voice": vname, "source": folder, "folder": out_dir, "cats": cats, "warnings": warns})
        return {"final": final, "report": report}

    @staticmethod
    def _clone_match(metas, loaded):
        """Клоны папки ↔ тайминги: по метке ru / kz / без в имени, остальное — по длительности
        (клон дописывает тишину в конце, бывает чуть растянут). [((путь, x, rate), (js, meta), how)]."""
        pairs, free_m, free_c = [], list(metas), list(loaded)
        for c in list(free_c):
            cat = _clone_cat(c[0])
            m = next((jm for jm in free_m if cat and (jm[1].get("lang") or None) == cat), None)
            if m:
                pairs.append((c, m, 'name')); free_m.remove(m); free_c.remove(c)

        def cost(c, jm):
            ms, tot = len(c[1]) * 1000 / c[2], jm[1]["total_ms"]
            return abs(ms - tot) / tot + (1.0 if ms < tot * 0.9 else 0)
        while free_m and free_c:
            c, jm = min(((c, jm) for c in free_c for jm in free_m), key=lambda t: cost(*t))
            pairs.append((c, jm, 'length')); free_m.remove(jm); free_c.remove(c)
        return pairs

    @staticmethod
    def _clone_pick_meta(metas, clone_name, clone_ms):
        """Тайминги для клона: одни — они; по языкам — по метке ru / kz в имени
        клона, иначе — по длительности (клон дописывает тишину в конце, бывает
        чуть растянут)."""
        if len(metas) == 1:
            return metas[0][0], metas[0][1], None
        lang = _clone_lang(clone_name)
        for js, m in metas:
            if lang and m.get("lang") == lang:
                return js, m, 'name'
        js, m = min(metas, key=lambda jm: abs(clone_ms - jm[1]["total_ms"]) + (jm[1]["total_ms"] * 0.5 if clone_ms < jm[1]["total_ms"] * 0.9 else 0))
        return js, m, 'length'

    def clone_open_folder(self, path):
        try:
            os.startfile(path)                                  # Windows
        except Exception:
            pass
        return True
