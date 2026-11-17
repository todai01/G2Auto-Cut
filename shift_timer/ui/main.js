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

// ---------- задачи ----------
let TKM = null, TKAT = 0, tkMainTimer = null, tdId = null;
const escT = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const CKS = '<svg viewBox="0 0 24 24"><path d="M6.5 12.5l3.5 3.5 7.5-8"/></svg>';
const taskById = id => TKM && TKM.tasks.find(t => t.id === id);
const taskSec = t => t.elapsed_s + (t.running ? (performance.now() - TKAT) / 1000 : 0);
const waitSec = t => t.waiting ? t.waiting.elapsed_s + (performance.now() - TKAT) / 1000 : 0;
const waitText = t => `жду ${escT(t.waiting.who || 'ответа')} · ${Shift.dur(waitSec(t))}`;
function applyTasks(v) {
    if (!v || !v.tasks) return;
    TKM = v; TKAT = performance.now();
    renderTasksMain();
    if (tdId !== null && !taskById(tdId)) closeDlg();                                      // задачу удалили / она скрылась
}
function renderTasksMain() {
    if (!TKM) return;
    const ts = TKM.tasks;
    setText($('tkCnt'), TKM.total ? `${TKM.done} из ${TKM.total}` : '');
    $('tkBar').style.width = (TKM.total ? TKM.done / TKM.total * 100 : 0) + '%';
    const now = new Date();
    $('tkMain').innerHTML = ts.length ? ts.map(t => {
        const sn = t.subs.length, sd = t.subs.filter(s => s.done).length;
        const meta = [`создана ${Shift.when(t.created, now)}`, t.done ? `выполнена ${Shift.when(t.finished, now)}` : '', sn ? `подзадачи ${sd}/${sn}` : '',
                      t.files.length ? `файлов ${t.files.length}` : '', t.comment ? 'есть комментарий' : ''].filter(Boolean).join(' · ');
        const tg = t.tags.length ? `<span class="tk2-g">${t.tags.map(g => `<em>${escT(g)}</em>`).join('')}</span>` : '';
        const wt = t.waiting ? `<span class="tw" data-id="${t.id}">${waitText(t)}</span>` : '';
        return `<div class="tk2${t.done ? ' done' : ''}" data-id="${t.id}">`
            + `<button class="ck2" data-act="t" title="${t.done ? 'Вернуть в работу' : 'Выполнено'}">${t.done ? CKS : ''}</button>`
            + `<div class="tk2-b" data-act="o"><span class="tk2-t">${escT(t.text)}</span><span class="tk2-m">${escT(meta)}</span>${tg}${wt}</div>`
            + `<b class="tm num" data-id="${t.id}">${Shift.dur(taskSec(t))}</b><button class="tk2-x" data-act="d" title="Удалить">×</button></div>`;
    }).join('') : '<div class="empty">Пока пусто. Запишите задачу — секундомер пойдёт сам.</div>';
    tickTasks();
}
// секундомеры: сервер присылает «сколько прошло», секунды между опросами идут здесь
function tickTasks() {
    if (!TKM) return;
    document.querySelectorAll('.tk2 .tm').forEach(el => { const t = taskById(+el.dataset.id); if (t) setText(el, Shift.dur(taskSec(t))); });
    document.querySelectorAll('.tk2 .tw').forEach(el => { const t = taskById(+el.dataset.id); if (t && t.waiting) el.innerHTML = waitText(t); });
    const t = tdId !== null && taskById(tdId);
    if (t) {
        setText($('tdTimer'), Shift.dur(taskSec(t)));
        const w = $('tdWaitT'); if (w && t.waiting) setText(w, Shift.dur(waitSec(t)));
    }
}
async function loadTasksMain() { try { applyTasks(await pywebview.api.tasks_get()); } catch (e) { /* повторим */ } }
function startTasksTimer() { clearInterval(tkMainTimer); loadTasksMain(); tkMainTimer = setInterval(loadTasksMain, 3000); }

// окно задачи: название, времена, комментарий, подзадачи, файлы
const tdLocal = iso => (iso || '').slice(0, 16);
const TAGS = ['Срезка', 'Запись', 'Доработка', 'Ожидание', 'Прослушка и разметка', 'Синтез'];
function renderTdMeta(t) {
    $('tdTags').innerHTML = TAGS.map(g => `<button class="chip-b${t.tags.includes(g) ? ' on' : ''}" data-g="${escT(g)}" type="button">${escT(g)}</button>`).join('');
    const total = t.wait_s ? `<div class="td-note">Всего ждали ответа: ${Shift.dur(t.wait_s + (t.waiting ? (performance.now() - TKAT) / 1000 : 0))}</div>` : '';
    if (t.waiting) $('tdWait').innerHTML = `<div class="tw-on"><span>Жду ответа: <b>${escT(t.waiting.who || '—')}</b></span><b class="tm num" id="tdWaitT">${Shift.dur(waitSec(t))}</b><button class="btn sm" id="tdWaitEnd" type="button">Ответ получен</button></div>${total}`;
    else if (!t.done) $('tdWait').innerHTML = `<div class="tw-off"><input id="tdWho" maxlength="80" placeholder="От кого ждёте ответа (по желанию)" autocomplete="off"><button class="btn sm" id="tdWaitBtn" type="button">Жду ответа</button></div>${total}`;
    else $('tdWait').innerHTML = total;
}
function renderTdLists() {
    const t = taskById(tdId);
    if (!t) return;
    renderTdMeta(t);
    $('tdSubs').innerHTML = t.subs.length ? t.subs.map(s => `<div class="td-row${s.done ? ' done' : ''}" data-id="${s.id}"><button class="ck2 sm" data-a="st">${s.done ? CKS : ''}</button><span>${escT(s.text)}</span><button class="tk2-x on" data-a="sd" title="Удалить">×</button></div>`).join('')
        : '<div class="td-empty">Нет подзадач</div>';
    setText($('tdSubN'), t.subs.length ? `${t.subs.filter(s => s.done).length}/${t.subs.length}` : '');
    $('tdFiles').innerHTML = t.files.length ? t.files.map(f => `<div class="td-row" data-f="${escT(f)}"><button class="td-file" data-a="fo" title="Открыть">${escT(f)}</button><button class="tk2-x on" data-a="fd" title="Убрать">×</button></div>`).join('')
        : '<div class="td-empty">Нет файлов</div>';
    setText($('tdFileN'), t.files.length ? String(t.files.length) : '');
}
function openTask(id) {
    const t = taskById(id);
    if (!t) return;
    tdId = id;
    $('tdText').value = t.text; $('tdComment').value = t.comment;
    $('tdCreated').value = tdLocal(t.created); $('tdStarted').value = tdLocal(t.started); $('tdFinished').value = tdLocal(t.finished);
    $('tdFinRow').style.display = t.done ? '' : 'none';
    $('tdHint').textContent = ''; $('tdHint').classList.remove('err');
    renderTdLists(); tickTasks();
    openDlg('dlgTask'); tdId = id;
}
async function saveTask() {
    const id = tdId, t = taskById(id);
    if (!t) return;
    const r = await pywebview.api.task_times(id, $('tdCreated').value, $('tdStarted').value, $('tdFinished').value);
    if (r && r.error) { $('tdHint').textContent = r.error; $('tdHint').classList.add('err'); return; }
    const txt = $('tdText').value.replace(/\s+/g, ' ').trim();
    if (txt && txt !== t.text) await pywebview.api.task_edit(id, txt);
    await pywebview.api.task_comment(id, $('tdComment').value);
    closeDlg(); loadTasksMain();
}
const MAX_PASTE = 40 * 1024 * 1024;                       // картинку через мост передаём целиком — не больше 40 МБ
const b64 = f => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(',')[1] || ''); r.onerror = no; r.readAsDataURL(f); });
function pasteName(f, i) {                                 // у скриншота имя «image.png» — даём понятное
    if (f.name && !/^image\.\w+$/i.test(f.name)) return f.name;
    const d = new Date(), p = n => String(n).padStart(2, '0'), ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
    return `Снимок ${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}-${p(d.getMinutes())}-${p(d.getSeconds())}${i ? ' ' + (i + 1) : ''}.${ext}`;
}
async function pasteFiles(files, dropped) {
    const id = tdId, skipped = [];
    let added = 0, v = null;
    $('tdHint').classList.remove('err'); $('tdHint').textContent = dropped ? 'Добавляю…' : 'Вставляю…';
    try {
        const paths = files.map(f => f.pywebviewFullPath).filter(Boolean);        // перетащили из Проводника: pywebview знает путь
        if (dropped && paths.length === files.length) v = await pywebview.api.task_attach_paths(id, paths);
        else if (!dropped) v = await pywebview.api.task_paste(id);                 // Ctrl+V: файлы из Проводника — пути берёт Python
        if (v) { added = v.added || 0; skipped.push(...(v.skipped || [])); }
        if (!added && !(dropped && paths.length === files.length)) for (const [i, f] of files.entries()) {              // картинки и прочее без пути — содержимым
            if (f.size > MAX_PASTE) { skipped.push(`${f.name || 'файл'}: больше 40 МБ`); continue; }
            v = await pywebview.api.task_attach_data(id, pasteName(f, i), await b64(f));
            if (v.error) { skipped.push(v.error); continue; }
            added += v.added || 0; skipped.push(...(v.skipped || []));
        }
    } catch (e) { skipped.push('не удалось вставить'); }
    if (v && v.tasks) applyTasks(v);
    if (tdId === id) renderTdLists();
    $('tdHint').classList.toggle('err', !!skipped.length && !added);
    $('tdHint').textContent = (added ? `Добавлено файлов: ${added}. ` : '') + (skipped.length ? 'Не вставлено: ' + skipped.join('; ') : '');
}
async function tdAct(fn) { const v = await fn(); if (v && v.error) { $('tdHint').textContent = v.error; $('tdHint').classList.add('err'); } else { $('tdHint').classList.remove('err'); if (v && v.skipped && v.skipped.length) $('tdHint').textContent = 'Не прикреплено: ' + v.skipped.join('; '); else $('tdHint').textContent = ''; } applyTasks(v); renderTdLists(); }

// ---------- журнал: календарь, сводка, день ----------
let JR = null, jrTimer = null, jrY = 0, jrM = 0, jrKind = 'week', jrSel = null, CAL = null, SUM = null, dayCur = null;
const MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const WD_FULL = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];
const MARK = { vacation: 'Отпуск', sick: 'Больничный', dayoff: 'Выходной' }, MARK_SHORT = { vacation: 'отп', sick: 'бол', dayoff: 'вых' };
const p2 = n => String(n).padStart(2, '0');
const isoOf = d => `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())}`;
const todayIso = () => (App.day && App.day.date) || isoOf(new Date());
function weekOf(iso) {                                    // понедельник и воскресенье недели, в которую попал день
    const d = new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)), mon = new Date(d.getFullYear(), d.getMonth(), d.getDate() - (d.getDay() + 6) % 7);
    return [isoOf(mon), isoOf(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 6))];
}
const hmOr = (v, dash) => v ? Shift.hmStr(v) : (dash || '—');
async function loadJournal() {
    if (!jrY) { const t = todayIso(); jrY = +t.slice(0, 4); jrM = +t.slice(5, 7); jrSel = t; }
    try {
        const iso = jrKind === 'month' ? `${jrY}-${p2(jrM)}-01` : jrSel;
        [CAL, SUM] = await Promise.all([pywebview.api.get_calendar(jrY, jrM), pywebview.api.get_summary(jrKind, iso)]);
    } catch (e) { return; }
    renderJournal();
}
function startJournalTimer() { clearInterval(jrTimer); loadJournal(); jrTimer = setInterval(() => { if (!$('dlgBack').classList.contains('on')) loadJournal(); }, 5000); }
function sumRow(k, v) { return `<div class="row"><span class="k">${k}</span><span class="v">${v}</span></div>`; }
function renderJournal() {
    if (!CAL || !SUM || CAL.error) return;
    setText($('jrMonth'), `${MONTHS[jrM - 1]} ${jrY}`);
    document.querySelectorAll('#segSum button').forEach(b => b.classList.toggle('on', b.dataset.k === jrKind));
    setText($('jrRep'), jrKind === 'week' ? 'Отчёт за неделю (Excel)' : 'Отчёт за месяц (Excel)');
    setText($('sumLab'), SUM.label.replace(/^[^:]+: /, ''));
    const m = SUM, t = m.tasks, marks = [m.vacation ? `отпуск ${m.vacation}` : '', m.sick ? `больничный ${m.sick}` : '', m.dayoff ? `выходной ${m.dayoff}` : ''].filter(Boolean).join(' · ');
    $('jrSum').innerHTML = sumRow('Отработано', `${Shift.hmSec(m.worked_s)} ч`)
        + sumRow('Норма по графику 5/2', `${Shift.hmSec(m.norm_s)} ч · <b class="${m.delta_s < 0 ? 'neg' : 'pos'}">${Shift.signed(m.delta_s)}</b>`)
        + sumRow('Рабочих дней', `${m.workdays_done} из ${m.workdays}${marks ? ' · ' + marks : ''}`)
        + sumRow('Средний приход / уход', `${hmOr(m.avg_arrival)} / ${hmOr(m.avg_leave)}`)
        + sumRow('Задачи', `создано ${t.created} · выполнено ${t.done} · в работе ${t.work}`)
        + (Object.keys(t.by_tag).length ? sumRow('По тегам', Object.entries(t.by_tag).map(([g, v]) => `${escT(g)} ${v.n}`).join(' · ')) : '');
    const today = todayIso(), wk = jrKind === 'week' ? weekOf(jrSel) : null, lead = CAL.days[0].wd;
    let html = '<span></span>'.repeat(lead);
    CAL.days.forEach(d => {
        const cls = ['cal-d', d.today ? 'today' : '', d.wd >= 5 ? 'weekend' : '', d.mark, d.future ? 'future' : '', wk && d.date >= wk[0] && d.date <= wk[1] ? 'inwk' : '',
            d.record && !d.mark ? (d.worked_s >= d.norm_s ? 'ok' : (d.today ? 'prog' : 'low')) : ''].filter(Boolean).join(' ');
        const low = d.tasks_done ? `✓${d.tasks_done}` : '';
        html += `<button class="${cls}" data-d="${d.date}"><b>${+d.date.slice(8)}</b><span class="cw">${d.record ? Shift.hmSec(d.worked_s) : ''}</span><i class="cm">${d.mark ? MARK_SHORT[d.mark] : low}</i></button>`;
    });
    $('calG').innerHTML = html;
}
async function openDay(iso) {
    const info = await pywebview.api.get_day_info(iso);
    if (!info || info.error) return;
    dayCur = info; jrSel = iso;
    const d = new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
    setText($('ddTitle'), `${WD_FULL[(d.getDay() + 6) % 7]}, ${d.getDate()} ${MONTHS_GEN[d.getMonth()]}${info.today ? ' — сегодня' : ''}`);
    $('ddMark').innerHTML = info.mark ? `<span class="mk ${info.mark}">${MARK[info.mark]}</span>` : info.weekend ? '<span class="mk dayoff">Выходной день (сб, вс)</span>' : '';
    $('ddMark').style.display = $('ddMark').innerHTML ? '' : 'none';
    const c = (k, v, cls) => `<div class="dd-c"><span>${k}</span><b class="num ${cls || ''}">${v}</b></div>`;
    $('ddGrid').innerHTML = info.record
        ? c('Приход', hmOr(info.arrival)) + c('Уход', info.today ? 'идёт' : hmOr(info.leave)) + c('Отработано', `${Shift.hmSec(info.worked_s)} ч`) + c('Норма', `${Shift.hmSec(info.norm_s)} ч`)
          + c('Разница', info.future || (info.today && info.worked_s < info.norm_s) ? '—' : Shift.signed(info.delta_s), info.delta_s < 0 ? 'neg' : 'pos')
          + c('Перерывы', Shift.words(info.break_s, false) || '0 мин') + c('Обед', Shift.words(info.lunch_s, false) || '—')
        : `<div class="dd-none">${info.future ? 'День ещё не наступил.' : 'За этот день записей нет.'}${info.norm_s ? ` Норма — ${Shift.hmSec(info.norm_s)} ч.` : ''}</div>`;
    const ev = info.events.map(e => `<div class="ev-r"><span>${e.kind === 'sleep' ? 'пауза' : e.kind === 'lunch' ? 'обед' : 'блок'}</span><b class="num">${e.lock.slice(11, 16)} → ${e.unlock ? e.unlock.slice(11, 16) : 'сейчас'}</b><span class="num dim">${Shift.words(e.dur_s, false) || '< 1 мин'}</span><span></span></div>`).join('');
    $('ddEvents').innerHTML = ev; $('ddEvents').style.display = $('ddEvH').style.display = ev ? '' : 'none';
    $('ddTasks').innerHTML = info.tasks.length ? info.tasks.map(t => `<div class="dd-t"><span class="dd-r ${t.role[0]}">${t.role.join(' · ')}</span><span class="dd-x">${escT(t.text)}${t.tags.length ? ` <em>${t.tags.map(escT).join(', ')}</em>` : ''}</span>`
        + `<b class="num">${t.done && t.role.includes('выполнена') ? 'ушло ' + Shift.dur(t.elapsed_s) : t.waiting_who ? 'жду ' + escT(t.waiting_who) : ''}</b></div>`).join('')
        : '<div class="td-empty">Задач за этот день нет</div>';
    setText($('ddMarkBtn'), info.mark ? 'Изменить отметку…' : 'Отметить…');
    openDlg('dlgDay');
    loadJournal();
}
function openMark(from, to, kind) {
    $('mkFrom').value = from; $('mkTo').value = to || from;
    document.querySelectorAll('#mkKind button').forEach(b => b.classList.toggle('on', b.dataset.k === (kind || 'vacation')));
    $('mkHint').classList.remove('err');
    $('mkHint').textContent = 'Отмеченные дни не считаются недоработкой: норма за них — 0. Суббота и воскресенье и так выходные.';
    openDlg('dlgMark');
}
async function saveMark() {
    const on = document.querySelector('#mkKind button.on'), k = on ? on.dataset.k : 'vacation';
    const r = await pywebview.api.set_mark($('mkFrom').value, $('mkTo').value || $('mkFrom').value, k);
    if (r && r.error) { $('mkHint').textContent = r.error; $('mkHint').classList.add('err'); return; }
    closeDlg(); loadJournal();
}

// ---------- диалоги ----------
let editing = null;
function evText(row) {                                   // «12:10 → 12:55 · 45 мин» (дата — если разблокировали в другой день)
    const t = iso => iso ? (iso.slice(0, 10) === row.date ? iso.slice(11, 16) : iso.slice(8, 10) + '.' + iso.slice(5, 7) + ' ' + iso.slice(11, 16)) : 'сейчас';
    return (row.events || []).map(e => `<div class="ev-r"><span>${e.kind === 'sleep' ? 'пауза' : e.kind === 'lunch' ? 'обед' : 'блок'}</span><b class="num">${t(e.lock)} → ${t(e.unlock)}</b>`
        + `<span class="num dim">${Shift.words(e.dur_s, false) || '< 1 мин'}</span>`
        + (e.unlock ? `<button class="ev-b${e.kind === 'lunch' ? ' on' : ''}" data-i="${e.i}" data-k="${e.kind === 'lunch' ? 'lock' : 'lunch'}" title="${e.kind === 'lunch' ? 'Вернуть: это не обед, а блокировка' : 'Это был обед: забыли нажать «Обед»'}">${e.kind === 'lunch' ? 'не обед' : 'обед'}</button>` : '<span></span>')
        + '</div>').join('');
}
function openDlg(id) { $('dlgBack').classList.add('on'); document.querySelectorAll('#dlgBack .dlg').forEach(d => d.hidden = d.id !== id); tdId = null; }
function closeDlg() { $('dlgBack').classList.remove('on'); tdId = null; }
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

// Сообщаем Python, видно ли окно: клик по мини-окну откроет скрытое и спрячет видимое.
document.addEventListener('visibilitychange', () => { try { pywebview.api.main_visible(document.visibilityState === 'visible'); } catch (e) { /* окно ещё грузится */ } });
boot(() => {
    App.onChange = () => { render(); tickTasks(); };
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
        document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + t.dataset.v));
        if (t.dataset.v === 'jr') startJournalTimer(); else clearInterval(jrTimer);
        if (t.dataset.v === 'tk') startTasksTimer(); else clearInterval(tkMainTimer);
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
    $('jrPrev').onclick = () => { jrM--; if (jrM < 1) { jrM = 12; jrY--; } loadJournal(); };
    $('jrNext').onclick = () => { jrM++; if (jrM > 12) { jrM = 1; jrY++; } loadJournal(); };
    $('jrToday').onclick = () => { const t = todayIso(); jrY = +t.slice(0, 4); jrM = +t.slice(5, 7); jrSel = t; loadJournal(); };
    document.querySelectorAll('#segSum button').forEach(b => b.onclick = () => { jrKind = b.dataset.k; loadJournal(); });
    $('calG').onclick = e => { const b = e.target.closest('.cal-d'); if (b) openDay(b.dataset.d); };
    $('jrMark').onclick = () => openMark(jrSel || todayIso(), jrSel || todayIso(), '');
    $('jrRep').onclick = async () => {
        setText($('jrNote'), 'Готовлю отчёт…');
        const r = await pywebview.api.report_save(jrKind, jrKind === 'month' ? `${jrY}-${p2(jrM)}-01` : jrSel);
        setText($('jrNote'), r.error ? r.error : 'Отчёт сохранён и открыт: ' + r.path);
    };
    $('ddClose').onclick = closeDlg;
    $('ddMarkBtn').onclick = () => dayCur && openMark(dayCur.date, dayCur.date, dayCur.mark);
    $('ddEdit').onclick = async () => {
        if (!dayCur) return;
        if (dayCur.record) openEdit({ date: dayCur.date, arrival: dayCur.arrival, leave: dayCur.leave, worked_s: dayCur.worked_s, today: dayCur.today, events: dayCur.events });
        else { openEdit(null); $('dDate').value = dayCur.date; }
    };
    $('mkKind').onclick = e => { const b = e.target.closest('button'); if (b) document.querySelectorAll('#mkKind button').forEach(x => x.classList.toggle('on', x === b)); };
    $('mkCancel').onclick = closeDlg;
    $('mkSave').onclick = saveMark;
    const bk = t => setText($('bkNote'), t);
    $('bkSave').onclick = async () => {
        const r = await pywebview.api.backup_save();
        if (r.error) bk(r.error); else if (r.ok) bk(`Копия сохранена: ${r.path} (файлов в задачах: ${r.files}, ${Math.max(1, Math.round(r.size / 1024))} КБ).`);
    };
    $('bkRestore').onclick = async () => {
        if (!confirm('Восстановить данные из копии? Текущие журнал, задачи и файлы будут заменены (перед этим они сохранятся отдельным архивом).')) return;
        const r = await pywebview.api.backup_restore();
        if (r.error) { bk(r.error); return; }
        if (!r.ok) return;
        bk(`Восстановлено${r.created ? ' из копии от ' + r.created.replace('T', ' ').slice(0, 16) : ''}. Прежние данные сохранены: ${r.safety}`);
        await poll(); loadJournal(); loadTasksMain();
    };
    $('jrXls').onclick = async () => {
        const r = await pywebview.api.open_table();
        setText($('jrNote'), r.error ? r.error : 'Таблица обновлена и открыта: ' + r.path);
    };
    $('tkForm').onsubmit = async e => { e.preventDefault(); const v = $('tkInput').value.trim(); if (!v) return; $('tkInput').value = ''; applyTasks(await pywebview.api.task_add(v)); };
    $('tkMain').onclick = async e => {
        const row = e.target.closest('.tk2'), act = e.target.closest('[data-act]');
        if (!row || !act) return;
        const id = +row.dataset.id;
        if (act.dataset.act === 't') applyTasks(await pywebview.api.task_toggle(id));
        else if (act.dataset.act === 'd') applyTasks(await pywebview.api.task_delete(id));
        else if (act.dataset.act === 'o') openTask(id);
    };
    $('tkClear').onclick = async () => applyTasks(await pywebview.api.tasks_clear_done());
    $('tdSave').onclick = saveTask;
    $('tdCancel').onclick = async () => { if (tdId !== null) await pywebview.api.task_comment(tdId, $('tdComment').value); closeDlg(); loadTasksMain(); };
    $('tdComment').onchange = () => tdId !== null && pywebview.api.task_comment(tdId, $('tdComment').value);          // комментарий не теряется
    $('tdDel').onclick = async () => { const id = tdId; closeDlg(); applyTasks(await pywebview.api.task_delete(id)); };
    $('tdSubForm').onsubmit = e => { e.preventDefault(); const v = $('tdSubIn').value.trim(); if (!v) return; $('tdSubIn').value = ''; tdAct(() => pywebview.api.sub_add(tdId, v)); };
    $('tdSubs').onclick = e => {
        const b = e.target.closest('[data-a]'), r = e.target.closest('.td-row');
        if (!b || !r) return;
        tdAct(() => b.dataset.a === 'st' ? pywebview.api.sub_toggle(tdId, +r.dataset.id) : pywebview.api.sub_delete(tdId, +r.dataset.id));
    };
    // Ctrl+V с файлами или картинкой в буфере (скриншот, файлы из Проводника) → во вложения; обычный текст вставляется как раньше
    $('dlgTask').addEventListener('paste', e => {
        const cd = e.clipboardData, files = cd ? Array.from(cd.files || []) : [];
        if (!files.length || (cd.getData('text/plain') || '').length || tdId === null) return;
        e.preventDefault();
        pasteFiles(files);
    });
    $('tdTags').onclick = e => {
        const b = e.target.closest('.chip-b'), t = taskById(tdId);
        if (!b || !t) return;
        const on = t.tags.includes(b.dataset.g), tags = on ? t.tags.filter(g => g !== b.dataset.g) : [...t.tags, b.dataset.g];
        tdAct(() => pywebview.api.task_tags(tdId, tags));
    };
    $('tdWait').onclick = e => {
        if (e.target.closest('#tdWaitBtn')) tdAct(() => pywebview.api.task_wait(tdId, $('tdWho').value));
        else if (e.target.closest('#tdWaitEnd')) tdAct(() => pywebview.api.task_wait_end(tdId));
    };
    $('tdWait').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'tdWho') { e.preventDefault(); tdAct(() => pywebview.api.task_wait(tdId, e.target.value)); } });
    $('tdFolder').onclick = async () => { const r = await pywebview.api.task_open_folder(tdId); if (r && r.error) { $('tdHint').textContent = r.error; $('tdHint').classList.add('err'); } };
    // перетаскивание файлов мышью в окно задачи (пути даёт pywebview; нет пути — берём содержимое, как при вставке)
    ['dragover', 'drop'].forEach(n => document.addEventListener(n, e => e.preventDefault()));       // иначе WebView откроет файл вместо окна задачи
    const dz = $('dlgTask');
    dz.addEventListener('dragover', () => $('tdDrop').classList.add('on'));
    dz.addEventListener('dragleave', e => { if (!dz.contains(e.relatedTarget)) $('tdDrop').classList.remove('on'); });
    dz.addEventListener('drop', e => { $('tdDrop').classList.remove('on'); const f = Array.from((e.dataTransfer && e.dataTransfer.files) || []); if (f.length && tdId !== null) pasteFiles(f, true); });
    $('tdAttach').onclick = () => tdAct(() => pywebview.api.task_attach(tdId));
    $('tdFiles').onclick = async e => {
        const b = e.target.closest('[data-a]'), r = e.target.closest('.td-row');
        if (!b || !r) return;
        if (b.dataset.a === 'fo') { const x = await pywebview.api.task_file_open(tdId, r.dataset.f); if (x && x.error) { $('tdHint').textContent = x.error; $('tdHint').classList.add('err'); } }
        else tdAct(() => pywebview.api.task_file_remove(tdId, r.dataset.f));
    };
    $('tileArr').onclick = $('tileWorked').onclick = editToday;
    $('dSuggest').onclick = suggest;
    $('dEvents').onclick = async e => {                      // «обед» на блокировке: забыли нажать кнопку «Обед»
        const bt = e.target.closest('.ev-b');
        if (!bt || !editing) return;
        const r = await pywebview.api.event_kind(editing, +bt.dataset.i, bt.dataset.k);
        if (r && r.error) { $('dHint').textContent = r.error; $('dHint').classList.add('err'); return; }
        $('dHint').classList.remove('err');
        await loadJournal(); await poll();
        const row = JR && JR.rows.find(x => x.date === editing);
        if (row) $('dEvents').innerHTML = evText(row);
        render();
    };
    $('dCancel').onclick = closeDlg;
    $('dSave').onclick = saveEdit;
    $('dDel').onclick = async () => { await pywebview.api.delete_day(editing); closeDlg(); await loadJournal(); await poll(); render(); };
    $('dlgBack').onclick = e => { if (e.target === $('dlgBack')) closeDlg(); };
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDlg(); });
    render();
});
