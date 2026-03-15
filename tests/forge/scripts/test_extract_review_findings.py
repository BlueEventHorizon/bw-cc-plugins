#!/usr/bin/env python3
"""
extract_review_findings.py のテスト

実行:
    python3 -m unittest tests.forge.scripts.test_extract_review_findings -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_review_findings import extract_findings, generate_plan_yaml, summarize

# ===========================================================================
# テストデータ
# ===========================================================================

REVIEW_MD_MIXED = """\
## AIレビュー結果

### 🔴致命的問題

1. **セッション検出が欠落**: 設計書で必須とされている残存セッション検出が実装されていない。
   - 箇所: plugins/forge/skills/review/SKILL.md:183
   - 参照: session_management_design.md
   - 修正案: find フローを追加

2. **[セッション削除に cleanup 未使用]**: rm -rf を直接使用している。
   - 箇所: plugins/forge/skills/review/SKILL.md:436

### 🟡品質問題

1. **report.html 案内だが show-report 呼び出しが未記述**: 案内テキストはあるが生成指示がない。
   - 箇所: plugins/forge/skills/present-findings/SKILL.md:255

### 🟢改善提案

1. **session_format.md への参照リンクがない**: インライン定義があるが正規スキーマへの参照がない。

### サマリー

- 🔴致命的: 2件
- 🟡品質: 1件
- 🟢改善: 1件
"""

REVIEW_MD_EMPTY = """\
## AIレビュー結果

### 🔴致命的問題

（なし）

### 🟡品質問題

（なし）

### 🟢改善提案

（なし）

### サマリー

- 🔴致命的: 0件
"""

REVIEW_MD_NO_MARKERS = """\
## レビュー結果

問題は見つかりませんでした。
"""

REVIEW_MD_CRITICAL_ONLY = """\
### 🔴致命的問題

1. **問題A**: 説明A
2. **問題B**: 説明B
3. **問題C**: 説明C
"""


# ===========================================================================
# extract_findings テスト
# ===========================================================================

class TestExtractFindings(unittest.TestCase):
    """extract_findings のテスト"""

    def test_mixed_severities(self):
        """🔴🟡🟢 混在のパース"""
        findings = extract_findings(REVIEW_MD_MIXED)
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[0]['severity'], 'critical')
        self.assertEqual(findings[0]['title'], 'セッション検出が欠落')
        self.assertEqual(findings[1]['severity'], 'critical')
        self.assertEqual(findings[1]['title'], 'セッション削除に cleanup 未使用')
        self.assertEqual(findings[2]['severity'], 'major')
        self.assertEqual(findings[3]['severity'], 'minor')

    def test_ids_sequential(self):
        """id は 1 からの連番"""
        findings = extract_findings(REVIEW_MD_MIXED)
        ids = [f['id'] for f in findings]
        self.assertEqual(ids, [1, 2, 3, 4])

    def test_all_pending(self):
        """全件 status: pending"""
        findings = extract_findings(REVIEW_MD_MIXED)
        for f in findings:
            self.assertEqual(f['status'], 'pending')
            self.assertEqual(f['fixed_at'], '')
            self.assertEqual(f['files_modified'], [])
            self.assertEqual(f['skip_reason'], '')

    def test_empty_review(self):
        """指摘0件"""
        findings = extract_findings(REVIEW_MD_EMPTY)
        self.assertEqual(findings, [])

    def test_no_markers(self):
        """マーカーなしの Markdown"""
        findings = extract_findings(REVIEW_MD_NO_MARKERS)
        self.assertEqual(findings, [])

    def test_critical_only(self):
        """🔴のみ3件"""
        findings = extract_findings(REVIEW_MD_CRITICAL_ONLY)
        self.assertEqual(len(findings), 3)
        for f in findings:
            self.assertEqual(f['severity'], 'critical')

    def test_bracket_title(self):
        """[角括弧付き] タイトルのパース"""
        findings = extract_findings(REVIEW_MD_MIXED)
        self.assertEqual(findings[1]['title'], 'セッション削除に cleanup 未使用')

    def test_idempotent(self):
        """冪等性"""
        f1 = extract_findings(REVIEW_MD_MIXED)
        f2 = extract_findings(REVIEW_MD_MIXED)
        self.assertEqual(f1, f2)

    def test_summary_section_ignored(self):
        """サマリーセクションの内容は抽出されない"""
        findings = extract_findings(REVIEW_MD_MIXED)
        titles = [f['title'] for f in findings]
        for t in titles:
            self.assertNotIn('致命的: 2件', t)


# ===========================================================================
# generate_plan_yaml テスト
# ===========================================================================

class TestGeneratePlanYaml(unittest.TestCase):
    """generate_plan_yaml のテスト"""

    def test_basic(self):
        """基本的な YAML 生成"""
        findings = extract_findings(REVIEW_MD_MIXED)
        yaml_text = generate_plan_yaml(findings)
        self.assertIn('items:', yaml_text)
        self.assertIn('id: 1', yaml_text)
        self.assertIn('severity: critical', yaml_text)
        self.assertIn('status: pending', yaml_text)

    def test_empty_findings(self):
        """0件の YAML 生成"""
        yaml_text = generate_plan_yaml([])
        self.assertEqual(yaml_text, 'items:\n')

    def test_title_with_colon(self):
        """タイトルにコロンが含まれる場合"""
        findings = [{'id': 1, 'severity': 'critical', 'title': 'review/SKILL.md: 問題',
                     'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': ''}]
        yaml_text = generate_plan_yaml(findings)
        self.assertIn('title: "review/SKILL.md: 問題"', yaml_text)

    def test_all_fields_present(self):
        """全フィールドが含まれる"""
        findings = extract_findings(REVIEW_MD_CRITICAL_ONLY)
        yaml_text = generate_plan_yaml(findings)
        for field in ('id:', 'severity:', 'title:', 'status:', 'fixed_at:', 'files_modified:', 'skip_reason:'):
            self.assertIn(field, yaml_text)


# ===========================================================================
# summarize テスト
# ===========================================================================

class TestSummarize(unittest.TestCase):
    """summarize のテスト"""

    def test_mixed(self):
        findings = extract_findings(REVIEW_MD_MIXED)
        s = summarize(findings)
        self.assertEqual(s['total'], 4)
        self.assertEqual(s['critical'], 2)
        self.assertEqual(s['major'], 1)
        self.assertEqual(s['minor'], 1)

    def test_empty(self):
        s = summarize([])
        self.assertEqual(s['total'], 0)
        self.assertEqual(s['critical'], 0)


# ===========================================================================
# CLI テスト
# ===========================================================================

class TestCLI(unittest.TestCase):
    """CLI インターフェースのテスト"""

    def test_basic_cli(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(REVIEW_MD_MIXED)
            f.flush()
            review_path = f.name

        output_path = review_path + '.plan.yaml'

        try:
            result = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), review_path, output_path],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0)
            data = json.loads(result.stdout)
            self.assertEqual(data['status'], 'ok')
            self.assertEqual(data['total'], 4)

            # plan.yaml が生成されている
            plan_content = Path(output_path).read_text(encoding='utf-8')
            self.assertIn('items:', plan_content)
            self.assertIn('severity: critical', plan_content)
        finally:
            Path(review_path).unlink(missing_ok=True)
            Path(output_path).unlink(missing_ok=True)

    def test_file_not_found_cli(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'),
             '/nonexistent.md', '/tmp/out.yaml'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)

    def test_no_args_cli(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py')],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
