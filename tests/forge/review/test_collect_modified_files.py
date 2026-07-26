#!/usr/bin/env python3
"""collect_modified_files.py のテスト（DES-047 §3.5 テスト設計、実 Codex レビューで発見の回帰）。

`git status --porcelain`（-z 無し）は空白・改行・非 ASCII を含むパスを C-style quote し、
rename/copy は ` -> ` を含む1行で表現するため、行/矢印単位の手動パースでは実パスを取り違える。
`-z`（NUL 区切り・quote 無し）出力の解析が正しく行えることを検証する。

実行:
  python3 -m unittest tests.forge.review.test_collect_modified_files -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "collect_modified_files.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_collect_modified_files", _SCRIPT_PATH)
collect_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(collect_mod)


class ParsePorcelainZTest(unittest.TestCase):
    """_parse_porcelain_z(): NUL 区切り出力の解析。"""

    def test_single_modified_file(self):
        raw = b" M a.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["a.txt"])

    def test_untracked_file(self):
        raw = b"?? newfile.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["newfile.txt"])

    def test_multiple_files(self):
        raw = b" M a.txt\x00?? b.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["a.txt", "b.txt"])

    def test_rename_record_consumes_two_tokens_and_keeps_new_path(self):
        """rename は「XY 新パス」+「旧パス（status 無し、消費のみ）」の2トークンで1レコード

        （git 実挙動で実測確認: 1トークン目が現在のパス、2トークン目が旧パス）。
        """
        raw = b"R  new.txt\x00old.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["new.txt"])

    def test_copy_record_consumes_two_tokens(self):
        raw = b"C  copy.py\x00orig.py\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["copy.py"])

    def test_rename_followed_by_another_normal_entry(self):
        """rename レコードの2トークン消費後、次の通常レコードを正しく続けて解析できる。"""
        raw = b"R  new.txt\x00old.txt\x00 M other.py\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["new.txt", "other.py"])

    def test_non_ascii_filename(self):
        raw = "M  日本語.txt\x00".encode("utf-8")
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["日本語.txt"])

    def test_filename_with_spaces(self):
        raw = b"M  file with spaces.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["file with spaces.txt"])

    def test_filename_containing_arrow_substring_is_not_misparsed(self):
        """ファイル名自体に ` -> ` を含む場合でも、矢印区切りではなく NUL 区切りで正しく1パスとして扱われる。

        行/矢印ベースの手動パース（実 Codex レビューで指摘）では、この種のファイル名を
        rename の区切りと誤認識しうる。NUL 区切り解析ならこの曖昧性は生じない。
        """
        raw = b"M  weird -> name.txt\x00"
        self.assertEqual(collect_mod._parse_porcelain_z(raw), ["weird -> name.txt"])

    def test_empty_output_returns_empty_list(self):
        self.assertEqual(collect_mod._parse_porcelain_z(b""), [])

    def test_trailing_nul_does_not_produce_empty_entry(self):
        raw = b" M a.txt\x00 M b.txt\x00"
        result = collect_mod._parse_porcelain_z(raw)
        self.assertNotIn("", result)
        self.assertEqual(len(result), 2)


class CollectModifiedFilesRealGitTest(unittest.TestCase):
    """collect_modified_files(): 実 git リポジトリでの end-to-end 動作確認。"""

    def test_real_repo_modified_added_and_renamed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=tmpdir, check=True)
            # グローバル設定で commit.gpgSign=true の環境でも commit が失敗しないよう、
            # このリポジトリ限定で署名を無効化する（実行環境の個人設定に依存しない。
            # 実 Codex レビューで発見: test_resolve_targets.py の既存対策と同じ）。
            subprocess.run(["git", "config", "commit.gpgSign", "false"], cwd=tmpdir, check=True)

            (Path(tmpdir) / "existing.txt").write_text("original\n", encoding="utf-8")
            (Path(tmpdir) / "to_rename.txt").write_text("keep\n", encoding="utf-8")
            (Path(tmpdir) / "to_delete.txt").write_text("gone\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmpdir, check=True)

            (Path(tmpdir) / "existing.txt").write_text("changed\n", encoding="utf-8")
            (Path(tmpdir) / "new_file.txt").write_text("brand new\n", encoding="utf-8")
            (Path(tmpdir) / "to_rename.txt").rename(Path(tmpdir) / "renamed.txt")
            (Path(tmpdir) / "to_delete.txt").unlink()
            subprocess.run(["git", "add", "-A"], cwd=tmpdir, check=True)

            result = collect_mod.collect_modified_files(project_root=tmpdir)

        self.assertEqual(result["status"], "ok")
        self.assertIn("existing.txt", result["files"])
        self.assertIn("to_delete.txt", result["files"])
        self.assertIn("new_file.txt", result["files"])
        self.assertIn("renamed.txt", result["files"])
        self.assertNotIn("to_rename.txt", result["files"])


class MainTest(unittest.TestCase):
    def test_cli_outputs_single_json(self):
        result = subprocess.run(
            ["python3", str(_SCRIPT_PATH)],
            capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertIsInstance(payload["files"], list)


if __name__ == "__main__":
    unittest.main()
