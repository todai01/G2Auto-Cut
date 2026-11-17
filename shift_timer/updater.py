"""Обновление GTime через сетевую папку команды и «одна копия на компьютере».

В папке команды лежат `GTime_team/update/GTime.exe` и `version.json` ({"version": N, "sha256", "notes", "published"}).
Клиент сравнивает N со своим номером сборки (version.BUILD) и по кнопке «Обновить» заменяет свой exe:
Windows не даёт перезаписать запущенный файл, но даёт его переименовать — старый становится GTime.old.exe,
на его место ложится новый, запускается и старый закрывается. Удаляется .old при следующем запуске.

Самоустановка: любой запущенный exe переносит себя в %LOCALAPPDATA%\\GTime\\GTime.exe (если там версия старее или файла нет)
и запускается оттуда — автозапуск всегда указывает на одну копию. Один экземпляр на пользователя — именованный mutex.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime

try:
    from version import BUILD
except ImportError:                                      # запуск не из папки приложения
    BUILD = 0

SUB = 'GTime_team'
EXE = 'GTime.exe'
MANIFEST = 'version.json'
MUTEX = 'Local\\GTime_single'
EV_SHOW, EV_QUIT = 'Local\\GTime_show', 'Local\\GTime_quit'


class UpdateError(Exception):
    """Понятная пользователю ошибка."""


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def update_folder(team_dir):
    return os.path.join(team_dir, SUB, 'update')


def install_dir():
    return os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'GTime')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.{os.getpid()}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_remote(team_dir):
    """Что лежит в папке обновлений: {"version", "sha256", "notes", "published", "size"} или None (нет папки / файл повреждён)."""
    if not team_dir:
        return None
    try:
        with open(os.path.join(update_folder(team_dir), MANIFEST), 'r', encoding='utf-8') as f:
            m = json.load(f)
        v = int(m["version"])
        sha = str(m["sha256"]).lower()
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if v <= 0 or len(sha) != 64:
        return None
    return {"version": v, "sha256": sha, "notes": str(m.get("notes") or '')[:1000], "published": m.get("published"), "size": int(m.get("size") or 0)}


def check(team_dir, current=None):
    """Есть ли новее своей сборки. Возвращает {"current", "remote", "available"}; нет папки — UpdateError."""
    current = BUILD if current is None else current
    if not team_dir:
        raise UpdateError('Папка команды не выбрана (Настройки → Команда).')
    if not os.path.isdir(team_dir):
        raise UpdateError('Сетевая папка недоступна.')
    r = read_remote(team_dir)
    ok = bool(r and os.path.isfile(os.path.join(update_folder(team_dir), EXE)))
    return {"current": current, "remote": r, "available": bool(ok and r["version"] > current)}


def publish(team_dir, exe_path, version=None, notes=''):
    """Выложить exe для команды: копия в папку обновлений + version.json. Номер — сборки этого exe (version.BUILD)."""
    version = BUILD if version is None else int(version)
    if version <= 0:
        raise UpdateError('У этой сборки нет номера (запуск из исходников) — выкладывать нечего.')
    if not team_dir or not os.path.isdir(team_dir):
        raise UpdateError('Сетевая папка недоступна.')
    if not exe_path or not os.path.isfile(exe_path):
        raise UpdateError('Не найден файл exe.')
    cur = read_remote(team_dir)
    if cur and cur["version"] > version:
        raise UpdateError(f'В папке уже более новая сборка ({cur["version"]}), а эта — {version}.')
    folder = update_folder(team_dir)
    os.makedirs(folder, exist_ok=True)
    dst, tmp = os.path.join(folder, EXE), os.path.join(folder, EXE + '.tmp')
    shutil.copyfile(exe_path, tmp)
    sha = sha256_file(tmp)
    if sha != sha256_file(exe_path):
        os.remove(tmp)
        raise UpdateError('Копия в папке не совпала с исходным файлом — повторите.')
    os.replace(tmp, dst)
    m = {"version": version, "sha256": sha, "notes": str(notes or '').strip()[:1000], "published": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
         "size": os.path.getsize(dst)}
    _write_json(os.path.join(folder, MANIFEST), m)
    return m


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


def apply_update(team_dir, exe_path, launch=_spawn, extra_args=()):
    """Заменить exe_path новой сборкой из папки команды и запустить её. Возвращает номер новой версии; после этого процесс должен закрыться."""
    r = read_remote(team_dir)
    src = os.path.join(update_folder(team_dir or ''), EXE)
    if not r or not os.path.isfile(src):
        raise UpdateError('В папке обновлений нет новой сборки.')
    new = exe_path + '.new'
    try:
        shutil.copyfile(src, new)
        if sha256_file(new) != r["sha256"]:
            raise UpdateError('Файл обновления повреждён (контрольная сумма не совпала). Попросите выложить сборку заново.')
        _swap_in(new, exe_path)
    except UpdateError:
        _silent_remove(new)
        raise
    except OSError as e:
        _silent_remove(new)
        raise UpdateError(f'Не удалось заменить программу: {e.strerror or e}')
    _write_version(os.path.dirname(exe_path), r["version"])
    launch(exe_path, ['--replace'] + list(extra_args))
    return r["version"]


def _silent_remove(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _write_version(folder, v):
    try:
        with open(os.path.join(folder, 'version.txt'), 'w', encoding='utf-8') as f:
            f.write(str(int(v)))
    except OSError:
        pass


def _read_version(folder):
    try:
        with open(os.path.join(folder, 'version.txt'), 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def cleanup_old(exe_path=None):
    """Убрать остатки прошлого обновления рядом с exe (GTime.exe.old / .new)."""
    exe_path = exe_path or sys.executable
    for ext in ('.old', '.new'):
        _silent_remove(exe_path + ext)


def ensure_installed(argv, exe_path=None, target=None, launch=_spawn, frozen=None, build=None):
    """Самоустановка в %LOCALAPPDATA%\\GTime\\GTime.exe. True — запущена копия оттуда, этот процесс надо закрыть. Только Windows / exe."""
    frozen = is_frozen() if frozen is None else frozen
    if not frozen or ('--no-install' in argv):
        return False
    build = BUILD if build is None else build
    me = os.path.abspath(exe_path or sys.executable)
    target = os.path.abspath(target or os.path.join(install_dir(), EXE))
    if os.path.normcase(me) == os.path.normcase(target):
        return False
    rest = [a for a in argv[1:] if a not in ('--replace',)]
    folder = os.path.dirname(target)
    try:
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(target) and _read_version(folder) >= build:
            launch(target, rest)                         # там уже такая же или новее — просто запускаем её (она покажет окно)
            return True
        new = target + '.new'
        shutil.copyfile(me, new)
        _swap_in(new, target)
        _write_version(folder, build)
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
