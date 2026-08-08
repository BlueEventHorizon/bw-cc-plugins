#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_toc_checksums.py のユニットテスト。

実行:
  python3 -m unittest tests.forge.doc_structure.test_generate_toc_checksums -v
"""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from forge.helpers import _FsTestCase

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / 'plugins' / 'forge' / 'scripts' / 'doc_structure' / 'generate_toc_checksums.py'
)

DOC_STRUCTURE_YAML = """\
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""


class TestGenerateTocChecksums(_FsTestCase):

    def setUp(self):
        super().setUp()
        self._write_file('doc_structure.yaml', DOC_STRUCTURE_YAML)
        self._write_file('docs/rules/a.md', 'A content')
        self._write_file('docs/rules/b.md', 'B content')

    def _run(self, extra_args=None):
        cmd = [
            sys.executable, str(SCRIPT_PATH),
            '--doc-structure', 'doc_structure.yaml',
            '--project-root', str(self.tmpdir),
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_stdout_output_contains_sha256_of_each_file(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

        expected_a = hashlib.sha256(b'A content').hexdigest()
        expected_b = hashlib.sha256(b'B content').hexdigest()

        self.assertIn(f'docs/rules/a.md: {expected_a}', result.stdout)
        self.assertIn(f'docs/rules/b.md: {expected_b}', result.stdout)
        self.assertIn('file_count: 2', result.stdout)

    def test_output_is_deterministic_across_runs(self):
        first = self._run().stdout
        second = self._run().stdout
        self.assertEqual(first, second)

    def test_content_change_produces_different_checksum(self):
        before = self._run().stdout
        self._write_file('docs/rules/a.md', 'A content changed')
        after = self._run().stdout
        self.assertNotEqual(before, after)

    def test_output_file_written_when_output_arg_given(self):
        result = self._run(['--output', 'checksums.yaml'])
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['file_count'], 2)

        output_path = self.tmpdir / 'checksums.yaml'
        self.assertTrue(output_path.exists())
        self.assertIn('checksums:', output_path.read_text(encoding='utf-8'))

    def test_missing_doc_structure_file_is_reported_as_error(self):
        cmd = [
            sys.executable, str(SCRIPT_PATH),
            '--doc-structure', 'nonexistent.yaml',
            '--project-root', str(self.tmpdir),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'error')
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
