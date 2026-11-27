"""Самоустановка GTime и «один экземпляр на компьютере».

Самоустановка: любой запущенный exe переносит себя в %LOCALAPPDATA%\\GTime\\GTime.exe (если там версия старее или файла нет)
и запускается оттуда — автозапуск всегда указывает на одну копию. Запущенный файл Windows не даёт перезаписать, но даёт переименовать:
старая копия становится GTime.exe.old, на её место ложится новая; .old удаляется при следующем запуске.
Один экземпляр на пользователя — именованный mutex.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time

try:
    from version import BUILD, VERSION
except ImportError:                                      # запуск не из папки приложения
    BUILD, VERSION = 0, '0.0'

EXE = 'GTime.exe'
MUTEX = 'Local\\GTime_single'
EV_SHOW, EV_QUIT = 'Local\\GTime_show', 'Local\\GTime_quit'


def parse_version(v):
    """«1.10.2» → (1, 10, 2); «1.1» → (1, 1, 0). Сравнение — по числам, а не по тексту (1.10 новее 1.9)."""
    nums = [int(x) for x in re.findall(r'\d+', str(v or ''))][:3]
    return tuple(nums + [0] * (3 - len(nums)))


def newer(a_version, a_build, b_version, b_build):
    """a новее b? Сначала версия, при равной версии — номер сборки (заново выложенная сборка той же версии)."""
    return (parse_version(a_version), int(a_build or 0)) > (parse_version(b_version), int(b_build or 0))


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def install_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'GTime')


def _spawn(exe, args):
    """Запустить exe отдельным процессом. Для onefile-сборки сбрасываем окружение распаковки родителя, иначе потомок ищет его папку."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('_MEIPASS2', None)
    flags = 0
    if sys.platform == 'win32':
        flags = 0x00000008 | 0x00000200                  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([exe] + list(args), env=env, creationflags=flags, close_fds=True, cwd=os.path.dirname(exe) or None)


def _swap_in(new_path, target):
    """new_path → target. Запущенный target сначала переименовывается в .old (так можно), при сбое всё возвращается."""
    old = target + '.old'
    for stale in (old,):
        try:
            if os.path.exists(stale):
                os.remove(stale)
        except OSError:
            pass
    had = os.path.exists(target)
    if had:
        os.replace(target, old)
    try:
        os.replace(new_path, target)
    except OSError:
        if had:
            os.replace(old, target)
        raise


def _silent_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _write_version(folder, version, build):
    try:
        with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8') as f:
            f.write(f'{version} {int(build)}')
    except OSError:
        pass


def _read_version(folder):
    """(версия, сборка) установленной копии; нет файла — ((0, 0, 0), 0)."""
    try:
        with open(os.path.join(folder, 'version.txt'), 'r', encoding='utf-8') as f:
            v, _, b = f.read().strip().partition(' ')
        return parse_version(v), int(b or 0)
    except (OSError, ValueError):
        return (0, 0, 0), 0


def cleanup_old(exe_path=None):
    """Убрать остатки прошлого обновления рядом с exe (GTime.exe.old / .new)."""
    exe_path = exe_path or sys.executable
    for ext in ('.old', '.new'):
        _silent_remove(exe_path + ext)


def ensure_installed(argv, exe_path=None, target=None, launch=_spawn, frozen=None, build=None, version=None):
    """Самоустановка в %LOCALAPPDATA%\\GTime\\GTime.exe. True — запущена копия оттуда, этот процесс надо закрыть. Только Windows / exe."""
    frozen = is_frozen() if frozen is None else frozen
    if not frozen or ('--no-install' in argv):
        return False
    build = BUILD if build is None else build
    version = VERSION if version is None else version
    me = os.path.abspath(exe_path or sys.executable)
    target = os.path.abspath(target or os.path.join(install_dir(), EXE))
    if os.path.normcase(me) == os.path.normcase(target):
        return False
    rest = [a for a in argv[1:] if a not in ('--replace',)]
    folder = os.path.dirname(target)
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(target) and _read_version(folder) >= (parse_version(version), build):
            launch(target, rest)                         # там уже такая же или новее — просто запускаем её (она покажет окно)
            return True
        new = target + '.new'
        shutil.copyfile(me, new)
        _swap_in(new, target)
        _write_version(folder, version, build)
    except OSError:
        return False                                     # установить нельзя (права) — работаем из текущего места
    launch(target, ['--replace'] + rest)
    return True


# ---------- один экземпляр (Windows) ----------
_mutex_handle = None


def _k32():
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.CreateMutexW.argtypes, k.CreateMutexW.restype = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], ctypes.c_void_p
    k.CreateEventW.argtypes, k.CreateEventW.restype = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], ctypes.c_void_p
    k.OpenEventW.argtypes, k.OpenEventW.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR], ctypes.c_void_p
    k.SetEvent.argtypes, k.SetEvent.restype = [ctypes.c_void_p], wintypes.BOOL
    k.CloseHandle.argtypes, k.CloseHandle.restype = [ctypes.c_void_p], wintypes.BOOL
    k.WaitForMultipleObjects.argtypes = [wintypes.DWORD, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD]
    k.WaitForMultipleObjects.restype = wintypes.DWORD
    return k


def instance_acquire(wait_s=0.0):
    """Занять «единственный экземпляр». False — другой GTime уже работает (ждём его закрытия не дольше wait_s)."""
    global _mutex_handle
    if sys.platform != 'win32':
        return True
    try:
        import ctypes
        k = _k32()
        end = time.monotonic() + wait_s
        while True:
            h = k.CreateMutexW(None, False, MUTEX)
            if h and ctypes.windll.kernel32.GetLastError() != 183:      # 183 — уже существует
                _mutex_handle = h
                return True
            if h:
                k.CloseHandle(h)
            if time.monotonic() >= end:
                return False
            time.sleep(0.3)
    except Exception:
        return True                                      # не смогли проверить — не мешаем запуску


def instance_signal(which):
    """Сказать работающему экземпляру: «show» — открой окно, «quit» — закройся (его заменяет новая сборка)."""
    if sys.platform != 'win32':
        return False
    try:
        k = _k32()
        h = k.OpenEventW(0x0002, False, EV_SHOW if which == 'show' else EV_QUIT)     # EVENT_MODIFY_STATE
        if not h:
            return False
        k.SetEvent(h)
        k.CloseHandle(h)
        return True
    except Exception:
        return False


def instance_watch(on_show, on_quit):
    """Фоновый поток: второй запуск просит показать окно или закрыться."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        k = _k32()
        evs = [k.CreateEventW(None, False, False, EV_SHOW), k.CreateEventW(None, False, False, EV_QUIT)]
        arr = (ctypes.c_void_p * 2)(*evs)
    except Exception:
        return None

    def loop():
        while True:
            r = k.WaitForMultipleObjects(2, arr, False, 0xFFFFFFFF)
            try:
                if r == 0:
                    on_show()
                elif r == 1:
                    on_quit()
                    return
                else:
                    return
            except Exception:
                pass
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t
