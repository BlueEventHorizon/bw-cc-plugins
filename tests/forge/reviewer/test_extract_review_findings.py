#!/usr/bin/env python3
"""
extract_review_findings.py のテスト

実行:
    python3 -m unittest tests.forge.reviewer.test_extract_review_findings -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'skills' / 'reviewer' / 'scripts'
sys.path.insert(0, str(SCRIPTS_DIR))

from extract_review_findings import (
    extract_findings, generate_plan_yaml, summarize,
    extract_perspective_from_filename, deduplicate_findings,
    generate_review_md, run_session_dir_mode,
)

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

# issue 再現: reviewer が見出し形式で出力したケース
REVIEW_MD_HEADING_FORMAT = """\
### 🔴致命的問題

### 1. **APP-001 のフォーマット崩れ**: テーブル構文が不正でパースできない
- 箇所: APP-001_overview.md:44-48行目

### 2. **必須フィールドの欠落**: FNC-003 に必須の入力仕様が未定義
- 箇所: FNC-003_login.md:15

### 🟡品質問題

### 1. **用語の不統一**: 「ユーザー」と「利用者」が混在
- 箇所: 全体
"""

# h2 見出し形式
REVIEW_MD_H2_HEADING = """\
### 🔴致命的問題

## 1. **重大な問題**: 説明

### 🟢改善提案

## 1. **改善案**: 説明
"""

# 見出し形式と通常形式の混在
REVIEW_MD_MIXED_FORMAT = """\
### 🔴致命的問題

### 1. **見出し形式の問題**: 説明A
2. **通常形式の問題**: 説明B

### 🟡品質問題

1. **通常形式の品質問題**: 説明C
### 2. **見出し形式の品質問題**: 説明D
"""

# サマリー後に見出し形式の指摘がある（無視されるべき）
REVIEW_MD_FINDING_AFTER_SUMMARY = """\
### 🔴致命的問題

1. **正当な指摘**: 説明

### サマリー

- 🔴致命的: 1件

### 1. **サマリー後の偽指摘**: これは抽出されてはいけない
"""

# 英語 Summary
REVIEW_MD_ENGLISH_SUMMARY = """\
### 🔴致命的問題

1. **A problem**: description

### Summary

- 🔴Critical: 1
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

    def test_heading_format(self):
        """### 1. **問題名** 形式（issue 再現ケース）"""
        findings = extract_findings(REVIEW_MD_HEADING_FORMAT)
        self.assertEqual(len(findings), 3)
        self.assertEqual(findings[0]['severity'], 'critical')
        self.assertEqual(findings[0]['title'], 'APP-001 のフォーマット崩れ')
        self.assertEqual(findings[1]['severity'], 'critical')
        self.assertEqual(findings[1]['title'], '必須フィールドの欠落')
        self.assertEqual(findings[2]['severity'], 'major')
        self.assertEqual(findings[2]['title'], '用語の不統一')

    def test_h2_heading_format(self):
        """## 1. **問題名** 形式（h2 見出し）"""
        findings = extract_findings(REVIEW_MD_H2_HEADING)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]['severity'], 'critical')
        self.assertEqual(findings[0]['title'], '重大な問題')
        self.assertEqual(findings[1]['severity'], 'minor')
        self.assertEqual(findings[1]['title'], '改善案')

    def test_mixed_heading_and_normal_format(self):
        """見出し形式と通常形式の混在"""
        findings = extract_findings(REVIEW_MD_MIXED_FORMAT)
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[0]['title'], '見出し形式の問題')
        self.assertEqual(findings[0]['severity'], 'critical')
        self.assertEqual(findings[1]['title'], '通常形式の問題')
        self.assertEqual(findings[1]['severity'], 'critical')
        self.assertEqual(findings[2]['title'], '通常形式の品質問題')
        self.assertEqual(findings[2]['severity'], 'major')
        self.assertEqual(findings[3]['title'], '見出し形式の品質問題')
        self.assertEqual(findings[3]['severity'], 'major')
        # id は混在しても連番
        self.assertEqual([f['id'] for f in findings], [1, 2, 3, 4])

    def test_finding_after_summary_ignored(self):
        """サマリー後の見出し形式指摘は無視される"""
        findings = extract_findings(REVIEW_MD_FINDING_AFTER_SUMMARY)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['title'], '正当な指摘')

    def test_english_summary_resets_severity(self):
        """英語 Summary でも severity がリセットされる"""
        findings = extract_findings(REVIEW_MD_ENGLISH_SUMMARY)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]['title'], 'A problem')

    def test_empty_string(self):
        """空文字列入力"""
        findings = extract_findings("")
        self.assertEqual(findings, [])

    def test_location_extraction(self):
        """箇所（location）が正しく抽出される"""
        findings = extract_findings(REVIEW_MD_MIXED)
        self.assertEqual(findings[0]['location'], 'plugins/forge/skills/review/SKILL.md:183')
        self.assertEqual(findings[1]['location'], 'plugins/forge/skills/review/SKILL.md:436')
        self.assertEqual(findings[2]['location'], 'plugins/forge/skills/present-findings/SKILL.md:255')
        self.assertEqual(findings[3]['location'], '')  # 箇所なし


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

    def _make_finding(self, title):
        return [{'id': 1, 'severity': 'critical', 'title': title,
                 'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': ''}]

    def test_title_with_backslash_and_colon(self):
        """タイトルにバックスラッシュ+コロンが含まれる場合（エスケープ分岐）"""
        yaml_text = generate_plan_yaml(self._make_finding('C:\\path: エラー'))
        self.assertIn('C:\\\\path', yaml_text)

    def test_title_with_double_quote(self):
        """タイトルにダブルクォートが含まれる場合"""
        yaml_text = generate_plan_yaml(self._make_finding('値が "null" になる'))
        self.assertIn('\\"null\\"', yaml_text)

    def test_title_starting_with_brace(self):
        """タイトルが { で始まる場合"""
        yaml_text = generate_plan_yaml(self._make_finding('{key: value} の構文エラー'))
        self.assertIn('title: "{key', yaml_text)

    def test_title_starting_with_bracket(self):
        """タイトルが [ で始まる場合"""
        yaml_text = generate_plan_yaml(self._make_finding('[配列] の要素不足'))
        self.assertIn('title: "[配列]', yaml_text)

    def test_perspective_field(self):
        """単一 perspective フィールドが出力される"""
        findings = [{'id': 1, 'severity': 'critical', 'title': '問題',
                     'status': 'pending', 'fixed_at': '', 'files_modified': [],
                     'skip_reason': '', 'perspective': 'correctness'}]
        yaml_text = generate_plan_yaml(findings)
        self.assertIn('perspective: correctness', yaml_text)

    def test_perspectives_field(self):
        """複数 perspectives フィールド（配列）が出力される"""
        findings = [{'id': 1, 'severity': 'critical', 'title': '問題',
                     'status': 'pending', 'fixed_at': '', 'files_modified': [],
                     'skip_reason': '', 'perspectives': ['correctness', 'resilience']}]
        yaml_text = generate_plan_yaml(findings)
        self.assertIn('perspectives: [correctness, resilience]', yaml_text)
        self.assertNotIn('perspective:', yaml_text.replace('perspectives:', ''))

    def test_no_perspective_field_when_empty(self):
        """perspective が空文字列の場合はフィールドが出力されない"""
        findings = [{'id': 1, 'severity': 'critical', 'title': '問題',
                     'status': 'pending', 'fixed_at': '', 'files_modified': [],
                     'skip_reason': '', 'perspective': ''}]
        yaml_text = generate_plan_yaml(findings)
        self.assertNotIn('perspective:', yaml_text)


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
# CLI テスト（旧モード: 2引数）
# ===========================================================================

class TestCLI(unittest.TestCase):
    """CLI インターフェースのテスト（旧モード）"""

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


# ===========================================================================
# extract_perspective_from_filename テスト
# ===========================================================================

class TestExtractPerspectiveFromFilename(unittest.TestCase):
    """extract_perspective_from_filename のテスト"""

    def test_standard_name(self):
        self.assertEqual(extract_perspective_from_filename('review_correctness.md'), 'correctness')

    def test_hyphenated_name(self):
        self.assertEqual(extract_perspective_from_filename('review_project-rules.md'), 'project-rules')

    def test_underscored_name(self):
        self.assertEqual(extract_perspective_from_filename('review_my_perspective.md'), 'my_perspective')

    def test_generic(self):
        self.assertEqual(extract_perspective_from_filename('review_generic.md'), 'generic')

    def test_non_review_file(self):
        """review_ プレフィックスのないファイル"""
        self.assertEqual(extract_perspective_from_filename('plan.yaml'), '')

    def test_review_md_without_perspective(self):
        """review.md（perspective なし）"""
        self.assertEqual(extract_perspective_from_filename('review.md'), '')


# ===========================================================================
# deduplicate_findings テスト
# ===========================================================================

class TestDeduplicateFindings(unittest.TestCase):
    """deduplicate_findings のテスト"""

    def test_no_duplicates(self):
        """重複なしの場合はそのまま返す"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '問題A', 'location': 'file.py:10',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'correctness'},
            {'id': 2, 'severity': 'major', 'title': '問題B', 'location': 'file.py:20',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'resilience'},
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['perspective'], 'correctness')
        self.assertEqual(result[1]['perspective'], 'resilience')

    def test_duplicate_merged(self):
        """同一タイトル+箇所の重複が統合される"""
        findings = [
            {'id': 1, 'severity': 'major', 'title': '問題A', 'location': 'file.py:10',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'correctness'},
            {'id': 2, 'severity': 'critical', 'title': '問題A', 'location': 'file.py:10',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'resilience'},
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(len(result), 1)
        # severity は最高を採用
        self.assertEqual(result[0]['severity'], 'critical')
        # perspectives に両方が記録される
        self.assertIn('perspectives', result[0])
        self.assertEqual(result[0]['perspectives'], ['correctness', 'resilience'])
        # ID は振り直し
        self.assertEqual(result[0]['id'], 1)

    def test_different_location_not_merged(self):
        """同一タイトルでも箇所が異なれば統合しない"""
        findings = [
            {'id': 1, 'severity': 'major', 'title': '問題A', 'location': 'file.py:10',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'correctness'},
            {'id': 2, 'severity': 'major', 'title': '問題A', 'location': 'file.py:20',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'resilience'},
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(len(result), 2)

    def test_severity_max_adopted(self):
        """severity は最高を採用（minor < major < critical）"""
        findings = [
            {'id': 1, 'severity': 'minor', 'title': '問題', 'location': '',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'a'},
            {'id': 2, 'severity': 'major', 'title': '問題', 'location': '',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'b'},
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(result[0]['severity'], 'major')

    def test_triple_duplicate(self):
        """3つの perspective から同一指摘がある場合"""
        findings = [
            {'id': 1, 'severity': 'minor', 'title': '問題', 'location': 'x.py:1',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'a'},
            {'id': 2, 'severity': 'major', 'title': '問題', 'location': 'x.py:1',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'b'},
            {'id': 3, 'severity': 'critical', 'title': '問題', 'location': 'x.py:1',
             'status': 'pending', 'fixed_at': '', 'files_modified': [], 'skip_reason': '',
             'perspective': 'c'},
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['severity'], 'critical')
        self.assertEqual(result[0]['perspectives'], ['a', 'b', 'c'])


# ===========================================================================
# session_dir モード テスト
# ===========================================================================

# session_dir テスト用のレビューデータ
REVIEW_CORRECTNESS = """\
### 🔴致命的問題

1. **境界値チェック漏れ**: 配列の範囲外アクセスが発生する。
   - 箇所: utils.py:42

### 🟡品質問題

1. **戻り値の型が不統一**: None と空リストが混在。
   - 箇所: utils.py:88
"""

REVIEW_RESILIENCE = """\
### 🔴致命的問題

1. **入力バリデーション不足**: ユーザー入力が未検証のまま使用されている。
   - 箇所: handler.py:15

### 🟡品質問題

1. **境界値チェック漏れ**: 配列の範囲外アクセスが発生する。
   - 箇所: utils.py:42

### 🟢改善提案

1. **エラーメッセージの改善**: ユーザーにとって不明瞭。
"""

REVIEW_GENERIC = """\
### 🔴致命的問題

1. **事実の誤り**: ドキュメントの記述が実装と異なる。
   - 箇所: README.md:10

### 🟢改善提案

1. **冗長な記述**: 同じ内容が複数箇所に重複している。
"""


class TestSessionDirMode(unittest.TestCase):
    """session_dir モードのテスト"""

    def setUp(self):
        """テスト用の一時 session_dir を作成"""
        self.tmpdir = tempfile.mkdtemp()
        self.session_path = Path(self.tmpdir)

    def tearDown(self):
        """一時ディレクトリを削除"""
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_review(self, filename, content):
        (self.session_path / filename).write_text(content, encoding='utf-8')

    def test_basic_multi_file(self):
        """session_dir モード基本テスト: 2ファイル → 統合 plan.yaml + review.md"""
        self._write_review('review_correctness.md', REVIEW_CORRECTNESS)
        self._write_review('review_resilience.md', REVIEW_RESILIENCE)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['files_processed'], 2)

        # plan.yaml が生成されている
        plan_path = self.session_path / 'plan.yaml'
        self.assertTrue(plan_path.exists())
        plan_content = plan_path.read_text(encoding='utf-8')
        self.assertIn('items:', plan_content)

        # review.md が生成されている
        review_path = self.session_path / 'review.md'
        self.assertTrue(review_path.exists())
        review_content = review_path.read_text(encoding='utf-8')
        self.assertIn('統合レビュー結果', review_content)

    def test_perspective_tags(self):
        """perspective タグ付与テスト: ファイル名から perspective 名が正しく抽出される"""
        self._write_review('review_correctness.md', REVIEW_CORRECTNESS)
        self._write_review('review_resilience.md', REVIEW_RESILIENCE)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        # correctness の指摘に perspective が付いている
        self.assertIn('perspective: correctness', plan_content)
        # resilience の指摘に perspective が付いている
        self.assertIn('perspective: resilience', plan_content)

    def test_cross_file_sequential_ids(self):
        """ファイル間通し番号テスト: 複数ファイルで ID が連番"""
        self._write_review('review_correctness.md', REVIEW_CORRECTNESS)
        self._write_review('review_resilience.md', REVIEW_RESILIENCE)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        # ID が連番であることを確認（重複除去後の再採番）
        import re
        ids = [int(m) for m in re.findall(r'id: (\d+)', plan_content)]
        self.assertEqual(ids, list(range(1, len(ids) + 1)))

    def test_deduplication(self):
        """重複除去テスト: 同一タイトル+箇所の指摘が統合される"""
        self._write_review('review_correctness.md', REVIEW_CORRECTNESS)
        self._write_review('review_resilience.md', REVIEW_RESILIENCE)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        data = json.loads(result.stdout)
        # 「境界値チェック漏れ」が両方に同一タイトル+同一箇所で存在 → 1つに統合
        self.assertGreater(data['duplicates_removed'], 0)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        # 統合された指摘には perspectives フィールドがある
        self.assertIn('perspectives: [correctness, resilience]', plan_content)

    def test_partial_failure(self):
        """partial-failure テスト: 一部ファイルが空でも他のファイルが正常処理される"""
        self._write_review('review_correctness.md', REVIEW_CORRECTNESS)
        self._write_review('review_resilience.md', '')  # 空ファイル

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['files_processed'], 1)
        self.assertEqual(data['files_failed'], 1)
        self.assertGreater(data['total'], 0)

    def test_all_failure(self):
        """all-failure テスト: review_*.md が0件の場合のエラーハンドリング"""
        # review_*.md が存在しない
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)
        error_data = json.loads(result.stderr)
        self.assertEqual(error_data['status'], 'error')

    def test_all_empty_failure(self):
        """全ファイルが空の場合もエラー"""
        self._write_review('review_correctness.md', '')
        self._write_review('review_resilience.md', '')

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)

    def test_generic_single_file(self):
        """generic テスト: review_generic.md 単一ファイルの場合（perspectives 配列なし）"""
        self._write_review('review_generic.md', REVIEW_GENERIC)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['files_processed'], 1)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        # 単一 perspective なので perspective フィールド（perspectives 配列ではない）
        self.assertIn('perspective: generic', plan_content)
        self.assertNotIn('perspectives:', plan_content)

    def test_nonexistent_directory(self):
        """存在しないディレクトリの場合のエラー"""
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), '/nonexistent/dir'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 1)

    def test_alphabetical_order(self):
        """ファイルはアルファベット順に処理される"""
        # z_ が先に作成されても、a_ が先に処理されるべき
        self._write_review('review_z_last.md', """\
### 🟢改善提案

1. **最後の指摘**: 説明
""")
        self._write_review('review_a_first.md', """\
### 🔴致命的問題

1. **最初の指摘**: 説明
""")

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'), self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        # a_first の指摘が先に来る（ID=1）
        lines = plan_content.split('\n')
        first_title_idx = next(i for i, l in enumerate(lines) if 'title:' in l)
        self.assertIn('最初の指摘', lines[first_title_idx])


# ===========================================================================
# generate_review_md テスト
# ===========================================================================

class TestGenerateReviewMd(unittest.TestCase):
    """generate_review_md のテスト"""

    def test_basic_output(self):
        """基本的な review.md 生成"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '問題A', 'location': 'file.py:10',
             'perspective': 'correctness'},
            {'id': 2, 'severity': 'minor', 'title': '問題B', 'location': '',
             'perspective': 'resilience'},
        ]
        md = generate_review_md(findings)
        self.assertIn('# 統合レビュー結果', md)
        self.assertIn('🔴致命的問題', md)
        self.assertIn('問題A', md)
        self.assertIn('[correctness]', md)
        self.assertIn('箇所: file.py:10', md)
        self.assertIn('🟢改善提案', md)
        self.assertIn('問題B', md)

    def test_empty_findings(self):
        """0件の場合"""
        md = generate_review_md([])
        self.assertIn('（なし）', md)

    def test_perspectives_display(self):
        """複数 perspectives の表示"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '問題',
             'location': '', 'perspectives': ['correctness', 'resilience']},
        ]
        md = generate_review_md(findings)
        self.assertIn('[correctness, resilience]', md)

    def test_bodies_by_perspective_rendered_for_duplicates(self):
        """重複項目(perspectives 複数)は各 perspective の body が併記される。"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '共通問題',
             'location': 'x.py:1',
             'perspectives': ['logic', 'resilience'],
             'bodies_by_perspective': {
                 'logic': '1. **共通問題**: logic の視点での説明\n   - 根拠: ルールA',
                 'resilience': '1. **共通問題**: resilience の視点での説明\n   - 根拠: ルールB',
             }},
        ]
        md = generate_review_md(findings)
        self.assertIn('#### logic の視点', md)
        self.assertIn('#### resilience の視点', md)
        self.assertIn('logic の視点での説明', md)
        self.assertIn('resilience の視点での説明', md)
        self.assertIn('ルールA', md)
        self.assertIn('ルールB', md)

    def test_bodies_not_rendered_for_single_perspective(self):
        """単独 perspective の場合は bodies_by_perspective の併記は行われない。"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '単独問題',
             'location': 'y.py:1', 'perspective': 'logic',
             'body': '1. **単独問題**: 説明'},
        ]
        md = generate_review_md(findings)
        # 併記見出し(#### の perspective 見出し)は出力されない
        self.assertNotIn('#### logic の視点', md)

    def test_bodies_preserves_perspective_order(self):
        """bodies の出力順は perspectives リストの順序に従う。"""
        findings = [
            {'id': 1, 'severity': 'critical', 'title': '共通',
             'location': '',
             'perspectives': ['resilience', 'alignment', 'logic'],
             'bodies_by_perspective': {
                 'logic': 'body-logic',
                 'alignment': 'body-alignment',
                 'resilience': 'body-resilience',
             }},
        ]
        md = generate_review_md(findings)
        idx_r = md.index('#### resilience の視点')
        idx_a = md.index('#### alignment の視点')
        idx_l = md.index('#### logic の視点')
        self.assertLess(idx_r, idx_a)
        self.assertLess(idx_a, idx_l)


# ===========================================================================
# body 抽出テスト
# ===========================================================================

REVIEW_MD_WITH_BODY = """\
### 🔴致命的問題

1. **問題A**: 説明A
   - 箇所: file.py:10
   - なぜ問題か: ルール違反
   - 修正案: 正しい書き方に変更
2. **問題B**: 説明B
   - 箇所: file.py:20

### 🟢改善提案

1. **改善案**: 改善説明
"""


class TestExtractFindingsBody(unittest.TestCase):
    """body 抽出のテスト"""

    def test_body_includes_finding_details(self):
        """body には該当指摘の複数行の詳細が含まれる。"""
        findings = extract_findings(REVIEW_MD_WITH_BODY)
        self.assertEqual(len(findings), 3)
        body_a = findings[0]['body']
        self.assertIn('問題A', body_a)
        self.assertIn('なぜ問題か', body_a)
        self.assertIn('修正案', body_a)
        # 次の指摘 "問題B" は含まれない
        self.assertNotIn('問題B', body_a)

    def test_body_stops_at_next_severity_section(self):
        """body は次の severity セクション直前で終わる。"""
        findings = extract_findings(REVIEW_MD_WITH_BODY)
        body_b = findings[1]['body']
        self.assertIn('問題B', body_b)
        # 次のセクションの改善案は含まれない
        self.assertNotIn('改善案', body_b)
        self.assertNotIn('改善提案', body_b)

    def test_body_trailing_blank_lines_stripped(self):
        """body の末尾空行は除去されている。"""
        findings = extract_findings(REVIEW_MD_WITH_BODY)
        for f in findings:
            self.assertFalse(f['body'].endswith('\n'))
            self.assertFalse(f['body'].endswith('\n\n'))


# ===========================================================================
# deduplicate_findings の bodies_by_perspective テスト
# ===========================================================================

class TestDeduplicateBodies(unittest.TestCase):
    """deduplicate_findings の bodies_by_perspective 機能のテスト"""

    def _finding(self, title, location, perspective, body, severity='major'):
        return {
            'id': 0, 'severity': severity, 'title': title, 'location': location,
            'status': 'pending', 'fixed_at': '', 'files_modified': [],
            'skip_reason': '', 'perspective': perspective, 'body': body,
        }

    def test_duplicate_preserves_both_bodies(self):
        """重複項目は各 perspective の body を bodies_by_perspective に保持する。"""
        findings = [
            self._finding('問題', 'f.py:1', 'logic', 'logic の原文'),
            self._finding('問題', 'f.py:1', 'resilience', 'resilience の原文'),
        ]
        result = deduplicate_findings(findings)
        self.assertEqual(len(result), 1)
        bodies = result[0]['bodies_by_perspective']
        self.assertEqual(bodies['logic'], 'logic の原文')
        self.assertEqual(bodies['resilience'], 'resilience の原文')

    def test_triple_duplicate_all_bodies(self):
        """3 perspective の重複で 3 つの body が保持される。"""
        findings = [
            self._finding('問題', 'x.py:1', 'a', 'body-a'),
            self._finding('問題', 'x.py:1', 'b', 'body-b'),
            self._finding('問題', 'x.py:1', 'c', 'body-c'),
        ]
        result = deduplicate_findings(findings)
        bodies = result[0]['bodies_by_perspective']
        self.assertEqual(len(bodies), 3)
        self.assertEqual(bodies['a'], 'body-a')
        self.assertEqual(bodies['b'], 'body-b')
        self.assertEqual(bodies['c'], 'body-c')

    def test_non_duplicate_no_bodies_by_perspective(self):
        """重複していない finding には bodies_by_perspective が付与されない。"""
        findings = [
            self._finding('問題A', 'f.py:1', 'logic', 'body-a'),
            self._finding('問題B', 'f.py:2', 'logic', 'body-b'),
        ]
        result = deduplicate_findings(findings)
        for f in result:
            self.assertNotIn('bodies_by_perspective', f)


# ===========================================================================
# --review-only モードのテスト
# ===========================================================================

class TestReviewOnlyMode(unittest.TestCase):
    """--review-only モードのテスト"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_path = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, filename, content):
        (self.session_path / filename).write_text(content, encoding='utf-8')

    def test_review_only_does_not_overwrite_plan_yaml(self):
        """--review-only は既存 plan.yaml を書き換えない。"""
        self._write('review_correctness.md', REVIEW_CORRECTNESS)
        # 既存 plan.yaml を用意(evaluator 判定情報を含む想定)
        existing_plan = """\
items:
  - id: 1
    severity: critical
    title: "境界値チェック漏れ"
    status: pending
    recommendation: fix
    auto_fixable: true
    reason: "evaluator 判定理由"
"""
        (self.session_path / 'plan.yaml').write_text(existing_plan, encoding='utf-8')

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'),
             self.tmpdir, '--review-only'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # plan.yaml は上書きされていない
        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        self.assertIn('recommendation: fix', plan_content)
        self.assertIn('evaluator 判定理由', plan_content)

        # review.md は再生成されている
        self.assertTrue((self.session_path / 'review.md').exists())

        data = json.loads(result.stdout)
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['review_only'])

    def test_normal_mode_still_writes_plan_yaml(self):
        """通常モード(--review-only なし)では plan.yaml が書き換えられる。"""
        self._write('review_correctness.md', REVIEW_CORRECTNESS)

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'),
             self.tmpdir],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0)

        plan_content = (self.session_path / 'plan.yaml').read_text(encoding='utf-8')
        self.assertIn('items:', plan_content)
        # 判定フィールドは含まれない(reviewer 段階では未生成)
        self.assertNotIn('recommendation:', plan_content)

        data = json.loads(result.stdout)
        self.assertFalse(data['review_only'])

    def test_review_only_renders_bodies_in_review_md(self):
        """--review-only で統合 review.md に重複項目の各 perspective の body が併記される。"""
        self._write('review_correctness.md', """\
### 🔴致命的問題

1. **境界値チェック漏れ**: correctness の視点で説明
   - 箇所: utils.py:42
   - 根拠: ルール AA
""")
        self._write('review_resilience.md', """\
### 🔴致命的問題

1. **境界値チェック漏れ**: resilience の視点で説明
   - 箇所: utils.py:42
   - 根拠: ルール BB
""")

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'),
             self.tmpdir, '--review-only'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        review_md = (self.session_path / 'review.md').read_text(encoding='utf-8')
        self.assertIn('#### correctness の視点', review_md)
        self.assertIn('#### resilience の視点', review_md)
        self.assertIn('correctness の視点で説明', review_md)
        self.assertIn('resilience の視点で説明', review_md)
        self.assertIn('ルール AA', review_md)
        self.assertIn('ルール BB', review_md)

    def test_raw_md_files_are_excluded_from_glob(self):
        """`review_*.raw.md` は glob から除外される(evaluator バックアップを二重処理しない)。"""
        # evaluator 書き換え後の最終系と、reviewer 原文バックアップの両方を配置
        self._write('review_logic.md', """\
### 🔴致命的問題

1. **整形後タイトル**: evaluator が書き換えた内容
   - 箇所: file.py:10
""")
        self._write('review_logic.raw.md', """\
### 🔴致命的問題

1. **原文のタイトル**: reviewer 原文
   - 箇所: file.py:10
""")

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / 'extract_review_findings.py'),
             self.tmpdir, '--review-only'],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # .raw.md は処理されないため、total は 1 件のみ
        data = json.loads(result.stdout)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['files_processed'], 1)

        review_md = (self.session_path / 'review.md').read_text(encoding='utf-8')
        self.assertIn('整形後タイトル', review_md)
        self.assertNotIn('原文のタイトル', review_md)


# ===========================================================================
# severity 切替時の body 上書きバグ(回帰テスト)
# ===========================================================================

class TestExtractFindingsSeverityBoundary(unittest.TestCase):
    """severity セクション切替後の余分な本文行が、前の finding の body を
    上書きしてしまうバグの回帰テスト。"""

    def test_body_not_overwritten_by_inter_section_text(self):
        """severity セクション間に説明文があっても、前 finding の body は保たれる。"""
        content = """\
### 🔴致命的問題

1. **致命的 A**: 問題 A の説明
   - 箇所: a.py:1
   - 根拠: ルール X
   - 修正案: A を直す

### 🟡品質問題

以下は品質に関する指摘です。全体で確認すべき事項を含みます。
書き換えは慎重に行ってください。

1. **品質 B**: 問題 B の説明
   - 箇所: b.py:2
"""
        findings = extract_findings(content)
        self.assertEqual(len(findings), 2)

        # 致命的 A の body は A の内容を保持しており、
        # 「以下は品質に関する指摘です」等の intro 文で上書きされていない
        body_a = findings[0]['body']
        self.assertIn('致命的 A', body_a)
        self.assertIn('問題 A の説明', body_a)
        self.assertIn('ルール X', body_a)
        self.assertNotIn('品質に関する指摘', body_a)
        self.assertNotIn('書き換えは慎重に', body_a)

        # 品質 B の body は B の内容を持つ
        body_b = findings[1]['body']
        self.assertIn('品質 B', body_b)
        self.assertIn('問題 B の説明', body_b)

    def test_body_closed_flag_not_leaked(self):
        """内部フラグ _body_closed は呼び出し元に漏れない。"""
        content = """\
### 🔴致命的問題

1. **A**: 説明
   - 箇所: f.py:1

### 🟡品質問題

中間の説明文

1. **B**: 説明
   - 箇所: f.py:2
"""
        findings = extract_findings(content)
        for f in findings:
            self.assertNotIn('_body_closed', f)


if __name__ == '__main__':
    unittest.main()
