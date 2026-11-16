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
            'stage4-tts':         'flex',
            'stage5-listen':      'flex'
        };

        // Рабочие экраны: «Вернуться к работе» в меню ведёт на последний из них.
        const WORK_STAGES = { 'stage2-workspace': 'Рабочий экран', 'stage3-constructor': 'Конструктор', 'stage4-tts': 'Студия записи', 'stage5-listen': 'Прослушка' };
        let lastWork = null;
        function showStage(activeId) {
            Object.keys(STAGE_DISPLAY).forEach(id => {
                let el = document.getElementById(id);
                if (el) el.style.display = (id === activeId) ? STAGE_DISPLAY[id] : 'none';
            });
            if (WORK_STAGES[activeId]) lastWork = { stage: activeId, area: embedAreaId, btn: embedBtnId };
            // цвет окон — по режиму: студия синяя, переменные янтарные
            if (activeId === 'stage4-tts') document.body.dataset.mode = 'new';
            else if (activeId === 'stage3-constructor' || activeId === 'stage5-listen') document.body.dataset.mode = 'vars';
        }
        // Есть ли куда вернуться: пустой рабочий экран (ничего не загружено) — не считается.
        function canResumeWork() {
            if (!lastWork) return false;
            if (lastWork.stage === 'stage4-tts') return !!(typeof tts !== 'undefined' && tts && tts.loaded);
            if (lastWork.stage === 'stage2-workspace') return workspaceReady && (parseInt((document.getElementById('statTotal') || {}).innerText, 10) || 0) > 0;
            return true;
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
            if (isShown('stage0-splash') && motionOK()) { fadeSplashToMenu(); return; }
            showMenuNow();
        }

        // Заставка → меню: просто плавная смена экранов (без полёта букв).
        async function fadeSplashToMenu() {
            stageAnimating = true;
            let splash = document.getElementById('stage0-splash');
            let menu = document.getElementById('stage1-loading');
            try {
                await splash.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 220, easing: 'ease-in', fill: 'forwards' }).finished;
            } catch (e) {}
            showMenuNow();
            splash.getAnimations().forEach(an => an.cancel());
            try {
                await menu.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 420, easing: 'cubic-bezier(.2,.7,.3,1)' }).finished;
            } catch (e) {}
            stageAnimating = false;
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
            if (btnResume) {
                let ok = canResumeWork();
                btnResume.style.display = ok ? 'inline-flex' : 'none';
                if (ok) btnResume.innerHTML = `&#8592;&nbsp; ${WORK_STAGES[lastWork.stage]}`;
            }

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
            if (radial.open && (!radial.cat || radial.cat === 'recent')) radialRender(false); else radialContinueRender();
        }

        // ===== Главное меню — круговое =====
        // Значок в центре: клик — вокруг раскрываются разделы; выбрали раздел —
        // в том же кольце его пункты, в центре — «назад». Пункты нажимают
        // прежние (скрытые) кнопки меню: вся логика, статусы и «×» — те же.
        const RADIAL_CATS = [
            { key: 'new', title: 'Новый проект', icon: 'plus-circle', desc: 'Студия записи, текст из Excel, нарезка сырого WAV, готовые чанки' },
            { key: 'vars', title: 'Переменные', icon: 'tenge', desc: 'Пакетная сборка сумм, готовая папка с переменными, конструктор', cls: 'var' },
            { key: 'tools', title: 'Утилиты', icon: 'zap', desc: 'Аудит проекта, названия по Excel, PowerPoint, конвертер, клон, синтез по таблице, очистка названий', cls: 'tool' },
            { key: 'recent', title: 'Недавние', icon: 'calendar', desc: 'Открыть один из последних проектов', cls: 'good' },
        ];
        const RADIAL_ITEMS = {
            new: [
                { title: 'Студия записи', icon: 'mic', src: '#btnTts' },
                { title: 'Загрузить текст', icon: 'file-text', src: '#btnLoadExcel', clear: 'excel' },
                { title: 'Резать сырой WAV', icon: 'sliders', src: '#btnLoadAudio', clear: 'project' },
                { title: 'Настройки нарезки', icon: 'scissors', act: 'cut' },
                { title: 'Открыть готовые чанки', icon: 'folder', src: '#btnLoadFolder', clear: 'project' },
            ],
            vars: [
                { title: 'Пакетная сборка', icon: 'refresh-cw', src: '.menu-row--var', cls: 'var' },
                { title: 'Готовая папка', icon: 'folder', src: '.menu-row--good', cls: 'good' },
                { title: 'Конструктор', icon: 'sliders', src: '.menu-row--info' },
                { title: 'Прослушка', icon: 'headphones', run: () => listenStart(),
                  desc: 'Записи переменных по таблице — послушать в фразе, подрезать, при нужде синтезировать' },
            ],
        };
        const RADIAL_CAT_KEY = 'gvox_radial_cat';
        let radial = { open: true, cat: null, items: [], cutOpen: false, inited: false };
        function radialSaveCat() { try { localStorage.setItem(RADIAL_CAT_KEY, radial.cat || ''); } catch (e) {} }
        function radialLoadCat() {
            let c = null;
            try { c = localStorage.getItem(RADIAL_CAT_KEY) || null; } catch (e) {}
            return RADIAL_CATS.some(x => x.key === c) ? c : null;
        }
        const radialEl = id => document.getElementById(id);
        function radialToolItems() {
            return [...document.querySelectorAll('.menu-grid .menu-tools .menu-tool')].map(b => {
                let use = b.querySelector('use');
                return { title: (b.querySelector('.menu-tool__title') || {}).textContent || '',
                         icon: ((use && use.getAttribute('href')) || '#icon-zap').replace('#icon-', ''), node: b, cls: 'tool' };
            });
        }
        function radialRecentItems() {
            return (recentProjectsCache || []).slice(0, 6).map((it, idx) => ({ title: it.name, icon: 'folder', cls: 'good',
                desc: `${it.path || ''}${it.updated_at ? ' · ' + formatRecentTime(it.updated_at) : ''}`, run: () => openRecentProject(idx) }));
        }
        function radialList() {
            if (!radial.open) return [];
            if (!radial.cat) return RADIAL_CATS.filter(c => c.key !== 'recent' || (recentProjectsCache || []).length).map(c => ({ ...c, isCat: true }));
            if (radial.cat === 'tools') return radialToolItems();
            if (radial.cat === 'recent') return radialRecentItems();
            return (RADIAL_ITEMS[radial.cat] || []).map(it => ({ ...it, node: it.src ? document.querySelector('.menu-grid ' + it.src) : null }));
        }
        function radialDesc(it) {
            if (it.desc) return it.desc;
            if (it.act === 'cut') return `Сейчас: ${(radialEl('cutSummary') || {}).textContent || ''}. Обычно подбираются сами под запись`;
            let n = it.node;
            if (!n) return '';
            let d = n.querySelector('.option-desc, .menu-row__desc');
            return [d && d.textContent, n.getAttribute('title')].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(' — ');
        }
        function radialHubHTML() {
            if (!radial.cat) return `<span class="radial__logo">G<span>Vox</span></span><span class="radial__hub-sub">${radial.open ? 'свернуть' : 'меню'}</span>`;
            let c = RADIAL_CATS.find(x => x.key === radial.cat);
            return `<span class="radial__hub-icon">${iconHTML(c.icon)}</span><span class="radial__hub-title">${escapeHtml(c.title)}</span><span class="radial__hub-sub">&larr; назад</span>`;
        }
        function radialInfoHTML(it) {
            if (it) return `<div class="radial__info-title">${escapeHtml(it.title)}</div><div class="radial__info-desc">${escapeHtml(radialDesc(it))}</div>`;
            let step = (radialEl('setupStatus') || {}).textContent || '';
            if (!radial.open) return `${step ? `<div class="radial__info-step">${escapeHtml(step)}</div>` : ''}<div class="radial__info-desc">Нажмите на значок — откроется меню</div>`;
            let n = radial.items.length;
            return `<div class="radial__info-desc">${radial.cat ? 'Выберите действие' : 'Выберите раздел'}${n ? ` · клавиши <kbd>1</kbd>–<kbd>${n}</kbd>` : ''} · <kbd>Esc</kbd> — ${radial.cat ? 'назад' : 'свернуть'}</div>`;
        }
        function radialSetInfo(it) { radialEl('radialInfo').innerHTML = radialInfoHTML(it); }
        // Под кольцом: параметры пакетной сборки, настройки нарезки, «очистить недавние».
        function radialExtraRender() {
            let ex = radialEl('radialExtra');
            let opts = document.querySelector('.menu-row__opts');
            let home = document.querySelector('.menu-grid .menu-row--var');
            let cut = document.querySelector('details.menu-cut');
            let col = document.querySelector('.menu-grid .setup-col');
            if (radial.open && radial.cat === 'vars' && opts) { if (opts.parentNode !== ex) ex.appendChild(opts); }
            else if (opts && home && opts.parentNode !== home) home.insertBefore(opts, home.querySelector('.menu-row__go'));
            if (radial.open && radial.cat === 'new' && radial.cutOpen && cut) { if (cut.parentNode !== ex) { ex.appendChild(cut); cut.open = true; } }
            else if (cut && col && cut.parentNode !== col) col.insertBefore(cut, radialEl('btnLoadFolder'));
            let rc = radialEl('radialRecentClear');
            if (radial.open && radial.cat === 'recent') {
                if (!rc) ex.insertAdjacentHTML('beforeend', `<button type="button" class="radial__link" id="radialRecentClear" onclick="radialRecentClear()" title="Убрать все проекты из списка. Сами папки и файлы не удаляются">Очистить список</button>`);
            } else if (rc) rc.remove();
        }
        async function radialRecentClear() {
            await clearMenuRecent();
            let rc = radialEl('radialRecentClear');
            if (rc) rc.textContent = radialEl('menuRecentClear').classList.contains('is-confirm') ? 'Точно очистить?' : 'Очистить список';
            if (!(recentProjectsCache || []).length) { radial.cat = null; radialRender(true); }
        }
        function radialRender(animate) {
            let ring = radialEl('radialRing');
            if (!ring) return;
            let root = radialEl('radial');
            if (animate) radial.animUntil = performance.now() + 1400;     // пока летят пункты — статус не перерисовываем
            if (!animate) {               // обновление статуса (✓, ×, недавние) — без пружины и прорисовки лучей
                root.classList.add('is-static');
                clearTimeout(radial.staticT);
                radial.staticT = setTimeout(() => root.classList.remove('is-static'), 60);
            }
            root.classList.toggle('is-open', radial.open);
            root.dataset.cat = radial.cat || '';
            let hub = radialEl('radialHubIn'), hubHTML = radialHubHTML();
            if (hub.innerHTML !== hubHTML) {
                hub.innerHTML = hubHTML;
                if (animate && motionOK()) { hub.classList.remove('is-swap'); void hub.offsetWidth; hub.classList.add('is-swap'); }
            }
            radialEl('radialHub').title = !radial.open ? 'Открыть меню' : radial.cat ? 'Назад (Esc)' : 'Свернуть (Esc)';
            let list = radialList();
            radial.items = list;
            radialContinueRender();
            let draw = () => {
                let n = list.length;
                ring.innerHTML = list.map((it, k) => {
                    let a = (-90 + 360 / Math.max(1, n) * k) * Math.PI / 180;
                    let loaded = it.node && it.node.classList.contains('loaded');
                    let badge = it.isCat ? radialBadge(it.key) : '';
                    return `<button type="button" class="radial__item ${it.isCat ? 'radial__item--cat' : ''} ${loaded ? 'is-loaded' : ''}"
                        data-k="${k}" data-ac="${it.isCat ? it.key : radial.cat}" style="--x: ${(Math.cos(a)).toFixed(4)} * var(--R); --y: ${(Math.sin(a)).toFixed(4)} * var(--R); --dl: ${animate ? 60 + k * 55 : 0}ms">
                        <span class="radial__item-icon">${iconHTML(it.icon)}</span>
                        <span class="radial__item-title">${escapeHtml(it.title)}</span>
                        ${k < 9 ? `<span class="radial__item-key">${k + 1}</span>` : ''}${badge}
                        ${loaded && it.clear ? `<span class="radial__clear" role="button" title="Сбросить, чтобы загрузить заново" data-clear="${it.clear}">&times;</span>` : ''}
                    </button>`;
                }).join('');
                let lines = radialLines(list.length, animate);
                ring.querySelectorAll('.radial__item').forEach(b => {
                    let k = +b.dataset.k, it = list[k];
                    let hot = on => { let l = lines[k]; if (l) l.classList.toggle('is-hot', on); };
                    b.onmouseenter = b.onfocus = () => { radialSetInfo(it); hot(true); };
                    b.onmouseleave = b.onblur = () => { radialSetInfo(null); hot(false); };
                    b.onclick = e => {
                        let c = e.target.closest('[data-clear]');
                        if (c) { e.stopPropagation(); clearLoaded(e, c.dataset.clear); setTimeout(() => radialRender(false), 200); return; }
                        b.classList.remove('is-press'); void b.offsetWidth; b.classList.add('is-press');
                        radialRun(it);
                    };
                });
                let show = () => { ring.querySelectorAll('.radial__item').forEach(b => b.classList.add('is-in')); radialEl('radialLines').classList.add('is-in'); };
                if (animate) requestAnimationFrame(() => requestAnimationFrame(show)); else show();
                radialSetInfo(null);
                radialExtraRender();
            };
            let old = ring.querySelectorAll('.radial__item');
            if (animate && old.length && motionOK()) {
                radialEl('radialLines').classList.remove('is-in');
                old.forEach((b, k) => { b.style.setProperty('--dlo', `${(old.length - 1 - k) * 30}ms`); b.classList.remove('is-in'); b.classList.add('is-out'); });
                setTimeout(draw, 260 + old.length * 30);
            } else draw();
        }
        // Лучи от центра к пунктам (SVG): прорисовываются вслед за пунктами.
        function radialLines(n, animate) {
            let svg = radialEl('radialLines'), st = radialEl('radialStage');
            // --R/--S заданы через clamp() — меряем пробником в пикселях
            let probe = document.createElement('i');
            probe.style.cssText = 'position:absolute;visibility:hidden;width:var(--R);height:var(--S)';
            st.appendChild(probe);
            let R = probe.offsetWidth || 188, S = probe.offsetHeight || 104;
            probe.remove();
            let w = st.clientWidth, c = w / 2, hub = radialEl('radialHub').clientWidth / 2;
            svg.setAttribute('viewBox', `0 0 ${w} ${w}`);
            svg.classList.remove('is-in');
            svg.innerHTML = Array.from({ length: n }, (_, k) => {
                let a = (-90 + 360 / Math.max(1, n) * k) * Math.PI / 180, ux = Math.cos(a), uy = Math.sin(a);
                let r0 = hub + 6, r1 = R - S / 2 - 6, len = Math.max(1, r1 - r0);
                return `<line x1="${(c + ux * r0).toFixed(1)}" y1="${(c + uy * r0).toFixed(1)}" x2="${(c + ux * r1).toFixed(1)}" y2="${(c + uy * r1).toFixed(1)}"
                    style="--len: ${len.toFixed(1)}; --dl: ${animate ? 140 + k * 55 : 0}ms"/>`;
            }).join('');
            return [...svg.querySelectorAll('line')];
        }
        function radialRipple() {
            if (!motionOK()) return;
            let r = document.createElement('span');
            r.className = 'radial__ripple';
            radialEl('radialStage').appendChild(r);
            setTimeout(() => r.remove(), 750);
        }
        // Статус на разделе — видно, не заходя внутрь
        function radialBadge(key) {
            if (key === 'new') {
                let on = ['#btnLoadExcel', '#btnLoadAudio', '#btnLoadFolder'].map(q => document.querySelector('.menu-grid ' + q)).filter(n => n && n.classList.contains('loaded'));
                if (!on.length) return '';
                let what = on.map(n => (n.querySelector('.option-desc') || {}).textContent || '').filter(Boolean).join(' · ');
                return `<span class="radial__badge is-ok" title="Загружено: ${escapeHtml(what)}">✓${on.length > 1 ? on.length : ''}</span>`;
            }
            if (key === 'recent') {
                let n = (recentProjectsCache || []).length;
                return n ? `<span class="radial__badge" title="Недавних проектов: ${n}">${n}</span>` : '';
            }
            return '';
        }
        function radialRun(it) {
            if (!it) return;
            if (it.isCat) { radialRipple(); radial.cat = it.key; radial.cutOpen = false; radialSaveCat(); radialRender(true); return; }
            if (it.act === 'cut') { radial.cutOpen = !radial.cutOpen; radialExtraRender(); return; }
            document.body.dataset.mode = radial.cat || 'new';
            if (it.run) { it.run(); return; }
            if (it.node) setTimeout(() => { it.node.click(); setTimeout(() => { if (isShown('stage1-loading')) radialRender(false); }, 400); }, 160);
        }
        function radialHubClick() {
            radialRipple();
            if (!radial.open) radial.open = true;
            else if (radial.cat) radial.cat = null;
            else radial.open = false;
            radial.cutOpen = false;
            radialSaveCat();
            radialRender(true);
        }
        function radialKey(e) {
            if (!isShown('stage1-loading') || !radialEl('radial')) return;
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.ctrlKey || e.metaKey || e.altKey) return;
            if ([...document.querySelectorAll('.custom-alert-overlay')].some(o => o.style.display === 'flex')) return;
            if (e.code === 'Escape' && radial.open) { e.preventDefault(); radialHubClick(); return; }
            let m = /^(?:Digit|Numpad)([1-9])$/.exec(e.code);
            if (m && radial.open && radial.items[+m[1] - 1]) { e.preventDefault(); radialRun(radial.items[+m[1] - 1]); return; }
            if ((e.code === 'Enter' || e.code === 'NumpadEnter') && (recentProjectsCache || []).length
                && !(document.activeElement && document.activeElement.closest && document.activeElement.closest('button, a, details'))) {
                e.preventDefault(); radialContinue();
            }
        }
        // «Продолжить: <последний проект> →» — в один клик (или Enter)
        function radialContinueRender() {
            let box = radialEl('radialContinue'), last = (recentProjectsCache || [])[0];
            if (!box) return;
            box.style.display = last ? '' : 'none';
            if (last) box.innerHTML = `<span class="radial__continue-label">Продолжить</span><b>${escapeHtml(last.name)}</b>`
                + `${last.updated_at ? `<span class="radial__continue-time">${escapeHtml(formatRecentTime(last.updated_at))}</span>` : ''}<span class="radial__continue-go">&rarr;</span><kbd>Enter</kbd>`;
            if (last) box.title = last.path || '';
        }
        function radialContinue() {
            if (!(recentProjectsCache || []).length) return;
            radialRipple();
            openRecentProject(0);
        }
        function radialInit() {
            if (!radialEl('radial') || radial.inited) return;
            radial.inited = true;
            radialEl('radialStage').insertAdjacentHTML('afterbegin', `<div class="radial__orbit"><i></i><i></i><i></i></div><svg class="radial__lines" id="radialLines" aria-hidden="true"></svg>`);
            let acts = document.createElement('div');
            acts.className = 'radial__actions';
            let resume = radialEl('btnResume'), help = document.querySelector('#stage1-loading .btn-help');
            if (resume) acts.appendChild(resume);
            if (help) acts.appendChild(help);
            radialEl('radialExtra').after(acts);
            radialEl('radialInfo').insertAdjacentHTML('afterend', `<button type="button" class="radial__continue" id="radialContinue" onclick="radialContinue()" style="display:none"></button>`);
            let prog = radialEl('progressContainer');
            if (prog) radialEl('radial').appendChild(prog);            // ход нарезки — под кольцом
            radialBg();
            document.addEventListener('keydown', radialKey);
            // загрузили таблицу / проект — «✓» и «×» на кольце обновляются сами
            let grid = document.querySelector('.menu-grid'), t = null;
            // Перенос опций/настроек нарезки между меню и кольцом (radialExtraRender) — не изменение
            // статуса: без этого кольцо перерисовывалось бы посреди анимации и пункты прыгали.
            const own = n => n.nodeType === 1 && n.matches && n.matches('.menu-row__opts, details.menu-cut');
            const refresh = () => {
                let wait = (radial.animUntil || 0) - performance.now();
                if (wait > 0) { t = setTimeout(refresh, wait + 20); return; }
                if (radial.open && isShown('stage1-loading')) radialRender(false);
            };
            if (grid) new MutationObserver(muts => {
                if (muts.every(m => m.type === 'childList' && [...m.addedNodes, ...m.removedNodes].every(own))) return;
                clearTimeout(t); t = setTimeout(refresh, 120);
            })
                .observe(grid, { subtree: true, attributes: true, attributeFilter: ['class'], childList: true, characterData: true });
            radial.cat = radialLoadCat();
            if (radial.cat === 'recent' && !(recentProjectsCache || []).length) radial.cat = null;
            radialRender(false);
        }
        // Фон меню: мягкие цветные пятна, сетка точек и «звуковая дорожка».
        // Двигается только transform — видеокарта, без перерисовки страницы.
        function radialBg() {
            let st = radialEl('stage1-loading');
            if (!st || st.querySelector('.radial-bg')) return;
            let n = 96, bars = '';
            for (let k = 0; k < n; k++) {
                let x = k / (n - 1), env = Math.sin(Math.PI * x) ** 0.8;
                let h = 6 + env * (18 + 46 * Math.abs(Math.sin(k * 0.61) * Math.cos(k * 0.23 + 1.3)));
                bars += `<rect x="${k * 12 + 3}" y="${(80 - h / 2).toFixed(1)}" width="5" height="${h.toFixed(1)}" rx="2.5"/>`;
            }
            st.insertAdjacentHTML('afterbegin', `<div class="radial-bg" aria-hidden="true">
                <i class="radial-bg__blob radial-bg__blob--a"></i><i class="radial-bg__blob radial-bg__blob--b"></i><i class="radial-bg__blob radial-bg__blob--c"></i>
                <div class="radial-bg__grid"></div>
                <svg class="radial-bg__wave" viewBox="0 0 ${n * 12} 160" preserveAspectRatio="none">${bars}</svg></div>`);
        }
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', radialInit); else radialInit();

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
            if (!canResumeWork()) return;
            if (lastWork.stage === 'stage4-tts') { openTtsScreen(tts); return; }
            embedAreaId = lastWork.area; embedBtnId = lastWork.btn;
            showStage(lastWork.stage);
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

