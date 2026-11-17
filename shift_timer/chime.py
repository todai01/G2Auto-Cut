"""Тихий сигнал уведомления: одна спокойная нота, плавно возникает и затухает (колокольчик).

Звук строится кодом (WAV в памяти), файлов не нужно. Играет только в Windows (winsound), в остальных системах — тишина.
"""
import io
import math
import struct
import sys
import threading
import wave

RATE = 44100
FREQ = 659.25            # ми второй октавы — мягкая, не резкая нота
DURATION = 2.4           # секунд, вместе с затуханием
PEAK = 0.20              # громкость от максимума: тихо
ATTACK = 0.06            # плавное начало, без щелчка
DECAY = 0.55             # чем больше, тем дольше «звенит»
OVERTONES = ((1, 1.0), (2, 0.22), (3, 0.06), (4.2, 0.03))   # основной тон + лёгкий «колокольный» оттенок


def make_wav(freq=FREQ, duration=DURATION, peak=PEAK):
    n = int(RATE * duration)
    fade_out = int(RATE * 0.35)                          # последние 0,35 с — окончательное затухание до нуля
    norm = sum(a for _, a in OVERTONES)
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        env = (1 - math.exp(-t / (ATTACK / 3))) * math.exp(-t / DECAY)       # быстрый плавный подъём и экспоненциальный спад
        if i > n - fade_out:
            env *= (n - i) / fade_out
        v = sum(a * math.sin(2 * math.pi * freq * k * t) for k, a in OVERTONES) / norm
        frames += struct.pack('<h', int(max(-1.0, min(1.0, v * env * peak * 2.2)) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


_wav = None


def play_async():
    """Сыграть ноту, не задерживая вызывающего. Вне Windows — ничего."""
    global _wav
    if sys.platform != 'win32':
        return False

    def go():
        global _wav
        try:
            import winsound
            if _wav is None:
                _wav = make_wav()
            winsound.PlaySound(_wav, winsound.SND_MEMORY)     # SND_ASYNC с памятью не поддерживается — играем в своём потоке
        except Exception:
            pass
    threading.Thread(target=go, daemon=True).start()
    return True
