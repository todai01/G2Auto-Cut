// Обновление GTime через папку команды: плашка «Доступна версия N», кнопка «Обновить», «Опубликовать» для администратора.
let UPD = null;
async function updRefresh(force) {
    try { UPD = force ? await pywebview.api.update_check() : await pywebview.api.update_status(); } catch (e) { return; }
    updRender();
}
function updRender() {
    const u = UPD;
    if (!u) return;
    setText($('updVer'), u.build ? `сборка ${u.build}` : 'запуск из исходников');
    $('updBar').hidden = !u.available;
    if (u.available) setText($('updTxt'), `Доступна новая версия ${u.remote.version}` + (u.remote.notes ? ` — ${u.remote.notes}` : ''));
    $('updGo').hidden = !u.available;
    const admin = !!(typeof TM !== 'undefined' && TM && TM.user && TM.user.role === 'admin' && u.frozen && u.build > 0);
    $('updPubRow').hidden = $('updNotesRow').hidden = !admin;
    if (!u.dir) setText($('updState'), 'Папка команды не выбрана — обновления через неё недоступны.');
    else if (u.error) setText($('updState'), u.error);
    else if (u.available) setText($('updState'), `Есть новая версия ${u.remote.version} (у вас ${u.build}).`);
    else if (u.remote) setText($('updState'), `У вас актуальная сборка (в папке команды — ${u.remote.version}).`);
    else setText($('updState'), 'В папке команды пока нет выложенной сборки.');
}
async function updApply() {
    if (!confirm('GTime закроется и откроется уже обновлённым. Учёт времени продолжится. Обновить сейчас?')) return;
    setText($('updTxt'), 'Обновляю… GTime перезапустится.'); $('updBtn').disabled = true;
    const r = await pywebview.api.update_apply();
    if (r && r.error) { $('updBtn').disabled = false; setText($('updTxt'), r.error); setText($('updState'), r.error); }
}
function updateInit() {
    updRefresh(false);
    setInterval(() => updRefresh(false), 60000);
    $('updBtn').onclick = updApply; $('updGo').onclick = updApply;
    $('updCheck').onclick = async () => { setText($('updState'), 'Проверяю…'); await updRefresh(true); };
    $('updPub').onclick = async () => {
        setText($('updState'), 'Выкладываю…');
        const r = await pywebview.api.update_publish($('updNotes').value);
        if (r.error) { setText($('updState'), r.error); return; }
        setText($('updState'), `Сборка ${r.version} выложена (${Math.max(1, Math.round(r.size / 1048576))} МБ). Остальным придёт «Обновить».`);
        $('updNotes').value = ''; updRefresh(false);
    };
}
window.updRender = updRender;
