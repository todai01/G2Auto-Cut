import struct
import threading

import winsound


class AudioPlayer:
    """Проигрывание файлов. По умолчанию — в устройство Windows по умолчанию
    (winsound). Если выбрано своё устройство вывода (наушники того, кто
    слушает, а не гарнитура диктора) — через sounddevice прямо в него.

    Звучит всегда только одно: «играть» и «стоп» идут по очереди (команды с
    экрана приходят из разных потоков — клик по дорожке и кнопка «Слушать»
    могли запустить два звука поверх друг друга). Если пока файл готовился,
    пришла новая команда, — старый звук так и не начинается."""

    def __init__(self):
        self.is_playing = False
        self.device = None
        self._stream = None
        self._lock = threading.Lock()
        self._gen = 0

    def set_device(self, device):
        """device — номер устройства вывода sounddevice; None — по умолчанию."""
        self.stop()
        self.device = device

    def play(self, filepath):
        """Останавливает текущий звук и запускает новый файл асинхронно."""
        with self._lock:
            self._gen += 1
            my = self._gen
            self._stop_locked()
        prepared = None
        if self.device is not None:
            try:
                prepared = self._prepare(filepath)          # чтение и пересчёт — без блокировки
            except Exception:
                prepared = None                            # наушники отключили и т.п. — как раньше
        with self._lock:
            if my != self._gen:
                return                                     # уже попросили другое или «стоп»
            self._stop_locked()
            if prepared is not None:
                try:
                    self._start(*prepared)
                    self.is_playing = True
                    return
                except Exception:
                    pass
            winsound.PlaySound(filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.is_playing = True

    def stop(self):
        """Принудительно останавливает воспроизведение."""
        with self._lock:
            self._gen += 1
            self._stop_locked()

    def _stop_locked(self):
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.is_playing = False

    def _prepare(self, path):
        import numpy as np
        import sounddevice as sd
        data, rate = _read_audio(path)
        info = sd.query_devices(self.device, 'output')
        ch = 2 if data.shape[1] == 1 and info['max_output_channels'] >= 2 else data.shape[1]
        # Своя частота файла (8 кГц и т.п.) — пусть пересчитает Windows, как
        # раньше: качественно. Не принимает — пересчитываем сами, без «робота».
        out_rate = rate
        try:
            sd.check_output_settings(device=self.device, samplerate=rate, channels=ch, dtype='float32')
        except Exception:
            out_rate = int(info['default_samplerate']) or rate
            data = resample(data, rate, out_rate)
        if ch == 2 and data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)            # моно — в оба уха
        return np.ascontiguousarray(data, dtype=np.float32), out_rate

    def _start(self, data, rate):
        """Свой поток вывода (не общий sd.play): закрывается при следующем
        «играть»/«стоп», двух сразу не бывает."""
        import sounddevice as sd
        pos = [0]

        def callback(out, frames, t, status):
            n = max(0, min(frames, len(data) - pos[0]))
            out[:n] = data[pos[0]:pos[0] + n]
            out[n:] = 0
            pos[0] += n
            if n < frames:
                raise sd.CallbackStop

        stream = sd.OutputStream(samplerate=rate, channels=data.shape[1], dtype='float32',
                                 device=self.device, callback=callback)
        stream.start()
        self._stream = stream


def _read_audio(path):
    """(float32 [кадры, каналы], частота). WAV — сами (8/16/24/32 бит, float),
    остальное — через pydub."""
    import numpy as np
    from utils.wav_io import wav_layout
    lay = wav_layout(path)
    if lay:
        fmt, pos, size, block, rate = lay
        tag, ch = struct.unpack('<HH', fmt[0:4])
        bits = struct.unpack('<H', fmt[14:16])[0]
        if tag == 0xFFFE and len(fmt) >= 26:
            tag = struct.unpack('<H', fmt[24:26])[0]
        with open(path, 'rb') as f:
            f.seek(pos)
            raw = f.read(size - size % block)
        if tag == 3:
            x = np.frombuffer(raw, '<f4' if bits == 32 else '<f8').astype(np.float32)
        elif bits == 8:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif bits == 16:
            x = np.frombuffer(raw, '<i2').astype(np.float32) / 32768
        elif bits == 24:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
            v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
            x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
        else:
            x = np.frombuffer(raw, '<i4').astype(np.float32) / 2147483648
        return x.reshape(-1, max(1, ch)), rate
    from pydub import AudioSegment
    seg = AudioSegment.from_file(path)
    x = np.array(seg.get_array_of_samples(), dtype=np.float32) / float(1 << (8 * seg.sample_width - 1))
    return x.reshape(-1, seg.channels), seg.frame_rate


def resample(data, rate, out_rate):
    """Пересчёт частоты без искажений: scipy (если есть) или через спектр
    (FFT) — без «металла», который даёт простая линейная интерполяция."""
    import numpy as np
    if out_rate == rate or not len(data):
        return data
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(out_rate), int(rate))
        return resample_poly(data, int(out_rate) // g, int(rate) // g, axis=0).astype(np.float32)
    except Exception:
        pass
    n = len(data)
    m = int(round(n * out_rate / rate))
    spec = np.fft.rfft(data, axis=0)
    keep = min(spec.shape[0], m // 2 + 1)
    out = np.zeros((m // 2 + 1, data.shape[1]), dtype=spec.dtype)
    out[:keep] = spec[:keep]
    y = np.fft.irfft(out, n=m, axis=0) * (m / n)
    # края: короткое затухание, чтобы не щёлкало
    f = min(len(y) // 2, int(out_rate * 0.004))
    if f > 1:
        ramp = np.linspace(0, 1, f)[:, None]
        y[:f] *= ramp
        y[-f:] *= ramp[::-1]
    return y.astype(np.float32)
