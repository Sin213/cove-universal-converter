"""Centralized Cove design tokens + global stylesheet.

The palette mirrors the design bundle (`Cove Universal Converter.html`):
dark navy background with a teal accent, Geist-family fonts (system fallbacks
when Geist isn't installed).
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

# ---- Palette ---------------------------------------------------------------

ACCENT       = "#50e6cf"
ACCENT_SOFT  = "rgba(80, 230, 207, 0.14)"
ACCENT_RING  = "rgba(80, 230, 207, 0.35)"

BG           = "#0b0b10"
SURFACE      = "#13131b"
SURFACE_2    = "#181822"
SURFACE_3    = "#1f1f2b"

BORDER       = "rgba(255, 255, 255, 0.06)"
BORDER_STRONG = "rgba(255, 255, 255, 0.10)"

TEXT         = "#ececf1"
TEXT_DIM     = "#9a9aae"
TEXT_FAINT   = "#6b6b80"

GOOD         = "#3ddc97"
WARN         = "#ffb454"
DANGER       = "#ff6b6b"

# Category tints (must match the format-badge colors)
CAT_VIDEO    = "#5ab7ff"   # blue
CAT_AUDIO    = "#ff6bd6"   # pink
CAT_IMAGE    = ACCENT      # teal
CAT_DOC      = GOOD        # green
CAT_SUBTITLE = "#c5b1ff"   # lavender
CAT_SHEET    = "#5ee9b5"   # mint
CAT_ARCHIVE  = "#ffb454"   # warm gold
CAT_DATA     = "#7c8cff"   # indigo


# ---- Font helpers ----------------------------------------------------------

SANS_STACK = "'Geist', 'Inter', 'Segoe UI', 'SF Pro Text', system-ui, sans-serif"
MONO_STACK = "'Geist Mono', 'JetBrains Mono', 'Fira Code', ui-monospace, monospace"


def _pick_sans() -> str:
    families = set(QFontDatabase.families())
    for name in ("Geist", "Inter", "Segoe UI", "SF Pro Text"):
        if name in families:
            return name
    return ""  # let Qt fall back


def _pick_mono() -> str:
    families = set(QFontDatabase.families())
    for name in ("Geist Mono", "JetBrains Mono", "Fira Code", "Cascadia Mono", "Consolas"):
        if name in families:
            return name
    return ""


# ---- Global stylesheet -----------------------------------------------------

def _stylesheet() -> str:
    return f"""
/* ===== Base ===== */
QWidget {{ color: {TEXT}; font-family: {SANS_STACK}; font-size: 13px; }}
QToolTip {{ color: {TEXT}; background: #0f0f17; border: 1px solid {BORDER_STRONG}; padding: 4px 8px; border-radius: 6px; }}

/* ===== Window chrome (frameless) ===== */
#chromeRoot {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
#chromeContent {{ background: transparent; }}

/* ===== Title bar ===== */
#titleBar {{
    background: transparent;
    border-bottom: 1px solid {BORDER};
}}
/* The Cove icon stands on its own — no surrounding box. */
#tbIcon {{ background: transparent; border: none; }}
#tbTitle {{ color: {TEXT}; font-size: 13px; font-weight: 500; letter-spacing: -0.005em; }}
#tbVersion {{
    color: {ACCENT};
    background: {ACCENT_SOFT};
    border: 1px solid {ACCENT_RING};
    border-radius: 5px;
    padding: 2px 7px;
    font-family: {MONO_STACK};
    font-size: 10px;
    letter-spacing: 0.02em;
}}
QToolButton#tbBtn, QToolButton#tbBtnClose {{
    background: transparent;
    border: none;
    color: {TEXT};
    border-radius: 6px;
    padding: 0;
}}
QToolButton#tbBtn:hover {{ background: rgba(255, 255, 255, 0.10); color: #ffffff; }}
QToolButton#tbBtnClose:hover {{ background: #c93b3b; color: #ffffff; }}

/* ===== Drop zone ===== */
QFrame#dropZone {{
    border: 2px dashed rgba(255, 255, 255, 0.14);
    border-radius: 14px;
    background: rgba(255, 255, 255, 0.01);
}}
QFrame#dropZone:hover {{
    border: 2px dashed {ACCENT_RING};
    background: rgba(80, 230, 207, 0.025);
}}
QFrame#dropZone[dragActive="true"] {{
    border: 2px solid {ACCENT};
    background: {ACCENT_SOFT};
}}
QLabel#dzTitle {{ color: {TEXT}; font-size: 18px; font-weight: 600; letter-spacing: -0.015em; }}
QLabel#dzSub {{ color: {TEXT_FAINT}; font-family: {MONO_STACK}; font-size: 12px; }}
QFrame#dzArt {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {SURFACE_2}, stop:1 {SURFACE});
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
}}
QToolButton#dzInfo {{
    color: {TEXT};
    background: {SURFACE_2};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
}}
QToolButton#dzInfo:hover {{
    color: {ACCENT};
    background: {ACCENT_SOFT};
    border: 1px solid {ACCENT_RING};
}}

/* ===== Queue (table) ===== */
QFrame#queue {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QTableWidget {{
    background: transparent;
    border: none;
    gridline-color: transparent;
    selection-background-color: rgba(255, 255, 255, 0.03);
    selection-color: {TEXT};
    outline: 0;
}}
QTableWidget::item {{ padding: 8px 4px; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item:selected {{ background: rgba(80, 230, 207, 0.05); color: {TEXT}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: rgba(255, 255, 255, 0.025);
    color: {TEXT_FAINT};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 10px 12px;
    font-family: {MONO_STACK};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}}

/* ===== Format badge + status chip ===== */
QLabel#fbadge {{
    border-radius: 6px;
    font-family: {MONO_STACK};
    font-size: 9px;
    font-weight: 700;
    padding: 0 4px;
    qproperty-alignment: AlignCenter;
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QLabel#fbadge[cat="video"]    {{ color: {CAT_VIDEO};    border: 1px solid rgba(90, 183, 255, 0.25); background: rgba(90, 183, 255, 0.08); }}
QLabel#fbadge[cat="audio"]    {{ color: {CAT_AUDIO};    border: 1px solid rgba(255, 107, 214, 0.25); background: rgba(255, 107, 214, 0.08); }}
QLabel#fbadge[cat="image"]    {{ color: {ACCENT};       border: 1px solid {ACCENT_RING};             background: {ACCENT_SOFT}; }}
QLabel#fbadge[cat="doc"]      {{ color: {GOOD};         border: 1px solid rgba(61, 220, 151, 0.25);  background: rgba(61, 220, 151, 0.08); }}
QLabel#fbadge[cat="subtitle"] {{ color: {CAT_SUBTITLE}; border: 1px solid rgba(197, 177, 255, 0.25); background: rgba(197, 177, 255, 0.08); }}
QLabel#fbadge[cat="sheet"]    {{ color: {CAT_SHEET};    border: 1px solid rgba(94, 233, 181, 0.25);  background: rgba(94, 233, 181, 0.08); }}
QLabel#fbadge[cat="archive"]  {{ color: {CAT_ARCHIVE};  border: 1px solid rgba(255, 180, 84, 0.25);  background: rgba(255, 180, 84, 0.08); }}
QLabel#fbadge[cat="data"]     {{ color: {CAT_DATA};     border: 1px solid rgba(124, 140, 255, 0.25); background: rgba(124, 140, 255, 0.08); }}

QLabel#statChip {{
    border-radius: 9px;
    font-family: {MONO_STACK};
    font-size: 10px;
    font-weight: 600;
    padding: 2px 9px;
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid {BORDER};
    color: {TEXT_DIM};
    qproperty-alignment: AlignCenter;
}}
QLabel#statChip[state="processing"] {{ color: {ACCENT}; background: {ACCENT_SOFT}; border: 1px solid {ACCENT_RING}; }}
QLabel#statChip[state="done"]       {{ color: {GOOD};   background: rgba(61, 220, 151, 0.08); border: 1px solid rgba(61, 220, 151, 0.25); }}
QLabel#statChip[state="failed"]     {{ color: {DANGER}; background: rgba(255, 107, 107, 0.06); border: 1px solid rgba(255, 107, 107, 0.25); }}
QLabel#statChip[state="queued"]     {{ color: {WARN};   background: rgba(255, 180, 84, 0.06); border: 1px solid rgba(255, 180, 84, 0.25); }}

QLabel#fname {{ color: #ffffff; font-weight: 600; font-size: 13px; }}
QLabel#fsize {{ color: {TEXT_DIM}; font-family: {MONO_STACK}; font-size: 11px; }}

/* ===== Empty state ===== */
QLabel#emptyT {{ color: {TEXT}; font-size: 14px; font-weight: 500; }}
QLabel#emptyS {{ color: {TEXT_DIM}; font-family: {MONO_STACK}; font-size: 11px; }}

/* ===== Combo (target picker) ===== */
QComboBox#qtarget {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 4px 10px 4px 10px;
    color: {TEXT};
    font-family: {MONO_STACK};
    font-size: 12px;
    min-height: 22px;
}}
QComboBox#qtarget:hover {{ background: {SURFACE_3}; border: 1px solid {BORDER_STRONG}; }}
QComboBox#qtarget::drop-down {{ border: none; width: 18px; }}
QComboBox#qtarget::down-arrow {{ image: none; width: 0; }}
QComboBox#qtarget QAbstractItemView {{
    background: #0f0f17;
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
    color: {TEXT};
    padding: 4px;
    font-family: {MONO_STACK};
}}

/* ===== Progress bar ===== */
QProgressBar#qbar {{
    background: rgba(255, 255, 255, 0.05);
    border: none;
    border-radius: 3px;
    text-align: center;
    color: transparent;
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar#qbar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 #7cf0dd);
    border-radius: 3px;
}}
QProgressBar#qbar[state="done"]::chunk {{ background: {GOOD}; }}
QProgressBar#qbar[state="failed"]::chunk {{ background: {DANGER}; }}
QLabel#qpct {{ color: {TEXT_DIM}; font-family: {MONO_STACK}; font-size: 11px; }}

/* ===== Save row ===== */
QLabel#saveLabel {{ color: {TEXT_DIM}; font-size: 13px; }}
QFrame#saveInput {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QFrame#saveInput[focused="true"] {{ background: {SURFACE_2}; border: 1px solid {ACCENT_RING}; }}
QLineEdit#destEdit {{
    background: transparent; border: none;
    color: {TEXT}; padding: 0 4px;
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
}}

/* ===== Buttons ===== */
QPushButton#btnGhost {{
    color: {TEXT_DIM};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
    font-weight: 500;
    min-height: 20px;
}}
QPushButton#btnGhost:hover {{ color: {TEXT}; background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; }}
QPushButton#btnGhost:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}

QPushButton#btnPrimary {{
    color: #06121a;
    background: {ACCENT};
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 20px;
}}
QPushButton#btnPrimary:hover {{ background: #6cf0d8; }}
QPushButton#btnPrimary:disabled {{ background: {SURFACE_3}; color: {TEXT_FAINT}; }}

QToolButton#iconBtn {{
    color: {TEXT_DIM};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px;
    min-width: 22px; min-height: 22px;
}}
QToolButton#iconBtn:hover {{ color: {TEXT}; background: {SURFACE_2}; border: 1px solid {BORDER_STRONG}; }}

QToolButton#clearInput {{
    color: {TEXT_FAINT};
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 0;
    min-width: 18px; max-width: 18px;
    min-height: 18px; max-height: 18px;
}}
QToolButton#clearInput:hover {{ color: {TEXT}; background: rgba(255, 255, 255, 0.06); }}

QLabel#statusMsg {{ color: {TEXT_FAINT}; font-family: {MONO_STACK}; font-size: 11px; }}

/* ===== Dialog (modal) ===== */
QDialog {{ background: #0f0f17; }}
QDialog QWidget {{ background: transparent; }}
QLabel#modalTitle {{ font-size: 15px; font-weight: 600; color: {TEXT}; letter-spacing: -0.01em; }}
QLabel#sectionLabel {{
    color: {TEXT_DIM}; font-family: {MONO_STACK};
    font-size: 10px; font-weight: 600;
    letter-spacing: 0.06em; text-transform: uppercase;
}}
QLabel#categoryLabel {{
    color: {TEXT_FAINT}; font-family: {MONO_STACK};
    font-size: 10px; font-weight: 600;
    letter-spacing: 0.12em; text-transform: uppercase;
}}
QLabel#extChip {{
    color: {TEXT_DIM};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-family: {MONO_STACK}; font-size: 11px;
}}
QLabel#hint {{ color: {TEXT_FAINT}; font-family: {MONO_STACK}; font-size: 11px; }}
QLabel#banner {{
    color: {TEXT_DIM};
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12px;
}}
QFrame#sep {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QFrame#modalHead, QFrame#modalFoot {{ background: transparent; border: none; }}

QToolButton#modalX {{
    color: {TEXT_FAINT};
    background: transparent;
    border: none;
    border-radius: 6px;
}}
QToolButton#modalX:hover {{ color: {TEXT}; background: rgba(255, 255, 255, 0.06); }}

/* ===== Sliders / spinboxes / combos used in dialogs ===== */
QSlider::groove:horizontal {{ background: {SURFACE_3}; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {ACCENT}; width: 14px; height: 14px; margin: -6px 0;
    border-radius: 7px; border: 3px solid rgba(80, 230, 207, 0.18);
}}
QSlider::handle:horizontal:disabled {{ background: #555; border: none; }}

QComboBox#dlgCombo, QSpinBox#dlgSpin {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT};
    padding: 6px 10px;
    font-family: {MONO_STACK}; font-size: 12px;
    min-height: 18px;
}}
QComboBox#dlgCombo:hover, QSpinBox#dlgSpin:hover {{ border: 1px solid {BORDER_STRONG}; background: {SURFACE_2}; }}
QComboBox#dlgCombo::drop-down, QSpinBox#dlgSpin::up-button, QSpinBox#dlgSpin::down-button {{ border: none; width: 16px; }}
QComboBox#dlgCombo QAbstractItemView {{
    background: #0f0f17;
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT_SOFT};
    selection-color: {ACCENT};
    color: {TEXT};
    padding: 4px;
    font-family: {MONO_STACK};
}}

QCheckBox {{ color: {TEXT}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER_STRONG};
    background: {SURFACE};
    border-radius: 4px;
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    image: none;
}}

/* Segmented control */
QFrame#seg {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; }}
QPushButton#segBtn {{
    background: transparent;
    color: {TEXT_DIM};
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
QPushButton#segBtn:hover {{ color: {TEXT}; }}
QPushButton#segBtn[active="true"] {{
    background: {SURFACE_3};
    color: {TEXT};
}}

QLabel#sliderVal {{
    color: {TEXT};
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-family: {MONO_STACK}; font-size: 12px;
    min-width: 40px;
    qproperty-alignment: AlignCenter;
}}

/* ===== Toast ===== */
QFrame#toast {{
    background: #0f0f17;
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
}}
QLabel#toastText {{ color: {TEXT}; font-size: 13px; }}
QLabel#toastPip {{ background: transparent; }}

/* ===== Scroll bars ===== */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: rgba(255, 255, 255, 0.08); border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255, 255, 255, 0.16); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 4px; }}
QScrollBar::handle:horizontal {{ background: rgba(255, 255, 255, 0.08); border-radius: 4px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: rgba(255, 255, 255, 0.16); }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; background: transparent; }}
"""


def apply_global_theme(app: QApplication) -> None:
    """Apply the Cove dark/teal theme to the entire application."""
    app.setStyle("Fusion")
    sans = _pick_sans()
    if sans:
        font = QFont(sans, 10)
        app.setFont(font)
    app.setStyleSheet(_stylesheet())


def category_for(ext: str) -> str:
    e = ext.lower()
    if e in (".mp4", ".mkv", ".webm", ".mov", ".avi", ".gif", ".flv", ".wmv",
            ".m4v", ".mpg", ".mpeg", ".3gp", ".ts"):
        return "video"
    if e in (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".wma", ".aiff"):
        return "audio"
    if e in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif",
            ".ico", ".heic", ".heif"):
        return "image"
    if e in (".srt", ".vtt"):
        return "subtitle"
    if e in (".csv", ".xlsx"):
        return "sheet"
    if e in (".zip", ".tar", ".tgz", ".tar.gz", ".gz"):
        return "archive"
    if e in (".json", ".yaml", ".yml"):
        return "data"
    return "doc"
