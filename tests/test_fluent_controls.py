from qt_support import QT_APP
import unittest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from desktop_pet.ui.controls import FLUENT_MODE


@unittest.skipUnless(FLUENT_MODE, 'Native fallback selected')
class FluentControlTests(unittest.TestCase):
    def test_button_overload_initialization_keeps_label(self):
        from desktop_pet.ui.fluent import Button, PrimaryButton
        from qfluentwidgets import PushButton, PrimaryPushButton
        for cls, base in ((Button, PushButton), (PrimaryButton, PrimaryPushButton)):
            widget = cls('确认保存')
            self.assertIsInstance(widget, base)
            self.assertEqual(widget.text(), '确认保存')
            widget.deleteLater()
        QT_APP.processEvents()

    def test_combo_data_clear_and_keyboard_disabled_item(self):
        from desktop_pet.ui.fluent import ComboBox
        combo = ComboBox()
        combo.addItem('待机', 'idle')
        combo.addItem('点击', 'touch')
        combo.addItem('提醒', 'reminder')
        combo.setCurrentIndex(combo.findData('idle'))
        combo.setItemEnabled(1, False)
        QTest.keyClick(combo, Qt.Key_Down)
        self.assertEqual(combo.currentData(), 'reminder')
        combo.clear()
        self.assertIsNone(combo.currentData())
        combo.addItem('新会话', 'new')
        self.assertEqual(combo.findData('new'), 0)
        self.assertEqual(combo.currentData(), 'new')
        combo.deleteLater()
        QT_APP.processEvents()
