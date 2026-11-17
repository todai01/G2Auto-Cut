// Расчёт по отработанному времени — чистые функции, без DOM (проверяются node-тестами: tests/shift_logic.test.js).
// worked, norm — секунды активного времени (Python считает, пока экран не заблокирован).
(function (root) {
    const p2 = n => String(n).padStart(2, '0');

    function parseHM(s) {                                   // "08:30" → минуты
        const m = /^(\d{1,2}):(\d{2})$/.exec(String(s || '').trim());
        if (!m) return null;
        const h = +m[1], mi = +m[2];
        return h > 23 || mi > 59 ? null : h * 60 + mi;
    }

    // phase: work — идёт, paused — экран заблокирован, done — норма выполнена.
    // extra — сколько обеда ещё впереди (секунды): прогноз ухода учитывает его, день = норма + обед.
    function calc(worked, norm, nowMs, paused, showSeconds, extra) {
        const left = Math.max(0, norm - worked);
        const done = worked >= norm;
        // Без секунд оставшееся округляем ВВЕРХ: «00:01» держится до самой нормы, а не «00:00» за минуту до неё.
        const remain = showSeconds ? Math.ceil(left) : Math.ceil(left / 60) * 60;
        const shownWorked = showSeconds ? Math.floor(worked) : Math.floor(worked / 60) * 60;
        const finish = !done && !paused ? new Date(Math.ceil((nowMs + (left + (extra || 0)) * 1000) / 60000) * 60000) : null;
        return {
            phase: done ? 'done' : paused ? 'paused' : 'work',
            remain, worked: shownWorked, over: Math.max(0, Math.floor(worked - norm)), finish,
            progress: norm > 0 ? Math.min(1, worked / norm) : 1,
            soon: !done && left <= 30 * 60,
        };
    }

    // Обед — отдельный таймер: elapsed — сколько идёт, len — длина обеда (секунды).
    function lunch(elapsed, len, showSeconds) {
        const left = Math.max(0, len - elapsed);
        return { remain: showSeconds ? Math.ceil(left) : Math.ceil(left / 60) * 60, progress: len > 0 ? Math.min(1, elapsed / len) : 1, over: elapsed >= len };
    }

    function clock(sec, showSeconds) {                      // 9015 → "02:30:15" / "02:30"
        const t = Math.max(0, Math.floor(sec));
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
        return showSeconds ? `${p2(h)}:${p2(m)}:${p2(s)}` : `${p2(h)}:${p2(m)}`;
    }
    function words(sec, showSeconds) {                      // "2 ч 30 мин" / "2 ч 30 мин 15 с"
        const t = Math.max(0, Math.floor(sec));
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
        const out = [];
        if (h) out.push(`${h} ч`);
        if (m || (!h && !showSeconds)) out.push(`${m} мин`);
        if (showSeconds && (s || !out.length)) out.push(`${s} с`);
        return out.join(' ');
    }
    function hm(d) { return `${p2(d.getHours())}:${p2(d.getMinutes())}`; }
    function hmStr(t) { return t ? String(t).slice(0, 5) : '—'; }       // "09:02:11" → "09:02"
    function signed(sec) {                                              // 720 → "+0:12", -3900 → "−1:05"
        const a = Math.round(Math.abs(sec) / 60), s = sec < 0 ? '−' : '+';
        return `${s}${Math.floor(a / 60)}:${p2(a % 60)}`;
    }
    function hmSec(sec) { const a = Math.floor(Math.max(0, sec) / 60); return `${Math.floor(a / 60)}:${p2(a % 60)}`; }   // 28800 → "8:00"

    const api = { parseHM, calc, lunch, clock, words, hm, hmStr, signed, hmSec };
    if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Shift = api;
})(typeof window !== 'undefined' ? window : globalThis);
