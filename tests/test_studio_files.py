"""Студия: сырые переменные, отметки «Начало / конец», «Сборка переменной»; аудит — дубли по языкам."""
import os

from conftest import md5, wav


def test_take_to_raw_vars_never_overwrites(studio):
    a, st, U, wd = studio
    r1 = a.tts_take_to_raw_vars(0)
    r2 = a.tts_take_to_raw_vars(0)
    name = U[st["takes"][0]["unit"]]["name"]
    assert r1["raw_var"] == f'{name}.wav' and r2["raw_var"] == f'{name}_2.wav'
    d = os.path.join(wd, 'Фразы_Переменные')
    assert md5(os.path.join(d, r1["raw_var"])) and os.path.exists(os.path.join(d, r2["raw_var"]))
    assert st["takes"][0]["raw_var"] == r2["raw_var"]                    # дубль помечен «→ Перем.»
    assert os.path.exists(os.path.join(wd, st["takes"][0]["file"]))      # сам дубль на ленте остался


def test_take_without_phrase_named_by_chunk(studio):
    a, st, U, wd = studio
    st["takes"][1]["unit"] = None
    r = a.tts_take_to_raw_vars(1)
    assert r["raw_var"] == f'дубль_{st["takes"][1]["chunk"]:04d}.wav'


def test_raw_marks_toggle(studio):
    a, st, U, wd = studio
    d = os.path.join(wd, 'Фразы_Переменные')
    wav(os.path.join(d, 'нач.wav'), 'начало')
    wav(os.path.join(d, 'кон.wav'), 'конец')
    assert a.tts_raw_mark('нач.wav', 'start')["marks"] == {"start": 'нач.wav'}
    assert a.tts_raw_mark('нач.wav', 'end')["marks"] == {"end": 'нач.wav'}        # один файл — одна роль
    a.tts_raw_mark('нач.wav', 'start')
    m = a.tts_raw_mark('кон.wav', 'end')
    assert m["marks"] == {"start": 'нач.wav', "end": 'кон.wav'}
    assert {x["file"]: x["mark"] for x in m["raw"]} == {'нач.wav': 'start', 'кон.wav': 'end'}
    assert a.tts_raw_mark('кон.wav', 'end')["marks"] == {"start": 'нач.wav'}       # повторно — снять
    assert a.tts_raw_mark('кон.wav', 'middle').get("error")


def test_raw_assembly_asks_folder_once(studio, dialog, tmp_path):
    a, st, U, wd = studio
    d = os.path.join(wd, 'Фразы_Переменные')
    assert a.tts_raw_assembly().get("error")                              # без «Начала» — нельзя
    wav(os.path.join(d, 'нач.wav'), 'начало')
    a.tts_raw_mark('нач.wav', 'start')
    assert a.tts_raw_assembly() == {"need_folder": True}
    vals = tmp_path / 'значения'
    for n in ('10', '2', '1'):
        wav(str(vals / f'{n}.wav'), n)
    dialog(str(vals))
    s = a.tts_raw_assembly(pick=True)
    assert [r["name"] for r in s["rows"]] == ['1', '2', '10']
    assert s["pick"]["ru"]["start"].endswith('нач.wav') and s["pick"]["kz"]["start"].endswith('нач.wav')
    s2 = a.tts_raw_assembly()                                             # папку больше не спрашивает
    assert s2.get("rows") and not s2.get("need_folder")


def test_raw_var_to_rail_once(studio):
    a, st, U, wd = studio
    wav(os.path.join(wd, 'Фразы_Переменные', 'сырая.wav'), 'сырая запись')
    n = len(st["takes"])
    r1 = a.tts_raw_var_to_rail('сырая.wav')
    r2 = a.tts_raw_var_to_rail('сырая.wav')
    assert len(st["takes"]) == n + 1 and r1["index"] == r2["index"] == n
    assert next(x for x in a._tts_raw_vars_list() if x["file"] == 'сырая.wav')["on_rail"]


def test_audit_dups_same_language_only(tmp_path):
    from core.project_handler import ProjectMixin as P
    base = str(tmp_path)
    ru, kz = os.path.join(base, 'ru_mark', 'AUDI 80.wav'), os.path.join(base, 'kz_mark', 'AUDI 80.wav')
    assert P._audit_same_lang([ru, kz], base) == []                       # одна марка на двух языках — не дубль
    ru2 = os.path.join(base, 'ru_mark', 'old', 'AUDI 80.wav')
    assert sorted(P._audit_same_lang([ru, kz, ru2], base)) == sorted([ru, ru2])
    u1, u2 = os.path.join(base, 'a', 'x.wav'), os.path.join(base, 'b', 'x.wav')
    assert sorted(P._audit_same_lang([u1, u2], base)) == sorted([u1, u2])


def test_tts_state_empty_and_loaded(api, studio):
    s = api.tts_state()                                                   # программа только запущена
    assert s["loaded"] is False and s["takes"] == []
    a, st, U, wd = studio
    s = a.tts_state()
    assert s["loaded"] and s["has_takes"] and s["stats"]["units"] > 0
