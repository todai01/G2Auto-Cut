import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# синтез — на заглушке сервиса (вкладки и поля как у настоящего); браузер синтеза не headless → нужен xvfb-run
os.environ.setdefault('GVOX_SYNTH_URL', 'file://' + os.path.join(HERE, 'mock_synth.html'))
os.environ.setdefault('GVOX_BROWSER', '/opt/pw-browsers/chromium')
sys.path.insert(0, HERE)
from harness import *
import openpyxl
D = os.path.join(VID, 'Прослушка_демо'); shutil.rmtree(D, ignore_errors=True)
V = os.path.join(D, 'Имена'); os.makedirs(V)
import numpy as np
rng = np.random.default_rng(7)
for k, n in enumerate(['Гизат', 'Айгерим', 'Иван', 'Мария', 'Ерлан']):     # перед словом — вдох, громкость разная
    b = np.convolve(rng.standard_normal(int(R * 0.35)), np.ones(8) / 8, 'same')
    b = b / np.abs(b).max() * 0.05 * np.sin(np.pi * np.linspace(0, 1, len(b))) ** 0.7
    sp = speech(n, decl=1) * (0.6, 1.0, 1.4, 0.8, 1.2)[k]
    write(os.path.join(V, n + '.wav'), np.concatenate([0.002 * rng.standard_normal(int(R * 0.2)), b, sp]))
F = os.path.join(D, 'Фразы_Переменные')                 # кусочки фраз, разложены по языкам
for lang in ('ru', 'kz'):
    os.makedirs(os.path.join(F, lang))
    write(os.path.join(F, lang, 'hello_start.wav'), speech('Здравствуйте, уважаемый клиент, вас приветствует отдел обслуживания', decl=2))
    write(os.path.join(F, lang, 'hello_end.wav'), speech('у вас есть задолженность по кредиту, пожалуйста погасите её', decl=2))
    write(os.path.join(F, lang, 'debt_start.wav'), speech('сумма вашего платежа составляет', decl=2))
XL = os.path.join(D, 'Имена.xlsx'); wb = openpyxl.Workbook(); ws = wb.active
ws.append(['№', 'Имя'])
for k, n in enumerate(['Мария', 'Гизат', 'Ерлан', 'Асель', 'Иван', 'Айгерим'], 1): ws.append([k, n])
wb.save(XL)
a = Api()

with Rec('listen', a) as r:
    r.top = 'top'
    r.js("showMenuNow()", 2600); r.js("radial.open && radialHubClick()", 900)
    r.start()
    r.click('#radialHub', after=1000)
    r.click('.radial__item.is-in:not(.is-out)[data-k="1"]', after=1300)
    r.cap('<b>Прослушка</b> — записи переменных по таблице: послушать в фразе, подрезать, синтезировать', 2400)
    DIALOG.extend([[V], [F], [XL]])
    r.click('.radial__item.is-in:not(.is-out):has-text("Прослушка")', after=1200)
    r.cap('Папка с записями — файлы названы как значения («Гизат.wav»)', 1600)
    r.click('#customAlertOk', after=1200)
    r.cap('Папка с кусочками фраз — «Фразы_Переменные», внутри ru и kz', 1800)
    r.click('#customAlertOk', after=1300)
    r.cap('Отметьте, какой кусок — <b>начало</b>, а какой — <b>конец</b>. ▶ — послушать целиком', 600)
    r.click('.listen-phr__row:has-text("hello_start") button:has-text("Начало")', after=700)
    r.click('.listen-phr__row:has-text("hello_end") button:has-text("Конец")', after=900)
    r.cap('Пара своя для каждого языка: переключите на KZ и отметьте так же', 600)
    r.click('#listenPhrLang button:has-text("KZ")', after=700)
    r.click('.listen-phr__row:has-text("hello_start") button:has-text("Начало")', after=600)
    r.click('.listen-phr__row:has-text("hello_end") button:has-text("Конец")', after=900)
    r.click('#listenPhrOverlay .custom-alert-btn', after=1200)
    r.cap('Таблица названий: запись для строки ищется по имени, порядок не важен', 1800)
    r.click('#customAlertOk', after=2200)
    r.top = 'mid'
    r.cap('Крупно — текущая строка. Красным в списке — записи нет', 2400)
    r.cap('<b>RU / KZ</b> — язык всего: пара фраз, записи из ru / kz и синтез', 600)
    r.move('#listenLangTop', 700); r.wait(1600)
    r.cap('<b>Space</b> — слушать в фразе. «кратко» — конец начала и начало конца, для тайминга', 600)
    r.key('Space', 'Space', 3200)
    r.top = 'top'
    r.cap('Запись уже срезана по голосу: вдох и шум по краям убраны (серым). Звучит — уже срезанное', 3000)
    r.cap('<b>Enter</b> — сохранить и сразу к следующей. Первая сохранённая — <b>шаблон срезки</b>', 600)
    r.key('Enter', 'Enter', 2200)
    r.cap('Следующие — по шаблону: та же тишина по краям, громкость и темп', 3000)
    r.cap('Подправить: тяните края, выделите и <b>X</b> — вырезать. <b>A</b> — снова авто', 600)
    bb = r.pg.locator('#listenEdCanvas').bounding_box()
    y = bb['y'] + bb['height'] / 2
    r.drag(bb['x'] + bb['width'] * 0.5, y, bb['x'] + bb['width'] * 0.58, y, 600)
    r.key('X', 'KeyX', 900)
    r.key('A', 'KeyA', 1600)
    r.cap('«Шаблон из этой» — сделать шаблоном эту запись. <b>P</b> — только правка, дБ и темп — кнопками', 600)
    r.move('#listenEdBar button:has-text("Шаблон из этой")', 700); r.wait(1800)
    r.key('Enter', 'Enter', 1800)
    r.cap('Исходники — в «_до_правок»: «Вернуть исходник» вернёт запись как была', 2400)
    r.cap('<b>1 / 2 / 3</b> — править начало, переменную или конец (полностью)', 600)
    r.key('1', 'Digit1', 1600); r.key('2', 'Digit2', 1200)
    r.cap('Нет записи или она неудачная — синтез', 600)
    r.click('#listenList .listen-row.is-miss', after=1200)
    r.cap('Текст можно поправить — и «Синтезировать»', 600)
    r.click('#listenSynth .custom-alert-btn', after=600)
    for _ in range(60):
        if r.js("lRow() && lRow().synth") != 'busy': break
        r.wait(500)
    r.wait(800)
    r.cap('Послушать синтез в фразе и «Взять синтез» — заменит запись', 600)
    r.click('#listenSynth button:has-text("Синтез в фразе")', after=2600)
    r.click('#listenSynth button:has-text("Взять синтез")', after=2200)
    r.cap('')
