// «Сборка сумм» (core/sum_build.py): куски после «Разбора записи сумм» — суммы целиком с начальной и конечной
// фразой, у куска — основной и запасные варианты, края, громкость; «Авто-настройка» и «Готовые файлы».
let SB = null, SBR = null, sbSel = 0, sbF = 'all', sbL = 0, sbAnim = null, sbPlaying = false, sbAsked = null;
const SB_CLS = { million: 'млн', hundred_thousand: 'сотни тыс', hundred: 'сотни', thousand: 'тыс', tenge: 'тенге' };
const sbEl = id => document.getElementById(id);

async function sbStart() {
    let r = await pywebview.api.sb_state();
    if (r && r.out) { sbOpen(r); return; }
    let ok = await showBeautifulConfirm('<b>Сборка сумм</b><br><br>Выберите <b>папку кусков</b> после «Разбора записи сумм» '
        + '(«<запись>_куски» с папками «1 - 100 млн», «100 - 900»…). Таблицу сумм спрошу, если её нет в папке.', 'Выбрать папку', 'Отмена');
    if (ok) sbPick();
}
async function sbPick() {
    let r = await pywebview.api.sb_pick();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    sbOpen(r);
}
async function sbOpen(st) {
    SB = st;
    showStage('stage6-sumbuild');
    sbRenderHead();
    sbRenderList();
    let rows = sbRows();
    let cur = SBR && SB.rows.find(r => r.id === SBR.id) ? SBR.id : (rows[0] || SB.rows[0] || {}).id;
    if (cur != null) await sbGo(cur, true);
    if (sbAsked !== SB.out) { sbAsked = SB.out; await sbAskCtx(); }
}
function sbExit() { pywebview.api.sb_stop(); sbStopAnim(); showMenu(); }

// Начальные фразы (Фразы_Переменные) — как в «Прослушке»: без них сумма звучит без начала.
async function sbAskCtx() {
    let miss = (SB.starts || []).filter(s => s.text && !s.file);
    if (!miss.length || SB.start_any) return;
    let ok = await showBeautifulConfirm(`<b>Начальные фразы</b><br><br>Сумма звучит после начальной фразы: ${miss.map(s => '«' + escapeHtml(s.text) + '»').join(', ')}. `
        + 'Выберите для каждой аудиофайл (Фразы_Переменные) — тогда слышно, как сумма стыкуется. '
        + 'Если была запись фраз в разборе, они уже нарезаны и подставлены сами.', 'Выбрать', 'Позже');
    if (!ok) return;
    for (let s of miss) {
        showToast(`Начальная фраза: «${s.text}»`, 2500);
        let r = await pywebview.api.sb_ctx_pick('start', s.text);
        if (!r || r.error) break;
        SB = r;
    }
    let how = await showBeautifulChoice('<b>Конечная фраза</b><br><br>То, что звучит после суммы. Если её нет — пропустите.', 'Выбрать файл', 'Без конца', 'N', 'Отмена');
    if (how === 'ok') { let r = await pywebview.api.sb_ctx_pick('end'); if (r && !r.error) SB = r; }
    sbRenderHead();
    if (SBR) await sbGo(SBR.id, true);
}
async function sbCtx(which, text) {
    let r = await pywebview.api.sb_ctx_pick(which, text || '');
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    SB = r;
    sbRenderHead();
    if (SBR) await sbGo(SBR.id, true);
}
async function sbCtxClear(which, text) {
    SB = await pywebview.api.sb_ctx_clear(which, text || '');
    sbRenderHead();
    if (SBR) await sbGo(SBR.id, true);
}

// ---------- список ----------
const sbIsCheck = r => r.miss || r.bad || r.mark === 'flag';
function sbRows() {
    let q = (sbEl('sbFilter').value || '').trim().toLowerCase();
    return SB.rows.filter(r => (!sbL || r.logic === sbL)
        && (sbF === 'all' || (sbF === 'check' ? sbIsCheck(r) : r.mark !== 'ok'))
        && (!q || r.text.includes(q) || `стр ${r.row}` === q || r.start.includes(q)));
}
function sbSetFilter(f) { sbF = f; sbRenderList(); }
function sbSetLogic(l) { sbL = l; sbRenderList(); }
function sbRenderHead() {
    let ok = SB.rows.filter(r => r.mark === 'ok').length, n = SB.rows.length;
    sbEl('sbProgNum').innerText = `${ok} / ${n}`;
    sbEl('sbProgBar').style.width = n ? `${Math.round(ok / n * 1000) / 10}%` : '0';
    let chk = SB.rows.filter(sbIsCheck).length, miss = SB.rows.filter(r => r.miss).length;
    sbEl('sbStat').innerText = [chk && `проверить ${chk}`, miss && `без куска ${miss}`,
        SB.auto ? `авто-настройка ${SB.auto.done}` : 'авто-настройки ещё не было',
        SB.export ? `готовые файлы ${SB.export.time}` : ''].filter(Boolean).join(' · ');
    sbEl('sbMeta').innerText = (SB.out || '').split(/[\\/]/).pop() + ' · ' + (SB.table || '').split(/[\\/]/).pop();
    sbEl('sbMeta').title = `${SB.out}\n${SB.table}`;
    document.querySelectorAll('#sbTabs button').forEach(b => {
        b.classList.toggle('is-on', b.dataset.f === sbF);
        let c = b.dataset.f === 'check' ? chk : b.dataset.f === 'todo' ? n - ok : null;
        if (c != null) b.querySelector('b').innerText = c;
    });
    document.querySelectorAll('#sbLogic button').forEach(b => b.classList.toggle('is-on', +b.dataset.l === sbL));
}
function sbRenderList() {
    if (!SB) return;
    sbRenderHead();
    sbEl('sbList').innerHTML = sbRows().map(r =>
        `<button type="button" class="listen-row ${SBR && r.id === SBR.id ? 'is-on' : ''} ${r.mark === 'flag' ? 'is-flag' : r.miss || r.bad ? 'is-miss' : r.mark === 'ok' ? '' : 'is-todo'}" onclick="sbGo(${r.id})">
            <span class="listen-row__dot"></span><span class="listen-row__name">${escapeHtml(r.text)}</span>
            <span class="listen-row__tag">${r.miss ? 'нет куска' : r.bad ? 'проверить' : 'стр ' + r.row}</span></button>`).join('')
        || '<div class="tts-dim" style="padding:10px">Нет строк под этот фильтр</div>';
    let on = sbEl('sbList').querySelector('.is-on');
    if (on) on.scrollIntoView({ block: 'nearest' });
}

// ---------- строка ----------
async function sbGo(id, keepSel) {
    let r = await pywebview.api.sb_row(id);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    let same = SBR && SBR.id === r.id;
    SBR = r;
    if (!(keepSel && same)) sbSel = Math.max(0, r.segs.findIndex(s => s.kind === 'piece' && (!s.ok || !s.exists)));
    if (sbSel >= r.segs.length) sbSel = 0;
    if (!(keepSel && same) && !r.segs.some(s => s.kind === 'piece' && (!s.ok || !s.exists)))
        sbSel = Math.max(0, r.segs.findIndex(s => s.kind === 'piece'));
    sbRenderRow();
    sbRenderList();
}
function sbRenderRow() {
    let r = SBR;
    if (!r) return;
    let lst = sbRows(), k = lst.findIndex(x => x.id === r.id);
    sbEl('sbPos').innerText = `${k >= 0 ? k + 1 : '—'} из ${lst.length} · стр ${r.row} · блок ${r.block} · логика ${r.logic}`;
    let st = sbEl('sbStatus'), bad = r.segs.some(s => s.kind === 'piece' && (!s.ok || !s.exists));
    let [c, t] = r.mark === 'ok' ? ['is-done', 'Утверждена'] : r.mark === 'flag' ? ['is-flag', 'Исправить'] : bad ? ['is-miss', 'Проверить'] : ['is-todo', 'Не утверждена'];
    st.className = 'lp-status ' + c; st.innerText = t;
    sbEl('sbName').innerText = r.text;
    sbEl('sbSub').innerText = [r.start && `начало: «${r.start}»`, r.end_text && `конец: «${r.end_text}»`].filter(Boolean).join(' · ');
    let s0 = r.segs.find(s => s.kind === 'start'), s1 = r.segs.find(s => s.kind === 'end');
    sbEl('sbCtx').innerHTML = `<button type="button" class="sb-ctx__b ${s0 ? '' : 'is-miss'}" onclick="sbCtx('start', ${escapeHtml(JSON.stringify(r.start))})" title="Начальная фраза для «${escapeHtml(r.start || 'всех')}» — аудиофайл">начало: ${s0 ? escapeHtml(s0.label) : 'не выбрано'}</button>`
        + `<button type="button" class="sb-ctx__b" onclick="sbCtx('end')" title="Конечная фраза после суммы (необязательно)">конец: ${s1 ? escapeHtml(s1.label) : 'нет'}</button>`
        + (s1 ? `<button type="button" class="sb-ctx__x" onclick="sbCtxClear('end')" title="Без конечной фразы">✕</button>` : '');
    sbEl('sbChips').innerHTML = r.segs.map((s, i) => `<button type="button" class="sb-chip sb-chip--${s.kind} ${i === sbSel ? 'is-on' : ''} ${s.kind === 'piece' && !s.exists ? 'is-miss' : s.kind === 'piece' && !s.ok ? 'is-bad' : ''}"
        onclick="sbPick1(${i})" ondblclick="sbPlay(${i})" title="${s.kind === 'piece' ? escapeHtml(s.key) : ''}">
        <span>${escapeHtml(s.label)}</span><i>${s.kind === 'piece' ? (SB_CLS[s.cls] || escapeHtml(s.cls)) : s.kind === 'start' ? 'начало' : 'конец'}${s.var && s.var !== s.key ? ' · запасной' : ''}</i></button>`).join('<span class="sb-plus">+</span>');
    sbRenderPiece();
    sbDraw();
}
function sbPick1(i) { sbSel = i; sbRenderRow(); }
function sbRenderPiece() {
    let s = SBR.segs[sbSel], el = sbEl('sbPiece');
    if (!s) { el.innerHTML = ''; return; }
    if (s.kind !== 'piece') {
        el.innerHTML = `<div class="sb-piece__head"><b>${s.kind === 'start' ? 'Начальная фраза' : 'Конечная фраза'}</b> <span class="tts-dim">${escapeHtml(s.label)}</span></div>
            <div class="sb-row"><button class="custom-alert-btn" onclick="sbCtx('${s.kind}', ${escapeHtml(JSON.stringify(SBR.start))})">Другой файл…</button>
            <button class="custom-alert-btn" onclick="sbCtxClear('${s.kind}', ${escapeHtml(JSON.stringify(SBR.start))})">Убрать</button></div>`;
        return;
    }
    let v = (s.variants || []).map((x, i) => `<div class="sb-var ${x.rel === s.var ? 'is-on' : ''}">
            <button type="button" class="sb-var__pick" onclick="sbSet('var', ${escapeHtml(JSON.stringify(x.rel))})" title="Взять этот вариант (${i + 1})">${i + 1}. ${escapeHtml(x.label)}</button>
            <button type="button" class="sb-var__play" onclick="sbPlayVar(${escapeHtml(JSON.stringify(x.rel))})" title="Послушать сумму с этим вариантом">▶</button></div>`).join('');
    let knob = (f, label, val, unit, step, title) => `<div class="sb-knob" title="${title}"><span>${label}</span>
        <button type="button" onclick="sbSet('${f}', ${val} - ${step})">−</button><b>${val > 0 && f !== 'gain' ? '+' : ''}${String(val).replace('.', ',')} ${unit}</b>
        <button type="button" onclick="sbSet('${f}', ${val} + ${step})">+</button></div>`;
    el.innerHTML = `<div class="sb-piece__head"><b>${escapeHtml(s.label)}</b> <span class="tts-dim">${escapeHtml(s.key)}${s.uses > 1 ? ` · звучит в ${s.uses} строках — правка общая` : ''}</span></div>`
        + (!s.exists ? '<div class="clone-bad">Куска нет в папке — разбор его не нашёл (или файл убрали).</div>' : '')
        + (s.why && s.var === s.key ? `<div class="clone-bad">${escapeHtml(s.why)}</div>` : '')
        + (s.variants && s.variants.length ? `<div class="sb-vars">${v}</div>` : '')
        + `<div class="sb-row">${knob('head', 'до голоса', s.head, 'мс', 10, 'Сколько оставить перед началом голоса (сверх авто)')}
            ${knob('tail', 'после голоса', s.tail, 'мс', 10, 'Сколько оставить после конца голоса (сверх авто)')}
            ${knob('gain', 'громкость', s.gain, 'дБ', 1, 'Громкость сверх авто-выравнивания')}
            <span class="tts-dim" title="Пауза между голосами на стыке после этого куска — по естественному чтению («Авто-настройка»)">стык ${s.gap} мс</span>
            <button type="button" class="custom-alert-btn sb-reset" onclick="sbSet('reset', null)" title="Основной вариант, правки — по нулям">Сбросить</button></div>`;
}
async function sbSet(field, value) {
    let s = SBR.segs[sbSel];
    if (!s || s.kind !== 'piece') return;
    let r = await pywebview.api.sb_set(SBR.id, s.key, field, value);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    SBR = r;
    sbRenderRow();
    SB = await pywebview.api.sb_state();
    sbRenderList();
    if (field !== 'reset') sbPlay(Math.max(0, sbSel - 1));     // сразу слышно стык с соседом слева
}

// ---------- волна ----------
function sbDraw(head) {
    let cv = sbEl('sbCanvas');
    if (!cv || !SBR) return;
    let w = cv.clientWidth, h = cv.clientHeight, dpr = window.devicePixelRatio || 1;
    cv.width = w * dpr; cv.height = h * dpr;
    let g = cv.getContext('2d');
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    let total = SBR.segs.reduce((a, s) => a + s.ms, 0) || 1, x = 0;
    let css = getComputedStyle(document.documentElement), col = n => css.getPropertyValue(n).trim();
    SBR.segs.forEach((s, i) => {
        let sw = Math.max(s.ms ? 2 : 0, s.ms / total * w), c = s.kind !== 'piece' ? col('--text-dim')
            : !s.exists ? col('--accent-trash') : !s.ok && s.var === s.key ? col('--accent-trash') : col('--accent-var');
        g.fillStyle = i === sbSel ? 'rgba(255,255,255,.07)' : 'rgba(255,255,255,.025)';
        g.fillRect(x, 0, sw, h);
        g.fillStyle = c;
        let n = s.peaks.length || 1;
        s.peaks.forEach((p, j) => { let bh = Math.max(1, p * (h - 26)); g.fillRect(x + j / n * sw, (h + 10) / 2 - bh / 2, Math.max(1, sw / n - 0.5), bh); });
        g.fillStyle = i === sbSel ? col('--text') : col('--text-faint');
        g.font = '11px ' + col('--font-ui');
        g.fillText(s.label.length * 6 > sw ? s.label.slice(0, Math.max(1, Math.floor(sw / 6) - 1)) + '…' : s.label, x + 4, 13);
        if (i) { g.fillStyle = 'rgba(255,255,255,.25)'; g.fillRect(x, 18, 1, h - 18); }
        x += sw;
    });
    if (head != null) { g.fillStyle = col('--accent-primary'); g.fillRect(head / total * w, 0, 2, h); }
}
sbEl('sbCanvas') && sbEl('sbCanvas').addEventListener('click', e => sbCanvasHit(e, false));
sbEl('sbCanvas') && sbEl('sbCanvas').addEventListener('dblclick', e => sbCanvasHit(e, true));
function sbCanvasHit(e, play) {
    if (!SBR) return;
    let rc = e.target.getBoundingClientRect(), t = (e.clientX - rc.left) / rc.width * SBR.segs.reduce((a, s) => a + s.ms, 0), acc = 0;
    for (let i = 0; i < SBR.segs.length; i++) {
        acc += SBR.segs[i].ms;
        if (t <= acc) { if (play) sbPlay(i); else sbPick1(i); return; }
    }
}
window.addEventListener('resize', () => { if (SBR && isShown('stage6-sumbuild')) sbDraw(); });

// ---------- звук ----------
function sbStopAnim() { if (sbAnim) cancelAnimationFrame(sbAnim); sbAnim = null; sbPlaying = false; if (SBR) sbDraw(); }
function sbAnimate(from, ms) {
    sbStopAnim();
    sbPlaying = true;
    let t0 = performance.now();
    let step = () => {
        let t = from + performance.now() - t0;
        if (t >= ms || !sbPlaying) { sbStopAnim(); return; }
        sbDraw(t);
        sbAnim = requestAnimationFrame(step);
    };
    sbAnim = requestAnimationFrame(step);
}
async function sbPlay(k) {
    if (!SBR) return;
    if (sbPlaying && k == null) { await pywebview.api.sb_stop(); sbStopAnim(); return; }
    let r = await pywebview.api.sb_play(SBR.id, k == null ? null : k);
    if (!r || r.error) { showToast(r && r.error || 'Нечего слушать'); return; }
    sbAnimate(r.from, r.ms);
}
async function sbPlayVar(rel) {
    let s = SBR.segs[sbSel];
    let r = await pywebview.api.sb_play_var(SBR.id, s.key, rel);
    if (r && !r.error) sbAnimate(r.from, r.ms);
}

// ---------- решения ----------
async function sbMark(m) {
    if (!SBR) return;
    let cur = SBR.mark === m && m === 'flag' ? null : m;
    await pywebview.api.sb_mark(SBR.id, cur);
    let row = SB.rows.find(r => r.id === SBR.id);
    if (row) row.mark = cur;
    let lst = sbRows(), k = lst.findIndex(r => r.id === SBR.id);
    let nxt = (k >= 0 ? lst[k + 1] : lst.find(r => r.id > SBR.id)) || null;
    if (nxt) { await sbGo(nxt.id); sbPlay(); } else { sbRenderRow(); sbRenderList(); showToast('Это последняя строка в списке', 2500); }
}
async function sbStep(d) {
    let lst = sbRows(), k = lst.findIndex(r => r.id === (SBR || {}).id);
    let nx = lst[Math.max(0, Math.min(lst.length - 1, (k < 0 ? 0 : k + d)))];
    if (nx) { await pywebview.api.sb_stop(); sbStopAnim(); await sbGo(nx.id); }
}
async function sbAuto() {
    if (!(await showBeautifulConfirm('<b>Авто-настройка</b><br><br>Края кусков — по голосу, паузы на стыках — как в естественном чтении '
        + '(по всей записи), громкость — к общему уровню. Ручные правки и выбранные варианты остаются.', 'Настроить', 'Отмена'))) return;
    showToast('Настраиваю…', 2000);
    let r = await pywebview.api.sb_auto();
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
    SB = r.state;
    sbRenderHead();
    if (SBR) await sbGo(SBR.id, true);
    let a = r.auto;
    showToast(`Готово: ${a.pieces} кусков · стыки ${Object.entries(a.gaps).map(([k, v]) => `${SB_CLS[k] || k} ${v} мс`).join(', ') || 'по умолчанию'}`
        + (a.target != null ? ` · уровень ${String(a.target).replace('.', ',')} дБ` : ''), 6000);
}
async function sbExport() {
    if (!SB.auto && !(await showBeautifulConfirm('Авто-настройки ещё не было — файлы будут с краями и паузами по умолчанию. Сохранить так?', 'Сохранить', 'Отмена'))) return;
    showToast('Сохраняю готовые файлы…', 2000);
    let r = await pywebview.api.sb_export();
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
    SB = r.state;
    sbRenderHead();
    if (await showBeautifulConfirm(`<b>Готовые файлы</b><br><br>Кусков: <b>${r.pieces}</b> · начальных и конечных фраз: ${r.ctx}<br><span class="tts-dim">${escapeHtml(r.dir)}</span>`, 'Открыть папку', 'Закрыть'))
        pywebview.api.sb_open_folder('export');
}

function sbKey(e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) return;
    if (e.code === 'Space' || e.code === 'Numpad0') { e.preventDefault(); sbPlay(); return; }
    if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); sbMark('ok'); return; }
    if (e.code === 'Backspace') { e.preventDefault(); sbMark('flag'); return; }
    if (e.code === 'ArrowDown') { e.preventDefault(); sbStep(1); return; }
    if (e.code === 'ArrowUp') { e.preventDefault(); sbStep(-1); return; }
    if (e.code === 'ArrowRight' || e.code === 'ArrowLeft') {
        e.preventDefault();
        if (SBR) { sbSel = Math.max(0, Math.min(SBR.segs.length - 1, sbSel + (e.code === 'ArrowRight' ? 1 : -1))); sbRenderRow(); }
        return;
    }
    let d = /^(Digit|Numpad)([1-9])$/.exec(e.code);
    if (d && SBR) {
        let s = SBR.segs[sbSel], v = s && s.variants && s.variants[+d[2] - 1];
        if (v) { e.preventDefault(); sbSet('var', v.rel); }
        return;
    }
    if (e.code === 'Escape') { e.preventDefault(); pywebview.api.sb_stop(); sbStopAnim(); }
}
