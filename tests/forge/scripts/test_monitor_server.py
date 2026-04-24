#!/usr/bin/env python3
"""monitor/server.py の単体テスト。

YamlReader / RequestHandler / SkillMonitorServer の動作を検証する。
設計書: DES-012 show-browser 設計書 v3.0
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

# server.py へのパスを追加(monitor/ 配下)
MONITOR_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "plugins", "forge", "scripts", "monitor",
)
sys.path.insert(0, os.path.abspath(MONITOR_DIR))

from server import (  # noqa: E402
    FALLBACK_TEMPLATE,
    SESSION_END_MESSAGE,
    SKILL_TEMPLATE_MAP,
    SkillMonitorServer,
    YamlReader,
    _resolve_template_for_skill,
)


# ---------------------------------------------------------------------------
# 共通テンポラリベース
# ---------------------------------------------------------------------------
_BASE_TMPDIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    ".claude", ".temp", "test_tmp",
))


def setUpModule():
    # 前回の中断で残った残骸をクリーンスタート
    if os.path.isdir(_BASE_TMPDIR):
        shutil.rmtree(_BASE_TMPDIR)
    os.makedirs(_BASE_TMPDIR, exist_ok=True)


def tearDownModule():
    # 子テストの cleanup 漏れ(ignore_errors=True で握り潰されたもの含む)を巻き取る
    if os.path.isdir(_BASE_TMPDIR):
        shutil.rmtree(_BASE_TMPDIR, ignore_errors=True)


# ---------------------------------------------------------------------------
# テストユーティリティ
# ---------------------------------------------------------------------------

def _write_file(directory, filename, content):
    """テスト用ファイルを作成して絶対パスを返す。"""
    filepath = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    Path(filepath).write_text(content, encoding="utf-8")
    return filepath


def _make_monitor_dir(base_tmpdir, session_dir, skill="review", port=0,
                      extra=None):
    """monitor ディレクトリと config.json を作成して返す。"""
    monitor_dir = os.path.join(base_tmpdir, "monitor")
    os.makedirs(monitor_dir, exist_ok=True)
    config = {"skill": skill, "session_dir": session_dir, "port": port}
    if extra:
        config.update(extra)
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
    """テスト用 SSE サーバーのライフサイクル管理(with 文対応)。"""

    def __init__(self, session_dir, skill="review", port=None,
                 heartbeat_interval=30.0):
        self.port = port or _find_free_port()
        self.session_dir = session_dir
        self.heartbeat_interval = heartbeat_interval
        # session_dir の親 or CWD に tmpdir を作成
        parent = os.path.dirname(session_dir) if os.path.isdir(session_dir) else os.getcwd()
        self._tmpdir = tempfile.mkdtemp(dir=parent)
        self._monitor_dir = _make_monitor_dir(
            self._tmpdir, session_dir, skill=skill, port=self.port,
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
# _resolve_template_for_skill() のテスト
# ===========================================================================

class TestResolveTemplateForSkill(unittest.TestCase):
    """skill → テンプレート名の解決ロジック。"""

    def test_review_maps_to_review_template(self):
        self.assertEqual(_resolve_template_for_skill("review"), "review")

    def test_start_requirements_maps_to_document(self):
        self.assertEqual(_resolve_template_for_skill("start-requirements"), "document")

    def test_start_design_maps_to_document(self):
        self.assertEqual(_resolve_template_for_skill("start-design"), "document")

    def test_start_plan_maps_to_document(self):
        self.assertEqual(_resolve_template_for_skill("start-plan"), "document")

    def test_start_implement_maps_to_implement(self):
        self.assertEqual(_resolve_template_for_skill("start-implement"), "implement")

    def test_start_uxui_design_maps_to_uxui(self):
        self.assertEqual(_resolve_template_for_skill("start-uxui-design"), "uxui")

    def test_unknown_skill_falls_back(self):
        self.assertEqual(_resolve_template_for_skill("unknown"), FALLBACK_TEMPLATE)

    def test_empty_skill_falls_back(self):
        self.assertEqual(_resolve_template_for_skill(""), FALLBACK_TEMPLATE)

    def test_every_known_skill_has_mapping(self):
        """SKILL_TEMPLATE_MAP の全 skill に対して resolver が一貫した結果を返す。"""
        for skill, template in SKILL_TEMPLATE_MAP.items():
            self.assertEqual(_resolve_template_for_skill(skill), template)


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
        p = _write_file(self.tmpdir, "session.yaml",
                        "skill: review\nstatus: in_progress\n")
        result = self.reader.read_yaml_file(p)
        self.assertEqual(result["skill"], "review")
        self.assertEqual(result["status"], "in_progress")

    def test_nonexistent_returns_none(self):
        result = self.reader.read_yaml_file(os.path.join(self.tmpdir, "ghost.yaml"))
        self.assertIsNone(result)

    def test_empty_file_returns_empty_dict(self):
        p = _write_file(self.tmpdir, "empty.yaml", "")
        result = self.reader.read_yaml_file(p)
        self.assertEqual(result, {})

    def test_list_yaml(self):
        content = ("items:\n  - id: 1\n    severity: critical\n"
                   "    title: test\n    status: pending\n")
        p = _write_file(self.tmpdir, "plan.yaml", content)
        result = self.reader.read_yaml_file(p)
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["id"], 1)


class TestYamlReaderReadSessionDir(unittest.TestCase):
    """YamlReader.read_session_dir() のテスト。"""

    def setUp(self):
        self.reader = YamlReader()
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir)

    def test_existing_files_have_exists_true(self):
        _write_file(self.session_dir, "session.yaml",
                    "skill: review\nstatus: in_progress\n")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["files"]["session.yaml"]["exists"])
        self.assertEqual(result["files"]["session.yaml"]["content"]["skill"], "review")

    def test_missing_files_have_exists_false(self):
        result = self.reader.read_session_dir(self.session_dir)
        for key in YamlReader.SESSION_FILES:
            self.assertFalse(result["files"][key]["exists"])
            self.assertIsNone(result["files"][key]["content"])

    def test_requirements_md_detected(self):
        """SESSION_FILES に requirements.md が含まれる(v3.0 追加)。"""
        _write_file(self.session_dir, "requirements.md",
                    "# 要件定義\n\n...")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["files"]["requirements.md"]["exists"])

    def test_design_md_detected(self):
        """SESSION_FILES に design.md が含まれる(v3.0 追加)。"""
        _write_file(self.session_dir, "design.md", "# 設計\n\n...")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["files"]["design.md"]["exists"])

    def test_refs_yaml_detected(self):
        _write_file(self.session_dir, "refs.yaml",
                    "target_files:\n  - foo.py\n")
        result = self.reader.read_session_dir(self.session_dir)
        self.assertTrue(result["refs_yaml"]["exists"])


# ===========================================================================
# RequestHandler — GET / (skill ベースのテンプレート選択)
# ===========================================================================

class TestIndexTemplateSelection(unittest.TestCase):
    """GET / が skill に応じたテンプレートを返す。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        _write_file(self.session_dir, "session.yaml", "skill: review\n")
        # テンプレートが存在しない可能性があるので、動的に作成する
        self.templates_dir = os.path.join(MONITOR_DIR, "templates")
        self._created_templates = []
        os.makedirs(self.templates_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)
        for path in self._created_templates:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _ensure_template(self, name, content):
        """テンプレートファイルを作成する(既存なら触らない)。"""
        path = os.path.join(self.templates_dir, f"{name}.html")
        if not os.path.isfile(path):
            Path(path).write_text(content, encoding="utf-8")
            self._created_templates.append(path)
        return path

    def test_review_skill_returns_review_template(self):
        """skill=review なら review.html を返す。"""
        # 実テンプレートが配置されていれば流用。不在時のみスタブを生成。
        review_path = os.path.join(self.templates_dir, "review.html")
        real_template = os.path.isfile(review_path)
        self._ensure_template("review", "<!doctype html><title>REVIEW</title>")
        with _ServerContext(self.session_dir, skill="review") as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            conn.close()
        if real_template:
            # review.html 固有の marker(findings カードレイアウト)を確認
            self.assertIn('data-role="findings"', body)
        else:
            self.assertIn("REVIEW", body)

    def test_unknown_skill_falls_back_to_generic(self):
        """不明な skill は generic.html にフォールバックする。"""
        generic_path = os.path.join(self.templates_dir, "generic.html")
        real_template = os.path.isfile(generic_path)
        self._ensure_template("generic", "<!doctype html><title>GENERIC</title>")
        with _ServerContext(self.session_dir, skill="nosuch-skill") as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            conn.close()
        if real_template:
            # generic.html 固有の marker(single カラムレイアウト)を確認
            self.assertIn("layout--single", body)
        else:
            self.assertIn("GENERIC", body)

    def test_missing_template_uses_generic_fallback(self):
        """skill に対応するテンプレートが不在なら generic.html にフォールバック。"""
        self._ensure_template("generic", "<!doctype html><title>GENERIC</title>")
        # start-implement 用テンプレートを作らず generic だけ用意
        with _ServerContext(self.session_dir, skill="start-implement") as ctx:
            # implement.html が実在すると期待するが、存在しなければ generic へ
            implement_path = os.path.join(self.templates_dir, "implement.html")
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            conn.close()
        # implement.html があれば GENERIC は含まれない、無ければ GENERIC が返る
        if os.path.isfile(implement_path):
            self.assertIn("<", body)
        else:
            self.assertIn("GENERIC", body)

    def test_backward_compat_template_key(self):
        """config.json に template キーのみある場合(後方互換)でも動作する。"""
        # template キーだけセットされた config を直接作る
        tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        port = _find_free_port()
        server = None
        try:
            monitor_dir = os.path.join(tmpdir, "monitor")
            os.makedirs(monitor_dir, exist_ok=True)
            config = {
                "template": "review",
                "session_dir": self.session_dir,
                "port": port,
            }
            Path(os.path.join(monitor_dir, "config.json")).write_text(
                json.dumps(config), encoding="utf-8"
            )
            server = SkillMonitorServer(monitor_dir, port=port)
            self.assertEqual(server.skill, "review")
        finally:
            # serve_forever を呼んでいないので shutdown ではなく server_close のみ
            if server is not None:
                server.server_close()
            shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# RequestHandler — GET /assets/
# ===========================================================================

class TestAssetEndpoint(unittest.TestCase):
    """GET /assets/<path> の静的ファイル配信。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        self.assets_dir = os.path.join(MONITOR_DIR, "templates", "assets")
        os.makedirs(self.assets_dir, exist_ok=True)
        self._created = []

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)
        for path in self._created:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _create_asset(self, relpath, content):
        path = os.path.join(self.assets_dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        existed = os.path.isfile(path)
        Path(path).write_text(content, encoding="utf-8")
        if not existed:
            self._created.append(path)
        return path

    def test_css_asset_returned_with_correct_mime(self):
        self._create_asset("test-fixture.css", ":root { --x: 1; }")
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/assets/test-fixture.css")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("text/css", resp.getheader("Content-Type", ""))
            body = resp.read().decode("utf-8")
            conn.close()
        self.assertIn("--x", body)

    def test_js_asset_returned(self):
        self._create_asset("test-fixture.js", "export const x = 1;")
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/assets/test-fixture.js")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            self.assertIn("javascript", resp.getheader("Content-Type", ""))
            conn.close()

    def test_missing_asset_returns_404(self):
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/assets/nonexistent-xyz.css")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 404)
            conn.close()

    def test_path_traversal_rejected(self):
        """../ を含むパスは 400 を返す(パストラバーサル防御)。"""
        with _ServerContext(self.session_dir) as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/assets/../server.py")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 400)
            conn.close()


# ===========================================================================
# RequestHandler — GET /session / POST /notify
# ===========================================================================

class TestSessionEndpoint(unittest.TestCase):
    """GET /session は skill 情報を含む JSON を返す。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_get_session_includes_skill(self):
        _write_file(self.session_dir, "session.yaml", "skill: review\n")
        with _ServerContext(self.session_dir, skill="review") as ctx:
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("GET", "/session")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        self.assertEqual(body.get("skill"), "review")
        self.assertTrue(body["files"]["session.yaml"]["exists"])


class TestNotifyEndpoint(unittest.TestCase):
    """POST /notify エンドポイント。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_notify_returns_ok(self):
        with _ServerContext(self.session_dir) as ctx:
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], "ok")

    def test_notify_session_end_when_dir_gone(self):
        with _ServerContext(self.session_dir) as ctx:
            shutil.rmtree(self.session_dir)
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        self.assertEqual(body["status"], "session_end")

    def test_notify_refreshes_session_state(self):
        """POST /notify 成功時に mtime スナップショットが更新される。"""
        _write_file(self.session_dir, "plan.yaml", "items: []\n")
        with _ServerContext(self.session_dir, heartbeat_interval=30.0) as ctx:
            initial_state = ctx.server._session_state
            # ファイルを更新
            time.sleep(0.05)
            _write_file(self.session_dir, "plan.yaml",
                        "items:\n  - id: 1\n")
            # /notify 実行
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()
            updated_state = ctx.server._session_state
        self.assertNotEqual(initial_state, updated_state,
                            "mtime スナップショットが refresh されていない")

    def test_notify_payload_too_large_returns_413(self):
        with _ServerContext(self.session_dir) as ctx:
            oversized = b"x" * (65537)
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=oversized,
                         headers={"Content-Type": "application/octet-stream"})
            resp = conn.getresponse()
            self.assertEqual(resp.status, 413)
            conn.close()


# ===========================================================================
# mtime ハートビートのテスト
# ===========================================================================

class TestHeartbeatMtimeDetection(unittest.TestCase):
    """mtime 変化をハートビートが検知して update を Push する。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        _write_file(self.session_dir, "plan.yaml", "items: []\n")

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_heartbeat_detects_file_change(self):
        """heartbeat interval 経過後にファイル変化で update がブロードキャストされる。"""
        import socket as _socket

        received = []

        def _listen_raw(port, done_event):
            try:
                sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
                sock.sendall(
                    b"GET /sse HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                )
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    buf += chunk
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
                    if b"event: update" in buf and b'"file": "heartbeat"' in buf:
                        received.append("heartbeat")
                        done_event.set()
                        break
                sock.close()
            except Exception:
                done_event.set()

        with _ServerContext(self.session_dir, heartbeat_interval=0.3) as ctx:
            done = threading.Event()
            t = threading.Thread(target=_listen_raw, args=(ctx.port, done),
                                 daemon=True)
            t.start()
            # SSE 接続確立を待機
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with ctx.server.sse_lock:
                    if ctx.server.sse_clients:
                        break
                time.sleep(0.05)

            # ファイルを直接書き換え(通知を送らない)
            time.sleep(0.05)
            _write_file(self.session_dir, "plan.yaml",
                        "items:\n  - id: 1\n    title: test\n")

            # heartbeat 検知を待機(interval 0.3 × 2 サイクル)
            done.wait(timeout=3.0)

        self.assertIn("heartbeat", received,
                      "heartbeat による update イベントが受信されなかった")

    def test_heartbeat_detects_session_dir_removal(self):
        """session_dir 削除で session_end が送信され monitor_dir が削除される。"""
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

            shutil.rmtree(self.session_dir)
            time.sleep(1.0)

            self.assertFalse(
                os.path.isdir(monitor_dir),
                f"ハートビート検知後に monitor_dir が残存: {monitor_dir}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# monitor_dir クリーンアップ
# ===========================================================================

class TestMonitorDirCleanup(unittest.TestCase):
    """stop() / schedule_shutdown() による monitor_dir 削除。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        _write_file(self.session_dir, "session.yaml",
                    "skill: review\nstatus: in_progress\n")

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_stop_cleans_up_monitor_dir(self):
        port = _find_free_port()
        tmpdir = tempfile.mkdtemp(dir=_BASE_TMPDIR)
        monitor_dir = _make_monitor_dir(tmpdir, self.session_dir, port=port)
        try:
            server = SkillMonitorServer(monitor_dir, port=port)
            t = threading.Thread(target=server.start, daemon=True)
            t.start()
            time.sleep(0.3)

            server.stop()
            t.join(timeout=3.0)

            self.assertFalse(
                os.path.isdir(monitor_dir),
                f"stop() 後に monitor_dir が残存: {monitor_dir}",
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ===========================================================================
# session_end SSE メッセージ検証
# ===========================================================================

class TestSessionEndMessage(unittest.TestCase):
    """session_end イベントの payload に message が含まれる。"""

    def setUp(self):
        self.session_dir = tempfile.mkdtemp(dir=_BASE_TMPDIR)

    def tearDown(self):
        shutil.rmtree(self.session_dir, ignore_errors=True)

    def test_session_end_payload_contains_message(self):
        import socket as _socket

        received = {}

        def _listen_raw(port, done_event):
            try:
                sock = _socket.create_connection(("127.0.0.1", port), timeout=5)
                sock.sendall(
                    b"GET /sse HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Connection: keep-alive\r\n\r\n"
                )
                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = sock.recv(256)
                    if not chunk:
                        break
                    buf += chunk
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
                    if b"event: session_end" in buf:
                        text = buf.decode("utf-8", errors="replace")
                        lines = text.splitlines()
                        for i, line in enumerate(lines):
                            if line.strip() == "event: session_end":
                                for next_line in lines[i + 1:]:
                                    if next_line.startswith("data:"):
                                        received["data"] = next_line[len("data:"):].strip()
                                        break
                                break
                        done_event.set()
                        break
                sock.close()
            except Exception:
                done_event.set()

        with _ServerContext(self.session_dir) as ctx:
            done = threading.Event()
            t = threading.Thread(target=_listen_raw, args=(ctx.port, done),
                                 daemon=True)
            t.start()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                with ctx.server.sse_lock:
                    if ctx.server.sse_clients:
                        break
                time.sleep(0.05)

            shutil.rmtree(self.session_dir)
            payload = json.dumps({"file": "plan.yaml"}).encode()
            conn = HTTPConnection("127.0.0.1", ctx.port, timeout=3)
            conn.request("POST", "/notify", body=payload,
                         headers={"Content-Type": "application/json"})
            conn.getresponse().read()
            conn.close()

            done.wait(timeout=3.0)

        self.assertIn("data", received, "session_end イベントが受信されなかった")
        parsed = json.loads(received["data"])
        self.assertEqual(parsed.get("type"), "session_end")
        self.assertEqual(parsed.get("message"), SESSION_END_MESSAGE)


if __name__ == "__main__":
    unittest.main()
