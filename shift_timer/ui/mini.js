// Уведомление (каждый ровный час до нормы, перерыв) — плашка поверх мини-окна на 9 секунд; клик — закрыть.
const ICONS = {
    hour: '<path d="M6 17h12l-1.5-2V11a4.5 4.5 0 0 0-9 0v4L6 17z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    break: '<path d="M5 9h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9z"/><path d="M16 10h1.5a2 2 0 0 1 0 4H16M8 4v2M12 4v2"/>',
    lunch: '<path d="M5 9h11v5a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9z"/><path d="M16 10h1.5a2 2 0 0 1 0 4H16M8 4v2M12 4v2"/>',
    done: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12.5l2.5 2.5 4.5-5"/>',
};
// ---- задачи: развернуть / свернуть мини-окно ----
let TK = null, tkOpen = false, tkTimer = null, tkH = 0;
const esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const CK = '<svg viewBox="0 0 24 24"><path d="M6.5 12.5l3.5 3.5 7.5-8"/></svg>';
function fitTasks() {
    const h = tkOpen ? Shift.tasksHeight(TK ? TK.total : 0) : 100;
    if (h !== tkH) { tkH = h; pywebview.api.mini_resize(h); }
}
function renderTasks() {
    if (!TK) return;
    const ts = TK.tasks.slice().sort((a, b) => a.done - b.done);                       // невыполненные выше
    $('tkList').innerHTML = ts.length ? ts.map(t => `<button class="tk-row${t.done ? ' done' : ''}" data-id="${t.id}" title="${esc(t.text)}"><i class="ck">${t.done ? CK : ''}</i><span>${esc(t.text)}</span></button>`).join('')
        : '<div class="tk-empty">Задач пока нет — добавьте ниже</div>';
    setText($('mTaskN'), TK.total ? `${TK.done}/${TK.total}` : '');
    fitTasks();
}
async function loadTasks() { try { TK = await pywebview.api.tasks_get(); renderTasks(); } catch (e) { /* повторим через 3 с */ } }
function setTasksOpen(on, persist) {
    tkOpen = on; clearInterval(tkTimer);
    $('b').classList.toggle('exp', on);
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
    const { d, c, lunch } = v, s = App.s;
    if (d.notice && d.notice.id !== shownId) showNotice(d.notice);
    const phase = lunch ? 'lunch' : c.phase;
    $('b').className = 'mini ' + phase + (c.soon ? ' soon' : '') + (tkOpen ? ' exp' : '');   // «exp» (задачи развёрнуты) не теряем при каждой перерисовке
    if (lunch) {
        setText($('cap'), lunch.over ? 'обед закончился' : 'обед'); setText($('t'), Shift.clock(lunch.remain, s.seconds));
        $('t').classList.remove('muted'); $('fill').style.width = (lunch.progress * 100).toFixed(2) + '%';
        setText($('w'), `отработано ${Shift.clock(c.worked, s.seconds)}`);
        if (!tkOpen && d.tasks) setText($('mTaskN'), d.tasks.total ? `${d.tasks.done}/${d.tasks.total}` : '');
        return;
    }
    if (c.phase === 'done') { setText($('cap'), 'норма выполнена'); setText($('t'), '+' + Shift.clock(c.over, s.seconds)); }
    else { setText($('cap'), c.phase === 'paused' ? 'пауза — экран заблокирован' : 'осталось'); setText($('t'), Shift.clock(c.remain, s.seconds)); }
    $('t').classList.toggle('muted', c.phase === 'paused');
    $('fill').style.width = (c.progress * 100).toFixed(2) + '%';
    setText($('w'), `отработано ${Shift.clock(c.worked, s.seconds)}`);
    if (!tkOpen && d.tasks) setText($('mTaskN'), d.tasks.total ? `${d.tasks.done}/${d.tasks.total}` : '');
}
boot(() => {
    App.onChange = render;
    $('mOpen').onclick = () => pywebview.api.open_main();
    $('mLunch').onclick = () => pywebview.api.lunch_toggle().then(poll);
    $('mClose').onclick = () => save({ mini_visible: false });
    $('mTasks').onclick = () => setTasksOpen(!tkOpen, true);
    $('tkList').onclick = async e => { const r = e.target.closest('.tk-row'); if (r) { TK = await pywebview.api.task_toggle(+r.dataset.id); renderTasks(); } };
    $('tkForm').onsubmit = async e => { e.preventDefault(); const v = $('tkIn').value.trim(); if (!v) return; $('tkIn').value = ''; TK = await pywebview.api.task_add(v); renderTasks(); $('tkList').scrollTop = 1e6; };
    if (App.s.mini_tasks) setTasksOpen(true, false);                                   // как оставили в прошлый раз
    $('nb').onclick = hideNotice;
    $('nSkip').onclick = e => { e.stopPropagation(); hideNotice(); };
    $('nOff').onclick = e => { e.stopPropagation(); pywebview.api.skip_break(true); hideNotice(); };
    render();
});
