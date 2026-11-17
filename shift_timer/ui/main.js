const C = 2 * Math.PI * 104;
const STATUS = {
    work:   { chip: 'Идёт смена', cap: 'Осталось' },
    before: { chip: 'Смена ещё не началась', cap: 'До начала' },
    after:  { chip: 'Смена закончилась', cap: 'Смена окончена' },
};

function render() {
    const v = view(new Date());
    if (!v) { setText($('big'), '--:--'); setText($('sub'), 'Проверьте время в настройках'); return; }
    const { r, soon, pct } = v, s = App.s, st = STATUS[r.phase];
    $('chip').className = 'chip ' + r.phase;
    setText($('chipT'), st.chip);
    setText($('cap'), st.cap);
    const big = $('big');
    big.className = 'big' + (s.seconds ? ' ss' : ' s') + (r.phase === 'after' ? ' muted' : '');
    $('ring').className = 'ringbox ' + (soon ? 'soon ' : '') + r.phase;

    if (r.phase === 'work') { setText(big, Shift.clock(r.remain, s.seconds)); setText($('sub'), `до ${Shift.hm(r.end)}`); }
    else if (r.phase === 'before') { setText(big, Shift.clock(r.untilStart, s.seconds)); setText($('sub'), `начало в ${Shift.hm(r.start)}`); }
    else { setText(big, Shift.clock(0, s.seconds)); setText($('sub'), `после конца: ${Shift.words(r.over, false)}`); }
    setText($('pct'), r.phase === 'before' ? '' : `${pct}% дня`);
    $('fill').style.strokeDashoffset = String(C * (1 - r.progress));

    setText($('rRange'), `${Shift.hm(r.start)} – ${Shift.hm(r.end)}`);
    setText($('rDone'), Shift.words(r.elapsed, s.seconds));
    setText($('rLeft'), r.phase === 'after' ? 'смена окончена' : Shift.words(r.phase === 'before' ? r.total : r.remain, s.seconds));
    setText($('rTotal'), Shift.words(r.total, false));
    setText($('bMini'), s.mini_visible ? 'Скрыть мини-окно' : 'Показать мини-окно');
    syncSettings();
}

function setSwitch(id, on) { $(id).classList.toggle('on', !!on); $(id).setAttribute('aria-checked', String(!!on)); }
function syncSettings() {
    const s = App.s;
    if (document.activeElement !== $('iStart') && $('iStart').value !== s.start) $('iStart').value = s.start;   // не мешаем вводу
    if (document.activeElement !== $('iEnd') && $('iEnd').value !== s.end) $('iEnd').value = s.end;
    setSwitch('swSec', s.seconds); setSwitch('swMini', s.mini_visible); setSwitch('swTop', s.mini_on_top);
    document.querySelectorAll('#segTheme button').forEach(b => b.classList.toggle('on', b.dataset.t === s.theme));
}

boot(() => {
    App.onChange = render;
    document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
        document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
        document.querySelectorAll('.view').forEach(v => v.classList.toggle('on', v.id === 'v-' + t.dataset.v));
    });
    $('bMin').onclick = () => pywebview.api.minimize();
    $('bX').onclick = () => pywebview.api.close_app();
    $('bMini').onclick = () => save({ mini_visible: !App.s.mini_visible });
    $('swSec').onclick = () => save({ seconds: !App.s.seconds });
    $('swMini').onclick = () => save({ mini_visible: !App.s.mini_visible });
    $('swTop').onclick = () => save({ mini_on_top: !App.s.mini_on_top });
    document.querySelectorAll('#segTheme button').forEach(b => b.onclick = () => save({ theme: b.dataset.t }));
    $('iStart').onchange = e => e.target.value && save({ start: e.target.value });
    $('iEnd').onchange = e => e.target.value && save({ end: e.target.value });
    render();
});
