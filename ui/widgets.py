"""Общие Aero-виджеты: кнопки с hover-анимацией, поиск, комбобокс, календарь, диалоги."""
from __future__ import annotations

import time
from typing import Optional

from PyQt5.QtCore import (QDate, QEasingCurve, QEvent, QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation, pyqtSignal)
from PyQt5.QtGui import QColor, QCursor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QTextCharFormat
from PyQt5.QtWidgets import (QAbstractButton, QApplication, QCalendarWidget, QComboBox, QDialog, QHBoxLayout, QMenu,
                             QLabel, QLineEdit, QListView, QPushButton, QStyledItemDelegate, QTableView,
                             QDateEdit, QTextEdit, QTimeEdit, QVBoxLayout, QWidget)

import core
import i18n
import icons
import theme
from theme import S


# ---- Анимация наведения ------------------------------------------------------------------------
class HoverAnim(QObject):
    """Плавный прогресс 0..1 при наведении (QVariantAnimation, 120–180 мс)."""

    def __init__(self, widget: QWidget, duration: int = S.ANIM_FAST) -> None:
        super().__init__(widget)
        self.widget, self.value = widget, 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(duration)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set)
        widget.installEventFilter(self)

    def _set(self, v: object) -> None:
        self.value = max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
        try:
            self.widget.update()
        except RuntimeError:          # виджет уже удалён (например, строку списка пересоздали на лету)
            self._anim.stop()

    def go(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self.value)
        self._anim.setEndValue(target)
        self._anim.start()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() == QEvent.Enter:
            self.go(1.0)
        elif ev.type() in (QEvent.Leave, QEvent.Hide):
            self.go(0.0)
        return False


class FocusClearer(QObject):
    """Клик по «пустому» месту снимает фокус (и подсветку) с поля, списка, флажка и т.п.
    «Пустое» — виджет, у которого ни он сам, ни его родители не принимают фокус по клику."""

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() != QEvent.MouseButtonPress or not isinstance(obj, QWidget):
            return False
        if obj.window().windowType() == Qt.Popup or obj.inherits("QScrollBar"):
            return False
        w: Optional[QWidget] = obj
        while w is not None and not w.isWindow():
            proxy = w.focusProxy()
            if (w.focusPolicy() & Qt.ClickFocus) or (proxy is not None and proxy.focusPolicy() & Qt.ClickFocus):
                return False
            w = w.parentWidget()
        focused = QApplication.focusWidget()
        if focused is not None and focused is not obj:
            focused.clearFocus()
        return False


def paint_focus_ring(p: QPainter, r: QRectF, radius: float = S.R_CTL) -> None:
    """Мягкое синее свечение вместо пунктирной рамки (внутри границ виджета)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(Qt.NoBrush)
    for i, alpha in enumerate((200, 110, 50)):
        c = theme.col("glow"); c.setAlpha(alpha)
        p.setPen(QPen(c, 1))
        p.drawRoundedRect(r.adjusted(.5 + i, .5 + i, -.5 - i, -.5 - i), max(1.0, radius - i), max(1.0, radius - i))
    p.restore()


def repolish(w: QWidget) -> None:
    w.style().unpolish(w); w.style().polish(w); w.update()


def make_label(text: str = "", role: Optional[str] = None, parent: Optional[QWidget] = None) -> QLabel:
    lb = QLabel(text, parent)
    if role:
        lb.setProperty("role", role)
    return lb


class _FocusRing:
    """Миксин: мягкое свечение фокуса рисуется поверх виджета (без QGraphicsEffect — он даёт
    артефакты в скруглённых углах). Ставить ПЕРЕД Qt-классом."""
    ring_radius = S.R_CTL - 1

    def paintEvent(self, e: object) -> None:
        super().paintEvent(e)  # type: ignore[misc]
        if self.hasFocus() and self.isEnabled():  # type: ignore[attr-defined]
            paint_focus_ring(QPainter(self), QRectF(self.rect()), self.ring_radius)  # type: ignore[attr-defined]


class AeroLineEdit(_FocusRing, QLineEdit):
    pass


class AeroTimeEdit(_FocusRing, QTimeEdit):
    pass


class AeroDateEdit(_FocusRing, QDateEdit):
    pass


class AeroTextEdit(QTextEdit):
    """Рамка фокуса — через QSS (у области прокрутки нельзя рисовать поверх viewport)."""


# ---- Кнопки ----------------------------------------------------------------------------------
class AeroButton(QPushButton):
    """Глянцевая кнопка. role: ctl | accent | danger | flat."""

    def __init__(self, text: str = "", role: str = "ctl", parent: Optional[QWidget] = None,
                 compact: bool = False) -> None:
        super().__init__(text, parent)
        self.setProperty("role", role)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._compact = compact
        self._glyph: Optional[str] = None
        self._hover = HoverAnim(self)

    def set_glyph(self, name: str) -> None:
        """Кнопка-иконка (например «+»): глиф ровно по центру вместо текста."""
        self._glyph = name; self.update()

    def sizeHint(self) -> QSize:
        w = self.fontMetrics().horizontalAdvance(self.text()) + (22 if self._compact else 36)
        return QSize(max(w, 52 if self._compact else 76), 24 if self._compact else 28)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        r = QRectF(self.rect())
        role = self.property("role") or "ctl"
        on = self.isEnabled()
        k = self._hover.value if on else 0.0
        if role == "flat":
            if k > 0 or self.isDown():
                p.setOpacity(1.0 if self.isDown() else k)
                theme.paint_control(p, r, "sel")
                p.setOpacity(1.0)
        else:
            p.setOpacity(1.0 if on else 0.55)
            state = {"accent": "acc", "danger": "dng"}.get(role, "ctl") if on else "ctl"
            theme.paint_control(p, r, state, glow_k=k)
            if self.isDown():
                p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 45))
                p.setRenderHint(QPainter.Antialiasing)
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), S.R_CTL, S.R_CTL)
            p.setOpacity(1.0)
        if self.hasFocus() and on:
            paint_focus_ring(p, r)
        colored = role in ("accent", "danger") and on
        if self._glyph:
            g = 14.0
            icons.draw_icon(p, self._glyph, QRectF((r.width() - g) / 2, (r.height() - g) / 2, g, g),
                            theme.col("hl_text") if colored else theme.col("text" if on else "faint"), 2.0)
            return
        p.setPen(theme.col("hl_text") if colored else theme.col("text" if on else "faint"))
        f = QFont(self.font()); f.setBold(colored); p.setFont(f)
        p.drawText(r.translated(0, 1 if self.isDown() else 0), Qt.AlignCenter | Qt.TextShowMnemonic, self.text())


class IconButton(QAbstractButton):
    """Иконка-кнопка: приглушённая, при наведении ярче."""

    def __init__(self, icon: str, danger: bool = False, size: int = 28, glyph: int = 16,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon, self._danger, self._size, self._glyph = icon, danger, size, glyph
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = HoverAnim(self)

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def set_icon(self, icon: str) -> None:
        self._icon = icon; self.update()

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        r = QRectF(self.rect())
        k = self._hover.value if self.isEnabled() else 0.0
        if k > 0 or self.isDown():
            p.setOpacity(1.0 if self.isDown() else k)
            theme.paint_control(p, r, "sel")
            p.setOpacity(1.0)
        if self.hasFocus():
            paint_focus_ring(p, r)
        t = theme.tokens()
        color = theme.qcolor(theme.mix(t["dim"], t["danger" if self._danger else "text"], k))
        if not self.isEnabled():
            color = theme.col("faint")
        g = self._glyph
        icons.draw_icon(p, self._icon, QRectF((r.width() - g) / 2, (r.height() - g) / 2, g, g), color)


class DoneButton(QAbstractButton):
    """Круглая кнопка «Выполнено»: кольцо по приоритету, галочка по клику."""
    completed = pyqtSignal()

    def __init__(self, priority: str = core.NORMAL, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._priority = priority
        self.setFixedSize(28, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self._hover = HoverAnim(self)
        self._check = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(S.ANIM_FAST)
        self._anim.valueChanged.connect(self._set_check)

    def _set_check(self, v: object) -> None:
        self._check = float(v); self.update()  # type: ignore[arg-type]

    def set_priority(self, priority: str) -> None:
        self._priority = priority; self.update()

    def mouseReleaseEvent(self, e: object) -> None:
        inside = self.isEnabled() and self.rect().contains(e.pos())  # type: ignore[attr-defined]
        super().mouseReleaseEvent(e)  # type: ignore[arg-type]
        if inside:
            self._anim.stop(); self._anim.setStartValue(self._check); self._anim.setEndValue(1.0); self._anim.start()
            QTimer.singleShot(190, self.completed.emit)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.tokens()
        ring = theme.qcolor(t["danger" if self._priority == core.HIGH else "accent"])
        if not self.isEnabled():
            ring = theme.col("faint")
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        k = max(self._hover.value, 1.0 if self.isDown() else 0.0) if self.isEnabled() else 0.0
        m = min(1.0, 0.14 * k + self._check)          # сила заливки: лёгкий отлив при наведении, полная при клике
        if m > 0.01:                                    # Aero-стекло: градиент с резким переломом посередине
            def tone(f: int, al: float) -> QColor:
                c = QColor(ring).lighter(f); c.setAlpha(int(255 * min(1.0, al * m))); return c
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0.0, tone(135, 0.95)); g.setColorAt(0.5, tone(105, 0.95))
            g.setColorAt(0.51, tone(88, 1.0)); g.setColorAt(1.0, tone(118, 1.0))
            p.setBrush(g)
        else:
            p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring.darker(115) if self._check > .05 else ring, 2))
        p.drawEllipse(r)
        if m > 0.01:                                    # блик на верхней половине + светлая внутренняя кромка
            gl = QRectF(r.left() + r.width() * 0.14, r.top() + r.height() * 0.07, r.width() * 0.72, r.height() * 0.44)
            gg = QLinearGradient(gl.topLeft(), gl.bottomLeft())
            top, bot = QColor(255, 255, 255, int(190 * m)), QColor(255, 255, 255, int(40 * m))
            gg.setColorAt(0, top); gg.setColorAt(1, bot)
            p.setPen(Qt.NoPen); p.setBrush(gg); p.drawEllipse(gl)
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor(255, 255, 255, int(120 * m)), 1))
            p.drawEllipse(r.adjusted(1.5, 1.5, -1.5, -1.5))
        if self.hasFocus():
            paint_focus_ring(p, QRectF(self.rect()), 14)
        a = max(self._check, 0.55 * k if self.isEnabled() else 0.0)
        if a > 0:
            p.setOpacity(a)
            icons.draw_icon(p, "check", r.adjusted(2, 2, -2, -2),
                            theme.col("hl_text") if self._check > .5 else ring, 2.0)


class SearchEdit(QLineEdit):
    """Поле поиска со встроенной лупой и кнопкой очистки."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setProperty("role", "search")
        self._clear = IconButton("close", size=20, glyph=10, parent=self)
        self._clear.hide()
        self._clear.clicked.connect(self.clear)
        self.textChanged.connect(lambda s: self._clear.setVisible(bool(s)))

    def resizeEvent(self, e: object) -> None:
        super().resizeEvent(e)  # type: ignore[arg-type]
        self._clear.move(self.width() - 24, (self.height() - 20) // 2)

    def paintEvent(self, e: object) -> None:
        super().paintEvent(e)  # type: ignore[arg-type]
        p = QPainter(self)
        icons.draw_icon(p, "search", QRectF(9, (self.height() - 14) / 2, 14, 14), theme.col("dim"))
        if self.hasFocus():
            paint_focus_ring(p, QRectF(self.rect()), 12)

    def keyPressEvent(self, e: object) -> None:
        if e.key() == Qt.Key_Escape and self.text():  # type: ignore[attr-defined]
            self.clear(); return
        super().keyPressEvent(e)  # type: ignore[arg-type]


# ---- Меню ------------------------------------------------------------------------------------------
class AeroMenu(QMenu):
    """QMenu с собственной тенью в прозрачном поле (QSS margin = S.SHADOW). Используется везде."""

    def paintEvent(self, e: object) -> None:
        p = QPainter(self)
        m = S.SHADOW
        theme.paint_shadow(p, QRectF(self.rect()).adjusted(m, m, -m, -m), 8)
        p.end()
        super().paintEvent(e)  # type: ignore[arg-type]


# ---- Комбобокс -----------------------------------------------------------------------------------
class _RowDelegate(QStyledItemDelegate):
    def sizeHint(self, option: object, index: object) -> QSize:
        sh = super().sizeHint(option, index)  # type: ignore[arg-type]
        return QSize(sh.width(), _ComboPopup.ROW_H)


class _ComboPopup(QWidget):
    """Собственный popup: прозрачное frameless-окно, скруглённая стеклянная подложка и тень.
    Поле тени со стороны комбобокса минимально — иначе окно перекрывает сам комбобокс и клики
    по его краю уходят в прозрачную рамку popup, а не закрывают список."""
    ROW_H = 26
    NEAR = 4          # поле со стороны комбобокса

    def __init__(self, combo: "AeroComboBox", up: bool) -> None:
        super().__init__(combo, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.combo = combo
        m = S.SHADOW
        self.top_m, self.bottom_m = (m, self.NEAR) if up else (self.NEAR, m)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(m + 4, self.top_m + 4, m + 4, self.bottom_m + 4)
        self.view = QListView(self)
        self.view.setObjectName("comboList")
        self.view.setModel(combo.model())
        self.view.setFrameShape(QListView.NoFrame)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.setMouseTracking(True)
        self.view.setItemDelegate(_RowDelegate(self.view))
        self.view.setCurrentIndex(combo.model().index(combo.currentIndex(), combo.modelColumn()))
        self.view.clicked.connect(self._pick)
        self.view.activated.connect(self._pick)
        lay.addWidget(self.view)
        rows = min(combo.count(), combo.maxVisibleItems())
        self.view.setFixedHeight(rows * self.ROW_H + 8)
        self.setFixedSize(combo.width() + 2 * m, self.view.height() + self.top_m + self.bottom_m + 8)

    def _pick(self, index: object) -> None:
        self.combo.setCurrentIndex(index.row())  # type: ignore[attr-defined]
        self.combo.activated.emit(index.row())  # type: ignore[attr-defined]
        self.close()

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        m = S.SHADOW
        body = QRectF(self.rect()).adjusted(m, self.top_m, -m, -self.bottom_m)
        theme.paint_shadow(p, body, 8)
        p.setPen(QPen(theme.col("menu_edge"), 1)); p.setBrush(theme.col("menu"))
        p.drawRoundedRect(body.adjusted(.5, .5, -.5, -.5), 8, 8)

    def hideEvent(self, e: object) -> None:
        super().hideEvent(e)  # type: ignore[arg-type]
        self.combo._closed_at = time.monotonic()
        if self.combo._popup is self:
            self.combo._popup = None
        self.deleteLater()
        self.combo.update()


class AeroComboBox(_FocusRing, QComboBox):
    def __init__(self, parent: Optional[QWidget] = None, editable: bool = False) -> None:
        super().__init__(parent)
        self.setEditable(editable)
        self.setMaxVisibleItems(8)
        self._popup: Optional[_ComboPopup] = None
        self._closed_at = 0.0

    def _cursor_over(self) -> bool:
        # underMouse() тут не годится: пока открыт popup, комбобокс не получает Enter/Leave
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def showPopup(self) -> None:
        if self.count() == 0:
            return
        if self._popup is not None:                  # уже открыт: повторный клик закрывает
            self.hidePopup(); return
        # Клик по комбобоксу закрывает Qt.Popup, а Qt «проигрывает» это нажатие повторно и
        # открыл бы список заново — гасим такое повторное открытие.
        if time.monotonic() - self._closed_at < 0.3 and self._cursor_over():
            return
        below = self.mapToGlobal(QPoint(0, self.height()))
        screen = QGuiApplication.screenAt(below) or QGuiApplication.primaryScreen()
        rows = min(self.count(), self.maxVisibleItems())
        height = rows * _ComboPopup.ROW_H + 16 + S.SHADOW + _ComboPopup.NEAR
        up = below.y() + height > screen.availableGeometry().bottom()
        popup = self._popup = _ComboPopup(self, up)
        x = below.x() - S.SHADOW
        popup.move(x, self.mapToGlobal(QPoint(0, 0)).y() - popup.height() if up else below.y())
        popup.show()
        popup.view.setFocus()

    def hidePopup(self) -> None:
        if self._popup is not None:
            self._popup.close()                      # hideEvent сам сбросит ссылку и удалит окно


# ---- Календарь -----------------------------------------------------------------------------------
class AeroCalendar(QCalendarWidget):
    """Календарь с собственной отрисовкой ячеек и подложки (без нативного вида)."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        self.setNavigationBarVisible(True)
        self._hover: Optional[QDate] = None
        self._cells: dict[QDate, QRect] = {}
        self._view = self.findChild(QTableView)
        if self._view is not None:
            self._view.setFrameShape(QTableView.NoFrame)
            self._view.viewport().setAutoFillBackground(False)
            self._view.setMouseTracking(True)
            self._view.viewport().setMouseTracking(True)
            self._view.viewport().installEventFilter(self)
        self.currentPageChanged.connect(lambda *_a: self._cells.clear())
        self._apply_formats()

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if self._view is not None and obj is self._view.viewport():
            if ev.type() == QEvent.MouseMove:
                pos = ev.pos()  # type: ignore[attr-defined]
                hover = next((d for d, r in self._cells.items() if r.contains(pos)), None)
                if hover != self._hover:
                    self._hover = hover; obj.update()  # type: ignore[attr-defined]
            elif ev.type() == QEvent.Leave and self._hover is not None:
                self._hover = None; obj.update()  # type: ignore[attr-defined]
        return super().eventFilter(obj, ev)

    def _apply_formats(self) -> None:
        f = QTextCharFormat()
        f.setForeground(theme.col("dim")); f.setFontWeight(QFont.DemiBold)
        for d in range(1, 8):
            self.setWeekdayTextFormat(Qt.DayOfWeek(d), f)
        self.setHeaderTextFormat(f)

    def changeEvent(self, e: QEvent) -> None:
        super().changeEvent(e)
        if e.type() == QEvent.StyleChange:
            self._apply_formats()

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(theme.col("menu_edge"), 1)); p.setBrush(theme.col("menu"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)

    def paintCell(self, p: QPainter, rect: object, date: QDate) -> None:
        r = QRectF(rect).adjusted(2, 2, -2, -2)  # type: ignore[arg-type]
        selected = date == self.selectedDate()
        today = date == QDate.currentDate()
        outside = date.month() != self.monthShown()
        self._cells[date] = QRect(rect)  # type: ignore[arg-type]
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if selected:
            theme.paint_control(p, r, "sel", radius=4)
        elif date == self._hover:
            p.setOpacity(.75); theme.paint_control(p, r, "sel", radius=4); p.setOpacity(1.0)
        elif today:
            p.setBrush(Qt.NoBrush); p.setPen(QPen(theme.col("accent"), 1))
            p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 4, 4)
        t = theme.tokens()
        if selected:
            color = theme.col("sel_text")
        elif outside:
            color = theme.col("faint")
        elif date.dayOfWeek() >= 6:
            color = theme.qcolor(theme.mix(t["text"], t["danger"], .65))
        else:
            color = theme.col("text")
        f = QFont(self.font()); f.setBold(today or selected)
        p.setFont(f); p.setPen(color)
        p.drawText(r, Qt.AlignCenter, str(date.day()))
        p.restore()


# ---- Панели и диалоги -------------------------------------------------------------------------------
class GlassPanel(QWidget):
    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        theme.paint_glass_panel(p, QRectF(self.rect()))


class AeroDialog(QDialog):
    """База всех диалогов: фон-«стекло», DWM-цвет заголовка, Esc — отмена."""

    def __init__(self, parent: Optional[QWidget], title: str) -> None:
        super().__init__(parent, Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setWindowTitle(title)
        self.setWindowIcon(icons.app_icon())
        self.setModal(True)

    def paintEvent(self, _e: object) -> None:
        theme.paint_window_background(QPainter(self), QRectF(self.rect()))

    def showEvent(self, e: object) -> None:
        theme.apply_titlebar(self)
        super().showEvent(e)  # type: ignore[arg-type]


class _MessageDialog(AeroDialog):
    def __init__(self, parent: Optional[QWidget], title: str, text: str, ok_text: str,
                 danger: bool, cancel: bool) -> None:
        super().__init__(parent, title)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16); lay.setSpacing(S.SP * 2)
        label = QLabel(text); label.setWordWrap(True); label.setMinimumWidth(340)
        lay.addWidget(label)
        row = QHBoxLayout(); row.addStretch(1); row.setSpacing(S.SP)
        if cancel:
            c = AeroButton(i18n.tr("cancel")); c.clicked.connect(self.reject); row.addWidget(c)
        ok = AeroButton(ok_text, "danger" if danger else "accent")
        ok.setFocusPolicy(Qt.StrongFocus); ok.setDefault(True); ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        ok.setFocus()


def confirm(parent: Optional[QWidget], text: str, ok_text: Optional[str] = None, danger: bool = False) -> bool:
    dlg = _MessageDialog(parent, i18n.tr("confirm_title"), text, ok_text or i18n.tr("ok"), danger, True)
    return dlg.exec_() == QDialog.Accepted


def info(parent: Optional[QWidget], text: str, title: Optional[str] = None) -> None:
    _MessageDialog(parent, title or i18n.tr("info_title"), text, i18n.tr("ok"), False, False).exec_()


def ask_text(parent: Optional[QWidget], title: str, label: str, value: str = "") -> Optional[str]:
    dlg = AeroDialog(parent, title)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(24, 20, 24, 16); lay.setSpacing(S.SP)
    lay.addWidget(make_label(label, "dim"))
    edit = AeroLineEdit(value); edit.setMinimumWidth(320)
    lay.addWidget(edit)
    row = QHBoxLayout(); row.addStretch(1); row.setSpacing(S.SP)
    c = AeroButton(i18n.tr("cancel")); c.clicked.connect(dlg.reject)
    ok = AeroButton(i18n.tr("save"), "accent"); ok.setFocusPolicy(Qt.StrongFocus); ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    row.addWidget(c); row.addWidget(ok)
    lay.addSpacing(S.SP); lay.addLayout(row)
    edit.textChanged.connect(lambda s: ok.setEnabled(bool(s.strip())))
    ok.setEnabled(bool(value.strip())); edit.selectAll(); edit.setFocus()
    return edit.text().strip() if dlg.exec_() == QDialog.Accepted else None
