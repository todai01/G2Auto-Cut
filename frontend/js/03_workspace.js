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

