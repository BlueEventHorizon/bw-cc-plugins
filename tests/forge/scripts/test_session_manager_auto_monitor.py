#!/usr/bin/env python3
"""session_manager.cmd_init の monitor 自動起動統合テスト。

cmd_init が ensure_monitor_running を呼び、launcher.py 経由で
monitor_dir が作成され server.pid が書かれることを検証する。

失敗しても init 自体は成功する fault isolation も検証する。

設計書: DES-012 show-browser 設計書 v3.0
"""

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# プラグインスクリプトへの path を追加
_FORGE_SCRIPTS = (Path(__file__).resolve().parents[3]
                  / "plugins" / "forge" / "scripts")
sys.path.insert(0, str(_FORGE_SCRIPTS))

import session_manager  # noqa: E402


class _MonitorBaseCase(unittest.TestCase):
    """monitor 自動起動テストの基底: CWD を tmpdir にして .claude/.temp を作成。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)
        (self.tmpdir / ".claude" / ".temp").mkdir(parents=True, exist_ok=True)

        # launcher.py がブラウザを開かないよう環境変数で抑止
        self._orig_no_open = os.environ.get("FORGE_MONITOR_NO_OPEN")
        os.environ["FORGE_MONITOR_NO_OPEN"] = "1"
        # launcher.py が monitor_dir を tmpdir 配下に作るよう project_root を差し替え
        self._orig_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.tmpdir)
        # monitor スキップ環境変数は確実に解除(親プロセスの値を無視)
        self._orig_skip = os.environ.pop("FORGE_SESSION_SKIP_MONITOR", None)

    def tearDown(self):
        # 起動した server.py を後始末
        self._kill_monitor_servers()
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        if self._orig_no_open is None:
            os.environ.pop("FORGE_MONITOR_NO_OPEN", None)
        else:
            os.environ["FORGE_MONITOR_NO_OPEN"] = self._orig_no_open
        if self._orig_project_dir is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._orig_project_dir
        if self._orig_skip is not None:
            os.environ["FORGE_SESSION_SKIP_MONITOR"] = self._orig_skip

    def _kill_monitor_servers(self):
        """tmpdir 配下の monitor_dir から server.pid を読んで kill する。"""
        for pid_path in glob.glob(
            str(self.tmpdir / ".claude" / ".temp" / "*-monitor" / "server.pid")
        ):
            try:
                pid = int(Path(pid_path).read_text(encoding="utf-8").strip())
                os.kill(pid, 15)
            except (OSError, ValueError):
                pass


class _Args:
    def __init__(self, skill):
        self.skill = skill


class TestCmdInitLaunchesMonitor(_MonitorBaseCase):
    """cmd_init が monitor を自動起動する。"""

    def test_monitor_dir_created(self):
        """cmd_init 後に .claude/.temp/*-monitor/ が存在する。"""
        result = session_manager.cmd_init(_Args("review"), [])
        self.assertEqual(result["status"], "created")

        monitor_dirs = glob.glob(
            str(self.tmpdir / ".claude" / ".temp" / "*-monitor")
        )
        self.assertEqual(len(monitor_dirs), 1,
                         f"monitor ディレクトリが1個ではない: {monitor_dirs}")

    def test_config_json_records_skill(self):
        """monitor_dir/config.json に skill が記録される。"""
        result = session_manager.cmd_init(_Args("review"), [])
        self.assertEqual(result["status"], "created")

        monitor_dirs = glob.glob(
            str(self.tmpdir / ".claude" / ".temp" / "*-monitor")
        )
        self.assertTrue(monitor_dirs)
        config_path = os.path.join(monitor_dirs[0], "config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["skill"], "review")
        # session_dir が絶対パスで記録されている
        self.assertTrue(os.path.isabs(config["session_dir"]))

    def test_server_pid_written(self):
        """server.pid が 5 秒以内に書かれている。"""
        result = session_manager.cmd_init(_Args("review"), [])
        self.assertEqual(result["status"], "created")

        monitor_dirs = glob.glob(
            str(self.tmpdir / ".claude" / ".temp" / "*-monitor")
        )
        self.assertTrue(monitor_dirs)
        pid_path = os.path.join(monitor_dirs[0], "server.pid")
        # launcher.py は server.pid 出現を確認してから終了するので待機不要
        self.assertTrue(os.path.isfile(pid_path))
        pid = int(Path(pid_path).read_text(encoding="utf-8").strip())
        self.assertGreater(pid, 0)

    def test_monitor_field_in_init_result(self):
        """cmd_init の返り値に monitor 情報が含まれる。"""
        result = session_manager.cmd_init(_Args("review"), [])
        self.assertIn("monitor", result)
        self.assertTrue(result["monitor"]["ok"])
        self.assertIn("monitor_dir", result["monitor"])
        self.assertIn("port", result["monitor"])
        self.assertIn("url", result["monitor"])

    def test_monitor_dir_name_contains_skill(self):
        """monitor ディレクトリ名に skill が含まれる。"""
        result = session_manager.cmd_init(_Args("start-requirements"), [])
        self.assertEqual(result["status"], "created")
        monitor_dirs = glob.glob(
            str(self.tmpdir / ".claude" / ".temp" / "*-monitor")
        )
        self.assertTrue(monitor_dirs)
        self.assertIn("start-requirements", os.path.basename(monitor_dirs[0]))


class TestCmdInitSkipsMonitorViaEnv(_MonitorBaseCase):
    """FORGE_SESSION_SKIP_MONITOR=1 で monitor 起動をスキップできる。"""

    def test_env_skip_monitor(self):
        os.environ["FORGE_SESSION_SKIP_MONITOR"] = "1"
        try:
            result = session_manager.cmd_init(_Args("review"), [])
            self.assertEqual(result["status"], "created")
            self.assertFalse(result["monitor"]["ok"])
            self.assertEqual(result["monitor"]["reason"], "skipped_by_env")
            # monitor_dir は作られていない
            monitor_dirs = glob.glob(
                str(self.tmpdir / ".claude" / ".temp" / "*-monitor")
            )
            self.assertEqual(monitor_dirs, [])
        finally:
            os.environ.pop("FORGE_SESSION_SKIP_MONITOR", None)


class TestCmdInitMonitorFailureDoesNotBreakInit(_MonitorBaseCase):
    """monitor 起動失敗でも cmd_init は成功する(fault isolation)。"""

    def test_launcher_timeout_init_succeeds(self):
        """launcher.py が timeout しても session は作成される。"""
        # ensure_monitor_running を timeout シナリオに差し替える
        def fake(session_dir, skill, timeout=5.0):
            return {"ok": False, "reason": "launcher_timeout"}

        with mock.patch.object(session_manager, "ensure_monitor_running",
                               side_effect=fake):
            result = session_manager.cmd_init(_Args("review"), [])

        self.assertEqual(result["status"], "created")
        # session.yaml は作成されている
        yaml_path = os.path.join(result["session_dir"], "session.yaml")
        self.assertTrue(os.path.isfile(yaml_path))
        # monitor は失敗扱い
        self.assertFalse(result["monitor"]["ok"])
        self.assertEqual(result["monitor"]["reason"], "launcher_timeout")

    def test_launcher_raises_init_still_succeeds(self):
        """ensure_monitor_running が例外を投げても init は成功する。"""
        def fake(session_dir, skill, timeout=5.0):
            raise RuntimeError("simulated failure")

        with mock.patch.object(session_manager, "ensure_monitor_running",
                               side_effect=fake):
            result = session_manager.cmd_init(_Args("review"), [])

        self.assertEqual(result["status"], "created")
        self.assertFalse(result["monitor"]["ok"])
        self.assertEqual(result["monitor"]["reason"], "unexpected_error")


class TestEnsureMonitorRunningLauncherMissing(_MonitorBaseCase):
    """launcher.py が存在しなければ launcher_not_found が返る。"""

    def test_missing_launcher(self):
        """launcher.py の path 解決を差し替えて missing を再現。"""
        # monitor 同ディレクトリに存在しないファイル名を差し替える
        orig_isfile = os.path.isfile

        def fake_isfile(p):
            if p.endswith(os.path.join("monitor", "launcher.py")):
                return False
            return orig_isfile(p)

        with mock.patch("os.path.isfile", side_effect=fake_isfile):
            result = session_manager.ensure_monitor_running(
                str(self.tmpdir), "review"
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "launcher_not_found")


if __name__ == "__main__":
    unittest.main()
