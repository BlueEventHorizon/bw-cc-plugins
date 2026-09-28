#!/usr/bin/env python3
"""回帰防止テスト: ADR の ID 採番ガイドのカバレッジ。

背景: forge で ADR（Architecture Decision Record）を新規作成する際の
ID 採番手順がスキル・文書に明記されておらず、並行ブランチで同一 `ADR-003` が別内容で
衝突した。採番スクリプト `scan_spec_ids.py` は任意プレフィックスを汎用的に扱えるため
(ADR も同様に動作する)、修正はドキュメント/ワークフロー側で完結する。

本テストはこの修正が後退しないことを検証する:

- スクリプト挙動: scan_spec_ids が `ADR` プレフィックスを正しく採番する。
  ADR を設計ディレクトリ配下に置く限り、ADR 専用ディレクトリが scan 対象になくても
  既存 ADR を検出できること (「ADR-001〜004 使用済み → ADR-005」を再現)。
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

        これは実際に起きた衝突 (ブランチ A と B が双方 ADR-003 を作成) を
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

        duplicate_ids = {
            id_value
            for duplicate in result["duplicates"]
            for id_value in duplicate["ids"]
        }
        self.assertIn("ADR-003", duplicate_ids)


if __name__ == "__main__":
    unittest.main()
