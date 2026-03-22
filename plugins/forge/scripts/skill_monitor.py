#!/usr/bin/env python3
"""skill_monitor — セッション進捗のリアルタイムブラウザ表示サーバー。

SSE サーバーとして動作し、セッションディレクトリの YAML ファイルを
JSON に変換してブラウザに Push する。

このモジュールには以下のコンポーネントを含む:
  - YamlReader: セッション YAML リーダー（yaml_utils.parse_yaml に委譲）
  - SkillMonitorServer / RequestHandler: SSE サーバー
"""

import argparse
import json
import os

import sys
import threading

import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# yaml_utils.py の parse_yaml() を使用（content ベースのパース）
from session.yaml_utils import parse_yaml


# ---------------------------------------------------------------------------
# YamlReader — セッション YAML パーサー
# ---------------------------------------------------------------------------

class YamlReader:
    """セッションディレクトリ内の YAML / Markdown ファイルを読み込み、
    dict / str に変換する。

    YAML パースは yaml_utils.parse_yaml() に委譲する。
    review.md は Markdown のため文字列としてそのまま格納する。
    """

    # セッションディレクトリ内で読み込み対象のファイル一覧
    SESSION_FILES = [
        "session.yaml",
        "plan.yaml",
        "review.md",
    ]

    # refs/ ディレクトリ内で読み込み対象のファイル一覧
    REFS_FILES = [
        "specs.yaml",
        "rules.yaml",
        "code.yaml",
    ]

    def read_session_dir(self, session_dir):
        """セッションディレクトリ内の全ファイルを読み込み JSON 化する。

        Args:
            session_dir: セッションディレクトリのパス

        Returns:
            dict: 設計書 5.3 節準拠の /session レスポンス形式
                {
                    "session_dir": "...",
                    "files": {
                        "session.yaml": {"exists": true, "content": {...}},
                        ...
                    },
                    "refs": {
                        "specs.yaml": {"exists": true, "content": {...}},
                        ...
                    },
                    "refs_yaml": {"exists": true/false, "content": {...}/null}
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

            if content is not None:
                result["files"][filename] = {
                    "exists": True,
                    "content": content,
                }
            else:
                result["files"][filename] = {
                    "exists": False,
                    "content": None,
                }

        # refs/ ディレクトリ内のファイル
        refs_dir = os.path.join(session_dir, "refs")
        for filename in self.REFS_FILES:
            filepath = os.path.join(refs_dir, filename)
            content = self.read_yaml_file(filepath)

            if content is not None:
                result["refs"][filename] = {
                    "exists": True,
                    "content": content,
                }
            else:
                result["refs"][filename] = {
                    "exists": False,
                    "content": None,
                }

        # refs.yaml（フラットなメタデータ — review スキル用）
        refs_yaml_path = os.path.join(session_dir, "refs.yaml")
        refs_yaml_content = self.read_yaml_file(refs_yaml_path)
        if refs_yaml_content is not None:
            result["refs_yaml"] = {
                "exists": True,
                "content": refs_yaml_content,
            }

        return result

    def read_yaml_file(self, filepath):
        """YAML ファイルを読み込み dict に変換する。

        yaml_utils.parse_yaml() に委譲する。フラット・リスト付き両方に対応。

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
            print(f"警告: YAML ファイルの読み込みに失敗しました: {filepath}: {e}", file=sys.stderr)
            return None

        # 空ファイルは空 dict を返す
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
            print(f"警告: Markdown ファイルの読み込みに失敗しました: {filepath}: {e}", file=sys.stderr)
            return None



# ---------------------------------------------------------------------------
# RequestHandler — HTTP リクエストハンドラ
# ---------------------------------------------------------------------------

class RequestHandler(BaseHTTPRequestHandler):
    """SSE サーバーの HTTP リクエストハンドラ。

    設計書 5.2 節で定義された以下のエンドポイントを処理する:
      - GET /        : index.html を返す
      - GET /session : セッション全体を JSON で返す
      - GET /sse     : SSE ストリーム
      - GET /history : 更新履歴を JSON で返す
      - POST /notify : フックからの更新通知
    """

    def log_message(self, format, *args):
        """ログ出力を抑制する（テスト時のノイズ低減）。"""
        pass

    def do_GET(self):
        """GET リクエストを処理する。"""
        if self.path == "/":
            self._handle_index()
        elif self.path == "/session":
            self._handle_session()
        elif self.path == "/sse":
            self._handle_sse()
        elif self.path == "/history":
            self._handle_history()
        else:
            self._send_json({"error": "not_found"}, status=404)

    def do_POST(self):
        """POST リクエストを処理する。"""
        if self.path == "/notify":
            self._handle_notify()
        else:
            self._send_json({"error": "not_found"}, status=404)

    def _handle_index(self):
        """GET / — index.html を返す。ファイルが存在しない場合は「Coming soon」。"""
        # static/index.html のパスを解決
        script_dir = os.path.dirname(os.path.abspath(__file__))
        plugin_root = os.path.dirname(script_dir)
        index_path = os.path.join(plugin_root, "static", "index.html")

        if os.path.isfile(index_path):
            try:
                content = Path(index_path).read_text(encoding="utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
            except (IOError, OSError):
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Internal Server Error")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Coming soon")

    def _handle_session(self):
        """GET /session — セッション全体を JSON で返す。"""
        server = self.server
        reader = YamlReader()
        data = reader.read_session_dir(server.session_dir)
        self._send_json(data)

    def _handle_sse(self):
        """GET /sse — SSE ストリームを開始する。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        # クライアントを登録
        server = self.server
        with server.sse_lock:
            server.sse_clients.append(self.wfile)

        try:
            # SSE 接続を維持（クライアント切断まで待機）
            while not server.shutdown_event.is_set():
                server.shutdown_event.wait(timeout=1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with server.sse_lock:
                if self.wfile in server.sse_clients:
                    server.sse_clients.remove(self.wfile)

    def _handle_history(self):
        """GET /history — 更新履歴を JSON で返す。"""
        server = self.server
        with server.history_lock:
            data = list(server.history)
        self._send_json(data)

    def _handle_notify(self):
        """POST /notify — フックからの更新通知を受信する。

        通知を受信すると:
          1. session_dir の存在確認（消失時は session_end を送信して停止）
          2. history に追記
          3. SSE クライアントに update イベントを Push
        """
        server = self.server

        # リクエストボディを読み込み
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            self._send_json({"error": "invalid_json"}, status=400)
            return

        # payload が dict でない場合は 400 を返す（配列・文字列・数値等を拒否）
        if not isinstance(payload, dict):
            self._send_json({"error": "invalid_payload"}, status=400)
            return

        # session_dir の存在確認（設計書 5.8: 通知時チェック）
        if not os.path.isdir(server.session_dir):
            self._send_session_end(server)
            self._send_json({"status": "session_end"})
            return

        filename = payload.get("file", "unknown")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # history に追記（設計書 5.4.1）
        entry = {
            "timestamp": timestamp,
            "file": filename,
            "event": "update",
        }
        with server.history_lock:
            server.history.append(entry)

        # SSE Push（設計書 5.4）
        event_data = {
            "type": "update",
            "file": filename,
            "timestamp": timestamp,
        }
        self._broadcast_sse(server, "update", event_data)

        self._send_json({"status": "ok"})

    def _send_json(self, data, status=200):
        """JSON レスポンスを送信する。"""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _broadcast_sse(self, server, event_name, data):
        """全 SSE クライアントにイベントを送信する（server に委譲）。

        Args:
            server: SkillMonitorServer インスタンス
            event_name: SSE イベント名
            data: イベントデータ（dict）
        """
        server.broadcast_sse(event_name, data)

    def _send_session_end(self, server):
        """session_end イベントを全クライアントに送信し、サーバーを停止する（server に委譲）。"""
        server.send_session_end()


# ---------------------------------------------------------------------------
# SkillMonitorServer — SSE サーバー本体
# ---------------------------------------------------------------------------

class _ThreadingHTTPServer(HTTPServer):
    """リクエストごとにスレッドを生成する HTTPServer。

    SSE 接続を保持しながら他のリクエストを処理するため、
    socketserver.ThreadingMixIn 相当の機能を実装する。
    """

    daemon_threads = True

    def process_request(self, request, client_address):
        """リクエストを別スレッドで処理する。"""
        t = threading.Thread(
            target=self._process_request_thread,
            args=(request, client_address),
            daemon=True,
        )
        t.start()

    def _process_request_thread(self, request, client_address):
        """別スレッドでリクエストを処理する。"""
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


class SkillMonitorServer(_ThreadingHTTPServer):
    """セッション進捗のリアルタイム表示 SSE サーバー。

    設計書 5.1〜5.8 節に基づく実装:
      - HTTP サーバー（localhost のみ、マルチスレッド）
      - SSE クライアント管理
      - 更新履歴管理
      - ハートビート（定期的に session_dir 存在確認）

    Args:
        session_dir: 監視対象のセッションディレクトリ
        port: リッスンポート（デフォルト 8765）
        heartbeat_interval: ハートビート間隔（秒、デフォルト 30.0）
    """

    def __init__(self, session_dir, port=8765, heartbeat_interval=30.0):
        self.session_dir = session_dir
        self.port = port
        self.heartbeat_interval = heartbeat_interval
        self.history = []
        self.history_lock = threading.Lock()
        self.sse_clients = []
        self.sse_lock = threading.Lock()
        self.shutdown_event = threading.Event()
        self._heartbeat_thread = None

        # HTTPServer の初期化（localhost のみバインド — 設計書 5.2 セキュリティ）
        super().__init__(("127.0.0.1", port), RequestHandler)

    def start(self):
        """サーバーを起動し、ハートビートスレッドも開始する。"""
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        self.serve_forever()

    def stop(self):
        """サーバーを停止する。"""
        self.shutdown_event.set()
        self.shutdown()

    def schedule_shutdown(self):
        """別スレッドからサーバー停止をスケジュールする。

        serve_forever() のループ内から直接 shutdown() を呼ぶとデッドロック
        するため、別スレッドで実行する。
        """
        self.shutdown_event.set()
        t = threading.Thread(target=self.shutdown, daemon=True)
        t.start()

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
        """session_end イベントを全クライアントに送信し、サーバー停止をスケジュールする。

        history への追記、SSE broadcast、shutdown スケジュールを一括で行う。
        RequestHandler._send_session_end() と _heartbeat_loop() の両方から呼び出される。
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event_data = {
            "type": "session_end",
            "timestamp": timestamp,
        }
        # history に追記
        with self.history_lock:
            self.history.append({
                "timestamp": timestamp,
                "file": "",
                "event": "session_end",
            })
        self.broadcast_sse("session_end", event_data)
        # サーバー停止をスケジュール
        self.schedule_shutdown()

    def _heartbeat_loop(self):
        """定期的に session_dir の存在を確認し、消失時に停止する。

        設計書 5.8: ハートビートによる自動停止。
        周期は heartbeat_interval（デフォルト 30 秒）で制御する。
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

    設計書 5.1 節:
      python3 skill_monitor.py <session_dir> [--port 8765] [--no-open]
    """
    parser = argparse.ArgumentParser(
        description="セッション進捗のリアルタイムブラウザ表示 SSE サーバー"
    )
    parser.add_argument(
        "session_dir",
        help="監視対象のセッションディレクトリ",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="リッスンポート（デフォルト: 8765）",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="ブラウザ自動オープンを無効化",
    )
    args = parser.parse_args()

    # session_dir の存在確認
    if not os.path.isdir(args.session_dir):
        error = {
            "error": "session_dir_not_found",
            "session_dir": args.session_dir,
            "message": f"Session directory not found: {args.session_dir}",
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    try:
        server = SkillMonitorServer(args.session_dir, port=args.port)
    except OSError as e:
        # ポートバインド失敗（設計書 5.1: エラー JSON 出力）
        error = {
            "error": "port_bind_failed",
            "port": args.port,
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # ブラウザ自動オープン
    if not args.no_open:
        url = f"http://localhost:{args.port}/"
        threading.Thread(
            target=lambda: webbrowser.open(url), daemon=True
        ).start()

    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
