"""wake_codex.sh の単体テスト（DES-045 §3.8）。

実際の cmux CLI・実際の常駐 Codex ペインには依存しない。PATH を制御して cmux の
有無を切り替え、スタブ cmux で呼び出し引数を記録することで、決定論的な分岐
（skipped / sent / failed）のみを検証する。実際に cmux が動くペインへ入力が
届くかどうかは統合テスト対象（手動）とする（DES-045 §7 の踏襲）。

対象ペインの発見はファイル（旧 `.codex/cmux_target.json`）に依存せず、`cmux
workspace list` → `cmux list-panels` を毎回その場で呼ぶ設計に変更された（ユーザー
指摘: キャッシュされた workspace ID が stale 化し push 起床が恒久的に機能しなく
なる実事故があったため、キャッシュを廃止した）。テストのスタブもこれに合わせて
`workspace list`/`list-panels` の両方を模擬する。
"""

import json
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "forge"
    / "scripts"
    / "msg-sys"
    / "cmux"
    / "wake_codex.sh"
)

# wake_codex.sh の WAKE_TEXT と同一文字列（send-key 失敗後の再確認テストで、入力欄が
# 自分の送信内容のままかどうかを判定するスタブの再現に使う）。
WAKE_TEXT = "（自動チェック）msg-sys の inbox に新着メッセージがあれば確認してください。無ければ何もしないでください。"


def _run(project_root: Path, path_env: str, retry_interval_seconds: str = "0") -> subprocess.CompletedProcess:
    # 本番の既定値（10秒）のままテストを走らせるとリトライ検証テストが著しく遅くなる
    # ため、テストでは待機を意味の無い実時間にしない目的でのみ短縮する。
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), str(project_root)],
        capture_output=True,
        text=True,
        env={"PATH": path_env, "WAKE_SEND_RETRY_INTERVAL_SECONDS": retry_interval_seconds},
    )


def _minimal_path_without_cmux() -> str:
    # cmux が存在しない PATH を作る。python3/bash 等の標準コマンドは通常の
    # システムパスに含まれるため、それらは残しつつ cmux の実体だけを除外する。
    return "/usr/bin:/bin:/usr/local/bin"


def _idle_screen(project_root: Path) -> str:
    return "gpt-5.6-terra medium · ~/somewhere\n› \n"


def _workspace_entry(workspace_id: str, cwd: str) -> dict:
    return {"id": workspace_id, "current_directory": cwd}


def _workspace_list_json(*workspaces: dict) -> str:
    return json.dumps({"workspaces": list(workspaces)})


def _default_workspace_list_json(project_root: Path, workspace_id: str = "workspace:5") -> str:
    """project_root の cwd と一致する workspace が単一件だけ見つかる既定の応答。"""
    return _workspace_list_json(_workspace_entry(workspace_id, str(project_root)))


def _surface_dict(surface_id: str, cwd: str) -> dict:
    """`cmux list-panels` の surface エントリを組み立てる（cwd の記録のみ。Codex かどうかの
    判定は list-panels のメタデータではなく `cmux top --processes` の実プロセス確認で行う）。
    """
    return {"id": surface_id, "requested_working_directory": cwd, "resume_binding": None}


def _panel_list_json(*surfaces: dict) -> str:
    return json.dumps({"surfaces": list(surfaces)})


def _default_panel_list_json(project_root: Path, surface_id: str = "surface:5") -> str:
    """project_root の cwd と一致する surface が単一件だけ見つかる既定の応答。"""
    return _panel_list_json(_surface_dict(surface_id, str(project_root)))


def _top_processes_json(*surface_processes: tuple[str, str]) -> str:
    """`cmux top --processes --json --id-format uuids` の応答を組み立てる。
    surface_processes: [(surface_id, process_name), ...]
    """
    surfaces = [
        {"id": surface_id, "processes": [{"name": name, "cmux_surface_id": surface_id}]}
        for surface_id, name in surface_processes
    ]
    return json.dumps({"windows": [{"workspaces": [{"panes": [{"surfaces": surfaces}]}]}]})


def _default_top_processes_json(surface_id: str = "surface:5") -> str:
    """既定の Codex surface（surface:5）に codex プロセスがアタッチされている応答。"""
    return _top_processes_json((surface_id, "codex-aarch64-a"))


def _write_cmux_stub(
    bin_dir: Path,
    *,
    exit_code: int,
    calls_log: Path,
    screen_text: str,
    screen_exit_code: int = 0,
    workspace_list_json: str = '{"workspaces": []}',
    workspace_list_exit_code: int = 0,
    panels_json: str = '{"surfaces": []}',
    panels_exit_code: int = 0,
    top_processes_json: str = '{"windows": []}',
    top_processes_exit_code: int = 0,
) -> None:
    """スタブ cmux を作る。

    `workspace list` は `workspace_list_json` を返す。`list-panels --workspace <id>` は
    どの workspace id が渡されても一律 `panels_json` を返す（複数 workspace で異なる
    応答が必要なテストは個別にスタブスクリプトを書く）。`top --processes --json --id-format uuids`
    は find_codex_pane.py の Codex プロセス確認（cwd が一致する surface がある場合に必ず
    呼ばれる。唯一の検出方式であり、`list-panels` のメタデータで判定するフォールバック等は
    存在しない）向けに `top_processes_json`（既定: 該当プロセス無し）を返す。`read-screen` は
    `screen_text` を返す。それ以外（`send`/`send-key`）は呼び出し引数を calls_log に1行ずつ
    追記し、`exit_code` で終了する。
    """
    stub = bin_dir / "cmux"
    stub.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then\n'
        f"  cat <<'WAKE_CODEX_TEST_WS_EOF'\n{workspace_list_json}\nWAKE_CODEX_TEST_WS_EOF\n"
        f"  exit {workspace_list_exit_code}\n"
        "fi\n"
        'if [ "$1" = "list-panels" ]; then\n'
        f"  cat <<'WAKE_CODEX_TEST_PANELS_EOF'\n{panels_json}\nWAKE_CODEX_TEST_PANELS_EOF\n"
        f"  exit {panels_exit_code}\n"
        "fi\n"
        'if [ "$1" = "top" ]; then\n'
        f"  cat <<'WAKE_CODEX_TEST_TOP_EOF'\n{top_processes_json}\nWAKE_CODEX_TEST_TOP_EOF\n"
        f"  exit {top_processes_exit_code}\n"
        "fi\n"
        'if [ "$1" = "read-screen" ]; then\n'
        f"  cat <<'WAKE_CODEX_TEST_SCREEN_EOF'\n"
        f"{screen_text}"
        "WAKE_CODEX_TEST_SCREEN_EOF\n"
        f"  exit {screen_exit_code}\n"
        "fi\n"
        f'echo "$@" >> "{calls_log}"\n'
        f"exit {exit_code}\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class WakeCodexSkipTest(unittest.TestCase):
    def test_skipped_when_cmux_not_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            result = _run(project_root, _minimal_path_without_cmux())

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertIn("cmux", payload["reason"])


class WakeCodexDiscoveryTest(unittest.TestCase):
    """対象ペインの発見（ファイルへのキャッシュ無し、毎回その場で discover する設計。
    ユーザー指摘: `.codex/cmux_target.json` に発見結果をキャッシュしていた旧設計は、
    cmux が同じ pane を維持したまま workspace ID だけを再発行することがあり、
    stale 化して push 起床が恒久的に機能しなくなる実事故があったため廃止した）。
    """

    def test_failed_when_workspace_list_command_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=bin_dir / "calls.log",
                    screen_text="", workspace_list_exit_code=1,
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("探索に失敗", payload["reason"])

    def test_failed_when_workspace_list_returns_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=bin_dir / "calls.log",
                    screen_text="", workspace_list_json="not json",
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")

    def test_skipped_when_no_workspace_matches_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other_dir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text="",
                    workspace_list_json=_workspace_list_json(_workspace_entry("workspace:1", other_dir)),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertFalse(calls_log_exists)

    def test_failed_when_list_panels_command_fails_for_matching_workspace(self):
        """workspace は project_root と一致するが、その list-panels 呼び出しが失敗する場合。

        pane の有無を確認できない以上、「対象なし」という正常な見送りには分類しない。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text="",
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_exit_code=1,
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(calls_log_exists)

    def test_skipped_when_workspace_matches_but_no_codex_process(self):
        """workspace の cwd は一致するが、その surface に Codex プロセスが稼働していない場合。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text="",
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_panel_list_json(_surface_dict("surface:1", str(project_root))),
                    top_processes_json=_top_processes_json(("surface:1", "zsh")),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertFalse(calls_log_exists)

    def test_skipped_when_codex_pane_cwd_differs_from_workspace_directory(self):
        """workspace の cwd は一致するが、pane 自身の cwd が異なる（例: cd 済み）場合。"""
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as other_dir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text="",
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_panel_list_json(_surface_dict("surface:1", other_dir)),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertFalse(calls_log_exists)

    def test_skipped_when_multiple_codex_panes_match(self):
        """複数の workspace がいずれも project_root と一致し、それぞれに Codex pane が
        見つかった場合（曖昧）。自動選択を見送る。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text="",
                    workspace_list_json=_workspace_list_json(
                        _workspace_entry("workspace:1", str(project_root)),
                        _workspace_entry("workspace:2", str(project_root)),
                    ),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertFalse(calls_log_exists)

    def test_proceeds_when_single_codex_pane_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log,
                    screen_text=_idle_screen(project_root),
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")

    def test_proceeds_when_codex_launched_as_plain_shell_command(self):
        """ユーザー報告バグの再現: 通常のターミナル surface で codex CLI を直接起動した
        構成（cmux の resume 経由ではない）でも、実プロセス確認により発見・送信できる。
        list-panels 側のメタデータ（resume_binding/initial_command）には何の記録も無いが、
        `cmux top --processes` が実プロセスを直接返すため検出方式に影響しない。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log,
                    screen_text=_idle_screen(project_root),
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_panel_list_json(_surface_dict("surface:5", str(project_root))),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")


class WakeCodexBusyGuardTest(unittest.TestCase):
    """送信前の稼働状態確認（Codex レビューで発見: 検証なしの注入は誤投入・入力破壊のリスク）。"""

    def test_failed_when_read_screen_command_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=bin_dir / "calls.log",
                    screen_text="", screen_exit_code=1,
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("read-screen", payload["reason"])

    def test_skipped_when_target_pane_is_busy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log,
                    screen_text="• Working (12s • esc to interrupt)\n",
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                # send/send-key は一切呼ばれていない（calls_log が作られない）
                calls_log_exists = calls_log.exists()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        self.assertIn("作業中", payload["reason"])
        self.assertFalse(calls_log_exists)

    def test_skipped_when_read_screen_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=bin_dir / "calls.log",
                    screen_text="", screen_exit_code=0,
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")


class WakeCodexPreSendFieldContentTest(unittest.TestCase):
    """送信前は入力欄の内容を確認しない（設計方針・ユーザー指摘・実機確認済み）。

    旧実装は入力欄が既知プレースホルダーと完全一致するときだけ「空扱い」で送信し、
    それ以外の内容が残っていれば下書き破壊を避けて見送っていた。しかし実機の常駐
    Codex ペインでは、履歴の巻き戻り（上下キー）等による残留テキストが入力欄に
    残っているのが定常状態であり、この安全ゲートは実運用でほぼ常に成立し push 起床
    を恒久的に無効化していた（ユーザー報告・実機確認済み）。busy でないと確認できた
    時点で、入力欄の内容に関わらず送信する。
    """

    def test_sends_even_when_prompt_line_is_not_found(self):
        """`›` で始まる行自体が見つからない場合でも busy でなければ送信する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen = "gpt-5.6-terra medium · ~/somewhere\n(no prompt line here)\n"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text=screen,
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")

    def test_sends_even_when_multiple_prompt_lines_found(self):
        """`›` で始まる行が複数見つかった場合でも busy でなければ送信する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen = (
                    "gpt-5.6-terra medium · ~/somewhere\n"
                    "› 過去に送信されたメッセージの再表示\n"
                    "› \n"
                )
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text=screen,
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")

    def test_sends_even_when_prompt_line_has_leftover_text(self):
        """入力欄に履歴巻き戻り等の残留テキストがあっても見送らず送信する（実機バグ報告の再現）。

        `cmux send` が追記ではなく上書きすることは実機検証済みであり、実機の常駐
        Codex ペインではこの残留テキストが定常状態であることをユーザーが確認した
        （上下キーで過去の入力が表示される挙動）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen = "gpt-5.6-terra medium · ~/somewhere\n› 受信してないですか？\n"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log, screen_text=screen,
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")


class WakeCodexSendTest(unittest.TestCase):
    def test_sent_calls_send_then_send_key_enter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=0, calls_log=calls_log,
                    screen_text=_idle_screen(project_root),
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")

                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].startswith("send --workspace workspace:5 --surface surface:5"))
        self.assertEqual(calls[1], "send-key --workspace workspace:5 --surface surface:5 enter")

    def test_failed_when_cmux_send_errors(self):
        """安全ゲートを全て通過した上で cmux send 自体が失敗し続ける場合。

        ユーザー指摘対応: 安全ゲート通過後の送信失敗は best-effort で即座に諦めず、
        3回リトライしてから最終的に failed とする（cmux send は失敗すると exit code
        の時点で && が短絡し send-key は呼ばれないため、リトライ1回につき send の
        呼び出しが1件だけ calls_log に記録される）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                _write_cmux_stub(
                    bin_dir, exit_code=1, calls_log=calls_log,
                    screen_text=_idle_screen(project_root),
                    workspace_list_json=_default_workspace_list_json(project_root),
                    panels_json=_default_panel_list_json(project_root),
                    top_processes_json=_default_top_processes_json(),
                )
                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("3", payload["reason"])
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c.startswith("send --workspace") for c in calls))

    def test_sent_after_transient_send_failure_then_success(self):
        """1回目の cmux send が失敗しても、リトライで成功すれば sent とする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                counter_file = bin_dir / "send_attempts.count"
                stub = bin_dir / "cmux"
                stub.write_text(
                    "#!/bin/bash\n"
                    'if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then\n'
                    f"  cat <<'EOF'\n{_default_workspace_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "read-screen" ]; then\n'
                    f"  cat <<'EOF'\n{_idle_screen(project_root)}EOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "list-panels" ]; then\n'
                    f"  cat <<'EOF'\n{_default_panel_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "top" ]; then\n'
                    f"  cat <<'EOF'\n{_default_top_processes_json()}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send" ]; then\n'
                    f'  count=$(( $(cat "{counter_file}" 2>/dev/null || echo 0) + 1 ))\n'
                    f'  echo "$count" > "{counter_file}"\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    '  if [ "$count" -lt 2 ]; then exit 1; else exit 0; fi\n'
                    "fi\n"
                    f'echo "$@" >> "{calls_log}"\n'
                    "exit 0\n"
                )
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")
        # 1回目 send（失敗）、2回目 send（成功）、send-key の3件。
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[2], "send-key --workspace workspace:5 --surface surface:5 enter")

    def test_retries_send_key_only_when_field_still_holds_wake_text_after_send_key_failure(self):
        """cmux send は成功したが send-key だけ失敗した場合、入力欄が自分の WAKE_TEXT の
        ままであれば send-key のみ再試行し、text は再送しない（実 Codex レビューで発見の
        TOCTOU 対策。「空欄か」を再チェックすると自分が書き込んだ WAKE_TEXT 自体が常に
        疑わしいと誤判定されリトライが機能しなくなるため、「自分が送った文字列のままか」
        だけを確認する）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen_call_counter = bin_dir / "screen_calls.count"
                send_key_counter = bin_dir / "send_key_calls.count"
                stub = bin_dir / "cmux"
                stub.write_text(
                    "#!/bin/bash\n"
                    'if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then\n'
                    f"  cat <<'EOF'\n{_default_workspace_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "list-panels" ]; then\n'
                    f"  cat <<'EOF'\n{_default_panel_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "top" ]; then\n'
                    f"  cat <<'EOF'\n{_default_top_processes_json()}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "read-screen" ]; then\n'
                    f'  n=$(( $(cat "{screen_call_counter}" 2>/dev/null || echo 0) + 1 ))\n'
                    f'  echo "$n" > "{screen_call_counter}"\n'
                    '  if [ "$n" -le 1 ]; then\n'
                    f"    cat <<'EOF'\n{_idle_screen(project_root)}EOF\n"
                    "  else\n"
                    f"    cat <<'EOF'\ngpt-5.6-terra medium · ~/somewhere\n› {WAKE_TEXT}\nEOF\n"
                    "  fi\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send" ]; then\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send-key" ]; then\n'
                    f'  k=$(( $(cat "{send_key_counter}" 2>/dev/null || echo 0) + 1 ))\n'
                    f'  echo "$k" > "{send_key_counter}"\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    '  if [ "$k" -lt 2 ]; then exit 1; else exit 0; fi\n'
                    "fi\n"
                    f'echo "$@" >> "{calls_log}"\n'
                    "exit 0\n"
                )
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "sent")
        send_calls = [c for c in calls if c.split(" ", 1)[0] == "send"]
        send_key_calls = [c for c in calls if c.split(" ", 1)[0] == "send-key"]
        # send は1回だけ（テキストは再送されていない）、send-key は2回（1回目失敗・2回目成功）。
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(len(send_key_calls), 2)

    def test_skipped_when_field_changed_after_send_key_failure(self):
        """cmux send は成功したが send-key だけ失敗し、再確認時に入力欄の内容が自分の
        WAKE_TEXT と一致しなかった場合、それ以上の注入をやめて見送る（実 Codex レビューで
        発見: 待機中に利用者が入力欄へ書き込んだ内容を無条件に上書きするリスクへの対策）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen_call_counter = bin_dir / "screen_calls.count"
                stub = bin_dir / "cmux"
                stub.write_text(
                    "#!/bin/bash\n"
                    'if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then\n'
                    f"  cat <<'EOF'\n{_default_workspace_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "list-panels" ]; then\n'
                    f"  cat <<'EOF'\n{_default_panel_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "top" ]; then\n'
                    f"  cat <<'EOF'\n{_default_top_processes_json()}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "read-screen" ]; then\n'
                    f'  n=$(( $(cat "{screen_call_counter}" 2>/dev/null || echo 0) + 1 ))\n'
                    f'  echo "$n" > "{screen_call_counter}"\n'
                    '  if [ "$n" -le 1 ]; then\n'
                    f"    cat <<'EOF'\n{_idle_screen(project_root)}EOF\n"
                    "  else\n"
                    "    printf 'gpt-5.6-terra medium · ~/somewhere\\n› 利用者が新しく入力した内容\\n'\n"
                    "  fi\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send" ]; then\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send-key" ]; then\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    "  exit 1\n"
                    "fi\n"
                    f'echo "$@" >> "{calls_log}"\n'
                    "exit 0\n"
                )
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        send_calls = [c for c in calls if c.split(" ", 1)[0] == "send"]
        send_key_calls = [c for c in calls if c.split(" ", 1)[0] == "send-key"]
        # send-key が繰り返し失敗しても、入力欄が変化した時点で send は再送されない。
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(len(send_key_calls), 1)

    def test_skipped_when_retry_check_finds_multiple_prompt_lines(self):
        """send-key 失敗後の再確認で `›` 行が複数見つかった場合も、一意に確認できない
        として send を再送しない（実 Codex レビューで発見: 複数候補を機械的に選ぶと
        履歴上のテキストと混同しうる）。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            with tempfile.TemporaryDirectory() as bin_dir_str:
                bin_dir = Path(bin_dir_str)
                calls_log = bin_dir / "calls.log"
                screen_call_counter = bin_dir / "screen_calls.count"
                stub = bin_dir / "cmux"
                stub.write_text(
                    "#!/bin/bash\n"
                    'if [ "$1" = "workspace" ] && [ "$2" = "list" ]; then\n'
                    f"  cat <<'EOF'\n{_default_workspace_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "list-panels" ]; then\n'
                    f"  cat <<'EOF'\n{_default_panel_list_json(project_root)}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "top" ]; then\n'
                    f"  cat <<'EOF'\n{_default_top_processes_json()}\nEOF\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "read-screen" ]; then\n'
                    f'  n=$(( $(cat "{screen_call_counter}" 2>/dev/null || echo 0) + 1 ))\n'
                    f'  echo "$n" > "{screen_call_counter}"\n'
                    '  if [ "$n" -le 1 ]; then\n'
                    f"    cat <<'EOF'\n{_idle_screen(project_root)}EOF\n"
                    "  else\n"
                    f"    cat <<'EOF'\ngpt-5.6-terra medium · ~/somewhere\n› 過去のメッセージ\n› {WAKE_TEXT}\nEOF\n"
                    "  fi\n"
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send" ]; then\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    "  exit 0\n"
                    "fi\n"
                    'if [ "$1" = "send-key" ]; then\n'
                    f'  echo "$@" >> "{calls_log}"\n'
                    "  exit 1\n"
                    "fi\n"
                    f'echo "$@" >> "{calls_log}"\n'
                    "exit 0\n"
                )
                stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

                result = _run(project_root, f"{bin_dir}:/usr/bin:/bin")
                calls = calls_log.read_text().splitlines()

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "skipped")
        send_calls = [c for c in calls if c.split(" ", 1)[0] == "send"]
        send_key_calls = [c for c in calls if c.split(" ", 1)[0] == "send-key"]
        self.assertEqual(len(send_calls), 1)
        self.assertEqual(len(send_key_calls), 1)


if __name__ == "__main__":
    unittest.main()
