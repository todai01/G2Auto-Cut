// ===== Обучение: ролики по каждому процессу и утилите =====
// Ролики лежат рядом: tutorial/<id>.webm (+ <id>.jpg — превью). Слева —
// уроки по разделам, справа — ролик, шаги текстом и «Открыть» (переход
// прямо в этот раздел программы). Просмотренные помечаются ✓.
const TUTORIAL = [
    { section: 'Начало', items: [
        { id: 'menu', title: 'Главное меню', sub: 'Круговое меню, разделы, клавиши',
          steps: ['Клик по значку GVox — вокруг раскрываются разделы: Новый проект, Переменные, Утилиты, Недавние.',
                  'Наведите на пункт — внизу описание. Клик по разделу — его пункты в том же кольце.',
                  'Клавиши: 1–9 — пункт по номеру, Esc — назад / свернуть.',
                  '«Обучение» в правом нижнем углу или F1 на любом экране — ролики по каждому процессу.'],
          open: () => showMenu() },
    ] },
    { section: 'Студия записи', items: [
        { id: 'studio_new', title: 'Новый проект и таблица', sub: 'С чего начать запись',
          steps: ['Новый проект → Студия записи → «Выбрать таблицу».',
                  'Таблица: лист фраз с колонками <phrase>, <name_phrase>, флаги <start>/<start_2>/<end>, отдельные листы сумм и дат.',
                  '«Продолжить работу» — выбрать папку прежнего проекта: подтянутся дубли и место, где остановились.',
                  'Экран: в центре суфлёр, вверху режимы Фразы / Сумма / Дата, внизу лента дублей и счётчик «Переменные».'],
          open: () => openTts() },
        { id: 'studio_record', title: 'Запись с суфлёром', sub: 'R, Space, Backspace',
          steps: ['R или «Записывать» — включить микрофон. Первый раз программа спросит папку проекта.',
                  'Держите Space (или зажмите текст суфлёра мышью) и читайте фразу; отпустили — фраза записана.',
                  'Сбились — Backspace, пока держите Space: кусок выбрасывается.',
                  '↑ / ↓ или колесо мыши — листать фразы.',
                  '«Проверять сразу» — после каждой фразы открывается «Сборка»; выключено — читаете подряд.',
                  '«Без распознавания» — дубль = фраза на суфлёре; «Не ждать» — суфлёр сразу идёт дальше.',
                  'Снова R — стоп. Сырая запись лежит в папке «Записи».'],
          open: () => openTts() },
        { id: 'studio_assembly', title: 'Сборка: проверить и подрезать', sub: 'Края, вырез, Enter',
          steps: ['Клик по карточке на ленте — «Сборка» этого дубля.',
                  'Space — слушать; клик по волне — играть с этого места.',
                  'Ручки по краям — убрать лишнее в начале и конце. Выделите кусок и X — вырезать.',
                  'Ctrl+Z — отменить, «Сбросить» — как было. Громкость и темп — ползунками.',
                  'Enter — сохранить: фраза ложится в «Проверенные» (кусочки фраз с переменными — в «Фразы_Переменные»).',
                  'Del — удалить дубль, F — привязать к другой фразе, Esc — закрыть.'],
          open: () => openTts() },
        { id: 'studio_sums', title: 'Суммы и даты: поток и срезка', sub: 'Ярусы, логики, шаблон',
          steps: ['Режим «Сумма» — строки читаются целиком: «один миллион | сто | одна тысяча | один тенге».',
                  'Логика 1 — миллионы + сотни + тысячи + тенге. Логика 2 — только «сотни тысяч» (100–900), 9 строк.',
                  '«Поток» — читаете строки подряд, «Сборка» не открывается. После R появится «Начать срезку».',
                  'Срезка: каждая строка по очереди в «Сборке» → поправьте границы ярусов → Enter сохраняет и открывает следующую.',
                  '«▶ Стык» — конец начала фразы + сумма + продолжение; «▶ Начало» — последние 2,5 с начала фразы.',
                  'Первая сохранённая строка — шаблон: дальше границы ставятся по нему. «↻ перезаписать все» — пройти все строки заново.'],
          open: () => openTts() },
        { id: 'studio_ready', title: 'Готовые записи на ленте', sub: 'Импорт и правка фраз с переменными',
          steps: ['«Готовые записи» — выберите папку с уже записанным: файлы разложатся по местам проекта.',
                  'Фразы с переменными попадают на ленту с пометкой «готовый» — их можно править.',
                  'В «Сборке» строки суммы ✎ у «Начало» / «Конец» — открыть саму фразу и подрезать.',
                  'Enter или Esc — вернуться к строке, откуда пришли.'],
          open: () => openTts() },
    ] },
    { section: 'Проверка и сдача', items: [
        { id: 'audit', title: 'Аудит проекта', sub: 'Чего не хватает, дубли, запись',
          steps: ['Утилиты → Аудит проекта → таблица Студии и папка проекта.',
                  'Смотрит только «Проверенные», «Фразы_Переменные» и «Значения»; корзина и черновики не считаются.',
                  'Группы: фразы, фразы с переменными, суммы и даты по категориям. Красное — нет, жёлтое — дубли.',
                  '«● Записать все недостающие» — суфлёр покажет только их.',
                  '«Файл…» — взять готовый файл в нужную папку под нужным именем.'],
          open: () => runProjectAudit() },
        { id: 'audit_final', title: 'Финальная папка', sub: 'Перманентные и Переменные',
          steps: ['После аудита — «Финальная папка» и выберите, куда сложить.',
                  'Получится «Финал_<дата>»: «Перманентные_<дата>» — все фразы одной папкой, «Переменные_<дата>» — содержимое «Значения».',
                  'Месяцы называются коротко: jan_kz, jan_ru…',
                  'Если чего-то не хватает — программа предупредит до сборки.'],
          open: () => runProjectAudit() },
    ] },
    { section: 'Переменные', items: [
        { id: 'constructor', title: 'Конструктор', sub: 'Сверить стык с боевыми записями',
          steps: ['Переменные → Конструктор → папка «Значения» или папка проекта.',
                  'Сверху — листы: Сумма KZ / RU, Дата KZ / RU. Рулетки — значения каждого яруса.',
                  '◀ ▶ — фраза, где стоит эта переменная: start → значение → end.',
                  '«кратко» — только 2,5 с конца начала и начала продолжения.',
                  'Space — слушать. A / D — рулетка, W / S — листать. «Обновить» — в Audacity, «Сохранить» — обратно в файл.'],
          open: () => startConstructor() },
        { id: 'vars_ready', title: 'Готовая папка с переменными', sub: 'Разложить дубли сумм по ярусам',
          steps: ['Переменные → Готовая папка. Со словарём категории определятся сами; без словаря — только суммы.',
                  'Названия файлов — из таблицы Excel или как есть. Затем папка с нарезанными дублями.',
                  'Слева категории ярусов, справа дубли. Клик по дублю — послушать.',
                  '↑ / ↓ — категория, Z — текущий дубль в неё, X — отменить; или перетащите дубль мышью.',
                  'Enter — сохранить эталон. Все клавиши — «Подсказки по управлению».'],
          open: () => showPremadeVarTypeChoice() },
        { id: 'listen', title: 'Прослушка переменных', sub: 'Послушать в фразе, подрезать, синтез',
          steps: ['Переменные → Прослушка: папка с записями (например, «Гизат.wav»), начальная и конечная фраза, таблица названий.',
                  'Запись для строки ищется по имени, порядок в таблице не важен. Красным — записи нет.',
                  'Space — слушать в фразе: «кратко» — 2,5 с конца начала и начала конца; P — только правка. ↑ / ↓ — строки.',
                  'Правка: края мышью, выделить и X — вырезать, дБ и темп; Ctrl+S — сохранить, исходник — в «_до_правок». 1 / 2 / 3 — править начало, переменную или конец.',
                  'Синтез: RU / KZ, текст — и «Синтезировать». Послушать в фразе и «Взять синтез» — заменит запись.'],
          open: () => listenStart() },
        { id: 'vars_batch', title: 'Пакетная сборка', sub: 'Суммы по эталону в Audacity',
          steps: ['Нужна Audacity: клипы сумм с метками уже на дорожке, в папке вывода — эталоны start.wav и end.wav.',
                  'Переменные → Пакетная сборка → папка вывода: программа разберёт клипы и подгонит длительность под эталон.',
                  '«Простой экспорт» — без start/end и подгонки, просто разложить. «По цифрам» — сортировка меток по числам.',
                  'Дальше — экран отбора: Space — слушать, Enter — сохранить.'],
          open: () => { let b = document.querySelector('.menu-grid .menu-row--var'); if (b) b.click(); } },
    ] },
    { section: 'Нарезка записи', items: [
        { id: 'cut_wav', title: 'Резать сырой WAV', sub: 'Текст из Excel + длинная запись',
          steps: ['Новый проект → «Загрузить текст»: отметьте колонку с текстом — видно, сколько фраз получится.',
                  '«Резать сырой WAV» — программа замерит шум и речь и подберёт паузу, чтобы кусков было как фраз в таблице.',
                  'Быстрые варианты паузы показывают, сколько кусков выйдет. «Нарезать» → «Обычный режим».',
                  'Отбор: Space — слушать, Q / E — фраза, A / D — дубль, Z — в «Проверенные», C — в «Переменные».',
                  '«Открыть готовые чанки» — продолжить с уже нарезанной папкой.'],
          open: () => { let b = document.querySelector('.menu-grid #btnLoadExcel'); if (b) b.click(); } },
    ] },
    { section: 'Утилиты', items: [
        { id: 'rename_match', title: 'Названия по Excel', sub: 'Разложить файлы по ru / kz',
          steps: ['Утилиты → Названия по Excel → таблица и папка с файлами.',
                  'Короткие имена файлов ищутся в таблице, файлы раскладываются по языкам.'],
          open: () => openRenameMatch() },
        { id: 'pptx', title: 'Таблица → PowerPoint', sub: 'Строка = слайд',
          steps: ['Утилиты → Таблица → PowerPoint → выберите Excel.',
                  'Каждая строка — отдельный слайд, колонки — с паузами между ними. Удобно читать с экрана.'],
          open: () => openTablePptx() },
        { id: 'converter', title: 'Конвертер MP4', sub: 'В MP3 или WAV',
          steps: ['Утилиты → Конвертер MP4 → файлы.', 'Формат MP3 или WAV и частота — кнопками, затем «Конвертировать».'],
          open: () => openConverter() },
        { id: 'clone', title: 'Подготовка к клону', sub: 'Один WAV → обратно на файлы',
          steps: ['Утилиты → Подготовка к клону → «Папка с аудио»: все файлы склеятся в один WAV с паузами.',
                  'Этот WAV — в сервис клонирования голоса.',
                  '«Файлы клонов…» → «Нарезать»: готовые клоны режутся обратно на файлы с теми же именами.'],
          open: () => openClonePrep() },
        { id: 'strip', title: 'Очистить названия', sub: 'Оставить только цифры',
          steps: ['Утилиты → Очистить названия → папка.',
                  'Из имён файлов убираются слова «миллион», «тысяч» и т.п. — остаются цифры.'],
          open: () => stripFilenames() },
    ] },
];

const TUT_SEEN_KEY = 'gvox_tut_seen';
let tutCur = null;
const tutAll = () => TUTORIAL.flatMap(s => s.items.map(it => ({ ...it, section: s.section })));
function tutSeen() { try { return JSON.parse(localStorage.getItem(TUT_SEEN_KEY) || '[]'); } catch (e) { return []; } }
function tutMarkSeen(id) {
    let s = tutSeen();
    if (s.includes(id)) return;
    s.push(id);
    try { localStorage.setItem(TUT_SEEN_KEY, JSON.stringify(s)); } catch (e) {}
}

function openTutorial(id) {
    let ov = document.getElementById('tutorialOverlay');
    if (!ov) return;
    ov.style.display = 'flex';
    tutRenderList();
    tutShow(id || tutCur || (tutAll().find(t => !tutSeen().includes(t.id)) || tutAll()[0]).id);
}
function closeTutorial() {
    let ov = document.getElementById('tutorialOverlay');
    if (!ov) return;
    let v = document.getElementById('tutVideo');
    if (v) v.pause();
    ov.style.display = 'none';
}

function tutRenderList() {
    let seen = tutSeen(), all = tutAll();
    document.getElementById('tutProgress').innerText = `Просмотрено ${all.filter(t => seen.includes(t.id)).length} из ${all.length}`;
    document.getElementById('tutList').innerHTML = TUTORIAL.map(s => `
        <div class="tut-sec">${escapeHtml(s.section)}</div>
        ${s.items.map(t => `<button type="button" class="tut-item ${t.id === tutCur ? 'is-on' : ''} ${seen.includes(t.id) ? 'is-seen' : ''}" data-id="${t.id}" onclick="tutShow('${t.id}')">
            <span class="tut-item__thumb" style="background-image:url('tutorial/${t.id}.jpg')"></span>
            <span class="tut-item__text"><b>${escapeHtml(t.title)}</b><span>${escapeHtml(t.sub)}</span></span>
            <span class="tut-item__check">${seen.includes(t.id) ? '✓' : ''}</span></button>`).join('')}`).join('');
}

function tutShow(id) {
    let all = tutAll(), k = all.findIndex(t => t.id === id);
    if (k < 0) return;
    let t = all[k];
    tutCur = id;
    document.getElementById('tutSection').innerText = t.section;
    document.getElementById('tutTitle').innerText = t.title;
    document.getElementById('tutSteps').innerHTML = t.steps.map(s => `<li>${escapeHtml(s)}</li>`).join('');
    let v = document.getElementById('tutVideo');
    v.poster = `tutorial/${t.id}.jpg`;
    v.src = `tutorial/${t.id}.webm`;
    v.load();
    let p = v.play();
    if (p && p.catch) p.catch(() => {});
    document.getElementById('tutOpenBtn').innerHTML = `Открыть «${escapeHtml(t.title)}»`;
    document.getElementById('tutPrev').disabled = k === 0;
    document.getElementById('tutNext').disabled = k === all.length - 1;
    document.getElementById('tutNext').innerHTML = k < all.length - 1 ? `${escapeHtml(all[k + 1].title)} &rarr;` : 'Последний урок';
    document.querySelectorAll('#tutList .tut-item').forEach(b => b.classList.toggle('is-on', b.dataset.id === id));
    let on = document.querySelector('#tutList .tut-item.is-on');
    if (on) on.scrollIntoView({ block: 'nearest' });
}
// «?» в Студии — урок под то, что сейчас на экране
function ttsTutTopic() {
    let stage = document.getElementById('stage4-tts');
    if (stage && stage.classList.contains('show-assembly')) {
        let t = typeof ttsCurTake === 'function' ? ttsCurTake() : null;
        return t && t.unit !== null && tts.units[t.unit] && tts.units[t.unit].tiers ? 'studio_sums' : 'studio_assembly';
    }
    if (typeof tts !== 'undefined' && tts && (tts.prompt_mode || 'phrases') !== 'phrases') return 'studio_sums';
    if (typeof tts !== 'undefined' && tts && !tts.loaded) return 'studio_new';
    return 'studio_record';
}

function tutStep(d) {
    let all = tutAll(), k = all.findIndex(t => t.id === tutCur);
    if (all[k + d]) tutShow(all[k + d].id);
}
function tutOpen() {
    let t = tutAll().find(x => x.id === tutCur);
    closeTutorial();
    if (t && t.open) t.open();
}
function tutVideoEnded() {
    tutMarkSeen(tutCur);
    tutRenderList();
}
function tutKey(e) {
    let ov = document.getElementById('tutorialOverlay');
    if (!ov || ov.style.display !== 'flex') return false;
    let v = document.getElementById('tutVideo');
    if (e.code === 'Escape') closeTutorial();
    else if (e.code === 'ArrowRight' || e.code === 'PageDown') tutStep(1);
    else if (e.code === 'ArrowLeft' || e.code === 'PageUp') tutStep(-1);
    else if (e.code === 'Space') { if (v.paused) v.play(); else v.pause(); }
    else if (e.code === 'Enter') tutOpen();
    else return true;                                   // остальное окно глотает, но ничего не делает
    e.preventDefault();
    return true;
}
// F1 — обучение по тому экрану, где вы сейчас
function tutContextTopic() {
    let shown = id => { let el = document.getElementById(id); return el && el.style.display !== 'none' && el.offsetParent !== null; };
    let ov = id => { let el = document.getElementById(id); return el && el.style.display === 'flex'; };
    if (ov('auditOverlay')) return 'audit';
    if (ov('cloneOverlay')) return 'clone';
    if (ov('converterOverlay')) return 'converter';
    if (ov('renameMatchOverlay')) return 'rename_match';
    if (ov('tablePptxOverlay')) return 'pptx';
    if (shown('stage4-tts')) return ttsTutTopic();
    if (shown('stage3-constructor')) return 'constructor';
    if (shown('stage5-listen')) return 'listen';
    if (shown('stage2-workspace')) return 'cut_wav';
    return null;
}
document.addEventListener('keydown', e => {
    if (e.code === 'F1') { e.preventDefault(); e.stopImmediatePropagation(); openTutorial(tutContextTopic()); return; }
    if (tutKey(e)) e.stopImmediatePropagation();
}, true);
