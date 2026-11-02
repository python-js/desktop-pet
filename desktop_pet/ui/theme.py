"""Shared visual language for the desktop workspace and dialogs.

颜色、字号与尺寸来自 tokens.py；QSS 由 token 生成，纸白/夜幕切换时重建。
"""
import os
import re
from pathlib import Path
from string import Template

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import QGraphicsDropShadowEffect

from . import tokens as T
from .controls import FLUENT_MODE

INK = T.LIGHT.ink
MUTED = T.LIGHT.ink_3
ACCENT = T.LIGHT.brand
ACCENT_DARK = T.LIGHT.brand_press
ACCENT_SOFT = T.LIGHT.brand_wash
BORDER = T.LIGHT.border
CANVAS = T.LIGHT.bg

_active = T.LIGHT

# 0.30 暖色主题 QSS，保留作回退参考；新代码走 build_style()。
_LEGACY_STYLE_030 = '''
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
QLineEdit, QTextEdit, QTextBrowser, QDateTimeEdit, QComboBox, QSpinBox { background:white; border:1px solid #EDE3D7; border-radius:10px; padding:9px; selection-background-color:#FFE2D8; selection-color:#5A2A20; }
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

_STYLE = Template('''
QLabel { color:$ink; font-size:13px; background:transparent; }
QMainWindow, QDialog { background:$bg; }
QWidget#sidebar { background:$surface; border-right:1px solid $border; }
QWidget#winbar { background:$surface; border-bottom:1px solid $border; }
QLabel#brand { color:$brand; font-size:15px; font-weight:700; }
QLabel#subtitle { color:$ink_3; font-size:12px; }
QLabel#pageTitle { color:$ink; font-size:19px; font-weight:700; }
QLabel#sectionTitle { color:$ink; font-size:15px; font-weight:600; padding:20px 0 8px; }
QLabel#eyebrow { color:$ink_3; font-size:10px; font-weight:600; }
QLabel#winbarTitle { color:$ink; font-size:12px; font-weight:600; }
QLabel#winbarContext { color:$ink_3; font-size:12px; }
QLabel#versionLabel { color:$ink_4; font-size:10px; font-family:"Cascadia Mono","Consolas"; }
QLabel#dialogEyebrow { color:$ink_3; font-size:10px; font-weight:600; }
QLabel#dialogTitle { color:$ink; font-size:19px; font-weight:700; }
QLabel#dialogSubtitle { color:$ink_3; font-size:12px; }
QLabel#fieldLabel { color:$ink_2; font-size:12px; font-weight:600; }
QLabel#dialogHintText { color:$ink_3; font-size:12px; }
QFrame#dialogHint { background:$surface_2; border:1px solid $border; border-radius:10px; }
QTextBrowser#planPreview {
 border:1px solid $border; border-radius:12px; background:$surface_2; color:$ink_2;
 padding:12px; font-family:"Cascadia Mono","Consolas"; font-size:12px;
}
QLabel#reminderKicker { color:$brand_press; font-size:11px; font-weight:600; }
QLabel#reminderTitle { color:$ink; font-size:20px; font-weight:600; }
QLabel#reminderHint { color:$ink_3; font-size:12px; }
QFrame#reminderCard { background:$surface; border:1px solid $border; border-radius:20px; }
QToolButton#reminderClose {
 background:transparent; border:0; color:$ink_3; font-size:18px; border-radius:8px; padding:0;
}
QToolButton#reminderClose:hover { background:$brand_wash; color:$brand_press; }
QToolButton#reminderClose:focus { border:1px solid $brand; }
QToolButton#reminderLink {
 background:transparent; border:0; color:$ink_3; padding:8px 10px; font-size:12px; border-radius:8px;
}
QToolButton#reminderLink:hover { color:$brand_press; }
QToolButton#reminderLink:focus { border:1px solid $brand; }
QTabWidget::pane { border:0; background:transparent; }
QPushButton { background:$surface; border:1px solid $border; border-radius:10px; padding:8px 14px; color:$ink_2; }
QPushButton:hover { background:$surface_2; border-color:$border_strong; color:$ink; }
QPushButton:focus { border-color:$brand; }
QPushButton:pressed { background:$brand_wash; }
QPushButton:disabled { color:$ink_4; border-color:$border; background:$surface_2; }
QPushButton[variant="primary"] { background:$brand; color:$brand_on; border:1px solid $brand; font-weight:600; }
QPushButton[variant="primary"]:hover { background:$brand_hover; border-color:$brand_hover; }
QPushButton[variant="primary"]:pressed { background:$brand_press; border-color:$brand_press; }
QPushButton[variant="primary"]:disabled { background:$brand_line; border-color:$brand_line; color:$ink_3; }
QLineEdit, QTextEdit, QTextBrowser, QDateTimeEdit, QComboBox, QSpinBox {
 background:$surface; border:1px solid $border; border-radius:10px; padding:8px; color:$ink;
 selection-background-color:$brand_wash; selection-color:$ink;
}
QLineEdit:focus, QTextEdit:focus, QTextBrowser:focus, QDateTimeEdit:focus, QComboBox:focus, QSpinBox:focus { border-color:$brand; }
QTextBrowser#history { border:0; background:transparent; padding:0; }
QTextEdit#composer { border:0; background:transparent; padding:6px; }
QComboBox#nativeCombo { padding-right:24px; min-height:20px; }
QComboBox#nativeCombo::drop-down { border:0; width:24px; }
QComboBox#nativeCombo QAbstractItemView::item { min-height:32px; padding:4px 10px; border-radius:6px; }
QComboBox#nativeCombo QAbstractItemView {
 border:1px solid $border; border-radius:10px; outline:0; background:$surface;
 selection-background-color:$brand_wash; selection-color:$ink; padding:5px;
}
QListWidget#taskList { background:transparent; border:0; padding:0; outline:0; }
QListWidget#taskList::item { border:0; border-radius:14px; padding:16px; margin:5px 2px; background:$surface; }
QListWidget#taskList::item:hover { background:$surface_2; }
QListWidget#taskList::item:selected { background:$brand_wash; color:$ink; }
QSlider::groove:horizontal { height:4px; background:$surface_3; border-radius:2px; }
QSlider::sub-page:horizontal { background:$brand; border-radius:2px; }
QSlider::handle:horizontal {
 width:14px; height:14px; margin:-6px 0; background:$surface;
 border:2px solid $brand; border-radius:8px;
}
QSlider::handle:horizontal:hover { border-color:$brand_hover; }
QSlider:focus { border:1px solid $brand; border-radius:8px; }
QScrollArea { border:0; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { border:0; background:transparent; width:6px; margin:4px 0; }
QScrollBar::handle:vertical { background:$border_strong; border-radius:4px; min-height:28px; }
QScrollBar::handle:vertical:hover { background:$ink_4; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QScrollBar:horizontal { border:0; background:transparent; height:6px; }
QScrollBar::handle:horizontal { background:$border_strong; border-radius:3px; min-width:28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
QCheckBox { spacing:9px; padding:5px 0; color:$ink; }
QCheckBox::indicator { width:17px; height:17px; }
QStatusBar { color:$ink_3; background:$bg; font-size:11px; border-top:1px solid $border; }
QStatusBar::item { border:0; }
QToolTip { background:$ink; color:$bg; border:0; padding:8px; border-radius:6px; }
QMenu { background:$surface; border:1px solid $border; padding:6px; border-radius:10px; color:$ink; }
QMenu::item { padding:8px 24px; border-radius:6px; }
QMenu::item:selected { background:$brand_wash; color:$brand; }
QWidget#draftCard { background:$brand_wash; border:1px solid $brand_line; border-radius:14px; }
''')


def tokens():
    return _active


def mono_font(pixel):
    font = QFont(T.FONT_MONO)
    font.setStyleHint(QFont.Monospace)
    font.setPixelSize(pixel)
    return font


def build_style(t):
    return _STYLE.substitute(vars(t))


def _fluent_safe_stylesheet(qss, t):
    rules = re.findall(r'([^{}]+)\{([^{}]*)\}', qss)
    blocked = ('QComboBox', 'QSpinBox', 'QCheckBox', 'QPushButton')
    shell = ''.join(selector + '{' + body + '}' for selector, body in rules
                    if not any(name in selector for name in blocked))
    shell += (f'QDateTimeEdit {{background:{t.surface};border:1px solid {t.border};'
              f'border-radius:10px;padding:8px;min-height:22px;color:{t.ink};}}'
              f'QDateTimeEdit:focus {{border-color:{t.brand};}}'
              'QDateTimeEdit::drop-down {width:26px;border:0;}'
              f'QCalendarWidget QWidget {{background:{t.surface};color:{t.ink};}}'
              'QDialog QDialogButtonBox QPushButton {min-height:32px;padding:4px 16px;border-radius:10px;}')
    return shell


def apply_theme(app, theme='light'):
    global _active
    _active = T.get(theme)
    app.setStyle('Fusion')
    # Offscreen Qt may not discover installed system fonts automatically.
    if not QFontDatabase().families() and os.name == 'nt':
        font_file = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
        if font_file.is_file():
            QFontDatabase.addApplicationFont(str(font_file))
    font = QFont(T.FONT_UI if os.name == 'nt' else 'Sans Serif')
    font.setPixelSize(14)
    app.setFont(font)
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(_active.bg))
    palette.setColor(QPalette.Base, QColor(_active.surface))
    palette.setColor(QPalette.AlternateBase, QColor(_active.surface_2))
    palette.setColor(QPalette.Text, QColor(_active.ink))
    palette.setColor(QPalette.WindowText, QColor(_active.ink))
    palette.setColor(QPalette.ButtonText, QColor(_active.ink_2))
    palette.setColor(QPalette.Button, QColor(_active.surface))
    palette.setColor(QPalette.PlaceholderText, QColor(_active.ink_3))
    palette.setColor(QPalette.Highlight, QColor(_active.brand))
    palette.setColor(QPalette.HighlightedText, QColor(_active.brand_on))
    palette.setColor(QPalette.ToolTipBase, QColor(_active.ink))
    palette.setColor(QPalette.ToolTipText, QColor(_active.bg))
    app.setPalette(palette)
    if FLUENT_MODE:
        from .fluent import configure_fluent
        configure_fluent(_active.name)
        app.setStyleSheet(_fluent_safe_stylesheet(build_style(_active), _active))
    else:
        app.setStyleSheet(build_style(_active))


def application_icon():
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(_active.brand))
    painter.drawRoundedRect(1, 1, 62, 62, 16, 16)
    painter.setBrush(QColor(_active.brand_on))
    painter.drawEllipse(20, 31, 25, 21)
    for x, y, width, height in ((12, 24, 10, 12), (23, 14, 10, 13), (36, 15, 10, 13), (46, 26, 9, 11)):
        painter.drawEllipse(x, y, width, height)
    painter.end()
    return QIcon(canvas)


def add_soft_shadow(widget):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(30)
    effect.setOffset(0, 6)
    effect.setColor(QColor(0, 0, 0, 56) if _active.name == 'dark' else QColor(120, 82, 60, 24))
    widget.setGraphicsEffect(effect)
