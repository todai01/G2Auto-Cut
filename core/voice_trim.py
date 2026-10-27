"""Где в короткой записи (имя, сумма) голос — для срезки краёв.

Голос — кадры с периодичностью (основной тон 70–400 Гц) и громкие. Глухие
согласные на краю слова («С», «Ш», «К», «Т»…) — шум без тона, поэтому к голосу
добавляем шум, идущий вплотную к нему (без паузы), но не длиннее, чем бывает
у согласной. Вдох, причмокивание, щелчок, шум до паузы перед голосом — отрезаем."""
import numpy as np

HOP_MS, WIN_MS = 10, 30
MIN_VOICED_MS = 40            # короче — не голос (щелчок, призвук)
LEAD_CONS_MS = 160            # сколько глухого шума вплотную перед голосом считать согласной
TAIL_CONS_MS = 300            # после голоса: «с», «т», затухание
BREATH_MIN_MS = 80            # шум до паузы длиннее этого — вдох


def voice_span(x, rate):
    """(v0, v1, info) — начало и конец голоса в мс; info: что отрезано
    ({'breath': мс вдоха / шума до голоса, 'noise': мс шума после})."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    dur = int(len(x) * 1000 / rate)
    hop, win = max(1, rate * HOP_MS // 1000), max(2, rate * WIN_MS // 1000)
    n = (len(x) - win) // hop + 1
    if n < 5:
        return 0, dur, {}
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    fr = x[idx]
    fr = (fr - fr.mean(axis=1, keepdims=True)) * np.hanning(win)
    db = 10 * np.log10((fr ** 2).mean(axis=1) + 1e-12)
    floor, peak = np.percentile(db, 10), np.percentile(db, 99)
    if peak - floor < 10:                                   # ни голоса, ни тишины — не трогаем
        return 0, dur, {}
    thr_hi = max(floor + 15, peak - 30)                     # голос
    thr_lo = max(floor + 7, peak - 45)                      # согласные, хвосты, вдох
    # периодичность: нормированная автокорреляция на лагах основного тона
    spec = np.fft.rfft(fr, 2 * win, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :win]
    ac /= ac[:, :1] + 1e-12
    lo, hi = max(1, rate // 400), min(win - 1, rate // 70)
    per = ac[:, lo:hi].max(axis=1)
    voiced = (db > thr_hi) & ((per > 0.3) | (db > peak - 10))    # тон — или просто громко (вдох тише голоса)
    k = max(1, MIN_VOICED_MS // HOP_MS)
    runs = np.convolve(voiced.astype(int), np.ones(k, int), 'valid') == k
    core = np.nonzero(runs)[0]
    if len(core):
        a, b = int(core[0]), int(core[-1]) + k              # кадры [a, b)
    else:
        loud = np.nonzero(db > thr_hi)[0]
        if not len(loud):
            return 0, dur, {}
        a, b = int(loud[0]), int(loud[-1]) + 1
    j = a                                                   # согласная вплотную перед голосом
    while j > 0 and a - j < LEAD_CONS_MS // HOP_MS and db[j - 1] > thr_lo:
        j -= 1
    e = b                                                   # и после
    while e < n and e - b < TAIL_CONS_MS // HOP_MS and db[e] > thr_lo:
        e += 1
    info = {}
    before = int(np.sum(db[:j] > thr_lo)) * HOP_MS
    if before >= BREATH_MIN_MS:
        info["breath"] = before
    after = int(np.sum(db[e:] > thr_lo)) * HOP_MS
    if after >= 30:
        info["noise"] = after
    v0 = j * HOP_MS
    v1 = min(dur, (e - 1) * HOP_MS + WIN_MS)
    return int(v0), int(max(v1, v0 + 40)), info
