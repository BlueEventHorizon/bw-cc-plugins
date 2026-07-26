"""find_codex_pane.py の単体テスト（DES-045 §3.8 補足）。

`wake_codex.sh` の inline Python として存在していた発見ロジックを、DES-048（未実装）の
Step 1.6・`check_codex_liveness.py` からも再利用できるよう独立スクリプトへ切り出した
（実 Codex レビューで発見: 発見ロジックを重複実装すると liveness 判定と push 起床対象が
ずれる恐れがある）。本テストは `find_codex_pane()` を直接 import し、`subprocess.run` を
モックすることで、`wake_codex.sh` 経由の bash subprocess 実行より高速・直接的に検証する。

検出方式は `cmux top --processes --json --id-format uuids` による実プロセス確認のみ
（`resume_binding`/`initial_command` の正規表現判定は、実際に稼働している Codex プロセスを
見逃す実バグがあり撤去した。実プロセス確認はその上位互換であり二重に持つ理由が無い）。
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "msg-sys" / "cmux" / "find_codex_pane.py"
)

_spec = importlib.util.spec_from_file_location("msg_sys_find_codex_pane", _SCRIPT_PATH)
find_codex_pane_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(find_codex_pane_mod)


def _completed(stdout, returncode=0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=json.dumps(stdout), stderr="")


def _workspace_list_json(*workspaces: dict) -> dict:
    return {"workspaces": list(workspaces)}


def _panel_list_json(*surfaces: dict) -> dict:
    return {"surfaces": list(surfaces)}


def _surface(surface_id: str, cwd: str | None) -> dict:
    return {"id": surface_id, "requested_working_directory": cwd, "resume_binding": None}


def _top_processes_json(workspace_id: str, surfaces: list[dict]) -> dict:
    """`cmux top --processes --json --id-format uuids` の最小限のスキーマを模したフィクスチャ。
    surfaces: [{"id": "...", "processes": [{"name": "...", "cmux_surface_id": "..."}, ...]}]
    """
    return {"windows": [{"workspaces": [{"id": workspace_id, "panes": [{"surfaces": surfaces}]}]}]}


def _codex_process(surface_id: str, name: str = "codex-aarch64-a") -> dict:
    return {"name": name, "cmux_surface_id": surface_id}


def _other_process(surface_id: str, name: str = "zsh") -> dict:
    return {"name": name, "cmux_surface_id": surface_id}


_NO_CODEX_PROCESSES = {"windows": []}


class FindCodexPaneErrorTest(unittest.TestCase):
    def test_error_when_workspace_list_command_fails(self):
        with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=_completed({}, returncode=1)):
            result = find_codex_pane_mod.find_codex_pane("/some/project")
        self.assertEqual(result["status"], "error")

    def test_error_includes_workspace_list_stderr(self):
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="socket access denied")
        with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=proc):
            result = find_codex_pane_mod.find_codex_pane("/some/project")
        self.assertEqual(result["status"], "error")
        self.assertIn("socket access denied", result["reason"])

    def test_error_when_workspace_list_returns_invalid_json(self):
        bad_proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=bad_proc):
            result = find_codex_pane_mod.find_codex_pane("/some/project")
        self.assertEqual(result["status"], "error")

    def test_error_when_workspace_list_has_invalid_schema(self):
        bad_proc = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"workspaces": "not-a-list"}), stderr=""
        )
        with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=bad_proc):
            result = find_codex_pane_mod.find_codex_pane("/some/project")
        self.assertEqual(result["status"], "error")

    def test_error_when_workspace_list_raises(self):
        with mock.patch.object(find_codex_pane_mod.subprocess, "run", side_effect=OSError("no cmux")):
            result = find_codex_pane_mod.find_codex_pane("/some/project")
        self.assertEqual(result["status"], "error")


class FindCodexPaneNoMatchTest(unittest.TestCase):
    def test_not_found_when_no_workspace_matches_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-OTHER", "current_directory": "/somewhere/else"})
            with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=_completed(ws_json)):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "not_found")

    def test_error_when_list_panels_fails_for_matching_workspace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed({}, returncode=1)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "error")

    def test_error_when_matching_workspace_has_no_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"current_directory": project_root})
            with mock.patch.object(find_codex_pane_mod.subprocess, "run", return_value=_completed(ws_json)):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "error")

    def test_error_when_list_panels_has_invalid_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            invalid_panels = {"surfaces": "not-a-list"}
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(invalid_panels)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "error")

    def test_error_when_any_matching_workspace_cannot_be_inspected(self):
        """候補が一件見つかっても、別の同一 cwd workspace を調べられない場合は
        自動選択しない。未調査の pane への誤投入を避け、障害を可視化する。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json(
                {"id": "WS-1", "current_directory": project_root},
                {"id": "WS-2", "current_directory": project_root},
            )
            panel_json = _panel_list_json(_surface("SURF-1", project_root))
            top_json = _top_processes_json("WS-1", [{"id": "SURF-1", "processes": [_codex_process("SURF-1")]}])
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[
                    _completed(ws_json), _completed(panel_json), _completed(top_json),
                    _completed({}, returncode=1),
                ],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "error")

    def test_not_found_when_workspace_matches_but_no_codex_process(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            panel_json = _panel_list_json(_surface("SURF-1", project_root))
            top_json = _top_processes_json("WS-1", [{"id": "SURF-1", "processes": [_other_process("SURF-1")]}])
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(panel_json), _completed(top_json)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "not_found")

    def test_not_found_when_codex_pane_cwd_differs_from_workspace_directory(self):
        """プロセスツリー走査で codex プロセスが見つかっても、その surface の cwd が
        project_root と一致しない場合は候補にしない（無関係な別プロジェクトの Codex を
        誤検出しないため）。この場合、無駄な top --processes 呼び出しも行わない。
        """
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other_dir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            panel_json = _panel_list_json(_surface("SURF-1", other_dir))
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(panel_json)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "not_found")

    def test_error_when_process_tree_check_command_fails(self):
        """cwd が一致する surface があるのに `cmux top --processes` 自体が失敗した場合は
        `not_found` で隠蔽せず、機械的エラーとして報告する（存在確認ができなかったことと
        存在しないことは区別する）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            panel_json = _panel_list_json(_surface("SURF-1", project_root))
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(panel_json), _completed({}, returncode=1)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "error")


class FindCodexPaneAmbiguousTest(unittest.TestCase):
    def test_ambiguous_when_multiple_codex_panes_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json(
                {"id": "WS-1", "current_directory": project_root},
                {"id": "WS-2", "current_directory": project_root},
            )
            panel_json_1 = _panel_list_json(_surface("SURF-1", project_root))
            panel_json_2 = _panel_list_json(_surface("SURF-2", project_root))
            top_json_1 = _top_processes_json("WS-1", [{"id": "SURF-1", "processes": [_codex_process("SURF-1")]}])
            top_json_2 = _top_processes_json("WS-2", [{"id": "SURF-2", "processes": [_codex_process("SURF-2")]}])
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[
                    _completed(ws_json),
                    _completed(panel_json_1), _completed(top_json_1),
                    _completed(panel_json_2), _completed(top_json_2),
                ],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "ambiguous")


class FindCodexPaneFoundTest(unittest.TestCase):
    def test_found_when_single_codex_pane_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            panel_json = _panel_list_json(_surface("SURF-1", project_root))
            top_json = _top_processes_json("WS-1", [{"id": "SURF-1", "processes": [_codex_process("SURF-1")]}])
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(panel_json), _completed(top_json)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result, {"status": "found", "workspace": "WS-1", "surface": "SURF-1"})

    def test_found_when_codex_launched_as_plain_shell_command(self):
        """ユーザー報告バグの再現: 通常のターミナル surface で codex CLI を直接起動した
        構成（cmux の resume 経由ではない）でも、実プロセス確認により発見できる。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = str(Path(tmpdir).resolve())
            ws_json = _workspace_list_json({"id": "WS-1", "current_directory": project_root})
            panel_json = _panel_list_json(_surface("SURF-1", project_root))
            top_json = _top_processes_json("WS-1", [{"id": "SURF-1", "processes": [_codex_process("SURF-1")]}])
            with mock.patch.object(
                find_codex_pane_mod.subprocess, "run",
                side_effect=[_completed(ws_json), _completed(panel_json), _completed(top_json)],
            ):
                result = find_codex_pane_mod.find_codex_pane(project_root)
            self.assertEqual(result["status"], "found")


class MainTest(unittest.TestCase):
    def test_cli_outputs_single_json_and_exit_code_matches_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["python3", str(_SCRIPT_PATH), tmpdir],
                capture_output=True, text=True,
            )
        payload = json.loads(result.stdout)
        self.assertIn(payload["status"], {"not_found", "error"})
        self.assertEqual(result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
