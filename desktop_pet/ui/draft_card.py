from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QWidget, QFormLayout, QLineEdit, QHBoxLayout, QMessageBox

from .common import button, time_input, iso_input, repeat_input
from ..recurrence import REPEAT_LABELS
from .controls import LineEdit as QLineEdit


class DraftCard(QWidget):
    saved = pyqtSignal(str)
    removed = pyqtSignal()

    def __init__(self, store, task, session_id, parent=None):
        super().__init__(parent)
        self.setObjectName('draftCard')
        from .theme import add_soft_shadow
        add_soft_shadow(self)
        self.store = store
        self.session_id = session_id
        self.draft_id = task.get('id') or store.save_draft(task['title'], task['due_at'], session_id=session_id, repeat=task.get('repeat', 'none'))
        form = QFormLayout(self)
        form.setContentsMargins(16, 14, 16, 14)
        self.title = QLineEdit(task['title'])
        self.title.setMaxLength(200)
        self.date = time_input(task['due_at'])
        form.addRow('待确认', self.title)
        form.addRow('提醒时间', self.date)
        self.repeat = repeat_input(task.get('repeat_rule', task.get('repeat', 'none')))
        form.addRow('重复', self.repeat)
        actions = QHBoxLayout()
        self.save_button = button('确认保存', self.confirm, actions, primary=True)
        button('丢弃', self.discard, actions)
        form.addRow(actions)
        self.title.textChanged.connect(self.persist)
        self.date.dateTimeChanged.connect(self.persist)
        self.repeat.currentIndexChanged.connect(self.persist)

    def persist(self):
        self.store.save_draft(self.title.text(), iso_input(self.date), self.draft_id, self.session_id, self.repeat.currentData())

    def confirm(self):
        try:
            self.persist()
            self.store.confirm_draft(self.draft_id)
            self.save_button.setEnabled(False)
            self.saved.emit(f'已保存：{self.title.text()}，提醒时间 {self.date.text()}，{REPEAT_LABELS[self.repeat.currentData()]}。')
            self.removed.emit()
        except ValueError as exc:
            QMessageBox.warning(self, '无法保存', str(exc))

    def discard(self):
        self.store.discard_draft(self.draft_id)
        self.removed.emit()
