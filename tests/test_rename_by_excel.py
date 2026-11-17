"""tools/rename_by_excel.py: файлы 1, 2, … n → названия из Excel; ничего не теряется и не перезаписывается."""
import os
import sys

import openpyxl
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import rename_by_excel as rb                               # noqa: E402


def folder_with(tmp_path, names, content=True):
    d = tmp_path / 'audio'
    d.mkdir(exist_ok=True)
    for n in names:
        (d / n).write_bytes(n.encode('utf-8') if content else b'')      # содержимое = старое имя: видно, что файл не подменился
    return str(d)


def xlsx(tmp_path, values, header=None, name='t.xlsx', col=1):
    wb = openpyxl.Workbook()
    ws = wb.active
    r = 1
    if header is not None:
        ws.cell(r, col, header)
        r += 1
    for v in values:
        ws.cell(r, col, v)
        r += 1
    p = str(tmp_path / name)
    wb.save(p)
    return p


def listing(d):
    return sorted(f for f in os.listdir(d) if not f.startswith('_отмена'))


def test_basic_rename_keeps_extension_and_content(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav', '3.mp3'])
    cells, skipped = rb.read_names(xlsx(tmp_path, ['Иван', 'Мария', 'Пётр']))
    plan, warns = rb.build_plan(d, cells)
    assert warns == [] and skipped is None
    assert rb.apply_plan(d, plan) == 3
    assert listing(d) == ['Иван.wav', 'Мария.wav', 'Пётр.mp3']
    assert (tmp_path / 'audio' / 'Иван.wav').read_bytes() == b'1.wav'          # в «Иван» лежит то, что было «1»


def test_order_is_numeric_not_alphabetic(tmp_path):
    names = [f'{i}.wav' for i in range(1, 13)]
    d = folder_with(tmp_path, names)
    cells, _ = rb.read_names(xlsx(tmp_path, [f'имя{i}' for i in range(1, 13)]))
    rb.apply_plan(d, rb.build_plan(d, cells)[0])
    assert (tmp_path / 'audio' / 'имя10.wav').read_bytes() == b'10.wav' and (tmp_path / 'audio' / 'имя2.wav').read_bytes() == b'2.wav'


def test_header_is_skipped_automatically_or_by_flag(tmp_path):
    cells, skipped = rb.read_names(xlsx(tmp_path, ['a', 'b'], header='<name>'))
    assert cells == ['a', 'b'] and skipped == '<name>'                       # шапка вида <mark> — сама
    cells, skipped = rb.read_names(xlsx(tmp_path, ['a', 'b'], header='Названия', name='h.xlsx'), header=True)
    assert cells == ['a', 'b'] and skipped == 'Названия'
    cells, skipped = rb.read_names(xlsx(tmp_path, ['a', 'b'], header='Названия', name='h2.xlsx'))
    assert cells == ['Названия', 'a', 'b'] and skipped is None               # обычный текст в первой строке — это уже название


def test_other_column_and_sheet(tmp_path):
    p = xlsx(tmp_path, ['x', 'y'], col=3, name='c.xlsx')
    assert rb.read_names(p, 'C')[0] == ['x', 'y'] and rb.read_names(p, '3')[0] == ['x', 'y']
    assert rb.read_names(p, 'A')[0] == []


def test_forbidden_characters_and_numbers(tmp_path):
    assert rb.clean_name('Что? Где: когда/как') == 'Что_ Где_ когда_как'
    assert rb.clean_name('  много   пробелов  ') == 'много пробелов'
    assert rb.clean_name(5.0) == '5' and rb.clean_name(7) == '7' and rb.clean_name(2.5) == '2.5'
    assert rb.clean_name(None) == '' and rb.clean_name('   ') == '' and rb.clean_name('...') == ''
    assert rb.clean_name('CON') == '_CON'                                    # зарезервированное имя Windows
    assert len(rb.clean_name('я' * 500)) <= rb.MAX_LEN
    d = folder_with(tmp_path, ['1.wav'])
    rb.apply_plan(d, rb.build_plan(d, ['a/b:c'])[0])
    assert listing(d) == ['a_b_c.wav']


def test_duplicate_texts_get_numbers(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav', '3.wav'])
    plan, _ = rb.build_plan(d, ['Привет', 'привет', 'Привет'])
    assert [b for _, b in plan] == ['Привет.wav', 'привет (2).wav', 'Привет (3).wav']
    rb.apply_plan(d, plan)
    assert len(listing(d)) == 3


def test_empty_cells_extra_files_and_extra_rows_are_reported(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav', '5.wav'])
    plan, warns = rb.build_plan(d, ['один', None, 'три', 'четыре'])
    assert plan == [('1.wav', 'один.wav')]
    text = ' '.join(warns)
    assert 'ячейка №2 пустая' in text and 'нет строки №5' in text and 'строка №3' in text and 'строка №4' in text
    rb.apply_plan(d, plan)
    assert listing(d) == ['2.wav', '5.wav', 'один.wav']                      # лишние и пустые не тронуты


def test_leading_zeros_and_non_numbered_files_untouched(tmp_path):
    d = folder_with(tmp_path, ['01.wav', '02.WAV', 'note.txt', 'фон.wav', 'a1.wav'])
    plan, _ = rb.build_plan(d, ['один', 'два'])
    rb.apply_plan(d, plan)
    assert listing(d) == ['a1.wav', 'note.txt', 'два.WAV', 'один.wav', 'фон.wav']


def test_ambiguous_numbers_are_skipped(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '01.wav', '2.wav'])
    plan, warns = rb.build_plan(d, ['а', 'б'])
    assert [a for a, _ in plan] == ['1.wav', '2.wav'] or [a for a, _ in plan] == ['01.wav', '2.wav']
    assert any('уже есть' in w for w in warns)                               # один из двух «1» не угадываем молча


def test_swap_names_do_not_overwrite_each_other(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav'])
    plan, _ = rb.build_plan(d, ['2', '1'])                                   # 1→«2», 2→«1»: крест-накрест
    assert rb.apply_plan(d, plan) == 2
    assert (tmp_path / 'audio' / '2.wav').read_bytes() == b'1.wav' and (tmp_path / 'audio' / '1.wav').read_bytes() == b'2.wav'
    assert not [f for f in os.listdir(d) if f.startswith('~tmp')]


def test_never_overwrites_foreign_file(tmp_path):
    d = folder_with(tmp_path, ['1.wav', 'Иван.wav'])
    plan, warns = rb.build_plan(d, ['Иван'])
    assert plan == [] and any('занято' in w for w in warns)
    assert (tmp_path / 'audio' / 'Иван.wav').read_bytes() == 'Иван.wav'.encode('utf-8')


def test_rollback_on_failure(tmp_path, monkeypatch):
    d = folder_with(tmp_path, ['1.wav', '2.wav', '3.wav'])
    before = {f: open(os.path.join(d, f), 'rb').read() for f in os.listdir(d)}
    real, calls = os.replace, []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 5:                                                  # сбой на середине второго этапа (файл занят)
            raise PermissionError('занят')
        return real(a, b)
    plan, _ = rb.build_plan(d, ['а', 'б', 'в'])
    monkeypatch.setattr(os, 'replace', flaky)
    with pytest.raises(RuntimeError, match='возвращено как было'):
        rb.apply_plan(d, plan)
    monkeypatch.setattr(os, 'replace', real)
    assert {f: open(os.path.join(d, f), 'rb').read() for f in os.listdir(d)} == before     # всё как было, включая содержимое


def test_undo_restores_names_and_log_is_removed(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav', '3.wav'])
    rb.apply_plan(d, rb.build_plan(d, ['а', 'б', 'в'])[0])
    assert os.path.exists(os.path.join(d, rb.UNDO_FILE))
    assert rb.undo(d) == 3
    assert listing(d) == ['1.wav', '2.wav', '3.wav'] and not os.path.exists(os.path.join(d, rb.UNDO_FILE))
    assert (tmp_path / 'audio' / '2.wav').read_bytes() == b'2.wav'
    with pytest.raises(RuntimeError, match='нет записи'):
        rb.undo(d)


def test_undo_after_partial_manual_changes(tmp_path):
    d = folder_with(tmp_path, ['1.wav', '2.wav'])
    rb.apply_plan(d, rb.build_plan(d, ['а', 'б'])[0])
    os.remove(os.path.join(d, 'б.wav'))                                      # один файл успели удалить вручную
    assert rb.undo(d) == 1 and listing(d) == ['1.wav']


def test_cli_dry_run_and_yes(tmp_path, capsys):
    d = folder_with(tmp_path, ['1.wav', '2.wav'])
    x = xlsx(tmp_path, ['а', 'б'])
    assert rb.main(['--folder', d, '--excel', x, '--dry-run']) == 0
    assert listing(d) == ['1.wav', '2.wav'] and 'ничего не изменено' in capsys.readouterr().out      # просмотр ничего не меняет
    assert rb.main(['--folder', d, '--excel', x, '--yes']) == 0
    assert listing(d) == ['а.wav', 'б.wav']
    assert rb.main(['--folder', d, '--undo']) == 0 and listing(d) == ['1.wav', '2.wav']


def test_cli_confirmation_no_changes_nothing(tmp_path, monkeypatch):
    d = folder_with(tmp_path, ['1.wav'])
    monkeypatch.setattr('builtins.input', lambda *_: 'нет')
    rb.main(['--folder', d, '--excel', xlsx(tmp_path, ['а'])])
    assert listing(d) == ['1.wav']
    monkeypatch.setattr('builtins.input', lambda *_: 'да')
    rb.main(['--folder', d, '--excel', xlsx(tmp_path, ['а'], name='t2.xlsx')])
    assert listing(d) == ['а.wav']
