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
from core.tts_flow import FIND_SCORE, LEAD_S, TTS_CHUNKS_DIR, align_stream, end_word_ok, var_label
from utils.wav_io import wav_concat

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
# Запись «как голосовое»: держите Space — пишу, отпустили — распознаю.
PTT_PREROLL_MS = 250       # захватить чуть раньше нажатия (первый слог)
PTT_POSTROLL_MS = 350      # и чуть позже отпускания (хвост последнего слова)
PARTIAL_MIN_WORDS = 2      # верное начало длиннее — запоминаем и ждём продолжения
WORD_EQ = 0.66             # слово распознано «как в тексте»
LIVE_WAIT_MAX_MS = 45000   # недочитанную фразу ждём не дольше
PROMPT_PREFIX_SCORE = 0.6  # сказанное похоже на начало фразы — ждём продолжения


def tok_norms(text):
    """Слова фразы как на экране (по пробелам) и их нормальная форма для
    сравнения ('' — знак препинания, «—» и т.п.)."""
    toks = str(text or '').split()
    return toks, [_lat_to_cyr(_norm(t)) for t in toks]


def _word_eq(a, b):
    return bool(a) and bool(b) and (a == b or _ratio(a, b) >= WORD_EQ)


def _match_at(heard, h, word):
    """Слово фразы совпадает с услышанным, начиная с heard[h]? Составные
    («Push-уведомлением» → «пуш уведомлением») сверяем с 1–3 услышанными
    подряд. → сколько услышанных слов занято, или 0."""
    parts = len(word.split())
    for n in sorted({1, parts, parts + 1}):
        if h + n <= len(heard) and _word_eq(' '.join(heard[h:h + n]), word):
            return n
    return 0


def prefix_align(heard, tnorm, start=0, first_look=4, look=3):
    """Сколько слов фразы, начиная с start, прочитано подряд верно.
    heard — услышанные слова (нормальная форма), tnorm — слова фразы.
    → (k, pairs): k — индекс слова фразы, на котором чтение сбилось
    (len — дочитано до конца), pairs — [(слово фразы, первое и последнее
    слово услышанного)]. Короткое слово («в», «и»), которое распознавание
    проглотило, пропускаем."""
    pairs, h, t = [], 0, start
    while t < len(tnorm):
        if not tnorm[t]:
            t += 1
            continue
        window = first_look if not pairs else look
        found = None
        for d in range(window):
            n = _match_at(heard, h + d, tnorm[t])
            if n:
                found = (h + d, n)
                break
        if found is None and len(tnorm[t]) <= 2:
            nxt = next((x for x in range(t + 1, len(tnorm)) if tnorm[x]), None)
            if nxt is not None and any(_match_at(heard, h + d, tnorm[nxt]) for d in range(window)):
                t += 1
                continue
        if found is None:
            break
        pairs.append((t, found[0], found[0] + found[1] - 1))
        h, t = found[0] + found[1], t + 1
    return t, pairs


def continue_align(heard, tnorm, k, back=12):
    """Продолжение после сбоя: с какого слова фразы s (≤ k) диктор начал на
    этот раз — можно чуть раньше места сбоя. → (s, k_new, pairs) или None."""
    best = None
    cands = list(range(min(k, len(tnorm) - 1), max(-1, k - back - 1), -1)) + [0]
    for s in dict.fromkeys(cands):
        if s < 0 or not tnorm[s]:
            continue
        kk, pairs = prefix_align(heard, tnorm, s, first_look=3)
        if not pairs or pairs[0][0] != s:
            continue
        # Дальше всех дочитал; при равенстве — где он реально начал (раньше в
        # услышанном), потом — ближе к месту сбоя.
        key = (kk, -pairs[0][1], -abs(k - s))
        if best is None or key > best[0]:
            best = (key, s, kk, pairs)
    return best[1:] if best else None


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
        # Запас буфера побольше: пока модель занимает процессор, звук не теряется.
        self.stream = sd.InputStream(samplerate=self.rate, channels=1, dtype='int32',
                                     device=device, callback=self._callback, blocksize=0, latency='high')

    def _write_header(self, data_size):
        block, bits = 3, 24
        fmt = struct.pack('<HHIIHH', 1, 1, self.rate, self.rate * block, block, bits)
        self._f.seek(0)
        self._f.write(b'RIFF' + struct.pack('<I', min(0xFFFFFFFF, 36 + data_size)) + b'WAVE'
                      + b'fmt ' + struct.pack('<I', 16) + fmt + b'data' + struct.pack('<I', min(0xFFFFFFFF, data_size)))
        self._f.seek(0, 2)

    overflows = 0

    def _callback(self, indata, frames, t, status):
        if status and getattr(status, 'input_overflow', False):
            self.overflows += 1                  # компьютер не успел — кусок звука потерян
        block = indata[:, 0].copy()
        self.q.put(block)
        if self.mon is not None:
            self._mon_feed(block)

    # ----- прослушка: голос диктора сразу во вторые наушники -----
    mon = None
    MON_MAX_S = 0.25     # копится больше — выбрасываем старое: задержка не растёт
    MON_PRIME_S = 0.05   # после «опустело» — сначала подкопить, чтобы не трещало

    def set_monitor(self, device, volume=1.0):
        """Выводить микрофон в реальном времени на device (None — выключить).
        Возвращает название устройства вывода."""
        self._mon_close()
        if device is None:
            return None
        info = self.sd.query_devices(device, 'output')
        rate = int(info['default_samplerate']) or 48000
        ch = 2 if info['max_output_channels'] >= 2 else 1
        self.mon_rate, self.mon_gain = rate, float(volume)
        self.mon_buf = np.zeros(0, np.float32)
        self.mon_prime = True
        self.mon_lock = threading.Lock()
        stream = self.sd.OutputStream(samplerate=rate, channels=ch, dtype='float32', device=device,
                                      callback=self._mon_out, blocksize=0, latency=0.08)
        stream.start()
        self.mon = stream
        return info['name']

    def set_monitor_volume(self, volume):
        self.mon_gain = float(volume)

    def _mon_feed(self, block):
        x = block.astype(np.float32) / 2147483648.0
        if self.mon_rate != self.rate and len(x):
            n = int(round(len(x) * self.mon_rate / self.rate))
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32) if n else x[:0]
        with self.mon_lock:
            buf = np.concatenate([self.mon_buf, x])
            cap = int(self.MON_MAX_S * self.mon_rate)
            if len(buf) > cap:
                buf = buf[-int(self.MON_PRIME_S * 2 * self.mon_rate):]
            self.mon_buf = buf

    def _mon_out(self, outdata, frames, t, status):
        with self.mon_lock:
            if self.mon_prime and len(self.mon_buf) < self.MON_PRIME_S * self.mon_rate:
                outdata[:] = 0
                return
            self.mon_prime = False
            n = min(frames, len(self.mon_buf))
            out = self.mon_buf[:n]
            self.mon_buf = self.mon_buf[n:]
            if n < frames:
                self.mon_prime = True            # опустело — подкопить заново
        outdata[:n] = np.clip(out * self.mon_gain, -1.0, 1.0)[:, None]
        outdata[n:] = 0

    def _mon_close(self):
        mon, self.mon = self.mon, None
        if mon is not None:
            try:
                mon.stop()
                mon.close()
            except Exception:
                pass

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
        self._mon_close()
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
            out_default = sd.default.device[1]
            outs = [{"id": i, "name": d['name'], "default": i == out_default}
                    for i, d in enumerate(sd.query_devices()) if d['max_output_channels'] > 0]
            if host:
                outs = [d for d in outs if d["id"] in host] or outs
        except Exception as e:
            return {"error": f"Не удалось получить список микрофонов: {e}"}
        if not devs:
            return {"error": "Не найден ни один микрофон."}
        return {"devices": devs, "outputs": outs}

    def tts_monitor(self, device=None, volume=1.0):
        """Наушники пользователя (device — устройство вывода, None — по умолчанию
        Windows): туда идёт голос диктора в реальном времени (пока идёт запись)
        и всё прослушивание дублей. Запоминается до следующей записи."""
        device = None if device in (None, '', -1) else int(device)
        self._tts_mon = {"device": device, "volume": float(volume or 1.0)}
        # Прослушивание дублей — в те же наушники, а не в гарнитуру диктора.
        player = getattr(self, 'player', None)
        if player is not None and hasattr(player, 'set_device') and getattr(player, 'device', None) != device:
            player.set_device(device)
        rec = getattr(self, '_tts_rec', None)
        if not rec:
            return {"on": device is not None, "name": None, "pending": True}
        try:
            if device is not None and rec.mon is not None and getattr(rec, '_mon_device', None) == device:
                rec.set_monitor_volume(volume)
                return {"on": True, "name": rec._mon_name}
            name = rec.set_monitor(device, volume)
            rec._mon_device, rec._mon_name = device, name
        except Exception as e:
            return {"error": f"Не удалось вывести звук в наушники: {e}"}
        return {"on": device is not None, "name": name}

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
        model, err = self._auto_check_model(st["lang"])
        if err:
            if not isinstance(err, str):
                return {"error": "need_model_kz" if st["lang"] == 'kz' else "need_model"}
            return {"error": err}
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
        # Две блокировки: _tts_live_lock — правка дублей (короткая), _tts_q_lock —
        # нажатия Space/Backspace/Enter: они не ждут распознавания.
        self._tts_live_lock = threading.RLock()
        self._tts_q_lock = threading.Lock()
        self._tts_live = {"model": model, "done_ms": 0, "from_ms": 0, "busy": False, "added": 0,
                          "restarts": 0, "expected": self._tts_live_expected(), "queue": [], "hold": None,
                          "gen": 0}
        mon = getattr(self, '_tts_mon', None)
        mon_name = mon_err = None
        if mon and mon.get("device") is not None:
            try:
                mon_name = rec.set_monitor(mon["device"], mon.get("volume", 1.0))
                rec._mon_device, rec._mon_name = mon["device"], mon_name
            except Exception as e:
                mon_err = f"Прослушка не включилась: {e}"
        self._tts_prompt_fix()
        self._tts_save()
        threading.Thread(target=self._tts_live_loop, daemon=True).start()
        return {"status": "ok", "device": rec.device_name, "rate": rec.rate,
                "monitor": mon_name, "monitor_error": mon_err}

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
        live = self._tts_live
        with self._tts_q_lock:
            if live.get("hold") is not None:             # отпускание так и не пришло
                live["queue"].append((live["hold"], rec.ana_ms))
                live["hold"] = None
        rec.stop()
        live["stopping"] = True
        return {"status": "stopping"}

    def tts_rec_status(self):
        rec = getattr(self, '_tts_rec', None)
        live = getattr(self, '_tts_live', None) or {}
        if not rec:
            return {"recording": False}
        return {"recording": rec.running, "seconds": rec.frames / rec.rate, "level_db": round(rec.level_db, 1),
                "device": rec.device_name, "busy": live.get("busy", False),
                "pending_s": round(max(0, rec.ana_ms - live.get("done_ms", 0)) / 1000, 1),
                # Сколько записей этой сессии есть сейчас (удалённые «Заново» — не в счёт).
                "added": sum(len(h["takes"]) for h in live.get("history", [])), "restarts": live.get("restarts", 0),
                "waiting": live.get("waiting", False), "paused": bool(live.get("paused")),
                "hearing": bool(live.get("hearing")),
                "holding": live.get("hold") is not None,
                "hold_s": round(max(0, rec.ana_ms - live["hold"]) / 1000, 1) if live.get("hold") is not None else 0,
                "overflows": rec.overflows,
                "error": rec.error, "prompt": self.tts_prompt_info()}

    # ---------------- разбор в паузах ----------------

    def _tts_live_loop(self):
        """Разбираем только отрезки, записанные с зажатой клавишей (как
        голосовое сообщение): пока диктор читает, ничего не распознаётся
        и текст на экране не дёргается."""
        rec, live = self._tts_rec, self._tts_live
        try:
            while True:
                stopping = live.get("stopping") or not rec.running
                job = None
                with self._tts_q_lock:
                    q = live["queue"]
                    if q and (rec.ana_ms >= q[0][1] or stopping):
                        job = q.pop(0)
                        live["busy"] = True
                        gen = live["gen"]
                if job:
                    self._tts_push({"stage": "live_busy", "busy": True})
                    # Распознавание — без блокировок: Backspace / Enter не ждут его.
                    try:
                        self._tts_ptt_segment(rec, job[0], min(job[1], rec.ana_ms), gen)
                    except Exception as e:
                        self._tts_push({"stage": "live_error", "error": f"Не удалось разобрать запись: {e}"})
                    with self._tts_q_lock:
                        live["busy"] = bool(live["queue"])
                    self._tts_push({"stage": "live_busy", "busy": live["busy"]})
                    continue
                if stopping and not live["queue"]:
                    break
                time.sleep(0.05)
        finally:
            self._tts_rec = None
            self._tts_save()
            self._tts_push({"stage": "live_done", "state": self.tts_state(), "error": rec.error})

    # ---------------- разбор отрезка (держали Space) ----------------

    def _tts_ana_quiet(self, rec, lo_s, hi_s):
        """Самое тихое место (мс записи) в окне — там и режем."""
        lo_s, hi_s = self._tts_edge_window(lo_s, hi_s)
        L = max(0, int(lo_s * 1000) - 20)
        seg = rec.ana_segment(L, int(hi_s * 1000) + 20)
        return L + self._tts_quiet_point(seg, lo_s - L / 1000.0, hi_s - L / 1000.0)

    def _tts_word_span(self, rec, stream, h0, h1, end_s):
        """Кусок записи (мс) от слова h0 до слова h1 включительно, края — в тишине."""
        first_s, last_e = stream[h0][1], stream[h1][2]
        prev_e = stream[h0 - 1][2] if h0 > 0 else first_s - LEAD_S
        next_s = stream[h1 + 1][1] if h1 + 1 < len(stream) else end_s
        lo = self._tts_ana_quiet(rec, max(prev_e, first_s - LEAD_S), first_s + 0.03)
        hi = self._tts_ana_quiet(rec, last_e - 0.03, min(next_s, last_e + LEAD_S))
        if hi - lo < 150:
            lo, hi = int(first_s * 1000) - 50, int(last_e * 1000) + 80
        return max(0, lo), hi

    def _tts_hint_text(self):
        """Казахский: подсказываем модели текст фразы на суфлёре (и следующей) —
        так она пишет казахские слова правильно, а не «по-русски». Для
        русского не нужно — распознаётся и так."""
        st = self._tts()
        if st.get("lang") != 'kz':
            return None
        items = self._tts_prompt_items()
        if not items:
            return None
        pos = max(0, min(st.get("prompt_pos", 0), len(items) - 1))
        ids = items[pos] + (items[pos + 1] if pos + 1 < len(items) else [])
        text = ' '.join(st["units"][i]["text"] for i in ids)
        return text[:400] or None

    def _tts_ptt_segment(self, rec, a_ms, b_ms, gen=None):
        st = self._tts()
        live = self._tts_live
        if gen is None:
            gen = live.get("gen", 0)
        if b_ms - a_ms < 200:
            return
        last = live["last_seg"] = {"a": a_ms, "b": b_ms, "gen": gen, "outcome": "pending"}
        seg = rec.ana_segment(a_ms, b_ms)
        samples = np.frombuffer(seg.raw_data, '<i2').astype(np.float32) / 32768.0
        words = self._tts_transcribe_pack(live["model"], [{"index": 0, "audio": samples, "ms": len(seg)}],
                                          'kk' if st["lang"] == 'kz' else 'ru', live=True,
                                          hotwords=self._tts_hint_text())[0]
        with self._tts_live_lock:
            if live.get("gen", 0) != gen:
                return                     # пока распознавали — отменили (Backspace) или зафиксировали (Enter)
            last["outcome"] = self._tts_ptt_apply(rec, a_ms, b_ms, seg, words, gen) or "miss"

    def _tts_ptt_apply(self, rec, a_ms, b_ms, seg, words, gen):
        """Разобранный отрезок → дубль / начало длинной фразы / «не понял».
        Возвращает 'take' | 'partial' | 'miss'."""
        st = self._tts()
        live = self._tts_live
        text = ''.join(w[0] for w in words).strip()
        if not words or self._asr_is_noise(text):
            self._tts_push({"stage": "live_miss", "heard": "", "paused": False})
            return "miss"
        off = a_ms / 1000.0
        stream = [(w, off + s_, off + e, 0) for w, s_, e in words]
        items = self._tts_prompt_items()
        pos = st.get("prompt_pos", 0)
        ids = items[pos] if 0 <= pos < len(items) else None

        # Фраза с переменными (несколько кусочков) — как раньше, целиком.
        if not ids or len(ids) > 1:
            if self._tts_live_words(rec, seg, a_ms, stream, 0, len(stream), final=True) == "none":
                self._tts_push({"stage": "live_miss", "heard": text, "paused": False})
                return "miss"
            return "take"

        uid = ids[0]
        toks, tn = tok_norms(st["units"][uid]["text"])
        heard = [_lat_to_cyr(_norm(w[0])) for w in stream]
        part = live.get("partial")
        if part and (part["unit"] != uid or part["raw"] != rec.path or part.get("gen", gen) != gen):
            part = live["partial"] = None
        s0 = 0
        if part:
            r = continue_align(heard, tn, part["k"])
            if r and r[0] > 0:
                s0, kk, pairs = r
            else:
                part = None                                       # начал фразу с начала
        if not part:
            kk, pairs = prefix_align(heard, tn, 0)
        complete = all(not x for x in tn[kk:])
        if not pairs or (not complete and not part and len(pairs) < PARTIAL_MIN_WORDS):
            # Не начало текущей фразы — может, прочитали другую.
            if self._tts_live_words(rec, seg, a_ms, stream, 0, len(stream), final=True) == "none":
                self._tts_push({"stage": "live_miss", "heard": text, "paused": False})
                return "miss"
            return "take"

        this = self._tts_word_span(rec, stream, pairs[0][1], pairs[-1][2], b_ms / 1000.0)
        whole = pairs[0][1] == 0 and pairs[-1][2] == len(stream) - 1
        if whole and not self._tts_times_sane(rec, stream, a_ms, b_ms):
            # Время слов у модели «плывёт» (бывает у дообученных) — режем по голосу.
            this = self._tts_voice_bounds(rec, a_ms, b_ms)
        times = {t: (stream[h0][1], stream[h1][2]) for t, h0, h1 in pairs}
        heard_all = ((part.get("heard", '') + ' … ') if part else '') + text
        score_of = lambda n: round(n / max(1, sum(1 for x in tn if x)), 3)

        if not part:
            if complete:
                live["partial"] = None
                self._tts_live_make_take(rec, uid, [{"raw": rec.path, "a": this[0], "b": this[1], "cuts": [], "pos": 0}],
                                         heard_all, score_of(len(times)), pos)
                return "take"
            frags = []
        else:
            frags = [dict(f) for f in part["frags"]]
            prev = frags[-1]
            if s0 < part["k"]:
                # Начал раньше места сбоя — первый кусок звучит только до слова s0.
                pt = {int(k): v for k, v in prev["times"].items()}
                before = max((k for k in pt if k < s0), default=None)
                if before is not None:
                    e = pt[before][1]
                    prev["cut"] = self._tts_ana_quiet(rec, e - 0.03, e + LEAD_S)
                prev["times"] = {k: v for k, v in pt.items() if k < s0}
        # Фрагмент целиком (со сбоем на конце) — на дорожку; «cut» — где кончается верное.
        full = self._tts_word_span(rec, stream, pairs[0][1], len(stream) - 1, b_ms / 1000.0)
        frags.append({"a": this[0], "b": this[1] if complete else max(this[1], full[1]), "cut": this[1], "times": times})

        if complete:
            # Все фрагменты — отдельными клипами, уже выставленными по местам сбоя:
            # следующий начинается там, где кончается верное в предыдущем.
            clips, pos_ = [], 0
            for f in frags:
                clips.append({"raw": rec.path, "a": int(f["a"]), "b": int(f["b"]), "cuts": [], "pos": int(pos_)})
                pos_ += max(0, f["cut"] - f["a"])
            live["partial"] = None
            n_ok = sum(len(f["times"]) for f in frags)
            self._tts_live_make_take(rec, uid, clips, heard_all, score_of(n_ok), pos)
            return "take"
        live["partial"] = {"unit": uid, "k": kk, "raw": rec.path, "frags": frags, "heard": heard_all,
                           "gen": gen, "seg": [a_ms, b_ms]}
        word = toks[kk] if kk < len(toks) else ''
        self._tts_push({"stage": "live_partial", "prompt": self.tts_prompt_info(),
                        "message": f"Начало записано — продолжите с «{word}»"})
        return "partial"

    def _tts_live_make_take(self, rec, uid, clips, heard, score, pos, status=None):
        """Дубль из клипов исходной записи (байт в байт). Фраза из кусочков —
        несколько клипов на дорожке «Сборки»: их можно двигать и подрезать."""
        st = self._tts()
        live = self._tts_live
        n = max([t.get("chunk", 0) for t in st["takes"]] + [0]) + 1
        name = f"{n:04d}.wav"
        a0 = min(c["a"] for c in clips)
        b1 = max(c["b"] for c in clips)
        take = {"file": os.path.join(TTS_CHUNKS_DIR, name), "start_ms": a0, "ms": 0,
                "orig": [a0, b1], "raw": rec.path, "heard": heard, "listened": False, "chunk": n,
                "unit": uid, "score": score, "status": status or ("ok" if score >= 0.85 else "doubt")}
        if len(clips) > 1:
            take["clips"] = clips
            take["clips_orig"] = [dict(c) for c in clips]
            take["stitched"] = True
        else:
            take["orig"] = [clips[0]["a"], clips[0]["b"]]
        self._tts_render_clips(take, clips)
        cur = st["takes"][st["index"]] if st["takes"] and st["index"] < len(st["takes"]) else None
        st["takes"].append(take)
        live.setdefault("history", []).append({"takes": [take["file"]], "pos": pos})
        if uid is not None:
            live["expected"] = uid + 1
        if cur is None or cur.get("approved") or cur.get("rejected") or cur.get("unit") is None:
            st["index"] = len(st["takes"]) - 1
        self._tts_prompt_fix(pos + 1)
        live["added"] += 1
        self._tts_save()
        self._tts_push({"stage": "live", "state": self.tts_state(), "added": 1,
                        "prompt": self.tts_prompt_info(), "advanced": True})

    def tts_ptt(self, down):
        """Space / кнопка зажата — пишем; отпустили — отрезок в разбор."""
        live = getattr(self, '_tts_live', None)
        rec = getattr(self, '_tts_rec', None)
        if not live or not rec:
            return {"error": "Запись не идёт."}
        now = rec.ana_ms                      # время нажатия — сразу, ничего не ждём
        with self._tts_q_lock:
            if down:
                if live.get("hold") is None:
                    live["hold"] = max(live.get("mute_until", 0), now - PTT_PREROLL_MS, 0)
                return {"holding": True}
            start = live.get("hold")
            live["hold"] = None
            if start is None:
                return {"holding": False}
            live["queue"].append((start, now + PTT_POSTROLL_MS))
            live["busy"] = True
            return {"holding": False, "queued": True}

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
        live = getattr(self, '_tts_live', None) or {}
        part = live.get("partial")
        resume = None
        if part and items[pos] == [part["unit"]]:
            toks, _ = tok_norms(units[part["unit"]]["text"])
            resume = {"unit": part["unit"], "k": part["k"], "word": toks[part["k"]] if part["k"] < len(toks) else ''}
        return {"pos": pos, "total": len(items), "left": left, "done": left == 0, "resume": resume,
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
            live.pop("partial", None)
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
        """Backspace — заново, P — прослушать последнее."""
        live = getattr(self, '_tts_live', None)
        rec = getattr(self, '_tts_rec', None)
        if not live or not rec:
            return {"error": "Запись не идёт."}
        if action == "redo":
            # Держат Space или ещё распознаётся — отменяем сразу, не дожидаясь.
            with self._tts_q_lock:
                fast = live.get("hold") is not None or bool(live["queue"]) or live.get("busy")
                if fast:
                    live["hold"] = None
                    live["queue"].clear()
                    live["gen"] = live.get("gen", 0) + 1
                    live["busy"] = False
            if fast:
                live.pop("partial", None)
                live["restarts"] += 1
                self._tts_push({"stage": "live_busy", "busy": False})
                return {"action": "redo", "message": "Отменил — читайте фразу сначала", "paused": False,
                        "state": self.tts_state(), "prompt": self.tts_prompt_info(), "cancelled": True}
        if action == "commit":
            return self._tts_live_commit(rec)
        with self._tts_live_lock:
            if action == "redo":
                if live.pop("partial", None):
                    live["restarts"] += 1
                    msg = "Заново — читайте фразу с начала"
                else:
                    msg = self._tts_live_undo()
            elif action == "play":
                msg = self._tts_live_play(rec)
            else:
                return {"error": "Неизвестное действие."}
            return {"action": action, "message": msg, "paused": False,
                    "state": self.tts_state(), "prompt": self.tts_prompt_info()}

    def _tts_live_commit(self, rec):
        """Enter — «Зафиксировать»: последний записанный кусок становится
        дублем текущей фразы суфлёра, даже если распознавание его не поняло
        (или ещё не досчитало). Распознавание — помощник, а не шлагбаум."""
        live = self._tts_live
        now = rec.ana_ms
        with self._tts_q_lock:
            if live.get("hold") is not None:            # нажали, не отпустив Space
                seg = (live["hold"], now + PTT_POSTROLL_MS)
                live["hold"] = None
            elif live["queue"]:
                seg = live["queue"][-1]
            else:
                ls = live.get("last_seg")
                seg = (ls["a"], ls["b"]) if ls and ls.get("outcome") != "take" else None
            if seg:
                live["queue"].clear()
                live["gen"] = live.get("gen", 0) + 1     # результат распознавания — уже не нужен
                live["busy"] = False
        if not seg:
            part = live.get("partial")
            if not part:
                return {"error": "Нечего фиксировать — сначала запишите фразу (держите Space)"}
            seg = tuple(part["seg"])
        t_end = time.time() + 1.0
        while rec.ana_ms < seg[1] and rec.running and time.time() < t_end:
            time.sleep(0.02)
        a_ms, b_ms = seg[0], min(seg[1], rec.ana_ms)
        self._tts_push({"stage": "live_busy", "busy": False})
        with self._tts_live_lock:
            msg = self._tts_live_force(rec, a_ms, b_ms)
            ls = live.get("last_seg")
            if ls and ls["a"] == a_ms:
                ls["outcome"] = "take"
            else:
                live["last_seg"] = {"a": a_ms, "b": b_ms, "gen": live["gen"], "outcome": "take"}
            return {"action": "commit", "message": msg, "paused": False,
                    "state": self.tts_state(), "prompt": self.tts_prompt_info()}

    def _tts_times_sane(self, rec, stream, a_ms, b_ms):
        """Похоже ли время слов на правду: идут по порядку, длительности
        разумные и края речи совпадают с тем, где в записи громко."""
        prev = -1.0
        for w, s_, e, *_ in stream:
            if e <= s_ or s_ < prev - 0.05 or e - s_ > 2.5:
                return False
            prev = s_
        lo, hi = self._tts_voice_bounds(rec, a_ms, b_ms)
        ws, we = stream[0][1] * 1000, stream[-1][2] * 1000
        return abs(ws - lo) < 700 and abs(we - hi) < 700

    def _tts_voice_bounds(self, rec, a_ms, b_ms):
        """Где в отрезке голос: обрезаем тишину по краям (с запасом)."""
        seg = rec.ana_segment(a_ms, b_ms)
        db = self._tts_live_levels(seg)
        if not len(db):
            return a_ms, b_ms
        thr = max(-50.0, float(db.max()) - 35.0)
        on = np.nonzero(db > thr)[0]
        if not len(on):
            return a_ms, b_ms
        lo = a_ms + max(0, on[0] * LIVE_FRAME_MS - 120)
        hi = min(b_ms, a_ms + (on[-1] + 1) * LIVE_FRAME_MS + 160)
        return int(lo), int(hi)

    def _tts_live_force(self, rec, a_ms, b_ms):
        st = self._tts()
        live = self._tts_live
        items = self._tts_prompt_items()
        pos = st.get("prompt_pos", 0)
        ids = items[pos] if 0 <= pos < len(items) else None
        lo, hi = self._tts_voice_bounds(rec, a_ms, b_ms)
        part = live.pop("partial", None)
        if part and (not ids or ids != [part["unit"]] or part["raw"] != rec.path):
            part = None
        if part:
            # Длинная фраза: верное начало уже есть — к нему добавляем этот кусок.
            frags = [dict(f) for f in part["frags"]]
            if list(part.get("seg") or []) == [a_ms, b_ms]:
                frags[-1]["cut"] = frags[-1]["b"]        # этот кусок уже последний фрагмент
            else:
                frags.append({"a": lo, "b": hi, "cut": hi})
            clips, p = [], 0
            for f in frags:
                clips.append({"raw": rec.path, "a": int(f["a"]), "b": int(f["b"]), "cuts": [], "pos": int(p)})
                p += max(0, f["cut"] - f["a"])
            heard = part.get("heard", '') + ' … (зафиксировано вручную)'
        else:
            clips = [{"raw": rec.path, "a": lo, "b": hi, "cuts": [], "pos": 0}]
            heard = '(зафиксировано вручную)'
        if ids and len(ids) == 1:
            self._tts_live_make_take(rec, ids[0], clips, heard, 1.0, pos, status="manual")
            return f"Зафиксировал: {st['units'][ids[0]]['name']}"
        # Фраза с переменными — кусочки без распознавания не разрезать: дубль
        # целиком, без привязки; привязать (F) и подрезать — в «Сборке».
        self._tts_live_make_take(rec, None, clips, heard, 0.0, pos, status="none")
        return "Зафиксировал целиком — привяжите (F) и подрежьте в «Сборке»"

    def _tts_live_undo(self):
        """«Заново»: последний зафиксированный дубль — прочь (и из сохранённых),
        суфлёр — обратно на эту фразу."""
        st = self._tts()
        live = self._tts_live
        live.pop("partial", None)
        hist = live.get("history") or []
        if not hist:
            return "Нечего отменять — ещё ничего не записано"
        last = hist.pop()
        files = set(last["takes"])
        ls = live.get("last_seg")
        if ls and ls.get("outcome") == "take":
            ls["outcome"] = "undone"           # можно зафиксировать вручную (Enter)
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
