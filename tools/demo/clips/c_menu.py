import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import harness, time as _t
a = Api()
harness.RECENT[:] = [{"name": "Доставка_IVR", "path": "D:/Проекты/Доставка_IVR", "updated_at": _t.time() - 3600},
                     {"name": "Напоминания_KZ", "path": "D:/Проекты/Напоминания_KZ", "updated_at": _t.time() - 86400}]
with Rec('menu', a) as r:
    r.top = True
    r.js("showMenuNow()", 2600)
    r.js("radial.open && radialHubClick()", 900)
    r.start()
    r.cap('<b>Главное меню.</b> Нажмите на значок <b>GVox</b> — вокруг раскроются разделы', 1800)
    r.click('#radialHub', after=1400)
    r.cap('Наведите на раздел — внизу появится описание', 300)
    for k in range(4):
        r.move(f'.radial__item.is-in:not(.is-out)[data-k="{k}"]', 500); r.wait(900)
    r.cap('Клик по разделу — в том же кольце его пункты', 300)
    r.click('.radial__item.is-in:not(.is-out)[data-k="0"]', after=1500)
    for k in range(3):
        r.move(f'.radial__item.is-in:not(.is-out)[data-k="{k}"]', 450); r.wait(800)
    r.cap('В центре — <b>«назад»</b>. Клавиши: <b>1–9</b> — пункт по номеру, <b>Esc</b> — назад', 300)
    r.move('#radialHub', 500); r.wait(900)
    r.key('Esc', 'Escape', 1200)
    r.cap('<b>Утилиты</b> — аудит, названия по Excel, PowerPoint, конвертер, клон, очистка имён', 300)
    r.key('3', 'Digit3', 2600)
    r.key('Esc', 'Escape', 900)
    r.cap('<b>Обучение</b> в углу — ролики по каждому процессу и утилите', 300)
    r.click('#stage1-loading .btn-help', after=2800)
    r.key('→', 'ArrowRight', 1600)
    r.key('Esc', 'Escape', 900)
    r.cap('')
