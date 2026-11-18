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

    // Таймер ухода — простые настенные часы, от отработанного времени не зависят: уход = приход + норма + обед (8 ч + 1 ч = 9 ч).
    // Не стоит ни при блокировке экрана, ни на обеде; меняется только если исправили время прихода.
    // arrival — «ЧЧ:ММ:СС» (или «ЧЧ:ММ»), norm и lunchLen — секунды. Нет прихода — null.
    function parseSec(s) {
        const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(String(s || '').trim());
        return m ? +m[1] * 3600 + +m[2] * 60 + (m[3] ? +m[3] : 0) : null;
    }
    function day(arrival, norm, lunchLen, nowMs, showSeconds) {
        const a = parseSec(arrival);
        if (a === null) return null;
        const n = new Date(nowMs), nowS = n.getHours() * 3600 + n.getMinutes() * 60 + n.getSeconds() + n.getMilliseconds() / 1000;
        const total = norm + lunchLen, leave = a + total, left = leave - nowS;
        return {
            phase: left <= 0 ? 'done' : 'work',
            remain: showSeconds ? Math.ceil(Math.max(0, left)) : Math.ceil(Math.max(0, left) / 60) * 60,   // без секунд — вверх, как и раньше
            over: Math.max(0, Math.floor(-left)),
            progress: total > 0 ? Math.min(1, Math.max(0, (nowS - a) / total)) : 1,
            leave: `${p2(Math.floor(leave / 3600) % 24)}:${p2(Math.floor(leave % 3600 / 60))}`,
            soon: left > 0 && left <= 30 * 60,
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

    // Сколько идёт задача: до суток — секундомер «10:30:12», дальше — «1 д 10 ч 30 мин» (нулевые части пропускаются: «1 д 5 мин»).
    function dur(sec) {
        sec = Math.floor(Math.max(0, sec));
        if (sec < 86400) return `${Math.floor(sec / 3600)}:${p2(Math.floor(sec % 3600 / 60))}:${p2(sec % 60)}`;
        const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
        return [d + ' д', h ? h + ' ч' : '', m ? m + ' мин' : ''].filter(Boolean).join(' ');
    }
    // Когда создана: «сегодня 09:12», «вчера 16:40», «15.11 09:12» (iso — «ГГГГ-ММ-ДДTЧЧ:ММ:СС», now — Date).
    function when(iso, now) {
        const d = new Date(iso);
        if (isNaN(d)) return '';
        const day = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
        const diff = Math.round((day(now) - day(d)) / 86400000), t = hm(d);
        if (diff === 0) return 'сегодня ' + t;
        if (diff === 1) return 'вчера ' + t;
        return `${p2(d.getDate())}.${p2(d.getMonth() + 1)} ${t}`;
    }

    // Высота мини-окна с задачами: сам таймер (100) + список + поле «Новая задача». Задачи — массив текстов (или просто число):
    // короткая — строка 34, длинная переносится на две — 46; сумма не больше 190, дальше список прокручивается.
    const TASK_CHARS = 22;                                   // примерно столько знаков влезает в строку широкого мини-окна
    function tasksHeight(items) {
        const rows = Array.isArray(items) ? items.map(t => (String(t).length > TASK_CHARS ? 46 : 34)) : Array(Math.max(0, items | 0)).fill(34);
        return 100 + 8 + (rows.length ? Math.min(rows.reduce((a, b) => a + b, 0), 190) : 38) + 44;
    }

    const api = { parseHM, parseSec, day, calc, lunch, tasksHeight, dur, when, clock, words, hm, hmStr, signed, hmSec };
    if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.Shift = api;
})(typeof window !== 'undefined' ? window : globalThis);
