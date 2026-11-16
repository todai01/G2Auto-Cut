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
            if ((e.ctrlKey || e.metaKey) && (e.code === 'KeyS' || e.code === 'KeyZ') && isShown('stage5-listen')
                && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA'
                && document.getElementById('customAlertOverlay').style.display !== 'flex') {
                e.preventDefault();
                if (e.code === 'KeyS') listenSave(true); else listenEdUndo();
                return;
            }
            if ((e.ctrlKey || e.metaKey) && ['KeyD', 'KeyC', 'KeyV'].includes(e.code) && ttsEd
                && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA'
                && document.getElementById('stage4-tts').classList.contains('show-assembly')) {
                e.preventDefault();
                if (e.code === 'KeyD') ttsEdDupLane(); else if (e.code === 'KeyC') ttsEdCopy(); else ttsEdPaste();
                return;
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
            if (isShown('stage5-listen')) { listenKey(e); return; }

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

        // Клик по названию или тексту фразы (data-copy) — в буфер. Выделение мышью работает как обычно.
        function copyAttr(v) { return ` data-copy="${escapeHtml(String(v || ''))}"`; }
        function copyToClipboard(text) {
            try { navigator.clipboard.writeText(text); return; } catch (e) {}
            let ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select();
            try { document.execCommand('copy'); } catch (e) {} ta.remove();
        }
        document.addEventListener('click', e => {
            let el = e.target.closest && e.target.closest('[data-copy]');
            if (!el) return;
            e.stopPropagation(); e.preventDefault();
            if (String(window.getSelection && window.getSelection()).trim()) return;       // выделяют — не мешаем
            let t = el.dataset.copy;
            copyToClipboard(t);
            showToast('Скопировано: ' + (t.length > 80 ? t.slice(0, 80) + '…' : t), 1800);
        }, true);

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

