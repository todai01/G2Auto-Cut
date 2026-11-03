"""Общие мелочи правки записи — для аудита, Студии и «Прослушки»:
исходник «до правок», волна для редактора, вернуть исходник, громкость
на слух (LUFS-подобно), открыть папку."""
import json
import os

import numpy as np


class EditBasicsMixin:
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

    @staticmethod
    def _k_weight(x, rate):
        """K-фильтр (как в LUFS): полка +4 дБ выше 1,5 кГц и срез ниже 38 Гц.
        Для замера громкости хватает АЧХ — применяем её в спектре (быстро)."""
        import math
        n = len(x)
        f = np.fft.rfftfreq(n, 1 / rate)
        z = np.exp(-1j * 2 * np.pi * f / rate)

        def resp(b, a):
            return np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z))
        w0 = 2 * math.pi * 1500 / rate
        A, c = 10 ** (4 / 40), math.cos(w0)
        sa = 2 * math.sqrt(A) * math.sin(w0) / (2 / math.sqrt(2))
        h = resp((A * ((A + 1) + (A - 1) * c + sa), -2 * A * ((A - 1) + (A + 1) * c), A * ((A + 1) + (A - 1) * c - sa)),
                 ((A + 1) - (A - 1) * c + sa, 2 * ((A - 1) - (A + 1) * c), (A + 1) - (A - 1) * c - sa))
        w0 = 2 * math.pi * 38 / rate
        al, c = math.sin(w0) / (2 * 0.5), math.cos(w0)
        h = h * resp(((1 + c) / 2, -(1 + c), (1 + c) / 2), (1 + al, -2 * c, 1 - al))
        return np.fft.irfft(np.fft.rfft(x) * h, n)

    @classmethod
    def _loudness(cls, seg):
        """Громкость голоса на слух, дБ (LUFS-подобно); None — тишина."""
        seg = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        x = np.frombuffer(seg.raw_data, dtype='<i2').astype(np.float64) / 32768
        if len(x) < 1600:
            return None
        y = cls._k_weight(x, 16000)
        blk, hop = 1600, 400                                        # окна 100 мс, шаг 25 мс
        ms = np.array([np.mean(y[k:k + blk] ** 2) for k in range(0, len(y) - blk + 1, hop)])
        ms = ms[ms > 10 ** ((-70 + 0.691) / 10)]
        if not len(ms):
            return None
        ms = ms[ms > np.mean(ms) * 10 ** (-10 / 10)]                # без пауз и хвостов
        return round(-0.691 + 10 * np.log10(np.mean(ms)), 1) if len(ms) else None

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
