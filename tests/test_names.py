"""Поиск записи по названию: числа словами, языки папок, имена файлов."""
import os
import subprocess
import sys

import pytest

from conftest import ROOT, wav
from core.listen_mode import listen_dir_lang, listen_keys, listen_lang_root, listen_num, listen_num_name, listen_stem


@pytest.mark.parametrize('name, num', [
    ('одно опоздание', '1'), ('два опоздания', '2'), ('двенадцать опоздании', '12'), ('двадцать один опоздании', '21'),
    ('сто пять опоздании', '105'), ('тысяча опоздании', '1000'), ('бір рет', '1'), ('екі жүз елу', '250'),
    ('3 опоздания', '3'), ('Иван', None), ('Мария', None),
])
def test_listen_num(name, num):
    assert listen_num(name) == num


@pytest.mark.parametrize('name, stem', [
    ('одно опоздание', '1'), ('бір рет', '1'),
    ('AUDI 80', 'AUDI 80'), ('BMW X5', 'BMW X5'),          # у марок цифры — часть названия
    ('Lada', 'Lada'), ('a/b:c', 'a_b_c'),
])
def test_listen_stem(name, stem):
    assert listen_stem(name) == stem


def test_marks_never_match_by_number():
    assert listen_num_name('AUDI 80') is None
    assert listen_keys('AUDI 80') == [listen_keys('AUDI 80')[0]]      # только по названию, не «80.wav»


@pytest.mark.parametrize('name, lang', [
    ('ru', 'ru'), ('KZ', 'kz'), ('ru_mark', 'ru'), ('kz_mark', 'kz'), ('Фразы_kz', 'kz'),
    ('uni_mark', None), ('ru_kz_var', None), ('Марки', None),
])
def test_dir_lang(name, lang):
    assert listen_dir_lang(name) == lang


def test_lang_root_lifts_to_parent(tmp_path):
    for d in ('ru_mark', 'kz_mark'):
        wav(str(tmp_path / 'm' / d / 'x.wav'))
    assert listen_lang_root(str(tmp_path / 'm' / 'ru_mark')) == os.path.normpath(str(tmp_path / 'm'))
    alone = tmp_path / 'solo' / 'ru'
    wav(str(alone / 'x.wav'))
    assert listen_lang_root(str(alone)) == os.path.normpath(str(alone))    # соседа другого языка нет — не поднимаемся


def test_tr_title():
    from core.batch_synth import tr_title
    assert tr_title('BERİTAN') == 'Beritan'
    assert tr_title('GÜNAYDIN AVCİ') == 'Günaydın Avci'


def test_files_to_excel(tmp_path):
    import openpyxl
    src = tmp_path / 'in'
    for n in ('10.wav', '2.wav', 'AUDI 80.mp3', 'Lada_ru.wav'):
        (src / n).parent.mkdir(parents=True, exist_ok=True)
        (src / n).write_bytes(b'')
    out = tmp_path / 'out.xlsx'
    subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'files_to_excel.py'), str(src), str(out), '--suffix', '_ru'],
                   check=True, capture_output=True)
    ws = openpyxl.load_workbook(out).active
    assert [r[0].value for r in ws.iter_rows()] == ['2', '10', 'AUDI 80', 'Lada']
