import time
import shutil
import ctypes
import webview

class MontageMixin:
    """Модуль работы с окном Audacity: поиск, встраивание в окно программы, фокус."""

    def get_audacity_windows(self):
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible
        GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
        OpenProcess = ctypes.windll.kernel32.OpenProcess
        CloseHandle = ctypes.windll.kernel32.CloseHandle
        GetModuleFileNameEx = ctypes.windll.psapi.GetModuleFileNameExW

        windows = []

        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    title = buff.value

                    pid = ctypes.c_ulong()
                    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                    h_process = OpenProcess(0x0410, False, pid.value)
                    if h_process:
                        exe_buff = ctypes.create_unicode_buffer(260)
                        GetModuleFileNameEx(h_process, 0, exe_buff, 260)
                        CloseHandle(h_process)

                        if "audacity.exe" in exe_buff.value.lower():
                            if "privacy policy" not in title.lower():
                                windows.append({"hwnd": int(hwnd), "title": title})
            return True

        EnumWindows(EnumWindowsProc(foreach_window), 0)
        return windows

    def _block_if_audacity_ambiguous(self):
        """У Audacity один канал управления на весь компьютер — если открыто
        больше одного окна Audacity, программа не может выбрать, с каким
        именно она говорит. Команды вроде «очистить проект» уйдут в то окно,
        что первым перехватило канал, а не обязательно в то, с которым
        работает пользователь — и способны стереть содержимое чужого проекта.

        Вызывать перед любой командой, которая стирает содержимое проекта
        (SelectAll: + RemoveTracks:). Возвращает True и показывает
        предупреждение, если продолжать небезопасно; иначе False."""
        try:
            windows = self.get_audacity_windows()
        except Exception:
            return False  # не смогли проверить — не блокируем работу

        if len(windows) <= 1:
            return False

        try:
            webview.windows[0].evaluate_js(
                "showBeautifulAlert('⚠️ <b>Открыто несколько окон Audacity</b>"
                "<br><br>Программа управляет Audacity через единый канал на весь компьютер "
                "и не может выбрать нужное окно среди нескольких — команда могла бы случайно "
                "стереть содержимое другого проекта.<br><br>Закройте лишние окна Audacity, "
                "оставив только то, с которым работает эта программа, и повторите.');")
        except Exception:
            pass
        return True

    def _force_foreground(self, hwnd):
        """Надёжнее голого SetForegroundWindow: Windows обычно блокирует
        попытку окна перехватить фокус, если она идёт не от того потока,
        что был активен последним, — а вызовы из js_api как раз идут из
        фонового потока. AttachThreadInput на время «занимает» права
        активного окна, чтобы SetForegroundWindow не проваливался молча."""
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        try:
            fg_hwnd = user32.GetForegroundWindow()
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread = user32.GetWindowThreadProcessId(hwnd, None)
            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

            if fg_thread and fg_thread != current_thread:
                user32.AttachThreadInput(current_thread, fg_thread, True)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, True)

            try:
                import pyautogui
                pyautogui.press('alt')  # старый трюк — оставлен как доп. подстраховка
            except Exception:
                pass

            # SW_RESTORE (9) разворачивает окно из свёрнутого — но если окно
            # было развёрнуто на весь экран, он же его тихо схлопывает до
            # обычного размера. Разворачиваем принудительно только то, что
            # реально свёрнуто; иначе просто показываем как есть (SW_SHOW).
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            else:
                user32.ShowWindow(hwnd, 5)  # SW_SHOW — размер/состояние не трогаем
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)

            if fg_thread and fg_thread != current_thread:
                user32.AttachThreadInput(current_thread, fg_thread, False)
            if target_thread and target_thread != current_thread:
                user32.AttachThreadInput(current_thread, target_thread, False)
        except Exception:
            pass

    def set_active_window(self, hwnd):
        self._force_foreground(hwnd)
        time.sleep(0.5)
        return True


    def _ensure_audacity_ready(self):
        """Если Audacity закрыт — запускает его и ждёт, пока он начнёт
        отвечать на команды. Без этого первая же команда уходила в пустоту:
        канала управления ещё нет, ответа нет, и на экране просто ничего
        не происходило — пользователю казалось, что кнопка не работает."""
        resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON', auto_start=True)
        if resp and '[' in resp:
            return True

        # Холодный старт: программа уже запущена, но окно ещё открывается
        # и канал управления пока не отвечает — ждём до ~10 секунд.
        for _ in range(20):
            time.sleep(0.5)
            resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
            if resp and '[' in resp:
                return True
        return False

    # --- Вживление окна Audacity внутрь окна софта ---
    #
    # У Windows нет «официального» способа показать чужую программу
    # внутри своего окна — есть системный приём SetParent, который
    # переподчиняет чужое окно как дочернее нашему и убирает у него
    # рамку/заголовок. Audacity не проектировался для этого, поэтому
    # приём может повести себя не идеально (всплывающие диалоги Audacity
    # всё равно будут отдельными окнами поверх — это нормально и не
    # чинится). Если станет только хуже — есть unembed_audacity, который
    # возвращает Audacity в обычное отдельное окно.

    GWL_STYLE = -16
    WS_CHILD = 0x40000000
    WS_POPUP = 0x80000000
    WS_CAPTION = 0x00C00000
    WS_THICKFRAME = 0x00040000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    WS_SYSMENU = 0x00080000
    SWP_NOZORDER = 0x0004
    SWP_FRAMECHANGED = 0x0020
    SWP_SHOWWINDOW = 0x0040
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SW_MINIMIZE = 6

    def _get_own_hwnd(self):
        """Главное окно программы. Ищем по своему процессу, а не по точному
        заголовку: окно может подхватить заголовок страницы (<title>), и тогда
        FindWindowW по «GVox | Автосрезка» ничего не находит."""
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return None
        cached = getattr(self, '_own_hwnd', None)
        if cached and user32.IsWindow(cached):
            return cached

        hwnd = None
        try:
            from ctypes import wintypes
            pid = ctypes.windll.kernel32.GetCurrentProcessId()
            found = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def collect(h, _lparam):
                owner = wintypes.DWORD()
                user32.GetWindowThreadProcessId(h, ctypes.byref(owner))
                if owner.value == pid and user32.IsWindowVisible(h) and user32.GetWindowTextLengthW(h) > 0:
                    r = wintypes.RECT()
                    user32.GetWindowRect(h, ctypes.byref(r))
                    found.append(((r.right - r.left) * (r.bottom - r.top), h))
                return True

            user32.EnumWindows(collect, 0)
            if found:
                hwnd = max(found, key=lambda x: x[0])[1]
        except Exception:
            hwnd = None

        if not hwnd:
            hwnd = user32.FindWindowW(None, "GVox | Автосрезка") or None
        self._own_hwnd = hwnd
        return hwnd

    def embed_audacity(self, x, y, width, height):
        # _embedded_hwnd переживает закрытие самого Audacity (Python-процесс
        # софта не узнаёт об этом сам) — раньше следующая попытка вживления
        # молча «успешно» двигала уже несуществующее окно вместо того, чтобы
        # заново найти реальное. Проверяем, что дескриптор ещё живой.
        cached = getattr(self, '_embedded_hwnd', None)
        if cached and ctypes.windll.user32.IsWindow(cached):
            return self.sync_embed_position(x, y, width, height)
        self._embedded_hwnd = None

        own_hwnd = self._get_own_hwnd()
        if not own_hwnd:
            return {"error": "Не удалось найти окно софта."}

        windows = self.get_audacity_windows()
        if not windows:
            return {"error": "Audacity не найден. Сначала отправьте файл в Audacity."}
        if len(windows) > 1:
            return {"error": "Открыто несколько окон Audacity — закройте лишние, чтобы вживить нужное."}

        hwnd = windows[0]['hwnd']
        user32 = ctypes.windll.user32

        try:
            orig_style = user32.GetWindowLongW(hwnd, self.GWL_STYLE)
            new_style = orig_style
            new_style &= ~(self.WS_POPUP | self.WS_CAPTION | self.WS_THICKFRAME |
                           self.WS_MINIMIZEBOX | self.WS_MAXIMIZEBOX | self.WS_SYSMENU)
            new_style |= self.WS_CHILD

            user32.SetWindowLongW(hwnd, self.GWL_STYLE, new_style)
            user32.SetParent(hwnd, own_hwnd)
            user32.SetWindowPos(hwnd, 0, int(x), int(y), int(width), int(height),
                                 self.SWP_NOZORDER | self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW)

            self._embedded_hwnd = hwnd
            self._embed_orig_style = orig_style
            return {"status": "ok"}
        except Exception as e:
            return {"error": f"Не удалось вживить окно Audacity: {e}"}

    def sync_embed_position(self, x, y, width, height):
        """Подвинуть уже вживлённое окно Audacity под новую позицию/размер
        плашки (например, когда пользователь меняет размер окна софта)."""
        hwnd = getattr(self, '_embedded_hwnd', None)
        if not hwnd:
            return {"status": "not_embedded"}
        try:
            user32 = ctypes.windll.user32
            if not user32.IsWindow(hwnd) or not user32.MoveWindow(hwnd, int(x), int(y), int(width), int(height), True):
                # Дескриптор мёртв (Audacity закрыли) — сбрасываем, чтобы
                # следующий embed_audacity() честно искал окно заново, а не
                # притворялся, будто всё получилось.
                self._embedded_hwnd = None
                return {"error": "Окно Audacity пропало — вживление отменено."}
            return {"status": "ok"}
        except Exception:
            self._embedded_hwnd = None
            return {"error": "Окно Audacity пропало — вживление отменено."}

    def hide_embedded_audacity(self):
        """Прячет вживлённое окно Audacity, не отсоединяя его (позиция и
        встроенность сохраняются). Нужно, когда поверх открывается модальное
        окно самого софта: Audacity — настоящее окно Windows, а не часть
        веб-страницы, поэтому обычный CSS z-index его не перекрывает, и
        любой алерт рисовался у него ПОД низом. Прячем на время показа."""
        hwnd = getattr(self, '_embedded_hwnd', None)
        if hwnd and ctypes.windll.user32.IsWindow(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
        return {"status": "ok"}

    def show_embedded_audacity(self):
        """Возвращает видимость вживлённому окну Audacity после закрытия
        модального окна софта (см. hide_embedded_audacity)."""
        hwnd = getattr(self, '_embedded_hwnd', None)
        if hwnd and ctypes.windll.user32.IsWindow(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
        return {"status": "ok"}

    def unembed_audacity(self):
        """Вернуть Audacity обратно в обычное отдельное окно."""
        hwnd = getattr(self, '_embedded_hwnd', None)
        if not hwnd:
            return True
        user32 = ctypes.windll.user32
        try:
            user32.SetParent(hwnd, 0)
            orig_style = getattr(self, '_embed_orig_style', None)
            if orig_style is not None:
                user32.SetWindowLongW(hwnd, self.GWL_STYLE, orig_style)
            user32.SetWindowPos(hwnd, 0, 100, 100, 1000, 700,
                                 self.SWP_NOZORDER | self.SWP_FRAMECHANGED | self.SWP_SHOWWINDOW)
            self._force_foreground(hwnd)
        except Exception:
            pass
        self._embedded_hwnd = None
        self._embed_orig_style = None
        return True

    def minimize_audacity(self):
        """При возврате в главное меню сворачивает Audacity, а не просто
        отсоединяет — unembed_audacity() возвращал окно в обычный вид и
        выводил его на передний план (нужно, когда пользователь сам жмёт
        «Отсоединить»), а тут наоборот: не мешать на рабочем столе."""
        user32 = ctypes.windll.user32
        hwnd = getattr(self, '_embedded_hwnd', None)
        if hwnd and user32.IsWindow(hwnd):
            try:
                user32.SetParent(hwnd, 0)
                orig_style = getattr(self, '_embed_orig_style', None)
                if orig_style is not None:
                    user32.SetWindowLongW(hwnd, self.GWL_STYLE, orig_style)
                # Тот же набор флагов, что и в unembed_audacity() (там это
                # проверенно работает) — важен SWP_SHOWWINDOW: без него
                # окно иногда оставалось перерисованным «как встроенное»
                # и ShowWindow(..., SW_MINIMIZE) сразу за этим не срабатывал.
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                     self.SWP_NOZORDER | self.SWP_FRAMECHANGED |
                                     self.SWP_NOMOVE | self.SWP_NOSIZE | self.SWP_SHOWWINDOW)
            except Exception:
                pass
            self._embedded_hwnd = None
            self._embed_orig_style = None
            user32.ShowWindow(hwnd, self.SW_MINIMIZE)
            return {"status": "ok"}

        # Не было вживлено — просто ищем любое открытое окно Audacity и
        # сворачиваем его тоже, если оно есть.
        for w in self.get_audacity_windows():
            try:
                user32.ShowWindow(w['hwnd'], self.SW_MINIMIZE)
            except Exception:
                pass
        return {"status": "ok"}
