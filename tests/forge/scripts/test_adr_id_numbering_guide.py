#!/usr/bin/env python3
"""回帰防止テスト: ADR の ID 採番ガイドのカバレッジ (Issue #123)。

Issue #123 の背景: forge で ADR（Architecture Decision Record）を新規作成する際の
ID 採番手順がスキル・文書に明記されておらず、並行ブランチで同一 `ADR-003` が別内容で
衝突した。採番スクリプト `scan_spec_ids.py` は任意プレフィックスを汎用的に扱えるため
(ADR も同様に動作する)、修正はドキュメント/ワークフロー側で完結する。

本テストは Issue #123 の修正が後退しないことを検証する:

- スクリプト挙動: scan_spec_ids が `ADR` プレフィックスを正しく採番する。
  ADR を設計ディレクトリ配下に置く限り、ADR 専用ディレクトリが scan 対象になくても
  既存 ADR を検出できること (Issue #123 の「ADR-001〜004 使用済み → ADR-005」を再現)。
- 文書カバレッジ: ID 体系の正本 (spec_format.md)・採番スキル (next-spec-id)・
  生成スキル (start-design)・設計原則 (design_principles_spec) の各層に
  「ADR は next-spec-id で採番する」ガイドが存在すること。

実行:
  python3 -m unittest tests.forge.scripts.test_adr_id_numbering_guide -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
FORGE_DOCS = REPO_ROOT / "plugins" / "forge" / "docs"
SKILLS_DIR = REPO_ROOT / "plugins" / "forge" / "skills"

sys.path.insert(0, str(SKILLS_DIR / "next-spec-id" / "scripts"))

from scan_spec_ids import scan_spec_ids  # noqa: E402


def _read(path: Path) -> str:
    if not path.is_file():
        raise unittest.SkipTest(f"必須ファイルが存在しない: {path}")
    return path.read_text(encoding="utf-8")


class TestADRScanBehavior(unittest.TestCase):
    """scan_spec_ids が ADR プレフィックスを正しく扱うこと (修正不要の根拠)。"""

    @patch("scan_spec_ids.get_scan_branches")
    @patch("scan_spec_ids.detect_base_branch")
    @patch("scan_spec_ids._run_git")
    @patch("scan_spec_ids.get_specs_root_dirs")
    def test_adr_numbering_reproduces_issue_123(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """ADR-001〜004 使用済みのとき次は ADR-005 を返す (Issue #123 の再現)。

        ADR は設計ディレクトリ (specs/design/) 配下に置かれ、専用 adr ディレクトリは
        scan 対象に含まれない。それでも git スキャンが ADR を検出することを確認する。
        """
        # scan 対象は design ディレクトリのみ (ADR 専用ディレクトリは未定義)
        mock_dirs.return_value = ["specs/design/"]
        mock_base.return_value = "develop"
        mock_branches.return_value = ["develop"]

        def git_side_effect(*args, cwd=None):
            if args[0] == "ls-tree":
                # 設計書と ADR が同じ design ディレクトリに同居している
                return (
                    "specs/design/DES-001_a_design.md\n"
                    "specs/design/ADR-001_b.md\n"
                    "specs/design/ADR-002_c.md\n"
                    "specs/design/ADR-003_d.md\n"
                    "specs/design/ADR-004_e.md"
                )
            return ""

        mock_git.side_effect = git_side_effect

        result = scan_spec_ids("ADR", "/tmp/project", cwd="/tmp/project")

        self.assertEqual(result["next_id"], "ADR-005")
        self.assertEqual(result["prefix"], "ADR")
        self.assertEqual(result["max_number"], 4)
        self.assertEqual(result["ids_found"], 4)

    @patch("scan_spec_ids.get_scan_branches")
    @patch("scan_spec_ids.detect_base_branch")
    @patch("scan_spec_ids._run_git")
    @patch("scan_spec_ids.get_specs_root_dirs")
    def test_adr_detects_cross_branch_duplicates(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """並行ブランチで同一 ADR 番号が別内容で存在する場合に duplicates として検出する。

        これは Issue #123 で実際に起きた衝突 (ブランチ A と B が双方 ADR-003 を作成) を
        採番時に警告できることを保証する。
        """
        mock_dirs.return_value = ["specs/design/"]
        mock_base.return_value = "develop"
        mock_branches.return_value = ["feature/a", "feature/b"]

        def git_side_effect(*args, cwd=None):
            if args[0] == "ls-tree":
                branch = args[3]
                if branch == "feature/a":
                    return "specs/design/ADR-003_github_orchestrator.md"
                if branch == "feature/b":
                    return "specs/design/ADR-003_notification_state.md"
            return ""

        mock_git.side_effect = git_side_effect

        result = scan_spec_ids("ADR", "/tmp/project", cwd="/tmp/project")

        duplicate_ids = {d["id"] for d in result["duplicates"]}
        self.assertIn("ADR-003", duplicate_ids)


class TestADRDocCoverage(unittest.TestCase):
    """ADR 採番ガイドが各層の文書に存在し続けること (Issue #123 の構造的欠落の回帰防止)。"""

    def test_spec_format_design_catalog_includes_adr(self):
        """ID 体系の正本 spec_format.md の設計ID カタログに ADR が登録されていること。"""
        content = _read(FORGE_DOCS / "spec_format.md")
        self.assertIn("## 設計ID カタログ", content)
        self.assertIn(
            "`ADR-xxx`",
            content,
            "spec_format.md 設計ID カタログに ADR prefix の行がない "
            "(ADR が未定義 prefix のまま残存)",
        )
        self.assertIn(
            "next-spec-id",
            content,
            "spec_format.md が ADR 採番に next-spec-id を指していない",
        )

    def test_next_spec_id_skill_mentions_adr(self):
        """next-spec-id/SKILL.md の description と CLI 例示が ADR を含むこと。"""
        content = _read(SKILLS_DIR / "next-spec-id" / "SKILL.md")
        self.assertIn(
            "ADR",
            content,
            "next-spec-id/SKILL.md が ADR を例示・説明していない",
        )
        # CLI 例示に ADR プレフィックスの実行例があること
        self.assertIn(
            '"$SCRIPT" ADR',
            content,
            "next-spec-id/SKILL.md の CLI 例示に ADR 採番の実行例がない",
        )

    def test_start_design_instructs_adr_numbering(self):
        """start-design/SKILL.md が ADR 作成時の next-spec-id 採番を指示していること。"""
        content = _read(SKILLS_DIR / "start-design" / "SKILL.md")
        self.assertIn("ADR", content, "start-design/SKILL.md が ADR に言及していない")
        # 採番スクリプトを ADR プレフィックスで呼ぶ指示があること
        self.assertIn(
            'SCAN_SCRIPT" ADR',
            content,
            "start-design/SKILL.md に ADR を next-spec-id で採番する手順がない",
        )

    def test_design_principles_instructs_adr_numbering(self):
        """design_principles_spec.md が ADR 採番ルールと git スキャン注記を持つこと。"""
        content = _read(FORGE_DOCS / "design_principles_spec.md")
        self.assertIn("ADR", content)
        self.assertIn(
            "next-spec-id",
            content,
            "design_principles_spec.md が ADR 採番に next-spec-id を指していない",
        )
        # ADR 専用ディレクトリが .doc_structure.yaml になくても検出できる注記
        self.assertIn(
            ".doc_structure.yaml",
            content,
            "design_principles_spec.md に ADR の git スキャン検出に関する注記がない",
        )


if __name__ == "__main__":
    unittest.main()
