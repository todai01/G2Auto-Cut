"""Ролик для отдельной программы «Прослушка» (GVox-Listen): как пользоваться.

    xvfb-run -a python tools/demo/clips/c_listen_app.py [папка для ролика]

Окно берётся из собранного проекта (tools/make_listen_project.py), синтез — на заглушке сервиса.
Ролик и превью — в папке (по умолчанию tools/demo/_work/listen_app_ролик)."""
import os, sys, subprocess
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('GVOX_SYNTH_URL', 'file://' + os.path.join(HERE, 'mock_synth.html'))
os.environ.setdefault('GVOX_BROWSER', '/opt/pw-browsers/chromium')
sys.path.insert(0, HERE)
import harness
from harness import *
import numpy as np
import openpyxl

OUTDIR = next((os.path.abspath(a) for a in sys.argv[1:] if not a.startswith('-')), os.path.join(VID, 'listen_app_ролик'))
harness.OUT = OUTDIR
harness.ONLY[:] = []
PROJ = os.path.join(VID, 'listen_proj')
subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), 'make_listen_project.py'), PROJ], check=True, stdout=subprocess.DEVNULL)
harness.APP = os.path.join(PROJ, 'frontend', 'listen_app.html')

D = os.path.join(VID, 'Прослушка_приложение'); shutil.rmtree(D, ignore_errors=True)
V = os.path.join(D, 'Записи'); os.makedirs(V)
rng = np.random.default_rng(11)
rows = [['Мария', 'Иванова', 'Петровна'], ['Гизат', 'Ахметов', 'Ерланович'], ['Айгерим', 'Иванова', 'Сергеевна'],
        ['Ерлан', 'Сидоров', 'Петровна'], ['Асель', 'Ахметова', 'Ерлановна'], ['Иван', 'Попов', 'Иванович']]
k = 0
for name in sorted({v for r in rows for v in r}):
    if name == 'Сидоров':
        continue                                              # записи нет — покажем красную ячейку и синтез
    b = np.convolve(rng.standard_normal(int(R * 0.35)), np.ones(8) / 8, 'same')
    b = b / np.abs(b).max() * 0.05 * np.sin(np.pi * np.linspace(0, 1, len(b))) ** 0.7
    k += 1
    write(os.path.join(V, name + '.wav'), np.concatenate([0.002 * rng.standard_normal(int(R * 0.2)), b, speech(name, decl=1) * (0.8, 1.0, 1.25)[k % 3]]))
F = os.path.join(D, 'Фразы_Переменные')
for lang in ('ru', 'kz'):
    os.makedirs(os.path.join(F, lang))
    write(os.path.join(F, lang, 'hello_start.wav'), speech('Здравствуйте, уважаемый клиент, вас приветствует отдел обслуживания', decl=2))
    write(os.path.join(F, lang, 'hello_end.wav'), speech('у вас есть задолженность по кредиту, пожалуйста погасите её', decl=2))
XL = os.path.join(D, 'Таблица.xlsx'); wb = openpyxl.Workbook(); ws = wb.active
ws.append(['<firstname>', '<surname>', '<patronymic>'])
for r in rows:
    ws.append(r)
wb.save(XL)
a = Api()

with Rec('listen_app', a) as r:
    r.top = 'top'
    r.wait(1500)
    r.start()
    r.cap('<b>GVox · Прослушка переменных</b> — проверка записей имён, фамилий и отчеств по таблице', 2600)
    DIALOG.extend([[V], [F], [XL]])
    r.cap('Нажмите <b>«Начать прослушку»</b> (или Enter). Дальше три шага', 600)
    r.click('.entry__start', after=1100)
    r.cap('Шаг 1. Папка с записями — файлы названы как значения («Гизат.wav»)', 1800)
    r.click('#customAlertOk', after=1200)
    r.cap('Шаг 2. Папка с кусочками фраз — «Фразы_Переменные», внутри ru и kz', 1800)
    r.click('#customAlertOk', after=1300)
    r.cap('Отметьте, какой кусок — <b>начало</b> фразы, а какой — <b>конец</b>. ▶ — послушать', 600)
    r.click('.listen-phr__row:has-text("hello_start") button:has-text("Начало")', after=700)
    r.click('.listen-phr__row:has-text("hello_end") button:has-text("Конец")', after=900)
    r.click('#listenPhrOverlay .custom-alert-btn', after=1200)
    r.cap('Шаг 3. Таблица Excel: шапка <b>&lt;firstname&gt;, &lt;surname&gt;, &lt;patronymic&gt;</b> — все столбцы читаются', 2000)
    r.click('#customAlertOk', after=2400)
    r.top = 'mid'
    r.cap('Слева — ваша таблица. Идём <b>слева направо по строкам</b>. Текущая ячейка в рамке, под ней её звук', 3200)
    r.cap('Жёлтая полоска — не проверена, <span style="color:#ff8a80">красная</span> — записи нет. Повтор имени (↺) слушать не нужно', 3400)
    r.cap('<b>Space</b> — слушать в фразе: конец начала, имя и начало конца', 600)
    r.key('Space', 'Space', 3400)
    r.top = 'top'
    r.cap('Запись срезана по голосу: вдох и шум по краям убраны (серым)', 2800)
    r.cap('Всё хорошо — <b>Enter</b>. Ячейка станет <span style="color:#7be3a6">зелёной</span>, запись скопируется в папку «Готовые»', 600)
    r.key('Enter', 'Enter', 2200)
    r.key('Enter', 'Enter', 1800)
    r.cap('Подправить: тяните края, выделите и <b>X</b> — вырезать. <b>A</b> — снова авто', 600)
    bb = r.pg.locator('#listenEdCanvas').bounding_box()
    y = bb['y'] + bb['height'] / 2
    r.drag(bb['x'] + bb['width'] * 0.5, y, bb['x'] + bb['width'] * 0.58, y, 600)
    r.key('X', 'KeyX', 900)
    r.key('Enter', 'Enter', 2000)
    r.cap('Запись плохая — <b>Backspace</b>: <span style="color:#c4a2ff">фиолетовая</span> ячейка, копия — в папку «Исправить»', 600)
    r.key('Backspace', 'Backspace', 2600)
    r.cap('Ошиблись? <b>Ctrl+Z</b> отменяет последнее решение, можно несколько раз подряд', 600)
    r.key('Ctrl+Z', 'Control+z', 2600)
    r.cap('Или кнопка <b>«× из Готовые»</b> / <b>«× из Исправить»</b> у ячейки: запись уйдёт из папки, ячейка снова «не проверена»', 600)
    r.click('#listenList .lg-cell.is-done', after=1200)
    r.move('#listenUnfile button', 700); r.wait(1800)
    r.click('#listenUnfile button', after=1800)
    r.cap('<b>G</b> — автопрогон: имя звучит и само сохраняется. Любая клавиша — пауза', 600)
    r.key('G', 'KeyG', 600)
    for _ in range(80):
        if r.js("!lAuto"): break
        r.wait(250)
    r.wait(600)
    r.cap('Нет записи — <b>R</b>: программа спросит голос и синтезирует', 600)
    r.click('#listenList .lg-cell.is-miss', after=1000)
    r.key('R', 'KeyR', 600)
    for _ in range(40):
        if r.js("!!document.querySelector('.listen-voice')"): break
        r.wait(300)
    r.cap('Выберите голос из списка сервиса — дальше он запоминается (сменить: «голос: … ✎»)', 2600)
    r.click('.listen-voice label:nth-child(3)', after=700)
    r.click('#customAlertOk', after=900)
    for _ in range(60):
        if r.js("lRow() && lRow().synth") != 'busy': break
        r.wait(400)
    r.cap('Синтез встаёт на дорожку и звучит в фразе: подрежьте и <b>Enter</b>', 3000)
    r.cap('Кнопка <b>«Папки»</b> — сколько в «Готовые» и «Исправить», открыть папки с результатом (внутри — по столбцам таблицы)', 600)
    r.click('button:has-text("Папки")', after=2800)
    r.click('#customAlertCancel', after=800)
    r.cap('Готово. Папки «Готовые» и «Исправить» лежат внутри папки с записями', 2600)
    r.cap('')
