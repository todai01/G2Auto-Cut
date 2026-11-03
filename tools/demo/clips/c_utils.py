import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import subprocess
import numpy as np
from core.clone_prep import _mono
UD = os.path.join(VID, 'Утилиты'); shutil.rmtree(UD, ignore_errors=True); os.makedirs(UD)
a = Api()

def menu_tool(r, name, dialog=None):
    DIALOG.clear()
    r.js("showMenuNow()", 2600)
    r.js("radial.open && radialHubClick()", 900)
    r.start()
    r.click('#radialHub', after=1000)
    r.click('.radial__item.is-in:not(.is-out)[data-k="2"]', after=1200)
    if dialog is not None:
        DIALOG.append(dialog)
    r.click(f'.radial__item.is-in:not(.is-out):has-text("{name}")', after=1200)

# ---------- PowerPoint ----------
if want('pptx'):
    xl = demo_env.XL
    outp = os.path.join(UD, 'Слайды RU.pptx')
    with Rec('pptx', a) as r:
        r.top = 'top'
        menu_tool(r, 'PowerPoint')
        r.cap('<b>Таблица → PowerPoint</b>: каждая строка Excel — отдельный слайд', 2400)
        r.move('#tablePptxLangRuBtn', 600)
        r.cap('Язык: RU, KZ или перевод — у каждого свой файл', 2000)
        DIALOG.append([xl]); r.click('#tablePptxOverlay button:has-text("Выбрать файл")', after=1800)
        r.cap('В файле несколько листов — выберите лист с текстом', 600)
        r.click('#tablePptxOverlay button:has-text("Фразы")', after=1500)
        r.cap('Видно, сколько строк станет слайдами', 1800)
        DIALOG.append(outp); r.click('#btnRunTablePptx', after=2200)
        r.cap('Готово: читать с экрана удобно — колонки идут с паузами', 3000)
        r.cap('')

# ---------- Конвертер ----------
if want('converter'):
    srcs = []
    for n in ('Запись_звонка_1', 'Запись_звонка_2'):
        p = os.path.join(UD, n + '.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=330:duration=3', '-c:a', 'aac', p], check=True)
        srcs.append(p)
    outd = os.path.join(UD, 'MP3'); os.makedirs(outd)
    with Rec('converter', a) as r:
        r.top = 'top'
        menu_tool(r, 'Конвертер')
        r.cap('<b>Конвертер MP4</b>: звук из видео — в MP3 или WAV', 2200)
        DIALOG.append(srcs); r.click('#converterOverlay button:has-text("Выбрать файлы")', after=1300)
        DIALOG.append([outd]); r.click('#converterOverlay button:has-text("Выбрать папку")', after=1300)
        r.cap('Формат и частота — кнопками (для IVR обычно 8000 Гц)', 600)
        r.click('#converterOverlay input[name="convertFormat"][value="wav"] + *', after=700)
        r.click('#converterOverlay input[name="convertHz"] >> nth=-1', after=900)
        r.click('#converterOverlay .splash-btn', after=2200)
        r.cap('Готово — файлы в выбранной папке', 2600)
        r.cap('')

# ---------- Клон ----------
if want('clone'):
    cd = os.path.join(UD, 'Фразы_для_клона'); os.makedirs(cd)
    for k, t in enumerate(['Здравствуйте!', 'Ваш заказ передан курьеру.', 'Спасибо, что выбрали нас!'], 1):
        write(os.path.join(cd, f'phrase_{k}.wav'), speech(t))
    FAKE['clone_pick_folder'] = lambda: a.clone_scan(cd)
    with Rec('clone', a) as r:
        r.top = 'top'
        menu_tool(r, 'клону')
        r.cap('<b>Подготовка к клону</b>: все файлы папки — в один WAV с паузами', 2400)
        r.click('#cloneOverlay button:has-text("Папка с аудио")', after=1200)
        r.cap('Пауза между фразами и частота — как нужно сервису клонирования', 600)
        r.click('#cloneOverlay input[name="cloneRate"][value="44100"] + .opt-chip__box', after=900)
        r.click('#btnCloneBuild', after=2400)
        r.cap('Этот WAV — в сервис клонирования. Тайминги сохранены рядом', 2600)
        x, rr = _mono(os.path.join(cd, '_Клон', 'Клон_исходник.wav'))
        cl = []
        for name, delay in (('Клон_Голос_1', 0.12), ('Клон_Голос_2', 0.2)):
            pth = os.path.join(UD, name + '.wav'); write(pth, np.concatenate([np.zeros(int(rr * delay)), x]), rr); cl.append(pth)
        FAKE['clone_pick_clones'] = lambda: a.clone_set_clones(cl)
        r.cap('Готовые клоны: <b>«Файлы клонов…»</b> → <b>«Нарезать»</b>', 600)
        r.click('#cloneOverlay button:has-text("Файлы клонов")', after=1200)
        r.click('#btnCloneCut', after=3000)
        r.cap('Клоны разрезаны обратно на файлы с теми же именами — по папке на голос', 3000)
        r.cap('')
