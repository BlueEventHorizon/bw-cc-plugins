#!/usr/bin/env python3
"""回帰防止テスト: ADR の ID 採番ガイドのカバレッジ。

背景: forge で ADR（Architecture Decision Record）を新規作成する際の
ID 採番手順がスキル・文書に明記されておらず、並行ブランチで同一 `ADR-003` が別内容で
衝突した。採番スクリプト `scan_spec_ids.py` は任意プレフィックスを汎用的に扱えるため
(ADR も同様に動作する)、修正はドキュメント/ワークフロー側で完結する。

本テストはこの修正が後退しないことを検証する:

- スクリプト挙動: scan_spec_ids が `ADR` プレフィックスを正しく採番する。
  ADR は feature ごとの adr/ ディレクトリに置かれ、複数の feature にまたがっても
  既存の ADR ファイルを検出できること (「ADR-001〜004 使用済み → ADR-005」を再現)。
実行:
  python3 -m unittest tests.forge.scripts.test_adr_id_numbering_guide -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / "plugins" / "forge" / "skills"

sys.path.insert(0, str(SKILLS_DIR / "next-spec-id" / "scripts"))

from scan_spec_ids import scan_spec_ids  # noqa: E402


class TestADRScanBehavior(unittest.TestCase):
    """scan_spec_ids が ADR プレフィックスを正しく扱うこと (修正不要の根拠)。"""

    @patch("scan_spec_ids.get_scan_branches")
    @patch("scan_spec_ids.detect_base_branch")
    @patch("scan_spec_ids._run_git")
    @patch("scan_spec_ids.get_specs_root_dirs")
    def test_adr_numbering_reproduces_issue_123(
        self, mock_dirs, mock_git, mock_base, mock_branches
    ):
        """ADR-001〜004 使用済みのとき次は ADR-005 を返す。

        ADR は feature ごとの adr ディレクトリ (specs/<feature>/adr/) に置かれ、
        feature が複数あっても git スキャンが ADR ファイルを検出することを確認する。
        """
        # scan 対象は design ディレクトリと、feature ごとの adr ディレクトリ
        mock_dirs.return_value = ["specs/**/design/", "specs/**/adr/"]
        mock_base.return_value = "develop"
        mock_branches.return_value = ["develop"]

        def git_side_effect(*args, cwd=None):
            if args[0] == "ls-tree":
                # 設計書は design ディレクトリ、ADR は feature ごとの adr ディレクトリにある
                return (
                    "specs/a/design/DES-001_a_design.md\n"
                    "specs/a/adr/ADR-001_a.md\n"
                    "specs/b/adr/ADR-002_b.md\n"
                    "specs/c/adr/ADR-003_c.md\n"
                    "specs/d/adr/ADR-004_d.md"
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

        これは実際に起きた衝突 (ブランチ A と B が双方 ADR-003 を作成) を
        採番時に警告できることを保証する。
        """
        mock_dirs.return_value = ["specs/**/adr/"]
        mock_base.return_value = "develop"
        mock_branches.return_value = ["feature/a", "feature/b"]

        def git_side_effect(*args, cwd=None):
            if args[0] == "ls-tree":
                branch = args[3]
                if branch == "feature/a":
                    return "specs/foo/adr/ADR-003_foo.md"
                if branch == "feature/b":
                    return "specs/bar/adr/ADR-003_bar.md"
            return ""

        mock_git.side_effect = git_side_effect

        result = scan_spec_ids("ADR", "/tmp/project", cwd="/tmp/project")

        duplicate_ids = {
            id_value
            for duplicate in result["duplicates"]
            for id_value in duplicate["ids"]
        }
        self.assertIn("ADR-003", duplicate_ids)


if __name__ == "__main__":
    unittest.main()
