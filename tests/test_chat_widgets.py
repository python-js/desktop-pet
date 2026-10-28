from qt_support import QT_APP
import unittest
from PyQt5.QtTest import QTest
from desktop_pet.ui.chat_widgets import MessageHistory, MessageRow


class MessageWidgetTests(unittest.TestCase):
    def test_literal_text_and_system_notice_survive_clear(self):
        history = MessageHistory()
        history.resize(700, 400)
        history.show()
        try:
            payload = '<img src="https://example.com/x"> & literal'
            history.append_message('assistant', payload)
            history.append_message('system', '已保存：喝水')
            QTest.qWait(50)
            self.assertIn(payload, history.toPlainText())
            rows = history.content.findChildren(MessageRow)
            self.assertTrue(any(row.system for row in rows))
            self.assertEqual(rows[0].text.toPlainText(), payload)
            history.clear()
            QTest.qWait(20)
            self.assertEqual(history.toPlainText(), '')
            self.assertTrue(history.placeholder.isVisible())
        finally:
            history.close()
            history.deleteLater()
            QT_APP.processEvents()

    def test_assistant_markdown_renders_but_user_text_stays_literal(self):
        history = MessageHistory()
        history.resize(700, 400)
        history.show()
        try:
            history.append_message('assistant', '# 知识库方案\n\n- 解析文档\n- 建立索引\n\n用 **FTS5** 就够了')
            history.append_message('user', '**原样显示**')
            QTest.qWait(80)
            rows = history.content.findChildren(MessageRow)
            assistant_text = rows[0].text.toPlainText()
            self.assertIn('知识库方案', assistant_text)
            self.assertIn('解析文档', assistant_text)
            self.assertIn('FTS5', assistant_text)
            self.assertNotIn('#', assistant_text)
            self.assertNotIn('**', assistant_text)
            self.assertEqual(rows[1].text.toPlainText(), '**原样显示**')
        finally:
            history.close()
            history.deleteLater()
            QT_APP.processEvents()

    def test_stream_replaces_one_bubble_and_long_text_wraps(self):
        history = MessageHistory()
        history.resize(500, 320)
        history.show()
        try:
            history.setPlainText('partial')
            history.setPlainText('https://example.com/' + 'x' * 2500)
            QTest.qWait(150)
            self.assertEqual(len(history.messages), 1)
            self.assertNotIn('partial', history.toPlainText())
            self.assertEqual(history.horizontalScrollBar().maximum(), 0)
            history.resize(350, 320)
            QTest.qWait(150)
            self.assertEqual(history.horizontalScrollBar().maximum(), 0)
        finally:
            history.close()
            history.deleteLater()
            QT_APP.processEvents()

    def test_follow_stops_when_user_scrolls_up(self):
        history = MessageHistory()
        history.resize(500, 300)
        history.show()
        try:
            for i in range(20):
                history.append_message('assistant', f'历史 {i}\n' + '内容 ' * 40)
            QTest.qWait(200)
            bar = history.verticalScrollBar()
            self.assertGreater(bar.maximum(), 100)
            bar.setValue(0)
            QTest.qWait(20)
            row = history.rows.itemAt(history.rows.count() - 2).widget()
            history.update_row(row, '上滚后追加\n' + '更多 ' * 200)
            QTest.qWait(200)
            self.assertEqual(bar.value(), 0)
            bar.setValue(bar.maximum())
            history.update_row(row, '接近底部时追加\n' + '更多 ' * 200)
            QTest.qWait(200)
            self.assertEqual(bar.value(), bar.maximum())
            bar.setValue(0)
            history.scroll_to_end()
            QTest.qWait(200)
            self.assertEqual(bar.value(), bar.maximum())
        finally:
            history.close()
            history.deleteLater()
            QT_APP.processEvents()