#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""query_docdb.py のユニットテスト。

検証項目（DES-057 §9.1 / §9.3 の script 単体で閉じる経路）:

- path 抽出・順位維持・0 件・`Required documents:` 形式
- series 指定（未整備・0 件のいずれでも series を外した横断検索へ切り替えない）
- 実在しない path の除外と件数通知
- 対象文書 0 件の先行判定（索引側の状態確認より前）
- KEY / series 未整備の exit code 30 分類（`list_indexes` 依拠）
- ゴミ箱状態と障害の判別（`error.data.code` 正本。ADR-058）
- 初回接続成功・起動後接続成功・利用不能（exit 10 `unavailable`）の各経路
- 設定を読まないこと（責務分離。順序リストの解決は `resolve_backend_order.py`）
- MCP JSON 応答と SSE 応答（実 Client + transport 注入）

HTTP は transport 境界へ、runtime / resolver は `run()` の引数へ注入する。
実サーバ・実 git・利用者の home 設定には依存しない。

実行:
  python3 -m unittest tests.forge.doc_backend.test_query_docdb -v
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "query_docdb.py"
)

_spec = importlib.util.spec_from_file_location("doc_backend_query_docdb", _SCRIPT_PATH)
query_docdb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(query_docdb)

docdb_client = query_docdb.docdb_client
docdb_runtime = query_docdb.docdb_runtime


# --- fixture ------------------------------------------------------------------

_KEY = "sample-rules"
_SERIES = "feature/x"

#: list_indexes 応答（当該 KEY / series が登録済み）
LISTING_REGISTERED = {"indexes": [{"key": _KEY, "series": ["main", _SERIES]}]}

#: list_indexes 応答（KEY はあるが当該 series が未登録）
LISTING_SERIES_MISSING = {"indexes": [{"key": _KEY, "series": ["main"]}]}

#: list_indexes 応答（KEY 不在）
LISTING_KEY_MISSING = {"indexes": [{"key": "other-specs", "series": ["main"]}]}

#: list_indexes 応答（series が null。空集合と同義 = 未整備）
LISTING_SERIES_NULL = {"indexes": [{"key": _KEY, "series": None}]}


def _query_response(paths, warnings=None):
    response = {"results": [{"path": p, "score": 0.9} for p in paths]}
    if warnings is not None:
        response["warnings"] = warnings
    return response


def _tool_error(identifier=None, message="tool failed", code=None):
    data = {"code": identifier} if identifier else None
    return docdb_client.ToolError(message, code=code, data=data)


# --- 注入用 fake ----------------------------------------------------------------


class _FakeClient:
    """docdb_client.Client と同じ I/F で canned 応答を返す。呼び出しを記録する。"""

    def __init__(self, listing=None, query_result=None):
        self._listing = LISTING_REGISTERED if listing is None else listing
        self._query_result = _query_response([]) if query_result is None else query_result
        self.list_indexes_calls = 0
        self.query_calls = []

    def list_indexes(self):
        self.list_indexes_calls += 1
        if isinstance(self._listing, Exception):
            raise self._listing
        return self._listing

    def query(self, key, series, query, **kwargs):
        self.query_calls.append({"key": key, "series": series, "query": query, **kwargs})
        if isinstance(self._query_result, Exception):
            raise self._query_result
        return self._query_result


class _FakeAvailability:
    """docdb_runtime.Availability と同じ属性を持つ注入用の結果。"""

    def __init__(self, client=None, status="available",
                 startup=docdb_runtime.STARTUP_NOT_ATTEMPTED,
                 reason_code=None, detail=None):
        self.status = status
        self.startup = startup
        self.port = 58080
        self.url = "http://localhost:58080/mcp"
        self.reason_code = reason_code
        self.detail = detail
        self.client = client

    @property
    def available(self):
        return self.status == "available"


class _FakeDocs:
    """project_documents.ProjectDocuments と同じ属性を持つ注入用の解決結果。"""

    def __init__(self, project_root, paths, key=_KEY, series=_SERIES):
        self.project_root = Path(project_root)
        self.category = "rules"
        self.key = key
        self.series = series
        self.paths = tuple(paths)

    @property
    def count(self):
        return len(self.paths)

    @property
    def is_empty(self):
        return not self.paths


class _RefusingEnsure:
    """probe が呼ばれてはならない経路の検証用。呼ばれたら失敗させる。"""

    def __init__(self):
        self.called = False

    def __call__(self):
        self.called = True
        raise AssertionError("doc-db の probe を行ってはならない経路で ensure_available が呼ばれた")


class _Base(unittest.TestCase):
    """tempdir の project root と run() の共通呼び出しを持つ基盤。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def write_doc(self, relative):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# doc\n", encoding="utf-8")
        return relative

    def run_query(self, client=None, docs_paths=("docs/rules/a.md",),
                  availability=None, task="task", category="rules", docs=None):
        client = client if client is not None else _FakeClient()
        availability = availability or _FakeAvailability(client=client)
        docs = docs or _FakeDocs(self.root, docs_paths)
        exit_code, payload = query_docdb.run(
            category,
            task,
            self.root,
            ensure_available=lambda: availability,
            resolve_documents=lambda c, r: docs,
        )
        return exit_code, payload, client


# --- 責務分離（設定を読まないこと） ------------------------------------------------


class NoSettingsDependencyTest(unittest.TestCase):
    """本 CLI は設定・優先指定・選択順序を知らない（§2.5 の責務分離）。

    順序リストの解決（`.claude/.forge.yaml` の読み取り）は
    `resolve_backend_order.py` が担い、その分岐テストも同 CLI 側にある。
    """

    def test_does_not_import_forge_settings(self):
        import ast

        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("forge_settings", imported, "設定を読んではならない")


# --- 対象文書 0 件の先行判定 -------------------------------------------------------


class ZeroDocumentsTest(_Base):
    """0 件は索引に触れず「対象文書なし」の成功で終了する（判定順序の固定）。"""

    def test_zero_documents_succeeds_without_touching_index(self):
        # 索引側は「未整備」に見える状態にしておき、それでも参照されないことを確認
        client = _FakeClient(listing=LISTING_KEY_MISSING)
        exit_code, payload, client = self.run_query(client=client, docs_paths=())
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["document_count"], 0)
        self.assertEqual(payload["result"], "Required documents:\n")
        self.assertEqual(client.list_indexes_calls, 0)
        self.assertEqual(client.query_calls, [])
        self.assertTrue(any("対象文書" in n for n in payload["notices"]))

    def test_zero_documents_does_not_widen_search(self):
        """0 件でも series を外した横断検索へ切り替えない（query 自体を呼ばない）。"""
        exit_code, _, client = self.run_query(docs_paths=())
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(client.query_calls, [])


# --- KEY / series 未整備（exit 30） -----------------------------------------------


class IndexMissingTest(_Base):
    """未整備は exit 30。索引作成は行わず、横断検索へも切り替えない。"""

    def _assert_index_missing(self, listing, reason):
        client = _FakeClient(listing=listing)
        exit_code, payload, client = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_INDEX_MISSING)
        self.assertEqual(payload["status"], "index_missing")
        self.assertEqual(payload["reason_code"], reason)
        self.assertEqual(payload["key"], _KEY)
        self.assertEqual(payload["series"], _SERIES)
        # series を外した横断検索へ切り替えない
        self.assertEqual(client.query_calls, [])
        return payload

    def test_key_missing_is_exit_30(self):
        self._assert_index_missing(LISTING_KEY_MISSING, "key_not_found")

    def test_series_missing_is_exit_30(self):
        self._assert_index_missing(LISTING_SERIES_MISSING, "series_not_registered")

    def test_series_null_is_treated_as_empty_set(self):
        """`series: null` は空集合と同義（doc-db 側の契約）= 未整備。"""
        self._assert_index_missing(LISTING_SERIES_NULL, "series_not_registered")

    def test_key_not_found_from_query_is_exit_30(self):
        """query が KEY_NOT_FOUND を返した場合（競合等）も未整備に分類する。"""
        client = _FakeClient(query_result=_tool_error("KEY_NOT_FOUND"))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_INDEX_MISSING)
        self.assertEqual(payload["reason_code"], "key_not_found")


# --- ゴミ箱状態と障害の判別（ADR-058） ---------------------------------------------


class ErrorDiscriminationTest(_Base):
    """判別の正本は `error.data.code`。識別子を読み取れない error は障害。"""

    def test_key_trashed_is_operation_error_with_restore_guidance(self):
        client = _FakeClient(query_result=_tool_error("KEY_TRASHED"))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(payload["reason_code"], "key_trashed")
        self.assertIn("復活", payload["message"])

    def test_error_without_data_is_a_failure_not_index_missing(self):
        """`data` の無い error（0.3.3 未満・未知障害）は索引作成へ倒さない。"""
        client = _FakeClient(
            query_result=docdb_client.ToolError("internal error", code=-32603, data=None)
        )
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_tool_error")

    def test_unknown_identifier_is_a_failure(self):
        client = _FakeClient(query_result=_tool_error("KEY_LOCKED"))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_tool_error")

    def test_message_token_alone_is_not_trusted(self):
        """message 先頭トークンだけでは分岐しない（data.code が正本）。"""
        client = _FakeClient(
            query_result=docdb_client.ToolError(
                "KEY_NOT_FOUND: 文言のみで data を持たない", data=None
            )
        )
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_tool_error")

    def test_protocol_error_is_operation_error(self):
        client = _FakeClient(query_result=docdb_client.ProtocolError("empty response"))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_tool_error")

    def test_list_indexes_failure_is_operation_error(self):
        client = _FakeClient(listing=_tool_error(None, "listing failed"))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_tool_error")

    def test_malformed_query_response_is_invalid_response(self):
        client = _FakeClient(query_result={"stage_stats": {}})
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_invalid_response")

    def test_malformed_listing_is_invalid_response(self):
        client = _FakeClient(listing={"unexpected": True})
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "docdb_invalid_response")


# --- 出力構築 -----------------------------------------------------------------


class OutputConstructionTest(_Base):
    """path 抽出・順位維持・実在確認・`Required documents:` 形式。"""

    def test_paths_extracted_in_rank_order(self):
        rels = [self.write_doc(f"docs/rules/{n}.md") for n in ("b", "a", "c")]
        client = _FakeClient(query_result=_query_response(rels))
        exit_code, payload, _ = self.run_query(client=client, docs_paths=rels)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], rels)  # 順位どおり（ソートしない）
        self.assertEqual(
            payload["result"],
            "Required documents:\n\n- docs/rules/b.md\n- docs/rules/a.md\n- docs/rules/c.md\n",
        )

    def test_zero_hits_is_success_with_empty_header(self):
        exit_code, payload, client = self.run_query(
            client=_FakeClient(query_result=_query_response([]))
        )
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["result"], "Required documents:\n")
        self.assertEqual(payload["paths"], [])
        # 0 件でも再検索・横断検索を行わない（query は 1 回だけ）
        self.assertEqual(len(client.query_calls), 1)

    def test_missing_paths_are_excluded_and_counted(self):
        existing = [self.write_doc("docs/rules/a.md"), self.write_doc("docs/rules/c.md")]
        hit_paths = [existing[0], "docs/rules/deleted.md", existing[1]]
        client = _FakeClient(query_result=_query_response(hit_paths))
        exit_code, payload, _ = self.run_query(client=client, docs_paths=existing)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], existing)  # 除外後も元の順序
        self.assertEqual(payload["excluded_count"], 1)
        self.assertTrue(any("1 件" in n for n in payload["notices"]))
        self.assertNotIn("deleted.md", payload["result"])

    def test_all_paths_excluded_is_still_success(self):
        client = _FakeClient(query_result=_query_response(["docs/rules/gone.md"]))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["result"], "Required documents:\n")
        self.assertEqual(payload["excluded_count"], 1)

    def test_absolute_path_outside_root_is_excluded_even_if_it_exists(self):
        """実在する外部の絶対パスは除外する（BL-005: worktree 内に限定）。"""
        outside = tempfile.NamedTemporaryFile(suffix=".md", delete=False)
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(query_result=_query_response([outside.name, rel]))
        exit_code, payload, _ = self.run_query(client=client, docs_paths=(rel,))
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], [rel])
        self.assertEqual(payload["excluded_count"], 1)
        self.assertNotIn(outside.name, payload["result"])

    def test_parent_traversal_path_is_excluded_even_if_it_exists(self):
        """`../` で root の外の実在ファイルを指すパスは除外する。"""
        sibling_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, sibling_dir, True)
        (sibling_dir / "escape.md").write_text("# outside\n", encoding="utf-8")
        depth = len(self.root.parts) - 1
        traversal = "/".join([".."] * depth + [str(sibling_dir).lstrip("/"), "escape.md"])
        client = _FakeClient(query_result=_query_response([traversal]))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], [])
        self.assertEqual(payload["excluded_count"], 1)

    def test_symlink_escape_is_excluded_even_if_target_exists(self):
        """root 内の symlink が外の実在ファイルへ解決される場合は除外する。"""
        outside_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, outside_dir, True)
        target = outside_dir / "secret.md"
        target.write_text("# outside\n", encoding="utf-8")
        link_rel = "docs/rules/link.md"
        link_path = self.root / link_rel
        link_path.parent.mkdir(parents=True, exist_ok=True)
        link_path.symlink_to(target)
        client = _FakeClient(query_result=_query_response([link_rel]))
        exit_code, payload, _ = self.run_query(client=client)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], [])
        self.assertEqual(payload["excluded_count"], 1)

    def test_no_exclusion_no_notice(self):
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(query_result=_query_response([rel]))
        exit_code, payload, _ = self.run_query(client=client, docs_paths=(rel,))
        self.assertEqual(payload["excluded_count"], 0)
        self.assertEqual(payload["notices"], [])

    def test_warnings_are_reported_separately(self):
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(
            query_result=_query_response([rel], warnings=["index is old"])
        )
        _, payload, _ = self.run_query(client=client, docs_paths=(rel,))
        self.assertEqual(payload["warnings"], ["index is old"])
        self.assertNotIn("index is old", payload["result"])

    def test_absent_warnings_field_yields_empty_list(self):
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(query_result=_query_response([rel]))
        _, payload, _ = self.run_query(client=client, docs_paths=(rel,))
        self.assertEqual(payload["warnings"], [])

    def test_query_specifies_current_series(self):
        """query は必ず現在の branch を series として指定する。"""
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(query_result=_query_response([rel]))
        _, _, client = self.run_query(client=client, docs_paths=(rel,), task="find rules")
        self.assertEqual(len(client.query_calls), 1)
        call = client.query_calls[0]
        self.assertEqual(call["key"], _KEY)
        self.assertEqual(call["series"], _SERIES)
        self.assertEqual(call["query"], "find rules")


# --- backend 選択（接続経路） -----------------------------------------------------


class AvailabilityPathTest(_Base):
    """初回接続成功・起動後接続成功・利用不能の各経路。"""

    def test_unavailable_is_exit_10_with_runtime_reason(self):
        availability = _FakeAvailability(
            status="unavailable",
            startup=docdb_runtime.STARTUP_FAILED,
            reason_code=docdb_runtime.REASON_EXECUTABLE_MISSING,
            detail="doc-db 実行ファイルが PATH 上に見つかりません",
        )
        exit_code, payload, _ = self.run_query(availability=availability)
        self.assertEqual(exit_code, query_docdb.EXIT_UNAVAILABLE)
        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["reason_code"], docdb_runtime.REASON_EXECUTABLE_MISSING)
        self.assertEqual(payload["startup"], docdb_runtime.STARTUP_FAILED)
        self.assertEqual(payload["port"], 58080)

    def test_startup_succeeded_path_completes_query(self):
        """初回接続失敗 → 起動後接続成功の経路でも query が完了する。"""
        rel = self.write_doc("docs/rules/a.md")
        client = _FakeClient(query_result=_query_response([rel]))
        availability = _FakeAvailability(
            client=client, startup=docdb_runtime.STARTUP_SUCCEEDED
        )
        exit_code, payload, _ = self.run_query(
            client=client, docs_paths=(rel,), availability=availability
        )
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["startup"], docdb_runtime.STARTUP_SUCCEEDED)

    def test_documents_unresolved_is_operation_error(self):
        def raising_resolver(category, project_root):
            raise query_docdb.project_documents.ProjectDocumentsError("設定不備")

        exit_code, payload = query_docdb.run(
            "rules", "task", self.root,
            ensure_available=lambda: _FakeAvailability(client=_FakeClient()),
            resolve_documents=raising_resolver,
        )
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "documents_unresolved")

    def test_invalid_category_is_operation_error(self):
        exit_code, payload = query_docdb.run(
            "readme", "task", self.root, ensure_available=_RefusingEnsure(),
        )
        self.assertEqual(exit_code, query_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["reason_code"], "invalid_input")


# --- 実 Client との統合（JSON / SSE 応答注入） -------------------------------------


class RealClientIntegrationTest(_Base):
    """実 docdb_client.Client + transport 注入で query 経路を通す。

    mode=all / top_n=20 / series 指定が wire 上の arguments に載ることを検証する。
    """

    _INITIALIZE = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "serverInfo": {"name": "doc-db", "version": "0.3.3"}},
    })

    def _listing_json(self, response_id):
        return json.dumps({
            "jsonrpc": "2.0", "id": response_id,
            "result": {"content": [{
                "type": "text",
                "text": json.dumps(LISTING_REGISTERED),
            }]},
        })

    def _query_json(self, response_id, paths):
        return json.dumps({
            "jsonrpc": "2.0", "id": response_id,
            "result": {"content": [{
                "type": "text",
                "text": json.dumps(_query_response(paths)),
            }]},
        })

    class _Transport:
        def __init__(self, frames):
            self._frames = list(frames)
            self.calls = []

        def __call__(self, url, payload, session_id, timeout):
            self.calls.append(payload)
            body, content_type = self._frames.pop(0)
            if not body:
                return None, {"content-type": "application/json"}
            return (
                docdb_client.parse_response(
                    body.encode("utf-8"), content_type, payload.get("id")
                ),
                {"content-type": content_type, "mcp-session-id": "s-1"},
            )

    def _run_with_frames(self, frames, rel):
        transport = self._Transport(frames)
        client = docdb_client.Client(port=58080, transport=transport)
        availability = _FakeAvailability(client=client)
        exit_code, payload = query_docdb.run(
            "rules", "task", self.root,
            ensure_available=lambda: availability,
            resolve_documents=lambda c, r: _FakeDocs(self.root, [rel]),
        )
        return exit_code, payload, transport

    def test_json_response_path(self):
        rel = self.write_doc("docs/rules/a.md")
        json_ct = "application/json"
        frames = [
            (self._INITIALIZE, json_ct),
            ("", json_ct),
            (self._listing_json(2), json_ct),
            (self._query_json(3, [rel]), json_ct),
        ]
        exit_code, payload, transport = self._run_with_frames(frames, rel)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], [rel])
        query_call = transport.calls[-1]
        self.assertEqual(query_call["params"]["name"], "query")
        arguments = query_call["params"]["arguments"]
        self.assertEqual(arguments["series"], _SERIES)
        self.assertEqual(arguments["mode"], "all")
        self.assertEqual(arguments["top_n"], 20)

    def test_sse_response_path_is_equivalent(self):
        rel = self.write_doc("docs/rules/a.md")
        sse_ct = "text/event-stream"
        frames = [
            ("data: " + self._INITIALIZE + "\n", sse_ct),
            ("", "application/json"),
            ("data: " + self._listing_json(2) + "\n", sse_ct),
            ("data: " + self._query_json(3, [rel]) + "\n", sse_ct),
        ]
        exit_code, payload, _ = self._run_with_frames(frames, rel)
        self.assertEqual(exit_code, query_docdb.EXIT_SUCCESS)
        self.assertEqual(payload["paths"], [rel])
        self.assertEqual(payload["result"], f"Required documents:\n\n- {rel}\n")


# --- CLI 契約（probe 前に確定する経路のみ subprocess で検証） ----------------------


class CliContractTest(_Base):
    """exit code / JSON 出力の CLI 契約。実 doc-db への接続は行わない経路に限る。"""

    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_invalid_category_exits_20_not_argparse_2(self):
        result = self._run_cli("readme", "task", "--project-root", str(self.root))
        self.assertEqual(result.returncode, query_docdb.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(payload["reason_code"], "invalid_input")
        self.assertEqual(payload["backend"], "doc-db")
        self.assertEqual(payload["operation"], "query")

    def test_ignore_preference_flag_is_removed(self):
        """設定を知らない CLI に --ignore-preference は存在しない（責務分離）。"""
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                query_docdb.parse_args(["rules", "task", "--ignore-preference"])


# --- 契約定数 -----------------------------------------------------------------


class ContractConstantsTest(unittest.TestCase):
    """exit code / status が §4.4 の表どおりであること。"""

    def test_exit_codes(self):
        self.assertEqual(query_docdb.EXIT_SUCCESS, 0)
        self.assertEqual(query_docdb.EXIT_UNAVAILABLE, 10)
        self.assertEqual(query_docdb.EXIT_OPERATION_ERROR, 20)
        self.assertEqual(query_docdb.EXIT_INDEX_MISSING, 30)

    def test_status_values(self):
        self.assertEqual(query_docdb.STATUS_SUCCESS, "success")
        self.assertEqual(query_docdb.STATUS_UNAVAILABLE, "unavailable")
        self.assertEqual(query_docdb.STATUS_OPERATION_ERROR, "operation_error")
        self.assertEqual(query_docdb.STATUS_INDEX_MISSING, "index_missing")

    def test_backend_and_operation(self):
        self.assertEqual(query_docdb.BACKEND, "doc-db")
        self.assertEqual(query_docdb.OPERATION, "query")

    def test_identifier_contract_values(self):
        self.assertEqual(query_docdb.IDENTIFIER_KEY_NOT_FOUND, "KEY_NOT_FOUND")
        self.assertEqual(query_docdb.IDENTIFIER_KEY_TRASHED, "KEY_TRASHED")


if __name__ == "__main__":
    unittest.main()
