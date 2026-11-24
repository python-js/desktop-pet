import tempfile
import unittest
from pathlib import Path

from desktop_pet.knowledge import (KnowledgeBase, KnowledgeError, attach_missed_images,
                                   chunk_text, extract_text, format_context, _pdf_chunks)


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

    def test_docx_keeps_body_order_and_splits_at_questions(self):
        from docx import Document
        document = Document()
        document.add_paragraph('第一段说明')
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = '表格内容'
        document.add_paragraph('第二段说明')
        document.add_paragraph('1. 第一个问题')
        document.add_paragraph('问题一的答案')
        document.add_paragraph('2. 第二个问题')
        document.add_paragraph('问题二的答案')
        document.save(self.root / 'order.docx')
        text = extract_text(self.root / 'order.docx')
        self.assertLess(text.index('表格内容'), text.index('第二段说明'))
        chunks = chunk_text(text)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(chunks[0].startswith('第一段说明'))
        self.assertTrue(chunks[1].startswith('1.'))
        self.assertTrue(chunks[2].startswith('2.'))

    def test_docx_table_image_gets_placeholder(self):
        import base64
        from docx import Document
        (self.root / 'dot.png').write_bytes(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))
        document = Document()
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).paragraphs[0].add_run().add_picture(str(self.root / 'dot.png'))
        document.save(self.root / 'image.docx')
        self.assertIn('图片文字尚未识别', extract_text(self.root / 'image.docx'))

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

    def test_hard_boundary_is_never_merged(self):
        chunks = chunk_text('甲' * 300 + '\f' + '乙' * 300, 600, 80)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith('甲'))
        self.assertTrue(chunks[1].startswith('乙'))

    def test_heading_starts_a_new_chunk_and_sentences_stay_whole(self):
        from desktop_pet.knowledge import _structure_pdf_text
        structured = _structure_pdf_text(
            '前言正文第一行\n仍是同一段。\n\n第一章 总则\n本制度适用于\n全体员工。\n1.1 范围\n具体范围如下。超出部分另起。')
        self.assertIn('前言正文第一行仍是同一段。', structured)
        self.assertIn('本制度适用于全体员工。', structured)
        chunks = chunk_text(structured, 600, 80)
        self.assertTrue(chunks[0].startswith('前言'))
        self.assertNotIn('第一章', chunks[0])
        self.assertTrue(any(chunk.startswith('第一章 总则') and '全体员工' in chunk for chunk in chunks))
        self.assertTrue(any(chunk.startswith('1.1 范围') for chunk in chunks))
        long = '第一句内容完整。' * 3
        pieces = chunk_text(long, 20, 4)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(piece.endswith('。') for piece in pieces))


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

    def test_preview_snippet_is_centered_on_rare_query_term(self):
        self.source.write_text(
            '# 客户跟进\n\n' + '日常客户信息记录。' * 30 + '\n\n'
            '如果一个客户已经连续6个月没有采购，你应该重新激活客户：新品激活、爆款激活、采购季节激活。\n\n'
            + '其他备注。' * 20, encoding='utf-8')
        self.add()
        query = '如果一个客户已经连续6个月没有采购'
        preview = next(hit for hit in self.kb.search(query, preview=True) if hit['kind'] == 'raw')
        full = next(hit for hit in self.kb.search(query) if hit['kind'] == 'raw')
        self.assertIn('个月没', preview['text'])
        self.assertLessEqual(len(preview['text']), 302)
        self.assertGreater(len(full['text']), len(preview['text']))

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


class PdfImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_page_chunks_keep_the_figure_with_every_section(self):
        image_id = 'a' * 24
        chunks = _pdf_chunks([{
            'text': '点击设置按钮完成登录。\n\n' + '说明' * 400,
            'images': [{'id': image_id, 'caption': '右上角是设置按钮。'}],
        }])
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(f'[[img:{image_id}]]' in chunk and '设置按钮' in chunk for chunk in chunks))

    def test_missed_images_are_appended_once(self):
        image_id = 'b' * 24
        hits = [{'text': f'打开设置。\n[[img:{image_id}]] 右上角'}]
        self.assertTrue(attach_missed_images('按下面操作。', hits).endswith(f'[[img:{image_id}]]'))
        kept = f'1. 打开设置。\n\n[[img:{image_id}]]'
        self.assertEqual(attach_missed_images(kept, hits), kept)

    def test_missed_images_skipped_when_reply_says_not_found(self):
        image_id = 'd' * 24
        hits = [{'text': f'无关界面。\n[[img:{image_id}]]'}]
        reply = '本地知识库中没有金价相关资料，未找到可用数据。'
        self.assertEqual(attach_missed_images(reply, hits), reply)

    def test_context_tells_the_model_to_copy_image_tokens(self):
        image_id = 'c' * 24
        context = format_context([{
            'doc_name': '手册.pdf', 'kind': 'raw',
            'text': f'点击设置。\n[[img:{image_id}]] 右上角是设置按钮。'}])
        self.assertIn(f'[[img:{image_id}]]', context)
        self.assertIn('原样复制', context)

    def test_pdf_image_is_stored_captioned_and_removed_with_the_document(self):
        import os
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

        def captioner(settings, image, cancelled):
            self.assertEqual(image['mime'], 'image/png')
            return '右上角是设置按钮。'

        pdf = self.root / '手册.pdf'
        writer = PdfWriter()
        page = writer.add_blank_page(300, 400)

        def image(data, width, height):
            stream = StreamObject()
            stream.set_data(data)
            stream.update({
                NameObject('/Type'): NameObject('/XObject'),
                NameObject('/Subtype'): NameObject('/Image'),
                NameObject('/Width'): NumberObject(width),
                NameObject('/Height'): NumberObject(height),
                NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                NameObject('/BitsPerComponent'): NumberObject(8),
            })
            return writer._add_object(stream)

        resources = page[NameObject('/Resources')]
        resources[NameObject('/XObject')] = DictionaryObject({
            NameObject('/Im1'): image(os.urandom(100 * 100 * 3), 100, 100),
            NameObject('/Im2'): image(b'\xff' * (10 * 10 * 3), 10, 10),
        })
        font = writer._add_object(DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        }))
        resources[NameObject('/Font')] = DictionaryObject({NameObject('/F1'): font})
        contents = StreamObject()
        contents.set_data(
            b'BT /F1 12 Tf 40 260 Td (Click settings to sign in.) Tj ET '
            b'q 120 0 0 120 40 80 cm /Im1 Do Q q 10 0 0 10 20 20 cm /Im2 Do Q')
        page[NameObject('/Contents')] = writer._add_object(contents)
        with pdf.open('wb') as handle:
            writer.write(handle)

        kb = KnowledgeBase(self.root / 'knowledge', compiler=lambda *args: '', captioner=captioner)
        try:
            result = kb.add_file(pdf, SETTINGS)
            raw = next(hit for hit in kb.search('settings') if hit['kind'] == 'raw')
            self.assertIn('[[img:', raw['text'])
            self.assertIn('设置按钮', raw['text'])
            image_id = raw['text'].split('[[img:', 1)[1].split(']]', 1)[0]
            loaded = kb.doc_image(image_id)
            self.assertEqual(loaded['mime'], 'image/png')
            self.assertTrue(loaded['data'])
            self.assertEqual(len(list(kb.assets.iterdir())), 1)
            with self.assertRaises(KnowledgeError):
                kb.doc_image('../secret')
            self.assertTrue(kb.remove(result['id']))
            self.assertEqual(list(kb.assets.iterdir()), [])
        finally:
            kb.close()


if __name__ == '__main__':
    unittest.main()
