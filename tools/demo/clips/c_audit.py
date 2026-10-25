import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
a, st, U, wd = build_project()
a._tts_ensure_value_units()
src = os.path.join(wd, st['takes'][0]['file'])
rows = [u for u in U if u.get('tiers')]
for u in [r for r in rows if r['sheet'] == 'sum_ru' and r.get('logic') == 1][:6] + [r for r in rows if r['sheet'] == 'date_ru'][:4]:
    for t in u['tiers']:
        p = a._tts_tier_path(u, t); os.makedirs(os.path.dirname(p), exist_ok=True); shutil.copy(src, p)
# забытый файл в корзине и дубль фразы в другой папке
os.makedirs(os.path.join(wd, '_Корзина'), exist_ok=True); shutil.copy(src, os.path.join(wd, '_Корзина', 'bye_ru_1.wav'))
os.makedirs(os.path.join(wd, 'Проверенные', 'старое'), exist_ok=True); shutil.copy(src, os.path.join(wd, 'Проверенные', 'старое', 'hello_ru_1.wav'))
OUTD = os.path.join(VID, 'Сдача'); shutil.rmtree(OUTD, ignore_errors=True); os.makedirs(OUTD)

def menu_ready(r):
    r.js("showMenuNow()", 2600)
    r.js("radial.open && radialHubClick()", 900)

if want('audit'):
  with Rec('audit', a) as r:
    menu_ready(r)
    r.start()
    r.cap('<b>Аудит</b> — что записано, чего не хватает, где дубли', 1600)
    r.click('#radialHub', after=1100)
    r.click('.radial__item.is-in:not(.is-out)[data-k="2"]', after=1300)
    r.click('.radial__item.is-in:not(.is-out):has-text("Аудит")', after=1500)
    r.cap('<b>Таблица Студии записи</b> — все листы: фразы, суммы, даты', 2200)
    DIALOG.append([wd])
    r.click('#auditCategoryList .audit-category-item.is-main', after=600)
    r.cap('Выбираете папку проекта. Смотрю только <b>Проверенные</b>, <b>Фразы_Переменные</b>, <b>Значения</b>', 3200)
    r.move('.audit-scanned', 700)
    r.cap('Корзина и черновики — <b>«Не смотрю»</b>: файл из корзины готовым не считается', 3000)
    r.move('.audit-section', 700)
    r.cap('Группы: фразы цельные и с переменными, суммы и даты по ярусам. Красное — нет, жёлтое — дубли', 3000)
    r.click('.audit-grp.has-problems summary', after=1500)
    r.cap('Внутри — какие именно файлы. Клик — послушать, <b>«Файл…»</b> — взять готовый под нужное имя', 3000)
    r.move('button:has-text("Записать все недостающие")', 800)
    r.cap('<b>● Записать все недостающие</b> — суфлёр покажет только их', 1800)
    r.click('button:has-text("Записать все недостающие")', after=2200)
    r.cap('Метка «Недостающие из аудита» — осталось N из M. Записали — «Проверить аудитом снова»', 3200)
    r.cap('')

if want('audit_final'):
  with Rec('audit_final', a) as r:
    r.js("(async () => { let res = await pywebview.api.audit_rerun(); if (res && !res.error) renderAuditResult(res); })()", 1500)
    r.start()
    r.cap('Всё записано? <b>«Финальная папка»</b> — папка для сдачи', 2000)
    r.click('button:has-text("Финальная папка")', after=1500)
    r.cap('Если в аудите ещё есть пропуски или дубли — программа предупредит', 2400)
    DIALOG.append([OUTD])
    r.click('#customAlertOk', after=1800)
    r.cap('<b>Финал_&lt;дата&gt;</b>: «Перманентные» — все фразы одной папкой, «Переменные» — содержимое «Значения»', 3600)
    r.cap('Месяцы называются коротко: <b>jan_ru</b>, <b>jan_kz</b>… Исходники не трогаются', 3000)
    r.cap('')
