"""Обновление GTime через папку команды в Api: проверка раз в час, «Обновить», «Опубликовать для команды»."""
import os
import sys
import threading
import time

import team
import updater

CHECK_EVERY = 3600                                       # секунд между проверками папки
FIRST_CHECK = 20                                         # первая проверка — через 20 с после запуска


class UpdateMixin:
    def _update_init(self):
        self._upd = {"checked_at": None, "remote": None, "available": False, "error": ""}
        self._upd_next = time.monotonic() + FIRST_CHECK
        self._upd_busy = False
        self._upd_notified = 0

    def _exe_path(self):
        return sys.executable

    def _frozen(self):
        return updater.is_frozen()

    # ---------- проверка ----------
    def _update_check_now(self, notify=True):
        try:
            r = updater.check(self._s.get("team_dir") or '')
            self._upd = {"checked_at": time.strftime('%Y-%m-%dT%H:%M:%S'), "remote": r["remote"], "available": r["available"], "error": ""}
            if r["available"] and notify and self._upd_notified != r["remote"]["version"] and hasattr(self._t, "notify"):
                self._upd_notified = r["remote"]["version"]
                self._t.notify("update", f'Доступна новая версия GTime ({r["remote"]["version"]}) — обновите в главном окне')
        except (updater.UpdateError, OSError) as e:
            self._upd = {**self._upd, "checked_at": time.strftime('%Y-%m-%dT%H:%M:%S'), "available": False, "error": str(e)}
        finally:
            self._upd_busy = False

    def _update_maybe(self):
        """Из тика: раз в час, в отдельном потоке (сеть не тормозит учёт). Только для собранного exe с номером сборки."""
        if self._upd_busy or time.monotonic() < self._upd_next or not self._s.get("team_dir") or not self._frozen() or updater.BUILD <= 0:
            return
        self._upd_busy, self._upd_next = True, time.monotonic() + CHECK_EVERY
        threading.Thread(target=self._update_check_now, daemon=True).start()

    # ---------- для JS ----------
    def update_status(self):
        u = self._upd
        return {"build": updater.BUILD, "frozen": self._frozen(), "dir": self._s.get("team_dir") or '', "remote": u["remote"],
                "available": bool(u["available"]), "checked_at": u["checked_at"], "error": u["error"]}

    def update_check(self):
        """Проверить прямо сейчас (кнопка «Проверить»)."""
        self._update_check_now(notify=False)
        return self.update_status()

    def update_apply(self):
        """«Обновить»: заменить программу новой сборкой из папки команды и перезапуститься."""
        if not self._frozen() or updater.BUILD <= 0:
            return {"error": "Обновление работает только в собранном GTime.exe."}
        self._update_check_now(notify=False)
        if not self._upd["available"]:
            return {"error": self._upd["error"] or "Новой версии нет."}
        try:
            self._t.save()
            v = updater.apply_update(self._s.get("team_dir") or '', self._exe_path(), launch=self._relaunch)
        except updater.UpdateError as e:
            return {"error": str(e)}
        threading.Timer(0.6, self.close_app).start()     # новая копия уже запускается и дождётся нашего выхода
        return {"ok": True, "version": v}

    def _relaunch(self, exe, args):
        updater._spawn(exe, args)

    def update_publish(self, notes=''):
        """Администратор: выложить ЭТОТ exe в папку команды — все получат «Обновить»."""
        if not self._frozen() or updater.BUILD <= 0:
            return {"error": "Выкладывать можно только собранный GTime.exe (в нём есть номер сборки)."}
        if not self._s.get("team_dir"):
            return {"error": "Папка команды не выбрана."}
        if not self._user or self._user.get("role") != 'admin':
            return {"error": "Только для администратора: войдите под учёткой администратора."}
        try:
            m = updater.publish(self._s["team_dir"], self._exe_path(), notes=notes)
        except (updater.UpdateError, OSError) as e:
            return {"error": str(e) if isinstance(e, updater.UpdateError) else f"Не удалось выложить: {e.strerror or e}"}
        self._upd = {"checked_at": time.strftime('%Y-%m-%dT%H:%M:%S'), "remote": m, "available": False, "error": ""}
        return {"ok": True, "version": m["version"], "size": m["size"]}
