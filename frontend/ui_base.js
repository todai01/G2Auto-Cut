// Общие мелочи интерфейса GVox: иконки, экранирование, окно-вопрос, уведомления.
// Подключается до script.js (основная программа) и в отдельной «Прослушке».

// Единая замена смайликов иконками (спрайт <symbol> лежит в index.html):
// возвращает <svg class="icon"><use .../></svg> по имени иконки.
function iconHTML(name) {
    return `<svg class="icon"><use href="#icon-${name}"></use></svg>`;
}

// Многие тексты алертов/тостов приходят из бэкенда с эмодзи-префиксом
// (например "✅ Готово"). Вместо правки полусотни строк в Python — одно
// место, где эмодзи в начале строки распознаётся, убирается из текста,
// а на его месте показывается иконка + цветовой тон (ошибка/успех/т.д.).
const EMOJI_ICON_MAP = {
    '❌': { icon: 'x-circle', tone: 'error' },
    '⚠️': { icon: 'alert-triangle', tone: 'warning' },
    '⚠': { icon: 'alert-triangle', tone: 'warning' },
    '✅': { icon: 'check-circle', tone: 'success' },
    '🎉': { icon: 'check-circle', tone: 'success' },
    '🔄': { icon: 'refresh-cw', tone: 'info' },
    '🔁': { icon: 'refresh-cw', tone: 'info' },
    '✂️': { icon: 'scissors', tone: 'info' },
    '✂': { icon: 'scissors', tone: 'info' },
    '🔗': { icon: 'link-2', tone: 'info' },
    '💾': { icon: 'save', tone: 'info' },
    '⚡': { icon: 'zap', tone: 'info' },
    '📁': { icon: 'folder', tone: 'info' },
    '📂': { icon: 'folder', tone: 'info' },
    '🎙️': { icon: 'mic', tone: 'info' },
    '🎙': { icon: 'mic', tone: 'info' },
    '🎚️': { icon: 'sliders', tone: 'info' },
    '🎚': { icon: 'sliders', tone: 'info' },
    '🎧': { icon: 'headphones', tone: 'info' },
};
function extractLeadingIcon(text) {
    let m = /^([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2139}])️?\s*/u.exec(text || '');
    if (!m) return { icon: 'alert-circle', tone: 'info', text: text || '' };
    let mapped = EMOJI_ICON_MAP[m[0].trim()] || EMOJI_ICON_MAP[m[1]] || { icon: 'alert-circle', tone: 'info' };
    return { icon: mapped.icon, tone: mapped.tone, text: (text || '').slice(m[0].length) };
}

function escapeHtml(s) {
    let d = document.createElement('div');
    d.innerText = s == null ? '' : String(s);
    return d.innerHTML;
}

// НОВОВВЕДЕНИЕ: Поддержка ожидания клика "ОК" в красивом алерте
window.customAlertCallback = null;

function showBeautifulAlert(message) {
    return new Promise((resolve) => {
        let el = document.getElementById('customAlertText');
        if (el) {
            let { icon, tone, text } = extractLeadingIcon(message);
            let iconEl = document.getElementById('customAlertIcon');
            if (iconEl) {
                iconEl.innerHTML = iconHTML(icon);
                iconEl.className = 'custom-alert-icon icon-tone--' + tone;
            }
            // Используем HTML для форматирования текста (жирный шрифт, переносы)
            el.innerHTML = `<div class="alert-body">${text}</div>`;
            document.getElementById('customAlertOverlay').style.display = 'flex';
            window.customAlertCallback = resolve;
        } else {
            resolve(true);
        }
    });
}

// Вопрос с двумя кнопками в том же окне: resolve(true) — «ok»,
// resolve(false) — «cancel», крестик или Escape.
// Три варианта: → 'ok' (Enter), 'alt' (клавиша altKey), false (Esc / крестик).
async function showBeautifulChoice(message, okText, altText, altKey, cancelText = 'Отмена') {
    let alt = document.getElementById('customAlertAlt');
    alt.innerHTML = `${escapeHtml(altText)} <kbd>${altKey}</kbd>`;
    alt.dataset.key = 'Key' + altKey.toUpperCase();
    alt.style.display = '';
    document.querySelector('#customAlertOverlay .custom-alert-box').classList.add('custom-alert-box--wide');
    let r = await showBeautifulConfirm(message, okText, cancelText);
    return r === 'alt' ? 'alt' : (r ? 'ok' : false);
}

function showBeautifulConfirm(message, okText = 'ОК', cancelText = 'Отмена') {
    let ok = document.getElementById('customAlertOk');
    let cancel = document.getElementById('customAlertCancel');
    ok.innerHTML = `${escapeHtml(okText)} <kbd>Enter</kbd>`;
    cancel.innerHTML = `${escapeHtml(cancelText)} <kbd>Esc</kbd>`;
    cancel.style.display = '';
    return showBeautifulAlert(message);
}

// confirmed=true — закрыли по «ОК»/Enter/Space (действие после алерта
// продолжается); confirmed=false — закрыли крестиком/Escape (это
// отмена, вызвавший код должен остановиться, а не продолжать как
// будто нажали «ОК»).
function closeCustomAlert(confirmed = true) {
    document.getElementById('customAlertOverlay').style.display = 'none';
    // Окно снова обычное «сообщение с ОК» для следующего раза.
    let cancel = document.getElementById('customAlertCancel');
    if (cancel) cancel.style.display = 'none';
    let alt = document.getElementById('customAlertAlt');
    if (alt) alt.style.display = 'none';
    document.querySelector('#customAlertOverlay .custom-alert-box').classList.remove('custom-alert-box--wide');
    let ok = document.getElementById('customAlertOk');
    if (ok) ok.innerHTML = 'ОК <kbd>Enter</kbd>';
    // Если кто-то ждет ответа от алерта - даем сигнал идти дальше
    if (window.customAlertCallback) {
        window.customAlertCallback(confirmed);
        window.customAlertCallback = null;
    }
}

// Клавиши в окне-вопросе: Enter / Space — «ОК», Esc — отмена, своя буква — третий вариант.
// true — окно открыто и клавишу забрали.
function uiAlertKey(e) {
    let alertOverlay = document.getElementById('customAlertOverlay');
    if (!alertOverlay || alertOverlay.style.display !== 'flex') return false;
    if ((e.code === 'Enter' || e.code === 'Space') && e.target.tagName !== 'INPUT') {
        e.preventDefault();
        closeCustomAlert(true);
    } else if (e.code === 'Enter') {
        e.preventDefault();
        closeCustomAlert(true);
    } else if (e.code === 'Escape') {
        e.preventDefault();
        closeCustomAlert(false);
    } else {
        let alt = document.getElementById('customAlertAlt');
        if (alt && alt.style.display !== 'none' && e.code === alt.dataset.key) { e.preventDefault(); closeCustomAlert('alt'); }
    }
    return true;
}

function showToast(msg, duration) {
    let { icon, text } = extractLeadingIcon(msg);
    let toast = document.createElement('div');
    toast.className = 'toast';
    toast.innerHTML = `${iconHTML(icon)}<span>${escapeHtml(text)}</span>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), duration || 2200);
}
