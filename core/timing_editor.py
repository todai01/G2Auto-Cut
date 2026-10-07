"""Встроенный редактор тайминга для режима «Суммы».

Собирает текущую строку таблицы (связки start/end + значения категорий)
одной дорожкой. Правка прямо в программе: у каждого значения можно
подвинуть начало и конец мышью, поменять громкость, подставить в слот
любую другую запись (чип из категории или дубль из ленты), прослушать
сборку и сохранить эталон в «Проверенные» — без Audacity."""

import os
import tempfile
import time

from pydub import AudioSegment

EDITOR_RATE = 8000          # как SetProject: Rate=8000 в сборке через Audacity
PEAK_BUCKET_MS = 10
MIN_KEEP_MS = 40
GAIN_LIMIT_DB = 20


class TimingEditorMixin:

    def _editor_audio(self, path):
        return AudioSegment.from_file(path).set_frame_rate(EDITOR_RATE).set_channels(1).set_sample_width(2)

    @staticmethod
    def _editor_peaks(audio):
        samples = audio.get_array_of_samples()
        per = max(1, int(EDITOR_RATE * PEAK_BUCKET_MS / 1000))
        full = float(1 << (8 * audio.sample_width - 1))
        return [round(max(max(samples[i:i + per]), -min(samples[i:i + per])) / full, 3)
                for i in range(0, len(samples), per)]

    def _editor_overrides(self):
        """Подставленные вручную записи {категория: путь} — только для той
        строки таблицы, на которой их подставили."""
        ov = getattr(self, '_sum_editor_overrides', None)
        row_idx = getattr(self, 'sum_stage2_row_idx', 0)
        if not ov or ov.get('row_idx') != row_idx:
            self._sum_editor_overrides = {'row_idx': row_idx, 'slots': {}}
        return self._sum_editor_overrides['slots']

    def _editor_slots(self, indices):
        """[(ключ, путь|None, saveable, связка?, значение)] — со словарём
        включая значения строки, для которых ещё нет записи (пустой слот,
        куда можно бросить запись)."""
        columns = getattr(self, 'var_template_columns', None)
        if not columns:
            return [(k, p, sv, k not in self._all_category_keys(), self._sum_raw_value_from_path(p))
                    for k, p, sv in self._constructor_ordered_segments(indices or {})]

        overrides = self._editor_overrides()
        connectors = {c['key']: c.get('path') for c in getattr(self, 'var_connectors', [])}
        row = self._sum_stage2_current_row()
        slots = []
        for col in columns:
            key = col['key']
            if col['type'] == 'connector':
                path = connectors.get(key)
                if path and os.path.exists(path):
                    slots.append((key, path, False, True, None))
                continue
            value = row.get(key)
            if not value:
                continue
            if overrides.get(key):
                slots.append((key, overrides[key], True, False, value))
                continue
            path, saveable = self._sum_stage2_resolve_value(key, value)
            slots.append((key, path, bool(saveable), False, value))
        return slots

    def sum_editor_load(self, indices=None):
        """Сегменты текущей строки с волной для отрисовки."""
        slots = self._editor_slots(indices)
        overrides = self._editor_overrides() if getattr(self, 'var_template_columns', None) else {}
        cache, out, missing = [], [], []
        for key, path, saveable, is_connector, value in slots:
            audio = None
            if path:
                try:
                    audio = self._editor_audio(path)
                except Exception as e:
                    return {"error": f"Не удалось открыть {os.path.basename(path)}: {e}"}
            label = key if is_connector else self._category_label(key)
            if audio is None:
                missing.append(f"{label}: {value}")
            source = None
            if key in overrides and path:
                stem = os.path.splitext(os.path.basename(path))[0]
                source = self._sum_raw_value_from_path(path) if '_сырая_' in stem else stem
                if source == value:
                    source = None
            cache.append({"key": key, "path": path, "saveable": saveable, "connector": is_connector,
                          "audio": audio, "value": value, "override": key in overrides})
            out.append({
                "key": key,
                "label": label,
                "value": value,
                "source": source,
                "connector": is_connector,
                "saveable": bool(saveable),
                "missing": audio is None,
                "duration_ms": len(audio) if audio is not None else 0,
                "peaks": self._editor_peaks(audio) if audio is not None else [],
            })
        self._sum_editor = {"segments": cache, "row_idx": getattr(self, 'sum_stage2_row_idx', 0)}
        return {"segments": out, "bucket_ms": PEAK_BUCKET_MS, "missing": missing}

    def sum_editor_set_slot(self, key, path=None, dub_index=None, indices=None):
        """Подставить в слот категории key запись: путь (чип из категории)
        или дубль из ленты по номеру. Возвращает обновлённую сборку."""
        if key not in self._all_category_keys():
            return {"error": "Сюда можно бросить только в слот категории."}
        if not getattr(self, 'var_template_columns', None):
            return {"error": "Подстановка в сборку работает с таблицей-словарём."}
        if dub_index is not None:
            files, _ = self._sum_source_files()
            if not 0 <= int(dub_index) < len(files):
                return {"error": "Такого дубля нет."}
            path = files[int(dub_index)]
        if not path or not os.path.exists(path):
            return {"error": "Файл записи не найден."}
        self._editor_overrides()[key] = path
        return self.sum_editor_load(indices)

    def sum_editor_clear_slots(self, indices=None):
        self._editor_overrides().clear()
        return self.sum_editor_load(indices)

    @staticmethod
    def _editor_get(d, i):
        return (d or {}).get(str(i)) if (d or {}).get(str(i)) is not None else (d or {}).get(i)

    def _editor_trimmed(self, trims, gains=None):
        """Сегменты с учётом обрезки и громкости:
        trims = {номер: [начало_мс, конец_мс]}, gains = {номер: дБ}."""
        editor = getattr(self, '_sum_editor', None)
        if not editor:
            return None
        parts = []
        for i, seg in enumerate(editor["segments"]):
            audio = seg["audio"]
            if audio is None:
                continue
            if not seg["connector"]:
                t = self._editor_get(trims, i)
                if t:
                    a = max(0, min(int(t[0]), len(audio)))
                    b = max(a + MIN_KEEP_MS, min(int(t[1]), len(audio)))
                    audio = audio[a:b]
                g = self._editor_get(gains, i)
                if g:
                    audio = audio.apply_gain(max(-GAIN_LIMIT_DB, min(GAIN_LIMIT_DB, float(g))))
            parts.append((i, seg, audio))
        return parts

    def sum_editor_play(self, trims, from_ms=0, gains=None):
        """Прослушать сборку с обрезкой и громкостью, начиная с from_ms (по итоговой сборке)."""
        parts = self._editor_trimmed(trims, gains)
        if not parts:
            return {"error": "Редактор пуст — нет сборки для этой строки."}
        combined = AudioSegment.silent(duration=0, frame_rate=EDITOR_RATE)
        for _, _, audio in parts:
            combined += audio
        from_ms = max(0, min(int(from_ms or 0), len(combined) - 1))
        piece = combined[from_ms:]
        try:
            self.player.stop()
            old = getattr(self, '_editor_temp', None)
            if old and os.path.exists(old):
                try: os.remove(old)
                except OSError: pass
            temp = os.path.join(tempfile.gettempdir(), f"gvox_editor_{time.time_ns()}.wav")
            piece.export(temp, format="wav")
            self._editor_temp = temp
            self.player.play(temp)
        except Exception as e:
            return {"error": f"Не удалось проиграть: {e}"}
        return {"playing": True, "duration": len(piece) / 1000.0, "from_ms": from_ms}

    def sum_editor_save(self, trims, gains=None):
        """Сохранить эталон строки: каждое значение — с его обрезкой и
        громкостью — в «Проверенные». Сырые и подставленные вручную
        значения сохраняются всегда, уже готовые — только если их меняли."""
        editor = getattr(self, '_sum_editor', None)
        if not editor:
            return {"error": "Редактор пуст — нет сборки для этой строки."}
        if editor.get("row_idx") != getattr(self, 'sum_stage2_row_idx', 0):
            return {"error": "Строка таблицы сменилась — откройте редактор заново."}
        parts = self._editor_trimmed(trims, gains)

        raw_files = getattr(self, 'constructor_tier_files', None) or {}
        saved = {}
        for i, seg, audio in parts:
            if seg["connector"]:
                continue
            changed = len(audio) != len(seg["audio"]) or bool(self._editor_get(gains, i))
            if not seg["saveable"] and not changed:
                continue
            tier, path = seg["key"], seg["path"]
            if seg["saveable"]:
                # Имя — значение СЛОТА строки таблицы, даже если подставили
                # запись, присвоенную другому значению.
                target, name = self._sum_checked_target(tier, path, name_override=seg["value"])
            else:
                target, name = path, os.path.basename(path)
            ext = os.path.splitext(target)[1].lstrip('.').lower() or 'wav'
            try:
                audio.export(target, format=ext)
            except Exception as e:
                return {"error": f"Не удалось сохранить «{name}»: {e}"}

            if seg["saveable"]:
                tier_raw = raw_files.get(tier, [])
                if path in tier_raw:
                    # Сырая запись использована — убираем из категории.
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    tier_raw.remove(path)
                elif seg.get("override"):
                    # Дубль из ленты — сам файл не трогаем, но помечаем
                    # его разобранным, чтобы было видно на карточке.
                    self._sum_remember_source(target, path, tier)
                counts = getattr(self, 'sum_stage2_counts', None) or {}
                counts[tier] = counts.get(tier, 0) + 1
                self.sum_stage2_counts = counts
            if not hasattr(self, 'sum_manual_last_file'):
                self.sum_manual_last_file = {}
            self.sum_manual_last_file[tier] = target
            saved[tier] = name

        if getattr(self, 'var_template_columns', None):
            self._sum_stage2_advance_row()
        else:
            self._sum_stage2_advance()
        self._sum_editor = None

        if saved:
            summary = ', '.join(f'{self._category_label(t)} → {n}' for t, n in saved.items())
            self._sum_toast(f'💾 Сохранено: {summary}')
        else:
            self._sum_toast('Эта строка уже была готова — перешли к следующей.')
        return self.get_ui_state()
