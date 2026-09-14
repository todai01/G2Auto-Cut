import os
import wave
import contextlib

class FileUtils:
    @staticmethod
    def get_sorted_path(base_folder, filename):
        """Плоское сохранение: возвращает путь прямо в базовую папку без сортировки по подпапкам."""
        os.makedirs(base_folder, exist_ok=True)
        return os.path.join(base_folder, filename)

    @staticmethod
    def get_exact_audio_duration(file_path):
        """Возвращает точную длительность WAV файла в секундах."""
        try:
            with contextlib.closing(wave.open(file_path, 'r')) as f:
                return f.getnframes() / float(f.getframerate())
        except:
            return 2.0
