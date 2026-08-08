#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_toc.py のユニットテスト。

ToC のコピーと checksums 生成を単一操作に統合したことで、片方だけが
実行される事態（PR #172 の再発）を防げているかを検証する。

実行:
  python3 -m unittest tests.forge.doc_structure.test_finalize_toc -v
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
    / 'plugins' / 'forge' / 'scripts' / 'doc_structure' / 'finalize_toc.py'
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

TOC_SRC_CONTENT = "metadata:\n  key: test\ndocs:\n  docs/rules/a.md:\n    title: A\n"


class TestFinalizeToc(_FsTestCase):

    def setUp(self):
        super().setUp()
        self._write_file('doc_structure.yaml', DOC_STRUCTURE_YAML)
        self._write_file('docs/rules/a.md', 'A content')
        self._write_file('docs/rules/b.md', 'B content')
        self._write_file('toc_src.yaml', TOC_SRC_CONTENT)

    def _run(self, extra_args=None):
        cmd = [
            sys.executable, str(SCRIPT_PATH),
            '--doc-structure', 'doc_structure.yaml',
            '--project-root', str(self.tmpdir),
            '--toc-src', 'toc_src.yaml',
            '--toc-dest', 'toc_dest.yaml',
            '--checksums-output', 'checksums.yaml',
        ]
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_copies_toc_and_writes_checksums_in_one_call(self):
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(payload['file_count'], 2)

        toc_dest = self.tmpdir / 'toc_dest.yaml'
        self.assertTrue(toc_dest.exists())
        self.assertEqual(toc_dest.read_text(encoding='utf-8'), TOC_SRC_CONTENT)

        checksums_path = self.tmpdir / 'checksums.yaml'
        self.assertTrue(checksums_path.exists())
        expected_a = hashlib.sha256(b'A content').hexdigest()
        self.assertIn(f'docs/rules/a.md: {expected_a}', checksums_path.read_text(encoding='utf-8'))

    def test_missing_toc_src_is_reported_as_error_without_writing_checksums(self):
        result = subprocess.run(
            [
                sys.executable, str(SCRIPT_PATH),
                '--doc-structure', 'doc_structure.yaml',
                '--project-root', str(self.tmpdir),
                '--toc-src', 'nonexistent_toc.yaml',
                '--toc-dest', 'toc_dest.yaml',
                '--checksums-output', 'checksums.yaml',
            ],
            capture_output=True, text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload['status'], 'error')
        self.assertEqual(result.returncode, 1)

        # checksums だけが単独で書き出されていないことを確認
        # （「片方だけ実行される」失敗モードが再現していないこと）
        self.assertFalse((self.tmpdir / 'checksums.yaml').exists())
        self.assertFalse((self.tmpdir / 'toc_dest.yaml').exists())

    def test_output_is_deterministic_across_runs(self):
        first = self._run()
        toc_dest = self.tmpdir / 'toc_dest.yaml'
        checksums_path = self.tmpdir / 'checksums.yaml'
        first_toc = toc_dest.read_text(encoding='utf-8')
        first_checksums = checksums_path.read_text(encoding='utf-8')

        second = self._run()
        self.assertEqual(first.returncode, 0)
        self.assertEqual(second.returncode, 0)
        self.assertEqual(first_toc, toc_dest.read_text(encoding='utf-8'))
        self.assertEqual(first_checksums, checksums_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
