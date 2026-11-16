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

