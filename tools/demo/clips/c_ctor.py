import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
a, st, U, wd = build_project()
a._tts_ensure_value_units()
src = os.path.join(wd, st['takes'][0]['file'])
rows = [u for u in U if u.get('tiers')]
for u in [r for r in rows if r['sheet'] == 'sum_ru' and r.get('logic') == 1][:9] + [r for r in rows if r['sheet'] == 'date_ru'][:12]:
    t0 = 0
    for t in u['tiers']:
        p = a._tts_tier_path(u, t); os.makedirs(os.path.dirname(p), exist_ok=True)
        write(p, speech(t['text'], decl=1.0))
a._tts_save()

def menu_ready(r):
    r.js("showMenuNow()", 2600)
    r.js("radial.open && radialHubClick()", 900)

with Rec('constructor', a) as r:
    menu_ready(r)
    r.start()
    r.cap('<b>Конструктор</b> — собрать любую сумму или дату из эталонов и сверить с фразой', 1800)
    r.click('#radialHub', after=1100)
    r.click('.radial__item.is-in:not(.is-out)[data-k="1"]', after=1300)
    r.click('.radial__item.is-in:not(.is-out):has-text("Конструктор")', after=1300)
    r.cap('Выберите папку <b>«Значения»</b> или сам проект', 1800)
    DIALOG.append([wd])
    r.click('#customAlertOk', after=2200)
    r.cap('Сверху — листы: Сумма, Дата. Рулетки — значения каждого яруса', 2800)
    r.move('#constructorPhrase', 700)
    r.cap('<b>◀ ▶</b> — фраза, где стоит эта переменная: start → значение → end', 2600)
    r.move('#constructorPhrase label', 600)
    r.cap('<b>«кратко»</b> — играет только 2,5 с конца начала и начала продолжения: быстро сверить стык', 3000)
    r.cap('<b>A / D</b> — выбрать рулетку, <b>W / S</b> — листать (держите — ускоряется)', 600)
    r.key('S', 'KeyS', 500); r.key('S', 'KeyS', 500); r.key('D', 'KeyD', 500); r.key('S', 'KeyS', 500); r.key('D', 'KeyD', 500); r.key('S', 'KeyS', 900)
    r.cap('<b>Space</b> — послушать всю сборку', 600)
    r.key('Space', 'Space', 2200)
    r.click('#constructorLangRow button:has-text("Дата")', after=1600)
    r.cap('Лист дат: день и месяц по календарю', 600)
    r.key('S', 'KeyS', 500); r.key('D', 'KeyD', 500); r.key('S', 'KeyS', 500); r.key('S', 'KeyS', 1000)
    r.cap('Не нравится стык — <b>«Обновить в Audacity»</b>, поправьте и <b>«Сохранить»</b> поверх эталона', 3200)
    r.cap('')
