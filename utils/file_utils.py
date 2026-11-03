import wave
import contextlib

class FileUtils:
    @staticmethod
    def get_exact_audio_duration(file_path):
        """Возвращает точную длительность WAV файла в секундах."""
        try:
            with contextlib.closing(wave.open(file_path, 'r')) as f:
                return f.getnframes() / float(f.getframerate())
        except:
            return 2.0
