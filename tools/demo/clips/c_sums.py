import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import fake_rec
a, st, U, wd = build_project()
fake_rec.install(a)
a._tts_ensure_value_units()
a.tts_prompt_mode('sum_ru'); a.tts_sum_logic(1); a._tts_prompt_fix(0); a._tts_save()

def studio_ready(r):
    r.js("localStorage.setItem('gvox_tts_autoasm', '1'); localStorage.setItem('gvox_tts_flow', '1')")
    r.js("(async () => { openTtsScreen(await pywebview.api.tts_state()); await ttsLoadPrompt(); })()", 1500)

if want('studio_sums'):
  with Rec('studio_sums', a) as r:
    r.top = 'mid'
    studio_ready(r)
    r.start()
    r.cap('<b>Суммы и даты.</b> Режим «Сумма» — строка целиком, тонкие черты — где программа разрежет', 3000)
    r.move('#ttsPromptMeta button:has-text("1 101 001")', 700)
    r.cap('<b>Логика 1</b> — миллионы + сотни + тысячи + тенге. <b>Логика 2</b> — только «сотни тысяч» (9 строк)', 3000)
    r.move('#ttsPromptMeta button:has-text("Начало")', 700)
    r.cap('<b>▶ Начало</b> — последние 2,5 с фразы перед суммой: поймать интонацию', 2600)
    r.move('#ttsPromptMeta button:has-text("поток")', 700)
    r.cap('<b>Поток</b> включён: читаете строки подряд, «Сборка» не мешает', 2400)
    r.key('R', 'KeyR', 1200)
    for k in range(3):
        fake_rec.read_line(r, a, extra_ms=150)
        r.wait(650)
    r.cap('Счётчик <b>«✂ Срезка»</b> растёт. Прочитали — <b>R</b>', 1800)
    r.key('R', 'KeyR', 1800)
    r.cap('Теперь спокойно режем: строка за строкой', 1800)
    r.click('#customAlertBox button:has-text("Начать срезку"), .custom-alert-box button:has-text("Начать срезку")', after=2500)
    r.cap('<b>Ярусы</b>: волна строки поделена на куски — Миллионы, Сотни, Тысячи, Тенге', 2600)
    edge = r.js("""(() => { let e = document.querySelectorAll('#ttsTiers .tts-tiers__edge.is-r')[0].getBoundingClientRect(); return {x: e.left + e.width / 2, y: e.top + e.height / 2}; })()""")
    r.cap('Граница встала неточно — тяните её мышью', 500)
    r.drag(edge['x'], edge['y'], edge['x'] + 14, edge['y'], 800)
    r.wait(900)
    r.move('#ttsTiers button:has-text("Стык")', 600)
    r.cap('<b>▶ Стык</b> — конец начала фразы + сумма + продолжение: так прозвучит', 2600)
    r.cap('<b>Enter</b> — эталоны ярусов сохранены, открывается следующая строка', 600)
    r.key('Enter', 'Enter', 2600)
    r.cap('Первая строка стала <b>шаблоном</b>: границы следующих ставятся по ней', 2600)
    r.key('Enter', 'Enter', 2200)
    r.cap('<b>Esc</b> — прервать; продолжить — кнопка «✂ Срезка» в суфлёре', 600)
    r.key('Esc', 'Escape', 2200)
    r.cap('')
