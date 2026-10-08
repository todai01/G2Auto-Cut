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

from core.tts_flow import TTS_CHUNKS_DIR, align_stream

LIVE_RATE = 16000          # копия для распознавания
LIVE_SILENCE_MS = 700      # пауза, после которой сказанное считается готовым
LIVE_MIN_REGION_MS = 1200  # меньше — ещё рано разбирать
LIVE_FORCE_MS = 40000      # без пауз дольше — режем в самом тихом месте
LIVE_FRAME_MS = 20
LIVE_NOISE_ABOVE_DB = 10   # речь — громче фона хотя бы на столько
RECORDS_DIR = 'Записи'


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
        self._tts_live = {"model": model, "done_ms": 0, "busy": False, "added": 0,
                          "expected": self._tts_live_expected()}
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
                "added": live.get("added", 0), "error": rec.error}

    # ---------------- разбор в паузах ----------------

    def _tts_live_loop(self):
        rec, live = self._tts_rec, self._tts_live
        try:
            while True:
                stopping = live.get("stopping") or not rec.running
                total = rec.ana_ms
                cut = total if stopping else self._tts_live_cut(rec, live["done_ms"], total)
                if cut and cut - live["done_ms"] >= (1 if stopping else LIVE_MIN_REGION_MS):
                    live["busy"] = True
                    try:
                        self._tts_live_region(rec, live["done_ms"], cut)
                    except Exception as e:
                        self._tts_push({"stage": "live_error", "error": f"Не удалось разобрать кусок записи: {e}"})
                    live["done_ms"] = cut
                    live["busy"] = False
                if stopping:
                    break
                time.sleep(0.4)
        finally:
            self._tts_rec = None
            self._tts_save()
            self._tts_push({"stage": "live_done", "state": self.tts_state(), "error": rec.error})

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
        quiet = lv < floor + LIVE_NOISE_ABOVE_DB
        if not (~quiet).any():
            # Одна тишина — разбирать нечего, но и копить незачем.
            return total_ms - 300 if total_ms - done_ms > 3000 else None
        need = LIVE_SILENCE_MS // LIVE_FRAME_MS
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

    def _tts_live_region(self, rec, a_ms, b_ms):
        st = self._tts()
        live = self._tts_live
        seg = rec.ana_segment(a_ms, b_ms)
        lv = self._tts_live_levels(seg)
        if not len(lv):
            return
        samples = np.frombuffer(seg.raw_data, '<i2').astype(np.float32) / 32768.0
        words = self._tts_transcribe_pack(live["model"], [{"index": 0, "audio": samples, "ms": len(seg)}],
                                          'kk' if st["lang"] == 'kz' else 'ru')[0]
        text = ''.join(w[0] for w in words).strip()
        if not words or self._asr_is_noise(text):
            return
        off = a_ms / 1000.0
        stream = [(w, off + s, off + e, 0) for w, s, e in words]
        found = align_stream(stream, st["units"], live["expected"])
        spans = self._tts_spans(stream, found)
        if not spans:
            return
        first_n = max([t.get("chunk", 0) for t in st["takes"]] + [0]) + 1
        chunks_dir = os.path.join(st["work_dir"], TTS_CHUNKS_DIR)
        new = self._tts_cut_spans(seg, a_ms, stream, spans, rec.path, chunks_dir, first_n, push=False)
        if found:
            live["expected"] = found[-1]["unit"] + 1
        cur = st["takes"][st["index"]] if st["takes"] and st["index"] < len(st["takes"]) else None
        st["takes"].extend(new)
        # Текущий дубль уже сдан (или его нет) — встаём на первый новый.
        if cur is None or cur.get("approved") or cur.get("rejected") or cur.get("unit") is None:
            st["index"] = self._tts_next(max(-1, st["index"] - 1) if cur is None else st["index"])
        live["added"] += len(new)
        self._tts_save()
        self._tts_push({"stage": "live", "state": self.tts_state(), "added": len(new)})
