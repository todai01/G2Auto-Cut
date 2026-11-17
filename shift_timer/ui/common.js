// Общее для обоих окон: настройки и «день» от Python, тема, тик раз в 250 мс.
// Отработанное время считает Python (стоит на блокировке экрана); тут — только показ с плавным ходом секунд.
const App = { s: null, day: null, at: 0, onChange: null };
const $ = id => document.getElementById(id);
const setText = (el, t) => { if (el && el.textContent !== t) el.textContent = t; };

// Окно можно растянуть: кольцо на главном экране растёт вместе с высотой (до ×1,5).
function fitZoom() { document.documentElement.style.setProperty('--z', String(Math.max(1, Math.min(1.5, window.innerHeight / 700)).toFixed(2))); }
window.addEventListener('resize', fitZoom); fitZoom();
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
    if (d.locked || (d.lunch && d.lunch.on)) return d.worked_s;                               // на блокировке и на обеде работа стоит
    return d.worked_s + Math.min((performance.now() - App.at) / 1000, 3);                    // между опросами секунды идут плавно
}
// Обед идёт по настенным часам (и при блокировке): сколько прошло с его начала.
function liveLunch() {
    const L = App.day && App.day.lunch;
    if (!L) return 0;
    return L.elapsed_s + (L.on ? Math.min((performance.now() - App.at) / 1000, 3) : 0);
}
// Что показать — одно и то же в главном окне и в мини.
function view() {
    const d = App.day, s = App.s;
    if (!d || !s) return null;
    const L = d.lunch || { on: false, len_s: 3600, plan_s: 0 };
    const el = liveLunch(), left = L.on ? Math.max(0, L.len_s - el) : L.plan_s;          // обед ещё впереди → день = норма + обед
    const c = Shift.calc(liveWorked(), d.norm_s, Date.now(), d.locked && !L.on, s.seconds, left);
    const day = Shift.day(d.arrival, d.norm_s, L.len_s, Date.now(), s.seconds);          // таймер ухода: приход + норма + обед, от блокировок не зависит
    return { d, c, day, L, lunch: L.on ? Shift.lunch(el, L.len_s, s.seconds) : null };
}
