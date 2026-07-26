#!/usr/bin/env python3
"""
check_setup.py のテスト（DES-034 §3.1/§9 テスト設計）

msg-sys 既存 CLI（git・resolve_db_path）への呼び出しはモック、または一時ディレクトリ
に実ファイルを作成して検証する。settings.json / hooks.json は実ファイルとして
一時ディレクトリに作成し、実際の登録パターンでの検査を行う。

実行:
  python3 -m unittest tests.forge.msg-sys.test_check_setup -v
"""

import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "check_setup.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_check_setup", _SCRIPT_PATH)
check_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_setup)


def _claude_settings_command(agent_name="claude", max_round_trips="20"):
    """実際の登録パターン（`.claude/settings.json` 実物）に準じた command 文字列を組み立てる。

    `FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)"` のように値をダブル
    クォートで囲む（shlex.split で1トークンとして扱わせるため。無引用だと
    `$(git` 以降がスペースで複数トークンに分裂し、env 代入判定が誤って壊れる）。
    """
    parts = [f"FORGE_MSG_AGENT_NAME={agent_name}"]
    if max_round_trips is not None:
        parts.append(f"FORGE_MSG_MAX_ROUND_TRIPS={max_round_trips}")
    parts.append('FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)"')
    parts.append("python3")
    parts.append('"$(git rev-parse --show-toplevel)/plugins/forge/scripts/msg-sys/hooks/check_inbox.py"')
    return " ".join(parts)


class _FakeStdout(io.StringIO):
    """sys.stdout.reconfigure() を呼ぶコードをテスト可能にするための io.StringIO 拡張。"""

    def reconfigure(self, **kwargs):
        pass


def _run_main_capture(argv):
    """check_setup.main() を実行し、標準出力への書き込みを文字列として返す（DES-034 §3.1）。"""
    buf = _FakeStdout()
    with mock.patch.object(check_setup.sys, "argv", argv):
        with mock.patch.object(check_setup.sys, "stdout", buf):
            exit_code = check_setup.main()
    return buf.getvalue(), exit_code


def _write_settings(path: Path, command: str):
    data = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": command},
                    ]
                }
            ]
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _codex_hook_command(max_round_trips="20"):
    """`ensure_codex_hook.py` が実際に生成する codex 側 command 文字列と同じ形式を組み立てる。

    `_resolve_codex_hook_path()` は固定の1文字列との厳密一致 + symlink 検証を行うため
    （実 Codex レビューで発見の `..` トラバーサル対策）、テスト用のコマンドも
    `.codex/msg-sys/scripts/hooks/check_inbox.py` を指す必要がある。
    """
    parts = ["FORGE_MSG_AGENT_NAME=codex"]
    if max_round_trips is not None:
        parts.append(f"FORGE_MSG_MAX_ROUND_TRIPS={max_round_trips}")
    parts.append('FORGE_MSG_PROJECT_ROOT="$(git rev-parse --show-toplevel)"')
    parts.append("python3")
    parts.append('"$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/hooks/check_inbox.py"')
    return " ".join(parts)


class PluginHooksPathTest(unittest.TestCase):
    """_plugin_hooks_path(): forge プラグイン同梱の hooks/hooks.json を正しく指すこと。"""

    def test_resolves_to_plugin_hooks_json(self):
        expected = (
            Path(__file__).resolve().parents[3]
            / "plugins" / "forge" / "hooks" / "hooks.json"
        )
        self.assertEqual(check_setup._plugin_hooks_path(), expected)

    def test_shipped_hooks_json_is_registered_correctly(self):
        """実際に配布される hooks/hooks.json が claude 向け登録として正しく検出されること。

        プラグイン導入だけで Claude 側 Stop フックが自動有効化される設計（Claude Code の
        プラグイン hooks 自動登録機構）であり、`.claude/settings.json` の手動編集は
        不要になった。この静的ファイル自体が壊れていないことを検査する（実 Codex
        レビューでの指摘を踏まえた改善）。
        """
        check, matched = check_setup.check_agent_registration(
            Path("/unused"), check_setup._plugin_hooks_path(), "claude", "claude_plugin_hook_registration"
        )
        self.assertTrue(check["ok"])
        self.assertIsNotNone(matched)
        self.assertIn("FORGE_MSG_MAX_ROUND_TRIPS=", matched)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", matched)


class CheckGitRootTest(unittest.TestCase):
    def test_ok_in_git_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            result = check_setup.check_git_root(Path(tmpdir))
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "git_root_resolution")

    def test_error_not_a_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = check_setup.check_git_root(Path(tmpdir))
        self.assertFalse(result["ok"])

    def test_error_git_execution_fails(self):
        with mock.patch.object(check_setup.subprocess, "run", side_effect=OSError("no git")):
            result = check_setup.check_git_root(Path("/tmp"))
        self.assertFalse(result["ok"])
        self.assertIn("git 実行に失敗", result["detail"])

    def test_error_empty_toplevel(self):
        with mock.patch.object(
            check_setup.subprocess, "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ):
            result = check_setup.check_git_root(Path("/tmp"))
        self.assertFalse(result["ok"])


class CheckDbPathResolutionTest(unittest.TestCase):
    def test_project_root_used_when_env_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = check_setup.check_db_path_resolution(Path("/proj"))
            self.assertNotIn("FORGE_MSG_PROJECT_ROOT", os.environ)
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["detail"],
            str(Path("/proj") / ".claude" / ".temp" / "msg-sys" / "messages.db"),
        )

    def test_project_root_always_overrides_existing_env(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_PROJECT_ROOT": "/other/existing"}):
            result = check_setup.check_db_path_resolution(Path("/proj"))
            # 呼び出し後に元の値へ復元されること（with ブロック内で検証する）
            self.assertEqual(os.environ["FORGE_MSG_PROJECT_ROOT"], "/other/existing")
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["detail"],
            str(Path("/proj") / ".claude" / ".temp" / "msg-sys" / "messages.db"),
        )

    def test_env_restored_to_unset_after_call(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            check_setup.check_db_path_resolution(Path("/proj"))
            self.assertNotIn("FORGE_MSG_PROJECT_ROOT", os.environ)

    def test_env_restored_to_empty_string_after_call(self):
        with mock.patch.dict(os.environ, {"FORGE_MSG_PROJECT_ROOT": ""}):
            check_setup.check_db_path_resolution(Path("/proj"))
            self.assertEqual(os.environ["FORGE_MSG_PROJECT_ROOT"], "")

    def test_error_when_resolve_db_path_raises(self):
        with mock.patch.object(
            check_setup.mailbox, "resolve_db_path", side_effect=RuntimeError("boom")
        ):
            with mock.patch.dict(os.environ, {}, clear=True):
                result = check_setup.check_db_path_resolution(Path("/proj"))
                # 例外発生時も元の状態(未設定)へ復元されること
                self.assertNotIn("FORGE_MSG_PROJECT_ROOT", os.environ)
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["detail"])


class FindRegistrationTest(unittest.TestCase):
    def test_matches_real_registration_pattern(self):
        command = (
            "FORGE_MSG_AGENT_NAME=claude FORGE_MSG_PROJECT_ROOT=/repo "
            "python3 /repo/plugins/forge/scripts/msg-sys/hooks/check_inbox.py"
        )
        matched = check_setup._find_registration([command], "claude")
        self.assertEqual(matched, command)

    def test_matches_with_python_executable(self):
        command = (
            "FORGE_MSG_AGENT_NAME=codex python /repo/hooks/check_inbox.py"
        )
        matched = check_setup._find_registration([command], "codex")
        self.assertEqual(matched, command)

    def test_no_match_for_wrong_agent_name(self):
        command = (
            "FORGE_MSG_AGENT_NAME=codex python3 /repo/hooks/check_inbox.py"
        )
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_for_fake_echo_string(self):
        command = "echo check_inbox.py FORGE_MSG_AGENT_NAME=claude"
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_for_module_flag_not_executing_check_inbox(self):
        command = (
            "FORGE_MSG_AGENT_NAME=claude python3 -m module /tmp/check_inbox.py"
        )
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_when_prefix_has_non_env_token(self):
        command = (
            "not_an_env_assignment FORGE_MSG_AGENT_NAME=claude "
            "python3 /repo/hooks/check_inbox.py"
        )
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_when_python_token_missing(self):
        command = "FORGE_MSG_AGENT_NAME=claude /usr/bin/check_inbox.py"
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_for_unparsable_shlex(self):
        command = "FORGE_MSG_AGENT_NAME=claude python3 'unterminated"
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_no_match_when_exec_target_does_not_end_with_check_inbox(self):
        command = "FORGE_MSG_AGENT_NAME=claude python3 /repo/hooks/other_script.py"
        matched = check_setup._find_registration([command], "claude")
        self.assertIsNone(matched)

    def test_first_matching_command_returned_among_multiple(self):
        good = (
            "FORGE_MSG_AGENT_NAME=claude python3 /repo/hooks/check_inbox.py"
        )
        other = "echo unrelated"
        matched = check_setup._find_registration([other, good], "claude")
        self.assertEqual(matched, good)


_EXPECTED_CODEX_TOKEN = "$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/hooks/check_inbox.py"


def _link_codex_scripts_to_real_msg_sys(project_root: Path) -> None:
    """`<project_root>/.codex/msg-sys/scripts` を、テスト対象の本物の

    `plugins/forge/scripts/msg-sys/` （`check_setup.py` 自身が置かれているディレクトリ）
    への symlink にする。`_resolve_codex_hook_path()` は「symlink が現在ロード中の
    forge プラグイン自身の msg-sys を指しているか」まで検証するため、テストでも
    本物のディレクトリへの symlink を用意する必要がある。
    """
    link_parent = project_root / ".codex" / "msg-sys"
    link_parent.mkdir(parents=True, exist_ok=True)
    (link_parent / "scripts").symlink_to(_SCRIPT_PATH.parent, target_is_directory=True)


class ResolveCodexHookPathTest(unittest.TestCase):
    """_resolve_codex_hook_path(): ensure_codex_hook.py が生成する唯一の正当な

    token との厳密一致 + symlink の実解決先検証（実 Codex レビューで発見: 旧実装は
    (1) exec_target を `bash -c` へ直接連結しておりコマンドインジェクション可能、
    (2) 相対パスの緩い正規表現が `..` によるエスケープを許していた、
    (3) symlink が conflict で人間由来の実ディレクトリに置き換わっていても、
    その中にたまたま check_inbox.py があれば実在確認だけでは検出できなかった）。
    """

    def test_resolves_when_token_matches_and_symlink_points_to_current_plugin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            _link_codex_scripts_to_real_msg_sys(project_root)

            resolved = check_setup._resolve_codex_hook_path(_EXPECTED_CODEX_TOKEN, project_root)

        self.assertEqual(resolved, f"{project_root.resolve()}{check_setup._EXPECTED_CODEX_HOOK_SUFFIX}")

    def test_tolerates_surrounding_double_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            _link_codex_scripts_to_real_msg_sys(project_root)

            resolved = check_setup._resolve_codex_hook_path(f'"{_EXPECTED_CODEX_TOKEN}"', project_root)

        self.assertIsNotNone(resolved)

    def test_none_when_symlink_missing(self):
        """symlink 自体が無ければ、token が厳密一致していても解決失敗にする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)

            resolved = check_setup._resolve_codex_hook_path(_EXPECTED_CODEX_TOKEN, project_root)

        self.assertIsNone(resolved)

    def test_none_when_symlink_points_elsewhere(self):
        """symlink はあるが、現在ロード中の forge プラグインとは別の場所を指している。"""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as elsewhere:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            link_parent = project_root / ".codex" / "msg-sys"
            link_parent.mkdir(parents=True, exist_ok=True)
            (link_parent / "scripts").symlink_to(elsewhere, target_is_directory=True)

            resolved = check_setup._resolve_codex_hook_path(_EXPECTED_CODEX_TOKEN, project_root)

        self.assertIsNone(resolved)

    def test_none_when_conflict_real_directory_with_stale_check_inbox(self):
        """symlink であるべき場所に実ディレクトリ（かつ中に check_inbox.py がある）

        という conflict 状態でも、symlink でない以上は解決失敗にする（実 Codex
        レビューで発見: ファイルの実在確認だけでは、この conflict を見逃していた）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            conflict_hooks_dir = project_root / ".codex" / "msg-sys" / "scripts" / "hooks"
            conflict_hooks_dir.mkdir(parents=True)
            (conflict_hooks_dir / "check_inbox.py").write_text("# stale\n", encoding="utf-8")

            resolved = check_setup._resolve_codex_hook_path(_EXPECTED_CODEX_TOKEN, project_root)

        self.assertIsNone(resolved)

    def test_rejects_dotdot_path_traversal(self):
        """相対部分に `..` を含む変種は、symlink の有無に関わらず厳密一致で拒否する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            _link_codex_scripts_to_real_msg_sys(project_root)
            traversal_token = "$(git rev-parse --show-toplevel)/.codex/msg-sys/scripts/../../../etc/check_inbox.py"

            resolved = check_setup._resolve_codex_hook_path(traversal_token, project_root)

        self.assertIsNone(resolved)

    def test_returns_none_when_git_execution_fails(self):
        resolved = check_setup._resolve_codex_hook_path(_EXPECTED_CODEX_TOKEN, Path("/nonexistent/dir/xyz"))
        self.assertIsNone(resolved)

    def test_rejects_command_substitution_injection_without_executing_it(self):
        """悪意ある command substitution を含む token は一切実行せず None を返す

        （実 Codex レビューで発見の脆弱性の直接回帰テスト）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            marker_file = project_root / "PWNED"
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            malicious_token = f"$(git rev-parse --show-toplevel)/$(touch {marker_file})/x.py"

            resolved = check_setup._resolve_codex_hook_path(malicious_token, project_root)

            self.assertIsNone(resolved)
            self.assertFalse(marker_file.exists(), "悪意あるコマンドが実行されてしまっている")

    def test_rejects_backtick_injection_without_executing_it(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            marker_file = project_root / "PWNED2"
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            malicious_token = f"$(git rev-parse --show-toplevel)/`touch {marker_file}`/x.py"

            resolved = check_setup._resolve_codex_hook_path(malicious_token, project_root)

            self.assertIsNone(resolved)
            self.assertFalse(marker_file.exists(), "悪意あるコマンドが実行されてしまっている")

    def test_rejects_semicolon_command_chaining(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            marker_file = project_root / "PWNED3"
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            malicious_token = f"$(git rev-parse --show-toplevel)/x.py; touch {marker_file}"

            resolved = check_setup._resolve_codex_hook_path(malicious_token, project_root)

            self.assertIsNone(resolved)
            self.assertFalse(marker_file.exists(), "悪意あるコマンドが実行されてしまっている")

    def test_rejects_non_matching_arbitrary_string(self):
        resolved = check_setup._resolve_codex_hook_path("just some random string", Path("/tmp"))
        self.assertIsNone(resolved)


class CheckAgentRegistrationTest(unittest.TestCase):
    def test_ok_when_registered(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            command = _claude_settings_command()
            _write_settings(project_root / ".claude" / "settings.json", command)

            check, matched = check_setup.check_agent_registration(
                project_root, ".claude/settings.json", "claude", "claude_settings_registration"
            )
        self.assertTrue(check["ok"])
        self.assertEqual(matched, command)

    def test_error_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            check, matched = check_setup.check_agent_registration(
                project_root, ".claude/settings.json", "claude", "claude_settings_registration"
            )
        self.assertFalse(check["ok"])
        self.assertIsNone(matched)
        self.assertIn("が存在しません", check["detail"])

    def test_error_when_json_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            path = project_root / ".claude" / "settings.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not json", encoding="utf-8")

            check, matched = check_setup.check_agent_registration(
                project_root, ".claude/settings.json", "claude", "claude_settings_registration"
            )
        self.assertFalse(check["ok"])
        self.assertIsNone(matched)

    def test_error_when_no_registration_found(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            _write_settings(
                project_root / ".claude" / "settings.json",
                "FORGE_MSG_AGENT_NAME=codex python3 /repo/hooks/check_inbox.py",
            )

            check, matched = check_setup.check_agent_registration(
                project_root, ".claude/settings.json", "claude", "claude_settings_registration"
            )
        self.assertFalse(check["ok"])
        self.assertIsNone(matched)


class CheckAgentRegistrationExistenceTest(unittest.TestCase):
    """`resolve_script_path` による実在確認（実 Codex レビューで発見の再発防止）。

    「.codex/hooks.json 上は登録されているように見えるが、参照先スクリプトが
    実際には存在しない」ケースを検出できなかったことで、Codex の Stop フックが
    無限にブロックし続ける事故（meta-plugin プロジェクトでの実インシデント）が
    起きた。文字列パターン一致だけでは不十分であることの回帰テスト。
    """

    def test_ok_when_resolved_script_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            _link_codex_scripts_to_real_msg_sys(project_root)
            _write_settings(project_root / ".codex" / "hooks.json", _codex_hook_command())

            check, matched = check_setup.check_agent_registration(
                project_root, ".codex/hooks.json", "codex", "codex_hooks_registration",
                resolve_script_path=check_setup._resolve_codex_hook_path,
            )
        self.assertTrue(check["ok"])
        self.assertIsNotNone(matched)

    def test_error_when_resolved_script_does_not_exist(self):
        """meta-plugin インシデントの直接再現: 登録は文字列としては正しいが、

        参照先スクリプトが実在しない（symlink 自体が無い）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            # あえて symlink を作らない（実在しない状態を再現する）。
            _write_settings(project_root / ".codex" / "hooks.json", _codex_hook_command())

            check, matched = check_setup.check_agent_registration(
                project_root, ".codex/hooks.json", "codex", "codex_hooks_registration",
                resolve_script_path=check_setup._resolve_codex_hook_path,
            )
        self.assertFalse(check["ok"])
        self.assertIsNone(matched)
        self.assertIn("実在しません", check["detail"])

    def test_claude_side_uses_direct_path_not_shell_evaluation(self):
        """claude 側は `${CLAUDE_PLUGIN_ROOT}` のシェル評価に依存せず、実ファイルの

        直接パス計算で実在確認できること（実行時に環境変数が無い文脈でも
        誤って失敗しない）。
        """
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", os.environ)
            check, matched = check_setup.check_agent_registration(
                Path("/unused"), check_setup._plugin_hooks_path(), "claude", "claude_plugin_hook_registration",
                resolve_script_path=lambda _exec_target, _root: str(check_setup._plugin_check_inbox_path()),
            )
        self.assertTrue(check["ok"])
        self.assertIsNotNone(matched)


class CheckMaxRoundTripsTest(unittest.TestCase):
    def test_ok_when_both_configured(self):
        claude_cmd = _claude_settings_command(max_round_trips="20")
        codex_cmd = _claude_settings_command(agent_name="codex", max_round_trips="20")
        result = check_setup.check_max_round_trips(claude_cmd, codex_cmd)
        self.assertTrue(result["ok"])

    def test_error_when_claude_missing(self):
        claude_cmd = _claude_settings_command(max_round_trips=None)
        codex_cmd = _claude_settings_command(agent_name="codex", max_round_trips="20")
        result = check_setup.check_max_round_trips(claude_cmd, codex_cmd)
        self.assertFalse(result["ok"])
        self.assertIn("forge プラグイン hooks/hooks.json 側", result["detail"])

    def test_error_when_codex_missing(self):
        claude_cmd = _claude_settings_command(max_round_trips="20")
        codex_cmd = _claude_settings_command(agent_name="codex", max_round_trips=None)
        result = check_setup.check_max_round_trips(claude_cmd, codex_cmd)
        self.assertFalse(result["ok"])
        self.assertIn(".codex/hooks.json 側", result["detail"])

    def test_error_when_both_missing(self):
        claude_cmd = _claude_settings_command(max_round_trips=None)
        codex_cmd = _claude_settings_command(agent_name="codex", max_round_trips=None)
        result = check_setup.check_max_round_trips(claude_cmd, codex_cmd)
        self.assertFalse(result["ok"])
        self.assertIn("forge プラグイン hooks/hooks.json 側", result["detail"])
        self.assertIn(".codex/hooks.json 側", result["detail"])

    def test_error_when_registration_entries_not_found(self):
        result = check_setup.check_max_round_trips(None, None)
        self.assertFalse(result["ok"])
        self.assertIn("forge プラグイン hooks/hooks.json 側の登録エントリ", result["detail"])
        self.assertIn(".codex/hooks.json 側の登録エントリ", result["detail"])

    def test_error_when_only_claude_command_present(self):
        result = check_setup.check_max_round_trips(_claude_settings_command(), None)
        self.assertFalse(result["ok"])
        self.assertIn(".codex/hooks.json 側の登録エントリ", result["detail"])


class RunChecksTest(unittest.TestCase):
    def _setup_full_repo(self, tmpdir, with_max_round_trips=True):
        project_root = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
        _link_codex_scripts_to_real_msg_sys(project_root)
        mrt = "20" if with_max_round_trips else None
        _write_settings(
            project_root / ".claude" / "settings.json",
            _claude_settings_command("claude", max_round_trips=mrt),
        )
        _write_settings(
            project_root / ".codex" / "hooks.json",
            _codex_hook_command(max_round_trips=mrt),
        )
        return project_root

    def test_status_ok_when_all_checks_pass(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir)
            result = check_setup.run_checks(project_root)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(all(c["ok"] for c in result["checks"]))

    def test_status_ok_when_invoked_from_subdirectory(self):
        """`--project-root` にリポジトリのサブディレクトリを指定しても正しく診断できること

        （実 Codex レビューで発見: `git rev-parse --show-toplevel` が返す canonical な
        toplevel を後続の DB パス・`.codex/hooks.json` 検査に伝播していなかったため、
        サブディレクトリ起点で実行すると正しく設定済みのリポジトリを誤って error
        と診断していた）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir)
            subdir = project_root / "some" / "nested" / "subdir"
            subdir.mkdir(parents=True)
            result = check_setup.run_checks(subdir)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(all(c["ok"] for c in result["checks"]))
        db_check = next(c for c in result["checks"] if c["name"] == "db_path_resolution")
        self.assertEqual(
            db_check["detail"],
            str(project_root.resolve() / ".claude" / ".temp" / "msg-sys" / "messages.db"),
        )

    def test_status_error_when_one_check_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # git init しない → git_root_resolution が失敗する
            project_root = Path(tmpdir)
            _write_settings(
                project_root / ".claude" / "settings.json",
                _claude_settings_command("claude"),
            )
            _write_settings(
                project_root / ".codex" / "hooks.json",
                _claude_settings_command("codex"),
            )
            result = check_setup.run_checks(project_root)
        self.assertEqual(result["status"], "error")

    def test_status_error_when_max_round_trips_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir, with_max_round_trips=False)
            result = check_setup.run_checks(project_root)
        self.assertEqual(result["status"], "error")
        mrt_check = next(c for c in result["checks"] if c["name"] == "max_round_trips_configured")
        self.assertFalse(mrt_check["ok"])

    def test_warnings_always_contain_two_unverifiable_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir)
            result = check_setup.run_checks(project_root)
        self.assertEqual(len(result["warnings"]), 2)

        with tempfile.TemporaryDirectory() as tmpdir:
            # error ケースでも warnings は変わらず含まれる
            project_root = Path(tmpdir)
            result = check_setup.run_checks(project_root)
        self.assertEqual(len(result["warnings"]), 2)


class OutputSchemaTest(unittest.TestCase):
    def test_top_level_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = check_setup.run_checks(project_root)
        self.assertEqual(set(result.keys()), {"status", "checks", "warnings"})
        self.assertIn(result["status"], ("ok", "error"))
        self.assertIsInstance(result["checks"], list)
        self.assertIsInstance(result["warnings"], list)

    def test_each_check_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
            result = check_setup.run_checks(project_root)
        for check in result["checks"]:
            self.assertEqual(set(check.keys()), {"name", "ok", "detail"})
            self.assertIsInstance(check["name"], str)
            self.assertIsInstance(check["ok"], bool)
            self.assertIsInstance(check["detail"], str)

    def test_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = check_setup.run_checks(project_root)
        # ensure_ascii=False での直列化が例外を出さないこと
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIsInstance(serialized, str)
        parsed = json.loads(serialized)
        self.assertEqual(parsed, result)

    def test_check_names_are_the_five_expected_items(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = check_setup.run_checks(project_root)
        names = {c["name"] for c in result["checks"]}
        self.assertEqual(
            names,
            {
                "git_root_resolution",
                "db_path_resolution",
                "claude_plugin_hook_registration",
                "codex_hooks_registration",
                "max_round_trips_configured",
            },
        )


class MainTest(unittest.TestCase):
    """main() を実際に呼び出し、CLI 契約（--project-root 解釈・単一 UTF-8 JSON 標準出力）を検証する（DES-034 §3.1）。"""

    def _setup_full_repo(self, tmpdir):
        project_root = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=tmpdir, capture_output=True, text=True)
        _link_codex_scripts_to_real_msg_sys(project_root)
        _write_settings(
            project_root / ".claude" / "settings.json",
            _claude_settings_command("claude"),
        )
        _write_settings(
            project_root / ".codex" / "hooks.json",
            _codex_hook_command(),
        )
        return project_root

    def test_project_root_arg_reflected_in_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir)
            output, exit_code = _run_main_capture(
                ["check_setup.py", "--project-root", str(project_root)]
            )
        self.assertEqual(exit_code, 0)
        result = json.loads(output.strip())
        self.assertEqual(result["status"], "ok")
        db_check = next(c for c in result["checks"] if c["name"] == "db_path_resolution")
        self.assertEqual(
            db_check["detail"],
            str(project_root.resolve() / ".claude" / ".temp" / "msg-sys" / "messages.db"),
        )

    def test_cwd_used_as_fallback_when_project_root_omitted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = self._setup_full_repo(tmpdir)
            with mock.patch.object(check_setup.os, "getcwd", return_value=str(project_root)):
                output, exit_code = _run_main_capture(["check_setup.py"])
        self.assertEqual(exit_code, 0)
        result = json.loads(output.strip())
        db_check = next(c for c in result["checks"] if c["name"] == "db_path_resolution")
        self.assertEqual(
            db_check["detail"],
            str(project_root.resolve() / ".claude" / ".temp" / "msg-sys" / "messages.db"),
        )

    def test_stdout_contains_single_json_line_with_no_extraneous_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # git init しない（status=error のケースでも出力形式が壊れないことを併せて確認する）
            project_root = Path(tmpdir)
            output, exit_code = _run_main_capture(
                ["check_setup.py", "--project-root", str(project_root)]
            )
        self.assertEqual(exit_code, 0)
        lines = output.splitlines()
        self.assertEqual(len(lines), 1)
        result = json.loads(lines[0])
        self.assertEqual(result["status"], "error")
        self.assertEqual(set(result.keys()), {"status", "checks", "warnings"})


if __name__ == "__main__":
    unittest.main()
