"""Студия озвучки: материал для значений переменных.

Таблица с колонками <ru_var_…> / <kz_var_…> даёт «фразы-значения». Аудио для
них можно взять тремя путями:

  1. Сырой WAV — нарезка по паузам (миллисекунды паузы, чувствительность,
     запас по краям), потом конвейер чанков: чанки идут по порядку, а
     значения — по порядку таблицы. Распознавание речи не нужно. Если в
     одном чанке два значения — чанк разрезают; если одно значение разбито на
     несколько чанков — склеивают (после любой правки порядок значений
     пересчитывается сам).
  2. Запись в реальном времени — суфлёр, зажатый пробел, «Сборка» (это уже
     есть в tts_live.py, значения там — такие же фразы).
  3. Синтез — референс диктора (запись + её текст) клонируется сервисом
     синтеза на каждое значение; результат попадает на ту же ленту дублей.

Все три пути заканчиваются одинаково: дубль на ленте → «Сборка» (при желании) →
«Сохранить» → файл ложится в Значения/<лист>/<категория>/<значение>.wav."""

import os
import re
import shutil
import threading

import webview
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core.tts_flow import TTS_CHUNKS_DIR, TTS_CUT_PAD_MS, clean_name
from core.tts_synth import _SynthWorker
from core.ui_dialogs import ui_confirm
from utils.wav_io import wav_slice

VALS_SYNTH_DIR = 'Синтез_значения'
VALS_SYNTH_REF = '_референс'
_CHUNK_RE = re.compile(r'\d{4}(_\d+)?\.wav')


class _ValsSynthOwner:
    """Адаптер для очереди синтеза (_SynthWorker зовёт owner._synth_job)."""

    def __init__(self, api):
        self.api = api

    def _synth_job(self, uid, worker):
        self.api._vals_synth_job(uid, worker)

    def _synth_failed(self, uid, message):
        self.api._vals_synth_failed(uid, message)


class TtsValuesMixin:

    # ---------------- порядок: чанки по порядку, значения по порядку ----------------

    def _vals_reflow(self):
        """Дубли, привязанные «по порядку» (seq), заново раскладываются по
        значениям таблицы, которые ещё не сохранены и не закреплены вручную.
        Зовётся после любой правки: разрез, склейка, удаление дубля."""
        st = self._tts()
        takes = st["takes"]
        if not any(t.get("seq") for t in takes):
            return
        wd = st.get("work_dir")
        units = st["units"]
        pinned = {t["unit"] for t in takes
                  if t.get("unit") is not None and not t.get("rejected") and (t.get("approved") or not t.get("seq"))}
        free = [u["id"] for u in units
                if u["id"] not in pinned and not (wd and os.path.exists(self._tts_target(u)))]
        k = 0
        for t in takes:
            if not t.get("seq") or t.get("approved") or t.get("rejected"):
                continue
            if k < len(free):
                t.update({"unit": free[k], "status": "manual", "score": 0.0})
                k += 1
            else:
                t.update({"unit": None, "status": "none", "score": 0.0})

    def _vals_target_units(self):
        """Значения, которым ещё нужен звук (в порядке таблицы)."""
        st = self._tts()
        wd = st.get("work_dir")
        return [u for u in st["units"] if not (wd and os.path.exists(self._tts_target(u)))]

    # ---------------- ветка 1: сырой WAV → нарезка по паузам ----------------

    def tts_vals_pick_raw(self):
        """Выбрать сырой WAV, замерить его и предложить настройки нарезки."""
        st = self._tts()
        if not st["units"]:
            return {"error": "Сначала загрузите таблицу."}
        if getattr(self, '_tts_rec', None):
            return {"error": "Сейчас идёт запись с микрофона — сначала остановите её."}
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        path = picked if isinstance(picked, str) else picked[0]
        note = None
        if not st.get("work_dir"):
            note = self._tts_attach_folder(os.path.dirname(path))
            st = self._tts()
        try:
            audio = AudioSegment.from_file(path)
        except Exception as e:
            return {"error": f"Не удалось открыть файл «{os.path.basename(path)}»: {e}"}
        levels = self._frame_levels(audio)
        if not levels:
            return {"error": "Запись пустая или слишком короткая."}
        target = len(self._vals_target_units()) or len(st["units"])
        _, _, _, thresh, pause, expected = self._suggest_cut_settings(levels, target)
        self._vals_raw = {"path": path, "levels": levels, "len_ms": len(audio)}
        return {"name": os.path.basename(path), "duration_sec": round(len(audio) / 1000.0, 1),
                "suggested": {"pause": int(pause), "sens": int(thresh), "pad": TTS_CUT_PAD_MS},
                "predicted": int(expected), "values": target, "message": note}

    def tts_vals_predict(self, pause, sens):
        """Сколько кусков получится при таких настройках (быстрая оценка)."""
        raw = getattr(self, '_vals_raw', None)
        if not raw:
            return {"error": "Файл не выбран."}
        return {"chunks": self._count_ranges(raw["levels"], int(sens), int(pause))}

    def tts_vals_cut(self, pause, sens, pad):
        """Нарезать выбранный файл по паузам и разложить чанки по значениям."""
        raw = getattr(self, '_vals_raw', None)
        if not raw:
            return {"error": "Файл не выбран."}
        if getattr(self, '_vals_cutting', False):
            return {"error": "Нарезка уже идёт."}
        self._vals_cutting = True
        threading.Thread(target=self._vals_cut_job, args=(raw["path"], int(pause), int(sens), int(pad)),
                         daemon=True).start()
        return {"status": "started"}

    def _vals_cut_job(self, path, pause, sens, pad):
        try:
            st = self._tts()
            if any(not t.get("approved") for t in st["takes"]) and not ui_confirm(
                    "На ленте уже есть дубли. Нарезать заново?<br><br>Сохранённые значения останутся на месте, "
                    "несохранённые дубли заменятся новыми.", "Нарезать заново", "Отмена"):
                self._tts_push({"stage": "vals_cut", "cancelled": True, "state": self.tts_state()})
                return
            self._tts_push({"stage": "cut", "done": 0, "total": 0})
            audio = AudioSegment.from_file(path)
            ranges = detect_nonsilent(audio, min_silence_len=pause, silence_thresh=sens)
            if not ranges:
                self._tts_push({"stage": "error", "error": "В записи не нашлось речи при таких настройках."})
                return
            work_dir = st.get("work_dir") or self.tts_project_root(os.path.dirname(path))
            chunks_dir = os.path.join(work_dir, TTS_CHUNKS_DIR)
            os.makedirs(chunks_dir, exist_ok=True)
            keep = {t["file"] for t in st["takes"] if t.get("approved")}
            for f in os.listdir(chunks_dir):
                if _CHUNK_RE.fullmatch(f) and os.path.join(TTS_CHUNKS_DIR, f) not in keep:
                    try:
                        os.remove(os.path.join(chunks_dir, f))
                    except OSError:
                        pass
            # Одобренные дубли остаются; новые строятся заново с первого свободного номера.
            old = [t for t in st["takes"] if t.get("approved")]
            first = 1 + max([int(t.get("chunk") or 0) for t in old] + [0])
            takes = []
            for n, (a, b) in enumerate(ranges):
                lo, hi = max(0, a - pad), min(len(audio), b + pad)
                name = f"{first + n:04d}.wav"
                dst = os.path.join(chunks_dir, name)
                if not wav_slice(path, dst, lo, hi):
                    audio[lo:hi].export(dst, format="wav")
                takes.append({"file": os.path.join(TTS_CHUNKS_DIR, name), "start_ms": lo, "ms": hi - lo,
                              "orig": [lo, hi], "raw": path, "heard": '', "listened": False,
                              "chunk": first + n, "unit": None, "score": 0.0, "status": "none", "seq": True})
                if n % 20 == 0:
                    self._tts_push({"stage": "cut", "done": n + 1, "total": len(ranges)})
            st.update({"work_dir": work_dir, "raw_path": path, "takes": old + takes, "index": 0})
            self._vals_reflow()
            st["index"] = next((k for k, t in enumerate(st["takes"]) if t.get("seq") and not t.get("approved")), 0)
            self._tts_save()
            n_units = len(self._vals_target_units())
            msg = f"Нарезано кусков: {len(takes)}, значений в таблице: {n_units}."
            if len(takes) > n_units:
                msg += " Кусков больше — лишние удалите или склейте."
            elif len(takes) < n_units:
                msg += " Кусков меньше — если в куске два значения, разрежьте его в «Сборке»."
            self._tts_push({"stage": "vals_cut", "state": self.tts_state(), "message": msg})
        except Exception as e:
            self._tts_push({"stage": "error", "error": f"Не удалось нарезать запись: {e}"})
        finally:
            self._vals_cutting = False

    # ---------------- разрез и склейка чанков ----------------

    def _vals_new_file(self, t):
        """Свободное имя файла для нового дубля рядом с t (0007.wav → 0007_1.wav)."""
        st = self._tts()
        base = os.path.splitext(os.path.basename(t["file"]))[0].split('_')[0]
        used = {x.get("file") for x in st["takes"]}
        k = 1
        while os.path.join(TTS_CHUNKS_DIR, f"{base}_{k}.wav") in used or \
                os.path.exists(os.path.join(st["work_dir"], TTS_CHUNKS_DIR, f"{base}_{k}.wav")):
            k += 1
        return os.path.join(TTS_CHUNKS_DIR, f"{base}_{k}.wav")

    @staticmethod
    def _vals_pieces_to_clips(pieces):
        out, pos = [], 0
        for p in pieces:
            if p[0] == "silence":
                pos += p[1]
            else:
                out.append({"raw": p[1], "a": int(p[2]), "b": int(p[3]), "pos": pos, "cuts": []})
                pos += int(p[3] - p[2])
        return out

    def tts_take_split(self, i, ms):
        """Разрезать дубль на два в точке ms (время на дорожке «Сборки»):
        в куске два значения. Второй дубль встаёт сразу после первого."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"error": "Нет такого дубля."}
        t = st["takes"][i]
        if not st.get("work_dir"):
            return {"error": "Сначала создайте проект."}
        pieces = self._tts_timeline(self._tts_clips(t))
        ln = lambda p: (p[3] - p[2]) if p[0] == "audio" else p[1]
        total = sum(ln(p) for p in pieces)
        ms = int(ms)
        if ms < 80 or total - ms < 80:
            return {"error": "Разрез слишком близко к краю — поставьте метку ближе к середине."}
        left, right, cur = [], [], 0
        for p in pieces:
            n = ln(p)
            if cur + n <= ms:
                left.append(p)
            elif cur >= ms:
                right.append(p)
            else:
                k = ms - cur
                if p[0] == "audio":
                    left.append(("audio", p[1], p[2], p[2] + k))
                    right.append(("audio", p[1], p[2] + k, p[3]))
                else:
                    left.append(("silence", k))
                    right.append(("silence", n - k))
            cur += n
        a_clips, b_clips = self._vals_pieces_to_clips(left), self._vals_pieces_to_clips(right)
        if not a_clips or not b_clips:
            return {"error": "С одной из сторон не осталось звука."}
        second = {k: v for k, v in t.items() if k not in ("approved", "gain_db", "tempo", "clips", "clips_orig", "edit", "audacity")}
        second.update({"file": self._vals_new_file(t), "listened": False, "split": True, "unit": None,
                       "status": "none", "score": 0.0})
        t["approved"] = False
        for tk, clips in ((t, a_clips), (second, b_clips)):
            self._tts_render_clips(tk, clips)
            tk["clips"] = clips
            tk["clips_orig"] = [dict(c) for c in clips]
            tk["orig"] = [min(c["a"] for c in clips), max(c["b"] for c in clips)]
            tk["listened"] = False
        st["takes"].insert(i + 1, second)
        self._vals_reflow()
        st["index"] = i
        self._tts_save()
        return {**self.tts_state(), "message": "Разрезано на два дубля — значения расставлены заново по порядку."}

    def tts_take_merge(self, i):
        """Склеить дубль со следующим: одно значение было разбито на несколько чанков."""
        st = self._tts()
        if not (0 <= i < len(st["takes"]) - 1):
            return {"error": "Следующего дубля нет."}
        a, b = st["takes"][i], st["takes"][i + 1]
        if not st.get("work_dir"):
            return {"error": "Сначала создайте проект."}
        a_clips, b_clips = self._tts_clips(a), self._tts_clips(b)
        base_a = min(c["pos"] for c in a_clips)
        end_a = base_a + int(a.get("ms") or 0)
        base_b = min(c["pos"] for c in b_clips)
        merged = [dict(c) for c in a_clips] + [dict(c, pos=end_a + (c["pos"] - base_b)) for c in b_clips]
        a["approved"] = False
        self._tts_render_clips(a, merged)
        a["clips"] = merged
        a["clips_orig"] = [dict(c) for c in merged]
        a["listened"] = False
        a["heard"] = ''
        old_file = os.path.join(st["work_dir"], b["file"])
        if not any(o is not b and o.get("file") == b["file"] for o in st["takes"]) and os.path.exists(old_file):
            try:
                self._tts_trash(old_file)
            except OSError:
                pass
        del st["takes"][i + 1]
        self._vals_reflow()
        st["index"] = i
        self._tts_save()
        return {**self.tts_state(), "message": "Склеено — значения расставлены заново по порядку."}

    # ---------------- ветка 3: синтез по референсу ----------------

    def _vals_synth(self):
        st = self._tts()
        sy = st.get("vals_synth")
        if not sy:
            sy = st["vals_synth"] = {"ref": {}, "tries": {}}
        sy.setdefault("ref", {})
        sy.setdefault("tries", {})
        return sy

    def _vals_unit_lang(self, u):
        return u.get("lang") or self._tts().get("lang", "ru")

    def tts_vals_synth_state(self):
        st = self._tts()
        sy = self._vals_synth()
        w = getattr(self, '_vals_worker', None)
        queued = set(w.jobs) | ({w.current} if w and w.current is not None else set()) if w else set()
        have = {t["unit"] for t in st["takes"] if t.get("synth") and t.get("unit") is not None}
        langs = []
        for lg in sorted({self._vals_unit_lang(u) for u in st["units"]}):
            ref = sy["ref"].get(lg) or {}
            mine = [u for u in st["units"] if self._vals_unit_lang(u) == lg]
            langs.append({"lang": lg, "units": len(mine), "ref": os.path.basename(ref.get("file", '')) or None,
                          "ref_ok": bool(ref.get("file") and os.path.exists(ref["file"])),
                          "text": ref.get("text", ''),
                          "done": sum(1 for u in mine if u["id"] in have),
                          "queued": sum(1 for u in mine if u["id"] in queued)})
        return {"langs": langs, "has_project": bool(st.get("work_dir")), "queue": len(queued),
                "errors": dict(sy.get("errors") or {})}

    def tts_vals_synth_pick_ref(self, lang):
        """Референс — запись диктора с короткой фразой: по её голосу сервис озвучит значения."""
        st = self._tts()
        if not st.get("work_dir"):
            picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not picked:
                return {"error": "cancel"}
            self._tts_attach_folder(picked if isinstance(picked, str) else picked[0])
            st = self._tts()
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        dst_dir = os.path.join(st["work_dir"], VALS_SYNTH_DIR, VALS_SYNTH_REF)
        os.makedirs(dst_dir, exist_ok=True)
        dst = os.path.join(dst_dir, f"{lang}_{os.path.basename(src)}")
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)
        self._vals_synth()["ref"].setdefault(lang, {})["file"] = dst
        self._tts_save()
        return self.tts_vals_synth_state()

    def tts_vals_synth_set_text(self, lang, text):
        """Что сказано в референсе (дословно)."""
        self._vals_synth()["ref"].setdefault(lang, {})["text"] = str(text or '').strip()
        self._tts_save()
        return self.tts_vals_synth_state()

    def _vals_worker_get(self):
        w = getattr(self, '_vals_worker', None)
        if w is None or not w.is_alive():
            w = self._vals_worker = _SynthWorker(_ValsSynthOwner(self))
            w.start()
        return w

    def tts_vals_synth_run(self, uid=None, lang=None):
        """В очередь на синтез: одно значение (uid) или все, у которых ещё нет
        ни дубля, ни сохранённого файла (по языку — если задан)."""
        st = self._tts()
        sy = self._vals_synth()
        if not st.get("work_dir"):
            return {"error": "Сначала выберите папку проекта."}
        todo = []
        if uid is not None:
            if not (0 <= int(uid) < len(st["units"])):
                return {"error": "Нет такого значения."}
            todo = [st["units"][int(uid)]]
        else:
            have = {t["unit"] for t in st["takes"] if t.get("unit") is not None and not t.get("rejected")}
            todo = [u for u in self._vals_target_units() if u["id"] not in have]
            if lang:
                todo = [u for u in todo if self._vals_unit_lang(u) == lang]
        if not todo:
            return {**self.tts_vals_synth_state(), "error": "Синтезировать нечего: у всех значений уже есть дубль или файл."}
        for u in todo:
            ref = sy["ref"].get(self._vals_unit_lang(u)) or {}
            if not ref.get("file") or not os.path.exists(ref["file"]):
                return {**self.tts_vals_synth_state(),
                        "error": f"Нет референса для языка {self._vals_unit_lang(u).upper()}."}
            if not ref.get("text"):
                return {**self.tts_vals_synth_state(),
                        "error": f"Впишите текст референса для языка {self._vals_unit_lang(u).upper()}."}
        w = self._vals_worker_get()
        for u in todo:
            w.add(u["id"], front=uid is not None)
        self._tts_push({"stage": "vals_synth", "state": self.tts_state(), "synth": self.tts_vals_synth_state()})
        return self.tts_vals_synth_state()

    def tts_vals_synth_stop(self):
        w = getattr(self, '_vals_worker', None)
        if w:
            w.clear()
        return self.tts_vals_synth_state()

    def _vals_synth_job(self, uid, worker):
        st = self._tts()
        u = st["units"][uid]
        lang = self._vals_unit_lang(u)
        sy = self._vals_synth()
        ref = sy["ref"][lang]
        tries = sy["tries"].get(str(uid), 0) + 1
        vdir = os.path.join(st["work_dir"], VALS_SYNTH_DIR, lang.upper())
        os.makedirs(vdir, exist_ok=True)
        raw = os.path.join(vdir, f"{uid + 1:04d}_v{tries}.wav")
        self._synth_request(worker, ref["file"], ref["text"], lang, u["text"], raw)
        clean = os.path.join(vdir, f"{uid + 1:04d}_t{tries}.wav")
        self._synth_trim(raw, clean)                       # тишина по краям — долой
        ms = len(AudioSegment.from_file(clean))
        rel = os.path.join(TTS_CHUNKS_DIR, f"s{uid + 1:04d}_{tries}.wav")
        os.makedirs(os.path.join(st["work_dir"], TTS_CHUNKS_DIR), exist_ok=True)
        shutil.copy2(clean, os.path.join(st["work_dir"], rel))
        sy["tries"][str(uid)] = tries
        (sy.get("errors") or {}).pop(str(uid), None)
        # Прежний синтез этого значения заменяется новым дублем.
        st["takes"] = [t for t in st["takes"] if not (t.get("synth") and t.get("unit") == uid and not t.get("approved"))]
        st["takes"].append({"file": rel, "start_ms": 0, "ms": ms, "orig": [0, ms], "raw": clean,
                            "heard": u["text"], "listened": False, "chunk": uid + 1, "unit": uid,
                            "score": 0.0, "status": "manual", "synth": True})
        self._tts_save()
        self._tts_push({"stage": "vals_synth", "state": self.tts_state(), "synth": self.tts_vals_synth_state(),
                        "uid": uid, "message": f"Синтезировано: {u['value']}"})

    def _vals_synth_failed(self, uid, message):
        sy = self._vals_synth()
        sy.setdefault("errors", {})[str(uid)] = message
        self._tts_push({"stage": "vals_synth", "synth": self.tts_vals_synth_state(), "uid": uid, "error": message})

    # ---------------- «Сборка»: короткий вариант с контекстом ----------------
    # Значение слушают в окружении: конец стартовой фразы + значение + начало
    # конечной. У стартовой фразы чуть сокращается начало, у конечной — конец
    # (чтобы не слушать длинное целиком). Файлы на диске не трогаются: короткий
    # вариант собирается во временный файл.

    def _vals_keep_ms(self):
        return int((self._tts().get("vals_ctx") or {}).get("keep_ms", 1500))

    def _vals_trim(self, seg, keep_ms, head):
        """head=True — оставить хвост (стартовая фраза: начало срезается),
        False — оставить начало (конечная фраза: конец срезается). Разрез — в тишине."""
        if len(seg) <= keep_ms + 200:
            return seg
        cut = len(seg) - keep_ms if head else keep_ms
        q = self._tts_quiet_point(seg, max(0, cut - 250) / 1000.0, min(len(seg), cut + 250) / 1000.0)
        return seg[q:] if head else seg[:q]

    def _vals_unit_audio(self, st, unit, take=None):
        """Звук фразы для сборки: выбранный дубль, иначе сохранённый файл, иначе последний дубль."""
        wd = st.get("work_dir")
        if take is not None:
            path = os.path.join(wd, take["file"])
            if os.path.exists(path):
                return AudioSegment.from_file(self._tts_preview(path, *self._tts_sound(take)))
        target = self._tts_target(unit)
        if wd and os.path.exists(target):
            return AudioSegment.from_file(target)
        for t in reversed(st["takes"]):
            if t.get("unit") == unit["id"] and not t.get("rejected"):
                path = os.path.join(wd, t["file"])
                if os.path.exists(path):
                    return AudioSegment.from_file(self._tts_preview(path, *self._tts_sound(t)))
        return None

    def tts_ctx_play(self, i):
        """Прослушать дубль в коротком контексте: [стартовая] + значение + [конечная]."""
        st = self._tts()
        if not (0 <= i < len(st["takes"])):
            return {"playing": False, "error": "Нет такого дубля."}
        t = st["takes"][i]
        uid = t.get("unit")
        if uid is None or uid >= len(st["units"]):
            return {"playing": False, "error": "Дубль не привязан к фразе."}
        u = st["units"][uid]
        cat = u.get("cat")
        if not cat or not st.get("work_dir"):
            return {"playing": False, "error": "Для этой фразы нет контекста."}
        find = lambda role: next((x for x in st["units"] if x.get("ctx") and x.get("cat") == cat and x.get("role") == role), None)
        start_u, end_u = find("start"), find("end")
        if not start_u and not end_u:
            return {"playing": False, "error": "Стартовая и конечная фразы не заданы — задайте их в «Фразы_Переменные»."}
        # значение: сам дубль (если это значение) или любое готовое значение этой категории
        if u["kind"] == "value":
            value = self._vals_unit_audio(st, u, t)
        else:
            value = next((a for a in (self._vals_unit_audio(st, x) for x in st["units"]
                                      if x.get("kind") == "value" and x.get("cat") == cat) if a is not None), None)
        keep = self._vals_keep_ms()
        parts, used = [], []
        if start_u:
            a = self._vals_unit_audio(st, start_u, t if u is start_u else None)
            if a is not None:
                parts.append(self._vals_trim(a, keep, True))
                used.append("начало")
        if value is not None:
            parts.append(value)
            used.append("значение")
        if end_u:
            a = self._vals_unit_audio(st, end_u, t if u is end_u else None)
            if a is not None:
                parts.append(self._vals_trim(a, keep, False))
                used.append("конец")
        if len(parts) < 2:
            return {"playing": False, "error": "Для контекста не хватает записей: запишите (или сохраните) стартовую, конечную фразы и значение."}
        rate = parts[0].frame_rate
        out = None
        for p in parts:
            p = p.set_frame_rate(rate).set_channels(1)
            out = p if out is None else out + p
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_vals_ctx_{os.getpid()}.wav")
        out.export(tmp, format="wav")
        self._tts_mark_listened()
        self.player.play(tmp)
        return {"playing": True, "duration": len(out) / 1000.0, "parts": used}

    # ---------------- Фразы_Переменные: правка готовых файлов ----------------

    def _vals_take_from_file(self, uid, src, tag):
        """Файл → дубль на ленте (копия в «Чанки»): правится в «Сборке», исходник не трогается."""
        st = self._tts()
        wd = st.get("work_dir")
        if not wd:
            return None
        os.makedirs(os.path.join(wd, TTS_CHUNKS_DIR), exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(wd, TTS_CHUNKS_DIR, f"{tag}{uid + 1:04d}_{n}.wav")):
            n += 1
        rel = os.path.join(TTS_CHUNKS_DIR, f"{tag}{uid + 1:04d}_{n}.wav")
        dst = os.path.join(wd, rel)
        if src.lower().endswith('.wav'):
            shutil.copy2(src, dst)
        else:
            AudioSegment.from_file(src).export(dst, format="wav")
        ms = len(AudioSegment.from_file(dst))
        st["takes"] = [t for t in st["takes"] if not (t.get("unit") == uid and t.get("piece_edit") and not t.get("approved"))]
        st["takes"].append({"file": rel, "start_ms": 0, "ms": ms, "orig": [0, ms], "raw": dst,
                            "heard": st["units"][uid]["text"], "listened": False, "chunk": uid + 1, "unit": uid,
                            "score": 0.0, "status": "manual", "piece_edit": True})
        st["index"] = len(st["takes"]) - 1
        self._tts_save()
        return st["index"]

    def tts_piece_edit(self, unit_id):
        """Править готовую фразу: открыть её в «Сборке» (подрезка, вырезы, громкость, темп)."""
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return {"error": "Нет такой фразы."}
        # уже есть дубль этой фразы — просто к нему
        for k in range(len(st["takes"]) - 1, -1, -1):
            t = st["takes"][k]
            if t.get("unit") == unit_id and not t.get("rejected") and not t.get("approved"):
                st["index"] = k
                self._tts_save()
                return self.tts_state()
        target = self._tts_target(st["units"][unit_id])
        if not st.get("work_dir") or not os.path.exists(target):
            return {"error": "Файла этой фразы ещё нет — запишите её, нарежьте из WAV или синтезируйте."}
        self._vals_take_from_file(unit_id, target, "e")
        return self.tts_state()

    def tts_piece_replace(self, unit_id):
        """Заменить фразу своим файлом: он встаёт на ленту дублей, дальше — «Сборка» и «Сохранить»."""
        st = self._tts()
        if not (0 <= unit_id < len(st["units"])):
            return {"error": "Нет такой фразы."}
        if not st.get("work_dir"):
            return {"error": "Сначала выберите папку проекта."}
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        try:
            self._vals_take_from_file(unit_id, src, "r")
        except Exception as e:
            return {"error": f"Не удалось открыть файл: {e}"}
        return self.tts_state()
