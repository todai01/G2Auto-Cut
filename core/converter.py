import os
import webview
from pydub import AudioSegment


class ConverterMixin:
    """Простой конвертер: MP4 -> MP3 или WAV с выбором герцовки (44100/8000)."""

    def pick_convert_source(self):
        files = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=('Видео MP4 (*.mp4)', 'Все файлы (*.*)')
        )
        if not files:
            return {"files": [], "count": 0}
        self._convert_source_files = list(files)
        return {"files": [os.path.basename(f) for f in self._convert_source_files],
                "count": len(self._convert_source_files)}

    def pick_convert_output_dir(self):
        folder = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
        if not folder:
            return {"path": ""}
        self._convert_output_dir = folder[0]
        return {"path": self._convert_output_dir}

    def run_conversion(self, out_format, hz):
        src_files = getattr(self, '_convert_source_files', None)
        out_dir = getattr(self, '_convert_output_dir', None)
        if not src_files:
            return {"error": "Сначала выберите исходные MP4-файлы."}
        if not out_dir:
            return {"error": "Сначала выберите папку, куда сохранять."}

        try:
            hz = int(hz)
        except (TypeError, ValueError):
            hz = 44100
        out_format = 'mp3' if str(out_format).lower() == 'mp3' else 'wav'

        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            return {"error": f"Не удалось подготовить папку для сохранения: {e}"}

        done, errors, output_files = 0, [], []
        for path in src_files:
            try:
                audio = AudioSegment.from_file(path)
                name = os.path.splitext(os.path.basename(path))[0] + '.' + out_format
                target = os.path.join(out_dir, name)
                # Смену герцовки отдаём ffmpeg (-ar), а не pydub'у: встроенный
                # в pydub set_frame_rate() пересчитывает частоту «в лоб», без
                # сглаживающего фильтра — отсюда и цифровые/роботские
                # искажения, особенно заметные при сильном понижении (например,
                # до 8000 Гц). ffmpeg делает это через качественный ресемплер.
                export_kwargs = {"parameters": ["-ar", str(hz)]}
                if out_format == 'mp3':
                    export_kwargs["bitrate"] = "192k"
                audio.export(target, format=out_format, **export_kwargs)
                done += 1
                output_files.append(target)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")

        return {"done": done, "total": len(src_files), "errors": errors, "output_files": output_files}
