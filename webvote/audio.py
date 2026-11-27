"""Каталог вариантов и звук: пики волны, автоотметки, цепочка «начало → имя → конец»."""
import csv
import glob
import io
import json
import os
import re
import threading

import numpy as np

VARIANT_RE = re.compile(r'^вариант_(\d+)$')
GAP_BEFORE, GAP_AFTER = 120, 140        # мс тишины вокруг имени в цепочке
PEAKS = 180


class Catalog:
    """Папка результата «Прослушки»: имена.json, вариант_N/<имя>.wav, _контекст/start|end."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        with open(os.path.join(self.root, 'имена.json'), encoding='utf-8') as f:
            meta = json.load(f)
        self.names = list(meta["names"])
        self.stems = list(meta.get("stems") or self.names)
        self.meta = meta
        found = sorted(int(m.group(1)) for d in os.listdir(self.root) if (m := VARIANT_RE.match(d)))
        self.variants = found or list(range(1, int(meta.get("variants", 3)) + 1))
        self.lock = threading.Lock()
        self._peaks, self._span, self._chain, self._seg = {}, {}, {}, {}

    def path(self, idx, v):
        return os.path.join(self.root, f'вариант_{v}', f'{self.stems[idx]}.wav')

    def ctx_path(self, kind):
        for p in sorted(glob.glob(os.path.join(self.root, '_контекст', kind + '.*'))):
            return p
        return None

    def have(self, idx):
        return [v for v in self.variants if os.path.exists(self.path(idx, v))]

    def _key(self, path):
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)

    def segment(self, path):
        from pydub import AudioSegment
        k = self._key(path)
        with self.lock:
            sg = self._seg.get(k)
        if sg is None:
            sg = AudioSegment.from_file(path).set_sample_width(2)
            if sg.channels != 1:
                sg = sg.set_channels(1)
            with self.lock:
                if len(self._seg) > 60:
                    self._seg.clear()
                self._seg[k] = sg
        return sg

    def samples(self, sg):
        return np.frombuffer(sg.raw_data, dtype=np.int16).astype(np.float64) / 32768.0

    def info(self, idx, v):
        """{dur, peaks, auto:[a, b]} — длительность мс, огибающая для волны, автоотметка голоса."""
        p = self.path(idx, v)
        k = self._key(p)
        with self.lock:
            if k in self._peaks:
                return self._peaks[k]
        from core.voice_trim import voice_span
        sg = self.segment(p)
        x = self.samples(sg)
        n = PEAKS
        step = max(1, len(x) // n)
        pk = [round(float(np.abs(x[i:i + step]).max()), 3) if len(x[i:i + step]) else 0.0 for i in range(0, step * n, step)]
        top = max(pk) or 1.0
        pk = [round(a / top, 3) for a in pk]
        try:
            a, b, _ = voice_span(x, sg.frame_rate)
        except Exception:
            a, b = 0, len(sg)
        r = {"dur": len(sg), "peaks": pk, "auto": [int(a), int(b)]}
        with self.lock:
            self._peaks[k] = r
        return r

    def chain(self, idx, v, a=None, b=None, with_ctx=True):
        """(WAV-байты, сдвиг имени мс, длина имени мс): начало + пауза + имя[a:b] + пауза + конец. Частота — по началу фразы."""
        from pydub import AudioSegment
        from utils.wav_io import segment_to
        p = self.path(idx, v)
        key = (self._key(p), a, b, with_ctx)
        with self.lock:
            c = self._chain.get(key)
        if c:
            return c
        name = self.segment(p)
        if a is not None or b is not None:
            a = max(0, int(a or 0))
            b = len(name) if b is None else min(len(name), int(b))
            if b - a > 20:
                name = name[a:b].fade_in(6).fade_out(10)
        parts = []
        st, en = (self.ctx_path('start'), self.ctx_path('end')) if with_ctx else (None, None)
        rate = None
        segs = {}
        for key_, pth in (('start', st), ('end', en)):
            if pth:
                try:
                    segs[key_] = self.segment(pth)
                except Exception:
                    pass
        rate = (segs.get('start') or name).frame_rate
        out = AudioSegment.silent(0, frame_rate=rate)
        if 'start' in segs:
            out += segment_to(segs['start'], rate, 1) + AudioSegment.silent(GAP_BEFORE, frame_rate=rate)
        off = len(out)
        out += segment_to(name, rate, 1)
        nlen = len(out) - off
        if 'end' in segs:
            out += AudioSegment.silent(GAP_AFTER, frame_rate=rate) + segment_to(segs['end'], rate, 1)
        buf = io.BytesIO()
        out.export(buf, format='wav')
        data = (buf.getvalue(), off, nlen)
        with self.lock:
            if len(self._chain) > 40:
                self._chain.clear()
            self._chain[key] = data
        return data

    # ---------- выгрузка ----------
    def export(self, rows, out_dir=None):
        """rows — выбранные: [{idx, variant, a, b, user, ts, flag}]. Итоговые файлы в «Итог/» (целые, если границы не менялись)."""
        from utils.wav_io import export_like
        out_dir = out_dir or os.path.join(self.root, 'Итог')
        os.makedirs(out_dir, exist_ok=True)
        done, errors = 0, []
        report = [("№", "Имя", "Файл", "Вариант", "С, мс", "По, мс", "Кто выбрал", "Когда", "Пометка")]
        for r in sorted(rows, key=lambda r: r["idx"]):
            i, v = r["idx"], r.get("variant")
            line = [i + 1, self.names[i], self.stems[i] + '.wav', v or '', r.get("a") if v else '', r.get("b") if v else '',
                    r.get("user") or '', r.get("ts") or '', r.get("comment") or ('нужна правка' if r.get("flag") else '')]
            report.append(tuple(line))
            if not v:
                continue
            try:
                src = self.path(i, v)
                dst = os.path.join(out_dir, self.stems[i] + '.wav')
                sg = self.segment(src)
                a, b = r.get("a"), r.get("b")
                if a is None or b is None or (a <= 0 and b >= len(sg)):
                    tmp = dst + '.part'
                    with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
                        fo.write(fi.read())
                    os.replace(tmp, dst)
                else:
                    cut = sg[max(0, a):min(len(sg), b)].fade_in(4).fade_out(8)
                    tmp = dst + '.part.wav'
                    export_like(cut, tmp, src)
                    os.replace(tmp, dst)
                done += 1
            except Exception as e:
                errors.append(f'{self.names[i]}: {e}')
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=';')
        w.writerows(report)
        with open(os.path.join(out_dir, '_отчёт.csv'), 'w', encoding='utf-8-sig', newline='') as f:
            f.write(buf.getvalue())
        return {"done": done, "errors": errors, "dir": out_dir}
