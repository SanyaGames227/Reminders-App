"""Диалог «Доступно обновление»: версия, список изменений, переход на страницу релизов."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QRectF, QSize, QUrl, Qt
from PyQt5.QtGui import QDesktopServices, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

import core
import i18n
import icons
import theme
from core import Release
from theme import S
from ui.widgets import AeroButton, AeroDialog, GlassPanel, make_label

NOTES_H = 170


class _Badge(QWidget):
    """Плашка с номером новой версии: акцентное «стекло» и белый полужирный текст."""

    def __init__(self, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._text = text
        self.setFixedSize(self.sizeHint())

    def _font(self) -> QFont:
        f = QFont(self.font()); f.setBold(True)
        return f

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self._font()).horizontalAdvance(self._text) + 24, 24)

    def paintEvent(self, _e: object) -> None:
        p = QPainter(self)
        theme.paint_control(p, QRectF(self.rect()), "acc")
        p.setFont(self._font()); p.setPen(theme.col("hl_text"))
        p.drawText(QRectF(self.rect()), Qt.AlignCenter, self._text)


class _Notes(QTextBrowser):
    """Список изменений (Markdown) без собственной рамки — рамку даёт стеклянная панель."""

    def __init__(self, notes: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.setOpenExternalLinks(True)
        self.document().setDefaultStyleSheet(f"a {{ color: {theme.col('accent_text').name()}; }}")
        self.setViewportMargins(0, 0, 0, 0)
        if not notes:
            self.setPlainText(i18n.tr("update_no_notes"))
        elif hasattr(self, "setMarkdown"):      # Qt ≥ 5.14
            self.setMarkdown(notes)
        else:
            self.setPlainText(notes)


class UpdateDialog(AeroDialog):
    def __init__(self, parent: Optional[QWidget], release: Release) -> None:
        tr = i18n.tr
        super().__init__(parent, tr("update_title"))
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16); lay.setSpacing(S.SP * 2)

        # шапка: иконка, заголовок, «текущая → новая»
        logo = QLabel(); logo.setPixmap(icons.app_icon().pixmap(56, 56)); logo.setAlignment(Qt.AlignHCenter)
        title = make_label(tr("update_available"), "title"); title.setAlignment(Qt.AlignHCenter)
        old = make_label(f"{core.APP_VERSION}  →", "dim")
        ver = QHBoxLayout(); ver.setSpacing(S.SP)
        ver.addStretch(1); ver.addWidget(old); ver.addWidget(_Badge(release.version)); ver.addStretch(1)
        head = QVBoxLayout(); head.setSpacing(2)
        head.addWidget(logo); head.addSpacing(S.SP); head.addWidget(title); head.addSpacing(S.SP // 2); head.addLayout(ver)
        lay.addLayout(head)

        # список изменений: заголовок слева над стеклянной панелью (как в настройках)
        panel = GlassPanel(); pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 8, 10)
        notes = _Notes(release.notes); notes.setFixedHeight(NOTES_H)
        pl.addWidget(notes)
        sec = make_label(tr("update_notes"), "section"); sec.setContentsMargins(6, 0, 0, 4)
        box = QVBoxLayout(); box.setSpacing(0); box.addWidget(sec); box.addWidget(panel)
        lay.addLayout(box)

        later = AeroButton(tr("update_later")); later.clicked.connect(self.reject)
        get = AeroButton(tr("update_download"), "accent"); get.setFocusPolicy(Qt.StrongFocus); get.setDefault(True)
        get.clicked.connect(self._download)
        row = QHBoxLayout(); row.setSpacing(S.SP)
        row.addStretch(1); row.addWidget(later); row.addWidget(get)
        lay.addLayout(row)
        get.setFocus()

    def _download(self) -> None:
        QDesktopServices.openUrl(QUrl(core.RELEASES_URL))
        self.accept()
