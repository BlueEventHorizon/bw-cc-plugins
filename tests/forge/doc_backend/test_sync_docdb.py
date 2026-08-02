#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sync_docdb.py のユニットテスト。

検証項目（設計の単体テスト表の該当行）:

- desired state（一覧全体を `{path, local_path}` で投入する）
- 削除追従入力（一覧に無い文書を desired state に含めない = 現在の一覧だけを渡す）
- 0 件防御（同期せず明示エラー。doc-db に触れない）
- `--start` の job_id 返却（即時に返り、状態取得を行わない）
- `--status` の単発取得（1 回だけ問い合わせ、未完了でも exit 0 / 成功）
- 設定を読まないこと（責務分離。順序リストの解決は `resolve_backend_order.py`）
- プロセス内にポーリングループを持たないこと（静的検証）

doc-db・git・利用者の home 設定には依存しない。doc-db 利用可否（`ensure=`）と
対象文書解決（`resolve=`）は注入 fixture で閉じる。

実行:
  python3 -m unittest tests.forge.doc_backend.test_sync_docdb -v
"""

import ast
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "sync_docdb.py"
)

_spec = importlib.util.spec_from_file_location("doc_backend_sync_docdb", _SCRIPT_PATH)
sync_docdb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_docdb)

docdb_client = sync_docdb.docdb_client
docdb_runtime = sync_docdb.docdb_runtime
project_documents = sync_docdb.project_documents


# --- 注入用 fixture -------------------------------------------------------------


class _FakeDocuments:
    """`project_documents.ProjectDocuments` と同じ属性契約の fixture。"""

    def __init__(self, paths, key="proj-rules", series="feature/x", category="rules"):
        self.category = category
        self.key = key
        self.series = series
        self.paths = tuple(paths)
        self.project_root = Path("/proj")

    @property
    def count(self):
        return len(self.paths)

    @property
    def is_empty(self):
        return not self.paths

    @property
    def entries(self):
        return [
            {"path": path, "local_path": str(self.project_root / path)}
            for path in self.paths
        ]


#: DES-057 §4.5 の `get_sync_status` 応答契約を満たす進捗（running）
_JOB_RUNNING = {
    "status": "running",
    "processed": 0,
    "skipped": 0,
    "failed": 0,
    "deleted_paths_marked": 0,
    "errors": [],
}


class _FakeClient:
    """doc-db 4 tool のうち sync 系 2 つを canned 応答で返す fixture。"""

    def __init__(self, sync_result=None, status_result=None, error=None):
        self.sync_result = {"job_id": "job-42"} if sync_result is None else sync_result
        self.status_result = (
            dict(_JOB_RUNNING) if status_result is None else status_result
        )
        self.error = error
        self.sync_calls = []
        self.status_calls = []

    def sync_documents(self, key, series, documents):
        self.sync_calls.append({"key": key, "series": series, "documents": documents})
        if self.error is not None:
            raise self.error
        return self.sync_result

    def get_sync_status(self, job_id):
        self.status_calls.append(job_id)
        if self.error is not None:
            raise self.error
        return self.status_result


class _RecordingEnsure:
    """`docdb_runtime.ensure_available` と同じ返り値契約の fixture。"""

    def __init__(self, availability):
        self.availability = availability
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.availability


def _available(client, startup=docdb_runtime.STARTUP_NOT_ATTEMPTED):
    return docdb_runtime.Availability(
        status=docdb_runtime.STATUS_AVAILABLE,
        startup=startup,
        port=58080,
        url="http://localhost:58080/mcp",
        client=client,
    )


def _unavailable(reason_code=docdb_runtime.REASON_EXECUTABLE_MISSING, detail="not found"):
    return docdb_runtime.Availability(
        status=docdb_runtime.STATUS_UNAVAILABLE,
        startup=docdb_runtime.STARTUP_FAILED,
        port=58080,
        url="http://localhost:58080/mcp",
        reason_code=reason_code,
        detail=detail,
    )


def _resolve_returning(documents):
    def resolve(category, project_root):
        return documents

    return resolve


PATHS = ("docs/rules/alpha.md", "docs/rules/beta.md")


# --- --start: desired state ------------------------------------------------------


class StartDesiredStateTest(unittest.TestCase):
    """一覧全体が `{path, local_path}` の desired state として 1 回で投入されること。"""

    def _start(self, documents, client=None):
        client = client or _FakeClient()
        ensure = _RecordingEnsure(_available(client))
        payload = sync_docdb.start_sync(
            "rules", Path("/proj"), resolve=_resolve_returning(documents), ensure=ensure
        )
        return payload, client

    def test_all_documents_are_submitted_as_desired_state(self):
        documents = _FakeDocuments(PATHS)
        _, client = self._start(documents)
        self.assertEqual(len(client.sync_calls), 1)
        call = client.sync_calls[0]
        self.assertEqual(call["key"], "proj-rules")
        self.assertEqual(call["series"], "feature/x")
        self.assertEqual(
            call["documents"],
            [
                {"path": "docs/rules/alpha.md", "local_path": "/proj/docs/rules/alpha.md"},
                {"path": "docs/rules/beta.md", "local_path": "/proj/docs/rules/beta.md"},
            ],
        )

    def test_deleted_documents_are_absent_from_desired_state(self):
        """削除追従は「現在の一覧だけを渡す」ことで成立する（一覧外は含めない）。"""
        documents = _FakeDocuments(("docs/rules/alpha.md",))
        _, client = self._start(documents)
        submitted = json.dumps(client.sync_calls[0]["documents"])
        self.assertNotIn("beta.md", submitted)
        self.assertEqual(len(client.sync_calls[0]["documents"]), 1)

    def test_start_returns_job_id_immediately_without_status_polling(self):
        documents = _FakeDocuments(PATHS)
        payload, client = self._start(documents)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["job_id"], "job-42")
        self.assertEqual(client.status_calls, [], "投入後に状態取得してはならない")

    def test_start_payload_contract_fields(self):
        documents = _FakeDocuments(PATHS)
        payload, _ = self._start(documents)
        self.assertEqual(payload["backend"], "doc-db")
        self.assertEqual(payload["operation"], "sync_start")
        self.assertEqual(payload["startup"], "not_attempted")
        self.assertIsNone(payload["reason_code"])
        self.assertEqual(payload["category"], "rules")
        self.assertEqual(payload["key"], "proj-rules")
        self.assertEqual(payload["series"], "feature/x")
        self.assertEqual(payload["count"], 2)

    def test_startup_value_is_taken_from_availability(self):
        client = _FakeClient()
        ensure = _RecordingEnsure(
            _available(client, startup=docdb_runtime.STARTUP_SUCCEEDED)
        )
        payload = sync_docdb.start_sync(
            "rules",
            Path("/proj"),
            resolve=_resolve_returning(_FakeDocuments(PATHS)),
            ensure=ensure,
        )
        self.assertEqual(payload["startup"], "succeeded")


# --- --start: 0 件防御と失敗経路 ---------------------------------------------------


class StartFailureTest(unittest.TestCase):
    def test_zero_documents_is_explicit_error_without_touching_docdb(self):
        ensure = _RecordingEnsure(_available(_FakeClient()))
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules",
                Path("/proj"),
                resolve=_resolve_returning(_FakeDocuments(())),
                ensure=ensure,
            )
        exc = ctx.exception
        self.assertEqual(exc.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(exc.reason_code, sync_docdb.REASON_NO_DOCUMENTS)
        self.assertEqual(ensure.calls, 0, "0 件判定は doc-db に触れる前に行う")

    def test_resolver_failure_is_operation_error_without_touching_docdb(self):
        def failing_resolve(category, project_root):
            raise project_documents.ProjectDocumentsError("設定を解決できません")

        ensure = _RecordingEnsure(_available(_FakeClient()))
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules", Path("/proj"), resolve=failing_resolve, ensure=ensure
            )
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(
            ctx.exception.reason_code, sync_docdb.REASON_DOCUMENTS_UNRESOLVED
        )
        self.assertEqual(ensure.calls, 0)

    def test_invalid_category_is_rejected_before_resolution(self):
        def must_not_be_called(category, project_root):
            raise AssertionError("resolve が呼ばれてはならない")

        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "readme",
                Path("/proj"),
                resolve=must_not_be_called,
                ensure=_RecordingEnsure(_available(_FakeClient())),
            )
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(ctx.exception.reason_code, sync_docdb.REASON_INVALID_INPUT)

    def test_unavailable_docdb_yields_exit_10_unavailable(self):
        ensure = _RecordingEnsure(_unavailable())
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules",
                Path("/proj"),
                resolve=_resolve_returning(_FakeDocuments(PATHS)),
                ensure=ensure,
            )
        exc = ctx.exception
        self.assertEqual(exc.exit_code, sync_docdb.EXIT_UNAVAILABLE)
        self.assertEqual(exc.status, sync_docdb.STATUS_UNAVAILABLE)
        self.assertEqual(exc.reason_code, docdb_runtime.REASON_EXECUTABLE_MISSING)
        self.assertEqual(exc.startup, docdb_runtime.STARTUP_FAILED)

    def test_tool_error_is_operation_error_not_fallback(self):
        client = _FakeClient(error=docdb_client.ToolError("sync failed"))
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules",
                Path("/proj"),
                resolve=_resolve_returning(_FakeDocuments(PATHS)),
                ensure=_RecordingEnsure(_available(client)),
            )
        exc = ctx.exception
        self.assertEqual(exc.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(exc.reason_code, sync_docdb.REASON_SYNC_START_FAILED)
        self.assertIn("sync failed", str(exc))

    def test_missing_job_id_is_operation_error(self):
        client = _FakeClient(sync_result={"accepted": 2})
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules",
                Path("/proj"),
                resolve=_resolve_returning(_FakeDocuments(PATHS)),
                ensure=_RecordingEnsure(_available(client)),
            )
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(ctx.exception.reason_code, sync_docdb.REASON_SYNC_START_FAILED)

    def test_http_error_detail_hides_response_body(self):
        """HTTP エラーの応答 body（秘密値を含み得る）を診断へ載せないこと。"""
        client = _FakeClient(
            error=docdb_client.HttpError(500, "secret-token=abc", "http://localhost:58080/mcp")
        )
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.start_sync(
                "rules",
                Path("/proj"),
                resolve=_resolve_returning(_FakeDocuments(PATHS)),
                ensure=_RecordingEnsure(_available(client)),
            )
        message = str(ctx.exception)
        self.assertNotIn("secret-token", message)
        self.assertIn("HTTP 500", message)


# --- --status: 単発取得 -----------------------------------------------------------


class StatusSingleShotTest(unittest.TestCase):
    def _status(self, client, job_id="job-42"):
        return sync_docdb.get_status(
            "rules", job_id, Path("/proj"), ensure=_RecordingEnsure(_available(client))
        )

    def test_status_queries_exactly_once_and_succeeds_while_running(self):
        """未完了（running）でも成功として即時に返ること（単発・非ポーリング）。"""
        client = _FakeClient(status_result=dict(_JOB_RUNNING, processed=1))
        payload = self._status(client)
        self.assertEqual(client.status_calls, ["job-42"], "問い合わせは 1 回だけ")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["job"]["status"], "running")

    def test_status_payload_contract_fields(self):
        client = _FakeClient(
            status_result={
                "status": "done",
                "processed": 3,
                "skipped": 1,
                "failed": 0,
                "deleted_paths_marked": 2,
                "errors": [],
            }
        )
        payload = self._status(client)
        self.assertEqual(payload["backend"], "doc-db")
        self.assertEqual(payload["operation"], "sync_status")
        self.assertEqual(payload["startup"], "not_attempted")
        self.assertIsNone(payload["reason_code"])
        self.assertEqual(payload["job_id"], "job-42")
        self.assertEqual(payload["job"]["deleted_paths_marked"], 2)

    def test_status_does_not_submit_documents(self):
        client = _FakeClient()
        self._status(client)
        self.assertEqual(client.sync_calls, [])

    def test_status_tool_error_is_operation_error(self):
        client = _FakeClient(error=docdb_client.ToolError("job not found"))
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            self._status(client)
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(
            ctx.exception.reason_code, sync_docdb.REASON_SYNC_STATUS_FAILED
        )

    def _assert_contract_violation(self, status_result):
        client = _FakeClient(status_result=status_result)
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            self._status(client)
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_OPERATION_ERROR)
        self.assertEqual(
            ctx.exception.reason_code, sync_docdb.REASON_SYNC_STATUS_FAILED
        )
        return ctx.exception

    def test_status_empty_response_is_operation_error(self):
        """空応答 `{}` を success として返さない（BL-004: 応答の不正は明示エラー）。"""
        self._assert_contract_violation({})

    def test_status_unknown_status_value_is_operation_error(self):
        self._assert_contract_violation(dict(_JOB_RUNNING, status="unknown"))

    def test_status_missing_count_field_is_operation_error(self):
        broken = dict(_JOB_RUNNING)
        del broken["processed"]
        self._assert_contract_violation(broken)

    def test_status_wrong_type_count_field_is_operation_error(self):
        self._assert_contract_violation(dict(_JOB_RUNNING, failed="0"))

    def test_status_missing_errors_field_is_operation_error(self):
        broken = dict(_JOB_RUNNING)
        del broken["errors"]
        self._assert_contract_violation(broken)

    def test_contract_violation_after_startup_keeps_startup_succeeded(self):
        """起動成功後の不正応答でも startup=succeeded を通知する（FNC-004）。"""
        client = _FakeClient(status_result={})
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.get_status(
                "rules",
                "job-42",
                Path("/proj"),
                ensure=_RecordingEnsure(
                    _available(client, startup=docdb_runtime.STARTUP_SUCCEEDED)
                ),
            )
        self.assertEqual(ctx.exception.startup, docdb_runtime.STARTUP_SUCCEEDED)
        self.assertEqual(
            ctx.exception.reason_code, sync_docdb.REASON_SYNC_STATUS_FAILED
        )

    def test_status_non_dict_response_is_operation_error(self):
        exc = self._assert_contract_violation(["running"])
        # 応答本文の値をメッセージへ載せない
        self.assertNotIn("running", str(exc))

    def test_status_unavailable_docdb_yields_exit_10_unavailable(self):
        with self.assertRaises(sync_docdb.SyncDocDbError) as ctx:
            sync_docdb.get_status(
                "rules",
                "job-42",
                Path("/proj"),
                ensure=_RecordingEnsure(
                    _unavailable(docdb_runtime.REASON_RECONNECT_FAILED, "timeout")
                ),
            )
        self.assertEqual(ctx.exception.exit_code, sync_docdb.EXIT_UNAVAILABLE)
        self.assertEqual(ctx.exception.status, sync_docdb.STATUS_UNAVAILABLE)
        self.assertEqual(
            ctx.exception.reason_code, docdb_runtime.REASON_RECONNECT_FAILED
        )


# --- 責務分離（設定を読まないこと） ------------------------------------------------


class NoSettingsDependencyTest(unittest.TestCase):
    """本 CLI は設定・優先指定・選択順序を知らない（責務分離）。

    順序リストの解決（`.claude/.forge.yaml` の読み取り）は
    `resolve_backend_order.py` が担い、その分岐テストも同 CLI 側にある。
    """

    def test_does_not_import_forge_settings(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("forge_settings", imported, "設定を読んではならない")


# --- CLI 契約（exit code / JSON） --------------------------------------------------


class CliContractTest(unittest.TestCase):
    """CLI の exit code / JSON 契約。doc-db に到達する前に確定する経路のみを叩く。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def write_empty_doc_structure(self):
        (self.root / "docs" / "rules").mkdir(parents=True)
        (self.root / ".doc_structure.yaml").write_text(
            "# doc_structure_version: 3.0\n\n"
            "rules:\n"
            "  root_dirs:\n"
            "    - docs/rules/\n"
            "  patterns:\n"
            '    target_glob: "**/*.md"\n'
            "    exclude: []\n",
            encoding="utf-8",
        )

    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_zero_documents_exit_20_with_no_documents(self):
        self.write_empty_doc_structure()
        result = self._run_cli("rules", "--start", "--project-root", str(self.root))
        self.assertEqual(result.returncode, sync_docdb.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(payload["reason_code"], "no_documents")
        self.assertEqual(payload["operation"], "sync_start")
        self.assertEqual(payload["startup"], "not_attempted")

    def test_ignore_preference_flag_is_removed(self):
        """設定を知らない CLI に --ignore-preference は存在しない（責務分離）。"""
        result = self._run_cli(
            "rules", "--start", "--ignore-preference", "--project-root", str(self.root)
        )
        self.assertEqual(result.returncode, 2, "argparse が未知の flag として拒否する")

    def test_invalid_category_exits_20_not_argparse_2(self):
        result = self._run_cli("readme", "--start", "--project-root", str(self.root))
        self.assertEqual(result.returncode, sync_docdb.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["reason_code"], "invalid_input")


# --- ポーリングループを持たないこと（静的検証） --------------------------------------


class NoPollingLoopTest(unittest.TestCase):
    """完了待ちを SKILL 側へ固定するため、script 内に時間待ち・反復問い合わせを持たない。"""

    def test_no_time_import_and_no_sleep_calls(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("time", imported, "ポーリングのための時間待ちを持ち込まない")

        sleep_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "sleep"
        ]
        self.assertEqual(sleep_calls, [])

    def test_no_loop_around_status_retrieval(self):
        """`get_sync_status` の呼び出しがループ（while / for）の中にないこと。"""
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        for loop in [n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.For))]:
            for node in ast.walk(loop):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(
                        node.func.attr,
                        "get_sync_status",
                        "状態取得をプロセス内ループで反復してはならない",
                    )


if __name__ == "__main__":
    unittest.main()
