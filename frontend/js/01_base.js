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

let isProcessing = false;
        let currentState = null;
        let mergeParts = [null, null, null, null, null];
        let saveFilenameForMerge = null;
        let playTimeout = null;
        let sumPlaybackTimers = [];
        function clearSumPlaybackTimers() {
            sumPlaybackTimers.forEach(id => clearTimeout(id));
            sumPlaybackTimers = [];
        }

        // Значения по умолчанию — используются кнопкой «Сбросить»
        const CUT_DEFAULTS = { pause: 500, sens: -35, pad: 250 };

        function pauseWord(v)  { return v < 400 ? "Короткая" : (v > 900 ? "Длинная" : "Нормальная"); }
        function sensWord(v)   { return v > -30 ? "Высокая" : (v < -45 ? "Строгая" : "Оптимальная"); }
        function padWord(v)    { return v < 150 ? "Маленький" : (v > 300 ? "Большой" : "Безопасный"); }

        function updateSettingsText() {
            let p = parseInt(document.getElementById('inpPause').value);
            document.getElementById('valPause').innerText = `${pauseWord(p)} · ${p} мс`;

            let s = parseInt(document.getElementById('inpSens').value);
            document.getElementById('valSens').innerText = `${sensWord(s)} · ${s} дБ`;

            let pad = parseInt(document.getElementById('inpPad').value);
            document.getElementById('valPad').innerText = `${padWord(pad)} · ${pad} мс`;

            // Свёрнутые настройки в меню: коротко, что сейчас стоит.
            let sum = document.getElementById('cutSummary');
            if (sum) sum.innerText = `${p} мс · ${String(s).replace('-', '−')} дБ · ${pad} мс`;
        }

        function openMenuHelp() { document.getElementById('menuHelpOverlay').style.display = 'flex'; }
        function closeMenuHelp() { document.getElementById('menuHelpOverlay').style.display = 'none'; }

        // ===== РУЧНОЙ ВВОД НАСТРОЕК НАРЕЗКИ =====

        function openManualSettings() {
            document.getElementById('manPause').value = document.getElementById('inpPause').value;
            document.getElementById('manSens').value  = document.getElementById('inpSens').value;
            document.getElementById('manPad').value   = document.getElementById('inpPad').value;
            updateManualHints();
            document.getElementById('manualOverlay').style.display = 'flex';
            setTimeout(() => document.getElementById('manPause').focus(), 50);
        }

        function closeManualSettings() {
            document.getElementById('manualOverlay').style.display = 'none';
        }

        function resetManualSettings() {
            document.getElementById('manPause').value = CUT_DEFAULTS.pause;
            document.getElementById('manSens').value  = CUT_DEFAULTS.sens;
            document.getElementById('manPad').value   = CUT_DEFAULTS.pad;
            updateManualHints();
        }

        // Ограничиваем значение допустимыми рамками ползунка
        function clampToInput(sliderId, raw, fallback) {
            let slider = document.getElementById(sliderId);
            let v = parseInt(raw);
            if (isNaN(v)) return fallback;
            return Math.min(parseInt(slider.max), Math.max(parseInt(slider.min), v));
        }

        // Живые подсказки: объясняют простым языком, что даст введённое число
        function updateManualHints() {
            let p   = clampToInput('inpPause', document.getElementById('manPause').value, CUT_DEFAULTS.pause);
            let sn  = clampToInput('inpSens',  document.getElementById('manSens').value,  CUT_DEFAULTS.sens);
            let pad = clampToInput('inpPad',   document.getElementById('manPad').value,   CUT_DEFAULTS.pad);

            let hP = document.getElementById('hintPause');
            hP.classList.toggle('is-warn', p < 200 || p > 1500);
            hP.innerHTML = `Разрез произойдёт только там, где тишина длится дольше <b>${(p / 1000).toFixed(2)} сек</b>. `
                + (p < 200
                    ? 'Очень мало: программа разрежет даже короткие вдохи, дублей получится много и они будут рваными.'
                    : p > 1500
                        ? 'Очень много: короткие паузы между фразами программа пропустит, несколько фраз слипнутся в один дубль.'
                        : 'Обычная речевая пауза между фразами — хороший баланс.');

            let hS = document.getElementById('hintSens');
            hS.classList.toggle('is-warn', sn > -25 || sn < -55);
            hS.innerHTML = `Тишиной считается всё, что тише <b>${sn} дБ</b>. `
                + (sn > -25
                    ? 'Порог высокий: программа примет за тишину даже негромкую речь и может срезать начало слова.'
                    : sn < -55
                        ? 'Порог строгий: нужна почти стерильная тишина. При фоновом шуме разрезов почти не будет.'
                        : 'Подходит для обычной студийной записи с лёгким фоновым шумом.');

            let hPad = document.getElementById('hintPad');
            hPad.classList.toggle('is-warn', pad < 80 || pad > 600);
            hPad.innerHTML = `К каждому дублю добавится <b>${pad} мс</b> звука с обеих сторон. `
                + (pad < 80
                    ? 'Запас маленький: есть риск отрезать первый и последний звук слова.'
                    : pad > 600
                        ? 'Запас большой: в дубли попадут куски соседних фраз, придётся дочищать вручную.'
                        : 'Слово гарантированно не обрежется, лишнего почти не попадёт.');
        }

        function applyManualSettings() {
            let p   = clampToInput('inpPause', document.getElementById('manPause').value, CUT_DEFAULTS.pause);
            let sn  = clampToInput('inpSens',  document.getElementById('manSens').value,  CUT_DEFAULTS.sens);
            let pad = clampToInput('inpPad',   document.getElementById('manPad').value,   CUT_DEFAULTS.pad);

            document.getElementById('inpPause').value = p;
            document.getElementById('inpSens').value  = sn;
            document.getElementById('inpPad').value   = pad;

            updateSettingsText();
            closeManualSettings();
            showToast(`Настройки применены: ${p} мс · ${sn} дБ · ${pad} мс`);
        }

        // Пояснения по кнопкам «?»
        const SETTING_HELP = {
            pause: {
                title: 'Длина паузы для разреза',
                body: 'Программа слушает запись и ищет места, где вы молчите. Этот параметр говорит, '
                    + 'насколько долгим должно быть молчание, чтобы считать его концом фразы.<br><br>'
                    + '<b>Бытовой пример:</b> представьте, что вы читаете вслух список. Между словами внутри '
                    + 'предложения вы делаете короткие паузы, а между пунктами списка — длинные. '
                    + 'Здесь вы задаёте, какую паузу считать «между пунктами».<br><br>'
                    + '<b>Меньше число</b> — больше дублей, режет мелко.<br>'
                    + '<b>Больше число</b> — меньше дублей, несколько фраз могут слипнуться.'
            },
            sens: {
                title: 'Чувствительность к тихим звукам',
                body: 'Абсолютной тишины в записи не бывает — всегда есть шум микрофона, дыхание, гул комнаты. '
                    + 'Этот параметр задаёт громкость, ниже которой звук считается тишиной. '
                    + 'Измеряется в децибелах, и число всегда отрицательное: чем оно меньше, тем тише.<br><br>'
                    + '<b>Бытовой пример:</b> это как порог слышимости. Поставьте −20 дБ — программа «глуховата» '
                    + 'и примет за тишину даже негромкую речь. Поставьте −60 дБ — у неё идеальный слух, '
                    + 'и любой шорох она посчитает звуком.<br><br>'
                    + '<b>Ближе к −20</b> — режет охотнее, но может отхватить начало слова.<br>'
                    + '<b>Ближе к −60</b> — осторожнее, но при шумном фоне разрезов почти не будет.'
            },
            header: {
                title: 'Строка с заголовками',
                body: 'Номер строки, в которой написаны названия колонок — например «51-100 миллионов» '
                    + 'или «100-900». Программа берёт их как названия категорий, а фразы читает со '
                    + 'следующей строки.<br><br>'
                    + '<b>Поставьте 0</b>, если подписей сверху нет и данные начинаются прямо с первой '
                    + 'строки — так устроен простой формат «текст в первом столбце, имя файла во втором».<br><br>'
                    + 'Обычно программа определяет это сама, менять вручную нужно редко — например, '
                    + 'если сверху есть лишняя строка с датой или заметкой.'
            },
            pad: {
                title: 'Запас звука по краям',
                body: 'Найдя границу фразы, программа отступает немного назад и немного вперёд, '
                    + 'и только потом режет. Этот отступ и есть запас.<br><br>'
                    + '<b>Бытовой пример:</b> как поля на листе бумаги. Режете точно по буквам — рискуете '
                    + 'срезать край. Оставляете поля — текст цел.<br><br>'
                    + '<b>Меньше число</b> — дубли плотные, но можно потерять первый или последний звук.<br>'
                    + '<b>Больше число</b> — слово точно целое, но в дубль попадёт кусок соседней фразы.'
            }
        };

        function explainSetting(event, key) {
            if (event) { event.preventDefault(); event.stopPropagation(); }
            let h = SETTING_HELP[key];
            if (h) showBeautifulAlert(`<b>${h.title}</b><br><br>${h.body}`);
        }

        document.addEventListener('DOMContentLoaded', () => {
            updateSettingsText();
            loadRecentProjects();
            // Заставки нет: меню показываем сразу, не дожидаясь Python, — одним
            // проявлением. «Продолжить проект?» спросим, когда мост будет готов.
            if (isShown('stage0-splash')) {
                showStage('stage1-loading');
                let m = document.getElementById('stage1-loading');
                m.classList.add('is-boot');
                setTimeout(() => m.classList.remove('is-boot'), 700);
            }
        });

        // Прогрев при запуске: мост к Python готов — заранее берём недавние
        // проекты и один раз невидимо раскладываем меню, чтобы первое же
        // «Начать работу» шло плавно, без расчётов в момент перехода.
        let appWarmed = false;
        function warmUpApp() {
            if (appWarmed || !window.pywebview || !pywebview.api) return;
            appWarmed = true;
            loadRecentProjects();
            loadMenuRecent();
            if (!resumePromptAnswered) enterApp();           // недавний проект — спросить «продолжить?»
            const prerender = () => {
                let menu = document.getElementById('stage1-loading');
                if (!menu || menu.style.display !== 'none') return;
                Object.assign(menu.style, { visibility: 'hidden', position: 'absolute', left: '0', right: '0', top: '0', display: 'flex' });
                void menu.offsetHeight;
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    Object.assign(menu.style, { visibility: '', position: '', left: '', right: '', top: '', display: 'none' });
                }));
            };
            (document.fonts ? document.fonts.ready : Promise.resolve()).then(() =>
                (window.requestIdleCallback || (f => setTimeout(f, 200)))(prerender));
        }
        window.addEventListener('pywebviewready', warmUpApp);
        document.addEventListener('DOMContentLoaded', () => setTimeout(warmUpApp, 50));

        window.addEventListener('blur', () => {
            // Окно потеряло фокус — если W/S были зажаты, keyup может не
            // прийти вовсе (например, alt-tab), и прокрутка иначе крутилась
            // бы бесконечно быстрее и быстрее сама по себе.
            constructorStopHold('KeyW');
            constructorStopHold('KeyS');
        });

        function updateProgress(p, t) {
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('progressBar').value = p;
            document.getElementById('progressText').innerText = t;
            let pct = document.getElementById('progressPct');
            if (pct) pct.innerText = (p > 0 && p <= 100) ? `${Math.round(p)}%` : '';
        }

