import os
import subprocess
import threading
import time

# Audacity ставят в разные места, а раньше программа знала ровно один путь
# и молча сдавалась, если его там не было. Проверяем обычные места установки.
AUDACITY_PATHS = [
    r"C:\Program Files\Audacity\Audacity.exe",  # подтверждённый путь на машине пользователя
    r"C:\Audacity\Audacity.exe",
    r"C:\Program Files (x86)\Audacity\Audacity.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Audacity\Audacity.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\Audacity\Audacity.exe"),
]


class AudacityClient:
    def __init__(self):
        self._pipe_to = None
        self._pipe_from = None

    def is_connected(self):
        """Проверяет, активно ли подключение к Audacity."""
        return self._pipe_to is not None and not self._pipe_to.closed

    def connect(self, auto_start=False):
        """Устанавливает соединение с Audacity через пайпы."""
        if self.is_connected():
            return True

        pipe_to_name = r'\\.\pipe\ToSrvPipe'
        pipe_from_name = r'\\.\pipe\FromSrvPipe'

        try:
            self._pipe_to = open(pipe_to_name, 'w', encoding='utf-8')
            self._pipe_from = open(pipe_from_name, 'r', encoding='utf-8')
            return True
        except FileNotFoundError:
            if not auto_start:
                return False
            exe = next((p for p in AUDACITY_PATHS if p and os.path.exists(p)), None)
            if not exe:
                return False
            try:
                subprocess.Popen([exe])
            except Exception:
                return False
            # Холодный старт Audacity не укладывается в фиксированное время
            # на медленной машине — вместо одной слепой паузы опрашиваем
            # канал каждые полсекунды примерно до 20 секунд.
            for _ in range(40):
                time.sleep(0.5)
                try:
                    self._pipe_to = open(pipe_to_name, 'w', encoding='utf-8')
                    self._pipe_from = open(pipe_from_name, 'r', encoding='utf-8')
                    return True
                except Exception:
                    continue
            return False
        except Exception:
            return False

    def send_command(self, command, auto_start=False, timeout=20):
        """Отправляет команду в Audacity и ждёт ответа не дольше timeout
        секунд. Раньше чтение ответа не имело предела: если Audacity не
        отвечал (завис при старте, обрушился и т.п.), программа замирала
        насмерть — на Windows это выглядит так, будто зависло вообще всё
        окно, включая свои же кнопки и алерты."""
        if not self.connect(auto_start=auto_start):
            return ""

        try:
            self._pipe_to.write(command + '\n')
            self._pipe_to.flush()
        except Exception:
            self._pipe_to = self._pipe_from = None
            return ""

        pipe_from = self._pipe_from
        box = {}

        def _reader():
            try:
                result = ""
                while True:
                    line = pipe_from.readline()
                    if not line:
                        break
                    result += line
                    if "BatchCommand finished: OK" in line or "BatchCommand finished: Failed!" in line:
                        break
                box['result'] = result
            except Exception:
                box['result'] = ""

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()
        reader_thread.join(timeout)

        if reader_thread.is_alive():
            # Ответ не пришёл вовремя. Поток-читатель принудительно
            # остановить нельзя (Python не умеет прерывать блокирующее
            # чтение) — просто перестаём его ждать и считаем канал
            # нерабочим, чтобы следующий вызов переподключился заново.
            self._pipe_to = self._pipe_from = None
            return ""

        return box.get('result', "")
