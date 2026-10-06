"""Встроенный редактор тайминга для режима «Суммы».

Собирает текущую строку таблицы так же, как «Собрать в Audacity»
(связки start/end + значения категорий, см. _constructor_ordered_segments),
но правка идёт прямо в программе: у каждого значения можно подвинуть
начало и конец мышью, прослушать сборку с учётом обрезки и сохранить
эталон в «Проверенные» — без Audacity."""

import os
import tempfile
import time

from pydub import AudioSegment

EDITOR_RATE = 8000          # как SetProject: Rate=8000 в сборке через Audacity
PEAK_BUCKET_MS = 10
MIN_KEEP_MS = 40


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

    def sum_editor_load(self, indices=None):
        """Сегменты текущей строки с волной для отрисовки."""
        segments = self._constructor_ordered_segments(indices or {})
        if not segments:
            missing = getattr(self, 'sum_stage2_missing', None) or []
            return {"segments": [], "missing": missing}

        row = self._sum_stage2_current_row() if getattr(self, 'var_template_columns', None) else {}
        cache = []
        out = []
        for key, path, saveable in segments:
            try:
                audio = self._editor_audio(path)
            except Exception as e:
                return {"error": f"Не удалось открыть {os.path.basename(path)}: {e}"}
            is_connector = key not in self._all_category_keys()
            cache.append({"key": key, "path": path, "saveable": saveable,
                          "connector": is_connector, "audio": audio})
            out.append({
                "key": key,
                "label": key if is_connector else self._category_label(key),
                "value": None if is_connector else (row.get(key) or self._sum_raw_value_from_path(path)),
                "connector": is_connector,
                "saveable": bool(saveable),
                "duration_ms": len(audio),
                "peaks": self._editor_peaks(audio),
            })
        self._sum_editor = {"segments": cache, "row_idx": getattr(self, 'sum_stage2_row_idx', 0)}
        return {"segments": out, "bucket_ms": PEAK_BUCKET_MS,
                "missing": getattr(self, 'sum_stage2_missing', None) or []}

    def _editor_trimmed(self, trims):
        """Сегменты с учётом обрезки: trims = {номер сегмента: [начало_мс, конец_мс]}."""
        editor = getattr(self, '_sum_editor', None)
        if not editor:
            return None
        parts = []
        for i, seg in enumerate(editor["segments"]):
            audio = seg["audio"]
            t = (trims or {}).get(str(i)) or (trims or {}).get(i)
            if t and not seg["connector"]:
                a = max(0, min(int(t[0]), len(audio)))
                b = max(a + MIN_KEEP_MS, min(int(t[1]), len(audio)))
                audio = audio[a:b]
            parts.append((seg, audio))
        return parts

    def sum_editor_play(self, trims, from_ms=0):
        """Прослушать сборку с обрезкой, начиная с from_ms (по итоговой сборке)."""
        parts = self._editor_trimmed(trims)
        if not parts:
            return {"error": "Редактор пуст — нет сборки для этой строки."}
        combined = AudioSegment.silent(duration=0, frame_rate=EDITOR_RATE)
        for _, audio in parts:
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

    def sum_editor_save(self, trims):
        """Сохранить эталон строки: каждое значение — с его обрезкой — в
        «Проверенные». Сырые значения сохраняются всегда (как «Сохранить
        эталон» через Audacity), уже готовые — только если их подрезали."""
        editor = getattr(self, '_sum_editor', None)
        if not editor:
            return {"error": "Редактор пуст — нет сборки для этой строки."}
        if editor.get("row_idx") != getattr(self, 'sum_stage2_row_idx', 0):
            return {"error": "Строка таблицы сменилась — откройте редактор заново."}
        parts = self._editor_trimmed(trims)

        saved = {}
        for i, (seg, audio) in enumerate(parts):
            if seg["connector"]:
                continue
            trimmed = bool((trims or {}).get(str(i)) or (trims or {}).get(i)) and len(audio) != len(seg["audio"])
            if not seg["saveable"] and not trimmed:
                continue
            tier, path = seg["key"], seg["path"]
            if seg["saveable"]:
                target, name = self._sum_checked_target(tier, path)
            else:
                target, name = path, os.path.basename(path)
            ext = os.path.splitext(target)[1].lstrip('.').lower() or 'wav'
            try:
                audio.export(target, format=ext)
            except Exception as e:
                return {"error": f"Не удалось сохранить «{name}»: {e}"}

            if seg["saveable"]:
                try:
                    os.remove(path)
                except OSError:
                    pass
                files = (getattr(self, 'constructor_tier_files', None) or {}).get(tier, [])
                if path in files:
                    files.remove(path)
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
