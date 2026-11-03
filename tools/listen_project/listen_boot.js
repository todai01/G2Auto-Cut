// Отдельная «Прослушка»: стартовый экран, переключение экранов и клавиши.
// Сама прослушка — listen.js, общие окна и уведомления — ui_base.js.
const STAGES = ['listenHome', 'stage5-listen'];
const isShown = id => { let el = document.getElementById(id); return !!el && el.style.display !== 'none'; };
function showStage(id) {
    STAGES.forEach(s => { let el = document.getElementById(s); if (el) el.style.display = s === id ? 'flex' : 'none'; });
    document.body.dataset.mode = 'vars';
}
function showMenu() { showStage('listenHome'); }                 // «В начало»

document.addEventListener('keydown', e => {
    if (uiAlertKey(e)) return;                                   // открыт вопрос / сообщение
    if (isShown('listenHome')) {
        if (e.code === 'Enter' || e.code === 'Space') { e.preventDefault(); listenStart(); }
        return;
    }
    if (isShown('stage5-listen')) listenKey(e);
});
document.addEventListener('DOMContentLoaded', () => showStage('listenHome'));
