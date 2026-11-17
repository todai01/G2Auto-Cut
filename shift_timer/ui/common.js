// Общее для обоих окон: настройки и «день» от Python, тема, тик раз в 250 мс.
// Отработанное время считает Python (стоит на блокировке экрана); тут — только показ с плавным ходом секунд.
const App = { s: null, day: null, at: 0, onChange: null };
const $ = id => document.getElementById(id);
const setText = (el, t) => { if (el && el.textContent !== t) el.textContent = t; };

function applyTheme() {
    const t = App.s && App.s.theme;
    if (t === 'dark' || t === 'light') document.documentElement.dataset.theme = t;
    else delete document.documentElement.dataset.theme;
}
async function poll() {
    try { App.day = await pywebview.api.get_day(); App.at = performance.now(); } catch (e) { /* Python занят — возьмём на следующем тике */ }
}
// Python вызывает это при любой смене настроек — сразу в обоих окнах.
window.applySettings = s => { App.s = s; applyTheme(); poll().then(() => App.onChange && App.onChange()); };

function boot(onReady) {
    const go = async () => {
        App.s = await pywebview.api.get_settings();
        applyTheme();
        await poll();
        onReady();
        setInterval(poll, 1000);
        setInterval(() => App.onChange && App.onChange(), 250);
    };
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_settings) go();
    else window.addEventListener('pywebviewready', go);
}
const save = patch => pywebview.api.save_settings(patch);

function liveWorked() {
    const d = App.day;
    if (!d) return 0;
    return d.worked_s + (d.locked ? 0 : Math.min((performance.now() - App.at) / 1000, 3));    // между опросами секунды идут плавно
}
// Что показать — одно и то же в главном окне и в мини.
function view() {
    const d = App.day, s = App.s;
    if (!d || !s) return null;
    return { d, c: Shift.calc(liveWorked(), d.norm_s, Date.now(), d.locked, s.seconds) };
}
