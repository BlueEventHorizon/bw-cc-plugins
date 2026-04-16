#!/usr/bin/env python3
"""server.py — show-browser SSE サーバー。

monitor ディレクトリ（config.json）を読み込み、
セッションディレクトリの YAML ファイルを JSON に変換してブラウザに Push する。

コンポーネント:
  - YamlReader: セッション YAML リーダー
  - RequestHandler: HTTP リクエストハンドラ
  - SkillMonitorServer: SSE サーバー本体

設計書: DES-012 show-browser 設計書 v2.0
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

# server.py のパス: plugins/forge/skills/show-browser/scripts/server.py
# yaml_utils のパス: plugins/forge/scripts/session/yaml_utils.py
# 3階層上（show-browser/ → skills/ → forge/）+ scripts/
_SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "scripts",
)
sys.path.insert(0, os.path.abspath(_SCRIPTS_DIR))

from session.yaml_utils import parse_yaml


# ---------------------------------------------------------------------------
# YamlReader — セッション YAML パーサー
# ---------------------------------------------------------------------------

class YamlReader:
    """セッションディレクトリ内の YAML / Markdown ファイルを読み込み dict / str に変換する。

    YAML パースは session.yaml_utils.parse_yaml() に委譲する。
    review.md は Markdown のため文字列として格納する。
    """

    SESSION_FILES = [
        "session.yaml",
        "plan.yaml",
        "review.md",
    ]

    REFS_FILES = [
        "specs.yaml",
        "rules.yaml",
        "code.yaml",
    ]

    def read_session_dir(self, session_dir):
        """セッションディレクトリ内の全ファイルを読み込み JSON 化する。

        設計書 5.4 節準拠の /session レスポンス形式を返す。

        Args:
            session_dir: セッションディレクトリのパス

        Returns:
            dict: {
                "session_dir": str,
                "files": {filename: {"exists": bool, "content": dict|str|None}},
                "refs": {filename: {"exists": bool, "content": dict|None}},
                "refs_yaml": {"exists": bool, "content": dict|None},
            }
        """
        result = {
            "session_dir": session_dir,
            "files": {},
            "refs": {},
            "refs_yaml": {"exists": False, "content": None},
        }

        # セッションディレクトリ直下のファイル
        for filename in self.SESSION_FILES:
            filepath = os.path.join(session_dir, filename)
            if filename.endswith(".md"):
                content = self.read_markdown_file(filepath)
            else:
                content = self.read_yaml_file(filepath)
            result["files"][filename] = {
                "exists": content is not None,
                "content": content,
            }

        # refs/ ディレクトリ内のファイル
        refs_dir = os.path.join(session_dir, "refs")
        for filename in self.REFS_FILES:
            filepath = os.path.join(refs_dir, filename)
            content = self.read_yaml_file(filepath)
            result["refs"][filename] = {
                "exists": content is not None,
                "content": content,
            }

        # refs.yaml（フラット: review スキル用）
        refs_yaml_path = os.path.join(session_dir, "refs.yaml")
        refs_yaml_content = self.read_yaml_file(refs_yaml_path)
        if refs_yaml_content is not None:
            result["refs_yaml"] = {"exists": True, "content": refs_yaml_content}

        return result

    def read_yaml_file(self, filepath):
        """YAML ファイルを読み込み dict に変換する。

        Args:
            filepath: YAML ファイルのパス

        Returns:
            dict | None: パース結果。ファイルが存在しない場合は None
        """
        if not os.path.isfile(filepath):
            return None
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except (IOError, OSError) as e:
            print(f"警告: YAML 読み込み失敗: {filepath}: {e}", file=sys.stderr)
            return None
        if not content.strip():
            return {}
        return parse_yaml(content)

    def read_markdown_file(self, filepath):
        """Markdown ファイルを文字列として読み込む。

        Args:
            filepath: Markdown ファイルのパス

        Returns:
            str | None: ファイル内容。存在しない場合は None
        """
        if not os.path.isfile(filepath):
            return None
        try:
            return Path(filepath).read_text(encoding="utf-8")
        except (IOError, OSError) as e:
            print(f"警告: Markdown 読み込み失敗: {filepath}: {e}", file=sys.stderr)
            return None


# ---------------------------------------------------------------------------
# RequestHandler — HTTP リクエストハンドラ
# ---------------------------------------------------------------------------

class RequestHandler(BaseHTTPRequestHandler):
    """SSE サーバーの HTTP リクエストハンドラ。

    設計書 5.3 節エンドポイント:
      GET  /        → templates/{config.template}.html を返す
      GET  /session → session_dir の全 YAML を JSON で返す
      GET  /sse     → SSE ストリーム
      POST /notify  → notifier.py からの更新通知を受信し SSE Push
    """

    def log_message(self, format, *args):
        """ログ出力を抑制する（テスト時ノイズ低減）。"""
        pass

    def do_GET(self):
        if self.path == "/":
            self._handle_index()
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

    def _handle_index(self):
        """GET / — templates/{template}.html を返す。ファイルが存在しない場合は 404。"""
        server = self.server
        template = server.template

        # パストラバーサル防御: テンプレート名にパス区切り文字を含まないことを検証
        if os.path.basename(template) != template or ".." in template:
            self._send_error(400, "Invalid template name")
            return

        templates_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
            "templates",
        )
        html_path = os.path.join(templates_dir, f"{template}.html")

        if os.path.isfile(html_path):
            try:
                content = Path(html_path).read_text(encoding="utf-8")
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (IOError, OSError):
                self._send_error(500, "Internal Server Error")
        else:
            self._send_error(404, f"Template not found: {template}.html")

    def _handle_session(self):
        """GET /session — セッション全体を JSON で返す。"""
        reader = YamlReader()
        data = reader.read_session_dir(self.server.session_dir)
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

    # /notify ペイロードの最大サイズ（64KB）
    MAX_CONTENT_LENGTH = 65536

    def _handle_notify(self):
        """POST /notify — notifier.py からの更新通知を受信する。

        1. session_dir 存在確認（消失時は session_end を送信して停止）
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

        # session_dir 消失チェック（設計書 5.9）
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
        self._send_json({"status": "ok"})

    def _send_json(self, data, status=200):
        """JSON レスポンスを送信する。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status, message):
        """エラーレスポンスを送信する。"""
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
    """リクエストごとにスレッドを生成する HTTPServer。

    SSE 接続を保持しながら他のリクエストを処理するためスレッド分離する。
    """

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


# ハートビート間隔のデフォルト値（秒）— 設計書 DES-012 §5.9
DEFAULT_HEARTBEAT_INTERVAL = 30.0


class SkillMonitorServer(_ThreadingHTTPServer):
    """セッション進捗のリアルタイム表示 SSE サーバー。

    monitor_dir の config.json から session_dir / template / port を読み込み、
    localhost:{port} でリッスンする。

    設計書 3.2 節クラス設計 + 5.1〜5.9 節に基づく実装。

    Args:
        monitor_dir: monitor ディレクトリパス（config.json / server.pid を格納）
        port: リッスンポート
        heartbeat_interval: ハートビート間隔（秒）
    """

    def __init__(self, monitor_dir, port, heartbeat_interval=DEFAULT_HEARTBEAT_INTERVAL):
        # config.json を読み込む
        config_path = os.path.join(monitor_dir, "config.json")
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

        self.monitor_dir = monitor_dir
        self.session_dir = config["session_dir"]
        self.template = config.get("template", "review_list")
        self.port = port
        self.heartbeat_interval = heartbeat_interval

        self.sse_clients = []
        self.sse_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self._session_end_sent = False
        self._heartbeat_thread = None

        # localhost のみバインド（設計書 5.3 セキュリティ）
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
        """サーバーを停止する。monitor_dir も削除する。"""
        self.shutdown_event.set()
        self.shutdown()
        self._cleanup_monitor_dir()

    def schedule_shutdown(self):
        """別スレッドからサーバー停止をスケジュールする。

        serve_forever() 内から直接 shutdown() を呼ぶとデッドロックするため
        別スレッドで実行する。停止後に monitor_dir を削除する。
        """
        self.shutdown_event.set()

        def _do_shutdown():
            self.shutdown()
            self._cleanup_monitor_dir()

        # daemon=False: メインスレッド終了前に cleanup 完了を保証する
        t = threading.Thread(target=_do_shutdown, daemon=False)
        t.start()

    def _cleanup_monitor_dir(self):
        """monitor_dir（server.pid を含む）を削除する。

        設計書 5.9: 正常停止時は server.py が自身で削除する。
        """
        try:
            if os.path.isdir(self.monitor_dir):
                shutil.rmtree(self.monitor_dir)
        except OSError as e:
            print(f"警告: monitor_dir 削除失敗: {self.monitor_dir}: {e}", file=sys.stderr)

    def broadcast_sse(self, event_name, data):
        """全 SSE クライアントにイベントを送信する。

        Args:
            event_name: SSE イベント名
            data: イベントデータ（dict）
        """
        message = f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
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
        """session_end イベントを送信し、サーバー停止をスケジュールする。

        RequestHandler._handle_notify() と _heartbeat_loop() から呼ばれる。
        二重呼び出しをガードフラグでスレッドセーフに防止する。
        """
        with self.sse_lock:
            if self._session_end_sent:
                return
            self._session_end_sent = True
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.broadcast_sse("session_end", {"type": "session_end", "timestamp": timestamp})
        self.schedule_shutdown()

    def _heartbeat_loop(self):
        """定期的に session_dir の存在を確認し、消失時に自動停止する。

        設計書 5.9: ハートビートによる自動停止（30秒周期）。
        """
        while not self.shutdown_event.is_set():
            self.shutdown_event.wait(timeout=self.heartbeat_interval)
            if self.shutdown_event.is_set():
                break
            if not os.path.isdir(self.session_dir):
                self.send_session_end()
                break


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------

def main():
    """CLI エントリーポイント。

    設計書 5.2 節:
      python3 server.py --dir <monitor-dir> --port <port>
    """
    parser = argparse.ArgumentParser(
        description="show-browser SSE サーバー（monitor ディレクトリ指定）"
    )
    parser.add_argument(
        "--dir",
        required=True,
        metavar="MONITOR_DIR",
        help="monitor ディレクトリ（config.json / server.pid を格納）",
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
        # config.json の JSON パースエラー
        error = {
            "error": "config_invalid_json",
            "config_path": config_path,
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        # ポートバインド失敗（設計書 5.2）
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
