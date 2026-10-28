"""Shared visual language for the desktop workspace and dialogs."""
import os
import re
from pathlib import Path
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase, QPalette, QColor, QIcon, QPixmap, QPainter
from .controls import FLUENT_MODE

INK = '#2B2622'
MUTED = '#8A8178'
ACCENT = '#E8735A'
ACCENT_DARK = '#C9563F'
ACCENT_SOFT = '#FFF0EA'
BORDER = '#EDE3D7'
CANVAS = '#FAF7F2'

STYLE = '''
QLabel { color:#2B2622; font-size:14px; }
QMainWindow, QDialog { background:#FAF7F2; }
QWidget#sidebar { background:#FFFDF9; border:0; border-right:1px solid #F3EADF; }
QLabel#brand { color:#C9563F; font-size:21px; font-weight:700; }
QLabel#eyebrow { color:#A3998D; font-size:11px; font-weight:600; }
QLabel#pageTitle { color:#2B2622; font-size:22px; font-weight:700; }
QLabel#subtitle { color:#8A8178; font-size:13px; }
QLabel#sectionTitle { color:#3A322C; font-size:16px; font-weight:600; padding:20px 0 8px; }
QPushButton { background:#FFFFFF; border:1px solid #EDE3D7; border-radius:10px; padding:9px 16px; color:#5A5048; }
QPushButton:hover { background:#FFF6F1; border-color:#F3C9BA; color:#D65F47; }
QPushButton:focus { border-color:#E8735A; }
QPushButton:pressed { background:#FFEEE7; }
QPushButton:disabled { color:#B9AEA2; border-color:#F1E8DE; background:#FAF6F1; }
QPushButton[variant="primary"] { background:#C9563F; color:white; border:1px solid #C9563F; font-weight:600; }
QPushButton[variant="primary"]:hover { background:#B94A36; border-color:#B94A36; }
QPushButton[variant="primary"]:disabled { background:#E7A595; border-color:#E7A595; }
QPushButton[variant="nav"] { text-align:left; border:0; background:transparent; padding:13px 16px; font-weight:600; color:#8A8178; }
QPushButton[variant="nav"]:hover { background:#FFF6F1; color:#D65F47; }
QPushButton[variant="nav"]:checked { background:#FFF0EA; color:#D65F47; }
QLineEdit, QTextEdit, QTextBrowser, QDateTimeEdit, QComboBox, QSpinBox {
 background:white; border:1px solid #EDE3D7; border-radius:10px; padding:9px; selection-background-color:#FFE2D8; selection-color:#5A2A20;
}
QLineEdit:focus, QTextEdit:focus, QDateTimeEdit:focus, QComboBox:focus { border-color:#E8735A; }
QTextBrowser#history { border:0; background:transparent; padding:0; }
QTextEdit#composer { border:0; background:transparent; padding:6px; }
QComboBox#nativeCombo { padding-right:24px; min-height:20px; }
QComboBox#nativeCombo::drop-down { border:0; width:24px; }
QComboBox#nativeCombo QAbstractItemView::item { min-height:32px; padding:4px 10px; border-radius:6px; }
QComboBox#nativeCombo QAbstractItemView { border:1px solid #EDE3D7; border-radius:10px; outline:0; background:white; selection-background-color:#FFF0EA; selection-color:#D65F47; padding:5px; }
QListWidget#taskList { background:transparent; border:0; padding:0; outline:0; }
QListWidget#taskList::item { border:0; border-radius:14px; padding:16px; margin:5px 2px; background:#FFFFFF; }
QListWidget#taskList::item:hover { background:#FFFBF7; }
QListWidget#taskList::item:selected { background:#FFF4ED; color:#4A2A22; }
QScrollArea { border:0; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { border:0; background:transparent; width:6px; margin:4px 0; }
QScrollBar::handle:vertical { background:#E7DCD0; border-radius:4px; min-height:28px; }
QScrollBar::handle:vertical:hover { background:#D9CCBD; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QCheckBox { spacing:9px; padding:5px 0; }
QCheckBox::indicator { width:17px; height:17px; }
QStatusBar { color:#9A8F83; background:#FAF7F2; font-size:12px; border-top:1px solid #F1E8DC; }
QStatusBar::item { border:0; }
QToolTip { background:#3A322C; color:#FFF9F3; border:0; padding:8px; border-radius:6px; }
QMenu { background:white; border:1px solid #F0E4D8; padding:6px; border-radius:10px; }
QMenu::item { padding:8px 24px; border-radius:6px; }
QMenu::item:selected { background:#FFF0EA; color:#D65F47; }
QWidget#draftCard { background:#FFF6F1; border:1px solid #F6DCD2; border-radius:14px; }
'''


def apply_theme(app):
    app.setStyle('Fusion')
    # Offscreen Qt may not discover installed system fonts automatically.
    if not QFontDatabase().families() and os.name == 'nt':
        font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    font = QFont('Microsoft YaHei UI' if os.name == 'nt' else 'Sans Serif')
    font.setPixelSize(14)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(CANVAS))
    palette.setColor(QPalette.Base, QColor('#ffffff'))
    palette.setColor(QPalette.Text, QColor(INK))
    palette.setColor(QPalette.WindowText, QColor(INK))
    palette.setColor(QPalette.PlaceholderText, QColor('#A89D91'))
    app.setPalette(palette)
    if FLUENT_MODE:
        from .fluent import configure_fluent
        configure_fluent()
        # Keep project page/shell styles; let Fluent own its component styles.
        rules = re.findall(r'([^{}]+)\{([^{}]*)\}', STYLE)
        blocked = ('QComboBox', 'QSpinBox', 'QCheckBox', 'QPushButton')
        shell = ''.join(selector + '{' + body + '}' for selector, body in rules
                        if (not any(name in selector for name in blocked) and selector.strip() != 'QWidget') or 'variant="nav"' in selector)
        shell += ('QDateTimeEdit {background:#FFFFFF;border:1px solid #EDE3D7;border-radius:10px;padding:8px;min-height:22px;}'
                  'QDateTimeEdit:focus {border-color:#E8735A;}'
                  'QDateTimeEdit::drop-down {width:26px;border:0;}'
                  'QCalendarWidget QWidget {background:#FFFFFF;color:#2B2622;}'
                  'QDialog QDialogButtonBox QPushButton {min-height:32px;padding:4px 16px;border-radius:10px;}'
                  'QLabel#versionLabel {color:#B9AEA2;font-size:12px;}')
        app.setStyleSheet(shell)
    else:
        app.setStyleSheet(STYLE)


def application_icon():
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ACCENT_DARK))
    painter.drawRoundedRect(1, 1, 62, 62, 16, 16)
    painter.setBrush(QColor('#ffffff'))
    painter.drawEllipse(20, 31, 25, 21)
    for x, y, width, height in ((12, 24, 10, 12), (23, 14, 10, 13), (36, 15, 10, 13), (46, 26, 9, 11)):
        painter.drawEllipse(x, y, width, height)
    painter.end()
    return QIcon(canvas)


def add_soft_shadow(widget):
    from PyQt5.QtWidgets import QGraphicsDropShadowEffect
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(30)
    effect.setOffset(0, 6)
    effect.setColor(QColor(120, 82, 60, 24))
    widget.setGraphicsEffect(effect)
