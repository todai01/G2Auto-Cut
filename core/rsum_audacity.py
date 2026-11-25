"""Куски «Разбора записи сумм» → проект Audacity.

Сверху — дорожка «Сборка» (рабочий стол): start, свободное место, end. Ниже — по дорожке на каждый класс сумм
(«1 - 100 млн», «100 - 900 тыс», «100 - 900», «1 - 99 тыс», «1 - 100 тенге»): куски в ряд по возрастанию числа
(«0» — в конце), между ними пауза; под каждой дорожкой — метки с числами.

Дорожка собирается одним WAV (во временной папке) и импортируется разом, потом паузы между кусками вырезаются
с сохранением места (SplitDelete) — каждый кусок становится отдельным клипом, его можно перетаскивать.
Так в сотни раз быстрее, чем импортировать каждый файл по отдельности."""
import json
import os
import tempfile
import time

from core.raw_sums import RS_CATS, RS_CAT_DIRS, rs_find_sum_dirs, rs_sum_files

AUD_GAP = 0.5         # с, пауза между кусками на дорожке класса
AUD_DESK = 3.0        # с, свободное место между start и end на «Сборке»
AUD_EDGE = 0.25       # с, тишина перед первым куском


def aud_plan(out, start=None, end=None):
    """Дорожки: [{"name", "pieces": [(метка, путь)], "gap"}] — «Сборка» (если есть start / end) и классы по порядку."""
    tracks = []
    desk = [(lab, p) for lab, p in (('start', start), ('end', end)) if p and os.path.exists(p)]
    if desk:
        tracks.append({"name": 'Сборка', "pieces": desk, "gap": AUD_DESK})
    files = rs_sum_files(rs_find_sum_dirs(out)) if out and os.path.isdir(out) else {}
    for cat in RS_CATS:
        have = files.get(cat) or {}
        if not have:
            continue
        nums = sorted(have, key=lambda n: (n == 0, n))          # «ноль тенге» — в конце
        tracks.append({"name": RS_CAT_DIRS[cat], "pieces": [(str(n), have[n]) for n in nums], "gap": AUD_GAP})
    return tracks


def aud_render(track, folder, ref=None):
    """Дорожка → один WAV (16 бит, моно, частота ref или первого куска) и места кусков [(метка, начало, конец)] в секундах."""
    from pydub import AudioSegment
    from utils.wav_io import segment_to
    segs = []
    for lab, p in track["pieces"]:
        sg = AudioSegment.from_file(p).set_sample_width(2)
        segs.append((lab, sg.set_channels(1) if sg.channels != 1 else sg))
    rate = ref or segs[0][1].frame_rate
    audio = AudioSegment.silent(int(AUD_EDGE * 1000), frame_rate=rate)
    gap = AudioSegment.silent(int(track["gap"] * 1000), frame_rate=rate)
    spots = []
    for k, (lab, sg) in enumerate(segs):
        if k:
            audio += gap
        sg = segment_to(sg, rate, 1)
        a = len(audio)
        audio += sg
        spots.append((lab, a / 1000.0, len(audio) / 1000.0))
    path = os.path.join(folder, f'{len(os.listdir(folder)):02d} {track["name"]}.wav')
    audio.export(path, format='wav')
    return path, spots, rate


def aud_project_path(out):
    base = os.path.join(out, 'Суммы в Audacity')
    p, n = base + '.aup3', 1
    while os.path.exists(p):
        n += 1
        p = f'{base} {n}.aup3'
    return p


class RsumAudacityMixin:
    """«В Audacity» в окне «Разбор записи сумм»."""

    def _aud_tracks_n(self):
        r = self.audacity.send_command('GetInfo: Type=Tracks Format=JSON')
        try:
            return len(json.loads(r[r.find('['):r.rfind(']') + 1]))
        except Exception:
            return None

    def _aud_import(self, path):
        """Импорт файла — номер новой дорожки (ждём, пока Audacity её добавит)."""
        before = self._aud_tracks_n() or 0
        self.audacity.send_command('SelectNone:')
        self.audacity.send_command(f'Import2: Filename="{os.path.abspath(path).replace(chr(92), "/")}"')
        for _ in range(50):
            n = self._aud_tracks_n()
            if n is not None and n > before:
                return n - 1
            time.sleep(0.1)
        return before

    def rsum_to_audacity(self):
        st = self._rsum()
        if st.get("run"):
            return {"error": "Разбор ещё идёт — дождитесь конца."}
        tracks = aud_plan(st.get("out"), st.get("ctx_start"), st.get("ctx_end"))
        if not any(t["name"] != 'Сборка' for t in tracks):
            return {"error": "Кусков по классам сумм нет: разберите запись или укажите готовую папку."}
        if hasattr(self, '_block_if_audacity_ambiguous') and self._block_if_audacity_ambiguous():
            return {"error": "Открыто несколько окон Audacity — закройте лишние и нажмите ещё раз."}
        if not self._ensure_audacity_ready():
            return {"error": "Audacity не отвечает. Откройте его вручную и нажмите ещё раз."}
        self.player.stop()
        folder = tempfile.mkdtemp(prefix='gvox_rsum_aud_')
        try:
            rendered, rate = [], None
            for t in tracks:
                if t["name"] == 'Сборка':
                    continue
                path, spots, rate = aud_render(t, folder, rate)
                rendered.append((t, path, spots))
            if tracks[0]["name"] == 'Сборка':                    # start / end — в частоте кусков сумм
                path, spots, _ = aud_render(tracks[0], folder, rate)
                rendered.insert(0, (tracks[0], path, spots))
        except Exception as e:
            return {"error": f"Не получилось подготовить звук: {e}"}
        a = self.audacity
        a.send_command('SelectAll:')
        a.send_command('RemoveTracks:')
        a.send_command(f'SetProject: Rate={int(rate)}')
        labels, summary = 0, []
        for t, path, spots in rendered:
            idx = self._aud_import(path)
            a.send_command(f'SetTrack: Track={idx} Name="{t["name"]}"')
            # паузы между кусками — вырезать, место оставить: каждый кусок — свой клип
            for (_l0, _s0, e0), (_l1, s1, _e1) in zip(spots, spots[1:]):
                a.send_command(f'SelectTracks: Track={idx} Mode=Set')
                a.send_command(f'SelectTime: Start={e0 + 0.001:.3f} End={s1 - 0.001:.3f} RelativeTo=ProjectStart')
                a.send_command('SplitDelete:')
            # метки с числами — дорожкой ниже
            a.send_command('NewLabelTrack:')
            lt = idx + 1
            a.send_command(f'SetTrack: Track={lt} Name="{t["name"]} — метки"')
            for lab, s0, e0 in spots:
                a.send_command(f'SelectTracks: Track={lt} Mode=Set')
                a.send_command(f'SelectTime: Start={s0:.3f} End={e0:.3f} RelativeTo=ProjectStart')
                a.send_command('AddLabel:')
                a.send_command(f'SetLabel: Label={labels} Text="{lab}"')
                labels += 1
            summary.append({"name": t["name"], "n": len(spots)})
        a.send_command('SelectNone:')
        a.send_command('SelectTime: Start=0 End=20 RelativeTo=ProjectStart')
        a.send_command('ZoomSel:')
        a.send_command('SelectNone:')
        project = aud_project_path(st["out"])
        a.send_command(f'SaveProject2: Filename="{project.replace(chr(92), "/")}"')
        warn = None
        for _ in range(30):
            if os.path.exists(project):
                break
            time.sleep(0.1)
        else:
            warn = 'Проект собран, но файл .aup3 не появился — сохраните его в Audacity вручную (Ctrl+S).'
            project = None
        if hasattr(self, 'get_audacity_windows'):
            try:
                w = self.get_audacity_windows()
                if w:
                    self._force_foreground(w[0]['hwnd'])
            except Exception:
                pass
        return {"ok": True, "tracks": summary, "project": project, "warn": warn}
