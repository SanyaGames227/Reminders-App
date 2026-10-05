"""Список напоминаний и истории: самописные строки, Drag & Drop с линией вставки."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PyQt5.QtCore import QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap, QRegion
from PyQt5.QtWidgets import QApplication, QCheckBox, QLabel, QScrollArea, QWidget

import core
import i18n
import icons
import theme
from core import HistoryItem, Reminder
from theme import S
from ui.widgets import DoneButton, HoverAnim, IconButton

PAD, GAP, ROW_BASE, ROW_SNOOZE = 12, 6, 64, 80
ACTIVE, HISTORY = "active", "history"


@dataclass
class RowModel:
    id: str
    kind: str
    title: str
    priority: str
    line1: str
    overdue: bool = False
    repeat: Optional[str] = None      # подпись плашки: «Ежедневно» и т.д.
    early: Optional[str] = None       # плашка «заранее: 15 мин»
    line2: Optional[str] = None
    line2_accent: bool = False
    category: Optional[str] = None
    done_enabled: bool = True


def row_from_reminder(r: Reminder, now: datetime) -> RowModel:
    snooze = core.shown_snooze(r, now)
    can = core.can_complete(r, now)
    return RowModel(
        id=r.id, kind=ACTIVE, title=r.title, priority=r.priority, line1=i18n.fmt_due(r.due, now),
        overdue=core.is_overdue(r, now), repeat=i18n.repeat_label(r.repeat),
        early=i18n.tr("early_chip", t=i18n.lead_label(r.early_min)) if r.early_min else None,
        line2=i18n.tr("snoozed_until", when=i18n.fmt_due(snooze, now)) if snooze else None, line2_accent=True,
        category=r.category, done_enabled=can)


def row_from_history(h: HistoryItem, now: datetime) -> RowModel:
    return RowModel(
        id=h.id, kind=HISTORY, title=h.title, priority=h.priority, line1=i18n.fmt_due(h.due, now),
        repeat=i18n.repeat_label(h.repeat), line2=i18n.tr("h_completed", when=i18n.fmt_due(h.completed_at, now)),
        category=h.category)


def _text(p: QPainter, rect: QRectF, text: str, color: object) -> None:
    """Текст с лёгкой тенью (в тёмной теме) — цветной текст не сливается с фоном."""
    flags = Qt.AlignVCenter | Qt.AlignLeft
    sh = theme.col("text_shadow")
    if sh.alpha():
        p.setPen(sh); p.drawText(rect.translated(0, 1), flags, text)
    p.setPen(color); p.drawText(rect, flags, text)


class Row(QWidget):
    act = pyqtSignal(str, str)   # (действие, id)

    def __init__(self, owner: "ReminderList", model: RowModel, checked: bool) -> None:
        super().__init__(owner._content)
        self.owner, self.model = owner, model
        self.selected = False
        self.dragging = False
        self._hover = HoverAnim(self)
        self.setFixedHeight(ROW_SNOOZE if model.line2 else ROW_BASE)
        if model.kind == ACTIVE:
            self.lead: QWidget = DoneButton(model.priority, self)
            self.lead.setEnabled(model.done_enabled)
            self.lead.completed.connect(lambda: self.act.emit("done", model.id))  # type: ignore[attr-defined]
            self.btn_a = IconButton("edit", parent=self)
            self.btn_a.clicked.connect(lambda: self.act.emit("edit", model.id))
            self.btn_b = IconButton("trash", danger=True, parent=self)
        else:
            cb = QCheckBox(self); cb.setChecked(checked); cb.setFixedSize(20, 20)
            cb.toggled.connect(lambda v: self.act.emit("check" if v else "uncheck", model.id))
            self.lead = cb
            self.btn_a = IconButton("restore", parent=self)
            self.btn_a.clicked.connect(lambda: self.act.emit("restore", model.id))
            self.btn_b = IconButton("trash", danger=True, parent=self)
        self.btn_b.clicked.connect(lambda: self.act.emit("delete", model.id))
        self.setContextMenuPolicy(Qt.NoContextMenu)

    def resizeEvent(self, _e: object) -> None:
        w, h = self.width(), self.height()
        self.lead.move(PAD + (28 - self.lead.width()) // 2, (h - self.lead.height()) // 2)
        self.btn_b.move(w - PAD - 28, h - 8 - 28)
        self.btn_a.move(w - PAD - 28 * 2 - 4, h - 8 - 28)

    def text_x(self) -> int:
        return PAD + 28 + PAD

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.dragging:
            p.setOpacity(.35)
        r = QRectF(self.rect())
        theme.paint_glass_panel(p, r, 8, sheen=False)
        if self.selected:
            theme.paint_control(p, r, "sel", 8)
        elif self._hover.value > 0:
            p.setOpacity(p.opacity() * self._hover.value * .6)
            theme.paint_control(p, r, "sel", 8)
            p.setOpacity(.35 if self.dragging else 1.0)
        m, t = self.model, theme.tokens()
        x, f = self.text_x(), self.font()
        # категория — справа сверху
        right = self.width() - PAD
        cat_w = 0
        if m.category:
            fm = QFontMetrics(f)
            txt = fm.elidedText(m.category, Qt.ElideRight, 140)
            cat_w = fm.horizontalAdvance(txt)
            p.setFont(f); p.setPen(theme.col("dim"))
            p.drawText(QRectF(right - cat_w, 8, cat_w, 20), Qt.AlignVCenter | Qt.AlignRight, txt)
        tf = self.font(); tf.setWeight(63); tf.setPointSizeF(tf.pointSizeF() + 1)
        p.setFont(tf); p.setPen(theme.col("text"))
        tw = max(40, right - x - cat_w - PAD)
        p.drawText(QRectF(x, 8, tw, 22), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(tf).elidedText(m.title, Qt.ElideRight, tw))
        p.setFont(f)
        fm = QFontMetrics(f)
        warn = theme.col("danger_text") if m.overdue else theme.col("dim")
        d_w = min(fm.horizontalAdvance(m.line1), right - x - 120)
        _text(p, QRectF(x, 30, d_w + 4, 18), fm.elidedText(m.line1, Qt.ElideRight, d_w + 2), warn)
        cx = x + d_w + 12
        for chip in (m.repeat, m.early):           # плашки: «Ежедневно», «заранее: 15 мин»
            if not chip:
                continue
            cf = QFont(f); cf.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            cw = QFontMetrics(cf).horizontalAdvance(chip) + 18
            if cx + cw < right - 120:
                base = theme.col("danger" if m.overdue else "accent")
                fill, edge = QColor(base), QColor(base)
                fill.setAlpha(34); edge.setAlpha(125)
                p.setPen(QPen(edge, 1)); p.setBrush(fill)
                p.drawRoundedRect(QRectF(cx + .5, 31.5, cw - 1, 16), 8, 8)
                p.setFont(cf); p.setPen(theme.col("danger_text" if m.overdue else "accent_text"))
                p.drawText(QRectF(cx, 31, cw, 17), Qt.AlignCenter, chip)
                p.setFont(f)
                cx += cw + 6
        if m.line2:
            w2 = right - x - 120
            if m.line2_accent:                    # «Отложено до»: тёплый янтарный цвет + значок часов
                color = theme.col("snooze_text")
                icons.draw_icon(p, "clock", QRectF(x, 52, 14, 14), color, 1.4)
                tx = x + 20
            else:
                color, tx = theme.col("dim"), x
            _text(p, QRectF(tx, 50, w2 - (tx - x), 18), fm.elidedText(m.line2, Qt.ElideRight, int(w2 - (tx - x))), color)

    def mousePressEvent(self, e: object) -> None:
        if e.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.owner.row_pressed(self, e)
        elif e.button() == Qt.RightButton:  # type: ignore[attr-defined]
            self.owner.select(self.model.id)
            self.owner.context_requested.emit(self.model.id, e.globalPos())  # type: ignore[attr-defined]

    def mouseMoveEvent(self, e: object) -> None:
        self.owner.row_moved(self, e)

    def mouseReleaseEvent(self, e: object) -> None:
        self.owner.row_released(self, e)

    def mouseDoubleClickEvent(self, e: object) -> None:
        if self.model.kind == ACTIVE:
            self.act.emit("edit", self.model.id)


class _DropLine(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFixedHeight(4)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = theme.col("glow"); c.setAlpha(90)
        p.setPen(Qt.NoPen); p.setBrush(c); p.drawRoundedRect(QRectF(self.rect()), 2, 2)
        p.setBrush(theme.col("accent")); p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, 0, -1), 1, 1)


class _Empty(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.title = self.hint = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2 - 24
        p.setOpacity(.45)
        icons.draw_icon(p, "bell", QRectF(cx - 28, cy - 28, 56, 56), theme.col("dim"), 1.2)
        p.setOpacity(1.0)
        f = self.font(); f.setPointSizeF(f.pointSizeF() + 3); p.setFont(f); p.setPen(theme.col("dim"))
        p.drawText(QRectF(0, cy + 36, self.width(), 26), Qt.AlignCenter, self.title)
        if self.hint:
            f.setPointSizeF(f.pointSizeF() - 3); p.setFont(f); p.setPen(theme.col("faint"))
            p.drawText(QRectF(0, cy + 62, self.width(), 20), Qt.AlignCenter, self.hint)


class ReminderList(QScrollArea):
    done = pyqtSignal(str)
    edit = pyqtSignal(str)
    delete = pyqtSignal(str)
    restore = pyqtSignal(str)
    reordered = pyqtSignal(list)
    context_requested = pyqtSignal(str, QPoint)
    checks_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._content = QWidget()
        self.setWidget(self._content)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setAutoFillBackground(False)
        self._content.setAutoFillBackground(False)
        self._rows: list[Row] = []
        self._empty = _Empty(self.viewport())
        self._selected: Optional[str] = None
        self._checked: set[str] = set()
        self.drag_enabled = False
        self._press: Optional[Row] = None
        self._press_was_selected = False
        self._press_pos = QPoint()
        self._dragging = False
        self._ghost: Optional[QLabel] = None
        self._line = _DropLine(self._content); self._line.hide()
        self._drop_index = 0
        self._scroll_timer = QTimer(self); self._scroll_timer.setInterval(30)
        self._scroll_timer.timeout.connect(self._autoscroll)
        self._scroll_dir = 0

    # -- данные
    def set_items(self, models: list[RowModel], empty_title: str = "", empty_hint: str = "") -> None:
        self._cancel_drag()
        keep = self.verticalScrollBar().value()
        for r in self._rows:
            r.hide(); r.deleteLater()
        self._rows = []
        ids = {m.id for m in models}
        self._checked &= ids
        if self._selected not in ids:
            self._selected = None
        for m in models:
            row = Row(self, m, m.id in self._checked)
            row.act.connect(self._on_act)
            row.selected = m.id == self._selected
            row.show(); self._rows.append(row)
        self._empty.title, self._empty.hint = empty_title, empty_hint
        self._empty.update()                 # иначе при смене вкладки остаётся старый текст («Нажмите +»)
        self._layout_rows()
        self.verticalScrollBar().setValue(keep)

    def _on_act(self, action: str, rid: str) -> None:
        if action in ("check", "uncheck"):
            (self._checked.add if action == "check" else self._checked.discard)(rid)
            self.checks_changed.emit()
        else:
            getattr(self, action).emit(rid)

    def checked_ids(self) -> list[str]:
        return [r.model.id for r in self._rows if r.model.id in self._checked]

    def clear_checks(self) -> None:
        self._checked.clear()

    def ids(self) -> list[str]:
        return [r.model.id for r in self._rows]

    def selected_id(self) -> Optional[str]:
        return self._selected

    def select(self, rid: Optional[str], ensure_visible: bool = False) -> None:
        self._selected = rid
        for r in self._rows:
            r.selected = r.model.id == rid
            r.update()
            if ensure_visible and r.model.id == rid:
                self.ensureWidgetVisible(r, 0, 12)

    # -- раскладка
    def resizeEvent(self, e: object) -> None:
        super().resizeEvent(e)  # type: ignore[arg-type]
        self._layout_rows()

    def _layout_rows(self) -> None:
        w = self.viewport().width()
        y = 2
        for r in self._rows:
            r.setGeometry(2, y, w - 4, r.height())
            y += r.height() + GAP
        self._content.resize(w, max(y, 1))
        self._empty.setGeometry(self.viewport().rect())
        self._empty.setVisible(not self._rows)
        self._empty.raise_()

    # -- сброс выделения
    def clear_selection(self) -> None:
        self.select(None)

    def mousePressEvent(self, e: object) -> None:
        if e.button() == Qt.LeftButton:  # type: ignore[attr-defined]
            self.clear_selection()     # клик по пустому месту (по строкам событие сюда не доходит)
        super().mousePressEvent(e)  # type: ignore[arg-type]

    # -- клавиатура
    def keyPressEvent(self, e: object) -> None:
        k = e.key()  # type: ignore[attr-defined]
        ids = self.ids()
        if k == Qt.Key_Escape:
            self.clear_selection()
        elif k in (Qt.Key_Up, Qt.Key_Down) and ids:
            step = 1 if k == Qt.Key_Down else -1
            i = ids.index(self._selected) + step if self._selected in ids else (0 if step > 0 else len(ids) - 1)
            i = max(0, min(len(ids) - 1, i))
            self.select(ids[i], True)
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self._selected:
            row = next((r for r in self._rows if r.model.id == self._selected), None)
            if row and row.model.kind == ACTIVE:
                self.edit.emit(self._selected)
        elif k == Qt.Key_Delete and self._selected:
            self.delete.emit(self._selected)
        else:
            super().keyPressEvent(e)  # type: ignore[arg-type]

    # -- Drag & Drop
    def row_pressed(self, row: Row, e: object) -> None:
        self._press, self._press_pos = row, e.globalPos()  # type: ignore[attr-defined]
        self._press_was_selected = self._selected == row.model.id
        self.select(row.model.id)
        self.setFocus()

    def row_moved(self, row: Row, e: object) -> None:
        if not self.drag_enabled or self._press is not row:
            return
        gp = e.globalPos()  # type: ignore[attr-defined]
        if not self._dragging and (gp - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
            self._begin_drag(row)
        if self._dragging:
            self._update_drag(gp)

    def _begin_drag(self, row: Row) -> None:
        self._dragging = True
        dpr = row.devicePixelRatioF()
        pm = QPixmap(int(row.width() * dpr), int(row.height() * dpr))
        pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
        row.dragging = False                     # без DrawWindowBackground: скругления остаются прозрачными
        row.render(pm, QPoint(), QRegion(), QWidget.DrawChildren)
        self._ghost = QLabel(self.viewport())    # на viewport, а не на content: виден и ниже последней строки
        self._ghost.setPixmap(pm); self._ghost.setFixedSize(row.size())
        self._ghost.setAttribute(Qt.WA_TranslucentBackground)
        self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents); self._ghost.show()
        row.dragging = True; row.update()
        self._line.setParent(self._content); self._line.show(); self._line.raise_()

    def _update_drag(self, gp: QPoint) -> None:
        assert self._press is not None and self._ghost is not None
        pos = self._content.mapFromGlobal(gp)
        vp = self.viewport().mapFromGlobal(gp)
        gy = max(0, min(self.viewport().height() - self._ghost.height(), vp.y() - self._ghost.height() // 2))
        self._ghost.move(2, gy); self._ghost.raise_()
        others = [r for r in self._rows if r is not self._press]
        self._drop_index = sum(1 for r in others if r.geometry().center().y() < pos.y())
        if not others:
            y = 0
        elif self._drop_index == 0:
            y = others[0].geometry().top() - GAP // 2 - 2
        else:
            y = others[self._drop_index - 1].geometry().bottom() + GAP // 2 - 1
        self._line.setGeometry(6, y, self._content.width() - 12, 4); self._line.raise_()
        self._scroll_dir = -1 if vp.y() < 28 else (1 if vp.y() > self.viewport().height() - 28 else 0)
        if self._scroll_dir and not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _autoscroll(self) -> None:
        if not self._dragging or not self._scroll_dir:
            self._scroll_timer.stop(); return
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + 14 * self._scroll_dir)
        self._update_drag(self.cursor().pos())

    def row_released(self, row: Row, e: object) -> None:
        if self._dragging and self._press is row:
            others = [r.model.id for r in self._rows if r is not row]
            new = others[:self._drop_index] + [row.model.id] + others[self._drop_index:]
            old = self.ids()
            self._cancel_drag()
            if new != old:
                self.reordered.emit(new)
        elif self._press is row and self._press_was_selected and row.rect().contains(e.pos()):  # type: ignore[attr-defined]
            self.select(None)          # повторный клик по выделенной строке снимает выделение
        self._press = None

    def _cancel_drag(self) -> None:
        self._scroll_timer.stop()
        if self._ghost is not None:
            self._ghost.hide(); self._ghost.deleteLater(); self._ghost = None
        self._line.hide()
        for r in self._rows:
            if r.dragging:
                r.dragging = False; r.update()
        self._dragging = False
        self._press = None
