// Командный режим: вход по учётке, обзор команды и учётки (для администратора). Данные — в сетевой папке (см. team.py).
let TM = null, tmSkip = false, tmDay = null, tmTimer = null, tmStatusTimer = null, EMP = null, emLogin = null, emKind = 'week', accEdit = null, accRole = 'user';
const TM_STATE = { work: ['в работе', 'ok'], lunch: ['обед', 'lunch'], locked: ['блокировка', 'warn'], left: ['ушёл', 'dim'], offline: ['нет связи', 'dim'], absent: ['не пришёл', 'low'],
    weekend: ['выходной', 'dim'], mark: ['', 'mk'], came: ['был', 'ok'], nodata: ['не входил', 'dim'] };
const ROLE_RU = { admin: 'администратор', mentor: 'куратор', user: 'сотрудник' }, ROLE_SHORT = { admin: 'админ', mentor: 'куратор', user: 'сотрудник' };
const MARK_RU = { vacation: 'отпуск', sick: 'больничный', dayoff: 'выходной' };
const err = (id, t) => { const h = $(id); h.textContent = t || ''; h.classList.toggle('err', !!t); };

// ---------- состояние: что показать — вход, форму первого админа, смену пароля или сам GTime ----------
let lastLock = null;
function lockMode(mode) {
    const L = $('lock'); L.hidden = !mode;
    if (mode !== lastLock) { ['lkPass', 'lkNew', 'lkNew2'].forEach(i => $(i).value = ''); lastLock = mode; }
    if (!mode) return;
    const m = { login: ['Вход в GTime', 'Логин и пароль выдаёт администратор.', 'Войти'], setup: ['Первый запуск команды', 'В папке пока нет учёток. Создайте учётку администратора.', 'Создать и войти'],
                change: ['Смените пароль', 'Вы вошли со стартовым паролем. Придумайте свой — от 6 знаков.', 'Сменить и продолжить'],
                offline: ['Сетевая папка недоступна', 'Проверьте подключение к сети. Учёт времени идёт и без неё — данные уйдут в папку позже.', 'Повторить'] }[mode];
    setText($('lkTitle'), m[0]); setText($('lkSub'), m[1]); setText($('lkBtn'), m[2]);
    const show = (id, on) => { $(id).hidden = !on; };
    show('lkLogin', mode === 'login' || mode === 'setup'); show('lkName', mode === 'setup'); show('lkPass', mode === 'login' || mode === 'setup' || mode === 'change');
    show('lkNew', mode === 'change'); show('lkNew2', mode === 'change'); show('lkRemRow', mode === 'login');
    $('lkPass').placeholder = mode === 'change' ? 'Стартовый (текущий) пароль' : mode === 'setup' ? 'Пароль (от 6 знаков)' : 'Пароль';
    $('lkPass').autocomplete = mode === 'login' ? 'current-password' : 'new-password';
    $('lkSkip').hidden = mode === 'change';
    $('lkForm').dataset.mode = mode; err('lkHint', '');
    setTimeout(() => { const f = $(mode === 'change' ? 'lkPass' : mode === 'offline' ? 'lkBtn' : 'lkLogin'); f && f.focus(); }, 50);
}
function applyTeam() {
    const s = TM, user = s && s.user;
    $('tabTeam').hidden = !(user && (user.role === 'admin' || user.role === 'mentor') && !user.must_change);
    $('tmAcc').hidden = !(user && user.role === 'admin');                                 // учётками и обновлениями управляет только администратор-разработчик
    if (!s || !s.enabled) { lockMode(null); }
    else if (user && user.must_change) lockMode('change');
    else if (!s.reachable && !user) lockMode(tmSkip ? null : 'offline');
    else if (s.reachable && s.need_admin && !user) lockMode(tmSkip ? null : 'setup');
    else if (!user) lockMode(tmSkip ? null : 'login');
    else lockMode(null);
    if ($('tabTeam').hidden && document.querySelector('.tab[data-v=team].on')) document.querySelector('.tab[data-v=home]').click();
    window.updRender && window.updRender();
    setText($('tmDir'), s && s.enabled ? s.dir + (s.reachable ? '' : ' — недоступна') : 'не выбрана — GTime работает сам по себе');
    $('tmOff').disabled = !(s && s.enabled);
    $('tmWhoRow').style.display = user ? '' : 'none';
    if (user) setText($('tmWho'), `${user.name} · ${ROLE_RU[user.role] || 'сотрудник'}${s.sync && s.sync.ok === false ? ' · нет связи с папкой' : ''}`);
}
async function teamRefresh() { try { TM = await pywebview.api.team_status(); } catch (e) { return; } applyTeam(); }
window.teamChanged = teamRefresh;

function teamInit() {
    teamRefresh();
    tmStatusTimer = setInterval(() => { if ($('lock').hidden || $('lkForm').dataset.mode === 'offline') teamRefresh(); }, 15000);
    $('lkForm').onsubmit = async e => {
        e.preventDefault();
        const mode = $('lkForm').dataset.mode, A = pywebview.api;
        err('lkHint', '');
        if (mode === 'offline') { await teamRefresh(); if (TM && !TM.reachable) err('lkHint', 'Папка по-прежнему недоступна.'); return; }
        let r;
        if (mode === 'setup') r = await A.team_setup_admin($('lkLogin').value, $('lkName').value, $('lkPass').value);
        else if (mode === 'change') {
            if ($('lkNew').value !== $('lkNew2').value) { err('lkHint', 'Новые пароли не совпадают.'); return; }
            r = await A.team_change_password($('lkPass').value, $('lkNew').value);
        } else r = await A.team_login($('lkLogin').value, $('lkPass').value, $('lkRem').checked);
        if (r.error) { err('lkHint', r.error); return; }
        ['lkPass', 'lkNew', 'lkNew2'].forEach(i => $(i).value = '');
        TM = r; applyTeam(); loadTasksMain && loadTasksMain();
    };
    $('lkSkip').onclick = () => { tmSkip = true; applyTeam(); };
    $('lkDir').onclick = async () => { const r = await pywebview.api.team_pick_dir(); if (r && r.error) err('lkHint', r.error); else if (r && !r.cancelled) { TM = r; applyTeam(); } };
    $('tmPick').onclick = async () => { const r = await pywebview.api.team_pick_dir(); if (r && r.error) setText($('tmSetNote'), r.error); else if (r && !r.cancelled) { tmSkip = false; TM = r; applyTeam(); } };
    $('tmOff').onclick = async () => { if (!confirm('Отключить командный режим? Данные в сетевой папке останутся.')) return; TM = await pywebview.api.team_set_dir(''); tmSkip = false; applyTeam(); };
    $('tmOut').onclick = async () => { TM = await pywebview.api.team_logout(); tmSkip = false; applyTeam(); };
    $('tmPass').onclick = () => { ['psOld', 'psNew', 'psNew2'].forEach(i => $(i).value = ''); err('psHint', ''); openDlg('dlgPass'); $('psOld').focus(); };
    $('psCancel').onclick = closeDlg;
    $('psSave').onclick = async () => {
        if ($('psNew').value !== $('psNew2').value) { err('psHint', 'Новые пароли не совпадают.'); return; }
        const r = await pywebview.api.team_change_password($('psOld').value, $('psNew').value);
        if (r.error) { err('psHint', r.error); return; }
        TM = r; closeDlg(); applyTeam(); setText($('tmSetNote'), 'Пароль изменён.');
    };
    // ---- обзор команды ----
    $('tmPrev').onclick = () => { tmDay = shiftIso(tmDay || todayIso(), -1); loadTeam(); };
    $('tmNext').onclick = () => { tmDay = shiftIso(tmDay || todayIso(), 1); loadTeam(); };
    $('tmToday').onclick = () => { tmDay = null; loadTeam(); };
    $('tmList').onclick = e => { const r = e.target.closest('.tm-row'); if (r && r.dataset.l) openEmp(r.dataset.l); };
    const rep = async k => { setText($('tmNote'), 'Готовлю отчёт…'); const r = await pywebview.api.team_report(k, tmDay || todayIso()); setText($('tmNote'), r.error ? r.error : `Отчёт команды (${r.people} чел.) сохранён и открыт: ${r.path}`); };
    $('tmRepW').onclick = () => rep('week'); $('tmRepM').onclick = () => rep('month');
    $('emClose').onclick = closeDlg;
    $('emSeg').onclick = e => { const b = e.target.closest('button'); if (b) { emKind = b.dataset.k; loadEmp(); } };
    $('tmAcc').onclick = openAcc;
    $('acClose').onclick = () => { closeDlg(); loadTeam(); };
    $('acRole').onclick = e => { const b = e.target.closest('button'); if (b && !accEdit) { accRole = b.dataset.r; document.querySelectorAll('#acRole button').forEach(x => x.classList.toggle('on', x === b)); } };
    $('acNew').onclick = () => accForm(null);
    $('acSave').onclick = saveAcc;
    $('accList').onclick = async e => {
        const b = e.target.closest('[data-a]'), row = e.target.closest('.acc-row');
        if (!b || !row) return;
        const l = row.dataset.l, a = ACC.find(x => x.login === l);
        let r;
        if (b.dataset.a === 'pw') { accForm(a); return; }
        if (b.dataset.a === 'on') r = await pywebview.api.team_account_active(l, !a.active);
        else if (b.dataset.a === 'role') r = await pywebview.api.team_account_role(l, b.dataset.r);
        if (r && r.error) err('acHint', r.error); else if (r) { err('acHint', ''); ACC = r.accounts; renderAcc(); }
    };
}
const shiftIso = (iso, n) => { const d = new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10) + n); return isoOf(d); };
function teamStart() { clearInterval(tmTimer); loadTeam(); tmTimer = setInterval(() => { if (!$('dlgBack').classList.contains('on')) loadTeam(); }, 20000); }
function teamStop() { clearInterval(tmTimer); }

async function loadTeam() {
    const iso = tmDay || todayIso(), r = await pywebview.api.team_overview(iso);
    if (r.error) { setText($('tmNote'), r.error); return; }
    const d = new Date(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
    setText($('tmDate'), (iso === r.today ? 'Сегодня, ' : '') + `${d.getDate()} ${MONTHS_GEN[d.getMonth()]}, ${WD_FULL[(d.getDay() + 6) % 7].toLowerCase()}`);
    $('tmNext').disabled = iso >= r.today;
    $('tmList').innerHTML = r.rows.length ? r.rows.map(u => {
        const [lab, cls] = TM_STATE[u.state] || ['', 'dim'], text = u.state === 'mark' ? (MARK_RU[u.mark] || '') : lab;
        const upd = u.state === 'offline' && u.updated ? ` · ${u.updated.slice(11, 16)}` : '';
        return `<button class="tm-row${u.active ? '' : ' off'}" data-l="${escT(u.login)}"><span class="tm-n"><b>${escT(u.name)}</b><i>${escT(u.login)}${u.role === 'admin' ? ' · админ' : u.role === 'mentor' ? ' · куратор' : ''}${u.active ? '' : ' · отключён'}</i></span>`
            + `<span class="num"><b>${u.arrival ? Shift.hmStr(u.arrival) : '—'}</b></span><span><em class="st ${cls}">${text}${upd}</em></span>`
            + `<span class="num">${u.worked_s ? Shift.hmSec(u.worked_s) : '—'}</span><span class="num dim">${u.tasks_open} · ✓${u.tasks_done}</span></button>`;
    }).join('') : '<div class="empty">Учёток пока нет.</div>';
}

// ---------- карточка сотрудника ----------
async function openEmp(login) { emLogin = login; emKind = 'week'; await loadEmp(true); }
async function loadEmp(open) {
    const r = await pywebview.api.team_user(emLogin, emKind, tmDay || todayIso());
    if (r.error) { setText($('tmNote'), r.error); return; }
    EMP = r;
    document.querySelectorAll('#emSeg button').forEach(b => b.classList.toggle('on', b.dataset.k === emKind));
    setText($('emTitle'), r.name || r.login);
    if (r.nodata) { $('emSum').innerHTML = '<div class="empty">Сотрудник ещё не входил в GTime — данных нет.</div>'; $('emDays').innerHTML = $('emTasks').innerHTML = ''; setText($('emLab'), ''); if (open) openDlg('dlgEmp'); return; }
    const m = r.summary, t = m.tasks, marks = [m.vacation ? `отпуск ${m.vacation}` : '', m.sick ? `больничный ${m.sick}` : '', m.dayoff ? `выходной ${m.dayoff}` : ''].filter(Boolean).join(' · ');
    setText($('emLab'), m.label.replace(/^[^:]+: /, '') + (r.updated ? ` · данные от ${r.updated.slice(8, 10)}.${r.updated.slice(5, 7)} ${r.updated.slice(11, 16)}` : ''));
    $('emSum').innerHTML = sumRow('Отработано', `${Shift.hmSec(m.worked_s)} ч`)
        + sumRow('Норма по графику 5/2', `${Shift.hmSec(m.norm_s)} ч · <b class="${m.delta_s < 0 ? 'neg' : 'pos'}">${Shift.signed(m.delta_s)}</b>`)
        + sumRow('Рабочих дней', `${m.workdays_done} из ${m.workdays}${marks ? ' · ' + marks : ''}`)
        + sumRow('Средний приход / уход', `${hmOr(m.avg_arrival)} / ${hmOr(m.avg_leave)}`)
        + sumRow('Задачи', `создано ${t.created} · выполнено ${t.done} · в работе ${t.work}`)
        + (Object.keys(t.by_tag).length ? sumRow('По тегам', Object.entries(t.by_tag).map(([g, v]) => `${escT(g)} ${v.n} (${Shift.hmSec(v.sec)} ч)`).join(' · ')) : '');
    $('emDays').innerHTML = r.days.filter(d => !d.future).map(d => {
        const ex = d.mark ? MARK_RU[d.mark] : d.weekend && !d.arrival ? 'выходной' : '';
        return `<div class="em-d${d.weekend || d.mark ? ' dim' : ''}"><span>${d.date.slice(8)}.${d.date.slice(5, 7)} <i>${d.weekday}</i></span><span class="num">${d.arrival ? Shift.hmStr(d.arrival) : '—'} – ${d.leave ? Shift.hmStr(d.leave) : (d.arrival ? '…' : '—')}</span>`
            + `<b class="num">${d.worked_s ? Shift.hmSec(d.worked_s) : ''}</b><span class="dim">${ex}</span></div>`;
    }).join('');
    setText($('emTkN'), r.tasks.length ? String(r.tasks.length) : '');
    $('emTasks').innerHTML = r.tasks.length ? r.tasks.map(x => {
        const st = x.done ? 'выполнена' : x.waiting_who ? `жду ${x.waiting_who}` : 'в работе', dur = x.elapsed_s != null ? Shift.dur(x.elapsed_s) : '';
        const body = [`создана ${x.created.slice(8, 10)}.${x.created.slice(5, 7)} ${x.created.slice(11, 16)}`, x.finished ? `выполнена ${x.finished.slice(8, 10)}.${x.finished.slice(5, 7)} ${x.finished.slice(11, 16)}` : '',
                      x.wait_s ? `ждали ответа ${Shift.dur(x.wait_s)}` : '', x.files.length ? `файлы: ${x.files.join(', ')}` : ''].filter(Boolean).map(escT).join(' · ')
            + (x.comment ? `<div class="em-c">${escT(x.comment)}</div>` : '')
            + (x.subs.length ? `<div class="em-s">${x.subs.map(s => `<div class="${s.done ? 'done' : ''}">${s.done ? '✓' : '○'} ${escT(s.text)}</div>`).join('')}</div>` : '');
        return `<details class="em-t${x.done ? ' done' : ''}"><summary><span class="dd-r ${x.done ? 'выполнена' : ''}">${escT(st)}</span><span class="dd-x">${escT(x.text)}${x.tags.length ? ` <em>${x.tags.map(escT).join(', ')}</em>` : ''}</span><b class="num">${dur}</b></summary><div class="em-b">${body}</div></details>`;
    }).join('') : '<div class="td-empty">Задач за период нет</div>';
    if (open) openDlg('dlgEmp');
}

// ---------- учётки ----------
let ACC = [];
function renderAcc() {
    $('accList').innerHTML = ACC.map(a => `<div class="acc-row${a.active ? '' : ' off'}" data-l="${escT(a.login)}"><span class="tm-n"><b>${escT(a.name)}</b><i>${escT(a.login)}${a.must_change ? ' · ждёт смены пароля' : ''}</i></span>`
        + `<span class="mk ${a.role === 'admin' ? 'dayoff' : a.role === 'mentor' ? 'vacation' : ''}">${ROLE_RU[a.role] || 'сотрудник'}</span>`
        + `<span class="acc-b"><button class="btn sm" data-a="pw" title="Задать новый стартовый пароль">Пароль</button>${['user', 'mentor', 'admin'].filter(r => r !== a.role).map(r => `<button class="btn sm" data-a="role" data-r="${r}" title="Сменить роль">→ ${ROLE_SHORT[r]}</button>`).join('')}<button class="btn sm${a.active ? '' : ' primary'}" data-a="on">${a.active ? 'Отключить' : 'Включить'}</button></span></div>`).join('')
        || '<div class="td-empty">Учёток нет</div>';
}
function accForm(a) {
    accEdit = a ? a.login : null;
    setText($('accFormT'), a ? `Новый пароль для ${a.name}` : 'Новая учётка');
    $('acLogin').value = a ? a.login : ''; $('acLogin').disabled = !!a; $('acName').value = a ? a.name : ''; $('acName').hidden = !!a; $('acPass').value = '';
    $('acPass').placeholder = a ? 'Новый стартовый пароль (сотрудник сменит при входе)' : 'Стартовый пароль (сотрудник сменит при входе)';
    $('acRole').style.display = a ? 'none' : ''; $('acNew').hidden = !a; setText($('acSave'), a ? 'Задать пароль' : 'Добавить'); err('acHint', '');
    (a ? $('acPass') : $('acLogin')).focus();
}
async function openAcc() {
    const r = await pywebview.api.team_accounts();
    if (r.error) { setText($('tmNote'), r.error); return; }
    ACC = r.accounts; renderAcc(); accForm(null); openDlg('dlgAcc');
}
async function saveAcc() {
    const A = pywebview.api, r = accEdit ? await A.team_account_reset(accEdit, $('acPass').value) : await A.team_account_create($('acLogin').value, $('acName').value, $('acPass').value, accRole);
    if (r.error) { err('acHint', r.error); return; }
    ACC = r.accounts; renderAcc();
    const who = accEdit || $('acLogin').value.trim();
    accForm(null); err('acHint', ''); setText($('acHint'), `Готово: ${who}. Сообщите сотруднику логин и стартовый пароль — при первом входе он задаст свой.`);
}
