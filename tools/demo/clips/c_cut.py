import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import openpyxl
import numpy as np
CD = os.path.join(VID, 'Нарезка'); shutil.rmtree(CD, ignore_errors=True); os.makedirs(CD)
phr = ['Здравствуйте! Вас приветствует служба доставки.', 'Ваш заказ передан курьеру.', 'Курьер приедет сегодня до вечера.',
       'Оплатить можно картой или наличными.', 'Если хотите изменить время, нажмите один.', 'Спасибо, что выбрали нас!']
xl = os.path.join(CD, 'Тексты.xlsx'); wb = openpyxl.Workbook(); ws = wb.active; ws.title = 'Фразы'
for t in phr: ws.append([t])
wb.save(xl)
parts = []
for t in phr:
    for take in range(2):                                  # по два дубля каждой фразы
        parts += [speech(t), np.zeros(int(R * 1.1), np.float32)]
raw = os.path.join(CD, 'Сырая_запись.wav'); write(raw, np.concatenate(parts))

class Aud:
    def __getattr__(self, n): return lambda *x, **k: ''
a = Api(); a.audacity = Aud()
FAKE['get_audacity_windows'] = lambda: []

with Rec('cut_wav', a) as r:
    r.top = 'top'
    r.js("showMenuNow()", 2600); r.js("radial.open && radialHubClick()", 900)
    r.start()
    r.cap('<b>Нарезка длинной записи</b>: сначала тексты из Excel, потом сырой WAV', 1800)
    r.click('#radialHub', after=1000)
    r.click('.radial__item.is-in:not(.is-out)[data-k="0"]', after=1200)
    DIALOG.append([xl])
    r.click('.radial__item.is-in:not(.is-out):has-text("Загрузить текст")', after=1800)
    r.cap('Отметьте колонку с текстом — справа видно, сколько фраз получится', 2600)
    r.click('#excelOverlay button:has-text("Загрузить фразы")', after=1500)
    DIALOG.append([raw])
    r.cap('Теперь <b>«Резать сырой WAV»</b>', 600)
    r.click('.radial__item.is-in:not(.is-out):has-text("Резать")', after=2600)
    r.cap('Программа замерила шум и речь и подобрала паузу так, чтобы кусков было как фраз в таблице', 3200)
    r.move('#tunePresets .preset-chip', 600)
    r.cap('Быстрые варианты паузы — сразу видно, сколько кусков выйдет', 2400)
    r.click('#autoTuneOverlay button:has-text("Нарезать")', after=3500)
    r.cap('Нарезано. Режим: <b>Обычный</b> — по одной фразе', 600)
    r.click('button:has-text("Обычный режим")', after=2500)
    r.cap('Рабочий экран: слева фраза из таблицы, справа дубли. <b>Space</b> — слушать', 3000)
    r.key('D', 'KeyD', 1200)
    r.cap('<b>A / D</b> — дубль, <b>Q / E</b> — фраза, <b>Z</b> — в «Проверенные», <b>C</b> — в «Переменные»', 3200)
    r.key('E', 'KeyE', 1200)
    r.cap('Готовое ложится в «Проверенные» под именем из Excel', 2600)
    r.cap('')
