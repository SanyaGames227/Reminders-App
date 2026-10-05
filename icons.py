"""Векторные иконки (QPainter), иконка приложения, экспорт .ico, генерация и проигрывание звука.

Запуск `python icons.py` экспортирует icon.ico для PyInstaller.
"""
from __future__ import annotations

import functools
import math
import struct
import sys
import wave
from pathlib import Path
from typing import Callable

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QRadialGradient)

import storage

GRID = 16.0  # все иконки нарисованы на сетке 16×16


# ---- Примитивы ---------------------------------------------------------------------------
def _poly(pts: list[tuple[float, float]], close: bool = False) -> QPainterPath:
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    return path


def _lines(*segs: tuple[float, float, float, float]) -> QPainterPath:
    path = QPainterPath()
    for x1, y1, x2, y2 in segs:
        path.moveTo(x1, y1)
        path.lineTo(x2, y2)
    return path


def _circle(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), r, r)
    return path


def _circular_arrow(rect: QRectF, start: float, span: float) -> QPainterPath:
    """Дуга со стрелкой на конце (углы в градусах, против часовой — как в Qt)."""
    path = QPainterPath()
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, span)
    end = path.currentPosition()
    theta = math.radians(start + span)
    sign = 1 if span > 0 else -1
    dx, dy = -math.sin(theta) * sign, -math.cos(theta) * sign
    for a in (math.radians(150), math.radians(-150)):
        rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
        path.moveTo(end)
        path.lineTo(end.x() + rx * 3.2, end.y() + ry * 3.2)
    return path


def _bell_body() -> QPainterPath:
    p = QPainterPath(QPointF(3, 11.5))
    p.cubicTo(4.6, 10.3, 4.6, 8.8, 4.6, 7)
    p.cubicTo(4.6, 4.6, 6.2, 3.6, 8, 3.6)
    p.cubicTo(9.8, 3.6, 11.4, 4.6, 11.4, 7)
    p.cubicTo(11.4, 8.8, 11.4, 10.3, 13, 11.5)
    p.closeSubpath()
    return p


def _bell_clapper() -> QPainterPath:
    p = QPainterPath(QPointF(6.3, 12.6))
    p.quadTo(8, 15, 9.7, 12.6)
    return p


# Каждая иконка: (список контуров-штрихов, список залитых контуров)
def _build_icons() -> dict[str, Callable[[], tuple[list[QPainterPath], list[QPainterPath]]]]:
    def stroke(*paths: QPainterPath):
        return lambda: (list(paths), [])

    def mixed(strokes: list[QPainterPath], fills: list[QPainterPath]):
        return lambda: (strokes, fills)

    rrect = QPainterPath()
    rrect.addRoundedRect(QRectF(2.5, 3.5, 11, 10), 1.8, 1.8)

    pencil = QPainterPath()
    pencil.moveTo(3.2, 12.8); pencil.lineTo(4, 9.6); pencil.lineTo(10.6, 3); pencil.lineTo(13, 5.4)
    pencil.lineTo(6.4, 12); pencil.closeSubpath()

    gear = QPainterPath()
    gear.addEllipse(QPointF(8, 8), 4.2, 4.2)
    gear.addEllipse(QPointF(8, 8), 1.7, 1.7)
    teeth = QPainterPath()
    for i in range(8):
        a = math.radians(i * 45)
        teeth.moveTo(8 + 4.9 * math.cos(a), 8 + 4.9 * math.sin(a))
        teeth.lineTo(8 + 6.6 * math.cos(a), 8 + 6.6 * math.sin(a))

    folder = _poly([(2.5, 4), (6.5, 4), (7.7, 5.7), (13.5, 5.7), (13.5, 12.5), (2.5, 12.5)], True)

    undo = _poly([(6.5, 3.5), (3.5, 6.5), (6.5, 9.5)])
    undo.moveTo(3.5, 6.5); undo.lineTo(9, 6.5)
    undo.cubicTo(12.4, 6.5, 12.4, 12.5, 9, 12.5); undo.lineTo(6, 12.5)

    trash = _lines((3, 4.5, 13, 4.5), (6.5, 4.5, 6.5, 3), (6.5, 3, 9.5, 3), (9.5, 3, 9.5, 4.5),
                   (7, 7, 7, 11), (9, 7, 9, 11))
    trash.addPath(_poly([(4.5, 4.5), (5.2, 13), (10.8, 13), (11.5, 4.5)]))

    cal = QPainterPath(rrect)
    cal.addPath(_lines((2.5, 6.5, 13.5, 6.5), (5.5, 2, 5.5, 4.5), (10.5, 2, 10.5, 4.5)))

    clock_hands = _poly([(8, 4.8), (8, 8), (10.4, 9.4)])
    lst = _lines((5.5, 4.5, 13, 4.5), (5.5, 8, 13, 8), (5.5, 11.5, 13, 11.5))

    return {
        "check": stroke(_poly([(3.5, 8.5), (6.7, 11.6), (12.5, 4.6)])),
        "close": stroke(_lines((4, 4, 12, 12), (12, 4, 4, 12))),
        "plus": stroke(_lines((8, 3, 8, 13), (3, 8, 13, 8))),
        "dash": stroke(_lines((4, 8, 12, 8))),
        "dot": mixed([], [_circle(8, 8, 3.2)]),
        "arrow_down": stroke(_poly([(4, 6), (8, 10), (12, 6)])),
        "arrow_up": stroke(_poly([(4, 10), (8, 6), (12, 10)])),
        "arrow_left": stroke(_poly([(10, 4), (6, 8), (10, 12)])),
        "arrow_right": stroke(_poly([(6, 4), (10, 8), (6, 12)])),
        "edit": stroke(pencil),
        "trash": stroke(trash),
        "repeat": stroke(_circular_arrow(QRectF(3, 3, 10, 10), 70, 280)),
        "restore": stroke(undo),
        "search": stroke(_circle(6.7, 6.7, 4.2), _lines((9.8, 9.8, 13, 13))),
        "bell": mixed([_bell_clapper()], [_bell_body()]),
        "clock": stroke(_circle(8, 8, 5.6), clock_hands),
        "history": stroke(_circular_arrow(QRectF(2.2, 2.2, 11.6, 11.6), 80, 285), _poly([(8, 5.4), (8, 8), (10, 9.3)])),
        "all": mixed([lst], [_circle(3, 4.5, 0.9), _circle(3, 8, 0.9), _circle(3, 11.5, 0.9)]),
        "today": mixed([cal], [_circle(8, 10, 1.1)]),
        "overdue": mixed([_circle(8, 8, 5.6), _lines((8, 4.8, 8, 8.6))], [_circle(8, 11, 0.9)]),
        "settings": stroke(gear, teeth),
        "folder": stroke(folder),
    }


_ICONS = _build_icons()


def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor, pen_w: float = 1.5) -> None:
    strokes, fills = _ICONS[name]()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(rect.topLeft())
    p.scale(rect.width() / GRID, rect.height() / GRID)
    pen = QPen(color, pen_w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    for s in strokes:
        p.drawPath(s)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    for f in fills:
        p.drawPath(f)
    p.restore()


def icon_image(name: str, size: int, color: QColor, dpr: float = 1.0, pen_w: float = 1.5) -> QImage:
    px = max(1, round(size * dpr))
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_icon(p, name, QRectF(0, 0, px, px), color, pen_w)
    p.end()
    img.setDevicePixelRatio(dpr)
    return img


def icon_pixmap(name: str, size: int, color: QColor, dpr: float = 1.0) -> QPixmap:
    return QPixmap.fromImage(icon_image(name, size, color, dpr))


# ---- Иконка приложения ---------------------------------------------------------------------
def app_icon_image(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    m = size * 0.04
    body = QRectF(m, m, size - 2 * m, size - 2 * m)
    r = size * 0.22
    bg = QLinearGradient(0, body.top(), 0, body.bottom())
    bg.setColorAt(0, QColor("#7fd4f7")); bg.setColorAt(0.5, QColor("#2b9be0"))
    bg.setColorAt(0.51, QColor("#1c6fc2")); bg.setColorAt(1, QColor("#2f8ee0"))
    p.setPen(QPen(QColor(10, 50, 100, 220), max(1.0, size * 0.025)))
    p.setBrush(bg)
    p.drawRoundedRect(body, r, r)
    p.setPen(QPen(QColor(255, 255, 255, 150), max(1.0, size * 0.02)))
    p.setBrush(Qt.NoBrush)
    inner = body.adjusted(size * 0.03, size * 0.03, -size * 0.03, -size * 0.03)
    p.drawRoundedRect(inner, r * 0.8, r * 0.8)
    # колокольчик: тень + белая заливка
    bell = QRectF(size * 0.16, size * 0.14, size * 0.68, size * 0.68)
    p.save()
    p.translate(bell.topLeft()); p.scale(bell.width() / GRID, bell.height() / GRID)
    shadow = QPainterPath(_bell_body()); shadow.translate(0.0, 0.5)
    p.setPen(Qt.NoPen); p.setBrush(QColor(5, 40, 90, 110)); p.drawPath(shadow)
    p.setBrush(QColor("#ffffff")); p.drawPath(_bell_body())
    p.drawEllipse(QPointF(8, 3.1), 0.9, 0.9)
    clap = QPainterPath(); clap.addEllipse(QPointF(8, 13.1), 1.7, 1.3)
    p.drawPath(clap)
    p.restore()
    # верхний блик
    gloss = QPainterPath()
    gloss.addRoundedRect(body.adjusted(size * 0.04, size * 0.04, -size * 0.04, -size * 0.5), r * 0.7, r * 0.7)
    g = QLinearGradient(0, body.top(), 0, body.top() + size * 0.5)
    g.setColorAt(0, QColor(255, 255, 255, 120)); g.setColorAt(1, QColor(255, 255, 255, 10))
    p.setPen(Qt.NoPen); p.setBrush(g); p.drawPath(gloss)
    p.end()
    return img


@functools.lru_cache(maxsize=1)
def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(app_icon_image(s)))
    return icon


def export_ico(path: Path) -> None:
    """ICO с PNG-кадрами (поддерживается Windows Vista+ и PyInstaller)."""
    sizes = (16, 24, 32, 48, 64, 128, 256)
    frames = []
    for s in sizes:
        ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
        app_icon_image(s).save(buf, "PNG"); buf.close()
        frames.append(bytes(ba))
    out = bytearray(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for s, data in zip(sizes, frames):
        out += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    for data in frames:
        out += data
    path.write_bytes(bytes(out))


# ---- Звук ----------------------------------------------------------------------------------
SAMPLE_RATE = 22050
SOUND_VERSION = 1


def _chime(freq: float, dur: float = 0.55) -> list[float]:
    n = int(SAMPLE_RATE * dur)
    out = []
    for i in range(n):
        t = i / SAMPLE_RATE
        env = min(1.0, t / 0.006) * math.exp(-5.5 * t)
        s = math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(2 * math.pi * 2 * freq * t) \
            + 0.12 * math.sin(2 * math.pi * 3 * freq * t)
        out.append(s * env * 0.42)
    return out


def _write_wav(path: Path, samples: list[float]) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in samples))


def sound_path(high: bool) -> Path:
    """WAV создаётся один раз во временной папке системы."""
    path = storage.temp_dir() / f"alert-{'high' if high else 'normal'}-v{SOUND_VERSION}.wav"
    if not path.exists():
        if high:   # двойной сигнал
            gap = [0.0] * int(SAMPLE_RATE * 0.08)
            samples = _chime(1046.5, 0.3) + gap + _chime(1318.5, 0.5)
        else:
            samples = _chime(880.0)
        _write_wav(path, samples)
    return path


def play_alert(high: bool) -> None:
    """Windows — winsound; Linux/macOS — внешний проигрыватель (paplay, pw-play, aplay, afplay). Тихо, если нет."""
    try:
        path = str(sound_path(high))
        if sys.platform == "win32":
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            return
        import shutil
        import subprocess
        for player in ("afplay", "pw-play", "paplay", "aplay"):
            exe = shutil.which(player)
            if exe:
                subprocess.Popen([exe, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    except Exception:  # нет звукового устройства
        pass


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "icon.ico"
    export_ico(out)
    print("written", out)
