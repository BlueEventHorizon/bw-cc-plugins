#!/usr/bin/env python3
"""show_browser.py の単体テスト。

find_free_port / cleanup_orphan_monitors / create_monitor_dir のテスト。
設計書: DES-012 show-browser 設計書 v2.0（§5.1 / §5.10）
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

# show_browser.py へのパスを追加
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "plugins", "forge", "skills", "show-browser", "scripts"
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from show_browser import find_free_port, cleanup_orphan_monitors, create_monitor_dir


class TestFindFreePort(unittest.TestCase):
    """find_free_port() のテスト。"""

    def test_returns_int(self):
        """int を返す。"""
        port = find_free_port(start=19200)
        self.assertIsInstance(port, int)

    def test_port_in_range(self):
        """指定開始ポート以上の値を返す。"""
        port = find_free_port(start=19200)
        self.assertGreaterEqual(port, 19200)

    def test_port_is_free(self):
        """返されたポートに実際にバインドできる。"""
        import socket
        port = find_free_port(start=19300)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # バインド成功 = ポートが空いている
            s.bind(("127.0.0.1", port))


class TestCreateMonitorDir(unittest.TestCase):
    """create_monitor_dir() のテスト。"""

    def setUp(self):
        _base = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".claude", ".temp", "test_tmp")
        os.makedirs(_base, exist_ok=True)
        self.project_root = tempfile.mkdtemp(dir=_base)
        self.session_dir = tempfile.mkdtemp(dir=self.project_root)

    def tearDown(self):
        shutil.rmtree(self.project_root)

    def test_creates_directory(self):
        """monitor ディレクトリが作成される。"""
        monitor_dir = create_monitor_dir(self.project_root, "review_list", self.session_dir, 8765)
        self.assertTrue(os.path.isdir(monitor_dir))

    def test_creates_config_json(self):
        """config.json が作成され、正しい内容を持つ。"""
        monitor_dir = create_monitor_dir(self.project_root, "review_list", self.session_dir, 8765)
        config_path = os.path.join(monitor_dir, "config.json")
        self.assertTrue(os.path.isfile(config_path))
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertEqual(config["template"], "review_list")
        self.assertEqual(config["port"], 8765)
        self.assertEqual(config["session_dir"], os.path.abspath(self.session_dir))

    def test_monitor_dir_name_contains_template(self):
        """monitor ディレクトリ名にテンプレート名が含まれる。"""
        monitor_dir = create_monitor_dir(self.project_root, "review_list", self.session_dir, 8765)
        self.assertIn("review_list", os.path.basename(monitor_dir))

    def test_monitor_dir_name_ends_with_monitor(self):
        """monitor ディレクトリ名が -monitor で終わる。"""
        monitor_dir = create_monitor_dir(self.project_root, "review_list", self.session_dir, 8765)
        self.assertTrue(os.path.basename(monitor_dir).endswith("-monitor"))

    def test_monitor_dir_under_temp(self):
        """monitor ディレクトリが .claude/.temp/ 配下に作成される。"""
        monitor_dir = create_monitor_dir(self.project_root, "review_list", self.session_dir, 8765)
        expected_parent = os.path.join(self.project_root, ".claude", ".temp")
        self.assertEqual(os.path.dirname(monitor_dir), expected_parent)


class TestCleanupOrphanMonitors(unittest.TestCase):
    """cleanup_orphan_monitors() のテスト。"""

    def setUp(self):
        _base = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".claude", ".temp", "test_tmp")
        os.makedirs(_base, exist_ok=True)
        self.project_root = tempfile.mkdtemp(dir=_base)

    def tearDown(self):
        shutil.rmtree(self.project_root)

    def _make_monitor_dir(self, name):
        """テスト用 monitor ディレクトリを .claude/.temp/ に作成する。"""
        d = os.path.join(self.project_root, ".claude", ".temp", name)
        os.makedirs(d, exist_ok=True)
        return d

    def test_removes_dir_without_pid(self):
        """server.pid がない monitor ディレクトリは削除される。"""
        monitor_dir = self._make_monitor_dir("old-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text("{}", encoding="utf-8")
        # server.pid なし → 孤立

        cleanup_orphan_monitors(self.project_root)

        self.assertFalse(os.path.isdir(monitor_dir), "孤立 monitor は削除されるべき")

    def test_removes_dir_with_dead_pid(self):
        """server.pid の PID が死亡している monitor ディレクトリは削除される。"""
        monitor_dir = self._make_monitor_dir("dead-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text("{}", encoding="utf-8")
        # 存在しない PID（99999 は通常 zombie にならない）
        Path(os.path.join(monitor_dir, "server.pid")).write_text("99999", encoding="utf-8")

        cleanup_orphan_monitors(self.project_root)

        # PID が生きている場合もある（環境依存）ので、削除されたかどうかだけ確認
        # ここでは is_process_alive が False を返す仮定でテスト
        # 注: macOS / Linux では PID 99999 は通常存在しない
        # 存在してしまう場合はスキップ
        import signal
        try:
            os.kill(99999, 0)
            # プロセスが生きている → スキップ
        except ProcessLookupError:
            self.assertFalse(os.path.isdir(monitor_dir), "死亡 PID の monitor は削除されるべき")
        except PermissionError:
            # アクセス拒否 = プロセスは存在するがアクセスできない → スキップ
            pass

    def test_keeps_dir_with_alive_pid(self):
        """自分自身の PID は生存しているため monitor は削除されない。"""
        monitor_dir = self._make_monitor_dir("alive-monitor")
        Path(os.path.join(monitor_dir, "config.json")).write_text("{}", encoding="utf-8")
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            str(os.getpid()), encoding="utf-8"
        )

        cleanup_orphan_monitors(self.project_root)

        self.assertTrue(os.path.isdir(monitor_dir), "生存 PID の monitor は削除されないべき")

    def test_no_temp_dir_no_error(self):
        """.claude/.temp/ が存在しなくてもエラーにならない。"""
        # cleanup_orphan_monitors はエラーを出さずに正常終了する
        cleanup_orphan_monitors(self.project_root)


if __name__ == "__main__":
    unittest.main()
