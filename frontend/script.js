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
    let m = /^([\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}])️?\s*/u.exec(text || '');
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

        // Размытие/затемнение фона, когда окно программы теряет фокус ОС
        // (например, когда Audacity выходит на передний план после C, R
        // или выбора исходника для start/end). Это стандартные события
        // window — их не нужно вызывать вручную из Python.
        // Когда Audacity вживлён внутрь софта, клик по нему технически уводит
        // фокус браузерного слоя — но это всё ещё то же самое окно, а не
        // отдельная программа, поэтому темнить/размывать фон не нужно.
        // В «Конструкторе переменных» своей рамки под встраивание пока нет —
        // Audacity там всегда выходит отдельным окном по кнопке «Обновить
        // сумму», и это нормальная часть работы с этим экраном, а не повод
        // затемнять программу.
        window.addEventListener('blur', () => {
            // Окно потеряло фокус — если W/S были зажаты, keyup может не
            // прийти вовсе (например, alt-tab), и прокрутка иначе крутилась
            // бы бесконечно быстрее и быстрее сама по себе.
            constructorStopHold('KeyW');
            constructorStopHold('KeyS');
            if (audacityEmbedded) return;
            let constructorStage = document.getElementById('stage3-constructor');
            if (constructorStage && constructorStage.style.display !== 'none') return;
            document.body.classList.add('app-unfocused');
        });
        window.addEventListener('focus', () => document.body.classList.remove('app-unfocused'));

        function updateProgress(p, t) {
            document.getElementById('progressContainer').style.display = 'block';
            document.getElementById('progressBar').value = p;
            document.getElementById('progressText').innerText = t;
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
            'stage3-constructor': 'block'
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
            splash.classList.add('is-leaving');
            await wait(230);

            // Исходные позиции — пока заставка ещё на экране.
            let from = logoLetters(mark);
            let wordA = textRect(mark);
            let fontSize = parseFloat(getComputedStyle(mark).fontSize);
            let lineA = tagline ? tagline.getBoundingClientRect() : null;

            let menu = document.getElementById('stage1-loading');
            menu.classList.add('menu-entering');
            showMenuNow();
            splash.classList.remove('is-leaving');

            let target = menu.querySelector('.setup-brand__mark');
            let header = menu.querySelector('.setup-header');
            let wordB = finalRect(target, textRect);
            let headB = finalRect(header, el => el.getBoundingClientRect());
            let k = wordB.height / wordA.height;
            target.style.visibility = 'hidden';

            let layer = document.createElement('div');
            layer.className = 'fx-layer';
            document.body.appendChild(layer);
            let jobs = [];

            // Линия-граница: из-под подписи заставки — в низ шапки.
            if (lineA) {
                let line = document.createElement('div');
                line.className = 'fx-line';
                Object.assign(line.style, { left: lineA.left + 'px', top: (lineA.bottom - 1) + 'px', width: lineA.width + 'px' });
                layer.appendChild(line);
                let sx = headB.width / lineA.width;
                jobs.push(line.animate([
                    { transform: 'translate(0,0) scaleX(1)', opacity: 1 },
                    { transform: `translate(${headB.left - lineA.left}px, ${(headB.bottom - 1) - (lineA.bottom - 1)}px) scaleX(${sx})`, opacity: 1, offset: .85 },
                    { transform: `translate(${headB.left - lineA.left}px, ${(headB.bottom - 1) - (lineA.bottom - 1)}px) scaleX(${sx})`, opacity: 0 }
                ], { duration: 900, delay: 60, easing: 'cubic-bezier(.77,0,.18,1)', fill: 'forwards' }).finished);
            }

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
            const EASE = 'cubic-bezier(.33,1,.68,1)';
            // Момент, когда кольцо (easeOutCubic) доходит до расстояния d.
            const reach = d => WAVE_MS * (1 - Math.cbrt(1 - Math.min(1, d / R)));

            // Вспышка в точке посадки «G».
            let flash = document.createElement('div');
            flash.className = 'fx-flash';
            Object.assign(flash.style, { left: ox + 'px', top: oy + 'px' });
            document.body.appendChild(flash);
            flash.animate([
                { transform: 'translate(-50%,-50%) scale(.2)', opacity: 1 },
                { transform: 'translate(-50%,-50%) scale(1.6)', opacity: 0 }
            ], { duration: 420, easing: 'cubic-bezier(.2,.8,.3,1)' }).finished.catch(() => {}).then(() => flash.remove());

            // Два кольца: яркое ведущее и мягкое следом.
            [{ cls: 'fx-wave', delay: 0, dur: WAVE_MS, op: 1 },
             { cls: 'fx-wave fx-wave--soft', delay: 110, dur: WAVE_MS * 1.25, op: .7 }].forEach(w => {
                // Кольцо сразу конечного размера, растёт через scale — это
                // делает видеокарта, без перерисовки на каждом кадре.
                let el = document.createElement('div');
                el.className = w.cls;
                Object.assign(el.style, { left: ox + 'px', top: oy + 'px', width: R * 2 + 'px', height: R * 2 + 'px' });
                document.body.appendChild(el);
                el.animate([
                    { transform: 'translate(-50%,-50%) scale(0.001)', opacity: w.op },
                    { transform: 'translate(-50%,-50%) scale(1)', opacity: w.op * .8, offset: .7 },
                    { transform: 'translate(-50%,-50%) scale(1.05)', opacity: 0 }
                ], { duration: w.dur, delay: w.delay, easing: EASE, fill: 'backwards' }).finished
                    .catch(() => {}).then(() => el.remove());
            });

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

        // «Активация» карточки: от точки, где её коснулась волна, по рамке в обе
        // стороны бегут две полоски света, встречаются напротив — и вся рамка
        // коротко вспыхивает.
        function traceBorder(card, ox, oy, delay) {
            let r = card.getBoundingClientRect();
            let deg = Math.atan2(ox - (r.left + r.width / 2), -(oy - (r.top + r.height / 2))) * 180 / Math.PI;
            let tr = document.createElement('span');
            tr.className = 'fx-trace';
            tr.style.setProperty('--fx-start', deg + 'deg');
            card.appendChild(tr);
            let run = tr.animate([
                { '--fx-p': '0deg', opacity: 1 },
                { '--fx-p': '180deg', opacity: 1, offset: .72 },
                { '--fx-p': '180deg', opacity: 0 }
            ], { duration: 820, delay, easing: 'cubic-bezier(.45,.05,.35,1)', fill: 'both' });
            tr.animate([
                { filter: 'drop-shadow(0 0 0 rgba(77,149,234,0))' },
                { filter: 'drop-shadow(0 0 6px rgba(110,170,255,.9))', offset: .72 },
                { filter: 'drop-shadow(0 0 0 rgba(77,149,234,0))' }
            ], { duration: 820, delay, fill: 'both' });
            run.finished.catch(() => {}).then(() => tr.remove());
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
            recentProjectsCache = items || [];

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
                recentProjectsCache = items || [];
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
            document.getElementById('stage1-loading').classList.remove('menu-fx');
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
            recentProjectsCache = items || [];
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

        // ===== ЧТЕНИЕ ТАБЛИЦЫ: ВЫБОР КОЛОНОК =====

        let excelInfo = null;
        let excelPreviewTimer = null;
        let excelAnalyzeTimer = null;

        function excelError(msg) {
            showBeautifulAlert(`❌ <b>Таблица не загружена</b><br><br>${String(msg).replace(/\n/g, '<br>')}`);
        }

        async function loadExcel() {
            let picked;
            try {
                picked = await pywebview.api.pick_excel();
            } catch (e) { excelError(e); return; }

            if (!picked || picked.error === 'cancel') { pendingPremadeAfterExcel = false; return; }
            if (picked.error) { pendingPremadeAfterExcel = false; excelError(picked.error); return; }

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
        async function startPremadeSumMode() {
            updateProgress(0, 'Загрузка папки...');
            document.getElementById('progressContainer').style.display = 'block';
            let state = await pywebview.api.sum_load_folder();
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
                    area.style.display = sumModeActive ? 'block' : 'none';
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
                    let tag = sumEl('span', 'sum-dub__tag', value || it.tiers[n]);
                    tag.title = `${it.tiers[n]}${value ? ': ' + value : ''}`;
                    tag.style.setProperty('--tier-accent', sumTierAccent(k));
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
        async function pickAsrModel() {
            let res = await pywebview.api.sum_auto_check_pick_model();
            if (!res || res.error === 'cancel') return;
            if (res.error) { showBeautifulAlert(`❌ <b>Модель</b><br><br>${escapeHtml(res.error)}`); return; }
            closeAsrModel();
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
            // Выделены дубли — проверяем их; иначе все неразобранные и ещё не
            // проверенные во всём списке (не только в видимой ленте).
            let indices = sumDubSel.size ? [...sumDubSel].sort((a, b) => a - b) : null;
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
            btn.textContent = 'Автопроверка';
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
                area.style.display = sumModeActive ? 'block' : 'none';
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
                    if (btn) btn.innerText = embedBtnId === 'sumEmbedAudacityBtn' ? 'Прикрепить Audacity' : 'Встроить окно Audacity сюда';
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
            if (area) area.style.display = sumModeActive ? 'block' : 'none';
            if (btn) btn.innerText = embedBtnId === 'sumEmbedAudacityBtn' ? 'Прикрепить Audacity' : 'Встроить окно Audacity сюда';
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
                alert("Сначала отметьте фразы на монтажном столе (клавиши 1, 2...)!");
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
                alert("Нет фраз для экспорта! Отметьте их клавишами 1, 2...");
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
                alert("Отметьте хотя бы одну часть для выгрузки на монтаж (клавиши 1, 2...)!");
                return;
            }

            if (isProcessing) return; isProcessing = true;
            await pywebview.api.prep_merge(mergeParts);
            isProcessing = false;
        }

        async function saveMerge() {
            if (!saveFilenameForMerge) { alert("Нет данных. Выберите части."); return; }
            if (isProcessing) return; isProcessing = true;
            await pywebview.api.save_merge(saveFilenameForMerge, document.getElementById('addSilence').checked, false);
            alert("Склейка сохранена в Проверенные!");

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
            if (!saveFilenameForMerge) { alert("Нет данных. Выберите части."); return; }
            if (isProcessing) return; isProcessing = true;
            // Передаем true в Python, чтобы файл ушел в папку Переменные
            await pywebview.api.save_merge(saveFilenameForMerge, document.getElementById('addSilence').checked, true);
            alert("Склейка сохранена в Переменные!");

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

        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // РАЗРЕШАЕМ СТАНДАРТНЫЕ КОМБИНАЦИИ (Ctrl+C, Ctrl+A, и т.д.)
            if (e.ctrlKey || e.metaKey) return;

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
                if (e.code === 'Space') { e.preventDefault(); playAudio(true); }
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
            if (e.code === 'Space') { e.preventDefault(); playAudio(true); }
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

        // confirmed=true — закрыли по «ОК»/Enter/Space (действие после алерта
        // продолжается); confirmed=false — закрыли крестиком/Escape (это
        // отмена, вызвавший код должен остановиться, а не продолжать как
        // будто нажали «ОК»).
        function closeCustomAlert(confirmed = true) {
            document.getElementById('customAlertOverlay').style.display = 'none';
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
                    if (key === 'excel') runProjectAudit(key); else askAuditChunks(key, label);
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
            if (!res || res.error) {
                alert(res?.error || "Сначала загрузите Excel-файл с текстом!");
                return;
            }
            renderAuditResult(res);
        }

        function renderAuditResult(res) {
            // Показываем красивое модальное окно
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

            // Запускаем анимацию счетчиков (на 1200 миллисекунд)
            animateValue(document.getElementById('auditTotalExcel'), 0, res.total_excel, 1200);
            animateValue(document.getElementById('auditTotalDisk'), 0, res.total_disk, 1200);
            animateValue(document.getElementById('auditMissing'), 0, res.missing_count, 1200);
            animateValue(document.getElementById('auditDups'), 0, voice ? unknown.length : res.duplicates_count, 1200);

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
                        <span class="audit-row__name audit-row__name--lost">${m.filename}</span>
                        <div class="audit-row__meta">Строка ${m.index}: ${m.text}</div>
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
                document.getElementById('auditDetails').innerHTML = detailsHtml;
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

            document.getElementById('auditDetails').innerHTML = detailsHtml;
            document.getElementById('auditExportBtn').style.display = res.can_export ? '' : 'none';
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
