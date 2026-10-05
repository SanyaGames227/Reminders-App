"""Единая система оформления Aero: токены, QPalette, QSS-шаблон, глифы, «стекло», DWM.

Весь внешний вид задаётся здесь. Цвета вне палитры токенов в остальном коде не допускаются.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from string import Template
from typing import Callable, Optional

from PyQt5.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QLinearGradient, QPainter, QPainterPath, QPalette, QPen,
                         QRadialGradient)
from PyQt5.QtWidgets import QApplication, QWidget

import icons
import storage


# ---- Размеры и константы (кратно 4/8) ------------------------------------------------------
class S:
    SP = 8
    R_CTL = 4
    R_PANEL = 9
    SIDEBAR_W = 232
    WIN_MIN = (900, 600)
    WIN_DEFAULT = (1040, 680)
    ROW_H = 64
    TOAST_W = 360
    TOAST_H = 84
    TOAST_GAP = 8
    TOAST_MAX = 4
    SHADOW = 12          # поле под тень у всплывающих окон
    ANIM_FAST = 140      # мс, hover
    ANIM_TOAST = 220     # мс, появление/исчезновение
    FONT = "Segoe UI"
    FONT_PT = 9


# ---- Токены --------------------------------------------------------------------------------
BASE = {
    "light": dict(
        bg1="#e9f7fd", bg2="#98cfea", glare="rgba(255,255,255,150)",
        panel="rgba(255,255,255,135)", panel_edge="rgba(35,85,125,120)", panel_in="rgba(255,255,255,200)",
        sheen="rgba(255,255,255,95)",
        text="#14283a", dim="#46607a", faint="#8ea2b3",
        accent="#2a85d8", glow="#38c6f4", danger="#d63c3c",
        field="#fdfeff", field_edge="#7b97b2",
        ctl_hi="#fdfeff", ctl_lo="#cadbec", ctl_edge="#6f8da9", ctl_in="rgba(255,255,255,210)",
        sel_t1="#f2faff", sel_t2="#dcf0fc", sel_b1="#c4e5f9", sel_b2="#d3ecfb", sel_edge="#78bde8",
        menu="rgba(248,253,255,246)", menu_edge="rgba(40,90,130,170)", sep="rgba(60,100,140,70)",
        hl="#3d93df", hl_text="#ffffff", sel_text="#10243a",
        dis_bg="rgba(200,215,228,120)", dis_edge="rgba(120,140,160,110)",
        caption="#d4ebf8", caption_text="#14283a", shadow="rgba(10,40,70,95)",
        icon_on="#2a85d8", danger_text="#c93434", accent_text="#1f78cc", snooze_text="#b45f06",
        text_shadow="rgba(0,0,0,0)",
    ),
    "dark": dict(
        bg1="#1b4c88", bg2="#071a36", glare="rgba(140,200,255,70)",
        panel="rgba(255,255,255,26)", panel_edge="rgba(0,0,0,170)", panel_in="rgba(255,255,255,62)",
        sheen="rgba(255,255,255,34)",
        text="#e9f2fb", dim="#a9bdd2", faint="#6f849b",
        accent="#3b93e8", glow="#4fd0f7", danger="#e0494b",
        field="#0f2441", field_edge="#050f1d",
        ctl_hi="#547aa8", ctl_lo="#1f3a60", ctl_edge="#050f1d", ctl_in="rgba(255,255,255,70)",
        sel_t1="rgba(150,210,255,115)", sel_t2="rgba(100,175,240,100)", sel_b1="rgba(50,125,210,105)",
        sel_b2="rgba(70,150,230,100)", sel_edge="rgba(140,200,250,175)",
        menu="rgba(16,38,68,248)", menu_edge="rgba(120,180,230,150)", sep="rgba(255,255,255,45)",
        hl="#2f7fd0", hl_text="#ffffff", sel_text="#ffffff",
        dis_bg="rgba(255,255,255,16)", dis_edge="rgba(0,0,0,120)",
        caption="#10294a", caption_text="#e9f2fb", shadow="rgba(0,0,0,150)",
        icon_on="#ffffff", danger_text="#ff8f8f", accent_text="#93dbff", snooze_text="#ffc15e",
        text_shadow="rgba(0,10,30,190)",
    ),
}

_RGBA = re.compile(r"rgba\((\d+),\s*(\d+),\s*(\d+),\s*(\d+)\)")


def qcolor(s: str) -> QColor:
    m = _RGBA.fullmatch(s.strip())
    return QColor(int(m[1]), int(m[2]), int(m[3]), int(m[4])) if m else QColor(s)


def css(c: QColor) -> str:
    return f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})" if c.alpha() < 255 else c.name()


def mix(a: str, b: str, t: float) -> str:
    ca, cb = qcolor(a), qcolor(b)
    f = lambda x, y: round(x + (y - x) * t)
    return css(QColor(f(ca.red(), cb.red()), f(ca.green(), cb.green()),
                      f(ca.blue(), cb.blue()), f(ca.alpha(), cb.alpha())))


def fade(a: str, k: float) -> str:
    c = qcolor(a)
    c.setAlpha(round(c.alpha() * k))
    return css(c)


def lighter(a: str, k: int) -> str:
    return css(qcolor(a).lighter(k))


def darker(a: str, k: int) -> str:
    return css(qcolor(a).darker(k))


def vgrad(c1: str, c2: str, c3: str, c4: str, horizontal: bool = False) -> str:
    """Стеклянный градиент: резкий разрыв на 50% (верх светлее низа)."""
    axis = "x1:0,y1:0,x2:1,y2:0" if horizontal else "x1:0,y1:0,x2:0,y2:1"
    return (f"qlineargradient({axis},stop:0 {c1},stop:0.49 {c2},stop:0.5 {c3},stop:1 {c4})")


def make_tokens(name: str) -> dict[str, str]:
    t = dict(BASE[name])
    hi, lo, glow = t["ctl_hi"], t["ctl_lo"], t["glow"]
    stops = (hi, mix(hi, lo, .3), lo, mix(lo, hi, .3))
    t["g_ctl"] = vgrad(*stops)
    hov = tuple(mix(c, glow, .33) for c in stops)
    t["g_hov"] = vgrad(*hov)
    t["h_edge"] = mix(t["ctl_edge"], glow, .75)
    prs = (darker(stops[2], 108), darker(stops[3], 108), darker(stops[2], 125), darker(stops[3], 112))
    t["g_prs"] = vgrad(*prs)
    t["p_edge"] = mix(t["ctl_edge"], t["accent"], .45)
    for key, base in (("acc", t["accent"]), ("dng", t["danger"])):
        s = (lighter(base, 150), lighter(base, 116), darker(base, 112), base)
        t[f"g_{key}"] = vgrad(*s)
        t[f"g_{key}_hov"] = vgrad(*(mix(c, "#ffffff", .18) for c in s))
        t[f"g_{key}_prs"] = vgrad(*(darker(c, 118) for c in s))
        t[f"{key}_edge"] = darker(base, 175)
    sel = (t["sel_t1"], t["sel_t2"], t["sel_b1"], t["sel_b2"])
    t["g_sel"] = vgrad(*sel)
    t["g_selh"] = vgrad(*(fade(c, .55) for c in sel))
    t["sh_edge"] = fade(t["sel_edge"], .6)
    t["g_dis"] = t["dis_bg"]
    hs = tuple(fade(c, .92) for c in stops)
    t["g_handle_v"] = vgrad(*hs, horizontal=True)
    t["g_handle_v_hov"] = vgrad(*(fade(c, 1) for c in hov), horizontal=True)
    t["field_edge_top"] = darker(t["field_edge"], 118)
    t["tip"] = t["menu"]
    return t


# ---- Глифы (PNG для QSS image:url) -----------------------------------------------------------
GLYPHS: dict[str, tuple[str, str, int, float]] = {
    # имя: (иконка, цвет-токен или #hex, логический размер, толщина)
    "arrow_down": ("arrow_down", "dim", 10, 1.7), "arrow_up": ("arrow_up", "dim", 10, 1.7),
    "arrow_left": ("arrow_left", "text", 12, 1.8), "arrow_right": ("arrow_right", "text", 12, 1.8),
    "arrow_down_dis": ("arrow_down", "faint", 10, 1.7), "arrow_up_dis": ("arrow_up", "faint", 10, 1.7),
    "check_w": ("check", "#ffffff", 12, 2.1), "check_dis": ("check", "faint", 12, 2.1),
    "dash_w": ("dash", "#ffffff", 12, 2.3), "dot_w": ("dot", "#ffffff", 12, 1.0),
    "dot_dis": ("dot", "faint", 12, 1.0),
}


def ensure_glyphs(t: dict[str, str]) -> dict[str, str]:
    """PNG на 1x/2x/3x (Qt сам выбирает @2x/@3x под devicePixelRatio) в общей временной папке."""
    colors = {k: (t.get(v, v)) for k, (_, v, _, _) in GLYPHS.items()}
    key = hashlib.md5(json.dumps(colors, sort_keys=True).encode()).hexdigest()[:10]
    folder = storage.temp_dir() / f"glyphs-{key}"
    folder.mkdir(exist_ok=True)
    out: dict[str, str] = {}
    for name, (icon, color, size, pen) in GLYPHS.items():
        for scale, suffix in ((1, ""), (2, "@2x"), (3, "@3x")):
            path = folder / f"{name}{suffix}.png"
            if not path.exists():
                img = icons.icon_image(icon, size, qcolor(t.get(color, color)), scale, pen)
                img.setDevicePixelRatio(1.0)
                img.save(str(path), "PNG")
        out[f"gl_{name}"] = f'url("{(folder / (name + ".png")).as_posix()}")'
    return out


# ---- QSS-шаблон (один на обе темы) ------------------------------------------------------------
QSS = Template(r"""
QWidget { color: $text; selection-background-color: $hl; selection-color: $hl_text; outline: 0; }
QWidget:disabled { color: $faint; }
QLabel { background: transparent; }
QLabel[role="title"] { font-size: 20pt; font-weight: 600; }
QLabel[role="subtitle"], QLabel[role="dim"] { color: $dim; }
QLabel[role="section"] { color: $dim; font-weight: 600; padding-top: 8px; }
QLabel[role="link"] { color: $accent; }
QLabel[role="hint"] { color: $accent; }
QFrame[role="separator"] { background: $sep; border: none; max-height: 1px; min-height: 1px; }
QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }

/* ---- Поля ввода ---- */
QLineEdit, QTextEdit, QPlainTextEdit {
  background: $field; border: 1px solid $field_edge; border-top-color: $field_edge_top;
  border-radius: 3px; padding: 3px 6px; selection-background-color: $hl; selection-color: $hl_text;
}
QLineEdit { min-height: 20px; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus { border: 1px solid $accent; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled { background: $dis_bg; border-color: $dis_edge; color: $faint; }
QLineEdit[role="search"] { padding-left: 26px; padding-right: 24px; border-radius: 12px; min-height: 22px; }
QLineEdit[invalid="true"] { border: 1px solid $danger; }

/* ---- Кнопки ---- */
QPushButton, QToolButton[role="glass"] {
  background: $g_ctl; border: 1px solid $ctl_edge; border-radius: 4px; padding: 4px 16px; min-height: 22px; min-width: 64px;
}
QPushButton:hover, QToolButton[role="glass"]:hover { background: $g_hov; border-color: $h_edge; }
QPushButton:pressed, QToolButton[role="glass"]:pressed { background: $g_prs; border-color: $p_edge; padding-top: 5px; padding-bottom: 3px; }
QPushButton:focus { border-color: $accent; }
QPushButton:disabled { background: $g_dis; border-color: $dis_edge; color: $faint; }
QPushButton[role="accent"], QPushButton:default {
  background: $g_acc; border-color: $acc_edge; color: #ffffff; font-weight: 600;
}
QPushButton[role="accent"]:hover, QPushButton:default:hover { background: $g_acc_hov; border-color: $glow; }
QPushButton[role="accent"]:pressed, QPushButton:default:pressed { background: $g_acc_prs; }
QPushButton[role="accent"]:disabled { background: $g_dis; border-color: $dis_edge; color: $faint; }
QPushButton[role="danger"] { background: $g_dng; border-color: $dng_edge; color: #ffffff; font-weight: 600; }
QPushButton[role="danger"]:hover { background: $g_dng_hov; }
QPushButton[role="danger"]:pressed { background: $g_dng_prs; }
QPushButton[role="flat"] { background: transparent; border: 1px solid transparent; }
QPushButton[role="flat"]:hover { background: $g_selh; border: 1px solid $sh_edge; }
QPushButton[role="flat"]:pressed { background: $g_sel; border: 1px solid $sel_edge; }
/* AeroButton рисует себя сам: QSS-отступы и min-размеры не должны раздувать его (иначе setFixedSize не работает) */
AeroButton, AeroButton:hover, AeroButton:pressed, AeroButton:focus, AeroButton:disabled { min-width: 0; min-height: 0; padding: 0; }
QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 3px; }
QToolButton:hover { background: $g_selh; border: 1px solid $sh_edge; }
QToolButton:pressed, QToolButton:checked { background: $g_sel; border: 1px solid $sel_edge; }
QToolButton::menu-indicator { image: none; }

/* ---- Флажки и радио ---- */
QCheckBox, QRadioButton { spacing: 8px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; background: $g_ctl; border: 1px solid $ctl_edge; }
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { background: $g_hov; border-color: $h_edge; }
QCheckBox::indicator:pressed, QRadioButton::indicator:pressed { background: $g_prs; border-color: $p_edge; }
QCheckBox::indicator:focus, QRadioButton::indicator:focus { border-color: $accent; }
QCheckBox::indicator:checked { background: $g_acc; border-color: $acc_edge; image: $gl_check_w; }
QCheckBox::indicator:indeterminate { background: $g_acc; border-color: $acc_edge; image: $gl_dash_w; }
QRadioButton::indicator:checked { background: $g_acc; border-color: $acc_edge; image: $gl_dot_w; }
QCheckBox::indicator:checked:hover, QCheckBox::indicator:indeterminate:hover, QRadioButton::indicator:checked:hover { background: $g_acc_hov; border-color: $glow; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: $g_dis; border-color: $dis_edge; }
QCheckBox::indicator:checked:disabled { image: $gl_check_dis; }
QRadioButton::indicator:checked:disabled { image: $gl_dot_dis; }

/* ---- Выпадающий список ---- */
QComboBox {
  background: $field; border: 1px solid $field_edge; border-top-color: $field_edge_top; border-radius: 3px;
  padding: 2px 28px 2px 6px; min-height: 22px; combobox-popup: 0;
}
QComboBox:hover { border-color: $h_edge; }
QComboBox:focus, QComboBox:on { border-color: $accent; }
QComboBox:disabled { background: $dis_bg; border-color: $dis_edge; color: $faint; }
QComboBox::drop-down {
  subcontrol-origin: padding; subcontrol-position: top right; width: 22px; background: $g_ctl;
  border-left: 1px solid $ctl_edge; border-top-right-radius: 2px; border-bottom-right-radius: 2px;
}
QComboBox::drop-down:hover { background: $g_hov; }
QComboBox::drop-down:on { background: $g_prs; }
QComboBox::down-arrow { image: $gl_arrow_down; width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: $gl_arrow_down_dis; }
QComboBox QLineEdit, QComboBox QLineEdit:focus { background: transparent; border: none; padding: 0; min-height: 0; }
QListView#comboList { background: transparent; border: none; padding: 4px; outline: 0; }
QListView#comboList::item { min-height: 22px; padding: 2px 8px; border: 1px solid transparent; border-radius: 3px; }

/* ---- Спины, время, дата ---- */
QAbstractSpinBox {
  background: $field; border: 1px solid $field_edge; border-top-color: $field_edge_top; border-radius: 3px;
  padding: 2px 24px 2px 6px; min-height: 22px;
}
QAbstractSpinBox:hover { border-color: $h_edge; }
QAbstractSpinBox:focus { border-color: $accent; }
QAbstractSpinBox:disabled { background: $dis_bg; border-color: $dis_edge; color: $faint; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
  subcontrol-origin: border; width: 20px; background: $g_ctl; border-left: 1px solid $ctl_edge;
}
QAbstractSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 3px; border-bottom: 1px solid $ctl_edge; }
QAbstractSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 3px; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: $g_hov; }
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed { background: $g_prs; }
QAbstractSpinBox::up-arrow { image: $gl_arrow_up; width: 10px; height: 10px; }
QAbstractSpinBox::down-arrow { image: $gl_arrow_down; width: 10px; height: 10px; }
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off { image: $gl_arrow_up_dis; }
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off { image: $gl_arrow_down_dis; }
QDateEdit::drop-down {
  subcontrol-origin: border; subcontrol-position: top right; width: 22px; background: $g_ctl;
  border-left: 1px solid $ctl_edge; border-top-right-radius: 3px; border-bottom-right-radius: 3px;
}
QDateEdit::drop-down:hover { background: $g_hov; }
QDateEdit::down-arrow { image: $gl_arrow_down; width: 10px; height: 10px; }

/* ---- Календарь ---- */
QCalendarWidget { background: $menu; border: 1px solid $menu_edge; border-radius: 8px; }
QCalendarWidget QWidget#qt_calendar_navigationbar { background: $g_ctl; border: none; border-top-left-radius: 8px; border-top-right-radius: 8px; border-bottom: 1px solid $ctl_edge; }
QCalendarWidget QToolButton { background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; min-height: 22px; color: $text; font-weight: 600; }
QCalendarWidget QToolButton:hover { background: $g_selh; border-color: $sh_edge; }
QCalendarWidget QToolButton:pressed { background: $g_sel; border-color: $sel_edge; }
QCalendarWidget QToolButton::menu-indicator { image: none; }
QCalendarWidget QToolButton#qt_calendar_prevmonth { qproperty-icon: none; image: $gl_arrow_left; min-width: 24px; }
QCalendarWidget QToolButton#qt_calendar_nextmonth { qproperty-icon: none; image: $gl_arrow_right; min-width: 24px; }
QCalendarWidget QSpinBox { background: $field; border: 1px solid $field_edge; border-radius: 3px; padding: 0 20px 0 4px; min-height: 20px; }
QCalendarWidget QAbstractItemView:enabled { background: transparent; color: $text; selection-background-color: transparent; selection-color: $text; outline: 0; }
QCalendarWidget QAbstractItemView:disabled { color: $faint; }
QCalendarWidget QHeaderView::section { background: transparent; color: $dim; border: none; }

/* ---- Полосы прокрутки ---- */
QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0; }
QScrollBar::handle:vertical { background: $g_handle_v; border: 1px solid $ctl_edge; border-radius: 3px; margin: 2px 3px; min-height: 32px; }
QScrollBar::handle:horizontal { background: $g_ctl; border: 1px solid $ctl_edge; border-radius: 3px; margin: 3px 2px; min-width: 32px; }
QScrollBar::handle:vertical:hover { background: $g_handle_v_hov; border-color: $h_edge; margin: 2px 1px; }
QScrollBar::handle:horizontal:hover { background: $g_hov; border-color: $h_edge; margin: 1px 2px; }
QScrollBar::handle:vertical:pressed, QScrollBar::handle:horizontal:pressed { background: $g_prs; border-color: $p_edge; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; background: none; border: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QAbstractScrollArea::corner { background: transparent; border: none; }

/* ---- Списки ---- */
QAbstractItemView { background: transparent; border: none; outline: 0; alternate-background-color: transparent; }
QListView::item, QTreeView::item { border: 1px solid transparent; border-radius: 4px; padding: 2px 6px; }
QListView::item:hover, QTreeView::item:hover { background: $g_selh; border: 1px solid $sh_edge; }
QListView::item:selected, QTreeView::item:selected { background: $g_sel; border: 1px solid $sel_edge; color: $sel_text; }

/* ---- Меню ---- */
QMenu { background: $menu; border: 1px solid $menu_edge; border-radius: 8px; padding: 4px; margin: 12px; }
QMenu::item { padding: 5px 28px 5px 26px; border: 1px solid transparent; border-radius: 3px; margin: 1px 2px; }
QMenu::item:selected { background: $g_sel; border: 1px solid $sel_edge; color: $sel_text; }
QMenu::item:disabled { color: $faint; background: transparent; border-color: transparent; }
QMenu::separator { height: 1px; background: $sep; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; margin-left: 6px; }
QMenu::indicator:checked { image: $gl_check_dis; }
QMenu::icon { margin-left: 6px; }
QMenu::right-arrow { image: $gl_arrow_right; width: 10px; height: 10px; margin-right: 6px; }

/* ---- Прочее ---- */
QGroupBox { background: $panel; border: 1px solid $panel_edge; border-radius: 8px; margin-top: 14px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; color: $dim; font-weight: 600; }
QProgressBar { background: $field; border: 1px solid $field_edge; border-radius: 4px; text-align: center; min-height: 14px; }
QProgressBar::chunk { background: $g_acc; border: 1px solid $acc_edge; border-radius: 3px; }
QTabBar::tab { background: $g_ctl; border: 1px solid $ctl_edge; border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 5px 14px; margin-right: 2px; }
QTabBar::tab:hover { background: $g_hov; border-color: $h_edge; }
QTabBar::tab:selected { background: $g_acc; border-color: $acc_edge; color: #ffffff; }
QSplitter::handle { background: $sep; }
QSplitter::handle:hover { background: $glow; }
""")


def build_qss(t: dict[str, str]) -> str:
    return QSS.safe_substitute({**t, **ensure_glyphs(t)})


# ---- Палитра -------------------------------------------------------------------------------
def build_palette(t: dict[str, str]) -> QPalette:
    p = QPalette()
    for grp in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        dis = grp == QPalette.Disabled
        text = qcolor(t["faint"] if dis else t["text"])
        roles = {
            QPalette.Window: t["bg2"], QPalette.WindowText: text, QPalette.Base: t["field"],
            QPalette.AlternateBase: mix(t["field"], t["bg2"], .15), QPalette.Text: text,
            QPalette.Button: t["ctl_lo"], QPalette.ButtonText: text,
            QPalette.Highlight: t["hl"], QPalette.HighlightedText: t["hl_text"],
            QPalette.ToolTipBase: mix(t["menu"], "#000000", 0), QPalette.ToolTipText: t["text"],
            QPalette.PlaceholderText: t["faint"], QPalette.Link: t["accent"],
            QPalette.LinkVisited: t["accent"], QPalette.BrightText: "#ffffff",
            QPalette.Light: t["ctl_hi"], QPalette.Midlight: mix(t["ctl_hi"], t["ctl_lo"], .4),
            QPalette.Mid: mix(t["ctl_lo"], t["ctl_edge"], .5), QPalette.Dark: t["ctl_edge"],
            QPalette.Shadow: "#000000",
        }
        for role, c in roles.items():
            p.setColor(grp, role, c if isinstance(c, QColor) else qcolor(c))
    return p


# ---- Состояние темы и подписчики ---------------------------------------------------------------
_name = "light"
_tokens: dict[str, str] = make_tokens("light")
_subs: list[Callable[[], None]] = []


def name() -> str:
    return _name


def tokens() -> dict[str, str]:
    return _tokens


def col(key: str) -> QColor:
    return qcolor(_tokens[key])


def subscribe(cb: Callable[[], None]) -> None:
    if cb not in _subs:
        _subs.append(cb)


def unsubscribe(cb: Callable[[], None]) -> None:
    if cb in _subs:
        _subs.remove(cb)


def init_app(app: QApplication) -> None:
    """Вызывать сразу после создания QApplication."""
    app.setStyle("Fusion")
    family = S.FONT if sys.platform == "win32" else QFontDatabase.systemFont(QFontDatabase.GeneralFont).family()
    font = QFont(family, S.FONT_PT)
    font.setFamilies([family, "sans-serif"])
    app.setFont(font)
    polisher = PopupPolisher(app)
    app.installEventFilter(polisher)
    app.setProperty("_aero_polisher", polisher)


def apply_theme(app: QApplication, theme_name: str) -> None:
    global _name, _tokens
    _name = theme_name if theme_name in BASE else "light"
    _tokens = make_tokens(_name)
    app.setPalette(build_palette(_tokens))
    app.setStyleSheet(build_qss(_tokens))
    for cb in list(_subs):
        cb()


# ---- Рисование «стекла» --------------------------------------------------------------------------
def paint_window_background(p: QPainter, rect: QRectF) -> None:
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    g.setColorAt(0, col("bg1")); g.setColorAt(1, col("bg2"))
    p.fillRect(rect, g)
    glare = QRadialGradient(QPointF(rect.width() * .22, rect.top() - rect.height() * .08), rect.width() * .75)
    glare.setColorAt(0, col("glare")); glare.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(rect, glare)
    swoosh = QPainterPath(QPointF(rect.left(), rect.bottom() * .72))
    swoosh.cubicTo(rect.width() * .35, rect.bottom() * .55, rect.width() * .62, rect.bottom() * .95,
                   rect.right(), rect.bottom() * .62)
    swoosh.lineTo(rect.right(), rect.bottom()); swoosh.lineTo(rect.left(), rect.bottom()); swoosh.closeSubpath()
    c = col("glare"); c.setAlpha(max(10, c.alpha() // 6))
    p.setPen(Qt.NoPen); p.setBrush(c); p.setRenderHint(QPainter.Antialiasing); p.drawPath(swoosh)


def paint_glass_panel(p: QPainter, rect: QRectF, radius: float = S.R_PANEL, sheen: bool = True,
                      fill: Optional[QColor] = None) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    outer = rect.adjusted(.5, .5, -.5, -.5)
    path = QPainterPath(); path.addRoundedRect(outer, radius, radius)
    p.setPen(Qt.NoPen); p.setBrush(fill if fill is not None else col("panel")); p.drawPath(path)
    if sheen:
        p.setClipPath(path)
        g = QLinearGradient(0, rect.top(), 0, rect.top() + rect.height() * .5)
        g.setColorAt(0, col("sheen")); g.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(g); p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), rect.height() * .5))
        p.setClipping(False)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(col("panel_edge"), 1)); p.drawPath(path)
    inner = QPainterPath(); inner.addRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius - 1, radius - 1)
    p.setPen(QPen(col("panel_in"), 1)); p.drawPath(inner)
    p.restore()


def paint_shadow(p: QPainter, body: QRectF, radius: float = S.R_PANEL, spread: int = S.SHADOW - 3,
                 dy: int = 3) -> None:
    """Мягкая тень, нарисованная вручную внутри окна. QGraphicsDropShadowEffect на прозрачных
    top-level окнах выходит за их границы и ломает UpdateLayeredWindowIndirect (окно перестаёт обновляться)."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath(); clip.setFillRule(Qt.OddEvenFill)
    clip.addRect(body.adjusted(-spread - 4, -spread - 4, spread + 4, spread + dy + 4))
    hole = QPainterPath(); hole.addRoundedRect(body, radius, radius)
    clip.addPath(hole)
    p.setClipPath(clip)
    base = col("shadow")
    p.setPen(Qt.NoPen)
    for i in range(spread, 0, -1):
        k = (spread - i + 1) / spread
        c = QColor(base); c.setAlpha(int(base.alpha() * k * k * 0.18))
        p.setBrush(c)
        p.drawRoundedRect(body.adjusted(-i, -i + dy, i, i + dy), radius + i, radius + i)
    p.restore()


def paint_control(p: QPainter, rect: QRectF, state: str = "ctl", radius: float = S.R_CTL,
                  glow_k: float = 0.0) -> None:
    """Стеклянный контрол: градиент с разрывом на 50% + внешняя тёмная и внутренняя светлая рамки.
    state: ctl | acc | dng | sel. glow_k (0..1) — плавное «наведение» (анимируется снаружи)."""
    t = _tokens
    if state in ("acc", "dng"):
        base = t["accent" if state == "acc" else "danger"]
        raw = [lighter(base, 150), lighter(base, 116), darker(base, 112), base]
        stops = [qcolor(mix(c, "#ffffff", .18 * glow_k)) for c in raw]
        edge = darker(base, 175)
    elif state == "sel":
        stops = [qcolor(t[k]) for k in ("sel_t1", "sel_t2", "sel_b1", "sel_b2")]
        edge = t["sel_edge"]
    else:
        hi, lo = t["ctl_hi"], t["ctl_lo"]
        raw = [hi, mix(hi, lo, .3), lo, mix(lo, hi, .3)]
        stops = [qcolor(mix(c, t["glow"], .33 * glow_k)) for c in raw]
        edge = mix(t["ctl_edge"], t["glow"], .75 * glow_k)
    g = QLinearGradient(0, rect.top(), 0, rect.bottom())
    for pos, c in zip((0, .49, .5, 1), stops):
        g.setColorAt(pos, c)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(g)
    p.setPen(QPen(qcolor(edge), 1))
    p.drawRoundedRect(rect.adjusted(.5, .5, -.5, -.5), radius, radius)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(col("ctl_in"), 1))
    p.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), max(0, radius - 1), max(0, radius - 1))
    p.restore()


# ---- Windows: DWM, размытие -----------------------------------------------------------------------
def _colorref(c: QColor) -> int:
    return c.red() | (c.green() << 8) | (c.blue() << 16)


def apply_titlebar(widget: QWidget, theme_name: Optional[str] = None) -> None:
    """Цвет заголовка нативной рамки под тему. Тихий фолбэк на старых системах/не-Windows."""
    try:
        import ctypes
        n = theme_name or _name
        t = _tokens if n == _name else make_tokens(n)
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi  # type: ignore[attr-defined]
        dark = ctypes.c_int(1 if n == "dark" else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новый/старый номер)
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(dark), ctypes.sizeof(dark)) == 0:
                break
        for attr, key in ((35, "caption"), (36, "caption_text"), (34, "caption")):  # Win11+
            v = ctypes.c_int(_colorref(qcolor(t[key])))
            dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


# ---- Всплывающие окна: скругление без квадратных артефактов ----------------------------------------
class PopupPolisher(QObject):
    """Делает любые QMenu и календарь-popup прозрачными frameless-окнами, чтобы
    скруглённый QSS-фон рисовался без квадратных углов. Тень рисуют сами окна (paint_shadow)."""

    TRANSLUCENT = ("QCalendarPopup",)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if ev.type() == QEvent.ToolTip:      # подсказок в приложении нет вообще
            return True
        if ev.type() != QEvent.Polish or not isinstance(obj, QWidget) or not obj.isWindow():
            return False
        if obj.property("_aero_popup") or not (obj.inherits("QMenu") or obj.metaObject().className() in self.TRANSLUCENT):
            return False
        obj.setProperty("_aero_popup", True)
        obj.setWindowFlags(obj.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        obj.setAttribute(Qt.WA_TranslucentBackground, True)
        return False
