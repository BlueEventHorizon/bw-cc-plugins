#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docdb_runtime.py のユニットテスト。

検証項目は接続済み、実行ファイル不在、起動成功、早期終了、再接続不能、秘密値非出力。

実サーバ・実プロセス・実行ファイル・実時間には依存しない。`shutil.which` / `Popen` /
接続 probe（`client_factory`）/ `sleep` / `now` をすべて注入で差し替え、
port 解決は明示指定または一時ディレクトリの設定ファイルで行うため、
利用者の home 設定にも依存しない。

実行:
  python3 -m unittest tests.forge.doc_backend.test_docdb_runtime -v
"""

import importlib.util
import inspect
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "docdb_runtime.py"
)

_spec = importlib.util.spec_from_file_location("doc_backend_docdb_runtime", _SCRIPT_PATH)
docdb_runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docdb_runtime)

docdb_client = docdb_runtime.docdb_client

_PORT = 58080
_EXECUTABLE = "/opt/example/bin/doc-db"

#: 設定ファイル fixture（認証情報らしき値が同居していても port だけを読むこと）
CONFIG_WITH_PORT = (
    "port: 59999\n"
    "api_key: dummy-placeholder"
    "\n"
)


# --- 注入する境界 -------------------------------------------------------------


class _Clock:
    """`sleep` で進む仮想時計（テストが実時間に依存しないための注入ポイント）。"""

    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def now(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


class _FakeProcess:
    """`Popen` の代替。`poll()` の戻り値だけを制御する。"""

    def __init__(self, exit_code=None):
        self._exit_code = exit_code
        self.poll_calls = 0

    def poll(self):
        self.poll_calls += 1
        return self._exit_code


class _FakeClient:
    """`initialize()` の成否だけを持つ `docdb_client.Client` の代替。"""

    def __init__(self, error=None):
        self.error = error
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        if self.error is not None:
            raise self.error


class _FactorySpy:
    """`client_factory` の代替。`outcomes` の順に接続の成否を返す。

    要素が None なら接続成功（`_FakeClient`）、例外インスタンスならその例外を
    `initialize()` で送出する。末尾に達したら最後の要素を繰り返す。
    """

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.timeouts = []
        self.clients = []

    def __call__(self, timeout):
        self.timeouts.append(timeout)
        outcome = self._outcomes.pop(0) if len(self._outcomes) > 1 else self._outcomes[0]
        client = _FakeClient(error=outcome)
        self.clients.append(client)
        return client

    @property
    def attempts(self):
        return len(self.timeouts)


def _refused():
    return docdb_client.TransportError(
        "doc-db に接続できません (http://localhost:58080/mcp): Connection refused"
    )


def _ensure(outcomes, *, which_result=_EXECUTABLE, spawn=None, clock=None, **kwargs):
    """`ensure_available()` を全境界注入で呼ぶ（実サーバ・実プロセス・実時間に触れない）。"""
    factory = _FactorySpy(outcomes)
    clock = clock or _Clock()
    which_calls = []

    def which(name):
        which_calls.append(name)
        return which_result

    spawn_calls = []

    def default_spawn(executable):
        spawn_calls.append(executable)
        return _FakeProcess()

    spawn_fn = spawn
    if spawn_fn is None:
        spawn_fn = default_spawn
    else:
        original = spawn_fn

        def spawn_fn(executable, _original=original):  # noqa: F811
            spawn_calls.append(executable)
            return _original(executable)

    result = docdb_runtime.ensure_available(
        port=_PORT,
        client_factory=factory,
        which=which,
        spawn=spawn_fn,
        sleep=clock.sleep,
        now=clock.now,
        **kwargs,
    )
    return result, {
        "factory": factory,
        "clock": clock,
        "which_calls": which_calls,
        "spawn_calls": spawn_calls,
    }


# --- テスト -------------------------------------------------------------------


class AlreadyConnectedTest(unittest.TestCase):
    """初回接続に成功した場合、起動を試みない。"""

    def test_connected_returns_available_without_startup(self):
        result, spy = _ensure([None])
        self.assertTrue(result.available)
        self.assertEqual(result.status, docdb_runtime.STATUS_AVAILABLE)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_NOT_ATTEMPTED)
        self.assertIsNone(result.reason_code)
        self.assertEqual(spy["which_calls"], [])
        self.assertEqual(spy["spawn_calls"], [])

    def test_connected_client_is_returned_for_reuse(self):
        """probe で確立した session をそのまま operation に使えること。"""
        result, spy = _ensure([None])
        self.assertIs(result.client, spy["factory"].clients[0])
        self.assertEqual(result.client.initialize_calls, 1)

    def test_probe_uses_probe_timeout_not_operation_timeout(self):
        result, spy = _ensure([None])
        self.assertEqual(spy["factory"].timeouts, [docdb_client.PROBE_TIMEOUT_SECONDS])
        self.assertNotEqual(
            docdb_client.PROBE_TIMEOUT_SECONDS, docdb_client.DEFAULT_TIMEOUT_SECONDS
        )

    def test_port_and_url_are_reported(self):
        result, _ = _ensure([None])
        self.assertEqual(result.port, _PORT)
        self.assertEqual(result.url, docdb_client.endpoint_url(_PORT))

    def test_no_sleep_when_already_connected(self):
        _, spy = _ensure([None])
        self.assertEqual(spy["clock"].sleeps, [])


class ExecutableMissingTest(unittest.TestCase):
    """異常系 1: 実行ファイル不在。"""

    def test_reason_code_and_no_spawn(self):
        result, spy = _ensure([_refused()], which_result=None)
        self.assertFalse(result.available)
        self.assertEqual(result.reason_code, docdb_runtime.REASON_EXECUTABLE_MISSING)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_FAILED)
        self.assertEqual(spy["which_calls"], [docdb_runtime.DOCDB_EXECUTABLE])
        self.assertEqual(spy["spawn_calls"], [])

    def test_empty_which_result_is_treated_as_missing(self):
        result, _ = _ensure([_refused()], which_result="")
        self.assertEqual(result.reason_code, docdb_runtime.REASON_EXECUTABLE_MISSING)

    def test_no_client_is_returned(self):
        result, _ = _ensure([_refused()], which_result=None)
        self.assertIsNone(result.client)


class SpawnFailedTest(unittest.TestCase):
    """異常系 2: プロセス起動失敗。"""

    def test_os_error_becomes_spawn_failed(self):
        def spawn(executable):
            raise OSError("Permission denied")

        result, spy = _ensure([_refused()], spawn=spawn)
        self.assertEqual(result.reason_code, docdb_runtime.REASON_SPAWN_FAILED)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_FAILED)
        self.assertEqual(spy["spawn_calls"], [_EXECUTABLE])

    def test_spawn_failure_does_not_retry_connection(self):
        def spawn(executable):
            raise OSError("Permission denied")

        result, spy = _ensure([_refused()], spawn=spawn)
        self.assertEqual(spy["factory"].attempts, 1)
        self.assertEqual(spy["clock"].sleeps, [])


class ExitedEarlyTest(unittest.TestCase):
    """異常系 3: 起動したプロセスが接続確立前に終了した。"""

    def test_reason_code_and_exit_code_in_detail(self):
        result, _ = _ensure(
            [_refused()], spawn=lambda executable: _FakeProcess(exit_code=3)
        )
        self.assertEqual(result.reason_code, docdb_runtime.REASON_EXITED_EARLY)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_FAILED)
        self.assertIn("3", result.detail)

    def test_grace_probe_is_attempted_only_once(self):
        """自分のプロセスが無いことは確定しているため、期限いっぱい待たない。"""
        result, spy = _ensure(
            [_refused()], spawn=lambda executable: _FakeProcess(exit_code=1)
        )
        self.assertEqual(result.reason_code, docdb_runtime.REASON_EXITED_EARLY)
        # 初回 probe（起動前） + 起動後の probe + 猶予 probe の 3 回で打ち切る
        self.assertEqual(spy["factory"].attempts, 3)
        self.assertEqual(
            spy["clock"].sleeps, [docdb_client.STARTUP_RETRY_INTERVAL_SECONDS]
        )

    def test_peer_server_reachable_after_own_process_exits_is_available(self):
        """別 wrapper が起動した doc-db に接続できれば、自分のプロセスが死んでいても利用可能。"""
        result, spy = _ensure(
            [_refused(), None], spawn=lambda executable: _FakeProcess(exit_code=0)
        )
        self.assertTrue(result.available)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_SUCCEEDED)
        self.assertIsNone(result.reason_code)
        self.assertIsNotNone(result.client)


class ReconnectFailedTest(unittest.TestCase):
    """異常系 4: プロセスは生きているが期限内に接続できない。"""

    def test_reason_code_after_deadline(self):
        result, spy = _ensure([_refused()], spawn=lambda executable: _FakeProcess())
        self.assertEqual(result.reason_code, docdb_runtime.REASON_RECONNECT_FAILED)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_FAILED)
        self.assertIsNone(result.client)

    def test_retries_until_deadline_with_configured_interval(self):
        result, spy = _ensure([_refused()], spawn=lambda executable: _FakeProcess())
        clock = spy["clock"]
        self.assertTrue(all(s == docdb_client.STARTUP_RETRY_INTERVAL_SECONDS for s in clock.sleeps))
        self.assertAlmostEqual(clock.value, docdb_client.STARTUP_DEADLINE_SECONDS, places=6)
        # 起動前の初回 probe 1 回 + 起動後の probe（sleep 回数 + 1 回）
        expected_attempts = 1 + int(
            docdb_client.STARTUP_DEADLINE_SECONDS / docdb_client.STARTUP_RETRY_INTERVAL_SECONDS
        ) + 1
        self.assertEqual(spy["factory"].attempts, expected_attempts)

    def test_deadline_and_interval_are_injectable(self):
        result, spy = _ensure(
            [_refused()],
            spawn=lambda executable: _FakeProcess(),
            deadline=1.0,
            retry_interval=0.5,
        )
        self.assertEqual(result.reason_code, docdb_runtime.REASON_RECONNECT_FAILED)
        self.assertEqual(spy["clock"].sleeps, [0.5, 0.5])
        self.assertEqual(spy["factory"].attempts, 4)

    def test_startup_succeeds_after_a_few_failed_probes(self):
        result, spy = _ensure(
            [_refused(), _refused(), _refused(), None],
            spawn=lambda executable: _FakeProcess(),
        )
        self.assertTrue(result.available)
        self.assertEqual(result.startup, docdb_runtime.STARTUP_SUCCEEDED)
        self.assertEqual(spy["factory"].attempts, 4)
        self.assertEqual(len(spy["clock"].sleeps), 2)

    def test_sleep_never_exceeds_remaining_deadline(self):
        _, spy = _ensure(
            [_refused()],
            spawn=lambda executable: _FakeProcess(),
            deadline=0.6,
            retry_interval=0.25,
        )
        sleeps = spy["clock"].sleeps
        self.assertEqual(sleeps[:2], [0.25, 0.25])
        self.assertAlmostEqual(sleeps[-1], 0.1, places=6)
        self.assertLessEqual(spy["clock"].value, 0.6)


class ReasonCodeDistinctnessTest(unittest.TestCase):
    """4 つの異常系がそれぞれ固有の理由コードで返ること。"""

    def test_all_reason_codes_are_distinct(self):
        codes = [
            docdb_runtime.REASON_EXECUTABLE_MISSING,
            docdb_runtime.REASON_SPAWN_FAILED,
            docdb_runtime.REASON_EXITED_EARLY,
            docdb_runtime.REASON_RECONNECT_FAILED,
        ]
        self.assertEqual(len(set(codes)), 4)

    def test_each_failure_path_yields_its_own_code(self):
        def raising_spawn(executable):
            raise OSError("boom")

        observed = [
            _ensure([_refused()], which_result=None)[0].reason_code,
            _ensure([_refused()], spawn=raising_spawn)[0].reason_code,
            _ensure(
                [_refused()], spawn=lambda executable: _FakeProcess(exit_code=1)
            )[0].reason_code,
            _ensure([_refused()], spawn=lambda executable: _FakeProcess())[0].reason_code,
        ]
        self.assertEqual(
            observed,
            [
                docdb_runtime.REASON_EXECUTABLE_MISSING,
                docdb_runtime.REASON_SPAWN_FAILED,
                docdb_runtime.REASON_EXITED_EARLY,
                docdb_runtime.REASON_RECONNECT_FAILED,
            ],
        )


class ProbeTest(unittest.TestCase):
    """接続 probe が MCP initialize の成否だけで判定すること。"""

    def test_success_returns_client(self):
        factory = _FactorySpy([None])
        client, detail = docdb_runtime.probe(factory)
        self.assertIsNotNone(client)
        self.assertIsNone(detail)

    def test_transport_error_returns_detail(self):
        """失敗理由は分類（例外クラス名）で返る。例外メッセージの生文字列は載らない。"""
        factory = _FactorySpy([_refused()])
        client, detail = docdb_runtime.probe(factory)
        self.assertIsNone(client)
        self.assertEqual(detail, "TransportError")
        self.assertNotIn("Connection refused", detail)

    def test_http_and_protocol_errors_are_also_treated_as_not_connected(self):
        for error in (
            docdb_client.HttpError(500, "boom", "http://localhost:58080/mcp"),
            docdb_client.ProtocolError("initialize が空応答を返しました"),
        ):
            client, detail = docdb_runtime.probe(_FactorySpy([error]))
            self.assertIsNone(client)
            self.assertTrue(detail)

    def test_unexpected_exception_is_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            docdb_runtime.probe(_FactorySpy([RuntimeError("bug")]))


class SpawnServerTest(unittest.TestCase):
    """起動が新規セッション・標準入出力切り離しであり、ログファイルを作らないこと。"""

    def test_popen_kwargs(self):
        with mock.patch.object(docdb_runtime.subprocess, "Popen") as popen:
            docdb_runtime.spawn_server(_EXECUTABLE)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [_EXECUTABLE])
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertTrue(kwargs["start_new_session"])
        self.assertTrue(kwargs["close_fds"])

    def test_no_log_file_is_opened_by_forge(self):
        """forge 側でログファイルを作らない（出力先は doc-db 自身の設定に委ねる）。"""
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        # `Popen(` は許容し、単独の `open(` だけを検出する
        self.assertIsNone(re.search(r"\bopen\s*\(", code), "ファイルを開く処理が混入している")
        for forbidden in ("NamedTemporaryFile", "write_text", ".log"):
            self.assertNotIn(forbidden, code, f"ログ・ファイル生成の疑い: {forbidden}")

    def test_startup_command_takes_no_extra_arguments(self):
        """port やログ先を起動引数で上書きしない（利用者の doc-db 設定を尊重する）。"""
        with mock.patch.object(docdb_runtime.subprocess, "Popen") as popen:
            docdb_runtime.spawn_server(_EXECUTABLE)
        self.assertEqual(popen.call_args[0][0], [_EXECUTABLE])


class ConstantReuseTest(unittest.TestCase):
    """通信定数を再定義せず docdb_client のものを使うこと。"""

    def test_defaults_come_from_docdb_client(self):
        defaults = inspect.signature(docdb_runtime.ensure_available).parameters
        self.assertEqual(
            defaults["probe_timeout"].default, docdb_client.PROBE_TIMEOUT_SECONDS
        )
        self.assertEqual(defaults["deadline"].default, docdb_client.STARTUP_DEADLINE_SECONDS)
        self.assertEqual(
            defaults["retry_interval"].default, docdb_client.STARTUP_RETRY_INTERVAL_SECONDS
        )

    def test_communication_constants_are_not_redefined(self):
        for name in (
            "PROBE_TIMEOUT_SECONDS",
            "STARTUP_DEADLINE_SECONDS",
            "STARTUP_RETRY_INTERVAL_SECONDS",
            "DEFAULT_PORT",
        ):
            self.assertNotIn(
                name,
                docdb_runtime.__dict__,
                f"{name} は docdb_client の定義を使うこと",
            )


class PortResolutionTest(unittest.TestCase):
    """port 解決は docdb_client に委ね、利用者の home 設定に依存しない。"""

    def test_config_path_is_used_when_port_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "doc-db.yaml"
            config.write_text(CONFIG_WITH_PORT, encoding="utf-8")
            result = docdb_runtime.ensure_available(
                config_path=config,
                client_factory=_FactorySpy([None]),
                which=lambda name: None,
                sleep=lambda seconds: None,
                now=lambda: 0.0,
            )
        self.assertEqual(result.port, 59999)
        self.assertEqual(result.url, "http://localhost:59999/mcp")

    def test_make_client_factory_builds_client_with_given_port_and_timeout(self):
        factory = docdb_runtime.make_client_factory(_PORT, transport=lambda *a: (None, {}))
        client = factory(docdb_client.PROBE_TIMEOUT_SECONDS)
        self.assertEqual(client.port, _PORT)
        self.assertEqual(client.timeout, docdb_client.PROBE_TIMEOUT_SECONDS)
        self.assertEqual(client.url, docdb_client.endpoint_url(_PORT))


class NoCredentialHandlingTest(unittest.TestCase):
    """認証情報・環境変数値・設定本文を読まず、出力もしないこと。"""

    def _code(self):
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        return "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )

    def test_module_source_has_no_credential_reads(self):
        code = self._code().lower()
        for forbidden in ("api_key", "apikey", "token", "password", "secret", "authorization"):
            self.assertNotIn(forbidden, code, f"認証情報の取り扱いが混入している: {forbidden}")

    def test_module_source_does_not_read_environment(self):
        code = self._code()
        for forbidden in ("os.environ", "getenv", "environb"):
            self.assertNotIn(forbidden, code, f"環境変数の読み取りが混入している: {forbidden}")

    def test_failure_detail_contains_no_config_body(self):
        """設定ファイルに認証情報らしき値があっても、失敗理由に混ざらないこと。"""
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "doc-db.yaml"
            config.write_text(CONFIG_WITH_PORT, encoding="utf-8")
            result = docdb_runtime.ensure_available(
                config_path=config,
                client_factory=_FactorySpy([_refused()]),
                which=lambda name: None,
                sleep=lambda seconds: None,
                now=lambda: 0.0,
            )
        self.assertEqual(result.reason_code, docdb_runtime.REASON_EXECUTABLE_MISSING)
        for secret in ("dummy-placeholder", "api_key", str(config)):
            self.assertNotIn(secret, result.detail)

    def test_all_failure_details_are_limited_to_non_secret_facts(self):
        def raising_spawn(executable):
            raise OSError("Permission denied")

        results = [
            _ensure([_refused()], which_result=None)[0],
            _ensure([_refused()], spawn=raising_spawn)[0],
            _ensure([_refused()], spawn=lambda e: _FakeProcess(exit_code=1))[0],
            _ensure([_refused()], spawn=lambda e: _FakeProcess())[0],
        ]
        for result in results:
            for secret in ("dummy-placeholder", "api_key", "Authorization"):
                self.assertNotIn(secret, result.detail)

    def test_http_error_body_is_not_leaked_into_detail(self):
        """HTTP エラー応答の body（秘密値を含み得る）を detail に載せないこと。

        `HttpError` の例外メッセージはサーバ応答 body をそのまま含む。
        doc-db や前段の proxy が認証エラー時に body へ設定値・token を載せた場合、
        detail 経由で利用者向け出力へ流出する経路になる。
        """
        leaked = "Authorization: Bearer sk-should-not-appear"
        http_error = docdb_client.HttpError(401, leaked, "http://localhost:58080/mcp")
        self.assertIn(leaked, str(http_error))  # 例外自体には載っている（前提の確認）

        for kwargs in (
            {"which_result": None},
            {"spawn": lambda e: _FakeProcess(exit_code=1)},
            {"spawn": lambda e: _FakeProcess()},
        ):
            result, _ = _ensure([http_error], **kwargs)
            self.assertNotIn("sk-should-not-appear", result.detail)
            self.assertNotIn("Bearer", result.detail)
            self.assertNotIn("Authorization", result.detail)
            # 判別に必要な事実は残っていること
            self.assertIn("401", result.detail)

    def test_probe_detail_excludes_exception_message(self):
        """probe が返す失敗理由に例外メッセージの生文字列が入らないこと。

        注入値は秘密情報スキャナが placeholder と判定する形にしている
        （実値らしい文字列をテストへ書くと、リポジトリ全体の混入スキャンに
        検出されるため。抑止マーカーでの回避はしない）。
        """
        leaked = "Authorization: Bearer dummy-placeholder-body"
        client, detail = docdb_runtime.probe(
            _FactorySpy([docdb_client.HttpError(500, leaked, "http://localhost:58080/mcp")])
        )
        self.assertIsNone(client)
        self.assertNotIn("dummy-placeholder-body", detail)
        self.assertNotIn("Bearer", detail)
        self.assertIn("HttpError", detail)
        self.assertIn("500", detail)



if __name__ == "__main__":
    unittest.main()
