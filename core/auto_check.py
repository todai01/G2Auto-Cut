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
from concurrent.futures import ThreadPoolExecutor

import webview

AUTO_CHECK_THRESHOLD = 0.80   # совпадение, начиная с которого дубль «зелёный»
AUTO_CHECK_MARGIN = 0.10      # насколько лучший вариант должен опережать второй
MODEL_DIR_NAME = 'whisper-model'
DEFAULT_MODEL = 'small'
MODEL_PATH_FILE = os.path.join(os.path.expanduser('~'), '.gvox', 'whisper_model_path.txt')
# Казахский: small распознаёт его плохо — отдельная, более крупная модель.
# Своя папка (запоминается) или «whisper-model-kz» рядом с программой;
# иначе — скачать large-v3-turbo (~1,6 ГБ, один раз).
KZ_MODEL = 'mobiuslabsgmbh/faster-whisper-large-v3-turbo'
KZ_MODEL_DIR_NAME = 'whisper-model-kz'
KZ_MODEL_PATH_FILE = os.path.join(os.path.expanduser('~'), '.gvox', 'whisper_model_path_kz.txt')
NEED_MODEL = object()   # модель не скачалась и локальной нет — спросить папку

ASR_RATE = 16000        # Whisper работает на 16 кГц
PACK_MAX_SEC = 24.0     # дубли склеиваются в окна до ~24 с (модель всё равно считает окно 30 с)
PACK_GAP_SEC = 1.0      # тишина между дублями внутри окна
CLIP_SOLO_SEC = 10.0    # длинный дубль идёт отдельным окном
NOISE_MIN_MS = 150      # короче — точно не слово
NOISE_MAX_DBFS = -42.0  # тише пика -42 дБ — тишина/фон, распознавать незачем
SPEECH_MIN_SCORE = 0.45 # ниже — распознанное ни на что не похоже, считаем шумом
# Фразы, которые Whisper «придумывает» на тишине и шуме.
_HALLUCINATIONS = ('продолжение следует', 'субтитр', 'спасибо за просмотр', 'спасибо за внимание',
                   'подписывайтесь', 'редактор', 'торзок', 'thank you', 'thanks for watching',
                   'altyazı', 'izlediğiniz için')

_LAT2CYR = [
    ('shch', 'щ'), ('sch', 'щ'), ('sh', 'ш'), ('ch', 'ч'), ('zh', 'ж'), ('kh', 'х'), ('ts', 'ц'),
    ('yu', 'ю'), ('ya', 'я'), ('yo', 'ё'), ('ee', 'и'), ('oo', 'у'), ('ph', 'ф'), ('th', 'т'),
    ('a', 'а'), ('b', 'б'), ('c', 'к'), ('d', 'д'), ('e', 'е'), ('f', 'ф'), ('g', 'г'), ('h', 'х'),
    ('i', 'и'), ('j', 'дж'), ('k', 'к'), ('l', 'л'), ('m', 'м'), ('n', 'н'), ('o', 'о'), ('p', 'п'),
    ('q', 'к'), ('r', 'р'), ('s', 'с'), ('t', 'т'), ('u', 'у'), ('v', 'в'), ('w', 'в'), ('x', 'кс'),
    ('y', 'й'), ('z', 'з'),
]


# Казахские буквы → похожие русские: Whisper и таблица пишут их по-разному
# («қ»/«к», «і»/«и», «ү»/«у»), сравниваем без этой разницы. Латиница
# казахского алфавита 2021 года — туда же.
_KZ_FOLD = str.maketrans({'ә': 'а', 'ғ': 'г', 'қ': 'к', 'ң': 'н', 'ө': 'о', 'ұ': 'у', 'ү': 'у', 'һ': 'х', 'і': 'и',
                          'ä': 'а', 'ğ': 'г', 'ñ': 'н', 'ö': 'о', 'ū': 'у', 'ü': 'у', 'ı': 'ы', 'ş': 'ш'})


def fix_feature_size(model, n_mels=None):
    """large-v3 / turbo и дообученные на них модели слушают 128 мел-полос, а
    не 80. Число faster-whisper берёт из preprocessor_config.json; если его в
    папке модели нет — ставит 80, и распознавание падает с «expected an input
    with shape (1, 128, 3000)». Сверяем с самой моделью и чиним. True — поправили."""
    try:
        n = int(n_mels or getattr(getattr(model, 'model', None), 'n_mels', 0) or 0)
        fe = getattr(model, 'feature_extractor', None)
        if not n or fe is None or getattr(fe, 'mel_filters', None) is None or fe.mel_filters.shape[0] == n:
            return False
        from faster_whisper.feature_extractor import FeatureExtractor
        kw = dict(getattr(model, 'feat_kwargs', None) or {})
        kw['feature_size'] = n
        try:
            model.feature_extractor = FeatureExtractor(**kw)
        except TypeError:
            model.feature_extractor = FeatureExtractor(feature_size=n)
        if hasattr(model, 'feat_kwargs'):
            model.feat_kwargs = kw
        return True
    except Exception:
        return False


def mels_from_error(err):
    """«expected an input with shape (1, 128, 3000)» → 128."""
    m = re.search(r'expected an input with shape \(\d+,\s*(\d+),', str(err))
    return int(m.group(1)) if m else None


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
    return ''.join(out).replace('ё', 'е').translate(_KZ_FOLD)


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

    def _auto_check_model_path(self, lang=None):
        """Папка с моделью: та, что юзер указал сам (запоминается), или
        «whisper-model» рядом с программой (для казахского — свои)."""
        kz = lang == 'kz'
        try:
            with open(KZ_MODEL_PATH_FILE if kz else MODEL_PATH_FILE, 'r', encoding='utf-8') as f:
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
            p = os.path.join(base, KZ_MODEL_DIR_NAME if kz else MODEL_DIR_NAME)
            if self._is_model_dir(p):
                return p
        return None

    def sum_auto_check_pick_model(self, lang=None):
        """Указать папку с уже скачанной моделью (если интернет закрыт).
        lang='kz' — модель для казахского (хранится отдельно)."""
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not picked:
            return {"error": "cancel"}
        folder = picked[0]
        if not self._is_model_dir(folder):
            return {"error": "В этой папке нет файлов модели (нужны model.bin, config.json, "
                              "tokenizer.json, vocabulary.txt)."}
        kz = lang == 'kz'
        try:
            os.makedirs(os.path.dirname(MODEL_PATH_FILE), exist_ok=True)
            with open(KZ_MODEL_PATH_FILE if kz else MODEL_PATH_FILE, 'w', encoding='utf-8') as f:
                f.write(folder)
        except OSError:
            pass
        if kz:
            self._asr_model_kz = None
        else:
            self._asr_model = None
        return {"status": "ok", "path": folder}

    def _auto_check_model(self, lang=None):
        kz = lang == 'kz'
        slot = '_asr_model_kz' if kz else '_asr_model'
        model = getattr(self, slot, None)
        if model is not None:
            self._asr_workers = getattr(model, '_gvox_workers', 1)
            return model, None
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return None, ("Не установлен модуль распознавания речи. В командной строке выполните:\n"
                          "pip install faster-whisper")
        local = self._auto_check_model_path(lang)
        cores = os.cpu_count() or 2
        if kz:
            # Крупная модель: одна очередь и одно ядро в запасе под запись и
            # прослушку (у них теперь большой буфер — этого хватает).
            workers, threads = 1, max(2, cores - 1)
        else:
            workers = 2 if cores >= 4 else 1
            threads = max(1, cores // workers)
        try:
            model = WhisperModel(local or (KZ_MODEL if kz else DEFAULT_MODEL), device='cpu', compute_type='int8',
                                 cpu_threads=threads, num_workers=workers)
        except Exception as e:
            if local:
                return None, f"Не удалось загрузить модель из папки «{local}».\n\n{e}"
            return None, NEED_MODEL
        fix_feature_size(model)
        model._gvox_workers = workers
        self._asr_workers = workers
        setattr(self, slot, model)
        return model, None

    def _auto_check_push(self, payload):
        try:
            webview.windows[0].evaluate_js(f"sumAutoCheckProgress({json.dumps(payload, ensure_ascii=False)})")
        except Exception:
            pass

    @staticmethod
    def _asr_load(path):
        """Дубль как float32 16 кГц моно + длительность и пик (дБ)."""
        import numpy as np
        from pydub import AudioSegment
        seg = AudioSegment.from_file(path).set_channels(1).set_frame_rate(ASR_RATE).set_sample_width(2)
        samples = np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0
        return samples, len(seg), seg.max_dBFS

    @staticmethod
    def _asr_packs(items):
        """Склеивает короткие дубли в окна до PACK_MAX_SEC — модель считает
        каждое окно как 30 с, так что один проход на 10 дублей вместо 10."""
        packs, cur, cur_len = [], [], 0.0
        for it in items:
            d = it['ms'] / 1000.0
            if d >= CLIP_SOLO_SEC:
                packs.append([it])
                continue
            if cur and cur_len + PACK_GAP_SEC + d > PACK_MAX_SEC:
                packs.append(cur)
                cur, cur_len = [], 0.0
            cur_len += (PACK_GAP_SEC if cur else 0.0) + d
            cur.append(it)
        if cur:
            packs.append(cur)
        return packs

    def _asr_transcribe_pack(self, model, pack, language):
        """Распознаёт окно и раскладывает слова обратно по дублям по времени."""
        import numpy as np
        gap = np.zeros(int(PACK_GAP_SEC * ASR_RATE), dtype=np.float32)
        parts, spans, t = [], [], 0.0
        for k, it in enumerate(pack):
            if k:
                parts.append(gap)
                t += PACK_GAP_SEC
            parts.append(it['audio'])
            d = len(it['audio']) / ASR_RATE
            spans.append((t, t + d))
            t += d
        audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
        segments, _info = model.transcribe(
            audio, language=None if language == 'auto' else language,
            beam_size=1, best_of=1, word_timestamps=True, vad_filter=True,
            condition_on_previous_text=False)
        words = [[] for _ in pack]
        for seg in segments:
            # Кусок, который сама модель считает «не речью», — выдумка на шуме.
            if getattr(seg, 'no_speech_prob', 0) > 0.6 and getattr(seg, 'avg_logprob', 0) < -0.7:
                continue
            for w in (seg.words or []):
                mid = (w.start + w.end) / 2
                for k, (a, b) in enumerate(spans):
                    if a - 0.3 <= mid <= b + 0.3:
                        words[k].append(w.word)
                        break
        return [''.join(ws).strip() for ws in words]

    @staticmethod
    def _asr_is_noise(heard):
        low = _norm(heard)
        return len(low.replace(' ', '')) < 2 or any(h in low for h in _HALLUCINATIONS)

    def sum_auto_check(self, tier, indices, language='ru'):
        """Распознать дубли и сверить со значениями категории tier.
        indices=None — все ещё не разобранные и не проверенные дубли списка."""
        values = (getattr(self, 'var_extra_tag_values', None) or {}).get(tier) or []
        if not values:
            return {"error": "Для этой категории в таблице нет списка значений."}
        files, _ = self._sum_source_files()
        if not isinstance(getattr(self, 'sum_asr_results', None), dict):
            self.sum_asr_results = {}
        if indices is None:
            assigned = self._sum_assigned_sources()
            indices = [i for i, p in enumerate(files)
                       if p not in assigned and (self.sum_asr_results.get(p) or {}).get('tier') != tier]
        indices = sorted({int(i) for i in (indices or []) if 0 <= int(i) < len(files)})
        if not indices:
            return {"error": "Нет дублей для проверки — все уже разобраны или проверены."}
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
            self._auto_check_stop = False
            total = len(indices)
            progress = {"done": 0}
            finish_lock = threading.Lock()

            def finish(i, heard, noise=False, err_text=None):
                scored = score_candidates(heard, values, transcripts) if heard and not noise else []
                best, best_score = scored[0] if scored else (None, 0.0)
                second = scored[1][1] if len(scored) > 1 else 0.0
                if not noise and heard and best_score < SPEECH_MIN_SCORE:
                    noise = True
                confident = (not noise and best_score >= AUTO_CHECK_THRESHOLD
                             and best_score - second >= AUTO_CHECK_MARGIN)
                result = {"tier": tier, "heard": heard, "best": None if noise else best,
                          "score": round(best_score, 3), "second": round(second, 3),
                          "confident": confident, "noise": noise, "error": err_text}
                with finish_lock:
                    self.sum_asr_results[files[i]] = result
                    progress["done"] += 1
                    done = progress["done"]
                self._auto_check_push({"index": i, "path": files[i], "done": done, "total": total, **result})

            # 1) Быстрый отсев: слишком короткое или тихое — шум без распознавания.
            items = []
            for i in indices:
                if self._auto_check_stop:
                    break
                try:
                    audio, ms, peak = self._asr_load(files[i])
                except Exception as e:
                    finish(i, '', err_text=str(e))
                    continue
                if ms < NOISE_MIN_MS or peak < NOISE_MAX_DBFS:
                    finish(i, '', noise=True)
                else:
                    items.append({"index": i, "audio": audio, "ms": ms})

            # 2) Остальное — окнами, параллельно.
            def run(pack):
                if self._auto_check_stop:
                    return
                try:
                    heard_list = self._asr_transcribe_pack(model, pack, language)
                except Exception as e:
                    for it in pack:
                        finish(it['index'], '', err_text=str(e))
                    return
                for it, heard in zip(pack, heard_list):
                    finish(it['index'], heard, noise=self._asr_is_noise(heard))

            with ThreadPoolExecutor(max_workers=getattr(self, '_asr_workers', 1)) as ex:
                list(ex.map(run, self._asr_packs(items)))
            try:
                from core import project_state
                project_state.save(self)
            except Exception:
                pass
            return {"status": "ok", "done": progress["done"], "total": total, "stopped": self._auto_check_stop}
        finally:
            lock.release()

    def sum_auto_check_stop(self):
        self._auto_check_stop = True
        return {"status": "ok"}
