"""Живая запись в TTS-проекте: читаете фразы в микрофон, а программа в
паузах распознаёт уже сказанное, находит фразы таблицы, вырезает их и
выкладывает дубли на ленту — сдавать готовое можно, не останавливая запись.

Звук пишется на диск сразу в полном качестве (24 бита, частота микрофона),
а для распознавания параллельно копится облегчённая копия 16 кГц. Готовым
кусок считается, когда после него была пауза (LIVE_SILENCE_MS): фраза,
которая ещё звучит, не режется посередине."""

import os
import queue
import struct
import threading
import time

import numpy as np
import webview
from pydub import AudioSegment

from core.auto_check import _lat_to_cyr, _norm, _ratio
from core.tts_flow import FIND_SCORE, TTS_CHUNKS_DIR, align_stream, end_word_ok, var_label

LIVE_RATE = 16000          # копия для распознавания
LIVE_SILENCE_MS = 700      # пауза, после которой сказанное считается готовым
LIVE_MIN_REGION_MS = 600   # меньше — ещё рано разбирать
LIVE_SHORT_SILENCE_MS = 350  # после короткой реплики — разбираем быстрее
LIVE_SHORT_SPEECH_MS = 1200  # «короткая» — столько речи или меньше
LIVE_FORCE_MS = 40000      # без пауз дольше — режем в самом тихом месте
LIVE_FRAME_MS = 20
LIVE_NOISE_ABOVE_DB = 6    # речь — громче фона хотя бы на столько
# Шумно, вокруг разговаривают: речью считаем только то, что не тише вашего
# голоса больше чем на LIVE_VOICE_DROP_DB (гарнитура у рта — вы громче всех).
LIVE_VOICE_DROP_DB = 18
LIVE_VOICE_SPREAD_DB = 22   # голос заметно громче фона — значит, есть по чему отсчитывать
RECORDS_DIR = 'Записи'
LIVE_WAIT_MAX_MS = 45000   # недочитанную фразу ждём не дольше
PROMPT_PREFIX_SCORE = 0.6  # сказанное похоже на начало фразы — ждём продолжения


class LiveRecorder:
    """Запись с микрофона в WAV (24 бита) + копия 16 кГц в памяти."""

    def __init__(self, path, device=None):
        import sounddevice as sd
        self.sd = sd
        info = sd.query_devices(device, 'input')
        self.rate = int(info['default_samplerate']) or 48000
        self.device = device
        self.device_name = info['name']
        self.path = path
        self.q = queue.Queue()
        self.ana = bytearray()          # int16 16 кГц моно
        self.frames = 0
        self.level_db = -90.0
        self.running = False
        self.error = None
        self._f = open(path, 'wb')
        self._write_header(0xFFFFFFFF - 36)   # пока пишем — «до конца файла»
        self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype='int32',
                                     device=device, callback=self._callback, blocksize=0)

    def _write_header(self, data_size):
        block, bits = 3, 24
        fmt = struct.pack('<HHIIHH', 1, 1, self.rate, self.rate * block, block, bits)
        self._f.seek(0)
        self._f.write(b'RIFF' + struct.pack('<I', min(0xFFFFFFFF, 36 + data_size)) + b'WAVE'
                      + b'fmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', min(0xFFFFFFFF, data_size)))
        self._f.seek(0, 2)

    def _callback(self, indata, frames, t, status):
        self.q.put(indata[:, 0].copy())

    def start(self):
        self.running = True
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()
        self.stream.start()

    def _write_loop(self):
        while self.running or not self.q.empty():
            try:
                block = self.q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                v = (block >> 8).astype('<i4')                   # 24 старших бита
                self._f.write(v.view(np.uint8).reshape(-1, 4)[:, :3].tobytes())
                self._f.flush()
                self.frames += len(block)
                x = block.astype(np.float32) / 2147483648.0
                peak = float(np.abs(x).max()) if len(x) else 0.0
                self.level_db = 20 * np.log10(peak) if peak > 1e-6 else -90.0
                self.ana += self._to16k(x).tobytes()
            except Exception as e:      # диск переполнен и т.п. — запись встаёт, но не роняет программу
                self.error = str(e)
                self.running = False

    def _to16k(self, x):
        if self.rate == LIVE_RATE:
            y = x
        elif self.rate % LIVE_RATE == 0:
            k = self.rate // LIVE_RATE
            if not hasattr(self, '_tail'):
                self._tail = np.zeros(0, np.float32)
            x = np.concatenate([self._tail, x])
            n = len(x) // k * k
            self._tail = x[n:]
            y = x[:n].reshape(-1, k).mean(axis=1)
        else:
            n = int(round(len(x) * LIVE_RATE / self.rate))
            y = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x) if n else np.zeros(0)
        return np.clip(y * 32767, -32768, 32767).astype('<i2')

    @property
    def ana_ms(self):
        return len(self.ana) // 2 * 1000 // LIVE_RATE

    def ana_segment(self, a_ms, b_ms):
        a, b = a_ms * LIVE_RATE // 1000 * 2, b_ms * LIVE_RATE // 1000 * 2
        return AudioSegment(data=bytes(self.ana[a:b]), sample_width=2, frame_rate=LIVE_RATE, channels=1)

    def stop(self):
        try:
            self.stream.stop()
            self.stream.close()
        except Exception:
            pass
        self.running = False
        if hasattr(self, '_writer'):
            self._writer.join(timeout=5)
        try:
            self._write_header(self.frames * 3)
            self._f.close()
        except Exception:
            pass


class TtsLiveMixin:

    def tts_rec_devices(self):
        try:
            import sounddevice as sd
        except Exception:
            return {"error": "Для записи нужен модуль sounddevice. В командной строке выполните:\n"
                             "pip install sounddevice"}
        try:
            default = sd.default.device[0]
            devs = [{"id": i, "name": d['name'], "default": i == default}
                    for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]
            # Один и тот же микрофон Windows показывает через разные «host API» —
            # оставляем вариант из основного (MME / системного по умолчанию).
            host = sd.query_hostapis(sd.default.hostapi)['devices'] if sd.default.hostapi >= 0 else None
            if host:
                devs = [d for d in devs if d["id"] in host] or devs
        except Exception as e:
            return {"error": f"Не удалось получить список микрофонов: {e}"}
        if not devs:
            return {"error": "Не найден ни один микрофон."}
        return {"devices": devs}

    def tts_rec_start(self, device=None):
        st = self._tts()
        if not st["units"]:
            return {"error": "Сначала загрузите таблицу."}
        if getattr(self, '_tts_rec', None):
            return {"error": "Запись уже идёт."}
        if not st.get("work_dir"):
            picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if not picked:
                return {"error": "cancel"}
            st["work_dir"] = picked if isinstance(picked, str) else picked[0]
        model, err = self._auto_check_model()
        if err:
            return {"error": "need_model"} if not isinstance(err, str) else {"error": err}
        folder = os.path.join(st["work_dir"], RECORDS_DIR)
        os.makedirs(folder, exist_ok=True)
        os.makedirs(os.path.join(st["work_dir"], TTS_CHUNKS_DIR), exist_ok=True)
        path = os.path.join(folder, time.strftime('Запись_%Y-%m-%d_%H-%M-%S.wav'))
        try:
            rec = LiveRecorder(path, None if device in (None, '', -1) else int(device))
            rec.start()
        except Exception as e:
            return {"error": f"Не удалось включить микрофон: {e}"}
        self._tts_rec = rec
        self._tts_live_lock = threading.RLock()
        self._tts_live = {"model": model, "done_ms": 0, "from_ms": 0, "busy": False, "added": 0,
                          "restarts": 0, "expected": self._tts_live_expected()}
        self._tts_prompt_fix()
        self._tts_save()
        threading.Thread(target=self._tts_live_loop, daemon=True).start()
        return {"status": "ok", "device": rec.device_name, "rate": rec.rate}

    def _tts_live_expected(self):
        """С какой строки таблицы диктор, скорее всего, продолжит: после
        последней найденной фразы."""
        takes = self._tts()["takes"]
        units = [t["unit"] for t in takes if t.get("unit") is not None]
        return units[-1] + 1 if units else 0

    def tts_rec_stop(self):
        rec = getattr(self, '_tts_rec', None)
        if not rec:
            return self.tts_state()
        rec.stop()
        self._tts_live["stopping"] = True
        return {"status": "stopping"}

    def tts_rec_status(self):
        rec = getattr(self, '_tts_rec', None)
        live = getattr(self, '_tts_live', None) or {}
        if not rec:
            return {"recording": False}
        return {"recording": rec.running, "seconds": rec.frames / rec.rate, "level_db": round(rec.level_db, 1),
                "device": rec.device_name, "busy": live.get("busy", False),
                "pending_s": round(max(0, rec.ana_ms - live.get("done_ms", 0)) / 1000, 1),
                "added": live.get("added", 0), "restarts": live.get("restarts", 0),
                "waiting": live.get("waiting", False), "paused": bool(live.get("paused")),
                "hearing": bool(live.get("hearing")),
                "error": rec.error, "prompt": self.tts_prompt_info()}

    # ---------------- разбор в паузах ----------------

    def _tts_live_loop(self):
        rec, live = self._tts_rec, self._tts_live
        try:
            while True:
                stopping = live.get("stopping") or not rec.running
                total = rec.ana_ms
                if live.get("paused"):
                    # Пауза (Space): сказанное не разбираем вовсе.
                    with self._tts_live_lock:
                        live["done_ms"] = live["from_ms"] = total
                        live["hearing"] = live["waiting"] = False
                    if stopping:
                        break
                    time.sleep(0.15)
                    continue
                # «Готово» (клик по тексту / Enter): разбираем сразу, не ждём тишины.
                forced = live.pop("force_cut", None)
                if forced is not None:
                    cut = max(forced, live["done_ms"] + 1)
                else:
                    cut = total if stopping else self._tts_live_cut(rec, live["done_ms"], total)
                final = stopping or forced is not None
                if cut and cut - live["done_ms"] >= (1 if final else LIVE_MIN_REGION_MS):
                    live["busy"] = True
                    self._tts_push({"stage": "live_busy", "busy": True})
                    with self._tts_live_lock:
                        try:
                            # Разбираем с from_ms: недочитанная фраза ждёт продолжения
                            # и разбирается заново вместе с ним.
                            live["from_ms"] = self._tts_live_region(rec, live["from_ms"], cut, final=final)
                        except Exception as e:
                            live["from_ms"] = cut
                            self._tts_push({"stage": "live_error", "error": f"Не удалось разобрать кусок записи: {e}"})
                        live["done_ms"] = max(live["done_ms"], cut)
                    live["busy"] = False
                    live["hearing"] = False
                    self._tts_push({"stage": "live_busy", "busy": False, "waiting": live.get("waiting", False)})
                if stopping:
                    break
                time.sleep(0.15)
        finally:
            self._tts_rec = None
            self._tts_save()
            self._tts_push({"stage": "live_done", "state": self.tts_state(), "error": rec.error})

    # ---------------- суфлёр ----------------
    # Фразы по порядку таблицы. Обычная фраза — одна строка; фраза с
    # переменными — вся цепочка start → [значение] → … → end целиком (читается
    # одной фразой с любым значением, кусочки вырежутся сами).

    def _tts_prompt_items(self):
        st = self._tts()
        items, seen = [], set()
        for u in st["units"]:
            if u["id"] in seen:
                continue
            ch = st["chains"][u["chain"]] if u.get("chain") is not None and u["chain"] < len(st.get("chains", [])) else None
            ids = ch["parts"] if ch else [u["id"]]
            seen.update(ids)
            items.append(ids)
        return items

    def _tts_prompt_needed(self, ids):
        """Нужно ли ещё читать: хоть один кусочек не сохранён и не записан."""
        st = self._tts()
        have = {t["unit"] for t in st["takes"] if t.get("unit") is not None and not t.get("rejected")}
        return any(i not in have and not (st.get("work_dir") and os.path.exists(self._tts_target(st["units"][i])))
                   for i in ids)

    def _tts_prompt_fix(self, start=None):
        """Встать на ближайшую фразу, которую ещё нужно прочитать."""
        st = self._tts()
        items = self._tts_prompt_items()
        if not items:
            st["prompt_pos"] = 0
            return
        pos = st.get("prompt_pos", 0) if start is None else start
        pos = max(0, min(pos, len(items) - 1))
        for k in list(range(pos, len(items))) + list(range(0, pos)):
            if self._tts_prompt_needed(items[k]):
                st["prompt_pos"] = k
                return
        st["prompt_pos"] = pos

    def tts_prompt_info(self):
        st = self._tts()
        items = self._tts_prompt_items()
        if not items:
            return None
        pos = max(0, min(st.get("prompt_pos", 0), len(items) - 1))
        units = st["units"]

        def show(ids):
            return [{"id": i, "name": units[i]["name"], "text": units[i]["text"], "role": units[i]["role"],
                     "vars": units[i].get("vars", []),
                     "var_before": units[i].get("var_before") if k == 0 else None,
                     "var_after": units[i].get("var_after")} for k, i in enumerate(ids)]
        left = sum(1 for ids in items if self._tts_prompt_needed(ids))
        nxt = next((items[k] for k in range(pos + 1, len(items)) if self._tts_prompt_needed(items[k])), None)
        return {"pos": pos, "total": len(items), "left": left, "done": left == 0,
                "var_cols": [{"key": k, "label": var_label(k)} for k in (st.get("var_cols") or [])],
                "current": show(items[pos]), "next": show(nxt) if nxt else None}

    def tts_prompt_move(self, step):
        """«Назад» — на предыдущую фразу (в т.ч. уже записанную — перечитать);
        «Пропустить» — на следующую, которую ещё нужно прочитать."""
        st = self._tts()
        items = self._tts_prompt_items()
        if not items:
            return None
        pos = st.get("prompt_pos", 0)
        if step < 0:
            st["prompt_pos"] = max(0, pos - 1)
        else:
            nxt = next((k for k in range(pos + 1, len(items)) if self._tts_prompt_needed(items[k])), None)
            st["prompt_pos"] = nxt if nxt is not None else min(len(items) - 1, pos + 1)
        live = getattr(self, '_tts_live', None)
        rec = getattr(self, '_tts_rec', None)
        if live and rec:
            live["from_ms"] = rec.ana_ms        # недочитанное к старой фразе не относим
        self._tts_save()
        return self.tts_prompt_info()

    @staticmethod
    def _tts_find_window(wn, text, start=0):
        """Окно слов [i, j) от start, дословно похожее на text (строго целиком)."""
        t = _lat_to_cyr(_norm(text))
        n = max(1, len(t.split()))
        best = (0.0, None, None)
        for i in range(start, len(wn)):
            for size in range(max(1, n - 2), n + 3):
                j = i + size
                if j > len(wn):
                    break
                if not end_word_ok(wn[i:j], t):
                    continue
                sc = _ratio(' '.join(wn[i:j]), t)
                if sc > best[0] + 1e-9:
                    best = (sc, i, j)
        return best

    def _tts_prompt_match(self, stream, ids):
        """Прочитана ли текущая фраза суфлёра: все её кусочки по порядку.
        → [(i, j, info)] или None."""
        st = self._tts()
        wn = [_lat_to_cyr(_norm(w[0])) for w in stream]
        spans, cur = [], 0
        for uid in ids:
            sc, i, j = self._tts_find_window(wn, st["units"][uid]["text"], cur)
            n = len(_norm(st["units"][uid]["text"]).split())
            if i is None or sc < (0.9 if n <= 2 else FIND_SCORE):
                return None
            spans.append((i, j, {"unit": uid, "score": round(sc, 3), "status": "ok" if sc >= 0.85 else "doubt"}))
            cur = j
        return spans

    def _tts_prompt_partial(self, stream, ids):
        """Сказанное похоже на начало текущей фразы — фразу дочитывают."""
        st = self._tts()
        heard = _lat_to_cyr(_norm(' '.join(w[0] for w in stream)))
        full = _lat_to_cyr(_norm(' '.join(st["units"][i]["text"] for i in ids)))
        if not heard or not full:
            return False
        n = len(heard.split())
        head = ' '.join(full.split()[:n + 1])
        return _ratio(heard, head) >= PROMPT_PREFIX_SCORE

    @staticmethod
    def _tts_live_levels(seg):
        frames = len(seg) // LIVE_FRAME_MS
        if not frames:
            return np.zeros(0)
        x = np.frombuffer(seg.raw_data, '<i2')[:frames * LIVE_FRAME_MS * LIVE_RATE // 1000].astype(np.float32)
        x = x.reshape(frames, -1)
        rms = np.sqrt((x ** 2).mean(axis=1)) / 32768.0
        return 20 * np.log10(np.maximum(rms, 1e-6))

    def _tts_live_cut(self, rec, done_ms, total_ms):
        """Где уже можно резать: середина последней паузы ≥ LIVE_SILENCE_MS
        (или начало паузы, которая идёт прямо сейчас). None — ещё рано."""
        if total_ms - done_ms < LIVE_MIN_REGION_MS:
            return None
        seg = rec.ana_segment(done_ms, total_ms)
        lv = self._tts_live_levels(seg)
        if not len(lv):
            return None
        hist = self._tts_live_levels(rec.ana_segment(max(0, total_ms - 60000), total_ms))
        floor = float(np.percentile(hist, 10)) if len(hist) else -70.0
        thr = floor + LIVE_NOISE_ABOVE_DB
        if len(hist) >= 150:                                   # хотя бы 3 с истории
            voice = float(np.percentile(hist, 95))
            if voice - floor > LIVE_VOICE_SPREAD_DB:
                thr = max(thr, voice - LIVE_VOICE_DROP_DB)     # чужие голоса вдалеке — это «тишина»
        quiet = lv < thr
        # «Слышу речь»: в ещё не разобранном куске есть голос.
        live = getattr(self, '_tts_live', None)
        if live is not None:
            live["hearing"] = bool((~quiet).any())
        if not (~quiet).any():
            # Одна тишина — разбирать нечего, но и копить незачем.
            return total_ms - 300 if total_ms - done_ms > 3000 else None
        # Короткая реплика (обычно команда) — не ждём длинной паузы.
        voiced_ms = int((~quiet).sum()) * LIVE_FRAME_MS
        need = (LIVE_SHORT_SILENCE_MS if voiced_ms <= LIVE_SHORT_SPEECH_MS else LIVE_SILENCE_MS) // LIVE_FRAME_MS
        best, run = None, 0
        for k, q in enumerate(quiet):
            run = run + 1 if q else 0
            if run >= need:
                start = k - run + 1
                best = start + min(run, need) // 2          # не середина длинной тишины — недалеко от речи
        if best is not None and (~quiet[:best]).any():
            return done_ms + best * LIVE_FRAME_MS
        if total_ms - done_ms > LIVE_FORCE_MS:
            tail = lv[-500:]
            return done_ms + (len(lv) - len(tail) + int(np.argmin(tail))) * LIVE_FRAME_MS
        return None

    def _tts_live_region(self, rec, a_ms, b_ms, final=False):
        """Разбор куска записи [a_ms, b_ms). Возвращает, с какого места
        разбирать дальше (начало недочитанной фразы — если её ещё дочитывают)."""
        st = self._tts()
        live = self._tts_live
        a_ms = max(a_ms, live.get("mute_until", 0))      # пока звучало прослушивание (P) — не слушаем
        if b_ms <= a_ms:
            return b_ms
        seg = rec.ana_segment(a_ms, b_ms)
        if not len(seg):
            return b_ms
        samples = np.frombuffer(seg.raw_data, '<i2').astype(np.float32) / 32768.0
        words = self._tts_transcribe_pack(live["model"], [{"index": 0, "audio": samples, "ms": len(seg)}],
                                          'kk' if st["lang"] == 'kz' else 'ru', live=True)[0]
        text = ''.join(w[0] for w in words).strip()
        if not words or self._asr_is_noise(text):
            live["waiting"] = False
            return b_ms
        off = a_ms / 1000.0
        stream = [(w, off + s_, off + e, 0) for w, s_, e in words]
        state = self._tts_live_words(rec, seg, a_ms, stream, 0, len(stream), final=final)
        if state == "partial":
            live["waiting"] = True
            return max(a_ms, int(stream[0][1] * 1000) - 150)          # ждём, пока дочитают
        live["waiting"] = False
        if state == "none":
            # Отклик: сказанное не стало фразой таблицы.
            self._tts_push({"stage": "live_miss", "heard": text, "paused": False})
        return b_ms

    def _tts_live_words(self, rec, seg, a_ms, stream, i0, j0, final):
        """Слова stream[i0:j0] — текущая фраза суфлёра? → 'captured' |
        'partial' (похоже на начало — ждать) | 'other' (нашли другие фразы) | 'none'."""
        st = self._tts()
        live = self._tts_live
        sub = stream[i0:j0]
        items = self._tts_prompt_items()
        pos = st.get("prompt_pos", 0)
        ids = items[pos] if 0 <= pos < len(items) else None
        spans = self._tts_prompt_match(sub, ids) if ids else None
        advanced = False
        if spans:
            advanced = True
        elif ids and not final and self._tts_prompt_partial(sub, ids):
            return "partial"
        else:
            # Прочитали не ту фразу — ищем по всей таблице.
            found = align_stream(sub, st["units"], live["expected"])
            # Непонятная речь при записи с суфлёром — не дубль, а отклик «Не понял».
            spans = [sp for sp in self._tts_spans(sub, found) if sp[2]["unit"] is not None]
            advanced = bool(ids and any(f["unit"] in ids for f in found))
            if ids and not spans and self._tts_prompt_partial(sub, ids):
                return "partial"
        if not spans:
            return "none"
        # Индексы — в общий поток, чтобы края резались по соседним словам (и командам).
        spans = [(i0 + i, i0 + j, info) for i, j, info in spans]
        first_n = max([t.get("chunk", 0) for t in st["takes"]] + [0]) + 1
        chunks_dir = os.path.join(st["work_dir"], TTS_CHUNKS_DIR)
        new = self._tts_cut_spans(seg, a_ms, stream, spans, rec.path, chunks_dir, first_n, push=False)
        units_found = [t["unit"] for t in new if t.get("unit") is not None]
        if units_found:
            live["expected"] = max(units_found) + 1
        cur = st["takes"][st["index"]] if st["takes"] and st["index"] < len(st["takes"]) else None
        first_idx = len(st["takes"])
        st["takes"].extend(new)
        live.setdefault("history", []).append({"takes": [t["file"] for t in new], "pos": pos})
        if cur is None or cur.get("approved") or cur.get("rejected") or cur.get("unit") is None:
            st["index"] = self._tts_next(first_idx - 1)
        if advanced:
            self._tts_prompt_fix(pos + 1)
        live["added"] += len(new)
        self._tts_save()
        self._tts_push({"stage": "live", "state": self.tts_state(), "added": len(new),
                        "prompt": self.tts_prompt_info(), "advanced": advanced})
        return "captured"

    # ---------------- клавиши во время записи ----------------
    # Space — пауза / продолжить, Backspace — заново, P — прослушать последнее.

    def tts_live_key(self, action):
        live = getattr(self, '_tts_live', None)
        rec = getattr(self, '_tts_rec', None)
        if not live or not rec:
            return {"error": "Запись не идёт."}
        with self._tts_live_lock:              # дождаться, если сейчас идёт распознавание
            msg = None
            if action == "pause":
                live["paused"] = not live.get("paused")
                live["done_ms"] = live["from_ms"] = rec.ana_ms   # недосказанное — не в счёт
                live["hearing"] = live["waiting"] = False
                msg = "Пауза — ничего не фиксирую. Space — продолжить" if live["paused"] else "Продолжаем запись"
            elif action == "redo":
                if live.get("waiting") or live.get("hearing"):
                    # Фраза ещё не зафиксирована — просто начать её сначала.
                    live["done_ms"] = live["from_ms"] = rec.ana_ms
                    live["hearing"] = live["waiting"] = False
                    live["restarts"] += 1
                    msg = "Заново — читайте фразу с начала"
                else:
                    msg = self._tts_live_undo()
            elif action == "commit":
                # Диктор закончил — не ждём паузы (вокруг может долго шуметь).
                if live.get("paused"):
                    return {"error": "Сейчас пауза — Space, чтобы продолжить."}
                live["force_cut"] = rec.ana_ms
                live["busy"] = True
                msg = None
            elif action == "play":
                msg = self._tts_live_play(rec)
            else:
                return {"error": "Неизвестное действие."}
            return {"action": action, "message": msg, "paused": bool(live.get("paused")),
                    "state": self.tts_state(), "prompt": self.tts_prompt_info()}

    def _tts_live_undo(self):
        """«Заново»: последний зафиксированный дубль — прочь (и из сохранённых),
        суфлёр — обратно на эту фразу."""
        st = self._tts()
        live = self._tts_live
        hist = live.get("history") or []
        if not hist:
            return "Нечего отменять — ещё ничего не записано"
        last = hist.pop()
        files = set(last["takes"])
        gone = [t for t in st["takes"] if t["file"] in files]
        for t in gone:
            if t.get("approved") and t.get("unit") is not None:
                target = self._tts_target(st["units"][t["unit"]])
                if os.path.exists(target):
                    self._tts_trash(target)
            try:
                os.remove(os.path.join(st["work_dir"], t["file"]))
            except OSError:
                pass
        cur = st["takes"][st["index"]]["file"] if st["takes"] and st["index"] < len(st["takes"]) else None
        st["takes"] = [t for t in st["takes"] if t["file"] not in files]
        idx = next((k for k, t in enumerate(st["takes"]) if t["file"] == cur), None)
        st["index"] = idx if idx is not None else max(0, len(st["takes"]) - 1)
        st["prompt_pos"] = last["pos"]
        live["restarts"] += 1
        names = ', '.join(st["units"][t["unit"]]["name"] for t in gone if t.get("unit") is not None) or 'дубль'
        self._tts_save()
        return f"Заново — удалил {names}, читайте эту фразу ещё раз"

    def _tts_live_play(self, rec):
        """«Играй»: только что записанное (фраза с переменными — все кусочки
        подряд). Пока играет — микрофон не фиксирует, чтобы звук из колонок
        не стал новым дублем."""
        st = self._tts()
        live = self._tts_live
        hist = live.get("history") or []
        if not hist:
            return "Ещё ничего не записано"
        files = [os.path.join(st["work_dir"], f) for f in hist[-1]["takes"]]
        files = [f for f in files if os.path.exists(f)]
        if not files:
            return "Файл пропал с диска"
        out = None
        for f in files:
            p = AudioSegment.from_file(self._tts_preview(f))
            out = p if out is None else out + AudioSegment.silent(150, frame_rate=p.frame_rate) + p
        import tempfile
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_tts_last_{os.getpid()}.wav")
        out.export(tmp, format="wav")
        self._tts_mark_listened()
        self.player.play(tmp)
        live["mute_until"] = rec.ana_ms + len(out) + 400
        return None

    @staticmethod
    def _tts_spans_with_rest(stream, spans):
        used = set()
        for i, j, _ in spans:
            used.update(range(i, j))
        x, out = 0, list(spans)
        while x < len(stream):
            if x in used:
                x += 1
                continue
            y = x
            while y < len(stream) and y not in used:
                y += 1
            if y - x >= 4:
                out.append((x, y, {"unit": None, "score": 0.0, "status": "none"}))
            x = y
        return sorted(out, key=lambda sp: sp[0])
