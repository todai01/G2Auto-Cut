import winsound

class AudioPlayer:
    def __init__(self):
        self.is_playing = False

    def play(self, filepath):
        """Останавливает текущий звук и запускает новый файл асинхронно."""
        self.stop()
        winsound.PlaySound(filepath, winsound.SND_FILENAME | winsound.SND_ASYNC)
        self.is_playing = True

    def stop(self):
        """Принудительно останавливает воспроизведение."""
        if self.is_playing:
            winsound.PlaySound(None, winsound.SND_PURGE)
            self.is_playing = False
