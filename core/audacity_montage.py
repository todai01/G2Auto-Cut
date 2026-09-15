import os
import json
import time
import shutil
import ctypes
import webview
from pydub import AudioSegment
from utils.file_utils import FileUtils

class MontageMixin:
    """Модуль работы с монтажным столом Audacity, склейкой и экспортом аудио."""

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

    def _get_own_hwnd(self):
        try:
            return ctypes.windll.user32.FindWindowW(None, "G2Studio | Автосрезка")
        except Exception:
            return None

    def embed_audacity(self, x, y, width, height):
        if getattr(self, '_embedded_hwnd', None):
            return self.sync_embed_position(x, y, width, height)

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
            ctypes.windll.user32.MoveWindow(hwnd, int(x), int(y), int(width), int(height), True)
            return {"status": "ok"}
        except Exception:
            self._embedded_hwnd = None
            return {"error": "Окно Audacity пропало — вживление отменено."}

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

    def _get_montage_track_idx(self):
        resp = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        try:
            s = resp.find('[')
            e = resp.rfind(']')
            t_data = json.loads(resp[s:e + 1])
            audio_tracks = [t.get('track', i) for i, t in enumerate(t_data) if t.get('kind') == 'wave']
            if len(audio_tracks) == 1: return audio_tracks[0]
            if len(audio_tracks) >= 2: return audio_tracks[1]
        except:
            pass
        return 1

    def _move_imported_track_to_paste(self, current_paste):
        response = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        try:
            start_idx, end_idx = response.find('['), response.rfind(']')
            tracks = json.loads(response[start_idx:end_idx + 1])
            last_track_idx = len(tracks) - 1
        except:
            last_track_idx = 2

        self.audacity.send_command(f'SelectTracks: Track={last_track_idx} Mode=Set')
        self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
        self.audacity.send_command('Copy:')
        self.audacity.send_command('RemoveTracks:')

        self.audacity.send_command('SelectTracks: Track=1 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={current_paste} End={current_paste} RelativeTo=ProjectStart')
        self.audacity.send_command('Paste:')

    def prep_merge(self, parts_paths):
        valid_paths = [p for p in parts_paths if p]
        if not valid_paths: return

        self.last_montage_sequence = [{'type': 'part', 'path': p} for p in valid_paths]

        self.audacity.send_command('SelectNone:')
        response = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
        max_end_project = 0.0
        if response:
            try:
                start_idx, end_idx = response.find('['), response.rfind(']')
                if start_idx != -1 and end_idx != -1:
                    json_data = json.loads(response[start_idx:end_idx + 1])
                    for track in json_data:
                        for label in track[1]:
                            end_time = float(label[1])
                            if end_time > max_end_project: max_end_project = end_time
            except:
                pass

        insert_time = max_end_project + 15.0
        current_paste = insert_time

        for path in valid_paths:
            if not os.path.exists(path): continue
            dur = FileUtils.get_exact_audio_duration(path)
            self.audacity.send_command(f'Import2: Filename="{os.path.abspath(path).replace(chr(92), "/")}"')
            time.sleep(0.3)
            self._move_imported_track_to_paste(current_paste)
            current_paste += dur + 0.1

        self.audacity.send_command('SelectTracks: Track=1 Mode=Set')
        self.audacity.send_command(f'SelectTime: Start={insert_time} End={current_paste} RelativeTo=ProjectStart')
        self.audacity.send_command('ZoomSel:')
        webview.windows[0].evaluate_js("alert('Файлы успешно импортированы на монтажную дорожку!');")

    def save_separate_parts(self, parts_paths, add_silence):
        if not hasattr(self, 'last_montage_sequence') or not self.last_montage_sequence:
            webview.windows[0].evaluate_js("alert('Нет данных о загруженных файлах!');")
            return False

        response = self.audacity.send_command('GetInfo: Type=Clips Format=JSON')
        try:
            start_idx = response.find('[')
            end_idx = response.rfind(']')
            tracks_data = json.loads(response[start_idx:end_idx + 1])
        except:
            return False

        m_idx = 1
        montage_clips = []
        for item in tracks_data:
            if 'clips' in item:
                if item.get('track') == m_idx: montage_clips.extend(item['clips'])
            else:
                if item.get('track') == m_idx: montage_clips.append(item)

        if not montage_clips:
            webview.windows[0].evaluate_js("alert('Монтажная дорожка пуста!');")
            return False

        montage_clips.sort(key=lambda x: x['start'])

        if len(montage_clips) != len(self.last_montage_sequence):
            webview.windows[0].evaluate_js(
                f"alert('Ошибка! Вы закинули {len(self.last_montage_sequence)} фрагментов, а на дорожке их {len(montage_clips)}.\\n\\nНе разрезайте аудио на части, скрипт работает по позициям.');")
            return False

        checked_dir = os.path.join(self.work_dir, 'Проверенные')
        os.makedirs(checked_dir, exist_ok=True)
        exported_count = 0

        audio_tracks = [t.get('track', i) for i, t in enumerate(tracks_data) if t.get('kind') == 'wave']

        for clip, seq_item in zip(montage_clips, self.last_montage_sequence):
            if seq_item['type'] == 'var':
                continue

            start_sec = clip['start']
            end_sec = clip['end']

            clean_clip_name = os.path.basename(seq_item['path']).replace('.wav', '').replace('.mp3', '')

            save_name = clean_clip_name
            phrase_idx = -1
            if self.phrases_data:
                for i, p in enumerate(self.phrases_data):
                    expected_raw = f"фраза_{i + 1:04d}"
                    custom_name = p.get("filename", "")
                    if custom_name.lower() == clean_clip_name.lower() or expected_raw.lower() == clean_clip_name.lower():
                        if custom_name: save_name = custom_name
                        phrase_idx = i
                        break

            if phrase_idx != -1:
                self.phrases_data[phrase_idx]["checked"] = True

            if not save_name.lower().endswith('.wav'): save_name += '.wav'
            target_path = os.path.join(checked_dir, save_name)
            safe_path = os.path.abspath(target_path).replace('\\', '/')

            self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
            self.audacity.send_command(f'SelectTime: Start={start_sec} End={end_sec} RelativeTo=ProjectStart')
            self.audacity.send_command('Copy:')

            self.audacity.send_command('NewMonoTrack:')
            resp_tracks = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
            try:
                s_idx = resp_tracks.find('[')
                e_idx = resp_tracks.rfind(']')
                t_data = json.loads(resp_tracks[s_idx:e_idx + 1])
                temp_track_idx = len(t_data) - 1
            except:
                temp_track_idx = 2

            self.audacity.send_command(f'SelectTracks: Track={temp_track_idx} Mode=Set')
            self.audacity.send_command('SelectTime: Start=0 End=0 RelativeTo=ProjectStart')
            self.audacity.send_command('Paste:')

            for t_idx in audio_tracks:
                self.audacity.send_command(f'SelectTracks: Track={t_idx} Mode=Set')
                self.audacity.send_command('MuteTracks:')

            self.audacity.send_command(f'SelectTracks: Track={temp_track_idx} Mode=Set')
            self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')

            self.audacity.send_command('RemoveTracks:')
            for t_idx in audio_tracks:
                self.audacity.send_command(f'SelectTracks: Track={t_idx} Mode=Set')
                self.audacity.send_command('UnmuteTracks:')

            if add_silence and os.path.exists(target_path):
                try:
                    audio = AudioSegment.from_file(target_path).set_frame_rate(8000)
                    audio += AudioSegment.silent(duration=450, frame_rate=8000)
                    audio.export(target_path, format="wav")
                except:
                    pass

            exported_count += 1

        if exported_count > 0:
            self.audacity.send_command(f'SelectTracks: Track={m_idx} Mode=Set')
            self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
            self.audacity.send_command('Delete:')
            webview.windows[0].evaluate_js(
                "alert('✅ Отредактированные фразы успешно вырезаны и сохранены в папку Проверенные (без переменной)!');")

        return self.get_ui_state()

    def save_merge(self, save_name, add_silence, is_variable=False):
        if not save_name.lower().endswith('.wav'):
            save_name += '.wav'

        # Одна конечная папка вместо двухступенчатого отбора Good -> Проверенные
        folder_name = 'Переменные' if is_variable else 'Проверенные'
        target_path = FileUtils.get_sorted_path(os.path.join(self.work_dir, folder_name), save_name)
        safe_path = os.path.abspath(target_path).replace('\\', '/')

        self.audacity.send_command('Copy:')
        self.audacity.send_command('SelectTracks: Track=1 Mode=Set')
        self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
        self.audacity.send_command('Delete:')
        self.audacity.send_command('SelectTime: Start=0 End=0 RelativeTo=ProjectStart')
        self.audacity.send_command('Paste:')
        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command('MuteTracks:')
        self.audacity.send_command('SelectTracks: Track=1 Mode=Set')
        self.audacity.send_command(f'Export2: Filename="{safe_path}" NumChannels=1')
        self.audacity.send_command('SelectTime: Start=0 End=99999 RelativeTo=ProjectStart')
        self.audacity.send_command('Delete:')
        self.audacity.send_command('SelectTracks: Track=0 Mode=Set')
        self.audacity.send_command('UnmuteTracks:')
        self._sync_audacity_selection()

        if add_silence and os.path.exists(target_path):
            try:
                audio = AudioSegment.from_file(target_path).set_frame_rate(8000)
                audio += AudioSegment.silent(duration=450, frame_rate=8000)
                audio.export(target_path, format="wav")
            except:
                pass
        return True

    def process_action(self, action, add_silence):
        if not self.chunks_data or self.chunk_index >= len(self.chunks_data):
            return self.get_ui_state()

        item = self.chunks_data[self.chunk_index]
        source_path = item['filepath']
        chunk_name_no_ext = item['filename'].replace('.wav', '')

        # Мусор не размечается: ненужный дубль просто пролистывается клавишей D
        if action in ['good', 'variable']:
            self.audacity.send_command('SelectNone:')
            response = self.audacity.send_command('GetInfo: Type=Labels Format=JSON')
            start_sec, end_sec = None, None

            if response:
                try:
                    start_idx, end_idx = response.find('['), response.rfind(']')
                    if start_idx != -1 and end_idx != -1:
                        json_data = json.loads(response[start_idx:end_idx + 1])
                        for track in json_data:
                            for label in track[1]:
                                if label[2].strip() == chunk_name_no_ext:
                                    start_sec, end_sec = float(label[0]), float(label[1])
                                    break
                except:
                    pass

            if self.current_mode == 'Chunks' and start_sec and end_sec and self.raw_audio_full:
                final_audio = self.raw_audio_full[int(start_sec * 1000):int(end_sec * 1000)]
            else:
                final_audio = AudioSegment.from_file(source_path)

            final_audio = final_audio.set_frame_rate(8000)

            save_name = item['filename']
            if self.phrases_data and self.phrase_index < len(self.phrases_data):
                custom = self.phrases_data[self.phrase_index]["filename"]
                if custom:
                    save_name = f"{custom}.wav" if not custom.lower().endswith('.wav') else custom

            if action == 'good':
                target_path = FileUtils.get_sorted_path(os.path.join(self.work_dir, 'Проверенные'), save_name)
                if add_silence:
                    final_audio += AudioSegment.silent(duration=450, frame_rate=8000)
            else:
                target_path = FileUtils.get_sorted_path(os.path.join(self.work_dir, 'Переменные'), save_name)

            final_audio.export(target_path, format="wav")

            if self.phrases_data:
                self.phrase_index += 1
            self.chunk_index += 1

        self._sync_audacity_selection()
        return self.get_ui_state()
