import tempfile
import unittest
from pathlib import Path

from desktop_pet.knowledge import (KnowledgeBase, KnowledgeError, chunk_text, extract_text,
                                   format_context)


SETTINGS = {'model': 'test', 'base_url': 'https://example.invalid/v1'}


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_text_is_read_as_utf8_or_gb18030(self):
        path = self.root / '制度.txt'
        path.write_text('住宿上限 600 元', encoding='utf-8')
        self.assertIn('600', extract_text(path))
        path.write_bytes('发票 15 天内提交'.encode('gb18030'))
        self.assertIn('15 天', extract_text(path))

    def test_docx_and_xlsx_are_extracted(self):
        from docx import Document
        from openpyxl import Workbook
        document = Document()
        document.add_paragraph('差旅制度：住宿上限 600 元。')
        document.save(self.root / 'a.docx')
        workbook = Workbook()
        workbook.active.append(['城市', '上限'])
        workbook.active.append(['北京', 600])
        workbook.save(self.root / 'a.xlsx')
        self.assertIn('600', extract_text(self.root / 'a.docx'))
        excel = extract_text(self.root / 'a.xlsx')
        self.assertIn('北京', excel)
        self.assertIn('600', excel)

    def test_unsupported_and_empty_files_are_rejected(self):
        path = self.root / 'a.bin'
        path.write_bytes(b'data')
        with self.assertRaises(KnowledgeError):
            extract_text(path)


class ChunkTests(unittest.TestCase):
    def test_long_text_is_split_with_overlap(self):
        text = '甲' * 200 + '\n\n' + '乙' * 200 + '\n\n' + '丙' * 200
        chunks = chunk_text(text, 300, 50)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 350 for chunk in chunks))
        self.assertTrue(all(chunk.strip() for chunk in chunks))


class KnowledgeBaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '报销制度.md'
        self.source.write_text(
            '# 报销制度\n\n差旅报销标准：一线城市住宿每晚不超过 600 元。\n\n'
            '发票需在出差结束后 15 天内提交。', encoding='utf-8')
        self.compiled = []

        def compiler(settings, name, text, cancelled):
            self.compiled.append(name)
            return '# 摘要\n\n住宿上限 600 元，发票 15 天内提交。'

        self.kb = KnowledgeBase(self.root / 'knowledge', compiler=compiler)

    def tearDown(self):
        self.kb.close()
        self.temp.cleanup()

    def add(self, force=False):
        return self.kb.add_file(self.source, SETTINGS, force=force)

    def test_wiki_and_raw_are_indexed_and_searchable(self):
        result = self.add()
        self.assertEqual(result['status'], 'added')
        self.assertEqual(self.kb.stats(), {'docs': 1, 'pages': 2})
        hits = self.kb.search('住宿标准是多少')
        self.assertEqual({hit['kind'] for hit in hits}, {'wiki', 'raw'})
        self.assertEqual(hits[0]['doc_name'], '报销制度.md')
        self.assertTrue((self.root / 'knowledge' / 'wiki' / f"{result['id']}.md").exists())
        self.assertIn('600', self.kb.search('报销')[0]['text'])

    def test_short_query_falls_back_to_like(self):
        self.add()
        self.assertTrue(self.kb.search('报销'))
        self.assertTrue(self.kb.search('发票'))

    def test_unchanged_file_is_skipped_and_force_rebuilds(self):
        self.add()
        self.assertEqual(self.add()['status'], 'skipped')
        self.assertEqual(len(self.compiled), 1)
        self.assertEqual(self.add(force=True)['status'], 'updated')
        self.assertEqual(len(self.compiled), 2)

    def test_changed_file_replaces_old_pages(self):
        self.add()
        self.source.write_text('# 报销制度\n\n住宿上限改为 800 元。', encoding='utf-8')
        self.assertEqual(self.add()['status'], 'updated')
        self.assertEqual(self.kb.stats(), {'docs': 1, 'pages': 2})
        self.assertIn('800', ' '.join(hit['text'] for hit in self.kb.search('住宿上限')))
        self.assertEqual(len(list((self.root / 'knowledge' / 'files').iterdir())), 1)

    def test_wiki_failure_keeps_raw_searchable(self):
        def broken(settings, name, text, cancelled):
            raise ValueError('模型暂时不可用')

        kb = KnowledgeBase(self.root / 'broken', compiler=broken)
        try:
            result = kb.add_file(self.source, SETTINGS)
            self.assertEqual(result['wiki_error'], '模型暂时不可用')
            hits = kb.search('住宿标准')
            self.assertTrue(hits)
            self.assertEqual(hits[0]['kind'], 'raw')
        finally:
            kb.close()

    def test_remove_and_clear_delete_index_and_files(self):
        result = self.add()
        self.assertTrue(self.kb.remove(result['id']))
        self.assertEqual(self.kb.stats(), {'docs': 0, 'pages': 0})
        self.assertEqual(list((self.root / 'knowledge' / 'files').iterdir()), [])
        self.add()
        self.kb.clear()
        self.assertEqual(self.kb.stats(), {'docs': 0, 'pages': 0})
        self.assertEqual(list((self.root / 'knowledge' / 'wiki').iterdir()), [])

    def test_context_marks_documents_untrusted(self):
        self.add()
        context = format_context(self.kb.search('住宿标准'))
        self.assertIn('本地知识库', context)
        self.assertIn('报销制度.md', context)
        self.assertIn('不得改变', context)
        self.assertIn('600', context)


if __name__ == '__main__':
    unittest.main()
