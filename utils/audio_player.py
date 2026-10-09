import struct

import winsound


class AudioPlayer:
    """Проигрывание файлов. По умолчанию — в устройство Windows по умолчанию
    (winsound). Если выбрано своё устройство вывода (наушники того, кто
    слушает, а не гарнитура диктора) — через sounddevice прямо в него."""

    def __init__(self):
        self.is_playing = False
        self.device = None
        self._sd = None

    def set_device(self, device):
        """device — номер устройства вывода sounddevice; None — по умолчанию."""
        self.stop()
        self.device = device

    def play(self, filepath):
        """Останавливает текущий звук и запускает новый файл асинхронно."""
        self.stop()
        if self.device is not None:
            try:
                self._play_device(filepath)
                self.is_playing = True
                return
            except Exception:
                pass                     # наушники отключили и т.п. — играем как раньше
        winsound.PlaySound(filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.is_playing = True

    def stop(self):
        """Принудительно останавливает воспроизведение."""
        if self.is_playing:
            if self._sd is not None:
                try:
                    self._sd.stop()
                except Exception:
                    pass
                self._sd = None
            winsound.PlaySound(None, winsound.SND_PURGE)
            self.is_playing = False

    def _play_device(self, path):
        import numpy as np
        import sounddevice as sd
        data, rate = _read_audio(path)
        info = sd.query_devices(self.device, 'output')
        out_rate = int(info['default_samplerate']) or rate
        if out_rate != rate and len(data):
            n = int(round(len(data) * out_rate / rate))
            t = np.linspace(0, len(data) - 1, n)
            data = np.stack([np.interp(t, np.arange(len(data)), data[:, c]) for c in range(data.shape[1])], axis=1)
        if data.shape[1] == 1 and info['max_output_channels'] >= 2:
            data = np.repeat(data, 2, axis=1)            # моно — в оба уха
        sd.play(data.astype(np.float32), out_rate, device=self.device)
        self._sd = sd


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
