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
            await pywebview.api.tts_live_fast(ttsFastOn() || ttsFlowActive());
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

        // Опрос не накладывается: пока прошлый ответ не пришёл, новый не шлём
        // (иначе при медленном ответе вызовы копятся и окно «не отвечает»).
        let ttsRecPollBusy = false;
        async function ttsRecPoll() {
            if (ttsRecPollBusy) return;
            ttsRecPollBusy = true;
            let s;
            try { s = await pywebview.api.tts_rec_status(); } finally { ttsRecPollBusy = false; }
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
                showToast(`Логика ${pr.logic_switched.from}: остальные строки не нужны — их эталоны уже есть в проекте. Дальше ${n[pr.logic_switched.to]}.`
                    + (pr.tier_redo ? '' : ' Записать заново — «↻ перезаписать все»'), 7000);
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
            if (pr && pr.focus_switched) showToast(`Дальше недостающие: ${pr.focus_switched}`, 4000);
            if (pr && pr.focus_done && !pr.pending) {
                text.innerHTML = 'Недостающие из аудита записаны 🎉';
                meta.innerHTML = `<span>${ttsFocusHTML(pr)}</span>`;
                next.innerHTML = `<button type="button" class="tts-reuse-chip is-on" onclick="ttsAuditAgain()">Проверить аудитом снова</button>
                    <button type="button" class="tts-reuse-chip" onclick="ttsFocusClear()">Показать всю таблицу</button>
                    <span class="tts-dim">· сдавайте дубли: клик по карточке внизу — сборка, Enter — сохранить</span>`;
                ttsPromptKey = 'focus-done'; ttsRenderMarks(null);
                return;
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
                meta.innerHTML = `<span>${ttsModesHTML(pr)}${ttsSumLogicHTML(pr)}${ttsTierRedoHTML(pr)}${ttsFlowHTML()} ${pr.total} из ${pr.total}</span>`;
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
            let modes = ttsFocusHTML(pr) + ttsModesHTML(pr);
            if (pr.context) modes += ` <button type="button" class="tts-reuse-chip ${pr.context.start_saved ? 'is-on' : ''}" onclick="ttsCtxPlay('start')"
                    title="${pr.context.start_saved ? 'Послушать конец начала «' + escapeHtml(pr.context.start_name) + '» (последние 2–3 секунды) — и сразу читайте сумму в той же интонации' : 'Начало «' + escapeHtml(pr.context.start_name) + '» ещё не записано (режим «Фразы»)'}">&#9654; Начало</button>`;
            if (pr.var_ctx && pr.mode !== 'phrases') {
                let vc = pr.var_ctx;
                modes += ` <button type="button" class="tts-reuse-chip ${vc.custom ? 'is-on' : ''}" onclick="ttsVarCtxAsk('${escapeHtml(pr.mode)}', true)"
                    title="${vc.custom ? 'Начало «' + escapeHtml(vc.start || '—') + '», конец «' + escapeHtml(vc.end || 'нет') + '» — нажмите, чтобы выбрать другие'
                        : 'Начальная и конечная фразы вокруг значения — аудиофайлы'}">${vc.custom ? 'начало и конец ✎' : 'начало и конец…'}</button>`;
            }
            if (pr.sum_logic) modes += ttsSumLogicHTML(pr);
            modes += ttsTierRedoHTML(pr);
            modes += ttsFlowHTML();
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

        // «Новый проект»: сбросить текущий TTS-проект и загрузить другую папку/таблицу.
        async function ttsResetProject() {
            if (ttsRec.on) { showToast('Сначала остановите запись (R)'); return; }
            if (tts && tts.loaded && !(await showBeautifulConfirm(
                `Закрыть проект <b>${escapeHtml(tts.project || tts.excel_name || '')}</b> и начать новый?<br><br>Всё записанное и сохранённое останется в его папке — его можно открыть снова.`,
                'Новый проект', 'Отмена'))) return;
            await ttsStopPlay();
            let res = await pywebview.api.tts_reset();
            if (!res || res.error) { showToast(res && res.error || 'Не получилось'); return; }
            tts = res;
            ttsTR = null; ttsEd = null; ttsTS = null; ttsAudacitySent = -1; ttsPromptKey = null;
            ttsAsmQueue = []; ttsAsmAuto = false;
            let asm = document.getElementById('ttsAssembly'); if (asm) asm.dataset.key = '';
            ttsShowAssembly(false);
            ttsRender();
            await ttsLoadPrompt();
            showToast('Проект закрыт — выберите таблицу («Таблица») для нового');
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
            document.getElementById('stage4-tts').classList.remove('is-holding');
            ttsSetPaused(false);
            ttsRec.on = false;
            ttsSetRecUi(false);
            ttsLiveSt.holding = ttsLiveSt.busy = false; ttsLiveSt.micOff = false; ttsLiveRender();
            if (state) ttsLiveUpdate(state, 0);
            ttsLoadPrompt();
            if (error) { showBeautifulAlert('⚠️ Запись остановилась с ошибкой:<br><br>' + escapeHtml(error)); return; }
            showToast('Запись сохранена в папку «Записи»');
            let cut = ttsCutList().length;
            if (ttsFlowActive() && cut) {
                // Поток: прочитали — теперь спокойно срезаем, строка за строкой.
                showBeautifulAlert(`✂️ <b>Записано строк: ${cut}</b><br><br>Теперь срезка: каждая строка откроется в «Сборке»,
                    поправьте границы ярусов и нажмите <b>Enter</b> — сохранится и откроется следующая. Esc — прервать,
                    продолжить потом — «✂ Срезка» в суфлёре.<br><br>
                    <button type="button" class="custom-alert-btn" onclick="closeCustomAlert(); ttsCutStart()">Начать срезку</button>`);
                return;
            }
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
                rail.querySelectorAll('.tts-take[data-i]').forEach((el, k) => { if (k >= tts.takes.length - added) el.classList.add('is-new'); });
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
            document.getElementById('stage4-tts').classList.toggle('is-holding', down);   // затемнение вокруг текста
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
        // ----- «Поток»: суммы/даты читаются подряд, без «Сборки» и ожидания распознавания;
        // срезка потом — «✂ Срезка N»: строка за строкой в обычной «Сборке», Enter — сохранить и дальше. -----
        function ttsFlowOn() {
            try { return localStorage.getItem('gvox_tts_flow') !== '0'; } catch (e) { return true; }
        }
        const ttsValueMode = () => !!tts && (tts.prompt_mode || 'phrases') !== 'phrases';
        const ttsFlowActive = () => ttsFlowOn() && ttsValueMode();
        async function ttsFlowToggle() {
            let on = !ttsFlowOn();
            try { localStorage.setItem('gvox_tts_flow', on ? '1' : '0'); } catch (e) {}
            if (ttsRec.on) await pywebview.api.tts_live_fast(ttsFastOn() || ttsFlowActive());
            ttsPromptKey = null; ttsLoadPrompt();
            showToast(on ? 'Поток: читайте строки подряд — «Сборка» не откроется. Срезка потом: «✂ Срезка»'
                         : 'Поток выключен: после каждой строки — «Сборка»', 4500);
        }
        // Дубли строк сумм/дат, ещё не сохранённые эталонами, — по порядку записи.
        function ttsCutList() {
            if (!tts) return [];
            return tts.takes.filter(t => t.unit !== null && !t.approved && !t.rejected
                && tts.units[t.unit] && tts.units[t.unit].tiers).map(t => t.i);
        }
        function ttsFlowHTML() {
            if (!ttsValueMode()) return '';
            let n = ttsCutList().length;
            return ` <button type="button" class="tts-reuse-chip ${ttsFlowOn() ? 'is-on' : ''}" onclick="ttsFlowToggle()"
                    title="${ttsFlowOn() ? 'Включено: читаете строки подряд, суфлёр сразу дальше, «Сборка» не открывается. Клик — выключить' : 'Включить: читать строки подряд без «Сборки», срезать потом'}">&#9654;&#9654; поток${ttsFlowOn() ? ' ✓' : ''}</button>`
                + `<button type="button" class="tts-reuse-chip ${n ? 'is-on tts-cut-chip' : ''}" id="ttsCutChip" onclick="ttsCutStart()" ${n ? '' : 'disabled'}
                    title="Срезать записанные строки по очереди: «Сборка» → границы ярусов → Enter сохраняет и открывает следующую. Esc — прервать">&#9986; Срезка ${n}</button>`;
        }
        function ttsCutChipUpdate() {
            let b = document.getElementById('ttsCutChip');
            if (!b) return;
            let n = ttsCutList().length;
            b.innerHTML = `&#9986; Срезка ${n}`;
            b.disabled = !n;
            b.classList.toggle('is-on', !!n); b.classList.toggle('tts-cut-chip', !!n);
        }
        let ttsCutMode = false;
        async function ttsCutStart() {
            if (ttsRec.on) { showToast('Сначала остановите запись (R) — срезка после чтения'); return; }
            ttsCutMode = true;
            ttsCutNext(-1);
        }
        function ttsCutNext(after) {
            let list = ttsCutList();
            if (!ttsCutMode) return;
            if (!list.length) {
                ttsCutMode = false;
                ttsShowAssembly(false);
                showToast('Срезка закончена — все записанные строки сохранены', 4000);
                ttsLoadPrompt();
                return;
            }
            let k = list.find(i => i > after);
            tts.index = k === undefined ? list[0] : k;
            ttsRenderRail(); ttsRenderCurrent(); ttsShowAssembly(true); ttsTogglePlay();
            showToast(`Срезка: осталось строк ${list.length} · Enter — сохранить и дальше, Del — удалить`, 2500);
        }

        function ttsAutoAsm(added) {
            if (!(added > 0) || !ttsRec.on || !ttsAutoAsmOn() || !tts || !tts.takes.length) return;
            if (ttsFlowActive()) { ttsCutChipUpdate(); return; }      // поток: срезка потом
            if (ttsPttDown) { ttsAutoAsmPending = added; return; }     // сейчас пишут — откроем, когда отпустят
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
            document.getElementById('stage4-tts').classList.remove('is-holding');
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
        // «Перезаписать все»: суфлёр ведёт по всем строкам листа, готовые эталоны пишутся заново.
        function ttsTierRedoHTML(pr) {
            if (pr.tier_redo === undefined) return '';
            return ` <button type="button" class="tts-pmode ${pr.tier_redo ? 'is-on' : ''}" onclick="ttsTierRedo(${!pr.tier_redo})"
                title="${pr.tier_redo ? 'Включено: суфлёр идёт по всем строкам, эталоны перезаписываются (каждое значение — один раз). Клик — выключить'
                    : 'Сейчас суфлёр пропускает строки, у которых все эталоны уже есть в проекте. Клик — пройти все строки заново и перезаписать эталоны'}">${pr.tier_redo ? '↻ перезапись: вкл' : '↻ перезаписать все'}</button>`;
        }
        async function ttsTierRedo(on) {
            if (ttsRec.on && on) { showToast('Сначала остановите запись (R)'); return; }
            let r = await pywebview.api.tts_tier_redo(on);
            if (!r || r.error) { if (r) showToast(r.error); return; }
            tts = r.state; ttsRender(); ttsPromptKey = null;
            if (r.prompt) ttsRenderPrompt(r.prompt, 'next');
            showToast(on ? 'Перезапись: суфлёр пройдёт все строки, старые эталоны уйдут в корзину проекта при сохранении' : 'Перезапись выключена', 4000);
        }

        function ttsFocusHTML(pr) {
            return pr.focus ? `<span class="tts-focus" title="Суфлёр показывает только то, чего не хватило в аудите">Недостающие из аудита · осталось ${pr.focus.left} из ${pr.focus.total}
                <button type="button" onclick="ttsFocusClear()" title="Показать всю таблицу">×</button></span> ` : '';
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
                : r.prompt && r.prompt.sum_logic ? 'Читаем суммы строками — Enter в «Сборке» сохранит ярусы сразу эталонами в «Значения/sum_…»'
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
            let s = tts.stats, vp = tts.vars_progress;            // «только переменные»: считаем значения листа
            document.getElementById('ttsStatLabel').innerText = vp ? vp.label : 'Сохранено';
            document.getElementById('ttsMissingBtn').style.display = tts.vars_only ? 'none' : '';
            document.getElementById('ttsStatSaved').innerText = vp ? vp.done : s.saved;
            document.getElementById('ttsStatUnits').innerText = vp ? vp.total : s.units;
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
            // правили фразу из строки переменных — закрыть = вернуться к строке
            if (on === false && ttsTierBackHere(ttsCurTake()) && !ttsRec.on) { ttsTierReturn(); return; }
            let stage = document.getElementById('stage4-tts');
            stage.classList.toggle('show-assembly', on === undefined ? !stage.classList.contains('show-assembly') : on);
            let open = stage.classList.contains('show-assembly');
            if (open) {
                ttsPttCancel(); ttsEd = null; document.getElementById('ttsAssembly').dataset.key = ''; ttsRenderAssembly();
                let t = ttsCurTake();                   // «из записанного» — куски сразу в Audacity
                if (t && t.reuse && ttsAudacitySent !== t.i) ttsSendToAudacity(true);
            }
            else { ttsAsmAuto = false; ttsAsmQueue = []; ttsCutMode = false; }
            // Сборка открыта — микрофон выключен: не шумит при прослушивании.
            if (ttsRec.on && ttsLiveSt.micOff !== open) {
                ttsLiveSt.micOff = open;
                pywebview.api.tts_live_mic(!open);
                ttsLiveRender();
            }
            else if (ttsPlayingIdx >= 0) ttsStopPlay().then(() => { ttsRenderRail(); ttsRenderCurrent(); });
        }


// Всплывающее полное название над дублем на ленте (в ленте оно обрезается)
(function ttsRailTip() {
    let tip = null, cur = null;
    const hide = () => { cur = null; if (tip) tip.classList.remove('is-on'); };
    document.addEventListener('mouseover', e => {
        let el = e.target.closest && e.target.closest('#ttsRail .tts-take[data-tip]');
        if (!el) { if (cur) hide(); return; }
        if (el === cur) return;
        cur = el;
        if (!tip) { tip = document.createElement('div'); tip.className = 'tts-tip'; document.body.appendChild(tip); }
        tip.innerHTML = `${escapeHtml(el.dataset.tip)}${el.dataset.tip2 ? `<small>${escapeHtml(el.dataset.tip2)}</small>` : ''}`;
        let r = el.getBoundingClientRect(), tw = tip.offsetWidth, th = tip.offsetHeight;
        tip.style.left = Math.max(6, Math.min(innerWidth - tw - 6, r.left + r.width / 2 - tw / 2)) + 'px';
        tip.style.top = Math.max(6, r.top - th - 8) + 'px';
        tip.classList.add('is-on');
    });
    document.addEventListener('mouseleave', hide, true);
    document.addEventListener('dragstart', hide, true);
    document.addEventListener('scroll', hide, true);
})();
