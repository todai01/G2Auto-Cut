"""Аудит → исправить на месте: записать недостающее (в суфлёре — только оно),
взять готовый файл в нужную папку под нужным именем, разобрать дубли.

Результат последнего аудита (_audit_run) хранится в self._audit_res; каждое
действие меняет его и возвращает целиком — окно аудита перерисовывается
с новыми цифрами без повторного сканирования."""
import os
import re
import shutil
import time
import wave

import webview
from pydub import AudioSegment

from core.num_words import month_abbr

AUDIT_TRASH_DIR = 'trash_аудит'      # «trash» в имени — аудит эту папку не сканирует


class AuditFixMixin:

    # ---------------- куда и в каком формате сохранять ----------------
    def _audit_group(self, gid):
        res = getattr(self, '_audit_res', None) or {}
        return next((g for g in res.get("groups") or [] if g["id"] == gid), None)

    @staticmethod
    def _audit_format(folder):
        """Формат соседних записей папки (частота, бит, каналы); нет — 8 кГц/16/моно."""
        try:
            for name in sorted(os.listdir(folder)):
                if name.lower().endswith('.wav'):
                    with wave.open(os.path.join(folder, name), 'rb') as w:
                        return w.getframerate(), w.getsampwidth(), w.getnchannels()
        except Exception:
            pass
        return 8000, 2, 1

    def _audit_trash(self, path):
        """Файл → «trash_аудит/» рядом с выбранной папкой (не удаляем насовсем)."""
        res = getattr(self, '_audit_res', None) or {}
        root = res.get("scan_dir") or os.path.dirname(path)
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            rel = os.path.basename(path)
        if rel.startswith('..'):
            rel = os.path.basename(path)
        dst = os.path.join(root, AUDIT_TRASH_DIR, time.strftime('%Y-%m-%d_%H-%M-%S'), rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(path, dst)
        return dst

    def _audit_write(self, seg, dst, normalize=True):
        """Сохранить в формате соседних файлов. normalize — громкость речи как у
        готовых записей программы (OUT_SPEECH_DB)."""
        folder = os.path.dirname(dst)
        os.makedirs(folder, exist_ok=True)
        rate, width, ch = self._audit_format(folder)
        seg = seg.set_channels(1)
        if normalize:
            seg = self._tts_normalized(seg)
        tmp = dst + '.tmp.wav'
        codec = {1: 'pcm_u8', 2: 'pcm_s16le', 3: 'pcm_s24le', 4: 'pcm_s32le'}.get(width, 'pcm_s16le')
        try:
            seg.export(tmp, format='wav', parameters=['-ar', str(rate), '-ac', str(ch), '-acodec', codec])
        except Exception:
            seg.set_frame_rate(rate).set_channels(ch).set_sample_width(min(width, 4)).export(tmp, format='wav')
        if os.path.exists(dst):
            self._audit_trash(dst)
        os.replace(tmp, dst)
        return dst

    def _audit_found(self, gid, filename, path):
        """Отметить в результате: недостающее теперь есть."""
        res = self._audit_res
        key = filename.lower()
        m = next((x for x in res["missing"] if x.get("group") == gid and x["filename"].lower() == key), None)
        if m:
            res["missing"].remove(m)
            res["missing_count"] = len(res["missing"])
            f = {"filename": os.path.basename(path), "path": path, "text": m.get("text", ""), "group": gid, "new": True}
            if m.get("phrase"):
                f["phrase"] = m["phrase"]
            if str(gid).startswith('ph_'):
                f["i"] = m["index"] - 1
            res["files"].append(f)
            res["total_disk"] = len(res["files"])
            g = self._audit_group(gid)
            if g:
                g["missing"] = max(0, g["missing"] - 1)
                g["found"] += 1
            last = getattr(self, '_audit_last', None)
            if last and last.get("missing"):
                last["missing"].discard(m.get("text"))
        res["can_export"] = bool(res["can_export"] and res["missing"])
        return res

    def _audit_target(self, gid, filename):
        g = self._audit_group(gid)
        m = next((x for x in (getattr(self, '_audit_res', None) or {}).get("missing") or []
                  if x.get("group") == gid and x["filename"].lower() == str(filename).lower()), None)
        folder = (m or {}).get("dir") or (g or {}).get("target")      # своя папка файла (аудит по таблице студии)
        if not folder:
            return None, {"error": "Не знаю, куда сохранить — запустите аудит заново."}
        name = filename if filename.lower().endswith('.wav') else re.sub(r'\.mp3$', '', filename, flags=re.I) + '.wav'
        return os.path.join(folder, name), None

    # ---------------- записать недостающее — в суфлёре, как обычно ----------------
    def audit_to_prompter(self, scope='all', key=None):
        """Суфлёр показывает только недостающее из аудита (scope: 'all' — всё,
        'group' — группа key, 'one' — с недостающего key и дальше по его группе).
        Дальше всё как обычно: запись, «Сборка», ярусы, сохранение."""
        res = getattr(self, '_audit_res', None)
        if not res:
            return {"error": "Запустите аудит заново."}
        st = getattr(self, 'tts', None)
        if not st or not st.get("units") or not st.get("work_dir"):
            return {"error": "Сначала откройте проект в режиме записи (суфлёр) — недостающее запишется там, как обычно."}
        miss = res.get("missing") or []
        if scope == 'group':
            miss = [m for m in miss if m.get("group") == key]
        elif scope == 'one':
            m0 = miss[int(key)] if 0 <= int(key) < len(miss) else None
            miss = [m for m in miss if m0 and m.get("group") == m0.get("group")]
        if not miss:
            return {"error": "Здесь уже нечего записывать."}
        norm = lambda p: os.path.normcase(os.path.abspath(p))
        want_paths, want_names = {}, {}
        for m in miss:
            g = self._audit_group(m.get("group")) or {}
            if str(m.get("group", '')).startswith('ph_'):
                want_names[re.sub(r'\.(wav|mp3)$', '', m["filename"].lower())] = m
            elif g.get("target"):
                want_paths[norm(os.path.join(g["target"], m["filename"]))] = m
        self._tts_ensure_value_units()
        units, found = [], set()
        for u in st["units"]:                                  # фразы — по названию файла
            if u.get("tiers") or u["kind"] == "value":
                continue
            name = os.path.splitext(os.path.basename(self._tts_target(u)))[0].lower()
            if name in want_names:
                units.append(u["id"])
                found.add(id(want_names[name]))
        rows = sorted(self._tts_row_units(), key=lambda u: u.get("logic") or 0)
        for p, m in want_paths.items():                        # ярусы — первая строка, где есть этот эталон
            u = next((u for u in rows if any(norm(self._tts_tier_path(u, t)) == p for t in u["tiers"])), None)
            if u:
                found.add(id(m))
                if u["id"] not in units:
                    units.append(u["id"])
        if not units:
            return {"error": "Этих записей нет в открытом проекте записи. Откройте в суфлёре проект, чью папку "
                             "«Проверенные» вы проверяли, или запустите аудит по ней."}
        lost = [m["filename"] for m in miss if id(m) not in found]
        first = st["units"][units[0]]
        if "prompt_focus" not in st:                           # куда вернуться после
            st["prompt_focus_restore"] = {"mode": st.get("prompt_mode", "phrases"), "pos": st.get("prompt_pos", 0),
                                          "pos_by": dict(st.get("prompt_pos_by_mode") or {}),
                                          "sum_logic": st.get("sum_logic", 1)}
        st["prompt_focus"] = {"units": units, "n": len(miss) - len(lost)}
        st["prompt_mode"] = first.get("sheet") if first.get("tiers") else "phrases"
        if first.get("logic"):
            st["sum_logic"] = first["logic"]
        self._tts_prompt_fix(0)
        self._tts_save()
        return {"state": self.tts_state(), "n": len(miss) - len(lost), "lost": lost}

    # ---------------- Студия: «Готовые записи» ----------------
    def tts_import_existing(self):
        """Папка с уже записанным → копии на свои места в проекте (как их назвал бы
        суфлёр), чтобы суфлёр видел их записанными. Сверка — как в аудите по
        таблице: все листы, все вложенные папки. Исходники не трогаем, готовое
        в проекте не перезаписываем."""
        st = getattr(self, 'tts', None) or {}
        wd, xl = st.get("work_dir"), st.get("excel_path")
        if not wd or not os.path.isdir(wd):
            return {"error": "Сначала откройте проект Студии (папку проекта) — туда лягут записи."}
        if not xl or not os.path.exists(xl):
            return {"error": "Сначала загрузите таблицу (кнопка «Таблица»)."}
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER, directory=st.get("import_dir") or '')
        if not picked:
            return {"error": "cancel"}
        src_dir = picked if isinstance(picked, str) else picked[0]
        res = self._audit_studio(src_dir, xl, only_work=False)     # чужая папка — все подпапки, кроме корзины
        if res.get("error"):
            return res
        norm = lambda p: os.path.normcase(os.path.abspath(p))
        copied = same = kept = 0
        failed = []
        for f in res.get("files") or []:
            if not f.get("rel") or not os.path.exists(f["path"]):
                continue
            dst = os.path.join(wd, f["rel"])
            if norm(dst) == norm(f["path"]):
                same += 1
                continue
            if os.path.exists(dst):
                kept += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(f["path"], dst)
                copied += 1
            except OSError as e:
                failed.append(f"{f['filename']}: {e}")
        st["import_dir"] = src_dir
        try:                                               # сколько по таблице ещё нет в самом проекте
            left = sum(1 for e in self._audit_studio_expected(xl) if not os.path.exists(os.path.join(wd, e[0])))
        except Exception:
            left = res.get("missing_count", 0)
        self.tts = st
        self.__dict__.pop('_tts_claims_cache', None)
        self._tts_prompt_fix()
        self._tts_save()
        rail = self.tts_ready_to_rail()                    # фразы с переменными — на ленту, для правки
        return {"src": src_dir, "rail": rail.get("added", 0), "found": len(res.get("files") or []), "expected": res.get("total_excel", 0),
                "copied": copied, "same": same, "kept": kept, "failed": failed[:10],
                "extra": len(res.get("extra") or []), "missing": left,
                "state": self.tts_state(), "prompt": self.tts_prompt_info()}

    READY_DIR = 'Готовые'           # внутри «Записи»: исходники готовых файлов для ленты

    def tts_ready_to_rail(self, kinds=('piece',)):
        """Готовые фразы с переменными (и др. по kinds) — на ленту дублями, чтобы
        править их в «Сборке» вместе со значениями и сохранять поверх.
        Исходник — копия в «Записи/Готовые» (правка режет из неё, как из
        записи); сам готовый файл меняется только при сохранении."""
        from core.tts_flow import TTS_CHUNKS_DIR, TTS_RECORDS_DIR
        st = self._tts()
        wd = st.get("work_dir")
        if not wd or not os.path.isdir(wd):
            return {"error": "Сначала откройте проект Студии."}
        have = {t["unit"] for t in st["takes"] if t.get("unit") is not None and not t.get("rejected")}
        src_dir = os.path.join(wd, TTS_RECORDS_DIR, self.READY_DIR)
        n = max([t.get("chunk", 0) for t in st["takes"]] + [0])
        added = 0
        for u in st["units"]:
            if u["kind"] not in kinds or u.get("tiers") or u["id"] in have:
                continue
            target = self._tts_target(u)
            if not os.path.exists(target):
                continue
            try:
                raw = os.path.join(src_dir, os.path.relpath(target, wd).replace(os.sep, '__'))
                if not os.path.exists(raw):
                    os.makedirs(src_dir, exist_ok=True)
                    shutil.copy2(target, raw)
                try:
                    with wave.open(raw, 'rb') as w:
                        ms = int(w.getnframes() * 1000 / w.getframerate())
                except Exception:
                    ms = len(AudioSegment.from_file(raw))
                n += 1
                f = os.path.join(TTS_CHUNKS_DIR, f"{n:04d}.wav")
                os.makedirs(os.path.join(wd, TTS_CHUNKS_DIR), exist_ok=True)
                shutil.copy2(raw, os.path.join(wd, f))
            except OSError:
                continue
            st["takes"].append({"file": f, "start_ms": 0, "ms": ms, "orig": [0, ms], "raw": raw, "heard": '',
                                "listened": True, "chunk": n, "unit": u["id"], "score": 1.0, "status": "manual",
                                "approved": True, "ready": True})
            added += 1
        if added:
            first = len(st["takes"]) - added
            st["index"] = first
            self._tts_save()
        return {"added": added, "state": self.tts_state()}

    def audit_export_folders(self):
        """«Разложить по папкам Студии»: найденные записи — копиями в выбранную
        папку, в той же структуре, что создаёт суфлёр (Проверенные/…,
        Фразы_Переменные/…, Значения/<лист>/<категория>/…); папки категорий
        создаются и для пока пустых. Исходники не трогаем, готовое не перезаписываем."""
        res = getattr(self, '_audit_res', None)
        if not res or res.get("mode") != "studio":
            return {"error": "Сначала запустите аудит по таблице Студии записи."}
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER, directory=res.get("scan_dir") or '')
        if not picked:
            return {"error": "cancel"}
        dest = picked if isinstance(picked, str) else picked[0]
        norm = lambda p: os.path.normcase(os.path.abspath(p))
        copied = same = kept = 0
        failed = []
        for g in res.get("groups") or []:
            if g.get("rel_dir"):
                os.makedirs(os.path.join(dest, g["rel_dir"]), exist_ok=True)
        for f in res.get("files") or []:
            if not f.get("rel") or not os.path.exists(f["path"]):
                continue
            dst = os.path.join(dest, f["rel"])
            if norm(dst) == norm(f["path"]):
                same += 1                                  # уже лежит на своём месте
                continue
            if os.path.exists(dst):
                kept += 1                                  # там уже есть файл — не перезаписываем
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(f["path"], dst)
                copied += 1
            except OSError as e:
                failed.append(f"{f['filename']}: {e}")
        return {"dest": dest, "copied": copied, "same": same, "kept": kept, "failed": failed[:10],
                "folders": sorted({g["rel_dir"] for g in res.get("groups") or [] if g.get("rel_dir")})}

    def audit_final_folder(self):
        """Финальная папка сдачи по результату аудита: «Финал_<дата>/» с двумя
        папками — «Перманентные_<дата>» (все фразы и кусочки фраз с
        переменными одной папкой) и «Переменные_<дата>» (содержимое «Значения»:
        <лист>/<категория>/<значение>.wav). Берутся только найденные аудитом
        записи из рабочих папок; исходники не трогаем."""
        res = getattr(self, '_audit_res', None)
        if not res or res.get("mode") != "studio":
            return {"error": "Сначала запустите аудит по таблице Студии записи."}
        picked = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER,
                                                       directory=os.path.dirname(os.path.normpath(res.get("scan_dir") or '')))
        if not picked:
            return {"error": "cancel"}
        base = picked if isinstance(picked, str) else picked[0]
        date = time.strftime('%d.%m.%Y')
        root = os.path.join(base, f"Финал_{date}")
        n = 2
        while os.path.exists(root):                            # уже собирали сегодня — рядом новая
            root = os.path.join(base, f"Финал_{date} ({n})")
            n += 1
        perm, var = os.path.join(root, f"Перманентные_{date}"), os.path.join(root, f"Переменные_{date}")
        os.makedirs(perm)
        os.makedirs(var)
        n_perm = n_var = 0
        clash, failed, seen = [], [], {}
        for f in res.get("files") or []:
            rel = (f.get("rel") or '').replace('\\', '/')
            if not rel or not os.path.exists(f["path"]):
                continue
            parts = rel.split('/')
            if self._audit_norm_dir(parts[0]) == 'значения':
                dst = os.path.join(var, *parts[1:])
                cat = parts[-2] if len(parts) >= 3 else ''
                lm = re.search(r'_(ru|kz|kk)$', cat.lower())
                ab = month_abbr(os.path.splitext(parts[-1])[0]) if re.sub(r'_(ru|kz|kk)$', '', cat.lower()) == 'month' else None
                if ab:                                         # месяцы — коротко по-английски: jan_kz.wav, jan_ru.wav
                    lang = 'kz' if lm and lm.group(1) in ('kz', 'kk') else 'ru'
                    dst = os.path.join(os.path.dirname(dst), f"{ab}_{lang}{os.path.splitext(parts[-1])[1]}")
            else:
                dst = os.path.join(perm, parts[-1])
                key = parts[-1].lower()
                if key in seen:                                # одно имя из двух папок — оставляем первый
                    if os.path.normcase(seen[key]) != os.path.normcase(f["path"]):
                        clash.append(parts[-1])
                    continue
                seen[key] = f["path"]
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(f["path"], dst)
                if dst.startswith(var):
                    n_var += 1
                else:
                    n_perm += 1
            except OSError as e:
                failed.append(f"{f['filename']}: {e}")
        return {"dest": root, "perm": n_perm, "var": n_var, "perm_dir": os.path.basename(perm),
                "var_dir": os.path.basename(var), "missing": res.get("missing_count", 0),
                "duplicates": res.get("duplicates_count", 0), "clash": clash[:10], "failed": failed[:10]}

    def audit_rerun(self):
        """Проверить снова ту же папку (после записи в суфлёре)."""
        res = getattr(self, '_audit_res', None)
        if not res or not os.path.isdir(res.get("scan_dir") or ''):
            return {"error": "Запустите аудит заново."}
        if res.get("mode") == "studio":
            return self._audit_studio(res["scan_dir"], res["studio_excel"])
        return self._audit_run(res["scan_dir"], res["parts"], res["mode"])

    # ---------------- готовый файл вместо записи ----------------
    def audit_put_file(self, gid, filename):
        """Взять готовую запись (любой формат) — сохранить как недостающий файл."""
        dst, err = self._audit_target(gid, filename)
        if err:
            return err
        picked = webview.windows[0].create_file_dialog(
            webview.FileDialog.OPEN, file_types=('Аудио (*.wav;*.mp3;*.flac;*.ogg;*.m4a)', 'Все файлы (*.*)'))
        if not picked:
            return {"error": "cancel"}
        src = picked if isinstance(picked, str) else picked[0]
        try:
            self._audit_write(AudioSegment.from_file(src), dst, normalize=False)
        except Exception as e:
            return {"error": f"Не удалось взять файл: {e}"}
        return {"saved": dst, "res": self._audit_found(gid, os.path.basename(filename), dst)}

    # ---------------- дубли ----------------
    def audit_dup_keep(self, gid, filename, keep):
        """Оставить один из дублей; остальные — в «trash_аудит/» (не удаляются)."""
        res = getattr(self, '_audit_res', None)
        if not res:
            return {"error": "Запустите аудит заново."}
        d = next((x for x in res["duplicates"] if x.get("group") == gid and x["filename"] == filename), None)
        if not d or keep not in d["paths"]:
            return {"error": "Этот дубль уже разобран."}
        moved = []
        for p in d["paths"]:
            if p != keep and os.path.exists(p):
                try:
                    moved.append(self._audit_trash(p))
                except Exception as e:
                    return {"error": f"Не удалось убрать {os.path.basename(p)}: {e}"}
        res["duplicates"].remove(d)
        res["duplicates_count"] = len(res["duplicates"])
        g = self._audit_group(gid)
        if g:
            g["duplicates"] = max(0, g["duplicates"] - 1)
        for f in res["files"]:
            if f.get("group") == gid and f["filename"].lower() == filename:
                f["path"] = keep
        return {"moved": len(moved), "trash": os.path.join(res["scan_dir"], AUDIT_TRASH_DIR), "res": res}

    def audit_open_folder(self, path):
        path = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(path):
            return {"error": "Папки нет."}
        try:
            os.startfile(path)                      # Windows
        except AttributeError:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        return {"ok": True}
