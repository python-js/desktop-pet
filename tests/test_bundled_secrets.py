"""Bundled Tavily key loader."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_pet import bundled_secrets


class BundledSecretsTests(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        with TemporaryDirectory() as folder:
            missing = Path(folder) / 'bundled_tavily.key'
            with patch.object(bundled_secrets, '_TAVILY_FILE', missing):
                self.assertEqual(bundled_secrets.bundled_tavily_key(), '')

    def test_reads_trimmed_key(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bundled_tavily.key'
            path.write_text('  tvly-real-key  \n', encoding='utf-8')
            with patch.object(bundled_secrets, '_TAVILY_FILE', path):
                self.assertEqual(bundled_secrets.bundled_tavily_key(), 'tvly-real-key')

    def test_skips_comment_header(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bundled_tavily.key'
            path.write_text('# note\n# more\ntvly-from-file\n', encoding='utf-8')
            with patch.object(bundled_secrets, '_TAVILY_FILE', path):
                self.assertEqual(bundled_secrets.bundled_tavily_key(), 'tvly-from-file')

    def test_rejects_example_placeholder(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'bundled_tavily.key'
            path.write_text('# header\ntvly-REPLACE_ME\n', encoding='utf-8')
            with patch.object(bundled_secrets, '_TAVILY_FILE', path):
                self.assertEqual(bundled_secrets.bundled_tavily_key(), '')
