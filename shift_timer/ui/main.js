const C = 2 * Math.PI * 104;
let TRAY = false;
const CHIP = { work: 'Идёт учёт времени', paused: 'Пауза — экран заблокирован', done: 'Норма выполнена', lunch: 'Обед' };

function render() {
    const v = view();
    if (!v) { setText($('big'), '--:--'); return; }
    const { d, c, L, lunch } = v, s = App.s;
    const phase = lunch ? 'lunch' : c.phase;
    $('chip').className = 'chip ' + phase;
    setText($('chipT'), CHIP[phase]);
    const big = $('big');
    big.className = 'big' + (s.seconds || phase === 'done' ? ' ss' : ' s') + (phase === 'paused' ? ' muted' : '');
    $('ring').className = 'ringbox ' + (c.soon && phase === 'work' ? 'soon ' : '') + phase;

    if (lunch) {
        setText($('cap'), 'Обед'); setText(big, Shift.clock(lunch.remain, s.seconds));
        setText($('sub'), lunch.over ? 'обед закончился' : 'работа на паузе');
    } else if (c.phase === 'done') {
        setText($('cap'), 'Норма выполнена'); setText(big, '+' + Shift.clock(c.over, s.seconds)); setText($('sub'), 'сверх нормы');
    } else {
        setText($('cap'), 'Осталось'); setText(big, Shift.clock(c.remain, s.seconds));
        setText($('sub'), c.phase === 'paused' ? 'время стоит' : `закончите около ${Shift.hm(c.finish)}`);
    }
    setText($('pct'), lunch ? `${Math.floor(lunch.progress * 100)}% обеда` : `${Math.floor(c.progress * 100)}% нормы`);
    $('fill').style.strokeDashoffset = String(C * (1 - (lunch ? lunch.progress : c.progress)));

    setText($('tWorked'), Shift.clock(c.worked, s.seconds));
    setText($('tArr'), Shift.hmStr(d.arrival));
    setText($('rNorm'), `${Shift.hmSec(d.norm_s)} + ${Shift.hmSec(L.len_s)} ч`);
    setText($('rFinish'), c.phase === 'done' ? 'уже можно' : c.finish ? Shift.hm(c.finish) : '—');
    setText($('rBreak'), d.events_n ? `${Shift.words(d.break_s, false) || '0 мин'} · ${d.events_n}×` : 'нет');
    setText($('bMini'), s.mini_visible ? 'Скрыть мини' : 'Мини-окно');
    setText($('bLunch'), L.on ? 'Закончить обед' : 'Обед');
    $('bLunch').classList.toggle('on', L.on);
    syncSettings();
}

function setSwitch(id, on) { $(id).classList.toggle('on', !!on); $(id).setAttribute('aria-checked', String(!!on)); }
function syncSettings() {
    const s = App.s;
    if (document.activeElement !== $('iNorm') && $('iNorm').value !== s.norm) $('iNorm').value = s.norm;   // не мешаем вводу
    setSwitch('swSec', s.seconds); setSwitch('swMini', s.mini_visible); setSwitch('swTop', s.mini_on_top); setSwitch('swAuto', s.autostart);
    document.querySelectorAll('#segTheme button').forEach(b => b.classList.toggle('on', b.dataset.t === s.theme));
    document.querySelectorAll('#segLunch button').forEach(b => b.classList.toggle('on', +b.dataset.m === s.lunch_min));
    setSwitch('swSound', s.sound); setSwitch('swHours', s.notify_hours); setSwitch('swBreak', s.notify_break);
    document.querySelectorAll('#segVol button').forEach(b => { b.classList.toggle('on', b.dataset.v === s.volume); b.disabled = !s.sound; });
    document.querySelectorAll('#segBreak button').forEach(b => { b.classList.toggle('on', +b.dataset.m === s.break_min); b.disabled = !s.notify_break; });
}

// ---------- журнал ----------
let JR = null, jrTimer = null;
const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
async function loadJournal() {
    try { JR = await pywebview.api.get_history(); } catch (e) { return; }
    const m = JR.month, now = new Date();
    setText($('jrMonth'), MONTHS[now.getMonth()]);
    $('jrSum').innerHTML = `<div class="row"><span class="k">Отработано за месяц</span><span class="v">${Shift.words(m.worked_s, false) || '0 мин'}</span></div>`
        + `<div class="row"><span class="k">Норма (${m.days} дн.)</span><span class="v">${Shift.hmSec(m.norm_s)} ч · <b class="${m.delta_s < 0 ? 'neg' : 'pos'}">${Shift.signed(m.delta_s)}</b></span></div>`;
    $('jrList').innerHTML = JR.rows.length ? JR.rows.map(r => {
        const dd = r.date.slice(8) + '.' + r.date.slice(5, 7);
        return `<button class="jr-row${r.today ? ' today' : ''}" data-d="${r.date}"><span><b>${dd}</b> <i>${r.weekday}</i></span>`
            + `<span class="num">${Shift.hmStr(r.arrival)}</span><span class="num">${r.today ? 'идёт' : Shift.hmStr(r.leave)}</span>`
            + `<span class="num"><b>${Shift.hmSec(r.worked_s)}</b></span>`
            + `<span class="num ${r.today ? 'dim' : r.delta_s < 0 ? 'neg' : 'pos'}">${r.today ? '' : Shift.signed(r.delta_s)}</span></button>`;
    }).join('') : '<div class="empty">Дней пока нет — запись начнётся сама.</div>';
}
function startJournalTimer() { clearInterval(jrTimer); loadJournal(); jrTimer = setInterval(loadJournal, 5000); }

// ---------- диалоги ----------
let editing = null;
function evText(row) {                                   // «12:10 → 12:55 · 45 мин» (дата — если разблокировали в другой день)
    const t = iso => iso ? (iso.slice(0, 10) === row.date ? iso.slice(11, 16) : iso.slice(8, 10) + '.' + iso.slice(5, 7) + ' ' + iso.slice(11, 16)) : 'сейчас';
    return (row.events || []).map(e => `<div class="ev-r"><span>${e.kind === 'sleep' ? 'пауза' : e.kind === 'lunch' ? 'обед' : 'блок'}</span><b class="num">${t(e.lock)} → ${t(e.unlock)}</b>`
        + `<span class="num dim">${Shift.words(e.dur_s, false) || '< 1 мин'}</span></div>`).join('');
}
function openDlg(id) { $('dlgBack').classList.add('on'); $('dlgEdit').hidden = id !== 'dlgEdit'; $('dlgClose').hidden = id !== 'dlgClose'; }
function closeDlg() { $('dlgBack').classList.remove('on'); }
function openEdit(row) {
    editing = row ? row.date : null;
    const today = row && row.today;
    $('dTitle').textContent = today ? 'Сегодня: приход и отработано' : row ? 'Исправить день' : 'Добавить день';
    $('dDate').value = row ? row.date : new Date().toISOString().slice(0, 10);
    $('dDate').disabled = !!row;
    $('dArr').value = row ? Shift.hmStr(row.arrival) : '09:00';
    $('dLeave').value = row ? Shift.hmStr(row.leave) : '18:00';
    $('dLeave').disabled = !!today;
    $('dWork').value = row ? Shift.hmSec(row.worked_s).padStart(5, '0') : '08:00';
    $('dHint').textContent = '';
    $('dHint').classList.remove('err');
    $('dDel').style.display = row && !today ? '' : 'none';
    $('dSuggest').hidden = !today;
    if (today) $('dHint').textContent = 'Укажите, во сколько пришли и сколько уже отработано, — дальше время пойдёт само. Уход за сегодня обновляется сам.';
    const ev = row ? evText(row) : '';
    $('dEvents').innerHTML = ev; $('dEvents').style.display = $('dEvH').style.display = ev ? '' : 'none';
    openDlg('dlgEdit');
}
// «Приход» / «Отработано» на главном экране — сразу правка сегодняшнего дня (приложение могли открыть позже, чем вы пришли).
async function editToday() {
    let row = null;
    try { row = ((await pywebview.api.get_history()).rows || []).find(r => r.today); } catch (e) { /* нет журнала — правим по данным дня */ }
    const d = App.day;
    openEdit(row || { date: d.date, arrival: d.arrival || new Date().toTimeString().slice(0, 8), leave: d.leave, worked_s: d.worked_s, today: true, events: [] });
}
async function suggest() {
    const sec = await pywebview.api.suggest_worked($('dArr').value);
    if (sec === null || sec === undefined) { $('dHint').textContent = 'Приход не может быть позже, чем сейчас.'; $('dHint').classList.add('err'); return; }
    $('dWork').value = Shift.hmSec(sec).padStart(5, '0'); $('dHint').classList.remove('err');
    $('dHint').textContent = 'Вычла блокировки и паузы. Если вы отходили без блокировки — уменьшите время.';
}
async function saveEdit() {
    const r = await pywebview.api.edit_day($('dDate').value, $('dArr').value, $('dLeave').value, $('dWork').value);
    if (r && r.error) { $('dHint').textContent = r.error; $('dHint').classList.add('err'); return; }
    $('dHint').classList.remove('err'); closeDlg(); await loadJournal(); await poll(); render();
}

boot(() => {
    App.onChange = render;
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
        document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + t.dataset.v));
        if (t.dataset.v === 'jr') startJournalTimer(); else clearInterval(jrTimer);
    });
    $('bMin').onclick = () => pywebview.api.minimize();
    pywebview.api.can_tray().then(v => {
        TRAY = !!v;
        $('cHint').textContent = TRAY ? 'Чтобы учёт шёл, уберите окно в фон — значок останется у часов (в трее). Если закрыть совсем, время считаться не будет.'
                                      : 'Пока она закрыта, время не считается. Чтобы учёт шёл, просто сверните окно.';
        $('cMin').textContent = TRAY ? 'В фон' : 'Свернуть';
    });
    $('bX').onclick = () => openDlg('dlgClose');
    $('cMin').onclick = () => { closeDlg(); TRAY ? pywebview.api.hide_main() : pywebview.api.minimize(); };
    $('cQuit').onclick = () => pywebview.api.close_app();
    $('bMini').onclick = () => save({ mini_visible: !App.s.mini_visible });
    $('bLunch').onclick = () => pywebview.api.lunch_toggle().then(poll);
    document.querySelectorAll('#segLunch button').forEach(b => b.onclick = () => save({ lunch_min: +b.dataset.m }));
    $('swSec').onclick = () => save({ seconds: !App.s.seconds });
    $('swMini').onclick = () => save({ mini_visible: !App.s.mini_visible });
    $('swTop').onclick = () => save({ mini_on_top: !App.s.mini_on_top });
    $('swSound').onclick = () => save({ sound: !App.s.sound });
    document.querySelectorAll('#segVol button').forEach(b => b.onclick = () => save({ volume: b.dataset.v }));
    $('swHours').onclick = () => save({ notify_hours: !App.s.notify_hours });
    $('swBreak').onclick = () => save({ notify_break: !App.s.notify_break });
    document.querySelectorAll('#segBreak button').forEach(b => b.onclick = () => save({ break_min: +b.dataset.m }));
    $('swAuto').onclick = () => save({ autostart: !App.s.autostart });
    document.querySelectorAll('#segTheme button').forEach(b => b.onclick = () => save({ theme: b.dataset.t }));
    $('iNorm').onchange = e => e.target.value && save({ norm: e.target.value });
    $('jrAdd').onclick = () => openEdit(null);
    $('jrList').onclick = e => { const b = e.target.closest('.jr-row'); if (b && JR) openEdit(JR.rows.find(r => r.date === b.dataset.d)); };
    $('jrXls').onclick = async () => {
        const r = await pywebview.api.open_table();
        setText($('jrNote'), r.error ? r.error : 'Таблица обновлена и открыта: ' + r.path);
    };
    $('tileArr').onclick = $('tileWorked').onclick = editToday;
    $('dSuggest').onclick = suggest;
    $('dCancel').onclick = closeDlg;
    $('dSave').onclick = saveEdit;
    $('dDel').onclick = async () => { await pywebview.api.delete_day(editing); closeDlg(); await loadJournal(); await poll(); render(); };
    $('dlgBack').onclick = e => { if (e.target === $('dlgBack')) closeDlg(); };
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDlg(); });
    render();
});
