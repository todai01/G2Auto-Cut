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

        // ===== ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ =====
        // Каждому экрану нужен свой способ раскладки: заставка и экран подготовки
        // построены на flex, рабочий экран — обычный block. Раньше это значение
        // подставлялось руками в каждой функции, и стоило один раз ошибиться —
        // заставка съезжала в левый край. Теперь оно живёт в одном месте.
        const STAGE_DISPLAY = {
            'stage0-splash':      'flex',
            'stage1-loading':     'flex',
            'stage2-workspace':   'block',
            'stage3-constructor': 'block',
            'stage4-tts':         'flex'
        };

        function showStage(activeId) {
            Object.keys(STAGE_DISPLAY).forEach(id => {
                let el = document.getElementById(id);
                if (el) el.style.display = (id === activeId) ? STAGE_DISPLAY[id] : 'none';
            });
        }

        const motionOK = () => !(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
        const isShown = id => { let el = document.getElementById(id); return !!el && el.style.display !== 'none'; };
        let stageAnimating = false;

        // Прямоугольник самого текста (без отступов кнопки) — для «перелёта» логотипа.
        function textRect(el) {
            let r = document.createRange();
            r.selectNodeContents(el);
            return r.getBoundingClientRect();
        }

        const wait = ms => new Promise(r => setTimeout(r, ms));

        // Подпись по буквам и кнопка «втягиваются» в логотип заставки;
        // логотип при этом коротко «заряжается» светом. Промис — когда всё вошло.
        function absorbIntoLogo(splash, tagline, btn, logo, layer, line) {
            let jobs = [];
            let cx = logo.left + logo.width / 2, cy = logo.top + logo.height * .62;
            if (line) {
                // Линия стягивается к центру, светлеет и уходит вверх в буквы.
                let r = line.getBoundingClientRect();
                let dx = cx - (r.left + r.width / 2), dy = cy - r.top;
                line.style.transformOrigin = '50% 50%';
                jobs.push(line.animate([
                    { transform: 'translate(0,0) scaleX(1)', opacity: 1, background: 'rgba(38,43,52,1)' },
                    { transform: 'translate(0,0) scaleX(.35)', opacity: 1, background: 'rgba(110,170,255,1)', offset: .45 },
                    { transform: `translate(${dx}px, ${dy}px) scaleX(.02)`, opacity: 0, background: 'rgba(150,195,255,1)' }
                ], { duration: 460, delay: 120, easing: 'cubic-bezier(.55,0,.6,.3)', fill: 'forwards' }).finished
                    .then(() => line.remove()));
            }
            if (tagline && tagline.firstChild) {
                let text = tagline.textContent, node = tagline.firstChild;
                let chars = [];
                for (let i = 0; i < text.length; i++) {
                    if (!text[i].trim()) continue;
                    let r = document.createRange();
                    r.setStart(node, i); r.setEnd(node, i + 1);
                    chars.push({ ch: text[i], rect: r.getBoundingClientRect() });
                }
                let cs = getComputedStyle(tagline);
                tagline.style.visibility = 'hidden';
                let n = chars.length;
                chars.forEach((c, i) => {
                    let el = document.createElement('span');
                    el.className = 'fx-char';
                    el.textContent = c.ch;
                    Object.assign(el.style, { left: c.rect.left + 'px', top: c.rect.top + 'px', fontSize: cs.fontSize, color: cs.color, lineHeight: c.rect.height + 'px' });
                    layer.appendChild(el);
                    // Каждая буква — в свою точку внутри логотипа; уходят от краёв к центру.
                    let tx = cx + (i / Math.max(1, n - 1) - .5) * logo.width * .55 - (c.rect.left + c.rect.width / 2);
                    let ty = cy - (c.rect.top + c.rect.height / 2);
                    let order = Math.abs(i - (n - 1) / 2) / ((n - 1) / 2 || 1);
                    jobs.push(el.animate([
                        { transform: 'translate(0,0) scale(1)', opacity: 1 },
                        { transform: `translate(${tx * .35}px, ${ty * .2 + 6}px) scale(.9)`, opacity: 1, offset: .35 },
                        { transform: `translate(${tx}px, ${ty}px) scale(.15)`, opacity: 0 }
                    ], { duration: 420, delay: (1 - order) * 140, easing: 'cubic-bezier(.55,0,.75,.2)', fill: 'forwards' })
                        .finished.then(() => el.remove()));
                });
            }
            if (btn) {
                let r = btn.getBoundingClientRect();
                let dy = cy - (r.top + r.height / 2), dx = cx - (r.left + r.width / 2);
                btn.style.transformOrigin = '50% 50%';
                jobs.push(btn.animate([
                    { transform: 'translate(0,0) scale(1,1)', opacity: 1, filter: 'brightness(1)' },
                    { transform: 'translate(0,0) scale(.92,.12)', opacity: 1, filter: 'brightness(1.8)', offset: .4 },
                    { transform: `translate(${dx}px, ${dy}px) scale(.06,.04)`, opacity: 0, filter: 'brightness(2)' }
                ], { duration: 460, delay: 90, easing: 'cubic-bezier(.55,0,.6,.3)', fill: 'forwards' }).finished);
            }
            // Логотип «заряжается», впитывая подпись и кнопку.
            let mark = splash.querySelector('.splash-mark');
            mark.animate([
                { textShadow: '0 0 0 rgba(120,175,255,0)' },
                { textShadow: '0 0 26px rgba(120,175,255,.55)', offset: .8 },
                { textShadow: '0 0 18px rgba(120,175,255,.35)' }
            ], { duration: 560, easing: 'ease-in', fill: 'forwards' });
            return Promise.all(jobs).catch(() => {});
        }

        // Прямоугольник элемента в КОНЕЧНОМ положении: анимации предков
        // (меню ещё «въезжает») на миг проматываем в конец и возвращаем.
        function finalRect(el, measure) {
            let anims = [];
            for (let n = el; n && n.getAnimations; n = n.parentElement) {
                n.getAnimations().forEach(an => anims.push([an, an.currentTime]));
            }
            anims.forEach(([an]) => { let t = an.effect && an.effect.getComputedTiming(); if (t) an.currentTime = t.endTime; });
            let r = measure(el);
            anims.forEach(([an, t]) => { an.currentTime = t; });
            return r;
        }

        // Буквы логотипа с их прямоугольниками: каждая полетит отдельно.
        function logoLetters(markEl) {
            let out = [];
            markEl.childNodes.forEach(node => {
                let accent = node.nodeType === 1;
                let text = node.textContent;
                let textNode = accent ? node.firstChild : node;
                for (let i = 0; i < text.length; i++) {
                    let r = document.createRange();
                    r.setStart(textNode, i); r.setEnd(textNode, i + 1);
                    out.push({ ch: text[i], accent, rect: r.getBoundingClientRect() });
                }
            });
            return out;
        }

        // Заставка → меню. Хореография:
        //  1) подпись, кнопка и список уходят;
        //  2) линия под подписью растягивается в нижнюю границу шапки;
        //  3) буквы GVox по одной перелетают по дуге в шапку (с размытием в движении);
        //  4) логотип вспыхивает при посадке, проявляется шапка, карточки встают лесенкой.
        async function animateSplashToMenu() {
            stageAnimating = true;
            let splash = document.getElementById('stage0-splash');
            let mark = splash.querySelector('.splash-mark');
            let tagline = splash.querySelector('.entry__tagline');
            let startBtn = splash.querySelector('.entry__start');

            // Исходные позиции — пока заставка ещё нетронута.
            let from = logoLetters(mark);
            let wordA = textRect(mark);
            let fontSize = parseFloat(getComputedStyle(mark).fontSize);
            let lineA = tagline ? tagline.getBoundingClientRect() : null;

            let layer = document.createElement('div');
            layer.className = 'fx-layer';
            document.body.appendChild(layer);
            let jobs = [];

            // Линия-разделитель отделяется от подписи и ждёт своего полёта.
            let line = null;
            if (lineA) {
                line = document.createElement('div');
                line.className = 'fx-line is-resting';
                Object.assign(line.style, { left: lineA.left + 'px', top: (lineA.bottom - 1) + 'px', width: lineA.width + 'px' });
                layer.appendChild(line);
            }

            // Подпись и кнопка «втягиваются» в логотип.
            let absorb = absorbIntoLogo(splash, tagline, startBtn, wordA, layer, line);
            splash.classList.add('is-leaving');
            await absorb;

            let menu = document.getElementById('stage1-loading');
            menu.classList.add('menu-entering');
            showMenuNow();
            menu.classList.add('menu-line-pending');
            splash.classList.remove('is-leaving');
            splash.getAnimations({ subtree: true }).forEach(an => an.cancel());
            if (tagline) tagline.style.visibility = '';

            let target = menu.querySelector('.setup-brand__mark');
            let header = menu.querySelector('.setup-header');
            let wordB = finalRect(target, textRect);
            let headB = finalRect(header, el => el.getBoundingClientRect());
            let k = wordB.height / wordA.height;
            target.style.visibility = 'hidden';

            // Сначала «Vox» по дуге собирается в шапке; «G» ждёт на месте.
            let gJob = null, gOrigin = null;
            const place = L => ({
                tx: wordB.left + (L.rect.left - wordA.left) * k - L.rect.left,
                ty: wordB.top + (L.rect.top - wordA.top) * k - L.rect.top
            });
            const spawn = L => {
                let el = document.createElement('span');
                el.className = 'fx-letter' + (L.accent ? ' is-accent' : '');
                el.textContent = L.ch;
                Object.assign(el.style, { left: L.rect.left + 'px', top: L.rect.top + 'px', fontSize: fontSize + 'px', lineHeight: L.rect.height + 'px' });
                layer.appendChild(el);
                return el;
            };
            let vox = from.filter(L => L.accent), g = from.filter(L => !L.accent);
            vox.forEach((L, i) => {
                let el = spawn(L), { tx, ty } = place(L);
                let lift = 34 + i * 3;
                jobs.push(el.animate([
                    { transform: 'translate(0,0) scale(1)', filter: 'blur(0)', offset: 0 },
                    { transform: `translate(${tx * .18}px, ${ty * .1 - lift}px) scale(${1 - (1 - k) * .25})`, filter: 'blur(.6px)', offset: .28 },
                    { transform: `translate(${tx * .78}px, ${ty * .82}px) scale(${k + (1 - k) * .12})`, filter: 'blur(1.4px)', offset: .72 },
                    { transform: `translate(${tx}px, ${ty}px) scale(${k})`, filter: 'blur(0)', offset: 1 }
                ], { duration: 820, delay: 40 + i * 50, easing: 'cubic-bezier(.65,0,.2,1)', fill: 'forwards' }).finished);
            });
            // «G» — рогатка: пока «Vox» летит, она натягивается назад (от цели),
            // копит свечение и дрожит от напряжения — и выстреливает в шапку.
            // Её посадка запускает волну.
            g.forEach(L => {
                let el = spawn(L), { tx, ty } = place(L);
                el.classList.add('is-g');
                gOrigin = { x: L.rect.left + tx + L.rect.width * k / 2, y: L.rect.top + ty + L.rect.height * k / 2 };
                let n = Math.hypot(tx, ty) || 1, ux = tx / n, uy = ty / n;
                const back = d => `translate(${-ux * d}px, ${-uy * d}px)`;
                const glow = a => `0 0 ${8 + a * 26}px rgba(120,175,255,${(.15 + a * .6).toFixed(2)})`;
                gJob = el.animate([
                    { transform: 'translate(0,0) scale(1)', textShadow: glow(0), filter: 'blur(0)', easing: 'cubic-bezier(.4,0,.6,1)' },
                    { transform: `${back(34)} scale(1.07, .95)`, textShadow: glow(.8), offset: .6, easing: 'linear' },
                    { transform: `translate(${-ux * 35 + 1.6}px, ${-uy * 35 - 1.2}px) scale(1.08, .94)`, textShadow: glow(.9), offset: .64, easing: 'linear' },
                    { transform: `translate(${-ux * 36 - 1.6}px, ${-uy * 36 + 1.2}px) scale(1.08, .94)`, textShadow: glow(.95), offset: .68, easing: 'linear' },
                    { transform: `${back(38)} scale(1.09, .93)`, textShadow: glow(1), filter: 'blur(0)', offset: .72, easing: 'cubic-bezier(.9,0,.35,1)' },
                    { transform: `translate(${tx + ux * 6}px, ${ty + uy * 6}px) scale(${k * 1.06}, ${k * .96})`, textShadow: glow(.6), filter: 'blur(2.5px)', offset: .93, easing: 'cubic-bezier(.2,.8,.3,1)' },
                    { transform: `translate(${tx}px, ${ty}px) scale(${k})`, textShadow: glow(0), filter: 'blur(0)' }
                ], { duration: 1320, delay: 0, fill: 'forwards' }).finished;
                jobs.push(gJob);
                // Волна стартует ровно в момент касания (93% полёта «G»), не дожидаясь усадки.
                setTimeout(() => {
                    revealMenuFromLogo(menu, gOrigin);
                    drawHeaderLine(menu, headB, gOrigin.x);
                }, Math.round(1320 * .93));
            });

            await Promise.all(jobs).catch(() => {});
            target.style.visibility = '';
            target.classList.add('is-landing');
            layer.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140 }).finished
                .catch(() => {}).then(() => layer.remove());
            if (!gOrigin) {
                let lr = target.getBoundingClientRect();
                revealMenuFromLogo(menu, { x: lr.left + lr.width / 2, y: lr.top + lr.height / 2 });
            }
            setTimeout(() => target.classList.remove('is-landing'), 1400);
            stageAnimating = false;
        }

        // Посадка логотипа «включает» меню: от логотипа расходится световая
        // волна, и каждый элемент проявляется, когда она до него доходит —
        // ближние раньше, дальние позже, чуть «вытягиваясь» со стороны логотипа.
        function revealMenuFromLogo(menu, origin) {
            let ox = origin.x, oy = origin.y;
            let items = Array.from(menu.querySelectorAll(
                '.setup-brand__sub, .setup-header__right, .section-label, .rise'))
                .filter(el => el.offsetParent !== null);
            let R = Math.hypot(Math.max(ox, innerWidth - ox), Math.max(oy, innerHeight - oy));
            const WAVE_MS = 1100;  // волна быстро стартует и замедляется к краям (easeOutCubic)
            // Момент, когда кольцо (easeOutCubic) доходит до расстояния d.
            const reach = d => WAVE_MS * (1 - Math.cbrt(1 - Math.min(1, d / R)));

            // Вспышка и два кольца (яркое ведущее + мягкое следом) рисуются на
            // одном холсте покадрово: никаких огромных слоёв с размытыми тенями,
            // которые подвешивали первый кадр волны.
            drawWaveCanvas(ox, oy, R, WAVE_MS);

            // Каждый элемент включается, когда его касается кольцо: с пружинкой
            // и короткой вспышкой рамки. fill: backwards держит их скрытыми до очереди.
            items.forEach(el => {
                let r = el.getBoundingClientRect();
                let cx = Math.max(r.left, Math.min(ox, r.right));
                let cy = Math.max(r.top, Math.min(oy, r.bottom));
                let dx = cx - ox, dy = cy - oy;
                let n = Math.hypot(dx, dy) || 1;
                let delay = reach(n);
                el.animate([
                    { opacity: 0, transform: `translate(${-dx / n * 22}px, ${-dy / n * 22}px) scale(.94)` },
                    { opacity: 1, transform: `translate(${dx / n * 2}px, ${dy / n * 2}px) scale(1.012)`, offset: .62 },
                    { opacity: 1, transform: 'none' }
                ], { duration: 520, delay, easing: 'cubic-bezier(.2,.8,.3,1)', fill: 'backwards' });
                if (el.matches('.option-card, .menu-row, .menu-tool, .menu-cut')) traceBorder(el, ox, oy, delay);
            });
            menu.classList.add('menu-fx');
            menu.classList.remove('menu-entering');
        }

        // Граница шапки прорисовывается, когда «G» встала на место: линия
        // растёт от «G» вправо, по ней бежит яркая «головка».
        function drawHeaderLine(menu, headB, fromX) {
            let y = headB.bottom - 1;
            let x0 = Math.max(headB.left, Math.min(fromX, headB.right));
            let left = document.createElement('div'), right = document.createElement('div');
            let head = document.createElement('div');
            left.className = right.className = 'fx-line fx-line--draw';
            head.className = 'fx-head';
            // Левый короткий кусок (до края шапки) и правый — от «G» до правого края.
            Object.assign(left.style, { left: headB.left + 'px', top: y + 'px', width: (x0 - headB.left) + 'px', transformOrigin: '100% 50%' });
            Object.assign(right.style, { left: x0 + 'px', top: y + 'px', width: (headB.right - x0) + 'px' });
            Object.assign(head.style, { left: x0 + 'px', top: y + 'px' });
            document.body.append(left, right, head);
            const D = 820, E = 'cubic-bezier(.5,0,.2,1)';
            left.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: 260, easing: 'ease-out', fill: 'both' });
            right.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: D, easing: E, fill: 'both' });
            head.animate([
                { transform: 'translate(-50%,-50%) translateX(0)', opacity: 1 },
                { opacity: 1, offset: .85 },
                { transform: `translate(-50%,-50%) translateX(${headB.right - x0}px)`, opacity: 0 }
            ], { duration: D, easing: E, fill: 'both' });
            // Нарисованная линия гаснет — под ней проявляется настоящая граница шапки.
            setTimeout(() => menu.classList.remove('menu-line-pending'), D);
            [left, right, head].forEach(el => el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, delay: D, fill: 'forwards' })
                .finished.catch(() => {}).then(() => el.remove()));
        }

        // Волна на холсте: вспышка в точке «G» и два кольца с мягким свечением
        // (свечение — несколько широких полупрозрачных обводок, без shadowBlur).
        function drawWaveCanvas(ox, oy, R, waveMs) {
            let dpr = Math.min(2, window.devicePixelRatio || 1);
            let cv = document.createElement('canvas');
            cv.className = 'fx-canvas';
            cv.width = Math.round(innerWidth * dpr); cv.height = Math.round(innerHeight * dpr);
            document.body.appendChild(cv);
            let ctx = cv.getContext('2d');
            ctx.scale(dpr, dpr);
            const easeOut = t => 1 - Math.pow(1 - t, 3);
            const rings = [
                { delay: 0, dur: waveMs, alpha: 1, width: 2 },
                { delay: 110, dur: waveMs * 1.25, alpha: .45, width: 1.2 }
            ];
            const total = Math.max(...rings.map(r => r.delay + r.dur));
            let t0 = performance.now();
            const frame = now => {
                let t = now - t0;
                ctx.clearRect(0, 0, innerWidth, innerHeight);
                // Вспышка
                if (t < 420) {
                    let p = t / 420, rr = 14 + 100 * easeOut(p);
                    let g = ctx.createRadialGradient(ox, oy, 0, ox, oy, rr);
                    g.addColorStop(0, `rgba(170,205,255,${.75 * (1 - p)})`);
                    g.addColorStop(.4, `rgba(77,149,234,${.28 * (1 - p)})`);
                    g.addColorStop(1, 'rgba(77,149,234,0)');
                    ctx.fillStyle = g;
                    ctx.beginPath(); ctx.arc(ox, oy, rr, 0, Math.PI * 2); ctx.fill();
                }
                rings.forEach(w => {
                    let p = (t - w.delay) / w.dur;
                    if (p <= 0 || p >= 1) return;
                    let rad = R * 1.05 * easeOut(p);
                    let a = w.alpha * (p < .7 ? 1 : 1 - (p - .7) / .3);
                    ctx.beginPath(); ctx.arc(ox, oy, rad, 0, Math.PI * 2);
                    [[16, .05], [9, .09], [4, .18]].forEach(([lw, k]) => {
                        ctx.strokeStyle = `rgba(77,149,234,${a * k})`; ctx.lineWidth = lw; ctx.stroke();
                    });
                    ctx.strokeStyle = `rgba(140,190,255,${a * .9})`; ctx.lineWidth = w.width; ctx.stroke();
                });
                if (t < total) requestAnimationFrame(frame); else cv.remove();
            };
            requestAnimationFrame(frame);
        }

        // «Активация» карточки: от точки, где её коснулась волна, по рамке в обе
        // стороны бегут две полоски света, встречаются напротив — и вся рамка
        // коротко вспыхивает.
        function traceBorder(card, ox, oy, delay) {
            let r = card.getBoundingClientRect();
            let deg = Math.atan2(ox - (r.left + r.width / 2), -(oy - (r.top + r.height / 2))) * 180 / Math.PI;
            // Элемент подсветки создаём ровно в момент касания — не все сразу.
            setTimeout(() => {
                let tr = document.createElement('span');
                tr.className = 'fx-trace';
                tr.style.setProperty('--fx-start', deg + 'deg');
                card.appendChild(tr);
                tr.animate([
                    { '--fx-p': '0deg', opacity: 1 },
                    { '--fx-p': '180deg', opacity: 1, offset: .72 },
                    { '--fx-p': '180deg', opacity: 0 }
                ], { duration: 820, easing: 'cubic-bezier(.45,.05,.35,1)', fill: 'both' })
                    .finished.catch(() => {}).then(() => tr.remove());
            }, delay);
        }

        // Запоминаем, что рабочий экран уже открывался: тогда из меню
        // можно вернуться к работе одной кнопкой, ничего не загружая заново.
        let workspaceReady = false;

        // Вопрос «Хотите продолжить проект?» — спрашиваем только один раз за
        // текущий запуск программы. Если пользователь уже ответил (неважно,
        // «Продолжить» или «Начать заново»), повторные нажатия «Начать
        // работу» на заставке сразу ведут в меню, без повторного вопроса.
        let resumePromptAnswered = false;

        async function showSplash() {
            // Меню → заставка: меню мягко гаснет, заставка проявляется заново.
            if (isShown('stage1-loading') && motionOK() && !stageAnimating) {
                stageAnimating = true;
                let menu = document.getElementById('stage1-loading');
                await menu.animate([{ opacity: 1, filter: 'blur(0)' }, { opacity: 0, filter: 'blur(6px)' }],
                                   { duration: 260, easing: 'ease-in' }).finished.catch(() => {});
                stageAnimating = false;
            }
            showStage('stage0-splash');
            loadRecentProjects();
        }

        // ===== НЕДАВНИЕ ПРОЕКТЫ =====
        let recentProjectsCache = [];

        function escapeHtml(s) {
            let d = document.createElement('div');
            d.innerText = s == null ? '' : String(s);
            return d.innerHTML;
        }

        function formatRecentTime(ts) {
            if (!ts) return '';
            let diffMin = Math.floor(Date.now() / 1000 - ts) / 60;
            if (diffMin < 1) return 'только что';
            if (diffMin < 60) return `${Math.floor(diffMin)} мин назад`;
            let diffH = diffMin / 60;
            if (diffH < 24) return `${Math.floor(diffH)} ч назад`;
            return `${Math.floor(diffH / 24)} дн назад`;
        }

        async function loadRecentProjects() {
            let panel = document.getElementById('recentProjectsPanel');
            let list = document.getElementById('recentProjectsList');
            if (!panel || !list) return;

            let items = [];
            try { items = await pywebview.api.get_recent_projects(); recentsLoaded = true; } catch (e) { items = []; }
            recentProjectsCache = Array.isArray(items) ? items : [];

            if (!recentProjectsCache.length) {
                panel.style.display = 'none';
                return;
            }

            list.innerHTML = recentProjectsCache.slice(0, 4).map((it, idx) => `
                <button class="menu-recent__item" onclick="openRecentProject(${idx})" title="${escapeHtml(it.path || '')}">
                    <span class="menu-recent__icon">${iconHTML('folder')}</span>
                    <span class="menu-recent__name">${escapeHtml(it.name)}</span>
                    <span class="menu-recent__time">${formatRecentTime(it.updated_at)}</span>
                </button>`).join('');
            panel.style.display = 'block';
        }

        async function openRecentProject(idx) {
            let item = recentProjectsCache[idx];
            if (!item) return;

            updateProgress(0, 'Продолжаем проект...');
            document.getElementById('progressContainer').style.display = 'block';
            let state = await pywebview.api.open_recent_project(item.path);
            document.getElementById('progressContainer').style.display = 'none';

            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                loadRecentProjects(); // вдруг папка пропала — обновим список
                return;
            }

            if (state && state.tts) { openTtsScreen(state); return; }
            updateUI(state);
            showWorkspace();
        }

        // Заставка -> экран подготовки проекта. Если есть недавний проект —
        // сперва спрашиваем, продолжать ли его, а не сразу открываем
        // подготовку нового.
        async function enterApp() {
            if (resumePromptAnswered) {
                showMenu();
                return;
            }

            if (!recentsLoaded) {
                let items = [];
                try { items = await pywebview.api.get_recent_projects(); } catch (e) { items = []; }
                recentProjectsCache = Array.isArray(items) ? items : [];
                recentsLoaded = true;
            }

            if (recentProjectsCache.length) {
                document.getElementById('resumeProjectName').innerText = recentProjectsCache[0].name;
                document.getElementById('resumeProjectOverlay').style.display = 'flex';
            } else {
                showMenu();
            }
        }

        async function confirmResumeProject() {
            resumePromptAnswered = true;
            document.getElementById('resumeProjectOverlay').style.display = 'none';
            await openRecentProject(0);
        }

        function declineResumeProject() {
            resumePromptAnswered = true;
            document.getElementById('resumeProjectOverlay').style.display = 'none';
            showMenu();
        }

        function showMenu() {
            if (stageAnimating) return;
            if (isShown('stage0-splash') && motionOK()) { animateSplashToMenu(); return; }
            showMenuNow();
        }

        function showMenuNow() {
            // Следы прошлого входа из заставки: обычные анимации меню — снова как есть.
            document.getElementById('stage1-loading').classList.remove('menu-fx', 'menu-line-pending');
            detachEmbeddedAudacity(true);
            embedAreaId = 'audacityEmbedArea';
            embedBtnId = 'btnEmbedAudacity';
            showStage('stage1-loading');

            // Кнопка возврата появляется, только если работать уже есть с чем
            let btnResume = document.getElementById('btnResume');
            if (btnResume) btnResume.style.display = workspaceReady ? 'inline-flex' : 'none';

            // Перезапускаем появление блоков «лесенкой»
            document.getElementById('stage1-loading').querySelectorAll('.rise').forEach(el => {
                el.style.animation = 'none';
                void el.offsetWidth;
                el.style.animation = '';
            });
            loadMenuRecent();
        }

        // Недавние проекты прямо в меню — открыть в один клик.
        let recentsLoaded = false;
        let menuRecentSig = null;
        async function loadMenuRecent() {
            // Сначала — мгновенно из уже загруженного списка (переход в меню
            // не ждёт Python), потом тихо обновляем, только если что-то поменялось.
            if (recentsLoaded) renderMenuRecent();
            let items;
            try { items = await pywebview.api.get_recent_projects(); } catch (e) { return; }
            recentProjectsCache = Array.isArray(items) ? items : [];
            recentsLoaded = true;
            if (!stageAnimating) renderMenuRecent();
        }
        function renderMenuRecent() {
            let box = document.getElementById('menuRecent');
            let list = document.getElementById('menuRecentList');
            if (!box || !list) return;
            let sig = JSON.stringify(recentProjectsCache.slice(0, 4).map(it => [it.name, it.path, it.updated_at]));
            if (sig === menuRecentSig) return;
            menuRecentSig = sig;
            if (!recentProjectsCache.length) { box.style.display = 'none'; return; }
            list.innerHTML = recentProjectsCache.slice(0, 4).map((it, idx) => `
                <button class="menu-recent__item rise" style="--d: ${6 + idx}" onclick="openRecentProject(${idx})" title="${escapeHtml(it.path || '')}">
                    <span class="menu-recent__icon">${iconHTML('folder')}</span>
                    <span class="menu-recent__name">${escapeHtml(it.name)}</span>
                    <span class="menu-recent__time">${formatRecentTime(it.updated_at)}</span>
                </button>`).join('');
            box.style.display = 'block';
        }

        // Очистить список недавних: первый клик спрашивает, второй — очищает.
        let menuRecentClearTimer = null;
        async function clearMenuRecent() {
            let btn = document.getElementById('menuRecentClear');
            if (!btn.classList.contains('is-confirm')) {
                btn.classList.add('is-confirm');
                btn.textContent = 'Точно очистить?';
                clearTimeout(menuRecentClearTimer);
                menuRecentClearTimer = setTimeout(() => { btn.classList.remove('is-confirm'); btn.textContent = 'Очистить'; }, 3000);
                return;
            }
            clearTimeout(menuRecentClearTimer);
            btn.classList.remove('is-confirm');
            btn.textContent = 'Очистить';
            try { await pywebview.api.clear_recent_projects(); } catch (e) {}
            let box = document.getElementById('menuRecent');
            if (box && box.animate) {
                await box.animate([{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(6px)' }],
                                  { duration: 220, easing: 'ease-in' }).finished.catch(() => {});
            }
            recentProjectsCache = [];
            menuRecentSig = null;
            if (box) box.style.display = 'none';
            let splashPanel = document.getElementById('recentProjectsPanel');
            if (splashPanel) splashPanel.style.display = 'none';
            showToast('Список недавних проектов очищен');
        }

        // «Прожектор» в меню: карточка под курсором знает, где мышь (--mx/--my).
        (function initMenuSpotlight() {
            const SEL = '.option-card, .menu-row, .menu-tool, .menu-recent__item, .menu-cut';
            let stage = document.getElementById('stage1-loading');
            if (!stage) return;
            let raf = 0, last = null;
            stage.addEventListener('pointermove', e => {
                last = e;
                if (raf) return;
                raf = requestAnimationFrame(() => {
                    raf = 0;
                    let card = last.target.closest && last.target.closest(SEL);
                    if (!card || !stage.contains(card)) return;
                    let r = card.getBoundingClientRect();
                    // zoom у сетки меню: clientX в экранных пикселях, а --mx — в CSS-пикселях карточки.
                    let k = card.offsetWidth ? r.width / card.offsetWidth : 1;
                    card.style.setProperty('--mx', ((last.clientX - r.left) / k) + 'px');
                    card.style.setProperty('--my', ((last.clientY - r.top) / k) + 'px');
                });
            }, { passive: true });
        })();

        // Тот же «прожектор» на кнопке заставки.
        (function initSplashSpotlight() {
            let btn = document.querySelector('#stage0-splash .entry__start');
            if (!btn) return;
            btn.addEventListener('pointermove', e => {
                let r = btn.getBoundingClientRect();
                btn.style.setProperty('--mx', (e.clientX - r.left) + 'px');
                btn.style.setProperty('--my', (e.clientY - r.top) + 'px');
            }, { passive: true });
        })();

        // Плавное раскрытие «Настроек нарезки» (у <details> анимации нет).
        function toggleMenuCut(e) {
            let det = e.currentTarget.parentElement;
            let body = document.getElementById('menuCutBody');
            if (!body || !body.animate || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            e.preventDefault();
            if (det.dataset.anim) return;
            det.dataset.anim = '1';
            const done = () => { delete det.dataset.anim; body.style.overflow = ''; };
            body.style.overflow = 'hidden';
            if (!det.open) {
                det.open = true;
                let h = body.scrollHeight;
                body.animate([{ height: '0px', opacity: 0 }, { height: h + 'px', opacity: 1 }],
                             { duration: 260, easing: 'cubic-bezier(.2,.7,.3,1)' }).onfinish = done;
            } else {
                let h = body.scrollHeight;
                body.animate([{ height: h + 'px', opacity: 1 }, { height: '0px', opacity: 0 }],
                             { duration: 200, easing: 'ease-in' }).onfinish = () => { det.open = false; done(); };
            }
        }

        function showWorkspace() {
            workspaceReady = true;
            embedAreaId = 'audacityEmbedArea';
            embedBtnId = 'btnEmbedAudacity';
            showStage('stage2-workspace');
        }

        function resumeWorkspace() {
            if (!workspaceReady) return;
            showWorkspace();
        }

        // Подсказка в шапке экрана подготовки
        function setSetupStatus(text, ready) {
            let el = document.getElementById('setupStatus');
            if (!el) return;
            el.innerText = text;
            el.classList.toggle('setup-status--ready', !!ready);
        }

        function resetSilence() { document.getElementById('addSilence').checked = false; }

        // Полоса общего прогресса: проверенные, готовые и переменные в одной шкале
        function updateProjectProgress(stats) {
            let total = stats.total || 0;
            let bar = document.getElementById('projectProgress');
            if (!bar) return;

            if (!total) {
                bar.style.display = 'none';
                return;
            }
            bar.style.display = 'flex';

            // На полосе только реально существующие файлы: готовые и переменные.
            // Отметка клавишей W — это пометка фразы, а не файл на диске,
            // мешать её сюда значило бы рисовать прогресс, которого нет.
            let good = Math.min(stats.good || 0, total);
            let vars = Math.min(stats.var || 0, Math.max(0, total - good));
            let pct = v => (v / total * 100).toFixed(2) + '%';

            document.getElementById('barGood').style.width = pct(good);
            document.getElementById('barVar').style.width = pct(vars);

            let done = Math.min(total, good + vars);
            document.getElementById('progressLabel').innerText =
                `${Math.round(done / total * 100)}% · осталось ${total - done}`;
        }

        // Лента дублей: соседние дубли с их статусом, клик — переход
        const STRIP_TITLES = {
            checked: 'В «Проверенных»',
            var:     'В «Переменных»',
            none:    'Ещё не разобран'
        };

        function renderChunkStrip(strip) {
            let panel = document.getElementById('stripPanel');
            if (!panel) return;

            // В режиме «Суммы» вместо этой ленты — лента карточек для перетаскивания.
            if (sumModeActive || !strip || !strip.items || !strip.items.length) {
                panel.style.display = 'none';
                return;
            }
            panel.style.display = 'block';

            document.getElementById('stripRange').innerText =
                `${strip.from}–${strip.to} из ${strip.total}`;

            document.getElementById('stripRail').innerHTML = strip.items.map(it => {
                let title = `Дубль ${it.num} · ${STRIP_TITLES[it.status] || ''}\n${it.name}`;
                return `<button class="strip-cell strip-cell--${it.status}${it.current ? ' is-current' : ''}"`
                     + ` title="${title.replace(/"/g, '&quot;')}" onclick="jumpToChunk(${it.index})"></button>`;
            }).join('');
        }

        async function jumpToChunk(index) {
            let state = await pywebview.api.dispatch('jump', {index: index});
            if (state) updateUI(state);
        }

        // ===== ПОЛЗУНОК БЫСТРОЙ НАВИГАЦИИ ПО ДУБЛЯМ =====

        let trackTotal = 0;      // всего дублей
        let trackPos = 0;        // текущий номер, с единицы
        let trackDragging = false;

        function updateChunkTrack(counter) {
            // Пока тянут ползунок, состояние с сервера его не дёргает
            if (trackDragging) return;

            let m = String(counter || '').match(/(\d+)\s*\/\s*(\d+)/);
            if (!m) { trackTotal = 0; paintChunkTrack(0); return; }

            trackPos = parseInt(m[1]);
            trackTotal = parseInt(m[2]);
            paintChunkTrack(trackTotal > 1 ? (trackPos - 1) / (trackTotal - 1) : 0);
        }

        function paintChunkTrack(ratio) {
            let dot = document.getElementById('chunkTrackDot');
            let fill = document.getElementById('chunkTrackFill');
            if (!dot || !fill) return;

            let pct = (ratio * 100) + '%';
            dot.style.left = pct;
            fill.style.width = pct;
        }

        function trackIndexFromEvent(e) {
            let track = document.getElementById('chunkTrack');
            let rect = track.getBoundingClientRect();
            if (!rect.width) return 0;

            let ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
            return { ratio: ratio, index: Math.round(ratio * (trackTotal - 1)) };
        }

        function showTrackBubble(ratio, index) {
            let bubble = document.getElementById('chunkTrackBubble');
            bubble.style.left = (ratio * 100) + '%';
            bubble.innerText = `${index + 1} / ${trackTotal}`;
            bubble.classList.add('is-visible');
        }

        function setupChunkTrack() {
            let track = document.getElementById('chunkTrack');
            if (!track) return;

            track.addEventListener('pointerdown', e => {
                if (trackTotal < 2) return;
                e.preventDefault();
                trackDragging = true;
                track.classList.add('is-dragging');
                track.setPointerCapture(e.pointerId);

                let p = trackIndexFromEvent(e);
                paintChunkTrack(p.ratio);
                showTrackBubble(p.ratio, p.index);
            });

            track.addEventListener('pointermove', e => {
                if (!trackDragging) return;
                let p = trackIndexFromEvent(e);
                paintChunkTrack(p.ratio);
                showTrackBubble(p.ratio, p.index);
            });

            // Переход делаем один раз, когда кнопку отпустили: дёргать Python
            // на каждое движение мыши при 900 дублях — верный способ подвесить окно
            let finish = async e => {
                if (!trackDragging) return;
                trackDragging = false;
                track.classList.remove('is-dragging');
                document.getElementById('chunkTrackBubble').classList.remove('is-visible');
                try { track.releasePointerCapture(e.pointerId); } catch (err) {}

                let p = trackIndexFromEvent(e);
                await jumpToChunk(p.index);
            };

            track.addEventListener('pointerup', finish);
            track.addEventListener('pointercancel', finish);
        }

        document.addEventListener('DOMContentLoaded', setupChunkTrack);

        async function handleLoad(apiPromise) {
            let state = await apiPromise;
            updateUI(state);
            if (state.has_audio) { showWorkspace(); playAudio(); }
        }

        // Подсветка карточки «Загрузить текст (Excel)».
        // Раньше этот код был продублирован в двух местах и мог разойтись.
        let excelIsLoaded = false;
        function markExcelLoaded(fileName) {
            excelIsLoaded = true;
            let btnExcel = document.getElementById('btnLoadExcel');
            if (!btnExcel) return;

            btnExcel.classList.add('loaded');
            let descExcel = document.getElementById('descExcel');
            if (descExcel) descExcel.innerHTML = `<b>${fileName}</b>`;

            setSetupStatus('Шаг 2 · Таблица подключена — выберите аудио или режим', true);
        }

        // «×» на загруженной карточке: сбросить и загрузить заново.
        async function clearLoaded(e, what) {
            e.stopPropagation(); e.preventDefault();
            let label = what === 'excel' ? 'таблицу с текстом' : 'проект (нарезку и чанки)';
            let ok = await showBeautifulConfirm(`ℹ️ <b>Сбросить ${label}?</b><br><br>`
                + (what === 'excel' ? 'Фразы из таблицы будут выгружены — можно загрузить другую.'
                                    : 'Проект закроется (файлы на диске не трогаются, прогресс сохранён) — можно нарезать или открыть заново.'),
                'Сбросить', 'Отмена');
            if (!ok) return;
            try { await pywebview.api.clear_loaded(what); } catch (_) {}
            if (what === 'excel') {
                excelIsLoaded = false;
                document.getElementById('btnLoadExcel').classList.remove('loaded');
                document.getElementById('descExcel').innerText = 'Таблица не выбрана';
            } else {
                ['btnLoadAudio', 'btnLoadFolder'].forEach(id => document.getElementById(id).classList.remove('loaded'));
                document.getElementById('descAudio').innerText = 'Новый проект';
                document.getElementById('descFolder').innerText = 'Продолжить работу';
                workspaceReady = false;
                let br = document.getElementById('btnResume');
                if (br) br.style.display = 'none';
            }
            setSetupStatus(excelIsLoaded ? 'Шаг 2 · Таблица подключена — выберите аудио или режим'
                                         : 'Шаг 1 · Подключите таблицу с текстом', excelIsLoaded);
            showToast(what === 'excel' ? 'Таблица сброшена' : 'Проект сброшен');
        }

        // ===== ЧТЕНИЕ ТАБЛИЦЫ: ВЫБОР КОЛОНОК =====

        let excelInfo = null;
        let excelPreviewTimer = null;
        let excelAnalyzeTimer = null;

        function excelError(msg) {
            showBeautifulAlert(`❌ <b>Таблица не загружена</b><br><br>${String(msg).replace(/\n/g, '<br>')}`);
        }

        // Загрузку Excel запустили из аудита — после неё аудит продолжится сам.
        let pendingAuditAfterExcel = false;
        async function loadExcel() {
            let picked;
            try {
                picked = await pywebview.api.pick_excel();
            } catch (e) { pendingAuditAfterExcel = false; excelError(e); return; }

            if (!picked || picked.error === 'cancel') { pendingPremadeAfterExcel = false; pendingAuditAfterExcel = false; return; }
            if (picked.error) { pendingPremadeAfterExcel = false; pendingAuditAfterExcel = false; excelError(picked.error); return; }

            await analyzeExcel(true);
        }

        // 0 — допустимое значение («заголовков нет»), поэтому обычное || здесь нельзя
        function excelHeaderRow() {
            let v = parseInt(document.getElementById('excelHeaderRow').value);
            return isNaN(v) || v < 0 ? 0 : v;
        }

        async function analyzeExcel(openDialog) {
            let info;
            try {
                // При первом открытии строку заголовков определяет сам Python
                info = openDialog ? await pywebview.api.analyze_excel()
                                  : await pywebview.api.analyze_excel(excelHeaderRow());
            } catch (e) { excelError(e); return; }

            if (!info) { excelError('Пустой ответ'); return; }
            if (info.error) {
                if (openDialog) { excelError(info.error); return; }
                // Дальше правим номер строки прямо в окне — не закрываем его
                document.getElementById('excelColumns').innerHTML =
                    `<div class="excel-empty">${String(info.error).replace(/\n/g, '<br>')}</div>`;
                renderExcelResult(null);
                return;
            }

            excelInfo = info;

            if (openDialog) {
                document.getElementById('excelHeaderRow').value = info.header_row;
                document.getElementById('excelHeaderHint').innerText =
                    info.header_row ? `Строка ${info.header_row} — подписи категорий` : 'Заголовков нет, данные с первой строки';
                document.getElementById('excelNaming').value = info.suggested_naming || 'cell';
                document.getElementById('excelFile').innerHTML =
                    `<b>${info.name}</b> · лист «${info.sheet}» · ${info.total_rows} строк`;
                document.getElementById('excelOverlay').style.display = 'flex';
            }

            renderExcelColumns();
            scheduleExcelPreview();
        }

        function renderExcelColumns() {
            let sel = new Set(excelInfo.suggested || []);
            document.getElementById('excelColumns').innerHTML = excelInfo.columns.map(c => `
                <label class="col-card">
                    <input type="checkbox" class="col-card__check" value="${c.index}" ${sel.has(c.index) ? 'checked' : ''} onchange="scheduleExcelPreview()">
                    <span class="opt-chip__box" aria-hidden="true"></span>
                    <span class="col-card__body">
                        <span class="col-card__head">
                            <span class="col-card__letter">${c.letter}</span>
                            <span class="col-card__title">${c.header || '<i>без заголовка</i>'}</span>
                        </span>
                        <span class="col-card__samples">${c.samples.join(' · ')}</span>
                        <span class="col-card__stats">${c.filled} ячеек${c.duplicates ? ` · повторов: ${c.duplicates}` : ''}</span>
                    </span>
                </label>`).join('');
        }

        function selectedExcelColumns() {
            return Array.from(document.querySelectorAll('.col-card__check:checked')).map(el => parseInt(el.value));
        }

        function toggleAllExcelColumns(on) {
            document.querySelectorAll('.col-card__check').forEach(el => el.checked = on);
            scheduleExcelPreview();
        }

        function scheduleExcelReanalyze() {
            clearTimeout(excelAnalyzeTimer);
            excelAnalyzeTimer = setTimeout(() => analyzeExcel(false), 450);
        }

        function scheduleExcelPreview() {
            clearTimeout(excelPreviewTimer);
            let el = document.getElementById('excelResult');
            el.className = 'tune-result is-busy';
            el.innerHTML = 'Считаю…';
            excelPreviewTimer = setTimeout(runExcelPreview, 300);
        }

        async function runExcelPreview() {
            let cols = selectedExcelColumns();
            if (!cols.length) { renderExcelResult({ total: 0, unique: 0, duplicates: 0, result: 0, examples: [] }); return; }

            let res = await pywebview.api.preview_excel_selection(
                cols,
                document.getElementById('excelNaming').value,
                document.getElementById('excelSkipDupes').checked,
                excelHeaderRow()
            );
            renderExcelResult(res);
        }

        function renderExcelResult(res) {
            let el = document.getElementById('excelResult');
            if (!res || res.error) {
                el.className = 'tune-result is-bad';
                el.innerHTML = 'Не удалось посчитать. Проверьте номер строки с заголовками.';
                return;
            }

            if (!res.result) {
                el.className = 'tune-result is-bad';
                el.innerHTML = '<span class="tune-result__num">0</span><span class="tune-result__text">'
                             + '<b>фраз загрузится</b><br>Отметьте хотя бы одну колонку.</span>';
                return;
            }

            let skip = document.getElementById('excelSkipDupes').checked;
            let note;
            let cls = 'tune-result is-good';

            if (res.duplicates && skip) {
                note = `Из ${res.total} ячеек ${res.duplicates} — повторы, они пропущены.`;
            } else if (res.duplicates) {
                cls = 'tune-result is-warn';
                note = `Среди них ${res.duplicates} повторов. При одинаковых именах файлы затрут друг друга — `
                     + `лучше включить «Пропускать повторы».`;
            } else {
                note = 'Повторов нет, все тексты разные.';
            }

            let ex = (res.examples || []).filter(Boolean);
            if (ex.length) note += `<br><span class="tune-result__ex">Имена: ${ex.join(' · ')}</span>`;

            el.className = cls;
            el.innerHTML = `<span class="tune-result__num">${res.result}</span>`
                         + `<span class="tune-result__text"><b>фраз загрузится</b><br>${note}</span>`;
        }

        function closeExcelPicker() {
            document.getElementById('excelOverlay').style.display = 'none';
            // Отменили выбор колонок — значит и «Готовую папку», которую
            // собирались открыть сразу после загрузки Excel, тоже не открываем.
            pendingPremadeAfterExcel = false;
            pendingAuditAfterExcel = false;
        }

        async function confirmExcelSelection() {
            let cols = selectedExcelColumns();
            if (!cols.length) { showBeautifulAlert('Отметьте хотя бы одну колонку с текстом.'); return; }

            let state = await pywebview.api.load_excel_selection(
                cols,
                document.getElementById('excelNaming').value,
                document.getElementById('excelSkipDupes').checked,
                excelHeaderRow()
            );

            if (!state || state.error) { excelError(state && state.error || 'Пустой ответ'); return; }

            // closeExcelPicker() сбрасывает pendingPremadeAfterExcel (на случай
            // отмены) — запоминаем значение до вызова, а не после.
            let openPremadeAfter = pendingPremadeAfterExcel;
            let auditAfter = pendingAuditAfterExcel;
            closeExcelPicker();
            updateUI(state);

            let rep = state.load_report;
            if (rep) {
                showToast(rep.skipped
                    ? `Загружено ${rep.loaded} фраз, повторов пропущено: ${rep.skipped}`
                    : `Загружено ${rep.loaded} фраз`);
            }

            if (openPremadeAfter) {
                startPremadeSumMode();
            } else if (auditAfter) {
                runProjectAudit();
            }
        }

        // ===== АВТОПОДБОР НАСТРОЕК НАРЕЗКИ =====

        let tuneData = null;       // результат замеров по выбранному файлу
        let tunePredictTimer = null;

        async function loadAudio() {
            // Шаг 1 — выбор файла (Python открывает системное окно)
            let picked = await pywebview.api.pick_raw_audio();
            if (!picked || picked.error === 'cancel') return;
            if (picked.error) { showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${picked.error}`); return; }

            // Шаг 2 — замеры. Могут занять пару секунд, показываем прогресс
            updateProgress(30, `Анализ записи: ${picked.name}`);
            let res;
            try {
                res = await pywebview.api.analyze_picked_audio();
            } catch (e) {
                document.getElementById('progressContainer').style.display = 'none';
                showBeautifulAlert(`❌ <b>Не удалось проанализировать запись</b><br><br>${e}`);
                return;
            }
            document.getElementById('progressContainer').style.display = 'none';

            if (!res || res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${String(res && res.error || 'Пустой ответ').replace(/\n/g, '<br>')}`);
                return;
            }

            openAutoTune(res);
        }

        function openAutoTune(res) {
            tuneData = res;

            let mins = Math.floor(res.duration_sec / 60);
            let secs = Math.round(res.duration_sec % 60);
            document.getElementById('tuneFile').innerHTML =
                `<b>${res.name}</b> · ${mins} мин ${secs} сек`;

            document.getElementById('tuneNoise').innerText  = `${res.noise_db} дБ`;
            document.getElementById('tuneSpeech').innerText = `${res.speech_db} дБ`;
            document.getElementById('tuneSpread').innerText = `${res.spread} дБ`;

            let spreadNote = document.getElementById('tuneSpreadNote');
            if (res.spread < 10) {
                spreadNote.innerText = 'Мало: фон почти такой же громкий, как речь. Нарезка будет неточной.';
                spreadNote.className = 'measure-card__note is-warn';
            } else if (res.spread < 20) {
                spreadNote.innerText = 'Небольшой запас — возможны ошибки на тихих словах.';
                spreadNote.className = 'measure-card__note';
            } else {
                spreadNote.innerText = 'Хороший запас, речь чётко отделена от фона.';
                spreadNote.className = 'measure-card__note is-good';
            }

            document.getElementById('tuneVerdict').innerHTML = res.target_phrases
                ? `В таблице Excel <b>${res.target_phrases}</b> фраз — настройки подобраны так, чтобы кусков получилось примерно столько же.`
                : `Таблица Excel не загружена, поэтому подобрано «на глаз» по громкости записи. Загрузите Excel — и подбор станет точнее.`;

            restoreTuneSuggestion();

            // Быстрые варианты: та же чувствительность, разная длина паузы
            let presets = (res.variants || []).map(v =>
                `<button class="preset-chip" onclick="applyTunePreset(${v.pause})">${v.pause} мс<small>≈ ${v.chunks} кусков</small></button>`
            ).join('');
            document.getElementById('tunePresets').innerHTML = presets;

            document.getElementById('autoTuneOverlay').style.display = 'flex';
        }

        function closeAutoTune() {
            document.getElementById('autoTuneOverlay').style.display = 'none';
        }

        function restoreTuneSuggestion() {
            if (!tuneData) return;
            document.getElementById('tunePause').value = tuneData.suggested.pause;
            document.getElementById('tuneSens').value  = tuneData.suggested.sens;
            document.getElementById('tunePad').value   = tuneData.suggested.pad;
            renderTuneResult(tuneData.predicted_chunks);
        }

        function applyTunePreset(pause) {
            document.getElementById('tunePause').value = pause;
            runTunePredict();
        }

        // Пересчитываем не на каждое нажатие клавиши, а когда человек перестал печатать
        function scheduleTunePredict() {
            clearTimeout(tunePredictTimer);
            document.getElementById('tuneResult').className = 'tune-result is-busy';
            document.getElementById('tuneResult').innerHTML = 'Пересчитываю…';
            tunePredictTimer = setTimeout(runTunePredict, 400);
        }

        async function runTunePredict() {
            clearTimeout(tunePredictTimer);
            let pause = clampToInput('inpPause', document.getElementById('tunePause').value, CUT_DEFAULTS.pause);
            let sens  = clampToInput('inpSens',  document.getElementById('tuneSens').value,  CUT_DEFAULTS.sens);

            let res = await pywebview.api.predict_cut(pause, sens);
            renderTuneResult(res ? res.chunks : null);
        }

        function renderTuneResult(chunks) {
            let el = document.getElementById('tuneResult');
            if (chunks === null || chunks === undefined) {
                el.className = 'tune-result';
                el.innerHTML = 'Не удалось посчитать. Попробуйте выбрать файл заново.';
                return;
            }

            let target = tuneData ? tuneData.target_phrases : 0;
            let note = '';
            let cls = 'tune-result is-good';

            if (chunks <= 1) {
                cls = 'tune-result is-bad';
                note = 'Вся запись останется одним куском. Увеличьте чувствительность — например, до '
                     + `${Math.min(-10, parseInt(document.getElementById('tuneSens').value) + 4)} дБ.`;
            } else if (target && chunks < target * 0.6) {
                cls = 'tune-result is-warn';
                note = `Это заметно меньше, чем ${target} фраз в таблице. Уменьшите паузу или поднимите чувствительность.`;
            } else if (target && chunks > target * 1.6) {
                cls = 'tune-result is-warn';
                note = `Это заметно больше, чем ${target} фраз в таблице — фразы дробятся на части. Увеличьте паузу.`;
            } else if (target) {
                note = `В таблице ${target} фраз — цифры сходятся.`;
            } else {
                note = 'Проверьте на слух после нарезки: слова не должны обрываться.';
            }

            el.className = cls;
            el.innerHTML = `<span class="tune-result__num">≈ ${chunks}</span>`
                         + `<span class="tune-result__text"><b>кусков получится</b><br>${note}</span>`;
        }

        async function startCut() {
            let pause = clampToInput('inpPause', document.getElementById('tunePause').value, CUT_DEFAULTS.pause);
            let sens  = clampToInput('inpSens',  document.getElementById('tuneSens').value,  CUT_DEFAULTS.sens);
            let pad   = clampToInput('inpPad',   document.getElementById('tunePad').value,   CUT_DEFAULTS.pad);

            // Держим ползунки на экране подготовки в согласии с тем, чем резали
            document.getElementById('inpPause').value = pause;
            document.getElementById('inpSens').value  = sens;
            document.getElementById('inpPad').value   = pad;
            updateSettingsText();

            closeAutoTune();
            updateProgress(0, 'Нарезка...');
            let state = await pywebview.api.load_raw_audio(pause, sens, pad);
            document.getElementById('progressContainer').style.display = 'none';

            // Чанки нарезаны — это фундамент в любом случае. Дальше решает
            // пользователь, а не программа: обычный режим или каскад переменных.
            if (state && state.await_mode_choice) {
                document.getElementById('modeChoiceOverlay').style.display = 'flex';
                return;
            }

            updateUI(state);
            if (state.has_audio) { showWorkspace(); playAudio(); }
            maybeNudgeExcelAfterCut();
        }

        async function chooseCutMode(mode) {
            document.getElementById('modeChoiceOverlay').style.display = 'none';
            updateProgress(0, mode === 'premade' ? 'Готовим каскад переменных...' : 'Открываем Audacity...');
            document.getElementById('progressContainer').style.display = 'block';

            let state = await pywebview.api.choose_mode_after_cut(mode);
            document.getElementById('progressContainer').style.display = 'none';

            if (mode === 'premade') {
                nudgeExcelAfterCut = false;
                document.getElementById('onlyStartCheck').checked = false;
                handlePremadeResult(state);
                return;
            }

            if (state && state.error) {
                if (state.error !== "cancel") showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }

            updateUI(state);
            if (state.has_audio) { showWorkspace(); playAudio(); }
            maybeNudgeExcelAfterCut();
        }

        // ===== «ГОТОВЫЕ ПЕРЕМЕННЫЕ»: НЕ ХВАТАЕТ start/end =====
        // Единая точка разбора ответа для обоих мест, откуда грузится
        // «Готовая папка» (обычная кнопка и режим сразу после нарезки) —
        // чтобы поведение не расходилось между ними.
        let pendingMissing = [];

        function closeStartEndMissing() {
            document.getElementById('startEndMissingOverlay').style.display = 'none';
        }

        async function handlePremadeResult(state) {
            if (state && state.error === "cancel") return;

            if (state && state.status === 'waiting_labels') {
                pendingMissing = state.missing || pendingMissing;
                document.getElementById('startEndMissingOverlay').style.display = 'none';
                let baseText = `Выделите нужный кусок записи и нажмите <b>Ctrl+B</b>, впишите название метки — `
                    + `<b>${pendingMissing.join('</b> или <b>')}</b> — и нажмите ОК в Audacity. `
                    + `Когда участки отмечены, нажмите кнопку ниже.`;
                document.getElementById('waitLabelsText').innerHTML = state.error
                    ? `<span style="color:#e5484d;">${state.error}</span><br><br>${baseText}` : baseText;
                document.getElementById('waitLabelsOverlay').style.display = 'flex';
                return;
            }

            if (state && state.missing_start_end) {
                pendingMissing = state.missing || [];
                document.getElementById('waitLabelsOverlay').style.display = 'none';
                document.getElementById('startEndMissingText').innerHTML = pendingMissing.length
                    ? `В выбранной папке не найдено: <b>${pendingMissing.map(m => m + '.wav').join(', ')}</b>. Выберите, как их получить.`
                    : `Осталось получить: <b>start.wav</b>.`;
                document.getElementById('startEndMissingOverlay').style.display = 'flex';
                return;
            }

            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }

            document.getElementById('startEndMissingOverlay').style.display = 'none';
            document.getElementById('waitLabelsOverlay').style.display = 'none';
            updateUI(state);
            showWorkspace();
        }

        async function toggleOnlyStart(checked) {
            let state = await pywebview.api.set_only_start_mode(checked);
            handlePremadeResult(state);
        }

        async function pickStartEndManual() {
            document.getElementById('startEndMissingOverlay').style.display = 'none';
            let toPick = pendingMissing.slice();
            let lastResult = null;
            for (let which of toPick) {
                let result = await pywebview.api.pick_start_end_file(which);
                if (result && result.error === 'cancel') return;
                lastResult = result;
                if (result && result.error) break;
            }
            if (lastResult) handlePremadeResult(lastResult);
        }

        async function createStartEndFromRecording() {
            document.getElementById('startEndMissingOverlay').style.display = 'none';
            updateProgress(0, 'Открываем запись в Audacity...');
            document.getElementById('progressContainer').style.display = 'block';
            let state = await pywebview.api.create_start_end_from_recording();
            document.getElementById('progressContainer').style.display = 'none';
            handlePremadeResult(state);
        }

        async function finishStartEndLabels() {
            updateProgress(0, 'Экспортируем метки...');
            document.getElementById('progressContainer').style.display = 'block';
            let state = await pywebview.api.finish_create_start_end();
            document.getElementById('progressContainer').style.display = 'none';
            handlePremadeResult(state);
        }

        async function loadVariables() {
            if (currentState && currentState.mode === 'VarBatch') {
                showBeautifulAlert('ℹ️ <b>Режим переменных</b><br><br>Вкладки здесь не переключаются — конвейер уже открыт. Чтобы выйти, нажмите <b>Главное меню</b> в левом верхнем углу.');
                return;
            }
            await handleLoad(pywebview.api.load_variables_mode());
        }
        async function loadChecked() {
            // В конвейере переменных вкладка «Проверенные» не переключает
            // экран (это сломало бы каскад) — вместо этого проигрывает
            // сохранённую версию текущего дубля, если он уже отмечен.
            if (currentState && currentState.mode === 'VarBatch') {
                playAudio(false);
                return;
            }
            await handleLoad(pywebview.api.dispatch('switch_mode', {mode: 'checked'}));
        }
        async function loadMainMode() {
            if (currentState && currentState.mode === 'VarBatch') {
                showBeautifulAlert('ℹ️ <b>Режим конвейера</b><br><br>Вкладок здесь нет. Чтобы выйти, нажмите <b>Главное меню</b>.');
                return;
            }
            await handleLoad(pywebview.api.dispatch('switch_mode', {mode: 'chunks'}));
        }

        // Запуск режима конвейера переменных (С выбором окна)
        let pendingVarBatch = false;
        let pendingVarBatchPremade = false; // НОВОЕ: Флаг для готовой папки

        function closeProjectSelector() {
            document.getElementById('projectSelectorOverlay').style.display = 'none';
        }

        async function initVarBatch() {
            let windows = await pywebview.api.get_audacity_windows();

            if (windows && windows.length > 1) {
                let listHtml = '';
                windows.forEach(w => {
                    listHtml += `<button class="option-card project-option" onclick="selectAudacityProject(${w.hwnd})">
                                    <span class="option-icon">${iconHTML('headphones')}</span>
                                    <span class="project-option__title">${w.title}</span>
                                 </button>`;
                });
                document.getElementById('projectList').innerHTML = listHtml;
                document.getElementById('projectSelectorOverlay').style.display = 'flex';
                pendingVarBatch = true;
                pendingVarBatchPremade = false; // Сбрасываем соседний флаг
            } else {
                let targetHwnd = null;
                if (windows && windows.length === 1) targetHwnd = windows[0].hwnd;
                continueInitVarBatch(targetHwnd);
            }
        }

        // НОВОЕ: Функция инициализации загрузки готовой папки
        // Excel не обязателен для этого режима — но если его ещё не
        // загружали в этом проекте, спрашиваем один раз, как называть
        // сохранённые файлы: по тексту таблицы или как есть, по именам
        // файлов на диске.
        // «Готовая папка с переменными»: категории переменных программа
        // определяет сама по загруженной таблице-словарю (см.
        // load_var_template в variables_handler.py) — юзеру выбирать
        // «какие переменные» не нужно, только загрузить таблицу.
        function showPremadeVarTypeChoice() {
            document.getElementById('premadeVarTypeOverlay').style.display = 'flex';
        }
        function closePremadeVarTypeChoice() {
            document.getElementById('premadeVarTypeOverlay').style.display = 'none';
        }
        // Без словаря — старое поведение, только 5 ярусов Суммы.
        function premadeVarTypeSums() {
            closePremadeVarTypeChoice();
            initVarBatchPremade();
        }

        async function pickVarTemplate() {
            let res = await pywebview.api.load_var_template();
            if (res && res.error) {
                if (res.error !== 'cancel') showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            closePremadeVarTypeChoice();
            renderVarDictConnectors(res);
            document.getElementById('varDictConnectorsOverlay').style.display = 'flex';
            showConnSuggest(res.connector_suggestions, 'dict');
        }

        // Программа нашла в папке файлы для связок (start.wav, end.wav,
        // «на автомобиль».wav…) — подставляет их только после «Да».
        let connSuggestContext = null;
        function showConnSuggest(list, context) {
            if (!list || !list.length) return;
            connSuggestContext = context;
            let box = document.getElementById('connSuggestList');
            box.innerHTML = '';
            list.forEach(item => {
                let row = document.createElement('div');
                row.className = 'conn-suggest-row';
                let label = document.createElement('span');
                label.className = 'conn-suggest-row__label';
                label.textContent = `«${item.label}»`;
                let file = document.createElement('span');
                file.className = 'conn-suggest-row__file';
                file.textContent = item.file;
                file.title = item.path;
                row.append(label, file);
                box.appendChild(row);
            });
            document.getElementById('connSuggestOverlay').style.display = 'flex';
        }
        async function answerConnSuggest(accept) {
            document.getElementById('connSuggestOverlay').style.display = 'none';
            let res = await pywebview.api.apply_var_connector_suggestions(accept);
            if (!res || res.error) {
                if (res && res.error) showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            if (connSuggestContext === 'dict') {
                let st = await pywebview.api.get_var_template_state();
                renderVarDictConnectors({ extra_tags: st.extra_tags, connectors: res.connectors });
            } else {
                if (typeof sumEd !== 'undefined') sumEd.sig = null;
                updateUI(res);
            }
            if (accept) showToast('Файлы связок подставлены');
        }

        let lastVarDictSumsPresent = false;
        let lastVarDictTranscripts = null;
        function renderVarDictConnectors(res) {
            let extraTags = (res.extra_tags || []).map(t => t.label);
            if (res.columns) lastVarDictSumsPresent = res.columns.some(c => c.type === 'sum');
            if (res.transcripts) lastVarDictTranscripts = res.transcripts;
            res.transcripts = lastVarDictTranscripts;
            let sumsPresent = lastVarDictSumsPresent;
            let summary = `Найдено: ${extraTags.length ? extraTags.join(', ') : '—'}`
                + (sumsPresent ? ' + Суммы (Миллионы/Сотни/Тысячи/Тенге)' : '')
                + `. Связок нужно озвучить: ${(res.connectors || []).length}.`
                + (res.transcripts && Object.keys(res.transcripts).length
                    ? `<br>Транскрипция для автопроверки: ${Object.entries(res.transcripts).map(([k, n]) => `${escapeHtml(k)} (${n})`).join(', ')}.`
                    : (res.transcripts ? '<br>Колонки транскрипции нет — автопроверка будет сверять с самими значениями (менее точно).' : ''));
            document.getElementById('varDictSummary').innerHTML = summary;

            let list = document.getElementById('varDictConnectorsList');
            list.innerHTML = (res.connectors || []).map(c => `
                <div class="var-dict-connector ${c.path ? 'is-set' : ''}" id="varDictConn_${c.key}">
                    <div>
                        <div class="var-dict-connector__label">«${escapeHtml(c.label)}»</div>
                        <div class="var-dict-connector__file">${c.path ? escapeHtml(c.path.split(/[\\/]/).pop()) : 'Аудио не выбрано'}</div>
                    </div>
                    <div class="var-dict-connector__actions">
                        <button class="btn-tile btn-tile--sub" onclick="pickVarConnectorAudio('${c.key}')">Загрузить файл</button>
                    </div>
                </div>
            `).join('') || '<div class="modal-hint">В таблице нет отдельных связок.</div>';
        }

        async function pickVarConnectorAudio(key) {
            let res = await pywebview.api.set_var_connector_audio(key);
            if (res && res.error) {
                if (res.error !== 'cancel') showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            let state = await pywebview.api.get_var_template_state();
            renderVarDictConnectors({ extra_tags: state.extra_tags, connectors: state.connectors });
        }

        function closeVarDictConnectors() {
            document.getElementById('varDictConnectorsOverlay').style.display = 'none';
        }

        function continueAfterVarDict() {
            closeVarDictConnectors();
            // Идём сразу в выбор папки с дублями — старый вопрос «Есть Excel
            // с именами файлов?» и разбор его колонок тут не нужны: таблица,
            // из которой берутся и категории, и имена файлов, уже загружена
            // на предыдущем шаге (pickVarTemplate). Раньше здесь всё равно
            // вызывался initVarBatchPremade(), и этот вопрос всплывал заново,
            // а в разборе колонок среди прочего показывался и заголовок
            // связки «start» — как будто это тоже можно выбрать текстом фразы.
            startPremadeSumMode();
        }

        // === Все связки разом — метками в Audacity (тот же приём, что уже
        // работает для start/end: открываем полную запись, юзер сам
        // расставляет Ctrl+B метки с именами связок, потом «Готово»). ===
        async function createVarConnectorsFromRecording() {
            let res = await pywebview.api.create_var_connectors_from_recording();
            if (res && res.error) {
                if (res.error !== 'cancel') showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            document.getElementById('varDictLabelsNeeded').innerText = (res.needed || []).join(', ');
            document.getElementById('varDictLabelsHint').style.display = 'block';
            document.getElementById('varDictLabelsDoneBtn').style.display = 'block';
        }

        async function finishVarConnectorsFromRecording() {
            let res = await pywebview.api.finish_var_connectors_from_recording();
            if (res && res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            let state = await pywebview.api.get_var_template_state();
            renderVarDictConnectors({ extra_tags: state.extra_tags, connectors: res.connectors });

            if (res.missing && res.missing.length) {
                // Часть меток не нашлась — не закрываем шаг, предлагаем выбор:
                // продолжить без них (потом добить кнопкой «Загрузить файл»
                // у нужной связки) или вернуться в Audacity и попробовать
                // ещё раз, не открывая запись заново.
                document.getElementById('varDictLabelsMissingNames').innerText = res.missing.join(', ');
                document.getElementById('varDictLabelsMissing').style.display = 'block';
            } else {
                dismissVarDictLabelsMissing();
            }
        }

        function dismissVarDictLabelsMissing() {
            document.getElementById('varDictLabelsMissing').style.display = 'none';
            document.getElementById('varDictLabelsHint').style.display = 'none';
            document.getElementById('varDictLabelsDoneBtn').style.display = 'none';
        }

        let pendingPremadeAfterExcel = false;
        async function initVarBatchPremade() {
            if (!excelIsLoaded) {
                document.getElementById('premadeExcelChoiceOverlay').style.display = 'flex';
                return;
            }
            startPremadeSumMode();
        }

        function closePremadeExcelChoice() {
            document.getElementById('premadeExcelChoiceOverlay').style.display = 'none';
        }

        function premadeExcelChoiceYes() {
            closePremadeExcelChoice();
            pendingPremadeAfterExcel = true;
            loadExcel();
        }

        function premadeExcelChoiceNo() {
            closePremadeExcelChoice();
            startPremadeSumMode();
        }

        // «Готовая папка с переменными»: один экран режима «Суммы» —
        // выбираете папку с дублями (start/end не нужны), дальше сразу и
        // сортировка на слух по категориям (←/→ + ↑/↓), и сборка эталона
        // рулетками — вместе, без переключения между отдельными экранами.
        async function startPremadeSumMode(folder) {
            updateProgress(0, 'Загрузка папки...');
            document.getElementById('progressContainer').style.display = 'block';
            // folder — папку дал софт (синтезированные суммы), без диалога.
            let state = await pywebview.api.sum_load_folder(typeof folder === 'string' ? folder : null);
            document.getElementById('progressContainer').style.display = 'none';

            if (state && state.error) {
                if (state.error !== 'cancel') showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }

            // Бэкенд уже включил Режим «Суммы» сам — синхронизируем клиентский
            // флаг и раскладку экрана, как будто галочку нажали руками.
            sumModeActive = true;
            let sumCheck = document.getElementById('sumModeCheck');
            if (sumCheck) sumCheck.checked = true;

            updateUI(state);
            // showWorkspace() сбрасывает embedBtnId на общий 'btnEmbedAudacity' —
            // applySumModeLayout() должен идти ПОСЛЕ неё, иначе кнопка
            // «Прикрепить Audacity» режима «Суммы» останется ненайденной.
            showWorkspace();
            applySumModeLayout();
            await attachEmbeddedAudacity(true);
            showConnSuggest(state.connector_suggestions, 'workspace');
        }

        // --- ВОССТАНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ КНОПКИ "ОТКРЫТЬ ГОТОВЫЕ ЧАНКИ" ---
        async function loadFolder() {
            updateProgress(0, 'Загрузка папки...');
            document.getElementById('progressContainer').style.display = 'block';
            let state = await pywebview.api.load_chunks_folder();
            document.getElementById('progressContainer').style.display = 'none';
            if (state && state.error) {
                if (state.error !== "cancel") showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
            if (state.has_audio) { showWorkspace(); playAudio(); }
        }

        // --- ВОССТАНОВЛЕННАЯ ФУНКЦИЯ ДЛЯ КНОПКИ "ГОТОВАЯ ПАПКА С ПЕРЕМЕННЫМИ" ---
        async function continueInitVarBatchPremade(hwnd) {
            let confirmed = await showBeautifulAlert("📂 <b>Готовая папка (Шаг 1 из 1):</b><br><br>Выберите <b>КОРНЕВУЮ ПАПКУ</b> с переменными.<br><br><span style='font-size:12px;color:var(--text-dim)'>В ней должны лежать файлы <b>start.wav</b> и <b>end.wav</b>, а также подпапки с суммами.</span>");
            if (!confirmed) return;
            let inDir = await pywebview.api.pick_folder();
            if (!inDir) return;

            updateProgress(10, 'Чтение структуры готовой папки...');
            document.getElementById('progressContainer').style.display = 'block';

            let state = await pywebview.api.load_premade_variables_folder(hwnd, inDir);

            document.getElementById('progressContainer').style.display = 'none';
            document.getElementById('onlyStartCheck').checked = false;
            handlePremadeResult(state);
        }

        async function loadCheckedToAudacity() {
            if (isProcessing) return; isProcessing = true;
            updateProgress(0, 'Выгрузка из Проверенных...');
            document.getElementById('progressContainer').style.display = 'block';

            let state = await pywebview.api.load_checked_var_to_audacity();
            if (state) updateUI(state);

            document.getElementById('progressContainer').style.display = 'none';
            isProcessing = false;
        }

        async function stripFilenames() {
            if (isProcessing) return;
            isProcessing = true;
            await pywebview.api.strip_words_from_filenames();
            isProcessing = false;
        }

        async function selectAudacityProject(hwnd) {
            document.getElementById('projectSelectorOverlay').style.display = 'none';

            if (pendingVarBatch) {
                pendingVarBatch = false;
                continueInitVarBatch(hwnd);
            } else if (pendingVarBatchPremade) {
                pendingVarBatchPremade = false;
                continueInitVarBatchPremade(hwnd);
            }
        }

        async function continueInitVarBatch(hwnd) {
            // 1. Считываем состояние наших галочек
            let isReadyExport = document.getElementById('simpleExportCheck').checked;
            let sortByName = document.getElementById('sortByNameCheck').checked;

            // 2. Меняем текст предупреждения в зависимости от галочки
            let alertMsg = isReadyExport
                ? "📁 <b>Простой экспорт (Шаг 1 из 1):</b><br><br>Выберите <b>ПАПКУ</b>, куда будут рассортированы переменные."
                : `📁 <b>Пакетная сборка (Шаг 1 из 1):</b><br><br>Выберите <b>ПАПКУ</b>, куда будут экспортироваться переменные.<br><br><span style='font-size:12px;color:var(--text-dim)'>${iconHTML('alert-triangle')} Убедитесь, что в этой папке уже лежат эталонные файлы <b>start.wav</b> и <b>end.wav</b>!</span>`;

            let confirmed = await showBeautifulAlert(alertMsg);
            if (!confirmed) return;
            let outDir = await pywebview.api.pick_folder();
            if (!outDir) return;

            updateProgress(10, 'Анализ клипов в Audacity и экспорт...');
            document.getElementById('progressContainer').style.display = 'block';

            // 3. Передаем ОБА флага в Python
            let state = await pywebview.api.init_variables_batch_mode(hwnd, outDir, isReadyExport, sortByName);

            document.getElementById('progressContainer').style.display = 'none';
            if (state && state.error) {
                if (state.error !== "cancel") showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }

            updateUI(state);

            // Если это просто экспорт, мы никуда не переходим (остаемся в меню)
            if (!isReadyExport) {
                showWorkspace();
            }
        }


        async function saveVarBatch(normalize = false) {
            if (isProcessing) return;
            isProcessing = true;

            if (normalize) {
                updateProgress(0, 'Подготовка к нормализации...');
            }

            setTimeout(async () => {
                try {
                    let state = await pywebview.api.save_var_batch(normalize);
                    if (state) {
                        updateUI(state);
                        // === АВТОПЛЕЙ ПОСЛЕ СОХРАНЕНИЯ И ПЕРЕХОДА ===
                        playAudio(false);
                    }
                } catch (err) {
                    console.error("Ошибка при сохранении:", err);
                } finally {
                    if (normalize) document.getElementById('progressContainer').style.display = 'none';
                    isProcessing = false;
                }
            }, 50);
        }

        // === Режим «Суммы»: ручная разметка ярусов на обычной нарезке ===
        let sumModeActive = false;

        async function toggleSumMode(checked) {
            sumModeActive = checked;
            // Снимаем фокус с галочки, иначе горячие клавиши (C, Z, A/D)
            // считаются набором текста в поле и просто игнорируются.
            let box = document.getElementById('sumModeCheck');
            if (box) box.blur();
            let sumState = await pywebview.api.toggle_sum_mode(checked);
            renderSumPanel(sumState);
            // Раньше экран переключался только при следующей навигации по
            // дублям — галочка визуально «не срабатывала» сразу.
            applySumModeLayout();
            if (sumModeActive) {
                await attachEmbeddedAudacity(true);
            } else {
                await detachEmbeddedAudacity();
            }
        }

        async function setSumLogic(stage2) {
            let sumState = await pywebview.api.toggle_sum_stage2(stage2);
            renderSumPanel(sumState);
            applySumModeLayout();

            if (sumModeActive) {
                // Пробуем сразу занять освободившееся место окном Audacity.
                // Если он ещё не запущен — просто оставляем пустую рамку,
                // окно встанет туда само после первой отправки (C).
                await attachEmbeddedAudacity(true);
            } else {
                await detachEmbeddedAudacity();
            }
        }

        // В режиме «Суммы» на экране остаётся только то, что нужно для работы:
        // счётчики, подсказка про папку и три кнопки. Всё лишнее (монтажный
        // стол и кнопки режима переменных) прячется, а место под ними
        // отдаётся окну Audacity.
        function applySumModeLayout() {
            const show = (id, on) => {
                let el = document.getElementById(id);
                if (el) el.style.display = on ? 'flex' : 'none';
            };
            show('standardActions', !sumModeActive);
            show('sumManualActions', sumModeActive);
            if (sumModeActive) show('varBatchActions', false);

            // Кнопка «Прикрепить Audacity» — своя для режима «Суммы»: если
            // забыли открыть Audacity заранее (см. sendToAudacity/C) и
            // открыли уже после, автовживление больше не срабатывает само
            // по себе, нужна ручная кнопка, а у обычного экрана она —
            // #btnEmbedAudacity, спрятанный в другой, скрытой сейчас
            // панели действий.
            embedBtnId = sumModeActive ? 'sumEmbedAudacityBtn' : 'btnEmbedAudacity';

            let mergePanel = document.querySelector('.merge-panel');
            if (mergePanel && sumModeActive) mergePanel.style.display = 'none';

            // Общая статистика проекта и переключатель Проверенные/Переменные/
            // Основной — не нужны в режиме «Суммы», у него свой счётчик «Готово».
            let statRow = document.querySelector('.stat-row');
            if (statRow) statRow.style.display = sumModeActive ? 'none' : 'flex';
            let modeSwitch = document.querySelector('.mode-switch');
            if (modeSwitch) modeSwitch.style.display = sumModeActive ? 'none' : 'flex';

            let area = document.getElementById('audacityEmbedArea');
            let grid = document.getElementById('workspaceGrid');
            if (area && grid) {
                // В режиме «Суммы» рамка переезжает из правой колонки вниз, под
                // обе колонки — так под окно Audacity уходит вся ширина экрана.
                let columns = grid.querySelectorAll('.panel-column');
                let column = columns[columns.length - 1];
                if (sumModeActive && area.parentElement !== grid) {
                    grid.appendChild(area);
                } else if (!sumModeActive && area.parentElement === grid && column) {
                    // Возвращаем рамку на своё место — перед списком горячих клавиш
                    let hotkeys = column.querySelector('.work-hotkeys');
                    column.insertBefore(area, hotkeys || null);
                }
                grid.classList.toggle('workspace-grid--sum', sumModeActive);
                document.body.classList.toggle('sum-mode', sumModeActive);
                if (sumModeActive || !audacityEmbedded) {
                    area.style.display = sumModeActive ? 'block' : (embedAreaId === 'ttsEmbedArea' ? 'flex' : 'none');
                }
            }

            // Рамка могла изменить размер после скрытия лишних кнопок —
            // подгоняем под неё уже встроенное окно Audacity.
            if (audacityEmbedded) onEmbedWindowResize();
        }

        // Единый экран режима «Суммы»: колонки-категории (рулетки) встроены
        // в область текста, действия — все сразу в одной панели. "stage2" в
        // sumState — переключатель ЛОГИКИ (какой набор ярусов участвует),
        // не путать с рулетками ниже (то же название исторически осталось
        // от прежнего разделения на «этапы» — см. variables_handler.py).
        let lastSumState = null;
        function renderSumPanel(sumState) {
            if (!document.querySelector('.is-space-zone')) setTimeout(() => sumSetSpaceZone(sumSpaceZone), 0);
            if (!sumState) return;
            lastSumState = sumState;
            let logic1Btn = document.getElementById('sumLogic1Btn');
            let logic2Btn = document.getElementById('sumLogic2Btn');
            if (logic1Btn) logic1Btn.classList.toggle('btn-tile--solid-mode', !sumState.stage2);
            if (logic2Btn) logic2Btn.classList.toggle('btn-tile--solid-mode', !!sumState.stage2);

            let doneEl = document.getElementById('sumDoneCounter');
            if (doneEl) doneEl.innerText = `Готово: ${sumState.done_total || 0} / ${sumState.excel_total || 0}`;

            let panel = document.getElementById('sumActionsPanel');
            if (panel) panel.style.display = sumState.active ? 'flex' : 'none';

            if (sumState.active) {
                // Сначала показать блок: в скрытом прокрутка ленты к текущему не работает.
                setSumEmbedMode('sum');
                renderSumReels(sumState.reels);
                renderSumDubs(sumState.dubs);
            } else {
                setSumEmbedMode('text');
            }
        }

        // Режим «Суммы» подменяет собой область с текстом фразы (та же
        // зона, где в остальных режимах читается строка Excel).
        function setSumEmbedMode(mode) { // 'text' | 'sum'
            let text = document.getElementById('phraseText');
            let hint = document.getElementById('phraseHint');
            let embed = document.getElementById('sumEmbed');
            if (text) text.style.display = mode === 'text' ? '' : 'none';
            if (hint) hint.style.display = mode === 'text' ? '' : 'none';
            if (embed) embed.style.display = mode === 'sum' ? 'flex' : 'none';
        }

        // Одна строка на экран: слева название категории, справа — значение
        // из неё. ↑/↓ листают категории (sumStage1MoveSelection), ←/→
        // листают значения внутри текущей категории (sumStage1BrowseMove) —
        // раньше это была рулетка мышкой, теперь то же самое клавиатурой.
        // Z сохраняет текущий дубль в выбранную категорию (sumStage1Send),
        // X отменяет последнее сохранение (sumStage1Undo).
        let sumStage1Tiers = []; // [{key, label}], порядок категорий
        let sumStage1SelectedIdx = 0;
        let sumStage1BrowseIdx = {}; // tier -> какое по счёту значение сейчас показано
        let sumStage1BrowseCount = {}; // tier -> сколько значений было при прошлом рендере

        // Быстрая анимация «въезда» с той стороны, куда листали — снимает
        // класс, форсирует reflow (иначе повторное добавление того же
        // класса подряд не перезапустит @keyframes) и навешивает заново.
        function triggerSumAnim(el, cls) {
            if (!el) return;
            el.classList.remove('sum-anim-up', 'sum-anim-down', 'sum-anim-left', 'sum-anim-right');
            void el.offsetWidth;
            el.classList.add(cls);
        }

        function sumStage1MoveSelection(dir) {
            // ВНИМАНИЕ: тут нарочно НЕ вызываем playCurrentSumValue() — эта
            // категория обычно уже что-то сохранённое, и её старое значение,
            // проигранное поверх нового дубля, который сейчас разбираете,
            // только сбивает с толку. Звук значения играет только при
            // листании ←/→ внутри категории (sumStage1BrowseMove) — там это
            // явно то, что хотели послушать.
            if (!sumStage1Tiers.length) return;
            sumStage1SelectedIdx = (sumStage1SelectedIdx + dir + sumStage1Tiers.length) % sumStage1Tiers.length;
            renderSumSingleRow();
            triggerSumAnim(sumSelectedTile(), dir < 0 ? 'sum-anim-up' : 'sum-anim-down');
        }
        function sumStage1BrowseMove(dir) {
            if (!sumStage1Tiers.length || !lastSumState || !lastSumState.reels) return;
            let tier = sumStage1Tiers[sumStage1SelectedIdx].key;
            let items = (lastSumState.reels.tiers[tier] || {}).items || [];
            if (!items.length) return;
            let idx = sumStage1BrowseIdx[tier] || 0;
            sumStage1BrowseIdx[tier] = (idx + dir + items.length) % items.length;
            renderSumSingleRow();
            triggerSumAnim(sumSelectedTile(), dir < 0 ? 'sum-anim-left' : 'sum-anim-right');
            playCurrentSumValue();
        }

        // ===== РЕЖИМ «СУММЫ»: перетаскивание =====
        // Сверху — лента карточек дублей (тянутся мышкой, клик — прослушать,
        // Ctrl/Shift — выбрать несколько). Ниже — все категории сразу, каждая
        // — зона сброса: брошенный дубль получает значение «ждёт». Последняя
        // зона — Audacity: туда (или кнопкой у выделения) отправляются один
        // или несколько дублей подряд на одну дорожку.
        // Клавиатура работает как раньше: ↑/↓ — выбранная категория
        // (подсвечена), Z — текущий дубль в неё, ←/→ — записанное в ней.

        function sumEl(tag, cls, text) {
            let el = document.createElement(tag);
            if (cls) el.className = cls;
            if (text !== undefined && text !== null) el.textContent = text;
            return el;
        }
        // Цвет категории: ярусы Суммы — свои постоянные, доп.категории
        // словаря (марка, год…) — из отдельной палитры по порядку колонок.
        const SUM_EXTRA_ACCENTS = ['#ff7eb6', '#7dd3fc', '#c3e88d', '#f78c6c', '#c792ea', '#ffcb6b'];
        function sumTierAccent(key) {
            if (CONSTRUCTOR_TIER_ACCENT[key]) return CONSTRUCTOR_TIER_ACCENT[key];
            let extras = sumStage1Tiers.map(t => t.key).filter(k => !CONSTRUCTOR_TIER_ACCENT[k]);
            let i = extras.indexOf(key);
            if (i < 0) i = [...String(key)].reduce((a, ch) => a + ch.charCodeAt(0), 0);
            return SUM_EXTRA_ACCENTS[i % SUM_EXTRA_ACCENTS.length];
        }
        function sumSelectedTile() {
            let tier = sumStage1Tiers[sumStage1SelectedIdx];
            return tier ? document.querySelector(`.sum-cat[data-tier="${CSS.escape(tier.key)}"]`) : null;
        }

        let sumTierPlayTimeout = null;
        function stopSumTierHighlight() {
            clearTimeout(sumTierPlayTimeout);
            document.querySelectorAll('.sum-rec.is-playing, .sum-dub.is-playing').forEach(e => e.classList.remove('is-playing'));
        }
        async function sumPlayPath(path, el) {
            if (!path) return;
            let res;
            try { res = await pywebview.api.play_specific_file(path); } catch (e) { return; }
            stopSumTierHighlight();
            if (res && res.playing && el) {
                el.classList.add('is-playing');
                sumTierPlayTimeout = setTimeout(stopSumTierHighlight, res.duration * 1000);
            }
        }
        async function playCurrentSumValue() {
            if (!sumStage1Tiers.length || !lastSumState || !lastSumState.reels) return;
            let tier = sumStage1Tiers[sumStage1SelectedIdx].key;
            let info = lastSumState.reels.tiers[tier] || {};
            let idx = sumStage1BrowseIdx[tier] || 0;
            let path = (info.paths || [])[idx];
            let tile = sumSelectedTile();
            await sumPlayPath(path, tile ? tile.querySelector(`.sum-rec[data-idx="${idx}"]`) : null);
        }

        function sumRecordedLabel(tier, raw) {
            return humanizeTierItem(tier, (raw || '').replace(/^сырая_/, ''));
        }

        // --- Перетаскивание: общие обработчики зон сброса ---
        const SUM_DND_TYPE = 'application/x-gvox-dubs';
        function sumDragIndices(e) {
            try { return JSON.parse(e.dataTransfer.getData(SUM_DND_TYPE) || e.dataTransfer.getData('text/plain') || '[]'); }
            catch (_) { return []; }
        }
        function sumMakeDropZone(el, onDrop) {
            el.addEventListener('dragover', e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; el.classList.add('is-over'); });
            el.addEventListener('dragleave', e => { if (!el.contains(e.relatedTarget)) el.classList.remove('is-over'); });
            el.addEventListener('drop', e => {
                e.preventDefault();
                el.classList.remove('is-over');
                document.body.classList.remove('sum-dragging');
                let indices = sumDragIndices(e);
                if (indices.length) onDrop(indices);
            });
        }

        // --- Сетка категорий ---
        function renderSumSingleRow() {
            let grid = document.getElementById('sumCats');
            if (!grid || !lastSumState || !lastSumState.reels) return;
            let data = lastSumState.reels;
            grid.innerHTML = '';

            sumStage1Tiers.forEach((tierInfo, tIdx) => {
                let tier = tierInfo.key;
                let info = data.tiers[tier] || { items: [] };
                let items = info.items || [];
                let tile = sumEl('div', 'sum-cat' + (tIdx === sumStage1SelectedIdx ? ' is-selected' : ''));
                tile.dataset.tier = tier;
                tile.style.setProperty('--tier-accent', sumTierAccent(tier));
                tile.addEventListener('click', e => {
                    if (e.target.closest('select, .sum-rec')) return;
                    sumStage1SelectedIdx = tIdx;
                    document.querySelectorAll('.sum-cat.is-selected').forEach(t => t.classList.remove('is-selected'));
                    tile.classList.add('is-selected');
                });

                let head = sumEl('div', 'sum-cat__head');
                head.appendChild(sumEl('span', 'sum-cat__name', info.label || tierInfo.label));
                if (typeof info.expected_idx === 'number' && info.values_total) {
                    head.appendChild(sumEl('span', 'sum-cat__progress', `${info.expected_idx + 1}/${info.values_total}`));
                }
                tile.appendChild(head);

                tile.appendChild(sumEl('div', 'sum-cat__label', 'ждёт'));
                let select = sumEl('select', 'sum-cat__expect');
                let choices = info.name_choices || [];
                if (!info.expected_next || !choices.length) {
                    let opt = sumEl('option', null, 'нет значений');
                    opt.value = '';
                    select.appendChild(opt);
                    select.disabled = true;
                } else {
                    choices.forEach((name, i) => {
                        let opt = sumEl('option', null, `${i + 1}. ${name}`);
                        opt.value = name;
                        select.appendChild(opt);
                    });
                    select.value = info.expected_next;
                    let sel = select.options[select.selectedIndex];
                    if (sel) sel.textContent = info.expected_next;
                }
                select.title = 'Это значение получит следующий брошенный сюда дубль. Кликните, чтобы начать с другого места списка';
                select.addEventListener('change', () => sumSetExpected(tier, select.value));
                // Сам select не умеет переносить строку — длинная марка
                // обрезалась. Видимый текст — отдельно, полностью, с
                // переносом; прозрачный select поверх ловит клик.
                let expectBox = sumEl('div', 'sum-cat__expect-box');
                expectBox.appendChild(sumEl('div', 'sum-cat__expect-text' + (select.disabled ? ' is-empty' : ''),
                    select.disabled ? 'нет значений' : info.expected_next));
                expectBox.appendChild(select);
                tile.appendChild(expectBox);

                // Автонавигация: дубль, где автопроверка услышала ожидаемое.
                let am = info.asr_match;
                if (am) {
                    let chip = sumEl('button', 'sum-cat__asr-match' + (am.confident ? ' is-sure' : ''),
                        `◎ ${(am.name.match(/(\d+)\s*$/) || [, am.name])[1]} · ${Math.round(am.score * 100)}%`);
                    chip.type = 'button';
                    chip.title = `Автопроверка услышала «${info.expected_next}» в дубле ${am.name}. Клик — перейти к нему и послушать`;
                    chip.addEventListener('click', e => { e.stopPropagation(); sumFocusDub(am.index); });
                    tile.appendChild(chip);
                    sumAutoNavigate(tier, info.expected_next, am);
                }

                // Записанное — чипы: клик слушать, × убрать (брак).
                let recs = sumEl('div', 'sum-cat__recs');
                if (!items.length) recs.appendChild(sumEl('span', 'sum-cat__empty', 'перетащите дубль сюда'));
                let browse = sumStage1BrowseIdx[tier] || 0;
                for (let i = items.length - 1; i >= 0; i--) {
                    let chip = sumEl('span', 'sum-rec' + (i === browse && tIdx === sumStage1SelectedIdx ? ' is-browsed' : ''));
                    chip.dataset.idx = i;
                    chip.title = 'Клик — прослушать. Перетащите на дорожку «Сборки», чтобы поставить в сборку';
                    chip.draggable = true;
                    chip.addEventListener('dragstart', e => {
                        e.dataTransfer.setData(SUM_REC_TYPE, JSON.stringify({ tier, path: (info.paths || [])[i] }));
                        e.dataTransfer.effectAllowed = 'copy';
                        document.body.classList.add('sum-dragging');
                    });
                    chip.addEventListener('dragend', () => document.body.classList.remove('sum-dragging'));
                    chip.appendChild(sumEl('span', 'sum-rec__name', sumRecordedLabel(tier, items[i])));
                    let x = sumEl('button', 'sum-rec__x', '×');
                    x.type = 'button';
                    x.title = 'Убрать запись (брак) — значение снова будет ожидаться';
                    x.addEventListener('click', e => { e.stopPropagation(); sumRemoveRecord(tier, (info.paths || [])[i]); });
                    chip.appendChild(x);
                    chip.addEventListener('click', () => {
                        sumStage1SelectedIdx = tIdx;
                        sumStage1BrowseIdx[tier] = i;
                        sumPlayPath((info.paths || [])[i], chip);
                    });
                    recs.appendChild(chip);
                }
                tile.appendChild(recs);

                sumMakeDropZone(tile, indices => sumDropToCategory(tier, indices));
                grid.appendChild(tile);
            });

            let aud = sumEl('div', 'sum-cat sum-cat--audacity');
            aud.appendChild(sumEl('div', 'sum-cat__name', 'Audacity'));
            aud.appendChild(sumEl('div', 'sum-cat__hint', 'Бросьте сюда дубли, чтобы поправить или разрезать слипшиеся'));
            sumMakeDropZone(aud, indices => sumDubsToAudacity(indices));
            grid.appendChild(aud);
        }

        // --- Лента карточек дублей ---
        let sumDubSel = new Set();
        let sumDubAnchor = null;
        let sumDubLastCurrent = null;

        let sumDubWindow = null;   // {from, count, total} — что сейчас загружено в ленту
        let sumDubPaging = false;

        function renderSumDubs(dubs, keepAnchor) {
            let rail = document.getElementById('sumDubsRail');
            let range = document.getElementById('sumDubsRange');
            if (!rail) return;
            sumDubsBindWheel(rail);
            // Какая карточка стояла у левого края — чтобы после перерисовки
            // лента не прыгала (ни после действий, ни после подгрузки куска).
            let anchorIdx = null, anchorOffset = 0;
            let cards = rail.querySelectorAll('.sum-dub');
            for (let c of cards) {
                if (c.offsetLeft + c.offsetWidth > rail.scrollLeft) {
                    anchorIdx = parseInt(c.dataset.index);
                    anchorOffset = c.offsetLeft - rail.scrollLeft;
                    break;
                }
            }
            rail.innerHTML = '';
            if (!dubs || !dubs.items || !dubs.items.length) {
                if (range) range.innerText = '';
                rail.appendChild(sumEl('div', 'sum-cat__empty', 'Дубли не загружены'));
                renderSumSelbar();
                return;
            }
            let items = dubs.items;
            if (range) range.innerText = `${items[0].index + 1}–${items[items.length - 1].index + 1} из ${dubs.total}`;
            let visible = new Set(items.map(it => it.index));
            sumDubSel.forEach(i => { if (!visible.has(i)) sumDubSel.delete(i); });

            let currentCard = null;
            items.forEach(it => {
                let card = sumEl('div', 'sum-dub');
                card.classList.toggle('is-current', it.current);
                card.classList.toggle('is-done', it.tiers.length > 0);
                card.classList.toggle('is-selected', sumDubSel.has(it.index));
                card.dataset.index = it.index;
                card.draggable = true;
                card.title = `${it.name}\nКлик — слушать, Ctrl/Shift — выбрать несколько, перетащите в категорию.\nДвойной клик — сделать текущим.`;

                let m = it.name.match(/(\d+)\s*$/);
                card.appendChild(sumEl('div', 'sum-dub__num', m ? m[1] : it.name));
                let tags = sumEl('div', 'sum-dub__tags');
                (it.tier_keys || []).forEach((k, n) => {
                    // Видно, какое значение получил дубль, а не только категорию.
                    let value = (it.values || [])[n];
                    let rec = (it.assigned || [])[n];
                    let tag = sumEl('span', 'sum-dub__tag', value || it.tiers[n]);
                    tag.title = `${it.tiers[n]}${value ? ': ' + value : ''}${rec && rec.checked ? ' — эталон в «Проверенных»' : ''}`;
                    tag.style.setProperty('--tier-accent', sumTierAccent(k));
                    if (rec && rec.path) {
                        // Ошиблись — «×» отменяет запись: сырую убирает как брак,
                        // эталон из «Проверенных» уносит в _Корзина проекта.
                        let x = sumEl('button', 'sum-dub__tag-x', '×');
                        x.type = 'button';
                        x.title = rec.checked ? 'Убрать этот эталон из «Проверенных» (в _Корзина) — значение снова будет ожидаться'
                                              : 'Убрать эту запись из категории (брак) — значение снова будет ожидаться';
                        x.addEventListener('click', e => { e.stopPropagation(); sumUnassign(rec.tier, rec.path, value); });
                        x.addEventListener('dblclick', e => e.stopPropagation());
                        tag.appendChild(x);
                    }
                    tags.appendChild(tag);
                });
                card.appendChild(tags);
                sumDubRenderAsr(card, it.asr);

                card.addEventListener('click', e => sumDubClick(e, it, card, items));
                card.addEventListener('dblclick', () => sumFocusDub(it.index));
                card.addEventListener('dragstart', e => {
                    let indices = sumDubSel.has(it.index) ? [...sumDubSel].sort((a, b) => a - b) : [it.index];
                    e.dataTransfer.setData(SUM_DND_TYPE, JSON.stringify(indices));
                    e.dataTransfer.setData('text/plain', JSON.stringify(indices));
                    e.dataTransfer.effectAllowed = 'copy';
                    if (indices.length > 1) {
                        let ghost = sumEl('div', 'sum-dub-ghost', `${indices.length} дублей`);
                        document.body.appendChild(ghost);
                        e.dataTransfer.setDragImage(ghost, 20, 20);
                        setTimeout(() => ghost.remove(), 0);
                    }
                    document.body.classList.add('sum-dragging');
                });
                card.addEventListener('dragend', () => document.body.classList.remove('sum-dragging'));

                if (it.current) currentCard = card;
                rail.appendChild(card);
            });

            sumDubWindow = { from: items[0].index, count: items.length, total: dubs.total };
            let anchorCard = anchorIdx !== null ? rail.querySelector(`.sum-dub[data-index="${anchorIdx}"]`) : null;
            if (currentCard && sumDubLastCurrent !== dubs.current && !keepAnchor) {
                currentCard.scrollIntoView({ inline: 'center', block: 'nearest' });
            } else if (anchorCard) {
                rail.scrollLeft = anchorCard.offsetLeft - anchorOffset;
            }
            sumDubLastCurrent = dubs.current;
            renderSumSelbar();
        }

        // Колесо мыши над лентой — листает её вбок. Подгрузка соседнего
        // куска срабатывает от ЛЮБОЙ прокрутки (колесо, полоса прокрутки,
        // тачпад) и заранее — за ~300 px до края, чтобы лента не упиралась.
        const SUM_DUB_PREFETCH_PX = 300;
        function sumDubsBindWheel(rail) {
            if (rail.dataset.wheel) return;
            rail.dataset.wheel = '1';
            rail.addEventListener('wheel', e => {
                let delta = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
                if (!delta) return;
                e.preventDefault();
                if (e.deltaMode === 1) delta *= 40;
                rail.scrollLeft += delta;
                sumDubsCheckEdge();
            }, { passive: false });
            rail.addEventListener('scroll', sumDubsCheckEdge, { passive: true });
        }
        function sumDubsCheckEdge() {
            let rail = document.getElementById('sumDubsRail');
            let w = sumDubWindow;
            if (!rail || !w || sumDubPaging) return;
            let toEnd = rail.scrollWidth - (rail.scrollLeft + rail.clientWidth);
            if (toEnd <= SUM_DUB_PREFETCH_PX && w.from + w.count < w.total) sumDubsPage(1);
            else if (rail.scrollLeft <= SUM_DUB_PREFETCH_PX && w.from > 0) sumDubsPage(-1);
        }
        async function sumDubsPage(dir) {
            let w = sumDubWindow;
            if (!w || sumDubPaging) return;
            let step = Math.floor(w.count / 2);
            let start = dir > 0 ? w.from + step : Math.max(0, w.from - step);
            sumDubPaging = true;
            let ok = false;
            try {
                let dubs = await pywebview.api.sum_dub_cards_at(start);
                if (dubs && dubs.items && dubs.items.length) {
                    if (lastSumState) lastSumState.dubs = dubs;
                    renderSumDubs(dubs, true);
                    ok = true;
                }
            } catch (e) {
                showToast(`Не удалось подгрузить дубли: ${e}`);
            } finally {
                sumDubPaging = false;
            }
            // Прокрутили быстро и снова у края — подгружаем дальше.
            if (ok) requestAnimationFrame(sumDubsCheckEdge);
        }

        // ===== АВТОПРОВЕРКА (прототип) =====
        // Распознаёт дубли локально и показывает на карточке, на какое
        // значение категории это похоже и на сколько процентов. Ничего не
        // сохраняет само — зелёные можно смело тащить, жёлтые — послушать.
        let sumAsrRunning = false;
        function sumDubRenderAsr(card, asr) {
            let old = card.querySelector('.sum-dub__asr');
            if (old) old.remove();
            card.classList.remove('asr-ok', 'asr-low', 'asr-noise');
            if (!asr) return;
            let line = document.createElement('div');
            line.className = 'sum-dub__asr';
            if (asr.noise) {
                line.textContent = 'шум';
                card.classList.add('asr-noise');
            } else if (asr.error || !asr.heard) {
                line.textContent = asr.error ? 'ошибка' : 'тишина?';
                card.classList.add('asr-low');
            } else {
                line.textContent = `${Math.round(asr.score * 100)}% ${asr.best || ''}`;
                card.classList.add(asr.confident ? 'asr-ok' : 'asr-low');
            }
            card.title = (asr.heard ? `Распознано: «${asr.heard}»\n` : '')
                + (asr.best ? `Похоже на: ${asr.best} — ${Math.round(asr.score * 100)}% (второй вариант ${Math.round((asr.second || 0) * 100)}%)\n` : '')
                + (asr.noise ? 'Похоже на шум/тишину — слов не нашлось' : asr.confident ? 'Уверенно — можно переносить' : 'Не уверен — послушайте')
                + (asr.error ? `\nОшибка: ${asr.error}` : '');
            card.appendChild(line);
        }
        let sumAsrStats = { ok: 0, low: 0, noise: 0 };
        function sumAutoCheckProgress(p) {
            if (p.noise) sumAsrStats.noise++; else if (p.confident) sumAsrStats.ok++; else sumAsrStats.low++;
            let dubs = lastSumState && lastSumState.dubs;
            if (dubs) {
                let it = dubs.items.find(x => x.index === p.index);
                if (it) it.asr = p;
            }
            let card = document.querySelector(`#sumDubsRail .sum-dub[data-index="${p.index}"]`);
            if (card) sumDubRenderAsr(card, p);
            let btn = document.getElementById('sumAsrBtn');
            if (btn && sumAsrRunning) btn.textContent = `Стоп (${p.done}/${p.total})`;
        }
        function closeAsrModel() {
            document.getElementById('asrModelOverlay').style.display = 'none';
        }
        // Окно «нужна модель»: для казахского — своя, крупнее (small его почти не понимает).
        let asrModelLang = null;
        const ASR_HINT_RU = document.getElementById('asrModelHint') ? document.getElementById('asrModelHint').innerHTML : '';
        function showAsrModel(lang) {
            asrModelLang = lang === 'kz' ? 'kz' : null;
            document.getElementById('asrModelHint').innerHTML = asrModelLang ? `
                Для <b>казахского</b> нужна модель крупнее: скачать её автоматически не получилось — похоже, доступ к сайту <b>huggingface.co</b> закрыт.
                Скачайте один раз вручную (можно на другом компьютере):
                <ol>
                    <li>Откройте <b>huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo</b> → вкладка <b>Files</b>.</li>
                    <li>Скачайте все файлы: <code>config.json</code>, <code>model.bin</code> (~1,6 ГБ), <code>tokenizer.json</code>, <code>vocabulary.json</code>, <code>preprocessor_config.json</code>.</li>
                    <li>Сложите их в одну папку и укажите её кнопкой ниже — программа запомнит (для русского останется прежняя модель).</li>
                </ol>
                Подойдёт и другая модель faster-whisper (CTranslate2), например дообученная на казахском — укажите её папку.` : ASR_HINT_RU;
            document.getElementById('asrModelOverlay').style.display = 'flex';
        }
        async function pickAsrModel() {
            let res = await pywebview.api.sum_auto_check_pick_model(asrModelLang);
            if (!res || res.error === 'cancel') return;
            if (res.error) { showBeautifulAlert(`❌ <b>Модель</b><br><br>${escapeHtml(res.error)}`); return; }
            closeAsrModel();
            if (isShown('stage4-tts')) { showToast('Модель найдена — можно записывать (R)'); return; }
            showToast('Модель найдена — запускаю автопроверку');
            sumAutoCheckToggle();
        }
        async function sumAutoCheckToggle() {
            let btn = document.getElementById('sumAsrBtn');
            if (sumAsrRunning) {
                try { await pywebview.api.sum_auto_check_stop(); } catch (_) {}
                return;
            }
            if (!sumStage1Tiers.length) return;
            let tier = sumStage1Tiers[sumStage1SelectedIdx];
            // Выделено НЕСКОЛЬКО дублей (Ctrl/Shift) — проверяем их; иначе все
            // неразобранные и ещё не проверенные во всём списке. Обычный клик
            // «послушать» выделяет один дубль — он автопроверку не ограничивает.
            let indices = sumDubSel.size > 1 ? [...sumDubSel].sort((a, b) => a - b) : null;
            let lang = (document.getElementById('sumAsrLang') || {}).value || 'ru';
            sumAsrRunning = true;
            sumAsrStats = { ok: 0, low: 0, noise: 0 };
            btn.classList.add('is-running');
            btn.textContent = 'Загружаю модель…';
            showToast(indices ? `Автопроверка: ${indices.length} выделенных против «${tier.label}»`
                              : `Автопроверка всех неразобранных против «${tier.label}» — можно продолжать работать`);
            let res;
            try { res = await pywebview.api.sum_auto_check(tier.key, indices, lang); }
            catch (e) { res = { error: String(e) }; }
            sumAsrRunning = false;
            btn.classList.remove('is-running');
            sumAsrBtnLabel();
            if (res && res.need_model) { document.getElementById('asrModelOverlay').style.display = 'flex'; return; }
            if (res && res.error) { showBeautifulAlert(`❌ <b>Автопроверка</b><br><br>${escapeHtml(res.error).replace(/\n/g, '<br>')}`); return; }
            showToast(`${res.stopped ? 'Остановлено' : 'Готово'}: проверено ${res.done} — уверенно ${sumAsrStats.ok}, на прослушку ${sumAsrStats.low}, шум ${sumAsrStats.noise}`, 6000);
        }

        function sumDubClick(e, it, card, items) {
            if (e.shiftKey && sumDubAnchor !== null) {
                let [a, b] = [Math.min(sumDubAnchor, it.index), Math.max(sumDubAnchor, it.index)];
                items.forEach(x => { if (x.index >= a && x.index <= b) sumDubSel.add(x.index); });
            } else if (e.ctrlKey || e.metaKey) {
                if (sumDubSel.has(it.index)) sumDubSel.delete(it.index); else sumDubSel.add(it.index);
                sumDubAnchor = it.index;
            } else {
                sumDubSel = new Set([it.index]);
                sumDubAnchor = it.index;
                sumPlayPath(it.path, card);
            }
            document.querySelectorAll('#sumDubsRail .sum-dub').forEach(c =>
                c.classList.toggle('is-selected', sumDubSel.has(parseInt(c.dataset.index))));
            renderSumSelbar();
        }

        function renderSumSelbar() {
            let bar = document.getElementById('sumDubsSelbar');
            if (!bar) return;
            let n = sumDubSel.size;
            bar.style.display = n > 1 ? 'flex' : 'none';
            let cnt = document.getElementById('sumDubsSelCount');
            if (cnt) cnt.innerText = `Выбрано: ${n}`;
            sumAsrBtnLabel();
        }
        // На кнопке видно, что проверится: все неразобранные или выделенные.
        function sumAsrBtnLabel() {
            let btn = document.getElementById('sumAsrBtn');
            if (!btn || sumAsrRunning) return;
            let n = sumDubSel.size;
            btn.textContent = n > 1 ? `Автопроверка · ${n}` : 'Автопроверка';
            btn.title = n > 1
                ? `Распознать ${n} выделенных дублей и сверить с выбранной категорией. Снять выделение — проверятся все неразобранные`
                : 'Распознать все неразобранные дубли во всём списке и сверить с выбранной категорией. Чтобы проверить только некоторые — выделите их через Ctrl/Shift. Идёт в фоне';
        }
        function sumClearDubSelection() {
            sumDubSel.clear();
            document.querySelectorAll('#sumDubsRail .sum-dub.is-selected').forEach(c => c.classList.remove('is-selected'));
            renderSumSelbar();
        }

        // --- Действия ---
        async function sumApply(call, playIfMoved) {
            let before = lastSumState && lastSumState.dubs ? lastSumState.dubs.current : null;
            let state;
            try { state = await call(); } catch (e) { showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${e}`); return null; }
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return null;
            }
            updateUI(state);
            let after = lastSumState && lastSumState.dubs ? lastSumState.dubs.current : null;
            if (playIfMoved && before !== after) playAudio(false);
            return state;
        }
        async function sumDropToCategory(tier, indices) {
            let res = await sumApply(() => pywebview.api.sum_send_dubs(tier, indices), true);
            if (res) indices.forEach(i => sumDubSel.delete(i));
            renderSumSelbar();
        }
        async function sumDubsToAudacity(indices) {
            let res = await sumApply(() => pywebview.api.sum_dubs_to_audacity(indices), false);
            if (res && sumModeActive && !audacityEmbedded) await attachEmbeddedAudacity(true);
        }
        async function sumSelectedToAudacity() {
            if (!sumDubSel.size) return;
            await sumDubsToAudacity([...sumDubSel].sort((a, b) => a - b));
        }
        function sumShowHelp() {
            showBeautifulAlert('ℹ️ <b>Управление в «Суммах»</b><br><br>'
                + '<b>Мышью:</b> перетащите дубль в категорию · клик — слушать · Ctrl/Shift — несколько · '
                + '× на записи — убрать брак · × на метке дубля — отменить записанное (и эталон) · '
                + 'в сборке тяните ручки краёв, протяните по волне и Del — вырезать середину.<br><br>'
                + '<b>Клавиши:</b> ↑↓ категория · Z текущий дубль в неё · X отменить · Del убрать запись / вырезать выделенное · '
                + 'Space — слушать: после клика по дублям — дубль, после клика по «Сборке» — сборку с начала · '
                + 'P слушать сборку · Enter сохранить эталон.');
        }
        let sumSpaceZone = 'dubs';
        function sumSetSpaceZone(zone) {
            sumSpaceZone = zone;
            let ed = document.getElementById('sumEditor');
            if (ed) ed.classList.toggle('is-space-zone', zone === 'editor');
            let dubs = document.querySelector('.sum-dubs');
            if (dubs) dubs.classList.toggle('is-space-zone', zone === 'dubs');
        }
        document.addEventListener('pointerdown', e => {
            if (!sumModeActive || !e.target.closest) return;
            if (e.target.closest('#sumEditor')) sumSetSpaceZone('editor');
            else if (e.target.closest('.sum-dubs, #sumCats')) sumSetSpaceZone('dubs');
        }, true);
        // Space: в зоне «Сборка» — слушать сборку с начала (start → переменная → end),
        // в зоне дублей — только выбранный кликом (или текущий) дубль. Повторно — стоп.
        async function sumSpace() {
            if (sumSpaceZone === 'editor') {
                stopSumTierHighlight();
                sumEditorTogglePlay();
                return;
            }
            if (typeof sumEd !== 'undefined' && sumEd.play) await sumEditorStop();
            if (document.querySelector('.sum-dub.is-playing, .sum-rec.is-playing')) {
                stopSumTierHighlight();
                try { await pywebview.api.stop_audio(); } catch (_) {}
                return;
            }
            let dubs = lastSumState && lastSumState.dubs;
            let idx = sumDubSel.size === 1 ? [...sumDubSel][0] : (dubs ? dubs.current : null);
            let it = dubs && (dubs.items || []).find(x => x.index === idx);
            let card = document.querySelector(`#sumDubsRail .sum-dub[data-index="${idx}"]`);
            if (it) sumPlayPath(it.path, card); else playAudio(true);
        }
        async function sumUnassign(tier, path, value) {
            let ok = await showBeautifulConfirm(`ℹ️ <b>Отменить «${escapeHtml(value || '')}»?</b><br><br>`
                + 'Запись уберётся (эталон — в папку <b>_Корзина</b> проекта), значение снова будет ожидаться, '
                + 'а сборка перейдёт на его строку.', 'Отменить запись', 'Оставить');
            if (!ok) return;
            if (typeof sumEd !== 'undefined') sumEd.sig = null;
            await sumApply(() => pywebview.api.sum_unassign(tier, path), false);
        }
        // Ожидаемое значение сменилось и автопроверка его где-то услышала —
        // сразу переходим к этому дублю (один раз на значение). Отключается
        // галочкой «Автонавигация».
        let sumAutoNavSeen = {};
        function sumAutoNavigate(tier, value, match) {
            let key = tier + '|' + value;
            if (sumAutoNavSeen[tier] === key) return;
            sumAutoNavSeen[tier] = key;
            let cb = document.getElementById('sumAutoNav');
            if (cb && !cb.checked) return;
            if (lastSumState && lastSumState.dubs && lastSumState.dubs.current === match.index) return;
            // Без звука: сборка в это время может сама проигрываться.
            setTimeout(() => sumApply(() => pywebview.api.sum_focus_dub(match.index), false), 0);
        }
        async function sumFocusDub(index) {
            await sumApply(() => pywebview.api.sum_focus_dub(index), true);
        }
        async function sumSetExpected(tier, value) {
            if (!value) return;
            await sumApply(() => pywebview.api.sum_set_expected_value(tier, value), false);
        }
        // Убрать запись (брак). Если это только что отправленный дубль —
        // полный откат: дубль возвращается текущим.
        async function sumRemoveRecord(tier, path) {
            if (!path) return;
            await sumApply(() => pywebview.api.sum_remove_raw(tier, path), true);
        }
        // Delete — убрать запись, подсвеченную в выбранной категории.
        async function sumRemoveBrowsed() {
            if (!sumStage1Tiers.length || !lastSumState || !lastSumState.reels) return;
            let tier = sumStage1Tiers[sumStage1SelectedIdx].key;
            let info = lastSumState.reels.tiers[tier] || {};
            let paths = info.paths || [];
            if (!paths.length) { showToast('В этой категории пока нечего убирать'); return; }
            await sumRemoveRecord(tier, paths[sumStage1BrowseIdx[tier] || 0]);
        }

        async function sumStage1SendSelected() {
            if (!sumStage1Tiers.length) return;
            await sumStage1Send(sumStage1Tiers[sumStage1SelectedIdx].key);
        }
        async function sumStage1Send(tier) {
            let res = await sumApply(() => pywebview.api.sum_stage1_send(tier), false);
            if (!res) return;
            // Z: после записи — следующая категория и сразу звук следующего дубля.
            if (sumStage1Tiers.length) {
                sumStage1SelectedIdx = (sumStage1SelectedIdx + 1) % sumStage1Tiers.length;
                renderSumSingleRow();
            }
            playAudio(false);
        }
        async function sumStage1Undo() {
            let res = await sumApply(() => pywebview.api.sum_stage1_undo(), false);
            if (!res) return;
            if (sumStage1Tiers.length) {
                sumStage1SelectedIdx = (sumStage1SelectedIdx - 1 + sumStage1Tiers.length) % sumStage1Tiers.length;
                renderSumSingleRow();
            }
            playAudio(false);
        }

        function renderSumReels(data) {
            if (!data) return;
            let tiersOrder = Object.keys(data.tiers);
            sumStage1Tiers = tiersOrder.map(key => ({ key, label: data.tiers[key].label }));
            if (sumStage1SelectedIdx >= sumStage1Tiers.length) sumStage1SelectedIdx = 0;

            let nextName = document.getElementById('sumStage2NextName');
            if (nextName) {
                nextName.innerText = (data.rows_total)
                    ? `Строка ${(data.row_idx || 0) + 1} / ${data.rows_total}`
                    : (data.next_name ? `→ ${data.next_name}` : '');
            }

            // Подсветка записанного (←/→) по умолчанию — на самом свежем;
            // если в категорию что-то добавилось — переезжает на новое.
            let defaults = data.default_indices || {};
            tiersOrder.forEach(tier => {
                let count = ((data.tiers[tier] || {}).items || []).length;
                let grew = (sumStage1BrowseCount[tier] || 0) < count;
                if ((!(tier in sumStage1BrowseIdx) || grew) && typeof defaults[tier] === 'number') {
                    sumStage1BrowseIdx[tier] = defaults[tier];
                }
                if (sumStage1BrowseIdx[tier] >= count) sumStage1BrowseIdx[tier] = Math.max(0, count - 1);
                sumStage1BrowseCount[tier] = count;
            });

            renderSumSingleRow();
            sumEditorBind();
            sumEditorMaybeReload(data);
            sumEditorRenderRow();
        }

        // ===== РЕДАКТОР ТАЙМИНГА (сборка строки прямо в программе) =====
        // Волна всей сборки: связки (start/end) серым, значения категорий —
        // цветом категории, у каждого значения две ручки — начало и конец.
        // Тянете ручку — после отпускания звучит стык; клик по волне —
        // слушать с этого места. «Сохранить эталон» пишет обрезанные значения
        // в «Проверенные» и переходит к следующей строке.
        let sumEd = { segs: [], trims: [], gains: [], cuts: [], sel: null, bucket: 10, sig: null, drag: null, play: null, loading: false };
        const ED_PAD = 6, ED_LABEL_H = 20, ED_HANDLE_HIT = 7;
        const ED_MISSING_MS = 900;   // ширина пустого слота на дорожке (записи ещё нет)
        const SUM_REC_TYPE = 'application/x-gvox-rec';   // перетаскивание записанного чипа

        function sumEditorSignature(reels) {
            let parts = [reels.row_idx, reels.rows_total];
            Object.keys(reels.tiers || {}).sort().forEach(t => {
                let x = reels.tiers[t];
                parts.push(t, x.row_value, x.row_ready, x.active, (x.paths || []).length);
            });
            if (!reels.rows_total) parts.push(JSON.stringify(sumStage2Indices()));
            return JSON.stringify(parts);
        }
        function sumEditorMaybeReload(reels) {
            if (!reels || !document.getElementById('sumEditor')) return;
            let sig = sumEditorSignature(reels);
            if (sig === sumEd.sig) return;
            sumEd.sig = sig;
            sumEditorLoad();
        }
        async function sumEditorLoad() {
            if (sumEd.loading) return;
            sumEd.loading = true;
            let res;
            try { res = await pywebview.api.sum_editor_load(sumStage2Indices()); }
            catch (e) { res = { error: String(e) }; }
            finally { sumEd.loading = false; }
            sumEditorApplyLoad(res);
        }
        function sumEditorApplyLoad(res) {
            sumEditorStopPlayhead();
            let msg = document.getElementById('sumEditorMsg');
            if (res && res.error) {
                sumEd.segs = []; sumEd.trims = []; sumEd.gains = []; sumEd.cuts = []; sumEd.sel = null;
                if (msg) msg.innerText = res.error;
            } else {
                sumEd.segs = (res && res.segments) || [];
                sumEd.bucket = (res && res.bucket_ms) || 10;
                sumEd.trims = sumEditorAutoTrims();
                sumEd.ref = (res && res.ref_loudness_db != null) ? res.ref_loudness_db : null;
                sumEd.gains = sumEditorAutoGains();
                sumEd.cuts = sumEd.segs.map(() => []);
                sumEd.sel = null;
                let missing = (res && res.missing) || [];
                if (msg) msg.innerText = !sumEd.segs.length
                    ? 'Для этой строки ещё нет записей — перетащите сюда дубль или запись из категории'
                    : (missing.length ? `Нет записи: ${missing.join(', ')} — перетащите на пустой слот дубль из ленты или запись из категории` : '');
            }
            sumEditorRenderRow();
            sumEditorRenderGains();
            sumEditorRenderCutBtn();
            sumEditorDraw();
            // После «Сохранить эталон» следующая строка сразу звучит.
            if (sumEd.playNext && sumEd.segs.length && sumEditorOpt('gvox_auto_play')) sumEditorPlay(0);
            sumEd.playNext = false;
            sumEd.loadedAt = performance.now();
        }
        function sumEditorRenderRow() {
            let el = document.getElementById('sumEditorRow');
            let reels = lastSumState && lastSumState.reels;
            if (!el || !reels) return;
            let values = Object.values(reels.row_values || {}).filter(Boolean);
            el.innerText = reels.rows_total
                ? `Строка ${(reels.row_idx || 0) + 1} / ${reels.rows_total}${values.length ? ' · ' + values.join(' · ') : ''}`
                : '';
        }

        // --- геометрия ---
        function edDur(i) { let s = sumEd.segs[i]; return s.missing ? ED_MISSING_MS : s.duration_ms; }
        function edTotal() { let t = 0; for (let j = 0; j < sumEd.segs.length; j++) t += edDur(j); return t; }
        function edSegStart(i) { let t = 0; for (let j = 0; j < i; j++) t += edDur(j); return t; }
        function edSlotAt(canvas, x) {
            let ms = edMsAt(canvas, x);
            for (let j = 0; j < sumEd.segs.length; j++) {
                let s0 = edSegStart(j);
                if (ms >= s0 && ms < s0 + edDur(j)) return j;
            }
            return -1;
        }
        function edX(canvas, ms) { let w = canvas.clientWidth - 2 * ED_PAD; return ED_PAD + (edTotal() ? ms / edTotal() * w : 0); }
        function edMsAt(canvas, x) { let w = canvas.clientWidth - 2 * ED_PAD; return Math.max(0, Math.min(edTotal(), (x - ED_PAD) / w * edTotal())); }
        // Оставшиеся после обрезки краёв и вырезов куски сегмента j (мс от его начала).
        function edKept(j) {
            let [a, b] = sumEd.trims[j];
            let cuts = (sumEd.cuts[j] || []).map(c => [Math.max(a, c[0]), Math.min(b, c[1])])
                .filter(c => c[1] > c[0]).sort((x, y) => x[0] - y[0]);
            let out = [], cur = a;
            for (let [c0, c1] of cuts) { if (c0 > cur) out.push([cur, c0]); cur = Math.max(cur, c1); }
            if (b > cur) out.push([cur, b]);
            return out;
        }
        function edOutLen(j) { return edKept(j).reduce((acc, k) => acc + k[1] - k[0], 0); }
        function edOrigToOut(ms) {
            let acc = 0, start = 0;
            for (let j = 0; j < sumEd.segs.length; j++) {
                let d = edDur(j);
                if (ms < start + d) {
                    let local = ms - start;
                    return acc + edKept(j).reduce((x, k) => x + Math.max(0, Math.min(local, k[1]) - k[0]), 0);
                }
                acc += edOutLen(j); start += d;
            }
            return acc;
        }
        function edOutToOrig(out) {
            let start = 0;
            for (let j = 0; j < sumEd.segs.length; j++) {
                for (let [k0, k1] of edKept(j)) {
                    if (out < k1 - k0) return start + k0 + out;
                    out -= k1 - k0;
                }
                start += edDur(j);
            }
            return edTotal();
        }
        function edAccent(seg) {
            return seg.connector ? 'rgba(160,170,190,0.75)'
                : (getComputedStyle(document.documentElement).getPropertyValue('--accent-var').trim() || '#eeac3e');
        }
        function edTierColor(seg) {
            let c = sumTierAccent(seg.key);
            if (c && c.startsWith('var(')) c = getComputedStyle(document.documentElement).getPropertyValue(c.slice(4, -1)).trim();
            return c || edAccent(seg);
        }

        // --- отрисовка ---
        function sumEditorDraw(playOrigMs) {
            let canvas = document.getElementById('sumEditorCanvas');
            if (!canvas) return;
            let dpr = window.devicePixelRatio || 1;
            let W = canvas.clientWidth, H = canvas.clientHeight;
            if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
                canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
            }
            let ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, W, H);
            let timeEl = document.getElementById('sumEditorTime');
            if (!sumEd.segs.length) { if (timeEl) timeEl.innerText = ''; return; }

            let top = ED_LABEL_H, h = H - ED_LABEL_H - 4, mid = top + h / 2;
            ctx.font = '600 11px system-ui, sans-serif';
            ctx.textBaseline = 'middle';
            sumEd.segs.forEach((seg, i) => {
                let s0 = edSegStart(i), x0 = edX(canvas, s0), x1 = edX(canvas, s0 + edDur(i));
                let color = seg.connector ? edAccent(seg) : edTierColor(seg);
                if (seg.missing) {
                    // Пустой слот: записи для этого значения ещё нет — сюда бросают.
                    ctx.save();
                    ctx.setLineDash([5, 4]); ctx.strokeStyle = color; ctx.lineWidth = 1.5;
                    ctx.strokeRect(x0 + 2, top + 2, x1 - x0 - 4, h - 4);
                    ctx.restore();
                    ctx.save();
                    ctx.beginPath(); ctx.rect(x0 + 2, 0, Math.max(0, x1 - x0 - 4), H); ctx.clip();
                    ctx.fillStyle = color;
                    ctx.fillText(`${seg.label}: ${seg.value || ''}`, x0 + 4, ED_LABEL_H / 2);
                    ctx.fillStyle = 'rgba(200,205,215,0.7)';
                    ctx.fillText('перетащите', x0 + 8, mid - 7);
                    ctx.fillText('запись сюда', x0 + 8, mid + 8);
                    ctx.restore();
                    return;
                }
                ctx.fillStyle = seg.connector ? 'rgba(255,255,255,0.03)' : 'rgba(255,255,255,0.06)';
                ctx.fillRect(x0, top, x1 - x0, h);
                let gainK = Math.pow(10, (sumEd.gains[i] || 0) / 20);

                ctx.strokeStyle = color; ctx.lineWidth = 1;
                ctx.beginPath();
                let n = seg.peaks.length;
                for (let k = 0; k < n; k++) {
                    let x = edX(canvas, s0 + k * sumEd.bucket);
                    let amp = Math.max(0.5, Math.min(1, seg.peaks[k] * gainK) * (h / 2 - 2));
                    ctx.moveTo(x, mid - amp); ctx.lineTo(x, mid + amp);
                }
                ctx.stroke();

                let [a, b] = sumEd.trims[i];
                ctx.fillStyle = 'rgba(8,10,14,0.72)';
                if (a > 0) ctx.fillRect(x0, top, edX(canvas, s0 + a) - x0, h);
                if (b < seg.duration_ms) { let xb = edX(canvas, s0 + b); ctx.fillRect(xb, top, x1 - xb, h); }
                // Вырезанное из середины — затемнено со штриховкой, клик возвращает.
                (sumEd.cuts[i] || []).forEach(([c0, c1]) => {
                    let cx0 = edX(canvas, s0 + c0), cx1 = edX(canvas, s0 + c1);
                    ctx.fillStyle = 'rgba(8,10,14,0.78)';
                    ctx.fillRect(cx0, top, cx1 - cx0, h);
                    ctx.save();
                    ctx.beginPath(); ctx.rect(cx0, top, cx1 - cx0, h); ctx.clip();
                    ctx.strokeStyle = 'rgba(229,72,77,0.55)'; ctx.lineWidth = 1;
                    for (let hx = cx0 - h; hx < cx1; hx += 7) { ctx.beginPath(); ctx.moveTo(hx, top + h); ctx.lineTo(hx + h, top); ctx.stroke(); }
                    ctx.restore();
                    ctx.fillStyle = 'rgba(229,72,77,0.9)';
                    ctx.fillRect(cx0, top, 1, h); ctx.fillRect(cx1 - 1, top, 1, h);
                });
                if (sumEd.sel && sumEd.sel.i === i) {
                    let sx0 = edX(canvas, s0 + sumEd.sel.a), sx1 = edX(canvas, s0 + sumEd.sel.b);
                    ctx.fillStyle = 'rgba(122,162,255,0.28)';
                    ctx.fillRect(sx0, top, sx1 - sx0, h);
                    ctx.fillStyle = 'rgba(122,162,255,0.95)';
                    ctx.fillRect(sx0, top, 1, h); ctx.fillRect(sx1 - 1, top, 1, h);
                }

                ctx.fillStyle = 'rgba(255,255,255,0.18)';
                ctx.fillRect(x1 - 0.5, top, 1, h);

                let g = sumEd.gains[i] || 0;
                let label = seg.connector ? seg.label
                    : `${seg.label}: ${seg.value || ''}${seg.source ? ' ← ' + seg.source : ''}${g ? ` (${g > 0 ? '+' : ''}${g} дБ)` : ''}`;
                ctx.save();
                ctx.beginPath(); ctx.rect(x0 + 2, 0, Math.max(0, x1 - x0 - 4), ED_LABEL_H); ctx.clip();
                ctx.fillStyle = seg.connector ? 'rgba(160,170,190,0.8)' : color;
                ctx.fillText(label, x0 + 4, ED_LABEL_H / 2);
                ctx.restore();

                if (!seg.connector && (seg.speech_groups || []).length) {
                    // Несколько кусков речи — номер над каждым (клавиши 1, 2…).
                    ctx.save();
                    ctx.font = '700 11px system-ui, sans-serif';
                    seg.speech_groups.forEach((g, k) => {
                        let gx0 = edX(canvas, s0 + g[0]), gx1 = edX(canvas, s0 + g[1]);
                        let picked = a === g[0] && b === g[1];
                        ctx.fillStyle = picked ? color : 'rgba(255,255,255,0.10)';
                        ctx.fillRect(gx0, top + h - 3, Math.max(2, gx1 - gx0), 3);
                        ctx.fillStyle = picked ? '#111' : 'rgba(255,255,255,0.85)';
                        let tx = (gx0 + gx1) / 2;
                        ctx.beginPath(); ctx.arc(tx, top + 10, 8, 0, Math.PI * 2);
                        ctx.fillStyle = picked ? color : 'rgba(0,0,0,0.65)'; ctx.fill();
                        ctx.fillStyle = picked ? '#111' : '#fff';
                        ctx.textAlign = 'center';
                        ctx.fillText(String(k + 1), tx, top + 10.5);
                    });
                    ctx.restore();
                }
                if (!seg.connector) {
                    [a, b].forEach((ms, side) => {
                        let x = edX(canvas, s0 + ms);
                        ctx.fillStyle = color;
                        ctx.fillRect(x - 1, top, 2, h);
                        let tabW = 7;
                        ctx.fillRect(side === 0 ? x : x - tabW, top, tabW, 14);
                    });
                }
            });

            if (typeof playOrigMs === 'number') {
                let x = edX(canvas, playOrigMs);
                ctx.fillStyle = '#ffffff';
                ctx.fillRect(x - 1, top - 2, 2, h + 4);
            }

            if (timeEl) {
                let total = sumEd.segs.reduce((acc, _, j) => acc + edOutLen(j), 0);
                timeEl.innerText = `${(total / 1000).toFixed(2)} с`;
            }
        }

        // --- мышь ---
        function edHit(canvas, x) {
            let best = null;
            sumEd.segs.forEach((seg, i) => {
                if (seg.connector || seg.missing) return;
                let s0 = edSegStart(i);
                sumEd.trims[i].forEach((ms, side) => {
                    let d = Math.abs(edX(canvas, s0 + ms) - x);
                    if (d <= ED_HANDLE_HIT && (!best || d < best.d)) best = { i, side, d };
                });
            });
            return best;
        }
        function sumEditorBind() {
            let canvas = document.getElementById('sumEditorCanvas');
            if (!canvas || canvas.dataset.bound) return;
            canvas.dataset.bound = '1';
            canvas.addEventListener('pointerdown', e => {
                if (!sumEd.segs.length) return;
                let x = e.offsetX, hit = edHit(canvas, x);
                canvas.setPointerCapture(e.pointerId);
                if (hit) {
                    sumEd.drag = hit;
                    sumEditorStop();
                } else {
                    // Клик — слушать отсюда; протянуть по переменной — выделить кусок.
                    sumEd.press = { x, slot: edSlotAt(canvas, x), selecting: false };
                }
            });
            canvas.addEventListener('pointermove', e => {
                let x = e.offsetX;
                let pr = sumEd.press;
                if (pr) {
                    let seg = sumEd.segs[pr.slot];
                    if (!pr.selecting && Math.abs(x - pr.x) > 4 && seg && !seg.connector && !seg.missing) {
                        pr.selecting = true;
                        sumEditorStop();
                    }
                    if (pr.selecting) {
                        let s0 = edSegStart(pr.slot), [ta, tb] = sumEd.trims[pr.slot];
                        let m1 = Math.round(edMsAt(canvas, pr.x) - s0), m2 = Math.round(edMsAt(canvas, x) - s0);
                        let a = Math.max(ta, Math.min(m1, m2)), b = Math.min(tb, Math.max(m1, m2));
                        sumEd.sel = b - a >= 10 ? { i: pr.slot, a, b } : null;
                        sumEditorRenderCutBtn();
                        sumEditorDraw();
                    }
                    return;
                }
                if (!sumEd.drag) {
                    canvas.style.cursor = edHit(canvas, x) ? 'ew-resize' : (edCutAt(canvas, x) ? 'pointer' : 'text');
                    return;
                }
                let { i, side } = sumEd.drag;
                let s0 = edSegStart(i), dur = sumEd.segs[i].duration_ms;
                let ms = Math.round(edMsAt(canvas, x) - s0);
                let t = sumEd.trims[i];
                if (side === 0) t[0] = Math.max(0, Math.min(ms, t[1] - 40));
                else t[1] = Math.min(dur, Math.max(ms, t[0] + 40));
                sumEditorDraw();
            });
            const end = e => {
                let pr = sumEd.press;
                if (pr) {
                    sumEd.press = null;
                    try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
                    if (pr.selecting) {
                        // Сразу слышно, что выделено.
                        if (sumEd.sel) sumEditorPlay(edOrigToOut(edSegStart(sumEd.sel.i) + sumEd.sel.a));
                        return;
                    }
                    let cut = edCutAt(canvas, pr.x);
                    if (cut) { sumEditorUncut(cut.i, cut.k); return; }
                    sumEd.sel = null;
                    sumEditorRenderCutBtn();
                    sumEditorPlay(edOrigToOut(edMsAt(canvas, pr.x)));
                    return;
                }
                if (!sumEd.drag) return;
                let { i, side } = sumEd.drag;
                sumEd.drag = null;
                try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
                // Сразу слышно стык, который поправили: с ~0.8 с до края.
                let edge = edSegStart(i) + sumEd.trims[i][side];
                sumEditorPlay(Math.max(0, edOrigToOut(edge) - 800));
            };
            canvas.addEventListener('pointerup', end);
            canvas.addEventListener('pointercancel', end);

            // Перетаскивание на дорожку: дубль из ленты или запись из категории.
            let box = document.getElementById('sumEditor');
            box.addEventListener('dragover', e => {
                let t = e.dataTransfer.types;
                if (!t.includes(SUM_DND_TYPE) && !t.includes(SUM_REC_TYPE)) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
                box.classList.add('is-over');
            });
            box.addEventListener('dragleave', e => { if (!box.contains(e.relatedTarget)) box.classList.remove('is-over'); });
            box.addEventListener('drop', e => {
                box.classList.remove('is-over');
                document.body.classList.remove('sum-dragging');
                let rec = e.dataTransfer.getData(SUM_REC_TYPE);
                let dubs = e.dataTransfer.getData(SUM_DND_TYPE);
                if (!rec && !dubs) return;
                e.preventDefault();
                let rect = canvas.getBoundingClientRect();
                let over = (e.clientY >= rect.top && e.clientY <= rect.bottom) ? edSlotAt(canvas, e.clientX - rect.left) : -1;
                if (rec) {
                    let r = JSON.parse(rec);
                    sumEditorDropToSlot(r.tier, { path: r.path });
                } else {
                    let indices = JSON.parse(dubs);
                    if (indices.length > 1) showToast('В слот ставится одна запись — беру первый выделенный дубль');
                    sumEditorDropToSlot(sumEditorPickSlot(over), { dub: indices[0] });
                }
            });
            window.addEventListener('resize', () => sumEditorDraw());
            // Волна могла загрузиться, пока экран был скрыт (размер 0) —
            // перерисовываем, как только у холста появился/сменился размер.
            if (window.ResizeObserver) {
                new ResizeObserver(() => sumEditorDraw()).observe(canvas);
            }
        }

        // --- звук ---
        function sumEditorTrimsPayload() {
            let out = {};
            sumEd.trims.forEach((t, i) => {
                let seg = sumEd.segs[i];
                if (!seg.connector && (t[0] > 0 || t[1] < seg.duration_ms)) out[i] = t;
            });
            return out;
        }
        // Вырез под курсором (для «вернуть»).
        function edCutAt(canvas, x) {
            let j = edSlotAt(canvas, x);
            if (j < 0) return null;
            let local = edMsAt(canvas, x) - edSegStart(j);
            let k = (sumEd.cuts[j] || []).findIndex(c => local >= c[0] && local <= c[1]);
            return k >= 0 ? { i: j, k } : null;
        }
        function sumEditorRenderCutBtn() {
            let btn = document.getElementById('sumEditorCutBtn');
            if (btn) btn.disabled = !sumEd.sel;
        }
        // Вырезать выделенный кусок из середины переменной.
        function sumEditorCut() {
            let sel = sumEd.sel;
            if (!sel) { showToast('Сначала протяните мышью по волне переменной, чтобы выделить кусок'); return; }
            let list = sumEd.cuts[sel.i] || (sumEd.cuts[sel.i] = []);
            list.push([sel.a, sel.b]);
            // Пересекающиеся вырезы — в один.
            list.sort((x, y) => x[0] - y[0]);
            let merged = [];
            for (let c of list) {
                let last = merged[merged.length - 1];
                if (last && c[0] <= last[1]) last[1] = Math.max(last[1], c[1]); else merged.push([c[0], c[1]]);
            }
            sumEd.cuts[sel.i] = merged;
            sumEd.sel = null;
            sumEditorRenderCutBtn();
            sumEditorDraw();
            // Слушаем стык: с ~0.8 с до места выреза.
            sumEditorPlay(Math.max(0, edOrigToOut(edSegStart(sel.i) + sel.a) - 800));
        }
        function sumEditorUncut(i, k) {
            sumEd.cuts[i].splice(k, 1);
            sumEditorDraw();
            showToast('Вырезанный кусок возвращён');
        }
        function sumEditorCutsPayload() {
            let out = {};
            sumEd.cuts.forEach((c, i) => { if (c && c.length) out[i] = c; });
            return out;
        }
        function sumEditorGainsPayload() {
            let out = {};
            sumEd.gains.forEach((g, i) => { if (g) out[i] = g; });
            return out;
        }
        // Авто-громкость: переменная подгоняется под громкость связок,
        // чтобы сборка звучала единым потоком. Выключатель запоминается.
        function sumEditorOpt(name) {
            try { return localStorage.getItem(name) !== '0'; } catch (e) { return true; }
        }
        function sumEditorSetOpt(name, on) {
            try { localStorage.setItem(name, on ? '1' : '0'); } catch (e) {}
        }
        function sumEditorAutoOn() { return sumEditorOpt('gvox_auto_gain'); }
        function sumEditorAutoGains() {
            let on = sumEditorAutoOn();
            return sumEd.segs.map(s => (on && !s.connector && s.auto_gain_db) ? s.auto_gain_db : 0);
        }
        // Авто-обрезка: ручки краёв сразу стоят по речи, без тишины.
        function sumEditorAutoTrims() {
            let on = sumEditorOpt('gvox_auto_trim');
            return sumEd.segs.map(s => (on && !s.connector && s.auto_trim) ? [s.auto_trim[0], s.auto_trim[1]] : [0, s.duration_ms]);
        }
        function sumEditorToggleAuto(on) {
            sumEditorSetOpt('gvox_auto_gain', on);
            sumEd.gains = sumEditorAutoGains();
            sumEditorRenderGains();
            sumEditorDraw();
        }
        // Оставить один кусок речи (или все) — и сразу послушать его.
        function sumEditorPickPiece(i, g) {
            sumEd.trims[i] = [g[0], g[1]];
            (sumEd.cuts[i] || []).length = 0;
            sumEditorRenderGains();
            sumEditorDraw();
            sumEditorPlay(Math.max(0, edOrigToOut(edSegStart(i) + g[0]) - 400));
        }
        // Клавиши 1…9: кусок в первой переменной, где их несколько.
        function sumEditorPieceKey(n) {
            let i = sumEd.segs.findIndex(s => !s.connector && (s.speech_groups || []).length);
            if (i < 0) return false;
            let g = sumEd.segs[i].speech_groups[n - 1];
            if (!g) return false;
            sumEditorPickPiece(i, g);
            return true;
        }
        function sumEditorToggleTrim(on) {
            sumEditorSetOpt('gvox_auto_trim', on);
            sumEd.trims = sumEditorAutoTrims();
            sumEditorDraw();
        }
        function sumEditorOptBox(text, name, onChange, title) {
            let box = sumEl('label', 'sum-gain sum-gain--auto');
            let cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = sumEditorOpt(name);
            cb.addEventListener('change', () => { cb.blur(); onChange ? onChange(cb.checked) : sumEditorSetOpt(name, cb.checked); });
            box.append(cb, sumEl('span', '', text));
            box.title = title;
            return box;
        }
        const edDb = g => `${g > 0 ? '+' : ''}${g} дБ`;
        // Громкость каждой переменной: ▼/▲ по 1 дБ, сразу слышно.
        function sumEditorRenderGains() {
            let box = document.getElementById('sumEditorGains');
            if (!box) return;
            box.innerHTML = '';
            if (sumEd.segs.some(s => !s.connector && !s.missing)) {
                let auto = sumEl('label', 'sum-gain sum-gain--auto');
                let cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.checked = sumEditorAutoOn();
                cb.addEventListener('change', () => { cb.blur(); sumEditorToggleAuto(cb.checked); });
                auto.append(cb, sumEl('span', '', 'Авто-громкость под связки'));
                auto.title = sumEd.ref != null
                    ? `Громкость речи в связках: ${sumEd.ref} дБ. Переменные подтягиваются к ней; ▲▼ — поправить на слух`
                    : 'Связок в сборке нет — подгонять не под что';
                if (sumEd.ref == null) auto.classList.add('is-off');
                box.appendChild(auto);
                box.appendChild(sumEditorOptBox('Авто-обрезка тишины', 'gvox_auto_trim', sumEditorToggleTrim,
                    'Ручки краёв сразу ставятся по началу и концу речи. Поправить — тянуть ручки как раньше'));
                box.appendChild(sumEditorOptBox('Слушать следующую сразу', 'gvox_auto_play', null,
                    'После «Сохранить эталон» (Enter) следующая строка проигрывается сама'));
            }
            sumEd.segs.forEach((seg, i) => {
                if (seg.connector || seg.missing) return;
                let row = sumEl('span', 'sum-gain');
                row.style.setProperty('--tier-accent', sumTierAccent(seg.key));
                row.appendChild(sumEl('span', 'sum-gain__name', seg.label));
                if (seg.source) row.appendChild(sumEl('span', 'sum-gain__src', `← ${seg.source}`));
                let down = sumEl('button', 'sum-gain__btn', '▼');
                let val = sumEl('span', 'sum-gain__val', '');
                let up = sumEl('button', 'sum-gain__btn', '▲');
                down.type = up.type = 'button';
                down.title = 'Тише на 1 дБ'; up.title = 'Громче на 1 дБ';
                const paint = () => {
                    let g = sumEd.gains[i] || 0;
                    val.textContent = g ? edDb(g) : '0 дБ';
                    val.classList.toggle('is-changed', !!g);
                    let auto = sumEditorAutoOn() && seg.auto_gain_db;
                    val.classList.toggle('is-auto', !!auto && g === seg.auto_gain_db);
                    val.title = (seg.loudness_db != null ? `Громкость записи: ${seg.loudness_db} дБ` : '')
                        + (auto ? `\nАвто-поправка под связки: ${edDb(seg.auto_gain_db)}` : '');
                };
                const bump = d => {
                    sumEd.gains[i] = Math.round(Math.max(-20, Math.min(20, (sumEd.gains[i] || 0) + d)) * 10) / 10;
                    paint(); sumEditorDraw();
                    sumEditorPlay(Math.max(0, edOrigToOut(edSegStart(i) + sumEd.trims[i][0]) - 400));
                };
                down.addEventListener('click', () => bump(-1));
                up.addEventListener('click', () => bump(1));
                paint();
                row.append(down, val, up);
                box.appendChild(row);
                let groups = seg.speech_groups || [];
                if (groups.length) {
                    let pick = sumEl('span', 'sum-gain sum-pieces');
                    pick.style.setProperty('--tier-accent', sumTierAccent(seg.key));
                    pick.title = 'В записи несколько кусков речи через паузу — выберите нужный (клавиши 1, 2…), «Всё» — оставить целиком';
                    pick.appendChild(sumEl('span', 'sum-gain__name', 'Кусок'));
                    let opts = groups.map((g, k) => [String(k + 1), g]).concat([['Всё', [groups[0][0], groups[groups.length - 1][1]]]]);
                    opts.forEach(([text, g]) => {
                        let btn = sumEl('button', 'sum-pieces__btn', text);
                        btn.type = 'button';
                        let t = sumEd.trims[i];
                        if (t && t[0] === g[0] && t[1] === g[1]) btn.classList.add('is-on');
                        btn.addEventListener('click', () => { btn.blur(); sumEditorPickPiece(i, g); });
                        pick.appendChild(btn);
                    });
                    box.appendChild(pick);
                }
            });
        }
        // Куда ставить брошенный дубль: слот под курсором, иначе пустой
        // слот, иначе слот выбранной категории, иначе первый.
        function sumEditorPickSlot(over) {
            let segs = sumEd.segs;
            if (over >= 0 && !segs[over].connector) return segs[over].key;
            let empty = segs.find(s => s.missing);
            if (empty) return empty.key;
            let sel = sumStage1Tiers[sumStage1SelectedIdx];
            if (sel && segs.some(s => s.key === sel.key && !s.connector)) return sel.key;
            let first = segs.find(s => !s.connector);
            return first ? first.key : null;
        }
        async function sumEditorDropToSlot(key, src) {
            if (!key || !sumEd.segs.some(s => s.key === key && !s.connector)) {
                showToast('В сборке этой строки нет такого слота');
                return;
            }
            let res;
            try {
                res = await pywebview.api.sum_editor_set_slot(key, src.path || null,
                    src.dub !== undefined ? src.dub : null, sumStage2Indices());
            } catch (e) { res = { error: String(e) }; }
            if (res && res.error) { showBeautifulAlert(`❌ <b>Сборка</b><br><br>${escapeHtml(res.error)}`); return; }
            sumEditorApplyLoad(res);
            let i = sumEd.segs.findIndex(s => s.key === key);
            if (i >= 0) sumEditorPlay(Math.max(0, edOrigToOut(edSegStart(i)) - 600));
        }
        function sumEditorStopPlayhead() {
            if (sumEd.play) cancelAnimationFrame(sumEd.play.raf);
            sumEd.play = null;
            sumEditorDraw();
        }
        async function sumEditorStop() {
            if (!sumEd.play) return;
            sumEditorStopPlayhead();
            try { await pywebview.api.stop_audio(); } catch (_) {}
        }
        async function sumEditorPlay(fromOut) {
            if (!sumEd.segs.length) return;
            let res;
            try { res = await pywebview.api.sum_editor_play(sumEditorTrimsPayload(), Math.round(fromOut || 0), sumEditorGainsPayload(), sumEditorCutsPayload()); }
            catch (e) { return; }
            if (!res || res.error) { if (res && res.error) showToast(res.error); return; }
            if (sumEd.play) cancelAnimationFrame(sumEd.play.raf);
            let t0 = performance.now(), from = res.from_ms || 0, len = (res.duration || 0) * 1000;
            sumEd.play = { raf: 0 };
            const tick = () => {
                let el = performance.now() - t0;
                if (!sumEd.play || el >= len) { sumEd.play = null; sumEditorDraw(); return; }
                sumEditorDraw(edOutToOrig(from + el));
                sumEd.play.raf = requestAnimationFrame(tick);
            };
            sumEd.play.raf = requestAnimationFrame(tick);
            let btn = document.getElementById('sumEditorPlayBtn');
            if (btn) btn.blur();
        }
        function sumEditorTogglePlay() {
            if (sumEd.play) sumEditorStop(); else sumEditorPlay(0);
        }
        async function sumEditorReset() {
            // Края, громкость и подставленные вручную записи — как было.
            let res;
            try { res = await pywebview.api.sum_editor_clear_slots(sumStage2Indices()); } catch (e) { res = null; }
            if (res && !res.error) { sumEditorApplyLoad(res); return; }
            sumEd.trims = sumEditorAutoTrims();
            sumEd.gains = sumEditorAutoGains();
            sumEd.cuts = sumEd.segs.map(() => []);
            sumEd.sel = null;
            sumEditorRenderGains();
            sumEditorDraw();
        }
        async function sumEditorSave() {
            if (!sumEd.segs.length) { showToast('Нечего сохранять — для строки нет записей'); return; }
            // Двойной Enter не сохраняет следующую строку вслепую.
            if (sumEd.saving || sumEd.loading || performance.now() - (sumEd.loadedAt || 0) < 400) return;
            sumEd.saving = true;
            try {
                await sumEditorStop();
                sumEd.sig = null;
                sumEd.playNext = true;
                let ok = await sumApply(() => pywebview.api.sum_editor_save(sumEditorTrimsPayload(), sumEditorGainsPayload(), sumEditorCutsPayload()), false);
                if (!ok) sumEd.playNext = false;
            } finally { sumEd.saving = false; }
        }

        function sumStage2Indices() {
            let indices = {};
            sumStage1Tiers.forEach(({ key: tier }) => {
                let items = (lastSumState && lastSumState.reels && lastSumState.reels.tiers[tier]) ?
                    lastSumState.reels.tiers[tier].items : [];
                if (items.length) indices[tier] = sumStage1BrowseIdx[tier] || 0;
            });
            return indices;
        }

        // Раньше у каждой категории была своя галочка «слушать» — убрали
        // из интерфейса, но объект оставляем пустым (=ничего не заглушено)
        // для sumStage2Play/sumStage2SendToAudacity ниже, которые всё ещё
        // фильтруют по нему.
        let sumStage2MuteState = {};

        let sumStage2IsPlaying = false;
        let sumStage2PlayTimeout = null;
        async function sumStage2Play() {
            let indices = sumStage2Indices();
            let filtered = {};
            Object.keys(indices).forEach(tier => {
                if (!sumStage2MuteState[tier]) filtered[tier] = indices[tier];
            });
            let res = await pywebview.api.constructor_play(filtered);
            if (res && res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            clearTimeout(sumStage2PlayTimeout);
            if (res && res.playing) {
                sumStage2IsPlaying = true;
                sumStage2PlayTimeout = setTimeout(() => { sumStage2IsPlaying = false; }, (res.duration || 0) * 1000);
            } else {
                sumStage2IsPlaying = false;
            }
        }
        async function sumStage2Stop() {
            clearTimeout(sumStage2PlayTimeout);
            sumStage2IsPlaying = false;
            await pywebview.api.stop_audio();
        }
        async function sumStage2TogglePlay() {
            if (sumStage2IsPlaying) await sumStage2Stop();
            else await sumStage2Play();
        }

        async function sumStage2SendToAudacity() {
            let btn = document.querySelector('#sumActionsPanel .btn-tile--primary');
            let origHtml = btn ? btn.innerHTML : null;
            if (btn) { btn.disabled = true; btn.innerHTML = 'Открываю Audacity...'; }
            let res;
            try {
                res = await pywebview.api.constructor_send_to_audacity(sumStage2Indices());
            } finally {
                if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
            }
            if (res && res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            if (sumModeActive && !audacityEmbedded) await attachEmbeddedAudacity(true);
        }

        async function sumSendDubToAudacity() {
            let state;
            try {
                state = await pywebview.api.sum_send_current_dub_to_audacity();
            } catch (e) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${e}`);
                return;
            }
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
            if (sumModeActive && !audacityEmbedded) await attachEmbeddedAudacity(true);
        }

        async function sumCollectDubLabels() {
            let state = await pywebview.api.sum_collect_dub_labels();
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
        }

        async function sumStage2Save() {
            let state = await pywebview.api.sum_stage2_save();
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
        }

        // Клик по счётчикам «Суммы»: подробная карточка — сколько сохранено
        // и осталось по каждому ярусу, и на каком числе юзер остановился
        // в последний раз (чтобы не гадать, что уже сделано).
        function showSumStatsModal() {
            if (!lastSumState || !lastSumState.stats) return;
            let rows = lastSumState.stats.map(s => {
                let capText = s.cap ? `${s.done} из ${s.cap}` : `${s.done}`;
                let remainingText = (s.remaining !== null && s.remaining !== undefined)
                    ? `осталось ${s.remaining}` : '';
                let lastText = s.last ? `последний: <b>${escapeHtml(s.last)}</b>` : 'ещё нет сохранённых';
                return `<div class="sum-stats-row">
                    <div class="sum-stats-tier">${escapeHtml(s.tier)} <span class="sum-stats-dir">(${escapeHtml(s.dir)})</span></div>
                    <div class="sum-stats-nums">${capText}${remainingText ? ' · ' + remainingText : ''}</div>
                    <div class="sum-stats-last">${lastText}</div>
                </div>`;
            }).join('');
            showBeautifulAlert(`<div class="sum-stats-modal"><h4>Статистика по ярусам</h4>${rows}</div>`);
        }

        async function sumSendToAudacity() {
            // Если Audacity закрыт, программа сама его запускает и ждёт
            // ответа — это может занять до 20-30 секунд на холодном старте,
            // а без индикатора кажется, что кнопка просто не работает.
            let btn = document.querySelector('#sumManualActions .btn-tile--primary');
            let origHtml = btn ? btn.innerHTML : null;
            if (btn) { btn.disabled = true; btn.innerHTML = 'Открываю Audacity...'; }

            let state;
            try {
                state = await pywebview.api.sum_send_to_audacity();
            } finally {
                if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
            }

            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
            // Теперь Audacity точно запущен — сажаем его окно в отведённую рамку
            if (sumModeActive && !audacityEmbedded) await attachEmbeddedAudacity(true);
        }

        async function sumManualSave() {
            let state = await pywebview.api.sum_manual_save(document.getElementById('addSilence').checked);
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
        }

        // Одна кнопка вместо «Остаток»/«Склеить» — бэкенд сам решает, какую
        // из двух логик применить, по тому, открыт ли сейчас дубль в
        // Audacity (см. sum_fix_split в variables_handler.py): открыт —
        // сохраняет выделение под ожидаемым именем в текущую ↑/↓
        // категорию; не открыт — склеивает текущий дубль со следующим.
        async function sumFixSplit() {
            if (!sumStage1Tiers.length) return;
            let state = await pywebview.api.sum_fix_split(sumStage1Tiers[sumStage1SelectedIdx].key);
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
        }

        // --- Вживление окна Audacity внутрь софта ---
        // Приём системный (Windows SetParent) — Audacity не создан для этого,
        // поэтому если поведение станет хуже, кнопка сразу отсоединяет обратно.
        // embedAreaId/embedBtnId — на какой экран сейчас нацелено вживление:
        // у рабочего экрана и у конструктора своя рамка и своя кнопка, но
        // вся остальная логика (позиционирование, сторож, пряталка под
        // модалки) общая — переключаем цель, а не дублируем код.
        let audacityEmbedded = false;
        let embedResizeTimer = null;
        let embedAreaId = 'audacityEmbedArea';
        let embedBtnId = 'btnEmbedAudacity';

        function toggleEmbedAudacity() {
            if (audacityEmbedded) {
                detachEmbeddedAudacity();
            } else {
                attachEmbeddedAudacity();
            }
        }

        // Окно Windows живёт в «настоящих» точках экрана, а вёрстка — в своих,
        // и при масштабе экрана 125/150% это разные числа. Без пересчёта окно
        // Audacity садилось мимо рамки и обрезалось.
        function embedAreaRect() {
            const area = document.getElementById(embedAreaId);
            if (!area) return null;
            const r = area.getBoundingClientRect();
            const k = window.devicePixelRatio || 1;
            return {
                x: Math.round(r.left * k), y: Math.round(r.top * k),
                w: Math.round(r.width * k), h: Math.round(r.height * k)
            };
        }

        // silent = попытка встроить «между делом» (например, при включении
        // режима «Суммы», когда Audacity может быть ещё не запущен) — тогда
        // не ругаемся окном об ошибке и оставляем пустую рамку под окно.
        async function attachEmbeddedAudacity(silent) {
            const area = document.getElementById(embedAreaId);
            const btn = document.getElementById(embedBtnId);
            area.style.display = 'block';
            const rect = embedAreaRect();

            const result = await pywebview.api.embed_audacity(rect.x, rect.y, rect.w, rect.h);

            if (result && result.error) {
                if (silent) return;
                area.style.display = sumModeActive ? 'block' : (embedAreaId === 'ttsEmbedArea' ? 'flex' : 'none');
                showBeautifulAlert('⚠️ ' + result.error);
                return;
            }

            audacityEmbedded = true;
            lastEmbedRect = null;
            if (btn) btn.innerText = 'Отсоединить Audacity';
            window.addEventListener('resize', onEmbedWindowResize);
            startEmbedWatchdog();
            modalOpenForAudacity = false;
            refreshModalAudacityVisibility();
        }

        // Рамка уезжает не только при изменении размера окна: страницу можно
        // прокрутить, панели над ней — свернуть или развернуть. Событий на всё
        // это нет, поэтому просто раз в полсекунды сверяем, где рамка сейчас,
        // и двигаем окно Audacity, только если она реально сдвинулась.
        let lastEmbedRect = null;
        let embedWatchdogTimer = null;

        function startEmbedWatchdog() {
            stopEmbedWatchdog();
            embedWatchdogTimer = setInterval(async () => {
                if (!audacityEmbedded) { stopEmbedWatchdog(); return; }
                const r = embedAreaRect();
                if (!r) return;
                const same = lastEmbedRect && lastEmbedRect.x === r.x && lastEmbedRect.y === r.y
                          && lastEmbedRect.w === r.w && lastEmbedRect.h === r.h;
                if (same) return;
                lastEmbedRect = r;
                let res = await pywebview.api.sync_embed_position(r.x, r.y, r.w, r.h);
                if (res && res.error) {
                    // Audacity закрыли, пока был встроен — окно пропало,
                    // сторож сам себя останавливает вместо бесконечных ошибок
                    audacityEmbedded = false;
                    stopEmbedWatchdog();
                    let btn = document.getElementById(embedBtnId);
                    if (btn) btn.innerText = ['sumEmbedAudacityBtn', 'ttsEmbedBtn'].includes(embedBtnId) ? 'Прикрепить Audacity' : 'Встроить окно Audacity сюда';
                }
            }, 500);
        }

        function stopEmbedWatchdog() {
            if (embedWatchdogTimer) clearInterval(embedWatchdogTimer);
            embedWatchdogTimer = null;
        }

        // Вживлённое окно Audacity — настоящее окно Windows поверх страницы,
        // а не HTML-элемент: обычный CSS z-index на него не действует, и
        // любое модальное окно софта (алерты, поиск, выбор проекта и т.д.)
        // рисовалось у него ПОД низом. Следим за всеми такими модалками и на
        // время их показа прячем Audacity, возвращая обратно при закрытии.
        let modalOpenForAudacity = false;
        function refreshModalAudacityVisibility() {
            if (!audacityEmbedded) return;
            const anyOpen = Array.from(document.querySelectorAll('.custom-alert-overlay'))
                .some(el => el.style.display && el.style.display !== 'none');
            if (anyOpen === modalOpenForAudacity) return;
            modalOpenForAudacity = anyOpen;
            if (anyOpen) pywebview.api.hide_embedded_audacity();
            else pywebview.api.show_embedded_audacity();
        }

        document.addEventListener('DOMContentLoaded', () => {
            document.querySelectorAll('.custom-alert-overlay').forEach(el => {
                new MutationObserver(refreshModalAudacityVisibility)
                    .observe(el, { attributes: true, attributeFilter: ['style'] });
            });
        });

        // Пометка «что сейчас играет» рядом с текстом: «готовая» (уже
        // сохранённая/проверенная версия), «черновик» (сырой дубль,
        // ещё не сохранён) или «цепочка» (склейка нескольких ярусов
        // «Суммы»). Раньше подсветка при проигрывании была одинаковая для
        // всех случаев (жёлтая), и было не понять, что именно звучит.
        function playSourceLabel(src) {
            if (src === 'saved') return iconHTML('check-circle') + ' Готовая версия';
            if (src === 'chain') return iconHTML('link-2') + ' Цепочка «Суммы»';
            return iconHTML('mic') + ' Черновик (дубль)';
        }
        document.addEventListener('DOMContentLoaded', () => {
            const phraseEl = document.getElementById('phraseText');
            const badge = document.getElementById('playSourceBadge');
            if (!phraseEl || !badge) return;
            const sync = () => {
                // В «Суммах» бейдж над лентой сдвигал всё вниз — там вместо него
                // пульсирует карточка текущего дубля (класс на ленте переживает
                // перерисовку карточек).
                let rail = document.getElementById('sumDubsRail');
                let playing = phraseEl.classList.contains('is-playing');
                if (rail) rail.classList.toggle('is-playing', playing);
                if (document.body.classList.contains('sum-mode')) {
                    badge.className = 'play-source-badge';
                    badge.innerHTML = '';
                    return;
                }
                if (playing && phraseEl.dataset.playSource) {
                    badge.className = 'play-source-badge is-visible src-' + phraseEl.dataset.playSource;
                    badge.innerHTML = playSourceLabel(phraseEl.dataset.playSource);
                } else {
                    badge.className = 'play-source-badge';
                    badge.innerHTML = '';
                }
            };
            new MutationObserver(sync).observe(phraseEl, { attributes: true, attributeFilter: ['class'] });
        });

        async function detachEmbeddedAudacity(minimize) {
            if (!audacityEmbedded) {
                // Даже если окно не было вживлено (или его уже отсоединили) —
                // при уходе в главное меню всё равно сворачиваем, если оно
                // просто открыто отдельно на рабочем столе.
                if (minimize) { try { await pywebview.api.minimize_audacity(); } catch (e) {} }
                return;
            }
            window.removeEventListener('resize', onEmbedWindowResize);
            stopEmbedWatchdog();
            audacityEmbedded = false;
            modalOpenForAudacity = false;
            const area = document.getElementById(embedAreaId);
            const btn = document.getElementById(embedBtnId);
            // В режиме «Суммы» рамка остаётся на экране: место под окно
            // Audacity закреплено за ней, даже когда окно отсоединено.
            if (area) area.style.display = sumModeActive ? 'block' : (embedAreaId === 'ttsEmbedArea' ? 'flex' : 'none');
            if (btn) btn.innerText = ['sumEmbedAudacityBtn', 'ttsEmbedBtn'].includes(embedBtnId) ? 'Прикрепить Audacity' : 'Встроить окно Audacity сюда';
            try {
                // При возврате в главное меню окно не просто отсоединяем
                // (это возвращает его на передний план поверх всего) —
                // сворачиваем, чтобы оно не мешало на рабочем столе.
                if (minimize) await pywebview.api.minimize_audacity();
                else await pywebview.api.unembed_audacity();
            } catch (e) {}
        }

        function onEmbedWindowResize() {
            clearTimeout(embedResizeTimer);
            embedResizeTimer = setTimeout(() => {
                if (!audacityEmbedded) return;
                const r = embedAreaRect();
                if (!r) return;
                lastEmbedRect = r;
                pywebview.api.sync_embed_position(r.x, r.y, r.w, r.h);
            }, 150);
        }

        async function sendToAudacity() {
            if (isProcessing) return;
            isProcessing = true;
            updateProgress(0, 'Отправка файлов в Audacity...');
            document.getElementById('progressContainer').style.display = 'block';

            setTimeout(async () => {
                try {
                    let state = await pywebview.api.send_to_audacity();
                    if (state) updateUI(state);
                } catch (err) {
                    console.error("Ошибка при отправке в Audacity:", err);
                } finally {
                    document.getElementById('progressContainer').style.display = 'none';
                    isProcessing = false;
                }
            }, 50);
        }

        async function playAudio(toggle = false) {
            let res = await pywebview.api.dispatch('play', {toggle: toggle});
            let phraseEl = document.getElementById('phraseText');

            clearTimeout(playTimeout);
            clearSumPlaybackTimers();
            if(res && res.playing) {
                phraseEl.dataset.playSource = res.source || 'draft';
                phraseEl.classList.add('is-playing');
                playTimeout = setTimeout(() => { phraseEl.classList.remove('is-playing'); }, res.duration * 1000);

                // Режим «Суммы»: играем всю цепочку целиком, а текст на экране
                // переключаем в такт — под то, что звучит прямо сейчас.
                if (res.segments && res.segments.length) {
                    const originalText = phraseEl.innerText;
                    res.segments.forEach(seg => {
                        sumPlaybackTimers.push(setTimeout(() => { phraseEl.innerText = seg.label; }, seg.start * 1000));
                    });
                    sumPlaybackTimers.push(setTimeout(() => { phraseEl.innerText = originalText; }, res.duration * 1000));
                }
            } else {
                phraseEl.classList.remove('is-playing');
            }
        }

        let isNavigatingPhrase = false;
        async function navPhrase(dir) {
            if (isNavigatingPhrase) return;
            isNavigatingPhrase = true;
            try {
                let state = await pywebview.api.navigate_phrase(dir);
                updateUI(state);
                resetSilence();

                let phraseEl = document.getElementById('phraseText');
                clearTimeout(playTimeout);
                clearSumPlaybackTimers();
                phraseEl.classList.remove('is-playing');

                if (state.completed_filepath) {
                    let res = await pywebview.api.play_specific_file(state.completed_filepath);
                    if(res && res.playing) {
                        phraseEl.dataset.playSource = res.source || 'saved';
                        phraseEl.classList.add('is-playing');
                        playTimeout = setTimeout(() => { phraseEl.classList.remove('is-playing'); }, res.duration * 1000);
                    }
                } else {
                    await pywebview.api.dispatch('stop');
                }
            } finally {
                isNavigatingPhrase = false;
            }
        }

        let navChunkTimeout = null;
        let isNavigatingChunk = false;
        let isNavigatingCategory = false;

        async function navCategory(dir) {
            if (isNavigatingCategory) return;
            isNavigatingCategory = true;
            try {
                updateProgress(0, 'Смена категории...');
                document.getElementById('progressContainer').style.display = 'block';

                let state = await pywebview.api.navigate_var_category(dir);
                if (state && !state.error) {
                    updateUI(state);
                    // === АВТОПЛЕЙ ПРИ СМЕНЕ КАТЕГОРИИ ===
                    playAudio(false);
                } else if (state && state.error) {
                    showBeautifulAlert(`⚠️ <b>Ошибка</b><br><br>${state.error}`);
                }
            } finally {
                document.getElementById('progressContainer').style.display = 'none';
                isNavigatingCategory = false;
            }
        }

        async function navChunk(dir) {
            // === НОВОВВЕДЕНИЕ: Отдельная логика для режима Переменных (VarBatch) ===
            if (currentState && currentState.mode === 'VarBatch') {
                let state = await pywebview.api.navigate_var_chunk_ui(dir);
                if (state) updateUI(state);

                clearTimeout(navChunkTimeout);

                navChunkTimeout = setTimeout(async () => {
                    updateProgress(0, 'Загрузка дубля...');
                    document.getElementById('progressContainer').style.display = 'block';

                    let finalState = await pywebview.api.sync_var_chunk_audacity();
                    if (finalState) updateUI(finalState);

                    document.getElementById('progressContainer').style.display = 'none';

                    // === АВТОПЛЕЙ ПОСЛЕ ПЕРЕЛИСТЫВАНИЯ ===
                    playAudio(false);
                }, 650);
            }
            else {
                // === СТАРАЯ ЛОГИКА ДЛЯ ОСНОВНОГО РЕЖИМА (Main) ===
                if (isNavigatingChunk) return;
                isNavigatingChunk = true;
                try {
                    updateUI(await pywebview.api.dispatch('navigate', {direction: dir, auto_play: true}));
                    resetSilence();
                    clearTimeout(navChunkTimeout);
                    navChunkTimeout = setTimeout(async () => {
                        let res = await pywebview.api.dispatch('play_sync');
                        let phraseEl = document.getElementById('phraseText');
                        clearTimeout(playTimeout);
                        clearSumPlaybackTimers();
                        if(res && res.playing) {
                            phraseEl.dataset.playSource = res.source || 'draft';
                            phraseEl.classList.add('is-playing');
                            playTimeout = setTimeout(() => { phraseEl.classList.remove('is-playing'); }, res.duration * 1000);
                        } else {
                            phraseEl.classList.remove('is-playing');
                        }
                    }, 300);
                } finally {
                    isNavigatingChunk = false;
                }
            }
        }

        async function processAction(action) {
            if (isProcessing) return; isProcessing = true;
            try {
                let addSil = document.getElementById('addSilence').checked;
                let state = await pywebview.api.dispatch('save', {kind: action, add_silence: addSil});
                if (state) updateUI(state);
                playAudio();
                resetSilence();
            } finally { isProcessing = false; }
        }

        // НОВОВВЕДЕНИЕ: Универсальная логика двойного нажатия с визуальным таймером
        let tapTimers = {};
        function handleDoubleTap(btnId, callbackFunction, originalText) {
            let btn = document.getElementById(btnId);
            if (!btn) return;

            // Поддержка как старых кнопок с <kbd>, так и новых без них
            let kbd = btn.querySelector('kbd');

            if (tapTimers[btnId]) {
                // Сценарий 2: Второе нажатие успело вовремя
                clearTimeout(tapTimers[btnId]);
                delete tapTimers[btnId];

                btn.classList.remove('btn-waiting');
                if (kbd) { kbd.innerText = originalText; } else { btn.innerText = originalText; }

                callbackFunction(); // Выполняем нужное сохранение
            } else {
                // Сценарий 1: Первое нажатие - запускаем таймер
                btn.classList.add('btn-waiting');
                if (kbd) { kbd.innerText = 'Ещё раз!'; } else { btn.innerText = 'Ещё раз!'; }

                tapTimers[btnId] = setTimeout(() => {
                    // Время вышло - возвращаем в исходное состояние
                    delete tapTimers[btnId];
                    btn.classList.remove('btn-waiting');
                    if (kbd) { kbd.innerText = originalText; } else { btn.innerText = originalText; }
                }, 400); // 400 миллисекунд на подтверждение
            }
        }

        // НОВОВВЕДЕНИЕ: Логика двойного нажатия для W (Good)
        let lastWTime = 0;
        function triggerGoodDoubleTap() {
            let now = new Date().getTime();
            if (now - lastWTime < 400) { // 400 миллисекунд на двойной клик
                processAction('good');
                lastWTime = 0;
            } else {
                lastWTime = now;
            }
        }

        // НОВОВВЕДЕНИЕ: Логика двойного нажатия для R (Переменные)
        let lastRTime = 0;
        function triggerVarDoubleTap() {
            let now = new Date().getTime();
            if (now - lastRTime < 400) {
                processAction('variable');
                lastRTime = 0;
            } else {
                lastRTime = now;
            }
        }

        function capitalize(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

        function getVarName(type) {
            if(type === 'date') return "Дата";
            if(type === 'name') return "Имя";
            if(type === 'amount') return "Сумма";
            return "";
        }

        function getVarIcon(type) {
            if(type === 'date') return iconHTML('calendar');
            if(type === 'name') return iconHTML('user');
            if(type === 'amount') return iconHTML('dollar-sign');
            return "";
        }

        async function loadVarFile(varType) {
            let result = await pywebview.api.load_var_file(varType);
            if (result && result.filename) {
                let btnLoad = document.getElementById(`btnVar${capitalize(varType)}Load`);
                let btnMix = document.getElementById(`btnVar${capitalize(varType)}Mix`);

                // Красим кнопку файла, давая понять, что он заряжен
                btnLoad.innerHTML = `${getVarIcon(varType)} ${escapeHtml(getVarName(varType))}: ${escapeHtml(result.filename)}`;
                btnLoad.style.color = 'var(--text)';
                btnLoad.style.borderColor = 'var(--accent-var)';
                btnLoad.style.background = 'var(--tint-var)';

                btnMix.disabled = false;
            }
        }

        async function mixWithVar(varType) {
            let activeParts = mergeParts.filter(p => p !== null);
            if (activeParts.length === 0) {
                showBeautifulAlert("ℹ️ <b>Нечего выгружать</b><br><br>Сначала отметьте фразы на монтажном столе клавишами <b>1</b>, <b>2</b>…");
                return;
            }
            if (isProcessing) return; isProcessing = true;

            // НОВОВВЕДЕНИЕ: Считываем состояние галочки
            let varAtStart = document.getElementById('varAtStart').checked;
            await pywebview.api.build_scene_with_var(mergeParts, varType, varAtStart);

            isProcessing = false;
        }

        async function saveSeparateParts() {
            let activeParts = mergeParts.filter(p => p !== null);
            if (activeParts.length === 0) {
                showBeautifulAlert("ℹ️ <b>Нет фраз для экспорта</b><br><br>Отметьте их клавишами <b>1</b>, <b>2</b>…");
                return;
            }
            if (isProcessing) return; isProcessing = true;

            let addSil = document.getElementById('addSilence').checked;

            // Получаем ответ от Python с обновленными галочками
            let newState = await pywebview.api.save_separate_parts(mergeParts, addSil);

            // Экран обновляется, а уведомление об успехе или ошибке вызовет сам Python!
            if (newState) {
                updateUI(newState);
            }

            // Очистка слотов монтажного стола
            mergeParts = [null, null, null, null, null];
            saveFilenameForMerge = null;
            for(let i=1; i<=5; i++) {
                document.getElementById(`labelPart${i}`).innerText = "-";
                document.getElementById(`btnPart${i}`).classList.remove('filled');
                document.getElementById(`boxPart${i}`).classList.remove('has-data');
            }
            resetSilence();
            isProcessing = false;
        }

        async function toggleChecked() {
            if (isProcessing) return; isProcessing = true;
            let state = await pywebview.api.toggle_phrase_checked();
            updateUI(state);
            isProcessing = false;
        }

        // НОВОВВЕДЕНИЕ: Таймер для удержания кнопки удаления фразы
        let phraseDeleteTimer = null;
        function startPhraseDeleteHold() {
            let btn = document.getElementById('btnDeletePhrase');
            if(btn) btn.classList.add('holding');

            phraseDeleteTimer = setTimeout(async () => {
                if(btn) {
                    btn.classList.remove('holding');
                    btn.style.opacity = '0';
                    setTimeout(() => btn.style.opacity = '1', 200);
                }
                if (isProcessing) return; isProcessing = true;
                updateUI(await pywebview.api.delete_current_phrase());
                isProcessing = false;
                resetSilence();
            }, 600); // Время удержания крестика (0.6 секунды)
        }

        function stopPhraseDeleteHold() {
            clearTimeout(phraseDeleteTimer);
            let btn = document.getElementById('btnDeletePhrase');
            if(btn) btn.classList.remove('holding');
        }

        function updateUI(state) {
            currentState = state;
            let phraseEl = document.getElementById('phraseText');
            phraseEl.innerText = state.phrase_text;

            let customNameEl = document.getElementById('customFileName');
            customNameEl.innerHTML = state.custom_filename ? `${iconHTML('save')} Сохранится как: <b>${state.custom_filename}</b>` : "";
            customNameEl.dataset.rawname = state.custom_filename || "";

            let excelName = state.custom_filename ? state.custom_filename.replace('.wav', '') : "";
            let matchEl = document.getElementById('nameMatchIndicator');

            if (excelName) {
                if (state.is_done || state.is_var) {
                    // Используем умное имя папки от Python (Проверенные или Переменные)
                    let folderName = state.folder_name || (state.is_done ? "Проверенные" : "Переменные");

                    // Если файл готов (is_done), красим в зеленый, иначе - в желтый
                    let color = (state.is_done) ? "var(--accent-good)" : "var(--accent-var)";

                    let tint = (state.is_done) ? "var(--tint-good)" : "var(--tint-var)";

                    matchEl.innerHTML = `<span style="color: ${color};">Сохранено в «${folderName}»: ${excelName}.wav</span>`;
                    matchEl.style.border = `1px solid ${color}`;
                    matchEl.style.background = tint;
                } else {
                    matchEl.innerHTML = `<span style="color: var(--text-dim);">Ожидает выгрузки: ${excelName}.wav</span>`;
                    matchEl.style.border = "1px solid var(--border)";
                    matchEl.style.background = "var(--panel)";
                }
            } else {
                matchEl.innerHTML = "";
                matchEl.style.border = "none";
                matchEl.style.background = "transparent";
            }

            document.getElementById('phraseCounter').innerText = `Фраза: ${state.phrase_counter}`;
            document.getElementById('chunkName').innerText = state.chunk_name;
            document.getElementById('chunkCounter').innerText = `Дубль: ${state.chunk_counter}`;
            updateChunkTrack(state.chunk_counter);
            renderChunkStrip(state.strip);

            // НОВЫЙ БЛОК: Управление меткой "Проверено"
            let badge = document.getElementById('checkedBadge');
            if (badge) badge.style.display = state.is_checked ? 'inline-block' : 'none';

            let btnCheck = document.getElementById('btnCheckToggle');
            if (btnCheck) {
                if (state.is_checked) {
                    btnCheck.style.color = 'var(--accent-good)';
                    btnCheck.style.borderColor = 'var(--accent-good)';
                    btnCheck.style.background = 'var(--tint-good)';
                } else {
                    btnCheck.style.color = 'var(--text-dim)';
                    btnCheck.style.borderColor = 'var(--border)';
                    btnCheck.style.background = 'var(--panel)';
                }
            }

            phraseEl.classList.toggle('is-done', !!state.is_done);
            // НОВОВВЕДЕНИЕ: Применяем класс желтого свечения, если это переменная
            phraseEl.classList.toggle('is-var', !!state.is_var);

            if (document.getElementById('varMixPanel')) {
                document.getElementById('varMixPanel').style.display = (state.mode === 'Переменные') ? 'block' : 'none';
            }

            if(state.stats) {
                document.getElementById('statTotal').innerText = state.stats.total;
                document.getElementById('statGood').innerText = state.stats.good;
                document.getElementById('statVar').innerText = state.stats.var;

                let checkedEl = document.getElementById('statChecked');
                if (checkedEl) checkedEl.innerText = state.stats.checked || 0;

                let missingEl = document.getElementById('statMissing');
                if (missingEl) {
                    missingEl.innerText = state.stats.total - state.stats.good;
                }

                updateProjectProgress(state.stats);

                if(state.stats.excel_name) {
                    markExcelLoaded(state.stats.excel_name);
                }
                if(state.stats.project_name) {
                    document.getElementById('btnLoadFolder').classList.add('loaded');
                    document.getElementById('descFolder').innerText = state.stats.project_name;
                    document.getElementById('btnLoadAudio').classList.add('loaded');
                    document.getElementById('descAudio').innerText = state.stats.project_name;
                }
            }
            // === АКТИВНАЯ ВКЛАДКА ===
            // Сравниваем с меткой data-mode: раньше сверяли по надписи на кнопке,
            // и любое переименование вкладки ломало подсветку.
            let md = (state.mode || '').toLowerCase();
            document.querySelectorAll('.mode-switch .chip').forEach(btn => {
                btn.classList.toggle('chip-mode--active', (btn.dataset.mode || '') === md);
            });


            if (state.mode === 'VarBatch') {
                document.getElementById('workspaceGrid').classList.add('workspace-grid--varbatch');
                document.getElementById('standardActions').style.display = 'none';
                document.getElementById('varBatchActions').style.display = sumModeActive ? 'none' : 'flex';
                document.getElementById('sumManualActions').style.display = sumModeActive ? 'flex' : 'none';
                // Счётчики по ярусам застывали на значениях первого включения — сюда
                // (в отличие от обычного режима ниже) обновление панели забыли добавить,
                // хотя «Суммы» точно так же работают и внутри конвейера «Переменные».
                if (sumModeActive && state.sum_mode) renderSumPanel(state.sum_mode);
                // Теперь берем правильный текст фразы, а если его нет — название папки
                document.getElementById('phraseText').innerText = state.phrase_text || state.var_batch_cat;
                document.getElementById('chunkName').innerText = state.var_batch_name || "";

                let mergePanel = document.querySelector('.merge-panel');
                if(mergePanel) mergePanel.style.display = 'none';
                let addSil = document.getElementById('addSilence');
                if(addSil && addSil.parentElement) addSil.parentElement.style.display = 'none';

            } else {
                document.getElementById('workspaceGrid').classList.remove('workspace-grid--varbatch');
                document.getElementById('varBatchActions').style.display = 'none';
                applySumModeLayout();
                if (sumModeActive && state.sum_mode) renderSumPanel(state.sum_mode);

                let mergePanel = document.querySelector('.merge-panel');
                if(mergePanel) mergePanel.style.display = sumModeActive ? 'none' : 'block';
                let addSil = document.getElementById('addSilence');
                if(addSil && addSil.parentElement) addSil.parentElement.style.display = sumModeActive ? 'none' : 'flex';
            }
        }

        async function toggleMissingPanel() {
            let grid = document.getElementById('workspaceGrid');
            let panel = document.getElementById('missingPanel');

            if (panel.style.display === 'none') {
                grid.style.display = 'none';
                panel.style.display = 'flex';

                let missingList = await pywebview.api.get_missing_phrases();
                let html = '';
                missingList.forEach(m => {
                    html += `<div class="missing-item" onclick="jumpToMissing(${m.index})">
                                <div class="missing-item-text">${m.text}</div>
                                <div class="missing-item-name">${m.filename}</div>
                             </div>`;
                });

                if(missingList.length === 0) html = '<div class="audit-ok">Все фразы готовы</div>';
                document.getElementById('missingList').innerHTML = html;
            } else {
                panel.style.display = 'none';
                grid.style.display = '';
            }
        }

        async function jumpToMissing(index) {
            updateUI(await pywebview.api.jump_to_phrase(index));
            resetSilence();
            toggleMissingPanel();
        }

        function markPart(partNum) {
            if (!currentState || !currentState.chunk_name) return;

            // БЕРЕМ ТОЧНЫЙ ПУТЬ ДО ФАЙЛА НА ДИСКЕ (из Проверенных, Переменных или сырой папки)
            let exactFilePath = currentState.completed_filepath || currentState.filepath;

            // А для красоты на экране показываем имя
            let rawName = currentState.raw_chunk_name || currentState.chunk_name.replace('.wav', '').replace('.mp3', '');
            let displayName = currentState.custom_filename || rawName;

            let idx = partNum - 1;
            mergeParts[idx] = exactFilePath; // <-- В Python теперь уходит абсолютный путь!

            document.getElementById(`labelPart${partNum}`).innerText = displayName;
            document.getElementById(`btnPart${partNum}`).classList.add('filled');
            document.getElementById(`boxPart${partNum}`).classList.add('has-data');

            if(!saveFilenameForMerge) saveFilenameForMerge = currentState.custom_filename || currentState.chunk_name;
        }

        function clearPart(partNum) {
            let idx = partNum - 1;
            mergeParts[idx] = null;
            document.getElementById(`labelPart${partNum}`).innerText = "-";
            document.getElementById(`btnPart${partNum}`).classList.remove('filled');
            document.getElementById(`boxPart${partNum}`).classList.remove('has-data');

            if (partNum === 1 || mergeParts.every(p => p === null)) {
                saveFilenameForMerge = null;
            }
        }

        async function prepMerge() {
            let activeParts = mergeParts.filter(p => p !== null);

            if (activeParts.length === 0) {
                showBeautifulAlert("ℹ️ <b>Нет частей для монтажа</b><br><br>Отметьте хотя бы одну часть клавишами <b>1</b>, <b>2</b>…");
                return;
            }

            if (isProcessing) return; isProcessing = true;
            await pywebview.api.prep_merge(mergeParts);
            isProcessing = false;
        }

        async function saveMerge() {
            if (!saveFilenameForMerge) { showBeautifulAlert("ℹ️ <b>Нет данных</b><br><br>Сначала выберите части для склейки."); return; }
            if (isProcessing) return; isProcessing = true;
            await pywebview.api.save_merge(saveFilenameForMerge, document.getElementById('addSilence').checked, false);
            showToast("Склейка сохранена в «Проверенные»");

            mergeParts = [null, null, null, null, null];
            saveFilenameForMerge = null;
            for(let i=1; i<=5; i++) {
                document.getElementById(`labelPart${i}`).innerText = "-";
                document.getElementById(`btnPart${i}`).classList.remove('filled');
                document.getElementById(`boxPart${i}`).classList.remove('has-data');
            }
            resetSilence();
            isProcessing = false;
        }

        async function saveMergeVar() {
            if (!saveFilenameForMerge) { showBeautifulAlert("ℹ️ <b>Нет данных</b><br><br>Сначала выберите части для склейки."); return; }
            if (isProcessing) return; isProcessing = true;
            // Передаем true в Python, чтобы файл ушел в папку Переменные
            await pywebview.api.save_merge(saveFilenameForMerge, document.getElementById('addSilence').checked, true);
            showToast("Склейка сохранена в «Переменные»");

            mergeParts = [null, null, null, null, null];
            saveFilenameForMerge = null;
            for(let i=1; i<=5; i++) {
                document.getElementById(`labelPart${i}`).innerText = "-";
                document.getElementById(`btnPart${i}`).classList.remove('filled');
                document.getElementById(`boxPart${i}`).classList.remove('has-data');
            }
            resetSilence();
            isProcessing = false;
        }

        let holdTimers = {};
        let isLongPress = {};
        const HOLD_DURATION = 600;

        function startHold(keyNum, btnId, actionFunc) {
            isLongPress[keyNum] = false;
            let btn = document.getElementById(btnId);
            if(btn) btn.classList.add('holding');

            holdTimers[keyNum] = setTimeout(() => {
                isLongPress[keyNum] = true;
                if(btn) {
                    btn.classList.remove('holding');
                    btn.classList.add('executed');
                    setTimeout(() => btn.classList.remove('executed'), 150);
                }
                actionFunc();
            }, HOLD_DURATION);
        }

        function releaseHold(keyNum, btnId, shortActionFunc) {
            clearTimeout(holdTimers[keyNum]);
            let btn = document.getElementById(btnId);
            if(btn) btn.classList.remove('holding');

            if (!isLongPress[keyNum]) {
                shortActionFunc();
            }
            isLongPress[keyNum] = false;
        }

        // Полный экран — F11 на любом экране программы.
        async function toggleFullscreen() {
            let res = await pywebview.api.toggle_fullscreen();
            if (res && res.error) showToast(res.error);
        }
        document.addEventListener('keydown', e => {
            if (e.code === 'F11') { e.preventDefault(); toggleFullscreen(); }
            if (aEd && (e.ctrlKey || e.metaKey) && document.getElementById('auditEdOverlay').style.display === 'flex') {
                if (e.code === 'KeyZ') { e.preventDefault(); auditEdUndo(); return; }
                if (e.code === 'KeyS') { e.preventDefault(); auditEdSave(); return; }
            }
            // «Сборка» открыта: Ctrl+Z — отменить шаг, Ctrl+Y / Ctrl+Shift+Z — вернуть.
            // По коду клавиши — работает и в русской раскладке (Ctrl+Я).
            if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyZ' || e.code === 'KeyY')
                && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA'
                && document.getElementById('stage4-tts').classList.contains('show-assembly')) {
                e.preventDefault();
                if (e.code === 'KeyY' || e.shiftKey) { if (ttsEd) ttsEdUndo(true); }
                else ttsUndoAny();               // срезка или удалённый дубль — что было последним
            }
            // Экран записи (не «Сборка»): Ctrl+Z — вернуть удалённый дубль.
            else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyZ' && !e.shiftKey && tts && tts.loaded
                && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA'
                && isShown('stage4-tts') && !document.getElementById('stage4-tts').classList.contains('show-assembly')
                && !['ttsVarsOverlay', 'ttsListOverlay', 'ttsMarkOverlay'].some(id => document.getElementById(id).style.display === 'flex')) {
                e.preventDefault();
                ttsUndoDelete();
            }
        });

        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // РАЗРЕШАЕМ СТАНДАРТНЫЕ КОМБИНАЦИИ (Ctrl+C, Ctrl+A, и т.д.)
            if (e.ctrlKey || e.metaKey) return;

            // Правка записи из аудита — окно поверх всего.
            let aEdOv = document.getElementById('auditEdOverlay');
            if (aEdOv && aEdOv.style.display === 'flex' && aEd && !((document.getElementById('customAlertOverlay') || {}).style || {}).display?.includes('flex')) {
                auditEdKey(e);
                return;
            }
            // Разметка живых слов (синтез сумм) — окно поверх всего.
            let mkOverlay = document.getElementById('ttsMarkOverlay'), alertOn = document.getElementById('customAlertOverlay');
            if (mkOverlay && mkOverlay.style.display === 'flex' && ttsMk && !(alertOn && alertOn.style.display === 'flex')) {
                ttsMkKey(e);
                return;
            }

            // На заставке любая из клавиш Enter / Space открывает экран подготовки
            let splash = document.getElementById('stage0-splash');
            if (splash && splash.style.display !== 'none') {
                if (e.code === 'Enter' || e.code === 'Space') {
                    e.preventDefault();
                    enterApp();
                }
                return;
            }

            let alertOverlay = document.getElementById('customAlertOverlay');
            if (alertOverlay && alertOverlay.style.display === 'flex') {
                if (e.code === 'Enter' || e.code === 'Space') {
                    e.preventDefault();
                    closeCustomAlert(true);
                } else if (e.code === 'Escape') {
                    e.preventDefault();
                    closeCustomAlert(false);
                } else {
                    let alt = document.getElementById('customAlertAlt');
                    if (alt && alt.style.display !== 'none' && e.code === alt.dataset.key) { e.preventDefault(); closeCustomAlert('alt'); }
                }
                return;
            }

            let helpOverlay = document.getElementById('menuHelpOverlay');
            if (helpOverlay && helpOverlay.style.display === 'flex') {
                if (e.code === 'Escape' || e.code === 'Enter') { e.preventDefault(); closeMenuHelp(); }
                return;
            }

            // Окно выбора колонок таблицы: Escape закрывает
            let excelOverlay = document.getElementById('excelOverlay');
            if (excelOverlay && excelOverlay.style.display === 'flex') {
                if (e.code === 'Escape') {
                    e.preventDefault();
                    closeExcelPicker();
                }
                return;
            }

            // Окно автоподбора: Escape закрывает, печатать цифры не мешаем
            let tuneOverlay = document.getElementById('autoTuneOverlay');
            if (tuneOverlay && tuneOverlay.style.display === 'flex') {
                if (e.code === 'Escape') {
                    e.preventDefault();
                    closeAutoTune();
                }
                return;
            }

            // Окно ручной настройки: Escape закрывает, остальные клавиши не мешаем
            let manualOverlay = document.getElementById('manualOverlay');
            if (manualOverlay && manualOverlay.style.display === 'flex') {
                if (e.code === 'Escape') {
                    e.preventDefault();
                    closeManualSettings();
                }
                return;
            }

            // Выбор режима после нарезки, выбор start/end и ожидание меток —
            // везде нужен явный клик, без горячих клавиш, чтобы не было
            // случайного выхода куда-то на полпути.
            let modeChoiceOverlay = document.getElementById('modeChoiceOverlay');
            if (modeChoiceOverlay && modeChoiceOverlay.style.display === 'flex') {
                return;
            }
            let startEndMissingOverlay = document.getElementById('startEndMissingOverlay');
            if (startEndMissingOverlay && startEndMissingOverlay.style.display === 'flex') {
                if (e.code === 'Escape') { e.preventDefault(); closeStartEndMissing(); }
                return;
            }
            let waitLabelsOverlay = document.getElementById('waitLabelsOverlay');
            if (waitLabelsOverlay && waitLabelsOverlay.style.display === 'flex') {
                return;
            }

            // Блокируем горячие клавиши программы, если открыт Аудит
            let auditOverlay = document.getElementById('auditOverlay');
            if (auditOverlay && auditOverlay.style.display === 'flex') {
                if (e.code === 'Escape') {
                    e.preventDefault();
                    closeAudit();
                }
                return;
            }

            // TTS-проект: свои клавиши (Space / Enter / стрелки / Del / F).
            if (isShown('stage4-tts')) { ttsHandleKey(e); return; }

            // Конструктор переменных — свой мини-режим со своим плеером:
            // Space играет/останавливает собранную сумму, остальные горячие
            // клавиши основного конвейера здесь не имеют смысла.
            let constructorStage = document.getElementById('stage3-constructor');
            if (constructorStage && constructorStage.style.display !== 'none') {
                if (e.code === 'Space') { e.preventDefault(); constructorTogglePlay(); }
                else if (e.code === 'KeyA' && !e.repeat) { e.preventDefault(); constructorMoveSelection(-1); }
                else if (e.code === 'KeyD' && !e.repeat) { e.preventDefault(); constructorMoveSelection(1); }
                else if (e.code === 'KeyW') { e.preventDefault(); if (!e.repeat) constructorStartHold('KeyW', (animate) => constructorStepSelected(-1, animate)); }
                else if (e.code === 'KeyS') { e.preventDefault(); if (!e.repeat) constructorStartHold('KeyS', (animate) => constructorStepSelected(1, animate)); }
                return;
            }

            if (document.activeElement && (document.activeElement.tagName === 'BUTTON' || document.activeElement.classList.contains('sum-cat__expect'))) document.activeElement.blur();

            if (e.repeat && !['KeyQ', 'KeyE', 'KeyA', 'KeyD'].includes(e.code)) return;

            // «Суммы»: 1…9 — выбрать кусок речи в переменной, где их несколько.
            let digit = /^(Digit|Numpad)([1-9])$/.exec(e.code);
            if (digit && sumModeActive && typeof sumEd !== 'undefined' && sumEditorPieceKey(+digit[2])) {
                e.preventDefault();
                return;
            }

            if (currentState && currentState.mode === 'VarBatch') {
                // Цифры 1-5 — это разметка монтажа в основном режиме, здесь её нет
                if (['Digit1', 'Digit2', 'Digit3', 'Digit4', 'Digit5'].includes(e.code)) {
                    e.preventDefault();
                    showBeautifulAlert('ℹ️ <b>Режим переменных</b><br><br>Здесь эта кнопка отключена. Для сохранения и перехода жмите <b>Z</b>, для навигации аудио — <b>A/D</b>, для навигации текста — <b>Q/E</b>, выгрузить готовое — <b>R</b>.');
                    return;
                }
                if (e.code === 'Escape') {
                    e.preventDefault();
                    showBeautifulAlert('ℹ️ <b>Режим переменных</b><br><br>Чтобы выйти из конвейера, нажмите <b>Главное меню</b> в левом верхнем углу.');
                    return;
                }

                // ВНИМАНИЕ: Здесь Q и E крутят текст, а A и D крутят аудио!
                if (e.code === 'Space') { e.preventDefault(); if (sumModeActive) sumSpace(); else playAudio(true); }
                else if (e.code === 'KeyQ') { e.preventDefault(); navPhrase(-1); }
                else if (e.code === 'KeyE') { e.preventDefault(); navPhrase(1); }
                else if (e.code === 'KeyA') { e.preventDefault(); navChunk(-1); }
                else if (e.code === 'KeyD') { e.preventDefault(); navChunk(1); }
                else if (e.code === 'KeyZ') { e.preventDefault(); if (sumModeActive) sumStage1SendSelected(); else saveVarBatch(false); }
                else if (e.code === 'KeyX' && sumModeActive) { e.preventDefault(); sumStage1Undo(); }
                else if (e.code === 'Delete' && sumModeActive) { e.preventDefault(); if (sumEd.sel) sumEditorCut(); else sumRemoveBrowsed(); }
                else if (e.code === 'KeyP' && sumModeActive) { e.preventDefault(); sumEditorTogglePlay(); }
                else if ((e.code === 'Enter' || e.code === 'NumpadEnter') && sumModeActive) { e.preventDefault(); sumEditorSave(); }
                else if (e.code === 'KeyW') { e.preventDefault(); toggleChecked(); }
                else if (e.code === 'KeyR') { e.preventDefault(); loadCheckedToAudacity(); }
                else if (e.code === 'KeyC') { e.preventDefault(); if (sumModeActive) sumStage2SendToAudacity(); else sendToAudacity(); }
                else if (e.code === 'KeyN' && sumModeActive) { e.preventDefault(); sumFixSplit(); }
                else if (e.code === 'KeyV' && sumModeActive) { e.preventDefault(); sumSendDubToAudacity(); }
                else if (e.code === 'KeyB' && sumModeActive) { e.preventDefault(); sumCollectDubLabels(); }
                else if (e.code === 'ArrowUp' && sumModeActive) { e.preventDefault(); sumStage1MoveSelection(-1); }
                else if (e.code === 'ArrowDown' && sumModeActive) { e.preventDefault(); sumStage1MoveSelection(1); }
                else if (e.code === 'ArrowLeft' && sumModeActive) { e.preventDefault(); sumStage1BrowseMove(-1); }
                else if (e.code === 'ArrowRight' && sumModeActive) { e.preventDefault(); sumStage1BrowseMove(1); }
                return;
            }

            // === СТАНДАРТНАЯ ЛОГИКА ДЛЯ ОСТАЛЬНЫХ РЕЖИМОВ ===
            if (e.code === 'Space') { e.preventDefault(); if (sumModeActive) sumSpace(); else playAudio(true); }
            else if (e.code === 'KeyQ') { e.preventDefault(); navPhrase(-1); }
            else if (e.code === 'KeyE') { e.preventDefault(); navPhrase(1); }
            else if (e.code === 'KeyA') { e.preventDefault(); navChunk(-1); }
            else if (e.code === 'KeyD') { e.preventDefault(); navChunk(1); }
            else if (e.code === 'KeyZ') { e.preventDefault(); if (sumModeActive) sumStage1SendSelected(); else processAction('good'); }
            else if (e.code === 'KeyX' && sumModeActive) { e.preventDefault(); sumStage1Undo(); }
            else if (e.code === 'Delete' && sumModeActive) { e.preventDefault(); if (sumEd.sel) sumEditorCut(); else sumRemoveBrowsed(); }
            else if (e.code === 'KeyP' && sumModeActive) { e.preventDefault(); sumEditorTogglePlay(); }
            else if ((e.code === 'Enter' || e.code === 'NumpadEnter') && sumModeActive) { e.preventDefault(); sumEditorSave(); }
            else if (e.code === 'KeyC') { e.preventDefault(); if (sumModeActive) sumStage2SendToAudacity(); else processAction('variable'); }
            else if (e.code === 'KeyN' && sumModeActive) { e.preventDefault(); sumFixSplit(); }
            else if (e.code === 'KeyV' && sumModeActive) { e.preventDefault(); sumSendDubToAudacity(); }
            else if (e.code === 'KeyB' && sumModeActive) { e.preventDefault(); sumCollectDubLabels(); }
            else if (e.code === 'ArrowUp' && sumModeActive) { e.preventDefault(); sumStage1MoveSelection(-1); }
            else if (e.code === 'ArrowDown' && sumModeActive) { e.preventDefault(); sumStage1MoveSelection(1); }
            else if (e.code === 'ArrowLeft' && sumModeActive) { e.preventDefault(); sumStage1BrowseMove(-1); }
            else if (e.code === 'ArrowRight' && sumModeActive) { e.preventDefault(); sumStage1BrowseMove(1); }
            else if (e.code === 'Escape') { e.preventDefault(); loadMainMode(); }
            else if (e.code === 'KeyF') { e.preventDefault(); openSearch(); }
            else if (e.code === 'KeyW') { e.preventDefault(); toggleChecked(); }
            else if (e.code === 'KeyS') {
                e.preventDefault();
                let chk = document.getElementById('addSilence');
                chk.checked = !chk.checked;
            }
            else if (e.code === 'Digit1') { e.preventDefault(); startHold(1, 'btnPrepMerge', prepMerge); }
            else if (e.code === 'Digit2') { e.preventDefault(); handleDoubleTap('btnSaveMerge', saveMerge, '2. В проверенные'); }
            else if (e.code === 'Digit3') { e.preventDefault(); handleDoubleTap('btnSaveMergeVar', saveMergeVar, '3. В переменные'); }
            else if (e.code === 'Digit4') { e.preventDefault(); markPart(4); }
            else if (e.code === 'Digit5') { e.preventDefault(); markPart(5); }
        });

        document.addEventListener('keyup', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // НОВОВВЕДЕНИЕ: Отключаем отпускание кнопок при открытом Аудите
            let auditOverlay = document.getElementById('auditOverlay');
            if (auditOverlay && auditOverlay.style.display === 'flex') return;

            if (e.code === 'Digit1') { releaseHold(1, 'btnPrepMerge', () => markPart(1)); }
            else if (e.code === 'Digit2') { releaseHold(2, 'btnSaveMerge', () => markPart(2)); }
            if (e.code === 'Digit3') { releaseHold(3, 'btnSaveMergeVar', () => markPart(3)); }

            if (e.code === 'KeyW' || e.code === 'KeyS') { constructorStopHold(e.code); }
        });

        window.alert = function(message) {
            let el = document.getElementById('customAlertText');
            if(el) {
                el.innerText = message;
                document.getElementById('customAlertOverlay').style.display = 'flex';
            }
        };

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

        function copyRawText(text) {
            if (!text) return;
            navigator.clipboard.writeText(text);
            showToast("Скопировано: " + text);
        }

        function showToast(msg, duration) {
            let { icon, text } = extractLeadingIcon(msg);
            let toast = document.createElement('div');
            toast.className = 'toast';
            toast.innerHTML = `${iconHTML(icon)}<span>${escapeHtml(text)}</span>`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), duration || 2200);
        }

        // === Конвертер MP4 -> MP3/WAV ===
        // ----- Подготовка к клону -----
        let cloneSt = { folder: null, json: null, clones: 0 };
        function openClonePrep() {
            document.getElementById('cloneOverlay').style.display = 'flex';
            cloneRefresh();
        }
        function closeClonePrep() { document.getElementById('cloneOverlay').style.display = 'none'; }
        function cloneRefresh() {
            document.getElementById('btnCloneBuild').disabled = !cloneSt.folder;
            document.getElementById('btnCloneCut').disabled = !(cloneSt.json && cloneSt.clones);
        }
        const cloneDur = s => s >= 60 ? `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с` : `${s} с`;
        async function clonePickFolder() {
            let r = await pywebview.api.clone_pick_folder();
            if (!r) return;
            cloneSt.folder = r.count ? r.folder : null;
            document.getElementById('cloneFolderLabel').innerText = r.count
                ? `${r.folder} — файлов: ${r.count}${r.subdirs ? `, подпапок: ${r.subdirs}` : ''}` : `${r.folder} — аудиофайлов нет`;
            if (r.prev) {                                   // уже собирали — тайминги подхватим
                let j = await pywebview.api.clone_load_json(r.prev);
                if (j && !j.error) cloneSetJson(j, 'прошлая сборка этой папки');
            }
            cloneRefresh();
        }
        function cloneSetJson(j, note) {
            cloneSt.json = j.json;
            document.getElementById('cloneJsonLabel').innerText = `${note ? note + ': ' : ''}${j.count} файлов, ${cloneDur(j.total_s)}`;
            cloneRefresh();
        }
        async function cloneBuild() {
            let btn = document.getElementById('btnCloneBuild'), out = document.getElementById('cloneBuildResult');
            btn.disabled = true; btn.innerText = 'Собираю…'; out.innerHTML = '';
            try {
                let r = await pywebview.api.clone_build(+document.querySelector('input[name="cloneGap"]:checked').value,
                                                        +document.querySelector('input[name="cloneRate"]:checked').value);
                if (!r || r.error) { out.innerHTML = `<span class="clone-bad">${escapeHtml(r && r.error || 'Не получилось')}</span>`; return; }
                out.innerHTML = `Готово: <b>${escapeHtml(r.wav)}</b><br>${r.count} файлов · ${cloneDur(r.total_s)} · ${r.rate} Гц · тайминги — «Клон_исходник.json» рядом
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="pywebview.api.clone_open_folder(${escapeHtml(JSON.stringify(r.wav.replace(/[\\/][^\\/]*$/, '')))})">Открыть папку</button>`
                    + (r.errors && r.errors.length ? `<div class="clone-bad">Не прочитались: ${r.errors.map(escapeHtml).join('; ')}</div>` : '');
                cloneSetJson({ json: r.json, count: r.count, total_s: r.total_s }, 'из шага 1');
            } finally { btn.innerText = 'Собрать WAV'; cloneRefresh(); }
        }
        async function clonePickJson() {
            let j = await pywebview.api.clone_pick_json();
            if (!j) return;
            if (j.error) { showToast(j.error); return; }
            cloneSetJson(j, '');
        }
        async function clonePickClones() {
            let r = await pywebview.api.clone_pick_clones();
            if (!r) return;
            cloneSt.clones = r.clones.length;
            document.getElementById('cloneClonesLabel').innerText = r.clones.join(', ');
            cloneRefresh();
        }
        async function cloneCut() {
            let btn = document.getElementById('btnCloneCut'), out = document.getElementById('cloneCutResult');
            btn.disabled = true; btn.innerText = 'Режу…'; out.innerHTML = '';
            try {
                let r = await pywebview.api.clone_cut(document.querySelector('input[name="cloneOutRate"]:checked').value);
                if (!r || r.error) { out.innerHTML = `<span class="clone-bad">${escapeHtml(r && r.error || 'Не получилось')}</span>`; return; }
                out.innerHTML = r.report.map(c => c.error ? `<div class="clone-bad">${escapeHtml(c.clone)}: ${escapeHtml(c.error)}</div>`
                    : `<div class="clone-row"><b>${escapeHtml(c.clone)}</b> — файлов: ${c.files}
                        <span class="tts-dim">· сдвиг ${c.offset_ms} мс${c.scale !== 1 ? ` · растяжение ${((c.scale - 1) * 100).toFixed(2)}%` : ''}${c.fix_max_ms ? ` · подравнено до ${c.fix_max_ms} мс` : ''}</span>
                        <button type="button" class="btn-ghost btn-ghost--compact" onclick="pywebview.api.clone_open_folder(${escapeHtml(JSON.stringify(c.folder))})">Открыть</button>
                        ${c.warnings.length ? `<div class="clone-bad">${c.warnings.map(escapeHtml).join('<br>')}</div>` : ''}</div>`).join('');
            } finally { btn.innerText = 'Нарезать'; cloneRefresh(); }
        }

        function openConverter() {
            document.getElementById('convertSourceLabel').innerText = 'Файлы не выбраны';
            document.getElementById('convertOutputLabel').innerText = 'Папка не выбрана';
            document.getElementById('converterOverlay').style.display = 'flex';
        }

        function closeConverter() {
            document.getElementById('converterOverlay').style.display = 'none';
        }

        async function pickConvertSource() {
            let result = await pywebview.api.pick_convert_source();
            let label = document.getElementById('convertSourceLabel');
            if (!result || !result.count) {
                label.innerText = 'Файлы не выбраны';
                return;
            }
            label.innerText = result.count === 1 ? result.files[0] : `Выбрано файлов: ${result.count}`;
        }

        async function pickConvertOutputDir() {
            let result = await pywebview.api.pick_convert_output_dir();
            let label = document.getElementById('convertOutputLabel');
            label.innerText = (result && result.path) ? result.path : 'Папка не выбрана';
        }

        let lastConvertedFiles = [];

        async function runConversion() {
            let btn = document.getElementById('btnRunConvert');
            let format = document.querySelector('input[name="convertFormat"]:checked').value;
            let hz = document.querySelector('input[name="convertHz"]:checked').value;

            btn.disabled = true;
            btn.innerText = 'Конвертирую...';
            try {
                let result = await pywebview.api.run_conversion(format, hz);
                if (result && result.error) {
                    showBeautifulAlert('⚠️ ' + result.error);
                    return;
                }
                let msg = `${iconHTML('check-circle')} Готово: ${result.done} из ${result.total}`;
                if (result.errors && result.errors.length) {
                    msg += `<br><br>Не удалось (${result.errors.length}):<br>` + result.errors.map(escapeHtml).join('<br>');
                }

                lastConvertedFiles = result.output_files || [];
                closeConverter();

                if (lastConvertedFiles.length) {
                    document.getElementById('postConvertText').innerHTML = msg;
                    document.getElementById('postConvertOverlay').style.display = 'flex';
                } else {
                    showBeautifulAlert(msg);
                }
            } finally {
                btn.disabled = false;
                btn.innerText = 'Конвертировать';
            }
        }

        // === «Сопоставить названия по Excel»: короткое имя файла (da_1_1)
        // ищем как конец полного из Excel (gizat_ru_da_1_1), переименовываем
        // и раскладываем по языкам ru/kz/Прочее ===
        function openRenameMatch() {
            document.getElementById('renameMatchFolderLabel').innerText = 'Папка не выбрана';
            document.getElementById('renameMatchExcelLabel').innerText = 'Файл не выбран';
            document.getElementById('renameMatchResult').style.display = 'none';
            document.getElementById('renameMatchLangRu').checked = false;
            document.getElementById('renameMatchLangKz').checked = false;
            document.getElementById('renameMatchOverlay').style.display = 'flex';
        }

        function closeRenameMatch() {
            document.getElementById('renameMatchOverlay').style.display = 'none';
        }

        async function pickRenameMatchFolder() {
            let result = await pywebview.api.rename_match_pick_folder();
            let label = document.getElementById('renameMatchFolderLabel');
            if (!result || result.error) {
                if (!result || result.error !== 'cancel') label.innerText = (result && result.error) || 'Папка не выбрана';
                return;
            }
            label.innerText = `${result.folder} — файлов: ${result.count}`;
        }

        async function pickRenameMatchExcel() {
            let result = await pywebview.api.rename_match_pick_excel();
            let label = document.getElementById('renameMatchExcelLabel');
            if (!result || result.error) {
                if (!result || result.error !== 'cancel') label.innerText = (result && result.error) || 'Файл не выбран';
                return;
            }
            label.innerText = `${result.file} — названий: ${result.count}`;
        }

        async function runRenameMatch() {
            let btn = document.getElementById('btnRunRenameMatch');
            let langs = [];
            if (document.getElementById('renameMatchLangRu').checked) langs.push('ru');
            if (document.getElementById('renameMatchLangKz').checked) langs.push('kz');

            btn.disabled = true;
            btn.innerText = 'Сопоставляю...';
            let result;
            try {
                result = await pywebview.api.rename_match_run(langs);
            } finally {
                btn.disabled = false;
                btn.innerText = 'Сопоставить и разложить';
            }

            if (!result || result.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${(result && result.error) || 'Неизвестная ошибка'}`);
                return;
            }

            let parts = [`${iconHTML('check-circle')} Переименовано и разложено: <b>${result.renamed_count}</b>`];
            if (result.unmatched_count) {
                parts.push(`<div style="margin-top:10px">${iconHTML('alert-triangle')} Не нашлось пары в Excel (${result.unmatched_count}):<br>` +
                    result.unmatched.map(u => `${escapeHtml(u.file)} — ${escapeHtml(u.detail)}`).join('<br>') + `</div>`);
            }
            if (result.ambiguous_count) {
                parts.push(`<div style="margin-top:10px">${iconHTML('alert-triangle')} Неоднозначно, оставлено как есть (${result.ambiguous_count}):<br>` +
                    result.ambiguous.map(a => `${escapeHtml(a.file)} — ${escapeHtml(a.reason)}`).join('<br>') + `</div>`);
            }
            parts.push(`<button class="custom-alert-btn" style="margin-top:14px; width:100%;" onclick="exportRenameMatchReport()">${iconHTML('file-text')} Экспортировать полный отчёт в Excel</button>`);

            let box = document.getElementById('renameMatchResult');
            box.innerHTML = parts.join('');
            box.style.display = 'block';
        }

        async function exportRenameMatchReport() {
            let result = await pywebview.api.rename_match_export_report();
            if (!result || result.error) {
                if (!result || result.error !== 'cancel') {
                    showBeautifulAlert(`<b>Ошибка</b><br><br>${(result && result.error) || 'Неизвестная ошибка'}`);
                }
                return;
            }
            showToast(`Отчёт сохранён: ${result.path}`);
        }

        // === «Таблица → PowerPoint»: построчный экспорт Excel в слайды ===
        // РУ, КАЗ и TR таблицы загружаются и хранятся отдельно (разный
        // порядок/набор колонок) — тумблер только переключает, какую из
        // них показывает и собирает интерфейс, сам выбор файла и результат
        // экспорта остаются каждый при своём языке.
        let tablePptxLang = 'ru';
        let tablePptxState = { ru: null, kz: null, tr: null };

        function openTablePptx() {
            tablePptxLang = 'ru';
            tablePptxState = { ru: null, kz: null, tr: null };
            document.getElementById('tablePptxResult').style.display = 'none';
            renderTablePptxLangUI();
            document.getElementById('tablePptxOverlay').style.display = 'flex';
        }

        function closeTablePptx() {
            document.getElementById('tablePptxOverlay').style.display = 'none';
        }

        function setTablePptxLang(lang) {
            tablePptxLang = lang;
            renderTablePptxLangUI();
        }

        function renderTablePptxLangUI() {
            let ruBtn = document.getElementById('tablePptxLangRuBtn');
            let kzBtn = document.getElementById('tablePptxLangKzBtn');
            let trBtn = document.getElementById('tablePptxLangTrBtn');
            if (ruBtn) ruBtn.classList.toggle('btn-tile--solid-mode', tablePptxLang === 'ru');
            if (kzBtn) kzBtn.classList.toggle('btn-tile--solid-mode', tablePptxLang === 'kz');
            if (trBtn) trBtn.classList.toggle('btn-tile--solid-mode', tablePptxLang === 'tr');

            let label = document.getElementById('tablePptxExcelLabel');
            let info = document.getElementById('tablePptxInfo');
            let btn = document.getElementById('btnRunTablePptx');
            let result = tablePptxState[tablePptxLang];

            if (!result) {
                label.innerText = 'Файл не выбран';
                info.style.display = 'none';
                btn.disabled = true;
                return;
            }
            label.innerText = `${result.file}${result.sheet ? ' · лист «' + result.sheet + '»' : ''} — строк: ${result.rows}`;
            let bits = [`Колонок в таблице: <b>${result.columns.length}</b> (${result.columns.map(escapeHtml).join(', ')})`];
            bits.push(result.brand_pair
                ? `${iconHTML('check-circle')} Марка+транскрипция найдены: «${escapeHtml(result.brand_pair[0])}» над «${escapeHtml(result.brand_pair[1])}» — пойдут одним блоком`
                : `${iconHTML('alert-triangle')} Колонки «марка»/«транскрипция» не найдены — все колонки лягут отдельными блоками`);
            if (result.sum_columns && result.sum_columns.length) {
                bits.push(`${iconHTML('check-circle')} Колонки-суммы: ${result.sum_columns.map(escapeHtml).join(', ')}`);
            }
            bits.push(result.logic2_available
                ? `${iconHTML('check-circle')} Строка с пометкой «ноль» («0 tl» / «sıfır tl» / «ноль тенге») покажется как есть, а после неё пойдут слайды «Миллионы (первое значение) + Сотни тысяч (каждое значение колонки, до конца) + Тенге (первое значение)»`
                : `${iconHTML('alert-triangle')} Переключения не будет — в таблице не нашлась строка с пометкой «ноль» («0 tl» / «sıfır tl» / «ноль тенге»), либо колонка «Сотни тысяч» вообще пустая`);
            if (result.ignored_columns && result.ignored_columns.length) {
                bits.push(`${iconHTML('alert-triangle')} Без заголовка — не показываются на слайдах: ${result.ignored_columns.map(escapeHtml).join(', ')}`);
            }
            info.innerHTML = bits.join('<br>');
            info.style.display = 'block';
            btn.disabled = false;
        }

        function renderTablePptxSheetChoice(result) {
            let label = document.getElementById('tablePptxExcelLabel');
            let info = document.getElementById('tablePptxInfo');
            let btn = document.getElementById('btnRunTablePptx');
            label.innerText = `${result.file} — выберите лист`;
            btn.disabled = true;

            info.innerHTML = '';
            let intro = document.createElement('div');
            intro.innerText = 'В файле несколько листов — выберите, какой анализировать:';
            info.appendChild(intro);

            let row = document.createElement('div');
            row.style.marginTop = 'var(--space-2)';
            result.sheets.forEach(name => {
                let b = document.createElement('button');
                b.className = 'custom-alert-btn';
                b.style.margin = '4px 6px 0 0';
                b.innerText = name;
                b.onclick = () => chooseTablePptxSheet(result.lang, name);
                row.appendChild(b);
            });
            info.appendChild(row);
            info.style.display = 'block';
        }

        async function chooseTablePptxSheet(lang, sheetName) {
            let result = await pywebview.api.table_pptx_pick_sheet(lang, sheetName);
            if (!result || result.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${(result && result.error) || 'Неизвестная ошибка'}`);
                return;
            }
            tablePptxState[lang] = result;
            renderTablePptxLangUI();
        }

        async function pickTablePptxExcel() {
            let result = await pywebview.api.table_pptx_pick_excel(tablePptxLang);
            if (!result || result.error) {
                if (!result || result.error !== 'cancel') {
                    showBeautifulAlert(`<b>Ошибка</b><br><br>${(result && result.error) || 'Неизвестная ошибка'}`);
                }
                return;
            }
            if (result.status === 'choose_sheet') {
                renderTablePptxSheetChoice(result);
                return;
            }
            tablePptxState[tablePptxLang] = result;
            renderTablePptxLangUI();
        }

        async function runTablePptxExport() {
            let btn = document.getElementById('btnRunTablePptx');
            btn.disabled = true;
            btn.innerText = 'Собираю...';
            let result;
            try {
                result = await pywebview.api.table_pptx_export(tablePptxLang);
            } finally {
                btn.disabled = false;
                btn.innerText = 'Собрать презентацию';
            }

            if (!result || result.error) {
                if (!result || result.error !== 'cancel') {
                    showBeautifulAlert(`<b>Ошибка</b><br><br>${(result && result.error) || 'Неизвестная ошибка'}`);
                }
                return;
            }

            let box = document.getElementById('tablePptxResult');
            box.innerHTML = `${iconHTML('check-circle')} Готово — слайдов: <b>${result.slides}</b><br>${escapeHtml(result.path)}`;
            box.style.display = 'block';
            showToast(`Презентация сохранена: ${result.path}`);
        }

        // --- Ненавязчивая подсказка "что дальше" после конвертации ---
        function closePostConvert() {
            document.getElementById('postConvertOverlay').style.display = 'none';
        }

        async function startCutFromConverted() {
            let path = lastConvertedFiles[0];
            closePostConvert();
            if (!path) return;

            let picked = await pywebview.api.select_raw_audio_path(path);
            if (!picked || picked.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${picked ? picked.error : 'Файл не найден'}`);
                return;
            }

            showMenu();
            updateProgress(30, `Анализ записи: ${picked.name}`);
            let res;
            try {
                res = await pywebview.api.analyze_picked_audio();
            } catch (e) {
                document.getElementById('progressContainer').style.display = 'none';
                showBeautifulAlert(`❌ <b>Не удалось проанализировать запись</b><br><br>${e}`);
                return;
            }
            document.getElementById('progressContainer').style.display = 'none';

            if (!res || res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${String(res && res.error || 'Пустой ответ').replace(/\n/g, '<br>')}`);
                return;
            }

            nudgeExcelAfterCut = true;
            openAutoTune(res);
        }

        // --- Ненавязчивая подсказка загрузить Excel после нарезки ---
        // Срабатывает только для нарезки, начатой из конвертера, и только
        // один раз — чтобы не надоедать при обычной работе.
        let nudgeExcelAfterCut = false;

        function closePostCutExcel() {
            document.getElementById('postCutExcelOverlay').style.display = 'none';
        }

        function maybeNudgeExcelAfterCut() {
            if (!nudgeExcelAfterCut) return;
            nudgeExcelAfterCut = false;
            if (excelIsLoaded) return;
            document.getElementById('postCutExcelOverlay').style.display = 'flex';
        }

        // === НОВОВВЕДЕНИЕ: Логика системы поиска ===
        function openSearch() {
            let totalChunks = currentState?.chunk_counter ? currentState.chunk_counter.split(' / ')[1] : 0;
            document.getElementById('searchMaxChunk').innerText = totalChunks;
            document.getElementById('searchOverlay').style.display = 'flex';

            let searchInp = document.getElementById('searchText');
            searchInp.focus();
            searchInp.select(); // Выделяем старый текст, чтобы можно было сразу писать новый
        }

        function closeSearch() {
            document.getElementById('searchOverlay').style.display = 'none';
            // Мы НЕ стираем searchText, чтобы можно было легко искать следующее совпадение
            document.getElementById('searchChunkNum').value = '';
        }

        // Новая функция поиска по тексту
        async function doSearchText() {
            let val = document.getElementById('searchText').value;
            if (val.trim() !== "") {
                let state = await pywebview.api.search_phrase(val);
                updateUI(state);
                resetSilence();
                closeSearch();

                // Проигрываем файл, если он уже выгружен (как при навигации Q/E)
                let phraseEl = document.getElementById('phraseText');
                clearTimeout(playTimeout);
                clearSumPlaybackTimers();
                phraseEl.classList.remove('is-playing');
                if (state.completed_filepath) {
                    let res = await pywebview.api.play_specific_file(state.completed_filepath);
                    if(res && res.playing) {
                        phraseEl.dataset.playSource = res.source || 'saved';
                        phraseEl.classList.add('is-playing');
                        playTimeout = setTimeout(() => { phraseEl.classList.remove('is-playing'); }, res.duration * 1000);
                    }
                } else {
                    await pywebview.api.dispatch('stop');
                }
            }
        }

        async function doSearchChunk() {
            let val = parseInt(document.getElementById('searchChunkNum').value);
            if (val > 0) {
                updateUI(await pywebview.api.dispatch('jump', {index: val - 1}));
                resetSilence();
                closeSearch();

                // Проигрываем выбранный дубль, как при нажатии A/D
                let res = await pywebview.api.dispatch('play_sync');
                let phraseEl = document.getElementById('phraseText');
                clearTimeout(playTimeout);
                clearSumPlaybackTimers();
                if(res && res.playing) {
                    phraseEl.dataset.playSource = res.source || 'draft';
                    phraseEl.classList.add('is-playing');
                    playTimeout = setTimeout(() => { phraseEl.classList.remove('is-playing'); }, res.duration * 1000);
                } else {
                    phraseEl.classList.remove('is-playing');
                }
            }
        }

        function closeAudit() {
            document.getElementById('auditOverlay').style.display = 'none';
            pywebview.api.audit_play_stop();
        }

        function closeAuditCategoryPicker() {
            document.getElementById('auditCategoryOverlay').style.display = 'none';
        }

        function renderAuditCategoryChoice(res) {
            let list = document.getElementById('auditCategoryList');
            list.innerHTML = '';

            const addOption = (key, label) => {
                let btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'audit-category-item';
                btn.textContent = label;
                btn.onclick = () => {
                    closeAuditCategoryPicker();
                    askAuditChunks(key, key === 'excel' ? 'Текст из Excel' : label);
                };
                list.appendChild(btn);
            };

            if (res.has_excel) addOption('excel', 'Список дублей из Excel (Шаг 1)');
            res.categories.forEach(c => addOption(c.key, c.label));

            document.getElementById('auditCategoryOverlay').style.display = 'flex';
        }

        // Перед аудитом категории: чанки уже готовы или запись ещё не нарезана?
        let auditChunksCategory = null;
        function askAuditChunks(key, label) {
            auditChunksCategory = key;
            document.getElementById('auditChunksTitle').textContent = `Аудит: ${label}. Есть уже готовые чанки?`;
            document.getElementById('auditChunksOverlay').style.display = 'flex';
        }
        function closeAuditChunks() {
            document.getElementById('auditChunksOverlay').style.display = 'none';
        }
        function auditChunksAnswer(kind) {
            closeAuditChunks();
            let key = auditChunksCategory;
            if (!key) return;
            if (kind === 'named') runProjectAudit(key);
            else runAuditVoice(key, kind === 'cut' ? 'cut' : 'folder');
        }

        // Аудит по голосу: нарезать (если нужно), распознать, сверить с таблицей.
        async function runAuditVoice(category, source) {
            if (isProcessing) return; isProcessing = true;
            auditAsrProgress({ stage: 'pick', done: 0, total: 0 });
            let res;
            try { res = await pywebview.api.audit_recognize(category, source); }
            catch (e) { res = { error: String(e) }; }
            finally { isProcessing = false; document.getElementById('auditAsrOverlay').style.display = 'none'; }
            if (res && res.error === 'cancel') return;
            if (res && res.need_model) { document.getElementById('asrModelOverlay').style.display = 'flex'; return; }
            if (!res || res.error) { showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${escapeHtml(res ? res.error : 'нет ответа')}`); return; }
            renderAuditResult(res);
        }
        function auditAsrProgress(p) {
            let box = document.getElementById('auditAsrOverlay');
            box.style.display = 'flex';
            let text = { pick: 'Выберите запись или папку с чанками…', model: 'Загружаю модель распознавания…',
                         cut: `Нарезаю запись: ${p.done} из ${p.total}`,
                         asr: `Распознаю чанки: ${p.done} из ${p.total}` }[p.stage] || '';
            document.getElementById('auditAsrText').textContent = text;
            document.getElementById('auditAsrBar').value = p.total ? Math.round(p.done / p.total * 100) : 0;
        }
        async function stopAuditVoice() {
            document.getElementById('auditAsrText').textContent = 'Останавливаю… покажу то, что успели распознать';
            try { await pywebview.api.sum_auto_check_stop(); } catch (e) {}
        }

        // Функция плавной анимации цифр
        function animateValue(obj, start, end, duration) {
            let startTimestamp = null;
            const step = (timestamp) => {
                if (!startTimestamp) startTimestamp = timestamp;
                const progress = Math.min((timestamp - startTimestamp) / duration, 1);
                // Эффект замедления к концу
                const easeProgress = 1 - Math.pow(1 - progress, 3);
                obj.innerHTML = Math.floor(easeProgress * (end - start) + start);
                if (progress < 1) {
                    window.requestAnimationFrame(step);
                }
            };
            window.requestAnimationFrame(step);
        }

        async function runProjectAudit(category) {
            if (isProcessing) return; isProcessing = true;

            // Вызываем Python-сканер. Без категории — если загружен словарь
            // переменных, сперва вернётся запрос выбрать категорию (ниже),
            // иначе сразу откроется окно выбора папки.
            let res = await pywebview.api.audit_project_files(category);
            isProcessing = false;

            if (res && res.error === "cancel") return; // Юзер закрыл окно выбора
            if (res && res.status === "choose_category") {
                renderAuditCategoryChoice(res);
                return;
            }
            if (res && res.status === "choose_chunks") {
                askAuditChunks(res.category, res.label);
                return;
            }
            if (!res || res.error) {
                let msg = res?.error || '';
                if (!msg || /Сначала загрузите Excel/i.test(msg)) {
                    // Не «загрузите», а сразу предлагаем загрузить — и продолжаем аудит.
                    let go = await showBeautifulConfirm('ℹ️ <b>Нужна таблица</b><br><br>Чтобы найти недостающие записи, выберите Excel-таблицу — '
                        + 'после загрузки аудит продолжится сам.', 'Загрузить таблицу', 'Отмена');
                    if (go) { pendingAuditAfterExcel = true; loadExcel(); }
                } else {
                    showBeautifulAlert(`❌ <b>Ошибка аудита</b><br><br>${escapeHtml(msg)}`);
                }
                return;
            }
            renderAuditResult(res);
        }

        function renderAuditResult(res, quiet) {
            // Показываем красивое модальное окно
            window.auditRes = res;
            let voice = !!res.by_voice;
            let unknown = res.unknown || [];
            let categoryNote = res.category ? ` — категория «${res.category_label}»` : '';
            if (voice) categoryNote += ` — по голосу, чанков: ${res.chunks_total}${res.stopped ? ' (остановлено, проверены не все)' : ''}`;
            document.getElementById('auditOverlay').style.display = 'flex';
            document.getElementById('auditPath').innerHTML = iconHTML('folder') + (voice ? " Чанки: " : " Директория сканирования: ") + escapeHtml(res.scan_dir) + escapeHtml(categoryNote);
            document.querySelector('#auditOverlay .stat-card--total .stat-card__label').textContent =
                res.category ? 'Всего в словаре' : 'Всего в Excel';
            document.querySelector('#auditOverlay .stat-card--found .stat-card__label').textContent = voice ? 'Услышано' : 'Найдено';
            document.querySelector('#auditOverlay .stat-card--lost .stat-card__label').textContent = voice ? 'Не хватает' : 'Потеряно';
            document.querySelector('#auditOverlay .stat-card--dups .stat-card__label').textContent = voice ? 'Не распознано' : 'Дубликаты';

            // Запускаем анимацию счетчиков (на 1200 миллисекунд); после правки текста — сразу числа
            let counts = [['auditTotalExcel', res.total_excel], ['auditTotalDisk', res.total_disk],
                          ['auditMissing', res.missing_count], ['auditDups', voice ? unknown.length : res.duplicates_count]];
            counts.forEach(([id, v]) => quiet ? (document.getElementById(id).innerHTML = v) : animateValue(document.getElementById(id), 0, v, 1200));

            // Генерируем детальные списки и чистый текст для копирования
            let detailsHtml = '';
            window.lastAuditReportText = `ОТЧЁТ АУДИТА ПРОЕКТА${categoryNote}\nДиректория: ${res.scan_dir}\n`;
            window.lastAuditReportText += `База: ${res.total_excel} | Найдено: ${res.total_disk} | Потеряно: ${res.missing_count} | Дубликаты: ${res.duplicates_count}\n\n`;

            // Блок отсутствующих файлов
            if (res.missing_count > 0) {
                detailsHtml += `<h4 class="audit-group-title audit-group-title--lost">Отсутствуют — ${res.missing_count}</h4>`;
                window.lastAuditReportText += `ОТСУТСТВУЮТ (${res.missing_count}):\n`;

                res.missing.forEach(m => {
                    detailsHtml += voice ? `
                    <div class="audit-row">
                        <span class="audit-row__name audit-row__name--lost">${escapeHtml(m.text)}</span>
                        <div class="audit-row__meta">Строка ${m.index}: не услышано ни в одном чанке</div>
                    </div>` : `
                    <div class="audit-row">
                        <span class="audit-row__name audit-row__name--lost">${escapeHtml(m.filename)}</span>
                        <div class="audit-row__meta">Строка ${m.index}: ${escapeHtml(m.phrase || m.text)}</div>
                    </div>`;
                    window.lastAuditReportText += `- ${m.filename} (Строка ${m.index}: ${m.text})\n`;
                });
                window.lastAuditReportText += `\n`;
            } else {
                detailsHtml += `<div class="audit-ok">Все файлы по списку Excel на месте</div>`;
            }

            // По голосу: чанки, где речь есть, но марку уверенно не узнали —
            // их стоит послушать: возможно, там как раз «недостающее».
            if (voice) {
                if (unknown.length) {
                    detailsHtml += `<h4 class="audit-group-title audit-group-title--dups">Не распознано уверенно — ${unknown.length} (послушайте)</h4>`;
                    window.lastAuditReportText += `НЕ РАСПОЗНАНО (${unknown.length}):\n`;
                    unknown.forEach(u => {
                        detailsHtml += `
                        <div class="audit-row">
                            <span class="audit-row__name audit-row__name--dups">${escapeHtml(u.filename)}</span>
                            <div class="audit-row__meta">Услышано: «${escapeHtml(u.heard)}» · похоже на ${escapeHtml(u.guess)} (${Math.round(u.score * 100)}%)</div>
                        </div>`;
                        window.lastAuditReportText += `- ${u.filename}: «${u.heard}» ~ ${u.guess} (${Math.round(u.score * 100)}%)\n`;
                    });
                }
                auditSetDetails(detailsHtml + auditFilesHTML(res), quiet);
                document.getElementById('auditExportBtn').style.display = res.can_export ? '' : 'none';
                return;
            }

            // Блок дубликатов
            if (res.duplicates_count > 0) {
                detailsHtml += `<h4 class="audit-group-title audit-group-title--dups">Дубликаты — ${res.duplicates_count}</h4>`;
                window.lastAuditReportText += `ДУБЛИКАТЫ (${res.duplicates_count}):\n`;

                res.duplicates.forEach(d => {
                    detailsHtml += `
                    <div class="audit-row">
                        <span class="audit-row__name audit-row__name--dups">${d.filename}</span> — найдено ${d.count} шт.
                        <div class="audit-row__meta">${d.paths.join('<br>')}</div>
                    </div>`;
                    window.lastAuditReportText += `- ${d.filename} (Найдено: ${d.count} шт.)\n`;
                });
            } else {
                detailsHtml += `<div class="audit-ok">Дубликатов не обнаружено</div>`;
            }

            auditSetDetails(auditFilesHTML(res) + detailsHtml, quiet);
            document.getElementById('auditExportBtn').style.display = res.can_export ? '' : 'none';
        }

        // ----- Записи в аудите: послушать и поправить текст -----
        let auditFilter = '';
        function auditSetDetails(html, quiet) {
            let box = document.getElementById('auditDetails');
            let top = quiet ? box.scrollTop : 0;
            let focus = quiet && document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.k : null;
            box.innerHTML = html;
            if (quiet) box.scrollTop = top;
            if (focus) { let el = box.querySelector(`.audit-file__text[data-k="${focus}"]`); if (el) el.focus(); }
            box.querySelectorAll('.audit-file__phrase').forEach(t => { t.style.height = 'auto'; t.style.height = t.scrollHeight + 'px'; });
            auditApplyFilter();
        }
        function auditFilesHTML(res) {
            let files = res.files || [];
            if (!files.length) return '';
            let voice = !!res.by_voice;
            let editable = voice || (!res.category && res.can_edit);
            let rows = files.map((f, k) => {
                let badge = voice
                    ? (f.match ? `<span class="audit-file__badge is-ok" title="Совпало со значением таблицы">✓ ${escapeHtml(f.match)}</span>`
                               : f.text ? `<span class="audit-file__badge" title="Не совпало ни с одним значением уверенно">? ${escapeHtml(f.guess || '')}</span>`
                                        : '<span class="audit-file__badge">тишина</span>')
                    : '';
                let note = voice && f.fixed ? `<div class="audit-file__heard">распознано: «${escapeHtml(f.heard || '—')}» · исправлено вами</div>` : '';
                if (voice && f.phrase) note += `<div class="audit-file__heard">фраза: «${escapeHtml(f.phrase)}»</div>`;
                // по названиям: текст фразы из таблицы (по названию файла) — видно и правится в своей ячейке
                if (!voice && f.phrase) return `<div class="audit-file" data-q="${escapeHtml((f.filename + ' ' + f.phrase).toLowerCase())}">
                    <span class="audit-file__btns"><button type="button" class="audit-file__play" data-k="${k}" onclick="auditPlay(${k})" title="Прослушать (ещё раз — стоп)">&#9654;</button><button type="button" class="audit-file__play" onclick="auditEdOpen(${k})" title="Править запись: срезать края, вырезать лишнее">&#9986;</button></span>
                    <span class="audit-file__name" title="${escapeHtml(f.path)}">${escapeHtml(f.filename)}</span>
                    <textarea class="audit-file__text audit-file__phrase" data-k="${k}" rows="1" title="Текст фразы — исправленный запишется в ту же ячейку таблицы Excel"
                        onkeydown="if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.blur(); } if (event.key === 'Escape') { this.value = this.defaultValue; this.blur(); }"
                        oninput="this.style.height = 'auto'; this.style.height = this.scrollHeight + 'px'"
                        onchange="auditPhraseFix(${k}, this.value)">${escapeHtml(f.phrase)}</textarea>
                    <span></span>
                </div>`;
                return `<div class="audit-file" data-q="${escapeHtml((f.filename + ' ' + (f.text || '') + ' ' + (f.match || '')).toLowerCase())}">
                    <span class="audit-file__btns"><button type="button" class="audit-file__play" data-k="${k}" onclick="auditPlay(${k})" title="Прослушать (ещё раз — стоп)">&#9654;</button><button type="button" class="audit-file__play" onclick="auditEdOpen(${k})" title="Править запись: срезать края, вырезать лишнее">&#9986;</button></span>
                    <span class="audit-file__name" title="${escapeHtml(f.path)}">${escapeHtml(f.filename)}</span>
                    ${editable
                        ? `<input class="audit-file__text" data-k="${k}" value="${escapeHtml(f.text || '')}" placeholder="${voice ? 'что сказано — впишите' : 'текст фразы'}"
                             onkeydown="if (event.key === 'Enter') this.blur(); if (event.key === 'Escape') { this.value = this.defaultValue; this.blur(); }"
                             onchange="auditFix(${k}, this.value)" title="${voice ? 'Исправьте, если распознано неверно — сверка пересчитается' : 'Исправленный текст запишется в таблицу Excel'}">`
                        : `<span class="audit-file__text is-ro">${escapeHtml(f.text || '')}</span>`}
                    ${badge}${note}
                </div>`;
            }).join('');
            return `<h4 class="audit-group-title">Записи — ${files.length}
                    <input class="audit-files__filter" placeholder="найти по названию или тексту" value="${escapeHtml(auditFilter)}" oninput="auditFilter = this.value; auditApplyFilter()"></h4>
                <div class="tts-dim audit-files__hint">${voice
                    ? '▶ — послушать. Распознано неверно — исправьте текст и нажмите Enter: сверка с таблицей пересчитается, правка запомнится в папке чанков.'
                    : editable ? '▶ — послушать. Текст фразы можно исправить — он запишется в таблицу Excel (перед первой правкой сохраню её копию «… .до_правок»).'
                               : '▶ — послушать запись.'}</div>
                <div class="audit-files">${rows}</div>`;
        }
        function auditApplyFilter() {
            let q = auditFilter.trim().toLowerCase();
            document.querySelectorAll('#auditDetails .audit-file').forEach(el => el.style.display = !q || el.dataset.q.includes(q) ? '' : 'none');
        }
        let auditPlayTimer = null;
        async function auditPlay(k) {
            let f = (window.auditRes.files || [])[k];
            if (!f) return;
            let btns = document.querySelectorAll('.audit-file__play');
            let was = document.querySelector(`.audit-file__play[data-k="${k}"]`);
            let replay = was && was.classList.contains('is-playing');
            btns.forEach(b => { b.classList.remove('is-playing'); b.innerHTML = '&#9654;'; });
            clearTimeout(auditPlayTimer);
            let r = await pywebview.api.audit_play(f.path);
            if (!r || r.error) { if (r && r.error) showToast(r.error); return; }
            if (!r.playing || replay) return;
            if (was) { was.classList.add('is-playing'); was.innerHTML = '&#9632;'; }
            auditPlayTimer = setTimeout(() => { if (was) { was.classList.remove('is-playing'); was.innerHTML = '&#9654;'; } }, r.duration * 1000 + 100);
        }
        // ----- правка записи прямо из аудита -----
        // Правка = какие куски исходника оставить; сохраняется байт в байт,
        // исходник лежит в «_до_правок/» рядом — его можно вернуть.
        let aEd = null;
        async function auditEdOpen(k) {
            let f = (window.auditRes.files || [])[k];
            if (!f) return;
            await pywebview.api.audit_play_stop();
            let r = await pywebview.api.audit_edit_load(f.path);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            aEd = { ...r, k, sel: null, cur: 0, head: null, hist: [], saved: JSON.stringify(r.ranges) };
            document.getElementById('auditEdTitle').textContent = 'Правка записи — ' + r.name;
            document.getElementById('auditEdOverlay').style.display = 'flex';
            document.getElementById('auditEdCanvas').onmousedown = auditEdDown;
            auditEdRender();
        }
        const aEdLen = () => aEd.ranges.reduce((s, [a, b]) => s + b - a, 0);
        const aEdDirty = () => aEd && JSON.stringify(aEd.ranges) !== aEd.saved;
        async function auditEdClose(force) {
            if (!aEd) return;
            if (!force && aEdDirty() && !(await showBeautifulConfirm('Правка не сохранена. Закрыть без сохранения?', 'Закрыть', 'Остаться'))) return;
            auditEdStop();
            pywebview.api.audit_play_stop();
            document.getElementById('auditEdOverlay').style.display = 'none';
            aEd = null;
        }
        function auditEdDraw() {
            let cv = document.getElementById('auditEdCanvas'), dpr = window.devicePixelRatio || 1;
            let w = cv.clientWidth, h = cv.clientHeight;
            if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
            let g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
            let L = aEdLen() || 1, x = ms => ms / L * w, mid = h / 2;
            let css = getComputedStyle(document.documentElement);
            g.fillStyle = css.getPropertyValue('--text-dim').trim() || '#999';
            let pos = 0, joins = [];
            aEd.ranges.forEach(([a, b]) => {
                for (let t = a; t < b; t += aEd.bucket) {
                    let p = aEd.peaks[Math.floor(t / aEd.bucket)] || 0, y = Math.max(1, p * (mid - 10));
                    g.fillRect(x(pos + t - a), mid - y, Math.max(1, w * aEd.bucket / L), y * 2);
                }
                pos += b - a; joins.push(pos);
            });
            g.fillStyle = 'rgba(239,91,80,.8)';
            joins.slice(0, -1).forEach(j => g.fillRect(x(j) - 1, 0, 2, h));        // места склеек
            if (aEd.sel) { g.fillStyle = 'rgba(90,150,255,.32)'; g.fillRect(x(aEd.sel.a), 0, x(aEd.sel.b) - x(aEd.sel.a), h); }
            g.fillStyle = '#5a96ff'; g.fillRect(x(aEd.cur) - 1, 0, 2, h);
            if (aEd.head !== null) { g.fillStyle = css.getPropertyValue('--accent-primary').trim() || '#f5a623'; g.fillRect(x(aEd.head), 0, 2, h); }
        }
        function auditEdRender() {
            let L = aEdLen(), sel = aEd.sel ? Math.round(aEd.sel.b - aEd.sel.a) : 0;
            document.getElementById('auditEdBar').innerHTML = `
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdPlay(false)">&#9654; С места <kbd>Space</kbd></button>
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdPlay(true)" ${aEd.sel ? '' : 'disabled'}>&#9654; Выделенное</button>
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdCut()" ${aEd.sel ? '' : 'disabled'} title="Убрать выделенное">Вырезать <kbd>Del</kbd></button>
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdKeep()" ${aEd.sel ? '' : 'disabled'} title="Срезать всё до и после выделенного">Оставить выделенное</button>
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdUndo()" ${aEd.hist.length ? '' : 'disabled'}>&#8630; <kbd>Ctrl+Z</kbd></button>
                <button class="btn-ghost btn-ghost--compact" onclick="auditEdReset()" title="Вернуть всю исходную запись (до сохранения — можно отменить)">Как было</button>
                <span class="tts-dim">${(L / 1000).toFixed(2)} с${sel ? ` · выделено ${sel} мс` : ''}${aEd.has_backup ? ' · исходник в «_до_правок»' : ''}</span>
                <span class="tts-ed__spacer"></span>
                ${aEd.has_backup ? '<button class="btn-ghost btn-ghost--compact" onclick="auditEdRestore()" title="Записать обратно исходную запись (до всех правок)">Вернуть исходник</button>' : ''}
                <button class="custom-alert-btn" onclick="auditEdSave()" ${aEdDirty() ? '' : 'disabled'}>Сохранить <kbd>Ctrl+S</kbd></button>`;
            auditEdDraw();
        }
        function auditEdDown(e) {
            let cv = e.currentTarget, r = cv.getBoundingClientRect(), L = aEdLen();
            let toMs = cx => Math.max(0, Math.min(L, (cx - r.left) / cv.clientWidth * L));
            let start = toMs(e.clientX), moved = false;
            let move = ev => {
                if (!moved && Math.abs(ev.clientX - e.clientX) < 3) return;
                moved = true;
                let t = toMs(ev.clientX);
                aEd.sel = { a: Math.min(start, t), b: Math.max(start, t) };
                auditEdDraw();
            };
            let up = () => {
                window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
                if (!moved) { aEd.sel = null; aEd.cur = start; }
                else aEd.cur = aEd.sel.a;
                auditEdRender();
            };
            window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
        }
        // вырезать [s, e] дорожки (в мс после правок) → новые куски исходника
        function aEdRemove(s, e) {
            let out = [], pos = 0;
            aEd.ranges.forEach(([a, b]) => {
                let p0 = pos, p1 = pos + b - a;
                if (e <= p0 || s >= p1) out.push([a, b]);
                else {
                    if (s > p0) out.push([a, a + (s - p0)]);
                    if (e < p1) out.push([a + (e - p0), b]);
                }
                pos = p1;
            });
            return out.filter(([a, b]) => b - a >= 5).map(([a, b]) => [Math.round(a), Math.round(b)]);
        }
        function auditEdPush() { aEd.hist.push(JSON.stringify(aEd.ranges)); if (aEd.hist.length > 100) aEd.hist.shift(); }
        function auditEdCut() {
            if (!aEd.sel) return;
            let n = aEdRemove(aEd.sel.a, aEd.sel.b);
            if (!n.length) { showToast('Нельзя вырезать всё'); return; }
            auditEdPush(); aEd.ranges = n; aEd.cur = aEd.sel.a; aEd.sel = null; auditEdRender();
        }
        function auditEdKeep() {
            if (!aEd.sel) return;
            let L = aEdLen(), s = aEd.sel;
            auditEdPush();
            aEd.ranges = aEdRemove(s.b, L);
            aEd.ranges = aEdRemove(0, s.a);
            aEd.sel = null; aEd.cur = 0; auditEdRender();
        }
        function auditEdUndo() { if (!aEd.hist.length) return; aEd.ranges = JSON.parse(aEd.hist.pop()); aEd.sel = null; aEd.cur = 0; auditEdRender(); }
        function auditEdReset() { auditEdPush(); aEd.ranges = [[0, aEd.dur]]; aEd.sel = null; aEd.cur = 0; auditEdRender(); }
        let aEdTimer = null;
        function auditEdStop() { if (aEdTimer) cancelAnimationFrame(aEdTimer); aEdTimer = null; if (aEd) { aEd.head = null; auditEdDraw(); } }
        async function auditEdPlay(sel) {
            if (aEd.head !== null) { auditEdStop(); pywebview.api.audit_play_stop(); return; }
            let from = sel && aEd.sel ? aEd.sel.a : aEd.cur, to = sel && aEd.sel ? aEd.sel.b : null;
            let r = await pywebview.api.audit_edit_play(aEd.path, aEd.ranges, from, to);
            if (!r || r.error) { if (r) showToast(r.error); return; }
            let t0 = performance.now(), d = r.duration * 1000;
            let step = () => {
                if (!aEd) return;
                let t = performance.now() - t0;
                if (t > d) { auditEdStop(); return; }
                aEd.head = from + t; auditEdDraw(); aEdTimer = requestAnimationFrame(step);
            };
            aEdTimer = requestAnimationFrame(step);
        }
        async function auditEdSave() {
            if (!aEdDirty()) return;
            auditEdStop();
            let r = await pywebview.api.audit_edit_save(aEd.path, aEd.ranges);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            aEd.saved = JSON.stringify(aEd.ranges); aEd.has_backup = true;
            auditEdRender();
            showToast(`Сохранено: ${aEd.name} (${(r.ms / 1000).toFixed(2)} с). Исходник — в «_до_правок»`);
        }
        async function auditEdRestore() {
            if (!(await showBeautifulConfirm(`Вернуть исходную запись «${escapeHtml(aEd.name)}»? Все правки этой записи пропадут.`, 'Вернуть', 'Отмена'))) return;
            auditEdStop();
            let r = await pywebview.api.audit_edit_restore(aEd.path);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            aEd = { ...aEd, ...r, sel: null, cur: 0, hist: [], saved: JSON.stringify(r.ranges) };
            auditEdRender();
            showToast('Исходная запись возвращена');
        }
        function auditEdKey(e) {
            if (e.code === 'Escape') { e.preventDefault(); auditEdClose(); return; }
            if (e.code === 'Space') { e.preventDefault(); auditEdPlay(false); return; }
            if (e.code === 'Delete' || e.code === 'Backspace' || e.code === 'KeyX') { e.preventDefault(); auditEdCut(); return; }
        }

        async function auditPhraseFix(k, text) {
            let f = (window.auditRes.files || [])[k];
            if (!f) return;
            let r = await pywebview.api.audit_phrase_fix(f.filename, text);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            f.phrase = r.text;
            showToast('Текст фразы исправлен и записан в таблицу');
        }
        async function auditFix(k, text) {
            let res = window.auditRes, f = (res.files || [])[k];
            if (!f) return;
            if (res.by_voice) {
                let r = await pywebview.api.audit_voice_fix(f.filename, text);
                if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
                renderAuditResult(r, true);
                let nf = r.files[k];
                showToast(nf && nf.match ? `«${f.filename}» → ${nf.match}` : 'Правка сохранена');
            } else {
                let r = await pywebview.api.audit_text_fix(f.i, text);
                if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
                f.text = r.text;
                showToast(r.excel_saved ? 'Текст исправлен и записан в таблицу' : 'Текст исправлен в программе');
            }
        }

        // Таблица в формате словаря, только с недостающими строками.
        async function exportAuditMissing() {
            let res;
            try { res = await pywebview.api.audit_export_missing(); } catch (e) { res = { error: String(e) }; }
            if (!res || res.error) {
                if (res && res.error !== 'cancel') showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${escapeHtml(res.error)}`);
                return;
            }
            showBeautifulAlert(`✅ <b>Таблица недостающих сохранена</b><br><br>Строк: <b>${res.rows}</b><br><span style="word-break:break-all">${escapeHtml(res.saved)}</span><br><br>Загрузите её как таблицу-словарь — и в работе будут только недостающие значения.`);
        }

        // НОВОВВЕДЕНИЕ: Функция копирования отчета
        function copyAuditReport() {
            if (window.lastAuditReportText) {
                navigator.clipboard.writeText(window.lastAuditReportText);
                showToast("Отчет аудита скопирован в буфер обмена!");
            }
        }

        // ==================================================================
        //  КОНСТРУКТОР ПЕРЕМЕННЫХ («Суммы») — рулетки с физикой прокрутки.
        //  Не завязан на очередь Excel/дублей: пользователь листает уже
        //  сохранённые значения по каждому ярусу и вручную собирает любую
        //  комбинацию — послушать целиком или отправить в Audacity на
        //  точечную правку.
        // ==================================================================

        // Пятый ярус «Сотни тысяч» (100-900 тыс.) — для сумм за миллион,
        // когда старые «Сотни (100-900)» и «Тысячи (1-99 тыс.)» упёрлись в
        // потолок. Порядок и имена ярусов совпадают с SUM_TIER_ORDER в
        // core/variables_handler.py — держите их в паре, если меняете одно.
        const CONSTRUCTOR_TIER_ORDER = ['millions', 'hundred_thousands', 'hundreds', 'thousands', 'tenge'];
        // У каждого яруса — свой акцентный цвет (уже есть в общей палитре
        // софта), чтобы рулетки визуально отличались друг от друга, а не
        // сливались в одинаковые серые колонки.
        const CONSTRUCTOR_TIER_ACCENT = {
            millions: 'var(--accent-var)', hundred_thousands: 'var(--accent-mode)', hundreds: 'var(--accent-primary)',
            thousands: 'var(--accent-good)', tenge: 'var(--accent-info)'
        };
        // Файлы с голыми цифрами («70.wav», «500.wav») читаются на рулетке и
        // в превью тоже голыми цифрами — а должны звучать как «70 миллионов»,
        // «500», «20 тысяч», «50 тенге» (у «Сотен» единица не нужна, число
        // само по себе понятно). Если слово единицы уже есть в названии файла
        // («1 миллион.wav») — трогать не нужно, просто показываем как есть.
        const CONSTRUCTOR_TIER_UNIT_KEYWORDS = {
            millions: ['миллион', 'млн'], hundred_thousands: ['тысяч', 'тыс'],
            thousands: ['тысяч', 'тыс'], tenge: ['тенге', 'kzt', '₸'],
        };
        const CONSTRUCTOR_TIER_UNIT_FORMS = {
            millions: ['миллион', 'миллиона', 'миллионов'],
            hundred_thousands: ['тысяча', 'тысячи', 'тысяч'],
            thousands: ['тысяча', 'тысячи', 'тысяч'],
        };
        function ruPluralForm(n, forms) {
            let n100 = Math.abs(n) % 100, n10 = n100 % 10;
            if (n100 > 10 && n100 < 20) return forms[2];
            if (n10 === 1) return forms[0];
            if (n10 >= 2 && n10 <= 4) return forms[1];
            return forms[2];
        }
        function humanizeTierItem(tier, raw) {
            if (tier === 'hundreds' || !raw) return raw;
            let keywords = CONSTRUCTOR_TIER_UNIT_KEYWORDS[tier] || [];
            if (keywords.some(k => raw.toLowerCase().includes(k))) return raw;
            let m = raw.match(/\d+/);
            if (!m) return raw;
            if (tier === 'tenge') return `${raw} тенге`;
            let forms = CONSTRUCTOR_TIER_UNIT_FORMS[tier];
            return forms ? `${raw} ${ruPluralForm(parseInt(m[0], 10), forms)}` : raw;
        }

        let constructorState = null;
        let constructorReelInstances = {};

        class Reel {
            constructor(container, items, itemHeight, onChange) {
                this.container = container;
                this.track = container.querySelector('.reel-track');
                this.items = items;
                this.itemHeight = itemHeight;
                this.onChange = onChange;
                // Открываем рулетку сразу на первом (самом маленьком) значении
                // — «1 миллион», «100», «1 тысяча» и т.д., а не с середины списка.
                this.index = 0;
                this.offset = -this.index * this.itemHeight;
                this.velocity = 0;
                this.dragging = false;
                this.lastY = 0;
                this.lastT = 0;
                this.rafId = null;
                this._snapTimer = null;
                this._onChangeRaf = null;
                this._render();
                this._bind();
            }
            _render() {
                this.track.innerHTML = this.items.map(t => `<div class="reel-item">${escapeHtml(t)}</div>`).join('');
                this._applyOffset();
            }
            _applyOffset() {
                this.track.style.transform = `translateY(${this.offset}px)`;
                this._markActive();
                this._scheduleOnChange();
            }
            // На быстрой передаче W/S дёргает шаг чаще, чем раз в кадр —
            // без объединения вызовов onChange (перерисовка строки
            // предпросмотра) пересобирался бы на каждый шаг, а не на
            // каждый кадр экрана, и всё вместе подтормаживало.
            _scheduleOnChange() {
                if (!this.onChange || this._onChangeRaf) return;
                this._onChangeRaf = requestAnimationFrame(() => {
                    this._onChangeRaf = null;
                    this.onChange();
                });
            }
            _markActive() {
                // Подсвечиваем крупным цветным текстом ровно то значение,
                // что сейчас под индикатором — живьём, на каждый пиксель
                // прокрутки, а не только когда рулетка окончательно встала.
                if (this._activeEl) this._activeEl.classList.remove('reel-item--active');
                if (!this.items.length) { this._activeEl = null; return; }
                const idx = this.getIndex();
                this._activeEl = this.track.children[idx] || null;
                if (this._activeEl) this._activeEl.classList.add('reel-item--active');
            }
            _clampOffset(v) {
                if (!this.items.length) return 0;
                const min = -(this.items.length - 1) * this.itemHeight;
                return Math.min(0, Math.max(min, v));
            }
            _bind() {
                if (!this.items.length) return;
                const pointY = (e) => (e.touches ? e.touches[0].clientY : e.clientY);
                const onDown = (e) => {
                    this.dragging = true;
                    cancelAnimationFrame(this.rafId);
                    this.lastY = pointY(e);
                    this.lastT = performance.now();
                    this.velocity = 0;
                    e.preventDefault();
                };
                const onMove = (e) => {
                    if (!this.dragging) return;
                    const y = pointY(e);
                    const dy = y - this.lastY;
                    const now = performance.now();
                    const dt = Math.max(1, now - this.lastT);
                    this.velocity = dy / dt;
                    this.offset = this._clampOffset(this.offset + dy);
                    this._applyOffset();
                    this.lastY = y;
                    this.lastT = now;
                };
                const onUp = () => {
                    if (!this.dragging) return;
                    this.dragging = false;
                    this._momentum();
                };
                this.container.addEventListener('mousedown', onDown);
                window.addEventListener('mousemove', onMove);
                window.addEventListener('mouseup', onUp);
                this.container.addEventListener('touchstart', onDown, { passive: false });
                this.container.addEventListener('touchmove', onMove, { passive: false });
                this.container.addEventListener('touchend', onUp);
                this.container.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    cancelAnimationFrame(this.rafId);
                    this.offset = this._clampOffset(this.offset - e.deltaY * 0.6);
                    this._applyOffset();
                    clearTimeout(this._snapTimer);
                    this._snapTimer = setTimeout(() => this._snap(), 120);
                }, { passive: false });
            }
            _momentum() {
                const friction = 0.94;
                const step = () => {
                    if (Math.abs(this.velocity) < 0.02) { this._snap(); return; }
                    this.velocity *= friction;
                    this.offset = this._clampOffset(this.offset + this.velocity * 16);
                    this._applyOffset();
                    this.rafId = requestAnimationFrame(step);
                };
                this.rafId = requestAnimationFrame(step);
            }
            _snap() {
                if (!this.items.length) return;
                const idx = Math.round(-this.offset / this.itemHeight);
                const clamped = Math.min(this.items.length - 1, Math.max(0, idx));
                this._animateTo(-clamped * this.itemHeight, clamped);
            }
            // Программный шаг на delta позиций (клавиатура W/S) — та же
            // плавная анимация прилипания, что и у обычной прокрутки.
            // animate=false — мгновенный прыжок без 220мс плавной анимации.
            // На быстрой передаче удержания W/S шаги идут чаще, чем сама
            // анимация успевает доиграть — каждый новый шаг обрывал
            // предыдущую на середине, отчего прокрутка визуально дёргалась
            // и «тормозила» вместо того, чтобы ускоряться. Плавную анимацию
            // оставляем только для одиночного нажатия.
            step(delta, animate = true) {
                if (!this.items.length) return;
                const idx = this.getIndex();
                const clamped = Math.min(this.items.length - 1, Math.max(0, idx + delta));
                if (animate) {
                    this._animateTo(-clamped * this.itemHeight, clamped);
                } else {
                    cancelAnimationFrame(this.rafId);
                    this.offset = -clamped * this.itemHeight;
                    this.index = clamped;
                    this._applyOffset();
                }
            }
            _animateTo(target, newIndex) {
                cancelAnimationFrame(this.rafId);
                const start = this.offset;
                const startT = performance.now();
                const dur = 220;
                const step = (now) => {
                    const t = Math.min(1, (now - startT) / dur);
                    const eased = 1 - Math.pow(1 - t, 3);
                    this.offset = start + (target - start) * eased;
                    this._applyOffset();
                    if (t < 1) {
                        this.rafId = requestAnimationFrame(step);
                    } else {
                        this.index = newIndex;
                    }
                };
                this.rafId = requestAnimationFrame(step);
            }
            getIndex() {
                // Считаем прямо по текущему положению на экране, а не по
                // закэшированному this.index — тот обновлялся только когда
                // анимация прилипания к ближайшему пункту полностью
                // доигрывала до конца. Если нажать «Играть» посреди
                // прокрутки/анимации, значение всегда должно быть то, что
                // видно на экране прямо сейчас, а не то, что стояло секунду
                // назад.
                if (!this.items.length) return -1;
                const idx = Math.round(-this.offset / this.itemHeight);
                return Math.min(this.items.length - 1, Math.max(0, idx));
            }
        }

        async function startConstructor() {
            let confirmed1 = await showBeautifulAlert('<b>Загрузите папку, где лежат суммы</b><br><br>Ту же папку «Суммы», где лежат подпапки ярусов.');
            if (!confirmed1) return;
            let state = await pywebview.api.constructor_pick_sum_folder();
            if (state && state.error === 'cancel') return;
            if (!state || state.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${state && state.error ? state.error : 'Неизвестная ошибка'}`);
                return;
            }
            constructorState = state;

            let confirmed2 = await showBeautifulAlert('<b>Теперь start</b><br><br>Выберите файл начальной фразы (start.wav).');
            if (!confirmed2) return;
            let startRes = await pywebview.api.constructor_pick_start();
            if (startRes && startRes.error === 'cancel') return;
            if (startRes && !startRes.error) constructorState = startRes;

            document.getElementById('constructorEndOverlay').style.display = 'flex';
        }

        async function openConstructorFromSumMode() {
            // Режим «Суммы» уже знает папку, старт и энд — конструктору не
            // нужно спрашивать их заново диалогами, как при заходе из
            // главного меню.
            let state = await pywebview.api.constructor_open_from_sum_mode();
            if (state && state.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            constructorState = state;
            openConstructorScreen();
        }

        async function constructorPickEnd() {
            document.getElementById('constructorEndOverlay').style.display = 'none';
            let res = await pywebview.api.constructor_pick_end();
            if (res && !res.error) constructorState = res;
            openConstructorScreen();
        }

        function constructorSkipEnd() {
            document.getElementById('constructorEndOverlay').style.display = 'none';
            openConstructorScreen();
        }

        function openConstructorScreen() {
            embedAreaId = 'constructorEmbedArea';
            embedBtnId = 'constructorEmbedBtn';
            constructorBigMode = false;
            showStage('stage3-constructor');
            renderConstructorMeta();
            renderConstructorLangRow();
            renderConstructorReels();
        }

        // RU/KZ: папка «Суммы» может содержать сразу обе версии — подпапки
        // «Суммы RU» и «Суммы KZ», каждая со своими 5 ярусами. Кнопки
        // видны только когда constructor_pick_sum_folder() реально нашёл
        // обе (или хотя бы вторую) — если папка старого формата (без
        // RU/KZ), тумблер просто прячем, он там не нужен.
        function renderConstructorLangRow() {
            let row = document.getElementById('constructorLangRow');
            if (!row) return;
            let available = (constructorState && constructorState.lang_available) || [];
            row.style.display = available.length > 1 ? 'flex' : 'none';
            let ruBtn = document.getElementById('constructorLangRuBtn');
            let kzBtn = document.getElementById('constructorLangKzBtn');
            let lang = constructorState ? constructorState.lang : 'ru';
            if (ruBtn) ruBtn.classList.toggle('btn-tile--solid-mode', lang === 'ru');
            if (kzBtn) kzBtn.classList.toggle('btn-tile--solid-mode', lang === 'kz');
        }

        async function setConstructorLang(lang) {
            if (!constructorState || constructorState.lang === lang) return;
            let state = await pywebview.api.constructor_set_lang(lang);
            if (state && state.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            constructorState = state;
            renderConstructorLangRow();
            renderConstructorReels();
        }

        // Сотни (100-900) и Тысячи (1-99 тыс.) — это обычные суммы. Для сумм
        // за миллион та же пара клеток переворачивается в одну большую —
        // «Сотни тысяч» (100-900 тыс.) — кнопкой под ними. Одновременно
        // видна только одна сторона, поэтому «Играть»/«Обновить сумму»
        // автоматически берут либо Сотни+Тысячи, либо Сотни тысяч — то, что
        // сейчас показано — и звучит либо «...900, 99 тысяч, 100 тенге»,
        // либо «...100 тысяч, 100 тенге», как и должно быть.
        let constructorBigMode = false;
        function constructorVisibleTiers() {
            return CONSTRUCTOR_TIER_ORDER.filter(t => {
                if (t === 'hundred_thousands') return constructorBigMode;
                if (t === 'hundreds' || t === 'thousands') return !constructorBigMode;
                return true;
            });
        }
        function constructorToggleBigMode() {
            constructorBigMode = !constructorBigMode;
            renderConstructorReels();
        }

        function renderConstructorMeta() {
            if (!constructorState) return;
            let bits = [
                constructorState.start ? `start: ${constructorState.start}` : 'start: не выбран',
                constructorState.end ? `end: ${constructorState.end}` : 'end: без окончания'
            ];
            document.getElementById('constructorMeta').innerText = bits.join(' · ');
        }

        function constructorReelColHTML(tier, wide = false) {
            let items = constructorState.tiers[tier].items;
            let isEmpty = items.length === 0;
            let cls = 'reel-col' + (isEmpty ? ' reel-col--empty' : '') + (wide ? ' reel-col--wide' : '');
            return `
            <div class="${cls}" data-tier="${tier}" style="--tier-accent: ${CONSTRUCTOR_TIER_ACCENT[tier]}">
                <div class="reel-col__label">${escapeHtml(constructorState.tiers[tier].label)}</div>
                <div class="reel" id="reel-${tier}">
                    <div class="reel-indicator"></div>
                    <div class="reel-track"></div>
                </div>
                <div class="reel-col__count">${isEmpty ? 'не найдено — пропускается' : items.length + ' шт.'}</div>
            </div>`;
        }

        function renderConstructorReels() {
            let wrap = document.getElementById('constructorReels');
            if (!constructorState || !constructorState.tiers) { wrap.innerHTML = ''; return; }

            // «Сотни» + «Тысячи» и «Сотни тысяч» занимают одно и то же место
            // в ряду — переворачиваются кнопкой между собой, а не стоят
            // рядом впятером.
            let flipLabel = constructorBigMode
                ? 'Обычные суммы (Сотни и Тысячи)'
                : 'Сумма за миллион (Сотни тысяч)';
            let flipGroup = `
                <div class="constructor-flip-group">
                    <div class="constructor-flip-group__reels">
                        ${constructorBigMode ? constructorReelColHTML('hundred_thousands', true)
                                              : constructorReelColHTML('hundreds') + constructorReelColHTML('thousands')}
                    </div>
                    <button class="constructor-flip-btn" onclick="constructorToggleBigMode()">
                        ${iconHTML('refresh-cw')} ${flipLabel}
                    </button>
                </div>`;

            wrap.innerHTML = constructorReelColHTML('millions') + flipGroup + constructorReelColHTML('tenge');

            constructorReelInstances = {};
            constructorVisibleTiers().forEach(tier => {
                let items = constructorState.tiers[tier].items.map(t => humanizeTierItem(tier, t));
                let container = document.getElementById(`reel-${tier}`);
                constructorReelInstances[tier] = new Reel(container, items, 44, updateConstructorPreview);
            });
            updateConstructorPreview();
            constructorSelectedTier = null;
            constructorEnsureSelection();
            constructorRenderSelection();
        }

        // ==================================================================
        // Управление конструктором с клавиатуры (WASD): A/D переключают,
        // какая рулетка сейчас «активна», W/S крутят её вверх/вниз. При
        // удержании W/S прокрутка постепенно ускоряется — так удобнее
        // долистать от «1» до «99», чем щёлкать по одному шагу.
        // ==================================================================
        let constructorSelectedTier = null;
        let constructorHoldTimers = {};

        function constructorEnsureSelection() {
            if (!constructorState || !constructorState.tiers) return;
            let visible = constructorVisibleTiers();
            if (constructorSelectedTier && visible.includes(constructorSelectedTier)) return;
            constructorSelectedTier = visible.find(t => constructorState.tiers[t].items.length) || visible[0];
        }

        function constructorRenderSelection() {
            CONSTRUCTOR_TIER_ORDER.forEach(tier => {
                let col = document.querySelector(`.reel-col[data-tier="${tier}"]`);
                if (col) col.classList.toggle('reel-col--selected', tier === constructorSelectedTier);
            });
        }

        function constructorMoveSelection(dir) {
            constructorEnsureSelection();
            let visible = constructorVisibleTiers();
            let idx = visible.indexOf(constructorSelectedTier);
            let next = Math.min(visible.length - 1, Math.max(0, idx + dir));
            constructorSelectedTier = visible[next];
            constructorRenderSelection();
        }

        function constructorStepSelected(dir, animate = true) {
            constructorEnsureSelection();
            let reel = constructorReelInstances[constructorSelectedTier];
            if (reel) reel.step(dir, animate);
        }

        // Общий «держатель» для W/S: первый шаг сразу по нажатию, затем,
        // пока клавиша зажата, повторяем со всё уменьшающейся паузой —
        // это и есть ускорение прокрутки при удержании.
        // «Передачи» скорости: пока клавиша зажата, ускорение не упирается
        // в один и тот же потолок, а ступенчато переключается на всё более
        // быструю передачу — держишь дольше, следующая передача ощутимо
        // быстрее финальной скорости предыдущей, а не топчется на месте.
        function constructorHoldInterval(elapsedMs) {
            if (elapsedMs < 1200) return 220 - (220 - 70) * (elapsedMs / 1200);
            if (elapsedMs < 3000) return 70 - (70 - 25) * ((elapsedMs - 1200) / 1800);
            if (elapsedMs < 5000) return 25 - (25 - 10) * ((elapsedMs - 3000) / 2000);
            return 10;
        }
        function constructorStartHold(code, action) {
            if (constructorHoldTimers[code]) return;
            action(true);
            const startedAt = performance.now();
            const tick = () => {
                // Повторы при удержании идут чаще, чем успевает доиграть
                // плавная анимация шага — прыгаем мгновенно (см. Reel.step),
                // иначе на быстрой передаче прокрутка дёргается и «тормозит».
                action(false);
                let interval = constructorHoldInterval(performance.now() - startedAt);
                constructorHoldTimers[code].id = setTimeout(tick, interval);
            };
            constructorHoldTimers[code] = { id: setTimeout(tick, 380) };
        }
        function constructorStopHold(code) {
            let timer = constructorHoldTimers[code];
            if (timer) { clearTimeout(timer.id); delete constructorHoldTimers[code]; }
        }

        function updateConstructorPreview() {
            let el = document.getElementById('constructorPreview');
            if (!el || !constructorState) return;
            let parts = [];
            if (constructorState.start) parts.push(escapeHtml(constructorState.start));
            constructorVisibleTiers().forEach(tier => {
                let items = constructorState.tiers[tier].items;
                let reel = constructorReelInstances[tier];
                if (!items.length) { parts.push(`<em>${escapeHtml(constructorState.tiers[tier].label)} — пропущено</em>`); return; }
                let idx = reel ? reel.getIndex() : 0;
                let shown = reel ? reel.items[idx] : humanizeTierItem(tier, items[idx]);
                parts.push(`<b>${escapeHtml(shown ?? '')}</b>`);
            });
            if (constructorState.end) parts.push(escapeHtml(constructorState.end));
            el.innerHTML = parts.join(' &nbsp;→&nbsp; ');
        }

        function constructorIndices() {
            let indices = {};
            CONSTRUCTOR_TIER_ORDER.forEach(tier => {
                let reel = constructorReelInstances[tier];
                if (reel) {
                    let idx = reel.getIndex();
                    if (idx >= 0) indices[tier] = idx;
                }
            });
            return indices;
        }

        // Play/Стоп по Space — так же, как в основном рабочем экране.
        // Раз в конструкторе нет длинной цепочки фраз, а просто одна
        // склеенная сумма, состояние держим одним флагом плюс таймер на
        // длительность (чтобы флаг сам сбросился, когда проигрывание
        // закончилось само, без нажатия Space второй раз).
        let constructorIsPlaying = false;
        let constructorPlayTimeout = null;

        async function constructorPlay() {
            let res = await pywebview.api.constructor_play(constructorIndices());
            if (res && res.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            clearTimeout(constructorPlayTimeout);
            if (res && res.playing) {
                constructorIsPlaying = true;
                constructorPlayTimeout = setTimeout(() => { constructorIsPlaying = false; }, (res.duration || 0) * 1000);
            } else {
                constructorIsPlaying = false;
            }
        }

        async function constructorStop() {
            clearTimeout(constructorPlayTimeout);
            constructorIsPlaying = false;
            await pywebview.api.stop_audio();
        }

        async function constructorTogglePlay() {
            if (constructorIsPlaying) await constructorStop();
            else await constructorPlay();
        }

        async function constructorSendToAudacity() {
            let btn = document.querySelector('#stage3-constructor .btn-tile--primary');
            let origHtml = btn ? btn.innerHTML : null;
            if (btn) { btn.disabled = true; btn.innerHTML = 'Открываю Audacity...'; }
            let res;
            try {
                res = await pywebview.api.constructor_send_to_audacity(constructorIndices());
            } finally {
                if (btn) { btn.disabled = false; btn.innerHTML = origHtml; }
            }
            if (res && res.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${res.error}`);
                return;
            }
            // Теперь Audacity точно запущен — сажаем его окно в рамку конструктора
            if (!audacityEmbedded) await attachEmbeddedAudacity(true);
        }

        async function constructorSaveResult() {
            let res = await pywebview.api.constructor_save();
            if (res && res.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${res.error}`);
            } else if (res) {
                showToast(`Сохранено кусков: ${res.saved}`);
            }
        }

        // ===== TTS-ПРОЕКТ =====
        // Таблица (фразы + флаги start/start_2/end + листы переменных) и одна
        // сырая запись. Программа режет запись на дубли, распознаёт каждый и
        // привязывает к фразе. От пользователя — только прослушать и Enter.
        // Сохраняется дубль лишь после прослушивания: автопроверка ошибается.
        let tts = null;              // состояние с бэкенда (tts_state)
        let ttsPlayTimer = null;
        let ttsPlayingIdx = -1;
        // Номер последнего «играть»/«стоп»: всё, что относится к прежнему
        // запуску (ответ, бегунок, таймер), — не трогает экран.
        let ttsPlayGen = 0, ttsPlayPending = false;
        let ttsListMode = 'all';

        async function openTts() {
            let st = await pywebview.api.tts_state();
            if (!st || !st.loaded) {
                let how = await showBeautifulChoice('<b>TTS-проект</b><br><br>Загрузите таблицу: лист фраз с колонками '
                    + '<code>&lt;phrase&gt;</code>, <code>&lt;name_phrase&gt;</code>, флаги <code>&lt;start&gt;</code> / '
                    + '<code>&lt;start_2&gt;</code> / <code>&lt;end&gt;</code> и листы переменных (суммы, даты).<br><br>'
                    + '<b>Продолжить работу</b> — выберите папку прежнего проекта (или папку «Записи» в ней): '
                    + 'подтяну дубли, сохранённое и место, где остановились.',
                    'Выбрать таблицу', 'Продолжить работу', 'P', 'Отмена');
                if (how === 'alt') {
                    st = await pywebview.api.tts_pick_project();
                    if (!st || st.error === 'cancel') return;
                    if (st.error) { showBeautifulAlert('⚠️ ' + escapeHtml(st.error)); return; }
                    openTtsScreen(st);
                    if (st.message) showToast(st.message);
                    return;
                }
                if (how !== 'ok') return;
                st = await ttsPickExcelFlow();
                if (!st) return;
            }
            openTtsScreen(st);
            if (!st.has_takes) {
                let how = await showBeautifulChoice(`<b>Таблица загружена</b><br><br>${st.stats.units - st.stats.pieces} обычных фраз и `
                    + `${st.stats.pieces} кусочков фраз с переменными (${st.stats.chains} фраз).<br><br>`
                    + `<b>Записать с микрофона</b> — покажу фразы по очереди, готовые сразу появятся на ленте.<br>`
                    + `<b>Выбрать файл</b> — уже записанный сырой WAV: нарежу и сверю с таблицей.`,
                    'Записать с микрофона', 'Выбрать файл', 'F', 'Позже');
                if (how === 'ok') ttsToggleRec();
                else if (how === 'alt') ttsLoadRecording();
            }
        }

        async function ttsPickExcelFlow() {
            let st = await pywebview.api.tts_pick_excel();
            if (st && st.choose_sheet) {
                let title = await ttsChooseSheet(st.choose_sheet);
                if (!title) return null;
                st = await pywebview.api.tts_choose_sheet(title);
            }
            if (!st || st.error === 'cancel') return null;
            if (st.error) { showBeautifulAlert('⚠️ ' + escapeHtml(st.error)); return null; }
            return st;
        }

        function ttsChooseSheet(sheets) {
            return new Promise(resolve => {
                ttsOpenListOverlay('Какой лист фраз?', false);
                document.getElementById('ttsList').innerHTML = sheets.map((s, i) =>
                    `<button type="button" class="audit-category-item" data-i="${i}">${escapeHtml(s.title)}
                        <span class="audit-choice-desc">${s.lang.toUpperCase()} · ${s.units} фраз</span></button>`).join('');
                document.querySelectorAll('#ttsList [data-i]').forEach(b => b.onclick = () => {
                    ttsListOnClose = null;
                    ttsCloseList(); resolve(sheets[+b.dataset.i].title);
                });
                ttsListOnClose = () => resolve(null);
            });
        }

        function openTtsScreen(st) {
            tts = st;
            embedAreaId = 'ttsEmbedArea';
            embedBtnId = 'ttsEmbedBtn';
            showStage('stage4-tts');
            document.getElementById('stage4-tts').classList.add('is-prompter');
            ttsRender();
            ttsLoadPrompt();
            ttsLiveRender();
            ttsMonitorLabel();
            ttsFastRender();
            // Прослушивание дублей — сразу в выбранные наушники (не только во время записи).
            pywebview.api.tts_rec_devices().then(l => { if (l && !l.error) ttsMonitorApply(l.outputs); });
        }

        // Язык распознавания: если в таблице есть метки <…_kz> / <…_ru> — сам,
        // по фразе на суфлёре; иначе — переключатель (язык всего листа).
        let ttsLangNow = null;
        function ttsLangShow(lang) {
            let box = document.getElementById('ttsLang');
            if (!box) return;
            box.classList.toggle('is-auto', !!(tts && tts.lang_auto));
            box.title = tts && tts.lang_auto ? 'Язык распознавания — сам: по тексту фразы на экране (казахские буквы — KZ) и меткам full_phrase_kz / full_phrase_ru' : 'Язык распознавания речи';
            box.querySelectorAll('button').forEach(b => b.classList.toggle('is-on', b.dataset.l === lang));
        }
        async function ttsSetLang(lang) {
            if (tts && tts.lang_auto) { showToast('Язык переключается сам — по тексту фразы на экране (и меткам full_phrase_kz / full_phrase_ru)'); return; }
            if (!tts || !tts.loaded || tts.lang === lang) return;
            let st = await pywebview.api.tts_set_lang(lang);
            if (st && st.error) { showToast(st.error); return; }
            tts = st;
            ttsRender();
            ttsFastRender();
            showToast(lang === 'kz' ? 'Распознаю по-казахски' : 'Распознаю по-русски');
        }

        async function ttsLoadPrompt() {
            if (!tts || !tts.loaded) { ttsRenderPrompt({ none: true }); return; }
            let pr = await pywebview.api.tts_prompt_info();
            ttsRenderPrompt(pr || { none: true });
        }

        async function ttsLoadExcel() {
            let st = await ttsPickExcelFlow();
            if (st) { tts = st; ttsRender(); ttsLoadPrompt(); }
        }

        async function ttsLoadRecording() {
            let res = await pywebview.api.tts_pick_recording();
            if (res && res.state) { tts = res.state; ttsRender(); ttsLoadPrompt(); }
            if (res && res.message) showToast(res.message);
            if (!res || res.error === 'cancel') return;
            if (res.error) { showBeautifulAlert('⚠️ ' + escapeHtml(res.error)); return; }
            ttsShowBusy('Режу запись на дубли…', 0);
        }

        function ttsShowBusy(text, pct) {
            let cur = document.getElementById('ttsRail');
            cur.innerHTML = `<div class="tts-busy">
                <div class="progress-head"><span class="progress-spinner" aria-hidden="true"></span>
                <div class="progress-text">${escapeHtml(text)}</div><span class="progress-pct">${pct ? pct + '%' : ''}</span></div>
                <progress max="100" value="${pct || 0}"></progress>
                <button class="btn-ghost btn-ghost--compact" onclick="pywebview.api.tts_stop()">Остановить</button></div>`;
        }

        // Python шлёт сюда ход нарезки и распознавания.
        function ttsProgress(p) {
            if (!p) return;
            if (p.stage === 'cut') ttsShowBusy(p.total ? `Режу запись: ${p.done} / ${p.total}` : 'Режу запись на дубли…',
                                               p.total ? Math.round(p.done / p.total * 100) : 0);
            else if (p.stage === 'model') ttsShowBusy('Загружаю модель распознавания…', 0);
            else if (p.stage === 'save') ttsShowBusy(`Раскладываю фразы: ${p.done} / ${p.total}`, Math.round(p.done / p.total * 100));
            else if (p.stage === 'asr') ttsShowBusy(`Слушаю дубли: ${p.done} / ${p.total}`, Math.round(p.done / p.total * 100));
            else if (p.stage === 'error') {
                ttsRender();
                if (p.error === 'need_model' || p.error === 'need_model_kz') { showAsrModel(p.error === 'need_model_kz' ? 'kz' : 'ru'); return; }
                showBeautifulAlert('⚠️ ' + escapeHtml(p.error));
            } else if (p.stage === 'live') {
                let before = tts ? tts.takes.length : 0;
                ttsLiveUpdate(p.state, p.added);
                if (p.tier_auto === null || p.tier_auto === undefined) ttsAutoAsm(tts.takes.length - before);
                else showToast(`Строка сохранена по шаблону: эталонов ${p.tier_auto}`, 2500);
                if (p.prompt) ttsRenderPrompt(p.prompt, p.advanced ? 'next' : null);
                if (p.added) ttsLiveFlash('ok', tts.takes.slice(-p.added).map(t => t.name || 'не фраза').join(' · '));
            } else if (p.stage === 'synth') {
                ttsSynthEvent(p);
            } else if (p.stage === 'take_synth') {
                ttsTakeSynthEvent(p);
            } else if (p.stage === 'marks') {
                ttsShowMarksPending(p.pending, p.error);
            } else if (p.stage === 'live_partial') {
                if (p.prompt) { if (p.back) ttsPromptKey = null; ttsRenderPrompt(p.prompt, p.back ? 'restart' : null); }
                ttsLiveFlash('partial', p.message);
            } else if (p.stage === 'live_busy') {
                ttsLiveSt.busy = p.busy;
                if (!p.busy) ttsLiveSt.waiting = !!p.waiting;
                ttsLiveRender();
            } else if (p.stage === 'live_doubt') {
                let before = tts ? tts.takes.length : 0;
                ttsLiveUpdate(p.state, 0);
                ttsAutoAsm(tts.takes.length - before);
                ttsLiveFlash('miss-msg', p.message);
            } else if (p.stage === 'live_miss') {
                ttsLiveFlash(p.paused ? 'pause-miss' : 'miss', p.heard);
            } else if (p.stage === 'live_cmd') {
                if (p.state) ttsLiveUpdate(p.state, 0);
                if (p.prompt) ttsRenderPrompt(p.prompt, p.cmd === 'redo' ? 'restart' : null);
                ttsSetPaused(p.paused);
                ttsLiveSt.paused = !!p.paused;
                ttsLiveFlash('cmd-' + p.cmd, p.message);
            } else if (p.stage === 'live_restart') {
                if (p.prompt) ttsRenderPrompt(p.prompt, 'restart');
            } else if (p.stage === 'live_done') {
                ttsRecStopped(p.state, p.error);
            } else if (p.stage === 'live_error') {
                showToast(p.error);
            } else if (p.stage === 'done') {
                tts = p.state;
                ttsRender();
                let s = tts.stats;
                showToast(`Готово: ${tts.takes.length} дублей. Сомнительных — ${s.doubt}, не найдено фраз — ${s.missing}`);
            }
        }

        const ttsCurTake = () => tts && tts.takes.length ? tts.takes[tts.index] : null;
        const ttsUnit = id => (id === null || id === undefined || !tts) ? null : tts.units[id];

        function ttsRender() {
            if (!tts) return;
            let s = tts.stats;
            document.getElementById('ttsMeta').innerText = tts.loaded
                ? `${tts.excel_name}${tts.project ? ' · ' + tts.project : ''}` : 'Таблица не загружена';
            document.getElementById('ttsLang').style.display = tts.loaded ? '' : 'none';
            ttsLangShow(ttsLangNow || tts.lang);
            document.getElementById('ttsStatSaved').innerText = s.saved;
            document.getElementById('ttsStatUnits').innerText = s.units;
            document.getElementById('ttsStatDoubt').innerText = s.doubt;
            document.getElementById('ttsStatMissing').innerText = s.missing;
            document.getElementById('ttsVarCount').innerText = `${s.pieces_saved} / ${s.pieces}`;
            ttsRenderHintBtns();
            let cats = Object.values(tts.var_sheets || {}).map(v => v.label).join(', ');
            document.getElementById('ttsVarDesc').innerText = cats ? `Фразы с переменными · ${cats}` : 'Фразы с переменными';
            ttsRenderRail();
            ttsRenderCurrent();
            ttsRenderAssembly();
            ttsShowMarksPending(tts.marks_pending);
            // Audacity встроен — текущий дубль сам уезжает туда.
            let cur = ttsCurTake();
            if (audacityEmbedded && cur && ttsAudacitySent !== cur.i) {
                ttsAudacitySent = cur.i;
                ttsSendToAudacity(true);
            }
        }

        function ttsTakeClass(t) {
            if (t.rejected) return 'is-rejected';
            if (t.approved && t.unit_saved) return 'is-saved';
            if (t.unit_saved) return 'is-done';
            if (t.unit === null) return t.status === 'noise' ? 'is-noise' : 'is-none';
            return t.status === 'ok' ? 'is-ok' : (t.status === 'manual' ? 'is-manual' : 'is-doubt');
        }

        function ttsRenderRail() {
            let rail = document.getElementById('ttsRail');
            if (!tts.takes.length) {
                rail.innerHTML = `<div class="tts-rail__empty">${!tts.loaded ? 'Загрузите таблицу и запись' : (ttsRec.on ? 'Записанные фразы появятся здесь' : 'Загрузите или запишите запись — здесь появятся дубли')}</div>`;
                return;
            }
            rail.innerHTML = tts.takes.map(t => `
                <button type="button" class="tts-take ${ttsTakeClass(t)} ${t.i === tts.index ? 'is-current' : ''} ${t.kind === 'piece' ? 'is-chain' : ''}"
                        data-i="${t.i}" onclick="ttsRailClick(${t.i})" draggable="true"
                        ondragstart="ttsTakeDragStart(event, ${t.i})" ondragend="ttsTakeDragEnd()" title=""${escapeHtml(t.heard || 'тишина / шум')}">
                    <span class="tts-take__num">${String(t.chunk || t.i + 1).padStart(3, '0')}${t.split ? '<span class="tts-take__cut">✂</span>' : ''}</span>
                    <span class="tts-take__name">${t.name ? escapeHtml(t.name) : '—'}</span>
                    <span class="tts-take__meta">${t.status === 'manual' && t.unit !== null ? 'вручную' : (t.unit !== null ? Math.round(t.score * 100) + '%' : '')}${t.take_total > 1 ? ` · ${t.take_no}/${t.take_total}` : ''}</span>
                </button>`).join('');
            rail.classList.toggle('is-playing', ttsPlayingIdx === tts.index);
            let cur = rail.querySelector('.is-current');
            if (cur) cur.scrollIntoView({ block: 'nearest', inline: 'center', behavior: motionOK() ? 'smooth' : 'auto' });
        }

        const TTS_STATUS = {
            ok: ['Совпало', 'good'], doubt: ['Сомнительно — проверьте на слух', 'var'],
            manual: ['Привязан вручную', 'info'], none: ['Не похоже ни на одну фразу', 'trash'], noise: ['Тишина / шум', 'trash']
        };

        function ttsRenderCurrent() {
            let el = document.getElementById('ttsCurrent');
            let t = ttsCurTake();
            if (!t) {
                el.innerHTML = `<div class="tts-current__empty">${tts.loaded ? 'Загрузите запись' : 'Загрузите таблицу'}</div>`;
                return;
            }
            let u = ttsUnit(t.unit);
            let [label, tone] = ttsTakeStatus(t);
            let where = u ? (u.kind === 'piece' ? 'Фразы_Переменные' : 'Проверенные') : '';
            el.innerHTML = `
                <div class="tts-current__head">
                    <span class="tts-pill tts-pill--${tone}">${label}</span>
                    <span class="tts-current__score">${u ? Math.round(t.score * 100) + '%' : ''}</span>
                    <span class="tts-current__num">дубль ${t.i + 1} / ${tts.takes.length}</span>
                </div>
                <div class="tts-current__text">${u ? ttsUnitTextHTML(u) : '<span class="tts-dim">Фраза не определена</span>'}</div>
                <div class="tts-current__heard"><span class="tts-dim">Услышано:</span> ${t.heard ? escapeHtml(t.heard) : '<span class="tts-dim">—</span>'}</div>
                <div class="tts-current__file">${u ? `${escapeHtml(u.name)}.wav → ${where}` : ''}${t.split ? ` · вырезан из дубля ${String(t.chunk).padStart(3, '0')}` : ''}</div>
                <div class="tts-current__actions">
                    <button class="btn-tile ${ttsPlayingIdx === t.i ? 'is-active' : ''}" onclick="ttsTogglePlay()">${ttsPlayingIdx === t.i ? 'Стоп' : 'Слушать'} <kbd>Space</kbd></button>
                    <button class="btn-tile btn-tile--good" onclick="ttsApprove()" ${u ? '' : 'disabled'}>Сохранить <kbd>Enter</kbd></button>
                    <button class="btn-tile" onclick="ttsOpenUnits('assign')">Другая фраза <kbd>F</kbd></button>
                    <button class="btn-tile btn-tile--sub" onclick="ttsReject()" title="Убрать дубль с дорожки. Ctrl+Z — вернуть">Удалить дубль <kbd>Del</kbd></button>
                </div>
`;
        }

        function ttsTakeStatus(t) {
            if (t.unit_saved) return t.approved ? ['Сохранён этот дубль', 'good'] : ['Фраза уже сохранена другим дублем', 'good'];
            return TTS_STATUS[t.status] || TTS_STATUS.none;
        }

        function ttsUnitTextHTML(u) {
            let pill = v => v ? `<span class="tts-var">${escapeHtml(ttsVarLabel(v))}</span>` : '';
            if (u.kind !== 'piece') return escapeHtml(u.text);
            return [pill(u.var_before), escapeHtml(u.text), pill(u.var_after)].filter(Boolean).join(' ');
        }

        function ttsVarLabel(key) {
            let v = (tts.var_sheets || {})[key];
            return v ? v.label : key;
        }

        // «Сборка»: вся фраза из кусочков — что уже сохранено, где текущий.
        function ttsRenderAssembly() {
            let el = document.getElementById('ttsAssembly');
            let t = ttsCurTake();
            let u = t ? ttsUnit(t.unit) : null;
            if (!u) { el.innerHTML = '<div class="tts-assembly__title">Сборка</div><div class="tts-dim">Выберите дубль на ленте</div>'; return; }
            let chain = u.chain !== null && u.chain !== undefined ? (tts.chains || [])[u.chain] : null;
            let block = p => `<div class="tts-block ${p.id === u.id ? 'is-current' : ''} ${p.saved ? 'is-saved' : ''}"
                    ${p.saved ? `onclick="ttsPlayUnit(${p.id})" title="Слушать сохранённое"` : ''}>
                    <span class="tts-block__role">${p.kind === 'value' ? escapeHtml(p.cat_label || 'значение') : (p.role || 'фраза')}${p.saved ? ' ✓' : ''}</span>
                    <span class="tts-block__name">${escapeHtml(p.name)}</span>
                    <span class="tts-block__text">${escapeHtml(p.text)}</span></div>`;
            let varBlock = v => `<div class="tts-block tts-block--var"><span class="tts-block__role">переменная</span>
                    <span class="tts-block__name">${escapeHtml(ttsVarLabel(v))}</span></div>`;
            let blocks;
            if (chain && chain.values && chain.values.length) {
                // значение из ячейки: start, это значение (или первое), продолжение
                let k = chain.parts.indexOf(chain.inline_at) + (chain.inline_after ? 1 : 0);
                let val = chain.values.includes(u.id) ? u.id : chain.values[0];
                blocks = chain.parts.slice(0, k).concat([val], chain.parts.slice(k)).map(id => block(tts.units[id])).join('');
            } else blocks = chain
                ? chain.parts.map(id => tts.units[id]).map((p, k) =>
                    (k === 0 && p.var_before ? varBlock(p.var_before) : '') + block(p) + (p.var_after ? varBlock(p.var_after) : '')).join('')
                : block(u);
            let saved = chain ? chain.parts.filter(id => tts.units[id].saved).length : (u.saved ? 1 : 0);
            let [label, tone] = ttsTakeStatus(t);
            el.innerHTML = `<div class="tts-assembly__title">Сборка <span class="tts-dim">${chain
                    ? `${escapeHtml(chain.name)} · кусочков сохранено ${saved} / ${chain.parts.length}` : u.tiers ? 'строка переменных' : 'обычная фраза'}</span>
                    <span class="tts-pill tts-pill--${tone}">${label}</span>
                    <span class="tts-dim tts-asm-num">дубль ${t.i + 1} / ${tts.takes.length}</span>
                    <button class="tts-asm-close" onclick="ttsShowAssembly(false)" title="Закрыть и вернуться к чтению (Esc или клик мимо карточек)">Закрыть <kbd>Esc</kbd></button></div>
                <div class="tts-blocks">${blocks}</div>
                ${u.tiers ? '<div class="tts-tiers" id="ttsTiers"></div>' : ''}
                <div class="tts-tsyn" id="ttsTsyn" style="display:none"></div>
                ${t.reuse ? `<div class="tts-asm-heard tts-asm-reuse">Собрано из записанного: ${(t.reuse.srcs || [t.reuse.src]).map(n => '«' + escapeHtml(n) + '»').join(', ')}${t.reuse.rec ? ` + ${t.reuse.rec === 1 ? 'новый кусок' : 'новые куски'} из этой записи` : ''}. Куски — в Audacity отдельными клипами: склейте там и нажмите «Сохранить из Audacity».
                    <button type="button" class="btn-ghost btn-ghost--info btn-ghost--compact" onclick="ttsSendToAudacity()">Фрагменты → Audacity</button>
                    <button type="button" class="btn-ghost btn-ghost--good btn-ghost--compact" onclick="ttsSaveFromAudacity()">Сохранить из Audacity</button></div>` : ''}
                <div class="tts-asm-heard"><span class="tts-dim">Услышано:</span> ${t.heard ? escapeHtml(t.heard) : '<span class="tts-dim">—</span>'}</div>
                <div class="tts-ed">
                    <canvas class="tts-ed__canvas" id="ttsEdCanvas"></canvas>
                    <div class="tts-ed__bar">
                        <span class="tts-ed__time" id="ttsEdTime"></span>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdCutBtn" onclick="ttsEditorCut()" disabled title="Вырезать выделенное (выделите мышью на клипе)">Вырезать <kbd>X</kbd></button>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdUndo" onclick="ttsEdUndo()" disabled>&#8630; <kbd>Ctrl+Z</kbd></button>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdRedo" onclick="ttsEdUndo(true)" disabled>&#8631;</button>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsEditorReset()" title="Вернуть дубль, как его нарезала программа (тоже отменяется Ctrl+Z)">Сбросить</button>
                        ${u.kind === 'value' ? `<button class="btn-ghost btn-ghost--compact" onclick="ttsCtxPlay('whole', ${t.i})" title="Послушать в фразе: начало + этот дубль + продолжение">&#9654; В фразе</button>` : ''}
                        <button class="btn-ghost btn-ghost--compact" id="ttsTsynBtn" onclick="ttsTsynToggle()" title="Добить конец фразы синтезом (если не выговаривается) — ляжет на дорожку отдельным клипом">Синтез…</button>
                        <span class="tts-ed__zoom">
                            <button class="btn-ghost btn-ghost--compact" onclick="ttsEdZoom(0.66)" title="Отдалить (Ctrl + колесо)">&minus;</button>
                            <button class="btn-ghost btn-ghost--compact" onclick="ttsEdZoom(1.5)" title="Приблизить (Ctrl + колесо)">+</button>
                            <button class="btn-ghost btn-ghost--compact" onclick="ttsEdFit(); ttsEditorDraw()" title="Вся дорожка в окне">Вписать</button>
                        </span>
                        <span class="tts-ed__spacer"></span>
                        <button class="btn-ghost btn-ghost--info btn-ghost--compact" onclick="ttsSendToAudacity()" title="Открыть дубль в Audacity">В Audacity</button>
                        <button class="btn-ghost btn-ghost--info btn-ghost--compact" onclick="ttsTakeFromAudacity()" title="Забрать правку из Audacity в этот дубль">Забрать из Audacity</button>
                        <button class="btn-ghost btn-ghost--good btn-ghost--compact" onclick="ttsSaveFromAudacity()" title="Забрать дорожку из Audacity (как склеили там) и сразу сохранить фразу">Сохранить из Audacity</button>
                    </div>
                    ${ttsSoundBarHTML(t)}
                </div>
                <div class="tts-asm-actions">
                    <button class="btn-tile ${ttsPlayingIdx === t.i ? 'is-active' : ''}" onclick="ttsTogglePlay()">${ttsPlayingIdx === t.i ? 'Стоп' : 'Слушать'} <kbd>Space</kbd></button>
                    <button class="btn-tile btn-tile--good" onclick="ttsApprove()">Сохранить <kbd>Enter</kbd></button>
                    <button class="btn-tile" onclick="ttsOpenUnits('assign')">Другая фраза <kbd>F</kbd></button>
                    <button class="btn-tile btn-tile--sub" onclick="ttsReject()" title="Убрать дубль и записать фразу заново. Ctrl+Z — вернуть">Удалить дубль <kbd>Del</kbd></button>
                </div>`;
            ttsEditorLoad();
            if (u.tiers) ttsTiersLoad(t.i);
            if (ttsTS && ttsTS.i === t.i) ttsTsynRender(); else ttsTS = null;
        }

        // ----- «Ярусы»: строка переменных режется на эталоны ярусов -----
        // Границы ставятся сами (в паузы), их можно двигать мышью. Клик по
        // ярусу — послушать, как он сохранится. Enter — каждый ярус ложится
        // своим финальным файлом; готовые ярусы не трогаются (если не
        // отмечено «перезаписать»).
        let ttsTR = null;
        async function ttsTiersLoad(i) {
            let r = await pywebview.api.tts_tier_marks(i);
            let t = ttsCurTake();
            if (!t || t.i !== i) return;
            ttsTR = r && r.tiers ? r : null;
            ttsTiersRender();
        }
        // Две дорожки, как в режиме «Суммы»: «Дубль» — откуда взят каждый ярус
        // (края тянутся), «Сборка» — ярусы друг за другом, как склеятся файлы,
        // с концом начала фразы и началом продолжения; клип яруса тянется
        // вправо/влево — пауза перед ним. Готовый ярус (из другой строки) —
        // в сборке своим файлом, серый.
        function ttsTiersLayout() {
            let r = ttsTR, x = 0, out = [];
            if (r.ctx.start) { out.push({ ctx: 'start', x, w: r.ctx.start.len, peaks: r.ctx.start.peaks, name: r.ctx.start.name }); x += r.ctx.start.len; }
            r.tiers.forEach(t => {
                let fixed = t.exists && !t.write && t.file_len;
                let pre = fixed ? 0 : t.pre;
                let w = fixed ? t.file_len : Math.round((t.b - t.a) / (t.tempo * (r.take_tempo || 1)));
                let post = fixed ? 0 : (t.post || 0);
                out.push({ k: t.k, x: x + pre, w, peaks: fixed ? t.file_peaks : t.peaks, fixed, pre, post, t });
                x += pre + w + post;
            });
            if (r.ctx.end) { out.push({ ctx: 'end', x, w: r.ctx.end.len, peaks: r.ctx.end.peaks, name: r.ctx.end.name }); x += r.ctx.end.len; }
            return { clips: out, total: x };
        }
        function ttsDrawPeaks(cv, peaks) {
            if (!cv) return;
            let dpr = window.devicePixelRatio || 1;
            cv.width = Math.max(1, cv.clientWidth * dpr); cv.height = Math.max(1, cv.clientHeight * dpr);
            let g = cv.getContext('2d'), n = peaks.length, mid = cv.height / 2;
            g.fillStyle = getComputedStyle(cv).color;
            for (let k = 0; k < n; k++) {
                let h = Math.max(1, peaks[k] * mid * 0.92);
                g.fillRect(k / n * cv.width, mid - h, Math.max(1, cv.width / n), 2 * h);
            }
        }
        function ttsTiersRender() {
            let el = document.getElementById('ttsTiers');
            if (!el) return;
            if (!ttsTR) { el.innerHTML = '<div class="tts-dim">Ярусы: не удалось прочитать дубль</div>'; return; }
            let r = ttsTR, lay = ttsTiersLayout();
            let span = Math.max(r.length, lay.total) || 1;
            let pct = ms => (100 * ms / span).toFixed(3) + '%';
            let regions = r.tiers.map(t => `<div class="tts-tiers__reg ${t.exists && !t.write ? 'is-skip' : ''}" style="left:${pct(t.a)};width:${pct(t.b - t.a)}"
                    title="${escapeHtml(t.label)}: ${escapeHtml(t.text)} — края тяните мышью">
                    <span>${escapeHtml(t.label)}</span>
                    <i class="tts-tiers__edge is-l" onpointerdown="ttsTierEdge(event, ${t.k}, 'a')"></i>
                    <i class="tts-tiers__edge is-r" onpointerdown="ttsTierEdge(event, ${t.k}, 'b')"></i></div>`).join('');
            let clips = lay.clips.map((c, n) => c.ctx
                ? `<div class="tts-tiers__clip is-ctx" style="left:${pct(c.x)};width:${pct(c.w)}" title="${c.ctx === 'start' ? 'Конец начала фразы' : 'Начало продолжения'} «${escapeHtml(c.name)}»">
                     <canvas data-n="${n}"></canvas><span>${c.ctx === 'start' ? '… ' + escapeHtml(c.name) : escapeHtml(c.name) + ' …'}</span></div>`
                : `${c.pre ? `<div class="tts-tiers__gap" style="left:${pct(c.x - c.pre)};width:${pct(c.pre)}">${c.pre}</div>` : ''}
                   <div class="tts-tiers__clip ${c.fixed ? 'is-fixed' : ''}" style="left:${pct(c.x)};width:${pct(c.w)}"
                     ${c.fixed ? `onpointerdown="event.stopPropagation(); ttsTierPlay(${c.k})" title="${escapeHtml(c.t.label)} ${escapeHtml(c.t.value)} — уже готов, берётся как есть"`
                       : `onpointerdown="ttsTierMove(event, ${c.k})" title="${escapeHtml(c.t.label)} ${escapeHtml(c.t.value)} — тяните: пауза перед ярусом; клик — послушать"`}>
                     <canvas data-n="${n}"></canvas><span>${escapeHtml(c.t.label)} <b>${escapeHtml(c.t.value)}</b></span></div>
                   ${c.post ? `<div class="tts-tiers__gap" style="left:${pct(c.x + c.w)};width:${pct(c.post)}">${c.post}</div>` : ''}`).join('');
            let chips = r.tiers.map(x => `<div class="tts-tiers__chip ${x.exists && !x.write ? 'is-skip' : ''}">
                    <button type="button" class="tts-tiers__play" onclick="ttsTierPlay(${x.k})" title="Послушать ярус">&#9654;</button>
                    <span class="tts-tiers__lbl">${escapeHtml(x.label)} <b>${escapeHtml(x.value)}</b></span>
                    <span class="tts-tiers__txt">${escapeHtml(x.text)}</span>
                    ${x.exists && !x.write ? '' : `<span class="tts-tiers__knob" title="Темп яруса (без смены высоты голоса)">темп
                        <button type="button" onclick="ttsTierKnob(${x.k}, 'tempo', -0.03)">&minus;</button><b>${Math.round(x.tempo * 100)}%</b><button type="button" onclick="ttsTierKnob(${x.k}, 'tempo', 0.03)">+</button></span>
                      <span class="tts-tiers__knob" title="Громкость яруса — к громкости фразы">дБ
                        <button type="button" onclick="ttsTierKnob(${x.k}, 'gain', -1)">&minus;</button><b>${x.gain > 0 ? '+' : ''}${x.gain}</b><button type="button" onclick="ttsTierKnob(${x.k}, 'gain', 1)">+</button></span>`}
                    ${x.exists ? `<label class="tts-tiers__exists" title="Этот эталон уже сохранён из другой строки — по умолчанию не трогаем">
                        <input type="checkbox" ${x.write ? 'checked' : ''} onchange="ttsTierWrite(${x.k}, this.checked)"> уже есть · перезаписать</label>`
                      : x.mine ? '<span class="tts-tiers__ok">сохранён ✓</span>' : ''}</div>`).join('');
            let tp = r.tpl, o = r.opts || {}, hasCtx = !!(r.ctx.start || r.ctx.end);
            el.innerHTML = `<div class="tts-tiers__title">Ярусы
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierPlay(-1)" title="С секунды до первого яруса и до конца. Клик по дорожке «Сборка» — играть с этого места">&#9654; Вся сумма</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierStop()" title="Остановить">&#9632;</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierJoinPlay()" title="Стык: конец начала фразы + строка + начало продолжения (по ${TTS_JOIN_MS / 1000} с)">&#9654; Стык</button>
                    ${ttsJoinHTML(r.tiers, 'ttsTierJoin')}
                    ${hasCtx ? `<button type="button" class="tts-reuse-chip ${o.noise ? 'is-on' : ''}" onclick="ttsTierOpt('noise', ${!o.noise})" title="Пауза перед ярусом и фон под голосом — шумом комнаты из начала фразы">фон как во фразе${o.noise ? ' ✓' : ''}</button>
                    <button type="button" class="tts-reuse-chip ${o.level ? 'is-on' : ''}" onclick="ttsTierOpt('level', ${!o.level})" title="Громкость речи ярусов — как у начала и продолжения фразы${r.ctx_level !== null ? ' (' + r.ctx_level + ' дБ)' : ''}">громкость как у фразы${o.level ? ' ✓' : ''}</button>` : '<span class="tts-dim">начало фразы не записано — фон и громкость не с чем сравнить</span>'}
                    ${ttsBgHTML(r.bg)}
                    <span class="tts-tiers__tpl">${tp ? `шаблон: ${escapeHtml(tp.from)}${tp.used ? ' · размечено по нему' : ''}` : 'шаблона нет — первая сохранённая строка станет шаблоном'}
                      <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierTpl()" title="Края, паузы, темп и громкость ярусов этой строки — для следующих строк">Шаблон из этой строки</button>
                      ${tp ? `<button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierTplApply()" title="Разметить этот дубль заново по шаблону">По шаблону</button>
                      <button type="button" class="tts-reuse-chip ${tp.auto ? 'is-on' : ''}" onclick="ttsTierAutoSet(${!tp.auto})" title="Записали строку — ярусы сохраняются сами, «Сборка» не открывается">сохранять сразу${tp.auto ? ' ✓' : ''}</button>` : ''}</span></div>
                ${ttsTierPhraseHTML(r)}
                <div class="tts-tiers__row"><span class="tts-tiers__name">Дубль</span>
                    <div class="tts-tiers__wave" id="ttsTiersWave"><canvas id="ttsTiersCanvas" style="width:${pct(r.length)}"></canvas>${regions}</div></div>
                <div class="tts-tiers__row"><span class="tts-tiers__name">Сборка</span>
                    <div class="tts-tiers__asm" id="ttsTiersAsm" onpointerdown="ttsTierSeek(event)" title="Клик — слушать с этого места">${clips}<i class="tts-tiers__head" id="ttsTiersHead"></i></div></div>
                <div class="tts-tiers__chips">${chips}</div>`;
            ttsDrawPeaks(document.getElementById('ttsTiersCanvas'), r.peaks);
            el.querySelectorAll('.tts-tiers__clip canvas').forEach(cv => ttsDrawPeaks(cv, lay.clips[+cv.dataset.n].peaks || []));
        }
        const ttsTiersSpan = () => Math.max(ttsTR.length, ttsTiersLayout().total) || 1;
        async function ttsTiersSend() {
            let i = ttsCurTake() && ttsCurTake().i;
            let res = await pywebview.api.tts_tier_set(i, ttsTR.tiers.map(t => ({ a: t.a, b: t.b, pre: t.pre, post: t.post, tempo: t.tempo, gain: t.gain })), null);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
        }
        // край клипа на дорожке «Дубль»: откуда и докуда берётся ярус
        function ttsTierEdge(e, k, side) {
            e.preventDefault(); e.stopPropagation();
            let span = ttsTiersSpan(), t = ttsTR.tiers[k];
            let move = ev => {
                let rc = document.getElementById('ttsTiersWave').getBoundingClientRect();
                if (!rc.width) return;
                let ms = Math.round((ev.clientX - rc.left) / rc.width * span);
                if (side === 'a') t.a = Math.max(0, Math.min(t.b - 40, ms));
                else t.b = Math.min(ttsTR.length, Math.max(t.a + 40, ms));
                ttsTiersRender();
            };
            let up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); ttsTiersSend(); };
            window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
        }
        // клип на дорожке «Сборка»: тянуть — пауза перед ярусом, просто клик — послушать
        function ttsTierMove(e, k) {
            e.preventDefault(); e.stopPropagation();
            let span = ttsTiersSpan(), t = ttsTR.tiers[k], x0 = e.clientX, pre0 = t.pre, moved = false;
            let move = ev => {
                let rc = document.getElementById('ttsTiersAsm').getBoundingClientRect();
                if (!rc.width || Math.abs(ev.clientX - x0) < 3 && !moved) return;
                moved = true;
                t.pre = Math.max(0, Math.min(3000, Math.round(pre0 + (ev.clientX - x0) / rc.width * span)));
                ttsTiersRender();
            };
            let up = () => {
                window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
                if (moved) ttsTiersSend(); else ttsTierPlay(k);
            };
            window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
        }
        // Фразы с этой переменной — по очереди: начало и продолжение вокруг
        // суммы; их громкость/темп правятся прямо здесь (меняется их дубль).
        // Стык с фразой: пауза после начала (перед первым ярусом) и до продолжения
        // (после последнего). ▶ Стык — конец начала + строка + начало продолжения.
        const TTS_JOIN_MS = 1200;
        function ttsJoinHTML(tiers, fn) {
            let first = tiers[0], last = tiers[tiers.length - 1];
            let knob = (lbl, tip, val, which) => `<span class="tts-tiers__knob" title="${tip}">${lbl}
                <button type="button" onclick="${fn}('${which}', -50)">&minus;</button><b>${val} мс</b><button type="button" onclick="${fn}('${which}', 50)">+</button></span>`;
            return knob('после начала', 'Пауза между концом начала фразы и первым ярусом (ложится в файл первого яруса)', first.pre || 0, 'pre')
                + knob('до конца', 'Пауза между последним ярусом и продолжением фразы (ложится в файл последнего яруса)', last.post || 0, 'post');
        }
        async function ttsTierJoin(which, d) {
            let tiers = ttsTR.tiers, t = which === 'pre' ? tiers[0] : tiers[tiers.length - 1];
            t[which] = Math.max(0, Math.min(1500, (t[which] || 0) + d));
            ttsTiersRender();
            await ttsTiersSend();
            ttsTierJoinPlay();
        }
        async function ttsTierJoinPlay() {
            await ttsStopPlay();
            let r = await pywebview.api.tts_tier_play(ttsCurTake().i, null, 0, TTS_JOIN_MS);
            if (r && r.error) showToast(r.error);
        }

        // Фон из файла (например, 15 с шума офиса) — под все переменные.
        function ttsBgHTML(bg) {
            if (!bg) return ` <button type="button" class="tts-reuse-chip" onclick="ttsBgPick()" title="Загрузить звук фона (шум офиса и т.п.) — подмешается под каждый ярус и паузы">фон из файла…</button>`;
            return ` <button type="button" class="tts-reuse-chip ${bg.on ? 'is-on' : ''}" onclick="ttsBgSet(${!bg.on}, null)" title="Фон «${escapeHtml(bg.name)}» (${bg.sec} с) под переменными — вкл/выкл">фон: ${escapeHtml(bg.name)}${bg.on ? ' ✓' : ''}</button>`
                + (bg.on ? `<span class="tts-tiers__knob" title="Громкость фона относительно голоса">
                    <button type="button" onclick="ttsBgSet(null, ${bg.db - 2})">&minus;</button><b>${bg.db} дБ</b><button type="button" onclick="ttsBgSet(null, ${bg.db + 2})">+</button></span>` : '')
                + `<button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsBgPick()" title="Загрузить другой файл фона">сменить</button>`;
        }
        async function ttsBgAfter(r) {
            if (!r) return;
            if (r.error) { showToast(r.error); return; }
            if (ttsBatchIsOpen()) { ttsBatch.bg = r.bg; ttsBatchRender(); if (ttsBatch.rows.length) ttsBatchPlay(0, -2); }
            else { let t = ttsCurTake(); if (t) { await ttsTiersLoad(t.i); ttsTierJoinPlay(); } }
        }
        async function ttsBgPick() {
            let r = await pywebview.api.tts_tier_bg_pick();
            if (r && r.bg) showToast(`Фон «${r.bg.name}» (${r.bg.sec} с) — под переменными. Сохранённые раньше эталоны — «Пересохранить готовые»`, 5000);
            ttsBgAfter(r);
        }
        async function ttsBgSet(on, db) { ttsBgAfter(await pywebview.api.tts_tier_bg_set(on, db)); }

        function ttsTierPhraseHTML(r) {
            let ph = r.phrase;
            if (!ph) return '<div class="tts-tiers__phrase tts-dim">Эта переменная не стоит ни в одной фразе таблицы</div>';
            let knobs = (which, snd, take) => snd ? `<span class="tts-tiers__knob" title="Громкость фразы (её дубль пересохранится)">дБ
                    <button type="button" onclick="ttsTierCtxSound('${which}', 'gain', -1)">&minus;</button><b>${snd[0] > 0 ? '+' : ''}${snd[0]}</b><button type="button" onclick="ttsTierCtxSound('${which}', 'gain', 1)">+</button></span>
                  <span class="tts-tiers__knob" title="Темп фразы">темп
                    <button type="button" onclick="ttsTierCtxSound('${which}', 'tempo', -0.03)">&minus;</button><b>${Math.round(snd[1] * 100)}%</b><button type="button" onclick="ttsTierCtxSound('${which}', 'tempo', 0.03)">+</button></span>
                  <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierOpenTake(${take})" title="Открыть дубль фразы в «Сборке»: края, вырезать, Audacity">✎</button>` : '';
            let lv = r.ctx_level !== null && r.ctx_level !== undefined
                ? `<span class="tts-dim" title="Громкость голоса на слух у стыков фраз с этой переменной (медиана) и у этой строки до выравнивания">фраза ${r.ctx_level} · строка ${r.row_level ?? '—'} LUFS</span>` : '';
            return `<div class="tts-tiers__phrase">
                <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierNav(-1)" title="Прошлая фраза с этой переменной">&#9664;</button>
                <b>Фраза ${ph.pos + 1} / ${ph.total}</b>
                <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierNav(1)" title="Следующая фраза с этой переменной">&#9654;</button>
                <span class="tts-tiers__pname">${escapeHtml(ph.name)}</span> ${lv}
                <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierResaveAll()" title="Пересобрать все уже сохранённые ярусы этого листа — с нынешней громкостью и фоном">Пересохранить готовые (${r.resave_n})</button>
              </div>
              <div class="tts-tiers__ctxrow"><span class="tts-tiers__cl">Начало</span>
                ${ph.start_saved ? `<span class="tts-tiers__ctxt" title="${escapeHtml(ph.start_text)}">${escapeHtml(ph.start_name)}</span>${knobs('start', ph.start_sound, ph.start_take)}`
                  : `<span class="tts-dim">«${escapeHtml(ph.start_name)}» ещё не записано</span>`}</div>
              <div class="tts-tiers__ctxrow"><span class="tts-tiers__cl">Конец</span>
                ${!ph.end_name && !ph.end_from && !ph.end_saved ? '<span class="tts-dim">у фразы нет продолжения, и взять не из чего</span>'
                  : ph.end_from ? `<span class="tts-tiers__ctxt">взят из «${escapeHtml(ph.end_from)}»</span> <span class="tts-dim">— ${ph.end_name ? `своё «${escapeHtml(ph.end_name)}» ещё не записано` : 'у этой фразы продолжения нет'}</span>`
                  : ph.end_saved ? `<span class="tts-tiers__ctxt" title="${escapeHtml(ph.end_text)}">${escapeHtml(ph.end_name)}</span>${knobs('end', ph.end_sound, ph.end_take)}`
                  : `<span class="tts-dim">«${escapeHtml(ph.end_name)}» ещё не записано</span>`}</div>`;
        }
        async function ttsTierNav(d) {
            await ttsTierStop();
            let res = await pywebview.api.tts_tier_ctx_nav(ttsCurTake().i, d, null);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); ttsTierPlay(-1); }
        }
        async function ttsTierCtxSound(which, field, d) {
            let ph = ttsTR.phrase, snd = which === 'start' ? ph.start_sound : ph.end_sound;
            let g = field === 'gain' ? Math.max(-12, Math.min(12, snd[0] + d)) : null;
            let tp = field === 'tempo' ? Math.round(Math.max(0.7, Math.min(1.4, snd[1] + d)) * 100) / 100 : null;
            let res = await pywebview.api.tts_tier_ctx_sound(ttsCurTake().i, which, g, tp);
            if (res && res.error) showToast(res.error);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); ttsTierPlay(-1); }
        }
        async function ttsTierOpenTake(k) {
            if (k === null || k === undefined) return;
            await ttsSelect(k);
        }
        async function ttsTierResaveAll() {
            let r = await pywebview.api.tts_tier_resave_all();
            showToast(`Пересохранено эталонов: ${r.resaved}`);
            let t = ttsCurTake(); if (t) ttsTiersLoad(t.i);
        }
        async function ttsTierKnob(k, field, d) {
            let t = ttsTR.tiers[k];
            t[field] = field === 'tempo' ? Math.round(Math.max(0.8, Math.min(1.25, t.tempo + d)) * 100) / 100
                : Math.max(-9, Math.min(9, t.gain + d));
            ttsTiersRender();
            await ttsTiersSend();
            ttsTierPlay(k);
        }
        async function ttsTierOpt(key, on) {
            let res = await pywebview.api.tts_tier_set(ttsCurTake().i, null, null, { [key]: on });
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
        }
        async function ttsTierTpl() {
            let res = await pywebview.api.tts_tier_template(ttsCurTake().i);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); showToast('Шаблон — эта строка: следующие строки разметятся по ней'); ttsLoadPrompt(); }
        }
        async function ttsTierTplApply() {
            let res = await pywebview.api.tts_tier_template_reset(ttsCurTake().i);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
        }
        async function ttsTierAutoSet(on) {
            let r = await pywebview.api.tts_tier_auto(on);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            if (ttsTR) { ttsTR.tpl.auto = r.auto; ttsTiersRender(); }
            ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt, null);
            showToast(r.auto ? 'Строки сохраняются по шаблону сразу после записи' : 'Строки снова проверяете в «Сборке»');
        }
        // прослушка сборки с любого места: бегунок по дорожке «Сборка»
        let ttsTierHeadTimer = null;
        function ttsTierHead(fromMs, durMs) {
            clearInterval(ttsTierHeadTimer);
            let span = ttsTiersSpan(), t0 = performance.now();
            let step = () => {
                let el = document.getElementById('ttsTiersHead');
                let ms = fromMs + (performance.now() - t0);
                if (!el || ms > fromMs + durMs) { if (el) el.style.display = 'none'; clearInterval(ttsTierHeadTimer); return; }
                el.style.display = 'block'; el.style.left = (100 * ms / span) + '%';
            };
            step(); ttsTierHeadTimer = setInterval(step, 40);
        }
        async function ttsTierSeek(e) {
            let rc = document.getElementById('ttsTiersAsm').getBoundingClientRect();
            if (!rc.width) return;
            await ttsTierPlayFrom(Math.max(0, Math.round((e.clientX - rc.left) / rc.width * ttsTiersSpan())));
        }
        async function ttsTierPlayFrom(ms) {
            await ttsStopPlay();
            let r = await pywebview.api.tts_tier_play(ttsCurTake().i, null, ms);
            if (r && r.error) { showToast(r.error); return; }
            if (r && r.playing) ttsTierHead(r.from, r.duration * 1000);
        }
        async function ttsTierStop() {
            clearInterval(ttsTierHeadTimer);
            let el = document.getElementById('ttsTiersHead'); if (el) el.style.display = 'none';
            await pywebview.api.tts_stop_audio();
        }
        async function ttsTierWrite(k, on) {
            let w = {};
            ttsTR.tiers.forEach(x => { w[x.k] = x.k === k ? on : x.write; });
            let res = await pywebview.api.tts_tier_set(ttsCurTake().i, null, w);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
        }
        async function ttsTierPlay(k) {
            if (k < 0) {                       // вся сумма — с секунды до первого яруса
                let st0 = ttsTR && ttsTR.ctx.start ? Math.max(0, ttsTR.ctx.start.len - 1000) : 0;
                return ttsTierPlayFrom(st0);
            }
            await ttsStopPlay();
            clearInterval(ttsTierHeadTimer);
            let r = await pywebview.api.tts_tier_play(ttsCurTake().i, k, null);
            if (r && r.error) showToast(r.error);
        }

        // ----- «Синтез…» в «Сборке»: добить фразу синтезом -----
        // Нажимаете слово, с которого начинается синтез. Синтезируется остаток
        // фразы, начиная на пару слов раньше (перекрытие): на стыке выбираете,
        // где резать — так склейка живого голоса и синтеза звучит естественно.
        let ttsTS = null;
        async function ttsTsynToggle() {
            let t = ttsCurTake();
            if (!t) return;
            if (ttsTS && ttsTS.i === t.i) { ttsTS = null; ttsTsynRender(); return; }
            let r = await pywebview.api.tts_take_synth_info(t.i);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            ttsTS = { i: t.i, words: r.words, start: r.start, overlap: 2, text: null,
                      mode: r.refs.length ? r.refs[0].mode : 'auto', refs: r.refs, fake: r.fake,
                      tail_word: r.tail_word, noise: r.noise, lang: r.lang, busy: r.busy };
            ttsTsynRender();
        }
        const ttsTsynText = () => ttsTS.text !== null ? ttsTS.text
            : ttsTS.words.slice(Math.max(0, ttsTS.start - ttsTS.overlap)).join(' ');
        // Слово-запас в конце: сервис синтеза срезает конец — режется запас, а не фраза.
        const ttsSynTailOn = () => { try { return localStorage.getItem('gvox_syn_tail') !== '0'; } catch (e) { return true; } };
        function ttsSynTailToggle() {
            try { localStorage.setItem('gvox_syn_tail', ttsSynTailOn() ? '0' : '1'); } catch (e) {}
            ttsTsynRender();
        }
        function ttsTsynRender() {
            let el = document.getElementById('ttsTsyn');
            if (!el) return;
            if (!ttsTS) { el.style.display = 'none'; el.innerHTML = ''; return; }
            el.style.display = '';
            let s = ttsTS, ov0 = Math.max(0, s.start - s.overlap);
            let words = s.words.map((w, k) => {
                let cls = k >= s.start ? 'is-syn' : (k >= ov0 ? 'is-ovl' : 'is-rec');
                return `<button type="button" class="tts-tsyn__w ${cls}" onclick="ttsTsynSet({start: ${k}})" title="Синтез — с этого слова">${escapeHtml(w)}</button>`;
            }).join('');
            let chip = (on, label, js, dis) => `<button type="button" class="chip ${on ? 'chip-mode--active' : ''}" onclick="${js}" ${dis ? 'disabled' : ''}>${label}</button>`;
            el.innerHTML = `
                <div class="tts-tsyn__head"><b>${s.fake ? 'Пересинтез' : 'Добить синтезом'}</b>
                    <span class="tts-dim">нажмите слово, с которого начинается синтез ·
                    <span class="tts-tsyn__lg is-rec">записано</span> <span class="tts-tsyn__lg is-ovl">перекрытие</span> <span class="tts-tsyn__lg is-syn">синтез</span></span></div>
                <div class="tts-tsyn__words">${words}</div>
                <div class="tts-tsyn__row">
                    <span class="tts-dim">Перекрытие</span>
                    ${[0, 1, 2, 3].map(n => chip(s.overlap === n, n === 0 ? 'нет' : `${n} сл.`, `ttsTsynSet({overlap: ${n}})`)).join('')}
                    ${chip(s.start === 0, 'всю фразу', 'ttsTsynSet({start: 0})')}
                </div>
                <div class="tts-tsyn__row">
                    <span class="tts-dim">Образец голоса</span>
                    ${s.refs.map(r => chip(s.mode === r.mode, escapeHtml(r.label), `ttsTsynSet({mode: '${r.mode}'})`, r.mode === 'take' && s.start === 0)).join('')
                      || '<span class="tts-dim">нет — запишите хотя бы одну фразу на этом языке</span>'}
                    <span class="tts-dim" style="margin-left:14px">В конце</span>
                    ${chip(ttsSynTailOn(), `+ «${escapeHtml(s.tail_word)}» (запас, срежете)`, 'ttsSynTailToggle()')}
                </div>
                <div class="tts-tsyn__row">${ttsNoiseChips(s.noise, 'ttsTsynNoise')}
                </div>
                <div class="tts-tsyn__row">
                    <input class="tts-tsyn__text" id="ttsTsynText" value="${escapeHtml(ttsTsynText())}" title="Что синтезировать — можно поправить"
                        oninput="ttsTS.text = this.value">
                    ${s.busy ? '<span class="tts-dim"><span class="lv-spin"></span> синтез…</span>'
                        : '<button class="btn-ghost btn-ghost--info btn-ghost--compact" onclick="ttsTsynRun()">Синтезировать</button>'}
                    <button class="btn-ghost btn-ghost--compact" onclick="ttsTS = null; ttsTsynRender()">Закрыть</button>
                </div>`;
        }
        // Фон комнаты под синтезом: шум из пауз образца голоса — синтез звучит
        // «из той же комнаты», что и живые фразы, стык при склейке незаметнее.
        function ttsNoiseChips(n, fn) {
            n = n || { on: true, db: 0 };
            let chip = (on, label, js, tip) => `<button type="button" class="chip ${on ? 'chip-mode--active' : ''}" onclick="${js}" title="${tip}">${label}</button>`;
            return `<span class="tts-dim" title="Шум комнаты и микрофона из пауз образца голоса подкладывается под синтез — для реализма">Фон комнаты</span>`
                + chip(!n.on, 'выкл', `${fn}(false, 0)`, 'Синтез без фона — «студийно чистый»')
                + chip(n.on && n.db < 0, 'тише', `${fn}(true, -6)`, 'Фон на 6 дБ тише, чем в образце')
                + chip(n.on && n.db === 0, 'как в записи', `${fn}(true, 0)`, 'Фон того же уровня, что в вашей записи')
                + chip(n.on && n.db > 0, 'громче', `${fn}(true, 6)`, 'Фон на 6 дБ громче, чем в образце');
        }
        async function ttsTsynNoise(on, db) {
            let r = await pywebview.api.tts_synth_noise(on, db);
            if (ttsTS) { ttsTS.noise = r; ttsTsynRender(); }
        }
        async function ttsSynthNoise(on, db) {
            await pywebview.api.tts_synth_noise(on, db);
            ttsSynthLoad(true);
        }
        function ttsTsynSet(o) {
            if (!ttsTS || ttsTS.busy) return;
            if (o.start !== undefined || o.overlap !== undefined) ttsTS.text = null;     // текст — заново по словам
            Object.assign(ttsTS, o);
            ttsTsynRender();
        }
        async function ttsTsynRun() {
            if (!ttsTS || ttsTS.busy) return;
            let mode = ttsTS.start === 0 && ttsTS.mode === 'take' ? 'auto' : ttsTS.mode;
            let r = await pywebview.api.tts_take_synth(ttsTS.i, ttsTS.start, ttsTS.overlap, ttsTsynText(), mode, ttsSynTailOn());
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            ttsTS.busy = true;
            ttsTsynRender();
            showToast(`Синтезирую (${r.lang === 'kz' ? 'казахский' : 'русский'}, образец — ${r.ref})…`);
        }
        async function ttsPromptSynth() {
            if (!tts || !tts.loaded) return;
            let r = await pywebview.api.tts_prompt_synth(null, ttsSynTailOn(), 'auto');
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            showToast(`Синтезирую фразу${r.count > 1 ? ` (${r.count} кусочка)` : ''}, образец — ${r.ref}…`);
        }
        async function ttsTakeSynthEvent(p) {
            if (ttsTS) ttsTS.busy = false;
            if (p.error) { showToast('Синтез: ' + p.error); ttsTsynRender(); return; }
            if (p.state) tts = p.state;
            if (p.new) {
                // фраза целиком синтезом — сразу в «Сборку»
                let k = tts.takes.findIndex(t => t.file === p.file);
                if (k >= 0) tts.index = k;
                ttsRender();
                ttsShowAssembly(true);
                ttsTogglePlay();
            } else {
                let cur = ttsCurTake();
                ttsRenderRail();
                if (cur && cur.file === p.file) {
                    ttsTS = null; ttsTsynRender();
                    await ttsEditorLoad(true);
                    if (ttsEd) { ttsEdFit(); ttsEditorDraw(); }          // новый клип — сразу виден целиком
                }
            }
            if (p.message) showToast(p.message, 5000);
        }

        // ----- громкость и темп дубля -----
        // Темп — без смены высоты голоса (ffmpeg atempo). Слушаете и сохраняете
        // ровно с этими настройками; сохранённый дубль пересобирается сам.
        function ttsSoundBarHTML(t) {
            let g = +(t.gain_db || 0), k = Math.round((t.tempo || 1) * 100);
            return `<div class="tts-snd">
                <label class="tts-snd__item" title="Громче / тише относительно выровненного уровня (−18 дБ). Пики не перегружаются">
                    <span class="tts-snd__lbl">Громкость</span>
                    <input type="range" id="ttsGain" min="-12" max="12" step="0.5" value="${g}"
                        oninput="ttsSoundLabel()" onchange="ttsSoundApply(this)">
                    <b id="ttsGainTxt">${ttsGainText(g)}</b></label>
                <label class="tts-snd__item" title="Темп речи без изменения высоты голоса">
                    <span class="tts-snd__lbl">Темп</span>
                    <input type="range" id="ttsTempo" min="70" max="140" step="1" value="${k}"
                        oninput="ttsSoundLabel()" onchange="ttsSoundApply(this)">
                    <b id="ttsTempoTxt">${k}%</b></label>
                <button class="btn-ghost btn-ghost--compact" onclick="ttsSoundReset()" title="Громкость 0 дБ, темп 100%" ${g === 0 && k === 100 ? 'disabled' : ''}>Звук по умолчанию</button>
            </div>`;
        }
        const ttsGainText = g => `${g > 0 ? '+' : ''}${(+g).toFixed(1).replace('.0', '')} дБ`;
        function ttsSoundLabel() {
            let g = document.getElementById('ttsGain'), k = document.getElementById('ttsTempo');
            if (g) document.getElementById('ttsGainTxt').innerText = ttsGainText(+g.value);
            if (k) document.getElementById('ttsTempoTxt').innerText = k.value + '%';
        }
        async function ttsSoundApply(el, values) {
            let t = ttsCurTake();
            if (!t) return;
            if (el) el.blur();                       // Space / Enter снова работают
            let g = values ? values[0] : +document.getElementById('ttsGain').value;
            let k = values ? values[1] : +document.getElementById('ttsTempo').value / 100;
            let wasPlaying = ttsPlayingIdx === t.i;
            await ttsStopPlay();
            let res = await pywebview.api.tts_take_sound(t.i, g, k);
            if (!res) return;
            if (res.error) showToast(res.error);
            if (res.takes) { tts = res; ttsRenderRail(); ttsRenderCurrent(); ttsRenderAssembly(); }
            if (res.resaved) showToast('Сохранённый файл обновлён');
            if (wasPlaying) ttsTogglePlay();          // слушали — сразу с новым звуком
        }
        function ttsSoundReset() { ttsSoundApply(null, [0, 1]); }

        // ----- дорожка «Сборки»: клипы, как в Audacity, прямо здесь -----
        // Дубль — клипы на дорожке. Клип = кусок исходной записи [a, b] без
        // вырезов, стоящий с позиции pos. Клик — слушать с этого места;
        // полоска сверху клипа — тащить клип; края — подрезать (можно
        // вытянуть наружу); выделение + X — вырезать середину (красная
        // метка — клик возвращает). Ctrl + колесо — масштаб, колесо — листать.
        // Клипы звучат по порядку: промежуток — тишина, наезд — хвост
        // предыдущего не звучит (затемнён). Правка пишется в файл сразу и
        // требует повторной прослушки перед сохранением.
        let ttsEd = null;
        const TTS_ED_HIT = 7, TTS_ED_HEAD = 16, TTS_ED_RULER = 14;

        async function ttsEditorLoad(force) {
            let t = ttsCurTake();
            if (!t) { ttsEd = null; return; }
            if (ttsEd && ttsEd.i === t.i && !force) { ttsEditorBind(); ttsEditorDraw(); return; }
            let want = t.i, keepView = force && ttsEd && ttsEd.i === t.i ? { zoom: ttsEd.zoom, scroll: ttsEd.scroll } : null;
            let r = await pywebview.api.tts_clips_load(t.i);
            if (!tts || tts.index !== want) return;
            if (!r || r.error) { ttsEd = null; let c = document.getElementById('ttsEdTime'); if (c) c.innerText = r && r.error || ''; return; }
            ttsEd = { ...r, sel: null, drag: null, play: null, zoom: null, scroll: 0 };
            ttsEditorBind();
            if (keepView) Object.assign(ttsEd, keepView); else ttsEdFit();
            ttsEditorDraw();
        }

        const tlRanges = c => {
            let out = [], cur = c.a;
            [...(c.cuts || [])].map(([x, y]) => [Math.max(c.a, x), Math.min(c.b, y)]).filter(([x, y]) => y > x)
                .sort((p, q) => p[0] - q[0]).forEach(([x, y]) => { if (x > cur) out.push([cur, x]); cur = Math.max(cur, y); });
            if (c.b > cur) out.push([cur, c.b]);
            return out;
        };
        const tlLen = c => tlRanges(c).reduce((acc, [x, y]) => acc + y - x, 0);
        const tlOrder = () => ttsEd.clips.map((c, k) => k).sort((p, q) => ttsEd.clips[p].pos - ttsEd.clips[q].pos);
        const tlBase = () => Math.min(...ttsEd.clips.map(c => c.pos));
        const tlTotal = () => Math.max(...ttsEd.clips.map(c => c.pos + tlLen(c)));
        // Где кончается звучание клипа: следующий по дорожке клип его обрывает.
        function tlLimit(k) {
            let ord = tlOrder(), j = ord.indexOf(k);
            return j + 1 < ord.length ? ttsEd.clips[ord[j + 1]].pos : Infinity;
        }
        // Время на дорожке ↔ место в исходной записи для клипа.
        function tlRawAt(c, t) {
            let off = Math.max(0, t - c.pos);
            for (let [x, y] of tlRanges(c)) { if (off <= y - x) return x + off; off -= y - x; }
            return c.b;
        }
        function tlTimeOfRaw(c, ms) {
            let off = 0;
            for (let [x, y] of tlRanges(c)) { if (ms <= y) return c.pos + off + Math.max(0, ms - x); off += y - x; }
            return c.pos + off;
        }
        // Соседние клипы — на разных дорожках (через одну), чтобы наезд был виден.
        function tlLane(k) {
            let multi = ttsEd.clips.length > 1, H = document.getElementById('ttsEdCanvas').clientHeight;
            let h = (H - TTS_ED_RULER) / (multi ? 2 : 1), l = multi ? tlOrder().indexOf(k) % 2 : 0;
            return { top: TTS_ED_RULER + l * h, h };
        }
        const tlW = () => { let cv = document.getElementById('ttsEdCanvas'); return cv ? cv.clientWidth : 800; };
        const tlX = t => (t - ttsEd.scroll) * ttsEd.zoom;
        const tlT = x => x / ttsEd.zoom + ttsEd.scroll;

        function ttsEdFit() {
            if (!ttsEd) return;
            let base = tlBase(), total = tlTotal() - base;
            ttsEd.zoom = tlW() / Math.max(800, total * 1.08);
            ttsEd.scroll = base - total * 0.04;
        }
        function ttsEdZoom(k, atX) {
            if (!ttsEd) return;
            let x = atX === undefined ? tlW() / 2 : atX, t = tlT(x);
            ttsEd.zoom = Math.max(0.02, Math.min(3, ttsEd.zoom * k));
            ttsEd.scroll = t - x / ttsEd.zoom;
            ttsEditorDraw();
        }

        function ttsEditorDraw() {
            let canvas = document.getElementById('ttsEdCanvas');
            if (!canvas || !ttsEd) return;
            canvas.classList.toggle('is-multi', ttsEd.clips.length > 1);
            let dpr = window.devicePixelRatio || 1, W = canvas.clientWidth, H = canvas.clientHeight;
            if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
                canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
            }
            let ctx = canvas.getContext('2d');
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, W, H);
            // линейка времени (от начала дорожки)
            let base = tlBase(), stepMs = [100, 250, 500, 1000, 2000, 5000].find(v => v * ttsEd.zoom >= 60) || 10000;
            ctx.font = '600 9.5px ui-monospace, monospace'; ctx.textBaseline = 'top';
            for (let tt = Math.ceil(tlT(0) / stepMs) * stepMs; tt < tlT(W); tt += stepMs) {
                let x = tlX(tt);
                ctx.fillStyle = 'rgba(255,255,255,0.12)'; ctx.fillRect(x, 0, 1, TTS_ED_RULER - 4);
                ctx.fillStyle = 'rgba(146,154,171,0.7)'; ctx.fillText(((tt - base) / 1000).toFixed(stepMs < 1000 ? 2 : 1), x + 3, 1);
            }
            let colors = ['#4d95ea', '#2bc0cf', '#9270ea', '#eeac3e'];
            tlOrder().forEach((k, j) => {
                let c = ttsEd.clips[k], len = tlLen(c), limit = tlLimit(k);
                let x0 = tlX(c.pos), x1 = tlX(c.pos + len), col = colors[j % colors.length];
                let multi = ttsEd.clips.length > 1, { top, h: laneH } = tlLane(k), bot = top + laneH;
                // тело и полоска для перетаскивания
                ctx.fillStyle = 'rgba(255,255,255,0.045)'; ctx.fillRect(x0, top, x1 - x0, laneH);
                if (multi) {
                    ctx.fillStyle = col; ctx.globalAlpha = 0.55; ctx.fillRect(x0, top, x1 - x0, TTS_ED_HEAD); ctx.globalAlpha = 1;
                    ctx.fillStyle = '#fff'; ctx.font = '700 10px system-ui, sans-serif'; ctx.textBaseline = 'middle';
                    ctx.save(); ctx.beginPath(); ctx.rect(x0, top, Math.max(0, x1 - x0), TTS_ED_HEAD); ctx.clip();
                    ctx.fillText(`клип ${j + 1}  ⇔`, x0 + 6, top + TTS_ED_HEAD / 2); ctx.restore();
                }
                let wTop = top + (multi ? TTS_ED_HEAD : 0), mid = wTop + (bot - wTop) / 2, half = (bot - wTop) / 2 - 3;
                // волна по звучащим кускам
                let off = 0;
                ctx.lineWidth = 1;
                for (let [r0, r1] of tlRanges(c)) {
                    for (let ms = r0; ms < r1; ms += ttsEd.bucket) {
                        let tt = c.pos + off + (ms - r0), x = tlX(tt);
                        if (x < -2 || x > W + 2) continue;
                        let amp = Math.max(0.5, (c.peaks[Math.floor((ms - c.lo) / ttsEd.bucket)] || 0) * half);
                        ctx.strokeStyle = tt >= limit ? 'rgba(146,154,171,0.25)' : col;
                        ctx.beginPath(); ctx.moveTo(x, mid - amp); ctx.lineTo(x, mid + amp); ctx.stroke();
                    }
                    off += r1 - r0;
                }
                // хвост под следующим клипом — не звучит
                if (limit < c.pos + len) { let xl = tlX(limit); ctx.fillStyle = 'rgba(8,10,14,0.6)'; ctx.fillRect(xl, wTop, x1 - xl, bot - wTop); }
                // метки вырезов (клик — вернуть)
                (c.cuts || []).forEach(([c0]) => {
                    let x = tlX(tlTimeOfRaw(c, c0));
                    ctx.fillStyle = 'rgba(239,91,80,0.95)'; ctx.fillRect(x - 1, wTop, 2, bot - wTop);
                    ctx.beginPath(); ctx.moveTo(x - 5, wTop); ctx.lineTo(x + 5, wTop); ctx.lineTo(x, wTop + 7); ctx.fill();
                });
                // ручки краёв
                ctx.fillStyle = '#eef1f6';
                [x0, x1].forEach((x, side) => { ctx.fillRect(x - 1, top, 2, laneH); ctx.fillRect(side ? x - 7 : x, bot - 12, 7, 12); });
            });
            if (ttsEd.sel) {
                let c = ttsEd.clips[ttsEd.sel.k];
                let a = Math.max(c.pos, Math.min(ttsEd.sel.t0, ttsEd.sel.t1)), b = Math.min(c.pos + tlLen(c), Math.max(ttsEd.sel.t0, ttsEd.sel.t1));
                let ln = tlLane(ttsEd.sel.k);
                ctx.fillStyle = 'rgba(122,162,255,0.28)'; ctx.fillRect(tlX(a), ln.top, tlX(b) - tlX(a), ln.h);
            }
            if (ttsEd.play != null) { ctx.fillStyle = '#2fbf7d'; ctx.fillRect(tlX(ttsEd.play) - 1, 0, 2, H); }
            let time = document.getElementById('ttsEdTime');
            if (time) {
                let cuts = ttsEd.clips.reduce((acc, c) => acc + (c.cuts || []).length, 0);
                let tk = ((tts.takes[ttsEd.i] || {}).tempo) || 1;
                time.innerText = `${((tlTotal() - base) / 1000).toFixed(2)} с${Math.abs(tk - 1) > 0.004 ? ` · в темпе ${Math.round(tk * 100)}% — ${((tlTotal() - base) / 1000 / tk).toFixed(2)} с` : ''}${ttsEd.clips.length > 1 ? ` · клипов ${ttsEd.clips.length}` : ''}`
                    + `${cuts ? ` · вырезов ${cuts}` : ''}${ttsEd.audacity ? ' · правлен в Audacity' : ''}`;
            }
            let cut = document.getElementById('ttsEdCutBtn');
            if (cut) cut.disabled = !ttsEd.sel;
            ttsEdHistButtons();
        }

        // Что под мышью: ручка края / полоска клипа / метка выреза / тело / пусто.
        function tlHit(x, y) {
            let multi = ttsEd.clips.length > 1;
            let ord = tlOrder().reverse().filter(k => {   // только клипы своей дорожки
                let { top, h } = tlLane(k); return !multi || (y >= top && y < top + h);
            });
            for (let k of ord) {
                let c = ttsEd.clips[k], x0 = tlX(c.pos), x1 = tlX(c.pos + tlLen(c));
                if (Math.abs(x - x0) <= TTS_ED_HIT) return { kind: 'trim', k, side: 'a' };
                if (Math.abs(x - x1) <= TTS_ED_HIT) return { kind: 'trim', k, side: 'b' };
            }
            for (let k of ord) {
                let c = ttsEd.clips[k], x0 = tlX(c.pos), x1 = tlX(c.pos + tlLen(c));
                if (x < x0 || x > x1) continue;
                let { top } = tlLane(k);
                if (multi && y >= top && y < top + TTS_ED_HEAD) return { kind: 'move', k };
                let cutIdx = (c.cuts || []).findIndex(([c0]) => Math.abs(tlX(tlTimeOfRaw(c, c0)) - x) <= 5);
                if (cutIdx >= 0) return { kind: 'uncut', k, cutIdx };
                return { kind: 'body', k };
            }
            return { kind: 'empty' };
        }

        function ttsEdPos(e) {
            let r = document.getElementById('ttsEdCanvas').getBoundingClientRect();
            return { x: e.clientX - r.left, y: e.clientY - r.top };
        }

        window.addEventListener('mousemove', e => {
            if (!ttsEd || !ttsEd.drag || !document.getElementById('ttsEdCanvas')) return;
            let { x } = ttsEdPos(e), t = tlT(x), d = ttsEd.drag, c = ttsEd.clips[d.k];
            d.moved = d.moved || Math.abs(x - d.x0) > 3;
            if (d.kind === 'trim' && d.side === 'a') {
                let na = Math.round(Math.max(c.lo, Math.min(c.b - 80, d.a0 + (t - d.t0))));
                c.pos = Math.max(0, d.pos0 + (na - d.a0)); c.a = na;
            } else if (d.kind === 'trim') {
                c.b = Math.round(Math.max(c.a + 80, Math.min(c.hi, d.b0 + (t - d.t0))));
            } else if (d.kind === 'move') {
                c.pos = Math.max(0, Math.round(d.pos0 + (t - d.t0)));
            } else if (d.kind === 'body' && d.moved) {
                ttsEd.sel = { k: d.k, t0: d.t0, t1: t };
            }
            ttsEditorDraw();
        });
        window.addEventListener('mouseup', e => {
            if (!ttsEd || !ttsEd.drag) return;
            let d = ttsEd.drag; ttsEd.drag = null;
            if ((d.kind === 'trim' || d.kind === 'move') && d.moved) {
                ttsEdRemember(d.kind === 'move' ? `сдвиг клипа ${d.k + 1}` : 'подрезка края', d.snap);
                ttsEditorApply(); return;
            }
            if (d.kind === 'body' && d.moved && ttsEd.sel && Math.abs(ttsEd.sel.t1 - ttsEd.sel.t0) >= 15) { ttsEditorDraw(); return; }
            // Просто клик — слушать с этого места.
            ttsEd.sel = null;
            ttsPlayFrom(d.t0);
        });

        function ttsEditorBind() {
            let canvas = document.getElementById('ttsEdCanvas');
            if (!canvas || canvas.dataset.bound) return;
            canvas.dataset.bound = '1';
            canvas.addEventListener('mousedown', e => {
                if (!ttsEd || e.button !== 0) return;
                e.preventDefault();
                let { x, y } = ttsEdPos(e), t = tlT(x), h = tlHit(x, y);
                if (h.kind === 'uncut') {
                    ttsEdRemember('возврат выреза');
                    let c = ttsEd.clips[h.k], len0 = tlLen(c), at = tlTimeOfRaw(c, c.cuts[h.cutIdx][0]);
                    c.cuts.splice(h.cutIdx, 1); ttsEd.sel = null;
                    ttsEdRipple(c, at, tlLen(c) - len0);
                    ttsEditorApply(); return;
                }
                let c = h.k !== undefined ? ttsEd.clips[h.k] : null;
                ttsEd.drag = { kind: h.kind, side: h.side, k: h.k, x0: x, t0: t, moved: false,
                               a0: c && c.a, b0: c && c.b, pos0: c && c.pos,
                               snap: (h.kind === 'trim' || h.kind === 'move') ? ttsEdSnap() : null };
                if (h.kind !== 'body') ttsEd.sel = null;
            });
            canvas.addEventListener('mousemove', e => {
                if (!ttsEd || ttsEd.drag) return;
                let { x, y } = ttsEdPos(e), h = tlHit(x, y);
                canvas.style.cursor = h.kind === 'trim' ? 'ew-resize' : h.kind === 'move' ? 'grab'
                    : h.kind === 'uncut' ? 'pointer' : 'text';
            });
            canvas.addEventListener('wheel', e => {
                if (!ttsEd) return;
                e.preventDefault();
                if (e.ctrlKey || e.metaKey) ttsEdZoom(e.deltaY < 0 ? 1.25 : 0.8, ttsEdPos(e).x);
                else { ttsEd.scroll += (e.deltaY || e.deltaX) / ttsEd.zoom * 0.6; ttsEditorDraw(); }
            }, { passive: false });
        }

        function ttsEditorCut() {
            if (!ttsEd || !ttsEd.sel) return;
            let c = ttsEd.clips[ttsEd.sel.k];
            let t0 = Math.min(ttsEd.sel.t0, ttsEd.sel.t1), t1 = Math.max(ttsEd.sel.t0, ttsEd.sel.t1);
            let r0 = Math.round(tlRawAt(c, t0)), r1 = Math.round(tlRawAt(c, t1));
            ttsEd.sel = null;
            if (r1 - r0 < 15) { ttsEditorDraw(); return; }
            ttsEdRemember(`вырез ${((r1 - r0) / 1000).toFixed(2)} с`);
            let len0 = tlLen(c);
            c.cuts = (c.cuts || []).concat([[r0, r1]]);
            ttsEdRipple(c, t1, tlLen(c) - len0);
            ttsEditorApply();
        }

        // ----- отмена по шагам в «Сборке»: Ctrl+Z — отменить, Ctrl+Y / Ctrl+Shift+Z — вернуть -----
        // Своя история у каждого дубля (по файлу), до 100 шагов. Шаг — подрезка
        // края, сдвиг клипа, вырез, возврат выреза, «Сбросить».
        const ttsEdHist = {};
        const TTS_ED_HIST_MAX = 100;
        function ttsEdHistOf() {
            let t = ttsEd && tts && tts.takes[ttsEd.i];
            if (!t) return null;
            return ttsEdHist[t.file] || (ttsEdHist[t.file] = { undo: [], redo: [] });
        }
        const ttsEdSnap = () => ttsEd.clips.map(c => ({ a: c.a, b: c.b, pos: c.pos, cuts: (c.cuts || []).map(x => [...x]) }));
        function ttsEdRemember(label, snap) {
            let h = ttsEdHistOf();
            if (!h) return;
            h.undo.push({ label, clips: snap || ttsEdSnap(), seq: ++ttsActSeq });
            if (h.undo.length > TTS_ED_HIST_MAX) h.undo.shift();
            h.redo = [];                                 // новое действие — «вернуть» больше нечего
            ttsEdHistButtons();
        }
        function ttsEdHistButtons() {
            let h = ttsEdHistOf(), u = document.getElementById('ttsEdUndo'), r = document.getElementById('ttsEdRedo');
            if (u) { u.disabled = !(h && h.undo.length); u.title = h && h.undo.length ? `Отменить: ${h.undo[h.undo.length - 1].label} (Ctrl+Z)` : 'Отменять нечего (Ctrl+Z)'; }
            if (r) { r.disabled = !(h && h.redo.length); r.title = h && h.redo.length ? `Вернуть: ${h.redo[h.redo.length - 1].label} (Ctrl+Y)` : 'Возвращать нечего (Ctrl+Y)'; }
        }
        async function ttsEdUndo(redo) {
            if (!ttsEd || ttsEd.drag) return;
            let h = ttsEdHistOf();
            let from = h && (redo ? h.redo : h.undo), to = h && (redo ? h.undo : h.redo);
            if (!from || !from.length) { showToast(redo ? 'Возвращать нечего' : 'Отменять нечего'); return; }
            let step = from.pop();
            to.push({ label: step.label, clips: ttsEdSnap(), seq: ++ttsActSeq });
            step.clips.forEach((sn, k) => {
                let c = ttsEd.clips[k];
                if (c) { c.a = sn.a; c.b = sn.b; c.pos = sn.pos; c.cuts = sn.cuts.map(x => [...x]); }
            });
            ttsEd.sel = null;
            ttsEditorDraw();
            await ttsEditorApply();
            ttsEdHistButtons();
            showToast((redo ? 'Вернул: ' : 'Отменил: ') + step.label);
        }

        // Вырез/возврат куска сдвигает клипы после него — склейка не рвётся.
        function ttsEdRipple(c, from, delta) {
            if (!delta) return;
            ttsEd.clips.forEach(o => { if (o !== c && o.pos >= from - 1) o.pos = Math.max(0, o.pos + delta); });
        }

        async function ttsEditorApply() {
            if (!ttsEd) return;
            await ttsStopPlay();
            let clips = ttsEd.clips.map(c => ({ raw: c.raw, a: c.a, b: c.b, pos: c.pos, cuts: c.cuts || [] }));
            let res = await pywebview.api.tts_clips_apply(ttsEd.i, clips);
            if (res && res.error) { showToast(res.error); ttsEditorLoad(true); return; }
            tts = res;
            ttsEd.audacity = false;
            ttsRenderRail(); ttsRenderCurrent();
            ttsEditorDraw();
        }

        async function ttsEditorReset() {
            if (!ttsEd) return;
            ttsEdRemember('сброс');                      // и «Сбросить» можно отменить
            await ttsStopPlay();
            tts = await pywebview.api.tts_editor_reset(ttsEd.i);
            ttsEd = null;
            ttsRender();
        }

        // Слушать с места на дорожке (t — время дорожки).
        async function ttsPlayFrom(t) {
            if (!ttsEd) return;
            await ttsStopPlay();
            let base = tlBase(), from = Math.max(0, Math.round(t - base));
            let g = ++ttsPlayGen;
            ttsPlayPending = true;
            let res = await pywebview.api.tts_play_from(ttsEd.i, from);
            if (g === ttsPlayGen) ttsPlayPending = false;
            if (g !== ttsPlayGen || !ttsEd) return;      // пока запускалось — нажали другое
            if (!res || !res.playing) { if (res && res.error) showToast(res.error); return; }
            ttsPlayingIdx = ttsEd.i;
            ttsRenderRail(); ttsRenderCurrent();
            ttsEditorPlayhead(res.duration, res.from, g, res.tempo);
            clearTimeout(ttsPlayTimer);
            let i = ttsEd.i;
            ttsPlayTimer = setTimeout(() => {
                if (g !== ttsPlayGen) return;
                ttsPlayingIdx = -1;
                pywebview.api.tts_select(i).then(st => { tts = st; ttsRenderRail(); ttsRenderCurrent(); });
            }, res.duration * 1000 + 120);
        }

        // Бегунок по дорожке во время прослушки (время файла = время дорожки).
        function ttsEditorPlayhead(duration, fromMs, gen, tempo) {
            if (!ttsEd) return;
            // Темп ≠ 100% — бегунок идёт по дорожке (время записи) быстрее/медленнее.
            let k = tempo || 1;
            let t0 = performance.now(), i = ttsEd.i, start = tlBase() + (fromMs || 0), end = start + duration * 1000 * k;
            let g = gen === undefined ? ttsPlayGen : gen;
            let step = () => {
                if (g !== ttsPlayGen) return;            // бегунок прежнего запуска — тихо уходим
                if (!ttsEd || ttsEd.i !== i || ttsPlayingIdx !== i) { if (ttsEd) { ttsEd.play = null; ttsEditorDraw(); } return; }
                let pos = start + (performance.now() - t0) * k;
                if (pos > end) { ttsEd.play = null; ttsEditorDraw(); return; }
                ttsEd.play = pos;
                ttsEditorDraw();
                requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        }

        // ----- Audacity: дубль туда и правка обратно -----
        let ttsAudacitySent = -1;
        async function ttsSendToAudacity(silent) {
            let t = ttsCurTake();
            if (!t) return;
            let res = await pywebview.api.tts_send_to_audacity(t.i);
            if (res && res.error) { if (!silent) showBeautifulAlert('⚠️ ' + escapeHtml(res.error)); return; }
            ttsAudacitySent = t.i;
            if (res && res.fragments) showToast(`В Audacity — ${res.fragments.length} фрагм. на одной дорожке: склейте и нажмите «Сохранить из Audacity»`, 5000);
        }

        async function ttsSaveFromAudacity() {
            let t = ttsCurTake();
            if (!t) return;
            await ttsStopPlay();
            let res = await pywebview.api.tts_save_from_audacity(t.i);
            if (res && res.error) { showBeautifulAlert('⚠️ ' + escapeHtml(res.error)); return; }
            tts = res;
            ttsEd = null;
            showToast(`Сохранено из Audacity: ${res.saved_name}.wav`);
            ttsRender();
            if (document.getElementById('stage4-tts').classList.contains('show-assembly') && ttsRec.on) ttsShowAssembly(false);
        }

        async function ttsTakeFromAudacity() {
            let t = ttsCurTake();
            if (!t) return;
            await ttsStopPlay();
            let res = await pywebview.api.tts_take_from_audacity(t.i);
            if (res && res.error) { showBeautifulAlert('⚠️ ' + escapeHtml(res.error)); return; }
            tts = res;
            ttsEd = null;
            ttsRender();
            showToast('Правка из Audacity — в дубле. Прослушайте и сохраните');
        }

        async function ttsSelect(i) {
            await ttsStopPlay();
            tts = await pywebview.api.tts_select(i);
            ttsRender();
        }

        async function ttsStep(dir) {
            if (!tts || !tts.takes.length) return;
            let i = Math.max(0, Math.min(tts.takes.length - 1, tts.index + dir));
            if (i !== tts.index) { await ttsSelect(i); ttsTogglePlay(); }
        }

        async function ttsStopPlay() {
            clearTimeout(ttsPlayTimer);
            let pending = ttsPlayPending;
            ttsPlayGen++;                              // прежний запуск — уже не наш
            ttsPlayPending = false;
            if (ttsPlayingIdx >= 0 || pending) { ttsPlayingIdx = -1; await pywebview.api.tts_stop_audio(); }
        }

        async function ttsTogglePlay() {
            let t = ttsCurTake();
            if (!t) return;
            if (ttsPlayingIdx === t.i) { await ttsStopPlay(); ttsRender(); return; }
            clearTimeout(ttsPlayTimer);
            let g = ++ttsPlayGen;
            ttsPlayPending = true;
            let res = await pywebview.api.tts_play(t.i);
            if (g === ttsPlayGen) ttsPlayPending = false;
            if (g !== ttsPlayGen) return;                // пока запускалось — нажали другое
            if (!res || !res.playing) { if (res && res.error) showToast(res.error); return; }
            ttsPlayingIdx = t.i;
            ttsRenderRail(); ttsRenderCurrent();
            ttsEditorPlayhead(res.duration, 0, g, res.tempo);
            ttsPlayTimer = setTimeout(() => {
                if (g !== ttsPlayGen) return;
                // Отыграл до конца — считаем прослушанным (бэкенд сверит по времени).
                ttsPlayingIdx = -1;
                pywebview.api.tts_select(t.i).then(st => { tts = st; ttsRender(); });
            }, res.duration * 1000 + 120);
        }

        async function ttsPlayUnit(id) {
            await ttsStopPlay();
            await pywebview.api.tts_play_unit(id);
        }

        let ttsApproving = false;
        async function ttsApprove() {
            let t = ttsCurTake();
            if (!t || ttsApproving) return;
            if (t.unit === null) { ttsOpenUnits('assign'); return; }
            ttsApproving = true;
            try {
                await ttsStopPlay();                    // играет — останавливаем и сохраняем сразу
                let res = await pywebview.api.tts_approve(t.i);
                if (res && res.error) { showToast(res.error); return; }
                tts = res;
                if (res.tiers_saved) {
                    let w = res.tiers_saved.written.length, sk = res.tiers_saved.skipped;
                    showToast(`Сохранено эталонов: ${w}${sk.length ? ` · уже были: ${sk.join(', ')}` : ''}`, 4000);
                }
                else if (res.saved_kind === 'piece') ttsDropToVars(t.i);
                else if (res.twins && res.twins.length)
                    showToast(`Сохранено: ${res.saved_name}.wav — и под ${res.twins.length === 1 ? 'названием' : 'названиями'} с тем же текстом: ${res.twins.slice(0, 4).join(', ')}${res.twins.length > 4 ? ` и ещё ${res.twins.length - 4}` : ''}`, 5000);
                else showToast(`Сохранено: ${res.saved_name}.wav`);
                ttsRender();
                // Идёт запись и дубль проверяли в «Сборке» — сохранили и сразу обратно к чтению.
                if (ttsRec.on && document.getElementById('stage4-tts').classList.contains('show-assembly')) {
                    // Фраза с переменными: следующий кусочек — сразу здесь же; всё сохранили — к чтению.
                    let next = null;
                    while (ttsAsmQueue.length && next === null) {
                        let k = tts.takes.findIndex(x => x.file === ttsAsmQueue[0]);
                        ttsAsmQueue.shift();
                        if (k >= 0 && !tts.takes[k].unit_saved) next = k;
                    }
                    if (next !== null) {
                        tts.index = next;
                        ttsRenderRail(); ttsRenderCurrent(); ttsShowAssembly(true); ttsAsmAuto = true; ttsTogglePlay();
                    } else ttsShowAssembly(false);
                }
                else if (ttsCurTake() && !ttsCurTake().unit_saved) ttsTogglePlay();
            } finally { ttsApproving = false; }
        }

        // ----- карточку дубля можно перетащить в папку «Переменные» -----
        // Кусочек фразы с переменной — сохраняется туда сразу (после
        // прослушивания); другой дубль — сначала выбрать, какой это кусочек.
        let ttsDragIdx = null;
        function ttsTakeDragStart(e, i) {
            ttsDragIdx = i;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', 'tts-take:' + i);
            e.currentTarget.classList.add('is-drag');
            document.getElementById('ttsRail').classList.add('is-dragging');
        }
        function ttsTakeDragEnd() {
            ttsDragIdx = null;
            document.getElementById('ttsRail').classList.remove('is-dragging');
            document.querySelectorAll('#ttsRail .is-drag').forEach(el => el.classList.remove('is-drag'));
            document.getElementById('ttsVarCard').classList.remove('is-drop');
        }
        function ttsVarDragOver(e) {
            if (ttsDragIdx === null) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            e.currentTarget.classList.add('is-drop');
        }
        async function ttsVarDrop(e) {
            e.preventDefault();
            let i = ttsDragIdx;
            ttsTakeDragEnd();
            if (i === null || !tts.takes[i]) return;
            if (i !== tts.index) await ttsSelect(i);
            ttsShowAssembly(true);
            let u = ttsUnit(tts.takes[i].unit);
            if (u && u.kind === 'piece') { ttsApprove(); return; }
            // Не кусочек переменной — спросить, к какому кусочку относится.
            ttsOpenUnits('assign-var');
        }

        // Фраза с переменной «падает» с ленты в карточку «Переменные».
        function ttsDropToVars(i) {
            let card = document.getElementById('ttsVarCard');
            let from = document.querySelector(`#ttsRail [data-i="${i}"]`);
            card.classList.remove('is-bump'); void card.offsetWidth; card.classList.add('is-bump');
            if (!from || !motionOK()) return;
            let a = from.getBoundingClientRect(), b = card.getBoundingClientRect();
            let ghost = from.cloneNode(true);
            ghost.className = 'tts-take is-chain tts-take--ghost';
            Object.assign(ghost.style, { left: a.left + 'px', top: a.top + 'px', width: a.width + 'px', height: a.height + 'px' });
            document.body.appendChild(ghost);
            let dx = b.left + b.width / 2 - (a.left + a.width / 2), dy = b.top + b.height / 2 - (a.top + a.height / 2);
            ghost.animate([
                { transform: 'translate(0,0) scale(1)', opacity: 1 },
                { transform: `translate(${dx * .5}px, ${dy * .35}px) scale(.9)`, opacity: 1, offset: .5 },
                { transform: `translate(${dx}px, ${dy}px) scale(.35)`, opacity: 0 }
            ], { duration: 520, easing: 'cubic-bezier(.4,0,.2,1)' }).onfinish = () => ghost.remove();
        }

        // Удалить дубль с дорожки: файл и сохранённая из него фраза уходят,
        // суфлёр — обратно к этой фразе. Ctrl+Z возвращает.
        // Порядок действий для Ctrl+Z в «Сборке»: срезка и удаление дубля — по очереди, последнее первым.
        let ttsActSeq = 0, ttsDelSeqs = [];
        function ttsUndoAny() {
            let h = ttsEd && ttsEdHistOf();
            let edSeq = h && h.undo.length ? (h.undo[h.undo.length - 1].seq || 0) : -1;
            let delSeq = ttsDelSeqs.length ? ttsDelSeqs[ttsDelSeqs.length - 1] : -1;
            if (delSeq > edSeq || (edSeq < 0 && delSeq < 0)) ttsUndoDelete();
            else ttsEdUndo(false);
        }
        async function ttsReject() {
            let t = ttsCurTake();
            if (!t) return;
            await ttsStopPlay();
            let res = await pywebview.api.tts_take_delete(t.i);
            if (!res || res.error) { if (res && res.error) showToast(res.error); return; }
            tts = res;
            ttsDelSeqs.push(++ttsActSeq);
            if (ttsRec.on && document.getElementById('stage4-tts').classList.contains('show-assembly')) { ttsAsmQueue = []; ttsShowAssembly(false); }
            ttsRender();
            ttsLoadPrompt();
            showToast(`Удалён: ${res.deleted} — Ctrl+Z вернёт`);
        }
        async function ttsUndoDelete() {
            await ttsStopPlay();
            let res = await pywebview.api.tts_take_undo_delete();
            if (!res) return;
            if (res.error) { ttsDelSeqs = []; showToast(res.error); return; }
            tts = res;
            ttsDelSeqs.pop();
            ttsRender();
            ttsLoadPrompt();
            showToast(`Вернул: ${res.restored}`);
        }

        // ----- список фраз: все / не найдено / привязка дубля / переменные -----
        let ttsListOnClose = null;

        function ttsOpenListOverlay(title, withSearch) {
            document.getElementById('ttsListTitle').innerText = title;
            let search = document.getElementById('ttsListSearch');
            search.style.display = withSearch ? '' : 'none';
            search.value = '';
            document.getElementById('ttsListTabs').innerHTML = '';
            document.getElementById('ttsListOverlay').style.display = 'flex';
            if (withSearch) setTimeout(() => search.focus(), 30);
        }

        function ttsCloseList() {
            document.getElementById('ttsListOverlay').style.display = 'none';
            let cb = ttsListOnClose; ttsListOnClose = null;
            if (cb) cb();
        }

        function ttsOpenUnits(mode) {
            if (!tts || !tts.loaded) return;
            ttsListMode = mode || 'all';
            let titles = { all: 'Все фразы', missing: 'Не найдено в записи', assign: 'К какой фразе относится дубль?', vars: 'Фразы с переменными',
                           'assign-var': 'Какой это кусочек фразы с переменной?' };
            ttsOpenListOverlay(titles[ttsListMode] || 'Фразы', true);
            if (ttsListMode !== 'assign' && ttsListMode !== 'assign-var') {
                let tabs = [['all', 'Все'], ['missing', 'Не найдено'], ['vars', 'С переменными']];
                document.getElementById('ttsListTabs').innerHTML = tabs.map(([k, l]) =>
                    `<button type="button" class="chip ${k === ttsListMode ? 'chip-mode--active' : ''}" onclick="ttsListMode='${k}'; ttsOpenUnits('${k}')">${l}</button>`).join('');
            }
            ttsRenderList();
        }

        // ----- экран «Переменные»: фразы-цепочки и значения переменных -----
        let ttsVars = null, ttsVarsTab = 'chains', ttsVarsCat = {}, ttsChainInfo = {};

        async function ttsOpenVars() {
            if (!tts || !tts.loaded) return;
            ttsVars = await pywebview.api.tts_vars_state();
            document.getElementById('ttsVarsOverlay').style.display = 'flex';
            ttsRenderVars();
            ttsLoadChainInfo();
        }

        function ttsCloseVars() {
            document.getElementById('ttsVarsOverlay').style.display = 'none';
            ttsStopPlay();
        }

        function ttsVarsSetTab(tab) { ttsVarsTab = tab; ttsRenderVars(); if (tab === 'synth') ttsSynthLoad(true); }

        // ===== 4 этап: суммы голосом диктора — клонирование по эталону =====
        // Эталон (запись диктора с суммой) + его текст → сервис синтеза клонирует
        // голос и озвучивает каждую сумму списка. Вы слушаете: ↻ — ещё раз,
        // ✓ — одобрить (тишина по краям срезается, файл — в «Синтез_суммы»).
        // Пока слушаете — следующие уже синтезируются. Дальше — режим «Суммы».
        let ttsSynth = null, ttsSynthCur = 0, ttsSynthWaitPlay = null;
        const TTS_SYN_STATUS = {
            idle: ['—', ''], queued: ['в очереди', 'wait'], working: ['синтез…', 'work'],
            ready: ['готово — слушайте', 'ready'], approved: ['одобрено ✓', 'ok'], error: ['ошибка', 'err'],
        };
        const ttsSumFmt = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');

        async function ttsSynthLoad(keepCur) {
            ttsSynth = await pywebview.api.tts_synth_state();
            if (!keepCur || ttsSynthCur >= ttsSynth.items.length) {
                let i = ttsSynth.items.findIndex(it => it.status !== 'approved');
                ttsSynthCur = i < 0 ? 0 : i;
            }
            if (document.getElementById('ttsVarsOverlay').style.display === 'flex') ttsRenderVars();
        }
        async function ttsSynthCall(promise) {
            let res = await promise;
            if (res && res.error) { if (res.error !== 'cancel') showToast(res.error); return null; }
            if (res && res.items) { ttsSynth = res; ttsRenderVars(); }
            return res;
        }
        function ttsSynthHTML() {
            let sy = ttsSynth;
            let chip = (on, label, js) => `<button type="button" class="chip ${on ? 'chip-mode--active' : ''}" onclick="${js}">${label}</button>`;
            let rows = sy.items.map(it => {
                let [lbl, cls] = TTS_SYN_STATUS[it.status] || TTS_SYN_STATUS.idle;
                let ok = it.status === 'approved';
                return `<div class="tts-syn__item ${it.k === ttsSynthCur ? 'is-cur' : ''} is-${it.status}" data-k="${it.k}" onclick="ttsSynthSelect(${it.k})">
                    <span class="tts-syn__num">${it.k + 1}</span>
                    <span class="tts-syn__sum">${ttsSumFmt(it.n)}</span>
                    <div class="tts-syn__tx">
                        <input class="tts-syn__text" value="${escapeHtml(it.text)}" title="Текст для синтеза — можно поправить"
                            onclick="event.stopPropagation()" onchange="ttsSynthSetText(${it.k}, this.value)">
                        ${ttsSynthPlanHTML(it.plan)}
                    </div>
                    <span class="tts-syn__st tts-syn__st--${cls}" title="${escapeHtml(it.error || '')}">${it.status === 'working' ? '<span class="lv-spin"></span>' : ''}${lbl}</span>
                    <button class="btn-ghost btn-ghost--compact" title="Слушать" ${it.has_variant || it.has_file ? '' : 'disabled'}
                        onclick="event.stopPropagation(); ttsSynthPlay(${it.k})">&#9654;</button>
                    <button class="btn-ghost btn-ghost--compact" title="${it.has_variant ? 'Пересинтезировать' : 'Синтезировать'}"
                        onclick="event.stopPropagation(); ttsSynthRun(${it.k})" ${it.status === 'working' || it.status === 'queued' ? 'disabled' : ''}>&#8635;</button>
                    ${ok ? `<button class="btn-ghost btn-ghost--compact" title="Убрать из одобренных" onclick="event.stopPropagation(); ttsSynthUnapprove(${it.k})">&times;</button>`
                         : `<button class="btn-ghost btn-ghost--compact tts-syn__ok" title="Одобрить" ${it.has_variant ? '' : 'disabled'}
                            onclick="event.stopPropagation(); ttsSynthApprove(${it.k})">&#10003;</button>`}
                </div>`;
            }).join('');
            let first = sy.items[0];
            return `<div class="tts-syn">
                <div class="tts-syn__setup">
                    <div class="tts-syn__row">
                        <span class="tts-syn__lbl">Эталон</span>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsSynthPickEtalon()" title="Запись диктора с суммой — с неё клонируется голос">
                            ${sy.etalon ? escapeHtml(sy.etalon) : 'Выбрать запись…'}</button>
                        ${sy.etalon_ok ? '<button class="btn-ghost btn-ghost--compact" onclick="ttsSynthPlayEtalon()" title="Слушать эталон">&#9654;</button>' : ''}
                        ${sy.etalon_ok && first && first.status !== 'approved' ? '<button class="btn-ghost btn-ghost--compact" onclick="ttsSynthEtalonFirst()" title="В эталоне сказана первая сумма списка — взять его как одобренный №1">Эталон = №1</button>' : ''}
                    </div>
                    <div class="tts-syn__row">
                        <span class="tts-syn__lbl">Текст эталона</span>
                        <input class="tts-syn__ettext" id="ttsSynthEtText" value="${escapeHtml(sy.etalon_text || '')}"
                            placeholder="что сказано в записи, словами" onchange="ttsSynthSetup({etalon_text: this.value})">
                    </div>
                    <div class="tts-syn__row">
                        <span class="tts-syn__lbl">Живые слова</span>
                        ${chip(sy.hybrid, 'Гибрид', 'ttsSynthSetup({hybrid: true})')}${chip(!sy.hybrid, 'Всё синтезом', 'ttsSynthSetup({hybrid: false})')}
                        ${sy.hybrid ? sy.words.map(w => w.ok
                            ? `<span class="tts-syn__word is-ok" title="Живое, из «${escapeHtml(w.src || '')}»"><button type="button" onclick="ttsSynthWordPlay('${w.form}')">&#9654; ${escapeHtml(w.form)}</button><button type="button" title="Поправить на дорожке «${escapeHtml(w.src || '')}»" onclick="ttsMkReopen('${escapeHtml(w.src || '')}')">&#9998;</button><button type="button" title="Убрать — это слово пойдёт в синтез" onclick="ttsSynthWordRemove('${w.form}')">&times;</button></span>`
                            : `<span class="tts-syn__word" title="Нет живой записи этой формы — синтезируется вместе с числом. Добавьте запись, где диктор её говорит.">${escapeHtml(w.form)} — синтез</span>`).join('') : ''}
                        ${sy.hybrid ? `<button class="btn-ghost btn-ghost--compact" onclick="ttsMkOpen(false)" ${sy.etalon_ok ? '' : 'disabled'} title="Открыть дорожку эталона и выделить слова мышью">Разметить в эталоне</button>
                               <button class="btn-ghost btn-ghost--compact" onclick="ttsMkOpen(true)" title="Другая запись диктора, где есть недостающие формы (например «миллиона», «тысяч»)">+ запись со словами</button>` : ''}
                    </div>
                    <div class="tts-syn__row">
                        <span class="tts-syn__lbl">Фон</span>
                        ${ttsNoiseChips(sy.noise, 'ttsSynthNoise').replace('<span class="tts-dim"', '<span class="tts-dim" style="display:none"')}
                    </div>
                    <div class="tts-syn__row">
                        <span class="tts-syn__lbl">Язык</span>
                        ${chip(sy.lang === 'ru', 'Русский', "ttsSynthSetup({lang: 'ru'})")}${chip(sy.lang === 'kz', 'Казахский', "ttsSynthSetup({lang: 'kz'})")}
                        <span class="tts-syn__lbl" style="margin-left:18px">Суммы</span>
                        ${chip(sy.logic === 1, 'Логика 1 · 1 101 001', 'ttsSynthSetup({logic: 1})')}${chip(sy.logic === 2, 'Логика 2 · 1 100 001', 'ttsSynthSetup({logic: 2})')}
                    </div>
                    <div class="tts-syn__row">
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsSynthRunAll()" ${sy.etalon_ok ? '' : 'disabled'}>Синтезировать все</button>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsSynthStop()" ${sy.queue ? '' : 'disabled'}>Остановить</button>
                        <span class="tts-ed__spacer"></span>
                        <span class="tts-dim">одобрено ${sy.approved} из ${sy.items.length}${sy.queue ? ` · в очереди ${sy.queue}` : ''}</span>
                        <button class="custom-alert-btn tts-syn__go" onclick="ttsSynthToSums()" ${sy.approved ? '' : 'disabled'}
                            title="Открыть режим «Суммы» на одобренных суммах">Режим «Суммы» →</button>
                    </div>
                </div>
                <div class="tts-syn__keys"><kbd>Space</kbd> слушать <kbd>Enter</kbd> одобрить <kbd>Backspace</kbd> пересинтезировать <kbd>&#8593;</kbd><kbd>&#8595;</kbd> сумма</div>
                <div class="tts-syn__list">${rows}</div>
            </div>`;
        }
        function ttsSynthSelect(k) {
            ttsSynthCur = k;
            document.querySelectorAll('.tts-syn__item').forEach(el => el.classList.toggle('is-cur', +el.dataset.k === k));
        }
        async function ttsSynthPickEtalon() {
            let res = await ttsSynthCall(pywebview.api.tts_synth_pick_etalon());
            if (res && res.hybrid) ttsMkOpen(false);          // гибрид: сразу размечаем слова в эталоне
        }
        const ttsSynthPlayEtalon = () => ttsSynthCall(pywebview.api.tts_synth_play_etalon());
        const ttsSynthSetup = o => ttsSynthCall(pywebview.api.tts_synth_setup(o.lang || null, o.logic || null,
            o.etalon_text === undefined ? null : o.etalon_text, o.hybrid === undefined ? null : o.hybrid));
        const ttsSynthWordRemove = f => ttsSynthCall(pywebview.api.tts_synth_word_remove(f));
        async function ttsSynthWordPlay(f) {
            await ttsStopPlay();
            let res = await pywebview.api.tts_synth_word_play(f);
            if (res && res.error) showToast(res.error);
        }
        // Из чего собрана сумма: живые слова — подсвечены, остальное — синтез.
        function ttsSynthPlanHTML(plan) {
            if (!plan || !plan.some(p => p[0] === 'live')) return '';
            return `<div class="tts-syn__plan">${plan.map(([kind, t]) =>
                kind === 'live' ? `<b title="живое слово">${escapeHtml(t)}</b>` : `<span title="синтез">${escapeHtml(t)}</span>`).join(' ')}</div>`;
        }
        const ttsSynthSetText = (k, v) => ttsSynthCall(pywebview.api.tts_synth_set_text(k, v));
        const ttsSynthRunAll = () => ttsSynthCall(pywebview.api.tts_synth_run_all());
        const ttsSynthStop = () => ttsSynthCall(pywebview.api.tts_synth_stop());
        const ttsSynthEtalonFirst = () => ttsSynthCall(pywebview.api.tts_synth_etalon_as_first()).then(() => ttsSynthLoad());
        const ttsSynthUnapprove = k => ttsSynthCall(pywebview.api.tts_synth_unapprove(k));
        async function ttsSynthRun(k) {
            ttsSynthSelect(k);
            ttsSynthWaitPlay = k;                       // как будет готово — сразу прозвучит
            await ttsSynthCall(pywebview.api.tts_synth_run(k, true));
        }
        async function ttsSynthPlay(k) {
            ttsSynthSelect(k);
            await ttsStopPlay();
            let res = await pywebview.api.tts_synth_play(k, false);
            if (res && res.error) showToast(res.error);
        }
        async function ttsSynthApprove(k) {
            let res = await ttsSynthCall(pywebview.api.tts_synth_approve(k));
            if (!res) return;
            // Следующая неодобренная — сразу слушаем, если готова; иначе прозвучит, как только будет.
            let next = res.items.find(it => it.k > k && it.status !== 'approved');
            if (!next) { showToast('Все суммы одобрены — можно в режим «Суммы»'); return; }
            ttsSynthSelect(next.k);
            ttsRenderVars();
            if (next.has_variant && next.status === 'ready') ttsSynthPlay(next.k);
            else ttsSynthWaitPlay = next.k;
        }
        async function ttsSynthToSums() {
            let res = await pywebview.api.tts_synth_sums_folder();
            if (!res || res.error) { showToast(res && res.error || 'Нет одобренных сумм'); return; }
            ttsCloseVars();
            startPremadeSumMode(res.folder);
        }
        // Сервис закончил очередную сумму (событие из Python).
        async function ttsSynthEvent(p) {
            if (p.error) showToast('Синтез: ' + p.error);
            else if (p.message && p.k === null) showToast(p.message);
            if (!ttsSynth) return;
            let typing = document.activeElement && document.activeElement.tagName === 'INPUT'
                && document.activeElement.closest('#ttsVarsOverlay');
            ttsSynth = await pywebview.api.tts_synth_state();
            let open = document.getElementById('ttsVarsOverlay').style.display === 'flex' && ttsVarsTab === 'synth';
            if (open && !typing) ttsRenderVars();
            let it = p.k !== null && p.k !== undefined ? ttsSynth.items[p.k] : null;
            if (open && it && it.k === ttsSynthWaitPlay && it.status === 'ready') { ttsSynthWaitPlay = null; ttsSynthPlay(it.k); }
        }
        // ----- разметка живых слов на дорожке записи -----
        let ttsMk = null;
        async function ttsMkOpen(extra) {
            ttsMkShow(await pywebview.api.tts_synth_marker_open(extra));
        }
        async function ttsMkReopen(src) {
            ttsMkShow(await pywebview.api.tts_synth_marker_reopen(src));
        }
        function ttsMkShow(res) {
            if (!res || res.error) { if (res && res.error !== 'cancel') showToast(res.error); return; }
            ttsMk = { ...res, sel: null, drag: null, head: null, suggest: [] };
            if (res.state) ttsSynth = res.state;
            document.getElementById('ttsMkTitle').textContent = 'Живые слова — ' + res.name;
            document.getElementById('ttsMarkOverlay').style.display = 'flex';
            let cv = document.getElementById('ttsMkCanvas');
            cv.onmousedown = ttsMkDown;
            ttsMkRender();
        }
        function ttsMkClose() {
            document.getElementById('ttsMarkOverlay').style.display = 'none';
            ttsMkStop();
            ttsMk = null;
            if (ttsSynth) ttsRenderVars();
        }
        const ttsMkX2ms = x => Math.max(0, Math.min(ttsMk.dur, x / document.getElementById('ttsMkCanvas').clientWidth * ttsMk.dur));
        const ttsMkMs2x = (ms, w) => ms / ttsMk.dur * w;
        function ttsMkDraw() {
            let cv = document.getElementById('ttsMkCanvas'), dpr = window.devicePixelRatio || 1;
            let w = cv.clientWidth, h = cv.clientHeight;
            if (cv.width !== Math.round(w * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
            let g = cv.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, w, h);
            let css = getComputedStyle(document.documentElement), col = v => css.getPropertyValue(v).trim();
            let box = (a, b, fill) => { g.fillStyle = fill; g.fillRect(ttsMkMs2x(a, w), 0, ttsMkMs2x(b - a, w), h); };
            g.fillStyle = col('--text-dim') || '#999';
            let p = ttsMk.peaks, mid = h / 2;
            for (let i = 0; i < p.length; i++) {
                let x = i / p.length * w, y = Math.max(1, p[i] * (mid - 18));
                g.fillRect(x, mid - y, Math.max(1, w / p.length), y * 2);
            }
            // метки — поверх волны, полупрозрачно: волна под ними видна
            ttsMk.suggest.forEach(m => box(m.a, m.b, 'rgba(200,200,200,.18)'));
            ttsMk.marks.forEach(m => box(m.a, m.b, 'rgba(46,204,113,.35)'));
            if (ttsMk.sel) box(ttsMk.sel.a, ttsMk.sel.b, 'rgba(90,150,255,.38)');
            g.font = '600 11px sans-serif'; g.textBaseline = 'top';
            let label = (m, color) => { g.fillStyle = color; g.fillText(m.form, ttsMkMs2x(m.a, w) + 4, 4); };
            ttsMk.suggest.forEach(m => label(m, '#aaa'));
            ttsMk.marks.forEach(m => label(m, '#2ecc71'));
            if (ttsMk.sel) {
                g.fillStyle = '#5a96ff';
                [ttsMk.sel.a, ttsMk.sel.b].forEach(t => g.fillRect(ttsMkMs2x(t, w) - 1, 0, 2, h));
            }
            if (ttsMk.head !== null) { g.fillStyle = col('--accent-primary') || '#f5a623'; g.fillRect(ttsMkMs2x(ttsMk.head, w), 0, 2, h); }
        }
        function ttsMkRender() {
            let done = new Set(ttsMk.marks.map(m => m.form));
            let cur = ttsMk.sel && ttsMk.marks.find(m => m.a === ttsMk.sel.a && m.b === ttsMk.sel.b);
            document.getElementById('ttsMkForms').innerHTML = ttsMk.forms.map((f, i) =>
                `<button type="button" class="chip ${done.has(f) ? 'tts-mk-done' : ''} ${cur && cur.form === f ? 'chip-mode--active' : ''}"
                    ${ttsMk.sel ? '' : 'disabled'} onclick="ttsMkAssign('${f}')" title="Клавиша ${i + 1}"><kbd>${i + 1}</kbd> ${escapeHtml(f)}${done.has(f) ? ' ✓' : ''}</button>`).join('');
            let len = ttsMk.sel ? Math.round(ttsMk.sel.b - ttsMk.sel.a) : 0;
            document.getElementById('ttsMkBar').innerHTML = `
                <button class="btn-ghost btn-ghost--compact" onclick="ttsMkPlay(true)" ${ttsMk.sel ? '' : 'disabled'}>&#9654; Выделенное <kbd>Space</kbd></button>
                <button class="btn-ghost btn-ghost--compact" onclick="ttsMkPlay(false)">&#9654; Всю запись</button>
                ${cur ? `<button class="btn-ghost btn-ghost--compact" onclick="ttsMkRemove('${cur.form}')">Убрать «${escapeHtml(cur.form)}»</button>` : ''}
                <span class="tts-dim">${ttsMk.sel ? `выделено ${len} мс` : ''}</span>
                <span class="tts-ed__spacer"></span>
                <button class="btn-ghost btn-ghost--compact" onclick="ttsMkAuto()" title="Распознать (Whisper) и подсветить серым, где слова. Вы проверяете и подтверждаете сами">Подсказать</button>
                <button class="custom-alert-btn" onclick="ttsMkClose()">Готово</button>`;
            ttsMkDraw();
        }
        function ttsMkDown(e) {
            let cv = e.currentTarget, r = cv.getBoundingClientRect(), x = e.clientX - r.left, w = cv.clientWidth;
            let s = ttsMk.sel, mode = 'new', start = ttsMkX2ms(x);
            if (s && Math.abs(ttsMkMs2x(s.a, w) - x) < 7) mode = 'a';
            else if (s && Math.abs(ttsMkMs2x(s.b, w) - x) < 7) mode = 'b';
            let moved = false;
            let move = ev => {
                let t = ttsMkX2ms(ev.clientX - r.left);
                if (mode === 'new') { if (Math.abs(ev.clientX - e.clientX) < 3 && !moved) return; moved = true; ttsMk.sel = { a: Math.min(start, t), b: Math.max(start, t) }; }
                else { moved = true; ttsMk.sel = { ...ttsMk.sel, [mode]: t }; if (ttsMk.sel.a > ttsMk.sel.b) ttsMk.sel = { a: ttsMk.sel.b, b: ttsMk.sel.a }; }
                ttsMkDraw();
            };
            let up = () => {
                window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
                if (!moved) {                     // клик: по метке — выделить её, иначе снять выделение
                    let m = ttsMk.marks.find(m => start >= m.a && start <= m.b) || ttsMk.suggest.find(m => start >= m.a && start <= m.b);
                    ttsMk.sel = m ? { a: m.a, b: m.b } : null;
                }
                if (ttsMk.sel) ttsMk.sel = { a: Math.round(ttsMk.sel.a), b: Math.round(ttsMk.sel.b) };
                ttsMkRender();
            };
            window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
        }
        let ttsMkTimer = null;
        function ttsMkStop() { if (ttsMkTimer) cancelAnimationFrame(ttsMkTimer); ttsMkTimer = null; if (ttsMk) { ttsMk.head = null; ttsMkDraw(); } }
        async function ttsMkPlay(sel) {
            await ttsStopPlay(); ttsMkStop();
            let a = sel && ttsMk.sel ? ttsMk.sel.a : 0, b = sel && ttsMk.sel ? ttsMk.sel.b : null;
            let res = await pywebview.api.tts_synth_marker_play(a, b);
            if (!res || res.error) { if (res) showToast(res.error); return; }
            let t0 = performance.now(), dur = res.duration * 1000;
            let step = () => {
                if (!ttsMk) return;
                let t = performance.now() - t0;
                if (t > dur) { ttsMkStop(); return; }
                ttsMk.head = a + t; ttsMkDraw(); ttsMkTimer = requestAnimationFrame(step);
            };
            ttsMkTimer = requestAnimationFrame(step);
        }
        async function ttsMkAssign(form) {
            if (!ttsMk || !ttsMk.sel) return;
            let res = await pywebview.api.tts_synth_marker_save(form, ttsMk.sel.a, ttsMk.sel.b);
            if (!res || res.error) { if (res) showToast(res.error); return; }
            ttsMk.marks = res.marks; ttsSynth = res.state;
            ttsMk.suggest = ttsMk.suggest.filter(m => !(m.a === ttsMk.sel.a && m.b === ttsMk.sel.b) && m.form !== form);
            ttsMkRender();
        }
        async function ttsMkRemove(form) {
            let res = await pywebview.api.tts_synth_marker_remove(form);
            if (!res || res.error) return;
            ttsMk.marks = res.marks; ttsSynth = res.state; ttsMk.sel = null; ttsMkRender();
        }
        async function ttsMkAuto() {
            showToast('Распознаю запись…');
            let res = await pywebview.api.tts_synth_marker_auto();
            if (!res || res.error) { if (res) showToast(res.error); return; }
            ttsMk.suggest = res.suggest;
            let first = res.suggest[0]; ttsMk.sel = first ? { a: first.a, b: first.b } : null;
            showToast('Серым — где, похоже, слова. Кликните по метке, проверьте ▶ и нажмите, что это.');
            ttsMkRender();
        }
        function ttsMkKey(e) {
            if (e.code === 'Escape') { e.preventDefault(); ttsMkClose(); return; }
            if (e.code === 'Space') { e.preventDefault(); ttsMkPlay(!!ttsMk.sel); return; }
            let d = /^(Digit|Numpad)([1-9])$/.exec(e.code);
            if (d && ttsMk.forms[+d[2] - 1]) { e.preventDefault(); ttsMkAssign(ttsMk.forms[+d[2] - 1]); }
        }

        function ttsSynthKey(e) {
            let it = ttsSynth && ttsSynth.items[ttsSynthCur];
            if (!it) return false;
            if (e.code === 'Space') { e.preventDefault(); ttsSynthPlay(it.k); return true; }
            if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); if (it.has_variant && it.status !== 'approved') ttsSynthApprove(it.k); return true; }
            if (e.code === 'Backspace') { e.preventDefault(); ttsSynthRun(it.k); return true; }
            if (e.code === 'ArrowDown' || e.code === 'ArrowUp') {
                e.preventDefault();
                ttsSynthSelect(Math.max(0, Math.min(ttsSynth.items.length - 1, ttsSynthCur + (e.code === 'ArrowDown' ? 1 : -1))));
                let row = document.querySelector('.tts-syn__item.is-cur');
                if (row) row.scrollIntoView({ block: 'nearest' });
                return true;
            }
            return false;
        }

        function ttsRenderVars() {
            let tabs = [['chains', `Фразы · ${ttsVars.chains.length}`]].concat(ttsVars.sheets.map(sh => {
                let ready = sh.categories.reduce((a, c) => a + c.ready, 0), all = sh.categories.reduce((a, c) => a + c.values.length, 0);
                return [sh.key, `${sh.label} · ${ready}/${all}`];
            })).concat([['synth', ttsSynth ? `Синтез сумм · ${ttsSynth.approved}/${ttsSynth.items.length}` : 'Синтез сумм']]);
            document.getElementById('ttsVarsTabs').innerHTML = tabs.map(([k, l]) =>
                `<button type="button" class="chip ${k === ttsVarsTab ? 'chip-mode--active' : ''}" onclick="ttsVarsSetTab('${k}')">${escapeHtml(l)}</button>`).join('');
            let body = document.getElementById('ttsVarsBody');
            if (ttsVarsTab === 'chains') { body.innerHTML = ttsVarsChainsHTML(); return; }
            if (ttsVarsTab === 'synth') {
                if (!ttsSynth) { body.innerHTML = '<div class="tts-dim tts-list__empty">Загружаю…</div>'; ttsSynthLoad(); return; }
                let list = body.querySelector('.tts-syn__list'), top = list ? list.scrollTop : null;
                body.innerHTML = ttsSynthHTML();
                let nl = body.querySelector('.tts-syn__list');
                if (nl && top !== null) nl.scrollTop = top;
                return;
            }
            let sh = ttsVars.sheets.find(x => x.key === ttsVarsTab);
            if (!sh) { ttsVarsTab = 'chains'; ttsRenderVars(); return; }
            body.innerHTML = ttsVarsSheetHTML(sh);
        }

        function ttsVarsChainsHTML() {
            if (!ttsVars.chains.length) return '<div class="tts-dim tts-list__empty">В таблице нет фраз с переменными</div>';
            let pill = v => `<span class="tts-var">${escapeHtml(ttsVarLabel(v))}</span>`;
            return ttsVars.chains.map(ch => {
                let info = ttsChainInfo[ch.id];
                let db = id => { let p = info && info.parts.find(x => x.id === id); return p && p.db !== null ? `${p.db} дБ` : ''; };
                let parts = ch.parts.map((p, k) =>
                    (k === 0 && p.var_before ? pill(p.var_before) : '') +
                    `<span class="tts-vpart ${p.saved ? 'is-saved' : ''}" title="${escapeHtml(p.text)}">
                        <span class="tts-vpart__role">${p.role}${p.saved ? ' ✓' : ''}</span>
                        <span class="tts-vpart__name">${escapeHtml(p.name)}</span>
                        <span class="tts-vpart__db">${db(p.id)}</span></span>` +
                    (p.var_after ? pill(p.var_after) : '')).join('');
                let saved = ch.parts.filter(p => p.saved).length;
                let spread = info && info.spread >= 3
                    ? `<span class="tts-pill tts-pill--var" title="Кусочки заметно отличаются по громкости — на стыках будет слышно">разброс ${info.spread} дБ</span>` : '';
                return `<div class="tts-vchain">
                    <div class="tts-vchain__head">
                        <span class="tts-vchain__name">${escapeHtml(ch.name)}</span>
                        <span class="tts-dim">${saved} / ${ch.parts.length}</span>
                        ${spread}
                        <span class="tts-ed__spacer"></span>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsChainPlay(${ch.id})" ${saved ? '' : 'disabled'}
                                title="Кусочки подряд, на месте переменных — пример готового значения (или пауза)">Слушать сборку</button>
                    </div>
                    <div class="tts-vchain__parts">${parts}</div>
                </div>`;
            }).join('');
        }

        async function ttsLoadChainInfo() {
            for (let ch of ttsVars.chains) {
                if (!ch.parts.some(p => p.saved)) continue;
                let info = await pywebview.api.tts_chain_info(ch.id);
                if (!info || info.error) continue;
                ttsChainInfo[ch.id] = info;
                if (ttsVarsTab === 'chains' && document.getElementById('ttsVarsOverlay').style.display === 'flex') ttsRenderVars();
            }
        }

        async function ttsChainPlay(id) {
            await ttsStopPlay();
            let res = await pywebview.api.tts_chain_play(id);
            if (res && res.error) showToast(res.error);
        }

        function ttsVarsSheetHTML(sh) {
            let catKey = ttsVarsCat[sh.key] || sh.categories[0].key;
            ttsVarsCat[sh.key] = catKey;
            let cat = sh.categories.find(c => c.key === catKey) || sh.categories[0];
            let cats = sh.categories.map(c => `<button type="button" class="tts-vcat ${c.key === cat.key ? 'is-active' : ''}"
                    onclick="ttsVarsCat['${sh.key}']='${c.key}'; ttsRenderVars()">
                    <span>${escapeHtml(c.label)}</span><span class="tts-vcat__n">${c.ready} / ${c.values.length}</span></button>`).join('');
            let vals = cat.values.map((v, k) => `<div class="tts-vval ${v.ready ? 'is-ready' : ''}">
                    <span class="tts-vval__value">${escapeHtml(v.value)}</span>
                    <input class="tts-vval__text ${v.custom ? 'is-custom' : ''}" value="${escapeHtml(v.text)}" spellcheck="false"
                           title="Текст для синтеза — можно поправить" onchange="ttsVarSetText('${sh.key}', '${cat.key}', ${k}, this)"
                           onkeydown="if (event.key === 'Enter' || event.key === 'Escape') this.blur()">
                    ${v.ready ? `<button class="tts-vval__play" onclick="ttsVarPlay('${sh.key}', '${cat.key}', ${k})" title="Слушать">▶</button>` : '<span class="tts-vval__dot" title="Ещё нет файла"></span>'}
                </div>`).join('');
            return `<div class="tts-vsheet">
                <div class="tts-vcats">${cats}</div>
                <div class="tts-vvals-wrap">
                    <div class="tts-vvals__bar">
                        <span class="tts-dim">Текст для синтеза — правьте прямо в строке. Синтез через сервис — следующий этап.</span>
                        <span class="tts-ed__spacer"></span>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsVarImport('${sh.key}', '${cat.key}')" title="Файлы «5.wav», «пять миллионов.wav» или «million_5.wav» — разложу по значениям">Загрузить готовые</button>
                        <button class="btn-ghost btn-ghost--compact" onclick="pywebview.api.tts_var_open_folder('${sh.key}', '${cat.key}')">Папка</button>
                    </div>
                    <div class="tts-vvals">${vals}</div>
                </div>
            </div>`;
        }

        function ttsVarFind(sheet, cat) {
            return ttsVars.sheets.find(x => x.key === sheet).categories.find(c => c.key === cat);
        }

        async function ttsVarSetText(sheet, cat, k, input) {
            let v = ttsVarFind(sheet, cat).values[k];
            await pywebview.api.tts_var_set_text(sheet, cat, v.value, input.value);
            ttsVars = await pywebview.api.tts_vars_state();
            ttsRenderVars();
        }

        async function ttsVarPlay(sheet, cat, k) {
            await ttsStopPlay();
            await pywebview.api.tts_var_play(sheet, cat, ttsVarFind(sheet, cat).values[k].value);
        }

        async function ttsVarImport(sheet, cat) {
            let res = await pywebview.api.tts_var_import(sheet, cat);
            if (!res || res.error === 'cancel') return;
            if (res.error) { showBeautifulAlert('⚠️ ' + escapeHtml(res.error)); return; }
            ttsVars = res.state;
            ttsRenderVars();
            let msg = `Разложено файлов: <b>${res.matched}</b>`;
            if (res.unknown_count) msg += `<br><br>Не понял, к какому значению относятся (${res.unknown_count}):<br>${res.unknown.map(escapeHtml).join('<br>')}`;
            showBeautifulAlert(msg);
        }

        function ttsRenderList() {
            let q = document.getElementById('ttsListSearch').value.trim().toLowerCase();
            let pm = tts.prompt_mode || 'phrases';
            let units = tts.units.filter(u =>
                (pm === 'phrases' ? u.kind !== 'value' : (u.kind === 'value' && u.sheet === pm
                    && (!u.logic || u.logic === tts.sum_logic) && !(tts.units.some(x => x.sheet === pm && x.logic) && !u.logic))) &&
                (ttsListMode !== 'missing' || (!u.saved && !u.takes.length)) &&
                ((ttsListMode !== 'vars' && ttsListMode !== 'assign-var') || u.kind === 'piece') &&
                (!q || u.text.toLowerCase().includes(q) || u.name.toLowerCase().includes(q)));
            let cur = ttsCurTake();
            let html = units.map(u => {
                let state = u.saved ? '<span class="tts-pill tts-pill--good">сохранено</span>'
                    : (u.takes.length ? `<span class="tts-pill tts-pill--info">дублей: ${u.takes.length}</span>` : '<span class="tts-pill tts-pill--trash">нет в записи</span>');
                let act = ttsListMode === 'assign' ? `onclick="ttsAssign(${u.id})"`
                    : ttsListMode === 'assign-var' ? `onclick="ttsAssign(${u.id}, true)"`
                    : (u.takes.length ? `onclick="ttsCloseList(); ttsSelect(${u.takes[0]})"` : '');
                return `<div class="tts-unit ${cur && cur.unit === u.id ? 'is-current' : ''}" ${act}>
                    <span class="tts-unit__name">${escapeHtml(u.name)}</span>
                    <span class="tts-unit__text">${ttsUnitTextHTML(u)}</span>
                    ${state}
                    ${u.saved && ttsListMode !== 'assign' ? `<button class="tts-unit__x" title="Убрать из сохранённых (в «_Корзина»)" onclick="event.stopPropagation(); ttsUnapprove(${u.id})">&times;</button>` : ''}
                </div>`;
            }).join('');
            if (ttsListMode === 'assign') html = `<div class="tts-unit" onclick="ttsAssign(-1)"><span class="tts-unit__text tts-dim">Не фраза (шум, оговорка)</span></div>` + html;
            if (ttsListMode === 'vars') {
                let cats = Object.values(tts.var_sheets || {}).map(v =>
                    `<div class="tts-varsheet"><b>${escapeHtml(v.label)}</b> ${v.categories.map(c => `${escapeHtml(c.label)} · ${c.count}`).join(' &nbsp;|&nbsp; ')}</div>`).join('');
                html = (cats ? `<div class="tts-varsheets">${cats}<div class="tts-dim">Синтез значений через сервис — следующий этап.</div></div>` : '') + html;
            }
            document.getElementById('ttsList').innerHTML = html || '<div class="tts-dim tts-list__empty">Ничего нет</div>';
        }

        async function ttsAssign(unitId, andSave) {
            let t = ttsCurTake();
            if (!t) return;
            tts = await pywebview.api.tts_assign(t.i, unitId);
            ttsCloseList();
            ttsRender();
            if (andSave) ttsApprove();
        }

        async function ttsUnapprove(unitId) {
            let u = tts.units[unitId];
            if (!(await showBeautifulConfirm(`Убрать <b>${escapeHtml(u.name)}.wav</b> из сохранённых?<br><br>Файл уйдёт в «_Корзина».`, 'Убрать', 'Отмена'))) return;
            tts = await pywebview.api.tts_unapprove(unitId);
            ttsRender();
            ttsRenderList();
        }

        function ttsHandleKey(e) {
            if (ttsBatchIsOpen()) return ttsBatchKey(e);
            if (document.getElementById('ttsMarkOverlay').style.display === 'flex') { if (ttsMk) ttsMkKey(e); return true; }
            let vars = document.getElementById('ttsVarsOverlay');
            if (vars.style.display === 'flex') {
                if (e.code === 'Escape') { e.preventDefault(); ttsCloseVars(); }
                else if (ttsVarsTab === 'synth') ttsSynthKey(e);
                return true;
            }
            let list = document.getElementById('ttsListOverlay');
            if (list.style.display === 'flex') {
                if (e.code === 'Escape') { e.preventDefault(); ttsCloseList(); }
                return true;
            }
            if (e.repeat && !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.code)) { e.preventDefault(); return true; }
            if (document.activeElement && document.activeElement.tagName === 'BUTTON') document.activeElement.blur();
            // Во время записи: держите Space — пишу, Backspace — заново, P — прослушать последнее.
            let inAssembly = document.getElementById('stage4-tts').classList.contains('show-assembly');
            if (inAssembly && e.code === 'Escape') { e.preventDefault(); ttsShowAssembly(false); return true; }
            // Открыта сборка — Space слушает/останавливает дубль, а не пишет.
            if (inAssembly && e.code === 'Space') { e.preventDefault(); ttsTogglePlay(); return true; }
            if (ttsRec.on && e.code === 'Space') { e.preventDefault(); ttsPtt(true); return true; }
            if (e.code === 'Space') { e.preventDefault(); ttsLiveFlash('off'); return true; }
            if (ttsRec.on && e.code === 'Backspace') { e.preventDefault(); ttsPttCancel(); ttsLiveAction('redo'); return true; }
            if (ttsRec.on && !inAssembly && (e.code === 'Enter' || e.code === 'NumpadEnter')) { e.preventDefault(); ttsLiveAction('commit'); return true; }
            if (ttsRec.on && e.code === 'KeyP') { e.preventDefault(); ttsLiveAction('play'); return true; }
            if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); ttsApprove(); }
            else if (e.code === 'ArrowRight' || e.code === 'KeyD') { e.preventDefault(); ttsStep(1); }
            else if (e.code === 'ArrowLeft' || e.code === 'KeyA') { e.preventDefault(); ttsStep(-1); }
            else if (e.code === 'Delete' || e.code === 'Backspace') { e.preventDefault(); ttsReject(); }
            else if (e.code === 'KeyF') { e.preventDefault(); ttsOpenUnits('assign'); }
            else if (e.code === 'KeyX') { e.preventDefault(); ttsEditorCut(); }
            else if (e.code === 'KeyR') { e.preventDefault(); ttsToggleRec(); }
            else if (e.code === 'ArrowDown') { e.preventDefault(); ttsPromptMove(1); }
            else if (/^(Digit|Numpad)\d$/.test(e.code)) { e.preventDefault(); ttsMarkKey(+e.code.slice(-1)); }
            else if (e.code === 'ArrowUp') { e.preventDefault(); ttsPromptMove(-1); }
            return true;
        }

        function ttsListSearchKey(e) {
            if (e.key === 'Escape') { e.preventDefault(); ttsCloseList(); }
            else if (e.key === 'Enter') {
                e.preventDefault();
                // В привязке первая строка — «Не фраза», берём первую настоящую.
                let rows = [...document.querySelectorAll('#ttsList .tts-unit[onclick]')];
                let first = ttsListMode === 'assign' ? rows[1] : rows[0];
                if (first) first.click();
            }
        }


        // ===== TTS: живая запись с микрофона =====
        // Читаете фразы — в паузах программа распознаёт сказанное, находит
        // фразы таблицы и выкладывает готовые дубли на ленту. Сдавать (Space,
        // Enter) можно прямо во время записи — лучше в наушниках.
        let ttsRec = { on: false, starting: false, timer: null };
        const TTS_MIC_KEY = 'gvox_tts_mic';

        async function ttsToggleRec() {
            if (ttsRec.starting) return;
            if (ttsRec.on) { ttsRecStop(); return; }
            if (!tts || !tts.loaded) { showToast('Сначала загрузите таблицу'); return; }
            let list = await pywebview.api.tts_rec_devices();
            if (list && list.error) { showBeautifulAlert('⚠️ ' + escapeHtml(list.error).replace(/\n/g, '<br>')); return; }
            let device = await ttsPickMic(list.devices);
            if (device === null) return;
            await ttsMonitorApply(list.outputs);
            ttsRec.starting = true;
            await pywebview.api.tts_live_no_asr(ttsNoAsrOn());
            ttsSetRecUi(true, ttsNoAsrOn() ? 'Включаю микрофон…'
                : (tts.lang === 'kz' ? 'Включаю микрофон и казахскую модель (первый раз скачивается ~1,6 ГБ)…' : 'Включаю микрофон и распознавание…'));
            let res;
            try { res = await pywebview.api.tts_rec_start(device); } finally { ttsRec.starting = false; }
            if (!res || res.error) {
                ttsSetRecUi(false);
                if (res && (res.error === 'need_model' || res.error === 'need_model_kz')) { showAsrModel(res.error === 'need_model_kz' ? 'kz' : 'ru'); return; }
                if (res && res.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(res.error));
                return;
            }
            ttsRec.on = true;
            ttsRec.device = res.device;
            if (res.restored && res.state) {
                // Выбрали папку прежней работы — подтянули её.
                tts = res.state; ttsRender();
                showToast(res.restored);
            }
            await pywebview.api.tts_live_fast(ttsFastOn());
            ttsFastRender();
            ttsLiveSt.micOff = document.getElementById('stage4-tts').classList.contains('show-assembly');
            if (ttsLiveSt.micOff) pywebview.api.tts_live_mic(false);
            if (res.monitor_error) showToast(res.monitor_error);
            ttsMonitorLabel(res.monitor || null);
            ttsSetRecUi(true);
            ttsLiveKey = null; ttsLiveRender();
            ttsPromptKey = null;
            let pr = await pywebview.api.tts_prompt_info();
            if (pr) ttsRenderPrompt(pr, 'next');
            clearInterval(ttsRec.timer);
            ttsRec.timer = setInterval(ttsRecPoll, 200);
        }

        // ----- устройства: микрофон диктора и наушники того, кто слушает -----
        // Запоминаем название + какое оно по счёту среди одноимённых: Windows
        // обрезает названия до 31 знака, и у двух гарнитур они могут совпасть,
        // а номера устройств меняются при переподключении.
        const TTS_MON_KEY = 'gvox_tts_monitor';
        const ttsLoad = k => { try { let v = JSON.parse(localStorage.getItem(k) || 'null'); return v && typeof v === 'object' ? v : null; } catch (e) { return null; } };
        const ttsSave = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
        const ttsMonitorSaved = () => ttsLoad(TTS_MON_KEY);
        const ttsMicSaved = () => ttsLoad(TTS_MIC_KEY);
        function ttsDevFind(list, saved) {
            if (!saved || !saved.name) return null;
            let same = (list || []).filter(d => d.name === saved.name);
            return same.find(d => (d.nth || 0) === (saved.nth || 0)) || (same.length === 1 ? same[0] : null);
        }
        const ttsDevLabel = (name, nth, same) => same > 1 || nth ? `${name} · №${(nth || 0) + 1}` : name;

        function ttsMonitorLabel(name) {
            let btn = document.getElementById('ttsMonBtn');
            if (!btn) return;
            let cfg = ttsMonitorSaved(), mic = ttsMicSaved();
            let on = !!(cfg && cfg.name);
            btn.classList.toggle('is-on', on);
            let label = on ? ttsDevLabel(cfg.name, cfg.nth, cfg.same) : '';
            let short = s => s.length > 18 ? s.slice(0, 17) + '…' : s;
            let num = on && (cfg.same > 1 || cfg.nth) ? ` №${(cfg.nth || 0) + 1}` : '';
            btn.innerHTML = on ? `&#127911; ${escapeHtml(short(cfg.name))}${num}` : '&#127911; Устройства';
            btn.title = `Микрофон диктора: ${mic && mic.name ? ttsDevLabel(mic.name, mic.nth, mic.same) : 'не выбран'}\n`
                + `Ваши наушники: ${on ? label + ` (громкость прослушки ${Math.round((cfg.volume || 1) * 100)}%)` : 'как в Windows'}\nКлик — сменить`;
        }
        async function ttsMonitorApply(outputs) {
            let cfg = ttsMonitorSaved();
            if (!cfg || !cfg.name) { await pywebview.api.tts_monitor(null, 1); return; }
            let dev = ttsDevFind(outputs, cfg);
            if (!dev) {
                showToast(`Наушники «${ttsDevLabel(cfg.name, cfg.nth, cfg.same)}» не найдены — звук пойдёт в устройство Windows`);
                await pywebview.api.tts_monitor(null, 1); return;
            }
            await pywebview.api.tts_monitor(dev.id, cfg.volume || 1);
        }

        // Одно окно — оба выбора; запоминается навсегда (до следующей смены).
        async function ttsMonitorPick() {
            let list = await pywebview.api.tts_rec_devices();
            if (!list || list.error) { showToast(list && list.error || 'Нет устройств'); return; }
            ttsOpenListOverlay('Устройства', false);
            let draw = () => {
                let cfg = ttsMonitorSaved() || {}, mic = ttsMicSaved() || {};
                let vol = cfg.volume || 1;
                let micNow = ttsDevFind(list.devices, mic), outNow = ttsDevFind(list.outputs, cfg);
                let item = (d, kind, on) => `<button type="button" class="audit-category-item ${on ? 'is-first' : ''}" data-kind="${kind}" data-id="${d.id}">
                        ${escapeHtml(ttsDevLabel(d.name, d.nth, d.same))}
                        <span class="audit-choice-desc">${on ? 'выбрано' : (d.default ? 'по умолчанию в Windows' : '')}</span></button>`;
                document.getElementById('ttsList').innerHTML = `
                    <div class="tts-dev-head">🎙 Микрофон диктора</div>
                    ${list.devices.map(d => item(d, 'mic', micNow && micNow.id === d.id)).join('')}
                    <div class="tts-dev-head">🎧 Ваши наушники <span class="tts-dim">— голос диктора вживую и всё прослушивание</span></div>
                    <button type="button" class="audit-category-item ${outNow ? '' : 'is-first'}" data-kind="out" data-id="-1">Как в Windows (по умолчанию)
                        <span class="audit-choice-desc">${outNow ? '' : 'выбрано'}</span></button>
                    ${list.outputs.map(d => item(d, 'out', outNow && outNow.id === d.id)).join('')}
                    <div class="tts-mon-vol"><span>Громкость прослушки</span>
                        <input type="range" id="ttsMonVol" min="0.5" max="4" step="0.1" value="${vol}">
                        <b id="ttsMonVolTxt">${Math.round(vol * 100)}%</b></div>
                    <div class="tts-dim tts-mon-hint">Две одинаковые гарнитуры различаются номером (№1, №2). Наушники выбирайте не те, что у диктора.</div>
                    <div class="modal-actions"><button class="custom-alert-btn" onclick="ttsCloseList()">Готово</button></div>`;
                document.querySelectorAll('#ttsList [data-kind]').forEach(b => b.onclick = async () => {
                    let id = +b.dataset.id;
                    if (b.dataset.kind === 'mic') {
                        let d = list.devices.find(x => x.id === id);
                        ttsSave(TTS_MIC_KEY, { name: d.name, nth: d.nth || 0, same: d.same || 1 });
                        if (ttsRec.on) showToast('Новый микрофон — со следующего включения записи (R)');
                    } else {
                        let d = list.outputs.find(x => x.id === id);
                        ttsSave(TTS_MON_KEY, d ? { name: d.name, nth: d.nth || 0, same: d.same || 1, volume: vol } : null);
                        let res = await pywebview.api.tts_monitor(d ? d.id : null, vol);
                        if (res && res.error) showToast(res.error);
                    }
                    ttsMonitorLabel();
                    draw();
                });
                let range = document.getElementById('ttsMonVol');
                range.oninput = () => {
                    vol = +range.value;
                    document.getElementById('ttsMonVolTxt').innerText = Math.round(vol * 100) + '%';
                    let c = ttsMonitorSaved();
                    if (c && c.name) {
                        c.volume = vol; ttsSave(TTS_MON_KEY, c);
                        let d = ttsDevFind(list.outputs, c);
                        if (d) pywebview.api.tts_monitor(d.id, vol);
                        ttsMonitorLabel();
                    }
                };
            };
            draw();
        }

        // Микрофон: один — сразу он; запомненный — сразу он, без вопросов
        // (сменить — кнопка «Устройства»); иначе — спросить один раз.
        function ttsPickMic(devices) {
            if (devices.length === 1) return Promise.resolve(devices[0].id);
            let saved = ttsMicSaved();
            let known = ttsDevFind(devices, saved);
            if (known) return Promise.resolve(known.id);
            return new Promise(resolve => {
                ttsOpenListOverlay('Микрофон диктора', false);
                let order = [...devices].sort((a, b) => b.default - a.default);
                document.getElementById('ttsList').innerHTML = order.map((d, i) =>
                    `<button type="button" class="audit-category-item ${i === 0 ? 'is-first' : ''}" data-id="${d.id}">${escapeHtml(ttsDevLabel(d.name, d.nth, d.same))}
                        <span class="audit-choice-desc">${d.default ? 'по умолчанию в Windows' : ''}</span></button>`).join('');
                document.querySelectorAll('#ttsList [data-id]').forEach(b => b.onclick = () => {
                    let d = devices.find(x => x.id === +b.dataset.id);
                    ttsSave(TTS_MIC_KEY, { name: d.name, nth: d.nth || 0, same: d.same || 1 });
                    ttsListOnClose = null;
                    ttsCloseList(); ttsMonitorLabel(); resolve(d.id);
                });
                ttsListOnClose = () => resolve(null);
            });
        }

        function ttsSetRecUi(on, info) {
            // Суфлёр на экране всегда; R только включает и выключает запись.
            document.getElementById('stage4-tts').classList.toggle('is-recording', on);
            requestAnimationFrame(ttsFitPrompt);
            let btn = document.getElementById('ttsRecBtn');
            btn.classList.toggle('is-recording', on);
            btn.innerHTML = on ? '■ Стоп <kbd>R</kbd>' : '● Записывать <kbd>R</kbd>';
            if (info !== undefined) document.getElementById('ttsRecInfo').innerText = info;
        }

        async function ttsRecPoll() {
            let s = await pywebview.api.tts_rec_status();
            if (!s || !s.recording) return;
            let sec = Math.floor(s.seconds);
            document.getElementById('ttsRecTime').innerText = `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
            // −60…0 дБ → 0…100%; выше −3 дБ — красный (перегруз).
            let pct = Math.max(0, Math.min(100, (s.level_db + 60) / 60 * 100));
            let lvl = document.getElementById('ttsRecLevel');
            lvl.style.width = pct + '%';
            lvl.classList.toggle('is-hot', s.level_db > -3);
            // Тихий микрофон: пики за последние ~5 с ниже −30 дБ (но звук есть).
            ttsRec.peaks = (ttsRec.peaks || []).concat(s.level_db).slice(-25);
            let top = Math.max(...ttsRec.peaks);
            let quiet = ttsRec.peaks.length >= 25 && top > -60 && top < -30;
            document.getElementById('ttsRecInfo').innerText = `записано: ${s.added}`
                + (quiet ? ' · микрофон тихий — громкость выровняется' : '')
                + (s.asr_s ? ` · распознавание ${s.asr_s} с` : '')
                + (s.pending_n > 1 ? ` · в очереди ${s.pending_n}` : '')
                + (s.overflows ? ` · ⚠ звук прерывался ${s.overflows} раз — компьютер не успевает` : '')
;
            if (s.error) showToast('Запись остановилась: ' + s.error);
            // Только что листали — не перебиваем выбранную фразу старым ответом опроса.
            if (s.prompt && performance.now() - ttsPromptNavAt > 600) ttsRenderPrompt(s.prompt, null, s.waiting);
            ttsSetPaused(s.paused);
            Object.assign(ttsLiveSt, { hearing: false, paused: false, waiting: false, busy: !!s.busy });
            if (!ttsPttDown) ttsLiveSt.holding = !!s.holding;
            let live = document.getElementById('ttsLive');
            if (live) live.style.setProperty('--lv', Math.max(0.15, Math.min(1, (s.level_db + 50) / 40)).toFixed(2));
            ttsLiveRender();
        }

        // Пауза (Space): ничего не фиксируется.
        function ttsSetPaused(paused) {
            let bar = document.getElementById('ttsRecBar');
            if (!bar || bar.classList.contains('is-paused') === !!paused) return;
            bar.classList.toggle('is-paused', !!paused);
            requestAnimationFrame(ttsFitPrompt);
            document.getElementById('ttsPromptPause').style.display = paused ? '' : 'none';
        }

        // ----- суфлёр: какую фразу читать сейчас -----
        let ttsPromptKey = null;
        // ----- листание фраз: ↑ / ↓ и колёсико мыши над суфлёром -----
        // Ровно на одну фразу в обе стороны. Целевую фразу считаем сразу у себя,
        // а ответ показываем только последний — при быстром листании без скачков.
        let ttsPromptPos = null, ttsPromptTotal = 0, ttsPromptSeq = 0, ttsPromptNavAt = 0;
        async function ttsPromptMove(step) {
            ttsPromptNavAt = performance.now();
            if (ttsPromptPos === null) {
                let pr = await pywebview.api.tts_prompt_move(step);
                if (pr) ttsRenderPrompt(pr, step < 0 ? 'up' : 'down', null, true);
                return;
            }
            let target = Math.max(0, Math.min(ttsPromptTotal - 1, ttsPromptPos + step));
            if (target === ttsPromptPos) { ttsPromptEdge(step); return; }
            ttsPromptPos = target;
            let seq = ++ttsPromptSeq;
            let pr = await pywebview.api.tts_prompt_goto(target);
            if (seq !== ttsPromptSeq || !pr) return;       // уже листнули дальше
            ttsPromptNavAt = performance.now();
            ttsRenderPrompt(pr, step < 0 ? 'up' : 'down', null, true);
        }
        // Дальше некуда — лёгкий толчок, чтобы было понятно, что это край списка.
        function ttsPromptEdge(step) {
            let text = document.getElementById('ttsPromptText');
            if (!text || !motionOK()) return;
            let d = step < 0 ? 1 : -1;
            text.animate([{ transform: 'translateY(0)' }, { transform: `translateY(${8 * d}px)` }, { transform: 'translateY(0)' }],
                         { duration: 220, easing: 'cubic-bezier(.3,.7,.4,1)' });
        }
        // Смена фразы: новая въезжает с той стороны, куда листаем.
        function ttsPromptAnim(dir) {
            if (!motionOK()) return;
            let d = dir === 'up' ? -1 : 1;
            let text = document.getElementById('ttsPromptText'), next = document.getElementById('ttsPromptNext');
            [text, next].forEach(el => el && el.getAnimations().forEach(a => a.cancel()));
            text.animate([{ opacity: 0, transform: `translateY(${34 * d}px) scale(.985)` },
                          { opacity: 1, transform: 'translateY(0) scale(1)' }],
                         { duration: 300, easing: 'cubic-bezier(.16,.84,.3,1)' });
            if (next) next.animate([{ opacity: 0, transform: `translateY(${14 * d}px)` }, { opacity: 1, transform: 'none' }],
                                   { duration: 360, delay: 40, easing: 'cubic-bezier(.16,.84,.3,1)', fill: 'backwards' });
        }
        (function ttsBindPromptWheel() {
            let box = document.getElementById('ttsPrompter');
            if (!box) return;
            let acc = 0, at = 0;
            box.addEventListener('wheel', e => {
                if (!tts || !tts.loaded || ttsPttDown) return;
                if (document.getElementById('stage4-tts').classList.contains('show-assembly')) return;
                e.preventDefault();
                acc += e.deltaY || e.deltaX;
                let now = performance.now();
                // Щелчок колёсика — одна фраза; тачпад шлёт много мелких — копим.
                if (Math.abs(acc) < 40 || now - at < 110) return;
                let dir = acc > 0 ? 1 : -1;
                acc = 0; at = now;
                ttsPromptMove(dir);
            }, { passive: false });
        })();

        function ttsRenderPrompt(pr, flash, waiting, browse) {
            if (pr && pr.logic_switched) {
                let n = { 1: 'логика 1 (миллионы + сотни + тысячи + тенге)', 2: 'логика 2 (миллионы + сотни тысяч + тенге)' };
                showToast(`Строки логики ${pr.logic_switched.from} прочитаны — дальше ${n[pr.logic_switched.to]}`, 5000);
                ttsPromptKey = null;
                if (tts) tts.sum_logic = pr.sum_logic;
            }
            let text = document.getElementById('ttsPromptText');
            let meta = document.getElementById('ttsPromptMeta');
            let next = document.getElementById('ttsPromptNext');
            if (pr.lang && pr.lang !== ttsLangNow) {
                if (ttsLangNow && tts && tts.lang_auto) ttsLiveFlash('lang', pr.lang === 'kz' ? 'Дальше по-казахски — распознаю на казахском' : 'Дальше по-русски — распознаю на русском');
                ttsLangNow = pr.lang;
                ttsLangShow(pr.lang);
            }
            if (pr.none) {
                text.innerHTML = '<span class="tts-dim">Загрузите таблицу</span>';
                meta.innerText = ''; next.innerText = ''; ttsPromptKey = null; ttsRenderMarks(null);
                return;
            }
            if (pr && pr.total) { ttsPromptPos = pr.pos; ttsPromptTotal = pr.total; }
            if (!browse && !pr.done && !pr.left && pr.pending) {
                text.innerHTML = '<span class="tts-dim">Всё прочитано — дораспознаю…</span>';
                meta.innerHTML = `<span>${ttsModesHTML(pr)}в очереди ${pr.pending}</span>`; next.innerText = ''; ttsPromptKey = null; ttsRenderMarks(null);
                return;
            }
            if (pr.done && !browse) {
                let vals = pr.mode && pr.mode !== 'phrases';
                let other = (pr.modes || []).filter(m => m.key !== (pr.mode || 'phrases'));
                text.innerHTML = pr.sum_logic ? 'Суммы прочитаны — обе логики 🎉' : vals ? 'Все строки прочитаны 🎉' : 'Все фразы прочитаны 🎉';
                // переключатель режимов (и логик сумм) — и здесь
                meta.innerHTML = `<span>${ttsModesHTML(pr)}${ttsSumLogicHTML(pr)}${ttsBatchChipHTML(pr)} ${pr.total} из ${pr.total}</span>`;
                next.innerHTML = other.length
                    ? `Дальше: ${other.map(m => `<button type="button" class="tts-reuse-chip is-on" onclick="ttsPromptModeSet('${m.key}')">${escapeHtml(m.label)} →</button>`).join(' ')}
                       <span class="tts-dim">· или сдавайте дубли: клик по карточке внизу — сборка, Enter — сохранить</span>`
                    : 'Сдавайте дубли: клик по карточке внизу — сборка, Enter — сохранить';
                ttsPromptKey = 'done';
                return;
            }
            // Место переменной — тихая пометка, чтобы не перебивать текст.
            let pill = v => v ? ` <span class="tts-slot" title="${escapeHtml(ttsVarLabel(v))}: прочитайте любое значение">${escapeHtml(ttsSlotLabel(v))}</span> ` : '';
            let line = (parts, tail) => parts.map(p => pill(p.var_before)
                + (p.kind === 'value' ? `<span class="tts-vcat">${escapeHtml(p.cat_label || '')}</span> ` : '')
                + (p.role === 'var' ? `<span class="tts-ivar" title="Значение переменной — сохранится отдельно">${escapeHtml(p.text)}</span>`
                   : p.tiers ? p.tiers.map(escapeHtml).join('<span class="tts-tiersep" title="Здесь программа разрежет на ярусы — небольшая пауза поможет"></span>')
                   : escapeHtml(p.text))
                + pill(p.var_after)).join(' ')
                + (tail ? ` <span class="tts-tail" title="Только начало продолжения — целиком прочитаете с последним значением">${escapeHtml(tail)}</span>` : '');
            let ru = pr.reuse && !pr.reuse.skip && pr.reuse.rest ? pr.reuse : null;
            let key = JSON.stringify(pr.current) + '|' + pr.pos + '|' + JSON.stringify(pr.resume || null) + '|' + JSON.stringify(pr.reuse || null);
            if (key !== ttsPromptKey) {
                ttsPromptKey = key;
                let ctx = pr.context && pr.current[0] && pr.current[0].kind === 'value' ? pr.context : null;
                text.innerHTML = pr.resume ? ttsResumeHTML(pr.current[0], pr.resume.k)
                    : ru ? ttsReuseHTML(pr.current[0], ru)
                    : ctx ? `<span class="tts-ctx" title="Начало фразы «${escapeHtml(ctx.start_name)}» — для интонации, не читать">${escapeHtml(ctx.before)}</span> ${line(pr.current, pr.tail)}`
                        + (ctx.after ? ` <span class="tts-ctx" title="Продолжение «${escapeHtml(ctx.end_name || '')}» — не читать">${escapeHtml(ctx.after)}</span>` : '')
                    : line(pr.current, pr.tail);
                text.classList.toggle('is-recorded', pr.here === 'done');
                if (flash === 'next' || flash === 'down' || flash === 'up') ttsPromptAnim(flash === 'up' ? 'up' : 'down');
            }
            let doneShare = pr.total ? Math.round((pr.total - pr.left) / pr.total * 100) : 0;
            let here = pr.here === 'done' && !pr.redo_here ? '<span class="tts-here tts-here--done">записана ✓</span> '
                : pr.here === 'pending' ? '<span class="tts-here tts-here--wait">распознаётся…</span> ' : '';
            let srcs = pr.reuse ? pr.reuse.srcs.map(n => '«' + escapeHtml(n) + '»').join(', ') : '';
            let reuseChip = pr.reuse ? (pr.reuse.rest
                ? (pr.reuse.skip
                    ? ` <button type="button" class="tts-reuse-chip" onclick="ttsReuseSkip(${pr.reuse.unit}, false)" title="Читать только выделенное, остальное подставлю из ${srcs}">${pr.reuse.pct}% уже записано · подставить</button>`
                    : ` <button type="button" class="tts-reuse-chip is-on" onclick="ttsReuseSkip(${pr.reuse.unit}, true)" title="Серое возьмётся из ${srcs} и склеится с новым в «Сборке». Нажмите, чтобы читать фразу целиком">${pr.reuse.pct}% из ${srcs} · читать целиком</button>`)
                : ` <button type="button" class="tts-reuse-chip is-on" onclick="ttsReuseBuild(${pr.reuse.unit})" title="Вся фраза уже звучит в ${srcs} — собрать без записи">целиком из записанного · собрать</button>`) : '';
            let modes = ttsModesHTML(pr);
            if (pr.context) modes += ` <button type="button" class="tts-reuse-chip ${pr.context.start_saved ? 'is-on' : ''}" onclick="ttsCtxPlay('start')"
                    title="${pr.context.start_saved ? 'Послушать записанное начало «' + escapeHtml(pr.context.start_name) + '» — и сразу читайте сумму в той же интонации' : 'Начало «' + escapeHtml(pr.context.start_name) + '» ещё не записано (режим «Фразы»)'}">&#9654; Начало</button>`;
            if (pr.sum_logic) modes += ttsSumLogicHTML(pr);
            modes += ttsBatchChipHTML(pr);
            if (pr.tier_tpl) modes += pr.tier_tpl.from
                ? ` <button type="button" class="tts-reuse-chip ${pr.tier_tpl.auto ? 'is-on' : ''}" onclick="ttsTierAutoSet(${!pr.tier_tpl.auto})" title="Шаблон ярусов — строка ${escapeHtml(pr.tier_tpl.from)}. Включено — записанная строка сохраняется сама, без «Сборки»">по шаблону сразу${pr.tier_tpl.auto ? ' ✓' : ''}</button>`
                : ` <span class="tts-dim" title="Сохраните первую строку в «Сборке» — её тайминг станет шаблоном для остальных">шаблон — после первой строки</span>`;
            let valN = pr.value_n ? ` <span class="tts-reuse-chip is-on" title="Значения переменной из таблицы читаются по очереди; продолжение фразы — целиком с последним">значение ${pr.value_n.k} из ${pr.value_n.n}</span>` : '';
            meta.innerHTML = `<span>${modes}${pr.redo_here ? '<span class="tts-redo-here">перезапись</span> ' : ''}${here}${pr.mode && pr.mode !== 'phrases' ? 'Строка' : 'Фраза'} <b>${pr.pos + 1}</b> из ${pr.total} · осталось ${pr.left}${pr.tiers_done ? ` · <span title="Сохранённые эталоны ярусов этого листа (одинаковые значения в разных строках — один файл)">эталонов ${pr.tiers_done[0]} из ${pr.tiers_done[1]}</span>` : ''}${reuseChip}${valN}`
                + (pr.redo ? ` · <button type="button" class="tts-redo-chip" onclick="ttsShowRedo()">к перезаписи: ${pr.redo}</button>` : '') + `</span>`
                + `<span class="tts-prompter__progress" title="Прочитано ${doneShare}%"><i style="width:${doneShare}%"></i></span>`
;
            next.innerHTML = pr.next ? `<span class="tts-prompter__next-label">Дальше</span> ${line(pr.next, pr.next_tail)}` : '';
            ttsRenderMarks(pr);
            ttsFitPrompt();
            if (flash === 'restart') {
                let box = document.getElementById('ttsPrompter');
                box.classList.remove('is-restart'); void box.offsetWidth; box.classList.add('is-restart');

            }
        }

        async function ttsRecStop() {
            clearInterval(ttsRec.timer);
            ttsRec.on = false;
            document.getElementById('ttsRecInfo').innerText = 'Останавливаю — дораспознаю последний кусок…';
            document.getElementById('ttsRecBtn').innerHTML = '… <kbd>R</kbd>';
            await pywebview.api.tts_rec_stop();
        }

        function ttsRecStopped(state, error) {
            clearInterval(ttsRec.timer);
            ttsSetPaused(false);
            ttsRec.on = false;
            ttsSetRecUi(false);
            ttsLiveSt.holding = ttsLiveSt.busy = false; ttsLiveSt.micOff = false; ttsLiveRender();
            if (state) ttsLiveUpdate(state, 0);
            ttsLoadPrompt();
            if (error) { showBeautifulAlert('⚠️ Запись остановилась с ошибкой:<br><br>' + escapeHtml(error)); return; }
            showToast('Запись сохранена в папку «Записи»');
            ttsShowRedo(true);
        }

        // ----- что перезаписать: сомнительные / нераспознанные / без привязки -----
        async function ttsShowRedo(auto) {
            let r = await pywebview.api.tts_redo_list();
            if (!r) return;
            if (auto && !r.redo.length && !r.loose.length) return;
            ttsOpenListOverlay(r.redo.length ? `Перезаписать: ${r.redo.length}` : 'Перезаписывать нечего', false);
            let rows = r.redo.map(x => `<button type="button" class="audit-category-item tts-redo-row" data-pos="${x.pos}">
                    <b>${escapeHtml(x.name)}</b> — ${escapeHtml(x.text)}
                    <span class="audit-choice-desc">${x.heard ? 'услышано: ' + escapeHtml(x.heard) : 'не распознано'}</span></button>`).join('');
            let loose = r.loose.length ? `<div class="tts-dev-head">Без привязки к фразе: ${r.loose.length}</div>
                <div class="tts-dim tts-mon-hint">Фразы с переменными, зафиксированные целиком. Откройте карточку на ленте — привяжите (F) и подрежьте, или удалите (Del).</div>
                ${r.loose.map(k => `<button type="button" class="audit-category-item" data-take="${k}">Дубль ${String((tts.takes[k] || {}).chunk || k + 1).padStart(3, '0')}
                    <span class="audit-choice-desc">${escapeHtml((tts.takes[k] || {}).heard || '')}</span></button>`).join('')}` : '';
            document.getElementById('ttsList').innerHTML =
                (r.redo.length ? `<div class="tts-dim tts-mon-hint">Распознались не полностью или с сомнением. Клик — суфлёр на эту фразу; «Перезаписать все» — по очереди с первой (R).</div>` : '')
                + rows + loose
                + `<div class="modal-actions">${r.redo.length ? '<button class="custom-alert-btn" id="ttsRedoAll">Перезаписать все</button>' : ''}
                   <button class="custom-alert-btn btn-secondary" onclick="ttsCloseList()">${r.redo.length ? 'Позже' : 'Закрыть'}</button></div>`;
            let go = async pos => {
                ttsCloseList();
                let pr = await pywebview.api.tts_prompt_goto(pos);
                if (pr) { ttsPromptKey = null; ttsRenderPrompt(pr, 'next'); }
                if (!ttsRec.on) showToast('Нажмите R — и читайте');
            };
            document.querySelectorAll('#ttsList [data-pos]').forEach(b => b.onclick = () => go(+b.dataset.pos));
            document.querySelectorAll('#ttsList [data-take]').forEach(b => b.onclick = () => { ttsCloseList(); ttsRailClick(+b.dataset.take); });
            let all = document.getElementById('ttsRedoAll');
            if (all) all.onclick = () => go(r.redo[0].pos);
        }

        // Новые дубли во время записи: не сбиваем то, что сейчас слушаете.
        function ttsLiveUpdate(state, added) {
            let keep = tts && tts.takes.length ? tts.index : null;
            let busy = ttsPlayingIdx >= 0 || (keep !== null && tts.takes[keep] && !tts.takes[keep].unit_saved && !tts.takes[keep].rejected);
            tts = state;
            if (busy && keep !== null && keep < tts.takes.length) tts.index = keep;
            ttsRenderRail();
            if (!busy) { ttsRenderCurrent(); ttsRenderAssembly(); }
            ttsRenderStats();
            if (busy) {
                let num = document.querySelector('#ttsCurrent .tts-current__num');
                if (num) num.innerText = `дубль ${tts.index + 1} / ${tts.takes.length}`;
            }
            if (added) {
                let rail = document.getElementById('ttsRail');
                rail.querySelectorAll('.tts-take').forEach((el, k) => { if (k >= tts.takes.length - added) el.classList.add('is-new'); });
            }
        }


        // ===== Отклик во время записи: слушаю / слышу / распознаю / итог =====
        let ttsLiveSt = { busy: false, hearing: false, waiting: false, paused: false, flash: null, flashT: null };

        const TTS_LIVE_CMD = {
            'cmd-redo': ['↺', 'Заново'], 'cmd-commit': ['✓', 'Зафиксировано'], 'cmd-pause': ['❚❚', 'Пауза'], 'cmd-resume': ['●', 'Продолжаем'], 'cmd-play': ['▶', 'Прослушать'],
        };

        // Итог разбора держится на экране ~2,5 с, потом — снова текущее состояние.
        function ttsLiveFlash(kind, text) {
            clearTimeout(ttsLiveSt.flashT);
            ttsLiveSt.flash = { kind, text: text || '', id: Date.now() };
            ttsLiveRender();
            ttsLiveSt.flashT = setTimeout(() => { ttsLiveSt.flash = null; ttsLiveRender(); }, kind.includes('miss') ? 3500 : 2500);
        }

        let ttsLiveKey = null;
        function ttsLiveRender() {
            let el = document.getElementById('ttsLive');
            if (!el) return;
            let f = ttsLiveSt.flash, cls, html;
            if (ttsRec.on && ttsLiveSt.micOff) {
                cls = 'is-off'; html = '<span class="lv-dot"></span><span>Микрофон выключен — идёт сборка (Esc — вернуться к записи)</span>';
            } else if (!ttsRec.on && !ttsRec.starting) {
                cls = f && f.kind === 'off' ? 'is-miss' : 'is-off';
                html = '<span class="lv-dot"></span><span>Запись выключена — нажмите <b>R</b></span>';
            } else if (f && f.kind === 'ok') {
                cls = 'is-ok'; html = `<span class="lv-ico">✓</span><span>Записано: <b>${escapeHtml(f.text)}</b></span>`;
            } else if (f && f.kind === 'lang') {
                cls = 'is-cmd'; html = `<span class="lv-ico">🌐</span><span>${escapeHtml(f.text)}</span>`;
            } else if (f && f.kind === 'miss-msg') {
                cls = 'is-miss'; html = `<span class="lv-ico">!</span><span>${escapeHtml(f.text)}</span>`;
            } else if (f && f.kind === 'miss') {
                cls = 'is-miss'; html = `<span class="lv-ico">✕</span><span>Не понял: «${escapeHtml(f.text)}»</span>`;
            } else if (f && f.kind === 'pause-miss') {
                cls = 'is-miss'; html = `<span class="lv-ico">❚❚</span><span>Пауза — не фиксирую. Space — продолжить</span>`;
            } else if (f && f.kind === 'partial') {
                cls = 'is-wait'; html = `<span class="lv-ico">▸</span><span>${escapeHtml(f.text)}</span>`;
            } else if (f && f.kind === 'mark') {
                cls = 'is-cmd'; html = `<span class="lv-ico">✎</span><span>Отмечено — ${escapeHtml(f.text)}</span>`;
            } else if (f && TTS_LIVE_CMD[f.kind]) {
                let [ico, name] = TTS_LIVE_CMD[f.kind];
                cls = 'is-cmd'; html = `<span class="lv-ico">${ico}</span><span>${escapeHtml(f.text || name)}</span>`;
            } else if (ttsLiveSt.holding) {
                cls = 'is-rec'; html = '<span class="lv-recdot"></span><span>Говорите… отпустите, когда закончите</span>';
            } else if (ttsLiveSt.busy) {
                cls = 'is-busy'; html = '<span class="lv-spin"></span><span>Распознаю…</span>';
            } else if (ttsLiveSt.paused) {
                cls = 'is-paused'; html = '<span class="lv-ico">❚❚</span><span>Пауза</span>';
            } else if (ttsLiveSt.hearing) {
                cls = 'is-hearing'; html = '<span class="lv-eq"><i></i><i></i><i></i><i></i><i></i></span><span>Слышу речь</span>';
            } else if (ttsLiveSt.waiting) {
                cls = 'is-wait'; html = '<span class="lv-dots"><i></i><i></i><i></i></span><span>Дочитайте фразу</span>';
            } else {
                cls = 'is-idle'; html = '<span class="lv-dot"></span><span>Держите Space и читайте</span>';
            }
            let key = cls + '|' + html + '|' + (f ? f.id : '');
            if (key === ttsLiveKey) return;
            let changed = !ttsLiveKey || ttsLiveKey.split('|')[0] !== cls || (f && !ttsLiveKey.endsWith('|' + f.id));
            ttsLiveKey = key;
            el.className = 'tts-live ' + cls;
            el.innerHTML = html;
            if (changed && motionOK()) { el.classList.remove('lv-pop'); void el.offsetWidth; el.classList.add('lv-pop'); }
            let text = document.getElementById('ttsPromptText');
            if (text) text.classList.toggle('is-busy', cls === 'is-busy');
        }


        // ===== Разметка таблицы прямо на суфлёре =====
        // Роль строки: 1 — start, 2 — start_2, 3 — end, 0 — снять; переменные
        // (колонки справа: Сумма, Дата…) — 4, 5…; клик по чипу — то же самое.
        // Клавиши действуют на последнюю строку текущей фразы суфлёра.
        const TTS_ROLES = [['start', 'start'], ['start_2', 'start_2'], ['end', 'end']];
        let ttsPromptNow = null;

        function ttsRenderMarks(pr) {
            ttsPromptNow = pr;
            let box = document.getElementById('ttsMarks');
            if (!box) return;
            if (!pr || pr.done || !pr.current) { box.innerHTML = ''; return; }
            let vars = pr.var_cols || [];
            let last = pr.current.length - 1;
            box.innerHTML = pr.current.map((p, k) => `
                <div class="tts-marks__row ${k === last ? 'is-keys' : ''}">
                    <span class="tts-marks__name" title="${escapeHtml(p.text)}">${escapeHtml(p.name)}</span>
                    ${TTS_ROLES.map(([r, label], i) => `<button type="button" class="tts-mark ${p.role === r ? 'is-on' : ''}"
                        onclick="ttsSetMark(${p.id}, 'role', '${r}')">${k === last ? `<kbd>${i + 1}</kbd>` : ''}${label}</button>`).join('')}
                    <span class="tts-marks__sep"></span>
                    ${vars.map((v, i) => `<button type="button" class="tts-mark tts-mark--var ${(p.vars || []).includes(v.key) ? 'is-on' : ''}"
                        onclick="ttsSetMark(${p.id}, 'var', '${v.key}')">${k === last ? `<kbd>${i + 4}</kbd>` : ''}${escapeHtml(v.label)}</button>`).join('')}
                </div>`).join('');
        }

        function ttsMarkKey(n) {
            let pr = ttsPromptNow;
            if (!pr || pr.done || !pr.current || !pr.current.length) return;
            let p = pr.current[pr.current.length - 1];
            if (n === 0) ttsSetMark(p.id, 'role', null);
            else if (n <= 3) ttsSetMark(p.id, 'role', TTS_ROLES[n - 1][0]);
            else { let v = (pr.var_cols || [])[n - 4]; if (v) ttsSetMark(p.id, 'var', v.key); }
        }

        async function ttsSetMark(unitId, what, value) {
            let cur = ttsPromptNow && ttsPromptNow.current.find(p => p.id === unitId);
            if (what === 'role' && cur && cur.role === value) value = null;          // повторный клик — снять
            let res = await pywebview.api.tts_set_mark(unitId, what, value);
            if (!res || res.error) { showToast(res && res.error || 'Не удалось отметить'); return; }
            if (res.state) ttsLiveUpdate(res.state, 0);
            if (res.prompt) { ttsPromptKey = null; ttsRenderPrompt(res.prompt); }
            let label = what === 'role' ? (value || 'без роли') : ((ttsPromptNow.var_cols || []).find(v => v.key === value) || {}).label;
            ttsLiveFlash('mark', `${cur ? cur.name : ''}: ${label}`);
        }

        function ttsShowMarksPending(n, error) {
            let btn = document.getElementById('ttsMarksBtn');
            if (!btn) return;
            btn.style.display = n ? '' : 'none';
            btn.innerText = `Разметка не записана в таблицу: ${n}`;
            if (error && n) btn.title = error;
            if (error && n && !ttsShowMarksPending.warned) { ttsShowMarksPending.warned = true; showToast(error); }
            if (!n) ttsShowMarksPending.warned = false;
            // Таблица открыта в Excel — пробуем дописать раз в 10 с, пока не получится.
            clearInterval(ttsShowMarksPending.timer);
            if (n) ttsShowMarksPending.timer = setInterval(async () => {
                let r = await pywebview.api.tts_marks_write();
                if (r && !r.pending) { ttsShowMarksPending(0); showToast('Разметка записана в таблицу'); }
            }, 10000);
        }

        async function ttsMarksRetry() {
            let res = await pywebview.api.tts_marks_write();
            ttsShowMarksPending(res.pending, res.error);
            showToast(res.saved ? 'Разметка записана в таблицу' : (res.error || 'Не удалось записать'));
        }


        // ===== Клавиши во время записи =====
        async function ttsLiveAction(action) {
            if (!ttsRec.on) return;
            if (action === 'play') { await ttsStopPlay(); ttsRenderRail(); }
            let res = await pywebview.api.tts_live_key(action);
            if (!res || res.error) { if (res && res.error) ttsLiveFlash('miss-msg', res.error); return; }
            if (res.cancelled || action === 'commit') { ttsLiveSt.busy = false; ttsLiveSt.holding = false; }
            if (res.state) ttsLiveUpdate(res.state, 0);
            if (res.prompt) { ttsPromptKey = null; ttsRenderPrompt(res.prompt, action === 'redo' ? 'restart' : null); }
            ttsSetPaused(res.paused);
            ttsLiveSt.paused = !!res.paused;
            let kind = action === 'pause' ? (res.paused ? 'cmd-pause' : 'cmd-resume') : 'cmd-' + action;
            if (action === 'pause' && !res.paused) ttsSetPaused(false);
            ttsLiveFlash(kind, res.message);
        }

        // «sum_ru» → «сумма», «date_ru» → «дата» — коротко, для пометки в тексте суфлёра.
        function ttsSlotLabel(key) {
            return ttsVarLabel(key).replace(/\s+(RU|KZ|KK)$/i, '').toLowerCase();
        }

        // Размер текста суфлёра — под длину фразы: длинная фраза уменьшается,
        // пока не поместится целиком в своё поле (короткая — крупно).
        const TTS_PROMPT_MAX = 58, TTS_PROMPT_MIN = 20;
        function ttsFitPrompt() {
            let stage = document.getElementById('stage4-tts');
            let box = document.getElementById('ttsPrompter');
            let text = document.getElementById('ttsPromptText');
            if (!stage || !box || !text) return;
            if (!stage.classList.contains('is-prompter')) { text.style.fontSize = ''; return; }
            // Всё остальное в поле суфлёра (номер, «Дальше», разметка, подсказка) — по факту.
            let others = 0, shown = 0;
            [...box.children].forEach(el => {
                if (el === text || !el.offsetParent || !el.offsetHeight) return;
                others += el.offsetHeight; shown++;
            });
            let cs = getComputedStyle(box);
            let gaps = (parseFloat(cs.rowGap) || 0) * shown + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
            let avail = box.clientHeight - others - gaps - 8;
            let maxByWidth = Math.max(TTS_PROMPT_MIN, Math.min(TTS_PROMPT_MAX, window.innerWidth / 30));
            let size = maxByWidth;
            text.style.fontSize = size + 'px';
            while (size > TTS_PROMPT_MIN && text.scrollHeight > avail) {
                size -= 2;
                text.style.fontSize = size + 'px';
            }
        }
        window.addEventListener('resize', () => requestAnimationFrame(ttsFitPrompt));



        // ===== Запись «как голосовое»: держите Space (или кнопку) — пишу =====
        let ttsPttDown = false;
        async function ttsPtt(down) {
            if (!ttsRec.on || ttsPttDown === down) return;
            ttsPttDown = down;
            if (!down && ttsAutoAsmPending) { let n = ttsAutoAsmPending; ttsAutoAsmPending = 0; setTimeout(() => ttsAutoAsm(n), 0); }
            ttsLiveSt.holding = down;
            if (!down) ttsLiveSt.busy = true;          // сразу «Распознаю…»
            document.getElementById('ttsRecBar').classList.toggle('is-holding', down);
            ttsLiveRender();
            let res = await pywebview.api.tts_ptt(down);
            if (res && res.error) { showToast(res.error); ttsLiveSt.busy = false; ttsLiveRender(); }
            // «Не ждать»: суфлёр уже на следующей фразе.
            if (res && res.prompt) { ttsPromptKey = null; ttsRenderPrompt(res.prompt, 'next'); }
            else if (res && res.checking) ttsLiveFlash('partial', res.resuming ? 'Продолжение — проверяю, дочитана ли фраза…' : 'Похоже, фраза не дочитана — проверяю, что записано…');
        }

        // ----- «Проверять сразу»: записали фразу — «Сборка» открывается сама -----
        // Дубль сразу звучит; подрезали → Enter сохраняет и возвращает к чтению.
        let ttsAutoAsmPending = 0, ttsAsmQueue = [], ttsAsmAuto = false;          // ещё не проверенные из этой записи (по файлу)
        function ttsAutoAsmOn() {
            try { return localStorage.getItem('gvox_tts_autoasm') !== '0'; } catch (e) { return true; }
        }
        function ttsAutoAsmRender() {
            let b = document.getElementById('ttsAutoAsmBtn');
            if (!b) return;
            let on = ttsAutoAsmOn();
            b.classList.toggle('is-on', on);
            b.innerHTML = on ? '&#9986; Проверять сразу: вкл' : '&#9986; Проверять сразу: выкл';
        }
        function ttsAutoAsmToggle() {
            let on = !ttsAutoAsmOn();
            try { localStorage.setItem('gvox_tts_autoasm', on ? '1' : '0'); } catch (e) {}
            ttsAutoAsmRender();
            showToast(on ? 'Записали фразу — сразу открою «Сборку» для проверки' : 'Сборка — только по кнопке');
        }
        // ----- Пакет переменных: записали подряд N строк → разметили и сохранили разом -----
        // В суфлёре режим «пакет N»: после записи строки «Сборка» не открывается;
        // набралось N строк — открывается пакет: у каждой строки волна дубля с
        // клипами ярусов (края тянутся мышью), ▶ — послушать; Enter — сохранить все.
        const TTS_BATCH_STEPS = [0, 5, 10, 20];
        const ttsBatchN = () => { try { let v = localStorage.getItem('gvox_tier_batch'); return v === null ? 10 : +v; } catch (e) { return 10; } };
        function ttsBatchCycle() {
            let i = TTS_BATCH_STEPS.indexOf(ttsBatchN());
            let n = TTS_BATCH_STEPS[(i + 1) % TTS_BATCH_STEPS.length];
            try { localStorage.setItem('gvox_tier_batch', String(n)); } catch (e) {}
            showToast(n ? `Пакет по ${n} строк: записываете подряд, потом размечаете и сохраняете разом` : 'Пакет выключен: каждая строка — сразу в «Сборку»');
            ttsPromptKey = null; ttsLoadPrompt();
        }
        // Сколько записанных, но не сохранённых строк текущего листа (по одной на строку).
        function ttsBatchPending() {
            if (!tts || !tts.takes) return 0;
            let seen = new Set(), last = {};
            tts.takes.forEach((t, k) => {
                let u = t.unit !== null && t.unit !== undefined ? tts.units[t.unit] : null;
                if (!u || !u.tiers || u.sheet !== tts.prompt_mode || (u.logic && u.logic !== tts.sum_logic) || t.rejected) return;
                last[u.id] = t;
            });
            return Object.values(last).filter(t => !t.approved).length;
        }
        function ttsBatchChipHTML(pr) {
            if (!pr || !pr.mode || pr.mode === 'phrases') return '';
            let n = ttsBatchN(), k = ttsBatchPending();
            return ` <button type="button" class="tts-reuse-chip ${n ? 'is-on' : ''}" onclick="ttsBatchCycle()" title="Сколько строк записывать подряд перед разметкой (клик — 5 / 10 / 20 / выкл)">пакет ${n || 'выкл'}</button>`
                + (k ? ` <button type="button" class="tts-reuse-chip is-on" onclick="ttsBatchOpen()" title="Разметить и сохранить записанные строки">разметить ${k}${n ? ' / ' + n : ''}</button>` : '');
        }
        let ttsBatch = null;
        async function ttsBatchOpen() {
            let r = await pywebview.api.tts_tier_batch(30);
            if (!r || !r.rows || !r.rows.length) { showToast('Нет записанных несохранённых строк'); return; }
            await ttsStopPlay();
            ttsBatch = r;
            let el = document.getElementById('ttsBatch');
            if (!el) { el = document.createElement('div'); el.id = 'ttsBatch'; el.className = 'tts-batch'; document.body.appendChild(el); }
            el.style.display = 'flex';
            if (ttsRec.on && !ttsLiveSt.micOff) { ttsLiveSt.micOff = true; pywebview.api.tts_live_mic(false); ttsLiveRender(); }
            ttsBatchRender();
        }
        function ttsBatchClose() {
            let el = document.getElementById('ttsBatch');
            if (el) el.style.display = 'none';
            ttsBatch = null;
            pywebview.api.tts_stop_audio();
            if (ttsRec.on && ttsLiveSt.micOff) { ttsLiveSt.micOff = false; pywebview.api.tts_live_mic(true); ttsLiveRender(); }
        }
        const ttsBatchIsOpen = () => { let el = document.getElementById('ttsBatch'); return !!(el && el.style.display === 'flex'); };
        function ttsBatchRowHTML(r, n) {
            let L = r.length || 1, pct = ms => (100 * ms / L).toFixed(3) + '%';
            let regs = r.tiers.map(t => `<div class="tts-tiers__reg ${t.exists && !t.write ? 'is-skip' : ''}" style="left:${pct(t.a)};width:${pct(t.b - t.a)}"
                    title="${escapeHtml(t.label)}: ${escapeHtml(t.text)} — края тяните мышью"><span>${escapeHtml(t.label)}</span>
                    <i class="tts-tiers__edge is-l" onpointerdown="ttsBatchEdge(event, ${n}, ${t.k}, 'a')"></i>
                    <i class="tts-tiers__edge is-r" onpointerdown="ttsBatchEdge(event, ${n}, ${t.k}, 'b')"></i></div>`).join('');
            let chips = r.tiers.map(t => `<span class="tts-batch__chip ${t.exists && !t.write ? 'is-skip' : ''}">
                    <button type="button" onclick="ttsBatchPlay(${n}, ${t.k})" title="Послушать ярус">&#9654;</button>${escapeHtml(t.label)} <b>${escapeHtml(t.value)}</b>
                    ${t.exists ? `<label title="Уже сохранён из другой строки"><input type="checkbox" ${t.write ? 'checked' : ''} onchange="ttsBatchWrite(${n}, ${t.k}, this.checked)"> есть · перезаписать</label>` : ''}</span>`).join('');
            return `<div class="tts-batch__row" id="ttsBatchRow${n}">
                <div class="tts-batch__head"><b>${n + 1}</b> <span class="tts-batch__txt">${escapeHtml(r.row)}</span>
                    ${ttsJoinHTML(r.tiers, 'ttsBatchJoin' + n + '_')}
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsBatchPlay(${n}, -2)" title="Стык: конец начала фразы + строка + начало продолжения (по ${TTS_JOIN_MS / 1000} с)">&#9654; Стык</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsBatchPlay(${n}, -1)" title="Вся строка с началом и концом фразы — как склеится">&#9654; Строка</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsBatchDelete(${n})" title="Удалить дубль — строку можно перезаписать">✕</button></div>
                <div class="tts-tiers__wave tts-batch__wave"><canvas style="width:100%"></canvas>${regs}</div>
                <div class="tts-batch__chips">${chips}</div></div>`;
        }
        function ttsBatchRender() {
            let el = document.getElementById('ttsBatch');
            if (!el || !ttsBatch) return;
            let rows = ttsBatch.rows;
            el.innerHTML = `<div class="tts-batch__box">
                <div class="tts-batch__top"><b>Пакет: ${rows.length} ${rows.length === 1 ? 'строка' : rows.length < 5 ? 'строки' : 'строк'}</b>
                    <span class="tts-dim">границы ярусов поставлены сами (по шаблону, если он есть) — поправьте, где нужно; ▶ — послушать</span>
                    ${ttsBgHTML(ttsBatch.bg)}
                    <span class="tts-batch__sp"></span>
                    <button type="button" class="btn-tile btn-tile--good" onclick="ttsBatchSave()">Сохранить все <kbd>Enter</kbd></button>
                    <button type="button" class="btn-tile btn-tile--sub" onclick="ttsBatchClose()">Закрыть <kbd>Esc</kbd></button></div>
                <div class="tts-batch__list">${rows.map((r, n) => ttsBatchRowHTML(r, n)).join('')}</div></div>`;
            rows.forEach((r, n) => { window['ttsBatchJoin' + n + '_'] = ttsBatchJoinFn(n); ttsDrawPeaks(el.querySelector(`#ttsBatchRow${n} canvas`), r.peaks); });
        }
        function ttsBatchRowRefresh(n) {
            let old = document.getElementById('ttsBatchRow' + n);
            if (!old) return;
            let tmp = document.createElement('div'); tmp.innerHTML = ttsBatchRowHTML(ttsBatch.rows[n], n);
            old.replaceWith(tmp.firstElementChild);
            ttsDrawPeaks(document.querySelector(`#ttsBatchRow${n} canvas`), ttsBatch.rows[n].peaks);
        }
        function ttsBatchEdge(e, n, k, side) {
            e.preventDefault(); e.stopPropagation();
            let r = ttsBatch.rows[n], t = r.tiers[k];
            let move = ev => {
                let box = document.querySelector(`#ttsBatchRow${n} .tts-batch__wave`);
                let rc = box && box.getBoundingClientRect();
                if (!rc || !rc.width) return;
                let ms = Math.round((ev.clientX - rc.left) / rc.width * r.length);
                if (side === 'a') t.a = Math.max(0, Math.min(t.b - 40, ms)); else t.b = Math.min(r.length, Math.max(t.a + 40, ms));
                ttsBatchRowRefresh(n);
            };
            let up = async () => {
                window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
                let res = await pywebview.api.tts_tier_set(r.i, r.tiers.map(x => ({ a: x.a, b: x.b, pre: x.pre, post: x.post, tempo: x.tempo, gain: x.gain })), null);
                if (res && res.tiers) res.tiers.forEach((x, j) => Object.assign(r.tiers[j], { a: x.a, b: x.b }));
                ttsBatchRowRefresh(n);
            };
            window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
        }
        async function ttsBatchPlay(n, k) {
            await pywebview.api.tts_stop_audio();
            let r = ttsBatch.rows[n];
            let res = k === -2 ? await pywebview.api.tts_tier_play(r.i, null, 0, TTS_JOIN_MS)
                : k < 0 ? await pywebview.api.tts_tier_play(r.i, null, 0) : await pywebview.api.tts_tier_play(r.i, k, null);
            if (res && res.error) showToast(res.error);
        }
        // ttsBatchJoin<n>_(which, d) — пауза у стыка строки n (имя с номером: так проще из onclick)
        function ttsBatchJoinFn(n) {
            return async (which, d) => {
                let r = ttsBatch.rows[n], tiers = r.tiers, t = which === 'pre' ? tiers[0] : tiers[tiers.length - 1];
                t[which] = Math.max(0, Math.min(1500, (t[which] || 0) + d));
                ttsBatchRowRefresh(n);
                await pywebview.api.tts_tier_set(r.i, tiers.map(x => ({ a: x.a, b: x.b, pre: x.pre, post: x.post, tempo: x.tempo, gain: x.gain })), null);
                ttsBatchPlay(n, -2);
            };
        }
        async function ttsBatchWrite(n, k, on) {
            let r = ttsBatch.rows[n], w = {};
            r.tiers.forEach(x => { w[x.k] = x.k === k ? on : x.write; });
            let res = await pywebview.api.tts_tier_set(r.i, null, w);
            if (res && res.tiers) res.tiers.forEach((x, j) => { r.tiers[j].write = x.write; });
            ttsBatchRowRefresh(n);
        }
        async function ttsBatchDelete(n) {
            let res = await pywebview.api.tts_take_delete(ttsBatch.rows[n].i);
            if (res && !res.error) tts = res;
            let r = await pywebview.api.tts_tier_batch(30);
            ttsRender(); ttsLoadPrompt();
            if (!r || !r.rows.length) { ttsBatchClose(); return; }
            ttsBatch = r; ttsBatchRender();
        }
        async function ttsBatchSave() {
            if (!ttsBatch) return;
            await pywebview.api.tts_stop_audio();
            let res = await pywebview.api.tts_tier_batch_save(ttsBatch.rows.map(r => r.i));
            if (!res || res.error) { showToast(res && res.error || 'Не получилось'); return; }
            tts = res;
            showToast(`Пакет сохранён: эталонов ${res.batch_saved}${res.batch_skipped ? ` · уже были: ${res.batch_skipped}` : ''}${res.batch_errors.length ? ' · ошибки: ' + res.batch_errors.join('; ') : ''}`, 5000);
            ttsBatchClose();
            ttsRender(); ttsPromptKey = null; ttsLoadPrompt();
        }
        function ttsBatchKey(e) {
            if (e.code === 'Enter' || e.code === 'NumpadEnter') { e.preventDefault(); ttsBatchSave(); }
            else if (e.code === 'Escape') { e.preventDefault(); ttsBatchClose(); }
            else if (e.code === 'Space') { e.preventDefault(); pywebview.api.tts_stop_audio(); }
            return true;
        }

        function ttsAutoAsm(added) {
            if (!(added > 0) || !ttsRec.on || !tts || !tts.takes.length) return;
            if (ttsPttDown) { ttsAutoAsmPending = added; return; }     // сейчас пишут — откроем, когда отпустят
            // пакет строк переменных: «Сборку» не открываем, набралось N — открываем пакет
            let freshT = tts.takes.slice(-added);
            if (ttsBatchN() && freshT.every(t => t.unit !== null && t.unit !== undefined && tts.units[t.unit] && tts.units[t.unit].tiers)) {
                ttsPromptKey = null; ttsLoadPrompt();
                if (ttsBatchPending() >= ttsBatchN() && !ttsBatchIsOpen()) ttsBatchOpen();
                return;
            }
            if (!ttsAutoAsmOn()) return;
            let fresh = tts.takes.slice(-added).map(t => t.file);
            if (document.getElementById('stage4-tts').classList.contains('show-assembly') && ttsAsmAuto) {
                ttsAsmQueue.push(...fresh);                             // кусочки той же фразы — по очереди после Enter
                return;
            }
            ttsAsmQueue = fresh.slice(1);
            let overlays = ['ttsVarsOverlay', 'ttsListOverlay', 'ttsMarkOverlay', 'customAlertOverlay'];
            if (overlays.some(id => { let el = document.getElementById(id); return el && el.style.display === 'flex'; })) return;
            tts.index = tts.takes.length - added;                       // первый из только что записанных
            ttsRenderRail();
            ttsRenderCurrent();
            ttsShowAssembly(true);
            ttsAsmAuto = true;
            ttsTogglePlay();
        }

        // ----- «Без распознавания»: дубль = фраза на суфлёре, без ожидания и без модели -----
        function ttsNoAsrOn() {
            try { return localStorage.getItem('gvox_tts_noasr') !== '0'; } catch (e) { return true; }
        }
        async function ttsNoAsrToggle() {
            let on = !ttsNoAsrOn();
            if (ttsRec.on && !on) showToast('Загружаю распознавание…');
            let res = await pywebview.api.tts_live_no_asr(on);
            if (res && res.error) {
                if (res.error === 'need_model' || res.error === 'need_model_kz') showAsrModel(res.error === 'need_model_kz' ? 'kz' : 'ru');
                else showToast(res.error);
                return;
            }
            try { localStorage.setItem('gvox_tts_noasr', on ? '1' : '0'); } catch (e) {}
            ttsFastRender();
            showToast(on ? 'Без распознавания: отпустили Space — дубль сразу к фразе на суфлёре'
                         : 'С распознаванием: программа сверяет, что прочитано');
        }
        function ttsNoAsrRender() {
            let b = document.getElementById('ttsNoAsrBtn');
            if (!b) return;
            let on = ttsNoAsrOn();
            b.classList.toggle('is-on', on);
            b.innerHTML = on ? 'Без распознавания' : 'С распознаванием';
            let fast = document.getElementById('ttsFastBtn');
            if (fast) fast.style.display = on ? 'none' : '';      // «Не ждать» — только когда распознаём
        }

        // ----- «Не ждать распознавания» (по умолчанию — для казахского) -----
        const ttsFastKey = () => 'gvox_tts_fast_' + ((tts && tts.lang) || 'ru');
        function ttsFastOn() {
            let v = null;
            try { v = localStorage.getItem(ttsFastKey()); } catch (e) {}
            return v === null ? true : v === '1';
        }
        function ttsFastRender() {
            let b = document.getElementById('ttsFastBtn');
            if (!b) return;
            let on = ttsFastOn();
            b.classList.toggle('is-on', on);
            b.innerHTML = on ? '&#9889; Не ждать: вкл' : '&#9889; Не ждать: выкл';
            ttsAutoAsmRender();
            ttsNoAsrRender();
        }
        async function ttsFastToggle() {
            let on = !ttsFastOn();
            try { localStorage.setItem(ttsFastKey(), on ? '1' : '0'); } catch (e) {}
            await pywebview.api.tts_live_fast(on);
            ttsFastRender();
            showToast(on ? 'Не жду распознавания: отпустили Space — сразу следующая фраза, нераспознанное станет жёлтым'
                         : 'Жду распознавания: следующая фраза — после того, как фраза распознана');
        }
        document.addEventListener('keyup', e => {
            if (ttsRec.on && e.code === 'Space') { e.preventDefault(); ttsPtt(false); }
        });
        // Backspace, пока держите Space: кусок выбрасывается сразу (бэкенд
        // сбросит его сам) — отпускание Space потом ничего не отправит.
        function ttsPttCancel() {
            if (!ttsPttDown) return;
            ttsPttDown = false;
            ttsLiveSt.holding = false;
            document.getElementById('ttsRecBar').classList.remove('is-holding');
            ttsLiveRender();
        }
        window.addEventListener('blur', () => { if (ttsPttDown) ttsPtt(false); });
        // Мышью: зажать кнопку записи или сам текст суфлёра.
        document.addEventListener('mousedown', e => {
            if (!ttsRec.on || e.button !== 0) return;
            if (e.target.closest && e.target.closest('#ttsHoldBtn, #ttsPromptText')) { e.preventDefault(); ttsPtt(true); }
        });
        document.addEventListener('mouseup', () => { if (ttsPttDown) ttsPtt(false); });

        // Длинная фраза, диктор сбился: верное начало — подсвечено, дальше —
        // «продолжите отсюда». Слова — как на экране (по пробелам), как и на бэкенде.
        // Переключатель «Фразы / Сумма RU / Дата RU» — на суфлёре всегда, и когда всё прочитано.
        // Логики сумм: 1 — миллионы + сотни + тысячи + тенге, 2 — миллионы + сотни тысяч + тенге.
        // Рядом — сколько строк каждой ещё читать.
        function ttsSumLogicHTML(pr) {
            if (!pr.sum_logic) return '';
            let left = pr.logic_left || {};
            let b = (l, lbl, tip) => `<button type="button" class="tts-pmode ${pr.sum_logic === l ? 'is-on' : ''}" onclick="ttsSumLogic(${l})"
                title="${tip}${left[l] !== undefined ? ' · осталось строк: ' + left[l] : ''}">${lbl}${left[l] === 0 ? ' ✓' : left[l] !== undefined ? ` <small>${left[l]}</small>` : ''}</button>`;
            return ' ' + b(1, '1 101 001', 'Логика 1: миллионы + сотни + тысячи + тенге') + b(2, '1 100 001', 'Логика 2: миллионы + сотни тысяч + тенге');
        }

        function ttsModesHTML(pr) {
            return (pr.modes || []).length > 1 ? ` <span class="tts-pmodes">${pr.modes.map(m =>
                `<button type="button" class="tts-pmode ${m.key === (pr.mode || 'phrases') ? 'is-on' : ''}" onclick="ttsPromptModeSet('${m.key}')"
                    title="${m.key === 'phrases' ? 'Читать фразы таблицы' : 'Записать значения листа «' + escapeHtml(m.label) + '» по порядку строк таблицы'}">${escapeHtml(m.label)}</button>`).join('')}</span>` : '';
        }

        // Начало фразы (перед записью суммы) / сумма в фразе (в «Сборке»).
        async function ttsCtxPlay(which, takeI) {
            await ttsStopPlay();
            let r = await pywebview.api.tts_value_context_play(which, takeI === undefined ? null : takeI);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            if (r.end_missing) showToast('Продолжение фразы ещё не записано — звучит начало и сумма');
        }
        async function ttsSumLogic(l) {
            let r = await pywebview.api.tts_sum_logic(l);
            if (!r) return;
            tts = r.state; ttsRender(); ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt, 'next');
        }
        async function ttsSumsOpen() {
            let pr = await pywebview.api.tts_prompt_info();
            if (!pr || !pr.sum_folder) return;
            if (ttsRec.on) { showToast('Сначала остановите запись (R)'); return; }
            startPremadeSumMode(pr.sum_folder);
        }

        // Что читать: фразы таблицы или значения листа переменных по порядку строк.
        async function ttsPromptModeSet(mode) {
            let r = await pywebview.api.tts_prompt_mode(mode);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            tts = r.state;
            ttsRender();
            ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt, 'next');
            showToast(mode === 'phrases' ? 'Читаем фразы таблицы'
                : r.prompt && r.prompt.sum_logic ? 'Читаем суммы строками — Enter в «Сборке» сохранит ярусы сразу эталонами в «Проверенные/Суммы»'
                : 'Читаем строки таблицы — Enter в «Сборке» сохранит каждое значение эталоном в «Значения»', 5000);
        }

        // Фраза на 80%+ уже записана: записанное — тихо, остаток — крупно.
        function ttsReuseHTML(p, r) {
            // серое — уже записано (подставлю сам), яркое — прочитать; несколько мест — с паузой между ними
            let recN = r.pieces.filter(x => x.kind === 'rec').length;
            return r.pieces.map((x, n) => x.kind === 'have'
                ? `<span class="tts-done" title="Уже записано в «${escapeHtml(x.src_name)}» — подставлю сам">${escapeHtml(x.text)}</span>`
                : (n === 0 || recN > 1 ? '' : `<span class="tts-resume">${n === r.pieces.length - 1 ? 'дочитайте' : 'прочитайте'}</span> `) + `<span class="tts-rest">${escapeHtml(x.text)}</span>`).join(' ')
                + (recN > 1 ? ` <span class="tts-resume">прочитайте выделенное по порядку, с паузой</span>` : '');
        }
        async function ttsReuseBuild(uid) {
            let res = await pywebview.api.tts_reuse_build(uid);
            if (!res || res.error) { showToast(res && res.error || 'Не получилось'); return; }
            tts = res;
            ttsRender();
            ttsShowAssembly(true);
            ttsTogglePlay();
            showToast(`«${res.built}» собрана из записанного — подровняйте стыки и сохраните (Enter)`, 5000);
        }
        async function ttsReuseSkip(uid, skip) {
            await pywebview.api.tts_reuse_skip(uid, skip);
            ttsPromptKey = null;
            ttsLoadPrompt();
        }
        // Список: какие фразы почти целиком уже есть в записанном.
        async function ttsShowReuse() {
            let r = await pywebview.api.tts_reuse_list();
            if (!r) return;
            ttsOpenListOverlay(r.items.length ? `Из записанного: ${r.items.length}` : 'Совпадений нет', false);
            let rows = r.items.map(x => {
                let parts = x.pieces.map(p => p.kind === 'have'
                    ? `<span class="tts-done" title="из «${escapeHtml(p.src_name)}»">${escapeHtml(p.text)}</span>`
                    : `<span class="tts-rest">${escapeHtml(p.text)}</span>`).join(' ');
                return `<button type="button" class="audit-category-item tts-redo-row" data-pos="${x.pos}">
                    <span><b>${escapeHtml(x.name)}</b> — ${x.pct}% уже записано в ${x.srcs.map(n => '<b>' + escapeHtml(n) + '</b>').join(', ')}</span>
                    <span class="audit-choice-desc tts-reuse-parts">${parts}</span>
                    <span class="audit-choice-desc">${x.rest ? `дописать: «${escapeHtml(x.rest)}»` : 'целиком из записанного — соберите без записи'}</span></button>`;
            }).join('');
            document.getElementById('ttsList').innerHTML =
                (r.items.length ? `<div class="tts-dim tts-mon-hint">Части этих фраз уже звучат в записанных (серым — откуда взять, ярким — что дописать). В режиме «Без распознавания» суфлёр попросит прочитать только новое, а записанное само встанет на дорожку «Сборки» — останется подровнять стыки. Клик — суфлёр на эту фразу.</div>` : '<div class="tts-dim tts-mon-hint">Пока нет фраз, которые хотя бы на 40% собираются из записанного.</div>')
                + rows + `<div class="modal-actions"><button class="custom-alert-btn btn-secondary" onclick="ttsCloseList()">Закрыть</button></div>`;
            document.querySelectorAll('#ttsList [data-pos]').forEach(b => b.onclick = async () => {
                ttsCloseList();
                let pr = await pywebview.api.tts_prompt_goto(+b.dataset.pos);
                if (pr) { ttsPromptKey = null; ttsRenderPrompt(pr, 'next'); }
            });
        }

        function ttsResumeHTML(p, k) {
            let toks = String(p.text || '').split(/\s+/).filter(Boolean);
            let done = toks.slice(0, k).map(escapeHtml).join(' ');
            let rest = toks.slice(k).map(escapeHtml).join(' ');
            return `<span class="tts-done" title="Уже записано">${done}</span> `
                + `<span class="tts-resume">продолжите отсюда</span> <span class="tts-rest">${rest}</span>`;
        }


        // Счётчики в шапке — всегда по текущему состоянию.
        function ttsRenderStats() {
            if (!tts) return;
            let s = tts.stats;
            document.getElementById('ttsStatSaved').innerText = s.saved;
            document.getElementById('ttsStatUnits').innerText = s.units;
            document.getElementById('ttsStatDoubt').innerText = s.doubt;
            document.getElementById('ttsStatMissing').innerText = s.missing;
            document.getElementById('ttsVarCount').innerText = `${s.pieces_saved} / ${s.pieces}`;
            ttsRenderHintBtns();
        }
        // Кнопки-подсказки в шапке: «Из записанного: N», «Одинаковые: N».
        function ttsRenderHintBtns() {
            let ru = document.getElementById('ttsReuseBtn');
            if (ru) { ru.style.display = tts.reuse_n ? '' : 'none'; document.getElementById('ttsReuseN').innerText = tts.reuse_n || 0; }
            let tw = document.getElementById('ttsTwinsBtn');
            if (tw) { tw.style.display = tts.twins_fill ? '' : 'none'; document.getElementById('ttsTwinsN').innerText = tts.twins_fill || 0; }
        }

        // Одинаковый текст под разными названиями: записанную фразу — под остальные названия.
        async function ttsTwinsFill() {
            let info = await pywebview.api.tts_twins_info();
            let groups = (info.groups || []).filter(g => g.can_fill);
            if (!groups.length) { showToast('Нечего заполнять'); return; }
            let rows = groups.slice(0, 8).map(g => {
                let src = g.units.find(u => u.saved && !u.copy_of);
                let to = g.units.filter(u => !u.saved).map(u => escapeHtml(u.name));
                return `«${escapeHtml(g.text.length > 60 ? g.text.slice(0, 60) + '…' : g.text)}»<br><span class="tts-dim">${escapeHtml(src.name)} → ${to.join(', ')}</span>`;
            }).join('<br><br>');
            let more = groups.length > 8 ? `<br><br><span class="tts-dim">и ещё ${groups.length - 8} групп</span>` : '';
            if (!(await showBeautifulConfirm(`Фразы с тем же текстом, но другим названием. Записанную скопирую под остальные названия (${info.fill} файлов):<br><br>${rows}${more}`, 'Заполнить', 'Отмена'))) return;
            let res = await pywebview.api.tts_twins_apply();
            if (!res || res.error) { showToast(res && res.error || 'Не получилось'); return; }
            tts = res; ttsRender(); ttsLoadPrompt();
            showToast(`Заполнено копиями: ${res.filled}`);
        }

        // Клик по ячейке ленты — сразу слушать (повторный клик — стоп). Во
        // время записи над лентой открывается «Сборка» этого дубля.
        async function ttsRailClick(i) {
            if (ttsPlayingIdx === i) { await ttsStopPlay(); ttsRender(); return; }
            await ttsSelect(i);
            ttsShowAssembly(true);
            ttsTogglePlay();
        }

        // «Сборка» открыта: клик по пустому месту вне карточек — закрыть и вернуться к записи.
        // Ловим нажатие раньше всех (capture), чтобы клик по суфлёру не начал запись.
        document.addEventListener('mousedown', e => {
            let stage = document.getElementById('stage4-tts');
            if (e.button !== 0 || !stage || !stage.classList.contains('show-assembly') || !stage.contains(e.target)) return;
            if (e.target.closest('.tts-current, .tts-assembly, .tts-rail-wrap, .tts-header, button, input, select, textarea, a, label')) return;
            e.preventDefault();
            e.stopPropagation();
            ttsShowAssembly(false);
        }, true);

        function ttsShowAssembly(on) {
            let stage = document.getElementById('stage4-tts');
            stage.classList.toggle('show-assembly', on === undefined ? !stage.classList.contains('show-assembly') : on);
            let open = stage.classList.contains('show-assembly');
            if (open) {
                ttsPttCancel(); ttsEd = null; ttsRenderAssembly();
                let t = ttsCurTake();                   // «из записанного» — куски сразу в Audacity
                if (t && t.reuse && ttsAudacitySent !== t.i) ttsSendToAudacity(true);
            }
            else { ttsAsmAuto = false; ttsAsmQueue = []; }
            // Сборка открыта — микрофон выключен: не шумит при прослушивании.
            if (ttsRec.on && ttsLiveSt.micOff !== open) {
                ttsLiveSt.micOff = open;
                pywebview.api.tts_live_mic(!open);
                ttsLiveRender();
            }
            else if (ttsPlayingIdx >= 0) ttsStopPlay().then(() => { ttsRenderRail(); ttsRenderCurrent(); });
        }
