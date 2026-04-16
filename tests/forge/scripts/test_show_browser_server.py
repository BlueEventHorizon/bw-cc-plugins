#!/usr/bin/env python3
"""show-browser server.py の単体テスト。

YamlReader と SkillMonitorServer / RequestHandler の動作を検証する。
設計書: DES-012 show-browser 設計書 v2.0（§8）
"""

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path

# server.py へのパスを追加
SERVER_SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "plugins", "forge", "skills", "show-browser", "scripts"
)
sys.path.insert(0, os.path.abspath(SERVER_SCRIPTS_DIR))

from server import YamlReader, SkillMonitorServer


# ---------------------------------------------------------------------------
# 共通テンポラリベース
# ---------------------------------------------------------------------------
# MEMORY.md: tempfile.mkdtemp() には必ず dir= を指定する
_BASE_TMPDIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".claude", ".temp", "test_tmp")
os.makedirs(_BASE_TMPDIR, exist_ok=True)


# ---------------------------------------------------------------------------
# テストユーティリティ
# ---------------------------------------------------------------------------

def _write_file(directory, filename, content):
    """テスト用ファイルを作成して絶対パスを返す。"""
    filepath = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    Path(filepath).write_text(content, encoding="utf-8")
    return filepath


def _make_monitor_dir(base_tmpdir, session_dir, template="review_list", port=0):
    """monitor ディレクトリと config.json を作成して返す。"""
    monitor_dir = os.path.join(base_tmpdir, "monitor")
    os.makedirs(monitor_dir, exist_ok=True)
    config = {"template": template, "session_dir": session_dir, "port": port}
    Path(os.path.join(monitor_dir, "config.json")).write_text(
        json.dumps(config), encoding="utf-8"
    )
    return monitor_dir


def _find_free_port(start=19000):
    """テスト用の空きポートを返す。"""
    import socket
    for port in range(start, start + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("空きポートが見つかりません")


class _ServerContext:
    """テスト用 SSE サーバーのライフサイクル管理（with 文対応）。"""

    def __init__(self, session_dir, port=None, heartbeat_interval=30.0):
        self.port = port or _find_free_port()
        self.session_dir = session_dir
        self.heartbeat_interval = heartbeat_interval
        # session_dir の親 or CWD に tmpdir を作成（/tmp ブロック時のフォールバック対策）
        parent = os.path.dirname(session_dir) if os.path.isdir(session_dir) else os.getcwd()
        self._tmpdir = tempfile.mkdtemp(dir=parent)
        self._monitor_dir = _make_monitor_dir(
            self._tmpdir, session_dir, port=self.port
        )
        self.server = None
        self._thread = None

    def __enter__(self):
        self.server = SkillMonitorServer(
            self._monitor_dir, port=self.port,
            heartbeat_interval=self.heartbeat_interval,
        )
        self._thread = threading.Thread(target=self.server.start, daemon=True)
        self._thread.start()
        # サーバー起動を待機
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                conn = HTTPConnection("127.0.0.1", self.port, timeout=0.2)
                conn.request("GET", "/session")
                conn.getresponse()
                conn.close()
                break
            except Exception:
                time.sleep(0.05)
        return self

    def __exit__(self, *_):
        if self.server:
            self.server.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# ===========================================================================
# YamlReader のテスト
# ===========================================================================

class TestYamlReaderReadYamlFile(unittest.TestCase):
    """YamlReader.read_yaml_file() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_flat_yaml(self):
        """フラット YAML を正しくパースする。"""
        p = _write_file(self.tmpdir, "session.yaml", "skill: review\nstatus: in_progress\n")
        result = self.reader.read_yaml_file(p)
        self.assertEqual(result["skill"], "review")
        self.assertEqual(result["status"], "in_progress")

    def test_nonexistent_returns_none(self):
        """存在しないファイルは None を返す。"""
        result = self.reader.read_yaml_file(os.path.join(self.tmpdir, "ghost.yaml"))
        self.assertIsNone(result)

    def test_empty_file_returns_empty_dict(self):
        """空ファイルは空 dict を返す。"""
        p = _write_file(self.tmpdir, "empty.yaml", "")
        result = self.reader.read_yaml_file(p)
        self.assertEqual(result, {})

    def test_list_yaml(self):
        """リスト付き YAML をパースする（plan.yaml 形式）。"""
        content = "items:\n  - id: 1\n    severity: critical\n    title: test\n    status: pending\n"
        p = _write_file(self.tmpdir, "plan.yaml", content)
        result = self.reader.read_yaml_file(p)
        self.assertIn("items", result)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], 1)
        self.assertEqual(result["items"][0]["severity"], "critical")


class TestYamlReaderReadMarkdownFile(unittest.TestCase):
    """YamlReader.read_markdown_file() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_reads_markdown(self):
        """Markdown ファイルを文字列として返す。"""
        p = _write_file(self.tmpdir, "review.md", "# レビュー結果\n問題なし\n")
        result = self.reader.read_markdown_file(p)
        self.assertIn("レビュー結果", result)

    def test_nonexistent_returns_none(self):
        """存在しないファイルは None を返す。"""
        result = self.reader.read_markdown_file(os.path.join(self.tmpdir, "ghost.md"))
        self.assertIsNone(result)


class TestYamlReaderReadSessionDir(unittest.TestCase):
    """YamlReader.read_session_dir() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir)

    def test_existing_files_have_exists_true(self):
        """存在するファイルは exists: true を返す。"""
        _write_file(self.session_dir, "session.yaml", "skill: review\nstatus: in_progress\n")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["files"]["session.yaml"]["exists"])
        self.assertEqual(result["files"]["session.yaml"]["content"]["skill"], "review")

    def test_missing_files_have_exists_false(self):
        """存在しないファイルは exists: false, content: null を返す。"""
        result = self.reader.read_session_dir(self.session_dir)
        for key in YamlReader.SESSION_FILES:
            self.assertFalse(result["files"][key]["exists"])
            self.assertIsNone(result["files"][key]["content"])

    def test_refs_yaml_detected(self):
        """refs.yaml があれば refs_yaml.exists が true になる。"""
        _write_file(self.session_dir, "refs.yaml", "target_files:\n  - foo.py\n")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["refs_yaml"]["exists"])

    def test_refs_subdir_files(self):
        """refs/ 配下のファイルを読み込む。"""
        _write_file(
            self.session_dir, "refs/specs.yaml",
            "source: query-specs\ndocuments: []\n"
        )
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["refs"]["specs.yaml"]["exists"])
        self.assertFalse(result["refs"]["rules.yaml"]["exists"])


# ===========================================================================
# RequestHandler — API エンドポイントのテスト
# ===========================================================================

class TestRequestHandlerSession(unittest.TestCase):
    """GET /session エンドポイントのテスト。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir)

    def test_get_session_returns_json(self):
        """GET /session が JSON を返す。"""
        _write_file(self.session_dir, "session.yaml", "skill: review\nstatus: in_progress\n")
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/session")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read())
            conn.close()

        self.assertIn("session_dir", body)
        self.assertIn("files", body)
        self.assertTrue(body["files"]["session.yaml"]["exists"])

    def test_get_session_missing_files(self):
        """空のセッションディレクトリでも /session が 200 を返す。"""
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/session")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read())
            conn.close()

        self.assertFalse(body["files"]["session.yaml"]["exists"])


class TestRequestHandlerNotify(unittest.TestCase):
    """POST /notify エンドポイントのテスト。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        # session_end テストでディレクトリを手動削除する場合があるため ignore_errors=True
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_notify_returns_ok(self):
        """有効な JSON を送ると {"status": "ok"} を返す。"""
        with _ServerContext(self.session_dir) as ctx:
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read())
            conn.close()

        self.assertEqual(body["status"], "ok")

    def test_notify_invalid_json_returns_400(self):
        """不正 JSON を送ると 400 を返す。"""
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=b"not json",
                         headers={"Content-Type": "application/json",
                                  "Content-Length": "8"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400)
            conn.close()

    def test_notify_session_end_when_dir_gone(self):
        """session_dir が消えた後の /notify は {"status": "session_end"} を返す。"""
        with _ServerContext(self.session_dir) as ctx:
            # session_dir を削除
            shutil.rmtree(self.session_dir)
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()

        self.assertEqual(body["status"], "session_end")

    def test_notify_triggers_sse_push(self):
        """POST /notify が SSE クライアントに update イベントを Push する。"""
        import socket as _socket

        received = []

        def _listen_raw(port, done_event):
            """生ソケットで SSE ストリームを受信するスレッド（http.client は SSE に不向き）。"""
            try:
                sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
                sock.sendall(b"GET /sse HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n")
                buf = b""
                # ヘッダー読み取り
                while b"\r\n\r\n" not in buf:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    buf += chunk
                # イベント受信ループ
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not done_event.is_set():
                    try:
                        sock.settimeout(0.5)
                        chunk = sock.recv(512)
                    except _socket.timeout:
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    if b"event: update" in buf:
                        received.append("update")
                        done_event.set()
                        break
                sock.close()
            except Exception:
                done_event.set()

        with _ServerContext(self.session_dir) as ctx:
            done = threading.Event()
            t = threading.Thread(target=_listen_raw, args=(ctx.port, done), daemon=True)
            t.start()

            # SSE 接続確立を待機（サーバーが sse_clients に登録するまで）
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with ctx.server.sse_lock:
                    if ctx.server.sse_clients:
                        break
                time.sleep(0.05)

            # /notify を送信
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()

            done.wait(timeout=3.0)

        self.assertIn("update", received, "SSE update イベントが受信されなかった")


class TestRequestHandlerUnknownPath(unittest.TestCase):
    """未知のパスのテスト。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir)

    def test_get_unknown_returns_404(self):
        """未知の GET パスは 404 を返す。"""
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/no-such-path")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            conn.close()


# ===========================================================================
# monitor_dir クリーンアップのテスト
# ===========================================================================

class TestMonitorDirCleanup(unittest.TestCase):
    """stop() / schedule_shutdown() による monitor_dir 削除のテスト。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        _write_file(self.session_dir, "session.yaml", "skill: review\nstatus: in_progress\n")

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_stop_cleans_up_monitor_dir(self):
        """stop() が monitor_dir を削除する。"""
        port = _find_free_port()
        tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        monitor_dir = _make_monitor_dir(tmpdir, self.session_dir, port=port)
        try:
            server = SkillMonitorServer(monitor_dir, port=port)
            t = threading.Thread(target=server.start, daemon=True)
            t.start()
            # サーバー起動待機
            time.sleep(0.3)

            server.stop()
            t.join(timeout=3.0)

            self.assertFalse(
                os.path.isdir(monitor_dir),
                f"stop() 後に monitor_dir が残存: {monitor_dir}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_schedule_shutdown_cleans_up_monitor_dir(self):
        """schedule_shutdown() が monitor_dir を削除する（non-daemon スレッド）。"""
        port = _find_free_port()
        tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        monitor_dir = _make_monitor_dir(tmpdir, self.session_dir, port=port)
        try:
            server = SkillMonitorServer(monitor_dir, port=port)
            t = threading.Thread(target=server.start, daemon=True)
            t.start()
            # サーバー起動待機
            time.sleep(0.3)

            server.schedule_shutdown()
            t.join(timeout=3.0)

            # schedule_shutdown の non-daemon スレッドが完了するのを待つ
            time.sleep(0.5)

            self.assertFalse(
                os.path.isdir(monitor_dir),
                f"schedule_shutdown() 後に monitor_dir が残存: {monitor_dir}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_heartbeat_detects_session_dir_removal(self):
        """session_dir 削除後にハートビートが monitor_dir を削除する。"""
        port = _find_free_port()
        tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        monitor_dir = _make_monitor_dir(tmpdir, self.session_dir, port=port)
        try:
            server = SkillMonitorServer(
                monitor_dir, port=port, heartbeat_interval=0.3,
            )
            t = threading.Thread(target=server.start, daemon=True)
            t.start()
            time.sleep(0.3)

            # session_dir を削除してハートビート検知を待つ
            shutil.rmtree(self.session_dir)
            time.sleep(1.0)

            self.assertFalse(
                os.path.isdir(monitor_dir),
                f"ハートビート検知後に monitor_dir が残存: {monitor_dir}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
