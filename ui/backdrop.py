"""Размытый фон под всплывающими окнами. Способ выбирается по платформе:

  live    Windows 10 2004+: окно исключается из захвата экрана (WDA_EXCLUDEFROMCAPTURE), кусочек экрана под
          ним снимается ~30 раз/с, уменьшается, размывается и рисуется как фон. Скругление и тень — свои.
  native  Linux/X11 с KDE (KWin, XWayland): размытие делает композитор по свойству _KDE_NET_WM_BLUR_BEHIND_REGION,
          оно живое и бесплатное. Приложение рисует только полупрозрачное стекло.
  static  Linux/X11 без размытия в композиторе: один снимок при появлении (как раньше).
  solid   Wayland, macOS, снимок не удался: плотная заливка, текст позади не просвечивает.

Принудительный выбор: переменная окружения REMINDERS_BLUR = live | native | static | solid | off.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
from typing import Optional

from PyQt5.QtCore import QObject, QPoint, QRect, QRectF, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QGuiApplication, QImage, QPainter, QPainterPath, QPixmap, QRegion
from PyQt5.QtWidgets import QGraphicsBlurEffect, QGraphicsPixmapItem, QGraphicsScene, QWidget

LIVE, NATIVE, STATIC, SOLID = "live", "native", "static", "solid"

BLUR_RADIUS = 8     # радиус размытия, px (логические)
BLUR_PAD = 10       # запас вокруг плашки при съёмке: без него размытие «съедает» края
DOWNSCALE = 4       # живой режим размывает картинку, уменьшенную в N раз: быстро и на глаз то же
FRAME_MS = 33       # период обновления в живом режиме
WDA_EXCLUDEFROMCAPTURE = 0x11


# ---- выбор режима ------------------------------------------------------------------------------------
def detect_mode() -> str:
    env = os.environ.get("REMINDERS_BLUR", "auto").strip().lower()
    if env in (LIVE, NATIVE, STATIC, SOLID):
        return env
    if env == "off":
        return SOLID
    if sys.platform == "win32":
        return LIVE
    if sys.platform.startswith("linux") and QGuiApplication.platformName() == "xcb":
        kde = "kde" in os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        wayland_session = os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        if kde:
            return NATIVE
        # XWayland видит на экране только X-окна: снимок был бы чёрным пятном
        return SOLID if wayland_session else STATIC
    return SOLID


# ---- размытие средствами Qt --------------------------------------------------------------------------
class _Blurrer:
    """QGraphicsBlurEffect с переиспользуемой сценой: создавать её каждый кадр дорого."""

    def __init__(self) -> None:
        self.item = QGraphicsPixmapItem()
        self.fx = QGraphicsBlurEffect()
        self.fx.setBlurHints(QGraphicsBlurEffect.QualityHint)
        self.item.setGraphicsEffect(self.fx)
        self.scene = QGraphicsScene()
        self.scene.addItem(self.item)

    def blur(self, img: QImage, radius: float) -> QImage:
        self.fx.setBlurRadius(max(0.1, radius))
        self.item.setPixmap(QPixmap.fromImage(img))
        rect = QRectF(img.rect())
        self.scene.setSceneRect(rect)
        out = QImage(img.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        p = QPainter(out); self.scene.render(p, rect, rect); p.end()
        return out


_blurrer: Optional[_Blurrer] = None


def blur_image(img: QImage, radius: float) -> QImage:
    global _blurrer
    if _blurrer is None:
        _blurrer = _Blurrer()
    return _blurrer.blur(img, radius)


def grab_screen(screen: object, x: int, y: int, w: int, h: int) -> QPixmap:
    return screen.grabWindow(0, x, y, w, h)  # type: ignore[attr-defined]


def blurred_backdrop(body: QRect, fast: bool, previous: Optional[QImage] = None
                     ) -> tuple[Optional[QPixmap], Optional[QImage]]:
    """Снимает экран под `body` (глобальные логические координаты) и размывает.
    Возвращает (фон, ключ-кадр для сравнения). fast=True — размытие на уменьшенной копии.
    Если кадр не изменился относительно `previous`, возвращает (None, previous)."""
    screen = QGuiApplication.screenAt(body.center()) or QGuiApplication.primaryScreen()
    geo = screen.geometry()
    area = body.adjusted(-BLUR_PAD, -BLUR_PAD, BLUR_PAD, BLUR_PAD).intersected(geo)
    if not area.contains(body):
        return None, None
    shot = grab_screen(screen, area.x() - geo.x(), area.y() - geo.y(), area.width(), area.height())
    if shot.isNull():
        return None, None
    dpr = shot.devicePixelRatio()
    img = shot.toImage(); img.setDevicePixelRatio(1.0)
    k = DOWNSCALE if fast else 1
    if k > 1:
        small = img.scaled(max(1, img.width() // k), max(1, img.height() // k),
                           Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        if previous is not None and small == previous:
            return None, previous
        blurred = blur_image(small, BLUR_RADIUS * dpr / k).scaled(img.size(), Qt.IgnoreAspectRatio,
                                                                  Qt.SmoothTransformation)
        key: Optional[QImage] = small
    else:
        blurred, key = blur_image(img, BLUR_RADIUS * dpr), None
    crop = blurred.copy(QRect(round((body.x() - area.x()) * dpr), round((body.y() - area.y()) * dpr),
                              round(body.width() * dpr), round(body.height() * dpr)))
    crop.setDevicePixelRatio(dpr)
    return QPixmap.fromImage(crop), key


# ---- Windows: исключить окно из захвата --------------------------------------------------------------
def exclude_from_capture(widget: QWidget) -> bool:
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        return bool(user32.SetWindowDisplayAffinity(wintypes.HWND(int(widget.winId())), WDA_EXCLUDEFROMCAPTURE))
    except Exception:
        return False


# ---- Linux/X11: размытие силами композитора (KWin, picom) ---------------------------------------------
_x11: Optional[tuple] = None


def _x11_lib() -> Optional[tuple]:
    global _x11
    if _x11 is None:
        try:
            lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            lib.XOpenDisplay.restype = ctypes.c_void_p; lib.XOpenDisplay.argtypes = (ctypes.c_char_p,)
            lib.XInternAtom.restype = ctypes.c_ulong
            lib.XInternAtom.argtypes = (ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int)
            lib.XChangeProperty.argtypes = (ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int)
            lib.XDeleteProperty.argtypes = (ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong)
            lib.XFlush.argtypes = (ctypes.c_void_p,)
            dpy = lib.XOpenDisplay(None)
            _x11 = (lib, dpy) if dpy else ()
        except Exception:
            _x11 = ()
    return _x11 or None


def rounded_rects(w: int, h: int, radius: float) -> list[QRect]:
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    return list(QRegion(path.toFillPolygon().toPolygon()).rects())


def set_kde_blur(win_id: int, rects: list[QRect], dpr: float) -> bool:
    """Свойство _KDE_NET_WM_BLUR_BEHIND_REGION: список прямоугольников (x, y, w, h) в пикселях окна.
    Пустой список снимает свойство. Композитор без поддержки его просто игнорирует."""
    x = _x11_lib()
    if x is None:
        return False
    lib, dpy = x
    try:
        atom = lib.XInternAtom(dpy, b"_KDE_NET_WM_BLUR_BEHIND_REGION", 0)
        if rects:
            vals = [round(v * dpr) for r in rects for v in (r.x(), r.y(), r.width(), r.height())]
            data = (ctypes.c_long * len(vals))(*vals)
            lib.XChangeProperty(dpy, win_id, atom, 6, 32, 0, ctypes.cast(data, ctypes.c_void_p), len(vals))  # 6 = XA_CARDINAL
        else:
            lib.XDeleteProperty(dpy, win_id, atom)
        lib.XFlush(dpy)
        return True
    except Exception:
        return False


# ---- провайдер фона для одного окна --------------------------------------------------------------------
class Backdrop(QObject):
    """Живёт вместе с окном-владельцем. Владелец вызывает prepare() до show(), activate() после, stop() при уходе."""
    changed = pyqtSignal()

    def __init__(self, owner: QWidget, radius: float) -> None:
        super().__init__(owner)
        self._owner, self._radius = owner, radius
        self.mode = detect_mode()
        self._pix: Optional[QPixmap] = None
        self._key: Optional[QImage] = None
        self._timer = QTimer(self); self._timer.setInterval(FRAME_MS); self._timer.timeout.connect(self._tick)

    # -- что рисовать
    def pixmap(self) -> Optional[QPixmap]:
        return self._pix

    def translucent(self) -> bool:
        """True — стекло можно делать полупрозрачным: под ним есть размытие (своё или композитора)."""
        return self.mode == NATIVE or self._pix is not None

    # -- жизненный цикл
    def _body_global(self, pos: QPoint) -> QRect:
        return self._owner.body().toRect().translated(pos)  # type: ignore[attr-defined]

    def prepare(self, pos: QPoint) -> None:
        """Первый кадр до показа окна: на экране в этот момент ещё нет самого окна."""
        self._pix = None
        if self.mode in (LIVE, STATIC):
            self._pix, self._key = blurred_backdrop(self._body_global(pos), fast=False)

    def activate(self) -> None:
        if self.mode == LIVE:
            if exclude_from_capture(self._owner):
                self._timer.start()
            else:
                self.mode = STATIC   # окно не исключить (старая Windows): остаётся снимок из prepare()
        elif self.mode == NATIVE:
            b = self._owner.body().toRect()  # type: ignore[attr-defined]
            rects = [r.translated(b.topLeft()) for r in rounded_rects(b.width(), b.height(), self._radius)]
            if not set_kde_blur(int(self._owner.winId()), rects, self._owner.devicePixelRatioF()):
                self.mode = SOLID

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        if not self._owner.isVisible() or self._owner.windowOpacity() <= 0.0:
            return
        pix, key = blurred_backdrop(self._body_global(self._owner.pos()), fast=True, previous=self._key)
        self._key = key
        if pix is not None:
            self._pix = pix; self.changed.emit()
