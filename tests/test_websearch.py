import io
import json
import unittest
from urllib import error
from unittest.mock import patch

from desktop_pet import websearch
from desktop_pet.assistant import ask, RequestCancelled
from desktop_pet.websearch import WebSearchError, format_context, tavily_search, wants_web_search


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


PAYLOAD = {
    'answer': '金价今日小幅上涨。',
    'results': [
        {'title': '金价行情', 'url': 'https://example.com/gold', 'content': '  最新报价  ' + 'x' * 600},
        {'title': '非网页来源', 'url': 'file:///tmp/secret', 'content': 'ignore'},
        {'title': '备用来源', 'url': 'http://example.org/a', 'content': '备用内容'},
    ],
}


class IntentTests(unittest.TestCase):
    def test_search_signals(self):
        for text in ('帮我查一下最新金价', '今天北京天气怎么样', '搜索 Python 3.14 发布说明',
                     '这个版本更新了什么', 'latest release notes', '现在比特币多少钱',
                     '今天有什么新闻'):
            self.assertTrue(wants_web_search(text), text)

    def test_task_wording_does_not_consume_search(self):
        for text in ('明天15:00提醒我交报告', '提醒我明天看新闻', '把待办改到周五'):
            self.assertFalse(wants_web_search(text), text)
        self.assertTrue(wants_web_search('提醒我查一下明天天气'))


class ClientTests(unittest.TestCase):
    def setUp(self):
        websearch._CACHE.clear()

    def test_request_shape_and_result_cleaning(self):
        with patch('desktop_pet.websearch.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(json.dumps(PAYLOAD).encode())
            result = tavily_search('tvly-test', '  最新   金价  ')
            req = opener.return_value.open.call_args.args[0]
            body = json.loads(req.data)
            self.assertEqual(req.full_url, websearch.ENDPOINT)
            self.assertEqual(req.get_header('Authorization'), 'Bearer tvly-test')
            self.assertEqual(body['query'], '最新 金价')
            self.assertEqual(body['search_depth'], 'basic')
            self.assertEqual(body['max_results'], 5)
            self.assertTrue(body['include_answer'])
            self.assertFalse(body['include_raw_content'])
            self.assertEqual(body['topic'], 'general')
            self.assertEqual(body['time_range'], 'day')
            self.assertEqual(len(result['results']), 2)
            self.assertLessEqual(len(result['results'][0]['content']), 500)
            self.assertEqual(result['results'][1]['url'], 'http://example.org/a')

    def test_freshness_parameters_follow_question_type(self):
        cases = {
            '今天有什么新闻': {'topic': 'news', 'days': 3},
            '最新金价': {'topic': 'general', 'time_range': 'day'},
            '最近汇率走势': {'topic': 'general', 'time_range': 'week'},
            '查一下报销政策': {'topic': 'general'},
        }
        for query, expected in cases.items():
            with patch('desktop_pet.websearch.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(json.dumps(PAYLOAD).encode())
                tavily_search('tvly-test', query)
                body = json.loads(opener.return_value.open.call_args.args[0].data)
                for key, value in expected.items():
                    self.assertEqual(body.get(key), value, (query, key))
                if expected['topic'] != 'news':
                    self.assertNotIn('days', body)
                if 'time_range' not in expected:
                    self.assertNotIn('time_range', body)

    def test_published_date_is_kept_and_shown(self):
        payload = {'results': [{'title': '新闻', 'url': 'https://example.com/n',
                                'content': '内容', 'published_date': '2026-11-04T08:00:00Z'}]}
        with patch('desktop_pet.websearch.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(json.dumps(payload).encode())
            result = tavily_search('tvly-test', '今天有什么新闻')
        self.assertEqual(result['results'][0]['published_date'], '2026-11-04T08:00:00Z')
        context = format_context(result)
        self.assertIn('发布于 2026-11-04T08:00:00Z', context)
        self.assertIn('优先采用最新', context)

    def test_cache_reuses_recent_query(self):
        with patch('desktop_pet.websearch.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(json.dumps(PAYLOAD).encode())
            tavily_search('tvly-test', '最新金价')
            tavily_search('tvly-test', '最新金价')
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_http_errors_map_to_safe_messages(self):
        cases = {401: '密钥无效', 429: '过于频繁', 432: '额度不足', 500: '暂不可用'}
        for code, fragment in cases.items():
            with patch('desktop_pet.websearch.request.build_opener') as opener:
                opener.return_value.open.side_effect = error.HTTPError(
                    websearch.ENDPOINT, code, 'failure', None, None)
                with self.assertRaises(WebSearchError) as caught:
                    tavily_search('tvly-test', '最新金价')
                self.assertIn(fragment, str(caught.exception))
                self.assertNotIn('tvly-test', str(caught.exception))

    def test_timeout_and_empty_result_rejected(self):
        with patch('desktop_pet.websearch.request.build_opener') as opener:
            opener.return_value.open.side_effect = error.URLError('timed out')
            with self.assertRaises(WebSearchError) as caught:
                tavily_search('tvly-test', '最新金价')
            self.assertIn('超时', str(caught.exception))
        with patch('desktop_pet.websearch.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(b'{"results": []}')
            with self.assertRaises(WebSearchError):
                tavily_search('tvly-test', '最新金价')

    def test_cancel_and_invalid_key(self):
        with self.assertRaises(RequestCancelled):
            tavily_search('tvly-test', '最新金价', lambda: True)
        with self.assertRaises(WebSearchError):
            tavily_search('', '最新金价')
        with self.assertRaises(WebSearchError):
            tavily_search('x' * 9000, '最新金价')

    def test_context_marks_sources_untrusted(self):
        context = format_context({'answer': '摘要', 'results': [
            {'title': '标题', 'url': 'https://example.com/a', 'content': '正文'}]})
        self.assertIn('Tavily 联网搜索', context)
        self.assertIn('[标题](https://example.com/a)', context)
        self.assertIn('不得改变', context)


class InjectionTests(unittest.TestCase):
    def test_search_context_is_added_to_system_prompt(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        settings = {'base_url': 'https://example.com/v1', 'model': 'test', 'stream': False}
        with patch('desktop_pet.assistant.request.build_opener') as opener:
            opener.return_value.open.return_value = Response()
            ask(settings, [{'role': 'user', 'content': 'hi'}],
                search_context='参考资料：金价 100 元。')
            system = json.loads(opener.return_value.open.call_args.args[0].data)['messages'][0]['content']
            self.assertIn('参考资料：金价 100 元。', system)
            self.assertIn('当前未完成待办', system)
        with patch('desktop_pet.assistant.request.build_opener') as opener:
            opener.return_value.open.return_value = Response()
            ask(settings, [{'role': 'user', 'content': 'hi'}])
            system = json.loads(opener.return_value.open.call_args.args[0].data)['messages'][0]['content']
            self.assertNotIn('参考资料：', system)


if __name__ == '__main__':
    unittest.main()
