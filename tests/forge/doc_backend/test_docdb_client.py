#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docdb_client.py のユニットテスト。

検証項目は initialize、session header、JSON / SSE 応答、HTTP / tool error の区別。

応答は HTTP 送信境界（`post_json_rpc`）へ注入する。socket を開く fake server は
用いない。時計・process には依存せず、port 解決は明示パス指定で行うため、
利用者の home 設定にも実サーバにも依存しない。

実行:
  python3 -m unittest tests.forge.doc_backend.test_docdb_client -v
"""

import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "docdb_client.py"
)

_spec = importlib.util.spec_from_file_location("doc_backend_docdb_client", _SCRIPT_PATH)
docdb_client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docdb_client)


# --- 応答注入用 fixture -------------------------------------------------------

#: initialize の成功応答（JSON 形式）
INITIALIZE_RESULT_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "serverInfo": {"name": "doc-db", "version": "0.3.3"},
    },
})

#: initialize が JSON-RPC error を返した応答
INITIALIZE_ERROR_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "error": {"code": -32600, "message": "invalid protocol version"},
})

#: query tool の応答本文（content[] の text に載る JSON）
QUERY_TOOL_PAYLOAD = {
    "results": [
        {"path": "docs/rules/alpha.md", "score": 0.91},
        {"path": "docs/rules/beta.md", "score": 0.72},
    ],
    "warnings": ["index is 2 hours old"],
}

#: query の成功応答（JSON 形式）
QUERY_RESULT_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [
            {"type": "text", "text": json.dumps(QUERY_TOOL_PAYLOAD)},
        ],
    },
})

#: query の成功応答（SSE 形式）。本文は JSON 形式と同一
QUERY_RESULT_SSE = (
    "event: message\n"
    "data: " + QUERY_RESULT_JSON + "\n"
    "\n"
)

#: 先頭に空の data 行と retry 行を含む SSE（解析が最初の非空 data 行を採ること）
QUERY_RESULT_SSE_WITH_NOISE = (
    "retry: 3000\n"
    "data:\n"
    ": keep-alive comment\n"
    "data: " + QUERY_RESULT_JSON + "\n"
)

#: data 行を持たない不正な SSE
SSE_WITHOUT_DATA = "event: message\nid: 7\n\n"

#: サーバ発 notification（`id` を持たない）が response より先に流れる SSE。
#: Streamable HTTP はこの順序を許すため、先頭 data 行を無条件に採ってはならない。
SERVER_NOTIFICATION_JSON = json.dumps({
    "jsonrpc": "2.0",
    "method": "notifications/message",
    "params": {"level": "info", "data": "indexing"},
})

#: サーバ発 request（別 id を持つ）が response より先に流れる SSE
SERVER_REQUEST_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 9001,
    "method": "roots/list",
    "params": {},
})

QUERY_RESULT_SSE_AFTER_NOTIFICATION = (
    "event: message\n"
    "data: " + SERVER_NOTIFICATION_JSON + "\n"
    "\n"
    "event: message\n"
    "data: " + QUERY_RESULT_JSON + "\n"
    "\n"
)

QUERY_RESULT_SSE_AFTER_SERVER_REQUEST = (
    "event: message\n"
    "data: " + SERVER_REQUEST_JSON + "\n"
    "\n"
    "event: message\n"
    "data: " + QUERY_RESULT_JSON + "\n"
    "\n"
)

#: 一致する id の response を含まない SSE（サーバ発 request のみ）
SSE_WITHOUT_MATCHING_ID = (
    "event: message\n"
    "data: " + SERVER_REQUEST_JSON + "\n"
    "\n"
)

#: KEY 不在の tool error（JSON-RPC error 経路）。doc-db 0.3.3 の識別子契約
#: （ADR-058）に基づく実応答の形（2026-08-02 実測）。判別の正本は `error.data.code`
#: であり、`message` 先頭の識別子トークンは補助。文言全文・数値 code を判別根拠にしない。
KEY_NOT_FOUND_ERROR_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "error": {
        "code": -31001,
        "message": 'KEY_NOT_FOUND: key "sample-rules" が存在しません',
        "data": {"code": "KEY_NOT_FOUND", "key": "sample-rules"},
    },
})

#: ゴミ箱状態の tool error（JSON-RPC error 経路）。`KEY_TRASHED` は公開契約の値で
#: あるため `trash_index` を実行して採取せず、契約記述（ADR-058 / DES-057 §4.5）から
#: 書く。message の文言は公開契約ではない（契約は先頭の識別子トークンのみ）。
KEY_TRASHED_ERROR_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "error": {
        "code": -31002,
        "message": "KEY_TRASHED: 文言は公開契約ではない（先頭トークンのみ契約）",
        "data": {"code": "KEY_TRASHED", "key": "sample-rules"},
    },
})

#: 識別子を持たない tool error（JSON-RPC error だが `data` が無い）。
#: 0.3.3 未満の doc-db や未知の障害はこの形で届きうる。呼び出し側は障害として扱う
UNIDENTIFIED_ERROR_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "error": {"code": -32603, "message": "internal error"},
})

#: tool error（result.isError 経路）。識別子契約の対象外であり、障害として扱う
TOOL_IS_ERROR_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "isError": True,
        "content": [{"type": "text", "text": "tool execution failed"}],
    },
})

#: HTTP error の応答本文
HTTP_ERROR_BODY = '{"error":"session expired"}'

#: sync_documents の成功応答
SYNC_START_RESULT_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [{"type": "text", "text": json.dumps({"job_id": "job-42", "accepted": 3})}],
    },
})

#: get_sync_status の成功応答（structuredContent 経路）
SYNC_STATUS_RESULT_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "structuredContent": {
            "status": "running",
            "processed": 1,
            "skipped": 0,
            "failed": 0,
            "deleted_paths_marked": 0,
            "errors": [],
        },
    },
})

#: list_indexes の成功応答
LIST_INDEXES_RESULT_JSON = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "indexes": [{"key": "sample-rules", "series": ["main", "feature/x"]}],
            }),
        }],
    },
})

#: 設定ファイル fixture（認証情報らしき値が同居していても port だけを読むこと）
CONFIG_WITH_PORT = (
    "port: 59999\n"
    "api_key: dummy-placeholder"
    "\n"
)
CONFIG_WITHOUT_PORT = (
    "log_level: info\n"
    "api_key: dummy-placeholder"
    "\n"
)

_JSON_CT = "application/json"
_SSE_CT = "text/event-stream"
_SESSION_ID = "session-abc123"


def _json_frame(body, session_id=None):
    """JSON 形式の canned 応答（wire 表現 + ヘッダ）を作る。"""
    headers = {"content-type": _JSON_CT}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return body, headers


def _sse_frame(body, session_id=None):
    """SSE 形式の canned 応答（wire 表現 + ヘッダ）を作る。"""
    headers = {"content-type": _SSE_CT}
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return body, headers


def _empty_frame():
    """notification に対する空 body 応答。"""
    return "", {"content-type": _JSON_CT}


class _InjectingTransport:
    """`post_json_rpc` と同じ signature で canned 応答を返す差し替え境界。

    canned 応答は wire 表現（本文文字列 + ヘッダ）で与え、解析は本番と同じ
    `parse_response()` に通す。これにより JSON 経路と SSE 経路の差が
    client から見て消えることを検証できる。
    要素が例外インスタンスの場合はそれを送出する（HTTP / 接続エラーの注入）。
    """

    def __init__(self, frames):
        self._frames = list(frames)
        self.calls = []

    def __call__(self, url, payload, session_id, timeout):
        self.calls.append({
            "url": url,
            "payload": payload,
            "session_id": session_id,
            "timeout": timeout,
        })
        if not self._frames:
            raise AssertionError(f"注入した応答が足りません: {payload.get('method')}")
        frame = self._frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        body, headers = frame
        if not body:
            return None, headers
        # 本番の `post_json_rpc` と同じく送信 id を渡し、id 相関も含めて検証対象にする。
        return (
            docdb_client.parse_response(
                body.encode("utf-8"), headers.get("content-type", ""), payload.get("id")
            ),
            headers,
        )


def _client(frames, **kwargs):
    """応答注入 transport を持つ Client を作る（port は固定し設定ファイルを読まない）。"""
    transport = _InjectingTransport(frames)
    client = docdb_client.Client(port=58080, transport=transport, **kwargs)
    return client, transport


def _initialize_frames():
    return [
        _json_frame(INITIALIZE_RESULT_JSON, session_id=_SESSION_ID),
        _empty_frame(),
    ]


class SseResponseCorrelationTest(unittest.TestCase):
    """SSE stream から送信 request の id に一致する response を選ぶ（先行 message を捨てない）。"""

    def test_notification_before_response_is_skipped(self):
        parsed = docdb_client.parse_response(
            QUERY_RESULT_SSE_AFTER_NOTIFICATION.encode("utf-8"), _SSE_CT, 2
        )
        self.assertEqual(parsed, json.loads(QUERY_RESULT_JSON))

    def test_server_request_with_other_id_is_skipped(self):
        parsed = docdb_client.parse_response(
            QUERY_RESULT_SSE_AFTER_SERVER_REQUEST.encode("utf-8"), _SSE_CT, 2
        )
        self.assertEqual(parsed, json.loads(QUERY_RESULT_JSON))

    def test_no_matching_id_is_protocol_error(self):
        with self.assertRaises(docdb_client.ProtocolError) as ctx:
            docdb_client.parse_response(SSE_WITHOUT_MATCHING_ID.encode("utf-8"), _SSE_CT, 2)
        self.assertIn("id", str(ctx.exception))

    def test_expected_id_none_takes_first_message_with_id(self):
        parsed = docdb_client.parse_response(
            QUERY_RESULT_SSE_AFTER_NOTIFICATION.encode("utf-8"), _SSE_CT, None
        )
        self.assertEqual(parsed, json.loads(QUERY_RESULT_JSON))

    def test_call_returns_tool_payload_despite_leading_notification(self):
        client, transport = _client(
            _initialize_frames() + [_sse_frame(QUERY_RESULT_SSE_AFTER_NOTIFICATION)]
        )
        result = client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(result, QUERY_TOOL_PAYLOAD)
        self.assertEqual(transport.calls[-1]["payload"]["method"], "tools/call")


class SessionExpiryTest(unittest.TestCase):
    """session header 付き request の HTTP 404 を session 失効として扱い、一度だけ再確立する。"""

    def _expired(self):
        return docdb_client.HttpError(
            docdb_client.HTTP_SESSION_EXPIRED, "session not found", "http://localhost:58080/mcp"
        )

    def test_expired_session_is_reinitialized_and_call_retried(self):
        client, transport = _client(
            _initialize_frames()
            + [self._expired()]
            + [
                _json_frame(INITIALIZE_RESULT_JSON, session_id="session-2"),
                _empty_frame(),
                _json_frame(QUERY_RESULT_JSON),
            ]
        )
        result = client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(result, QUERY_TOOL_PAYLOAD)
        self.assertEqual(client.session_id, "session-2")
        methods = [c["payload"].get("method") for c in transport.calls]
        self.assertEqual(
            methods,
            [
                "initialize",
                "notifications/initialized",
                "tools/call",
                "initialize",
                "notifications/initialized",
                "tools/call",
            ],
        )
        self.assertEqual(transport.calls[-1]["session_id"], "session-2")

    def test_retry_uses_a_fresh_request_id(self):
        client, transport = _client(
            _initialize_frames()
            + [self._expired()]
            + [
                _json_frame(INITIALIZE_RESULT_JSON, session_id="session-2"),
                _empty_frame(),
                _json_frame(QUERY_RESULT_JSON),
            ]
        )
        client.query(key="sample-rules", series="main", query="task")
        tool_calls = [c for c in transport.calls if c["payload"].get("method") == "tools/call"]
        self.assertEqual(len(tool_calls), 2)
        self.assertNotEqual(tool_calls[0]["payload"]["id"], tool_calls[1]["payload"]["id"])

    def test_404_without_session_is_not_retried(self):
        client, transport = _client(
            [
                _json_frame(INITIALIZE_RESULT_JSON),  # session header を返さないサーバ
                _empty_frame(),
                self._expired(),
            ]
        )
        with self.assertRaises(docdb_client.HttpError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(ctx.exception.status, docdb_client.HTTP_SESSION_EXPIRED)
        methods = [c["payload"].get("method") for c in transport.calls]
        self.assertEqual(methods.count("tools/call"), 1)

    def test_second_expiry_is_not_retried_again(self):
        client, transport = _client(
            _initialize_frames()
            + [self._expired()]
            + [
                _json_frame(INITIALIZE_RESULT_JSON, session_id="session-2"),
                _empty_frame(),
                self._expired(),
            ]
        )
        with self.assertRaises(docdb_client.HttpError):
            client.query(key="sample-rules", series="main", query="task")
        methods = [c["payload"].get("method") for c in transport.calls]
        self.assertEqual(methods.count("tools/call"), 2)

    def test_non_404_http_error_is_not_retried(self):
        client, transport = _client(
            _initialize_frames()
            + [docdb_client.HttpError(500, "boom", "http://localhost:58080/mcp")]
        )
        with self.assertRaises(docdb_client.HttpError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(ctx.exception.status, 500)
        methods = [c["payload"].get("method") for c in transport.calls]
        self.assertEqual(methods.count("tools/call"), 1)


class ReadPortTest(unittest.TestCase):
    """port 解決は明示パスで行い、利用者の home 設定に依存しない。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._tmp = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name, content):
        path = self._tmp / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_port_read_from_config(self):
        path = self._write("with_port.yaml", CONFIG_WITH_PORT)
        self.assertEqual(docdb_client.read_port(path), 59999)

    def test_default_port_when_config_missing(self):
        missing = self._tmp / "does_not_exist.yaml"
        self.assertEqual(docdb_client.read_port(missing), docdb_client.DEFAULT_PORT)

    def test_default_port_when_port_key_absent(self):
        path = self._write("no_port.yaml", CONFIG_WITHOUT_PORT)
        self.assertEqual(docdb_client.read_port(path), docdb_client.DEFAULT_PORT)

    def test_default_port_when_config_unreadable(self):
        with mock.patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            self.assertEqual(docdb_client.read_port(Path("/unused.yaml")), docdb_client.DEFAULT_PORT)

    def test_config_secrets_are_not_returned(self):
        """設定ファイルに認証情報らしき値があっても、返るのは port（整数）だけ。"""
        path = self._write("with_port.yaml", CONFIG_WITH_PORT)
        port = docdb_client.read_port(path)
        self.assertIsInstance(port, int)
        self.assertNotIn("dummy-placeholder", str(port))

    def test_endpoint_url_uses_localhost_and_mcp_path(self):
        self.assertEqual(docdb_client.endpoint_url(1234), "http://localhost:1234/mcp")


class CommunicationConstantsTest(unittest.TestCase):
    """通信定数が設計値どおりであること。"""

    def test_operation_constants(self):
        self.assertEqual(docdb_client.DEFAULT_PORT, 58080)
        self.assertEqual(docdb_client.DEFAULT_TIMEOUT_SECONDS, 600)
        self.assertEqual(docdb_client.SYNC_WAIT_LIMIT_SECONDS, 600)
        self.assertEqual(docdb_client.SYNC_POLL_INTERVAL_SECONDS, 2.0)

    def test_probe_constants(self):
        self.assertEqual(docdb_client.PROBE_TIMEOUT_SECONDS, 1)
        self.assertEqual(docdb_client.STARTUP_DEADLINE_SECONDS, 10)
        self.assertEqual(docdb_client.STARTUP_RETRY_INTERVAL_SECONDS, 0.25)

    def test_query_defaults(self):
        self.assertEqual(docdb_client.DEFAULT_QUERY_MODE, "all")
        self.assertEqual(docdb_client.DEFAULT_QUERY_TOP_N, 20)


class ParseResponseTest(unittest.TestCase):
    """JSON / SSE の両形式が同一の JSON-RPC dict へ解析されること。"""

    def test_json_and_sse_produce_identical_dict(self):
        from_json = docdb_client.parse_response(QUERY_RESULT_JSON.encode("utf-8"), _JSON_CT)
        from_sse = docdb_client.parse_response(QUERY_RESULT_SSE.encode("utf-8"), _SSE_CT)
        self.assertEqual(from_json, from_sse)

    def test_sse_skips_empty_data_and_comment_lines(self):
        parsed = docdb_client.parse_response(QUERY_RESULT_SSE_WITH_NOISE.encode("utf-8"), _SSE_CT)
        self.assertEqual(parsed, json.loads(QUERY_RESULT_JSON))

    def test_sse_content_type_with_charset_is_recognized(self):
        parsed = docdb_client.parse_response(
            QUERY_RESULT_SSE.encode("utf-8"), "text/event-stream; charset=utf-8"
        )
        self.assertEqual(parsed, json.loads(QUERY_RESULT_JSON))

    def test_sse_without_data_line_is_protocol_error(self):
        with self.assertRaises(docdb_client.ProtocolError):
            docdb_client.parse_response(SSE_WITHOUT_DATA.encode("utf-8"), _SSE_CT)

    def test_broken_json_is_protocol_error(self):
        with self.assertRaises(docdb_client.ProtocolError):
            docdb_client.parse_response(b"not json at all", _JSON_CT)

    def test_broken_sse_data_json_is_protocol_error(self):
        with self.assertRaises(docdb_client.ProtocolError):
            docdb_client.parse_response(b"data: {broken\n", _SSE_CT)


class InitializeTest(unittest.TestCase):
    """initialize の送信順序と session header の保持。"""

    def test_sends_initialize_then_initialized_notification(self):
        client, transport = _client(_initialize_frames())
        client.initialize()

        methods = [call["payload"]["method"] for call in transport.calls]
        self.assertEqual(methods, ["initialize", "notifications/initialized"])

        init_payload = transport.calls[0]["payload"]
        self.assertEqual(init_payload["jsonrpc"], "2.0")
        self.assertEqual(init_payload["params"]["protocolVersion"], docdb_client.PROTOCOL_VERSION)
        self.assertIn("clientInfo", init_payload["params"])
        self.assertIsNone(transport.calls[0]["session_id"])
        # notification は id を持たない
        self.assertNotIn("id", transport.calls[1]["payload"])

    def test_session_id_captured_from_response_header(self):
        client, _ = _client(_initialize_frames())
        client.initialize()
        self.assertEqual(client.session_id, _SESSION_ID)

    def test_session_id_sent_on_initialized_notification_and_tool_call(self):
        frames = _initialize_frames() + [_json_frame(QUERY_RESULT_JSON)]
        client, transport = _client(frames)
        client.query(key="sample-rules", series="main", query="task")

        self.assertEqual(transport.calls[1]["session_id"], _SESSION_ID)
        self.assertEqual(transport.calls[2]["session_id"], _SESSION_ID)

    def test_session_reused_across_multiple_tool_calls(self):
        frames = _initialize_frames() + [
            _json_frame(QUERY_RESULT_JSON),
            _json_frame(LIST_INDEXES_RESULT_JSON),
        ]
        client, transport = _client(frames)
        client.query(key="sample-rules", series="main", query="task")
        client.list_indexes()

        methods = [call["payload"]["method"] for call in transport.calls]
        self.assertEqual(
            methods,
            ["initialize", "notifications/initialized", "tools/call", "tools/call"],
        )
        self.assertEqual({call["session_id"] for call in transport.calls[1:]}, {_SESSION_ID})

    def test_request_ids_are_monotonic(self):
        frames = _initialize_frames() + [
            _json_frame(QUERY_RESULT_JSON),
            _json_frame(LIST_INDEXES_RESULT_JSON),
        ]
        client, transport = _client(frames)
        client.query(key="sample-rules", series="main", query="task")
        client.list_indexes()

        ids = [call["payload"]["id"] for call in transport.calls if "id" in call["payload"]]
        self.assertEqual(ids, [1, 2, 3])

    def test_call_initializes_session_lazily(self):
        frames = _initialize_frames() + [_json_frame(LIST_INDEXES_RESULT_JSON)]
        client, transport = _client(frames)
        self.assertIsNone(client.session_id)
        client.list_indexes()
        self.assertEqual(transport.calls[0]["payload"]["method"], "initialize")

    def test_initialize_error_response_is_protocol_error(self):
        client, _ = _client([_json_frame(INITIALIZE_ERROR_JSON)])
        with self.assertRaises(docdb_client.ProtocolError):
            client.initialize()

    def test_initialize_empty_response_is_protocol_error(self):
        client, _ = _client([_empty_frame()])
        with self.assertRaises(docdb_client.ProtocolError):
            client.initialize()

    def test_session_id_absent_header_leaves_session_none_but_call_proceeds(self):
        """サーバが session header を返さない場合も operation は続行する。"""
        frames = [
            _json_frame(INITIALIZE_RESULT_JSON),
            _empty_frame(),
            _json_frame(QUERY_RESULT_JSON),
        ]
        client, transport = _client(frames)
        client.initialize()
        self.assertIsNone(client.session_id)
        result = client.call("query", {})
        self.assertEqual(result, QUERY_TOOL_PAYLOAD)
        self.assertIsNone(transport.calls[2]["session_id"])
        # session header が無くても再 initialize しないこと
        methods = [call["payload"]["method"] for call in transport.calls]
        self.assertEqual(
            methods, ["initialize", "notifications/initialized", "tools/call"]
        )

    def test_timeout_is_passed_to_transport(self):
        client, transport = _client(_initialize_frames(), timeout=1)
        client.initialize()
        self.assertEqual([call["timeout"] for call in transport.calls], [1, 1])


class ResponseFormatEquivalenceTest(unittest.TestCase):
    """JSON 応答と SSE 応答が client から見て同一結果になること。"""

    def test_query_result_identical_for_json_and_sse(self):
        json_client, _ = _client(_initialize_frames() + [_json_frame(QUERY_RESULT_JSON)])
        sse_client, _ = _client([
            _sse_frame(
                "data: " + INITIALIZE_RESULT_JSON + "\n", session_id=_SESSION_ID
            ),
            _empty_frame(),
            _sse_frame(QUERY_RESULT_SSE),
        ])

        from_json = json_client.query(key="sample-rules", series="main", query="task")
        from_sse = sse_client.query(key="sample-rules", series="main", query="task")

        self.assertEqual(from_json, from_sse)
        self.assertEqual(from_json, QUERY_TOOL_PAYLOAD)
        self.assertEqual(from_json["results"][0]["path"], "docs/rules/alpha.md")


class ToolErrorTest(unittest.TestCase):
    """tool error が HTTP error と区別して返り、error の各要素が保持されること。"""

    def test_jsonrpc_error_raises_tool_error_with_wire_error_preserved(self):
        """message / code / data が wire の error オブジェクトのまま保持されること。

        比較対象は fixture の値そのもの（透過性の検証）であり、数値 code・文言の
        特定の値を doc-db の契約として固定するものではない。
        """
        client, _ = _client(_initialize_frames() + [_json_frame(KEY_NOT_FOUND_ERROR_JSON)])
        with self.assertRaises(docdb_client.ToolError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        wire_error = json.loads(KEY_NOT_FOUND_ERROR_JSON)["error"]
        self.assertEqual(ctx.exception.message, wire_error["message"])
        self.assertEqual(ctx.exception.code, wire_error["code"])
        self.assertEqual(ctx.exception.data, wire_error["data"])

    def test_tool_error_is_not_http_error(self):
        client, _ = _client(_initialize_frames() + [_json_frame(KEY_NOT_FOUND_ERROR_JSON)])
        with self.assertRaises(docdb_client.ToolError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertNotIsInstance(ctx.exception, docdb_client.HttpError)
        self.assertNotIsInstance(ctx.exception, docdb_client.TransportError)

    def test_is_error_result_raises_tool_error_with_text_message(self):
        client, _ = _client(_initialize_frames() + [_json_frame(TOOL_IS_ERROR_JSON)])
        with self.assertRaises(docdb_client.ToolError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertIn("tool execution failed", ctx.exception.message)

    def test_tool_error_delivered_over_sse_is_also_tool_error(self):
        client, _ = _client(_initialize_frames() + [
            _sse_frame("data: " + KEY_NOT_FOUND_ERROR_JSON + "\n"),
        ])
        with self.assertRaises(docdb_client.ToolError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(ctx.exception.data["code"], "KEY_NOT_FOUND")

    def test_empty_tool_call_response_is_protocol_error(self):
        client, _ = _client(_initialize_frames() + [_empty_frame()])
        with self.assertRaises(docdb_client.ProtocolError):
            client.query(key="sample-rules", series="main", query="task")


class ErrorIdentifierContractTest(unittest.TestCase):
    """doc-db 0.3.3 の error 識別子契約（ADR-058 / DES-057 §4.5）。

    判別の正本は `ToolError.data["code"]`（`KEY_NOT_FOUND` / `KEY_TRASHED`）であり、
    `message` 先頭の識別子トークンは補助。メッセージ文言の全文・数値 code では
    判別しない。識別子を読み取れない error は呼び出し側が障害として扱う。
    """

    def _tool_error(self, frame):
        client, _ = _client(_initialize_frames() + [frame])
        with self.assertRaises(docdb_client.ToolError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        return ctx.exception

    def test_key_not_found_identifier_is_readable_from_data_code(self):
        exc = self._tool_error(_json_frame(KEY_NOT_FOUND_ERROR_JSON))
        self.assertEqual(exc.data["code"], "KEY_NOT_FOUND")

    def test_key_trashed_identifier_is_readable_from_data_code(self):
        exc = self._tool_error(_json_frame(KEY_TRASHED_ERROR_JSON))
        self.assertEqual(exc.data["code"], "KEY_TRASHED")

    def test_message_leading_token_matches_data_code(self):
        """補助識別子: message は `data.code` と同一の識別子トークンで始まる。

        契約はトークンのみであり、トークン以降の文言には依拠しない。
        """
        for fixture, identifier in (
            (KEY_NOT_FOUND_ERROR_JSON, "KEY_NOT_FOUND"),
            (KEY_TRASHED_ERROR_JSON, "KEY_TRASHED"),
        ):
            with self.subTest(identifier=identifier):
                exc = self._tool_error(_json_frame(fixture))
                self.assertTrue(exc.message.startswith(identifier + ":"))
                self.assertEqual(exc.data["code"], identifier)

    def test_identifier_is_readable_over_sse(self):
        exc = self._tool_error(_sse_frame("data: " + KEY_NOT_FOUND_ERROR_JSON + "\n"))
        self.assertEqual(exc.data["code"], "KEY_NOT_FOUND")

    def test_error_without_data_has_none_data(self):
        """識別子を持たない error（0.3.3 未満・未知障害）は `data` が None のまま届く。

        呼び出し側はこれを判別不能とみなし、障害として扱う（索引作成へ倒さない）。
        """
        exc = self._tool_error(_json_frame(UNIDENTIFIED_ERROR_JSON))
        self.assertIsNone(exc.data)

    def test_is_error_result_has_no_identifier(self):
        """result.isError 経路には識別子が無い（`data` / `code` とも None）。

        識別子契約の対象外であり、呼び出し側は障害として扱う。
        """
        exc = self._tool_error(_json_frame(TOOL_IS_ERROR_JSON))
        self.assertIsNone(exc.data)
        self.assertIsNone(exc.code)


class HttpErrorTest(unittest.TestCase):
    """HTTP error / 接続エラーが tool error と区別して返ること。"""

    def test_http_error_propagates_with_status_and_body(self):
        injected = docdb_client.HttpError(400, HTTP_ERROR_BODY, "http://localhost:58080/mcp")
        client, _ = _client(_initialize_frames() + [injected])
        with self.assertRaises(docdb_client.HttpError) as ctx:
            client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("session expired", ctx.exception.body)
        self.assertNotIsInstance(ctx.exception, docdb_client.ToolError)

    def test_transport_error_propagates(self):
        injected = docdb_client.TransportError("doc-db に接続できません")
        client, _ = _client([injected])
        with self.assertRaises(docdb_client.TransportError) as ctx:
            client.initialize()
        self.assertNotIsInstance(ctx.exception, docdb_client.HttpError)

    def test_all_errors_share_the_client_error_base(self):
        for exc in (
            docdb_client.TransportError("x"),
            docdb_client.HttpError(500, "b", "u"),
            docdb_client.ProtocolError("x"),
            docdb_client.ToolError("x"),
        ):
            self.assertIsInstance(exc, docdb_client.DocDbClientError)


class PostJsonRpcTest(unittest.TestCase):
    """HTTP 送信境界そのものの検証（urlopen を差し替え、socket は開かない）。"""

    def _fake_response(self, body, headers):
        class _Response:
            def __init__(self):
                self.headers = headers

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *args):
                return False

            def read(self_inner):
                return body.encode("utf-8")

        return _Response()

    def test_request_headers_include_accept_content_type_and_session(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            captured["timeout"] = timeout
            return self._fake_response(
                QUERY_RESULT_JSON, {"Content-Type": _JSON_CT, "Mcp-Session-Id": _SESSION_ID}
            )

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            response, headers = docdb_client.post_json_rpc(
                "http://localhost:58080/mcp",
                {"jsonrpc": "2.0", "id": 1, "method": "tools/call"},
                _SESSION_ID,
                7,
            )

        request = captured["request"]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(
            request.get_header("Accept"), "application/json, text/event-stream"
        )
        self.assertEqual(request.get_header("Mcp-session-id"), _SESSION_ID)
        self.assertEqual(captured["timeout"], 7)
        self.assertEqual(response, json.loads(QUERY_RESULT_JSON))
        self.assertEqual(headers["mcp-session-id"], _SESSION_ID)

    def test_session_header_omitted_when_no_session(self):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["request"] = request
            return self._fake_response(INITIALIZE_RESULT_JSON, {"Content-Type": _JSON_CT})

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            docdb_client.post_json_rpc(
                "http://localhost:58080/mcp", {"jsonrpc": "2.0", "id": 1}, None, 1
            )

        self.assertIsNone(captured["request"].get_header("Mcp-session-id"))

    def test_empty_body_returns_none_response(self):
        def fake_urlopen(request, timeout=None):
            return self._fake_response("", {"Content-Type": _JSON_CT})

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            response, headers = docdb_client.post_json_rpc(
                "http://localhost:58080/mcp",
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                _SESSION_ID,
                1,
            )
        self.assertIsNone(response)
        self.assertEqual(headers["content-type"], _JSON_CT)

    def test_sse_body_is_parsed(self):
        def fake_urlopen(request, timeout=None):
            return self._fake_response(QUERY_RESULT_SSE, {"Content-Type": _SSE_CT})

        # 送信 id は fixture の response id と一致させる（サーバは request の id をエコーする）。
        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            response, _ = docdb_client.post_json_rpc(
                "http://localhost:58080/mcp", {"jsonrpc": "2.0", "id": 2}, None, 1
            )
        self.assertEqual(response, json.loads(QUERY_RESULT_JSON))

    def test_http_error_becomes_http_error(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.HTTPError(
                "http://localhost:58080/mcp", 404, "Not Found", {},
                io.BytesIO(HTTP_ERROR_BODY.encode("utf-8")),
            )

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(docdb_client.HttpError) as ctx:
                docdb_client.post_json_rpc(
                    "http://localhost:58080/mcp", {"jsonrpc": "2.0", "id": 1}, None, 1
                )
        self.assertEqual(ctx.exception.status, 404)
        self.assertIn("session expired", ctx.exception.body)

    def test_url_error_becomes_transport_error(self):
        def fake_urlopen(request, timeout=None):
            raise urllib.error.URLError("Connection refused")

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(docdb_client.TransportError) as ctx:
                docdb_client.post_json_rpc(
                    "http://localhost:58080/mcp", {"jsonrpc": "2.0", "id": 1}, None, 1
                )
        self.assertIn("http://localhost:58080/mcp", str(ctx.exception))

    def test_os_error_becomes_transport_error(self):
        def fake_urlopen(request, timeout=None):
            raise OSError("socket closed")

        with mock.patch.object(docdb_client.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(docdb_client.TransportError):
                docdb_client.post_json_rpc(
                    "http://localhost:58080/mcp", {"jsonrpc": "2.0", "id": 1}, None, 1
                )


class ToolContractTest(unittest.TestCase):
    """forge が使う 4 tool のリクエスト構築と応答取り出し。"""

    def _arguments_of_last_call(self, transport):
        return transport.calls[-1]["payload"]["params"]["arguments"]

    def _name_of_last_call(self, transport):
        return transport.calls[-1]["payload"]["params"]["name"]

    def test_query_request_arguments(self):
        client, transport = _client(_initialize_frames() + [_json_frame(QUERY_RESULT_JSON)])
        client.query(key="sample-rules", series="feature/x", query="review rules")

        self.assertEqual(self._name_of_last_call(transport), "query")
        self.assertEqual(
            self._arguments_of_last_call(transport),
            {
                "key": "sample-rules",
                "series": "feature/x",
                "query": "review rules",
                "mode": "all",
                "top_n": 20,
            },
        )

    def test_query_series_is_required(self):
        client, _ = _client(_initialize_frames() + [_json_frame(QUERY_RESULT_JSON)])
        with self.assertRaises(TypeError):
            client.query(key="sample-rules", query="review rules")

    def test_query_returns_results_and_warnings(self):
        client, _ = _client(_initialize_frames() + [_json_frame(QUERY_RESULT_JSON)])
        result = client.query(key="sample-rules", series="main", query="task")
        self.assertEqual(
            [entry["path"] for entry in result["results"]],
            ["docs/rules/alpha.md", "docs/rules/beta.md"],
        )
        self.assertEqual(result["warnings"], ["index is 2 hours old"])

    def test_sync_documents_request_and_job_id(self):
        client, transport = _client(_initialize_frames() + [_json_frame(SYNC_START_RESULT_JSON)])
        documents = [{"path": "docs/rules/alpha.md", "local_path": "/repo/docs/rules/alpha.md"}]
        result = client.sync_documents("sample-rules", "main", documents)

        self.assertEqual(self._name_of_last_call(transport), "sync_documents")
        self.assertEqual(
            self._arguments_of_last_call(transport),
            {"key": "sample-rules", "series": "main", "documents": documents},
        )
        self.assertEqual(result["job_id"], "job-42")

    def test_get_sync_status_request_and_structured_content(self):
        client, transport = _client(_initialize_frames() + [_json_frame(SYNC_STATUS_RESULT_JSON)])
        result = client.get_sync_status("job-42")

        self.assertEqual(self._name_of_last_call(transport), "get_sync_status")
        self.assertEqual(self._arguments_of_last_call(transport), {"job_id": "job-42"})
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["processed"], 1)

    def test_list_indexes_request_and_series(self):
        client, transport = _client(_initialize_frames() + [_json_frame(LIST_INDEXES_RESULT_JSON)])
        result = client.list_indexes()

        self.assertEqual(self._name_of_last_call(transport), "list_indexes")
        self.assertEqual(self._arguments_of_last_call(transport), {})
        self.assertEqual(result["indexes"][0]["series"], ["main", "feature/x"])

    def test_only_the_four_supported_tools_are_exposed(self):
        for removed in ("upsert_documents", "upsert_batch", "delete_series", "trash_index"):
            self.assertFalse(
                hasattr(docdb_client.Client, removed),
                f"{removed} は forge では使用しない",
            )

    def test_non_json_text_content_is_wrapped(self):
        response = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "plain message"}]},
        })
        client, _ = _client(_initialize_frames() + [_json_frame(response)])
        result = client.call("query", {})
        self.assertEqual(result, {"text": "plain message"})

    def test_result_without_content_is_returned_as_is(self):
        response = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"ok": True}})
        client, _ = _client(_initialize_frames() + [_json_frame(response)])
        self.assertEqual(client.call("query", {}), {"ok": True})


class NoCredentialHandlingTest(unittest.TestCase):
    """認証情報を読む処理・出力する処理を持たないこと。"""

    def test_module_source_has_no_credential_reads(self):
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        code_lines = [
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ]
        code = "\n".join(code_lines).lower()
        for forbidden in ("api_key", "apikey", "token", "password", "secret", "authorization"):
            self.assertNotIn(forbidden, code, f"認証情報の取り扱いが混入している: {forbidden}")

    def test_port_pattern_matches_only_port_lines(self):
        self.assertIsNone(docdb_client._PORT_PATTERN.search("export_port: 1234\n"))
        self.assertIsNotNone(docdb_client._PORT_PATTERN.search("  port: 1234\n"))


if __name__ == "__main__":
    unittest.main()
