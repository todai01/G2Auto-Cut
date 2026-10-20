"""Числа словами для текста синтеза — RU и KZ, с единицами.

Текст синтеза значения — «значение с единицей»: «пять миллионов»,
«сто тысяч», «двадцать тенге», «первого» (день). Правила зависят от
категории (колонки листа переменных: <million_ru>, <thousand_kz>, <day_ru>…).
Любой текст можно поправить руками на экране «Переменные»."""

import re

# ---------------- RU ----------------

_RU_UNITS_M = ['', 'один', 'два', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять']
_RU_UNITS_F = ['', 'одна', 'две', 'три', 'четыре', 'пять', 'шесть', 'семь', 'восемь', 'девять']
_RU_TEENS = ['десять', 'одиннадцать', 'двенадцать', 'тринадцать', 'четырнадцать', 'пятнадцать',
             'шестнадцать', 'семнадцать', 'восемнадцать', 'девятнадцать']
_RU_TENS = ['', '', 'двадцать', 'тридцать', 'сорок', 'пятьдесят', 'шестьдесят', 'семьдесят',
            'восемьдесят', 'девяносто']
_RU_HUNDREDS = ['', 'сто', 'двести', 'триста', 'четыреста', 'пятьсот', 'шестьсот', 'семьсот',
                'восемьсот', 'девятьсот']


def ru_plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many


def _ru_triad(n, fem=False):
    words = []
    h, rest = divmod(n, 100)
    if h:
        words.append(_RU_HUNDREDS[h])
    if 10 <= rest <= 19:
        words.append(_RU_TEENS[rest - 10])
    else:
        t, u = divmod(rest, 10)
        if t:
            words.append(_RU_TENS[t])
        if u:
            words.append((_RU_UNITS_F if fem else _RU_UNITS_M)[u])
    return words


def ru_words(n, fem=False):
    """Число прописью (до миллиардов). fem — женский род (одна, две)."""
    n = int(n)
    if n == 0:
        return 'ноль'
    words = []
    for value, forms, f in ((10 ** 9, ('миллиард', 'миллиарда', 'миллиардов'), False),
                            (10 ** 6, ('миллион', 'миллиона', 'миллионов'), False),
                            (10 ** 3, ('тысяча', 'тысячи', 'тысяч'), True)):
        part, n = divmod(n, value)
        if part:
            words += _ru_triad(part, f) + [ru_plural(part, *forms)]
    words += _ru_triad(n, fem)
    return ' '.join(w for w in words if w)


_RU_ORD_UNITS = ['', 'первого', 'второго', 'третьего', 'четвёртого', 'пятого', 'шестого', 'седьмого',
                 'восьмого', 'девятого']
_RU_ORD_TEENS = ['десятого', 'одиннадцатого', 'двенадцатого', 'тринадцатого', 'четырнадцатого',
                 'пятнадцатого', 'шестнадцатого', 'семнадцатого', 'восемнадцатого', 'девятнадцатого']
_RU_ORD_TENS = ['', '', 'двадцатого', 'тридцатого']


def ru_day_genitive(n):
    """1 → «первого», 25 → «двадцать пятого» (как в «до пятого мая»)."""
    n = int(n)
    if 10 <= n <= 19:
        return _RU_ORD_TEENS[n - 10]
    t, u = divmod(n, 10)
    if not u:
        return _RU_ORD_TENS[t] if t < len(_RU_ORD_TENS) else ru_words(n)
    return (f"{_RU_TENS[t]} " if t else '') + _RU_ORD_UNITS[u]


_RU_ORD_TENS_ALL = ['', '', 'двадцатого', 'тридцатого', 'сорокового', 'пятидесятого', 'шестидесятого',
                    'семидесятого', 'восьмидесятого', 'девяностого']
_RU_ORD_HUNDREDS = ['', 'сотого', 'двухсотого', 'трёхсотого', 'четырёхсотого', 'пятисотого', 'шестисотого',
                    'семисотого', 'восьмисотого', 'девятисотого']
_RU_ORD_THOUSANDS = {1: 'тысячного', 2: 'двухтысячного', 3: 'трёхтысячного'}


def _ru_ord_genitive_99(n):
    """1..99 → порядковое в родительном: 5 → «пятого», 40 → «сорокового», 25 → «двадцать пятого»."""
    if 10 <= n <= 19:
        return _RU_ORD_TEENS[n - 10]
    t, u = divmod(n, 10)
    if not u:
        return _RU_ORD_TENS_ALL[t]
    return (f"{_RU_TENS[t]} " if t else '') + _RU_ORD_UNITS[u]


def ru_year_genitive(n):
    """2025 → «две тысячи двадцать пятого года», 2000 → «двухтысячного года»
    (как в «до первого января две тысячи двадцать пятого года»)."""
    n = int(n)
    th, r = divmod(n, 1000)
    if not r:
        word = _RU_ORD_THOUSANDS.get(th, f"{ru_words(n)}-го")
    else:
        h, rr = divmod(r, 100)
        head = (['тысяча'] if th == 1 else [ru_words(th * 1000)]) if th else []
        if not rr:
            word = ' '.join(head + [_RU_ORD_HUNDREDS[h]])
        else:
            word = ' '.join(head + ([_RU_HUNDREDS[h]] if h else []) + [_ru_ord_genitive_99(rr)])
    return f"{word} года"


# ---------------- KZ ----------------

_KZ_UNITS = ['', 'бір', 'екі', 'үш', 'төрт', 'бес', 'алты', 'жеті', 'сегіз', 'тоғыз']
_KZ_TENS = ['', 'он', 'жиырма', 'отыз', 'қырық', 'елу', 'алпыс', 'жетпіс', 'сексен', 'тоқсан']


def _kz_triad(n, lead_one=False):
    words = []
    h, rest = divmod(n, 100)
    if h:
        words += ([_KZ_UNITS[h]] if h > 1 or lead_one else []) + ['жүз']
    t, u = divmod(rest, 10)
    if t:
        words.append(_KZ_TENS[t])
    if u:
        words.append(_KZ_UNITS[u])
    return words


def kz_words(n):
    """Число прописью по-казахски: 5 → «бес», 100 → «жүз», 2000 → «екі мың»."""
    n = int(n)
    if n == 0:
        return 'нөл'
    words = []
    for value, name in ((10 ** 9, 'миллиард'), (10 ** 6, 'миллион'), (10 ** 3, 'мың')):
        part, n = divmod(n, value)
        if part:
            # «бір миллион», но просто «мың» (тысяча без «бір») — как говорят.
            words += (_kz_triad(part) if part > 1 or value >= 10 ** 6 else []) + [name]
    words += _kz_triad(n)
    return ' '.join(w for w in words if w)


_KZ_FRONT = set('еәіөүі')


def kz_ordinal(n):
    """5 → «бесінші», 20 → «жиырмасыншы», 31 → «отыз бірінші»."""
    words = kz_words(n).split()
    last = words[-1]
    front = any(c in _KZ_FRONT for c in last)
    if last == 'жиырма':
        last = 'жиырмасыншы'
    elif last[-1] in 'аеыіоөұүуәэюя':
        last += 'нші' if front else 'ншы'
    else:
        last += 'інші' if front else 'ыншы'
    return ' '.join(words[:-1] + [last])


# ---------------- категория → текст ----------------

def _num(value):
    s = re.sub(r'[\s ]', '', str(value))
    return int(s) if re.fullmatch(r'\d+', s) else None


# Месяцы: русские названия (как часто пишут и в казахских таблицах) → казахские.
KZ_MONTHS = {}
for _ru, _kz in (('январ', 'қаңтар'), ('феврал', 'ақпан'), ('март', 'наурыз'), ('апрел', 'сәуір'), ('ма', 'мамыр'),
                 ('июн', 'маусым'), ('июл', 'шілде'), ('август', 'тамыз'), ('сентябр', 'қыркүйек'),
                 ('октябр', 'қазан'), ('ноябр', 'қараша'), ('декабр', 'желтоқсан')):
    for _end in ('ь', 'я', 'а', '', 'й', 'е'):
        KZ_MONTHS.setdefault(_ru + _end, _kz)
KZ_MONTHS.update({'май': 'мамыр', 'мая': 'мамыр', 'маю': 'мамыр'})
for _kz in ('қаңтар', 'ақпан', 'наурыз', 'сәуір', 'мамыр', 'маусым', 'шілде', 'тамыз', 'қыркүйек', 'қазан', 'қараша', 'желтоқсан'):
    KZ_MONTHS[_kz] = _kz
KZ_MONTHS.pop('ма', None)
KZ_MONTHS.pop('мае', None)


def synth_text(category_key, value, lang=None):
    """Текст для синтеза значения категории: «значение с единицей»."""
    key = (category_key or '').lower()
    lang = lang or ('kz' if re.search(r'_(kz|kk)$', key) else 'ru')
    base = re.sub(r'_(ru|kz|kk)$', '', key)
    n = _num(value)
    if n is None:
        if lang == 'kz' and base == 'month':             # месяц в казахском листе — по-казахски
            return KZ_MONTHS.get(str(value).strip().lower(), str(value).strip())
        return str(value).strip()
    if lang == 'kz':
        if base == 'million':
            return f"{kz_words(n)} миллион"
        if base in ('hundred_thousand', 'thousand'):
            return f"{kz_words(n)} мың"
        if base == 'tenge':
            return f"{kz_words(n)} теңге"
        if base == 'day':
            return kz_ordinal(n)
        if base == 'year':
            return f"{kz_words(n)} жылғы"
        return kz_words(n)
    if base == 'million':
        return f"{ru_words(n)} {ru_plural(n, 'миллион', 'миллиона', 'миллионов')}"
    if base == 'hundred_thousand':
        return f"{ru_words(n, fem=True)} {ru_plural(n, 'тысяча', 'тысячи', 'тысяч')}"
    if base == 'thousand':
        return f"{ru_words(n, fem=True)} {ru_plural(n, 'тысяча', 'тысячи', 'тысяч')}"
    if base == 'tenge':
        return f"{ru_words(n)} тенге"
    if base == 'day':
        return ru_day_genitive(n)
    if base == 'year':
        return ru_year_genitive(n)
    return ru_words(n)
