import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
# источник «готовых записей» — сохранённое демо-проекта
a0, st0, U0, wd0 = build_project()
SRC = os.path.join(VID, 'Готовые_записи'); shutil.rmtree(SRC, ignore_errors=True)
for d in ('Проверенные', 'Фразы_Переменные'):
    shutil.copytree(os.path.join(wd0, d), os.path.join(SRC, d))
NEW = os.path.join(VID, 'Проект_импорт'); shutil.rmtree(NEW, ignore_errors=True); os.makedirs(NEW)
a = Api()
a._tts_push = lambda p: JSQ.append(f"ttsProgress({json.dumps(json.loads(json.dumps(p, default=str)), ensure_ascii=False)})")
a.tts_load_excel(demo_env.XL); a._tts_attach_folder(NEW); a._tts_ensure_value_units(); a._tts_save()

def row_take(uid):
    u = a._tts()['units'][uid]; y = speech(' , '.join(x['text'] for x in u['tiers']), decl=1.0) * 1.6
    n = len(a._tts()['takes']) + 100
    rawp = os.path.join(NEW, 'Записи', f'Запись_сумма_{n}.wav'); write(rawp, y)
    f = os.path.join('Чанки', f'{n:04d}.wav'); write(os.path.join(NEW, f), y); ms = len(y) * 1000 // R
    a._tts()['takes'].append({"file": f, "start_ms": 0, "ms": ms, "orig": [0, ms], "raw": rawp, "heard": u['text'],
                              "listened": True, "chunk": n, "unit": uid, "score": 0.97, "status": "ok"})
    a._tts_save()

with Rec('studio_ready', a) as r:
    r.top = 'mid'
    r.js("localStorage.setItem('gvox_tts_autoasm', '0')")
    r.js("(async () => { openTtsScreen(await pywebview.api.tts_state()); await ttsLoadPrompt(); })()", 1500)
    r.start()
    r.cap('Уже есть записи из прошлых проектов? <b>«Готовые записи»</b> — выберите их папку', 2400)
    DIALOG.append([SRC])
    r.click('button:has-text("Готовые записи")', after=2200)
    r.cap('Файлы нашлись по таблице и легли на свои места — суфлёр их пропускает', 2800)
    r.click('#customAlertOk', after=1400)
    r.cap('Фразы с переменными — на ленте с пометкой <b>«готовый»</b>: их можно править', 2600)
    r.click('#ttsRail .tts-take:has-text("готовый")', after=1600)
    r.cap('Подрезать — как обычный дубль; <b>Enter</b> сохраняет поверх готового файла', 2400)
    r.key('Esc', 'Escape', 900)
    # строка суммы, чтобы показать ✎
    r.js("ttsPromptModeSet('sum_ru')", 1200)
    items = a._tts_prompt_items(); row_take(items[0][0])
    r.js("(async () => { tts = await pywebview.api.tts_state(); ttsRender(); ttsLoadPrompt(); })()", 900)
    r.cap('Строка суммы в «Сборке»: рядом начало и продолжение фразы', 600)
    i = len(a._tts()["takes"]) - 1
    r.move(f'#ttsRail .tts-take[data-i="{i}"]'); r.pg.mouse.down(); r.wait(60); r.pg.mouse.up()
    r.js(f"ttsCurTake() && ttsCurTake().i === {i} || ttsRailClick({i})", 2600)

    r.cap('<b>✎</b> у «Начало» — поправить тайминг самой фразы', 600)
    r.click('#ttsTiers button:has-text("✎")', after=2000)
    r.cap('Открылась фраза. Вверху — <b>«← К строке …»</b>', 2600)
    r.cap('Поправили — <b>Enter</b> (сохранить) или <b>Esc</b>: обратно к строке, откуда пришли', 600)
    r.key('Esc', 'Escape', 2600)
    r.cap('')
