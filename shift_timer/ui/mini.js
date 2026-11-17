function render() {
    const v = view(new Date());
    if (!v) { setText($('t'), '--:--'); return; }
    const { r, soon } = v, s = App.s;
    $('b').className = 'mini ' + r.phase + (soon ? ' soon' : '');
    if (r.phase === 'work') { setText($('cap'), `до ${Shift.hm(r.end)}`); setText($('t'), Shift.clock(r.remain, s.seconds)); }
    else if (r.phase === 'before') { setText($('cap'), `начало в ${Shift.hm(r.start)}`); setText($('t'), Shift.clock(r.untilStart, s.seconds)); }
    else { setText($('cap'), 'смена окончена'); setText($('t'), Shift.clock(0, s.seconds)); }
    $('t').classList.toggle('muted', r.phase === 'after');
    $('fill').style.width = (r.progress * 100).toFixed(2) + '%';
}
boot(() => {
    App.onChange = render;
    $('mOpen').onclick = () => pywebview.api.open_main();
    $('mClose').onclick = () => save({ mini_visible: false });
    render();
});
