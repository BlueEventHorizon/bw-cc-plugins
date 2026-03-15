#!/usr/bin/env python3
"""skill_monitor — セッション進捗のリアルタイムブラウザ表示サーバー。

SSE サーバーとして動作し、セッションディレクトリの YAML ファイルを
JSON に変換してブラウザに Push する。

このモジュールには以下のコンポーネントを含む:
  - YamlReader: セッション YAML パーサー（YAML → dict 変換）
  - SkillMonitorServer / RequestHandler: SSE サーバー（後続タスクで実装）
"""

import argparse
import json
import os
import re
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# session_manager.py の read_yaml() を再利用（フラット YAML 対応）
from session_manager import read_yaml


# ---------------------------------------------------------------------------
# YamlReader — セッション YAML パーサー
# ---------------------------------------------------------------------------

class YamlReader:
    """セッションディレクトリ内の YAML / Markdown ファイルを読み込み、
    dict / str に変換する。

    設計書 5.5 節で定義された3種の YAML パターンに対応:
      1. フラット key-value（session.yaml 等）
      2. リスト付き構造（plan.yaml, evaluation.yaml の items リスト）
      3. ネストオブジェクト付きリスト（refs.yaml の reference_docs 等）

    review.md は Markdown のため文字列としてそのまま格納する。
    """

    # セッションディレクトリ内で読み込み対象のファイル一覧
    SESSION_FILES = [
        "session.yaml",
        "plan.yaml",
        "evaluation.yaml",
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

        ファイル内容に応じて適切なパーサーを選択する:
          - リスト付き構造 → _parse_yaml_with_lists()
          - フラット key-value → read_yaml()（session_manager.py）

        Args:
            filepath: YAML ファイルのパス

        Returns:
            dict | None: パース結果。ファイルが存在しない場合は None
        """
        if not os.path.isfile(filepath):
            return None

        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except (IOError, OSError):
            return None

        # 空ファイルは空 dict を返す
        if not content.strip():
            return {}

        # リスト要素（"  - " パターン）を含むか判定
        if self._has_list_structure(content):
            return self._parse_yaml_with_lists(content)

        # フラット YAML は session_manager.py の read_yaml() を使用
        try:
            return read_yaml(filepath)
        except (IOError, OSError):
            return None

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
        except (IOError, OSError):
            return None

    # -------------------------------------------------------------------
    # 内部メソッド
    # -------------------------------------------------------------------

    def _has_list_structure(self, content):
        """YAML 内容がリスト構造を含むか判定する。

        インデントされた "- " パターン（リスト要素）の有無で判定する。
        トップレベルの "- " はインライン配列の可能性があるため除外。

        Args:
            content: YAML ファイルの内容

        Returns:
            bool: リスト構造を含む場合 True
        """
        for line in content.split("\n"):
            if not line or line.startswith("#"):
                continue
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent >= 2 and stripped.startswith("- "):
                return True
        return False

    def _parse_yaml_with_lists(self, content):
        """リスト付き YAML をパースする。

        対応パターン:
          - フラット key-value（トップレベル）
          - リスト付き構造（items リスト等）
          - ネストオブジェクト付きリスト（reference_docs 等）
          - 文字列リスト（target_files, files_modified 等）
          - インライン配列 ([a, b, c])

        resolve_doc_structure.py の parse_config() を参考に、
        セッション YAML 向けに最適化した実装。

        Args:
            content: YAML ファイルの内容

        Returns:
            dict: パース結果
        """
        result = {}
        lines = content.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 空行・コメントをスキップ
            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            indent = len(line) - len(line.lstrip())

            # トップレベルの key: value
            if indent == 0 and ":" in stripped and not stripped.startswith("- "):
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()

                if value:
                    # インライン配列 [a, b, c]
                    if value.startswith("[") and value.endswith("]"):
                        result[key] = self._parse_inline_array(value)
                    else:
                        result[key] = self._parse_scalar(value)
                    i += 1
                else:
                    # 次の行を先読みしてリストか辞書かを判定
                    child_items, consumed = self._parse_list_or_block(
                        lines, i + 1, parent_indent=0
                    )
                    result[key] = child_items
                    i += 1 + consumed
            else:
                i += 1

        return result

    def _parse_list_or_block(self, lines, start_idx, parent_indent):
        """子要素がリストかブロックかを判定してパースする。

        Args:
            lines: 全行のリスト
            start_idx: パース開始インデックス
            parent_indent: 親キーのインデント

        Returns:
            tuple: (パース結果（list または dict）, 消費した行数)
        """
        # 先読みしてリストか辞書かを判定
        for j in range(start_idx, min(start_idx + 10, len(lines))):
            line = lines[j]
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= parent_indent:
                # 親と同レベルか上 → 空コンテンツ
                return [], 0
            if stripped.startswith("- "):
                return self._parse_list_items(lines, start_idx, parent_indent)
            else:
                # 辞書ブロック
                return self._parse_dict_block(lines, start_idx, parent_indent)

        return [], 0

    def _parse_list_items(self, lines, start_idx, parent_indent):
        """リスト要素をパースする。

        "- key: value" 形式のオブジェクトリストと "- value" 形式の
        文字列リストの両方に対応。

        Args:
            lines: 全行のリスト
            start_idx: パース開始インデックス
            parent_indent: 親キーのインデント

        Returns:
            tuple: (リスト, 消費した行数)
        """
        items = []
        i = start_idx
        current_item = None
        item_indent = None

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # 空行・コメントをスキップ
            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            indent = len(line) - len(line.lstrip())

            # 親レベル以下に戻ったら終了
            if indent <= parent_indent:
                break

            if stripped.startswith("- "):
                item_indent = indent
                item_content = stripped[2:].strip()

                # "- key: value" 形式かどうか判定
                if ":" in item_content and not self._is_quoted_value(item_content):
                    # オブジェクト要素の開始
                    if current_item is not None:
                        items.append(current_item)
                    current_item = {}
                    k, _, v = item_content.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if v:
                        current_item[k] = self._parse_scalar(v)
                    else:
                        # 値なし → 次の行で子要素を読む
                        child, consumed = self._parse_list_or_block(
                            lines, i + 1, indent
                        )
                        current_item[k] = child
                        i += 1 + consumed
                        continue
                else:
                    # 文字列要素
                    if current_item is not None:
                        items.append(current_item)
                        current_item = None
                    items.append(self._parse_scalar(item_content))
                i += 1
            elif indent > parent_indent and current_item is not None:
                # リスト要素の継続行（オブジェクトのフィールド）
                if ":" in stripped and not stripped.startswith("- "):
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip()
                    if v:
                        if v.startswith("[") and v.endswith("]"):
                            current_item[k] = self._parse_inline_array(v)
                        else:
                            current_item[k] = self._parse_scalar(v)
                    else:
                        # 値なし → 次の行で子要素を読む
                        child, consumed = self._parse_list_or_block(
                            lines, i + 1, indent
                        )
                        current_item[k] = child
                        i += 1 + consumed
                        continue
                i += 1
            else:
                break

        if current_item is not None:
            items.append(current_item)

        return items, i - start_idx

    def _parse_dict_block(self, lines, start_idx, parent_indent):
        """辞書ブロックをパースする。

        Args:
            lines: 全行のリスト
            start_idx: パース開始インデックス
            parent_indent: 親のインデント

        Returns:
            tuple: (辞書, 消費した行数)
        """
        result = {}
        i = start_idx

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                i += 1
                continue

            indent = len(line) - len(line.lstrip())
            if indent <= parent_indent:
                break

            if ":" in stripped and not stripped.startswith("- "):
                k, _, v = stripped.partition(":")
                k = k.strip()
                v = v.strip()
                if v:
                    result[k] = self._parse_scalar(v)
                else:
                    child, consumed = self._parse_list_or_block(
                        lines, i + 1, indent
                    )
                    result[k] = child
                    i += 1 + consumed
                    continue
            i += 1

        return result, i - start_idx

    def _parse_inline_array(self, value):
        """インライン配列 [a, b, c] をパースする。

        Args:
            value: "[a, b, c]" 形式の文字列

        Returns:
            list: パース結果
        """
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [self._parse_scalar(item.strip()) for item in inner.split(",")]

    def _parse_scalar(self, value):
        """スカラー値をパースする（文字列、数値、真偽値）。

        Args:
            value: パース対象の値文字列

        Returns:
            str | int | bool: パース結果
        """
        if not value:
            return ""

        # クォート除去
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]

        # 真偽値
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False

        # 整数
        if value.lstrip("-").isdigit():
            return int(value)

        return value

    def _is_quoted_value(self, text):
        """テキストがクォートされた値かどうか判定する。

        "key: value" の value 部分ではなく、全体がクォートされている場合に True。

        Args:
            text: 判定対象のテキスト

        Returns:
            bool: クォートされた値の場合 True
        """
        stripped = text.strip()
        if len(stripped) >= 2:
            if stripped[0] == '"' and stripped[-1] == '"':
                return True
            if stripped[0] == "'" and stripped[-1] == "'":
                return True
        return False


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
        """全 SSE クライアントにイベントを送信する。

        Args:
            server: SkillMonitorServer インスタンス
            event_name: SSE イベント名
            data: イベントデータ（dict）
        """
        message = f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        encoded = message.encode("utf-8")

        with server.sse_lock:
            dead_clients = []
            for client in server.sse_clients:
                try:
                    client.write(encoded)
                    client.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    dead_clients.append(client)
            for client in dead_clients:
                server.sse_clients.remove(client)

    def _send_session_end(self, server):
        """session_end イベントを全クライアントに送信し、サーバーを停止する。"""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        event_data = {
            "type": "session_end",
            "timestamp": timestamp,
        }
        # history に追記
        with server.history_lock:
            server.history.append({
                "timestamp": timestamp,
                "file": "",
                "event": "session_end",
            })
        self._broadcast_sse(server, "session_end", event_data)
        # サーバー停止をスケジュール
        server.schedule_shutdown()


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
      - ハートビート（30秒周期で session_dir 存在確認）

    Args:
        session_dir: 監視対象のセッションディレクトリ
        port: リッスンポート（デフォルト 8765）
    """

    def __init__(self, session_dir, port=8765):
        self.session_dir = session_dir
        self.port = port
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

    def _heartbeat_loop(self):
        """30秒周期で session_dir の存在を確認し、消失時に停止する。

        設計書 5.8: ハートビートによる自動停止。
        """
        while not self.shutdown_event.is_set():
            self.shutdown_event.wait(timeout=30.0)
            if self.shutdown_event.is_set():
                break
            if not os.path.isdir(self.session_dir):
                # session_end イベントを送信
                timestamp = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                event_data = {
                    "type": "session_end",
                    "timestamp": timestamp,
                }
                with self.history_lock:
                    self.history.append({
                        "timestamp": timestamp,
                        "file": "",
                        "event": "session_end",
                    })
                # SSE クライアントに送信
                message = (
                    f"event: session_end\n"
                    f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                )
                encoded = message.encode("utf-8")
                with self.sse_lock:
                    for client in self.sse_clients:
                        try:
                            client.write(encoded)
                            client.flush()
                        except (BrokenPipeError, ConnectionResetError, OSError):
                            pass
                # サーバー停止
                self.schedule_shutdown()
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
