import os
import shutil
import tempfile
import urllib.request
import zipfile

# Официальная сборка ffmpeg для Windows — этот URL всегда указывает на
# актуальную стабильную версию (gyan.dev поддерживает его как постоянную
# ссылку), поэтому его можно жёстко прописать в коде.
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def ensure_ffmpeg(target_dir, on_progress=None):
    """Гарантирует, что ffmpeg.exe и ffprobe.exe лежат рядом с программой.
    Если их там нет (первый запуск на новом компьютере) — скачивает
    официальную сборку и достаёт из архива только эти два файла, не
    захламляя папку остальным содержимым zip'а.

    on_progress(percent, text) — необязательный колбэк для отображения
    прогресса в интерфейсе (см. main.py).

    Возвращает True, если оба файла на месте (были раньше или скачались
    только что), False — если скачать не удалось."""
    ffmpeg_path = os.path.join(target_dir, "ffmpeg.exe")
    ffprobe_path = os.path.join(target_dir, "ffprobe.exe")
    if os.path.exists(ffmpeg_path) and os.path.exists(ffprobe_path):
        return True

    try:
        if on_progress:
            on_progress(0, "Первый запуск: скачиваю ffmpeg (~80 МБ, один раз)...")

        with tempfile.TemporaryDirectory() as tmp:
            zip_path = os.path.join(tmp, "ffmpeg.zip")

            def _report(block_num, block_size, total_size):
                if on_progress and total_size > 0:
                    percent = min(100, int(block_num * block_size * 100 / total_size))
                    on_progress(percent, f"Скачивание ffmpeg: {percent}%")

            urllib.request.urlretrieve(FFMPEG_ZIP_URL, zip_path, _report)

            if on_progress:
                on_progress(100, "Распаковка ffmpeg...")

            with zipfile.ZipFile(zip_path) as z:
                for name in z.namelist():
                    base = os.path.basename(name)
                    if base == "ffmpeg.exe" and not os.path.exists(ffmpeg_path):
                        with z.open(name) as src, open(ffmpeg_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                    elif base == "ffprobe.exe" and not os.path.exists(ffprobe_path):
                        with z.open(name) as src, open(ffprobe_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)

        return os.path.exists(ffmpeg_path) and os.path.exists(ffprobe_path)
    except Exception as e:
        print(f"Не удалось скачать ffmpeg автоматически: {e}")
        return False
