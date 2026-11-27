'use strict';
/* «Выбор вариантов» — клиент. Без библиотек и внешних адресов (работает в закрытой сети). */
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ICON = {
  logo: '<svg viewBox="0 0 24 24"><path d="M4 13v-2m4 6V7m4 10V4m4 13V7m4 6v-2"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5l12 7-12 7z" fill="currentColor"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4-4"/></svg>',
  flag: '<svg viewBox="0 0 24 24"><path d="M5 21V4m0 1h12l-2 4 2 4H5"/></svg>',
  left: '<svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7"/></svg>',
  right: '<svg viewBox="0 0 24 24"><path d="M9 5l7 7-7 7"/></svg>',
  undo: '<svg viewBox="0 0 24 24"><path d="M9 7L4 12l5 5M4 12h10a6 6 0 010 8"/></svg>',
  moon: '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 019.5 4 8 8 0 1020 14.5z"/></svg>',
  out: '<svg viewBox="0 0 24 24"><path d="M10 5H5v14h5M15 8l4 4-4 4M19 12H9"/></svg>',
  key: '<svg viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9m-3 3l3 3m-6-0l2 2"/></svg>',
  all: '<svg viewBox="0 0 24 24"><path d="M5 6l6 6-6 6M13 6l6 6-6 6"/></svg>',
};
const S = { me: null, info: null, rows: [], filter: 'all', q: '', cur: -1, card: null, focus: 0, sel: {}, view: 'work', ctx: true,
  play: null, raf: 0, auto: false, theme: 'dark' };
try { S.theme = localStorage.getItem('gv_theme') || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'); S.ctx = localStorage.getItem('gv_ctx') !== '0'; } catch (e) { }
document.documentElement.dataset.theme = S.theme;

/* ---------- сеть ---------- */
async function api(path, data) {
  const opt = data === undefined ? { credentials: 'same-origin' }
    : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'webvote' }, body: JSON.stringify(data) };
  let r, j;
  try { r = await fetch(path, opt); j = await r.json(); } catch (e) { throw new Error('Нет связи с сервером.'); }
  if (r.status === 401 && S.me) { S.me = null; stopAudio(); render(); throw new Error('Сессия закончилась — войдите снова.'); }
  if (!r.ok) { const e = new Error(j.error || 'Ошибка'); e.must = j.must_change; throw e; }
  return j;
}
let toastT = 0;
function toast(msg, bad) { const t = $('#toast'); t.textContent = msg; t.className = 'show' + (bad ? ' bad' : ''); clearTimeout(toastT); toastT = setTimeout(() => t.className = '', bad ? 4200 : 2000); }
const fmt = ms => (ms / 1000).toFixed(2) + ' с';

/* ---------- вход ---------- */
function authScreen(kind) {
  const first = kind === 'setup', must = kind === 'must';
  const h = first ? 'Первый запуск' : must ? 'Новый пароль' : 'Вход';
  const p = first ? 'Создайте учётную запись администратора. Остальных сотрудников добавите сами.' : must ? 'Вам выдан временный пароль — задайте свой (от 6 знаков).' : 'Войдите, чтобы выбирать варианты.';
  $('#app').innerHTML = `<div class="auth"><form class="auth-card" id="af" autocomplete="on">
    <div class="logo"><div class="logo-mark">${ICON.logo}</div><div><b>Выбор вариантов</b><small>${esc(S.info?.voice || 'Синтез имён')}</small></div></div>
    <div><h2>${h}</h2><p>${p}</p></div>
    ${must ? `<div class="field"><label>Временный пароль</label><input class="input" type="password" name="old" autocomplete="current-password" required></div>
      <div class="field"><label>Новый пароль</label><input class="input" type="password" name="new" autocomplete="new-password" required></div>`
      : `${first ? '<div class="field"><label>Ваше имя</label><input class="input" name="name" autocomplete="name" placeholder="Например, Гизат"></div>' : ''}
      <div class="field"><label>Логин</label><input class="input" name="login" autocomplete="username" required autofocus></div>
      <div class="field"><label>Пароль</label><input class="input" type="password" name="password" autocomplete="${first ? 'new-password' : 'current-password'}" required></div>`}
    <div class="err" id="aerr"></div>
    <button class="btn primary" style="height:42px">${first ? 'Создать и войти' : must ? 'Сохранить' : 'Войти'}</button>
    ${must ? '<button type="button" class="btn ghost" id="alo">Выйти</button>' : ''}</form></div>`;
  $('#alo')?.addEventListener('click', logout);
  $('#af').addEventListener('submit', async ev => {
    ev.preventDefault();
    const d = Object.fromEntries(new FormData(ev.target));
    try {
      const r = await api(must ? '/api/password' : first ? '/api/setup' : '/api/login', d);
      S.me = r.user; await boot(true);
    } catch (e) { $('#aerr').textContent = e.message; }
  });
}
async function logout() { try { await api('/api/logout', {}); } catch (e) { } S.me = null; stopAudio(); S.cur = -1; render(); }

/* ---------- каркас ---------- */
function render() {
  if (!S.me) return authScreen(S.info?.setup ? 'setup' : 'login');
  if (S.me.must_change) return authScreen('must');
  const admin = S.me.role === 'admin';
  const done = S.stats.done, total = S.stats.total, pct = total ? Math.round(done * 100 / total) : 0;
  $('#app').innerHTML = `<div class="shell">
    <header class="top">
      <div class="logo-mark">${ICON.logo}</div><div class="title">Выбор вариантов</div>
      ${admin ? `<div class="tabs"><button class="tab ${S.view === 'work' ? 'on' : ''}" data-v="work">Работа</button><button class="tab ${S.view === 'admin' ? 'on' : ''}" data-v="admin">Администрирование</button></div>` : ''}
      <div class="grow"></div>
      <div class="progress"><div class="bar"><i id="pbar" style="width:${pct}%"></i></div><span id="ptxt">${done} из ${total} · ${pct}%</span></div>
      <button class="btn ghost icon" id="theme" title="Тема">${ICON.moon}</button>
      <div class="me"><div class="avatar">${esc((S.me.name || '?')[0].toUpperCase())}</div><div style="line-height:1.2"><b>${esc(S.me.name)}</b><br><small style="color:var(--faint)">${admin ? 'администратор' : 'сотрудник'}</small></div>
      <button class="btn ghost icon" id="pw" title="Сменить пароль">${ICON.key}</button>
      <button class="btn ghost icon" id="out" title="Выйти">${ICON.out}</button></div>
    </header>
    <div id="body" style="min-height:0;display:contents"></div></div>`;
  $('#theme').onclick = () => { S.theme = S.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = S.theme; try { localStorage.setItem('gv_theme', S.theme); } catch (e) { } draw(); };
  $('#out').onclick = logout; $('#pw').onclick = pwModal;
  document.querySelectorAll('.tab').forEach(b => b.onclick = () => { S.view = b.dataset.v; stopAudio(); render(); });
  if (S.view === 'admin' && admin) adminView(); else workView();
}
function setProgress() {
  const { done, total } = S.stats; const pct = total ? Math.round(done * 100 / total) : 0;
  const b = $('#pbar'); if (b) b.style.width = pct + '%'; const t = $('#ptxt'); if (t) t.textContent = `${done} из ${total} · ${pct}%`;
}
function pwModal() {
  const bg = document.createElement('div'); bg.className = 'modal-bg';
  bg.innerHTML = `<form class="modal"><h3>Сменить пароль</h3>
    <div class="field"><label>Текущий пароль</label><input class="input" type="password" name="old" autocomplete="current-password" required></div>
    <div class="field"><label>Новый пароль</label><input class="input" type="password" name="new" autocomplete="new-password" required></div>
    <div class="err"></div><div class="row-btns"><button type="button" class="btn" id="c">Отмена</button><button class="btn primary">Сохранить</button></div></form>`;
  document.body.appendChild(bg);
  bg.querySelector('#c').onclick = () => bg.remove(); bg.onclick = e => { if (e.target === bg) bg.remove(); };
  bg.querySelector('form').onsubmit = async e => { e.preventDefault(); try { await api('/api/password', Object.fromEntries(new FormData(e.target))); bg.remove(); toast('Пароль изменён'); } catch (er) { bg.querySelector('.err').textContent = er.message; } };
  bg.querySelector('input').focus();
}

/* ---------- рабочий экран ---------- */
function workView() {
  $('#body').innerHTML = `<div class="work">
    <aside class="side"><div class="side-head">
      <div class="search">${ICON.search}<input class="input" id="q" placeholder="Найти имя…" autocomplete="off" value="${esc(S.q)}"></div>
      <div class="chips" id="chips"></div></div>
      <div class="list" id="list"></div></aside>
    <section class="main" id="main"></section>
    <div class="actions" id="actions"></div></div>`;
  $('#q').oninput = e => { S.q = e.target.value; fillList(); };
  chips(); fillList();
  if (S.cur < 0) { const first = S.rows.find(r => r[2] === 'new' && !r[5]); S.cur = first ? first[0] : 0; }
  openName(S.cur);
}
function counts() { const c = { all: S.rows.length, new: 0, done: 0, flag: 0 }; S.rows.forEach(r => c[r[2]]++); return c; }
function chips() {
  const c = counts(), el = $('#chips'); if (!el) return;
  el.innerHTML = [['all', 'Все'], ['new', 'Осталось'], ['done', 'Выбраны'], ['flag', 'Помечены']].map(([k, t]) => `<button class="chip ${S.filter === k ? 'on' : ''}" data-f="${k}">${t}<b>${c[k]}</b></button>`).join('');
  el.querySelectorAll('.chip').forEach(b => b.onclick = () => { S.filter = b.dataset.f; chips(); fillList(); });
}
const STT = { done: v => 'вар. ' + v, flag: () => 'правка', new: () => '' };
function rowHTML(r) {
  const [i, nm, st, v, by, busy] = r;
  const cls = ['row', st === 'done' ? 'done' : st === 'flag' ? 'flag' : '', busy ? 'busy' : '', i === S.cur ? 'cur' : ''].join(' ');
  const tag = busy ? esc(busy) : STT[st](v);
  return `<button class="${cls}" data-i="${i}" id="r${i}"><span class="n">${i + 1}</span><span class="nm">${esc(nm)}</span>${tag ? `<span class="st">${tag}</span>` : ''}</button>`;
}
function fillList() {
  const q = S.q.trim().toLowerCase(), el = $('#list'); if (!el) return;
  const rows = S.rows.filter(r => (S.filter === 'all' || r[2] === S.filter) && (!q || r[1].toLowerCase().includes(q) || String(r[0] + 1) === q));
  el.innerHTML = rows.length ? rows.map(rowHTML).join('') : '<div class="empty">Ничего не найдено</div>';
  el.onclick = e => { const b = e.target.closest('.row'); if (b) openName(+b.dataset.i); };
}
function patchRow(i) {
  const r = S.rows[i], old = $('#r' + i); if (!old) return;
  const t = document.createElement('div'); t.innerHTML = rowHTML(r); old.replaceWith(t.firstChild);
}
async function refreshList(keepCur) {
  const j = await api('/api/list'); S.rows = j.rows; S.stats = { done: j.done, total: j.total, flag: j.flag };
  setProgress(); if ($('#list')) { chips(); fillList(); const c = $('#r' + S.cur); c && c.scrollIntoView({ block: 'nearest' }); }
}

async function openName(i) {
  if (!$('#main')) return;
  stopAudio();
  let card;
  try { card = await api('/api/name/' + i); } catch (e) { return toast(e.message, true); }
  const prev = S.cur; S.cur = i; S.card = card;
  S.sel = {}; card.variants.forEach(v => {
    const ch = card.choice && card.choice.v === v.v && card.choice.a != null ? [card.choice.a, card.choice.b] : null;
    S.sel[v.v] = ch || padded(v);
  });
  S.focus = card.choice?.v ? card.choice.v : (card.variants[0]?.v || 1);
  if (prev !== i) { const a = $('#r' + prev); a && a.classList.remove('cur'); }
  const c = $('#r' + i); if (c) { c.classList.add('cur'); c.scrollIntoView({ block: 'nearest' }); }
  draw();
  $('#main').scrollTop = 0;
}
function padded(v) { const [a, b] = v.auto; return [Math.max(0, a - 40), Math.min(v.dur, b + 60)]; }

function draw() {
  const card = S.card, main = $('#main'); if (!card || !main) return;
  const ch = card.choice;
  const badge = ch?.v ? `<span class="badge ok">${ICON.check} Выбран вариант ${ch.v} · ${esc(ch.by)}</span>` : ch?.flag ? `<span class="badge warn">${ICON.flag} Нужна правка · ${esc(ch.by)}</span>` : '<span class="badge dim">Не выбрано</span>';
  const total = card.variants.length;
  main.innerHTML = `<div class="stage">
    <div class="head"><div><div class="idx">Имя ${card.idx + 1} из ${card.total}</div><h1>${esc(card.name)}</h1></div><div class="grow"></div>${badge}</div>
    ${card.busy ? `<div class="banner">Сейчас это имя слушает ${esc(card.busy)} — выбирать нельзя, пока они не закончат.</div>` : ''}
    ${S.ctx && card.ctx ? `<div class="phrase"><span class="seg">начало фразы</span>${ICON.right}<span class="seg mid">${esc(card.name)}</span>${ICON.right}<span class="seg">конец фразы</span></div>` : ''}
    <div class="cards">${total ? card.variants.map(v => takeHTML(v)).join('') : '<div class="empty">Для этого имени нет готовых вариантов.</div>'}</div>
    <div class="keys"><span><kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> слушать</span><span><kbd>Пробел</kbd> ещё раз</span><span><kbd>A</kbd> все подряд</span><span><kbd>Enter</kbd> выбрать и дальше</span><span><kbd>F</kbd> нужна правка</span><span><kbd>←</kbd><kbd>→</kbd> имена</span></div></div>`;
  card.variants.forEach(v => { wire(v); paint(v); });
  actions();
}
function takeHTML(v) {
  const chosen = S.card.choice?.v === v.v;
  return `<div class="take ${S.focus === v.v ? 'focus' : ''} ${chosen ? 'chosen' : ''}" id="t${v.v}" data-v="${v.v}">
    <div class="take-head"><span class="key">${v.v}</span><b>Вариант ${v.v}</b><span class="grow"></span><small id="d${v.v}"></small></div>
    <div class="wave" id="w${v.v}"><canvas></canvas><i class="head-line" id="p${v.v}"></i><i class="handle" id="ha${v.v}" title="Начало"></i><i class="handle" id="hb${v.v}" title="Конец"></i></div>
    <div class="take-foot"><span class="t" id="s${v.v}"></span>
      <button class="btn sm" data-act="full" title="Весь файл, без подрезки">Целиком</button>
      <button class="btn sm" data-act="auto" title="Автоматическая подрезка тишины">Авто</button>
      <button class="btn sm icon" data-act="play" title="Слушать (${v.v})">${ICON.play}</button>
      <button class="btn sm ${chosen ? 'ok' : 'primary'}" data-act="pick">${chosen ? ICON.check + ' Выбрано' : 'Выбрать'}</button></div></div>`;
}
function paint(v) {
  const w = $('#w' + v.v); if (!w) return; const cv = w.querySelector('canvas');
  const r = w.getBoundingClientRect(), dpr = devicePixelRatio || 1; cv.width = r.width * dpr; cv.height = r.height * dpr;
  const g = cv.getContext('2d'), W = cv.width, H = cv.height, [a, b] = S.sel[v.v], css = getComputedStyle(document.documentElement);
  const on = css.getPropertyValue('--wave-on').trim(), off = css.getPropertyValue('--wave').trim();
  g.clearRect(0, 0, W, H); const n = v.peaks.length, bw = W / n, x0 = a / v.dur * W, x1 = b / v.dur * W;
  for (let i = 0; i < n; i++) {
    const x = i * bw, h = Math.max(2 * dpr, v.peaks[i] * H * 0.86);
    g.fillStyle = x + bw > x0 && x < x1 ? on : off; g.globalAlpha = x + bw > x0 && x < x1 ? 1 : .35;
    g.beginPath(); g.roundRect(x + bw * .15, (H - h) / 2, Math.max(1, bw * .7), h, 2 * dpr); g.fill();
  }
  g.globalAlpha = 1;
  $('#ha' + v.v).style.left = (a / v.dur * 100) + '%'; $('#hb' + v.v).style.left = (b / v.dur * 100) + '%';
  $('#d' + v.v).textContent = fmt(v.dur); $('#s' + v.v).textContent = `${fmt(a)} — ${fmt(b)} · ${fmt(b - a)}`;
}
function wire(v) {
  const t = $('#t' + v.v), w = $('#w' + v.v);
  t.addEventListener('pointerdown', e => { if (!e.target.closest('button,.handle')) setFocus(v.v); });
  t.querySelectorAll('[data-act]').forEach(b => b.onclick = () => {
    const a = b.dataset.act; setFocus(v.v);
    if (a === 'play') playOne(v.v); else if (a === 'pick') pick(v.v);
    else if (a === 'full') { S.sel[v.v] = [0, v.dur]; paint(v); } else if (a === 'auto') { S.sel[v.v] = padded(v); paint(v); }
  });
  ['a', 'b'].forEach((k, ki) => {
    const h = $('#h' + k + v.v);
    h.addEventListener('pointerdown', e => {
      e.preventDefault(); h.setPointerCapture(e.pointerId); setFocus(v.v); const r = w.getBoundingClientRect();
      const mv = ev => {
        const ms = Math.round(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * v.dur), s = S.sel[v.v];
        if (ki === 0) s[0] = Math.min(ms, s[1] - 80); else s[1] = Math.max(ms, s[0] + 80);
        paint(v);
      };
      const up = () => { h.removeEventListener('pointermove', mv); h.removeEventListener('pointerup', up); };
      h.addEventListener('pointermove', mv); h.addEventListener('pointerup', up);
    });
    h.addEventListener('dblclick', () => { S.sel[v.v][ki] = ki ? v.dur : 0; paint(v); });
  });
}
function setFocus(v) { S.focus = v; document.querySelectorAll('.take').forEach(t => t.classList.toggle('focus', +t.dataset.v === v)); }

function actions() {
  const el = $('#actions'); if (!el) return; const c = S.card, ch = c.choice;
  el.innerHTML = `<div class="inner">
    <button class="btn icon" id="prev" title="Предыдущее (←)">${ICON.left}</button>
    <button class="btn icon" id="next" title="Следующее (→)">${ICON.right}</button>
    <button class="btn" id="all" title="Все три подряд (A)">${ICON.all} Все три</button>
    <label class="opt"><input type="checkbox" id="ctx" ${S.ctx ? 'checked' : ''}> в составе фразы</label>
    <span class="grow" style="flex:1"></span>
    ${ch?.v ? `<button class="btn" id="un">${ICON.undo} Снять выбор</button>` : ''}
    <button class="btn ${ch?.flag ? 'danger' : ''}" id="fl">${ICON.flag} ${ch?.flag && !ch.v ? 'Снять пометку' : 'Нужна правка'}</button>
    <button class="btn ok" id="go" ${c.busy ? 'disabled' : ''}>Выбрать и дальше</button></div>`;
  $('#prev').onclick = () => step(-1); $('#next').onclick = () => step(1); $('#all').onclick = playAll;
  $('#ctx').onchange = e => { S.ctx = e.target.checked; try { localStorage.setItem('gv_ctx', S.ctx ? '1' : '0'); } catch (er) { } stopAudio(); draw(); };
  $('#go').onclick = () => pick(S.focus, true); $('#fl').onclick = flag; const u = $('#un'); if (u) u.onclick = unpick;
}
async function step(d) { const n = S.rows.length; await release(); openName((S.cur + d + n) % n); }
async function release() { if (S.card) { try { await api('/api/release', { idx: S.cur }); } catch (e) { } } }
async function goNext() {
  const j = await api('/api/next?from=' + S.cur);
  if (j.idx == null) { toast('Все имена обработаны'); return openName(S.cur); }
  openName(j.idx);
}
async function pick(v, advance) {
  if (S.card.busy) return toast('Имя сейчас слушает ' + S.card.busy, true);
  const [a, b] = S.sel[v];
  try { await api('/api/choose', { idx: S.cur, v, a, b }); } catch (e) { return toast(e.message, true); }
  await refreshList();
  if (advance) { toast(`«${S.card.name}» — вариант ${v}`); await goNext(); }
  else { S.card.choice = { v, a, b, by: S.me.name, mine: true }; draw(); }
}
async function unpick() { try { await api('/api/unchoose', { idx: S.cur }); await refreshList(); await openName(S.cur); } catch (e) { toast(e.message, true); } }
async function flag() {
  const on = !(S.card.choice?.flag && !S.card.choice?.v);
  let comment = '';
  if (on) { comment = prompt('Что не так? (необязательно)', '') ; if (comment === null) return; }
  try { await api('/api/flag', { idx: S.cur, on, comment }); await refreshList(); if (on) await goNext(); else await openName(S.cur); } catch (e) { toast(e.message, true); }
}

/* ---------- звук ---------- */
const audio = new Audio();
audio.preload = 'auto';
function stopAudio() { try { audio.pause(); } catch (e) { } cancelAnimationFrame(S.raf); S.play = null; document.querySelectorAll('.head-line').forEach(l => l.style.display = 'none'); document.querySelectorAll('[data-act=play]').forEach(b => b.innerHTML = ICON.play); }
async function playOne(v, onend) {
  if (S.play === v && !onend) return stopAudio();
  stopAudio(); const [a, b] = S.sel[v], vv = S.card.variants.find(x => x.v === v);
  const url = `/audio/chain?idx=${S.cur}&v=${v}&a=${a}&b=${b}&ctx=${S.ctx ? 1 : 0}`;
  let off = 0;
  try { const r = await fetch(url, { credentials: 'same-origin' }); if (!r.ok) throw 0; off = +(r.headers.get('X-Name-Offset') || 0); audio.src = URL.createObjectURL(await r.blob()); } catch (e) { return toast('Не удалось загрузить звук', true); }
  S.play = v; const btn = document.querySelector(`#t${v} [data-act=play]`); if (btn) btn.innerHTML = ICON.stop;
  audio.onended = () => { const f = onend; stopAudio(); f && f(); };
  try { await audio.play(); } catch (e) { return stopAudio(); }
  const line = $('#p' + v), tick = () => {
    if (S.play !== v) return; const ms = audio.currentTime * 1000 - off, pos = a + ms;
    if (line) { line.style.display = ms >= 0 ? 'block' : 'none'; line.style.left = (Math.min(b, Math.max(a, pos)) / vv.dur * 100) + '%'; }
    S.raf = requestAnimationFrame(tick);
  }; tick();
}
async function playAll() {
  const vs = S.card.variants.map(x => x.v); let k = 0;
  const next = () => { if (k < vs.length) { const v = vs[k++]; setFocus(v); playOne(v, () => setTimeout(next, 350)); } };
  next();
}

/* ---------- клавиши ---------- */
document.addEventListener('keydown', e => {
  if (!S.me || S.view !== 'work' || !S.card || e.target.matches('input,textarea,select') || e.ctrlKey || e.metaKey || e.altKey) return;
  if (document.querySelector('.modal-bg')) return;
  const k = e.key;
  if (/^[1-9]$/.test(k) && S.card.variants.some(v => v.v === +k)) { e.preventDefault(); setFocus(+k); playOne(+k); }
  else if (k === 'Enter') { e.preventDefault(); pick(S.focus, true); }
  else if (k === ' ') { e.preventDefault(); playOne(S.focus); }
  else if (k === 'ArrowRight') { e.preventDefault(); step(1); } else if (k === 'ArrowLeft') { e.preventDefault(); step(-1); }
  else if (k === 'a' || k === 'A' || k === 'ф' || k === 'Ф') playAll();
  else if (k === 'f' || k === 'F' || k === 'а' || k === 'А') flag();
  else if (k === 'Escape') stopAudio();
});
addEventListener('resize', () => { S.card && S.card.variants.forEach(paint); });

/* ---------- администрирование ---------- */
async function adminView() {
  $('#body').innerHTML = '<div class="admin"><div class="admin-in" id="ad"></div></div>';
  let st, us;
  try { [st, us] = await Promise.all([api('/api/admin/stats'), api('/api/users')]); } catch (e) { return toast(e.message, true); }
  const left = st.total - st.done, pct = st.total ? Math.round(st.done * 100 / st.total) : 0;
  const vmax = Math.max(1, ...Object.values(st.votes));
  $('#ad').innerHTML = `
    <div class="tiles"><div class="tile"><small>Выбрано</small><b>${st.done}</b></div><div class="tile"><small>Осталось</small><b>${left}</b></div>
      <div class="tile"><small>Нужна правка</small><b>${st.flag}</b></div><div class="tile"><small>Готовность</small><b>${pct}%</b></div></div>
    <div class="panel"><h3>Какие варианты выбирают <span class="grow"></span></h3><div class="pad"><div class="votes">${Object.entries(st.votes).map(([v, n]) =>
      `<div class="vote"><small>Вариант ${v}</small><b>${n}</b><div class="bar" style="margin-top:8px;height:6px"><i style="width:${n / vmax * 100}%"></i></div></div>`).join('')}</div></div></div>
    <div class="panel"><h3>Выгрузка <span class="grow"></span><button class="btn primary" id="exp">Выгрузить результат</button></h3>
      <div class="pad" id="expres" style="color:var(--dim)">Файлы выбранных вариантов (с подрезкой, если её поставили) и отчёт ляжут в папку «Итог» рядом с вариантами. Можно выгружать в любой момент.</div></div>
    <div class="panel"><h3>Сотрудники <span class="grow"></span></h3>
      <table><thead><tr><th>Имя</th><th>Логин</th><th>Роль</th><th>Выбрано</th><th></th></tr></thead><tbody>${us.users.map(u => {
        const s = st.users.find(x => x.id === u.id) || { n: 0 };
        return `<tr><td><b>${esc(u.name)}</b></td><td>${esc(u.login)}</td><td><span class="role ${u.active ? (u.role === 'admin' ? 'admin' : '') : 'off'}">${u.active ? (u.role === 'admin' ? 'админ' : 'сотрудник') : 'отключён'}</span></td>
        <td><div class="mini"><div class="bar"><i style="width:${st.total ? s.n / st.total * 100 : 0}%"></i></div>${s.n}</div></td>
        <td style="text-align:right;white-space:nowrap"><button class="btn sm" data-pw="${u.id}">Новый пароль</button> <button class="btn sm" data-role="${u.id}" data-r="${u.role}">${u.role === 'admin' ? 'Сделать сотрудником' : 'Сделать админом'}</button> <button class="btn sm ${u.active ? 'danger' : ''}" data-act="${u.id}" data-on="${u.active ? 1 : 0}">${u.active ? 'Отключить' : 'Включить'}</button></td></tr>`;
      }).join('')}</tbody></table>
      <form class="pad form-row" id="nu" style="border-top:1px solid var(--line)">
        <div class="field"><label>Логин</label><input class="input" name="login" required></div>
        <div class="field"><label>Имя</label><input class="input" name="name"></div>
        <div class="field"><label>Временный пароль</label><input class="input" name="password" required></div>
        <div class="field"><label>Роль</label><select class="input" name="role"><option value="user">сотрудник</option><option value="admin">администратор</option></select></div>
        <button class="btn primary" style="height:40px">Добавить</button></form></div>`;
  $('#exp').onclick = async () => { $('#exp').disabled = true; try { const r = await api('/api/admin/export', {}); $('#expres').innerHTML = `<b style="color:var(--ok)">Готово: ${r.done} файлов.</b> ${esc(r.dir)}${r.errors.length ? '<br><span style="color:var(--bad)">' + r.errors.map(esc).join('<br>') + '</span>' : ''}`; } catch (e) { toast(e.message, true); } $('#exp').disabled = false; };
  $('#nu').onsubmit = async e => { e.preventDefault(); try { await api('/api/users', Object.fromEntries(new FormData(e.target))); toast('Сотрудник добавлен — при входе он сменит пароль'); adminView(); } catch (er) { toast(er.message, true); } };
  document.querySelectorAll('[data-pw]').forEach(b => b.onclick = async () => { const p = prompt('Временный пароль (от 6 знаков):'); if (!p) return; try { await api('/api/users/' + b.dataset.pw, { password: p }); toast('Пароль задан — при входе сотрудник его сменит'); } catch (e) { toast(e.message, true); } });
  document.querySelectorAll('[data-role]').forEach(b => b.onclick = async () => { try { await api('/api/users/' + b.dataset.role, { role: b.dataset.r === 'admin' ? 'user' : 'admin' }); adminView(); } catch (e) { toast(e.message, true); } });
  document.querySelectorAll('[data-act]').forEach(b => b.onclick = async () => { try { await api('/api/users/' + b.dataset.act, { active: b.dataset.on !== '1' }); adminView(); } catch (e) { toast(e.message, true); } });
}

/* ---------- запуск ---------- */
async function boot(keep) {
  try { S.info = await api('/api/me'); } catch (e) { $('#app').innerHTML = `<div class="auth"><div class="auth-card"><h2>Нет связи</h2><p>${esc(e.message)}</p></div></div>`; return; }
  S.me = S.info.user;
  if (S.me && !S.me.must_change) { try { const j = await api('/api/list'); S.rows = j.rows; S.stats = { done: j.done, total: j.total, flag: j.flag }; } catch (e) { } }
  if (!keep) S.cur = -1;
  render();
}
setInterval(async () => {
  if (!S.me || S.me.must_change || document.hidden) return;
  try { if (S.view === 'work' && S.card) { const h = await api('/api/heartbeat', { idx: S.cur }); if ((h.busy || null) !== (S.card.busy || null)) { S.card.busy = h.busy; draw(); } await refreshList(); } } catch (e) { }
}, 20000);
boot();
