import json
import unittest
from datetime import datetime
from desktop_pet.assistant import local_reply


class RepeatPreferenceTests(unittest.TestCase):
    def test_default_once_and_explicit_repeat(self):
        now=datetime.fromisoformat('2026-10-27T10:00:00+08:00')
        examples=[('明天15:00提醒我喝水','none'),('明天15:00提醒我喝水，重复提醒','daily'),
                  ('每天15:00提醒我喝水','daily'),('每周三15:00提醒我喝水','weekly'),
                  ('明天15:00提醒我喝水，不要重复','none')]
        for text,expected in examples:
            with self.subTest(text=text):
                task=json.loads(local_reply(text,now))['tasks'][0]
                self.assertEqual(task['repeat'],expected)
                self.assertEqual(task['title'],'喝水')
