#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feature_marker.py（差分 feature の一時マーカーの判定）のユニットテスト。

契約は DES-074「build_task_context.py の並行状態文書の分類契約」。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'forge',
    'scripts', 'doc_structure'
)
sys.path.insert(0, SCRIPT_DIR)
import feature_marker as fm

SCRIPT = os.path.join(SCRIPT_DIR, 'feature_marker.py')

FEATURE_NOTE = [
    'feature_note:',
    '  - この文書が、この文書の対象範囲における現在の仕様である。',
    '  - feature_type: temporary-feature を付与すること。',
]


def write_doc(directory, name, frontmatter=None, closed=True):
    """frontmatter の行を渡して、本文付きの文書を書く。None なら frontmatter なし。"""
    path = os.path.join(directory, name)
    lines = []
    if frontmatter is not None:
        lines.append('---')
        lines.extend(frontmatter)
        if closed:
            lines.append('---')
    lines.append('# 見出し')
    lines.append('本文')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


class TestClassifyFeatureMarker(unittest.TestCase):

    def _classify(self, frontmatter, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_doc(tmp, 'doc.md', frontmatter, **kwargs)
            return fm.classify_feature_marker(path)

    def test_no_frontmatter_has_no_marker(self):
        self.assertEqual(self._classify(None), (False, None))

    def test_frontmatter_without_feature_type_has_no_marker(self):
        self.assertEqual(self._classify(['doc_status: draft']), (False, None))

    def test_marker_is_detected(self):
        self.assertEqual(
            self._classify(['feature_type: temporary-feature']), (True, None))

    def test_key_order_does_not_change_the_result(self):
        """`feature_type` と他のキー・feature_note の順序が結果を変えない"""
        for frontmatter in (
            ['feature_type: temporary-feature'] + FEATURE_NOTE,
            FEATURE_NOTE + ['feature_type: temporary-feature'],
            ['doc_status: draft', 'feature_type: temporary-feature'],
            ['feature_type: temporary-feature', 'doc_status: draft'] + FEATURE_NOTE,
        ):
            self.assertEqual(self._classify(frontmatter), (True, None), frontmatter)

    def test_indented_feature_type_is_not_a_top_level_key(self):
        """`feature_note` 配下の行に現れる `feature_type:` を拾わない"""
        self.assertEqual(self._classify(FEATURE_NOTE), (False, None))

    def test_duplicate_feature_type_is_undecidable(self):
        result, error = self._classify([
            'feature_type: temporary-feature', 'feature_type: temporary-feature'])
        self.assertIsNone(result)
        self.assertIn('2 回現れ', error)

    def test_undefined_value_is_undecidable(self):
        result, error = self._classify(['feature_type: permanent'])
        self.assertIsNone(result)
        self.assertIn('未定義', error)

    def test_empty_value_is_undecidable(self):
        result, error = self._classify(['feature_type:'])
        self.assertIsNone(result)
        self.assertIn('未定義', error)

    def test_unclosed_frontmatter_is_undecidable(self):
        result, error = self._classify(
            ['feature_type: temporary-feature'], closed=False)
        self.assertIsNone(result)
        self.assertIn("終端 '---'", error)

    def test_missing_file_is_undecidable_not_no_marker(self):
        """読めないことを「マーカーなし」と同一視しない"""
        result, error = fm.classify_feature_marker('/nonexistent/doc.md')
        self.assertIsNone(result)
        self.assertIn('読み取りに失敗', error)

    def test_non_utf8_file_is_undecidable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'doc.md')
            with open(path, 'wb') as f:
                f.write(b'---\n\xff\xfe\n---\n')
            result, error = fm.classify_feature_marker(path)
        self.assertIsNone(result)
        self.assertIn('UTF-8', error)


class TestClassifyPaths(unittest.TestCase):

    def test_results_keep_the_given_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = write_doc(tmp, 'a.md', None)
            b = write_doc(tmp, 'b.md', ['feature_type: temporary-feature'])
            results, errors = fm.classify_paths([b, a])
        self.assertEqual(errors, [])
        self.assertEqual(
            [(os.path.basename(r['path']), r['has_marker']) for r in results],
            [('b.md', True), ('a.md', False)])

    def test_errors_are_collected_per_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = write_doc(tmp, 'ok.md', None)
            results, errors = fm.classify_paths([ok, '/nonexistent/x.md'])
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)


class TestCli(unittest.TestCase):

    def _run(self, *paths):
        return subprocess.run(
            [sys.executable, SCRIPT, '--paths', *paths],
            capture_output=True, text=True,
        )

    def test_any_marker_true_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = write_doc(tmp, 'a.md', None)
            b = write_doc(tmp, 'b.md', ['feature_type: temporary-feature'])
            proc = self._run(a, b)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['any_marker'])

    def test_no_marker_exits_0(self):
        """マーカーが無いことは、完了した結果である（終了コードは 0）"""
        with tempfile.TemporaryDirectory() as tmp:
            a = write_doc(tmp, 'a.md', None)
            proc = self._run(a)
        self.assertEqual(proc.returncode, 0)
        self.assertFalse(json.loads(proc.stdout)['any_marker'])

    def test_undecidable_exits_1_with_errors_array(self):
        proc = self._run('/nonexistent/x.md')
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertEqual(data['status'], 'error')
        self.assertIsInstance(data['errors'], list)
        self.assertEqual(len(data['errors']), 1)

    def test_dirs_finds_marker_documents_recursively(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, 'sub'))
            write_doc(tmp, 'a.md', None)
            marked = write_doc(
                os.path.join(tmp, 'sub'), 'b.md', ['feature_type: temporary-feature'])
            proc = subprocess.run(
                [sys.executable, SCRIPT, '--dirs', tmp],
                capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertTrue(data['any_marker'])
        self.assertEqual(data['marker_paths'], [marked])
        self.assertEqual(data['checked_count'], 2)
        self.assertNotIn('results', data)

    def test_dirs_without_marker_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_doc(tmp, 'a.md', None)
            proc = subprocess.run(
                [sys.executable, SCRIPT, '--dirs', tmp],
                capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertFalse(data['any_marker'])
        self.assertEqual(data['marker_paths'], [])

    def test_dirs_ignores_marker_text_in_the_body(self):
        """本文中の `feature_type: temporary-feature` の行を拾わない（grep と違う点）"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'doc.md')
            with open(path, 'w', encoding='utf-8') as f:
                f.write('# 見出し\nfeature_type: temporary-feature\n')
            proc = subprocess.run(
                [sys.executable, SCRIPT, '--dirs', tmp],
                capture_output=True, text=True)
        self.assertFalse(json.loads(proc.stdout)['any_marker'])

    def test_dirs_missing_directory_exits_1(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, '--dirs', '/nonexistent/dir'],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('ディレクトリが存在しません', json.loads(proc.stdout)['errors'][0])

    def test_dirs_malformed_document_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_doc(tmp, 'bad.md', ['feature_type: permanent'])
            proc = subprocess.run(
                [sys.executable, SCRIPT, '--dirs', tmp],
                capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)

    def test_missing_arguments_exits_2(self):
        """--paths も --dirs も無いときは引数エラー（終了コード 2）"""
        proc = subprocess.run(
            [sys.executable, SCRIPT], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)


if __name__ == '__main__':
    unittest.main()
