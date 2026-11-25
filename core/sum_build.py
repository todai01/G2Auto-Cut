"""«Сборка сумм» — свой экран для кусков после «Разбора записи сумм» (без Студии и Прослушки).

Строки — суммы из таблицы разбора (как их читали): начальная фраза → куски ярусов → конечная фраза.
У куска — варианты (основной и запасные попытки из «_запасные»), подрезка краёв, громкость.
«Авто-настройка»: края — по голосу, паузы на стыках — как в естественном чтении (медиана по записи),
громкость — к общему уровню. «Готовые файлы» — «<папка кусков>/_готово/…» в той же раскладке
(«1 - 100 млн/5.wav»…) + «Фразы_Переменные/»; исходные куски не меняются.

Настройки — «<папка кусков>/сборка.json»: {"table", "pieces": {кусок: {"var", "head", "tail", "gain"}},
"starts": {начальная фраза: файл}, "end": файл, "marks": {строка: "ok" | "flag"}, "auto": {...}}."""
import glob
import json
import os
import re
import statistics
import tempfile
import threading
import time
import uuid

import numpy as np

from core.raw_sums import RS_PHR_DIR, RS_PHR_TIER, rs_piece_rel, rs_read_table, rs_safe_name

SB_CFG = 'сборка.json'
SB_OUT = '_готово'
SB_CTX_DIR = 'Фразы_Переменные'
HEAD_MS = 15          # до начала голоса — столько оставляем (атака согласной)
TAIL_KEEP = 25        # после конца голоса — столько оставляем, дальше тишина стыка
DEF_GAP = 120         # пауза между голосами на стыке, если по записи не посчитать
START_GAP = 180       # после начальной фразы
GAP_MIN, GAP_MAX = 40, 500
GAIN_MAX = 8.0
FADE_IN, FADE_OUT = 5, 8


def sb_rows(tdata, res=None):
    """Строки сборки из таблицы разбора: фраза таблицы → {"id", "row", "block", "start" (начальная фраза),
    "end_text", "cells": [{"rel", "text", "cls"}], "logic", "text"}. Фразы без чисел пропускаются."""
    rows = []
    for p in tdata["phrases"]:
        start, end, cells = [], [], []
        for c in p["cells"]:
            if not c.get("num"):
                (end if cells else start).extend(c["words"])
                continue
            cat = c.get("cat")
            rel = rs_piece_rel({"cat": tuple(cat) if cat else None, "tier": c["tier"], "text": c["text"]})
            cells.append({"rel": rel.replace(os.sep, '/'), "text": c["text"], "cls": cat[0] if cat else c["tier"]})
        if not cells:
            continue
        rows.append({"id": p["id"], "row": p["row"], "block": p["block"], "start": ' '.join(start),
                     "end_text": ' '.join(end), "cells": cells,
                     "logic": 2 if any(x["cls"] == 'hundred_thousand' for x in cells) else 1,
                     "text": ' '.join(x["text"] for x in cells)})
    return rows


def sb_variants(out, rel):
    """Основной кусок и запасные попытки: [{"rel", "label"}] (только существующие файлы)."""
    res = []
    if os.path.exists(os.path.join(out, rel)):
        res.append({"rel": rel, "label": 'основной'})
    d, n = os.path.split(rel)
    stem = os.path.splitext(n)[0]
    pat = os.path.join(out, '_запасные', d, glob.escape(stem) + ' — попытка *.wav')
    num = lambda p: int(re.search(r'попытка (\d+)', p).group(1)) if re.search(r'попытка (\d+)', p) else 0
    for p in sorted(glob.glob(pat), key=num):
        res.append({"rel": os.path.relpath(p, out).replace(os.sep, '/'), "label": f'попытка {num(p)}'})
    return res


def _load(path):
    from pydub import AudioSegment
    return AudioSegment.from_file(path).set_channels(1).set_sample_width(2)


def _floats(seg):
    return np.frombuffer(seg.raw_data, '<i2').astype(np.float64) / 32768.0


def sb_span(seg):
    """(начало голоса мс, конец голоса мс, громкость голоса дБFS)."""
    from core.voice_trim import voice_span
    x = _floats(seg)
    v0, v1, _ = voice_span(x, seg.frame_rate)
    v1 = max(v1, v0 + 10)
    part = x[int(v0 * seg.frame_rate / 1000):int(v1 * seg.frame_rate / 1000)]
    rms = float(np.sqrt((part ** 2).mean())) if len(part) else 0.0
    return int(v0), int(v1), 20 * np.log10(rms + 1e-9)


def sb_peaks(seg, step_ms=20):
    x = np.abs(_floats(seg))
    per = max(1, seg.frame_rate * step_ms // 1000)
    n = max(1, len(x) // per)
    return [float(v) for v in x[:n * per].reshape(n, per).max(axis=1)] if len(x) >= per else [0.0]


class SumBuildMixin:
    """pywebview API экрана «Сборка сумм» (sb_*)."""

    def _sbs(self):
        st = getattr(self, '_sb_st', None)
        if st is None:
            st = self._sb_st = {"out": None, "table": None, "rows": [], "cfg": {}, "res": None}
        return st

    # ---------- данные ----------
    def sb_load(self, out, table=None):
        """Открыть папку кусков. table — таблица разбора (иначе — из «сборка.json»)."""
        st = self._sbs()
        cfg = {}
        try:
            with open(os.path.join(out, SB_CFG), 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            pass
        table = table or cfg.get("table")
        if not table or not os.path.exists(table):
            return {"need_table": True, "error": "Нужна таблица разбора (Excel сумм)."}
        try:
            tdata = rs_read_table(table)
        except Exception as e:
            return {"error": f"Не удалось прочитать таблицу: {e}"}
        res = None
        try:
            with open(os.path.join(out, 'разбор.json'), 'r', encoding='utf-8') as f:
                res = json.load(f)
        except (OSError, ValueError):
            pass
        cfg["table"] = table
        for k in ("pieces", "starts", "marks"):
            cfg.setdefault(k, {})
        st.update(out=out, table=table, rows=sb_rows(tdata, res), cfg=cfg, res=res)
        st["info"] = {}
        for pc in (res or {}).get("pieces", []):
            if pc.get("role") == 'main' and pc.get("file"):
                st["info"][pc["file"].replace(os.sep, '/')] = pc
        self._sb_auto_starts()
        self._sb_save()
        return self.sb_state()

    def _sb_auto_starts(self):
        """Начальные фразы, нарезанные из записи фраз (_фразы_переменные/Фразы/<текст>.wav), — сами, если не выбраны."""
        st = self._sbs()
        d = os.path.join(st["out"], RS_PHR_DIR, rs_safe_name(RS_PHR_TIER))
        for t in {r["start"] for r in st["rows"] if r["start"]}:
            p = os.path.join(d, rs_safe_name(t) + '.wav')
            if not st["cfg"]["starts"].get(t) and os.path.exists(p):
                st["cfg"]["starts"][t] = p

    def _sb_save(self):
        st = self._sbs()
        if not st["out"]:
            return
        p = os.path.join(st["out"], SB_CFG)
        with open(p + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(st["cfg"], f, ensure_ascii=False, indent=1)
        os.replace(p + '.tmp', p)

    def _sb_cached(self, key, make):
        lock = self.__dict__.setdefault('_sb_lock', threading.RLock())
        with lock:
            mem = self.__dict__.setdefault('_sb_mem', {})
            if key in mem:
                return mem[key]
        v = make()
        with lock:
            if len(mem) > 3000:
                mem.clear()
            mem[key] = v
        return v

    def _sb_sig(self, path):
        s = os.stat(path)
        return (os.path.abspath(path), s.st_mtime_ns, s.st_size)

    def _sb_audio(self, path):
        return self._sb_cached(('seg',) + self._sb_sig(path), lambda: _load(path))

    def _sb_span(self, path):
        return self._sb_cached(('span',) + self._sb_sig(path), lambda: sb_span(self._sb_audio(path)))

    # ---------- звук ----------
    def _sb_piece_cfg(self, rel):
        return {"var": rel, "head": 0, "tail": 0, "gain": 0.0, **(self._sbs()["cfg"]["pieces"].get(rel) or {})}

    def _sb_gap(self, cls):
        a = self._sbs()["cfg"].get("auto") or {}
        return (a.get("gaps") or {}).get(cls, DEF_GAP)

    def _sb_level(self, loud, extra=0.0):
        target = (self._sbs()["cfg"].get("auto") or {}).get("target")
        g = 0.0 if target is None else max(-GAIN_MAX, min(GAIN_MAX, target - loud))
        return g + float(extra or 0)

    def _sb_cut(self, path, head=0, tail=0, gain=0.0, gap=None):
        """Кусок по голосу: HEAD_MS + head до голоса, TAIL_KEEP + tail после, громкость к общему уровню,
        микро-фейды, тишина стыка (gap — пауза между голосами, мс)."""
        from pydub import AudioSegment
        seg = self._sb_audio(path)
        v0, v1, loud = self._sb_span(path)
        a = max(0, v0 - HEAD_MS - int(head or 0))
        b = min(len(seg), max(a + 20, v1 + TAIL_KEEP + int(tail or 0)))
        x = seg[a:b].apply_gain(self._sb_level(loud, gain))
        x = x.fade_in(min(FADE_IN, len(x) // 4)).fade_out(min(FADE_OUT, len(x) // 4))
        if gap is not None:
            x += AudioSegment.silent(max(0, int(gap) - TAIL_KEEP - HEAD_MS), frame_rate=x.frame_rate)
        return x

    def _sb_piece(self, rel, cls, var=None):
        st = self._sbs()
        c = self._sb_piece_cfg(rel)
        path = os.path.join(st["out"], var or c["var"])
        if not os.path.exists(path):
            path = os.path.join(st["out"], rel)
        if not os.path.exists(path):
            return None
        return self._sb_cut(path, c["head"], c["tail"], c["gain"], self._sb_gap(cls))

    def _sb_ctx(self, row):
        cfg = self._sbs()["cfg"]
        ok = lambda p: p if p and os.path.exists(p) else None
        return ok(cfg["starts"].get(row["start"]) or cfg["starts"].get('')), ok(cfg.get("end"))

    def _sb_chain(self, row, override=None):
        """[(вид, ключ, подпись, звук|None)] — начало, куски, конец."""
        from utils.wav_io import segment_like
        start, end = self._sb_ctx(row)
        a = (self._sbs()["cfg"].get("auto") or {})
        out = []
        if start:
            out.append(('start', 'start', os.path.splitext(os.path.basename(start))[0],
                        self._sb_cut(start, gap=a.get("start_gap", START_GAP))))
        for c in row["cells"]:
            var = (override or {}).get(c["rel"])
            out.append(('piece', c["rel"], c["text"], self._sb_piece(c["rel"], c["cls"], var)))
        if end:
            out.append(('end', 'end', os.path.splitext(os.path.basename(end))[0], self._sb_cut(end)))
        ref = next((s for _k, _r, _l, s in out if s is not None and _k == 'piece'), None) or \
            next((s for *_x, s in out if s is not None), None)
        if ref is not None:
            out = [(k, r, l, segment_like(s, ref) if s is not None else None) for k, r, l, s in out]
        return out

    # ---------- экран ----------
    def sb_state(self):
        st = self._sbs()
        cfg = st["cfg"]
        rows = []
        for r in st["rows"]:
            miss = sum(1 for c in r["cells"] if not os.path.exists(os.path.join(st["out"], c["rel"])))
            bad = sum(1 for c in r["cells"] if not (st["info"].get(c["rel"]) or {}).get("ok", True)
                      and self._sb_piece_cfg(c["rel"])["var"] == c["rel"])
            rows.append({"id": r["id"], "row": r["row"], "block": r["block"] + 1, "text": r["text"], "start": r["start"],
                         "logic": r["logic"], "miss": miss, "bad": bad, "mark": cfg["marks"].get(str(r["id"]))})
        starts = sorted({r["start"] for r in st["rows"]})
        exp = os.path.join(st["out"], SB_OUT) if st["out"] else None
        return {"out": st["out"], "table": st["table"], "rows": rows,
                "starts": [{"text": t, "file": os.path.basename(cfg["starts"][t]) if cfg["starts"].get(t) else None}
                           for t in starts],
                "start_any": os.path.basename(cfg["starts"][""]) if cfg["starts"].get("") else None,
                "end": os.path.basename(cfg["end"]) if cfg.get("end") else None,
                "auto": cfg.get("auto"), "export": cfg.get("export"),
                "export_dir": exp if exp and os.path.isdir(exp) else None}

    def _sb_row(self, i):
        st = self._sbs()
        return next((r for r in st["rows"] if r["id"] == int(i)), None)

    def sb_row(self, i):
        """Строка подробно: звенья цепочки (длина, волна, у куска — варианты, правки, где ещё звучит)."""
        st = self._sbs()
        row = self._sb_row(i)
        if not row:
            return {"error": "Нет такой строки."}
        uses = {}
        for r in st["rows"]:
            for c in r["cells"]:
                uses[c["rel"]] = uses.get(c["rel"], 0) + 1
        segs = []
        for kind, key, label, seg in self._sb_chain(row):
            item = {"kind": kind, "key": key, "label": label, "ms": len(seg) if seg is not None else 0,
                    "peaks": sb_peaks(seg) if seg is not None else []}
            if kind == 'piece':
                c = next(x for x in row["cells"] if x["rel"] == key)
                info = st["info"].get(key) or {}
                pc = self._sb_piece_cfg(key)
                item.update(cls=c["cls"], exists=seg is not None, ok=info.get("ok", True), why=info.get("why") or '',
                            heard=info.get("heard") or '', variants=sb_variants(st["out"], key), var=pc["var"],
                            head=pc["head"], tail=pc["tail"], gain=pc["gain"], uses=uses.get(key, 1),
                            gap=self._sb_gap(c["cls"]))
            segs.append(item)
        top = max([max(s["peaks"] or [0]) for s in segs] + [1e-6])
        for s in segs:
            s["peaks"] = [round(v / top, 3) for v in s["peaks"]]
        return {"id": row["id"], "row": row["row"], "block": row["block"] + 1, "logic": row["logic"],
                "start": row["start"], "end_text": row["end_text"], "text": row["text"], "segs": segs,
                "mark": st["cfg"]["marks"].get(str(row["id"]))}

    def sb_play(self, i, k=None, override=None):
        """Строка целиком: начало → куски → конец (как будет звучать в IVR). k — с этого звена."""
        row = self._sb_row(i)
        if not row:
            return {"error": "Нет такой строки."}
        full = self._sb_chain(row, override)
        segs = [x[3] for x in full if x[3] is not None]
        if not segs:
            return {"error": "Нечего слушать: нет кусков."}
        k = int(k or 0)
        skip = sum(len(x[3]) for j, x in enumerate(full) if j < k and x[3] is not None)
        audio = sum(segs[1:], segs[0])
        d = os.path.join(tempfile.gettempdir(), 'gvox_sumbuild')
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):                       # прежние склейки
            try:
                if time.time() - os.path.getmtime(os.path.join(d, f)) > 60:
                    os.remove(os.path.join(d, f))
            except OSError:
                pass
        path = os.path.join(d, f'{uuid.uuid4().hex[:10]}.wav')
        audio[skip:].export(path, format='wav')
        self.player.stop()
        self.player.play(path)
        return {"playing": True, "from": skip, "ms": len(audio)}

    def sb_play_var(self, i, rel, var):
        """Строка с другим вариантом куска — сравнить, не выбирая."""
        if var not in {v["rel"] for v in sb_variants(self._sbs()["out"], rel)}:
            return {"error": "Нет такого варианта."}
        return self.sb_play(i, None, {rel: var})

    def sb_stop(self):
        self.player.stop()
        return {"ok": True}

    def sb_set(self, i, rel, field, value):
        """Правка куска (общая для всех строк, где он звучит): var / head / tail / gain; value=None — сбросить."""
        st = self._sbs()
        if field not in ("var", "head", "tail", "gain", "reset"):
            return {"error": "Нет такой правки."}
        p = dict(st["cfg"]["pieces"].get(rel) or {})
        if field == 'reset':
            p = {}
        elif field == 'var':
            if value and value not in {v["rel"] for v in sb_variants(st["out"], rel)}:
                return {"error": "Нет такого варианта."}
            p["var"] = value or rel
        elif field == 'gain':
            p["gain"] = round(max(-20.0, min(20.0, float(value or 0))), 1)
        else:
            p[field] = int(max(-300, min(600, int(value or 0))))
        if p:
            st["cfg"]["pieces"][rel] = p
        else:
            st["cfg"]["pieces"].pop(rel, None)
        self._sb_save()
        return self.sb_row(i)

    def sb_mark(self, i, mark):
        st = self._sbs()
        if mark in ('ok', 'flag'):
            st["cfg"]["marks"][str(int(i))] = mark
        else:
            st["cfg"]["marks"].pop(str(int(i)), None)
        self._sb_save()
        return {"mark": st["cfg"]["marks"].get(str(int(i)))}

    def sb_ctx_pick(self, which, text=''):
        """Начальная (для фразы text; '' — для всех) или конечная фраза — аудиофайл («Фразы_Переменные»)."""
        import webview
        st = self._sbs()
        if not st["out"]:
            return {"error": "Сначала откройте папку кусков."}
        cands = [os.path.join(st["out"], RS_PHR_DIR, rs_safe_name(RS_PHR_TIER)),
                 os.path.join(os.path.dirname(st["out"]), SB_CTX_DIR), os.path.dirname(st["out"])]
        prev = [v for v in list(st["cfg"]["starts"].values()) + [st["cfg"].get("end")] if v and os.path.exists(v)]
        d = next((c for c in [os.path.dirname(p) for p in prev] + cands if os.path.isdir(c)), '')
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, directory=d, file_types=('Аудио (*.wav;*.mp3;*.ogg;*.flac;*.m4a)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        if which == 'end':
            st["cfg"]["end"] = path
        else:
            st["cfg"]["starts"][text or ''] = path
        self._sb_save()
        return self.sb_state()

    def sb_ctx_clear(self, which, text=''):
        st = self._sbs()
        if which == 'end':
            st["cfg"].pop("end", None)
        else:
            st["cfg"]["starts"].pop(text or '', None)
        self._sb_save()
        return self.sb_state()

    # ---------- авто-настройка и готовые файлы ----------
    def sb_auto(self, progress=None):
        """Паузы на стыках — по естественному чтению (медиана пауз между голосами соседних кусков одной фразы
        в записи, по классу левого куска), громкость — к медиане кусков. Ручные правки остаются."""
        st = self._sbs()
        out = st["out"]
        by_r = {}
        for pc in (st["res"] or {}).get("pieces", []):
            if pc.get("role") == 'main' and pc.get("file") and os.path.exists(os.path.join(out, pc["file"])):
                by_r.setdefault(pc["r"], []).append(pc)
        rels = sorted({c["rel"] for r in st["rows"] for c in r["cells"] if os.path.exists(os.path.join(out, c["rel"]))})
        louds = []
        for n, rel in enumerate(rels):
            louds.append(self._sb_span(os.path.join(out, rel))[2])
            if progress:
                progress(n + 1, len(rels) * 2)
        gaps = {}
        for lst in by_r.values():
            lst.sort(key=lambda pc: pc["kc"])
            for a, b in zip(lst, lst[1:]):
                if b["kc"] != a["kc"] + 1:
                    continue
                pa, pb = os.path.join(out, a["file"]), os.path.join(out, b["file"])
                _a0, a1, _ = self._sb_span(pa)
                b0, _b1, _ = self._sb_span(pb)
                gap = (b["start"] - a["end"]) * 1000 + (len(self._sb_audio(pa)) - a1) + b0
                cls = a["cat"][0] if a.get("cat") else a["tier"]
                gaps.setdefault(cls, []).append(gap)
        auto = {"gaps": {k: int(max(GAP_MIN, min(GAP_MAX, statistics.median(v)))) for k, v in gaps.items()},
                "target": round(float(statistics.median(louds)), 1) if louds else None,
                "start_gap": START_GAP, "done": time.strftime('%Y-%m-%d %H:%M'), "pieces": len(rels),
                "measured": {k: len(v) for k, v in gaps.items()}}
        st["cfg"]["auto"] = auto
        self._sb_save()
        return {"auto": auto, "state": self.sb_state()}

    def sb_export(self, progress=None):
        """Готовые файлы: «_готово/<класс>/<число>.wav» (выбранный вариант, края, стык, громкость — как в сборке)
        и «_готово/Фразы_Переменные/…». Исходные куски не меняются; прежний «_готово» перезаписывается."""
        from utils.wav_io import export_like
        st = self._sbs()
        out = st["out"]
        dst_root = os.path.join(out, SB_OUT)
        cells = {}
        for r in st["rows"]:
            for c in r["cells"]:
                cells.setdefault(c["rel"], c["cls"])
        todo = [(rel, cls) for rel, cls in sorted(cells.items()) if os.path.exists(os.path.join(out, rel))]
        n = 0
        for k, (rel, cls) in enumerate(todo):
            seg = self._sb_piece(rel, cls)
            if seg is None:
                continue
            dst = os.path.join(dst_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            src = os.path.join(out, self._sb_piece_cfg(rel)["var"])
            export_like(seg, dst + '.tmp.wav', like_path=src if os.path.exists(src) else os.path.join(out, rel))
            os.replace(dst + '.tmp.wav', dst)
            n += 1
            if progress:
                progress(len(todo) + k + 1, len(todo) * 2)
        ctx = 0
        a = st["cfg"].get("auto") or {}
        used = {(t, p) for t, p in st["cfg"]["starts"].items() if p and os.path.exists(p)}
        for t, p in used:
            dst = os.path.join(dst_root, SB_CTX_DIR, rs_safe_name(t or os.path.splitext(os.path.basename(p))[0]) + '.wav')
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            export_like(self._sb_cut(p, gap=a.get("start_gap", START_GAP)), dst, like_path=p)
            ctx += 1
        e = st["cfg"].get("end")
        if e and os.path.exists(e):
            dst = os.path.join(dst_root, SB_CTX_DIR, os.path.basename(e))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            export_like(self._sb_cut(e), dst, like_path=e)
            ctx += 1
        st["cfg"]["export"] = {"time": time.strftime('%Y-%m-%d %H:%M'), "pieces": n, "ctx": ctx}
        self._sb_save()
        return {"dir": dst_root, "pieces": n, "ctx": ctx, "state": self.sb_state()}

    def sb_use_ctx(self, start=None, end=None):
        """Свои файлы начала и конца (выбраны в окне разбора) — для всех строк: начало вместо нарезанных
        из записи фраз (свои начала, выбранные вручную в «Сборке» для отдельных фраз, остаются)."""
        st = self._sbs()
        cfg, changed = st["cfg"], False
        if start and os.path.exists(start) and cfg["starts"].get('') != start:
            auto = os.path.normcase(os.path.join(st["out"], RS_PHR_DIR))
            for k in [k for k, p in cfg["starts"].items() if p and os.path.normcase(p).startswith(auto)]:
                del cfg["starts"][k]
            cfg["starts"][''] = start
            changed = True
        if end and os.path.exists(end) and cfg.get("end") != end:
            cfg["end"] = end
            changed = True
        if changed:
            self._sb_save()

    def sb_night(self, out, table, progress=None, start=None, end=None):
        """После разбора (ночью): открыть, начало и конец, авто-настройка, готовые файлы."""
        r = self.sb_load(out, table)
        if r.get("error"):
            raise RuntimeError(r["error"])
        self.sb_use_ctx(start, end)
        self.sb_auto(progress)                    # прогресс: авто-настройка — первая половина, файлы — вторая
        e = self.sb_export(progress)
        return {"pieces": e["pieces"], "ctx": e["ctx"], "dir": e["dir"]}

    # ---------- открыть ----------
    def sb_open_rsum(self):
        """Из окна разбора: папка кусков и таблица — те, что в разборе."""
        rs = self._rsum() if hasattr(self, '_rsum') else {}
        if not rs.get("out") or not os.path.isdir(rs["out"]):
            return {"error": "Кусков пока нет: разберите запись или укажите готовую папку."}
        if rs.get("run"):
            return {"error": "Разбор ещё идёт — дождитесь конца."}
        r = self.sb_load(rs["out"], rs.get("table"))
        if not r.get("error") and (rs.get("ctx_start") or rs.get("ctx_end")):
            self.sb_use_ctx(rs.get("ctx_start"), rs.get("ctx_end"))
            r = self.sb_state()
        return r

    def sb_pick(self):
        """Выбрать папку кусков (после разбора); таблицу — из «сборка.json» или спросить."""
        import webview
        st = self._sbs()
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER, directory=st["out"] or '')
        if not picked:
            return {"error": "cancel"}
        out = picked if isinstance(picked, str) else picked[0]
        r = self.sb_load(out)
        if r.get("need_table"):
            t = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN, directory=os.path.dirname(out),
                                                      file_types=('Excel (*.xlsx)', 'Все файлы (*.*)'))
            if not t:
                return {"error": "cancel"}
            r = self.sb_load(out, t if isinstance(t, str) else t[0])
        return r

    def sb_open_folder(self, which='out'):
        st = self._sbs()
        p = os.path.join(st["out"], SB_OUT) if which == 'export' else st["out"]
        if not p or not os.path.isdir(p):
            return {"error": "Папки ещё нет."}
        try:
            if os.name == 'nt':
                os.startfile(p)
            else:
                import subprocess
                subprocess.Popen(['xdg-open', p])
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}
