#!/usr/bin/env python3
"""monitor/notify.py の単体テスト。

session_dir フィルタリング・複数 monitor への通知・エラーハンドリングを検証する。
設計書: DES-012 show-browser 設計書 v3.0 §5.11
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# notify モジュールをインポート
_PLUGIN_SCRIPTS = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "plugins", "forge", "scripts"
)
sys.path.insert(0, os.path.abspath(_PLUGIN_SCRIPTS))
from monitor import notify  # noqa: E402


# ---------------------------------------------------------------------------
# テスト用ミニ HTTP サーバー
# ---------------------------------------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except Exception:
            data = {}
        self.server.received.append(data)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


class _MockServer:
    def __init__(self, port):
        self.port = port
        self.server = None
        self._thread = None

    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", self.port), _MockHandler)
        self.server.received = []
        self._thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *_):
        if self.server:
            self.server.shutdown()

    @property
    def received(self):
        return self.server.received


def _find_free_port(start=19100, end=19300):
    for port in range(start, end):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("テスト用空きポートが見つかりません")


# ---------------------------------------------------------------------------
# テストケース
# ---------------------------------------------------------------------------

class TestNotifySessionUpdate(unittest.TestCase):
    """notify_session_update の基本動作を検証する。"""

    def setUp(self):
        self.project_root = tempfile.mkdtemp(prefix="monitor_notify_test_")
        self.session_dir = os.path.join(
            self.project_root, ".claude", ".temp", "review-abc123"
        )
        os.makedirs(self.session_dir, exist_ok=True)
        self.port = _find_free_port()

        # CLAUDE_PROJECT_DIR を一時的に差し替える
        self._saved_env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = self.project_root

    def tearDown(self):
        if self._saved_env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self._saved_env
        shutil.rmtree(self.project_root, ignore_errors=True)

    def _make_monitor(self, session_dir, port, name="test-monitor"):
        """monitor ディレクトリを作成して config.json / server.pid を書く。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", name
        )
        os.makedirs(monitor_dir, exist_ok=True)
        config = {"skill": "review", "session_dir": session_dir, "port": port}
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            json.dumps(config), encoding="utf-8"
        )
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            "99999", encoding="utf-8"
        )
        return monitor_dir

    def test_matching_session_dir_triggers_notify(self):
        """session_dir が一致する monitor には通知が届く。"""
        self._make_monitor(self.session_dir, self.port)
        file_in_session = os.path.join(self.session_dir, "plan.yaml")
        Path(file_in_session).write_text("items: []", encoding="utf-8")

        with _MockServer(self.port) as srv:
            count = notify.notify_session_update(self.session_dir, file_in_session)
            time.sleep(0.2)

        self.assertEqual(count, 1)
        self.assertEqual(len(srv.received), 1)
        self.assertEqual(srv.received[0].get("file"), "plan.yaml")

    def test_non_matching_session_dir_no_notify(self):
        """session_dir が違う monitor には通知しない。"""
        other_session = os.path.join(
            self.project_root, ".claude", ".temp", "review-xyz999"
        )
        os.makedirs(other_session, exist_ok=True)
        self._make_monitor(other_session, self.port)

        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv:
            count = notify.notify_session_update(self.session_dir, file_in_session)
            time.sleep(0.2)

        self.assertEqual(count, 0)
        self.assertEqual(len(srv.received), 0)

    def test_file_outside_session_dir_no_notify(self):
        """session_dir 外のファイルは通知しない(防御的チェック)。"""
        self._make_monitor(self.session_dir, self.port)
        file_outside = os.path.join(self.project_root, "README.md")

        with _MockServer(self.port) as srv:
            count = notify.notify_session_update(self.session_dir, file_outside)
            time.sleep(0.2)

        self.assertEqual(count, 0)
        self.assertEqual(len(srv.received), 0)

    def test_server_down_no_crash(self):
        """サーバー未起動でもクラッシュせず 0 を返す。"""
        self._make_monitor(self.session_dir, self.port)
        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        # サーバー起動しない
        count = notify.notify_session_update(self.session_dir, file_in_session)
        self.assertEqual(count, 0)

    def test_missing_server_pid_skips_monitor(self):
        """server.pid がない monitor はスキップする。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", "nopid-monitor"
        )
        os.makedirs(monitor_dir, exist_ok=True)
        config = {
            "skill": "review",
            "session_dir": self.session_dir,
            "port": self.port,
        }
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            json.dumps(config), encoding="utf-8"
        )
        # server.pid は作らない

        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv:
            count = notify.notify_session_update(self.session_dir, file_in_session)
            time.sleep(0.2)

        self.assertEqual(count, 0)
        self.assertEqual(len(srv.received), 0)

    def test_missing_config_json_skips_monitor(self):
        """config.json がない monitor はスキップする。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", "noconfig-monitor"
        )
        os.makedirs(monitor_dir, exist_ok=True)
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            "99999", encoding="utf-8"
        )
        # config.json は作らない

        file_in_session = os.path.join(self.session_dir, "plan.yaml")
        count = notify.notify_session_update(self.session_dir, file_in_session)
        self.assertEqual(count, 0)

    def test_malformed_config_json_skips(self):
        """壊れた config.json はスキップする(クラッシュしない)。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", "broken-monitor"
        )
        os.makedirs(monitor_dir, exist_ok=True)
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            "not-json", encoding="utf-8"
        )
        Path(os.path.join(monitor_dir, "server.pid")).write_text(
            "99999", encoding="utf-8"
        )
        file_in_session = os.path.join(self.session_dir, "plan.yaml")
        count = notify.notify_session_update(self.session_dir, file_in_session)
        self.assertEqual(count, 0)

    def test_multiple_monitors_same_session(self):
        """同じ session_dir に複数 monitor があれば全てに通知する。"""
        port2 = _find_free_port(self.port + 1)
        self._make_monitor(self.session_dir, self.port, name="a-monitor")
        self._make_monitor(self.session_dir, port2, name="b-monitor")

        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv_a, _MockServer(port2) as srv_b:
            count = notify.notify_session_update(self.session_dir, file_in_session)
            time.sleep(0.2)

        self.assertEqual(count, 2)
        self.assertEqual(len(srv_a.received), 1)
        self.assertEqual(len(srv_b.received), 1)

    def test_empty_session_dir_returns_zero(self):
        """session_dir が空文字なら即座に 0 を返す。"""
        count = notify.notify_session_update("", "some_file")
        self.assertEqual(count, 0)

    def test_empty_file_path_returns_zero(self):
        """file_path が空文字なら即座に 0 を返す。"""
        count = notify.notify_session_update(self.session_dir, "")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
