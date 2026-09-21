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
        }

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

        // Запоминаем, что рабочий экран уже открывался: тогда из меню
        // можно вернуться к работе одной кнопкой, ничего не загружая заново.
        let workspaceReady = false;

        function showSplash() {
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
            try { items = await pywebview.api.get_recent_projects(); } catch (e) { items = []; }
            recentProjectsCache = items || [];

            if (!recentProjectsCache.length) {
                panel.style.display = 'none';
                return;
            }

            list.innerHTML = recentProjectsCache.map((it, idx) => `
                <button class="recent-project" onclick="openRecentProject(${idx})">
                    <span class="recent-project__name">${escapeHtml(it.name)}</span>
                    <span class="recent-project__time">${formatRecentTime(it.updated_at)}</span>
                </button>
            `).join('');
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
            let items = [];
            try { items = await pywebview.api.get_recent_projects(); } catch (e) { items = []; }
            recentProjectsCache = items || [];

            if (recentProjectsCache.length) {
                document.getElementById('resumeProjectName').innerText = recentProjectsCache[0].name;
                document.getElementById('resumeProjectOverlay').style.display = 'flex';
            } else {
                showMenu();
            }
        }

        async function confirmResumeProject() {
            document.getElementById('resumeProjectOverlay').style.display = 'none';
            await openRecentProject(0);
        }

        function declineResumeProject() {
            document.getElementById('resumeProjectOverlay').style.display = 'none';
            showMenu();
        }

        function showMenu() {
            detachEmbeddedAudacity();
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

            if (!strip || !strip.items || !strip.items.length) {
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

            if (!picked || picked.error === 'cancel') return;
            if (picked.error) { excelError(picked.error); return; }

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

            closeExcelPicker();
            updateUI(state);

            let rep = state.load_report;
            if (rep) {
                showToast(rep.skipped
                    ? `Загружено ${rep.loaded} фраз, повторов пропущено: ${rep.skipped}`
                    : `Загружено ${rep.loaded} фраз`);
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
        async function initVarBatchPremade() {
            // Пропускаем выбор окна проекта, так как данные берутся с диска
            // и Python сам создаст новый проект для конвейера.
            continueInitVarBatchPremade(null);
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

        async function startBatchNormalization() {
            if (isProcessing) return; isProcessing = true;

            updateProgress(0, 'Выбор папки и загрузка в Audacity...');
            document.getElementById('progressContainer').style.display = 'block';

            let res = await pywebview.api.prepare_batch_normalization();
            document.getElementById('progressContainer').style.display = 'none';
            isProcessing = false;

            if (res && res.error === "cancel") return;
            if (!res || res.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${res?.error || 'Неизвестная ошибка'}`);
                return;
            }

            // Ждем, пока пользователь настроит звук и нажмет ОК в нашем красивом алерте
            let confirmed = await showBeautifulAlert(`🎚️ <b>Эталон загружен в Audacity</b><br><br>Файл: <b style="color: var(--blue);">${res.filename}</b><br><br>1. Настройте идеальную громкость этого файла в Audacity (Эффекты -> Нормализация или Усиление).<br>2. Вернитесь сюда и нажмите ОК, чтобы применить эту громкость ко всем <b>${res.total}</b> файлам в папке.`);
            if (!confirmed) return;

            // Пользователь нажал ОК, запускаем процесс!
            isProcessing = true;
            updateProgress(0, 'Чтение эталона и обработка файлов...');
            document.getElementById('progressContainer').style.display = 'block';

            let applyRes = await pywebview.api.apply_batch_normalization();
            document.getElementById('progressContainer').style.display = 'none';
            isProcessing = false;

            if (applyRes && applyRes.error) {
                showBeautifulAlert(`❌ <b>Ошибка нормализации</b><br><br>${applyRes.error}`);
            } else {
                showBeautifulAlert('✅ <b>Успешно!</b><br><br>Все файлы в папке выровнены по громкости эталона.');
            }
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

            let mergePanel = document.querySelector('.merge-panel');
            if (mergePanel && sumModeActive) mergePanel.style.display = 'none';

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

        // Панель режима «Суммы»: счётчики по ярусам и подсказка, в какую
        // папку уйдёт текущая строка (ярус программа определяет сама).
        let lastSumState = null;
        function renderSumPanel(sumState) {
            if (!sumState) return;
            lastSumState = sumState;
            let counts = document.getElementById('sumCounts');
            if (counts && sumState.counts) {
                counts.innerHTML = Object.entries(sumState.counts)
                    .map(([label, count]) => `<span>${escapeHtml(label)}: <b>${count}</b></span>`)
                    .join('');
            }
            let target = document.getElementById('sumTarget');
            if (!target) return;
            target.innerHTML = sumState.detected_tier
                ? `«${escapeHtml(sumState.detected_from || '')}» → папка <b>${escapeHtml(sumState.detected_dir)}</b>`
                : 'Загрузите Excel — по его тексту выбирается папка';
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

        async function saveSumLeftover() {
            let state = await pywebview.api.save_sum_leftover();
            if (state && state.error) {
                showBeautifulAlert(`❌ <b>Ошибка</b><br><br>${state.error}`);
                return;
            }
            updateUI(state);
        }

        // Обратный случай «Сохранить остаток»: автонарезка иногда режет
        // одно число на два куска (например «55 тыс.» → «50» + «5 тыс.»).
        // Склеивает текущий дубль со следующим по списку в один файл.
        async function sumMergeWithNext() {
            let state = await pywebview.api.sum_merge_with_next();
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
                    if (btn) btn.innerText = 'Встроить окно Audacity сюда';
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
                if (phraseEl.classList.contains('is-playing') && phraseEl.dataset.playSource) {
                    badge.className = 'play-source-badge is-visible src-' + phraseEl.dataset.playSource;
                    badge.innerHTML = playSourceLabel(phraseEl.dataset.playSource);
                } else {
                    badge.className = 'play-source-badge';
                    badge.innerHTML = '';
                }
            };
            new MutationObserver(sync).observe(phraseEl, { attributes: true, attributeFilter: ['class'] });
        });

        async function detachEmbeddedAudacity() {
            if (!audacityEmbedded) return;
            window.removeEventListener('resize', onEmbedWindowResize);
            stopEmbedWatchdog();
            audacityEmbedded = false;
            modalOpenForAudacity = false;
            const area = document.getElementById(embedAreaId);
            const btn = document.getElementById(embedBtnId);
            // В режиме «Суммы» рамка остаётся на экране: место под окно
            // Audacity закреплено за ней, даже когда окно отсоединено.
            if (area) area.style.display = sumModeActive ? 'block' : 'none';
            if (btn) btn.innerText = 'Встроить окно Audacity сюда';
            try {
                await pywebview.api.unembed_audacity();
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
                if(mergePanel) mergePanel.style.display = 'block';
                let addSil = document.getElementById('addSilence');
                if(addSil && addSil.parentElement) addSil.parentElement.style.display = 'flex';
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

            if (document.activeElement && document.activeElement.tagName === 'BUTTON') document.activeElement.blur();

            if (e.repeat && !['KeyQ', 'KeyE', 'KeyA', 'KeyD'].includes(e.code)) return;

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
                else if (e.code === 'KeyZ') { e.preventDefault(); if (sumModeActive) sumManualSave(); else saveVarBatch(false); }
                else if (e.code === 'KeyW') { e.preventDefault(); toggleChecked(); }
                else if (e.code === 'KeyR') { e.preventDefault(); loadCheckedToAudacity(); }
                else if (e.code === 'KeyC') { e.preventDefault(); if (sumModeActive) sumSendToAudacity(); else sendToAudacity(); }
                else if (e.code === 'KeyM' && sumModeActive) { e.preventDefault(); sumMergeWithNext(); }
                return;
            }

            // === СТАНДАРТНАЯ ЛОГИКА ДЛЯ ОСТАЛЬНЫХ РЕЖИМОВ ===
            if (e.code === 'Space') { e.preventDefault(); playAudio(true); }
            else if (e.code === 'KeyQ') { e.preventDefault(); navPhrase(-1); }
            else if (e.code === 'KeyE') { e.preventDefault(); navPhrase(1); }
            else if (e.code === 'KeyA') { e.preventDefault(); navChunk(-1); }
            else if (e.code === 'KeyD') { e.preventDefault(); navChunk(1); }
            else if (e.code === 'KeyZ') { e.preventDefault(); if (sumModeActive) sumManualSave(); else processAction('good'); }
            else if (e.code === 'KeyC') { e.preventDefault(); if (sumModeActive) sumSendToAudacity(); else processAction('variable'); }
            else if (e.code === 'KeyM' && sumModeActive) { e.preventDefault(); sumMergeWithNext(); }
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

        function showToast(msg) {
            let { icon, text } = extractLeadingIcon(msg);
            let toast = document.createElement('div');
            toast.className = 'toast';
            toast.innerHTML = `${iconHTML(icon)}<span>${escapeHtml(text)}</span>`;
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 2200);
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
                    result.unmatched.map(escapeHtml).join('<br>') + `</div>`);
            }
            if (result.ambiguous_count) {
                parts.push(`<div style="margin-top:10px">${iconHTML('alert-triangle')} Неоднозначно, оставлено как есть (${result.ambiguous_count}):<br>` +
                    result.ambiguous.map(a => `${escapeHtml(a.file)} — ${escapeHtml(a.reason)}`).join('<br>') + `</div>`);
            }

            let box = document.getElementById('renameMatchResult');
            box.innerHTML = parts.join('');
            box.style.display = 'block';
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

        async function runProjectAudit() {
            if (isProcessing) return; isProcessing = true;

            // Вызываем Python-сканер (откроется окно выбора папки)
            let res = await pywebview.api.audit_project_files();
            isProcessing = false;

            if (res && res.error === "cancel") return; // Юзер закрыл окно выбора
            if (!res || res.error) {
                alert(res?.error || "Сначала загрузите Excel-файл с текстом!");
                return;
            }

            // Показываем красивое модальное окно
            document.getElementById('auditOverlay').style.display = 'flex';
            document.getElementById('auditPath').innerHTML = iconHTML('folder') + " Директория сканирования: " + escapeHtml(res.scan_dir);

            // Запускаем анимацию счетчиков (на 1200 миллисекунд)
            animateValue(document.getElementById('auditTotalExcel'), 0, res.total_excel, 1200);
            animateValue(document.getElementById('auditTotalDisk'), 0, res.total_disk, 1200);
            animateValue(document.getElementById('auditMissing'), 0, res.missing_count, 1200);
            animateValue(document.getElementById('auditDups'), 0, res.duplicates_count, 1200);

            // Генерируем детальные списки и чистый текст для копирования
            let detailsHtml = '';
            window.lastAuditReportText = `ОТЧЁТ АУДИТА ПРОЕКТА\nДиректория: ${res.scan_dir}\n`;
            window.lastAuditReportText += `Excel база: ${res.total_excel} | Найдено: ${res.total_disk} | Потеряно: ${res.missing_count} | Дубликаты: ${res.duplicates_count}\n\n`;

            // Блок отсутствующих файлов
            if (res.missing_count > 0) {
                detailsHtml += `<h4 class="audit-group-title audit-group-title--lost">Отсутствуют — ${res.missing_count}</h4>`;
                window.lastAuditReportText += `ОТСУТСТВУЮТ (${res.missing_count}):\n`;

                res.missing.forEach(m => {
                    detailsHtml += `
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
