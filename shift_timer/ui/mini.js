function render() {
    const v = view();
    if (!v) { setText($('t'), '--:--'); return; }
    const { d, c } = v, s = App.s;
    $('b').className = 'mini ' + c.phase + (c.soon ? ' soon' : '');
    if (c.phase === 'done') { setText($('cap'), 'норма выполнена'); setText($('t'), '+' + Shift.clock(c.over, s.seconds)); }
    else { setText($('cap'), c.phase === 'paused' ? 'пауза — экран заблокирован' : 'осталось'); setText($('t'), Shift.clock(c.remain, s.seconds)); }
    $('t').classList.toggle('muted', c.phase === 'paused');
    $('fill').style.width = (c.progress * 100).toFixed(2) + '%';
    setText($('w'), `отработано ${Shift.clock(c.worked, s.seconds)}`);
}
boot(() => {
    App.onChange = render;
    $('mOpen').onclick = () => pywebview.api.open_main();
    $('mClose').onclick = () => save({ mini_visible: false });
    render();
});
