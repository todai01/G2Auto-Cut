// Уведомление (каждый ровный час до нормы, перерыв) — плашка поверх мини-окна на 9 секунд; клик — закрыть.
const ICONS = {
    hour: '<path d="M6 17h12l-1.5-2V11a4.5 4.5 0 0 0-9 0v4L6 17z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    break: '<path d="M5 9h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9z"/><path d="M16 10h1.5a2 2 0 0 1 0 4H16M8 4v2M12 4v2"/>',
    lunch: '<path d="M5 9h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9z"/><path d="M16 10h1.5a2 2 0 0 1 0 4H16M8 4v2M12 4v2"/>',
    done: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
    update: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v7M8.8 11.8l3.2 3.2 3.2-3.2"/>',
};
// ---- задачи: развернуть / свернуть мини-окно ----
let TK = null, TKAT = 0, tkOpen = false, tkTimer = null, tkH = 0, tkWide = false;
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const CK = '<svg viewBox="0 0 24 24"><path d="M6.5 12.5l3.5 3.5 7.5-8"/></svg>';
function fitTasks() {
    const h = tkOpen ? Shift.tasksHeight(TK ? TK.tasks.map(t => t.text) : []) : 100;
    if (h !== tkH || tkOpen !== tkWide) { tkH = h; tkWide = tkOpen; pywebview.api.mini_resize(h, tkOpen); }     // с задачами окно шире — видно текст
}
function renderTasks() {
    if (!TK) return;
    const ts = TK.tasks;                                                               // невыполненные выше (порядок от сервера)
    $('tkList').innerHTML = ts.length ? ts.map(t => `<button class="tk-row${t.done ? ' done' : ''}" data-id="${t.id}" title="${esc(t.text)}"><i class="ck">${t.done ? CK : ''}</i><span>${esc(t.text)}</span><b class="tm num" data-id="${t.id}">${Shift.dur(taskSec(t))}</b></button>`).join('')
        : '<div class="tk-empty">Задач пока нет — добавьте ниже</div>';
    setText($('mTaskN'), TK.total ? `${TK.done}/${TK.total}` : '');
    fitTasks();
}
const taskSec = t => t.elapsed_s + (t.running ? (performance.now() - TKAT) / 1000 : 0);
function tickTasks() {                                                                 // секундомеры идут каждую секунду, список — раз в 3 с
    if (!TK || !tkOpen) return;
    document.querySelectorAll('#tkList .tm').forEach(el => { const t = TK.tasks.find(x => x.id === +el.dataset.id); if (t) setText(el, Shift.dur(taskSec(t))); });
}
function setTasks(v) { if (v && v.tasks) { TK = v; TKAT = performance.now(); renderTasks(); } }
async function loadTasks() { try { setTasks(await pywebview.api.tasks_get()); } catch (e) { /* повторим через 3 с */ } }
function setTasksOpen(on, persist) {
    tkOpen = on; clearInterval(tkTimer);
    $('b').classList.toggle('exp', on);
    $('mTasks').title = on ? 'Скрыть задачи (Esc)' : 'Задачи на сегодня';
    if (on) { loadTasks(); tkTimer = setInterval(loadTasks, 3000); } else fitTasks();
    if (persist) save({ mini_tasks: on });
}

let shownId = 0, noticeTimer = null;
function showNotice(n) {
    shownId = n.id;
    $('nb').className = 'nb ' + n.kind;
    $('nIcon').innerHTML = ICONS[n.kind] || ICONS.hour;
    setText($('nText'), n.text);
    $('nAct').style.display = n.kind === 'break' ? '' : 'none';
    requestAnimationFrame(() => $('nb').classList.add('on'));
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(hideNotice, 9000);
}
function hideNotice() { $('nb').classList.remove('on'); }

function render() {
    const v = view();
    if (!v) { setText($('t'), '--:--'); return; }
    const { d, c, day, L, lunch } = v, s = App.s;
    if (d.notice && d.notice.id !== shownId) showNotice(d.notice);
    // Главный таймер — до ухода (приход + норма + обед), он не стоит ни на блокировке, ни на обеде; стоит только «отработано».
    const locked = d.locked && !L.on, paused = d.locked || L.on;
    const done = !!day && day.phase === 'done';
    const phase = lunch ? 'lunch' : done ? 'done' : 'work';
    $('b').className = 'mini ' + phase + (day && day.soon && !lunch ? ' soon' : '') + (tkOpen ? ' exp' : '');   // «exp» (задачи развёрнуты) не теряем при каждой перерисовке
    $('w').classList.toggle('paused', paused);
    setText($('w'), `отработано ${Shift.clock(c.worked, s.seconds)}`);
    if (!tkOpen && d.tasks) setText($('mTaskN'), d.tasks.total ? `${d.tasks.done}/${d.tasks.total}` : '');
    $('t').classList.remove('muted');
    if (lunch) {
        setText($('cap'), lunch.over ? 'обед закончился' : 'обед'); setText($('t'), Shift.clock(lunch.remain, s.seconds));
        $('fill').style.width = (lunch.progress * 100).toFixed(2) + '%';
    } else if (!day) {
        setText($('cap'), 'до ухода'); setText($('t'), '--:--'); $('fill').style.width = '0%';
    } else if (done) {
        setText($('cap'), 'время ухода'); setText($('t'), '+' + Shift.clock(day.over, s.seconds)); $('fill').style.width = '100%';
    } else {
        setText($('cap'), locked ? 'до ухода · блок' : 'до ухода'); setText($('t'), Shift.clock(day.remain, s.seconds));
        $('fill').style.width = (day.progress * 100).toFixed(2) + '%';
    }
}
boot(() => {
    App.onChange = () => { render(); tickTasks(); };
    $('mOpen').onclick = () => pywebview.api.toggle_main();
    // Клик по любому месту мини-окна (кроме кнопок и полей) открывает главное окно, повторный — скрывает его. Перетаскивание окна не считается кликом.
    let down = null, moved = false, lastToggle = 0;
    const SKIP = 'button, input, textarea, a, form, .tk-row, .nb';
    document.addEventListener('mousedown', e => { down = { x: e.screenX, y: e.screenY, wx: window.screenX, wy: window.screenY }; moved = false; });
    document.addEventListener('mousemove', e => {
        if (down && (Math.hypot(e.screenX - down.x, e.screenY - down.y) > 4 || Math.abs(window.screenX - down.wx) > 3 || Math.abs(window.screenY - down.wy) > 3)) moved = true;
    });
    const maybeToggle = e => {
        const d = down; down = null;
        if (!d || moved || e.button > 0 || e.target.closest(SKIP) || Date.now() - lastToggle < 400) return;
        if (Math.abs(window.screenX - d.wx) > 3 || Math.abs(window.screenY - d.wy) > 3) return;     // окно двигали
        lastToggle = Date.now();
        pywebview.api.toggle_main();
    };
    document.addEventListener('mouseup', maybeToggle);
    document.addEventListener('click', e => { if (Date.now() - lastToggle >= 400 && !moved) { down = down || { x: e.screenX, y: e.screenY, wx: window.screenX, wy: window.screenY }; maybeToggle(e); } });
    $('mLunch').onclick = () => pywebview.api.lunch_toggle().then(poll);
    $('mClose').onclick = () => save({ mini_visible: false });
    $('mTasks').onclick = () => setTasksOpen(!tkOpen, true);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && tkOpen) { e.preventDefault(); document.activeElement && document.activeElement.blur(); setTasksOpen(false, true); } });
    $('tkList').onclick = async e => { const r = e.target.closest('.tk-row'); if (r) { setTasks(await pywebview.api.task_toggle(+r.dataset.id)); } };
    $('tkForm').onsubmit = async e => { e.preventDefault(); const v = $('tkIn').value.trim(); if (!v) return; $('tkIn').value = ''; setTasks(await pywebview.api.task_add(v)); $('tkList').scrollTop = 1e6; };
    if (App.s.mini_tasks) setTasksOpen(true, false);                                   // как оставили в прошлый раз
    $('nb').onclick = hideNotice;
    $('nSkip').onclick = e => { e.stopPropagation(); hideNotice(); };
    $('nOff').onclick = e => { e.stopPropagation(); pywebview.api.skip_break(true); hideNotice(); };
    render();
});
