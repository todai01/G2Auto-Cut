"""Тихий сигнал уведомления: две спокойные ноты — низкая, затем высокая, каждая плавно возникает и затухает (колокольчик).

Звук строится кодом (WAV в памяти), файлов не нужно. Играет только в Windows (winsound), в остальных системах — тишина.
"""
import io
import math
import struct
import sys
import threading
import wave

RATE = 44100
NOTES = ((523.25, 0.0), (783.99, 0.40))   # (частота, начало, с): до второй октавы, затем соль — низкая, потом высокая (квинта)
DURATION = 2.9           # секунд, вместе с затуханием
PEAK = 0.20              # громкость от максимума: тихо
ATTACK = 0.06            # плавное начало, без щелчка
DECAY = 0.55             # чем больше, тем дольше «звенит»
OVERTONES = ((1, 1.0), (2, 0.22), (3, 0.06), (4.2, 0.03))   # основной тон + лёгкий «колокольный» оттенок


def _note(t, freq):
    """Одна нота: быстрый плавный подъём и экспоненциальный спад (t — секунды от её начала)."""
    if t < 0:
        return 0.0
    env = (1 - math.exp(-t / (ATTACK / 3))) * math.exp(-t / DECAY)
    return env * sum(a * math.sin(2 * math.pi * freq * k * t) for k, a in OVERTONES)


def make_wav(notes=NOTES, duration=DURATION, peak=PEAK):
    n = int(RATE * duration)
    fade_out = int(RATE * 0.4)                           # последние 0,4 с — окончательное затухание до нуля
    norm = sum(a for _, a in OVERTONES) * 1.25           # запас: две ноты немного перекрываются
    frames = bytearray()
    for i in range(n):
        t = i / RATE
        v = sum(_note(t - start, f) for f, start in notes) / norm
        if i > n - fade_out:
            v *= (n - i) / fade_out
        frames += struct.pack('<h', int(max(-1.0, min(1.0, v * peak * 2.2)) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


_wav = None


def play_async():
    """Сыграть сигнал, не задерживая вызывающего. Вне Windows — ничего."""
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
