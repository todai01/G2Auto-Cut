import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harness import *
import openpyxl, subprocess
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

# ---------- Названия по Excel ----------
if want('rename_match'):
    fd = os.path.join(UD, 'Короткие_имена'); os.makedirs(fd)
    shorts = ['da_1_1', 'da_1_2', 'opl_2_1', 'opl_2_2', 'nap_3_1', 'test_9']
    for s_ in shorts: write(os.path.join(fd, s_ + '.wav'), speech('проверка связи', decl=1))
    xl = os.path.join(UD, 'Полные_названия.xlsx'); wb = openpyxl.Workbook(); ws = wb.active
    for n in ['dostavka_ru_da_1_1', 'dostavka_ru_da_1_2', 'dostavka_kz_opl_2_1', 'dostavka_kz_opl_2_2', 'dostavka_ru_nap_3_1']: ws.append([n])
    wb.save(xl)
    with Rec('rename_match', a) as r:
        r.top = 'top'
        menu_tool(r, 'Названия')
        r.cap('<b>Названия по Excel</b>: короткие имена файлов → полные «боевые» названия', 2400)
        DIALOG.append([fd]); r.click('button:has-text("Выбрать папку")', after=1300)
        r.cap('Папка с файлами вроде <b>da_1_1.wav</b>', 1600)
        DIALOG.append([xl]); r.click('#renameMatchOverlay button:has-text("Выбрать файл")', after=1300)
        r.cap('Excel со списком полных названий — <b>dostavka_ru_da_1_1</b>…', 2000)
        r.move('#renameMatchOverlay .opt-chip', 600)
        r.cap('«Искать только» ru / kz — если одно короткое имя есть в обоих языках', 2400)
        r.click('#btnRunRenameMatch', after=1800)
        r.cap('Файлы переименованы и разложены по папкам <b>ru</b> / <b>kz</b>. Без пары — список, их не трогаю', 3600)
        r.cap('')

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

# ---------- Очистить названия ----------
if want('strip'):
    sd = os.path.join(UD, 'Суммы_с_словами'); os.makedirs(sd)
    for n in ['1 миллион', '2 миллиона', '5 миллионов', '20 тысяч', '300 тенге']:
        write(os.path.join(sd, n + '.wav'), speech(n, decl=1))
    with Rec('strip', a) as r:
        r.top = 'top'
        r.top = 'top'
        r.cap('', 0)
        menu_tool(r, 'Очистить', dialog=[sd])
        r.cap('<b>Очистить названия</b>: «5 миллионов.wav» → «5.wav». Выберите папку — подпапки тоже', 2600)
        r.cap('Готово: остались только цифры. Одинаковые получат _1, _2', 3000)
        r.cap('')
