"""Автопроверка дублей (прототип).

Каждый выбранный дубль распознаётся локально (faster-whisper, без
интернета, если модель лежит рядом с программой) и сверяется со всеми
значениями выбранной категории — по транскрипции из таблицы-словаря
(колонка «<mark_транскрипция>»), а если её нет — по самому значению.
Прототип ничего не сохраняет сам: только показывает на карточках, что
распознано и на сколько процентов совпало, чтобы подобрать порог."""

import difflib
import json
import os
import re
import sys
import threading

import webview

AUTO_CHECK_THRESHOLD = 0.80   # совпадение, начиная с которого дубль «зелёный»
AUTO_CHECK_MARGIN = 0.10      # насколько лучший вариант должен опережать второй
MODEL_DIR_NAME = 'whisper-model'
DEFAULT_MODEL = 'small'
MODEL_PATH_FILE = os.path.join(os.path.expanduser('~'), '.gvox', 'whisper_model_path.txt')
NEED_MODEL = object()   # модель не скачалась и локальной нет — спросить папку

_LAT2CYR = [
    ('shch', 'щ'), ('sch', 'щ'), ('sh', 'ш'), ('ch', 'ч'), ('zh', 'ж'), ('kh', 'х'), ('ts', 'ц'),
    ('yu', 'ю'), ('ya', 'я'), ('yo', 'ё'), ('ee', 'и'), ('oo', 'у'), ('ph', 'ф'), ('th', 'т'),
    ('a', 'а'), ('b', 'б'), ('c', 'к'), ('d', 'д'), ('e', 'е'), ('f', 'ф'), ('g', 'г'), ('h', 'х'),
    ('i', 'и'), ('j', 'дж'), ('k', 'к'), ('l', 'л'), ('m', 'м'), ('n', 'н'), ('o', 'о'), ('p', 'п'),
    ('q', 'к'), ('r', 'р'), ('s', 'с'), ('t', 'т'), ('u', 'у'), ('v', 'в'), ('w', 'в'), ('x', 'кс'),
    ('y', 'й'), ('z', 'з'),
]


def _norm(text):
    text = (text or '').lower().replace('ё', 'е')
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _lat_to_cyr(text):
    out, i = [], 0
    while i < len(text):
        for lat, cyr in _LAT2CYR:
            if text.startswith(lat, i):
                out.append(cyr)
                i += len(lat)
                break
        else:
            out.append(text[i])
            i += 1
    return ''.join(out).replace('ё', 'е')


def _ratio(a, b):
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.replace(' ', ''), b.replace(' ', '')).ratio()


def similarity(heard, target):
    """Насколько распознанный текст похож на целевую фразу (0..1). Сравниваем
    и целиком, и с каждым «окном» из похожего числа слов — на случай, если в
    дубль попало лишнее слово («на автомобиль Хендай Авант»). Латиницу с
    обеих сторон переводим в кириллицу: Whisper иногда пишет марку
    латиницей, а транскрипция в таблице — кириллицей."""
    h = _lat_to_cyr(_norm(heard))
    t = _lat_to_cyr(_norm(target))
    if not h or not t:
        return 0.0
    best = _ratio(h, t)
    hw, n = h.split(), max(1, len(t.split()))
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(hw) - size + 1)):
            best = max(best, _ratio(' '.join(hw[i:i + size]), t))
    return best


def score_candidates(heard, values, transcripts):
    """[(значение, совпадение)] по убыванию — по транскрипции и по самому значению."""
    scored = []
    for v in values:
        targets = [v] + ([transcripts[v]] if transcripts.get(v) else [])
        scored.append((v, max(similarity(heard, t) for t in targets)))
    scored.sort(key=lambda x: -x[1])
    return scored


class AutoCheckMixin:

    @staticmethod
    def _is_model_dir(path):
        return bool(path) and os.path.isfile(os.path.join(path, 'model.bin')) \
            and os.path.isfile(os.path.join(path, 'config.json'))

    def _auto_check_model_path(self):
        """Папка с моделью: та, что юзер указал сам (запоминается), или
        «whisper-model» рядом с программой."""
        try:
            with open(MODEL_PATH_FILE, 'r', encoding='utf-8') as f:
                saved = f.read().strip()
            if self._is_model_dir(saved):
                return saved
        except OSError:
            pass
        bases = [os.path.dirname(os.path.abspath(sys.argv[0])), os.getcwd(),
                 os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
        if getattr(sys, 'frozen', False):
            bases.insert(0, os.path.dirname(sys.executable))
        for base in bases:
            p = os.path.join(base, MODEL_DIR_NAME)
            if self._is_model_dir(p):
                return p
        return None

    def sum_auto_check_pick_model(self):
        """Указать папку с уже скачанной моделью (если интернет закрыт)."""
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        folder = picked[0]
        if not self._is_model_dir(folder):
            return {"error": "В этой папке нет файлов модели (нужны model.bin, config.json, "
                              "tokenizer.json, vocabulary.txt)."}
        try:
            os.makedirs(os.path.dirname(MODEL_PATH_FILE), exist_ok=True)
            with open(MODEL_PATH_FILE, 'w', encoding='utf-8') as f:
                f.write(folder)
        except OSError:
            pass
        self._asr_model = None
        return {"status": "ok", "path": folder}

    def _auto_check_model(self):
        model = getattr(self, '_asr_model', None)
        if model is not None:
            return model, None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return None, ("Не установлен модуль распознавания речи. В командной строке выполните:\n"
                          "pip install faster-whisper")
        local = self._auto_check_model_path()
        try:
            model = WhisperModel(local or DEFAULT_MODEL, device='cpu', compute_type='int8')
        except Exception as e:
            if local:
                return None, f"Не удалось загрузить модель из папки «{local}».\n\n{e}"
            return None, NEED_MODEL
        self._asr_model = model
        return model, None

    def _auto_check_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"sumAutoCheckProgress({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    def sum_auto_check(self, tier, indices, language='ru'):
        """Распознать выбранные дубли и сверить со значениями категории tier."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(tier) or []
        if not values:
            return {"error": "Для этой категории в таблице нет списка значений."}
        files, _ = self._sum_source_files()
        indices = sorted({int(i) for i in (indices or []) if 0 <= int(i) < len(files)})
        if not indices:
            return {"error": "Нет дублей для проверки."}
        lock = getattr(self, '_auto_check_lock', None)
        if lock is None:
            lock = self._auto_check_lock = threading.Lock()
        if not lock.acquire(blocking=False):
            return {"error": "Автопроверка уже идёт."}
        try:
            model, err = self._auto_check_model()
            if err is NEED_MODEL:
                return {"need_model": True}
            if err:
                return {"error": err}
            transcripts = (getattr(self, 'var_transcripts', None) or {}).get(tier, {})
            expected, _ = self._var_expected_value(tier)
            if not isinstance(getattr(self, 'sum_asr_results', None), dict):
                self.sum_asr_results = {}
            self._auto_check_stop = False
            done = 0
            for n, i in enumerate(indices):
                if self._auto_check_stop:
                    break
                path = files[i]
                try:
                    segments, _info = model.transcribe(path, language=None if language == 'auto' else language,
                                                       beam_size=5, without_timestamps=True,
                                                       condition_on_previous_text=False)
                    heard = ' '.join(s.text for s in segments).strip()
                except Exception as e:
                    heard, err_text = '', str(e)
                else:
                    err_text = None
                scored = score_candidates(heard, values, transcripts) if heard else []
                best, best_score = scored[0] if scored else (None, 0.0)
                second = scored[1][1] if len(scored) > 1 else 0.0
                confident = best_score >= AUTO_CHECK_THRESHOLD and best_score - second >= AUTO_CHECK_MARGIN
                result = {
                    "tier": tier, "heard": heard, "best": best, "score": round(best_score, 3),
                    "second": round(second, 3), "confident": confident,
                    "is_expected": bool(best and best == expected), "error": err_text,
                }
                self.sum_asr_results[path] = result
                done += 1
                self._auto_check_push({"index": i, "path": path, "done": n + 1, "total": len(indices), **result})
            return {"status": "ok", "done": done, "total": len(indices), "stopped": self._auto_check_stop}
        finally:
            lock.release()

    def sum_auto_check_stop(self):
        self._auto_check_stop = True
        return {"status": "ok"}
