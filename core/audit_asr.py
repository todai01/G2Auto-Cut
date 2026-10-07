"""Аудит по голосу: какие значения категории (марки и т.п.) реально
записаны, если файлы ещё не названы по значениям.

Два пути:
  • чанки уже нарезаны (0001.wav, фраза_0001.wav…) — берём папку;
  • ещё не нарезано — режем запись сами (те же автонастройки, что у
    обычной нарезки, подгоняем под число значений в таблице) и кладём
    чанки рядом с записью в «<имя>_Chunks».
Каждый чанк распознаётся локально (как автопроверка) и сверяется со всеми
значениями категории. Чего не услышали — недостающее; его можно выгрузить
таблицей в формате словаря (audit_export_missing)."""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import webview
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

from core.auto_check import (ASR_RATE, NEED_MODEL, NOISE_MAX_DBFS, NOISE_MIN_MS,
                             SPEECH_MIN_SCORE, score_candidates)

AUDIT_FOUND_SCORE = 0.80      # лучший вариант засчитываем как «записано»
AUDIT_FOUND_MARGIN = 0.05     # …если он опережает второй хотя бы на столько
AUDIT_SURE_SCORE = 0.92       # почти дословное совпадение — засчитываем всегда
                              # (в один чанк могли слипнуться две марки)
AUDIT_CUT_PAD_MS = 150
AUDIO_EXT = ('.wav', '.mp3', '.flac', '.ogg')


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', name)]


class AuditAsrMixin:

    def _audit_asr_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"auditAsrProgress({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    def _audit_asr_cut(self, path, target):
        """Режет запись на чанки (автонастройки под target кусков) и
        сохраняет их в «<имя>_Chunks» рядом с записью. [(имя, AudioSegment)]."""
        audio = AudioSegment.from_file(path)
        levels = self._frame_levels(audio)
        if not levels:
            raise ValueError("Запись пустая или слишком короткая.")
        _, _, _, thresh, pause, _ = self._suggest_cut_settings(levels, target)
        ranges = detect_nonsilent(audio, min_silence_len=int(pause), silence_thresh=int(thresh))
        stem = os.path.splitext(os.path.basename(path))[0]
        out_dir = os.path.join(os.path.dirname(path), f"{stem}_Chunks")
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            if f.startswith('фраза_') and f.lower().endswith('.wav'):
                try:
                    os.remove(os.path.join(out_dir, f))
                except OSError:
                    pass
        chunks = []
        for i, (a, b) in enumerate(ranges):
            if self._auto_check_stop:
                break
            piece = audio[max(0, a - AUDIT_CUT_PAD_MS):min(len(audio), b + AUDIT_CUT_PAD_MS)]
            name = f"фраза_{i + 1:04d}.wav"
            piece.export(os.path.join(out_dir, name), format="wav")
            chunks.append((name, piece))
            if i % 20 == 0:
                self._audit_asr_push({"stage": "cut", "done": i + 1, "total": len(ranges)})
        return out_dir, chunks

    @staticmethod
    def _audit_asr_samples(seg):
        import numpy as np
        seg = seg.set_channels(1).set_frame_rate(ASR_RATE).set_sample_width(2)
        return np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0, len(seg), seg.max_dBFS

    def audit_recognize(self, category, source, language='ru'):
        """source: 'folder' — папка с уже нарезанными чанками без названий,
        'cut' — сырая запись, которую сперва нарежем."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(category) or []
        if not values:
            return {"error": "Для этой категории в таблице-словаре нет ни одного значения."}

        if source == 'cut':
            picked = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN, file_types=('Audio Files (*.wav;*.mp3)', 'All files (*.*)'))
        else:
            picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        picked = picked if isinstance(picked, str) else picked[0]

        lock = getattr(self, '_auto_check_lock', None)
        if lock is None:
            lock = self._auto_check_lock = threading.Lock()
        if not lock.acquire(blocking=False):
            return {"error": "Распознавание уже идёт."}
        try:
            self._auto_check_stop = False
            self._audit_asr_push({"stage": "model", "done": 0, "total": 0})
            model, err = self._auto_check_model()
            if err is NEED_MODEL:
                return {"need_model": True}
            if err:
                return {"error": err}

            # 1) Чанки: нарезать запись или взять готовую папку.
            if source == 'cut':
                try:
                    scan_dir, chunks = self._audit_asr_cut(picked, len(values))
                except Exception as e:
                    return {"error": f"Не удалось нарезать запись: {e}"}
            else:
                scan_dir = picked
                names = sorted((f for f in os.listdir(picked)
                                if f.lower().endswith(AUDIO_EXT) and not f.lower().startswith(('start', 'end'))),
                               key=_natural_key)
                chunks = [(n, os.path.join(picked, n)) for n in names]
            if not chunks:
                return {"error": "Не нашёл ни одного чанка для распознавания."}

            # 2) Распознаём (как автопроверка: окнами, параллельно).
            transcripts = (getattr(self, 'var_transcripts', None) or {}).get(category, {})
            total = len(chunks)
            heard_by = {}
            state = {"done": 0}
            done_lock = threading.Lock()

            def finish(k, heard):
                with done_lock:
                    heard_by[k] = heard
                    state["done"] += 1
                    d = state["done"]
                if d % 5 == 0 or d == total:
                    self._audit_asr_push({"stage": "asr", "done": d, "total": total})

            items = []
            for k, (name, src) in enumerate(chunks):
                if self._auto_check_stop:
                    break
                try:
                    seg = AudioSegment.from_file(src) if isinstance(src, str) else src
                    samples, ms, peak = self._audit_asr_samples(seg)
                except Exception:
                    finish(k, '')
                    continue
                if ms < NOISE_MIN_MS or peak < NOISE_MAX_DBFS:
                    finish(k, '')
                else:
                    items.append({"index": k, "audio": samples, "ms": ms})

            def run(pack):
                if self._auto_check_stop:
                    return
                try:
                    heard_list = self._asr_transcribe_pack(model, pack, language)
                except Exception:
                    heard_list = [''] * len(pack)
                for it, heard in zip(pack, heard_list):
                    finish(it['index'], '' if self._asr_is_noise(heard) else heard)

            with ThreadPoolExecutor(max_workers=getattr(self, '_asr_workers', 1)) as ex:
                list(ex.map(run, self._asr_packs(items)))
            stopped = self._auto_check_stop

            # 3) Сверяем каждый чанк со всеми значениями категории.
            found = {}       # значение -> чанк, где услышали
            unknown = []     # речь есть, но ни на что уверенно не похожа
            for k, (name, _) in enumerate(chunks):
                heard = heard_by.get(k, '')
                if not heard:
                    continue
                scored = score_candidates(heard, values, transcripts)
                best, best_score = scored[0]
                second = scored[1][1] if len(scored) > 1 else 0.0
                hit = False
                if best_score >= AUDIT_FOUND_SCORE and best_score - second >= AUDIT_FOUND_MARGIN:
                    found.setdefault(best, name)
                    hit = True
                for v, sc in scored:
                    if sc < AUDIT_SURE_SCORE:
                        break
                    found.setdefault(v, name)
                    hit = True
                if not hit and best_score >= SPEECH_MIN_SCORE:
                    unknown.append({"filename": name, "heard": heard, "guess": best,
                                    "score": round(best_score, 2)})

            missing_list = [{"index": i + 1, "filename": "не услышано", "text": v}
                            for i, v in enumerate(values) if v not in found]
            self._audit_last = {"category": category, "missing": {m["text"] for m in missing_list}}
            template = getattr(self, 'var_template_path', None)
            return {
                "category": category,
                "category_label": self._category_label(category),
                "by_voice": True,
                "stopped": stopped,
                "scan_dir": scan_dir,
                "chunks_total": total,
                "can_export": bool(missing_list and template and os.path.exists(template)),
                "total_excel": len(values),
                "total_disk": len(found),
                "missing_count": len(missing_list),
                "duplicates_count": 0,
                "missing": missing_list,
                "duplicates": [],
                "unknown": unknown,
            }
        finally:
            lock.release()
