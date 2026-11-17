// Общее для обоих окон: настройки от Python, тема, тик раз в 250 мс.
const App = { s: null, onChange: null };
const $ = id => document.getElementById(id);
const setText = (el, t) => { if (el && el.textContent !== t) el.textContent = t; };

function applyTheme() {
    const t = App.s && App.s.theme;
    if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
}
// Python вызывает это при любой смене настроек — сразу в обоих окнах.
window.applySettings = s => { App.s = s; applyTheme(); if (App.onChange) App.onChange(); };

function boot(onReady) {
    const go = async () => {
        App.s = await pywebview.api.get_settings();
        applyTheme();
        onReady();
        setInterval(() => App.onChange && App.onChange(), 250);
    };
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_settings) go();
    else window.addEventListener('pywebviewready', go);
}
const save = patch => pywebview.api.save_settings(patch);

// Что показать по расчёту смены — одно и то же в главном окне и в мини.
function view(now) {
    const s = App.s, r = Shift.report(now, s.start, s.end, s.seconds);
    if (!r) return null;
    const soon = r.phase === 'work' && r.remainExact <= 30 * 60000;
    return { r, soon, pct: Math.floor(r.progress * 100) };
}
