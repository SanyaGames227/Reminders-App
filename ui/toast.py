"""Уведомления в правом нижнем углу: не крадут фокус, стек до 4 + плашка «+N ещё»."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QObject, QPoint, QPropertyAnimation, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QCursor, QFontMetrics, QGuiApplication, QPainter
from PyQt5.QtWidgets import QWidget

import core
import i18n
import theme
from core import Reminder
from theme import S
from ui.backdrop import Backdrop
from ui.widgets import AeroButton, IconButton

MARGIN = 12      # отступ от края рабочей области


def set_no_activate(widget: QWidget) -> None:
    """WS_EX_NOACTIVATE: окно кликабельно, но не забирает фокус."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        put = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        get.restype = ctypes.c_ssize_t; get.argtypes = (wintypes.HWND, ctypes.c_int)
        put.restype = ctypes.c_ssize_t; put.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        hwnd = wintypes.HWND(int(widget.winId()))
        GWL_EXSTYLE, NOACTIVATE, TOOLWINDOW = -20, 0x08000000, 0x00000080
        put(hwnd, GWL_EXSTYLE, get(hwnd, GWL_EXSTYLE) | NOACTIVATE | TOOLWINDOW)
    except Exception:
        pass


class _Popup(QWidget):
    """Общая база: frameless, поверх всех, без активации, прозрачная, с тенью и анимацией."""
    closed = pyqtSignal(object)

    def __init__(self, body_h: int) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                         | Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        m = S.SHADOW
        self.body_h = body_h
        self.setFixedSize(S.TOAST_W + 2 * m, body_h + 2 * m)
        self._target = QPoint()
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setEasingCurve(QEasingCurve.OutCubic)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._leaving = False
        self._bd = Backdrop(self, S.R_PANEL)
        self._bd.changed.connect(self.update)

    def body(self) -> QRectF:
        m = S.SHADOW
        return QRectF(m, m, S.TOAST_W, self.body_h)

    def showEvent(self, e: object) -> None:
        set_no_activate(self)
        super().showEvent(e)  # type: ignore[arg-type]

    def paint_body(self, p: QPainter) -> None:
        """Тень, размытый фон (если есть) со сглаженными скруглёнными краями и стеклянная плашка поверх."""
        body = self.body()
        theme.paint_shadow(p, body)
        pix = self._bd.pixmap()
        if pix is not None:
            p.save()
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrushOrigin(body.topLeft())
            p.setBrush(QBrush(pix))
            p.drawRoundedRect(body.adjusted(.5, .5, -.5, -.5), S.R_PANEL, S.R_PANEL)
            p.restore()
        fill = theme.col("menu")
        fill.setAlpha(150 if self._bd.translucent() else 255)
        theme.paint_glass_panel(p, body, fill=fill)

    def place(self, pos: QPoint) -> None:
        first = not self.isVisible()
        self._target = pos
        self._slide.stop()
        self._slide.setDuration(S.ANIM_TOAST)
        if first:
            self._bd.prepare(pos)
            self.setWindowOpacity(0.0)
            self.move(pos + QPoint(0, 14))
            self.show()
            self._bd.activate()
            self._fade.stop(); self._fade.setDuration(S.ANIM_TOAST)
            self._fade.setStartValue(0.0); self._fade.setEndValue(1.0); self._fade.start()
        self._slide.setStartValue(self.pos()); self._slide.setEndValue(pos); self._slide.start()

    def leave(self, animate: bool = True) -> None:
        if self._leaving:
            return
        self._leaving = True
        self._bd.stop()
        if not animate or not self.isVisible():
            self.close(); self.closed.emit(self); return
        self._slide.stop(); self._fade.stop()
        self._fade.setDuration(S.ANIM_TOAST); self._slide.setDuration(S.ANIM_TOAST)
        self._fade.setStartValue(self.windowOpacity()); self._fade.setEndValue(0.0)
        self._slide.setStartValue(self.pos()); self._slide.setEndValue(self.pos() + QPoint(0, 10))
        self._fade.finished.connect(lambda: (self.close(), self.closed.emit(self)))
        self._fade.start(); self._slide.start()


class Toast(_Popup):
    activated = pyqtSignal(str)
    snoozed = pyqtSignal(str, object)
    dismissed = pyqtSignal(str)       # ✕ на «скоро»: просто закрыть, ничего не откладывая

    def __init__(self, rid: str, title: str, priority: str, due: datetime, early_min: int = 0) -> None:
        super().__init__(S.TOAST_H)
        self.rid, self._title, self._priority, self._due_dt = rid, title, priority, due
        self.early_min = early_min        # > 0: это предупреждение заранее, а не само напоминание
        self._due = ""
        b = self.body()
        self._close = IconButton("close", size=24, glyph=12, parent=self)
        self._close.move(int(b.right() - 30), int(b.top() + 6))
        self._b10 = AeroButton("", compact=True, parent=self)
        self._b60 = AeroButton("", compact=True, parent=self)
        self._close.clicked.connect(lambda: self.dismissed.emit(self.rid) if self.early_min
                                    else self.snoozed.emit(self.rid, core.SNOOZE_DISMISS))
        self._b10.clicked.connect(lambda: self.snoozed.emit(self.rid, core.SNOOZE_SHORT))
        self._b60.clicked.connect(lambda: self.snoozed.emit(self.rid, core.SNOOZE_LONG))
        self.retranslate()

    def retranslate(self) -> None:
        tr = i18n.tr
        mins = int(core.SNOOZE_SHORT.total_seconds() // 60)
        hours = int(core.SNOOZE_LONG.total_seconds() // 3600)
        self._due = i18n.fmt_due(self._due_dt, core.now_local())   # «Сегодня/Завтра», месяцы — тоже зависят от языка
        if self.early_min:
            self._due = tr("early_toast", t=i18n.lead_label(self.early_min), when=self._due)
        self._b10.setText(tr("plus_min", n=mins)); self._b60.setText(tr("plus_hour", n=hours))
        for btn in (self._b10, self._b60):
            btn.adjustSize(); btn.setVisible(not self.early_min)
        b = self.body()
        self._b60.move(int(b.right() - 10 - self._b60.width()), int(b.bottom() - 8 - self._b60.height()))
        self._b10.move(self._b60.x() - 6 - self._b10.width(), self._b60.y())
        self.update()

    def mousePressEvent(self, e: object) -> None:
        if e.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.activated.emit(self.rid)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        b = self.body()
        self.paint_body(p)
        t = theme.tokens()
        bar = theme.qcolor(t["danger" if self._priority == core.HIGH else "accent"])
        p.setPen(Qt.NoPen); p.setBrush(bar)
        p.drawRoundedRect(QRectF(b.left() + 10, b.top() + 12, 4, b.height() - 24), 2, 2)
        f = self.font(); f.setBold(True); f.setPointSizeF(f.pointSizeF() + 1)
        p.setFont(f); p.setPen(theme.col("text"))
        left, width = b.left() + 26, b.width() - 26 - 40
        p.drawText(QRectF(left, b.top() + 10, width, 22), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(self._title, Qt.ElideRight, int(width)))
        f.setBold(False); f.setPointSizeF(f.pointSizeF() - 1)
        p.setFont(f); p.setPen(theme.col("dim"))
        p.drawText(QRectF(left, b.top() + 32, b.width() - 26 - 12, 18), Qt.AlignVCenter | Qt.AlignLeft, self._due)


class MorePill(_Popup):
    clicked = pyqtSignal()
    PILL_H = 36

    def __init__(self) -> None:
        super().__init__(self.PILL_H)
        self._n = 0

    def set_count(self, n: int) -> None:
        self._n = n; self.update()

    def mousePressEvent(self, e: object) -> None:
        if e.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clicked.emit()

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        self.paint_body(p)
        p.setPen(theme.col("text"))
        p.drawText(self.body(), Qt.AlignCenter, i18n.tr("toast_more", n=self._n))


class ToastManager(QObject):
    activated = pyqtSignal(str)
    snoozed = pyqtSignal(str, object)
    more_clicked = pyqtSignal()
    early_closed = pyqtSignal(str)    # пользователь закрыл/открыл «скоро»

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._order: list[str] = []
        self._info: dict[str, tuple[str, str, datetime, int]] = {}
        self._toasts: dict[str, Toast] = {}
        self._pill: Optional[MorePill] = None
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._on_screen); app.screenRemoved.connect(lambda _s: self.relayout())
        for s in app.screens():
            self._on_screen(s)
        i18n.subscribe(self._retranslate)

    def _on_screen(self, screen: object) -> None:
        screen.availableGeometryChanged.connect(lambda _g: self.relayout())  # type: ignore[attr-defined]
        screen.logicalDotsPerInchChanged.connect(lambda _d: self.relayout())  # type: ignore[attr-defined]
        self.relayout()

    def _retranslate(self) -> None:
        for t in self._toasts.values():
            t.retranslate()
        if self._pill:
            self._pill.update()

    # -- API
    def show_alerts(self, items: list[Reminder]) -> None:
        for r in items:
            if r.id not in self._info:
                self._order.append(r.id)
            old = self._toasts.get(r.id)
            if old is not None and old.early_min:       # «скоро» превращается в настоящее уведомление
                self._toasts.pop(r.id).leave(False)
            self._info[r.id] = (r.title, r.priority, r.due, 0)
        self.relayout()

    def show_early(self, items: list[Reminder]) -> None:
        """Предупреждение заранее: без кнопок откладывания; не затирает уже показанное настоящее уведомление."""
        for r in items:
            if r.id in self._info:
                continue
            self._order.append(r.id)
            self._info[r.id] = (r.title, r.priority, r.due, r.early_min)
        self.relayout()

    def dismiss(self, rid: str, animate: bool = True) -> None:
        if rid in self._order:
            self._order.remove(rid); self._info.pop(rid, None)
        toast = self._toasts.pop(rid, None)
        if toast:
            toast.leave(animate)
        self.relayout()

    def has(self, rid: str) -> bool:
        return rid in self._info

    def close_all(self) -> None:
        for t in list(self._toasts.values()):
            t.leave(False)
        self._toasts.clear(); self._order.clear(); self._info.clear()
        if self._pill:
            self._pill.leave(False); self._pill = None

    # -- раскладка
    @staticmethod
    def _screen():
        return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

    def relayout(self) -> None:
        geo = self._screen().availableGeometry()   # учитывает панель задач
        m = S.SHADOW
        visible = self._order[:S.TOAST_MAX]
        for rid in visible:
            if rid not in self._toasts:
                title, prio, due, early = self._info[rid]
                t = Toast(rid, title, prio, due, early)
                t.activated.connect(self._on_activated); t.snoozed.connect(self._on_snoozed)
                t.dismissed.connect(self._on_early_dismissed)
                self._toasts[rid] = t
        x = geo.right() + 1 - MARGIN - S.TOAST_W - m
        bottom = geo.bottom() + 1 - MARGIN
        for rid in visible:
            self._toasts[rid].place(QPoint(x, bottom - S.TOAST_H - m))
            bottom -= S.TOAST_H + S.TOAST_GAP
        extra = len(self._order) - len(visible)
        if extra > 0:
            if self._pill is None:
                self._pill = MorePill(); self._pill.clicked.connect(self.more_clicked)
            self._pill.set_count(extra)
            self._pill.place(QPoint(x, bottom - MorePill.PILL_H - m))
        elif self._pill is not None:
            self._pill.leave(); self._pill = None

    def _on_early_dismissed(self, rid: str) -> None:
        self.dismiss(rid); self.early_closed.emit(rid)

    def _on_activated(self, rid: str) -> None:
        t = self._toasts.get(rid)
        if t is not None and t.early_min:
            self.early_closed.emit(rid)
        self.dismiss(rid); self.activated.emit(rid)

    def _on_snoozed(self, rid: str, delta: timedelta) -> None:
        self.dismiss(rid); self.snoozed.emit(rid, delta)
