import base64
import hashlib
import hmac
import io
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from desktop_pet import dingtalk

WEBHOOK = 'https://oapi.dingtalk.com/robot/send?access_token=abc123'


class Response(io.BytesIO):
    pass


class Opener:
    def __init__(self, body):
        self.body = body
        self.request = None
        self.timeout = None

    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return Response(self.body)


class DingTalkTests(unittest.TestCase):
    def test_webhook_validation(self):
        self.assertEqual(dingtalk.validate_webhook(WEBHOOK), WEBHOOK)
        for value in ('http://oapi.dingtalk.com/robot/send?access_token=abc',
                      'https://example.com/robot/send?access_token=abc',
                      'https://oapi.dingtalk.com/robot/send',
                      'https://user:secret@oapi.dingtalk.com/robot/send?access_token=abc'):
            with self.assertRaises(dingtalk.DingTalkError):
                dingtalk.validate_webhook(value)

    def test_signed_url_matches_dingtalk_algorithm(self):
        url = dingtalk.signed_url(WEBHOOK, 'SEC-test', 1700000000000)
        query = parse_qs(urlsplit(url).query)
        expected = base64.b64encode(hmac.new(b'SEC-test', b'1700000000000\nSEC-test',
                                             hashlib.sha256).digest()).decode()
        self.assertEqual(query['timestamp'], ['1700000000000'])
        self.assertEqual(query['sign'], [expected])
        self.assertEqual(query['access_token'], ['abc123'])

    def test_send_builds_text_message_and_reports_dingtalk_errors(self):
        opener = Opener(b'{"errcode":0,"errmsg":"ok"}')
        self.assertEqual(dingtalk.send(WEBHOOK, 'SEC-test', '交报告', '2099-01-01 15:00',
                                       '不重复', opener=opener), 'ok')
        self.assertEqual(json.loads(opener.request.data), {
            'msgtype': 'text',
            'text': {'content': '【待办提醒】交报告\n时间：2099-01-01 15:00\n重复：不重复'}})
        self.assertIn('timestamp=', opener.request.full_url)
        self.assertIn('sign=', opener.request.full_url)
        with self.assertRaises(dingtalk.DingTalkError):
            dingtalk.send(WEBHOOK, 'SEC-test', 't', 'd', 'r',
                          opener=Opener(b'{"errcode":310000,"errmsg":"sign not match"}'))
        with self.assertRaises(dingtalk.DingTalkError):
            dingtalk.send(WEBHOOK, '', 't', 'd', 'r', opener=opener)
        with self.assertRaises(dingtalk.DingTalkError):
            dingtalk.send(WEBHOOK, 'SEC-test', 't', 'd', 'r', opener=Opener(b'not json'))


if __name__ == '__main__':
    unittest.main()
