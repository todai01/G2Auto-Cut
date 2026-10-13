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

from utils.wav_io import slice_or_export, wav_concat
from core.auto_check import (ASR_RATE, NEED_MODEL, NOISE_MAX_DBFS, NOISE_MIN_MS,
                             SPEECH_MIN_SCORE, score_candidates)

AUDIT_FOUND_SCORE = 0.80      # лучший вариант засчитываем как «записано»
AUDIT_FOUND_MARGIN = 0.05     # …если он опережает второй хотя бы на столько
AUDIT_SURE_SCORE = 0.92       # почти дословное совпадение — засчитываем всегда
                              # (в один чанк могли слипнуться две марки)
AUDIT_CUT_PAD_MS = 150
AUDIO_EXT = ('.wav', '.mp3', '.flac', '.ogg')
AUDIT_FIX_FILE = '_аудит_текст.json'   # ваши правки распознанного текста — рядом с чанками


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
            lo, hi = max(0, a - AUDIT_CUT_PAD_MS), min(len(audio), b + AUDIT_CUT_PAD_MS)
            piece = audio[lo:hi]
            name = f"фраза_{i + 1:04d}.wav"
            slice_or_export(path, os.path.join(out_dir, name), lo, hi, audio)
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
        if category == 'excel':
            seen, values = set(), []
            for p in getattr(self, 'phrases_data', None) or []:
                t = str(p.get('text') or '').strip()
                if t and t not in seen:
                    seen.add(t)
                    values.append(t)
        else:
            values = (getattr(self, 'var_extra_tag_values', None) or {}).get(category) or []
        if not values:
            return {"error": "Нет значений для сверки — загрузите таблицу."}

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
            fixes = self._audit_fixes_load(scan_dir)
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
            rows = []
            for k, (name, src) in enumerate(chunks):
                heard = heard_by.get(k, '')
                path = src if isinstance(src, str) else os.path.join(scan_dir, name)
                rows.append({"filename": name, "path": path, "heard": heard,
                             "text": fixes.get(name, heard), "fixed": name in fixes})
            self._audit_voice = {"category": category, "values": values, "transcripts": transcripts,
                                 "rows": rows, "scan_dir": scan_dir, "stopped": stopped, "total": total}
            return self._audit_voice_result()
        finally:
            lock.release()

    # ---------------- правка распознанного текста и прослушка ----------------

    @staticmethod
    def _audit_fixes_load(scan_dir):
        try:
            with open(os.path.join(scan_dir, AUDIT_FIX_FILE), 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _audit_match(text, values, transcripts):
        """(уверенно найденные значения, лучшая догадка, её оценка)."""
        if not text:
            return [], None, 0.0
        scored = score_candidates(text, values, transcripts)
        best, best_score = scored[0]
        second = scored[1][1] if len(scored) > 1 else 0.0
        hits = []
        if best_score >= AUDIT_FOUND_SCORE and best_score - second >= AUDIT_FOUND_MARGIN:
            hits.append(best)
        for v, sc in scored:
            if sc < AUDIT_SURE_SCORE:
                break
            if v not in hits:
                hits.append(v)
        return hits, best, best_score

    def _audit_voice_result(self):
        """Итог аудита по голосу из текущих текстов чанков (с вашими правками)."""
        av = self._audit_voice
        values, transcripts, category = av["values"], av["transcripts"], av["category"]
        found, unknown, files = {}, [], []
        for r in av["rows"]:
            hits, best, sc = self._audit_match(r["text"], values, transcripts)
            for v in hits:
                found.setdefault(v, r["filename"])
            if r["text"] and not hits and sc >= SPEECH_MIN_SCORE:
                unknown.append({"filename": r["filename"], "heard": r["text"], "guess": best, "score": round(sc, 2)})
            files.append({"filename": r["filename"], "path": r["path"], "heard": r["heard"], "text": r["text"],
                          "fixed": r["fixed"], "match": hits[0] if hits else None,
                          "guess": best if not hits else None, "score": round(sc, 2)})
        missing_list = [{"index": i + 1, "filename": "не услышано", "text": v}
                        for i, v in enumerate(values) if v not in found]
        self._audit_last = {"category": category, "missing": {m["text"] for m in missing_list}}
        template = getattr(self, 'var_template_path', None)
        can_export = self._excel_source_ok() if category == 'excel' else bool(template and os.path.exists(template))
        return {
            "category": category,
            "category_label": "Текст из Excel" if category == 'excel' else self._category_label(category),
            "by_voice": True,
            "stopped": av["stopped"],
            "scan_dir": av["scan_dir"],
            "chunks_total": av["total"],
            "can_export": bool(missing_list and can_export),
            "total_excel": len(values),
            "total_disk": len(found),
            "missing_count": len(missing_list),
            "duplicates_count": 0,
            "missing": missing_list,
            "duplicates": [],
            "unknown": unknown,
            "files": files,
        }

    def audit_voice_fix(self, filename, text):
        """Исправить распознанный текст чанка: сверка пересчитывается сразу,
        правка запоминается в папке чанков (и в следующем аудите)."""
        av = getattr(self, '_audit_voice', None)
        if not av:
            return {"error": "Сначала запустите аудит по голосу."}
        row = next((r for r in av["rows"] if r["filename"] == filename), None)
        if row is None:
            return {"error": "Нет такого чанка."}
        text = str(text or '').strip()
        fixes = self._audit_fixes_load(av["scan_dir"])
        if text and text != row["heard"]:
            fixes[filename] = text
            row["text"], row["fixed"] = text, True
        else:                                                  # вернули как было — правку убираем
            fixes.pop(filename, None)
            row["text"], row["fixed"] = row["heard"], False
        try:
            with open(os.path.join(av["scan_dir"], AUDIT_FIX_FILE), 'w', encoding='utf-8') as f:
                json.dump(fixes, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
        return self._audit_voice_result()

    def audit_play(self, path):
        """Прослушать запись из аудита (повторный вызов того же файла — стоп)."""
        self.player.stop()
        if getattr(self, '_audit_playing', None) == path:
            self._audit_playing = None
            return {"playing": False}
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        self._audit_playing = path
        self.player.play(path)
        try:
            dur = len(AudioSegment.from_file(path)) / 1000.0
        except Exception:
            dur = 0
        return {"playing": True, "duration": dur}

    def audit_play_stop(self):
        self.player.stop()
        self._audit_playing = None
        return {"ok": True}

    # ---------------- правка записи прямо в аудите ----------------
    # Правка = какие куски исходного файла оставить [(начало_мс, конец_мс)].
    # Сохраняется байт в байт (без перекодирования); исходник — в
    # «_до_правок/» рядом, его можно вернуть.

    AUDIT_EDIT_BUCKET = 10

    @staticmethod
    def _audit_backup(path):
        return os.path.join(os.path.dirname(path), '_до_правок', os.path.basename(path))

    def _audit_src(self, path):
        """Исходник для правки: копия «до правок», если запись уже правилась."""
        b = self._audit_backup(path)
        return b if os.path.exists(b) else path

    def audit_edit_load(self, path):
        """Волна записи для правки: пики по 10 мс, длительность."""
        import numpy as np
        from utils.audio_player import _read_audio
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        src = self._audit_src(path)
        x, rate = _read_audio(src)
        mono = np.abs(x).max(axis=1) if x.ndim > 1 else np.abs(x)
        n = max(1, int(rate * self.AUDIT_EDIT_BUCKET / 1000))
        k = len(mono) // n
        peaks = mono[:k * n].reshape(k, n).max(axis=1) if k else np.zeros(0)
        top = float(peaks.max()) if len(peaks) else 0.0
        norm = min(40.0, 0.95 / top) if top > 1e-4 else 1.0
        dur = int(len(mono) * 1000 / rate)
        ranges = [[0, dur]]
        try:                                                   # прошлая правка — куски, что оставили
            with open(self._audit_backup(path) + '.json', 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if saved and all(0 <= a < b <= dur for a, b in saved):
                ranges = saved
        except (OSError, ValueError, TypeError):
            pass
        return {"path": path, "name": os.path.basename(path), "dur": dur, "ranges": ranges,
                "bucket": self.AUDIT_EDIT_BUCKET, "peaks": [round(min(1.0, float(v) * norm), 3) for v in peaks],
                "has_backup": src != path}

    def _audit_render(self, path, ranges, dst):
        ranges = [(int(a), int(b)) for a, b in ranges if int(b) - int(a) > 0]
        if not ranges:
            raise ValueError("Ничего не осталось.")
        if not wav_concat(path, dst, ranges):
            seg = AudioSegment.from_file(path)
            out = sum((seg[a:b] for a, b in ranges[1:]), seg[ranges[0][0]:ranges[0][1]])
            out.export(dst, format="wav")
        return sum(b - a for a, b in ranges)

    def audit_edit_play(self, path, ranges, from_ms=0, to_ms=None):
        """Прослушать запись с правками (весь звук или с места / кусок)."""
        import tempfile
        self.player.stop()
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        # кусок [from, to] на дорожке после правок → куски исходника
        out, pos = [], 0
        lo, hi = int(from_ms or 0), (int(to_ms) if to_ms is not None else 10 ** 9)
        for a, b in ranges:
            a, b = int(a), int(b)
            s, e = max(lo, pos), min(hi, pos + b - a)
            if e > s:
                out.append((a + s - pos, a + e - pos))
            pos += b - a
        self._audit_tmp_n = getattr(self, '_audit_tmp_n', 0) + 1
        tmp = os.path.join(tempfile.gettempdir(), f"gvox_audit_{os.getpid()}_{self._audit_tmp_n % 3}.wav")
        try:
            dur = self._audit_render(self._audit_src(path), out, tmp)
        except ValueError:
            return {"error": "Нечего играть."}
        self._audit_playing = None
        self.player.play(tmp)
        return {"playing": True, "duration": dur / 1000.0}

    def audit_edit_save(self, path, ranges):
        """Записать правку в файл (исходник — в «_до_правок/», один раз)."""
        import shutil
        import tempfile
        if not path or not os.path.exists(path):
            return {"error": "Файл не найден."}
        self.player.stop()
        backup = self._audit_backup(path)
        try:
            if not os.path.exists(backup):
                os.makedirs(os.path.dirname(backup), exist_ok=True)
                shutil.copy2(path, backup)
            src = backup                                      # правка всегда от исходника — без накопления
            tmp = os.path.join(tempfile.gettempdir(), f"gvox_audit_save_{os.getpid()}.wav")
            ms = self._audit_render(src, ranges, tmp)
            shutil.move(tmp, path)
            with open(backup + '.json', 'w', encoding='utf-8') as f:
                json.dump([[int(a), int(b)] for a, b in ranges], f)
        except PermissionError:
            return {"error": "Файл занят (открыт в другой программе) — закройте и повторите."}
        except Exception as e:
            return {"error": f"Не удалось сохранить: {e}"}
        return {"ok": True, "ms": ms, "has_backup": True}

    def audit_edit_restore(self, path):
        """Вернуть исходную запись (до правок)."""
        import shutil
        backup = self._audit_backup(path)
        if not os.path.exists(backup):
            return {"error": "Исходника нет — запись не правилась."}
        self.player.stop()
        shutil.copy2(backup, path)
        for f in (backup + '.json', backup):
            try:
                os.remove(f)
            except OSError:
                pass
        return self.audit_edit_load(path)

