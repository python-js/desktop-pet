"""Keep one QApplication alive across Qt/Fluent tests and global router objects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtWidgets import QApplication
QT_APP = QApplication.instance() or QApplication([])

from desktop_pet.ui.theme import apply_theme
apply_theme(QT_APP)
