#!/usr/bin/env python3
"""monitor/launcher.py の単体テスト。

find_free_port / cleanup_orphan_monitors / create_monitor_dir / _should_skip_open
のテスト。config.json に skill キーが記録されることを検証する。

設計書: DES-012 show-browser 設計書 v3.0 (§5.1 / §5.10)
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# launcher.py へのパスを追加(monitor/ 配下)
MONITOR_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "plugins", "forge", "scripts", "monitor",
)
sys.path.insert(0, os.path.abspath(MONITOR_DIR))

from launcher import (  # noqa: E402
    DEFAULT_PORT,
    DEFAULT_PORT_ATTEMPTS,
    NO_OPEN_ENV,
    cleanup_orphan_monitors,
    create_monitor_dir,
    find_free_port,
    _should_skip_open,
)


_TEST_TMP_BASE = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    ".claude", ".temp", "test_tmp",
))


def setUpModule():
    # 前回の中断で残った残骸をクリーンスタート
    if os.path.isdir(_TEST_TMP_BASE):
        shutil.rmtree(_TEST_TMP_BASE)
    os.makedirs(_TEST_TMP_BASE, exist_ok=True)


def tearDownModule():
    # 子テストの cleanup 漏れを巻き取る
    if os.path.isdir(_TEST_TMP_BASE):
        shutil.rmtree(_TEST_TMP_BASE)


class TestFindFreePort(unittest.TestCase):
    """find_free_port() のテスト。"""

    def test_returns_int(self):
        port = find_free_port(start=19200)
        self.assertIsInstance(port, int)

    def test_port_in_range(self):
        port = find_free_port(start=19200)
        self.assertGreaterEqual(port, 19200)

    def test_port_is_free(self):
        import socket
        port = find_free_port(start=19300)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))

    def test_fallback_when_start_port_busy(self):
        """start が占有済みでも次のポートにフォールバックする。"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupier:
            occupier.bind(("127.0.0.1", 19400))
            occupier.listen(1)
            port = find_free_port(start=19400, attempts=5)
            self.assertNotEqual(port, 19400)
            self.assertGreater(port, 19400)
            self.assertLess(port, 19405)

    def test_raises_when_no_port_available(self):
        """attempts を尽くしても空きがなければ RuntimeError。"""
        import socket
        sockets = []
        try:
            for i in range(3):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", 19500 + i))
                s.listen(1)
                sockets.append(s)
            with self.assertRaises(RuntimeError):
                find_free_port(start=19500, attempts=3)
        finally:
            for s in sockets:
                s.close()

    def test_default_attempts_is_11(self):
        """DEFAULT_PORT_ATTEMPTS は 8765〜8775 をカバーする 11。"""
        self.assertEqual(DEFAULT_PORT_ATTEMPTS, 11)

    def test_default_port_is_8765(self):
        """DEFAULT_PORT は 8765。"""
        self.assertEqual(DEFAULT_PORT, 8765)


class TestCreateMonitorDir(unittest.TestCase):
    """create_monitor_dir() のテスト。config.json に skill キーが記録される。"""

    def setUp(self):
        self.project_root = tempfile.mkdtemp(dir=_TEST_TMP_BASE)
        self.session_dir = tempfile.mkdtemp(dir=self.project_root)

    def tearDown(self):
        shutil.rmtree(self.project_root, ignore_errors=True)

    def test_creates_directory(self):
        monitor_dir = create_monitor_dir(
            self.project_root, "review", self.session_dir, 8765,
        )
        self.assertTrue(os.path.isdir(monitor_dir))

    def test_config_records_skill(self):
        """config.json に skill キーが(template ではなく)記録される。"""
        monitor_dir = create_monitor_dir(
            self.project_root, "review", self.session_dir, 8765,
        )
        with open(os.path.join(monitor_dir, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["skill"], "review")
        self.assertEqual(config["port"], 8765)
        self.assertEqual(config["session_dir"], os.path.abspath(self.session_dir))
        self.assertNotIn("template", config)

    def test_monitor_dir_name_contains_skill(self):
        """monitor ディレクトリ名に skill 名が含まれる。"""
        monitor_dir = create_monitor_dir(
            self.project_root, "start-requirements", self.session_dir, 8765,
        )
        self.assertIn("start-requirements", os.path.basename(monitor_dir))

    def test_monitor_dir_name_ends_with_monitor(self):
        monitor_dir = create_monitor_dir(
            self.project_root, "review", self.session_dir, 8765,
        )
        self.assertTrue(os.path.basename(monitor_dir).endswith("-monitor"))

    def test_monitor_dir_under_temp(self):
        monitor_dir = create_monitor_dir(
            self.project_root, "review", self.session_dir, 8765,
        )
        expected_parent = os.path.join(self.project_root, ".claude", ".temp")
        self.assertEqual(os.path.dirname(monitor_dir), expected_parent)


class TestCleanupOrphanMonitors(unittest.TestCase):
    """cleanup_orphan_monitors() のテスト。"""

    def setUp(self):
        self.project_root = tempfile.mkdtemp(dir=_TEST_TMP_BASE)

    def tearDown(self):
        shutil.rmtree(self.project_root, ignore_errors=True)

    def _make_monitor_dir(self, name):
        # 名前は *-monitor にマッチする必要がある
        d = os.path.join(self.project_root, ".claude", ".temp", name)
        os.makedirs(d, exist_ok=True)
        return d

    def test_removes_dir_without_pid(self):
        monitor_dir = self._make_monitor_dir("old-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            "{}", encoding="utf-8"
        )
        cleanup_orphan_monitors(self.project_root)
        self.assertFalse(os.path.isdir(monitor_dir))

    def test_removes_dir_with_dead_pid(self):
        monitor_dir = self._make_monitor_dir("dead-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            "{}", encoding="utf-8"
        )
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            "99999", encoding="utf-8"
        )
        try:
            os.kill(99999, 0)
            # PID が生きていたらスキップ
        except ProcessLookupError:
            cleanup_orphan_monitors(self.project_root)
            self.assertFalse(os.path.isdir(monitor_dir))
        except PermissionError:
            pass

    def test_keeps_dir_with_alive_pid(self):
        monitor_dir = self._make_monitor_dir("alive-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            "{}", encoding="utf-8"
        )
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            str(os.getpid()), encoding="utf-8"
        )
        cleanup_orphan_monitors(self.project_root)
        self.assertTrue(os.path.isdir(monitor_dir))

    def test_no_temp_dir_no_error(self):
        cleanup_orphan_monitors(self.project_root)

    def test_removes_dir_with_malformed_pid(self):
        """server.pid が数値でない場合も孤立として削除される。"""
        monitor_dir = self._make_monitor_dir("bad-monitor")
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            "notanumber", encoding="utf-8"
        )
        cleanup_orphan_monitors(self.project_root)
        self.assertFalse(os.path.isdir(monitor_dir))


class TestShouldSkipOpen(unittest.TestCase):
    """_should_skip_open() — FORGE_MONITOR_NO_OPEN 環境変数による抑制。"""

    def test_unset_returns_false(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(NO_OPEN_ENV, None)
            self.assertFalse(_should_skip_open())

    def test_empty_returns_false(self):
        with mock.patch.dict(os.environ, {NO_OPEN_ENV: ""}):
            self.assertFalse(_should_skip_open())

    def test_truthy_values_return_true(self):
        for val in ("1", "true", "yes", "on", "TRUE", "Yes"):
            with mock.patch.dict(os.environ, {NO_OPEN_ENV: val}):
                self.assertTrue(_should_skip_open(), f"{val!r} should skip")

    def test_falsy_values_return_false(self):
        for val in ("0", "false", "no", "off", "random"):
            with mock.patch.dict(os.environ, {NO_OPEN_ENV: val}):
                self.assertFalse(_should_skip_open(), f"{val!r} should not skip")


if __name__ == "__main__":
    unittest.main()
