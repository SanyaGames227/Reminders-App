"""Диалог «О программе»: версия, авторы, источники вдохновения, сторонние библиотеки, ссылки."""
from __future__ import annotations

import sqlite3
import sys
from typing import Optional

from PyQt5.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, QRectF, QSize, QUrl, Qt
from PyQt5.QtGui import QColor, QDesktopServices, QFontMetrics, QPainter
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

import core
import i18n
import icons
import theme
from theme import S
from ui.update_dialog import UpdateDialog
from ui.widgets import AeroButton, AeroDialog, GlassPanel, info, make_label
from updater import CURRENT, FOUND, UpdateResult, Updater

AUTHOR_IDEA = "sanyagames227"
AUTHOR_DEV = "Claude AI (Anthropic)"
INSPIRED = ("Windows Vista", "Apple iOS")


def libraries() -> list[tuple[str, str]]:
    """Что реально используется в программе. Версии берутся из работающей среды, а не прописаны вручную.
    Всё остальное (sqlite3, json, ctypes и т.д.) — стандартная библиотека Python."""
    v = sys.version_info
    return [("Python", f"{v.major}.{v.minor}.{v.micro}"),
            ("PyQt5", PYQT_VERSION_STR),
            ("Qt", QT_VERSION_STR),
            ("SQLite", sqlite3.sqlite_version)]


class _Footer(QWidget):
    """Строка «© … Создано с ♥ и …»: сердце — векторная иконка приложения (белая с лёгкой тенью), не символ шрифта."""
    HEART, GAP = 13, 5

    def __init__(self, template: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._before, _, self._after = (t.strip() for t in template.partition("{heart}"))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _width(self) -> int:
        fm = QFontMetrics(self.font())
        return fm.horizontalAdvance(self._before) + fm.horizontalAdvance(self._after) + self.HEART + 2 * self.GAP

    def sizeHint(self) -> QSize:
        return QSize(self._width(), max(20, QFontMetrics(self.font()).height() + 4))

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        fm = QFontMetrics(self.font())
        x, h = (self.width() - self._width()) / 2, self.height()
        p.setPen(theme.col("dim"))
        w1 = fm.horizontalAdvance(self._before)
        p.drawText(QRectF(x, 0, w1, h), Qt.AlignVCenter | Qt.AlignLeft, self._before)
        x += w1 + self.GAP
        box = QRectF(x, (h - self.HEART) / 2, self.HEART, self.HEART)
        icons.draw_icon(p, "heart", box.translated(0, 1), QColor(8, 40, 90, 110))      # тень — чтобы белое читалось на светлой теме
        icons.draw_icon(p, "heart", box, QColor("#ffffff"))
        x += self.HEART + self.GAP
        p.setPen(theme.col("dim"))
        p.drawText(QRectF(x, 0, fm.horizontalAdvance(self._after), h), Qt.AlignVCenter | Qt.AlignLeft, self._after)


class AboutDialog(AeroDialog):
    def __init__(self, parent: Optional[QWidget], updater: Updater) -> None:
        tr = i18n.tr
        super().__init__(parent, tr("about_title"))
        self.setMinimumWidth(420)
        self._updater = updater
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16); lay.setSpacing(S.SP * 2)

        # шапка: иконка, название, версия
        logo = QLabel(); logo.setPixmap(icons.app_icon().pixmap(64, 64)); logo.setAlignment(Qt.AlignHCenter)
        name = make_label(tr("app_title"), "title"); name.setAlignment(Qt.AlignHCenter)
        ver = make_label(tr("about_version", v=core.APP_VERSION), "dim"); ver.setAlignment(Qt.AlignHCenter)
        head = QVBoxLayout(); head.setSpacing(2)
        head.addWidget(logo); head.addSpacing(S.SP); head.addWidget(name); head.addWidget(ver)
        lay.addLayout(head)

        lay.addWidget(self._section("about_authors", [(tr("about_idea"), AUTHOR_IDEA), (tr("about_dev"), AUTHOR_DEV)]))
        lay.addWidget(self._section("about_inspired", [(None, "  •  ".join(INSPIRED))]))
        lay.addWidget(self._section("about_libs", libraries()))

        self._updates = AeroButton(tr("about_updates"))
        self._updates.setFixedWidth(max(self._updates.sizeHint().width(),            # ширина не прыгает при «Проверка…»
                                        self._updates.fontMetrics().horizontalAdvance(tr("update_checking")) + 36))
        self._updates.clicked.connect(lambda _c=False: self._check_updates())
        updater.done.connect(self._on_update_result)
        self.finished.connect(lambda _r: updater.done.disconnect(self._on_update_result))
        github = AeroButton(tr("about_github"))
        github.clicked.connect(lambda _c=False: QDesktopServices.openUrl(QUrl(core.GITHUB_URL)))
        row = QHBoxLayout(); row.setSpacing(S.SP)
        row.addStretch(1); row.addWidget(self._updates); row.addWidget(github); row.addStretch(1)
        lay.addLayout(row)

        lay.addWidget(_Footer(tr("about_footer")))

    def _check_updates(self) -> None:
        """Ручная проверка: в отличие от тихой при запуске, сообщает и об ошибке, и о «уже последняя»."""
        self._updates.setEnabled(False); self._updates.setText(i18n.tr("update_checking"))
        self._updater.check(manual=True)

    def _on_update_result(self, res: UpdateResult) -> None:
        if not res.manual:
            return
        tr = i18n.tr
        self._updates.setEnabled(True); self._updates.setText(tr("about_updates"))
        if res.status == FOUND and res.release is not None:
            UpdateDialog(self, res.release).exec_()
        else:
            info(self, tr("update_uptodate", v=core.APP_VERSION) if res.status == CURRENT else tr("update_failed"),
                 tr("update_title"))

    def _section(self, key: str, rows: list[tuple[Optional[str], str]]) -> QWidget:
        """Заголовок секции слева над стеклянной панелью (как в настройках); строки «подпись — значение»."""
        panel = GlassPanel(); g = QGridLayout(panel)
        g.setContentsMargins(20, 14, 20, 14); g.setHorizontalSpacing(S.SP * 3); g.setVerticalSpacing(S.SP)
        for i, (label, value) in enumerate(rows):
            if label is None:
                g.addWidget(QLabel(value), i, 0, 1, 2)
            else:
                g.addWidget(make_label(label, "dim"), i, 0); g.addWidget(QLabel(value), i, 1)
        g.setColumnStretch(1, 1); g.setColumnMinimumWidth(0, 140)
        box = QWidget(); v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        head = make_label(i18n.tr(key), "section"); head.setContentsMargins(6, 0, 0, 4)
        v.addWidget(head); v.addWidget(panel)
        return box
