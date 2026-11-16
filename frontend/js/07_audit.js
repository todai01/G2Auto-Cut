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

            const addOption = (key, label, desc, cls) => {
                let btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'audit-category-item' + (cls ? ' ' + cls : '');
                btn.innerHTML = escapeHtml(label) + (desc ? `<span class="audit-choice-desc">${escapeHtml(desc)}</span>` : '');
                btn.onclick = () => {
                    closeAuditCategoryPicker();
                    if (['all', 'vars', 'studio', 'studio_pick'].includes(key)) runProjectAudit(key);      // сразу по названиям файлов
                    else askAuditChunks(key, key === 'excel' ? 'Текст из Excel' : label);
                };
                list.appendChild(btn);
            };
            const addHead = text => {
                let h = document.createElement('div');
                h.className = 'audit-category-head';
                h.textContent = text;
                list.appendChild(h);
            };

            let cats = res.categories || [];
            let studio = res.studio || {};
            addOption('studio', 'Таблица Студии записи — все листы',
                (studio.loaded ? `«${studio.name}» · изменена ${studio.mtime} · ` : 'Выберу таблицу (.xlsx) · ')
                + 'фразы, суммы по ярусам, даты — во всех папках внутри выбранной', 'is-main');
            if (studio.loaded) addOption('studio_pick', 'Другая таблица (.xlsx) — все листы',
                'Обновили таблицу или она лежит в другом месте — выберите файл, читается заново');
            if (res.has_excel && cats.length)
                addOption('all', 'Весь проект (Шаг 1 + словарь)', 'Фразы по языкам и все переменные словаря — одной проверкой, по названиям файлов');
            if (res.has_excel) addOption('excel', 'Фразы (Excel, Шаг 1)', 'Названия из таблицы — по языкам');
            if (cats.length > 1) addOption('vars', 'Все переменные', 'Каждая категория — в своей папке («1 - 100 млн», «1 - 99 тыс»…)');
            if (cats.length) {
                addHead('Одна категория');
                cats.forEach(c => addOption(c.key, c.label, '', 'is-compact'));
            }

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

        // Аудит по группам: «Фразы» (по языкам) и «Переменные» (Суммы — по
        // ярусам, остальные категории — отдельно). В каждой группе — сводка
        // одной строкой, раскрывается: чего нет, дубли, записи.
        let auditFilter = '';
        let auditOnlyProblems = false;
        let auditOpen = {};                 // id группы/подсписка → раскрыт ли (запоминается между перерисовками)
        function auditGroupsOf(res) {
            if (res.groups && res.groups.length) return res.groups;
            let voice = !!res.by_voice;
            return [{ id: '_all', section: res.category ? 'Переменные' : 'Фразы',
                      title: res.category_label || (voice ? 'Записи' : 'Текст из Excel'),
                      total: res.total_excel, found: voice ? res.total_disk : (res.files || []).length,
                      missing: res.missing_count, duplicates: voice ? (res.unknown || []).length : res.duplicates_count }];
        }
        function renderAuditResult(res, quiet) {
            window.auditRes = res;
            let voice = !!res.by_voice;
            let unknown = res.unknown || [];
            let groups = auditGroupsOf(res);
            let gid0 = groups[0].id;
            let gidOf = x => x.group || gid0;
            let multi = groups.length > 1;
            let categoryNote = res.category ? ` — категория «${res.category_label}»`
                : res.mode === 'studio' ? ` — таблица «${res.studio_name || ''}» (изменена ${res.studio_mtime || '—'}), все листы`
                : res.mode === 'all' ? ' — весь проект' : res.mode === 'vars' ? ' — все переменные' : '';
            if (voice) categoryNote += ` — по голосу, чанков: ${res.chunks_total}${res.stopped ? ' (остановлено, проверены не все)' : ''}`;
            document.getElementById('auditOverlay').style.display = 'flex';
            document.getElementById('auditPath').innerHTML = iconHTML('folder') + (voice ? " Чанки: " : " Директория сканирования: ") + escapeHtml(res.scan_dir) + escapeHtml(categoryNote);
            document.querySelector('#auditOverlay .stat-card--total .stat-card__label').textContent =
                multi ? 'Всего ожидается' : res.category ? 'Всего в словаре' : 'Всего в Excel';
            document.querySelector('#auditOverlay .stat-card--found .stat-card__label').textContent = voice ? 'Услышано' : 'Найдено';
            document.querySelector('#auditOverlay .stat-card--lost .stat-card__label').textContent = voice ? 'Не хватает' : 'Потеряно';
            document.querySelector('#auditOverlay .stat-card--dups .stat-card__label').textContent = voice ? 'Не распознано' : 'Дубликаты';
            let counts = [['auditTotalExcel', res.total_excel], ['auditTotalDisk', res.total_disk],
                          ['auditMissing', res.missing_count], ['auditDups', voice ? unknown.length : res.duplicates_count]];
            counts.forEach(([id, v]) => quiet ? (document.getElementById(id).innerHTML = v) : animateValue(document.getElementById(id), 0, v, 1200));
            if (!quiet) auditOpen = {};

            // по группам
            let by = {};
            groups.forEach(g => by[g.id] = { missing: [], dups: [], unknown: [], files: [] });
            (res.missing || []).forEach((m, i) => { m._i = i; (by[gidOf(m)] || by[gid0]).missing.push(m); });
            (res.duplicates || []).forEach((d, i) => { d._i = i; (by[gidOf(d)] || by[gid0]).dups.push(d); });
            unknown.forEach(u => by[gid0].unknown.push(u));
            (res.files || []).forEach((f, k) => (by[gidOf(f)] || by[gid0]).files.push(k));

            // текст отчёта — тоже по группам
            let rep = `ОТЧЁТ АУДИТА ПРОЕКТА${categoryNote}\nДиректория: ${res.scan_dir}\n`;
            rep += `Всего: ${res.total_excel} | Найдено: ${res.total_disk} | Потеряно: ${res.missing_count} | Дубликаты: ${res.duplicates_count}\n`;
            groups.forEach(g => {
                let b = by[g.id];
                rep += `\n== ${g.section.replace(' · ', ' / ')} / ${g.title}: найдено ${g.found} из ${g.total}` +
                       `${b.missing.length ? `, нет ${b.missing.length}` : ''}${b.dups.length ? `, дубли ${b.dups.length}` : ''}\n`;
                b.missing.forEach(m => rep += `- нет: ${m.filename} (строка ${m.index}: ${m.text})\n`);
                b.dups.forEach(d => rep += `- дубль: ${d.filename} × ${d.count}\n${d.paths.map(p => '    ' + p).join('\n')}\n`);
                b.unknown.forEach(u => rep += `- не распознано: ${u.filename}: «${u.heard}» ~ ${u.guess} (${Math.round(u.score * 100)}%)\n`);
            });
            window.lastAuditReportText = rep;

            // разделы: «Фразы» / «Переменные» (внутри — «Суммы» и отдельные категории)
            let sections = [];
            groups.forEach(g => {
                let [sec, sub] = String(g.section || '').split(' · ');
                let S = sections.find(x => x.title === sec) || (sections.push({ title: sec, subs: [] }), sections[sections.length - 1]);
                let U = S.subs.find(x => x.title === (sub || '')) || (S.subs.push({ title: sub || '', groups: [] }), S.subs[S.subs.length - 1]);
                U.groups.push(g);
            });
            let html = `<div class="audit-toolbar">
                    <input class="audit-files__filter" placeholder="Поиск по названию или тексту" value="${escapeHtml(auditFilter)}" oninput="auditFilter = this.value; auditApplyFilter()">
                    <label class="audit-switch"><input type="checkbox" ${auditOnlyProblems ? 'checked' : ''} onchange="auditOnlyProblems = this.checked; auditApplyFilter()"> Только с проблемами</label>
                    <span class="audit-toolbar__spacer"></span>
                    ${res.mode === 'studio' ? `<button type="button" class="btn-ghost btn-ghost--compact" onclick="auditExportFolders()" title="Скопировать найденные записи в выбранную папку — в структуре, как у суфлёра: Проверенные/…, Фразы_Переменные/…, Значения/<лист>/<категория>/…">Разложить по папкам Студии</button>` : ''}
                    ${res.mode === 'studio' ? `<button type="button" class="btn-ghost btn-ghost--compact btn-ghost--good" onclick="auditFinalFolder()" title="Папка сдачи: «Финал_<дата>» → «Перманентные_<дата>» (все фразы одной папкой) и «Переменные_<дата>» (содержимое «Значения»)">Финальная папка</button>` : ''}
                    ${res.groups && res.missing_count ? `<button type="button" class="btn-ghost btn-ghost--compact audit-act is-rec" onclick="auditToPrompter('all')" title="Открыть суфлёр только с тем, чего не хватает — записывайте как обычно">● Записать все недостающие — ${res.missing_count}</button>` : ''}
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="auditToggleAll(true)">Развернуть все</button>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="auditToggleAll(false)">Свернуть все</button>
                </div>`;
            sections.forEach(S => {
                let n = S.subs.reduce((a, U) => a + U.groups.length, 0);
                let bad = S.subs.reduce((a, U) => a + U.groups.filter(g => g.missing || g.duplicates).length, 0);
                html += `<section class="audit-section"><div class="audit-section__title">${escapeHtml(S.title)}
                    <span class="audit-section__meta">${n} ${plural(n, 'группа', 'группы', 'групп')}${bad ? ` · с проблемами: ${bad}` : ' · всё на месте'}</span></div>`;
                S.subs.forEach(U => {
                    if (U.title) html += `<div class="audit-subsection">${escapeHtml(U.title)}</div>`;
                    U.groups.forEach(g => html += auditGroupHTML(res, g, by[g.id], groups.length === 1));
                });
                html += `</section>`;
            });
            let extra = res.extra || [];
            if (extra.length) {
                rep += `\n== Нет в таблице: ${extra.length}\n` + extra.map(e => `- ${e.folder}/${e.filename}`).join('\n') + '\n';
                window.lastAuditReportText = rep;
                let q = s => escapeHtml(String(s || '').toLowerCase());
                html += `<section class="audit-section"><div class="audit-section__title">Нет в таблице
                    <span class="audit-section__meta">${extra.length} ${plural(extra.length, 'файл', 'файла', 'файлов')} в папках проекта, которых нет в таблице — лишние или переименованные</span></div>
                    <details class="audit-grp has-problems" data-id="_extra" ${'_extra' in auditOpen ? (auditOpen._extra ? 'open' : '') : 'open'} ontoggle="auditOpen[this.dataset.id] = this.open">
                    <summary class="audit-grp__head"><span class="audit-grp__title">Файлы без строки в таблице</span><span></span>
                        <span class="audit-grp__count">${extra.length}</span><span class="audit-grp__pills"><span class="audit-pill is-dups">лишние ${extra.length}</span></span></summary>
                    <div class="audit-grp__body">${extra.map((e, i) => `<div class="audit-line has-acts" data-q="${q(e.folder + ' ' + e.filename)}">
                        <span class="audit-line__name is-dups">${escapeHtml(e.filename)}</span>
                        <span class="audit-line__text audit-line__paths">${escapeHtml(e.folder)}</span>
                        <span class="audit-line__meta"></span>
                        <span class="audit-line__acts"><button type="button" class="audit-file__play" onclick="auditPlayExtra(${i})" title="Послушать">&#9654;</button></span></div>`).join('')}</div>
                    </details></section>`;
            }
            if (res.studio_note) html = `<div class="audit-note">${escapeHtml(res.studio_note)}</div>` + html;
            if (res.scanned && res.scanned.length) {
                let total = res.scanned.reduce((a, d) => a + d.files, 0);
                html = `<div class="audit-scanned">${res.widened ? `<b>Выбрана «${escapeHtml(res.widened.split(/[\\/]/).pop())}» — смотрю весь проект.</b> ` : ''}`
                    + `Просмотрено ${total} ${plural(total, "запись", "записи", "записей")} в рабочих папках: `
                    + res.scanned.map(d => `<span class="audit-scanned__dir">${escapeHtml(d.folder)} <i>${d.files}</i></span>`).join('')
                    + ((res.skipped || []).length ? `<br><span class="tts-dim" title="Корзина, черновики записи, нарезка, кэш и папки вне «Проверенные / Фразы_Переменные / Значения» — не считаются">Не смотрю: </span>`
                        + res.skipped.map(d => `<span class="audit-scanned__dir is-skip">${escapeHtml(d.folder)} <i>${d.files}</i></span>`).join('') : '')
                    + `</div>` + html;
            }
            auditSetDetails(html, quiet);
            document.getElementById('auditExportBtn').style.display = res.can_export ? '' : 'none';
        }
        async function auditExportFolders() {
            let r = await pywebview.api.audit_export_folders();
            if (!r || r.error) { if (r && r.error !== 'cancel') showToast(r.error); return; }
            let lines = [`Скопировано: <b>${r.copied}</b>`];
            if (r.same) lines.push(`уже на своём месте: ${r.same}`);
            if (r.kept) lines.push(`не перезаписаны (там уже есть файл): ${r.kept}`);
            if (r.failed.length) lines.push(`ошибки: ${r.failed.map(escapeHtml).join('<br>')}`);
            let go = await showBeautifulConfirm(`✅ <b>Разложено по папкам Студии</b><br><br>${lines.join('<br>')}<br><br>`
                + `<span style="word-break:break-all">${escapeHtml(r.dest)}</span><br><br>Папки: ${r.folders.map(f => '«' + escapeHtml(f) + '»').join(', ')}`,
                'Открыть папку', 'Закрыть');
            if (go) pywebview.api.audit_open_folder(r.dest);
        }
        async function auditFinalFolder() {
            let res = window.auditRes || {};
            let warn = [];
            if (res.missing_count) warn.push(`не хватает записей: <b>${res.missing_count}</b>`);
            if (res.duplicates_count) warn.push(`дублей: <b>${res.duplicates_count}</b> — возьмётся первый найденный`);
            if (warn.length && !await showBeautifulConfirm(`⚠️ <b>Аудит ещё не чистый</b><br><br>${warn.join('<br>')}<br><br>Всё равно собрать финальную папку из того, что есть?`, 'Собрать', 'Отмена')) return;
            let r = await pywebview.api.audit_final_folder();
            if (!r || r.error) { if (r && r.error !== 'cancel') showToast(r.error); return; }
            let lines = [`«${escapeHtml(r.perm_dir)}»: <b>${r.perm}</b> ${plural(r.perm, 'файл', 'файла', 'файлов')}`,
                         `«${escapeHtml(r.var_dir)}»: <b>${r.var}</b> ${plural(r.var, 'файл', 'файла', 'файлов')}`];
            if (r.missing) lines.push(`<span class="tts-dim">без недостающих: ${r.missing}</span>`);
            if (r.clash.length) lines.push(`одинаковые имена в разных папках (взят первый): ${r.clash.map(escapeHtml).join(', ')}`);
            if (r.failed.length) lines.push(`ошибки: ${r.failed.map(escapeHtml).join('<br>')}`);
            let go = await showBeautifulConfirm(`✅ <b>Финальная папка собрана</b><br><br>${lines.join('<br>')}<br><br>`
                + `<span style="word-break:break-all">${escapeHtml(r.dest)}</span>`, 'Открыть папку', 'Закрыть');
            if (go) pywebview.api.audit_open_folder(r.dest);
        }
        async function auditPlayExtra(i) {
            let e = (window.auditRes.extra || [])[i];
            if (!e) return;
            let r = await pywebview.api.audit_play(e.path);
            if (r && r.error) showToast(r.error);
        }
        function plural(n, one, few, many) {
            let m10 = n % 10, m100 = n % 100;
            return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
        }
        function auditGroupHTML(res, g, b, only) {
            let voice = !!res.by_voice;
            let isVar = String(g.id).startsWith('var_') || (!res.groups && res.category);
            let probs = b.missing.length + b.dups.length + b.unknown.length;
            let open = g.id in auditOpen ? auditOpen[g.id] : (only || probs > 0);
            let pct = g.total ? Math.round(g.found / g.total * 100) : 0;
            let q = s => escapeHtml(String(s || '').toLowerCase());
            let body = '';
            let act = !!(res.groups && g.target);          // можно исправлять прямо здесь
            if (b.missing.length) {
                body += `<div class="audit-block"><div class="audit-block__title is-lost">${voice ? 'Не хватает' : 'Нет записи'} — ${b.missing.length}
                    ${act ? `<span class="audit-block__acts">
                        <button type="button" class="btn-ghost btn-ghost--compact audit-act is-rec" onclick="auditToPrompter('group', '${escapeHtml(g.id)}')" title="Открыть суфлёр только с недостающими этой группы — записывайте как обычно">● Записать ${b.missing.length > 1 ? 'все ' + b.missing.length : ''}</button>
                        <button type="button" class="btn-ghost btn-ghost--compact" onclick="auditOpenFolder('${escapeHtml(g.id)}')" title="${escapeHtml(g.target)}">Открыть папку</button></span>` : ''}</div>`;
                body += isVar || voice
                    ? `<div class="audit-chips">${b.missing.map(m => act
                        ? `<button type="button" class="audit-chip is-act" data-q="${q(m.filename + ' ' + m.text)}" onclick="auditToPrompter('one', ${m._i})" title="Записать в суфлёре: «${escapeHtml(m.text)}» → ${escapeHtml(m.filename)}">● ${escapeHtml(m.text)}</button>`
                        : `<span class="audit-chip" data-q="${q(m.filename + ' ' + m.text)}"${copyAttr(m.text)} title="Строка ${m.index}${voice ? '' : ' · файл ' + escapeHtml(m.filename)} · клик — скопировать текст">${escapeHtml(m.text)}</span>`).join('')}</div>`
                    : b.missing.map(m => `<div class="audit-line${act ? ' has-acts' : ''}" data-q="${q(m.filename + ' ' + (m.phrase || m.text))}">
                            <span class="audit-line__name is-lost"${copyAttr(m.filename)}>${escapeHtml(m.filename)}</span>
                            <span class="audit-line__text"${copyAttr(m.phrase || m.text)}>${escapeHtml(m.phrase || m.text)}</span>
                            <span class="audit-line__meta">стр. ${m.index}</span>
                            ${act ? `<span class="audit-line__acts"><button type="button" class="btn-ghost btn-ghost--compact audit-act is-rec" onclick="auditToPrompter('one', ${m._i})" title="Записать в суфлёре">● Записать</button><button type="button" class="btn-ghost btn-ghost--compact" onclick="auditPutFile(${m._i})" title="Взять готовую запись (wav/mp3…) — сохраню её сюда под этим именем">Файл…</button></span>` : ''}</div>`).join('');
                body += `</div>`;
            }
            if (b.dups.length) {
                body += `<div class="audit-block"><div class="audit-block__title is-dups">Дубли — ${b.dups.length} <span class="audit-block__hint">одно название в нескольких местах этой группы</span></div>`;
                body += b.dups.map(d => `<div class="audit-line audit-line--top" data-q="${q(d.filename + ' ' + d.paths.join(' '))}">
                        <span class="audit-line__name is-dups"${copyAttr(d.filename)}>${escapeHtml(d.filename)}</span>
                        <span class="audit-line__text">${d.paths.map((p, pi) => `<div class="audit-dup">
                            <button type="button" class="audit-file__play audit-dup__play" onclick="auditPlayPath(${d._i}, ${pi}, this)" title="Послушать">&#9654;</button>
                            <span class="audit-line__paths" title="${escapeHtml(p)}">${escapeHtml(auditRel(res, p))}</span>
                            ${res.groups ? `<button type="button" class="btn-ghost btn-ghost--compact" onclick="auditDupKeep(${d._i}, ${pi})" title="Оставить этот файл, остальные копии — в «trash_аудит» (не удаляются насовсем)">Оставить этот</button>` : ''}</div>`).join('')}</span>
                        <span class="audit-line__meta">× ${d.count}</span></div>`).join('');
                body += `</div>`;
            }
            if (b.unknown.length) {
                body += `<div class="audit-block"><div class="audit-block__title is-dups">Не распознано уверенно — ${b.unknown.length} <span class="audit-block__hint">послушайте: возможно, там как раз недостающее</span></div>`;
                body += b.unknown.map(u => `<div class="audit-line" data-q="${q(u.filename + ' ' + u.heard + ' ' + u.guess)}">
                        <span class="audit-line__name is-dups"${copyAttr(u.filename)}>${escapeHtml(u.filename)}</span>
                        <span class="audit-line__text"${copyAttr(u.heard)}>«${escapeHtml(u.heard)}» · похоже на ${escapeHtml(u.guess)}</span>
                        <span class="audit-line__meta">${Math.round(u.score * 100)}%</span></div>`).join('');
                body += `</div>`;
            }
            if (!probs) body += `<div class="audit-ok audit-ok--sm">Всё на месте${g.folder ? ` · папка «${escapeHtml(g.folder.split(/[\\/]/).pop())}»` : ''}</div>`;
            if (b.files.length) {
                let fid = g.id + ':files';
                let fopen = fid in auditOpen ? auditOpen[fid] : (voice || (only && b.files.length <= 30));
                let editable = voice || (!isVar && res.can_edit);
                body += `<details class="audit-sub" data-id="${escapeHtml(fid)}" ${fopen ? 'open' : ''} ontoggle="auditOpen[this.dataset.id] = this.open">
                    <summary>Записи — ${b.files.length}</summary>
                    <div class="tts-dim audit-files__hint">${voice
                        ? '▶ — послушать. Распознано неверно — исправьте текст и нажмите Enter: сверка с таблицей пересчитается, правка запомнится в папке чанков.'
                        : editable ? '▶ — послушать, ✂ — подрезать запись. Текст фразы можно исправить — он запишется в таблицу Excel (перед первой правкой сохраню её копию «… .до_правок»).'
                                   : '▶ — послушать, ✂ — подрезать запись.'}</div>
                    <div class="audit-files">${b.files.map(k => auditFileRow(res, res.files[k], k, editable)).join('')}</div>
                </details>`;
            }
            return `<details class="audit-grp${probs ? ' has-problems' : ''}" data-id="${escapeHtml(g.id)}" ${open ? 'open' : ''} ontoggle="auditOpen[this.dataset.id] = this.open">
                <summary class="audit-grp__head">
                    <span class="audit-grp__title">${escapeHtml(g.title)}</span>
                    <span class="audit-grp__bar" title="${pct}%"><i style="width:${pct}%"></i></span>
                    <span class="audit-grp__count">${g.found} из ${g.total}</span>
                    <span class="audit-grp__pills">${b.missing.length ? `<span class="audit-pill is-lost">нет ${b.missing.length}</span>` : ''}${b.dups.length ? `<span class="audit-pill is-dups">дубли ${b.dups.length}</span>` : ''}${b.unknown.length ? `<span class="audit-pill is-dups">?&nbsp;${b.unknown.length}</span>` : ''}${probs ? '' : '<span class="audit-pill is-ok">✓ всё на месте</span>'}</span>
                </summary>
                <div class="audit-grp__body">${body}</div>
            </details>`;
        }
        // ----- Исправить прямо в аудите: записать недостающее, взять файл, разобрать дубли -----
        function auditApplyRes(r) { if (r && r.res) renderAuditResult(r.res, true); }
        async function auditOpenFolder(gid) {
            let g = (window.auditRes.groups || []).find(x => x.id === gid);
            if (g) pywebview.api.audit_open_folder(g.target);
        }
        async function auditPutFile(mi) {
            let m = window.auditRes.missing[mi];
            if (!m) return;
            let r = await pywebview.api.audit_put_file(m.group, m.filename);
            if (!r || r.error) { if (r && r.error !== 'cancel') showToast(r.error); return; }
            auditApplyRes(r);
            showToast(`Сохранено: ${m.filename}`);
        }
        async function auditPlayPath(di, pi, btn) {
            let d = window.auditRes.duplicates[di];
            if (!d) return;
            let r = await pywebview.api.audit_play(d.paths[pi]);
            if (r && r.error) showToast(r.error);
        }
        async function auditDupKeep(di, pi) {
            let d = window.auditRes.duplicates[di];
            if (!d) return;
            let r = await pywebview.api.audit_dup_keep(d.group, d.filename, d.paths[pi]);
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            auditApplyRes(r);
            showToast(`Оставлен один файл «${d.filename}». Копии (${r.moved}) — в «trash_аудит»`);
        }

        // Записать недостающее — в суфлёре, как обычно: он покажет только то,
        // чего не хватает (фразы и строки сумм), остальное — запись, «Сборка»,
        // ярусы, сохранение — та же механика.
        async function auditToPrompter(scope, key) {
            let r = await pywebview.api.audit_to_prompter(scope, key === undefined ? null : key);
            if (!r || r.error) { showBeautifulAlert('ℹ️ ' + escapeHtml(r && r.error || 'Не получилось')); return; }
            closeAudit();
            openTtsScreen(r.state);
            showToast(`Суфлёр: только недостающие из аудита — ${r.n}` + (r.lost.length ? ` (не нашёл в проекте записи: ${r.lost.length})` : ''), 5000);
        }
        async function ttsFocusClear() {
            let r = await pywebview.api.tts_focus_clear();
            if (!r) return;
            tts = r.state; ttsPromptKey = null; ttsRender(); ttsRenderPrompt(r.prompt || { none: true });
        }
        async function ttsAuditAgain() {
            let r = await pywebview.api.audit_rerun();
            if (!r || r.error) { showToast(r && r.error || 'Не получилось'); return; }
            renderAuditResult(r);
        }

        // путь — от выбранной папки (короче и понятнее)
        function auditRel(res, p) {
            let root = String(res.scan_dir || '').replace(/[\\/]+$/, '');
            return root && p.startsWith(root) ? '…' + p.slice(root.length) : p;
        }
        function auditToggleAll(open) {
            document.querySelectorAll('#auditDetails details').forEach(d => {
                if (d.classList.contains('audit-sub') && open) return;   // записи — раскрываются по одной (их много)
                d.open = open; auditOpen[d.dataset.id] = open;
            });
        }

        // ----- Записи в аудите: послушать и поправить текст -----
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
        function auditFileRow(res, f, k, editable) {
            let voice = !!res.by_voice;
            let btns = `<span class="audit-file__btns"><button type="button" class="audit-file__play" data-k="${k}" onclick="auditPlay(${k})" title="Прослушать (ещё раз — стоп)">&#9654;</button><button type="button" class="audit-file__cut" onclick="auditEdOpen(${k})" title="Править запись: срезать края, вырезать лишнее">&#9986;</button></span>`;
            let badge = voice
                ? (f.match ? `<span class="audit-file__badge is-ok" title="Совпало со значением таблицы">✓ ${escapeHtml(f.match)}</span>`
                           : f.text ? `<span class="audit-file__badge" title="Не совпало ни с одним значением уверенно">? ${escapeHtml(f.guess || '')}</span>`
                                    : '<span class="audit-file__badge">тишина</span>')
                : '';
            let note = voice && f.fixed ? `<div class="audit-file__heard">распознано: «${escapeHtml(f.heard || '—')}» · исправлено вами</div>` : '';
            if (voice && f.phrase) note += `<div class="audit-file__heard">фраза: «${escapeHtml(f.phrase)}»</div>`;
            // по названиям: текст фразы из таблицы (по названию файла) — видно и правится в своей ячейке
            if (!voice && f.phrase) return `<div class="audit-file" data-q="${escapeHtml((f.filename + ' ' + f.phrase).toLowerCase())}">
                ${btns}
                <span class="audit-file__name" title="${escapeHtml(f.path)}">${escapeHtml(f.filename)}</span>
                <textarea class="audit-file__text audit-file__phrase" data-k="${k}" rows="1" title="Текст фразы — исправленный запишется в ту же ячейку таблицы Excel"
                    onkeydown="if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); this.blur(); } if (event.key === 'Escape') { this.value = this.defaultValue; this.blur(); }"
                    oninput="this.style.height = 'auto'; this.style.height = this.scrollHeight + 'px'"
                    onchange="auditPhraseFix(${k}, this.value)">${escapeHtml(f.phrase)}</textarea>
                <span></span>
            </div>`;
            return `<div class="audit-file" data-q="${escapeHtml((f.filename + ' ' + (f.text || '') + ' ' + (f.match || '')).toLowerCase())}">
                ${btns}
                <span class="audit-file__name" title="${escapeHtml(f.path)}">${escapeHtml(f.filename)}</span>
                ${editable
                    ? `<input class="audit-file__text" data-k="${k}" value="${escapeHtml(f.text || '')}" placeholder="${voice ? 'что сказано — впишите' : 'текст фразы'}"
                         onkeydown="if (event.key === 'Enter') this.blur(); if (event.key === 'Escape') { this.value = this.defaultValue; this.blur(); }"
                         onchange="auditFix(${k}, this.value)" title="${voice ? 'Исправьте, если распознано неверно — сверка пересчитается' : 'Исправленный текст запишется в таблицу Excel'}">`
                    : `<span class="audit-file__text is-ro">${escapeHtml(f.text || '')}</span>`}
                ${badge}${note}
            </div>`;
        }
        function auditApplyFilter() {
            let q = auditFilter.trim().toLowerCase();
            document.querySelectorAll('#auditDetails .audit-grp').forEach(g => {
                let hits = 0;
                g.querySelectorAll('[data-q]').forEach(el => {
                    let ok = !q || el.dataset.q.includes(q);
                    el.style.display = ok ? '' : 'none';
                    if (ok) hits++;
                });
                let title = g.querySelector('.audit-grp__title').textContent.toLowerCase();
                let show = (!auditOnlyProblems || g.classList.contains('has-problems')) && (!q || hits || title.includes(q));
                g.style.display = show ? '' : 'none';
                if (q && hits) { g.open = true; let sub = g.querySelector('.audit-sub'); if (sub && sub.querySelector('.audit-file[data-q]:not([style*="none"])')) sub.open = true; }
            });
            document.querySelectorAll('#auditDetails .audit-section').forEach(S =>
                S.style.display = [...S.querySelectorAll('.audit-grp')].some(g => g.style.display !== 'none') ? '' : 'none');
        }
        let auditPlayTimer = null;
        async function auditPlay(k) {
            let f = (window.auditRes.files || [])[k];
            if (!f) return;
            let btns = document.querySelectorAll('.audit-file__play[data-k]');     // только ▶ — ✂ рядом не трогаем
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

