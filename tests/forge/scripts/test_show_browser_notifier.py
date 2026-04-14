#!/usr/bin/env python3
"""notifier.py の単体テスト。

session_dir フィルタリング・複数 monitor への通知・エラーハンドリングを検証する。
設計書: DES-012 show-browser 設計書 v2.0（§5.7）
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# notifier.py のパス
NOTIFIER_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", ".claude", "hooks", "notifier.py"
)


# ---------------------------------------------------------------------------
# テスト用ミニ HTTP サーバー（/notify を受信して記録するモック）
# ---------------------------------------------------------------------------

class _MockHandler(BaseHTTPRequestHandler):
    """POST /notify リクエストを受信して記録するモックハンドラ。"""

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
    """モック HTTP サーバーのライフサイクル管理（with 文対応）。"""

    def __init__(self, port):
        self.port = port
        self.server = None
        self._thread = None

    def __enter__(self):
        self.server = HTTPServer(("127.0.0.1", self.port), _MockHandler)
        self.server.received = []
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_):
        if self.server:
            self.server.shutdown()

    @property
    def received(self):
        return self.server.received


# ---------------------------------------------------------------------------
# notifier.main() を stdin 経由で呼び出すユーティリティ
# ---------------------------------------------------------------------------

def _run_notifier(tool_name, file_path, env=None):
    """notifier.py の main() を指定の入力で実行する。

    Args:
        tool_name: tool_name フィールド値
        file_path: tool_input.file_path フィールド値
        env: 追加の環境変数 dict（省略時はデフォルト）

    Returns:
        None（stdout/stderr への出力は無視）
    """
    import subprocess
    input_data = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": file_path}})
    _env = os.environ.copy()
    if env:
        _env.update(env)
    subprocess.run(
        [sys.executable, NOTIFIER_PATH],
        input=input_data.encode(),
        env=_env,
        timeout=5,
    )


# ---------------------------------------------------------------------------
# テストケース
# ---------------------------------------------------------------------------

class TestNotifierSessionDirFilter(unittest.TestCase):
    """session_dir 配下のファイルのみ通知する。"""

    def setUp(self):
        _base = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".claude", ".temp", "test_tmp")
        os.makedirs(_base, exist_ok=True)
        self.project_root = tempfile.mkdtemp(dir=_base)
        self.session_dir = os.path.join(self.project_root, ".claude", ".temp", "review-abc123")
        os.makedirs(self.session_dir, exist_ok=True)

        # 空きポートを探す
        import socket
        for port in range(19100, 19200):
            with socket.socket() as s:
                try:
                    s.bind(("127.0.0.1", port))
                    self.port = port
                    break
                except OSError:
                    continue

    def tearDown(self):
        shutil.rmtree(self.project_root)

    def _make_monitor(self, session_dir, port):
        """monitor ディレクトリを作成して config.json を書く。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", "test-monitor"
        )
        os.makedirs(monitor_dir, exist_ok=True)
        config = {"template": "review_list", "session_dir": session_dir, "port": port}
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            json.dumps(config), encoding="utf-8"
        )
        # server.pid を作成（存在しないと notifier がスキップする）
        Path(os.path.join(monitor_dir, "server.pid")).write_text("99999", encoding="utf-8")
        return monitor_dir

    def test_session_dir_file_triggers_notify(self):
        """session_dir 配下のファイル更新は /notify を送信する。"""
        self._make_monitor(self.session_dir, self.port)

        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv:
            _run_notifier("Write", file_in_session, {"CLAUDE_PROJECT_DIR": self.project_root})
            import time; time.sleep(0.2)

        self.assertEqual(len(srv.received), 1, "session_dir 配下のファイルは通知されるべき")
        self.assertEqual(srv.received[0].get("file"), "plan.yaml")

    def test_outside_session_dir_no_notify(self):
        """session_dir 外のファイル更新は /notify を送信しない。"""
        self._make_monitor(self.session_dir, self.port)

        file_outside = os.path.join(self.project_root, "README.md")

        with _MockServer(self.port) as srv:
            _run_notifier("Write", file_outside, {"CLAUDE_PROJECT_DIR": self.project_root})
            import time; time.sleep(0.2)

        self.assertEqual(len(srv.received), 0, "session_dir 外のファイルは通知しないべき")

    def test_non_write_tool_no_notify(self):
        """Write / Edit 以外のツールは通知しない。"""
        self._make_monitor(self.session_dir, self.port)
        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv:
            _run_notifier("Read", file_in_session, {"CLAUDE_PROJECT_DIR": self.project_root})
            import time; time.sleep(0.2)

        self.assertEqual(len(srv.received), 0, "Read ツールは通知しないべき")

    def test_server_down_no_crash(self):
        """サーバーが起動していなくても exit 0 で終了する（クラッシュしない）。"""
        self._make_monitor(self.session_dir, self.port + 1)  # 未起動ポート
        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        # クラッシュしなければ OK
        _run_notifier("Write", file_in_session, {"CLAUDE_PROJECT_DIR": self.project_root})

    def test_no_server_pid_skips_monitor(self):
        """server.pid がない monitor はスキップする。"""
        monitor_dir = os.path.join(
            self.project_root, ".claude", ".temp", "nopid-monitor"
        )
        os.makedirs(monitor_dir, exist_ok=True)
        config = {"template": "review_list", "session_dir": self.session_dir, "port": self.port}
        Path(os.path.join(monitor_dir, "config.json")).write_text(
            json.dumps(config), encoding="utf-8"
        )
        # server.pid は作らない

        file_in_session = os.path.join(self.session_dir, "plan.yaml")

        with _MockServer(self.port) as srv:
            _run_notifier("Write", file_in_session, {"CLAUDE_PROJECT_DIR": self.project_root})
            import time; time.sleep(0.2)

        self.assertEqual(len(srv.received), 0, "server.pid がない monitor はスキップするべき")


if __name__ == "__main__":
    unittest.main()
