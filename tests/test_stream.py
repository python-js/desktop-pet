import io
import json
import unittest
from unittest.mock import patch

from desktop_pet.assistant import ask, read_stream, reply_preview, RequestCancelled


def event(content):
    return ('data: ' + json.dumps({'choices': [{'delta': {'content': content}}]}) + '\n\n').encode()


class StreamTests(unittest.TestCase):
    def test_unicode_chunks_and_usage_events(self):
        data = b': keepalive\n\n' + event('你') + b'data: {"choices":[]}\n\n' + event('好') + b'data: [DONE]\n\n'
        chunks = []
        self.assertEqual(read_stream(io.BytesIO(data), chunks.append, lambda: False), '你好')
        self.assertEqual(chunks, ['你', '好'])

    def test_incomplete_or_filtered_stream_is_rejected(self):
        for data in (event('partial'), event('partial') + b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'):
            with self.assertRaises(ValueError):
                read_stream(io.BytesIO(data), lambda _: None, lambda: False)

    def test_cancel_before_and_during_read(self):
        with self.assertRaises(RequestCancelled):
            read_stream(io.BytesIO(event('ignored')), lambda _: None, lambda: True)
        cancelled = []
        with self.assertRaises(RequestCancelled):
            read_stream(io.BytesIO(event('first') + event('second')), lambda _: cancelled.append(True), lambda: bool(cancelled))

    def test_reply_preview_hides_task_json_and_decodes_partial_escapes(self):
        self.assertEqual(reply_preview('{"reply":"你好\\n继续","tasks":[{"title":"secret"}]}'), '你好\n继续')
        self.assertEqual(reply_preview('{"rep'), '')
        self.assertEqual(reply_preview('{"reply":"你好\\u4f'), '你好')
        self.assertEqual(reply_preview('{"reply":"\\ud83d\\ude00'), '😀')
        self.assertEqual(reply_preview('{"reply":"hi\\'), 'hi')
        self.assertEqual(reply_preview('plain response'), 'plain response')

    def test_reply_preview_hides_streaming_tasks_block(self):
        preview = reply_preview('先说结论。\n\n```tasks\n[{"title":"整理文档"')
        self.assertIn('先说结论', preview)
        self.assertNotIn('tasks', preview)
        self.assertNotIn('整理文档', preview)

    def test_provider_stream_request_and_nonstream_setting(self):
        class Response(io.BytesIO):
            headers = {'Content-Type': 'text/event-stream; charset=utf-8'}

        settings = {'base_url': 'https://example.com/v1', 'model': 'test'}
        with patch('desktop_pet.assistant.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(event('hello') + b'data: [DONE]\n\n')
            parts = []
            self.assertEqual(ask(settings, [{'role': 'user', 'content': 'hi'}], parts.append), 'hello')
            self.assertTrue(json.loads(opener.return_value.open.call_args.args[0].data)['stream'])
            self.assertEqual(parts, ['hello'])
        class JsonResponse(io.BytesIO):
            headers = {'Content-Type': 'application/json'}
        with patch('desktop_pet.assistant.request.build_opener') as opener:
            opener.return_value.open.return_value = JsonResponse(b'{"choices":[{"message":{"content":"fallback"}}]}')
            self.assertEqual(ask(dict(settings, stream=False), [{'role': 'user', 'content': 'hi'}], lambda _: None), 'fallback')
            self.assertFalse(json.loads(opener.return_value.open.call_args.args[0].data)['stream'])

    def test_oversized_event_rejected(self):
        with self.assertRaises(ValueError):
            read_stream(io.BytesIO(b'data: ' + b'x' * 262145), lambda _: None, lambda: False)


if __name__ == '__main__':
    unittest.main()
