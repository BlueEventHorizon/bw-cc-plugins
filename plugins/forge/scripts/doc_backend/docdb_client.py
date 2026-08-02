#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-db の MCP Streamable HTTP エンドポイントを直接叩く軽量クライアント。

登録済み MCP tool ラッパー（`mcp__doc-db__*`）に依存せず、
`http://localhost:{port}/mcp` へ JSON-RPC を次の順で送る。

1. `initialize`
2. `notifications/initialized`
3. `tools/call`

`Mcp-Session-Id` は同一 operation 中（同一 `Client` インスタンス中）保持する。
サーバは JSON（`application/json`）と SSE（`text/event-stream`）のどちらでも
応答しうるため、両形式を同一の JSON-RPC response dict へ解析する。

## 依存

Python 標準ライブラリのみ。

## 情報保護 [MANDATORY]

本モジュールは **認証情報を読む処理も出力する処理も持たない**。
`~/.doc-db/doc-db.yaml` から取り出すのは `port`（整数）だけであり、
設定ファイルの本文・環境変数値を例外メッセージや戻り値へ載せない。
エラー本文に含めてよいのは URL、port、HTTP status、および doc-db が返した
非機密メッセージに限る。

## テスト境界

HTTP 送信は `post_json_rpc()` の 1 関数に閉じている。`Client` は
`transport=` でこの関数を差し替えられるため、JSON 応答・SSE 応答・
tool error・HTTP error はいずれも応答注入で決定論的に再現できる。
socket を開く fake server は用いない。
port 解決も `config_path=` / `port=` で差し替えられるため、
テストが利用者の home 設定に依存することはない。

## 提供する操作

forge が使う doc-db MCP tool は次の 4 つだけである。
これ以外の tool（`upsert_documents` / `schedule_delete_series` /
`trash_index` 等）は本モジュールでは扱わない。

| メソッド            | tool              | 用途                                       |
| ------------------- | ----------------- | ------------------------------------------ |
| `query()`           | `query`           | series を指定した検索                      |
| `sync_documents()`  | `sync_documents`  | desired-state 同期の投入（job_id 即時返却）|
| `get_sync_status()` | `get_sync_status` | 同期 job の状態を 1 回取得                 |
| `list_indexes()`    | `list_indexes`    | KEY 一覧と各 KEY の series[] の確認         |

完了待ちのポーリングループは本モジュールに持たない（呼び出し側の責務）。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

# --- 通信定数 -----------------------------------------------------------------
# 通常 operation 用の値と、起動確認（probe）専用の値を分けて持つ。
# probe 値は利用者向けの性能目標ではなく、未起動判定で長時間ブロックしないための
# 内部上限である。

#: doc-db の既定 port（`~/.doc-db/doc-db.yaml` に `port` が無い場合に使う）
DEFAULT_PORT = 58080

#: 通常 operation の HTTP timeout（秒）
DEFAULT_TIMEOUT_SECONDS = 600

#: 同期完了待ちの上限（秒）。ポーリングは呼び出し側が行い、本値をその上限に使う
SYNC_WAIT_LIMIT_SECONDS = 600

#: 同期状態のポーリング間隔（秒）
SYNC_POLL_INTERVAL_SECONDS = 2.0

#: 接続 probe の HTTP timeout（秒）。localhost の起動確認専用
PROBE_TIMEOUT_SECONDS = 1

#: doc-db 起動後の再接続を試み続ける期限（秒）
STARTUP_DEADLINE_SECONDS = 10

#: doc-db 起動後の再接続の再試行間隔（秒）
STARTUP_RETRY_INTERVAL_SECONDS = 0.25

#: MCP protocol version
PROTOCOL_VERSION = "2025-03-26"

#: クライアント識別子（MCP `clientInfo`）
CLIENT_NAME = "forge-doc-backend-client"
CLIENT_VERSION = "1.0"

#: doc-db の設定ファイル。取り出すのは `port` のみ
DEFAULT_CONFIG_PATH = Path.home() / ".doc-db" / "doc-db.yaml"

#: query の既定値。`top_n` は recall 優先の契約（doc-db 既定 10 より広く取る）
DEFAULT_QUERY_MODE = "all"
DEFAULT_QUERY_TOP_N = 20

#: session header を付けた request がこの HTTP status を返した場合、session の終了を意味する
HTTP_SESSION_EXPIRED = 404

_PORT_PATTERN = re.compile(r"^\s*port\s*:\s*(\d+)", re.MULTILINE)


# --- 例外 ---------------------------------------------------------------------


class DocDbClientError(Exception):
    """doc-db クライアントの基底例外。"""


class TransportError(DocDbClientError):
    """接続そのものが確立できなかった（サーバ未起動・名前解決不能等）。

    呼び出し側はこれを「doc-db が利用不能」の候補として扱ってよい。
    """


class HttpError(DocDbClientError):
    """HTTP レベルのエラー応答（4xx / 5xx）。

    接続は確立しているため、doc-db が利用不能であることの根拠にはならない。
    """

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} ({url}): {body}")
        self.status = status
        self.body = body
        self.url = url


class ProtocolError(DocDbClientError):
    """応答が MCP / JSON-RPC の契約を満たさない（解析不能・空応答・session 確立失敗）。

    接続確立後の障害であり、別 backend への切り替え理由にしない。
    """


class ToolError(DocDbClientError):
    """`tools/call` が tool 実行エラーを返した。

    接続確立後の障害であり、別 backend への切り替え理由にしない。
    KEY 不在・ゴミ箱状態もこの経路で届く（doc-db 0.3.3 以降は JSON-RPC error）。
    呼び出し側は `data["code"]` の識別子（`KEY_NOT_FOUND` / `KEY_TRASHED`）で
    未整備と障害を判別する。メッセージ文言・数値 `code` では判別しない。
    識別子を読み取れないもの（`data` なし・未知の識別子・isError 経路）は
    障害として扱う。
    """

    def __init__(self, message: str, code: int | None = None, data=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data


# --- port 解決 ----------------------------------------------------------------


def read_port(config_path: Path | None = None) -> int:
    """doc-db の設定ファイルから `port` を読む。

    YAML パーサに依存せず `port` 行だけを正規表現で取り出す。
    ファイル不在・読み取り不能・`port` 未設定はいずれも既定 port を返す
    （設定不備を接続失敗として扱わず、既定で接続を試みる）。

    設定ファイルの本文は戻り値にも例外にも載せない（認証情報の非出力）。
    """
    path = DEFAULT_CONFIG_PATH if config_path is None else Path(config_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PORT
    match = _PORT_PATTERN.search(text)
    if match is None:
        return DEFAULT_PORT
    return int(match.group(1))


def endpoint_url(port: int) -> str:
    """MCP Streamable HTTP のエンドポイント URL を組み立てる。"""
    return f"http://localhost:{port}/mcp"


# --- 応答解析 -----------------------------------------------------------------


def parse_response(raw: bytes, content_type: str, expected_id=None) -> dict:
    """JSON 応答と SSE 応答のどちらでも JSON-RPC response dict へ解析する。

    どちらの形式でも同一の dict を返す（呼び出し側に形式の差は現れない）。

    SSE の場合、送信した request の `id` と一致する response を stream から選ぶ。
    Streamable HTTP はサーバ発の notification / request を、元 request の response より
    先に同一 stream へ流すことが許されている。先頭の `data:` 行を無条件に採用すると、
    先行 notification を tool の応答と誤認し、本来の response を捨てることになる。

    `expected_id` が None の場合（相関の対象を持たない呼び出し）は、
    `id` を持つ最初の response を採用する。
    """
    body = raw.decode("utf-8", errors="replace")
    if "text/event-stream" in (content_type or "").lower():
        fallback: dict | None = None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if not data:
                continue
            try:
                message = json.loads(data)
            except json.JSONDecodeError as e:
                raise ProtocolError(f"SSE の data 行を JSON として解析できません: {e}") from e
            if not isinstance(message, dict):
                continue
            if "id" not in message:
                # サーバ発の notification。応答ではないため読み飛ばす。
                continue
            if expected_id is None:
                return message
            if message.get("id") == expected_id:
                return message
            # 別 id の message はサーバ発の request（応答ではない）。
            # 一致する response が現れなかった場合の診断用にのみ保持する。
            if fallback is None:
                fallback = message
        if fallback is not None:
            raise ProtocolError(
                "SSE 応答に送信した request と一致する id の response が含まれていません"
                f"（送信 id={expected_id!r}）"
            )
        raise ProtocolError("SSE 応答に data 行が見つかりません")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"応答を JSON として解析できません: {e}") from e


# --- HTTP 送信境界 ------------------------------------------------------------


def post_json_rpc(
    url: str,
    payload: dict,
    session_id: str | None,
    timeout: float,
) -> tuple[dict | None, dict]:
    """JSON-RPC payload を POST し、`(response dict または None, 応答ヘッダ)` を返す。

    **本関数が唯一の HTTP 送信境界である。** テストはここへ応答を注入する。

    notification（`id` を持たない payload）はサーバが空 body を返すため、
    response は None になる。ヘッダ名は小文字へ正規化して返す。
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    if session_id:
        request.add_header("Mcp-Session-Id", session_id)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            raw = response.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        raise HttpError(e.code, body, url) from e
    except urllib.error.URLError as e:
        raise TransportError(f"doc-db に接続できません ({url}): {e.reason}") from e
    except OSError as e:
        raise TransportError(f"doc-db に接続できません ({url}): {e}") from e

    if not raw:
        return None, headers
    return (
        parse_response(raw, headers.get("content-type", ""), payload.get("id")),
        headers,
    )


# --- クライアント -------------------------------------------------------------


class Client:
    """MCP session を保持し、同一 session で複数の `tools/call` を発行する。

    `transport` は `post_json_rpc` と同じ signature の呼び出し可能オブジェクトで、
    テストでは応答注入用の fake に差し替える。
    """

    def __init__(
        self,
        port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport=post_json_rpc,
        config_path: Path | None = None,
    ):
        self.port = read_port(config_path) if port is None else int(port)
        self.url = endpoint_url(self.port)
        self.timeout = timeout
        self._transport = transport
        self.session_id: str | None = None
        self._next_id = 1
        # session 確立済みかは専用 flag で持つ。`session_id` の有無で判定すると、
        # session header を返さないサーバに対して call ごとに再 initialize してしまう。
        self._initialized = False

    # -- session ---------------------------------------------------------------

    def initialize(self) -> None:
        """`initialize` → `notifications/initialized` を送り、session を確立する。"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._take_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        response, headers = self._transport(self.url, payload, None, self.timeout)
        if response is None:
            raise ProtocolError("initialize が空応答を返しました")
        if "error" in response:
            raise ProtocolError(f"initialize が失敗しました: {_error_message(response['error'])}")
        self.session_id = headers.get("mcp-session-id")
        self._initialized = True
        self._transport(
            self.url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            self.session_id,
            self.timeout,
        )

    def call(self, name: str, arguments: dict) -> dict:
        """`tools/call` を発行し、tool の応答本文（JSON）を dict で返す。

        session を付けた request が HTTP 404 を返した場合は session 失効として扱い、
        session を捨てて一度だけ再確立し、同じ tool 呼び出しを再送する（下記参照）。
        """
        if not self._initialized:
            self.initialize()
        response = self._call_once(name, arguments)
        if response is None:
            raise ProtocolError(f"tools/call({name}) が空応答を返しました")
        if "error" in response:
            error = response["error"] or {}
            raise ToolError(
                _error_message(error),
                code=error.get("code") if isinstance(error, dict) else None,
                data=error.get("data") if isinstance(error, dict) else None,
            )
        return _unwrap_result(name, response.get("result") or {})

    def _call_once(self, name: str, arguments: dict) -> dict | None:
        """`tools/call` を 1 回送る。session 失効を検出した場合だけ再確立して 1 回再送する。

        Streamable HTTP では、session header を付けた request に対する HTTP 404 が
        session の終了を意味する。この場合サーバは tool を実行しておらず
        （request は session 検証の段階で拒否される）、以後も同じ session を送り続けると
        query / sync が恒久的に失敗する。したがって session を捨てて再確立し、
        同じ呼び出しを 1 回だけ再送する。

        再送は 404 かつ session 保持時に限る。他の HTTP エラー・transport エラー・
        tool エラーは再送しない（成否が確定しており、再送しても結果は変わらない）。
        再送回数を 1 回に固定するのは、失効が連続する状態を無限に再試行しないため。

        再送の副作用安全性: 本 client が扱う 4 tool のうち読み取り
        （`query` / `get_sync_status` / `list_indexes`）は再送しても副作用がない。
        `sync_documents` は 404 の時点でサーバに到達していない（job は作られていない）ため、
        再送で job が二重に作られることはない。
        """
        payload = {
            "jsonrpc": "2.0",
            "id": self._take_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response, _ = self._transport(self.url, payload, self.session_id, self.timeout)
        except HttpError as e:
            if e.status != HTTP_SESSION_EXPIRED or not self.session_id:
                raise
            self.session_id = None
            self._initialized = False
            self.initialize()
            retry_payload = dict(payload, id=self._take_id())
            response, _ = self._transport(
                self.url, retry_payload, self.session_id, self.timeout
            )
        return response

    # -- forge が使う 4 tool ---------------------------------------------------

    def query(
        self,
        key: str,
        series: str,
        query: str,
        mode: str = DEFAULT_QUERY_MODE,
        top_n: int = DEFAULT_QUERY_TOP_N,
    ) -> dict:
        """`query` tool を呼ぶ。

        `series` は doc-db 側では任意引数だが、forge は現在の branch を必ず指定する
        （他 series の削除済み・改訂前の文書を結果へ復活させないため）。
        そのため本メソッドでは必須引数にしている。
        """
        return self.call(
            "query",
            {"key": key, "series": series, "query": query, "mode": mode, "top_n": top_n},
        )

    def sync_documents(self, key: str, series: str, documents: list) -> dict:
        """`sync_documents` tool を呼ぶ（desired-state 同期の投入。`job_id` が即時返る）。"""
        return self.call(
            "sync_documents",
            {"key": key, "series": series, "documents": list(documents)},
        )

    def get_sync_status(self, job_id: str) -> dict:
        """`get_sync_status` tool を 1 回呼ぶ（ポーリングはしない）。"""
        return self.call("get_sync_status", {"job_id": job_id})

    def list_indexes(self) -> dict:
        """`list_indexes` tool を呼ぶ（KEY 一覧と各 KEY の `series[]` を得る）。"""
        return self.call("list_indexes", {})

    # -- 内部 ------------------------------------------------------------------

    def _take_id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current


def _error_message(error) -> str:
    """JSON-RPC error オブジェクトから人が読めるメッセージを取り出す。"""
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        return json.dumps(error, ensure_ascii=False, sort_keys=True)
    return str(error)


def _unwrap_result(name: str, result: dict) -> dict:
    """`tools/call` の result から tool の応答本文を取り出す。

    doc-db は `content[]` の `type == "text"` 要素に JSON を載せる。
    `structuredContent` があればそれを優先する（同一内容の構造化表現）。
    `isError` が真の場合は tool 実行エラーとして `ToolError` を投げる。
    """
    if result.get("isError"):
        raise ToolError(_text_content(result) or f"tools/call({name}) が isError を返しました")

    if "structuredContent" in result:
        structured = result["structuredContent"]
        if isinstance(structured, dict):
            return structured

    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text", "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
        if isinstance(parsed, dict):
            return parsed
        return {"text": text}
    return result


def _text_content(result: dict) -> str:
    """result の `content[]` から text 要素を連結する（エラーメッセージ用）。"""
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "\n".join(p for p in parts if p)
