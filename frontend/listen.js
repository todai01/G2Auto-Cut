// ===== Прослушка переменных =====
// Папка записей → начало и конец фразы → таблица названий. Запись строки ищется
// по имени (не по порядку). Слушаем как в суфлёре: конец начала + переменная +
// начало продолжения; правим переменную или саму фразу (полностью); синтез —
// если запись неудачная или её нет.
let LS = null;                     // состояние с бэкенда (listen_state)
let lEd = null;                    // правка: {target, path, dur, peaks, bucket, ranges, gain, tempo, sel, cur, head, hist, saved}
let lTarget = 'var';               // что правим: var | start | end
let lPlay = null;                  // {t0, d, marks} — головка при прослушке
let lPlayTok = 0;                  // ответ прослушки, пришедший после перехода/стопа, — не наш

const lEl = id => document.getElementById(id);
const lRow = () => LS && LS.rows[LS.pos];

async function listenStart() {
    let ok = await showBeautifulAlert('<b>Прослушка переменных · шаг 1 из 3</b><br><br>Выберите <b>папку с записями переменных</b> — '
        + 'файлы, названные как значения (например, «Гизат.wav»). Подпапки тоже смотрю.');
    if (!ok) return;
    let r = await pywebview.api.listen_pick_folder();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    ok = await showBeautifulAlert(`<b>Шаг 2 из 3</b><br><br>Найдено записей: <b>${r.files}</b>.<br><br>Теперь папка с кусочками фраз — <b>«Фразы_Переменные»</b> `
        + '(внутри — <b>ru</b> и <b>kz</b>). В ней отметите, какой кусок — начало, а какой — конец.');
    if (!ok) return;
    r = await pywebview.api.listen_pick_phrases();
    if (r && r.error && r.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(r.error));
    if (r && !r.error) { LS = r; await listenPhrOpen(); }
    ok = await showBeautifulAlert('<b>Шаг 3 из 3</b><br><br><b>Таблица с названиями переменных</b> (.xlsx). Колонку найду сам — ту, где больше совпадений с папкой; '
        + 'по каждому названию ищу запись в папке, порядок в таблице не важен.');
    if (!ok) return;
    r = await pywebview.api.listen_pick_table();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    listenOpen();
    showToast(`Таблица: ${r.rows.length} названий · есть запись у ${r.found}${r.column ? ` · ${r.column}` : ''}`, 4500);
}

function listenOpen() {
    showStage('stage5-listen');
    lTarget = 'var';
    listenRender();
    listenLoadEditor();
}
function listenExit() {
    if (lEd && listenDirty()) {
        showBeautifulConfirm('Правка не сохранена. Выйти без сохранения?', 'Выйти', 'Остаться').then(go => { if (go) { lEd = null; showMenu(); } });
        return;
    }
    pywebview.api.listen_stop();
    showMenu();
}

async function listenPick(what) {
    let r = what === 'folder' ? await pywebview.api.listen_pick_folder() : await pywebview.api.listen_pick_table();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); if (!r.state) return; r = r.state; }
    LS = r;
    listenRender();
    listenLoadEditor();
}

// ----- отрисовка -----
function listenRender(light) {
    if (!LS) return;
    lEl('listenLangTop').innerHTML = listenLangBtns();
    lEl('listenMeta').innerText = [LS.folder_name && `папка «${LS.folder_name}» · ${LS.files} записей`, LS.lang.toUpperCase(),
        LS.start ? `начало: ${LS.start}` : 'начало: нет', LS.end ? `конец: ${LS.end}` : 'конец: нет'].filter(Boolean).join(' · ');
    lEl('listenShort').checked = !!LS.short;
    if (light) listenMarkList(); else listenRenderList();
    let r = lRow();
    lEl('listenPos').innerText = r ? `${LS.pos + 1} из ${LS.rows.length}` : 'Загрузите таблицу';
    lEl('listenName').innerText = r ? r.name : '—';
    lEl('listenName').classList.toggle('is-miss', !!r && !r.path);
    lEl('listenFile').innerHTML = !r ? '' : r.path
        ? `${escapeHtml(r.file)}${r.dups ? ` · <span class="listen-warn">в папке ещё ${r.dups} с тем же именем</span>` : ''}${r.edited ? ' · правилась' : ''}`
        : '<span class="listen-warn">записи с таким именем в папке нет — синтезируйте</span>';
    let part = (t, label, name, ok) => `<button type="button" class="listen-part ${lTarget === t ? 'is-on' : ''} ${ok ? '' : 'is-miss'}" ${ok ? '' : 'disabled'}
            onclick="listenTarget('${t}')" title="${ok ? 'Править' + (t === 'var' ? ' запись переменной' : ' фразу целиком') : ''}">
            <i>${label}</i><b>${escapeHtml(name || '—')}</b>${ok ? '<span>✎</span>' : ''}</button>`;
    let ctx = (LS.ctx_ms / 1000).toLocaleString('ru-RU');
    lEl('listenChain').innerHTML = part('start', LS.short ? `начало · последние ${ctx} с` : 'начало', LS.start, !!LS.start_path)
        + '<span class="listen-arrow">→</span>' + part('var', 'переменная', r && r.name, !!(r && r.path))
        + '<span class="listen-arrow">→</span>' + part('end', LS.short ? `конец · первые ${ctx} с` : 'конец', LS.end, !!LS.end_path);
    listenRenderSynth();
}
function listenRenderList() {
    if (!LS) return;
    let q = (lEl('listenFilter').value || '').trim().toLowerCase();
    lEl('listenList').innerHTML = LS.rows.map((r, k) => ({ r, k })).filter(({ r }) => !q || r.name.toLowerCase().includes(q)).map(({ r, k }) =>
        `<button type="button" class="listen-row ${k === LS.pos ? 'is-on' : ''} ${listenRowCls(r)}" data-k="${k}" onclick="listenGo(${k})">
            <span class="listen-row__dot"></span><span class="listen-row__name">${escapeHtml(r.name)}</span>
            <span class="listen-row__tag">${r.synth === 'busy' ? 'синтез…' : r.synth === 'ready' ? 'синтез ✓' : r.edited ? 'правка' : r.path ? '' : 'нет'}</span></button>`).join('');
    listenStatRender();
    let on = lEl('listenList').querySelector('.is-on');
    if (on) on.scrollIntoView({ block: 'nearest' });
}

// Кружок: красный — записи нет, жёлтый — есть, ещё не сохранена, зелёный — сохранена
const listenRowCls = r => !r.path ? 'is-miss' : r.done ? '' : 'is-todo';
function listenStatRender() {
    let n = LS.rows.length, done = LS.rows.filter(r => r.path && r.done).length;
    lEl('listenStat').innerText = n ? `сохранено ${done} из ${LS.found}${n > LS.found ? ` · без записи ${n - LS.found}` : ''}` : '';
}
// Шаг по списку — без перерисовки всех строк: только отметка текущей
function listenMarkList() {
    let list = lEl('listenList'), old = list.querySelector('.listen-row.is-on'), cur = list.querySelector(`.listen-row[data-k="${LS.pos}"]`);
    if (old && old !== cur) old.classList.remove('is-on');
    if (cur) {
        cur.classList.add('is-on');
        let r = LS.rows[LS.pos], tag = cur.querySelector('.listen-row__tag');
        cur.classList.toggle('is-miss', !r.path);
        cur.classList.toggle('is-todo', !!r.path && !r.done);
        if (tag) tag.innerText = r.synth === 'busy' ? 'синтез…' : r.synth === 'ready' ? 'синтез ✓' : r.edited ? 'правка' : r.path ? '' : 'нет';
        cur.scrollIntoView({ block: 'nearest' });
    }
}

// ----- навигация: один вызов — сразу звук, волна и эта строка -----
async function listenGo(k) {
    if (!LS || k === LS.pos) return;
    if (!(await listenLeave())) return;
    listenStopHead();
    LS.pos = k; lTarget = 'var';
    listenRender(true);                                  // имя — крупно сразу, не дожидаясь звука
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_go(k);
    if (!r || r.error || LS.pos !== k) return;           // уже ушли дальше
    LS.rows[k] = r.row;
    listenRender(true);
    listenSetEditor(r.edit || null, r.row.path);
    if (r.play && r.play.error !== 'skip') listenAfterPlay(r.play, tok);
}
function listenStep(d) { if (LS && LS.rows.length) listenGo(Math.max(0, Math.min(LS.rows.length - 1, LS.pos + d))); }
async function listenTarget(t) {
    if (t === lTarget) return;
    if (!(await listenLeave())) return;
    lTarget = t;
    listenRender();
    listenLoadEditor();
}
async function listenSetShort(on) { LS = await pywebview.api.listen_set(null, null, on); listenRender(); }
// Ушли с правленой записи — сохранить?
async function listenLeave() {
    if (!lEd || !listenDirty()) return true;
    if (lEd.auto && !lEd.hist.length) return true;       // автосрезку не трогали — уходим молча, файл как был
    let how = await showBeautifulChoice(`Правка «${escapeHtml(lEd.name)}» не сохранена.`, 'Сохранить', 'Не сохранять', 'N', 'Остаться');
    if (how === 'ok') return await listenSave();
    return how === 'alt';
}

// ----- редактор (координаты исходника: обрезанное — серым) -----
function listenTargetPath() {
    if (lTarget === 'start') return LS.start_path;
    if (lTarget === 'end') return LS.end_path;
    let r = lRow();
    return r && r.path;
}
async function listenLoadEditor() {
    listenStopHead();
    let path = LS && listenTargetPath();
    if (!path) { lEd = null; lEl('listenEd').classList.add('is-empty'); listenEdRender(); return; }
    let r = await pywebview.api.listen_edit_load(path);
    if (path !== listenTargetPath()) return;             // пока грузили — перешли на другое
    listenSetEditor(r, path);
}
function listenSetEditor(r, path) {
    if (!path) { lEd = null; lEl('listenEd').classList.add('is-empty'); listenEdRender(); return; }
    if (!r || r.error) { lEd = null; showToast(r && r.error || 'Не открылась запись'); listenEdRender(); return; }
    lEl('listenEd').classList.remove('is-empty');
    lEd = { ...r, target: lTarget, sel: null, cur: 0, head: null, hist: [] };
    lEd.saved = listenSnap();
    lEd.auto = null;
    if (r.auto && lTarget === 'var') listenApplyAuto(r.auto);   // ещё не правили — сразу срезка по голосу / шаблону
    let cv = lEl('listenEdCanvas');
    cv.onmousedown = listenEdDown;
    cv.onmousemove = listenEdHover;
    listenEdRender();
}
function listenApplyAuto(a) {
    lEd.ranges = a.ranges.map(x => [...x]); lEd.gain = a.gain; lEd.tempo = a.tempo;
    lEd.auto = a; lEd.sel = null;
}
// «Авто» — срезать заново по голосу (и шаблону), можно отменить Ctrl+Z
async function listenAuto() {
    if (!lEd || lEd.target !== 'var') return;
    let a = await pywebview.api.listen_auto(lEd.path);
    if (!a || a.error) { showToast(a && a.error || 'Не получилось'); return; }
    listenPush(); listenApplyAuto(a); listenEdRender();
    listenPlayChain();
}
async function listenTplSet() {
    if (!lEd || lEd.target !== 'var') return;
    let r = await pywebview.api.listen_tpl_set(lEd.path, lEd.ranges, lEd.gain, lEd.tempo, lRow() && lRow().name);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS.tpl = r.tpl; listenEdRender();
    showToast(`Шаблон срезки — «${r.tpl.from}»: тишина по краям, громкость, темп`);
}
const listenSnap = () => JSON.stringify({ r: lEd.ranges, g: lEd.gain, t: lEd.tempo });
const listenDirty = () => !!lEd && listenSnap() !== lEd.saved;
const lKept = () => lEd.ranges.reduce((s, [a, b]) => s + b - a, 0);
function listenPush() { lEd.hist.push(listenSnap()); if (lEd.hist.length > 100) lEd.hist.shift(); }

function listenEdRender() {
    let bar = lEl('listenEdBar');
    if (!lEd) {
        lEl('listenEdTitle').innerText = LS && LS.rows.length && lTarget === 'var' && !(lRow() || {}).path ? 'Записи нет — синтезируйте ниже' : '';
        bar.innerHTML = '';
        listenEdDraw();
        return;
    }
    let kind = { var: 'переменная', start: 'начало фразы (целиком)', end: 'конец фразы (целиком)' }[lEd.target];
    let au = lEd.auto, sec = ms => (ms / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
    let autoTxt = au ? ` · <span class="listen-auto">срезано по голосу${au.breath ? ` · вдох / шум ${sec(au.breath)} с` : ''}${au.by_tpl ? ` · по шаблону «${escapeHtml(au.by_tpl)}»` : ''}</span>` : '';
    lEl('listenEdTitle').innerHTML = `Правка — ${escapeHtml(lEd.name)} <span class="tts-dim">· ${kind}</span>${autoTxt}`;
    let sel = lEd.sel ? Math.round(lEd.sel.b - lEd.sel.a) : 0, len = lKept() / (lEd.tempo || 1);
    bar.innerHTML = `
        <button class="btn-ghost btn-ghost--compact" onclick="listenEdCut()" ${lEd.sel ? '' : 'disabled'} title="Убрать выделенное">Вырезать <kbd>X</kbd></button>
        <button class="btn-ghost btn-ghost--compact" onclick="listenEdKeep()" ${lEd.sel ? '' : 'disabled'} title="Оставить только выделенное">Оставить выделенное</button>
        <button class="btn-ghost btn-ghost--compact" onclick="listenEdUndo()" ${lEd.hist.length ? '' : 'disabled'}>&#8630; <kbd>Ctrl+Z</kbd></button>
        <button class="btn-ghost btn-ghost--compact" onclick="listenEdReset()" title="Вся исходная запись, громкость 0, темп 100%">Как было</button>
        <span class="listen-knob" title="Громкость">дБ <button onclick="listenKnob('gain', -1)">&minus;</button><b>${lEd.gain > 0 ? '+' : ''}${lEd.gain}</b><button onclick="listenKnob('gain', 1)">+</button></span>
        <span class="listen-knob" title="Темп (без смены высоты)">темп <button onclick="listenKnob('tempo', -0.03)">&minus;</button><b>${Math.round(lEd.tempo * 100)}%</b><button onclick="listenKnob('tempo', 0.03)">+</button></span>
        <span class="tts-dim">${(len / 1000).toFixed(2)} с${sel ? ` · выделено ${sel} мс` : ''}</span>
        ${lEd.target === 'var' ? `<button class="btn-ghost btn-ghost--compact" onclick="listenAuto()" title="Срезать по голосу: вдох и шум по краям — прочь, тишина, громкость и темп — по шаблону">Авто <kbd>A</kbd></button>
        <button class="btn-ghost btn-ghost--compact" onclick="listenTplSet()" title="${LS.tpl ? `Сейчас шаблон — «${escapeHtml(LS.tpl.from)}». ` : ''}Тишина до / после голоса, громкость и темп этой записи — для остальных">Шаблон из этой</button>
        <span class="listen-tpl">${LS.tpl ? `шаблон: «${escapeHtml(LS.tpl.from)}»` : 'шаблона нет — первая сохранённая станет им'}</span>` : ''}
        <span class="tts-ed__spacer"></span>
        ${lEd.target === 'var' && lRow() && lRow().done ? '<button class="btn-ghost btn-ghost--compact" onclick="listenUnsave(LS.pos)" title="Запись — как до сохранения: подправить и сохранить заново (Ctrl+Z сразу после сохранения)">Отменить сохранение</button>'
          : lEd.has_backup ? '<button class="btn-ghost btn-ghost--compact" onclick="listenRestore()" title="Записать обратно исходник из «_до_правок»">Вернуть исходник</button>' : ''}
        <button class="custom-alert-btn" onclick="listenSave(true)" ${listenDirty() ? '' : 'disabled'} title="Сохранить и перейти к следующей">Сохранить <kbd>Enter</kbd></button>`;
    listenEdDraw();
}
function listenEdDraw() {
    let cv = lEl('listenEdCanvas'), dpr = window.devicePixelRatio || 1;
    let w = cv.clientWidth, h = cv.clientHeight;
    if (!w) return;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    let g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    if (!lEd) return;
    let x = ms => ms / lEd.dur * w, mid = h / 2, css = getComputedStyle(document.documentElement);
    let kept = t => lEd.ranges.some(([a, b]) => t >= a && t < b);
    for (let t = 0; t < lEd.dur; t += lEd.bucket) {
        let p = lEd.peaks[Math.floor(t / lEd.bucket)] || 0, y = Math.max(1, p * (mid - 8));
        g.fillStyle = kept(t) ? (css.getPropertyValue('--accent-var').trim() || '#eeac3e') : 'rgba(255,255,255,.13)';
        g.fillRect(x(t), mid - y, Math.max(1, w * lEd.bucket / lEd.dur), y * 2);
    }
    // края: ручки начала и конца записи
    let a0 = lEd.ranges[0][0], b1 = lEd.ranges[lEd.ranges.length - 1][1];
    g.fillStyle = '#fff';
    [a0, b1].forEach(t => { g.fillRect(x(t) - 1, 0, 2, h); g.fillRect(x(t) - 5, h - 14, 10, 14); });
    g.fillStyle = 'rgba(239,91,80,.85)';                                  // вырезанное в середине
    lEd.ranges.slice(1).forEach(([a], i) => { let b = lEd.ranges[i][1]; g.fillRect(x(b), 0, Math.max(2, x(a) - x(b)), 3); });
    if (lEd.sel) { g.fillStyle = 'rgba(90,150,255,.32)'; g.fillRect(x(lEd.sel.a), 0, x(lEd.sel.b) - x(lEd.sel.a), h); }
    g.fillStyle = '#5a96ff'; g.fillRect(x(lEd.cur) - 1, 0, 2, h);
    if (lEd.head !== null) { g.fillStyle = css.getPropertyValue('--accent-good').trim() || '#2fbf7d'; g.fillRect(x(lEd.head) - 1, 0, 2, h); }
}
function listenEdHit(cx) {
    let cv = lEl('listenEdCanvas'), r = cv.getBoundingClientRect(), t = (cx - r.left) / cv.clientWidth * lEd.dur;
    let px = ms => ms / lEd.dur * cv.clientWidth, a0 = lEd.ranges[0][0], b1 = lEd.ranges[lEd.ranges.length - 1][1];
    let edge = Math.abs(px(t) - px(a0)) < 7 ? 'a' : Math.abs(px(t) - px(b1)) < 7 ? 'b' : null;
    return { t: Math.max(0, Math.min(lEd.dur, t)), edge };
}
function listenEdHover(e) { if (lEd) e.currentTarget.style.cursor = listenEdHit(e.clientX).edge ? 'ew-resize' : 'text'; }
function listenEdDown(e) {
    if (!lEd) return;
    e.preventDefault();
    let h = listenEdHit(e.clientX), moved = false, start = h.t, snap = listenSnap();
    let move = ev => {
        if (!moved && Math.abs(ev.clientX - e.clientX) < 3) return;
        moved = true;
        let t = listenEdHit(ev.clientX).t;
        if (h.edge === 'a') lEd.ranges[0][0] = Math.round(Math.min(t, lEd.ranges[0][1] - 30));
        else if (h.edge === 'b') { let L = lEd.ranges[lEd.ranges.length - 1]; L[1] = Math.round(Math.max(t, L[0] + 30)); }
        else lEd.sel = { a: Math.min(start, t), b: Math.max(start, t) };
        listenEdDraw();
    };
    let up = () => {
        window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
        if (h.edge && moved) { lEd.hist.push(snap); }
        else if (!moved) { lEd.sel = null; lEd.cur = start; }
        else lEd.cur = lEd.sel.a;
        listenEdRender();
    };
    window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
}
// вырезать [s, e] исходника из оставленных кусков
function lRemove(s, e) {
    let out = [];
    lEd.ranges.forEach(([a, b]) => {
        if (e <= a || s >= b) out.push([a, b]);
        else { if (s > a) out.push([a, s]); if (e < b) out.push([e, b]); }
    });
    return out.filter(([a, b]) => b - a >= 5).map(([a, b]) => [Math.round(a), Math.round(b)]);
}
function listenEdCut() {
    if (!lEd || !lEd.sel) return;
    let n = lRemove(lEd.sel.a, lEd.sel.b);
    if (!n.length) { showToast('Нельзя вырезать всё'); return; }
    listenPush(); lEd.ranges = n; lEd.cur = lEd.sel.a; lEd.sel = null; listenEdRender();
}
function listenEdKeep() {
    if (!lEd || !lEd.sel) return;
    listenPush();
    lEd.ranges = lRemove(lEd.sel.b, lEd.dur);
    lEd.ranges = lRemove(0, lEd.sel.a);
    lEd.sel = null; lEd.cur = lEd.ranges[0][0]; listenEdRender();
}
function listenEdUndo() {
    if (!lEd || !lEd.hist.length) { listenUndoSave(); return; }
    let s = JSON.parse(lEd.hist.pop());
    lEd.ranges = s.r; lEd.gain = s.g; lEd.tempo = s.t; lEd.sel = null; listenEdRender();
}
function listenEdReset() { if (!lEd) return; listenPush(); lEd.ranges = [[0, lEd.dur]]; lEd.gain = 0; lEd.tempo = 1; lEd.sel = null; lEd.auto = null; listenEdRender(); }
function listenKnob(k, d) {
    if (!lEd) return;
    listenPush();
    if (k === 'gain') lEd.gain = Math.max(-12, Math.min(12, lEd.gain + d));
    else lEd.tempo = Math.round(Math.max(0.8, Math.min(1.25, lEd.tempo + d)) * 100) / 100;
    listenEdRender();
}
// next — после сохранения переменной перейти к следующей строке (и сразу её послушать)
let lLastSaved = null;              // последняя сохранённая строка — Ctrl+Z отменит
async function listenSave(next) {
    if (!lEd) { if (next && lTarget === 'var' && LS && LS.pos < LS.rows.length - 1) listenStep(1); return true; }
    let go = next && lEd.target === 'var' && LS.pos < LS.rows.length - 1;
    if (!listenDirty()) {
        if (lEd.target === 'var' && lRow() && !lRow().done) {          // хороша как есть — отметить сохранённой
            let r = await pywebview.api.listen_mark_done(lEd.path);
            if (r && r.state) { let pos = LS.pos; LS = r.state; LS.pos = pos; }
            lLastSaved = { pos: LS.pos, path: lEd.path };
            listenMarkList(); listenStatRender();
            if (!go) { listenRender(true); listenEdRender(); }
        }
        if (go) listenStep(1);
        return true;
    }
    let r = await pywebview.api.listen_edit_save(lEd.path, lEd.ranges, lEd.gain, lEd.tempo, lEd.target === 'var');
    if (!r || r.error) { showToast(r && r.error || 'Не сохранилось'); return false; }
    lEd.saved = listenSnap(); lEd.has_backup = true; lEd.auto = null; lEd.hist = [];
    if (r.state) { let pos = LS.pos; LS = r.state; LS.pos = pos; }
    if (lEd.target === 'var') { lLastSaved = { pos: LS.pos, path: lEd.path }; listenMarkList(); listenStatRender(); }
    showToast(r.tpl_new ? `Сохранено: ${lEd.name} · стала шаблоном срезки для остальных` : `Сохранено: ${lEd.name}${go ? ' → дальше · Ctrl+Z — отменить' : ''}`);
    if (go) { listenStep(1); return true; }
    listenRender(); listenEdRender();
    return true;
}
// «Отменить сохранение»: запись — как до сохранения (кружок снова жёлтый), срезка по голосу заново
async function listenUnsave(pos) {
    let row = LS.rows[pos];
    if (!row || !row.path) return;
    let r = await pywebview.api.listen_edit_restore(row.path);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    let keep = LS.pos; LS = r.state; LS.pos = keep;
    if (lLastSaved && lLastSaved.pos === pos) lLastSaved = null;
    listenRender();
    if (pos === LS.pos && lTarget === 'var') await listenLoadEditor();
    showToast(`«${row.name}»: сохранение отменено — подправьте и сохраните заново (Enter)`);
}
// Ctrl+Z без правок на экране — отменить последнее сохранение (вернуться к той строке)
async function listenUndoSave() {
    if (!lLastSaved || !LS.rows[lLastSaved.pos] || LS.rows[lLastSaved.pos].path !== lLastSaved.path) return;
    let pos = lLastSaved.pos;
    if (pos !== LS.pos) { await listenGo(pos); if (LS.pos !== pos) return; }
    await listenUnsave(pos);
}
async function listenRestore() {
    if (!(await showBeautifulConfirm(`Вернуть исходную запись «${escapeHtml(lEd.name)}»? Все правки пропадут.`, 'Вернуть', 'Отмена'))) return;
    let r = await pywebview.api.listen_edit_restore(lEd.path);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS = r.state;
    lEd = { ...lEd, ...r, sel: null, cur: 0, hist: [] }; lEd.saved = listenSnap();
    listenRender(); listenEdRender();
    showToast('Исходная запись возвращена');
}

// ----- прослушка: в фразе (кратко) или одна правка -----
function listenPart(t) {
    if (lEd && lEd.target === t) return { path: lEd.path, ranges: lEd.ranges, gain: lEd.gain, tempo: lEd.tempo };
    let p = t === 'start' ? LS.start_path : t === 'end' ? LS.end_path : (lRow() || {}).path;
    return p ? { path: p } : null;
}
function listenStopHead() { lPlayTok++; if (lPlay && lPlay.raf) cancelAnimationFrame(lPlay.raf); lPlay = null; if (lEd) { lEd.head = null; listenEdDraw(); } lEl('listenPlayBtn').classList.remove('is-playing'); }
async function listenPlayChain() {
    if (!LS) return;
    if (lPlay) { listenStopHead(); pywebview.api.listen_stop(); return; }
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_play(listenPart('var'), listenPart('start'), listenPart('end'), null);
    listenAfterPlay(r, tok);
}
async function listenPlayOnly() {
    if (!LS || !lEd) return;
    if (lPlay) { listenStopHead(); pywebview.api.listen_stop(); return; }
    let p = listenPart(lEd.target);
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_play(lEd.target === 'var' ? p : null, lEd.target === 'start' ? p : null, lEd.target === 'end' ? p : null, lEd.target);
    listenAfterPlay(r, tok);
}
// Головка на волне правки: где в цепочке звучит правленый кусок
function listenAfterPlay(r, tok) {
    if (tok !== lPlayTok) { if (r && !r.error) pywebview.api.listen_stop(); return; }
    if (!r || r.error) { if (r) showToast(r.error); return; }
    lEl('listenPlayBtn').classList.add('is-playing');
    let off = 0, mine = null;
    (r.marks || []).forEach(m => { if (lEd && m.kind === lEd.target) mine = { off, ms: m.ms }; off += m.ms; });
    lPlay = { t0: performance.now(), d: r.duration * 1000, mine };
    let step = () => {
        if (!lPlay) return;
        let t = performance.now() - lPlay.t0;
        if (t > lPlay.d) { listenStopHead(); return; }
        if (lEd && lPlay.mine) {
            let local = t - lPlay.mine.off, kept = lKept(), tail = lEd.target === 'start' && LS.short ? Math.max(0, kept / lEd.tempo - lPlay.mine.ms) : 0;
            lEd.head = local >= 0 && local <= lPlay.mine.ms ? listenSrcAt((local + tail) * lEd.tempo) : null;
            listenEdDraw();
        }
        lPlay.raf = requestAnimationFrame(step);
    };
    lPlay.raf = requestAnimationFrame(step);
}
// время по оставленным кускам → время исходника
function listenSrcAt(t) {
    for (let [a, b] of lEd.ranges) { if (t <= b - a) return a + t; t -= b - a; }
    return null;
}

// ----- синтез -----
function listenRenderSynth() {
    let box = lEl('listenSynth'), r = lRow();
    if (!r) { box.innerHTML = ''; return; }
    let st = r.synth;
    box.innerHTML = `<div class="listen-synth__head">Синтез <span class="tts-dim">— если запись неудачная или её нет</span></div>
        <div class="listen-synth__row">
            <span class="listen-lang">${listenLangBtns()}</span>
            <input class="listen-synth__text" id="listenSynthText" value="${escapeHtml(r.name)}" title="Текст для синтеза — можно поправить (ударение, написание)">
            <button class="custom-alert-btn" onclick="listenSynth()" ${st === 'busy' ? 'disabled' : ''}>${st === 'busy' ? 'Синтезирую…' : 'Синтезировать'}</button>
        </div>
        ${st === 'ready' ? `<div class="listen-synth__row">
            <button class="btn-ghost" onclick="listenSynthPlay()">&#9654; Синтез в фразе</button>
            <button class="btn-ghost btn-ghost--good" onclick="listenSynthTake()" title="Записать вместо текущей (прежняя — в «_до_правок»)">Взять синтез</button>
            <button class="btn-ghost" onclick="listenSynthDrop()">Отклонить</button></div>` : ''}
        ${st === 'error' ? '<div class="listen-warn">Синтез не получился — попробуйте ещё раз</div>' : ''}`;
}
const listenLangBtns = (cur = LS.lang, fn = 'listenLang') => ['ru', 'kz'].map(l =>
    `<button type="button" class="${cur === l ? 'is-on' : ''}" onclick="${fn}('${l}')">${l.toUpperCase()}</button>`).join('');
// Язык — для всего: пара начало / конец, записи из ru / kz (если папка разделена) и синтез
async function listenLang(l) {
    if (!LS || l === LS.lang) return;
    if (!(await listenLeave())) return;
    listenStopHead(); pywebview.api.listen_stop();
    LS = await pywebview.api.listen_set(null, l);
    listenRender();
    await listenLoadEditor();
}

// ----- начало и конец: кусочки из «Фразы_Переменные» (ru / kz) -----
let lPhr = null;                   // {lang, done} — окно выбора открыто
async function listenPhrases() {
    if (!LS) return;
    if (!LS.phrases.length) {
        let r = await pywebview.api.listen_pick_phrases();
        if (!r || r.error === 'cancel') return;
        if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
        LS = r;
    }
    if (!(await listenLeave())) return;
    await listenPhrOpen();
    if (isShown('stage5-listen')) { listenRender(); listenLoadEditor(); }
}
function listenPhrOpen() {
    return new Promise(done => {
        lPhr = { lang: LS.lang, done };
        lEl('listenPhrFilter').value = '';
        lEl('listenPhrOverlay').style.display = 'flex';
        listenPhrRender();
    });
}
function listenPhrClose() {
    if (!lPhr) return;
    pywebview.api.listen_stop();
    lEl('listenPhrOverlay').style.display = 'none';
    let d = lPhr.done; lPhr = null; d();
}
async function listenPhrFolder() {
    let r = await pywebview.api.listen_pick_phrases();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showToast(r.error); return; }
    LS = r; listenPhrRender();
}
function listenPhrLang(l) { lPhr.lang = l; listenPhrRender(); }
async function listenPhrSet(which, k) {
    let p = LS.phrases[k], cur = (LS.pick[lPhr.lang] || {})[which];
    LS = await pywebview.api.listen_set_phrase(which, cur === p.path ? null : p.path, lPhr.lang);
    listenPhrRender();
}
function listenPhrPlay(k) { pywebview.api.listen_phrase_play(LS.phrases[k].path); }
function listenPhrRender() {
    if (!lPhr) return;
    let pick = LS.pick[lPhr.lang] || {}, q = lEl('listenPhrFilter').value.trim().toLowerCase();
    let split = LS.phrases.some(p => p.lang);
    lEl('listenPhrFolder').innerText = `папка «${LS.phr_folder_name}» · сменить`;
    lEl('listenPhrLang').innerHTML = listenLangBtns(lPhr.lang, 'listenPhrLang');
    let nm = p => p ? escapeHtml((LS.phrases.find(x => x.path === p) || {}).rel || p) : '—';
    lEl('listenPhrSel').innerHTML = `<span>${lPhr.lang.toUpperCase()} · начало: <b>${nm(pick.start)}</b></span><span>конец: <b>${nm(pick.end)}</b></span>`;
    let rows = LS.phrases.map((p, k) => ({ p, k })).filter(({ p }) => (!split || !p.lang || p.lang === lPhr.lang)
        && (!q || p.rel.toLowerCase().includes(q)));
    lEl('listenPhrList').innerHTML = rows.map(({ p, k }) => {
        let st = pick.start === p.path, en = pick.end === p.path;
        return `<div class="listen-phr__row ${st ? 'is-start' : ''} ${en ? 'is-end' : ''}">
            <button class="btn-ghost btn-ghost--compact" onclick="listenPhrPlay(${k})" title="Послушать целиком">&#9654;</button>
            <span class="listen-phr__name" title="${escapeHtml(p.rel)}">${escapeHtml(split ? p.rel.replace(/^[^/]*\//, '') : p.rel)}</span>
            <button class="btn-ghost btn-ghost--compact ${st ? 'is-on' : ''}" onclick="listenPhrSet('start', ${k})">Начало</button>
            <button class="btn-ghost btn-ghost--compact ${en ? 'is-on' : ''}" onclick="listenPhrSet('end', ${k})">Конец</button></div>`;
    }).join('') || `<div class="tts-list__empty tts-dim">${split ? `В папке ${lPhr.lang} нет кусочков` : 'Ничего не нашлось'}</div>`;
}
document.addEventListener('keydown', e => {
    if (!lPhr) return;
    if (e.code === 'Escape' || (e.code === 'Enter' && e.target.tagName !== 'BUTTON')) { e.preventDefault(); listenPhrClose(); }
    if (e.target.tagName !== 'INPUT') e.stopImmediatePropagation();
}, true);
async function listenSynth() {
    let r = await pywebview.api.listen_synth(LS.pos, lEl('listenSynthText').value, LS.lang);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS = r.state; listenRenderList(); listenRenderSynth();
    showToast('Синтез запущен — можно слушать другие строки');
}
async function listenSynthPlay() {
    listenStopHead();
    let r = await pywebview.api.listen_synth_play(LS.pos);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    lEl('listenPlayBtn').classList.add('is-playing');
    lPlay = { t0: performance.now(), d: r.duration * 1000, mine: null };
    setTimeout(() => { if (lPlay && performance.now() - lPlay.t0 >= lPlay.d - 50) listenStopHead(); }, r.duration * 1000);
}
async function listenSynthTake() {
    let r = await pywebview.api.listen_synth_take(LS.pos);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS = r.state; lTarget = 'var';
    listenRender(); await listenLoadEditor();
    showToast('Синтез записан вместо прежней записи — можно подрезать');
}
async function listenSynthDrop() { LS = await pywebview.api.listen_synth_drop(LS.pos); listenRender(); }
// Python → JS: синтез готов / ошибка
function listenEvent(p) {
    if (!p) return;
    if (p.state) { let pos = LS ? LS.pos : 0; LS = p.state; LS.pos = pos; }
    if (p.stage === 'synth') {
        let name = LS && LS.rows[p.k] ? LS.rows[p.k].name : '';
        showToast(p.ok ? `Синтез готов: ${name} — «▶ Синтез в фразе»` : `Синтез «${name}»: ${p.error}`, 4500);
        if (isShown('stage5-listen')) { listenRenderList(); if (LS && p.k === LS.pos) listenRenderSynth(); }
    }
}

// ----- клавиши -----
function listenKey(e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
    if (e.code === 'Space') { e.preventDefault(); listenPlayChain(); return; }
    if (e.code === 'KeyP') { e.preventDefault(); listenPlayOnly(); return; }
    if (e.code === 'ArrowDown' || e.code === 'KeyS') { e.preventDefault(); listenStep(1); return; }
    if (e.code === 'ArrowUp' || e.code === 'KeyW') { e.preventDefault(); listenStep(-1); return; }
    if (e.code === 'KeyX' || e.code === 'Delete') { e.preventDefault(); listenEdCut(); return; }
    if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); listenSave(true); return; }
    if (e.code === 'KeyA') { e.preventDefault(); listenAuto(); return; }
    if (e.code === 'Escape' && lEd && lEd.sel) { e.preventDefault(); lEd.sel = null; listenEdRender(); return; }
    if (e.code === 'Digit1') listenTarget('start');
    else if (e.code === 'Digit2') listenTarget('var');
    else if (e.code === 'Digit3') listenTarget('end');
}
window.addEventListener('resize', () => { if (isShown('stage5-listen')) listenEdDraw(); });
