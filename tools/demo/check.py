"""Быстрая проверка интерфейса GVox на демо-проекте (без Windows и Audacity).

    python tools/demo/check.py studio                       # Студия, фразы
    python tools/demo/check.py studio --mode sum_ru         # Студия, суммы
    python tools/demo/check.py menu
    python tools/demo/check.py constructor
    python tools/demo/check.py audit
    python tools/demo/check.py studio --js "ttsOpenUnits('all')" --shot out.png

Печатает ошибки JS и что видно на экране; скриншот — в tools/demo/_work/check.png
(или --shot). Логику кода проверяйте отдельно — через demo_env.build() в Python."""
import argparse, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import *                                   # noqa: E402,F401

p = argparse.ArgumentParser()
p.add_argument('screen', choices=['menu', 'studio', 'constructor', 'audit'])
p.add_argument('--mode', help="режим суфлёра: phrases | sum_ru | date_ru")
p.add_argument('--js', action='append', default=[], help="JS после открытия экрана (можно несколько раз)")
p.add_argument('--wait', type=int, default=1500)
p.add_argument('--shot', default=os.path.join(VID, 'check.png'))
p.add_argument('--size', default='1600x900')
args = p.parse_args()

if args.screen == 'menu':
    a = Api()
else:
    a, st, U, wd = build_project()
    a._tts_ensure_value_units()
    if args.mode:
        a.tts_prompt_mode(args.mode)
    a._tts_save()
with Rec('check', a) as r:
    if args.screen == 'menu':
        r.js("showMenuNow()", 2500)
    elif args.screen == 'studio':
        r.js("(async () => { openTtsScreen(await pywebview.api.tts_state()); await ttsLoadPrompt(); })()", 1500)
    elif args.screen == 'constructor':
        DIALOG.append([wd])
        r.js("(async () => { constructorState = await pywebview.api.constructor_pick_sum_folder(); openConstructorScreen(); })()", 1500)
    elif args.screen == 'audit':
        r.js(f"(async () => {{ renderAuditResult(await pywebview.api._audit_studio({json.dumps(wd)}, {json.dumps(demo_env.XL)})); }})()", 1500)
    for code in args.js:
        r.js(code, 600)
    r.wait(args.wait)
    r.pg.screenshot(path=args.shot)
    shown = r.js("[...document.querySelectorAll('.stage')].filter(s => s.offsetParent).map(s => s.id).join(', ')")
    print('экран:', shown or '—')
    print('скриншот:', args.shot)
    print('ошибки JS:', r.errs or 'нет')
