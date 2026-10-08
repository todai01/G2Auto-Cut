"""Работа с WAV без потери качества.

pydub при сохранении меняет формат: 24-битная запись становится 32-битной,
float — целочисленной. Здесь:
  • wav_slice — вырезать кусок байт в байт (никакого перекодирования);
  • export_like — сохранить обработанный звук (громкость, обрезка, склейка)
    в том же формате, что исходник: та же разрядность, float остаётся float."""

import os
import struct

WAVE_PCM, WAVE_FLOAT, WAVE_EXT = 1, 3, 0xFFFE


def wav_layout(path):
    """(байты fmt, начало data, размер data, байт на кадр, частота) или None."""
    try:
        total = os.path.getsize(path)
        with open(path, 'rb') as f:
            head = f.read(12)
            if len(head) < 12 or head[:4] != b'RIFF' or head[8:12] != b'WAVE':
                return None
            fmt, pos = None, 12
            while pos + 8 <= total:
                f.seek(pos)
                cid, size = struct.unpack('<4sI', f.read(8))
                if cid == b'fmt ':
                    fmt = f.read(size)
                elif cid == b'data':
                    if fmt is None or len(fmt) < 16:
                        return None
                    block = struct.unpack('<H', fmt[12:14])[0]
                    rate = struct.unpack('<I', fmt[4:8])[0]
                    return fmt, pos + 8, min(size, total - pos - 8), block, rate
                pos += 8 + size + (size & 1)
    except (OSError, struct.error):
        return None
    return None


def wav_kind(path):
    """('float' | 'int', бит на сэмпл) исходника или None."""
    lay = wav_layout(path)
    if not lay:
        return None
    fmt = lay[0]
    tag, bits = struct.unpack('<H', fmt[0:2])[0], struct.unpack('<H', fmt[14:16])[0]
    if tag == WAVE_EXT and len(fmt) >= 26:
        tag = struct.unpack('<H', fmt[24:26])[0]   # первые 2 байта SubFormat GUID
    return ('float' if tag == WAVE_FLOAT else 'int'), bits


def _write_wav(dst, fmt, data):
    fmt_chunk = b'fmt ' + struct.pack('<I', len(fmt)) + fmt + (b'\0' if len(fmt) & 1 else b'')
    body = b'WAVE' + fmt_chunk + b'data' + struct.pack('<I', len(data)) + data + (b'\0' if len(data) & 1 else b'')
    with open(dst, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', len(body)) + body)


def wav_slice(src, dst, start_ms, end_ms):
    """Вырезает кусок WAV без перекодирования — те же байты и тот же
    fmt-блок (частота, разрядность, каналы). False — исходник не WAV."""
    lay = wav_layout(src)
    if not lay:
        return False
    fmt, data_pos, data_size, block, rate = lay
    if block <= 0 or rate <= 0:
        return False
    a = max(0, int(start_ms * rate / 1000)) * block
    b = min(data_size // block, int(end_ms * rate / 1000)) * block
    if b <= a:
        return False
    with open(src, 'rb') as f:
        f.seek(data_pos + a)
        data = f.read(b - a)
    _write_wav(dst, fmt, data)
    return True


def slice_or_export(src, dst, start_ms, end_ms, segment=None):
    """Кусок [start_ms, end_ms) исходника в dst: байт в байт, если это WAV,
    иначе (mp3 и т.п.) — обычным сохранением pydub из уже прочитанного segment."""
    if wav_slice(src, dst, start_ms, end_ms):
        return
    if segment is None:
        from pydub import AudioSegment
        segment = AudioSegment.from_file(src)
    segment[start_ms:end_ms].export(dst, format="wav")


def export_like(segment, dst, like_path=None, kind=None):
    """Сохраняет обработанный звук в WAV той же разрядности и того же типа
    (int/float), что like_path (или kind=('int'|'float', бит)). Частота и
    каналы — как у segment (если их меняли намеренно — так и остаётся)."""
    kind = kind or (wav_kind(like_path) if like_path and os.path.exists(like_path) else None)
    if not kind:
        segment.export(dst, format="wav")
        return
    sort, bits = kind
    if sort == 'int' and bits in (8, 16, 32) and bits // 8 == segment.sample_width:
        segment.export(dst, format="wav")
        return
    import numpy as np
    w = segment.sample_width
    raw = np.frombuffer(segment.raw_data, dtype={1: np.uint8, 2: '<i2', 4: '<i4'}.get(w, '<i2'))
    if w == 1:
        x = (raw.astype(np.float64) - 128) / 128.0
    else:
        x = raw.astype(np.float64) / float(2 ** (8 * w - 1))
    ch, rate = segment.channels, segment.frame_rate
    if sort == 'float':
        bits = 64 if bits == 64 else 32
        data = x.astype('<f8' if bits == 64 else '<f4').tobytes()
        tag, extra = WAVE_FLOAT, struct.pack('<H', 0)
    else:
        bits = bits if bits in (8, 16, 24, 32) else 16
        if bits == 8:
            data = np.clip(np.round(x * 128 + 128), 0, 255).astype(np.uint8).tobytes()
        else:
            top = 2 ** (bits - 1)
            v = np.clip(np.round(x * top), -top, top - 1).astype('<i4')
            data = v.tobytes() if bits == 32 else (
                v.astype('<i2').tobytes() if bits == 16 else v.view(np.uint8).reshape(-1, 4)[:, :3].tobytes())
        tag, extra = WAVE_PCM, b''
    block = ch * bits // 8
    fmt = struct.pack('<HHIIHH', tag, ch, rate, rate * block, block, bits) + extra
    _write_wav(dst, fmt, data)


def wav_concat(src, dst, ranges_ms):
    """Склеивает куски исходника [(начало_мс, конец_мс), …] в один WAV —
    байт в байт, без перекодирования (вырезы внутри фразы)."""
    lay = wav_layout(src)
    if not lay:
        return False
    fmt, data_pos, data_size, block, rate = lay
    if block <= 0 or rate <= 0:
        return False
    out = []
    with open(src, 'rb') as f:
        for s, e in ranges_ms:
            a = max(0, int(s * rate / 1000)) * block
            b = min(data_size // block, int(e * rate / 1000)) * block
            if b > a:
                f.seek(data_pos + a)
                out.append(f.read(b - a))
    if not out:
        return False
    _write_wav(dst, fmt, b''.join(out))
    return True
