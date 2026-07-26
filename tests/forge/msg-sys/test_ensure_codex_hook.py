#!/usr/bin/env python3
"""ensure_codex_hook.py のテスト（DES-045 §3.8 補足、meta-plugin 無限フックインシデントの

再発防止）。

実行:
  python3 -m unittest tests.forge.msg-sys.test_ensure_codex_hook -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "ensure_codex_hook.py"
)
_REAL_MSG_SYS_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys"
)

_spec = importlib.util.spec_from_file_location("msg_sys_ensure_codex_hook", _SCRIPT_PATH)
ensure_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ensure_mod)


def _init_repo(tmpdir: str) -> Path:
    project_root = Path(tmpdir)
    subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmpdir, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmpdir, check=True)
    return project_root


class EnsureGitignoreEntryTest(unittest.TestCase):
    """`_ensure_gitignore_entry`: symlink 誤コミット防止のための .gitignore 自己管理（ユーザー指摘対応）。"""

    def test_adds_entry_when_gitignore_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = ensure_mod._ensure_gitignore_entry(project_root, ".codex/msg-sys/scripts", "comment")

            self.assertEqual(result["status"], "added")
            content = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".codex/msg-sys/scripts", content.splitlines())

    def test_adds_entry_when_gitignore_exists_without_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
            result = ensure_mod._ensure_gitignore_entry(project_root, ".codex/msg-sys/scripts", "comment")

            self.assertEqual(result["status"], "added")
            lines = (project_root / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertIn("node_modules/", lines)
            self.assertIn(".codex/msg-sys/scripts", lines)

    def test_adds_newline_before_appending_when_file_lacks_trailing_newline(self):
        """既存 .gitignore が末尾改行なしでも、追記行と結合して壊さない。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            (project_root / ".gitignore").write_text("node_modules/", encoding="utf-8")
            ensure_mod._ensure_gitignore_entry(project_root, ".codex/msg-sys/scripts", "comment")

            lines = (project_root / ".gitignore").read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], "node_modules/")
            self.assertIn(".codex/msg-sys/scripts", lines)

    def test_already_present_is_idempotent_and_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            ensure_mod._ensure_gitignore_entry(project_root, ".codex/msg-sys/scripts", "comment")
            result = ensure_mod._ensure_gitignore_entry(project_root, ".codex/msg-sys/scripts", "comment")

            self.assertEqual(result["status"], "already_present")
            content = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertEqual(content.count(".codex/msg-sys/scripts"), 1)

    def test_ensure_calls_gitignore_entry_end_to_end(self):
        """ensure() を通しで呼んだ場合に .gitignore へ実際に反映されること。"""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_dir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod.ensure(str(project_root), plugin_dir)

            self.assertEqual(result["gitignore"]["status"], "added")
            content = (project_root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".codex/msg-sys/scripts", content.splitlines())


class EnsureSymlinkTest(unittest.TestCase):
    def test_creates_symlink_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_dir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod._ensure_symlink(project_root, Path(plugin_dir))

            self.assertEqual(result["status"], "created")
            link = project_root / ".codex" / "msg-sys" / "scripts"
            self.assertTrue(link.is_symlink())
            self.assertEqual(str(link.resolve()), str(Path(plugin_dir).resolve()))

    def test_unchanged_when_symlink_already_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_symlink(project_root, Path(plugin_dir))
            result = ensure_mod._ensure_symlink(project_root, Path(plugin_dir))

            self.assertEqual(result["status"], "unchanged")

    def test_repairs_symlink_pointing_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             tempfile.TemporaryDirectory() as old_plugin_dir, \
             tempfile.TemporaryDirectory() as new_plugin_dir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_symlink(project_root, Path(old_plugin_dir))
            result = ensure_mod._ensure_symlink(project_root, Path(new_plugin_dir))

            self.assertEqual(result["status"], "repaired")
            link = project_root / ".codex" / "msg-sys" / "scripts"
            self.assertEqual(str(link.resolve()), str(Path(new_plugin_dir).resolve()))

    def test_repairs_dangling_symlink(self):
        """symlink 先が（プラグインの再インストール等で）消滅していても正しく修復できる。"""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_parent:
            project_root = _init_repo(tmpdir)
            vanished_target = Path(plugin_parent) / "vanished_version"
            vanished_target.mkdir()
            ensure_mod._ensure_symlink(project_root, vanished_target)
            vanished_target.rmdir()  # symlink 先が消える状況を再現する

            new_target = Path(plugin_parent) / "new_version"
            new_target.mkdir()
            result = ensure_mod._ensure_symlink(project_root, new_target)

            self.assertEqual(result["status"], "repaired")

    def test_conflict_when_real_directory_exists_instead_of_symlink(self):
        """symlink であるべき場所に実ディレクトリがある場合、上書きせず conflict を報告する。"""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_dir:
            project_root = _init_repo(tmpdir)
            real_dir = project_root / ".codex" / "msg-sys" / "scripts"
            real_dir.mkdir(parents=True)
            (real_dir / "important_human_file.txt").write_text("do not delete", encoding="utf-8")

            result = ensure_mod._ensure_symlink(project_root, Path(plugin_dir))

            self.assertEqual(result["status"], "conflict")
            self.assertTrue((real_dir / "important_human_file.txt").is_file())


class EnsureHooksJsonTest(unittest.TestCase):
    def test_creates_hooks_json_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod._ensure_hooks_json(project_root, 20)

            self.assertEqual(result["status"], "created")
            data = json.loads((project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertIn("FORGE_MSG_AGENT_NAME=codex", command)
            self.assertIn(".codex/msg-sys/scripts/hooks/check_inbox.py", command)

    def test_unchanged_when_already_correct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            ensure_mod._ensure_hooks_json(project_root, 20)
            result = ensure_mod._ensure_hooks_json(project_root, 20)

            self.assertEqual(result["status"], "unchanged")

    def test_repairs_broken_command_without_touching_other_hooks(self):
        """meta-plugin インシデントの直接再現: 壊れたパスを指す既存エントリだけを修復し、

        無関係な既存 Stop フック（通知音再生等）は変更しない。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            hooks_path = project_root / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True, exist_ok=True)
            broken_data = {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo unrelated notification"},
                                {
                                    "type": "command",
                                    "command": (
                                        "FORGE_MSG_AGENT_NAME=codex python3 "
                                        "/some/nonexistent/plugins/forge/scripts/msg-sys/hooks/check_inbox.py"
                                    ),
                                },
                            ]
                        }
                    ]
                }
            }
            hooks_path.write_text(json.dumps(broken_data, ensure_ascii=False), encoding="utf-8")

            result = ensure_mod._ensure_hooks_json(project_root, 20)

            self.assertEqual(result["status"], "repaired")
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            commands = [h["command"] for h in data["hooks"]["Stop"][0]["hooks"]]
            self.assertIn("echo unrelated notification", commands)  # 無関係な既存エントリは維持
            self.assertTrue(any(".codex/msg-sys/scripts/hooks/check_inbox.py" in c for c in commands))

    def test_appends_when_stop_hooks_exist_but_no_codex_entry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            hooks_path = project_root / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True, exist_ok=True)
            existing_data = {
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo unrelated"}]}]}
            }
            hooks_path.write_text(json.dumps(existing_data, ensure_ascii=False), encoding="utf-8")

            result = ensure_mod._ensure_hooks_json(project_root, 20)

            self.assertEqual(result["status"], "appended")
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["hooks"]["Stop"]), 2)
            self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "echo unrelated")

    def test_error_when_json_invalid_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            hooks_path = project_root / ".codex" / "hooks.json"
            hooks_path.parent.mkdir(parents=True, exist_ok=True)
            hooks_path.write_text("not valid json", encoding="utf-8")

            result = ensure_mod._ensure_hooks_json(project_root, 20)

            self.assertEqual(result["status"], "error")
            self.assertEqual(hooks_path.read_text(encoding="utf-8"), "not valid json")

    def test_max_round_trips_value_embedded_in_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod._ensure_hooks_json(project_root, 42)

            self.assertEqual(result["status"], "created")
            data = json.loads((project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
            command = data["hooks"]["Stop"][0]["hooks"][0]["command"]
            self.assertIn("FORGE_MSG_MAX_ROUND_TRIPS=42", command)


class EnsureEndToEndTest(unittest.TestCase):
    """ensure(): symlink + hooks.json を通しで確認し、実際に check_inbox.py が

    symlink 経由で動作することまで検証する（実 Codex レビューでの vendor 検証と
    同じ「実際に動かして確認する」原則）。
    """

    def test_ensure_creates_working_symlink_and_hooks_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            result = ensure_mod.ensure(str(project_root), str(_REAL_MSG_SYS_DIR))

            self.assertEqual(result["symlink"]["status"], "created")
            self.assertEqual(result["hooks_json"]["status"], "created")

            check_inbox_via_symlink = project_root / ".codex" / "msg-sys" / "scripts" / "hooks" / "check_inbox.py"
            self.assertTrue(check_inbox_via_symlink.is_file())

            # symlink 経由で実際に check_inbox.py を実行し、正常応答（continue:true、
            # メールボックス空なので）が返ることを確認する。
            proc = subprocess.run(
                ["python3", str(check_inbox_via_symlink)],
                cwd=str(project_root),
                env={
                    "FORGE_MSG_MAX_ROUND_TRIPS": "20",
                    "FORGE_MSG_AGENT_NAME": "codex",
                    "FORGE_MSG_PROJECT_ROOT": str(project_root),
                    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                },
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(proc.returncode, 0)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload, {"continue": True})

    def test_hooks_json_not_touched_when_symlink_conflicts_with_stale_check_inbox(self):
        """symlink 用の場所に、たまたま古い check_inbox.py を含む実ディレクトリが

        既にある場合（conflict）、hooks.json を書き換えない（実 Codex レビューで
        発見: symlink が conflict でも hooks.json だけ先に進めてしまうと、実在確認
        は通過するが現在ロード中の forge 実装ではない古いコードを Codex が起動する）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            conflicting_dir = project_root / ".codex" / "msg-sys" / "scripts" / "hooks"
            conflicting_dir.mkdir(parents=True)
            (conflicting_dir / "check_inbox.py").write_text("# stale old version\n", encoding="utf-8")

            result = ensure_mod.ensure(str(project_root), str(_REAL_MSG_SYS_DIR))

            self.assertEqual(result["symlink"]["status"], "conflict")
            self.assertEqual(result["hooks_json"]["status"], "skipped_due_to_symlink_conflict")
            self.assertFalse((project_root / ".codex" / "hooks.json").exists())

    def test_idempotent_second_run_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = _init_repo(tmpdir)
            ensure_mod.ensure(str(project_root), str(_REAL_MSG_SYS_DIR))
            result = ensure_mod.ensure(str(project_root), str(_REAL_MSG_SYS_DIR))

            self.assertEqual(result["symlink"]["status"], "unchanged")
            self.assertEqual(result["hooks_json"]["status"], "unchanged")


class MainTest(unittest.TestCase):
    def test_cli_outputs_single_json(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as plugin_dir:
            project_root = _init_repo(tmpdir)
            result = subprocess.run(
                [
                    "python3", str(_SCRIPT_PATH),
                    "--project-root", str(project_root),
                    "--plugin-msg-sys-dir", plugin_dir,
                ],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["symlink"]["status"], "created")
            self.assertEqual(payload["hooks_json"]["status"], "created")


if __name__ == "__main__":
    unittest.main()
