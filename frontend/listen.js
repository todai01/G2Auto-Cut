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
    LS = await pywebview.api.listen_mode('var');
    let how = await showBeautifulChoice('<b>Прослушка переменных</b><br><br>Есть ли уже <b>записи имён</b> (файлы «Гизат.wav»…)?<br><br>'
        + '<span class="tts-dim">Если записей нет, а есть только таблица с именами — выберите второй вариант: имена синтезируются по одному, '
        + 'прямо здесь, при прослушке.</span>', 'Есть записи', 'Только таблица — синтез', 'S', 'Отмена');
    if (!how) return;
    if (how === 'alt') return listenStartTableOnly();
    let ok = await showBeautifulAlert('<b>Прослушка переменных · шаг 1 из 3</b><br><br>Выберите <b>папку с записями переменных</b> — '
        + 'файлы, названные как значения (например, «Гизат.wav»). Подпапки тоже смотрю.');
    if (!ok) return;
    let r = await pywebview.api.listen_pick_folder();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    try { if (localStorage.getItem('gvox_listen_auto') === '0') LS = await pywebview.api.listen_set(null, null, null, null, null, false); } catch (e) {}
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

// ----- «Только таблица»: записей нет — имена синтезируются по одному (R) и сразу слушаются -----
async function listenStartTableOnly() {
    let ok = await showBeautifulAlert('<b>Только таблица · шаг 1 из 3</b><br><br><b>Таблица с именами</b> (.xlsx): список имён в одной колонке — '
        + 'шапку («Имя») пропущу, колонку найду сам.');
    if (!ok) return;
    let r = await pywebview.api.listen_pick_table();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    ok = await showBeautifulAlert(`<b>Шаг 2 из 3</b><br><br>В таблице имён: <b>${r.rows.length}</b>.<br><br>Выберите <b>папку для результата</b> — туда лягут синтезированные имена `
        + '(можно создать новую пустую). Записи в ней не нужны.');
    if (!ok) return;
    r = await pywebview.api.listen_pick_output();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    ok = await showBeautifulAlert('<b>Шаг 3 из 3</b><br><br>Папка <b>«Фразы_Переменные»</b> с вашей <b>начальной фразой</b> (start): по её громкости выравнивается каждое имя, '
        + 'и имя слышно внутри фразы. Отметьте «Начало» (и «Конец», если есть).');
    if (ok) {
        r = await pywebview.api.listen_pick_phrases();
        if (r && r.error && r.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(r.error));
        if (r && !r.error) { LS = r; await listenPhrOpen(); }
    }
    listenOpen();
    if (await listenVoiceReady()) {                                  // голос и образец — сразу, дальше имена синтезируются сами
        let pos = LS.pos; LS = await pywebview.api.listen_autosynth_kick(); LS.pos = pos;
        listenRenderList(); listenRenderSynth();
        showToast('Авто-синтез: первое имя уже синтезируется. Слушайте, Enter — сохранить; следующее синтезируется само и сразу звучит', 8000);
    }
}

// ----- режим «Фразы»: текст из таблицы + запись с этим названием (папка с ru / kz) -----
// Свои папка, таблица и позиция у каждого режима; переключатель — в шапке.
async function listenStartPhrases() {
    LS = await pywebview.api.listen_mode('phrase');
    await listenSetupPhrases();
}
async function listenSetupPhrases() {
    let ok = await showBeautifulAlert('<b>Прослушка фраз · шаг 1 из 2</b><br><br>Выберите <b>папку с записями фраз</b>. Если внутри папки <b>ru</b> и <b>kz</b> — язык переключается '
        + 'тумблером RU / KZ. Файлы названы так, как в таблице; подпапки тоже смотрю.');
    if (!ok) return;
    let r = await pywebview.api.listen_pick_folder();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    ok = await showBeautifulAlert(`<b>Шаг 2 из 2</b><br><br>Найдено записей: <b>${r.files}</b>.<br><br><b>Таблица с фразами</b> (.xlsx): колонка с текстом (<b>&lt;phrase&gt;</b>, `
        + '<b>&lt;phrase_ru&gt;</b>, <b>&lt;phrase_kz&gt;</b>) и колонка с названием файла (<b>&lt;name_phrase&gt;</b>…). Без шапки: колонка A — текст, B — название файла.');
    if (!ok) return;
    r = await pywebview.api.listen_pick_table();
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    LS = r;
    listenOpen();
    showToast(`Фраз: ${r.rows.length} · есть запись у ${r.found}${r.skipped ? ` · без названия или текста пропущено ${r.skipped}` : ''}`, 4500);
}
const listenModeBtns = () => [['phrase', 'Фразы'], ['var', 'Переменные']].map(([m, t]) =>
    `<button type="button" class="${LS.mode === m ? 'is-on' : ''}" onclick="listenModeSet('${m}')">${t}</button>`).join('');
async function listenModeSet(m) {
    if (!LS || LS.mode === m) return;
    if (!(await listenLeave())) return;
    listenAutoSet(false); listenStopHead(); pywebview.api.listen_stop();
    LS = await pywebview.api.listen_mode(m);
    lEd = null; lAsm = {};
    if (m === 'phrase' && (!LS.folder || !LS.rows.length)) { listenOpen(); await listenSetupPhrases(); return; }
    listenOpen();
}

function listenOpen() {
    showStage('stage5-listen');
    if (lEl('listenGap')) lEl('listenGap').value = String(lAutoGap);
    let ctx = null; try { ctx = localStorage.getItem('gvox_listen_ctx'); } catch (e) {}
    if (ctx && +ctx !== LS.ctx_ms) listenSetCtx(ctx);
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
    if (what === 'table' && r.skipped) showToast(`Без названия файла или текста пропущено строк: ${r.skipped}`, 4500);
}

// ----- отрисовка -----
function listenRender(light) {
    if (!LS) return;
    let phr = LS.mode === 'phrase';
    lEl('stage5-listen').dataset.lmode = LS.mode || 'var';
    lEl('listenTitle').innerText = phr ? 'Прослушка фраз' : 'Прослушка переменных';
    lEl('listenModeSw').innerHTML = listenModeBtns();
    lEl('listenPickFolder').title = phr ? 'Папка с записями фраз (внутри можно ru и kz)' : 'Папка с записями переменных';
    lEl('listenPickTable').title = phr ? 'Таблица с фразами: текст и название файла' : 'Таблица с названиями переменных';
    lEl('listenLangTop').innerHTML = listenLangBtns();
    lEl('listenMeta').innerText = (phr ? [LS.folder_name && `папка «${LS.folder_name}» · ${LS.files} записей`, listenLangName(LS.lang)]
        : [LS.folder_name && `папка «${LS.folder_name}» · ${LS.files} записей`, listenLangName(LS.lang),
        LS.start ? `начало: ${LS.start}` : 'начало: нет', LS.end ? `конец: ${LS.end}` : 'конец: нет']).filter(Boolean).join(' · ');
    lEl('listenShort').checked = !!LS.short;
    lEl('listenNorm').checked = LS.norm !== false;
    lEl('listenAutoOn').checked = LS.auto_on !== false;
    lEl('listenCtx').value = String(LS.ctx_ms);
    if (light) listenMarkList(); else listenRenderList();
    let r = lRow();
    lEl('listenPos').innerText = r ? `${LS.pos + 1} / ${LS.rows.length}` : 'Загрузите таблицу';
    listenStatusRender();
    lEl('listenName').innerText = r ? r.name : '—';
    lEl('listenPhrase').innerText = phr && r && r.text ? r.text : '';
    lEl('listenName').classList.toggle('is-miss', !!r && !r.path);
    listenStatusRender();
    lEl('listenFile').innerHTML = !r ? '' : r.path
        ? `${r.dir ? `<span class="listen-dir">${escapeHtml(r.dir)}/</span>` : ''}${escapeHtml(r.file)}${r.uni ? ' · <span class="listen-uni">универсал — RU и KZ</span>' : ''}${r.dups ? ` · <span class="listen-warn">в папке ещё ${r.dups} с тем же именем</span>` : ''}${r.edited ? ' · правилась' : ''}`
        : 'записи с таким именем в папке нет — синтез (R)';
    if (phr) { listenRenderSynth(); return; }                     // фразы: цепочки начало → имя → конец нет
    let part = (t, label, name, ok) => `<button type="button" class="listen-part ${lTarget === t ? 'is-on' : ''} ${ok ? '' : 'is-miss'}" ${ok ? '' : 'disabled'}
            onclick="listenTarget('${t}')" title="${ok ? 'Править' + (t === 'var' ? ' запись переменной' : ' фразу целиком') : ''}">
            <i>${label}</i><b>${escapeHtml(name || '—')}</b>${ok ? '<span>✎</span>' : ''}</button>`;
    let ctx = (LS.ctx_ms / 1000).toLocaleString('ru-RU');
    lEl('listenChain').innerHTML = part('start', 'начало', LS.start, !!LS.start_path)
        + '<span class="listen-arrow">→</span>' + part('var', 'имя', r && r.name, !!(r && r.path))
        + '<span class="listen-arrow">→</span>' + part('end', 'конец', LS.end, !!LS.end_path);
    listenRenderSynth();
    if (!light) lAsm = {};                               // волны начала / конца / имени — заново с диска: всегда как звучит
    listenAsmEnsure();
}
function listenRenderList() {
    if (!LS) return;
    let q = (lEl('listenFilter').value || '').trim().toLowerCase();
    lEl('listenList').innerHTML = LS.rows.map((r, k) => ({ r, k })).filter(({ r }) => (!q || r.name.toLowerCase().includes(q)) && (!lFlagOnly || r.flag) && (!lTodoOnly || listenIsTodo(r))).map(({ r, k }) =>
        `<button type="button" class="listen-row ${k === LS.pos ? 'is-on' : ''} ${listenRowCls(r)}" data-k="${k}" onclick="listenGo(${k})">
            <span class="listen-row__dot"></span><span class="listen-row__name">${escapeHtml(r.name)}</span>
            <span class="listen-row__tag">${r.synth === 'busy' ? 'синтез…' : r.synth === 'ready' ? 'синтез ✓' : r.edited ? 'правка' : r.path ? '' : 'нет'}</span></button>`).join('');
    listenStatRender();
    let on = lEl('listenList').querySelector('.is-on');
    if (on) on.scrollIntoView({ block: 'nearest' });
}

// Кружок: красный — записи нет, жёлтый — есть, ещё не сохранена, зелёный — сохранена
const listenRowCls = r => r.flag ? 'is-flag' : !r.path ? 'is-miss' : r.done ? '' : 'is-todo';
// Статус текущей записи — плашка над именем
function listenStatusRender() {
    let el = lEl('listenStatus'), r = lRow();
    if (!el) return;
    let [c, t] = !r ? ['', ''] : r.synth === 'busy' ? ['is-busy', 'Синтез…'] : r.flag ? ['is-flag', 'Исправить']
        : !r.path ? ['is-miss', 'Нет записи'] : r.done ? ['is-done', 'Сохранена'] : ['is-todo', 'Не проверена'];
    el.className = 'lp-status ' + c; el.innerText = t;
}
function listenStatRender() {
    listenTotalsSoon();
    let n = LS.rows.length, done = LS.rows.filter(r => r.path && r.done).length;
    let fl0 = LS.rows.filter(r => r.flag).length;
    lEl('listenProgNum').innerText = `${done} / ${LS.found}`;
    lEl('listenProgBar').style.width = LS.found ? `${Math.round(done / LS.found * 1000) / 10}%` : '0';
    lEl('listenStat').innerText = n ? [`не проверено ${LS.rows.filter(listenIsTodo).length}`, fl0 && `исправить ${fl0}`, n > LS.found && `без записи ${n - LS.found}`].filter(Boolean).join(' · ') : '';
    let fl = LS.rows.filter(r => r.flag).length, b = lEl('listenFlagMode');
    if (b) { b.innerHTML = `Помеченные <b>${fl}</b>`; b.classList.toggle('is-on', lFlagOnly); }
    let td = lEl('listenTodoMode');
    if (td) { td.innerHTML = `Не проверены <b>${LS.rows.filter(listenIsTodo).length}</b>`; td.classList.toggle('is-on', lTodoOnly); }
    if (lEl('listenFlagAll')) lEl('listenFlagAll').classList.toggle('is-on', !lFlagOnly && !lTodoOnly);
}
// Шаг по списку — без перерисовки всех строк: только отметка текущей
function listenMarkList() {
    let list = lEl('listenList'), old = list.querySelector('.listen-row.is-on'), cur = list.querySelector(`.listen-row[data-k="${LS.pos}"]`);
    if (old && old !== cur) old.classList.remove('is-on');
    if (cur) {
        cur.classList.add('is-on');
        let r = LS.rows[LS.pos], tag = cur.querySelector('.listen-row__tag');
        cur.classList.remove('is-miss', 'is-todo', 'is-flag');
        let c = listenRowCls(r); if (c) cur.classList.add(c);
        if (tag) tag.innerText = r.synth === 'busy' ? 'синтез…' : r.synth === 'ready' ? 'синтез ✓' : r.edited ? 'правка' : r.path ? '' : 'нет';
        cur.scrollIntoView({ block: 'nearest' });
    }
}

// ----- навигация: один вызов — сразу звук, волна и эта строка -----
async function listenGo(k) {
    if (!LS || k === LS.pos) return;
    if (!(await listenLeave())) return;
    listenStopHead();
    LS.pos = k; lTarget = 'var'; lAsm = {};
    listenRender(true);                                  // имя — крупно сразу, не дожидаясь звука
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_go(k);
    if (!r || r.error || LS.pos !== k) return;           // уже ушли дальше
    LS.rows[k] = r.row;
    listenRender(true);
    listenSetEditor(r.edit || null, r.row.path);
    lPlayKind = 'chain';
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
// Автонастройка (срезка по голосу, громкость) при открытии записи: выключили — запись как есть, «Авто» (A) — по нажатию
async function listenSetAutoOn(on) {
    let pos = LS.pos;
    LS = await pywebview.api.listen_set(null, null, null, null, null, on); LS.pos = pos;
    try { localStorage.setItem('gvox_listen_auto', on ? '1' : '0'); } catch (e) {}
    listenRender(true);
    showToast(on ? 'Автонастройка включена: новые записи срезаются по голосу и выравниваются по громкости'
                 : 'Автонастройка выключена: записи звучат как есть. «Авто» (A) — применить к этой', 5000);
    await listenLoadEditor();
}
// Громкость имён — по фразам «Фразы_Переменные»: вкл. — «Авто» и первая срезка подбирают дБ под них
async function listenSetNorm(on) {
    let pos = LS.pos;
    LS = await pywebview.api.listen_set(null, null, null, null, on); LS.pos = pos;
    listenRender(true);
    if (lEd && lEd.target === 'var' && (!listenDirty() || lEd.auto)) await listenAuto();
    showToast(on ? 'Громкость имён — по громкости фраз' : 'Громкость имён — как в записи');
}
async function listenSetShort(on) { LS = await pywebview.api.listen_set(null, null, on); listenRender(); }
async function listenSetCtx(ms) {
    let pos = LS.pos;
    LS = await pywebview.api.listen_set(null, null, null, +ms); LS.pos = pos;
    try { localStorage.setItem('gvox_listen_ctx', ms); } catch (e) {}
    listenRender(true);
}
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
    lEl('listenEd').classList.remove('is-empty'); lAsm = {}; setTimeout(listenAsmEnsure, 0);
    lEd = { ...r, target: lTarget, sel: null, cur: 0, head: null, hist: [], reveal: lRevealNext ? performance.now() : null };
    lRevealNext = false;
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
function listenPush() { listenAutoPause(); lEd.hist.push(listenSnap()); if (lEd.hist.length > 100) lEd.hist.shift(); }

function listenEdRender() {
    let bar = lEl('listenEdBar');
    lEl('listenEd').classList.toggle('is-empty', !lEd && !listenSynthBusy());
    if (!lEd) {
        lEl('listenEdTitle').innerText = listenSynthBusy() ? `Синтез «${lRow().name}»…`
            : LS && LS.rows.length && lTarget === 'var' && !(lRow() || {}).path ? 'Записи нет — синтез ниже (R)' : '';
        bar.innerHTML = '';
        listenEdDraw();
        return;
    }
    let kind = { var: LS.mode === 'phrase' ? 'фраза' : 'переменная', start: 'начало фразы (целиком)', end: 'конец фразы (целиком)' }[lEd.target];
    let au = lEd.auto, sec = ms => (ms / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 2 });
    let autoTxt = au ? ` · <span class="listen-auto">срезано по голосу${au.breath ? ` · вдох / шум ${sec(au.breath)} с` : ''}${au.by_tpl ? ` · по шаблону «${escapeHtml(au.by_tpl)}»` : ''}</span>` : '';
    lEl('listenEdTitle').innerHTML = listenSynthBusy() ? `Синтез «${escapeHtml(lRow().name)}»…`
        : `${escapeHtml(lEd.name)} <span class="tts-dim">· ${kind}</span>${autoTxt}`;
    let sel = lEd.sel ? Math.round(lEd.sel.b - lEd.sel.a) : 0, len = lKept() / (lEd.tempo || 1);
    bar.innerHTML = `
        <span class="lp-group">
            <button onclick="listenEdCut()" ${lEd.sel ? '' : 'disabled'} title="Убрать выделенное">Вырезать <kbd>X</kbd></button>
            <button onclick="listenEdKeep()" ${lEd.sel ? '' : 'disabled'} title="Оставить только выделенное">Оставить</button>
            <button onclick="listenEdUndo()" ${lEd.hist.length ? '' : 'disabled'} title="Отменить шаг (Ctrl+Z)">&#8630;</button>
            <button onclick="listenEdReset()" title="Вся исходная запись, громкость 0, темп 100%">Как было</button></span>
        <span class="lp-group" title="Громкость: + / − на клавиатуре"><span>дБ</span><button onclick="listenKnob('gain', -1)">&minus;</button><b>${lEd.gain > 0 ? '+' : ''}${lEd.gain}</b><button onclick="listenKnob('gain', 1)">+</button></span>
        <span class="lp-group" title="Темп (без смены высоты): NumPad 8 — быстрее, NumPad 2 — медленнее"><span>темп</span><button onclick="listenKnob('tempo', -0.03)">&minus;</button><b>${Math.round(lEd.tempo * 100)}%</b><button onclick="listenKnob('tempo', 0.03)">+</button></span>
        <span class="lp-group lp-edges" title="Края дорожки с клавиатуры: NumPad 1 / 3 — выбрать левый / правый край, NumPad 4 / 6 — сдвинуть влево / вправо (шаг 10 мс, Shift — 50 мс), Esc — снять выбор"><span>край</span>
            <button class="${lEd.edge === 'a' ? 'is-on' : ''}" onclick="listenEdgeSet('a')">левый <kbd>1</kbd></button>
            <button class="${lEd.edge === 'b' ? 'is-on' : ''}" onclick="listenEdgeSet('b')">правый <kbd>3</kbd></button>
            <button onclick="listenEdgeStep(-1)" title="Край влево (4)">&#9664;</button><button onclick="listenEdgeStep(1)" title="Край вправо (6)">&#9654;</button></span>
        ${lEd.target === 'var' ? `<span class="lp-group"><button onclick="listenAuto()" title="Срезать по голосу: вдох и шум по краям — прочь, тишина, громкость и темп — по шаблону">Авто <kbd>A</kbd></button>
        <button onclick="listenTplSet()" title="${LS.tpl ? `Сейчас шаблон — «${escapeHtml(LS.tpl.from)}». ` : 'Шаблона нет — первая сохранённая станет им. '}Тишина до / после голоса, громкость и темп этой записи — для остальных">Шаблон из этой</button></span>` : ''}
        ${`<span class="lp-group"><button onclick="listenToAudacity()" title="Запись на экране (с правкой) — в Audacity, чистый проект">В Audacity</button>
        <button onclick="listenFromAudacity()" title="Забрать из Audacity то, что на дорожках, в эту запись (прежняя — в «_до_правок»)">Из Audacity</button></span>`}
        <span class="tts-ed__spacer"></span>
        <span class="lp-len">${(len / 1000).toFixed(2)} с${sel ? ` · выделено ${sel} мс` : ''}</span>
        ${lEd.target === 'var' && lRow() && lRow().done ? '<button class="lp-link" onclick="listenUnsave(LS.pos)" title="Запись — как до сохранения: подправить и сохранить заново (Ctrl+Z сразу после сохранения)">Отменить сохранение</button>'
          : lEd.has_backup ? '<button class="lp-link" onclick="listenRestore()" title="Записать обратно исходник из «_до_правок»">Вернуть исходник</button>' : ''}`;
    listenEdDraw();
}
// Синтез этой строки идёт — на дорожке «дышащая» заглушка
const listenSynthBusy = () => lTarget === 'var' && !!lRow() && lRow().synth === 'busy';
let lAnimRaf = null, lRevealNext = false;
function listenAnimLoop() {
    if (lAnimRaf) return;
    lAnimRaf = requestAnimationFrame(() => { lAnimRaf = null; if (isShown('stage5-listen')) listenEdDraw(); });
}
let lSkel = null;                  // {k, t0} — когда началась заглушка (для плавного входа)
function listenEdSkeleton(g, w, h, now, color, k = 1) {
    let mid = h / 2, n = Math.max(12, Math.floor(w / 7)), bw = Math.max(2, w / n - 3);
    for (let i = 0; i < n; i++) {
        let env = Math.pow(Math.sin(Math.PI * (i + 0.5) / n), 0.7);
        let a = env * (0.18 + 0.5 * Math.abs(Math.sin(now / 320 - i * 0.32)) * (0.6 + 0.4 * Math.sin(now / 900 + i * 0.07)));
        let y = Math.max(1, a * (mid - 10) * k);
        g.globalAlpha = (0.25 + 0.55 * env) * k;
        g.fillStyle = color;
        g.fillRect(i * (w / n) + 1.5, mid - y, bw, y * 2);
    }
    let sx = ((now / 1400) % 1.4 - 0.2) * w, grad = g.createLinearGradient(sx - 80, 0, sx + 80, 0);  // блик бежит слева направо
    grad.addColorStop(0, 'rgba(255,255,255,0)'); grad.addColorStop(.5, 'rgba(255,255,255,.10)'); grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.globalAlpha = k; g.fillStyle = grad; g.fillRect(sx - 80, 0, 160, h);
    g.globalAlpha = 1;
}
// Вход в загрузку — появление наоборот: прежняя волна стирается справа налево до front (px)
function listenEdWipe(g, w, h, front, color) {
    if (!lEd || front <= 0) return;
    let mid = (h - 16) / 2, bw = w * lEd.bucket / lEd.dur;
    g.fillStyle = color;
    for (let t = 0; t < lEd.dur; t += lEd.bucket) {
        let px = t / lEd.dur * w;
        if (px > front) break;
        let p = lEd.peaks[Math.floor(t / lEd.bucket)] || 0, near = Math.min(1, (front - px) / 60);   // у фронта — опадает
        let y = Math.max(1, p * (mid - 6) * near);
        g.fillRect(px, mid - y, Math.max(1, bw - (bw > 3 ? 1 : 0)), y * 2);
    }
}
function listenEdDraw() {
    listenAsmDraw();
    let cv = lEl('listenEdCanvas'), dpr = window.devicePixelRatio || 1;
    let w = cv.clientWidth, h = cv.clientHeight;
    if (!w) return;
    if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    let g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    let css = getComputedStyle(document.documentElement), varColor = css.getPropertyValue('--accent-var').trim() || '#fbbf24';
    if (listenSynthBusy()) {
        let now = performance.now();
        if (!lSkel || lSkel.k !== LS.pos) lSkel = { k: LS.pos, t0: now };
        let p = Math.min(1, (now - lSkel.t0) / 600), e = 1 - Math.pow(1 - p, 3);   // та же кривая, что у появления
        let front = (1 - e) * w * 1.05;
        listenEdWipe(g, w, h, lEd ? front : 0, varColor);
        g.save(); g.beginPath(); g.rect(lEd ? front : 0, 0, w, h); g.clip();             // за фронтом — заглушка
        listenEdSkeleton(g, w, h, now, varColor, lEd ? 1 : e);
        g.restore();
        listenAnimLoop(); return;
    }
    lSkel = null;
    if (!lEd) return;
    let rv = lEd.reveal ? Math.min(1, (performance.now() - lEd.reveal) / 600) : 1;     // готовый синтез проявляется
    if (rv < 1) listenAnimLoop(); else lEd.reveal = null;
    let ease = 1 - Math.pow(1 - rv, 3);
    let x = ms => ms / lEd.dur * w, rul = 16, H = h - rul, mid = H / 2;
    let kept = t => lEd.ranges.some(([a, b]) => t >= a && t < b);
    let bar = (x0, y0, bw, bh) => { if (g.roundRect && bw >= 2) { g.beginPath(); g.roundRect(x0, y0, bw, bh, Math.min(1.5, bw / 2)); g.fill(); } else g.fillRect(x0, y0, bw, bh); };
    g.fillStyle = 'rgba(255,255,255,.05)'; g.fillRect(0, mid, w, 1);                      // нулевая линия
    let bw = w * lEd.bucket / lEd.dur, gap = bw > 3 ? 1 : 0;
    for (let t = 0; t < lEd.dur; t += lEd.bucket) {
        if (x(t) > ease * w * 1.05) break;
        let p = lEd.peaks[Math.floor(t / lEd.bucket)] || 0, y = Math.max(1, p * (mid - 6) * Math.min(1, ease * 1.3));
        g.fillStyle = kept(t) ? varColor : 'rgba(255,255,255,.16)';
        bar(x(t), mid - y, Math.max(1, bw - gap), y * 2);
    }
    let a0 = lEd.ranges[0][0], b1 = lEd.ranges[lEd.ranges.length - 1][1];
    g.fillStyle = 'rgba(0,0,0,.38)';                                                       // срезанное по краям — в тень
    g.fillRect(0, 0, x(a0), H); g.fillRect(x(b1), 0, w - x(b1), H);
    lEd.ranges.slice(1).forEach(([a], i) => {                                             // вырезанное в середине
        let b = lEd.ranges[i][1]; g.fillStyle = 'rgba(229, 72, 77,.16)'; g.fillRect(x(b), 0, x(a) - x(b), H);
        g.fillStyle = 'rgba(229, 72, 77,.85)'; g.fillRect(x(b), 0, Math.max(2, x(a) - x(b)), 2);
    });
    if (lEd.sel) {
        let s0 = x(lEd.sel.a), s1 = x(lEd.sel.b);
        g.fillStyle = 'rgba(90,150,255,.22)'; g.fillRect(s0, 0, s1 - s0, H);
        g.fillStyle = 'rgba(90,150,255,.8)'; g.fillRect(s0, 0, 1, H); g.fillRect(s1 - 1, 0, 1, H);
    }
    let ec = css.getPropertyValue('--accent-info').trim() || '#2dd4b0';
    [a0, b1].forEach((t, i) => {                                                          // ручки краёв
        let px = Math.round(x(t)), on = lEd.edge === (i ? 'b' : 'a');
        if (on) {                                                                         // выбранный клавишей край — цветной, со свечением и подписью
            g.save(); g.shadowColor = ec; g.shadowBlur = 12; g.fillStyle = ec; g.fillRect(px - 1.5, 0, 3, H); g.restore();
            g.fillStyle = ec; g.globalAlpha = 0.16; g.fillRect(i ? px - 46 : px, 0, 46, H); g.globalAlpha = 1;
            g.fillStyle = ec; bar(px - 5, mid - 14, 10, 28);
            g.fillStyle = 'rgba(0,0,0,.5)'; g.fillRect(px - 1, mid - 6, 2, 12);
            g.save(); g.font = '600 10.5px ' + (css.getPropertyValue('--font-ui').trim() || 'sans-serif'); g.textBaseline = 'top'; g.textAlign = i ? 'right' : 'left';
            g.fillStyle = ec; g.fillText(i ? 'правый край  ◂ 4 · 6 ▸' : 'левый край  ◂ 4 · 6 ▸', i ? px - 8 : px + 8, 4); g.restore();
        } else {
            g.fillStyle = 'rgba(255,255,255,.9)'; g.fillRect(px - 1, 0, 2, H);
            g.fillStyle = '#fff'; bar(px - 4, mid - 11, 8, 22);
            g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(px - 1, mid - 5, 2, 10);
        }
    });
    g.fillStyle = 'rgba(90,150,255,.9)'; g.fillRect(x(lEd.cur) - 0.5, 0, 1, H);
    if (lEd.head !== null) {
        let gc = css.getPropertyValue('--accent-good').trim() || '#34d399';
        g.save(); g.shadowColor = gc; g.shadowBlur = 8; g.fillStyle = gc; g.fillRect(x(lEd.head) - 1, 0, 2, H); g.restore();
    }
    // шкала времени
    let step = lEd.dur > 6000 ? 1000 : lEd.dur > 2500 ? 500 : lEd.dur > 1000 ? 250 : 100;
    g.fillStyle = 'rgba(255,255,255,.06)'; g.fillRect(0, H, w, 1);
    g.font = '10px ' + (css.getPropertyValue('--font-mono').trim() || 'monospace'); g.textBaseline = 'top';
    for (let t = 0, k = 0; t <= lEd.dur; t += step, k++) {
        let px = Math.round(x(t)), major = k % 2 === 0;
        g.fillStyle = major ? 'rgba(255,255,255,.28)' : 'rgba(255,255,255,.12)';
        g.fillRect(px, H + 1, 1, major ? 5 : 3);
        if (major && px < w - 24) { g.fillStyle = 'rgba(255,255,255,.32)'; g.fillText((t / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 2 }), px + 3, H + 3); }
    }
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
    listenAutoPause();
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
        if (h.edge) lEd.edge = h.edge;                         // мышью взяли край — дальше им же управляют 4 / 6
        if (h.edge && moved) { lEd.hist.push(snap); }
        else if (!moved) { lEd.sel = null; lEd.cur = start; }
        else lEd.cur = lEd.sel.a;
        listenEdRender();
        if (!moved) listenPlayAt(start);                      // простой клик — слушать с этого места
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
// Края дорожки с клавиатуры: 1 / 3 — левый / правый край (подсвечивается на волне), 4 / 6 — сдвиг влево / вправо
// (левый край вправо — начало срезается, правый влево — конец), шаг 10 мс, Shift — 50 мс. Серия нажатий — один шаг отмены.
let lEdgeT = 0, lEdgeKey = null;
function listenEdgeSet(which) {
    if (!lEd) return;
    lEd.edge = which; listenEdRender();
}
function listenEdgeStep(dir, big) {
    if (!lEd) return;
    if (!lEd.edge) { showToast('Сначала выберите край: 1 — левый, 3 — правый', 2600); return; }
    let ms = big ? 50 : 10, F = lEd.ranges[0], L = lEd.ranges[lEd.ranges.length - 1];
    let cur = lEd.edge === 'a' ? F[0] : L[1];
    let next = Math.round(lEd.edge === 'a' ? Math.max(0, Math.min(F[0] + dir * ms, F[1] - 30)) : Math.min(lEd.dur, Math.max(L[1] + dir * ms, L[0] + 30)));
    if (next === cur) return;
    let now = performance.now();
    if (now - lEdgeT > 900 || lEdgeKey !== lEd.edge) listenPush();
    lEdgeT = now; lEdgeKey = lEd.edge;
    if (lEd.edge === 'a') F[0] = next; else L[1] = next;
    listenEdRender();
    listenReplaySoon();
}
function listenKnob(k, d) {
    if (!lEd) return;
    listenPush();
    if (k === 'gain') lEd.gain = Math.max(-12, Math.min(12, lEd.gain + d));
    else lEd.tempo = Math.round(Math.max(0.8, Math.min(1.25, lEd.tempo + d)) * 100) / 100;
    listenEdRender();
    listenReplaySoon();
}
// Шла прослушка — переиграть с новой громкостью / темпом (после паузы в нажатиях)
let lReplayT = null, lPlayKind = 'chain';
function listenReplaySoon() {
    if (!lPlay) return;
    clearTimeout(lReplayT);
    lReplayT = setTimeout(() => {
        if (!lPlay) return;
        listenStopHead(); pywebview.api.listen_stop();
        lPlayKind === 'only' ? listenPlayOnly() : listenPlayChain();
    }, 350);
}
// next — после сохранения переменной перейти к следующей строке (и сразу её послушать)
let lLastSaved = null;              // последняя сохранённая строка — Ctrl+Z отменит
// Следующая несохранённая строка после from (жёлтая; withMiss — и красная, без записи)
function listenNextTodo(from, withMiss) {
    let n = LS.rows.length;
    if (lTodoOnly) {                                       // «Не проверены»: следующая жёлтая (по кругу)
        for (let i = 1; i <= n; i++) { let k = (from + i) % n; if (k !== from && listenIsTodo(LS.rows[k])) return k; }
        return -1;
    }
    if (lFlagOnly) {                                       // второй круг: следующая помеченная (по кругу)
        for (let i = 1; i <= n; i++) { let k = (from + i) % n; if (LS.rows[k].flag && k !== from) return k; }
        return -1;
    }
    for (let k = from + 1; k < n; k++) {
        let r = LS.rows[k];
        if (r.flag) continue;                              // помеченные — на второй круг
        if (r.path ? !r.done : withMiss) return k;
    }
    return -1;
}
function listenNext() {
    let k = listenNextTodo(LS.pos, !lAuto);
    if (k < 0) {
        if (lAuto) listenAutoSet(false, 'Автопрогон: несохранённых записей дальше нет');
        else if (lFlagOnly) { showToast('Помеченных больше нет'); listenFlagMode(false); }
        else if (lTodoOnly) { showToast('Непроверенных больше нет'); listenFlagMode(false); }
        else listenStep(1);
        return;
    }
    listenGo(k);
}
async function listenSave(next) {
    if (!lEd) { if (next && lTarget === 'var' && LS && LS.pos < LS.rows.length - 1) listenNext(); return true; }
    // «Сохранить» переменной — сразу дальше, файл пишется в фоне (не ждём диска)
    if (next && lEd.target === 'var' && lRow() && lRow().path === lEd.path) { listenStopHead(); pywebview.api.listen_stop(); listenSaveBg(); return true; }
    let go = next && lEd.target === 'var' && LS.pos < LS.rows.length - 1;
    if (!listenDirty()) {
        if (lEd.target === 'var' && lRow() && !lRow().done) {          // хороша как есть — отметить сохранённой
            let r = await pywebview.api.listen_mark_done(lEd.path);
            if (r && r.state) { let pos = LS.pos; LS = r.state; LS.pos = pos; }
            lLastSaved = { pos: LS.pos, path: lEd.path };
            listenRenderList();
            if (!go) { listenRender(true); listenEdRender(); }
        }
        if (go) listenNext();
        return true;
    }
    let r = await pywebview.api.listen_edit_save(lEd.path, lEd.ranges, lEd.gain, lEd.tempo, lEd.target === 'var');
    if (!r || r.error) { showToast(r && r.error || 'Не сохранилось'); return false; }
    lEd.saved = listenSnap(); lEd.has_backup = true; lEd.auto = null; lEd.hist = []; lAsm = {};
    if (r.state) { let pos = LS.pos; LS = r.state; LS.pos = pos; }
    if (lEd.target === 'var') { lLastSaved = { pos: LS.pos, path: lEd.path }; listenMarkList(); listenRenderList(); }
    showToast(r.tpl_new ? `Сохранено: ${lEd.name} · стала шаблоном срезки для остальных` : `Сохранено: ${lEd.name}${go ? ' → дальше · Ctrl+Z — отменить' : ''}`);
    if (go) { listenNext(); return true; }
    listenRender(); listenEdRender();
    return true;
}
// «Отменить сохранение»: запись — как до сохранения (кружок снова жёлтый), срезка по голосу заново
async function listenUnsave(pos) {
    let row = LS.rows[pos];
    if (!row || !row.path) return;
    let r = await pywebview.api.listen_edit_restore(row.path);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    let keep = LS.pos; LS = r.state; LS.pos = keep; lAsm = {};
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
    LS = r.state; lAsm = {};
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
// seek — {kind, ms}: начать с места внутри куска (клик по дорожке); ms — от начала куска после правки
async function listenPlayChain(seek) {
    if (!LS) return;
    if (!seek && lPlay) { listenStopHead(); pywebview.api.listen_stop(); return; }
    lPlayKind = 'chain';
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_play(listenPart('var'), listenPart('start'), listenPart('end'), null, null, seek ? seek.kind : null, seek ? seek.ms : 0);
    listenAfterPlay(r, tok);
}
async function listenPlayOnly(seek) {
    if (!LS || !lEd) return;
    if (!seek && lPlay) { listenStopHead(); pywebview.api.listen_stop(); return; }
    let p = listenPart(lEd.target);
    lPlayKind = 'only';
    let tok = ++lPlayTok;
    let r = await pywebview.api.listen_play(lEd.target === 'var' ? p : null, lEd.target === 'start' ? p : null, lEd.target === 'end' ? p : null, lEd.target, null, seek ? seek.kind : null, seek ? seek.ms : 0);
    listenAfterPlay(r, tok);
}
// Клик по дорожке: звучит с этого места (в фразе — или один кусок, если шла «P»); идущий звук заменяется
function listenPlayAt(srcMs) {
    if (!LS || !lEd) return;
    let kept = 0;
    lEd.ranges.forEach(([a, b]) => { if (srcMs >= b) kept += b - a; else if (srcMs > a) kept += srcMs - a; });
    let seek = { kind: lEd.target, ms: Math.round(kept / lEd.tempo) };
    let only = lPlay && lPlayKind === 'only';
    clearTimeout(lReplayT);
    listenStopHead(); pywebview.api.listen_stop();
    only ? listenPlayOnly(seek) : listenPlayChain(seek);
}
// Головка на волне правки: где в цепочке звучит правленый кусок
function listenAfterPlay(r, tok) {
    if (tok !== lPlayTok) { if (r && !r.error) pywebview.api.listen_stop(); return; }
    if (!r || r.error) { if (r && r.error !== 'skip') showToast(r.error); return; }
    lEl('listenPlayBtn').classList.add('is-playing');
    let off = 0, mine = null;
    (r.marks || []).forEach(m => { if (lEd && m.kind === lEd.target) mine = { off, ms: m.ms }; off += m.ms; });
    lPlay = { t0: performance.now() - (r.from || 0), d: r.duration * 1000, mine };
    let step = () => {
        if (!lPlay) return;
        let t = performance.now() - lPlay.t0;
        if (t > lPlay.d) { let chain = lPlayKind === 'chain'; listenStopHead(); if (chain) listenAutoDone(); return; }
        if (lEd && lPlay.mine) {
            let local = t - lPlay.mine.off, kept = lKept(), tail = lEd.target === 'start' && LS.short ? Math.max(0, kept / lEd.tempo - lPlay.mine.ms) : 0;
            lEd.head = local >= 0 && local <= lPlay.mine.ms ? listenSrcAt((local + tail) * lEd.tempo) : null;
            listenEdDraw();
        }
        lPlay.raf = requestAnimationFrame(step);
    };
    lPlay.raf = requestAnimationFrame(step);
}
// ----- автопрогон: имя прозвучало, ничего не нажали — сохранить и дальше -----
let lAuto = false;
function listenAutoSet(on, msg) {
    lAuto = !!on;
    if (lEl('listenAutoBtn')) lEl('listenAutoBtn').classList.toggle('is-on', lAuto);
    if (msg) showToast(msg, 2600);
}
function listenAutoRun() {
    if (lAuto) { listenAutoSet(false, 'Автопрогон — пауза'); return; }
    listenAutoSet(true, 'Автопрогон: звучит — и само сохраняется. Любая клавиша — пауза');
    let r = lRow();
    if (r && r.path && !r.done) { listenStopHead(); pywebview.api.listen_stop(); listenPlayChain(); }
    else listenNext();
}
let lAutoGap = 600, lAutoGapT = null;
try { let g = localStorage.getItem('gvox_listen_gap'); if (g !== null) lAutoGap = +g; } catch (e) {}
function listenSetGap(ms) { lAutoGap = +ms; try { localStorage.setItem('gvox_listen_gap', ms); } catch (e) {} }
function listenAutoPause() { if (lAuto) listenAutoSet(false, 'Автопрогон — пауза на этом имени. G — дальше'); }
function listenAutoDone() {
    if (!lAuto || !isShown('stage5-listen')) return;
    let r = lRow();
    if (!r || !r.path || r.done || !lEd || lEd.target !== 'var' || lEd.hist.length) return;
    if (lPlay) return;
    if (!lAutoGap) { listenSaveBg(true); return; }
    clearTimeout(lAutoGapT);                                // пауза: имя ещё текущее — Backspace пометит его
    lAutoGapT = setTimeout(() => { if (lAuto && lRow() === r && !lPlay && !lEd.hist.length) listenSaveBg(true); }, lAutoGap);
}
// Сохранить в фоне и сразу дальше (автопрогон): кружок зелёный сразу, ошибка — вернём жёлтый
function listenSaveBg(auto) {
    let pos = LS.pos, row = lRow(), e = lEd;
    if (!row || !e) return;
    let dirty = listenDirty(), args = [e.path, e.ranges, e.gain, e.tempo, true, true];
    if (!dirty && row.done && !row.flag) { listenNext(); return; }      // уже сохранена, правок нет
    e.saved = listenSnap(); e.hist = [];
    row.done = true; row.flag = false; lLastSaved = { pos, path: e.path };
    lAutoMoved = auto ? { pos, t: performance.now() } : null;   // «поздний Backspace» — только после автоперехода
    let q = dirty ? pywebview.api.listen_edit_save(...args) : pywebview.api.listen_mark_done(e.path, true);
    q.then(r => {
        if (!r || r.error) { row.done = false; showToast(`Не сохранилось «${row.name}»: ${r && r.error || ''}`, 4000); }
        else if (r.tpl_new) { LS.tpl = r.tpl; showToast(`«${row.name}» — шаблон срезки для остальных`); }
        listenRenderRow(pos); listenStatRender();
    });
    if (lFlagOnly || lTodoOnly) listenRenderList(); else { listenRenderRow(pos); listenStatRender(); }
    listenNext();
}
function listenRenderRow(k) {
    let el = lEl('listenList').querySelector(`.listen-row[data-k="${k}"]`), r = LS.rows[k];
    if (k === LS.pos) listenStatusRender();
    if (!el || !r) return;
    el.classList.remove('is-miss', 'is-todo', 'is-flag');
    let c = listenRowCls(r); if (c) el.classList.add(c);
}
// ----- Backspace: «исправить потом» — пометить и дальше; второй круг — только помеченные -----
let lAutoMoved = null, lFlagOnly = false, lTodoOnly = false;
const listenIsTodo = r => !!r.path && !r.done && !r.flag;     // жёлтая: запись есть, не сохранена, не помечена
async function listenFlag() {
    if (!LS || !LS.rows.length) return;
    // нажали чуть позже, чем автопрогон перешёл, — помечаем то, что только что прозвучало
    // (пока у нового имени звучит только начало фразы — контекст, но не больше 0,8 с)
    let win = LS.short ? Math.min(800, LS.ctx_ms) : 300;
    let k = lAutoMoved && performance.now() - lAutoMoved.t < win && lAutoMoved.pos !== LS.pos ? lAutoMoved.pos : LS.pos;
    let row = LS.rows[k], on = !row.flag;
    if (on && k !== LS.pos && row.done) {                  // его уже успели сохранить — вернуть как было
        await pywebview.api.listen_edit_restore(row.path);
        row.done = false;
    }
    let r = await pywebview.api.listen_flag(k, on);
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS.rows[k] = { ...LS.rows[k], ...r.row };
    if (lFlagOnly || lTodoOnly) listenRenderList(); else { listenRenderRow(k); listenStatRender(); }
    showToast(on ? `«${row.name}» — исправить потом` : `«${row.name}»: пометка снята`, 1400);
    if (on && k === LS.pos && !lFlagOnly) {                // текущее — сразу дальше
        if (lEd) { lEd.hist = []; lEd.saved = listenSnap(); }   // правку не сохраняем и не спрашиваем
        listenStopHead(); pywebview.api.listen_stop();
        listenNext();
    }
}
function listenTodoMode() {
    lTodoOnly = true; lFlagOnly = false;
    listenAutoSet(false);
    listenRenderList();
    if (!LS.rows[LS.pos] || !listenIsTodo(LS.rows[LS.pos])) {
        let k = listenNextTodo(LS.pos, false);
        if (k < 0) { showToast('Непроверенных нет — всё проверено'); lTodoOnly = false; listenRenderList(); return; }
        listenGo(k);
    }
}
function listenFlagMode(on) {
    lTodoOnly = false;
    lFlagOnly = on === undefined ? !lFlagOnly : !!on;
    if (lFlagOnly) listenAutoSet(false);
    listenRenderList();
    if (lFlagOnly) {
        if (!LS.rows[LS.pos] || !LS.rows[LS.pos].flag) {
            let k = listenNextTodo(LS.pos, true);
            if (k < 0) { showToast('Помеченных нет'); lFlagOnly = false; listenRenderList(); return; }
            listenGo(k);
        }
        showToast('Второй круг: только помеченные. Исправили — Enter, дальше следующая');
    }
}
// время по оставленным кускам → время исходника
function listenSrcAt(t) {
    for (let [a, b] of lEd.ranges) { if (t <= b - a) return a + t; t -= b - a; }
    return null;
}

// ----- финальная папка для сдачи -----
async function listenExport() {
    if (!LS || !LS.rows.length) { showToast('Сначала откройте папку и таблицу'); return; }
    let seen = new Set(), done = 0, todo = 0;
    LS.rows.forEach(r => { if (!r.path || r.flag || seen.has(r.path)) return; seen.add(r.path); r.done ? done++ : todo++; });
    let fl = LS.rows.filter(r => r.flag).length, miss = LS.rows.filter(r => !r.path).length;
    let how = await showBeautifulChoice(`<b>Финальная папка</b><br><br>Только аудио, без «_до_правок», «_синтез» и служебных файлов; ru / kz — как в папке.<br><br>`
        + `Сохранено: <b>${done}</b> · не проверено: <b>${todo}</b> · помечено: <b>${fl}</b> · без записи: <b>${miss}</b><br><br>`
        + 'Дальше — выберите, куда положить папку.', `Только сохранённые (${done})`, 'Все найденные', 'A', 'Отмена');
    if (!how) return;
    showToast('Собираю финальную папку…', 2500);
    let r = await pywebview.api.listen_export(how === 'ok' ? 'done' : 'all');
    if (!r || r.error === 'cancel') return;
    if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
    let rest = [r.todo && `не проверено ${r.todo}`, r.flagged && `помечено ${r.flagged}`, r.missing && `без записи ${r.missing}`, r.failed && `не скопировалось ${r.failed}`].filter(Boolean);
    let open = await showBeautifulConfirm(`<b>Готово: ${r.copied} аудио</b><br><br><span style="font-family:var(--font-mono);font-size:12px">${escapeHtml(r.dest)}</span>`
        + (rest.length ? `<br><br>Не вошло: ${rest.join(' · ')} — список рядом с папкой, в «${escapeHtml(r.report.split(/[\\/]/).pop())}».` : ''), 'Открыть папку', 'Закрыть');
    if (open) pywebview.api.audit_open_folder(r.dest);
}

// ----- синтез -----
function listenRenderSynth() {
    let box = lEl('listenSynth'), r = lRow();
    if (!r) { box.innerHTML = ''; return; }
    let st = r.synth;
    let keep = lEl('listenSynthText'), sk = `${LS.lang}:${r.base}`, txt = keep && keep.dataset.k === sk ? keep.value : (LS.mode === 'phrase' && r.text) || r.name;
    box.innerHTML = `<span class="listen-synth__label">Синтез ${listenLangName(LS.lang === 'uni' ? 'ru' : LS.lang)}</span>
        <input class="listen-synth__text" id="listenSynthText" data-k="${sk}" value="${escapeHtml(txt)}" title="Текст для синтеза — можно поправить (ударение, написание)">
        <button class="listen-synth__go" onclick="listenSynthQuick()" ${st === 'busy' ? 'disabled' : ''} title="Синтез сразу встанет на дорожку вместо записи (прежняя — в «_до_правок»)">${st === 'busy' ? 'Синтезирую…' : 'Синтезировать <kbd>R</kbd>'}</button>
        ${st === 'ready' ? `<button class="btn-ghost btn-ghost--compact" onclick="listenSynthPlay()">&#9654; в фразе</button>
            <button class="btn-ghost btn-ghost--compact btn-ghost--good" onclick="listenSynthTake()">Взять</button>
            <button class="btn-ghost btn-ghost--compact" onclick="listenSynthDrop()">Отклонить</button>` : ''}
        ${st === 'error' ? '<span class="listen-warn">не получился — ещё раз</span>' : ''}
        <button class="btn-ghost btn-ghost--compact" onclick="listenVoicePick()" title="Голос синтеза: свой образец (файл + транскрипция), запись на экране или готовый голос сервиса">голос: ${escapeHtml(LS.voice ? LS.voice.label : 'не выбран')} ✎</button>
        <label class="listen-opt" title="В конце имени — знак вопроса («Гизат?»): так сервис даёт нужную интонацию"><input type="checkbox" ${LS.qmark ? 'checked' : ''} onchange="listenQmark(this.checked)"> «?» в конце</label>
        <label class="listen-opt" title="Имя без записи синтезируется само — это и два следующих: после сохранения (Enter) следующее уже готово и сразу звучит в фразе"><input type="checkbox" ${LS.autosynth ? 'checked' : ''} onchange="listenAutoSynthSet(this.checked)"> авто-синтез</label>
        ${listenVariantsHTML()}
        ${LS.synth_busy ? `<button class="btn-ghost btn-ghost--compact" onclick="listenSynthStop()" title="Снять очередь синтеза (идущий доделается)">Стоп (${LS.synth_busy})</button>`
          : `<button class="btn-ghost btn-ghost--compact" onclick="listenSynthAll()" title="Синтез всех строк без записи по очереди — каждое встанет на место записи (громкость — по начальной фразе, тишина и вдохи срезаны)">Синтезировать все без записи (${LS.rows.filter(x => !x.path && x.synth !== 'ready').length})</button>`}`;
    listenStatusRender(); listenEdRender();
}
const listenLangName = l => l === 'uni' ? 'УНИВ' : l.toUpperCase();
const listenLangBtns = (cur = LS.lang, fn = 'listenLang', langs = LS.split && LS.mode !== 'phrase' ? ['ru', 'kz', 'uni'] : ['ru', 'kz']) => langs.map(l =>
    `<button type="button" class="${cur === l ? 'is-on' : ''}" onclick="${fn}('${l}')" ${l === 'uni' ? 'title="Универсалы — марки без цифр: одна запись на оба языка"' : ''}>${listenLangName(l)}</button>`).join('');
// Язык — для всего: пара начало / конец, записи из ru / kz (если папка разделена) и синтез
async function listenLang(l) {
    if (!LS || l === LS.lang) return;
    if (!(await listenLeave())) return;
    listenStopHead(); pywebview.api.listen_stop();
    LS = await pywebview.api.listen_set(null, l);
    listenRender();
    await listenLoadEditor();
    if (lRow() && lRow().path) listenPlayChain();       // та же строка — сразу слышно на другом языке
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
        lPhr = { lang: LS.lang === 'uni' ? 'ru' : LS.lang, done };
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
    lEl('listenPhrLang').innerHTML = listenLangBtns(lPhr.lang, 'listenPhrLang', ['ru', 'kz']);
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
// Голос синтеза: «по образцу» (запись на экране, текст образца — название строки) или голос из списка сервиса
async function listenVoicePick() {
    showToast('Получаю список голосов с сервиса…', 3000);
    let r = await pywebview.api.listen_voices(false);
    let cur = LS.voice ? LS.voice.index : -1;
    let item = (i, label, desc) => `<label class="listen-voice__row"><input type="radio" name="listenVoice" value="${i}" ${i === cur ? 'checked' : ''}>
        <span><b>${escapeHtml(label)}</b>${desc ? `<small>${escapeHtml(desc)}</small>` : ''}</span></label>`;
    let html = `<b>Голос синтеза</b><br><br><div class="listen-voice">`
        + item(-2, 'Свой образец — файл и его транскрипция', LS.sample ? `«${LS.sample.name}»: «${LS.sample.text}» — выберите, потом можно загрузить другой` : 'загрузите аудио с голосом и напишите, что в нём сказано')
        + item(-1, 'По образцу — запись на экране', 'голос и интонация — из текущей записи (с правкой), текст образца — название строки')
        + (r && r.voices || []).map(v => item(v.index, v.label)).join('')
        + `</div>` + (r && r.error ? `<br><span class="listen-warn">Список голосов не получен: ${escapeHtml(r.error)}</span>` : '');
    if (!(await showBeautifulConfirm(html, 'Выбрать', 'Отмена'))) return false;
    let el = document.querySelector('input[name="listenVoice"]:checked');
    if (!el) return false;
    let i = +el.value, v = (r && r.voices || []).find(x => x.index === i);
    if (i === -2) return await listenSampleSet(!LS.sample);
    let pos = LS.pos; LS = await pywebview.api.listen_set_voice(i, v ? v.label : null); LS.pos = pos;
    listenRenderSynth();
    return true;
}
// Свой образец голоса: файл + транскрипция (что в нём сказано) — их сервис синтеза берёт как эталон
async function listenSampleSet(force) {
    let s = LS.sample, path = null;
    if (s && !force) {
        let how = await showBeautifulChoice(`<b>Образец голоса</b><br><br>«${escapeHtml(s.name)}» — «${escapeHtml(s.text)}»`, 'Взять этот', 'Загрузить другой', 'D', 'Отмена');
        if (!how) return false;
        if (how === 'ok') { let pos = LS.pos, r = await pywebview.api.listen_set_voice(-2); if (r && !r.error) { LS = r; LS.pos = pos; } listenRenderSynth(); return true; }
    }
    let f = await pywebview.api.listen_pick_sample();
    if (!f || f.error) return false;
    path = f.path;
    let ok = await showBeautifulConfirm(`<b>Транскрипция образца</b><br><br><span class="tts-dim">${escapeHtml(path.split(/[\\/]/).pop())}</span><br>Что именно сказано в этой записи — слово в слово:`
        + `<br><br><textarea id="listenSampleText" rows="3" style="width:100%"></textarea>`, 'Сохранить', 'Отмена');
    let t = ((document.getElementById('listenSampleText') || {}).value || '').trim();
    if (!ok) return false;
    let pos = LS.pos, r = await pywebview.api.listen_set_sample(path, t);
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return false; }
    LS = r; LS.pos = pos;
    listenRenderSynth();
    showToast('Образец голоса сохранён — синтез будет его голосом');
    return true;
}
// «3 варианта»: каждое имя таблицы синтезируется три раза → папки вариант_1 / вариант_2 / вариант_3 в папке результата
// (для веб-сервиса выбора вариантов). Готовые файлы пропускаются — можно остановить и продолжить.
function listenVariantsHTML() {
    let v = LS.variants, dur = s => { s = Math.max(0, Math.round(s)); return s >= 3600 ? `${Math.floor(s / 3600)} ч ${Math.floor(s / 60) % 60} мин` : `${Math.floor(s / 60)} мин`; };
    if (v && v.running)
        return `<span class="listen-variants" title="${escapeHtml(v.current || '')}">варианты: <b>${v.done}</b> из ${v.total}${v.eta_s ? ` · осталось ~${dur(v.eta_s)}` : ''}${v.errors_n ? ` · <span class="listen-warn">ошибок ${v.errors_n}</span>` : ''}</span>
            <button class="btn-ghost btn-ghost--compact" onclick="listenVariantsStop()" title="Идущее имя доделается, готовые варианты остаются">Стоп вариантов</button>`;
    return `<button class="btn-ghost btn-ghost--compact" onclick="listenVariantsStart()" title="Все имена таблицы — по 3 раза в папки вариант_1 / вариант_2 / вариант_3 (для веб-сервиса выбора)">${v && v.done ? `Варианты: ${v.done} из ${v.total} — продолжить` : '3 варианта всех имён'}</button>`;
}
async function listenVariantsStart() {
    if (!LS || !LS.rows.length) { showToast('Сначала загрузите таблицу с именами'); return; }
    if (!LS.folder) { showToast('Выберите папку результата (кнопка «Папка»)'); return; }
    if (!(await listenVoiceReady())) return;
    let n = LS.rows.length;
    if (!(await showBeautifulConfirm(`<b>3 варианта всех имён</b><br><br>Имён: <b>${n}</b> → синтезов: <b>${n * 3}</b>. Каждое имя синтезируется три раза подряд (сервис каждый раз даёт чуть разный результат), `
        + `файлы — в папки «вариант_1», «вариант_2», «вариант_3» внутри «${escapeHtml(LS.folder_name || '')}», целые, громкость по start-фразе${LS.qmark ? ', с «?» в конце' : ''}.<br><br>`
        + 'Можно остановить и запустить снова — готовое не пересинтезируется. Моноблок и браузер сервиса должны остаться открытыми.', 'Начать', 'Отмена'))) return;
    let pos = LS.pos, r = await pywebview.api.listen_variants_start(3);
    if (r && r.state) { LS = r.state; LS.pos = pos; }
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); }
    listenRenderSynth();
}
async function listenVariantsStop() {
    let pos = LS.pos, r = await pywebview.api.listen_variants_stop();
    if (r && r.state) { LS = r.state; LS.pos = pos; }
    listenRenderSynth();
    showToast('Останавливаю: идущее имя доделается, готовые варианты остаются');
}
async function listenAutoSynthSet(on) {
    if (on && !(await listenVoiceReady())) { listenRenderSynth(); return; }
    let pos = LS.pos; LS = await pywebview.api.listen_set_autosynth(on); LS.pos = pos;
    listenRenderList(); listenRenderSynth();
    if (on) showToast('Авто-синтез: имена без записи синтезируются сами, по мере прослушки');
}
async function listenQmark(on) { let pos = LS.pos; LS = await pywebview.api.listen_set_qmark(on); LS.pos = pos; listenRenderSynth(); }
async function listenSynthAll() {
    if (!(await listenVoiceReady())) return;
    let n = LS.rows.filter(x => !x.path && x.synth !== 'ready').length;
    if (!n) { showToast('У всех строк уже есть запись'); return; }
    if (!(await showBeautifulConfirm(`<b>Синтезировать все без записи: ${n}</b><br><br>Голос: ${escapeHtml(LS.voice.label)}${LS.qmark ? ' · с «?» в конце' : ''}.<br>`
        + 'Каждое имя встанет на место записи; громкость — по начальной фразе, тишина и вдохи по краям срезаны. Остановить — «Стоп».', 'Начать', 'Отмена'))) return;
    let pos = LS.pos, r = await pywebview.api.listen_synth_all(LS.lang);
    if (r && r.state) { LS = r.state; LS.pos = pos; }
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); }
    listenRenderList(); listenRenderSynth();
    if (r && r.queued) showToast(`В очереди синтеза: ${r.queued}`, 4000);
}
async function listenSynthStop() {
    let pos = LS.pos, r = await pywebview.api.listen_synth_stop();
    if (r && r.state) { LS = r.state; LS.pos = pos; }
    listenRenderList(); listenRenderSynth();
    showToast(`Очередь снята: ${r ? r.dropped : 0}${r && r.running ? ' · текущий доделается' : ''}`);
}
async function listenVoiceReady() { return !!LS.voice || await listenVoicePick(); }
async function listenSynth() {
    if (!(await listenVoiceReady())) return;
    let r = await pywebview.api.listen_synth(LS.pos, lEl('listenSynthText').value, LS.lang, false, listenPart('var'));
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    LS = r.state; listenRenderList(); listenRenderSynth();
    showToast('Синтез запущен — можно слушать другие строки');
}
// R: синтез этого имени — готовый сам встаёт вместо записи (на дорожку)
async function listenSynthQuick() {
    let row = lRow();
    if (!row) return;
    if (row.synth === 'busy') { showToast('Синтез уже идёт'); return; }
    if (!(await listenVoiceReady())) return;
    let inp = lEl('listenSynthText'), text = inp && inp.value.trim() ? inp.value.trim() : (LS.mode === 'phrase' && row.text) || row.name;
    let r = await pywebview.api.listen_synth(LS.pos, text, LS.lang, true, listenPart('var'));
    if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
    let pos = LS.pos; LS = r.state; LS.pos = pos;
    listenMarkList(); listenRenderSynth();
    showToast(`Синтез «${row.name}» (${listenLangName(LS.lang === 'uni' ? 'ru' : LS.lang)}) — встанет на дорожку сам, можно листать дальше`);
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
    listenRender(); await listenLoadEditor();             // на рабочем столе — синтез (уже срезан по голосу)
    showToast('Синтез — вместо прежней записи (она в «_до_правок»). Подрежьте и Enter — сохранить');
    listenPlayChain();
}
async function listenSynthDrop() { LS = await pywebview.api.listen_synth_drop(LS.pos); listenRender(); }
// Python → JS: синтез готов / ошибка
function listenEvent(p) {
    if (!p) return;
    if (p.state) { let pos = LS ? LS.pos : 0; LS = p.state; LS.pos = pos; }
    if (p.stage === 'variants') {
        if (LS) LS.variants = p.variants;
        if (isShown('stage5-listen')) listenRenderSynth();
        if (p.variants && !p.variants.running && p.variants.done >= p.variants.total) showToast(`Варианты готовы: ${p.variants.done} файлов — папки вариант_1 / 2 / 3`, 8000);
        return;
    }
    if (p.stage === 'synth') {
        let name = LS && LS.rows[p.k] ? LS.rows[p.k].name : '';
        let voice = p.voice ? ` · голос «${p.voice}»` : '';
        if (!p.ok || !p.taken || (LS && p.k === LS.pos))               // авто-синтез впрок (другие строки) — без уведомлений
            showToast(!p.ok ? `Синтез «${name}»: ${p.error}` : p.taken ? `Синтез «${name}» — на дорожке${voice}` : `Синтез готов: ${name}${voice} — «▶ Синтез в фразе»`, 4500);
        if (isShown('stage5-listen')) {
            listenRenderList();
            if (LS && p.k === LS.pos) {
                if (!p.ok) listenEdRender();
                if (p.ok && p.taken && !lAuto) {                     // мы на этом имени — сразу на дорожку и слушать
                    lTarget = 'var'; lRevealNext = true; listenRender(true);
                    listenLoadEditor().then(() => { listenStopHead(); pywebview.api.listen_stop(); listenPlayChain(); });
                } else if (p.ok && p.taken) { lAsm = {}; listenLoadEditor(); }   // файл заменён — волна тоже новая
                else listenRenderSynth();
            }
        }
    }
}

// ----- клавиши -----
function listenKey(e) {
    if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT')) return;
    if (e.code === 'KeyG') { e.preventDefault(); listenAutoRun(); return; }
    if (e.code === 'Backspace') { e.preventDefault(); listenFlag(); return; }  // пометить — автопрогон не останавливается
    if (e.code !== 'Enter' && e.code !== 'NumpadEnter') listenAutoPause();     // любая другая клавиша — пауза
    if (e.code === 'KeyR') { e.preventDefault(); listenSynthQuick(); return; }
    if (e.code === 'Space' || e.code === 'Numpad0') { e.preventDefault(); listenPlayChain(); return; }       // NumPad 0 — как Space
    // цифровой блок: 8 / 2 — темп; 1 / 3 — выбрать левый / правый край дорожки; 4 / 6 — двигать выбранный край (Shift — крупнее)
    if (e.code === 'Numpad8') { e.preventDefault(); listenKnob('tempo', 0.03); return; }
    if (e.code === 'Numpad2') { e.preventDefault(); listenKnob('tempo', -0.03); return; }
    if (e.code === 'Numpad1') { e.preventDefault(); listenEdgeSet('a'); return; }
    if (e.code === 'Numpad3') { e.preventDefault(); listenEdgeSet('b'); return; }
    if (e.code === 'Numpad4') { e.preventDefault(); listenEdgeStep(-1, e.shiftKey); return; }
    if (e.code === 'Numpad6') { e.preventDefault(); listenEdgeStep(1, e.shiftKey); return; }
    if (e.code === 'KeyP') { e.preventDefault(); listenPlayOnly(); return; }
    if (e.code === 'KeyM') { e.preventDefault(); listenSwap(); return; }
    if (e.code === 'KeyL') { e.preventDefault(); listenLang(({ ru: 'kz', kz: LS.split && LS.mode !== 'phrase' ? 'uni' : 'ru', uni: 'ru' })[LS.lang]); return; }
    if (e.code === 'ArrowDown' || e.code === 'KeyS') { e.preventDefault(); listenStep(1); return; }
    if (e.code === 'ArrowUp' || e.code === 'KeyW') { e.preventDefault(); listenStep(-1); return; }
    if (e.code === 'KeyX' || e.code === 'Delete') { e.preventDefault(); listenEdCut(); return; }
    if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); listenSave(true); return; }
    if (e.code === 'KeyA') { e.preventDefault(); listenAuto(); return; }
    // + / − (основная клавиатура и цифровой блок) — громкость правки на 1 дБ
    if (e.code === 'NumpadAdd' || e.code === 'Equal') { e.preventDefault(); listenKnob('gain', 1); return; }
    if (e.code === 'NumpadSubtract' || e.code === 'Minus') { e.preventDefault(); listenKnob('gain', -1); return; }
    if (e.code === 'Escape' && lEd && lEd.sel) { e.preventDefault(); lEd.sel = null; listenEdRender(); return; }
    if (e.code === 'Escape' && lEd && lEd.edge) { e.preventDefault(); lEd.edge = null; listenEdRender(); return; }
    if (e.code === 'Digit1') listenTarget('start');
    else if (e.code === 'Digit2') listenTarget('var');
    else if (e.code === 'Digit3') listenTarget('end');
}
window.addEventListener('resize', () => { if (isShown('stage5-listen')) listenEdDraw(); });

// ----- «Сборка»: вся цепочка волнами — начало → имя → конец, как слышно в фразе -----
// Клик по куску — править его (ниже, в редакторе). Имя — с текущей правкой, живьём.
let lAsm = {}, lAsmBusy = false, lAsmHit = [];
const lAsmParts = () => ['start', 'var', 'end'].map(t => ({ t, path: t === 'start' ? LS.start_path : t === 'end' ? LS.end_path : (lRow() || {}).path }));
let lAsmAgain = false;
async function listenAsmEnsure() {
    if (!LS) return;
    if (lAsmBusy) { lAsmAgain = true; listenAsmDraw(); return; }     // идёт загрузка — после неё проверим ещё раз
    lAsmBusy = true;
    try {
        for (let round = 0; round < 4; round++) {
            lAsmAgain = false;
            let need = lAsmParts().filter(p => p.path && !(lEd && lEd.target === p.t && lEd.path === p.path) && !lAsm[p.path]);
            if (!need.length && !lAsmAgain) break;
            for (let p of need) {
                let r = await pywebview.api.listen_edit_load(p.path);
                if (r && !r.error) lAsm[p.path] = r;
            }
            if (!lAsmAgain) break;
        }
    } finally { lAsmBusy = false; }
    listenAsmDraw();
}
// Звучащий кусок: куски, что оставили; «кратко» — только конец начала / начало продолжения
function lAsmSeg(p) {
    let d = lEd && lEd.target === p.t && lEd.path === p.path ? lEd : lAsm[p.path];
    if (!p.path || !d) return { t: p.t, miss: !p.path, ms: 0, peaks: [] };
    let bucket = d.bucket, peaks = [], ranges = d.ranges || [[0, d.dur]];
    let g = p.t === 'var' ? Math.pow(10, (d.gain || 0) / 20) : 1;
    ranges.forEach(([a, b]) => { for (let t = a; t < b; t += bucket) peaks.push(Math.min(1, (d.peaks[Math.floor(t / bucket)] || 0) * g)); });
    let keep = Math.round(LS.ctx_ms / bucket);
    if (LS.short && p.t === 'start') peaks = peaks.slice(-keep);
    if (LS.short && p.t === 'end') peaks = peaks.slice(0, keep);
    let tempo = p.t === 'var' ? (d.tempo || 1) : 1;
    return { t: p.t, peaks, bucket, ms: peaks.length * bucket / tempo, name: d.name };
}
function listenAsmDraw() {
    let cv = lEl('listenAsmCanvas');
    if (!cv || !LS) return;
    let dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    if (!w) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    let g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
    let css = getComputedStyle(document.documentElement), mono = css.getPropertyValue('--font-mono').trim() || 'monospace';
    let col = { start: css.getPropertyValue('--accent-info').trim() || '#2dd4b0', var: css.getPropertyValue('--accent-var').trim() || '#fbbf24',
                end: css.getPropertyValue('--accent-good').trim() || '#34d399' };
    let label = { start: 'НАЧАЛО', var: 'ИМЯ', end: 'КОНЕЦ' };
    let segs = lAsmParts().map(lAsmSeg), gap = 6, W = w - gap * 2;
    let total = segs.reduce((a, x) => a + Math.max(x.ms, 400), 0) || 1;
    let x0 = 0; lAsmHit = [];
    segs.forEach(sg => {
        let sw = Math.max(46, W * Math.max(sg.ms, 400) / total), c = col[sg.t], on = lTarget === sg.t;
        lAsmHit.push({ t: sg.t, x0, x1: x0 + sw, ok: !sg.miss });
        g.fillStyle = on ? 'rgba(255,255,255,.06)' : 'rgba(255,255,255,.025)'; g.fillRect(x0, 0, sw, h);
        g.strokeStyle = on ? c : 'rgba(255,255,255,.1)'; g.lineWidth = on ? 1.5 : 1; g.strokeRect(x0 + .5, .5, sw - 1, h - 1);
        let mid = (h + 12) / 2, n = sg.peaks.length;
        if (n) {
            let bw = sw / n;
            g.fillStyle = on ? c : c + '99';
            for (let i = 0; i < n; i++) {
                let y = Math.max(1, sg.peaks[i] * (h - 22) / 2);
                g.fillRect(x0 + i * bw, mid - y, Math.max(1, bw - (bw > 3 ? 1 : 0)), y * 2);
            }
        } else if (sg.miss) { g.fillStyle = 'rgba(255,255,255,.25)'; g.font = '11px ' + mono; g.fillText('нет записи', x0 + 10, mid + 4); }
        g.font = '10px ' + mono; g.textBaseline = 'top'; g.fillStyle = on ? c : 'rgba(255,255,255,.4)';
        g.fillText(label[sg.t] + (sg.ms ? '  ' + (sg.ms / 1000).toLocaleString('ru-RU', { maximumFractionDigits: 2 }) + ' с' : ''), x0 + 7, 4);
        x0 += sw + gap;
    });
}
document.addEventListener('DOMContentLoaded', () => {
    let cv = lEl('listenAsmCanvas');
    if (!cv) return;
    let at = e => { let x = e.clientX - cv.getBoundingClientRect().left; return lAsmHit.find(z => x >= z.x0 && x < z.x1); };
    cv.onclick = e => { let hit = at(e); if (hit && hit.ok) listenTarget(hit.t); };
    cv.onmousemove = e => { let hit = at(e); cv.style.cursor = hit && hit.ok ? 'pointer' : 'default'; };
});


// ----- «Не та запись»: в файле звучит другое название — меняем записи двух строк местами -----
async function listenSwap() {
    let r = lRow();
    if (!r) return;
    if (!(await listenLeave())) return;
    let opts = LS.rows.map((x, i) => i === LS.pos ? '' : `<option value="${escapeHtml(x.name)}">`).join('');
    setTimeout(() => { let el = lEl('listenSwapTo'); if (el) el.focus(); }, 80);
    let ok = await showBeautifulConfirm(`<b>«${escapeHtml(r.name)}» — не та запись?</b><br><br>Какое название на самом деле звучит в записи?
        Записи двух строк поменяются местами (файлы переименуются вместе с правками).<br><br>
        <input id="listenSwapTo" class="lp-search" list="listenSwapList" placeholder="Начните вводить название" style="width:100%"
            onkeydown="event.stopPropagation(); if (event.key === 'Enter') { event.preventDefault(); closeCustomAlert(true); } else if (event.key === 'Escape') closeCustomAlert(false);">
        <datalist id="listenSwapList">${opts}</datalist>`, 'Поменять', 'Отмена');
    let v = ok && (lEl('listenSwapTo') || {}).value;
    if (!v) return;
    let q = v.trim().toLowerCase();
    let k = LS.rows.findIndex((x, i) => i !== LS.pos && x.name.toLowerCase() === q);
    if (k < 0) k = LS.rows.findIndex((x, i) => i !== LS.pos && x.name.toLowerCase().includes(q));
    if (k < 0) { showToast(`Строки «${v}» в таблице нет`); return; }
    listenStopHead(); pywebview.api.listen_stop();
    let res = await pywebview.api.listen_swap(LS.pos, k);
    if (!res || res.error) { showBeautifulAlert('⚠️ ' + escapeHtml(res && res.error || 'Не получилось')); return; }
    let pos = LS.pos; LS = res.state; LS.pos = pos; lAsm = {};
    listenRender(); await listenLoadEditor();
    showToast(`Записи «${res.a}» и «${res.b}» поменялись местами`, 4000);
}


// ----- универсалы: марки без цифр — из папки ru в общую (uni_mark), она звучит и в RU, и в KZ -----
async function listenUni() {
    if (!LS) return;
    let info = await pywebview.api.listen_uni_info();
    if (!info || info.error) { showBeautifulAlert('ℹ️ ' + escapeHtml(info && info.error || 'Не получилось')); return; }
    if (!info.n) { showToast(`В «${info.src}» нет записей без цифр${info.skip ? ` (уже в «${info.dst}»: ${info.skip})` : ''}`, 4000); return; }
    if (!(await listenLeave())) return;
    let ok = await showBeautifulConfirm(`<b>Универсалы — в отдельную папку</b><br><br>Записей без цифр в «${escapeHtml(info.src)}»: <b>${info.n}</b>
        (${info.examples.map(escapeHtml).join(', ')}${info.n > info.examples.length ? '…' : ''}).<br>
        Перенесу в «<b>${escapeHtml(info.dst)}</b>» — вместе с правками. Эта папка звучит и в RU, и в KZ.`
        + (info.twins ? `<br><br><span class="tts-dim">В папке kz с такими же именами: ${info.twins} — их не трогаю (в KZ звучат они).</span>` : '')
        + (info.skip ? `<br><span class="tts-dim">Уже есть в «${escapeHtml(info.dst)}», пропущу: ${info.skip}</span>` : ''), 'Перенести', 'Отмена');
    if (!ok) return;
    listenStopHead(); pywebview.api.listen_stop();
    let r = await pywebview.api.listen_uni_move();
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
    let pos = LS.pos; LS = r.state; LS.pos = pos; lAsm = {};
    listenRender(); await listenLoadEditor();
    showToast(`Перенесено в «${r.dst}»: ${r.moved}` + (r.failed.length ? ` · ошибки: ${r.failed.length}` : ''), 4500);
}


// ----- Audacity: туда и обратно -----
async function listenToAudacity() {
    if (!lEd) return;
    let r = await pywebview.api.listen_to_audacity({ path: lEd.path, ranges: lEd.ranges, gain: lEd.gain, tempo: lEd.tempo });
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
    showToast('Запись в Audacity — правьте там, потом «Из Audacity»', 4500);
}
async function listenFromAudacity() {
    if (!lEd) return;
    if (!(await showBeautifulConfirm(`Забрать из Audacity в «${escapeHtml(lEd.name)}»?<br><br>Прежняя запись останется в «_до_правок» (…_до_audacity).`, 'Забрать', 'Отмена'))) return;
    let path = lEd.path, tgt = lTarget;
    listenStopHead(); pywebview.api.listen_stop();
    let r = await pywebview.api.listen_from_audacity(path);
    if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
    let pos = LS.pos; LS = r.state; LS.pos = pos; lAsm = {};
    lTarget = tgt; listenRender(true); await listenLoadEditor();
    showToast(`Из Audacity: ${(r.ms / 1000).toFixed(2)} с — теперь это исходник записи`, 4500);
}

// ----- «Что где есть»: вся таблица с разметкой RU / KZ -----
let lOv = null;                   // {data, tab}
async function listenOvOpen() {
    if (!LS || !LS.rows.length) { showToast('Сначала загрузите таблицу'); return; }
    lOv = { data: await pywebview.api.listen_overview(), tab: 'all' };
    lEl('listenOvFilter').value = '';
    lEl('listenOvOverlay').style.display = 'flex';
    listenOvRender();
}
function listenOvClose() { lEl('listenOvOverlay').style.display = 'none'; lOv = null; }
function listenOvTab(t) { lOv.tab = t; listenOvRender(); }
function listenOvRender() {
    if (!lOv) return;
    let d = lOv.data, q = lEl('listenOvFilter').value.trim().toLowerCase();
    let tab = (k, label, n) => `<button type="button" class="${lOv.tab === k ? 'is-on' : ''}" onclick="listenOvTab('${k}')">${label}${n != null ? ` <b>${n}</b>` : ''}</button>`;
    lEl('listenOvTabs').innerHTML = tab('all', 'Все', d.rows.length) + tab('ru', 'Нет RU', d.miss_ru) + tab('kz', 'Нет KZ', d.miss_kz);
    let cell = c => c.file
        ? `<td class="is-ok" title="${escapeHtml((c.dir ? c.dir + '/' : '') + c.file)}">${c.uni ? '<span class="listen-uni">универсал</span>' : '✓'}${c.done ? ' <i>проверена</i>' : ''}<small>${escapeHtml(c.dir || '')}</small></td>`
        : '<td class="is-miss">нет</td>';
    let rows = d.rows.filter(r => (lOv.tab === 'all' || !r[lOv.tab].file)
        && (!q || r.ru.name.toLowerCase().includes(q) || r.kz.name.toLowerCase().includes(q)));
    lEl('listenOvTable').innerHTML = `<thead><tr><th>№</th><th>Название RU</th><th>RU</th><th>Название KZ</th><th>KZ</th></tr></thead><tbody>`
        + rows.map(r => `<tr class="${r.k === d.pos ? 'is-cur' : ''}" onclick="listenOvGo(${r.k}, '${r.kind}')"><td>${r.k + 1}</td><td>${escapeHtml(r.ru.name)}</td>${cell(r.ru)}<td>${escapeHtml(r.kz.name)}</td>${cell(r.kz)}</tr>`).join('')
        + `</tbody>`;
}
async function listenOvGo(k, kind) {
    listenOvClose();
    if (LS.split) {                                       // строка может быть в другом виде (универсал / язык)
        if (kind === 'uni' && LS.lang !== 'uni') await listenLang('uni');
        else if (kind !== 'uni' && LS.lang === 'uni') await listenLang('ru');
    }
    let i = LS.rows.findIndex(x => x.base === k);
    if (i >= 0) await listenGo(i);
}
document.addEventListener('keydown', e => {
    if (lOv && e.code === 'Escape') { e.preventDefault(); e.stopImmediatePropagation(); listenOvClose(); }
    else if (lOv && e.target.tagName !== 'INPUT') e.stopImmediatePropagation();
}, true);


// ----- общий счётчик по всей таблице: проверено / строк — RU, KZ, универсалы и вместе -----
let lTotT = null;
function listenTotalsSoon() { clearTimeout(lTotT); lTotT = setTimeout(listenTotals, 350); }
async function listenTotals() {
    let el = lEl('listenTotals');
    if (!el || !LS || !LS.rows.length) { if (el) el.innerHTML = ''; return; }
    let t = await pywebview.api.listen_totals();
    if (!t) return;
    let part = (k, label) => `<span class="${LS.lang === k ? 'is-on' : ''}" title="${label}: проверено / строк (записей найдено ${t[k][1]})">${label} <b>${t[k][0]}/${t[k][2]}</b></span>`;
    el.innerHTML = `<div class="lp-totals__all">Всего <b>${t.all[0]} / ${t.all[2]}</b> <small>записей найдено ${t.all[1]}</small></div>`
        + `<div class="lp-totals__parts">${part('ru', 'RU')}${part('kz', 'KZ')}${LS.split && LS.mode !== 'phrase' ? part('uni', 'УНИВ') : ''}</div>`;
}
