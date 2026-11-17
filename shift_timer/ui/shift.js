// Расчёт смены — чистые функции, без DOM (проверяются node-тестами: tests/shift_logic.test.js).
(function (root) {
    const DAY = 86400000;

    function parseHM(s) {                                   // "09:30" → минуты от полуночи
        const m = /^(\d{1,2}):(\d{2})$/.exec(String(s || '').trim());
        if (!m) return null;
        const h = +m[1], mi = +m[2];
        return h > 23 || mi > 59 ? null : h * 60 + mi;
    }

    function at(day, minutes) {                             // день (Date, 00:00) + минуты
        const d = new Date(day.getFullYear(), day.getMonth(), day.getDate(), 0, 0, 0, 0);
        d.setMinutes(minutes);
        return d;
    }

    // Смена, к которой относится «сейчас»: началась вчера и ещё идёт (ночная) / сегодняшняя.
    // phase: before — ещё не началась, work — идёт, after — закончилась.
    function shiftAt(now, startHM, endHM) {
        const s = parseHM(startHM), e = parseHM(endHM);
        if (s === null || e === null) return null;
        let dur = (e - s) * 60000;
        if (dur <= 0) dur += DAY;                           // 22:00 → 06:00 — через полночь; одинаковые — сутки
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today.getTime() - DAY);
        const mk = day => { const st = at(day, s); return { start: st, end: new Date(st.getTime() + dur) }; };
        const y = mk(yesterday), t = mk(today);
        let shift, phase;
        if (now >= y.start && now < y.end) { shift = y; phase = 'work'; }
        else if (now >= t.start && now < t.end) { shift = t; phase = 'work'; }
        else if (now < t.start) { shift = t; phase = 'before'; }
        else { shift = t; phase = 'after'; }
        return { ...shift, phase, total: dur };
    }

    function report(now, startHM, endHM, showSeconds) {
        const sh = shiftAt(now, startHM, endHM);
        if (!sh) return null;
        const left = sh.end - now, done = now - sh.start;
        let progress = 0, remain = 0, elapsed = 0, over = 0, untilStart = 0;
        if (sh.phase === 'work') {
            progress = done / sh.total; remain = left; elapsed = done;
        } else if (sh.phase === 'after') {
            progress = 1; elapsed = sh.total; over = now - sh.end;
        } else {
            untilStart = sh.start - now; remain = sh.total;
        }
        return { ...sh, progress, remain: roundLeft(remain, showSeconds), remainExact: remain, elapsed, over, untilStart: roundLeft(untilStart, showSeconds) };
    }

    // Без секунд оставшееся округляем ВВЕРХ: «00:01» держится до самого конца, а не «00:00» за минуту до него.
    function roundLeft(ms, showSeconds) {
        if (showSeconds) return Math.ceil(ms / 1000) * 1000;
        return Math.ceil(ms / 60000) * 60000;
    }

    const p2 = n => String(n).padStart(2, '0');
    function clock(ms, showSeconds) {                       // 9015000 → "02:30:15" / "02:31"
        const t = Math.max(0, Math.round(ms / 1000));
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
        return showSeconds ? `${p2(h)}:${p2(m)}:${p2(s)}` : `${p2(h)}:${p2(m)}`;
    }
    function words(ms, showSeconds) {                       // "2 ч 30 мин" / "2 ч 30 мин 15 с"
        const t = Math.max(0, Math.round(ms / 1000));
        const h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
        const out = [];
        if (h) out.push(`${h} ч`);
        if (m || (!h && !showSeconds)) out.push(`${m} мин`);
        if (showSeconds && (s || !out.length)) out.push(`${s} с`);
        return out.join(' ');
    }
    function hm(d) { return `${p2(d.getHours())}:${p2(d.getMinutes())}`; }

    const api = { parseHM, shiftAt, report, clock, words, hm, roundLeft };
    if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Shift = api;
})(typeof window !== 'undefined' ? window : globalThis);
