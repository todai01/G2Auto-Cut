import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import numpy as np
VD = os.path.join(VID, 'Переменные_демо'); shutil.rmtree(VD, ignore_errors=True)
TK = os.path.join(VD, 'Суммы_дубли'); os.makedirs(TK)
words = ['один миллион', 'два миллиона', 'три миллиона', 'сто', 'двести', 'триста', 'одна тысяча', 'две тысячи',
         'один тенге', 'два тенге', 'сто тысяч', 'двести тысяч']
for k, w in enumerate(words, 1):
    write(os.path.join(TK, f'{k:04d}.wav'), speech(w, decl=1))

class Aud:
    def __getattr__(self, n): return lambda *x, **k: ''
a = Api(); a.audacity = Aud()
FAKE['get_audacity_windows'] = lambda: []
FAKE['embed_audacity'] = lambda *x: {"ok": False}

def menu_vars(r):
    DIALOG.clear()
    r.js("showMenuNow()", 2600); r.js("radial.open && radialHubClick()", 900)
    r.start()
    r.click('#radialHub', after=1000)
    r.click('.radial__item.is-in:not(.is-out)[data-k="1"]', after=1300)

if want('vars_ready'):
  with Rec('vars_ready', a) as r:
    r.top = 'top'
    menu_vars(r)
    r.cap('<b>Готовая папка с переменными</b> — разложить нарезанные дубли сумм по ярусам', 2200)
    r.click('.radial__item.is-in:not(.is-out):has-text("Готовая папка")', after=1500)
    r.cap('Со словарём — категории определятся сами. Без словаря — только суммы', 2600)
    r.click('#premadeVarTypeOverlay .option-card--alt', after=1500)
    r.cap('Названия файлов: из таблицы Excel или как есть', 2000)
    DIALOG.append([TK])
    r.click('#premadeExcelChoiceOverlay .option-card--alt', after=2800)
    r.cap('Слева — категории ярусов, справа — дубли. Клик по дублю — послушать', 3000)
    r.key('↓', 'ArrowDown', 700)
    r.cap('<b>↑ / ↓</b> — категория, <b>Z</b> — текущий дубль в неё, <b>X</b> — отменить', 600)
    r.key('Z', 'KeyZ', 1100); r.key('Z', 'KeyZ', 1100)
    r.cap('Или перетащите дубль мышью в категорию. <b>Enter</b> — сохранить эталон', 3000)
    r.cap('Все клавиши — кнопка «Подсказки по управлению»', 2400)
    r.cap('')

if want('vars_batch'):
  with Rec('vars_batch', a) as r:
    r.top = 'top'
    menu_vars(r)
    r.cap('<b>Пакетная сборка</b>: суммы по эталону прямо в Audacity', 1800)
    r.move('.radial__item.is-in:not(.is-out):has-text("Пакетная")', 700)
    r.cap('Подготовьте в Audacity клипы сумм с метками; в папке вывода — эталоны start.wav и end.wav', 3400)
    r.move('#radialExtra .row-opt', 700)
    r.cap('<b>Простой экспорт</b> — без start/end и подгонки, просто разложить. <b>По цифрам</b> — сортировка меток', 3600)
    r.click('.radial__item.is-in:not(.is-out):has-text("Пакетная")', after=1500)
    r.cap('Выберите папку вывода — программа разберёт клипы в Audacity и подгонит длительность под эталон', 3400)
    r.click('#customAlertOk', after=1200)
    r.cap('Дальше — экран отбора: <b>Space</b> слушать, <b>Enter</b> сохранить, клавиши как в нарезке', 3000)
    r.cap('')
