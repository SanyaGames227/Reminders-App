"""Главное окно: сайдбар, шапка, списки, история, настройки и все действия пользователя."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from PyQt5.QtCore import QByteArray, QObject, QPoint, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QBrush, QCursor, QFontMetrics, QImage, QKeySequence, QPainter, QPainterPath, QPixmap, QRegion
from PyQt5.QtWidgets import (QAbstractButton, QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                             QScrollArea, QShortcut, QStackedWidget, QVBoxLayout, QWidget)

import core
import i18n
import icons
import storage
import theme
from core import (F_ALL, F_CATEGORY, F_OVERDUE, F_TODAY, Filter, Reminder)
from scheduler import Scheduler
from storage import Storage
from theme import S
from updater import FOUND, UpdateResult, Updater
from ui.about_dialog import AboutDialog
from ui.reminder_dialog import ReminderDialog
from ui.backdrop import BLUR_PAD, BLUR_RADIUS, SOLID, blur_image, detect_mode
from ui.reminder_list import ReminderList, _DropLine, row_from_history, row_from_reminder
from ui.settings_page import SettingsPage
from ui.toast import ToastManager
from ui.tray import Tray
from ui.update_dialog import UpdateDialog
from ui.widgets import (AeroButton, AeroMenu, GlassPanel, HoverAnim, SearchEdit, SortButton, ask_text, confirm, info,
                        make_label, paint_focus_ring)

HISTORY, SETTINGS, ABOUT = "history", "settings", "about"
NavKey = tuple  # (вид,) или ("category", имя)


def _fmt_size(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.2f} MB"


def force_foreground(w: QWidget) -> None:
    """Windows запрещает «воровать» фокус; обходим через AttachThreadInput."""
    try:
        import ctypes
        u, k = ctypes.windll.user32, ctypes.windll.kernel32  # type: ignore[attr-defined]
        hwnd = int(w.winId())
        fg = u.GetForegroundWindow()
        fg_thread = u.GetWindowThreadProcessId(fg, None)
        me = k.GetCurrentThreadId()
        if fg_thread and fg_thread != me:
            u.AttachThreadInput(fg_thread, me, True); u.SetForegroundWindow(hwnd); u.AttachThreadInput(fg_thread, me, False)
        else:
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


class NavItem(QAbstractButton):
    context_requested = pyqtSignal(QPoint)

    def __init__(self, key: NavKey, icon: str, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key, self._icon, self._text, self._count = key, icon, text, None
        self.reorder: Optional["CategoryReorder"] = None   # у категорий — контроллер перетаскивания
        self.dragging = False                               # тянется: тускнеет на месте (как строка списка)
        self.lifted = False                                 # рисуется «выделенной» — для призрака при перетаскивании
        self.setCheckable(True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        self._hover = HoverAnim(self)

    def focusInEvent(self, e: Any) -> None:
        super().focusInEvent(e)
        # Фокус только с клавиатуры (Tab); после закрытия окон Qt сам отдаёт его первой вкладке — снимаем
        if e.reason() not in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason):
            QTimer.singleShot(0, lambda: self.clearFocus() if self.hasFocus() else None)

    def set_text(self, text: str) -> None:
        self._text = text; self.update()

    def set_count(self, n: Optional[int]) -> None:
        self._count = n; self.update()

    def sizeHint(self) -> QSize:
        return QSize(100, 32)

    def contextMenuEvent(self, e: object) -> None:
        self.context_requested.emit(e.globalPos())  # type: ignore[attr-defined]

    def mousePressEvent(self, e: Any) -> None:
        if self.reorder and e.button() == Qt.LeftButton:
            self.reorder.pressed(self, e)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: Any) -> None:
        super().mouseMoveEvent(e)
        if self.reorder:
            self.reorder.moved(self, e)

    def mouseReleaseEvent(self, e: Any) -> None:
        if self.reorder and self.reorder.released(self):
            self.setDown(False); return          # перетаскивание — это не клик по пункту
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        base = .35 if self.dragging else 1.0
        p.setOpacity(base)
        r = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        on = self.isChecked() or self.lifted
        if on:
            theme.paint_control(p, r, "sel")
        elif self._hover.value > 0:
            p.setOpacity(self._hover.value * .75); theme.paint_control(p, r, "sel"); p.setOpacity(base)
        if self.hasFocus():
            paint_focus_ring(p, r)
        icons.draw_icon(p, self._icon, QRectF(14, 8, 16, 16),
                        theme.col("icon_on") if on else theme.col("dim"))
        right = self.width() - 12
        if self._count is not None:
            cw = QFontMetrics(self.font()).horizontalAdvance(str(self._count))
            p.setPen(theme.col("dim")); p.drawText(QRectF(right - cw, 0, cw, self.height()), Qt.AlignVCenter | Qt.AlignRight, str(self._count))
            right -= cw + 8
        p.setPen(theme.col("sel_text" if on else "text"))
        p.drawText(QRectF(40, 0, right - 40, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(self.font()).elidedText(self._text, Qt.ElideRight, int(right - 40)))


class CategoryReorder(QObject):
    """Перетаскивание категорий в сайдбаре — тот же механизм, что в списке напоминаний:
    призрак под курсором, линия вставки, тусклый оригинал, автопрокрутка у краёв."""
    reordered = pyqtSignal(list)   # новый порядок имён категорий

    def __init__(self, area: QScrollArea, content: QWidget) -> None:
        super().__init__(area)
        self.area, self.content = area, content
        self._items: list[NavItem] = []
        self._press: Optional[NavItem] = None
        self._press_pos = QPoint()
        self._dragging = False
        self._ghost: Optional[QLabel] = None
        self._line = _DropLine(content); self._line.hide()
        self._drop_index = 0
        self._scroll_dir = 0
        self._scroll_timer = QTimer(self); self._scroll_timer.setInterval(30)
        self._scroll_timer.timeout.connect(self._autoscroll)

    def set_items(self, items: list[NavItem]) -> None:
        self._cancel()
        self._items = items
        for it in items:
            it.reorder = self

    def pressed(self, item: NavItem, e: Any) -> None:
        self._press, self._press_pos = item, e.globalPos()

    def moved(self, item: NavItem, e: Any) -> None:
        if self._press is not item or len(self._items) < 2:
            return
        gp = e.globalPos()
        if not self._dragging and (gp - self._press_pos).manhattanLength() >= QApplication.startDragDistance():
            self._begin(item)
        if self._dragging:
            self._update(gp)

    def _begin(self, item: NavItem) -> None:
        self._dragging = True
        dpr = item.devicePixelRatioF()
        pm = QPixmap(int(item.width() * dpr), int(item.height() * dpr))
        pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
        item.lifted = True
        item.render(pm, QPoint(), QRegion(), QWidget.DrawChildren)
        item.lifted = False
        self._ghost = QLabel(self.area.viewport())
        self._ghost.setPixmap(pm); self._ghost.setFixedSize(item.size())
        self._ghost.setAttribute(Qt.WA_TranslucentBackground)
        self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents); self._ghost.show()
        item.dragging = True; item.update()
        self._line.setParent(self.content); self._line.show(); self._line.raise_()

    def _update(self, gp: QPoint) -> None:
        assert self._press is not None and self._ghost is not None
        pos = self.content.mapFromGlobal(gp)
        vp = self.area.viewport().mapFromGlobal(gp)
        vh = self.area.viewport().height()
        gy = max(0, min(vh - self._ghost.height(), vp.y() - self._ghost.height() // 2))
        self._ghost.move(self._press.x(), gy); self._ghost.raise_()
        others = [it for it in self._items if it is not self._press]
        self._drop_index = sum(1 for it in others if it.geometry().center().y() < pos.y())
        y = others[0].geometry().top() - 3 if self._drop_index == 0 else others[self._drop_index - 1].geometry().bottom()
        self._line.setGeometry(8, y, self.content.width() - 16, 4); self._line.raise_()
        self._scroll_dir = -1 if vp.y() < 28 else (1 if vp.y() > vh - 28 else 0)
        if self._scroll_dir and not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _autoscroll(self) -> None:
        if not self._dragging or not self._scroll_dir:
            self._scroll_timer.stop(); return
        bar = self.area.verticalScrollBar()
        bar.setValue(bar.value() + 14 * self._scroll_dir)
        self._update(self.area.cursor().pos())

    def released(self, item: NavItem) -> bool:
        """True — это было перетаскивание (клик по пункту засчитывать не нужно)."""
        if not (self._dragging and self._press is item):
            self._press = None
            return False
        others = [it.key[1] for it in self._items if it is not item]
        new = others[:self._drop_index] + [item.key[1]] + others[self._drop_index:]
        old = [it.key[1] for it in self._items]
        self._cancel()
        if new != old:
            self.reordered.emit(new)
        return True

    def _cancel(self) -> None:
        self._scroll_timer.stop()
        if self._ghost is not None:
            self._ghost.hide(); self._ghost.deleteLater(); self._ghost = None
        self._line.hide()
        for it in self._items:
            if it.dragging:
                it.dragging = False; it.update()
        self._dragging = False
        self._press = None


class UndoBar(QWidget):
    """Полоса «Отменить» после удаления однократного напоминания (~5 с)."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._text = ""
        self._cb: Optional[Callable[[], None]] = None
        self.btn = AeroButton("", "accent", self, compact=True)
        self.btn.clicked.connect(self._undo)
        self._timer = QTimer(self); self._timer.setInterval(30)      # отсчёт; на паузе (курсор над плашкой) не идёт
        self._timer.timeout.connect(self._countdown)
        self._left = float(core.UNDO_MS)                             # осталось, мс
        self._last = 0.0
        self._pix: Optional[QPixmap] = None                # размытое содержимое окна под плашкой
        self._blur_on = detect_mode() != SOLID
        self._blur_timer = QTimer(self); self._blur_timer.setInterval(100)   # список под плашкой может прокручиваться
        self._blur_timer.timeout.connect(self._refresh_blur)
        self.setFixedSize(380, 44); self.hide()

    def _refresh_blur(self) -> None:
        """Снимок окна под плашкой (фон + список, без самой плашки) → размытие → кэш для paintEvent."""
        page, win = self.parentWidget(), self.window()
        central = win.centralWidget() if hasattr(win, "centralWidget") else None
        if not self._blur_on or central is None or not self.isVisible():
            return
        pad, dpr = BLUR_PAD, self.devicePixelRatioF()
        area = self.rect().adjusted(-pad, -pad, pad, pad)
        img = QImage(int(area.width() * dpr), int(area.height() * dpr), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr); img.fill(Qt.transparent)
        origin = self.mapTo(central, area.topLeft())
        p = QPainter(img)
        p.translate(-origin)
        theme.paint_window_background(p, QRectF(central.rect()))
        p.translate(page.list.mapTo(central, QPoint()))
        page.list.render(p, QPoint(), QRegion(), QWidget.DrawChildren)
        p.end()
        img.setDevicePixelRatio(1.0)
        blurred = blur_image(img, BLUR_RADIUS * dpr)
        crop = blurred.copy(round(pad * dpr), round(pad * dpr), round(self.width() * dpr), round(self.height() * dpr))
        crop.setDevicePixelRatio(dpr)
        self._pix = QPixmap.fromImage(crop); self.update()

    def offer(self, text: str, undo: Callable[[], None]) -> None:
        self._text, self._cb = text, undo
        self.btn.setText(i18n.tr("undo")); self.btn.adjustSize()
        self.btn.move(self.width() - 12 - self.btn.width(), (self.height() - self.btn.height()) // 2)
        self._left, self._last = float(core.UNDO_MS), time.monotonic()
        self.show(); self.raise_(); self._timer.start()
        self._refresh_blur(); self._blur_timer.start()

    def _hovered(self) -> bool:
        # underMouse() не годится: кнопка внутри плашки перехватывает Enter/Leave
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _countdown(self) -> None:
        now = time.monotonic()
        paused = self._hovered()
        if not paused:
            self._left -= (now - self._last) * 1000
        self._last = now
        if self._left <= 0:
            self._timer.stop(); self.hide(); self._cb = None
            return
        self.update()

    def hideEvent(self, e: object) -> None:
        self._blur_timer.stop(); self._timer.stop(); self._pix = None
        super().hideEvent(e)  # type: ignore[arg-type]

    def _undo(self) -> None:
        self._timer.stop(); self.hide()
        if self._cb:
            self._cb()
        self._cb = None

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        r = QRectF(self.rect())
        if self._pix is not None:                          # размытый фон — текст списка под плашкой не просвечивает
            p.setRenderHint(QPainter.Antialiasing); p.setPen(Qt.NoPen)
            p.setBrush(QBrush(self._pix)); p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), S.R_PANEL, S.R_PANEL)
        fill = theme.col("menu"); fill.setAlpha(150 if self._pix is not None else 255)
        theme.paint_glass_panel(p, r, fill=fill)
        k = max(0.0, min(1.0, self._left / core.UNDO_MS))
        if k > 0:                                          # полоска оставшегося времени вдоль нижней кромки
            p.save(); p.setRenderHint(QPainter.Antialiasing)
            clip = QPainterPath(); clip.addRoundedRect(r.adjusted(.5, .5, -.5, -.5), S.R_PANEL, S.R_PANEL)
            p.setClipPath(clip)
            bar = theme.col("accent"); bar.setAlpha(210 if not self._hovered() else 140)   # на паузе — приглушена
            p.setPen(Qt.NoPen); p.setBrush(bar)
            p.drawRect(QRectF(r.left(), r.bottom() - 3, r.width() * k, 3))
            p.restore()
        p.setPen(theme.col("text"))
        p.drawText(QRectF(16, 0, self.width() - 120, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self._text)


class _ListPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.list = ReminderList(self)
        self.undo = UndoBar(self)

    def resizeEvent(self, _e: object) -> None:
        self.list.setGeometry(self.rect())
        self.undo.move((self.width() - self.undo.width()) // 2, self.height() - self.undo.height() - 16)


class _Central(QWidget):
    def paintEvent(self, _e: object) -> None:
        theme.paint_window_background(QPainter(self), QRectF(self.rect()))


class MainWindow(QMainWindow):
    def __init__(self, store: Storage, sched: Scheduler, toasts: ToastManager, tray: Optional[Tray]) -> None:
        super().__init__()
        self.store, self.sched, self.toasts, self.tray = store, sched, toasts, tray
        self.data = store.data
        self._quitting = False
        self.updater = Updater(self)
        self.updater.done.connect(self.on_update_result)
        self.key: NavKey = (F_ALL,)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(*S.WIN_MIN)

        central = _Central(); self.setCentralWidget(central)
        root = QHBoxLayout(central); root.setContentsMargins(12, 12, 12, 12); root.setSpacing(12)
        root.addWidget(self._build_sidebar())
        root.addLayout(self._build_main(), 1)

        self.settings_page.changed.connect(self.on_setting)
        self.settings_page.shortcut_requested.connect(self.on_shortcut)
        self.settings_page.export_requested.connect(self.on_export)
        self.settings_page.import_requested.connect(self.on_import)
        self.settings_page.optimize_requested.connect(self.on_optimize)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_reminder)
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_search)
        self._geo_timer = QTimer(self); self._geo_timer.setSingleShot(True); self._geo_timer.setInterval(500)
        self._geo_timer.timeout.connect(self.save_geometry)
        self._restore_geometry()
        i18n.subscribe(self.retranslate)
        self.toasts.activated.connect(self.on_toast_activated)
        self.toasts.snoozed.connect(lambda rid, delta: self.snooze(rid, core.now_local() + delta))
        self.toasts.more_clicked.connect(self.bring_to_front)
        self.sched.alerts.connect(self.toasts.show_alerts)
        self.sched.early_alerts.connect(self.toasts.show_early)
        self.toasts.early_closed.connect(self.on_early_closed)
        self.sched.refreshed.connect(self.refresh)
        s = store.settings
        last = s.get("last_page", F_ALL)
        cat = s.get("last_category")
        self.go((F_CATEGORY, cat) if last == F_CATEGORY and cat in self.data.categories
                else (last,) if last in (F_TODAY, F_OVERDUE, HISTORY, SETTINGS) else (F_ALL,))
        self.retranslate()
        self.list.setFocus()

    # ---- построение интерфейса
    def _build_sidebar(self) -> QWidget:
        panel = GlassPanel(); panel.setFixedWidth(S.SIDEBAR_W)
        lay = QVBoxLayout(panel); lay.setContentsMargins(8, 14, 8, 12); lay.setSpacing(2)
        self.nav: dict[NavKey, NavItem] = {}
        for key, icon in (((F_ALL,), "all"), ((F_TODAY,), "today"), ((F_OVERDUE,), "overdue")):
            lay.addWidget(self._nav(key, icon))
        self.cat_label = make_label("", "section"); self.cat_label.setContentsMargins(14, 8, 0, 0)
        lay.addWidget(self.cat_label)
        self.cat_area = QScrollArea(); self.cat_area.setWidgetResizable(True)
        self.cat_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget(); self.cat_lay = QVBoxLayout(inner)
        self.cat_lay.setContentsMargins(0, 0, 0, 0); self.cat_lay.setSpacing(2); self.cat_lay.addStretch(1)
        self.cat_area.setWidget(inner)
        self.cat_reorder = CategoryReorder(self.cat_area, inner)
        self.cat_reorder.reordered.connect(self.on_categories_reorder)
        lay.addWidget(self.cat_area, 1)
        sep = make_label(); sep.setProperty("role", "separator"); sep.setFixedHeight(1)
        lay.addWidget(sep)
        lay.addWidget(self._nav((HISTORY,), "history")); lay.addWidget(self._nav((SETTINGS,), "settings"))
        lay.addWidget(self._nav((ABOUT,), "info", self.show_about))   # не страница, а кнопка: открывает окно
        return panel

    def _nav(self, key: NavKey, icon: str, action: Optional[Callable[[], None]] = None) -> NavItem:
        item = NavItem(key, icon)
        if action:
            item.setCheckable(False)       # пункт-действие не «залипает» выбранным
            item.clicked.connect(lambda _c=False: action())
        else:
            item.clicked.connect(lambda: self.go(key))
        self.nav[key] = item
        return item

    def _build_main(self) -> QVBoxLayout:
        col = QVBoxLayout(); col.setSpacing(12)
        head = QHBoxLayout(); head.setSpacing(12)
        titles = QVBoxLayout(); titles.setSpacing(0)
        self.title = make_label("", "title"); self.subtitle = make_label("", "subtitle")
        titles.addWidget(self.title); titles.addWidget(self.subtitle)
        head.addLayout(titles, 1)
        self.search = SearchEdit(); self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.refresh)
        self.btn_sort = SortButton(); self.btn_sort.clicked.connect(self.sort_menu)
        self.plus = AeroButton("", "accent"); self.plus.set_glyph("plus"); self.plus.setFixedSize(28, 28)
        self.plus.clicked.connect(self.new_reminder)
        self.btn_del_sel = AeroButton("", "ctl"); self.btn_clear = AeroButton("", "danger")
        self.btn_del_sel.clicked.connect(self.delete_selected_history)
        self.btn_clear.clicked.connect(self.clear_history)
        for w in (self.search, self.btn_sort, self.plus, self.btn_del_sel, self.btn_clear):
            head.addWidget(w, 0, Qt.AlignVCenter)
        col.addLayout(head)

        self.stack = QStackedWidget()
        self.page_list = _ListPage(); self.list = self.page_list.list
        self.hist_list = ReminderList()
        self.settings_page = SettingsPage(self.store.settings)
        self.settings_scroll = QScrollArea(); self.settings_scroll.setWidgetResizable(True)   # скролл, если не влезает
        self.settings_scroll.setFrameShape(QScrollArea.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.settings_scroll.setWidget(self.settings_page)
        for w in (self.page_list, self.hist_list, self.settings_scroll):
            self.stack.addWidget(w)
        col.addWidget(self.stack, 1)
        for lst in (self.list, self.hist_list):
            lst.delete.connect(self.on_delete); lst.context_requested.connect(self.on_context)
        self.list.done.connect(self.on_done); self.list.edit.connect(self.on_edit)
        self.list.reordered.connect(self.on_reorder)
        self.hist_list.restore.connect(self.on_restore)
        self.hist_list.checks_changed.connect(self._update_history_tools)
        return col

    # ---- тексты
    def retranslate(self) -> None:
        tr = i18n.tr
        self.setWindowTitle(tr("app_title"))
        for key, name in (((F_ALL,), "nav_all"), ((F_TODAY,), "nav_today"), ((F_OVERDUE,), "nav_overdue"),
                          ((HISTORY,), "nav_history"), ((SETTINGS,), "nav_settings"), ((ABOUT,), "nav_about")):
            self.nav[key].set_text(tr(name))
        self.cat_label.setText(tr("nav_categories"))
        self.search.setPlaceholderText(tr("search_ph"))
        self.btn_clear.setText(tr("h_clear"))
        self.btn_sort.setToolTip(tr("sort_tip"))
        self.btn_sort.fit([tr(f"sort_{m}") for m in core.SORTS])
        self.settings_page.retranslate()
        self.refresh()

    # ---- навигация
    def go(self, key: NavKey) -> None:
        self.key = key
        kind = key[0]
        self.stack.setCurrentIndex(1 if kind == HISTORY else 2 if kind == SETTINGS else 0)
        self.store.set(last_page=kind, last_category=key[1] if kind == F_CATEGORY else None)
        self.refresh()

    @property
    def flt(self) -> Filter:
        return (self.key[0], self.key[1] if self.key[0] == F_CATEGORY else None)

    def _is_list_page(self) -> bool:
        return self.key[0] not in (HISTORY, SETTINGS)

    def _sync_categories(self) -> None:
        names = list(self.data.categories)
        current = [k[1] for k in self.nav if k[0] == F_CATEGORY]
        if names != current:
            for k in [k for k in self.nav if k[0] == F_CATEGORY]:
                item = self.nav.pop(k); item.hide(); item.deleteLater()
            for name in names:
                item = NavItem((F_CATEGORY, name), "folder", name)
                item.clicked.connect(lambda _c=False, n=name: self.go((F_CATEGORY, n)))
                item.context_requested.connect(lambda pos, n=name: self.category_menu(n, pos))
                self.nav[(F_CATEGORY, name)] = item
                self.cat_lay.insertWidget(self.cat_lay.count() - 1, item)
            self.cat_reorder.set_items([self.nav[(F_CATEGORY, n)] for n in names])
        self.cat_label.setVisible(bool(names))   # область категорий остаётся в раскладке: она поглощает свободную высоту

    def _page_title(self) -> str:
        tr, kind = i18n.tr, self.key[0]
        return {F_ALL: tr("nav_all"), F_TODAY: tr("nav_today"), F_OVERDUE: tr("nav_overdue"),
                HISTORY: tr("nav_history"), SETTINGS: tr("nav_settings")}.get(kind) or str(self.key[1])

    # ---- сортировка: общий список и категории хранятся раздельно
    def sort_mode(self) -> str:
        s = self.store.settings
        if self.key[0] == F_CATEGORY:
            mode = s.get("sort_cat")
            if s.get("sort_per_cat"):
                mode = (s.get("sort_cats") or {}).get(self.key[1], mode)
        else:
            mode = s.get("sort_all")
        return mode if mode in core.SORTS else core.MANUAL

    def set_sort_mode(self, mode: str) -> None:
        if self.key[0] != F_CATEGORY:
            self.store.set(sort_all=mode)
        elif self.store.settings.get("sort_per_cat"):
            self.store.set(sort_cats={**(self.store.settings.get("sort_cats") or {}), self.key[1]: mode})
        else:
            self.store.set(sort_cat=mode)
        self.refresh()

    def sort_menu(self) -> None:
        menu = AeroMenu(self)
        cur = self.sort_mode()
        for mode in core.SORTS:
            act = menu.addAction(i18n.tr(f"sort_{mode}"), lambda m=mode: self.set_sort_mode(m))
            act.setCheckable(True); act.setChecked(mode == cur)
        b = self.btn_sort
        pos = b.mapToGlobal(QPoint(b.width() - menu.sizeHint().width() + S.SHADOW, b.height() + 2 - S.SHADOW))
        menu.exec_(pos)

    def _forget_sort(self, name: str, new: Optional[str] = None) -> None:
        """Режим сортировки категории следует за ней при переименовании и удаляется вместе с ней."""
        cats = dict(self.store.settings.get("sort_cats") or {})
        if name in cats:
            mode = cats.pop(name)
            if new:
                cats[new] = mode
            self.store.set(sort_cats=cats)

    def on_categories_reorder(self, names: list) -> None:
        core.reorder_categories(self.data, names)
        self._commit()

    # ---- обновление
    def refresh(self, *_a: object) -> None:
        now = core.now_local()
        if self.key[0] == F_CATEGORY and self.key[1] not in self.data.categories:
            self.key = (F_ALL,)
        self._sync_categories()
        counts = core.counts(self.data, now)
        for key, item in self.nav.items():
            item.setChecked(key == self.key)
            if key[0] in (F_ALL, F_TODAY, F_OVERDUE):
                item.set_count(counts[key[0]])
            elif key[0] == F_CATEGORY:
                item.set_count(counts[F_CATEGORY].get(key[1], 0))
            else:
                item.set_count(None)
        kind = self.key[0]
        self.title.setText(self._page_title())
        on_list, on_hist = self._is_list_page(), kind == HISTORY
        for w in (self.search, self.btn_sort, self.plus):
            w.setVisible(on_list)
        for w in (self.btn_del_sel, self.btn_clear):
            w.setVisible(on_hist)
        self.subtitle.setVisible(kind != SETTINGS)
        tr = i18n.tr
        if on_list:
            query = self.search.text()
            mode = self.sort_mode()
            self.btn_sort.setText(tr(f"sort_{mode}"))
            rows = core.visible(self.data, self.flt, now, query, mode)
            self.list.drag_enabled = mode == core.MANUAL and kind in (F_ALL, F_CATEGORY)
            # подсказка «Нажмите +» осмысленна только там, где «+» добавляет прямо сюда
            hint = tr("empty_hint") if kind in (F_ALL, F_CATEGORY) and not query else ""
            self.list.set_items([row_from_reminder(r, now) for r in rows],
                                tr("empty_search" if query else "empty_title"), hint)
            self.subtitle.setText(i18n.plural("n_reminders", len(rows)))
        elif on_hist:
            items = sorted(self.data.history, key=lambda h: h.completed_at, reverse=True)
            self.hist_list.set_items([row_from_history(h, now) for h in items], tr("empty_history"))
            self.subtitle.setText(i18n.plural("n_reminders", len(items)))
            self._update_history_tools()

    def _update_history_tools(self) -> None:
        n = len(self.hist_list.checked_ids())
        self.btn_del_sel.setText(i18n.tr("h_delete_selected") + (f" ({n})" if n else ""))
        self.btn_del_sel.setEnabled(n > 0)
        self.btn_clear.setEnabled(bool(self.data.history))

    def _commit(self, dismiss: Optional[str] = None) -> None:
        self.store.save_data()
        if dismiss:
            self.toasts.dismiss(dismiss)
        self.refresh()

    # ---- действия над напоминаниями
    def new_reminder(self) -> None:
        if not self.isVisible() or self.isMinimized():
            self.bring_to_front()
        preset = self.key[1] if self.key[0] == F_CATEGORY else None
        dlg = ReminderDialog(self, self.data.categories, preset_category=preset)
        if dlg.exec_() != QDialog.Accepted:
            return
        v = dlg.values()
        r = Reminder.create(v["title"], v["due"], description=v["description"], category=v["category"],
                            priority=v["priority"], repeat=v["repeat"], silent=v["silent"], early_min=v["early_min"])
        core.add_reminder(self.data, r)
        self.store.save_data()
        self.sched.tick()           # время в прошлом — сработает сразу
        self.refresh()
        if self._is_list_page():
            self.list.select(r.id, True)

    def on_edit(self, rid: str) -> None:
        r = self.data.get(rid)
        if not r:
            return
        dlg = ReminderDialog(self, self.data.categories, r)
        if dlg.exec_() != QDialog.Accepted:
            return
        core.apply_edit(self.data, r, **dlg.values())
        self._commit(dismiss=rid if r.state != core.ALERTING else None)
        self.sched.tick()

    def on_done(self, rid: str) -> None:
        r = self.data.get(rid)
        if r and core.complete(self.data, r, core.now_local()):
            self._commit(dismiss=rid)
        else:
            self.refresh()

    def on_delete(self, rid: str) -> None:
        if self.key[0] == HISTORY:
            core.delete_history(self.data, [rid]); self._commit(); return
        r = self.data.get(rid)
        if not r:
            return
        if r.repeat != core.ONCE and not confirm(self, i18n.tr("confirm_delete_series"), i18n.tr("delete"), danger=True):
            return
        idx = core.delete_reminder(self.data, r)   # и у повторяющихся тоже можно «Отменить»: вернётся вся серия
        self._commit(dismiss=rid)
        self.page_list.undo.offer(i18n.tr("deleted"), lambda: self._undo_delete(r, idx))

    def _undo_delete(self, r: Reminder, idx: int) -> None:
        core.undo_delete(self.data, r, idx)
        self._commit()
        if r.state == core.ALERTING:
            self.toasts.show_alerts([r])

    def on_reorder(self, ids: list[str]) -> None:
        core.reorder_subset(self.data, ids, self.key[0] == F_CATEGORY)
        self.store.save_data(); self.refresh()

    def snooze(self, rid: str, until: datetime) -> None:
        r = self.data.get(rid)
        if r and core.snooze(r, until):
            self._commit(dismiss=rid)

    def on_context(self, rid: str, pos: QPoint) -> None:
        tr = i18n.tr
        menu = AeroMenu(self)
        if self.key[0] == HISTORY:
            h = next((x for x in self.data.history if x.id == rid), None)
            if h and h.repeat == core.ONCE:
                menu.addAction(tr("h_restore"), lambda: self.on_restore(rid))
            menu.addAction(tr("h_delete_forever"), lambda: self.on_delete(rid))
            menu.exec_(pos); return
        r = self.data.get(rid)
        if not r:
            return
        now = core.now_local()
        menu.addAction(tr("edit"), lambda: self.on_edit(rid), QKeySequence(Qt.Key_Return))
        sub = AeroMenu(tr("snooze"), menu); menu.addMenu(sub)
        t = i18n.fmt_time(datetime(2000, 1, 1, core.TOMORROW_HOUR))
        any_snooze = False
        for label, calc in ((tr("snooze_10"), lambda n: n + core.SNOOZE_SHORT),
                            (tr("snooze_1h"), lambda n: n + core.SNOOZE_LONG),
                            (tr("snooze_tomorrow", time=t), core.tomorrow_morning),
                            (tr("snooze_week"), core.week_morning)):
            act = sub.addAction(label, lambda calc=calc: self.snooze(rid, calc(core.now_local())))
            act.setEnabled(core.can_snooze(r, calc(now), now))     # рано: ни срок, ни «заранее» ещё не наступили
            any_snooze = any_snooze or act.isEnabled()
        sub.menuAction().setEnabled(any_snooze)
        done = menu.addAction(tr("done"), lambda: self.on_done(rid))
        done.setEnabled(core.can_complete(r, now))
        menu.addSeparator()
        menu.addAction(tr("delete"), lambda: self.on_delete(rid), QKeySequence(Qt.Key_Delete))
        menu.exec_(pos)

    # ---- история
    def on_restore(self, hid: str) -> None:
        h = next((x for x in self.data.history if x.id == hid), None)
        if h and h.repeat == core.ONCE:
            core.restore_from_history(self.data, h)
            self.store.save_data(); self.sched.tick(); self.refresh()

    def delete_selected_history(self) -> None:
        ids = self.hist_list.checked_ids()
        if ids and confirm(self, i18n.tr("confirm_delete_selected"), i18n.tr("delete"), danger=True):
            core.delete_history(self.data, ids); self.hist_list.clear_checks(); self._commit()

    def clear_history(self) -> None:
        if self.data.history and confirm(self, i18n.tr("confirm_clear_history"), i18n.tr("h_clear"), danger=True):
            core.delete_history(self.data, [h.id for h in self.data.history]); self.hist_list.clear_checks(); self._commit()

    # ---- категории
    def category_menu(self, name: str, pos: QPoint) -> None:
        tr = i18n.tr
        menu = AeroMenu(self)
        menu.addAction(tr("rename"), lambda: self.rename_category(name))
        menu.addAction(tr("delete"), lambda: self.delete_category(name))
        menu.exec_(pos)

    def rename_category(self, name: str) -> None:
        new = ask_text(self, i18n.tr("cat_rename_title"), i18n.tr("cat_name"), name)
        if new and new != name:
            core.rename_category(self.data, name, new)
            self._forget_sort(name, new)
            if self.key == (F_CATEGORY, name):
                self.key = (F_CATEGORY, new)
            self._commit()

    def delete_category(self, name: str) -> None:
        if confirm(self, i18n.tr("confirm_delete_category", name=name), i18n.tr("delete"), danger=True):
            core.delete_category(self.data, name)
            self._forget_sort(name)
            if self.key == (F_CATEGORY, name):
                self.key = (F_ALL,)
            self._commit()

    # ---- уведомления
    def on_toast_activated(self, rid: str) -> None:
        r = self.data.get(rid)
        if r and r.state == core.ALERTING:
            core.acknowledge(r); self.store.save_data()
        self.bring_to_front()
        if r:
            self.reveal(rid)

    def reveal(self, rid: str) -> None:
        r = self.data.get(rid)
        if not r:
            return
        now = core.now_local()
        if not self._is_list_page() or not core.matches(r, self.flt, now) or rid not in [
                x.id for x in core.visible(self.data, self.flt, now, self.search.text())]:
            self.search.clear()
            self.go((F_ALL,))
        self.refresh()
        self.list.select(rid, True)

    # ---- настройки
    def on_early_closed(self, rid: str) -> None:
        r = self.data.get(rid)
        if r and core.ack_early(r):
            self.store.save_data()

    def on_export(self) -> None:
        name = f"reminders-{core.now_local():%Y%m%d}.json"
        path, _f = QFileDialog.getSaveFileName(self, i18n.tr("export_title"), str(Path.home() / name),
                                               i18n.tr("json_filter"))
        if not path:
            return
        try:
            self.store.export_json(path)
            info(self, i18n.tr("export_ok"))
        except OSError:
            info(self, i18n.tr("err_export"))

    def on_import(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, i18n.tr("import_title"), str(Path.home()),
                                               i18n.tr("json_filter"))
        if not path:
            return
        try:
            n_r, n_h = self.store.import_json(path)
        except (OSError, ValueError):       # JSONDecodeError — подкласс ValueError
            info(self, i18n.tr("err_import")); return
        self.refresh(); self.sched.tick()   # просроченные из файла сработают сразу
        info(self, i18n.tr("import_ok", r=n_r, h=n_h) if n_r or n_h else i18n.tr("import_none"))

    def on_optimize(self) -> None:
        try:
            before, after = self.store.optimize_db()
        except (OSError, sqlite3.Error):
            info(self, i18n.tr("err_optimize")); return
        info(self, i18n.tr("db_optimize_ok", before=_fmt_size(before), after=_fmt_size(after)))

    def on_shortcut(self) -> None:
        info(self, i18n.tr("shortcut_ok" if storage.create_desktop_shortcut() else "err_shortcut"))

    def on_setting(self, key: str, value: Any) -> None:
        if key == "language":
            self.store.set(language=value); i18n.set_language(value)
        elif key == "theme":
            self.store.set(theme=value)
            theme.apply_theme(QApplication.instance(), value)
            theme.apply_titlebar(self, value)
            self.update()
        elif key == "autostart":
            if not storage.set_autostart(bool(value)):
                info(self, i18n.tr("err_autostart")); self.settings_page.set_autostart_checked(not value); return
            self.store.set(autostart=bool(value))
        elif key == "history_days":
            self.store.set(history_days=value); self.sched.purge_now()
        elif key == "sort_per_cat":
            self.store.set(sort_per_cat=bool(value)); self.refresh()
        else:
            self.store.set(**{key: value})

    def show_about(self) -> None:
        AboutDialog(self, self.updater).exec_()

    # ---- обновления
    def check_updates_on_start(self) -> None:
        """Тихая проверка в фоне при запуске (если включена в настройках)."""
        if self.store.settings.get("check_updates", True):
            self.updater.check()

    def on_update_result(self, res: UpdateResult) -> None:
        """Результат тихой проверки: показываем только найденное обновление, любые ошибки молча игнорируем.
        Ручную проверку обрабатывает окно «О программе»."""
        if res.manual or res.status != FOUND or res.release is None:
            return
        if QApplication.activeModalWidget() is not None:     # пользователь занят другим диалогом — спросим чуть позже
            QTimer.singleShot(3000, lambda: self.on_update_result(res))
            return
        UpdateDialog(self if self.isVisible() else None, res.release).exec_()

    # ---- окно: трей, геометрия, фокус
    def focus_search(self) -> None:
        if not self._is_list_page():
            self.go((F_ALL,))
        self.search.setFocus(); self.search.selectAll()

    def bring_to_front(self) -> None:
        if self.isMinimized():
            self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.show(); self.raise_(); self.activateWindow(); force_foreground(self)

    def showEvent(self, e: object) -> None:
        theme.apply_titlebar(self)
        super().showEvent(e)  # type: ignore[arg-type]

    def _restore_geometry(self) -> None:
        g = self.store.settings.get("geometry")
        if not (g and self.restoreGeometry(QByteArray.fromBase64(g.encode()))):
            self.resize(*S.WIN_DEFAULT)

    def save_geometry(self) -> None:
        self.store.set(geometry=bytes(self.saveGeometry().toBase64()).decode())

    def resizeEvent(self, e: object) -> None:
        super().resizeEvent(e)  # type: ignore[arg-type]
        self._geo_timer.start()

    def moveEvent(self, e: object) -> None:
        super().moveEvent(e)  # type: ignore[arg-type]
        self._geo_timer.start()

    def closeEvent(self, e: object) -> None:
        self.save_geometry()
        if self._quitting or self.tray is None:
            e.accept(); QApplication.quit(); return  # type: ignore[attr-defined]
        e.ignore()  # type: ignore[attr-defined]
        self.hide()
        if not self.store.settings.get("tray_hint_shown"):
            self.tray.show_hint(); self.store.set(tray_hint_shown=True)

    def quit_app(self) -> None:
        self._quitting = True
        QApplication.quit()
