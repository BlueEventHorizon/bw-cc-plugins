#!/usr/bin/env python3
"""
resolve_targets.py のテスト（DES-045 §3.3 / §7 テスト設計）

一時 git リポジトリを実際に作成し、staged / unstaged / untracked / commit 済みの
ケースを作り分けて実挙動を検証する（`tests/forge/msg-sys/test_check_setup.py` の
importlib 直接ロード・一時ディレクトリ実ファイル作成方式を踏襲）。

実行:
  python3 -m unittest tests.forge.review.test_resolve_targets -v
"""

import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "review" / "scripts" / "resolve_targets.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_resolve_targets", _SCRIPT_PATH)
resolve_targets_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve_targets_mod)


def _git(args, cwd):
    result = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return result.stdout


def _init_repo(project_root: Path, initial_branch: str = "main"):
    """一時 git リポジトリを初期化し、コミットに必要な user.email/user.name を設定する。

    グローバル設定で `commit.gpgSign=true` の環境でも commit が失敗しないよう、
    このリポジトリ限定で署名を無効化する（実行環境の個人設定に依存しない）。
    """
    _git(["init", "-b", initial_branch], project_root)
    _git(["config", "user.email", "test@example.com"], project_root)
    _git(["config", "user.name", "Test User"], project_root)
    _git(["config", "commit.gpgSign", "false"], project_root)


def _commit_all(project_root: Path, message: str):
    _git(["add", "-A"], project_root)
    _git(["commit", "-m", message], project_root)


def _write(project_root: Path, rel_path: str, content: str = "content\n"):
    path = project_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class DiffModeTest(unittest.TestCase):
    """diff モード: 未 commit 変更（staged + unstaged）+ 未追跡ファイルの列挙（DES-045 §3.3）。"""

    def test_staged_unstaged_untracked_are_all_listed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "base.txt", "base\n")
            _write(project_root, "unstaged.txt", "u\n")
            _commit_all(project_root, "initial commit")

            # unstaged: 既存ファイルを変更するが add しない
            _write(project_root, "unstaged.txt", "changed\n")

            # staged: 別の既存ファイルを変更して add
            _write(project_root, "base.txt", "staged change\n")
            _git(["add", "base.txt"], project_root)

            # untracked: 新規ファイルを作るのみ
            _write(project_root, "untracked.txt", "new\n")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "diff")
        self.assertEqual(
            set(result["files"]), {"base.txt", "unstaged.txt", "untracked.txt"}
        )

    def test_non_ascii_untracked_filename_is_not_escaped(self):
        """非ASCIIファイル名が git の C-style クォート化されずそのまま返る（msg-review review_id=043e2823d633478fb8e8dd1a74fa92a5 round=2 所見1）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            _write(project_root, "日本語.txt", "new\n")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertIn("日本語.txt", result["files"])

    def test_gitignored_untracked_file_is_excluded(self):
        """`.gitignore` 対象の未追跡ファイルは無視され、通常の未追跡ファイルのみ返る（DES-045 §3.3）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, ".gitignore", "ignored.txt\n")
            _commit_all(project_root, "initial commit")

            _write(project_root, "ignored.txt", "ignored\n")
            _write(project_root, "tracked_untracked.txt", "new\n")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertIn("tracked_untracked.txt", result["files"])
        self.assertNotIn("ignored.txt", result["files"])

    def test_deleted_file_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "keep.txt", "keep\n")
            _write(project_root, "to_delete.txt", "bye\n")
            _commit_all(project_root, "initial commit")

            _git(["rm", "to_delete.txt"], project_root)
            _write(project_root, "new.txt", "new\n")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertNotIn("to_delete.txt", result["files"])
        self.assertIn("new.txt", result["files"])

    def test_zero_targets_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["files"], [])
        self.assertIn("レビュー対象がありません", result["error"])

    def test_paths_are_project_root_relative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "sub/dir/file.txt", "x\n")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(result["status"], "ok")
        for f in result["files"]:
            self.assertFalse(Path(f).is_absolute())
        self.assertIn("sub/dir/file.txt", result["files"])


class BranchModeResolutionTest(unittest.TestCase):
    """base ブランチ解決の優先順位（.git_information.yaml → develop → main → master）。"""

    def test_configured_default_base_branch_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            _git(["branch", "develop"], project_root)
            _git(["branch", "custom-base"], project_root)

            (project_root / ".git_information.yaml").write_text(
                "default_base_branch: custom-base\n", encoding="utf-8"
            )

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertEqual(base_branch, "custom-base")
        self.assertEqual(base_ref, "custom-base")

    def test_develop_takes_priority_over_main_and_master(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _git(["branch", "develop"], project_root)
            _git(["branch", "master"], project_root)

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertEqual(base_branch, "develop")

    def test_main_takes_priority_over_master_when_no_develop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _git(["branch", "master"], project_root)

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertEqual(base_branch, "main")

    def test_master_used_when_only_master_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="master")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertEqual(base_branch, "master")

    def test_no_candidate_branch_resolves_to_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="feature-only")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertIsNone(base_branch)
        self.assertIsNone(base_ref)

    def test_configured_branch_falls_back_when_not_in_repo(self):
        """設定値のブランチがリポジトリに存在しない場合、develop/main/master へフォールバックする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            (project_root / ".git_information.yaml").write_text(
                "default_base_branch: does-not-exist\n", encoding="utf-8"
            )

            base_branch, base_ref = resolve_targets_mod.resolve_base_branch(project_root)

        self.assertEqual(base_branch, "main")


class BranchModeTargetsTest(unittest.TestCase):
    """branch モード: merge-base 以降の commit 済み + 未 commit + 未追跡の統合列挙。"""

    def test_committed_and_uncommitted_changes_are_combined(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            _git(["checkout", "-b", "feature"], project_root)
            _write(project_root, "committed.py", "print(1)\n")
            _commit_all(project_root, "add committed.py on feature")

            _write(project_root, "uncommitted.py", "print(2)\n")
            _git(["add", "uncommitted.py"], project_root)

            _write(project_root, "untracked.py", "print(3)\n")

            result = resolve_targets_mod.resolve_targets("branch", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["base_branch"], "main")
        self.assertEqual(
            set(result["files"]), {"committed.py", "uncommitted.py", "untracked.py"}
        )

    def test_no_resolvable_base_branch_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="feature-only")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets("branch", project_root, None)

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["base_branch"])
        self.assertIn("base ブランチを解決できません", result["error"])

    def test_zero_targets_is_error_when_no_diff_from_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _git(["checkout", "-b", "feature"], project_root)

            result = resolve_targets_mod.resolve_targets("branch", project_root, None)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["base_branch"], "main")
        self.assertIn("レビュー対象がありません", result["error"])

    def test_paths_are_project_root_relative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _git(["checkout", "-b", "feature"], project_root)
            _write(project_root, "sub/dir/committed.py", "x\n")
            _commit_all(project_root, "add nested file")

            result = resolve_targets_mod.resolve_targets("branch", project_root, None)

        self.assertEqual(result["status"], "ok")
        for f in result["files"]:
            self.assertFalse(Path(f).is_absolute())
        self.assertIn("sub/dir/committed.py", result["files"])


class BranchModeExplicitBaseTest(unittest.TestCase):
    """branch モード: `--base-branch` で渡した base が allowlist の起点になること（DES-066 §3.1.1）。

    base は利用者への確認で確定する（REQ-013）。確定した base を渡せないと、依頼本文の
    差分範囲と allowlist が別々の起点になり、範囲内のファイルへの修正が Step 7 の
    安全検証で allowlist 逸脱として上がる。
    """

    def _repo_with_two_bases(self, project_root: Path):
        """`main` → `feature/mid` → `feature/tip` の 3 段のブランチを作る。

        `main` 起点では 2 ファイル、`feature/mid` 起点では 1 ファイルが対象になる。
        """
        _init_repo(project_root, initial_branch="main")
        _write(project_root, "base.txt", "base\n")
        _commit_all(project_root, "initial commit")

        _git(["checkout", "-b", "feature/mid"], project_root)
        _write(project_root, "on_mid.py", "print(1)\n")
        _commit_all(project_root, "add on_mid.py")

        _git(["checkout", "-b", "feature/tip"], project_root)
        _write(project_root, "on_tip.py", "print(2)\n")
        _commit_all(project_root, "add on_tip.py")

    def test_explicit_base_narrows_the_allowlist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            self._repo_with_two_bases(project_root)

            result = resolve_targets_mod.resolve_targets(
                "branch", project_root, None, None, "feature/mid"
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["base_branch"], "feature/mid")
        self.assertEqual(set(result["files"]), {"on_tip.py"})

    def test_omitted_base_falls_back_to_self_resolution(self):
        """`--base-branch` 省略時のみ自前解決する（base 確定を持たない呼び出し向けの縮退経路）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            self._repo_with_two_bases(project_root)

            result = resolve_targets_mod.resolve_targets("branch", project_root, None)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["base_branch"], "main")
        self.assertEqual(set(result["files"]), {"on_mid.py", "on_tip.py"})

    def test_missing_explicit_base_is_error_and_does_not_self_resolve(self):
        """不在の base では自前解決へ落ちず error にする（fail closed）。

        自前解決へ落とすと、利用者が確定した base とは別の起点で allowlist が作られ、
        その食い違いが出力からは見えない。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            self._repo_with_two_bases(project_root)

            result = resolve_targets_mod.resolve_targets(
                "branch", project_root, None, None, "feature/nonexistent"
            )

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["base_branch"], "feature/nonexistent")
        self.assertEqual(result["files"], [])
        self.assertIn("指定された base ブランチが見つかりません", result["error"])

    def test_explicit_base_wins_over_configured_default(self):
        """`.git_information.yaml` の `default_base_branch` より明示指定が勝つこと。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            self._repo_with_two_bases(project_root)
            _write(
                project_root,
                ".git_information.yaml",
                "default_base_branch: main\n",
            )

            result = resolve_targets_mod.resolve_targets(
                "branch", project_root, None, None, "feature/mid"
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["base_branch"], "feature/mid")
        self.assertNotIn("on_mid.py", result["files"])

    def test_empty_base_branch_is_error_and_does_not_self_resolve(self):
        """空の `--base-branch` を「省略」と同義にしない。

        省略と同義にすると、確定した base を渡していない事実が出力から見えなくなり、
        非 branch モードでは error にしているのと非対称になる。
        """
        for value in ("", "   "):
            with self.subTest(value=repr(value)):
                with tempfile.TemporaryDirectory() as tmpdir:
                    project_root = Path(tmpdir)
                    self._repo_with_two_bases(project_root)

                    result = resolve_targets_mod.resolve_targets(
                        "branch", project_root, None, None, value
                    )

                self.assertEqual(result["status"], "error")
                self.assertIn("--base-branch に空の値は指定できません", result["error"])

    def test_base_branch_with_other_modes_is_error(self):
        """branch 以外のモードへ渡された `--base-branch` は黙って無視しない。"""
        for mode, files_arg, dirs_arg in (
            ("diff", None, None),
            ("files", "a.md", None),
            ("dirs", None, "docs"),
        ):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as tmpdir:
                    project_root = Path(tmpdir)
                    result = resolve_targets_mod.resolve_targets(
                        mode, project_root, files_arg, dirs_arg, "main"
                    )
                self.assertEqual(result["status"], "error")
                self.assertIn("--base-branch は branch モードでのみ", result["error"])

    def test_cli_accepts_base_branch_option(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            self._repo_with_two_bases(project_root)

            stdout, exit_code = _run_main_capture(
                [
                    "resolve_targets.py",
                    "--mode", "branch",
                    "--base-branch", "feature/mid",
                    "--project-root", str(project_root),
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["base_branch"], "feature/mid")
        self.assertEqual(payload["files"], ["on_tip.py"])


class FilesModeTest(unittest.TestCase):
    """files モード: 存在ファイルのみ ok。絶対パス・`..`・ルート外パスの拒否を含む。"""

    def test_existing_files_are_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "a.md", "a\n")
            _write(project_root, "sub/b.py", "b\n")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "a.md,sub/b.py"
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["files"], ["a.md", "sub/b.py"])

    def test_missing_file_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "a.md", "a\n")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "a.md,missing.py"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("missing.py", result["error"])

    def test_absolute_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "a.md", "a\n")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "/etc/passwd"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("/etc/passwd", result["error"])

    def test_dotdot_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "proj"
            project_root.mkdir()
            _write(project_root, "a.md", "a\n")
            # プロジェクトルート外に実在するファイルを作り、`..` で到達可能にしておく
            # （存在検証より前に拒否されることを保証するため）
            (Path(tmpdir) / "outside.txt").write_text("secret\n", encoding="utf-8")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "../outside.txt"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("../outside.txt", result["error"])

    def test_path_escaping_root_via_symlink_like_resolution_is_rejected(self):
        """`..` を含まなくても resolve() 結果がルート外になるパスは拒否される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            outer = Path(tmpdir)
            project_root = outer / "proj"
            project_root.mkdir()
            sibling = outer / "sibling"
            sibling.mkdir()
            (sibling / "leak.txt").write_text("leak\n", encoding="utf-8")

            # シンボリックリンク経由でルート外へ抜けるケース
            link_path = project_root / "escape"
            try:
                link_path.symlink_to(sibling)
            except OSError:
                self.skipTest("この環境ではシンボリックリンクを作成できません")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "escape/leak.txt"
            )

        self.assertEqual(result["status"], "error")

    def test_no_files_argument_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = resolve_targets_mod.resolve_targets("files", project_root, None)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["files"], [])

    def test_blank_files_argument_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = resolve_targets_mod.resolve_targets("files", project_root, "   ")

        self.assertEqual(result["status"], "error")

    def test_paths_are_project_root_relative(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "sub/dir/file.txt", "x\n")

            result = resolve_targets_mod.resolve_targets(
                "files", project_root, "sub/dir/file.txt"
            )

        self.assertEqual(result["status"], "ok")
        for f in result["files"]:
            self.assertFalse(Path(f).is_absolute())
        self.assertEqual(result["files"], ["sub/dir/file.txt"])


class DirsModeTest(unittest.TestCase):
    """dirs モード: ディレクトリの実在検証と配下ファイルの列挙。

    返る `files` は修正フェーズの allowlist 専用であり、依頼本文へは `dirs` を
    そのまま渡す（REQ-013 FNC-1312。本文側の契約は
    `test_build_review_request.DirsScopeTest` が検証する）。
    """

    def test_existing_dirs_list_their_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/a.md", "a\n")
            _write(project_root, "docs/sub/b.md", "b\n")
            _write(project_root, "src/c.py", "c\n")
            _write(project_root, "outside.txt", "x\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets(
                "dirs", project_root, None, "docs,src"
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "dirs")
        self.assertEqual(result["dirs"], ["docs", "src"])
        # 配下は再帰的に列挙し、指定外のファイルは含めない
        self.assertEqual(
            set(result["files"]), {"docs/a.md", "docs/sub/b.md", "src/c.py"}
        )

    def test_untracked_file_is_included(self):
        """未追跡の新規文書も allowlist に含まれること（追加直後にレビューできる）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/tracked.md", "t\n")
            _commit_all(project_root, "initial commit")
            _write(project_root, "docs/untracked.md", "u\n")

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "docs")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(result["files"]), {"docs/tracked.md", "docs/untracked.md"})

    def test_gitignored_file_is_excluded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, ".gitignore", "docs/ignored.md\n")
            _write(project_root, "docs/a.md", "a\n")
            _commit_all(project_root, "initial commit")
            _write(project_root, "docs/ignored.md", "secret\n")

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "docs")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["files"], ["docs/a.md"])

    def test_trailing_slash_is_normalized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/a.md", "a\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "docs/")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["dirs"], ["docs"])

    def test_missing_dir_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/a.md", "a\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets(
                "dirs", project_root, None, "docs,missing"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("missing", result["error"])

    def test_file_passed_as_dir_is_error(self):
        """ファイルを `--dirs` に渡した場合はディレクトリ不在として拒否される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/a.md", "a\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets(
                "dirs", project_root, None, "docs/a.md"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("docs/a.md", result["error"])

    def test_empty_dir_is_error(self):
        """配下に対象ファイルが無いディレクトリは対象 0 件として拒否される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "keep.txt", "k\n")
            _commit_all(project_root, "initial commit")
            (project_root / "empty").mkdir()

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "empty")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["files"], [])
        self.assertEqual(result["dirs"], ["empty"])

    def test_absolute_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "/etc")

        self.assertEqual(result["status"], "error")
        self.assertIn("/etc", result["error"])

    def test_dotdot_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "proj"
            project_root.mkdir()
            _init_repo(project_root)
            (Path(tmpdir) / "outside").mkdir()

            result = resolve_targets_mod.resolve_targets(
                "dirs", project_root, None, "../outside"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("../outside", result["error"])

    def test_path_escaping_root_via_symlink_is_rejected(self):
        """`..` を含まなくても resolve() 結果がルート外になるディレクトリは拒否される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            outer = Path(tmpdir)
            project_root = outer / "proj"
            project_root.mkdir()
            _init_repo(project_root)
            sibling = outer / "sibling"
            sibling.mkdir()
            (sibling / "leak.txt").write_text("leak\n", encoding="utf-8")

            link_path = project_root / "escape"
            try:
                link_path.symlink_to(sibling)
            except OSError:
                self.skipTest("この環境ではシンボリックリンクを作成できません")

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "escape")

        self.assertEqual(result["status"], "error")

    def test_no_dirs_argument_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, None)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["files"], [])
        self.assertEqual(result["dirs"], [])

    def test_blank_dirs_argument_is_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "   ")

        self.assertEqual(result["status"], "error")


class OutputSchemaTest(unittest.TestCase):
    """全モード共通の出力スキーマ（status/mode/base_branch/files/dirs/warnings）を検証する。

    `dirs` は dirs モード専用の値だが、全モードで返す（consumer が対象軸ごとに
    キーの有無を場合分けせずに読めるようにするため。dirs 以外では空配列）。
    """

    def test_diff_mode_error_has_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets("diff", project_root, None)

        self.assertEqual(
            set(result.keys()),
            {"status", "mode", "base_branch", "files", "dirs", "warnings", "error"},
        )
        self.assertIsNone(result["base_branch"])
        self.assertEqual(result["dirs"], [])

    def test_files_mode_ok_has_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "a.md", "a\n")

            result = resolve_targets_mod.resolve_targets("files", project_root, "a.md")

        self.assertEqual(
            set(result.keys()),
            {"status", "mode", "base_branch", "files", "dirs", "warnings"},
        )
        self.assertIsNone(result["base_branch"])
        self.assertEqual(result["dirs"], [])

    def test_dirs_mode_ok_has_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "docs/a.md", "a\n")
            _commit_all(project_root, "initial commit")

            result = resolve_targets_mod.resolve_targets("dirs", project_root, None, "docs")

        self.assertEqual(
            set(result.keys()),
            {"status", "mode", "base_branch", "files", "dirs", "warnings"},
        )
        self.assertIsNone(result["base_branch"])


class _FakeStdout(io.StringIO):
    """sys.stdout.reconfigure() を呼ぶコードをテスト可能にするための io.StringIO 拡張。"""

    def reconfigure(self, **kwargs):
        pass


def _run_main_capture(argv):
    """resolve_targets_mod.main() を実行し、標準出力への書き込みを文字列として返す。"""
    buf = _FakeStdout()
    with mock.patch.object(resolve_targets_mod.sys, "argv", argv):
        with mock.patch.object(resolve_targets_mod.sys, "stdout", buf):
            exit_code = resolve_targets_mod.main()
    return buf.getvalue(), exit_code


class MainTest(unittest.TestCase):
    """公開インターフェース main() の引数処理・単一 JSON 出力・終了コードを検証する（DES-045 §3.3）。"""

    def test_diff_mode_outputs_single_json_line_with_exit_code_0(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root)
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _write(project_root, "unstaged.txt", "new\n")

            argv = [
                "resolve_targets.py",
                "--mode", "diff",
                "--project-root", str(project_root),
            ]
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["mode"], "diff")
        self.assertIn("unstaged.txt", payload["files"])

    def test_branch_mode_outputs_single_json_line_with_exit_code_0(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _init_repo(project_root, initial_branch="main")
            _write(project_root, "base.txt", "base\n")
            _commit_all(project_root, "initial commit")
            _git(["checkout", "-b", "feature/x"], project_root)
            _write(project_root, "feature.txt", "feature\n")
            _commit_all(project_root, "feature commit")

            argv = [
                "resolve_targets.py",
                "--mode", "branch",
                "--project-root", str(project_root),
            ]
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["mode"], "branch")
        self.assertEqual(payload["base_branch"], "main")
        self.assertIn("feature.txt", payload["files"])

    def test_files_mode_outputs_single_json_line_with_exit_code_0(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write(project_root, "a.md", "a\n")

            argv = [
                "resolve_targets.py",
                "--mode", "files",
                "--files", "a.md",
                "--project-root", str(project_root),
            ]
            stdout, exit_code = _run_main_capture(argv)

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["mode"], "files")
        self.assertEqual(payload["files"], ["a.md"])


if __name__ == "__main__":
    unittest.main()
