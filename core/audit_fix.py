"""Аудит → исправить на месте: записать недостающее с микрофона (или взять
готовый файл) прямо в нужную папку под нужным именем, разобрать дубли.

Результат последнего аудита (_audit_run) хранится в self._audit_res; каждое
действие меняет его и возвращает целиком — окно аудита перерисовывается
с новыми цифрами без повторного сканирования."""
import os
import re
import shutil
import tempfile
import time
import wave

import numpy as np
import webview
from pydub import AudioSegment

AUDIT_TRASH_DIR = 'trash_аудит'      # «trash» в имени — аудит эту папку не сканирует
AUDIT_LEAD_MS = 120                  # тишины перед голосом в готовом файле
AUDIT_TAIL_MS = 220                  # и после
AUDIT_FRAME_MS = 10


class AuditFixMixin:

    # ---------------- куда и в каком формате сохранять ----------------
    def _audit_group(self, gid):
        res = getattr(self, '_audit_res', None) or {}
        return next((g for g in res.get("groups") or [] if g["id"] == gid), None)

    @staticmethod
    def _audit_format(folder):
        """Формат соседних записей папки (частота, бит, каналы); нет — 8 кГц/16/моно."""
        try:
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith('.wav'):
                    with wave.open(os.path.join(folder, name), 'rb') as w:
                        return w.getframerate(), w.getsampwidth(), w.getnchannels()
        except Exception:
            pass
        return 8000, 2, 1

    def _audit_trash(self, path):
        """Файл → «trash_аудит/» рядом с выбранной папкой (не удаляем насовсем)."""
        res = getattr(self, '_audit_res', None) or {}
        root = res.get("scan_dir") or os.path.dirname(path)
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            rel = os.path.basename(path)
        if rel.startswith('..'):
            rel = os.path.basename(path)
        dst = os.path.join(root, AUDIT_TRASH_DIR, time.strftime('%Y-%m-%d_%H-%M-%S'), rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(path, dst)
        return dst

    def _audit_write(self, seg, dst, normalize=True):
        """Сохранить в формате соседних файлов. normalize — громкость речи как у
        готовых записей программы (OUT_SPEECH_DB)."""
        folder = os.path.dirname(dst)
        os.makedirs(folder, exist_ok=True)
        rate, width, ch = self._audit_format(folder)
        seg = seg.set_channels(1)
        if normalize:
            seg = self._tts_normalized(seg)
        tmp = dst + '.tmp.wav'
        codec = {1: 'pcm_u8', 2: 'pcm_s16le', 3: 'pcm_s24le', 4: 'pcm_s32le'}.get(width, 'pcm_s16le')
        try:
            seg.export(tmp, format='wav', parameters=['-ar', str(rate), '-ac', str(ch), '-acodec', codec])
        except Exception:
            seg.set_frame_rate(rate).set_channels(ch).set_sample_width(min(width, 4)).export(tmp, format='wav')
        if os.path.exists(dst):
            self._audit_trash(dst)
        os.replace(tmp, dst)
        return dst

    def _audit_found(self, gid, filename, path):
        """Отметить в результате: недостающее теперь есть."""
        res = self._audit_res
        key = filename.lower()
        m = next((x for x in res["missing"] if x.get("group") == gid and x["filename"].lower() == key), None)
        if m:
            res["missing"].remove(m)
            res["missing_count"] = len(res["missing"])
            f = {"filename": os.path.basename(path), "path": path, "text": m.get("text", ""), "group": gid, "new": True}
            if m.get("phrase"):
                f["phrase"] = m["phrase"]
            if str(gid).startswith('ph_'):
                f["i"] = m["index"] - 1
            res["files"].append(f)
            res["total_disk"] = len(res["files"])
            g = self._audit_group(gid)
            if g:
                g["missing"] = max(0, g["missing"] - 1)
                g["found"] += 1
            last = getattr(self, '_audit_last', None)
            if last and last.get("missing"):
                last["missing"].discard(m.get("text"))
        res["can_export"] = bool(res["can_export"] and res["missing"])
        return res

    def _audit_target(self, gid, filename):
        g = self._audit_group(gid)
        if not g or not g.get("target"):
            return None, {"error": "Не знаю, куда сохранить — запустите аудит заново."}
        name = filename if filename.lower().endswith('.wav') else re.sub(r'\.mp3$', '', filename, flags=re.I) + '.wav'
        return os.path.join(g["target"], name), None

    # ---------------- запись с микрофона ----------------
    def audit_rec_start(self, device=None):
        if getattr(self, '_tts_rec', None):
            return {"error": "Идёт запись в режиме TTS — сначала остановите её."}
        if getattr(self, '_audit_rec', None):
            return {"error": "Запись уже идёт."}
        from core.tts_live import LiveRecorder
        try:
            self.player.stop()
        except Exception:
            pass
        path = os.path.join(tempfile.gettempdir(), f"gvox_audit_rec_{os.getpid()}.wav")
        try:
            rec = LiveRecorder(path, None if device in (None, '', -1) else int(device))
            rec.start()
        except Exception as e:
            return {"error": f"Не удалось включить микрофон: {e}"}
        self._audit_rec = rec
        return {"recording": True, "device": rec.device_name}

    def audit_rec_level(self):
        rec = getattr(self, '_audit_rec', None)
        if not rec:
            return {"recording": False}
        return {"recording": True, "db": round(rec.level_db, 1), "ms": rec.frames * 1000 // max(1, rec.rate),
                "error": rec.error}

    def audit_rec_stop(self):
        """Стоп → дубль: волна и границы голоса (тишина по краям срезается сама)."""
        rec = getattr(self, '_audit_rec', None)
        if not rec:
            return {"error": "Запись не идёт."}
        self._audit_rec = None
        rec.stop()
        try:
            seg = AudioSegment.from_file(rec.path).set_channels(1)
        except Exception as e:
            return {"error": f"Запись не читается: {e}"}
        if len(seg) < 200:
            return {"error": "Слишком коротко — запишите ещё раз."}
        x = np.frombuffer(seg.set_sample_width(2).raw_data, dtype='<i2').astype(np.float32) / 32768
        per = max(1, seg.frame_rate * AUDIT_FRAME_MS // 1000)
        n = len(x) // per
        rms = np.sqrt((x[:n * per].reshape(n, per) ** 2).mean(axis=1)) if n else np.zeros(0)
        top = float(rms.max()) if len(rms) else 0.0
        if top < 10 ** (-50 / 20):
            return {"error": "Тишина — проверьте микрофон и запишите ещё раз."}
        thr = max(top * 10 ** (-32 / 20), float(np.percentile(rms, 10)) * 3, 10 ** (-60 / 20))
        v = np.nonzero(rms > thr)[0]
        a = max(0, int(v[0]) * AUDIT_FRAME_MS - AUDIT_LEAD_MS)
        b = min(len(seg), int(v[-1] + 1) * AUDIT_FRAME_MS + AUDIT_TAIL_MS)
        clip = 20 * np.log10(float(np.abs(x).max()) + 1e-9) > -0.3
        self._audit_take = {"path": rec.path, "len": len(seg), "a": a, "b": b}
        step = max(1, len(rms) // 600)
        peaks = [round(float(rms[k:k + step].max()) / top, 3) for k in range(0, len(rms), step)]
        return {"take": {"len": len(seg), "a": a, "b": b, "peaks": peaks, "bucket": step * AUDIT_FRAME_MS,
                         "clipped": bool(clip)}}

    def audit_rec_bounds(self, a, b):
        t = getattr(self, '_audit_take', None)
        if not t:
            return {"error": "Нет записи."}
        t["a"] = max(0, min(int(a), t["len"] - 50))
        t["b"] = max(t["a"] + 50, min(int(b), t["len"]))
        return {"a": t["a"], "b": t["b"]}

    def audit_rec_play(self):
        """Послушать так, как сохранится (срезано, громкость выровнена)."""
        t = getattr(self, '_audit_take', None)
        if not t:
            return {"error": "Нет записи."}
        seg = self._tts_normalized(AudioSegment.from_file(t["path"])[t["a"]:t["b"]].set_channels(1))
        dst = os.path.join(tempfile.gettempdir(), f"gvox_audit_prev_{os.getpid()}.wav")
        seg.export(dst, format='wav')
        self.player.stop()
        self._audit_playing = None
        self.player.play(dst)
        return {"playing": True, "duration": len(seg) / 1000.0}

    def audit_rec_cancel(self):
        rec = getattr(self, '_audit_rec', None)
        if rec:
            self._audit_rec = None
            rec.stop()
        self._audit_take = None
        return {"ok": True}

    def audit_rec_save(self, gid, filename):
        """Дубль → в папку группы под именем недостающего файла."""
        t = getattr(self, '_audit_take', None)
        if not t:
            return {"error": "Сначала запишите."}
        dst, err = self._audit_target(gid, filename)
        if err:
            return err
        try:
            seg = AudioSegment.from_file(t["path"])[t["a"]:t["b"]]
            self._audit_write(seg, dst)
        except PermissionError:
            return {"error": "Файл занят другой программой — закройте его и повторите."}
        except Exception as e:
            return {"error": f"Не удалось сохранить: {e}"}
        self._audit_take = None
        return {"saved": dst, "res": self._audit_found(gid, os.path.basename(filename), dst)}

    # ---------------- готовый файл вместо записи ----------------
    def audit_put_file(self, gid, filename):
        """Взять готовую запись (любой формат) — сохранить как недостающий файл."""
        dst, err = self._audit_target(gid, filename)
        if err:
            return err
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Аудио (*.wav;*.mp3;*.flac;*.ogg;*.m4a)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        try:
            self._audit_write(AudioSegment.from_file(src), dst, normalize=False)
        except Exception as e:
            return {"error": f"Не удалось взять файл: {e}"}
        return {"saved": dst, "res": self._audit_found(gid, os.path.basename(filename), dst)}

    # ---------------- дубли ----------------
    def audit_dup_keep(self, gid, filename, keep):
        """Оставить один из дублей; остальные — в «trash_аудит/» (не удаляются)."""
        res = getattr(self, '_audit_res', None)
        if not res:
            return {"error": "Запустите аудит заново."}
        d = next((x for x in res["duplicates"] if x.get("group") == gid and x["filename"] == filename), None)
        if not d or keep not in d["paths"]:
            return {"error": "Этот дубль уже разобран."}
        moved = []
        for p in d["paths"]:
            if p != keep and os.path.exists(p):
                try:
                    moved.append(self._audit_trash(p))
                except Exception as e:
                    return {"error": f"Не удалось убрать {os.path.basename(p)}: {e}"}
        res["duplicates"].remove(d)
        res["duplicates_count"] = len(res["duplicates"])
        g = self._audit_group(gid)
        if g:
            g["duplicates"] = max(0, g["duplicates"] - 1)
        for f in res["files"]:
            if f.get("group") == gid and f["filename"].lower() == filename:
                f["path"] = keep
        return {"moved": len(moved), "trash": os.path.join(res["scan_dir"], AUDIT_TRASH_DIR), "res": res}

    def audit_open_folder(self, path):
        path = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(path):
            return {"error": "Папки нет."}
        try:
            os.startfile(path)                      # Windows
        except AttributeError:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        return {"ok": True}
