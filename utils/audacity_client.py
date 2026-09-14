import subprocess
import time


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
            if auto_start:
                try:
                    subprocess.Popen([r"C:\Audacity\Audacity.exe"])
                    time.sleep(7)
                    self._pipe_to = open(pipe_to_name, 'w', encoding='utf-8')
                    self._pipe_from = open(pipe_from_name, 'r', encoding='utf-8')
                    return True
                except:
                    pass
            return False
        except:
            return False

    def send_command(self, command, auto_start=False):
        """Отправляет команду в Audacity и возвращает результат."""
        if not self.connect(auto_start=auto_start):
            return ""

        try:
            self._pipe_to.write(command + '\n')
            self._pipe_to.flush()
            result = ""
            while True:
                line = self._pipe_from.readline()
                result += line
                if "BatchCommand finished: OK" in line or "BatchCommand finished: Failed!" in line:
                    break
            return result
        except:
            self._pipe_to = self._pipe_from = None
            return ""
