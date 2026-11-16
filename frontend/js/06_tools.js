        // === Конвертер MP4 -> MP3/WAV ===
        // ----- Подготовка к клону -----
        let cloneSt = { folder: null, json: null, voices: [] };
        function openClonePrep() {
            document.getElementById('cloneOverlay').style.display = 'flex';
            cloneRefresh();
        }
        function closeClonePrep() { document.getElementById('cloneOverlay').style.display = 'none'; }
        function cloneRefresh() {
            document.getElementById('btnCloneBuild').disabled = !cloneSt.folder;
            document.getElementById('btnCloneCut').disabled = !(cloneSt.json && cloneSt.voices.length);
        }
        const cloneDur = s => s >= 60 ? `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с` : `${s} с`;
        async function clonePickFolder() {
            let r = await pywebview.api.clone_pick_folder();
            if (!r) return;
            cloneSt.folder = r.count ? r.folder : null;
            let langs = r.langs || {}, lk = Object.keys(langs).sort((a, b) => ({ ru: 0, kz: 1 }[a] ?? 2) - ({ ru: 0, kz: 1 }[b] ?? 2));
            document.getElementById('cloneFolderLabel').innerText = r.count
                ? `${r.folder} — файлов: ${r.count}${lk.length > 1 ? ' (' + lk.map(k => `${k.replace('_', ' ')}: ${langs[k]}`).join(', ') + ')' : r.subdirs ? `, подпапок: ${r.subdirs}` : ''}` : `${r.folder} — аудиофайлов нет`;
            if (r.prev) {                                   // уже собирали — тайминги подхватим
                let j = await pywebview.api.clone_load_timings(r.prev.replace(/[\\/][^\\/]*$/, ''));
                if (j && !j.error) cloneSetJson(j, 'прошлая сборка этой папки');
            }
            cloneRefresh();
        }
        function cloneSetJson(j, note) {
            cloneSt.json = j.json;
            document.getElementById('cloneJsonLabel').innerText = `${note ? note + ': ' : ''}` + (j.parts
                ? j.parts.map(p => `${(p.lang || '').replace('_', ' ')} — ${p.count} файлов, ${cloneDur(p.total_s)}`).join(' · ')
                : `${j.count} файлов, ${cloneDur(j.total_s)}`);
            cloneRefresh();
        }
        async function cloneBuild() {
            let btn = document.getElementById('btnCloneBuild'), out = document.getElementById('cloneBuildResult');
            btn.disabled = true; btn.innerText = 'Собираю…'; out.innerHTML = '';
            try {
                let r = await pywebview.api.clone_build(+document.querySelector('input[name="cloneGap"]:checked').value,
                                                        +document.querySelector('input[name="cloneRate"]:checked').value, true);
                if (!r || r.error) { out.innerHTML = `<span class="clone-bad">${escapeHtml(r && r.error || 'Не получилось')}</span>`; return; }
                out.innerHTML = (r.parts ? `Готово по языкам (${r.rate} Гц), тайминги — рядом с каждым:<br>` + r.parts.map(p =>
                        `<b>${escapeHtml(p.wav.split(/[\\/]/).pop())}</b> — ${p.count} файлов · ${cloneDur(p.total_s)}`).join('<br>') + '<br>'
                    : `Готово: <b>${escapeHtml(r.wav)}</b><br>${r.count} файлов · ${cloneDur(r.total_s)} · ${r.rate} Гц · тайминги — «Клон_исходник.json» рядом`) + `
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="pywebview.api.clone_open_folder(${escapeHtml(JSON.stringify(r.wav.replace(/[\\/][^\\/]*$/, '')))})">Открыть папку</button>`
                    + (r.errors && r.errors.length ? `<div class="clone-bad">Не прочитались: ${r.errors.map(escapeHtml).join('; ')}</div>` : '');
                cloneSetJson({ json: r.json, count: r.count, total_s: r.total_s, parts: r.parts }, 'из шага 1');
            } finally { btn.innerText = 'Собрать WAV'; cloneRefresh(); }
        }
        const cloneCatName = l => l ? l.replace('_', ' ') : 'запись';
        async function clonePickTimings() {
            let j = await pywebview.api.clone_pick_timings();
            if (!j) return;
            if (j.error) { showBeautifulAlert('⚠️ ' + escapeHtml(j.error)); return; }
            cloneSetJson(j, '');
        }
        // Сколько голосов — столько папок по очереди; в каждой — клоны цельных записей
        async function clonePickVoices() {
            let n = Math.max(1, Math.min(20, +document.getElementById('cloneVoiceCount').value || 1)), got = [];
            for (let i = 1; i <= n; i++) {
                if (!(await showBeautifulAlert(`<b>Папка голоса ${i} из ${n}</b><br><br>В ней — клоны цельных записей этого голоса: ru, kz, без языка.`))) break;
                let v = await pywebview.api.clone_pick_voice_folder();
                if (!v) break;
                got.push(v);
            }
            if (!got.length) return;
            cloneSt.voices = got;
            document.getElementById('cloneClonesLabel').innerText = `голосов: ${got.length}`;
            document.getElementById('cloneVoices').innerHTML = got.map(v => `<div class="clone-voice"><b>${escapeHtml(v.name)}</b>`
                + (v.files.length ? v.files.map(f => `<span class="clone-voice__f">${escapeHtml(f.name)}${f.cat ? `<i>${escapeHtml(cloneCatName(f.cat))}</i>` : ''}</span>`).join('')
                    : '<span class="clone-bad">аудиофайлов нет</span>') + '</div>').join('');
            cloneRefresh();
        }
        async function cloneCut() {
            let btn = document.getElementById('btnCloneCut'), out = document.getElementById('cloneCutResult');
            btn.disabled = true; btn.innerText = 'Режу…'; out.innerHTML = '';
            try {
                let r = await pywebview.api.clone_cut_voices(cloneSt.voices.map(v => v.folder), document.querySelector('input[name="cloneOutRate"]:checked').value);
                if (!r || r.error) { out.innerHTML = `<span class="clone-bad">${escapeHtml(r && r.error || 'Не получилось')}</span>`; return; }
                out.innerHTML = `Финальная папка: <b>${escapeHtml(r.final)}</b>
                    <button type="button" class="btn-ghost btn-ghost--compact" onclick="pywebview.api.clone_open_folder(${escapeHtml(JSON.stringify(r.final))})">Открыть</button>`
                    + r.report.map(v => `<div class="clone-row"><b>${escapeHtml(v.voice)}</b> — `
                        + v.cats.map(c => `${escapeHtml(cloneCatName(c.lang))}: ${c.files} файлов <span class="tts-dim">(${escapeHtml(c.clone)}, ${c.by === 'name' ? 'по имени' : 'по длительности'}, сдвиг ${c.offset_ms} мс${c.scale !== 1 ? `, растяжение ${((c.scale - 1) * 100).toFixed(2)}%` : ''})</span>`).join(' · ')
                        + ([...v.warnings, ...v.cats.flatMap(c => c.warnings.map(w => cloneCatName(c.lang) + ': ' + w))].length
                            ? `<div class="clone-bad">${[...v.warnings, ...v.cats.flatMap(c => c.warnings.map(w => cloneCatName(c.lang) + ': ' + w))].map(escapeHtml).join('<br>')}</div>` : '')
                        + '</div>').join('');
            } finally { btn.innerText = 'Нарезать в финальную папку'; cloneRefresh(); }
        }

        // ----- Синтез по таблице: Excel → каждое значение готовым голосом, по одному, с паузами -----
        let bsSt = null;
        async function openBsynth() {
            document.getElementById('bsynthOverlay').style.display = 'flex';
            bsynthEvent(await pywebview.api.bsynth_state());
        }
        function closeBsynth() { document.getElementById('bsynthOverlay').style.display = 'none'; }
        async function bsynthPick() {
            let r = await pywebview.api.bsynth_pick_excel();
            if (!r) return;
            if (r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
            bsynthEvent(r);
        }
        const bsDur = s => s >= 3600 ? `${Math.floor(s / 3600)} ч ${Math.round(s % 3600 / 60)} мин` : s >= 60 ? `${Math.floor(s / 60)} мин ${Math.round(s % 60)} с` : `${s} с`;
        function bsynthEvent(s) {
            if (!s) return;
            let first = !bsSt;
            bsSt = s;
            let opt = (sel, list, cur) => {
                let el = document.getElementById(sel);
                if (!el.options.length) el.innerHTML = list.map(o => `<option value="${o.index}">${escapeHtml(o.label)}</option>`).join('');
                if (first) el.value = cur;
            };
            opt('bsynthVoice', s.voices, s.defaults.voice);
            opt('bsynthLang', s.langs, s.defaults.lang);
            if (first) document.getElementById('bsynthDelay').value = s.defaults.delay;
            if (first) try { document.getElementById('bsynthDups').checked = localStorage.getItem('gvox_bsynth_dups') !== '0'; } catch (e) {}
            document.getElementById('bsynthFile').innerText = s.path
                ? `${s.path.split(/[\\/]/).pop()} · лист «${s.sheet}» · строк: ${s.total_rows} · столбцы: ${s.cols.join(', ')}`
                : 'Первая строка — заголовки столбцов: <firstname>, <surname>…';
            document.getElementById('bsynthPreview').innerHTML = s.path && s.preview.length
                ? `<table><tr>${s.cols.map(c => `<th>${escapeHtml(c)}</th>`).join('')}</tr>${s.preview.map(r => `<tr>${r.map(v => `<td>${escapeHtml(v)}</td>`).join('')}</tr>`).join('')}</table>` : '';
            document.getElementById('btnBsynthStart').disabled = !s.path || s.run;
            document.getElementById('btnBsynthStart').style.display = s.run ? 'none' : '';
            document.getElementById('btnBsynthPick').disabled = s.run;
            document.getElementById('bsynthRun').style.display = s.total ? '' : 'none';
            if (!s.total) return;
            let pct = Math.round(100 * s.done / s.total);
            document.getElementById('bsynthBar').style.width = pct + '%';
            document.getElementById('bsynthCount').innerText = `${s.done} из ${s.total} · ${pct}%` + (s.errors ? ` · ошибок ${s.errors}` : '')
                + (s.skipped ? ` · уже были: ${s.skipped}` : '');
            document.getElementById('bsynthEta').innerText = s.run ? (s.pause ? 'на паузе' : s.eta_s != null ? `осталось ~${bsDur(s.eta_s)}` : 'считаю время…')
                : (s.left ? 'остановлено' : 'готово');
            let c = s.current;
            document.getElementById('bsynthNow').innerHTML = c && s.run
                ? `<span class="bsynth-spin"></span> Сейчас: строка ${c.row} · ${escapeHtml(c.col)} · <b>${escapeHtml(c.text || c.value)}</b>${s.voice_name ? ` <span class="tts-dim">— голос ${escapeHtml(s.voice_name)}</span>` : ''}`
                : s.run && !s.pause ? '<span class="tts-dim">Пауза перед следующим запросом — бережём сервис…</span>' : '';
            // по столбцам: строк → файлов; повторы и пустые — почему файлов меньше строк
            let lack = (s.report || []).reduce((n, r) => n + Math.max(0, r.files - r.have), 0);
            document.getElementById('bsynthReport').innerHTML = (s.report || []).map(r => {
                let why = [r.repeat_n ? `повторов ${r.repeat_n} — копии в папке повторов` : '', r.empty ? `пустых ячеек ${r.empty}` : ''].filter(Boolean).join(', ');
                return `<details class="bsynth-col"><summary><b>${escapeHtml(r.col)}</b> — строк ${r.rows} → файлов ${r.files}`
                    + `${why ? ` <span class="tts-dim">(${why})</span>` : ''} · в папке ${r.have}${r.have < r.files ? ` <span class="clone-bad">· не хватает ${r.files - r.have}</span>` : ''}</summary>`
                    + (r.repeats.length ? `<div class="bsynth-reps">Повторы — копией в ${r.dup_dirs.map(d => '«' + escapeHtml(d) + '»').join(', ')}: ${r.repeats.map(x => `<span>${escapeHtml(x.value)} <i>строки ${x.rows.join(', ')}</i></span>`).join('')}</div>` : '<div class="bsynth-reps tts-dim">Повторов нет</div>')
                    + `</details>`;
            }).join('');
            if (!s.run && !s.left && lack) document.getElementById('bsynthEta').innerText = `не хватает файлов: ${lack}`;
            document.getElementById('bsynthMsg').innerText = s.msg || '';
            document.getElementById('bsynthRecent').innerHTML = s.recent.slice().reverse().map(it =>
                `<div class="${it.status === 'error' ? 'clone-bad' : ''}">${it.status === 'error' ? '✕' : '✓'} ${it.row} · ${escapeHtml(it.col)} · ${escapeHtml(it.text || it.value)}${it.status === 'error' ? ' — ' + escapeHtml(it.error) : ''}</div>`).join('');
            let pb = document.getElementById('btnBsynthPause');
            pb.style.display = s.run ? '' : 'none'; pb.innerText = s.pause ? 'Продолжить' : 'Пауза';
            document.getElementById('btnBsynthStop').style.display = s.run ? '' : 'none';
            document.getElementById('btnBsynthRetry').style.display = !s.run && s.errors ? '' : 'none';
        }
        // Сколько строк — спрашиваем перед стартом.
        async function bsynthStart() {
            let s = bsSt;
            if (!s || !s.path) return;
            let n = s.total_rows, cols = s.cols.length;
            document.querySelector('#customAlertOverlay .custom-alert-box').classList.add('custom-alert-box--wide');
            let ok = await showBeautifulConfirm(`<b>Сколько строк синтезировать?</b><br><br>`
                + `В таблице ${n} строк, в строке ${cols} ${cols === 1 ? 'значение' : 'значения'}. Порядок — строка за строкой, слева направо; готовые файлы пропускаются.`
                + `<div class="bsynth-ask"><label>С строки<input type="number" id="bsFrom" min="1" max="${n}" value="1"></label>`
                + `<label>Сколько строк<input type="number" id="bsCount" min="1" max="${n}" value="${n}"></label></div>`, 'Начать', 'Отмена');
            if (!ok) return;
            let from = Math.max(1, Math.min(n, +document.getElementById('bsFrom').value || 1));
            let cnt = Math.max(1, Math.min(n - from + 1, +document.getElementById('bsCount').value || n));
            let r = await pywebview.api.bsynth_start(from, cnt, +document.getElementById('bsynthDelay').value || 4,
                +document.getElementById('bsynthVoice').value, +document.getElementById('bsynthLang').value,
                document.getElementById('bsynthDups').checked);
            if (r && r.error) { showBeautifulAlert('⚠️ ' + escapeHtml(r.error)); return; }
            bsynthEvent(r);
        }
        async function bsynthPause() { bsynthEvent(await pywebview.api.bsynth_pause(!(bsSt && bsSt.pause))); }
        async function bsynthStop() { bsynthEvent(await pywebview.api.bsynth_stop()); }
        async function bsynthRetry() {
            let r = await pywebview.api.bsynth_retry_failed();
            if (r && r.error) { showToast(r.error); return; }
            bsynthEvent(r);
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

