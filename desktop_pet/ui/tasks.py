"""Task page presentation, kept separate from chat and model requests."""
from datetime import datetime, timedelta
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QHBoxLayout, QComboBox,
                             QLineEdit, QListWidget, QListWidgetItem, QDialog, QMessageBox,
                             QFrame, QStyle, QStyledItemDelegate)
from ..core import parse_due
from ..recurrence import REPEAT_LABELS, in_period
from .common import button, local_time, iso_input, TaskDialog
from .controls import ComboBox as QComboBox
from .controls import LineEdit as QLineEdit
from .theme import ACCENT_DARK, INK, MUTED


def short_due(value, now):
    due = parse_due(value).astimezone()
    if due.date() == now.date():
        return f'今天 {due:%H:%M}'
    if due.date() == (now + timedelta(days=1)).date():
        return f'明天 {due:%H:%M}'
    return f'{due:%m月%d日 %H:%M}'


class TaskDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(0, 78)

    def paint(self, painter, option, index):
        task = index.data(Qt.UserRole)
        if not task:
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect.adjusted(2, 3, -2, -3))
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if selected:
            fill, border = QColor('#FFF4ED'), QColor('#F2CDBF')
        elif hover:
            fill, border = QColor('#FFFBF7'), QColor('#F3E5D8')
        else:
            fill, border = QColor('#FFFFFF'), QColor('#F3EADF')
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 14, 14)

        now = datetime.now().astimezone()
        due = parse_due(task['due_at']).astimezone()
        done = task.get('status') == 'done'
        deferred = not done and bool(task.get('deferred'))
        overdue = not done and due <= now
        circle = QRectF(rect.left() + 18, rect.center().y() - 9, 18, 18)
        if done:
            painter.setBrush(QColor(ACCENT_DARK))
            painter.setPen(QPen(QColor(ACCENT_DARK), 1.6))
        else:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor('#C25A43') if overdue and not deferred else QColor('#D9CDC0'), 1.6))
        painter.drawEllipse(circle)
        if done:
            painter.setPen(QPen(QColor('#FFFFFF'), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            center = circle.center()
            painter.drawLine(QPointF(center.x() - 4, center.y()), QPointF(center.x() - 1, center.y() + 3))
            painter.drawLine(QPointF(center.x() - 1, center.y() + 3), QPointF(center.x() + 5, center.y() - 3))

        left = circle.right() + 14
        width = rect.right() - left - 18
        title_font = QFont(option.font)
        title_font.setPixelSize(15)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(INK))
        title = painter.fontMetrics().elidedText(task.get('title', ''), Qt.ElideRight, int(width))
        painter.drawText(QRectF(left, rect.top() + 15, width, 22), Qt.AlignLeft | Qt.AlignVCenter, title)

        meta_font = QFont(option.font)
        meta_font.setPixelSize(12)
        painter.setFont(meta_font)
        painter.setPen(QColor('#B4432F') if overdue and not deferred else QColor(MUTED))
        repeat = REPEAT_LABELS.get(task.get('repeat_rule', 'none'), '不重复')
        prefix = '已延期' if deferred else ('已逾期' if overdue else '')
        meta = f"{prefix + ' · ' if prefix else ''}{short_due(task['due_at'], now)} · {repeat}"
        if task.get('dingtalk'):
            meta += ' · 钉钉'
        meta = painter.fontMetrics().elidedText(meta, Qt.ElideRight, int(width))
        painter.drawText(QRectF(left, rect.top() + 40, width, 18), Qt.AlignLeft | Qt.AlignVCenter, meta)
        painter.restore()


class TasksPageMixin:
    def build_tasks(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 28, 30, 20)
        layout.setSpacing(16)
        heading = QLabel('待办事项')
        heading.setObjectName('pageTitle')
        layout.addWidget(heading)
        subtitle = QLabel('让每件事都有着落。双击任务可编辑标题和提醒时间。')
        subtitle.setObjectName('subtitle')
        layout.addWidget(subtitle)
        filters = QHBoxLayout()
        self.task_filter = QComboBox()
        self.task_filter.addItems(['未完成', '已完成'])
        self.task_filter.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_filter)
        self.task_period = QComboBox()
        for label, value in [('全部时间', 'all'), ('今天', 'today'), ('未来日期', 'future'), ('已逾期', 'overdue')]:
            self.task_period.addItem(label, value)
        self.task_period.currentIndexChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_period)
        self.task_search = QLineEdit()
        self.task_search.setPlaceholderText('搜索任务标题')
        self.task_search.textChanged.connect(self.refresh_tasks)
        filters.addWidget(self.task_search, 1)
        self.task_count = QLabel()
        filters.addWidget(self.task_count)
        layout.addLayout(filters)
        self.tasks = QListWidget()
        self.tasks.setObjectName('taskList')
        self.tasks.setFrameShape(QFrame.NoFrame)
        self.tasks.setMouseTracking(True)
        self.tasks.setUniformItemSizes(True)
        self.tasks.setItemDelegate(TaskDelegate(self.tasks))
        self.tasks.itemDoubleClicked.connect(self.edit_task)
        layout.addWidget(self.tasks)
        self.task_empty = QLabel('还没有待办事项\n\n从一件小事开始，或让对话助手帮你整理。', self.tasks.viewport())
        self.task_empty.setObjectName('subtitle')
        self.task_empty.setAlignment(Qt.AlignCenter)
        empty_layout = QVBoxLayout(self.tasks.viewport())
        empty_layout.addStretch()
        empty_layout.addWidget(self.task_empty)
        empty_layout.addStretch()
        row = QHBoxLayout()
        button('新增待办', self.new_task, row, primary=True)
        self.complete_button = button('标记完成', self.complete_selected, row)
        self.snooze_button = button('十分钟后提醒', self.snooze_selected, row)
        button('删除', self.delete_selected, row)
        self.undo_button = button('撤销删除', self.undo_delete, row)
        self.undo_button.setEnabled(False)
        row.addStretch()
        layout.addLayout(row)
        self.tabs.addTab(page, '待办')

    def refresh_tasks(self):
        selected = self.tasks.currentItem()
        selected_id = selected.data(Qt.UserRole)['id'] if selected else None
        scroll = self.tasks.verticalScrollBar().value()
        self.tasks.clear()
        done = self.task_filter.currentIndex() == 1
        self.complete_button.setText('恢复待办' if done else '标记完成')
        self.snooze_button.setEnabled(not done)
        self.task_period.setEnabled(not done)
        rows = self.store.history('done' if done else 'pending', self.task_search.text())
        now = datetime.now().astimezone()
        if not done:
            rows = [row for row in rows if in_period(parse_due(row['due_at']), self.task_period.currentData(), now)]
        self.task_count.setText(f'{len(rows)} 项')
        self.task_empty.setVisible(not rows)
        for task in rows:
            overdue = not done and parse_due(task['due_at']) <= now
            deferred = not done and bool(task['deferred'])
            prefix = '已完成' if done else ('已延期' if deferred else ('已逾期' if overdue else '待提醒'))
            repeat = REPEAT_LABELS[task['repeat_rule']]
            item = QListWidgetItem(f"{task['title']}\n{prefix} · {local_time(task['due_at'])} · {repeat}")
            item.setData(Qt.UserRole, dict(task))
            item.setToolTip(task['title'])
            self.tasks.addItem(item)
            if task['id'] == selected_id:
                self.tasks.setCurrentItem(item)
        self.tasks.verticalScrollBar().setValue(scroll)
        self.refresh_home()

    def focus_task(self, task_id, done=False):
        self.task_filter.setCurrentIndex(1 if done else 0)
        self.task_period.setCurrentIndex(0)
        self.task_search.clear()
        self.refresh_tasks()
        for row in range(self.tasks.count()):
            item = self.tasks.item(row)
            if item.data(Qt.UserRole)['id'] == task_id:
                self.tasks.setCurrentRow(row)
                self.tasks.scrollToItem(item)
                break

    def new_task(self):
        self.task_dialog()

    def edit_task(self, item):
        if item.data(Qt.UserRole)['status'] == 'pending':
            self.task_dialog(item.data(Qt.UserRole))

    def task_dialog(self, task=None):
        dialog = TaskDialog(self, task)
        while dialog.exec_() == QDialog.Accepted:
            try:
                if task:
                    self.store.edit(task['id'], dialog.title.text(), iso_input(dialog.date),
                                    repeat=dialog.repeat.currentData(), dingtalk=dialog.dingtalk.isChecked())
                    self.dismiss_reminder(task['id'])
                else:
                    self.store.add(dialog.title.text(), iso_input(dialog.date),
                                   repeat=dialog.repeat.currentData(), dingtalk=dialog.dingtalk.isChecked())
                self.refresh_tasks()
                break
            except ValueError as exc:
                QMessageBox.warning(self, '无法保存', str(exc))

    def complete_selected(self):
        item = self.tasks.currentItem()
        if item:
            task = item.data(Qt.UserRole)
            if task['status'] == 'done':
                try:
                    self.store.reopen(task['id'])
                except ValueError as exc:
                    QMessageBox.information(self, '重复任务', str(exc))
                    return
                self.refresh_tasks()
                self.statusBar().showMessage('已恢复待办；已过期的任务会重新提醒，可在未完成页修改时间。', 8000)
            else:
                self.resolve(task['id'], False)

    def delete_selected(self):
        item = self.tasks.currentItem()
        if item:
            self.last_deleted = item.data(Qt.UserRole)['id']
            self.store.delete(self.last_deleted)
            self.dismiss_reminder(self.last_deleted)
            self.undo_button.setEnabled(True)
            self.refresh_tasks()
            self.statusBar().showMessage('已删除，可撤销最近一次删除。', 6000)

    def undo_delete(self):
        if self.last_deleted:
            self.store.undo_delete(self.last_deleted)
            self.last_deleted = None
            self.undo_button.setEnabled(False)
            self.refresh_tasks()

    def snooze_selected(self):
        item = self.tasks.currentItem()
        if item:
            task = item.data(Qt.UserRole)
            if task.get('deferred'):
                self.statusBar().showMessage('该待办已延期，不再提醒；双击修改提醒时间可重新开始。', 8000)
                return
            self.resolve(task['id'], True)

    def resolve(self, task_id, snooze):
        if snooze:
            self.store.snooze(task_id)
        else:
            next_id = self.store.complete(task_id)
            if next_id:
                self.statusBar().showMessage('本次已完成，已生成下一次重复待办。', 8000)
        self.dismiss_reminder(task_id)
        self.refresh_tasks()

