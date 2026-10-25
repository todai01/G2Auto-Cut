import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import fake_rec
demo_env.make_xlsx()
NEW = os.path.join(VID, 'Новый_проект'); shutil.rmtree(NEW, ignore_errors=True); os.makedirs(NEW)
a = Api()
a._tts_push = lambda p: JSQ.append(f"ttsProgress({json.dumps(json.loads(json.dumps(p, default=str)), ensure_ascii=False)})")
fake_rec.install(a, NEW)

def menu_ready(r):
    r.js("showMenuNow()", 2600)
    r.js("radial.open && radialHubClick()", 900)

if want('studio_new'):
  with Rec('studio_new', a) as r:
    r.top = 'mid'
    menu_ready(r)
    r.start()
    r.cap('<b>Студия записи</b> — запись фраз и переменных по таблице Excel', 1600)
    r.click('#radialHub', after=1200)
    r.click('.radial__item.is-in:not(.is-out)[data-k="0"]', after=1300)
    r.cap('Новый проект → <b>Студия записи</b>', 300)
    r.click('.radial__item.is-in:not(.is-out)[data-k="0"]', after=1500)
    r.cap('Таблица: лист фраз (<b>&lt;phrase&gt;</b>, <b>&lt;name_phrase&gt;</b>, флаги start/end) и листы сумм и дат', 2800)
    DIALOG.append([demo_env.XL])
    r.click('#customAlertOk', after=1800)
    r.cap('Таблица прочитана: обычные фразы и кусочки фраз с переменными', 2600)
    r.cap('<b>Записать с микрофона</b> — суфлёр покажет фразы по очереди. Пока — «Позже», посмотрим экран', 2400)
    r.click('#customAlertCancel', after=1200)
    r.cap('В центре — <b>суфлёр</b>: что читать сейчас и что дальше', 2600)
    r.move('#ttsPromptMeta .tts-pmode', 600); r.cap('Режимы: <b>Фразы</b>, <b>Сумма</b>, <b>Дата</b> — что читаем', 2400)
    r.move('#ttsRail', 700); r.cap('Внизу — <b>лента дублей</b>: каждая записанная фраза — карточка', 2400)
    r.move('.tts-varcard', 700); r.cap('<b>Переменные</b> — сколько кусочков фраз с переменными уже сохранено', 2400)
    r.move('#ttsRecBtn', 800)
    r.cap('Сверху: <b>Таблица</b>, <b>Готовые записи</b>, <b>Записывать (R)</b>, <b>Все фразы (F)</b>', 3000)
    r.cap('')

def studio_ready(r):
    r.js("(async () => { openTtsScreen(await pywebview.api.tts_state()); await ttsLoadPrompt(); })()", 1500)

if not a._tts().get("units"):
    a.tts_load_excel(demo_env.XL)
DIALOG.append([NEW])
with Rec('studio_record', a) as r:
    r.top = 'mid'
    r.js("localStorage.setItem('gvox_tts_autoasm', '0')")
    studio_ready(r)
    r.js("ttsAutoAsmRender()")
    r.start()
    r.cap('<b>Запись.</b> Нажмите <b>R</b> или «Записывать». Первый раз — выберите папку проекта', 2400)
    r.click('#ttsRecBtn', after=1600)
    r.cap('Микрофон включён. <b>Держите Space</b> и читайте фразу с суфлёра — отпустили, фраза записана', 2600)
    fake_rec.read_line(r, a)
    r.wait(1200)
    r.cap('Дубль сразу появился на ленте, суфлёр — на следующей фразе', 2200)
    fake_rec.read_line(r, a)
    r.wait(1000)
    r.cap('Сбились — <b>Backspace</b>, пока держите Space: кусок выбрасывается, читайте заново', 600)
    fake_rec.read_line(r, a, cancel=True)
    r.wait(700)
    fake_rec.read_line(r, a)
    r.wait(1000)
    r.move('#ttsPromptText', 500)
    r.cap('Можно и мышью: зажмите текст суфлёра. <b>↑ / ↓</b> или колесо — листать фразы', 2600)
    r.key('↓', 'ArrowDown', 900); r.key('↑', 'ArrowUp', 900)
    r.move('#ttsAutoAsmBtn', 600)
    r.cap('<b>Проверять сразу</b> — после каждой фразы откроется «Сборка». Выключено — читаете подряд', 2800)
    r.cap('<b>Без распознавания</b> — дубль = фраза на суфлёре. <b>Не ждать</b> — суфлёр идёт дальше сразу', 3000)
    r.cap('Готово — снова <b>R</b>: запись остановится, всё сохранено в папке «Записи»', 1600)
    r.key('R', 'KeyR', 2200)
    r.cap('')

ED_POS = """(() => { let cv = document.getElementById('ttsEdCanvas').getBoundingClientRect(), c = ttsEd.clips[0], L = tlLane(0);
    return {a: cv.left + tlX(c.pos), b: cv.left + tlX(c.pos + tlLen(c)), y: cv.top + L.top + L.h * 0.55, left: cv.left, w: cv.width}; })()"""

if want('studio_assembly'):
  with Rec('studio_assembly', a) as r:
    r.top = 'mid'
    r.js("localStorage.setItem('gvox_tts_autoasm', '0')")
    studio_ready(r)
    r.start()
    r.cap('<b>Сборка</b> — проверить и подрезать дубль. Клик по карточке на ленте', 1800)
    r.click('#ttsRail .tts-take[data-i="1"]', after=1500)
    r.cap('Волна дубля. <b>Space</b> — слушать, клик по волне — играть с этого места', 2600)
    p = r.js(ED_POS)
    r.cap('Края — <b>ручки</b> по бокам: тяните, чтобы убрать лишнее в начале и в конце', 600)
    r.drag(p['a'], p['y'], p['a'] + 40, p['y'], 900)
    p = r.js(ED_POS)
    r.drag(p['b'], p['y'], p['b'] - 50, p['y'], 900)
    r.wait(900)
    p = r.js(ED_POS)
    r.cap('Лишнее в середине: выделите мышью и нажмите <b>X</b> — вырезать', 600)
    x0 = p['a'] + (p['b'] - p['a']) * 0.45
    r.drag(x0, p['y'], x0 + (p['b'] - p['a']) * 0.08, p['y'], 700)
    r.key('X', 'KeyX', 1300)
    r.cap('<b>Ctrl+Z</b> — отменить, «Сбросить» — вернуть как было', 600)
    r.key('Ctrl+Z', 'Control+KeyZ', 1500)
    r.move('#ttsAssembly .tts-asm-row input[type=range], #ttsAssembly input[type=range]', 600)
    r.cap('Громкость и темп — ползунками; «В Audacity» — правка там', 2600)
    r.cap('Всё хорошо — <b>Enter</b>: фраза сохранена в «Проверенные» (или «Фразы_Переменные»)', 600)
    r.key('Enter', 'Enter', 2200)
    r.cap('<b>Del</b> — удалить дубль, <b>F</b> — привязать к другой фразе, <b>Esc</b> — закрыть', 2800)
    r.cap('')
