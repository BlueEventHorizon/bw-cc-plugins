#!/usr/bin/env python3
"""server.py — forge monitor SSE サーバー。

monitor ディレクトリ(config.json)を読み込み、セッションディレクトリの
YAML / Markdown ファイルを JSON に変換してブラウザに SSE で Push する。

主要コンポーネント:
  - YamlReader: セッション YAML リーダー
  - RequestHandler: HTTP リクエストハンドラ(skill ベースのテンプレート自動選択)
  - SkillMonitorServer: SSE サーバー本体(mtime ハートビート + session_dir 消失検知)

設計書: DES-012 show-browser 設計書 v3.0
"""

import argparse
import json
import os
import shutil
import sys
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# monitor/ → plugins/forge/scripts/ (2 階層上) で yaml_utils を解決
_SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from session_adapter import (  # noqa: E402
    REFS_FILES,
    SESSION_FILES,
    build_monitor_session,
)
from session.reader import read_entry  # noqa: E402


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

SESSION_END_MESSAGE = "セッションが終了しました。このタブは閉じて構いません"

# skill → テンプレート名のマッピング(設計書 §5.6)
SKILL_TEMPLATE_MAP = {
    "review": "review",
    "start-requirements": "document",
    "start-design": "document",
    "start-plan": "document",
    "start-implement": "implement",
    "start-uxui-design": "uxui",
}

# skill 不明時のフォールバックテンプレート
FALLBACK_TEMPLATE = "generic"

# ハートビート間隔(秒)
DEFAULT_HEARTBEAT_INTERVAL = 30.0

# 静的アセットの MIME タイプ
ASSET_MIME = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


# ---------------------------------------------------------------------------
# YamlReader — セッション YAML パーサー
# ---------------------------------------------------------------------------

class YamlReader:
    """セッションディレクトリ内の YAML / Markdown を読み込み dict / str に変換する。"""

    SESSION_FILES = SESSION_FILES
    REFS_FILES = REFS_FILES

    def read_session_dir(self, session_dir):
        """セッションディレクトリ内の全ファイルを読み込み JSON 化する。"""
        return build_monitor_session(session_dir)

    def read_yaml_file(self, filepath):
        entry = read_entry(filepath)
        if not entry.get("exists"):
            return None
        return entry.get("content")

    def read_markdown_file(self, filepath):
        entry = read_entry(filepath)
        if not entry.get("exists"):
            return None
        return entry.get("content")


# ---------------------------------------------------------------------------
# session_dir 状態スナップショット(mtime ハートビート用)
# ---------------------------------------------------------------------------

def _compute_session_state(session_dir):
    """session_dir 配下の全ファイルの (path, mtime) スナップショットを返す。

    heartbeat の状態比較に使う。書き込み直接通知が届かなかったケースを
    補完する保険的な役割。
    """
    state = []
    try:
        for root, _dirs, files in os.walk(session_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    state.append((path, os.path.getmtime(path)))
                except OSError:
                    continue
    except OSError:
        return tuple()
    return tuple(sorted(state))


# ---------------------------------------------------------------------------
# RequestHandler — HTTP リクエストハンドラ
# ---------------------------------------------------------------------------

def _resolve_template_for_skill(skill):
    """skill 名からテンプレート名を解決する(不明時は generic)。"""
    return SKILL_TEMPLATE_MAP.get(skill, FALLBACK_TEMPLATE)


class RequestHandler(BaseHTTPRequestHandler):
    """SSE サーバーの HTTP リクエストハンドラ。

    エンドポイント:
      GET  /              → skill に応じた HTML テンプレート
      GET  /assets/<path> → templates/assets/<path>(CSS/JS 等の静的配信)
      GET  /session       → session_dir の全 YAML を JSON で返す
      GET  /sse           → SSE ストリーム
      POST /notify        → 更新通知を受信し SSE で Push
    """

    # /notify ペイロード上限(64KB)
    MAX_CONTENT_LENGTH = 65536

    def log_message(self, format, *args):
        """ログ出力を抑制する(テスト時ノイズ低減)。"""
        pass

    def do_GET(self):
        if self.path == "/":
            self._handle_index()
        elif self.path.startswith("/assets/"):
            self._handle_asset(self.path[len("/assets/"):])
        elif self.path == "/session":
            self._handle_session()
        elif self.path == "/sse":
            self._handle_sse()
        else:
            self._send_json({"error": "not_found"}, status=404)

    def do_POST(self):
        if self.path == "/notify":
            self._handle_notify()
        else:
            self._send_json({"error": "not_found"}, status=404)

    def _templates_dir(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "templates"
        )

    def _handle_index(self):
        """GET / — skill 対応テンプレート → generic.html の順にフォールバック。"""
        server = self.server
        template = _resolve_template_for_skill(server.skill)

        # パストラバーサル防御
        if os.path.basename(template) != template or ".." in template:
            self._send_error(400, "Invalid template name")
            return

        templates_dir = self._templates_dir()
        html_path = os.path.join(templates_dir, f"{template}.html")
        if not os.path.isfile(html_path):
            # フォールバック: generic.html → 最後にエラー
            html_path = os.path.join(templates_dir, f"{FALLBACK_TEMPLATE}.html")
            if not os.path.isfile(html_path):
                self._send_error(
                    404, f"Template not found: {template}.html / {FALLBACK_TEMPLATE}.html"
                )
                return

        try:
            body = Path(html_path).read_text(encoding="utf-8").encode("utf-8")
        except (IOError, OSError):
            self._send_error(500, "Internal Server Error")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_asset(self, relpath):
        """GET /assets/<path> — templates/assets/ 配下の静的ファイルを返す。"""
        # パストラバーサル防御
        if ".." in relpath.split("/") or relpath.startswith("/"):
            self._send_error(400, "Invalid asset path")
            return

        assets_dir = os.path.join(self._templates_dir(), "assets")
        filepath = os.path.join(assets_dir, relpath)

        # realpath で assets_dir 配下を保証(シンボリックリンク経由の脱出防止)
        real_asset = os.path.realpath(filepath)
        real_base = os.path.realpath(assets_dir)
        if not (real_asset == real_base or real_asset.startswith(real_base + os.sep)):
            self._send_error(400, "Asset outside base directory")
            return

        if not os.path.isfile(real_asset):
            self._send_error(404, f"Asset not found: {relpath}")
            return

        ext = os.path.splitext(relpath)[1].lower()
        mime = ASSET_MIME.get(ext, "application/octet-stream")
        try:
            with open(real_asset, "rb") as f:
                body = f.read()
        except (IOError, OSError):
            self._send_error(500, "Internal Server Error")
            return

        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_session(self):
        """GET /session — セッション全体を JSON で返す。"""
        data = build_monitor_session(self.server.session_dir, self.server.skill)
        self._send_json(data)

    def _handle_sse(self):
        """GET /sse — SSE ストリームを開始する。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        server = self.server
        with server.sse_lock:
            server.sse_clients.append(self.wfile)

        try:
            while not server.shutdown_event.is_set():
                server.shutdown_event.wait(timeout=1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with server.sse_lock:
                if self.wfile in server.sse_clients:
                    server.sse_clients.remove(self.wfile)

    def _handle_notify(self):
        """POST /notify — 更新通知を受信する。

        1. session_dir 存在確認(消失時は session_end 送信して停止)
        2. SSE クライアントに update イベントを Push
        """
        server = self.server

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > self.MAX_CONTENT_LENGTH:
            self._send_json({"error": "payload_too_large"}, status=413)
            return
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json({"error": "invalid_json"}, status=400)
            return

        if not isinstance(payload, dict):
            self._send_json({"error": "invalid_payload"}, status=400)
            return

        # session_dir 消失チェック
        if not os.path.isdir(server.session_dir):
            server.send_session_end()
            self._send_json({"status": "session_end"})
            return

        filename = payload.get("file", "unknown")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event_data = {
            "type": "update",
            "file": filename,
            "timestamp": timestamp,
        }
        server.broadcast_sse("update", event_data)
        # mtime スナップショットも更新(heartbeat と重複通知を防ぐ)
        server.refresh_session_state()
        self._send_json({"status": "ok"})

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# SkillMonitorServer — SSE サーバー本体
# ---------------------------------------------------------------------------

class _ThreadingHTTPServer(HTTPServer):
    """リクエストごとにスレッドを生成する HTTPServer。SSE 並行処理のため。"""

    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(
            target=self._process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        t.start()

    def _process_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class SkillMonitorServer(_ThreadingHTTPServer):
    """セッション進捗のリアルタイム表示 SSE サーバー。

    monitor_dir の config.json から session_dir / skill / port を読み込み、
    localhost:{port} でリッスンする。

    - session_dir 消失 / mtime 変化をハートビートで監視
    - SSE 経由でブラウザに update / session_end を Push
    """

    def __init__(self, monitor_dir, port,
                 heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL):
        config_path = os.path.join(monitor_dir, "config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        self.monitor_dir = monitor_dir
        self.session_dir = config["session_dir"]
        # skill は v3.0 で追加。後方互換のため template キーもフォールバック参照。
        self.skill = config.get("skill") or config.get("template") or ""
        self.port = port
        self.heartbeat_interval = heartbeat_interval

        self.sse_clients = []
        self.sse_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self._session_end_sent = False
        self._heartbeat_thread = None

        # mtime スナップショット(heartbeat で差分検知)
        self._state_lock = threading.Lock()
        self._session_state = _compute_session_state(self.session_dir)

        super().__init__(("127.0.0.1", port), RequestHandler)

    def start(self):
        """サーバーを起動し、server.pid を書き込む。ハートビートも開始する。"""
        pid_path = os.path.join(self.monitor_dir, "server.pid")
        Path(pid_path).write_text(str(os.getpid()), encoding="utf-8")

        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        self.serve_forever()

    def stop(self):
        """サーバーを停止し、monitor_dir を削除する。"""
        self.shutdown_event.set()
        self.shutdown()
        self._cleanup_monitor_dir()

    def schedule_shutdown(self):
        """別スレッドからサーバー停止をスケジュールする(デッドロック回避)。"""
        self.shutdown_event.set()

        def _do_shutdown():
            self.shutdown()
            self._cleanup_monitor_dir()

        t = threading.Thread(target=_do_shutdown, daemon=False)
        t.start()

    def _cleanup_monitor_dir(self):
        try:
            if os.path.isdir(self.monitor_dir):
                shutil.rmtree(self.monitor_dir)
        except OSError as e:
            print(f"警告: monitor_dir 削除失敗: {self.monitor_dir}: {e}",
                  file=sys.stderr)

    def broadcast_sse(self, event_name, data):
        """全 SSE クライアントにイベントを送信する。"""
        message = (
            f"event: {event_name}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        )
        encoded = message.encode("utf-8")
        with self.sse_lock:
            dead_clients = []
            for client in self.sse_clients:
                try:
                    client.write(encoded)
                    client.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead_clients.append(client)
            for client in dead_clients:
                self.sse_clients.remove(client)

    def send_session_end(self):
        """session_end イベントを送信し、サーバー停止をスケジュールする。"""
        with self.sse_lock:
            if self._session_end_sent:
                return
            self._session_end_sent = True
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.broadcast_sse(
            "session_end",
            {
                "type": "session_end",
                "timestamp": timestamp,
                "message": SESSION_END_MESSAGE,
            },
        )
        self.schedule_shutdown()

    def refresh_session_state(self):
        """mtime スナップショットを更新する(POST /notify 成功時)。"""
        with self._state_lock:
            self._session_state = _compute_session_state(self.session_dir)

    def _heartbeat_loop(self):
        """session_dir の存在と mtime 変化を 30 秒周期で監視する。

        - session_dir 消失 → session_end を送信してサーバー停止
        - mtime 変化 → update を Push(直接通知が届かなかった場合の保険)
        """
        while not self.shutdown_event.is_set():
            self.shutdown_event.wait(timeout=self.heartbeat_interval)
            if self.shutdown_event.is_set():
                break
            if not os.path.isdir(self.session_dir):
                self.send_session_end()
                break

            current_state = _compute_session_state(self.session_dir)
            with self._state_lock:
                changed = current_state != self._session_state
                if changed:
                    self._session_state = current_state

            if changed:
                timestamp = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                self.broadcast_sse(
                    "update",
                    {
                        "type": "update",
                        "file": "heartbeat",
                        "timestamp": timestamp,
                    },
                )


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="forge monitor SSE サーバー(monitor ディレクトリ指定)"
    )
    parser.add_argument(
        "--dir",
        required=True,
        metavar="MONITOR_DIR",
        help="monitor ディレクトリ(config.json / server.pid を格納)",
    )
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="リッスンポート",
    )
    args = parser.parse_args()

    monitor_dir = os.path.abspath(args.dir)
    config_path = os.path.join(monitor_dir, "config.json")

    if not os.path.isfile(config_path):
        error = {
            "error": "config_not_found",
            "monitor_dir": monitor_dir,
            "message": f"config.json not found: {config_path}",
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    try:
        server = SkillMonitorServer(monitor_dir, port=args.port)
    except json.JSONDecodeError as e:
        error = {
            "error": "config_invalid_json",
            "config_path": config_path,
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        error = {
            "error": "port_bind_failed",
            "port": args.port,
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
