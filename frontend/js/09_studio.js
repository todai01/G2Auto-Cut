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
            // Ответа нет 10 с — сказать об этом, а не молчать (запрос мог зависнуть в Python).
            let slow = setTimeout(() => showToast('Студия не отвечает 10 с — подождите или перезапустите программу'), 10000);
            let st;
            try { st = await pywebview.api.tts_state(); }
            catch (e) { gvoxShowError('Студия: tts_state', e); return; }
            finally { clearTimeout(slow); }
            if (!st || !st.loaded) {
                let how = await showBeautifulChoice('<b>Студия записи</b><br><br>Загрузите таблицу: лист фраз с колонками '
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
            if (!st.has_takes && !(st.vars_only || (st.analysis && st.analysis.vars_only))) {
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
            if (st.auto_head) showToast(`Лист «${st.auto_head}» без шапки: A — фразы, B — названия аудио`, 4000);
            return await ttsScopeDialog(st);
        }

        // Разбор таблицы: что в ней, сколько переменных уже записано, что новое — и что записывать.
        async function ttsScopeDialog(st) {
            let a = st.analysis;
            if (!a || !a.vars.length) return st;
            let line = v => `<b>${escapeHtml(v.label)}</b> — значений ${v.values}`
                + (v.total !== null && v.total !== undefined ? ` · записано ${v.done} из ${v.total}${v.new ? `, <b>новых ${v.new}</b>` : ' — всё записано'}` : '');
            let head = `<b>Таблица разобрана</b><br><br>Фразы: <b>${a.phrases}</b>`
                + (a.phrases_saved !== null ? ` (записано ${a.phrases_saved})` : '') + '<br>Переменные:<br>' + a.vars.map(line).join('<br>')
                + (a.known ? '' : '<br><br><span class="tts-dim">Папка проекта ещё не выбрана — что уже записано, станет видно после выбора.</span>');
            let scope = 'all';
            if (!a.phrases) {
                await showBeautifulAlert(head + '<br><br>Фраз в таблице нет — записываем <b>только переменные</b>.');
                scope = 'vars';
            } else if (a.known && a.vars_new > 0) {
                let how = await showBeautifulChoice(head + '<br><br>Что записываем?', `Только переменные (новых ${a.vars_new})`,
                                                    'Фразы и переменные', 'A', 'Отмена');
                if (how === 'ok') scope = 'vars';
                else if (how !== 'alt') return null;
            } else {
                showToast(`Таблица: фраз ${a.phrases}, листов переменных ${a.vars.length}${a.known ? ', новых значений нет' : ''}`, 3500);
            }
            if (scope === 'all' && !st.analysis.vars_only) return st;
            let r = await pywebview.api.tts_set_scope(scope);
            if (!r || r.error) { if (r) showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return st; }
            r.state.analysis = a; r.state.vars_only = r.vars_only; r.state.prompt0 = r.prompt;
            return r.state;
        }

        // Лист переменных читается внутри фразы: начало звучит перед значением, конец — после.
        // Нет такой фразы в таблице — два аудиофайла выбирают сами («начало и конец ✎»), сами не спрашиваем.
        async function ttsVarCtxAsk(sheet, force) {
            let info = await pywebview.api.tts_var_ctx_info(sheet);
            if (!force && info && (info.asked || info.custom || info.chain)) return;
            let label = (tts && tts.var_sheets && tts.var_sheets[sheet] || {}).label || sheet;
            let ok = await showBeautifulAlert(`<b>Переменные «${escapeHtml(label)}»</b><br><br>Значения читаются внутри фразы. Выберите <b>начальную фразу</b> — `
                + 'она звучит перед значением: послушаете конец — и читаете в той же интонации. Потом — конечную.');
            if (!ok) { await pywebview.api.tts_var_ctx_asked(sheet); return; }
            let r = await pywebview.api.tts_var_ctx_pick('start', sheet);
            if (r && r.error && r.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(r.error));
            let how = await showBeautifulChoice('<b>Конечная фраза</b><br><br>То, что звучит после значения. Если её нет — пропустите.',
                                                'Выбрать файл', 'Без конца', 'N', 'Отмена');
            if (how === 'ok') {
                r = await pywebview.api.tts_var_ctx_pick('end', sheet);
                if (r && r.error && r.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(r.error));
            }
            let cur = await pywebview.api.tts_var_ctx_asked(sheet);
            ttsPromptKey = null;
            ttsLoadPrompt();
            if (cur && cur.custom) showToast(`Начало${cur.end ? ' и конец' : ''} фразы выбраны — «▶ Начало» и «В фразе» играют с ними`, 4000);
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

        // «Готовые записи»: папка с уже записанным → на свои места в проекте, суфлёр их пропустит.
        // Готовые фразы с переменными — на ленту: править вместе со значениями.
        async function ttsReadyToRail() {
            let r = await pywebview.api.tts_ready_to_rail();
            if (!r || r.error) { if (r) showBeautifulAlert('ℹ️ ' + escapeHtml(r.error)); return; }
            tts = r.state; ttsRender();
            showToast(r.added ? `На ленте готовых фраз: ${r.added}. Правьте в «Сборке» и сохраняйте (Enter)` : 'Готовых фраз с переменными нет — или они уже на ленте', 3500);
        }

        async function ttsImportExisting() {
            if (ttsRec && ttsRec.on) { showToast('Сначала остановите запись (R)'); return; }
            let r = await pywebview.api.tts_import_existing();
            if (!r || r.error) { if (r && r.error !== 'cancel') showBeautifulAlert('ℹ️ ' + escapeHtml(r.error)); return; }
            if (r.state) { tts = r.state; ttsRender(); }
            ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt); else ttsLoadPrompt();
            let lines = [`Найдено по таблице: <b>${r.found}</b> из ${r.expected}`, `Добавлено в проект: <b>${r.copied}</b>`];
            if (r.same) lines.push(`уже были на своих местах: ${r.same}`);
            if (r.kept) lines.push(`в проекте уже есть свой файл (не перезаписан): ${r.kept}`);
            if (r.extra) lines.push(`в папке есть файлы, которых нет в таблице: ${r.extra} — их видно в аудите`);
            if (r.rail) lines.push(`фраз с переменными на ленте для правки: <b>${r.rail}</b>`);
            if (r.failed.length) lines.push(`ошибки: ${r.failed.map(escapeHtml).join('<br>')}`);
            showBeautifulAlert(`✅ <b>Готовые записи учтены</b><br><br>${lines.join('<br>')}<br><br>Суфлёр теперь пропускает записанное — осталось ${r.missing}.`
                + `<br><br><span class="tts-dim" style="word-break:break-all">${escapeHtml(r.src)}</span>`);
        }

        async function ttsImportVars() {
            if (ttsRec && ttsRec.on) { showToast('Сначала остановите запись (R)'); return; }
            let r = await pywebview.api.tts_import_vars();
            if (!r || r.error) { if (r && r.error !== 'cancel') showBeautifulAlert('ℹ️ ' + escapeHtml(r.error)); return; }
            if (r.state) { tts = r.state; ttsRender(); }
            ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt); else ttsLoadPrompt();
            let lines = [`Файлов в папке: ${r.found}, подошло к таблице: <b>${r.matched}</b>`, `Добавлено в «Значения»: <b>${r.copied}</b>`];
            if (r.kept) lines.push(`в проекте уже есть свой файл (не перезаписан): ${r.kept}`);
            if (r.extra > 0) lines.push(`не нашлось в таблице: ${r.extra}`);
            lines.push(`строк на ленте для правки: <b>${r.rows}</b>`);
            if (r.failed.length) lines.push(`ошибки: ${r.failed.map(escapeHtml).join('<br>')}`);
            showBeautifulAlert(`✅ <b>Папка переменных загружена</b><br><br>${lines.join('<br>')}<br><br>Откройте строку в «Сборке»: значение стоит между началом и концом фразы — подрежьте края и нажмите Enter.`);
        }

        async function ttsLoadExcel() {
            let st = await ttsPickExcelFlow();
            if (st) {
                tts = st; ttsRender(); ttsPromptKey = null;
                if (st.prompt0) ttsRenderPrompt(st.prompt0, 'next'); else ttsLoadPrompt();
            }
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
            ttsRenderStats();
            let cats = Object.values(tts.var_sheets || {}).map(v => v.label).join(', ');
            document.getElementById('ttsVarDesc').innerText = cats ? `Фразы с переменными · ${cats}` : 'Фразы с переменными';
            ttsRenderRail();
            ttsRenderCurrent();
            ttsRenderAssembly();
            ttsCutChipUpdate();
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
                // Готовые файлы (импорт, прошлые проекты) — не дубли: на ленте только новые записи.
                let ready = tts.loaded && tts.stats ? tts.stats.saved : 0;
                let msg = !tts.loaded ? 'Загрузите таблицу и запись'
                    : ttsRec.on ? 'Записанные фразы появятся здесь'
                    : ready ? `Готовых записей в проекте: ${ready} — суфлёр их пропускает. Здесь появятся новые дубли`
                    : 'Загрузите или запишите запись — здесь появятся дубли';
                let canReady = tts.loaded && !ttsRec.on && tts.stats && tts.stats.pieces_saved;
                rail.innerHTML = `<div class="tts-rail__empty">${msg}${canReady ? ` <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsReadyToRail()"
                    title="Готовые фразы с переменными — дублями на ленту: править в «Сборке» вместе со значениями и сохранять поверх">Фразы с переменными — на ленту</button>` : ''}</div>`;
                return;
            }
            rail.innerHTML = tts.takes.map(t => `
                <button type="button" class="tts-take ${ttsTakeClass(t)} ${t.i === tts.index ? 'is-current' : ''} ${t.kind === 'piece' ? 'is-chain' : ''} ${t.raw_var && !t.raw_var_rail ? 'is-rawvar' : ''}"
                        data-i="${t.i}" onclick="ttsRailClick(${t.i})" draggable="true"
                        ondragstart="ttsTakeDragStart(event, ${t.i})" ondragend="ttsTakeDragEnd()" data-tip="${escapeHtml(t.name || '—')}" data-tip2="${escapeHtml((t.heard || 'тишина / шум') + (t.raw_var && !t.raw_var_rail ? ' · в «Переменных»: ' + t.raw_var : ''))}">
                    <span class="tts-take__num">${String(t.chunk || t.i + 1).padStart(3, '0')}${t.split ? '<span class="tts-take__cut">✂</span>' : ''}</span>
                    <span class="tts-take__name">${t.name ? escapeHtml(t.name) : '—'}</span>
                    <span class="tts-take__meta">${t.raw_var && !t.raw_var_rail ? '<span class="tts-take__rv" title="Перенесён в «Переменные» (Фразы_Переменные/' + escapeHtml(t.raw_var) + ')">→ Перем.</span> ' : ''}${t.ready ? 'готовый' : t.status === 'manual' && t.unit !== null ? 'вручную' : (t.unit !== null ? Math.round(t.score * 100) + '%' : '')}${t.take_total > 1 ? ` · ${t.take_no}/${t.take_total}` : ''}</span>
                </button>`).join('');
            // Готовые фразы с переменными, которых нет на ленте, — добавить для правки.
            let offRail = ttsRec.on ? 0 : tts.units.filter(u => u.kind === 'piece' && u.saved && !(u.takes || []).length).length;
            if (offRail) rail.insertAdjacentHTML('beforeend', `<button type="button" class="tts-take tts-take--add" onclick="ttsReadyToRail()"
                title="Готовые фразы с переменными — дублями на ленту: править в «Сборке» вместе со значениями">
                <span class="tts-take__num">+${offRail}</span><span class="tts-take__name">готовые фразы</span><span class="tts-take__meta">на ленту</span></button>`);
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
        // Кнопка «Слушать/Стоп» в «Сборке» — без перерисовки всего остального.
        function ttsAsmPlayBtn(t) {
            let b = document.querySelector('#ttsAssembly .tts-asm-play');
            if (!b || !t) return;
            let on = ttsPlayingIdx === t.i;
            b.classList.toggle('is-active', on);
            b.innerHTML = `${on ? 'Стоп' : 'Слушать'} <kbd>Space</kbd>`;
        }

        function ttsRenderAssembly(force) {
            let el = document.getElementById('ttsAssembly');
            let t = ttsCurTake();
            let u = t ? ttsUnit(t.unit) : null;
            if (!u) { el.innerHTML = '<div class="tts-assembly__title">Сборка</div><div class="tts-dim">Выберите дубль на ленте</div>'; return; }
            let chain = u.chain !== null && u.chain !== undefined ? (tts.chains || [])[u.chain] : null;
            let block = p => `<div class="tts-block ${p.id === u.id ? 'is-current' : ''} ${p.saved ? 'is-saved' : ''}"
                    ${p.saved ? `onclick="ttsPlayUnit(${p.id})" title="Слушать сохранённое"` : ''}>
                    <span class="tts-block__role">${p.kind === 'value' ? escapeHtml(p.cat_label || 'значение') : (p.role || 'фраза')}${p.saved ? ' ✓' : ''}</span>
                    <span class="tts-block__name"${copyAttr(p.name)} title="Клик — скопировать название">${escapeHtml(p.name)}</span>
                    <span class="tts-block__text"${copyAttr(p.text)} title="Клик — скопировать текст">${escapeHtml(p.text)}</span></div>`;
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
            // Ничего своего не поменялось (например, только кончилась прослушка) — не
            // перерисовываем: иначе волны пропадают и загружаются заново (мигают).
            let key = JSON.stringify([t.i, t.file, t.ms, t.unit, t.approved, t.unit_saved, t.status, t.gain_db, t.tempo,
                t.audacity, !!t.reuse, t.clips || null, t.edit || null, blocks, label, tts.takes.length, ttsTierBackHere(t)]);
            ttsAsmPlayBtn(t);
            if (el.dataset.key === key && el.firstElementChild) return;
            el.dataset.key = key;
            el.innerHTML = `<div class="tts-assembly__title">Сборка <span class="tts-dim">${chain
                    ? `${escapeHtml(chain.name)} · кусочков сохранено ${saved} / ${chain.parts.length}` : u.tiers ? 'строка переменных' : 'обычная фраза'}</span>
                    <span class="tts-pill tts-pill--${tone}">${label}</span>
                    <span class="tts-dim tts-asm-num">дубль ${t.i + 1} / ${tts.takes.length}</span>
                    ${ttsTierBackHere(t) ? `<button class="tts-asm-close tts-asm-back" onclick="ttsTierReturn()" title="Вернуться к строке переменных, из которой открыли эту фразу (Esc). Сохранили фразу (Enter) — вернётся само">&larr; К строке ${escapeHtml(ttsTierBack.name)} <kbd>Esc</kbd></button>`
                      : `<button class="tts-asm-close" onclick="ttsShowAssembly(false)" title="Закрыть и вернуться к чтению (Esc или клик мимо карточек)">Закрыть <kbd>Esc</kbd></button>`}</div>
                <div class="tts-blocks">${blocks}</div>
                ${u.tiers ? '<div class="tts-tiers" id="ttsTiers"></div>' : ''}
                <div class="tts-tsyn" id="ttsTsyn" style="display:none"></div>
                ${t.reuse ? `<div class="tts-asm-heard tts-asm-reuse">Собрано из записанного: ${(t.reuse.srcs || [t.reuse.src]).map(n => '«' + escapeHtml(n) + '»').join(', ')}${t.reuse.rec ? ` + ${t.reuse.rec === 1 ? 'новый кусок' : 'новые куски'} из этой записи` : ''}. Куски — в Audacity отдельными клипами: склейте там и нажмите «Сохранить из Audacity».
                    <button type="button" class="btn-ghost btn-ghost--info btn-ghost--compact" onclick="ttsSendToAudacity()">Фрагменты → Audacity</button>
                    <button type="button" class="btn-ghost btn-ghost--good btn-ghost--compact" onclick="ttsSaveFromAudacity()">Сохранить из Audacity</button></div>` : ''}
                <div class="tts-asm-heard"><span class="tts-dim">Услышано:</span> ${t.heard ? escapeHtml(t.heard) : '<span class="tts-dim">—</span>'}</div>
                <div class="tts-ed">
                    <div class="tts-ed__row"><div class="tts-ed__lanes" id="ttsEdLanes"></div><canvas class="tts-ed__canvas" id="ttsEdCanvas"></canvas></div>
                    <div class="tts-ed__bar">
                        <span class="tts-ed__time" id="ttsEdTime"></span>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdCutBtn" onclick="ttsEditorCut()" disabled title="Вырезать выделенное (выделите мышью на клипе)">Вырезать <kbd>X</kbd></button>
                        <button class="btn-ghost btn-ghost--compact tts-ed-bil" data-lang="ru" onclick="ttsEdBilSet('ru')" disabled style="display:none" title="Выделенное — русский (кусок RU)"><em class="tts-tiers__lang is-ru">RU</em> выделенное</button>
                        <button class="btn-ghost btn-ghost--compact tts-ed-bil" data-lang="kz" onclick="ttsEdBilSet('kz')" disabled style="display:none" title="Выделенное — казахский (кусок KZ)"><em class="tts-tiers__lang is-kz">KZ</em> выделенное</button>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdUndo" onclick="ttsEdUndo()" disabled>&#8630; <kbd>Ctrl+Z</kbd></button>
                        <button class="btn-ghost btn-ghost--compact" id="ttsEdRedo" onclick="ttsEdUndo(true)" disabled>&#8631;</button>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsEditorReset()" title="Вернуть дубль, как его нарезала программа (тоже отменяется Ctrl+Z)">Сбросить</button>
                        ${u.kind === 'value' ? `<button class="btn-ghost btn-ghost--compact" onclick="ttsCtxPlay('whole', ${t.i})" title="Послушать в фразе: начало + этот дубль + продолжение">&#9654; В фразе</button>` : ''}
                        <button class="btn-ghost btn-ghost--compact" id="ttsTsynBtn" onclick="ttsTsynToggle()" title="Синтез слов «с… по…» — образец: этот дубль, как прослушали; ляжет новой дорожкой под этими словами">Синтез…</button>
                        <button class="btn-ghost btn-ghost--compact" onclick="ttsEdAddLane()" title="Новая пустая дорожка (Ctrl+D — копия текущей, Ctrl+C / Ctrl+V — кусок с дорожки на дорожку)">+ Дорожка</button>
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
                    <button class="btn-tile tts-asm-play ${ttsPlayingIdx === t.i ? 'is-active' : ''}" onclick="ttsTogglePlay()">${ttsPlayingIdx === t.i ? 'Стоп' : 'Слушать'} <kbd>Space</kbd></button>
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
            if (!ttsTR && r && r.error) {
                let el = document.getElementById('ttsTiers');
                if (el) el.innerHTML = `<div class="tts-dim">Ярусы: ${escapeHtml(r.error)}</div>`;
            }
        }
        // Две дорожки, как в режиме «Суммы»: «Дубль» — откуда взят каждый ярус
        // (края тянутся), «Сборка» — ярусы друг за другом, как склеятся файлы,
        // с концом начала фразы и началом продолжения; клип яруса тянется
        // вправо/влево — пауза перед ним. Готовый ярус (из другой строки) —
        // в сборке своим файлом, серый.
        // «Два языка» — своя сборка на язык: начало + RU (или KZ) + продолжение.
        const ttsTierLangs = () => ttsTR && ttsTR.bil ? [...new Set(ttsTR.tiers.map(t => t.lang).filter(Boolean))] : [null];
        function ttsTiersLayout(lang) {
            let r = ttsTR, x = 0, out = [];
            if (r.ctx.start) { out.push({ ctx: 'start', x, w: r.ctx.start.len, peaks: r.ctx.start.peaks, name: r.ctx.start.name }); x += r.ctx.start.len; }
            r.tiers.filter(t => !lang || t.lang === lang).forEach(t => {
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
            let r = ttsTR, langs = ttsTierLangs(), lays = langs.map(lg => ttsTiersLayout(lg));
            let span = ttsTiersSpan();
            let pct = ms => (100 * ms / span).toFixed(3) + '%';
            let lg = t => t.lang ? `<em class="tts-tiers__lang is-${t.lang}">${t.lang.toUpperCase()}</em> ` : '';
            let regions = r.tiers.map(t => `<div class="tts-tiers__reg ${(t.exists || t.shared) && !t.write ? 'is-skip' : ''} ${t.lang ? 'is-' + t.lang : ''}" style="left:${pct(t.a)};width:${pct(t.b - t.a)}"
                    title="${escapeHtml(t.label)} ${escapeHtml(t.value)}: ${escapeHtml(t.text)} — края тяните мышью">
                    <span>${lg(t)}${escapeHtml(t.text || t.label)}</span>
                    <i class="tts-tiers__edge is-l" onpointerdown="ttsTierEdge(event, ${t.k}, 'a')"></i>
                    <i class="tts-tiers__edge is-r" onpointerdown="ttsTierEdge(event, ${t.k}, 'b')"></i></div>`).join('');
            let clipsHTML = (lay, row) => lay.clips.map((c, n) => c.ctx
                ? `<div class="tts-tiers__clip is-ctx" style="left:${pct(c.x)};width:${pct(c.w)}" title="${c.ctx === 'start' ? 'Конец начала фразы' : 'Начало продолжения'} «${escapeHtml(c.name)}»">
                     <canvas data-row="${row}" data-n="${n}"></canvas><span>${c.ctx === 'start' ? '… ' + escapeHtml(c.name) : escapeHtml(c.name) + ' …'}</span></div>`
                : `${c.pre ? `<div class="tts-tiers__gap" style="left:${pct(c.x - c.pre)};width:${pct(c.pre)}">${c.pre}</div>` : ''}
                   <div class="tts-tiers__clip ${c.fixed ? 'is-fixed' : ''}" style="left:${pct(c.x)};width:${pct(c.w)}"
                     ${c.fixed ? `onpointerdown="event.stopPropagation(); ttsTierPlay(${c.k})" title="${escapeHtml(c.t.label)} ${escapeHtml(c.t.value)} — уже готов, берётся как есть"`
                       : `onpointerdown="ttsTierMove(event, ${c.k})" title="${escapeHtml(c.t.label)} ${escapeHtml(c.t.value)} — тяните: пауза перед ярусом; клик — послушать"`}>
                     <canvas data-row="${row}" data-n="${n}"></canvas><span>${lg(c.t)}<b>${escapeHtml(c.t.text || c.t.value)}</b></span></div>
                   ${c.post ? `<div class="tts-tiers__gap" style="left:${pct(c.x + c.w)};width:${pct(c.post)}">${c.post}</div>` : ''}`).join('');
            let chips = r.tiers.map(x => `<div class="tts-tiers__chip ${(x.exists || x.shared) && !x.write ? 'is-skip' : ''}">
                    <button type="button" class="tts-tiers__play" onclick="ttsTierPlay(${x.k})" title="Послушать ярус">&#9654;</button>
                    <span class="tts-tiers__lbl">${lg(x)}<b>${escapeHtml(x.text || x.value)}</b></span>
                    <span class="tts-tiers__txt">${escapeHtml(x.label)} · ${escapeHtml(x.value)}</span>
                    ${x.exists && !x.write ? '' : `<span class="tts-tiers__knob" title="Темп яруса (без смены высоты голоса)">темп
                        <button type="button" onclick="ttsTierKnob(${x.k}, 'tempo', -0.03)">&minus;</button><b>${Math.round(x.tempo * 100)}%</b><button type="button" onclick="ttsTierKnob(${x.k}, 'tempo', 0.03)">+</button></span>
                      <span class="tts-tiers__knob" title="Громкость яруса — к громкости фразы">дБ
                        <button type="button" onclick="ttsTierKnob(${x.k}, 'gain', -1)">&minus;</button><b>${x.gain > 0 ? '+' : ''}${x.gain}</b><button type="button" onclick="ttsTierKnob(${x.k}, 'gain', 1)">+</button></span>`}
                    ${x.exists ? `<label class="tts-tiers__exists" title="Этот эталон уже сохранён из другой строки — по умолчанию не трогаем">
                        <input type="checkbox" ${x.write ? 'checked' : ''} onchange="ttsTierWrite(${x.k}, this.checked)"> уже есть · перезаписать</label>`
                      : x.shared && !x.mine ? `<label class="tts-tiers__exists" title="Логика 2 сохраняет только сотни тысяч. Этот ярус записывается в логике 1">
                        <input type="checkbox" ${x.write ? 'checked' : ''} onchange="ttsTierWrite(${x.k}, this.checked)"> из логики 1 · сохранить и здесь</label>`
                      : x.mine ? '<span class="tts-tiers__ok">сохранён ✓</span>' : ''}</div>`).join('');
            let tp = r.tpl, o = r.opts || {}, hasCtx = !!(r.ctx.start || r.ctx.end);
            el.innerHTML = `<div class="tts-tiers__title">Ярусы
                    ${r.bil ? langs.map(lg_ => `<button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierPlay(-1, '${lg_}')" title="Начало + ${lg_.toUpperCase()} + продолжение. Клик по дорожке — играть с этого места">&#9654; ${lg_.toUpperCase()}</button>`).join('')
                      : `<button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierPlay(-1)" title="С секунды до первого яруса и до конца. Клик по дорожке «Сборка» — играть с этого места">&#9654; Вся сумма</button>`}
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierStop()" title="Остановить">&#9632;</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsTierJoinPlay()" title="Стык: конец начала фразы + строка + начало продолжения (по ${TTS_JOIN_MS / 1000} с)">&#9654; Стык</button>
                    ${ttsJoinHTML(r.tiers, 'ttsTierJoin')}
                    ${r.bil_ok ? `<button type="button" class="tts-reuse-chip ${r.bil ? 'is-on' : ''}" onclick="ttsTakeBil(${!r.bil})"
                        title="${r.bil ? 'Две границы: RU и KZ — каждый сохранится в свою папку (…/ru/ и …/kz/). Нажмите — одна запись, один файл' : 'В записи два языка подряд: появятся две границы — RU и KZ, выставите их сами'}">два языка${r.bil ? ' ✓' : ''}</button>` : ''}
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
                ${langs.map((lg_, row) => `<div class="tts-tiers__row"><span class="tts-tiers__name">${lg_ ? `Сборка <em class="tts-tiers__lang is-${lg_}">${lg_.toUpperCase()}</em>` : 'Сборка'}</span>
                    <div class="tts-tiers__asm" data-lang="${lg_ || ''}" onpointerdown="ttsTierSeek(event, ${lg_ ? `'${lg_}'` : 'null'})" title="Клик — слушать с этого места">${clipsHTML(lays[row], row)}<i class="tts-tiers__head" data-lang="${lg_ || ''}"></i></div></div>`).join('')}
                <div class="tts-tiers__chips">${chips}</div>`;
            ttsDrawPeaks(document.getElementById('ttsTiersCanvas'), r.peaks);
            ttsEdBilBtns();
            el.querySelectorAll('.tts-tiers__clip canvas').forEach(cv => ttsDrawPeaks(cv, lays[+cv.dataset.row].clips[+cv.dataset.n].peaks || []));
        }
        const ttsTiersSpan = () => Math.max(ttsTR.length, ...ttsTierLangs().map(lg => ttsTiersLayout(lg).total)) || 1;
        const ttsTierAsmEl = lang => document.querySelector(`#ttsTiers .tts-tiers__asm[data-lang="${lang || ''}"]`);
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
                let rc = ttsTierAsmEl(ttsTR.bil ? t.lang : null).getBoundingClientRect();
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
            let v = Math.max(0, Math.min(1500, (t[which] || 0) + d));
            (ttsTR.bil ? tiers : [t]).forEach(x => { x[which] = v; });     // два языка: у каждого свой файл — пауза в обоих
            ttsTiersRender();
            await ttsTiersSend();
            ttsTierJoinPlay();
        }
        let ttsTierBusy = false;                     // звук ярусов готовится — лишние клики не копятся
        async function ttsTierCall(fn) {
            if (ttsTierBusy) return null;
            ttsTierBusy = true;
            try { return await fn(); } finally { ttsTierBusy = false; }
        }
        async function ttsTierJoinPlay() {
            await ttsStopPlay();
            let r = await ttsTierCall(() => pywebview.api.tts_tier_play(ttsCurTake().i, null, 0, TTS_JOIN_MS, ttsTR && ttsTR.bil ? 'ru' : null));
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
            let t = ttsCurTake();
            if (t) { await ttsTiersLoad(t.i); ttsTierJoinPlay(); }
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
                ${ph.custom ? `<button type="button" class="btn-ghost btn-ghost--compact" onclick="ttsVarCtxAsk('${escapeHtml(ph.sheet)}', true)" title="Выбрать другие файлы начала и конца">начало и конец ✎</button>` : ''}
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
        // ✎ у «Начало/Конец»: правим дубль фразы — и обратно к строке, откуда пришли
        // (кнопка «← к строке», Esc или само после сохранения).
        let ttsTierBack = null;
        async function ttsTierOpenTake(k) {
            if (k === null || k === undefined) return;
            let row = ttsCurTake();
            ttsTierBack = row && tts.takes[k] ? { row: row.file, name: row.name || '', phrase: tts.takes[k].file } : null;
            await ttsSelect(k);
            ttsShowAssembly(true);
        }
        const ttsTierBackHere = t => !!(ttsTierBack && t && t.file === ttsTierBack.phrase);
        async function ttsTierReturn(msg) {
            let back = ttsTierBack;
            ttsTierBack = null;
            if (!back) return;
            let i = tts.takes.findIndex(x => x.file === back.row);
            if (i < 0) { showToast('Строка, откуда пришли, уже удалена'); return; }
            await ttsSelect(i);
            ttsShowAssembly(true);
            if (msg) showToast(msg, 2500);
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
        // «Два языка» в одной записи: дубль строки — два куска, RU и KZ, границы вручную.
        async function ttsTakeBil(on) {
            let res = await pywebview.api.tts_take_bil(ttsCurTake().i, on);
            if (res && res.error) { showToast(res.error); return; }
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
            if (on) showToast('Выставьте границы RU и KZ на дорожке «Дубль» и сохраните (Enter) — файлы лягут в …/ru/ и …/kz/', 5000);
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
        function ttsTierHead(fromMs, durMs, lang) {
            clearInterval(ttsTierHeadTimer);
            document.querySelectorAll('#ttsTiers .tts-tiers__head').forEach(h => h.style.display = 'none');
            let span = ttsTiersSpan(), t0 = performance.now();
            let step = () => {
                let el = document.querySelector(`#ttsTiers .tts-tiers__head[data-lang="${lang || ''}"]`);
                let ms = fromMs + (performance.now() - t0);
                if (!el || ms > fromMs + durMs) { if (el) el.style.display = 'none'; clearInterval(ttsTierHeadTimer); return; }
                el.style.display = 'block'; el.style.left = (100 * ms / span) + '%';
            };
            step(); ttsTierHeadTimer = setInterval(step, 40);
        }
        async function ttsTierSeek(e, lang) {
            let rc = e.currentTarget.getBoundingClientRect();
            if (!rc.width) return;
            await ttsTierPlayFrom(Math.max(0, Math.round((e.clientX - rc.left) / rc.width * ttsTiersSpan())), lang);
        }
        async function ttsTierPlayFrom(ms, lang) {
            await ttsStopPlay();
            let r = await ttsTierCall(() => pywebview.api.tts_tier_play(ttsCurTake().i, null, ms, null, lang || null));
            if (r && r.error) { showToast(r.error); return; }
            if (r && r.playing) ttsTierHead(r.from, r.duration * 1000, lang);
        }
        async function ttsTierStop() {
            clearInterval(ttsTierHeadTimer);
            document.querySelectorAll('#ttsTiers .tts-tiers__head').forEach(h => h.style.display = 'none');
            await pywebview.api.tts_stop_audio();
        }
        async function ttsTierWrite(k, on) {
            let w = {};
            ttsTR.tiers.forEach(x => { w[x.k] = x.k === k ? on : x.write; });
            let res = await pywebview.api.tts_tier_set(ttsCurTake().i, null, w);
            if (res && res.tiers) { ttsTR = res; ttsTiersRender(); }
        }
        async function ttsTierPlay(k, lang) {
            if (k < 0) {                       // вся сумма — с секунды до первого яруса
                let st0 = ttsTR && ttsTR.ctx.start ? Math.max(0, ttsTR.ctx.start.len - 1000) : 0;
                return ttsTierPlayFrom(st0, lang || (ttsTR && ttsTR.bil ? 'ru' : null));
            }
            await ttsStopPlay();
            clearInterval(ttsTierHeadTimer);
            let r = await ttsTierCall(() => pywebview.api.tts_tier_play(ttsCurTake().i, k, null));
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
            ttsTS = { i: t.i, words: r.words, start: r.fake ? r.start : 0, end: r.words.length - 1, pick: 0, overlap: 0, text: null,
                      mode: r.refs.length ? r.refs[0].mode : 'auto', refs: r.refs, fake: r.fake,
                      tail_word: r.tail_word, noise: r.noise, lang: r.lang, busy: r.busy };
            ttsTsynRender();
        }
        const ttsTsynText = () => ttsTS.text !== null ? ttsTS.text : ttsTS.words.slice(ttsTS.start, ttsTS.end + 1).join(' ');
        // Слова «с… по…»: первый щелчок — начало, второй — конец (раньше начала — новое начало).
        function ttsTsynWord(k) {
            if (!ttsTS || ttsTS.busy) return;
            if (ttsTS.pick === 0 || k < ttsTS.start) { ttsTS.start = k; ttsTS.end = k; ttsTS.pick = 1; }
            else { ttsTS.end = k; ttsTS.pick = 0; }
            ttsTS.text = null;
            ttsTsynRender();
        }
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
            let s = ttsTS;
            let words = s.words.map((w, k) => {
                let cls = k >= s.start && k <= s.end ? 'is-syn' : 'is-rec';
                return `<button type="button" class="tts-tsyn__w ${cls}" onclick="ttsTsynWord(${k})" title="${s.pick ? 'По это слово' : 'С этого слова'}">${escapeHtml(w)}</button>`;
            }).join('');
            let chip = (on, label, js, dis) => `<button type="button" class="chip ${on ? 'chip-mode--active' : ''}" onclick="${js}" ${dis ? 'disabled' : ''}>${label}</button>`;
            el.innerHTML = `
                <div class="tts-tsyn__head"><b>Синтез слов — новой дорожкой</b>
                    <span class="tts-dim">${s.pick ? 'теперь — по какое слово' : 'щёлкните первое слово, затем последнее'} ·
                    <span class="tts-tsyn__lg is-syn">синтез</span></span></div>
                <div class="tts-tsyn__words">${words}</div>
                <div class="tts-tsyn__row">
                    ${chip(s.start === 0 && s.end === s.words.length - 1, 'всю фразу', `ttsTsynSet({start: 0, end: ${s.words.length - 1}, pick: 0})`)}
                    <span class="tts-dim">ляжет под этими словами — сдвиньте точно, на дорожке записи вырежьте ошибку или выключите её (M)</span>
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
            if (o.start !== undefined || o.end !== undefined || o.overlap !== undefined) ttsTS.text = null;     // текст — заново по словам
            Object.assign(ttsTS, o);
            ttsTsynRender();
        }
        async function ttsTsynRun() {
            if (!ttsTS || ttsTS.busy) return;
            let mode = ttsTS.start === 0 && ttsTS.mode === 'take' ? 'auto' : ttsTS.mode;
            if (ttsEd && ttsEd.i === ttsTS.i) await ttsEditorApply();           // образец — ровно то, что сейчас на дорожке
            let r = await pywebview.api.tts_take_synth(ttsTS.i, ttsTS.start, 0, ttsTsynText(), mode, ttsSynTailOn(), ttsTS.end, 'new');
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
            ttsEd = { ...r, sel: null, drag: null, play: null, zoom: null, scroll: 0, cur: { lane: 0, t: null } };
            ttsEd.clips.forEach(c => { c.lane = c.lane || 0; });
            ttsEd.lanes = r.lanes || [{ name: 'Запись', mute: false }];
            ttsEdLanesRender();
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
        // Несколько дорожек — каждая своей полосой, клип обрывает только клип своей дорожки.
        const TTS_LANE_H = 78;
        const tlLanesN = () => (ttsEd.lanes || []).length || 1;
        const tlMultiLane = () => tlLanesN() > 1;
        const tlLaneRect = l => ({ top: TTS_ED_RULER + l * TTS_LANE_H, h: TTS_LANE_H });
        const tlLaneAt = y => Math.max(0, Math.min(tlLanesN() - 1, Math.floor((y - TTS_ED_RULER) / TTS_LANE_H)));
        const tlBase = () => Math.min(...ttsEd.clips.map(c => c.pos));
        const tlTotal = () => Math.max(...ttsEd.clips.map(c => c.pos + tlLen(c)));
        // Где кончается звучание клипа: следующий по дорожке клип его обрывает.
        function tlLimit(k) {
            let lane = ttsEd.clips[k].lane || 0, ord = tlOrder().filter(q => (ttsEd.clips[q].lane || 0) === lane), j = ord.indexOf(k);
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
            if (tlMultiLane()) return tlLaneRect(ttsEd.clips[k].lane || 0);
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
            canvas.classList.toggle('is-multi', ttsEd.clips.length > 1 && !tlMultiLane());
            let wantH = tlMultiLane() ? `${TTS_ED_RULER + tlLanesN() * TTS_LANE_H}px` : '';
            if (canvas.style.height !== wantH) { canvas.style.height = wantH; ttsEdLanesRender(); }
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
            if (tlMultiLane()) ttsEd.lanes.forEach((ln, l) => {                 // полосы дорожек
                let { top, h } = tlLaneRect(l);
                ctx.fillStyle = l === ttsEd.cur.lane ? 'rgba(77,149,234,0.06)' : (l % 2 ? 'rgba(255,255,255,0.018)' : 'rgba(0,0,0,0)');
                ctx.fillRect(0, top, W, h);
                ctx.fillStyle = 'rgba(255,255,255,0.07)'; ctx.fillRect(0, top + h - 1, W, 1);
            });
            tlOrder().forEach((k, j) => {
                let c = ttsEd.clips[k], len = tlLen(c), limit = tlLimit(k);
                let lanes = tlMultiLane(), x0 = tlX(c.pos), x1 = tlX(c.pos + len), col = colors[(lanes ? (c.lane || 0) : j) % colors.length];
                let multi = ttsEd.clips.length > 1 || lanes, { top, h: laneH } = tlLane(k), bot = top + laneH;
                let muted = lanes && (ttsEd.lanes[c.lane || 0] || {}).mute;
                if (muted) ctx.globalAlpha = 0.35;
                // тело и полоска для перетаскивания
                ctx.fillStyle = 'rgba(255,255,255,0.045)'; ctx.fillRect(x0, top, x1 - x0, laneH);
                if (multi) {
                    ctx.fillStyle = col; ctx.globalAlpha = (muted ? 0.35 : 1) * 0.55; ctx.fillRect(x0, top, x1 - x0, TTS_ED_HEAD); ctx.globalAlpha = muted ? 0.35 : 1;
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
                ctx.globalAlpha = 1;
            });
            if (ttsEd.cur.t != null) {                                          // курсор вставки (Ctrl+V)
                let r = tlMultiLane() ? tlLaneRect(ttsEd.cur.lane) : { top: TTS_ED_RULER, h: H - TTS_ED_RULER };
                ctx.fillStyle = 'rgba(90,150,255,0.9)'; ctx.fillRect(tlX(ttsEd.cur.t) - 0.5, r.top, 1, r.h);
            }
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
            ttsEdBilBtns();
            ttsEdHistButtons();
        }

        // Что под мышью: ручка края / полоска клипа / метка выреза / тело / пусто.
        function tlHit(x, y) {
            let multi = ttsEd.clips.length > 1 || tlMultiLane();
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
            let { x, y } = ttsEdPos(e), t = tlT(x), d = ttsEd.drag, c = ttsEd.clips[d.k];
            d.moved = d.moved || Math.abs(x - d.x0) > 3;
            if (d.kind === 'trim' && d.side === 'a') {
                let na = Math.round(Math.max(c.lo, Math.min(c.b - 80, d.a0 + (t - d.t0))));
                c.pos = Math.max(0, d.pos0 + (na - d.a0)); c.a = na;
            } else if (d.kind === 'trim') {
                c.b = Math.round(Math.max(c.a + 80, Math.min(c.hi, d.b0 + (t - d.t0))));
            } else if (d.kind === 'move') {
                c.pos = Math.max(0, Math.round(d.pos0 + (t - d.t0)));
                if (tlMultiLane()) { c.lane = tlLaneAt(y); ttsEd.cur.lane = c.lane; }
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
                ttsEd.cur = { lane: tlMultiLane() ? tlLaneAt(y) : 0, t: Math.round(t) };      // сюда — Ctrl+V
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
        const ttsEdSnap = () => ({ clips: ttsEd.clips.map(c => ({ ...c, cuts: (c.cuts || []).map(x => [...x]) })),
                                   lanes: (ttsEd.lanes || []).map(l => ({ ...l })) });
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
            if (Array.isArray(step.clips)) {                              // старый формат шага
                step.clips.forEach((sn, k) => { let c = ttsEd.clips[k]; if (c) { c.a = sn.a; c.b = sn.b; c.pos = sn.pos; c.cuts = sn.cuts.map(x => [...x]); } });
            } else {
                ttsEd.clips = step.clips.clips.map(c => ({ ...c, cuts: c.cuts.map(x => [...x]) }));
                ttsEd.lanes = step.clips.lanes.map(l => ({ ...l }));
                ttsEd.cur.lane = Math.min(ttsEd.cur.lane, ttsEd.lanes.length - 1);
            }
            ttsEdLanesRender();
            ttsEd.sel = null;
            ttsEditorDraw();
            await ttsEditorApply();
            ttsEdHistButtons();
            showToast((redo ? 'Вернул: ' : 'Отменил: ') + step.label);
        }

        // Вырез/возврат куска сдвигает клипы после него (на той же дорожке) — склейка не рвётся.
        function ttsEdRipple(c, from, delta) {
            if (!delta) return;
            ttsEd.clips.forEach(o => { if (o !== c && (o.lane || 0) === (c.lane || 0) && o.pos >= from - 1) o.pos = Math.max(0, o.pos + delta); });
        }

        // ----- дорожки: как в Audacity — добавить, удалить, без звука, копия, кусок с дорожки на дорожку -----
        function ttsEdLanesRender() {
            let box = document.getElementById('ttsEdLanes');
            if (!box || !ttsEd) return;
            let multi = tlMultiLane();
            box.style.display = multi ? '' : 'none';
            if (!multi) { box.innerHTML = ''; return; }
            box.innerHTML = `<div class="tts-lane__ruler"></div>` + ttsEd.lanes.map((ln, l) => {
                let n = ttsEd.clips.filter(c => (c.lane || 0) === l).length;
                return `<div class="tts-lane ${l === ttsEd.cur.lane ? 'is-cur' : ''} ${ln.mute ? 'is-mute' : ''}" style="height:${TTS_LANE_H}px" onclick="ttsEdCurLane(${l})">
                    <span class="tts-lane__name" title="${escapeHtml(ln.name)}">${escapeHtml(ln.name)}</span>
                    <span class="tts-lane__n">${n ? `клипов: ${n}` : 'пусто'}</span>
                    <span class="tts-lane__btns">
                        <button type="button" class="${ln.mute ? 'is-on' : ''}" onclick="event.stopPropagation(); ttsEdMuteLane(${l})" title="Без звука — не входит в сохранение">M</button>
                        <button type="button" onclick="event.stopPropagation(); ttsEdDupLane(${l})" title="Копия дорожки (Ctrl+D)">⧉</button>
                        <button type="button" onclick="event.stopPropagation(); ttsEdDelLane(${l})" title="Удалить дорожку">&times;</button></span></div>`;
            }).join('');
        }
        function ttsEdCurLane(l) { if (!ttsEd) return; ttsEd.cur.lane = l; ttsEdLanesRender(); ttsEditorDraw(); }
        function ttsEdLanesChanged(label, snap) {
            ttsEdRemember(label, snap);
            ttsEdLanesRender();
            ttsEditorDraw();
            ttsEditorApply();
        }
        function ttsEdAddLane() {
            if (!ttsEd) return;
            let snap = ttsEdSnap();
            ttsEd.lanes.push({ name: `Дорожка ${ttsEd.lanes.length + 1}`, mute: false });
            ttsEd.cur.lane = ttsEd.lanes.length - 1;
            ttsEdFit();
            ttsEdLanesChanged('новая дорожка', snap);
        }
        function ttsEdDupLane(l) {
            if (!ttsEd) return;
            l = l === undefined ? (ttsEd.sel ? (ttsEd.clips[ttsEd.sel.k].lane || 0) : ttsEd.cur.lane) : l;
            let src = ttsEd.clips.filter(c => (c.lane || 0) === l);
            if (!src.length) { showToast('На этой дорожке нет клипов'); return; }
            let snap = ttsEdSnap(), k = ttsEd.lanes.length;
            ttsEd.lanes.push({ name: `${(ttsEd.lanes[l] || {}).name || 'Дорожка'} — копия`, mute: false });
            src.forEach(c => ttsEd.clips.push({ ...c, cuts: (c.cuts || []).map(x => [...x]), lane: k }));
            ttsEd.cur.lane = k;
            ttsEdLanesChanged('копия дорожки', snap);
            showToast('Копия дорожки — ниже. Совпадает с исходной: одну из них выключите (M) или сдвиньте');
        }
        function ttsEdDelLane(l) {
            if (!ttsEd || ttsEd.lanes.length < 2) { showToast('Это единственная дорожка'); return; }
            let rest = ttsEd.clips.filter(c => (c.lane || 0) !== l);
            if (!rest.length) { showToast('На остальных дорожках нет звука — нечего оставить'); return; }
            let snap = ttsEdSnap();
            ttsEd.clips = rest.map(c => ({ ...c, lane: (c.lane || 0) > l ? c.lane - 1 : (c.lane || 0) }));
            ttsEd.lanes.splice(l, 1);
            ttsEd.cur.lane = Math.min(ttsEd.cur.lane, ttsEd.lanes.length - 1);
            ttsEd.sel = null;
            ttsEdLanesChanged('удаление дорожки', snap);
        }
        function ttsEdMuteLane(l) {
            if (!ttsEd) return;
            let snap = ttsEdSnap();
            ttsEd.lanes[l].mute = !ttsEd.lanes[l].mute;
            ttsEdLanesChanged(ttsEd.lanes[l].mute ? 'дорожка без звука' : 'дорожка со звуком', snap);
        }
        let ttsEdClip = null;                                     // скопированный кусок (Ctrl+C)
        function ttsEdCopy() {
            if (!ttsEd || !ttsEd.sel) { showToast('Выделите кусок на клипе мышью — потом Ctrl+C'); return; }
            let c = ttsEd.clips[ttsEd.sel.k];
            let t0 = Math.min(ttsEd.sel.t0, ttsEd.sel.t1), t1 = Math.max(ttsEd.sel.t0, ttsEd.sel.t1);
            let r0 = Math.round(tlRawAt(c, t0)), r1 = Math.round(tlRawAt(c, t1));
            if (r1 - r0 < 15) return;
            ttsEdClip = { raw: c.raw, a: r0, b: r1, lo: c.lo, hi: c.hi, peaks: c.peaks,
                          cuts: (c.cuts || []).map(([x, y]) => [Math.max(r0, x), Math.min(r1, y)]).filter(([x, y]) => y > x) };
            showToast(`Скопировано ${((r1 - r0) / 1000).toFixed(2)} с — щёлкните место на дорожке и Ctrl+V`);
        }
        function ttsEdPaste() {
            if (!ttsEd || !ttsEdClip) { showToast('Сначала выделите кусок и Ctrl+C'); return; }
            let snap = ttsEdSnap(), lane = ttsEd.cur.lane;
            let at = ttsEd.cur.t != null ? ttsEd.cur.t : tlTotal() + 40;
            if (lane >= ttsEd.lanes.length) lane = ttsEd.lanes.length - 1;
            ttsEd.clips.push({ ...ttsEdClip, cuts: ttsEdClip.cuts.map(x => [...x]), pos: Math.max(0, Math.round(at)), lane });
            ttsEd.sel = null;
            ttsEdLanesChanged('вставка куска', snap);
        }

        async function ttsEditorApply() {
            if (!ttsEd) return;
            await ttsStopPlay();
            let clips = ttsEd.clips.map(c => ({ raw: c.raw, a: c.a, b: c.b, pos: c.pos, cuts: c.cuts || [], lane: c.lane || 0 }));
            let res = await pywebview.api.tts_clips_apply(ttsEd.i, clips, ttsEd.lanes);
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
            if (ttsPlayPending) return;                  // ещё готовится — второй клик не запускает заново
            clearTimeout(ttsPlayTimer);
            let g = ++ttsPlayGen;
            ttsPlayPending = true;
            let rng = ttsEdSelRange();                   // выделено — слушаем выделенное, нет — с начала
            let res = await pywebview.api.tts_play(t.i, rng ? rng[0] : null, rng ? rng[1] : null);
            if (g === ttsPlayGen) ttsPlayPending = false;
            if (g !== ttsPlayGen) return;                // пока запускалось — нажали другое
            if (!res || !res.playing) { if (res && res.error) showToast(res.error); return; }
            ttsPlayingIdx = t.i;
            ttsRenderRail(); ttsRenderCurrent();
            ttsEditorPlayhead(res.duration, rng ? rng[0] : 0, g, res.tempo);
            ttsPlayTimer = setTimeout(() => {
                if (g !== ttsPlayGen) return;
                // Отыграл до конца — считаем прослушанным (бэкенд сверит по времени).
                ttsPlayingIdx = -1;
                pywebview.api.tts_select(t.i).then(st => { tts = st; ttsRender(); });
            }, res.duration * 1000 + 120);
        }

        // Выделение в редакторе «Сборки» → [от, до] в мс файла дубля (null — нет выделения).
        function ttsEdSelRange() {
            let t = ttsCurTake();
            if (!ttsEd || !t || ttsEd.i !== t.i || !ttsEd.sel || Math.abs(ttsEd.sel.t1 - ttsEd.sel.t0) < 15) return null;
            let c = ttsEd.clips[ttsEd.sel.k], base = tlBase();
            if (!c) return null;
            let a = Math.max(c.pos, Math.min(ttsEd.sel.t0, ttsEd.sel.t1)), b = Math.min(c.pos + tlLen(c), Math.max(ttsEd.sel.t0, ttsEd.sel.t1));
            return b - a >= 15 ? [Math.round(a - base), Math.round(b - base)] : null;
        }
        function ttsEdBilBtns() {
            let bil = !!(ttsTR && ttsTR.bil && ttsEd && ttsTR.i === ttsEd.i);
            document.querySelectorAll('#ttsAssembly .tts-ed-bil').forEach(b => { b.style.display = bil ? '' : 'none'; b.disabled = !(ttsEd && ttsEd.sel); });
        }
        // «Два языка»: выделенное в редакторе — кусок RU или KZ.
        function ttsEdBilSet(lang) {
            let rng = ttsEdSelRange();
            if (!rng) { showToast('Выделите мышью на волне, где звучит ' + (lang === 'ru' ? 'русский' : 'казахский')); return; }
            if (!ttsTR || !ttsTR.bil) return;
            let x = ttsTR.tiers.find(q => q.lang === lang);
            if (!x) return;
            x.a = rng[0]; x.b = Math.min(ttsTR.length, rng[1]);
            ttsTiersRender(); ttsTiersSend();
            showToast(`${lang.toUpperCase()}: ${(x.a / 1000).toFixed(2)}–${(x.b / 1000).toFixed(2)} с`, 1500);
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
                else if (ttsTierBackHere(t) && !ttsRec.on) await ttsTierReturn(`Фраза сохранена — обратно к строке ${ttsTierBack.name}`);
                else if (ttsCutMode && !ttsRec.on) ttsCutNext(t.i);
                else if (ttsCurTake() && !ttsCurTake().unit_saved) ttsTogglePlay();
                ttsCutChipUpdate();
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
            let u = ttsUnit(tts.takes[i].unit);
            if (u && u.kind === 'piece') {
                if (i !== tts.index) await ttsSelect(i);
                ttsShowAssembly(true);
                ttsApprove();
                return;
            }
            // Не привязан к кусочку фразы — сохраняем сырым в «Фразы_Переменные», ничего не спрашивая.
            let r = await pywebview.api.tts_take_to_raw_vars(i);
            if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
            let card = document.getElementById('ttsVarCard');
            card.classList.remove('is-bump'); void card.offsetWidth; card.classList.add('is-bump');
            let keep = tts.index; tts = r; tts.index = keep; ttsRender();
            showToast(`Дубль отмечен «→ Перем.»: ${r.dir}/${r.raw_var}. Кнопка «Переменные» — сборка сырых`, 6000);
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
            if (ttsCutMode && !ttsRec.on) ttsCutNext(t.i - 1);
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
            if ((ttsVars.raw || []).length) ttsVarsTab = 'raw';                       // есть сырые — сразу они
            else if (ttsVarsTab === 'raw') ttsVarsTab = 'chains';
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
            let tabs = [['raw', `Сырые · ${(ttsVars.raw || []).length}`], ['chains', `Фразы · ${ttsVars.chains.length}`]].concat(ttsVars.sheets.map(sh => {
                let ready = sh.categories.reduce((a, c) => a + c.ready, 0), all = sh.categories.reduce((a, c) => a + c.values.length, 0);
                return [sh.key, `${sh.label} · ${ready}/${all}`];
            })).concat([['synth', ttsSynth ? `Синтез сумм · ${ttsSynth.approved}/${ttsSynth.items.length}` : 'Синтез сумм']]);
            document.getElementById('ttsVarsTabs').innerHTML = tabs.map(([k, l]) =>
                `<button type="button" class="chip ${k === ttsVarsTab ? 'chip-mode--active' : ''}" onclick="ttsVarsSetTab('${k}')">${escapeHtml(l)}</button>`).join('');
            let body = document.getElementById('ttsVarsBody');
            if (ttsVarsTab === 'raw') { body.innerHTML = ttsVarsRawHTML(); return; }
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

        // «Сырые»: файлы из «Фразы_Переменные», которые перенесли с ленты и ещё не сделали кусочками фраз
        function ttsVarsRawHTML() {
            let raw = ttsVars.raw || [];
            if (!raw.length) return `<div class="tts-dim tts-list__empty">Сырых нет. Перетащите дубль с ленты на карточку «Переменные» — он сохранится в «Фразы_Переменные», и здесь его можно будет собрать.</div>`;
            let q = f => JSON.stringify(f).replace(/"/g, '&quot;');
            let st = raw.find(r => r.mark === 'start'), en = raw.find(r => r.mark === 'end');
            return `<div class="tts-vraw__bar">
                    <span>Начало: <b>${st ? escapeHtml(st.name) : '—'}</b> · конец: <b>${en ? escapeHtml(en.name) : '—'}</b></span>
                    <span class="tts-ed__spacer"></span>
                    <button class="btn-ghost btn-ghost--compact" onclick="ttsRawAssembly(true)" title="Выбрать другую папку с записями переменной">папка переменных…</button>
                    <button class="custom-alert-btn" onclick="ttsRawAssembly(false)" ${st ? '' : 'disabled'} title="Начало → переменная → конец: слушать, подрезать каждую часть, сохранять">Сборка переменной →</button>
                </div>
                <div class="tts-dim" style="margin:6px 0 8px">Отметьте, какой файл — начальная фраза, а какой — конечная. Потом «Сборка переменной».</div>` + raw.map(r => `
                <div class="tts-vraw ${r.mark ? 'is-' + r.mark : ''}">
                    <button class="btn-ghost btn-ghost--compact" onclick="pywebview.api.tts_raw_var_play(${q(r.file)})" title="Слушать">&#9654;</button>
                    <span class="tts-vraw__name" title="${escapeHtml(r.file)}">${escapeHtml(r.name)}</span>
                    <span class="tts-dim">${(r.ms / 1000).toFixed(2)} с</span>
                    <span class="tts-ed__spacer"></span>
                    <button class="btn-ghost btn-ghost--compact ${r.mark === 'start' ? 'is-on' : ''}" onclick="ttsRawMark(${q(r.file)}, 'start')">Начало</button>
                    <button class="btn-ghost btn-ghost--compact ${r.mark === 'end' ? 'is-on' : ''}" onclick="ttsRawMark(${q(r.file)}, 'end')">Конец</button>
                    <button class="btn-ghost btn-ghost--compact btn-ghost--good" onclick="ttsRawVarToRail(${JSON.stringify(r.file).replace(/"/g, '&quot;')})">${r.on_rail ? 'на ленте — открыть' : 'В сборку'}</button>
                </div>`).join('');
        }
        async function ttsRawMark(file, which) {
            let r = await pywebview.api.tts_raw_mark(file, which);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            ttsVars.raw = r.raw; ttsRenderVars();
        }
        // «Сборка переменной»: начало + значение + конец — экран «Прослушки» с этой парой
        async function ttsRawAssembly(pick) {
            let r = await pywebview.api.tts_raw_assembly(!!pick);
            if (r && r.need_folder) {
                if (!(await showBeautifulConfirm('<b>Загрузите переменные</b><br><br>Выберите папку с записями переменной — файл на значение '
                    + '(можно с подпапками ru и kz). Сборка: начальная фраза → переменная → конечная фраза.', 'Выбрать папку', 'Отмена'))) return;
                r = await pywebview.api.tts_raw_assembly(true);
            }
            if (!r || r.error) { if (r && r.error !== 'cancel') showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
            ttsCloseVars();
            LS = r;
            listenOpen();
            showToast(`Сборка переменной: ${r.rows.length} значений · начало «${r.start || '—'}», конец «${r.end || '—'}»`, 5000);
        }
        async function ttsRawVarToRail(file) {
            let r = await pywebview.api.tts_raw_var_to_rail(file);
            if (!r || r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
            let idx = r.index;
            tts = r; ttsCloseVars(); ttsRender();
            await ttsSelect(idx);
            ttsShowAssembly(true);
            showToast('Сырой файл на ленте — подрежьте, дайте название (F) и сохраните (Enter)', 5000);
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


