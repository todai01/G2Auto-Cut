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
            let confirmed1 = await showBeautifulAlert('<b>Загрузите папку со значениями</b><br><br>Папку «Значения» проекта (или сам проект) — конструктор найдёт листы сумм и дат: sum_kz, sum_ru, date_kz… Подойдёт и старая папка «Суммы» с подпапками ярусов.');
            if (!confirmed1) return;
            let state = await pywebview.api.constructor_pick_sum_folder();
            if (state && state.error === 'cancel') return;
            if (!state || state.error) {
                showBeautifulAlert(`<b>Ошибка</b><br><br>${state && state.error ? state.error : 'Неизвестная ошибка'}`);
                return;
            }
            constructorState = state;
            // Проект Студии: фразы вокруг переменной уже известны — start/end не спрашиваем.
            if ((state.phrases || []).length) { openConstructorScreen(); return; }

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
            renderConstructorPhrase();
            renderConstructorReels();
        }
        function constructorPrimaryLabel() {
            let b = document.querySelector('#stage3-constructor .btn-tile--primary');
            if (b && !b.disabled) b.innerText = constructorIsSum() ? 'Обновить сумму' : 'Обновить в Audacity';
        }

        // RU/KZ: папка «Суммы» может содержать сразу обе версии — подпапки
        // «Суммы RU» и «Суммы KZ», каждая со своими 5 ярусами. Кнопки
        // видны только когда constructor_pick_sum_folder() реально нашёл
        // обе (или хотя бы вторую) — если папка старого формата (без
        // RU/KZ), тумблер просто прячем, он там не нужен.
        function renderConstructorLangRow() {
            let row = document.getElementById('constructorLangRow');
            if (!row) return;
            let title = document.querySelector('#stage3-constructor .constructor-title__main');
            let sheets = (constructorState && constructorState.sheets) || [];
            if (sheets.length) {                                   // папка «Значения»: листы сумм и дат
                if (!row.dataset.orig) row.dataset.orig = row.innerHTML;
                row.innerHTML = sheets.map(x => `<button class="btn-tile constructor-lang-btn ${x.key === constructorState.sheet ? 'btn-tile--solid-mode' : ''}"
                    onclick="setConstructorSheet('${escapeHtml(x.key)}')" title="Значения/${escapeHtml(x.key)}">${escapeHtml(x.label)}</button>`).join('');
                row.style.display = 'flex';
                let cur = sheets.find(x => x.key === constructorState.sheet);
                if (title && cur) title.innerHTML = `${iconHTML('sliders')} Конструктор переменных — ${escapeHtml(cur.label)}`;
                return;
            }
            if (row.dataset.orig) { row.innerHTML = row.dataset.orig; delete row.dataset.orig; }
            if (title) title.innerHTML = `${iconHTML('sliders')} Конструктор переменных — Суммы`;
            let available = (constructorState && constructorState.lang_available) || [];
            row.style.display = available.length > 1 ? 'flex' : 'none';
            let ruBtn = document.getElementById('constructorLangRuBtn');
            let kzBtn = document.getElementById('constructorLangKzBtn');
            let lang = constructorState ? constructorState.lang : 'ru';
            if (ruBtn) ruBtn.classList.toggle('btn-tile--solid-mode', lang === 'ru');
            if (kzBtn) kzBtn.classList.toggle('btn-tile--solid-mode', lang === 'kz');
        }

        // Фраза вокруг переменной (start → значение → start_2 / end), «кратко» — только стык.
        function renderConstructorPhrase() {
            let el = document.getElementById('constructorPhrase');
            if (!el) return;
            let ph = (constructorState && constructorState.phrases) || [];
            if (!ph.length) { el.style.display = 'none'; el.innerHTML = ''; return; }
            let k = constructorState.phrase_pos || 0, x = ph[k];
            let part = (role, name, text, ok) => name ? `<span class="constructor-phrase__part ${ok ? '' : 'is-miss'}" title="${escapeHtml(text || '')}${ok ? '' : ' — ещё не записана'}"><i>${escapeHtml(role)}</i>${escapeHtml(name)}</span>` : '';
            el.style.display = 'flex';
            el.innerHTML = `<span class="constructor-phrase__nav">
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="constructorPhraseNav(-1)" title="Предыдущая фраза с этой переменной">&#9664;</button>
                    Фраза <b>${k + 1}</b> / ${ph.length}
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="constructorPhraseNav(1)" title="Следующая фраза с этой переменной">&#9654;</button></span>
                <span class="constructor-phrase__name">${escapeHtml(x.name)}</span>
                ${part(x.start_role, x.start_name, x.start_text, x.start_ok)} → <b>значение</b> → ${part(x.end_role || 'end', x.end_name, x.end_text, x.end_ok) || '<span class="tts-dim">без продолжения</span>'}
                <label class="audit-switch" title="Играть только конец начала и начало продолжения (по ${(constructorState.short_ms || 2500) / 1000} с) — чтобы быстро сверить стык с боевыми записями">
                    <input type="checkbox" ${constructorState.short ? 'checked' : ''} onchange="constructorSetShort(this.checked)"> кратко</label>`;
        }
        async function constructorPhraseNav(d) {
            let st = await pywebview.api.constructor_phrase_nav(d);
            if (st && !st.error) { constructorState = st; renderConstructorPhrase(); renderConstructorMeta(); updateConstructorPreview(); }
        }
        async function constructorSetShort(on) {
            let st = await pywebview.api.constructor_set_short(on);
            if (st && !st.error) { constructorState = st; renderConstructorPhrase(); }
        }

        async function setConstructorSheet(key) {
            if (!constructorState || constructorState.sheet === key) return;
            let state = await pywebview.api.constructor_set_sheet(key);
            if (state && state.error) { showBeautifulAlert(`<b>Ошибка</b><br><br>${escapeHtml(state.error)}`); return; }
            constructorState = state;
            constructorBigMode = false;
            renderConstructorLangRow();
            renderConstructorMeta();
            renderConstructorPhrase();
            renderConstructorReels();
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
        // Лист «Значения» не сумма (даты…) — рулетки по его категориям, как есть.
        const constructorIsSum = () => !constructorState || (constructorState.kind || 'sum') === 'sum';
        const constructorAllTiers = () => constructorIsSum() ? CONSTRUCTOR_TIER_ORDER : (constructorState.order || []);
        const CONSTRUCTOR_EXTRA_ACCENTS = ['var(--accent-info)', 'var(--accent-var)', 'var(--accent-good)', 'var(--accent-mode)', 'var(--accent-primary)'];
        const constructorAccent = tier => CONSTRUCTOR_TIER_ACCENT[tier]
            || CONSTRUCTOR_EXTRA_ACCENTS[Math.max(0, constructorAllTiers().indexOf(tier)) % CONSTRUCTOR_EXTRA_ACCENTS.length];
        function constructorVisibleTiers() {
            if (!constructorIsSum()) return constructorAllTiers();
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
            <div class="${cls}" data-tier="${tier}" style="--tier-accent: ${constructorAccent(tier)}">
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
            let flipGroup = !constructorIsSum() ? '' : `
                <div class="constructor-flip-group">
                    <div class="constructor-flip-group__reels">
                        ${constructorBigMode ? constructorReelColHTML('hundred_thousands', true)
                                              : constructorReelColHTML('hundreds') + constructorReelColHTML('thousands')}
                    </div>
                    <button class="constructor-flip-btn" onclick="constructorToggleBigMode()">
                        ${iconHTML('refresh-cw')} ${flipLabel}
                    </button>
                </div>`;

            wrap.innerHTML = constructorIsSum()
                ? constructorReelColHTML('millions') + flipGroup + constructorReelColHTML('tenge')
                : constructorAllTiers().map(t => constructorReelColHTML(t)).join('');

            constructorReelInstances = {};
            constructorVisibleTiers().forEach(tier => {
                let items = constructorState.tiers[tier].items.map(t => constructorIsSum() ? humanizeTierItem(tier, t) : t);
                let container = document.getElementById(`reel-${tier}`);
                constructorReelInstances[tier] = new Reel(container, items, 44, updateConstructorPreview);
            });
            updateConstructorPreview();
            constructorPrimaryLabel();
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
            constructorAllTiers().forEach(tier => {
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
                let shown = reel ? reel.items[idx] : (constructorIsSum() ? humanizeTierItem(tier, items[idx]) : items[idx]);
                parts.push(`<b>${escapeHtml(shown ?? '')}</b>`);
            });
            if (constructorState.end) parts.push(escapeHtml(constructorState.end));
            el.innerHTML = parts.join(' &nbsp;→&nbsp; ');
        }

        function constructorIndices() {
            let indices = {};
            constructorAllTiers().forEach(tier => {
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

