// Автокликер: скрытое окно, открывается тройным щелчком по слову «Система» в настройках. Логика — autoclick.py.
(function () {
    let cfg = null, timer = null, picking = false;
    const $a = id => document.getElementById(id);
    const seg = (id, k) => document.querySelectorAll('#' + id + ' button').forEach(b => b.classList.toggle('on', b.dataset.k === k));
    const segVal = id => { const b = document.querySelector('#' + id + ' button.on'); return b ? b.dataset.k : null; };
    function fill() {
        $a('acInt').value = cfg.interval_ms; $a('acLim').value = cfg.limit; $a('acDelay').value = cfg.delay_s;
        seg('acBtn', cfg.button); seg('acMode', cfg.mode);
        $a('acDbl').classList.toggle('on', cfg.double); $a('acDbl').setAttribute('aria-checked', String(cfg.double));
        showPt();
    }
    function showPt() {
        $a('acPtRow').style.display = segVal('acMode') === 'point' ? '' : 'none';
        $a('acPt').textContent = `Точка: ${cfg.x}, ${cfg.y}`;
    }
    function read() {
        return { interval_ms: +$a('acInt').value || 1000, button: segVal('acBtn') || 'left', double: $a('acDbl').classList.contains('on'), mode: segVal('acMode') || 'cursor',
                 x: cfg.x, y: cfg.y, limit: +$a('acLim').value || 0, delay_s: +$a('acDelay').value || 0 };
    }
    function paint(st) {
        $a('acGo').textContent = st.running ? 'Стоп' : 'Старт';
        $a('acGo').classList.toggle('danger', !!st.running);
        $a('acCnt').textContent = st.running ? (st.phase === 'wait' ? 'Ждём…' : `Кликов: ${st.count}`) : st.count ? `Кликов: ${st.count}` : '';
        if (st.error) { $a('acHint').textContent = st.error; $a('acHint').classList.add('err'); }
    }
    async function tick() {
        if ($a('dlgAc').hidden) { clearInterval(timer); return; }                       // окно закрыли — опрос не нужен
        try { paint(await pywebview.api.ac_state()); } catch (e) { /* повторим */ }
    }
    async function open() {
        let r;
        try { r = await pywebview.api.ac_get(); } catch (e) { return; }
        cfg = r.cfg; fill(); paint(r.state);
        $a('acHint').classList.remove('err');
        $a('acHint').textContent = r.supported ? 'F6 — старт / стоп, Esc — стоп. Работает и при свёрнутом окне.' : 'Клики работают только в Windows.';
        openDlg('dlgAc');
        clearInterval(timer); timer = setInterval(tick, 400);
    }
    function close() { clearInterval(timer); closeDlg(); }
    function init() {
        $a('hSys').onclick = e => { if (e.detail === 3) open(); };
        $a('acClose').onclick = close;
        $a('acBtn').onclick = $a('acMode').onclick = e => {
            const b = e.target.closest('button'); if (!b) return;
            b.parentNode.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b)); showPt();
        };
        $a('acDbl').onclick = () => { const on = !$a('acDbl').classList.contains('on'); $a('acDbl').classList.toggle('on', on); $a('acDbl').setAttribute('aria-checked', String(on)); };
        $a('acPick').onclick = async () => {
            if (picking) return; picking = true;
            for (let i = 3; i > 0; i--) { $a('acPick').textContent = `Наведите курсор… ${i}`; await new Promise(r => setTimeout(r, 1000)); }
            const p = await pywebview.api.ac_pick();
            if (p && !p.error) { cfg.x = p.x; cfg.y = p.y; showPt(); }
            $a('acPick').textContent = 'Указать точку (3 с)'; picking = false;
        };
        $a('acGo').onclick = async () => {
            const st = await pywebview.api.ac_state();
            const r = st.running ? await pywebview.api.ac_stop() : await pywebview.api.ac_start(cfg = read());
            if (r && r.error) { $a('acHint').textContent = r.error; $a('acHint').classList.add('err'); } else $a('acHint').classList.remove('err');
            tick();
        };
        $a('dlgBack').addEventListener('click', e => { if (e.target === $a('dlgBack')) clearInterval(timer); });
    }
    init();
})();
