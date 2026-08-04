#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""resolve_backend_order.py のユニットテスト。

検証項目（設計の単体テスト表の該当行）:

- 未指定・ファイル不在で既定値の順序（doc-advisor 先位）
- `prefer: doc-db` / `prefer: doc-advisor` の反映
- 不正（非 mapping / 未知キー / 値域外 / 解析不能 / 読取失敗）の
  exit 20 `settings_invalid`（既定値へ落ちない）
- CLI 契約（exit code・JSON のみの出力）

設定は tempdir に実ファイルを組み立てて実 `forge_settings` を通す。
利用者の home 設定・実 doc-db には依存しない。

実行:
  python3 -m unittest tests.forge.doc_backend.test_resolve_backend_order -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "resolve_backend_order.py"
)

_spec = importlib.util.spec_from_file_location(
    "doc_backend_resolve_backend_order", _SCRIPT_PATH
)
resolve_backend_order = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve_backend_order)


class _Base(unittest.TestCase):
    """tempdir の project root と設定ファイル書き込みを持つ基盤。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def write_settings(self, content):
        claude_dir = self.root / ".claude"
        claude_dir.mkdir(exist_ok=True)
        (claude_dir / ".forge.yaml").write_text(content, encoding="utf-8")

    def assert_settings_invalid(self, exit_code, payload):
        """不正時の契約: exit 20 / settings_invalid、既定値へ落ちない。"""
        self.assertEqual(exit_code, resolve_backend_order.EXIT_OPERATION_ERROR)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(payload["reason_code"], "settings_invalid")
        self.assertIsNone(payload["order"], "不正時に既定値の順序を返してはならない")
        self.assertIsNone(payload["source"])


# --- 成功経路 -----------------------------------------------------------------


class ResolveOrderTest(_Base):
    def test_no_settings_file_yields_default_order(self):
        """ファイル不在は既定値の順序（doc-advisor 先位）。"""
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assertEqual(exit_code, resolve_backend_order.EXIT_SUCCESS)
        self.assertEqual(payload["status"], "success")
        self.assertIsNone(payload["reason_code"])
        self.assertEqual(payload["order"], ["doc-advisor", "doc-db"])
        self.assertEqual(payload["source"], "default")

    def test_no_doc_backend_section_yields_default_order(self):
        self.write_settings("other_feature:\n  bar: value\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assertEqual(exit_code, resolve_backend_order.EXIT_SUCCESS)
        self.assertEqual(payload["order"], ["doc-advisor", "doc-db"])
        self.assertEqual(payload["source"], "default")

    def test_prefer_doc_db_puts_doc_db_first(self):
        self.write_settings("doc_backend:\n  prefer: doc-db\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assertEqual(exit_code, resolve_backend_order.EXIT_SUCCESS)
        self.assertEqual(payload["order"], ["doc-db", "doc-advisor"])
        self.assertEqual(payload["source"], "setting")

    def test_prefer_doc_advisor_is_explicit_default(self):
        """`prefer: doc-advisor` は既定値の明示に過ぎない（source は setting）。"""
        self.write_settings("doc_backend:\n  prefer: doc-advisor\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assertEqual(exit_code, resolve_backend_order.EXIT_SUCCESS)
        self.assertEqual(payload["order"], ["doc-advisor", "doc-db"])
        self.assertEqual(payload["source"], "setting")

    def test_payload_contract_fields(self):
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assertEqual(exit_code, resolve_backend_order.EXIT_SUCCESS)
        self.assertEqual(payload["operation"], "resolve_backend_order")
        for field in ("status", "operation", "reason_code", "order", "source"):
            self.assertIn(field, payload)


# --- 不正（既定値へ落ちない） ------------------------------------------------------


class SettingsInvalidTest(_Base):
    def test_non_mapping_section_is_settings_invalid(self):
        self.write_settings("doc_backend: doc-advisor\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)

    def test_list_section_is_settings_invalid(self):
        self.write_settings("doc_backend:\n  - doc-advisor\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)

    def test_unknown_key_is_settings_invalid(self):
        """綴り誤り（preffer）を黙って無視しない。キー名は診断に載せる。"""
        self.write_settings("doc_backend:\n  preffer: doc-advisor\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)
        self.assertIn("preffer", payload["message"])

    def test_out_of_range_value_is_settings_invalid(self):
        """値域外（`prefer: grep`）。設定本文（値）はメッセージに載せない。"""
        self.write_settings("doc_backend:\n  prefer: grep\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)
        self.assertNotIn("grep", payload["message"])

    def test_prefer_without_value_is_settings_invalid(self):
        """`prefer:`（値なし）は値域外として扱う。"""
        self.write_settings("doc_backend:\n  prefer:\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)

    def test_unparseable_file_is_settings_invalid(self):
        """解析不能（flow style は対象外構文）も exit 20（既定値へ落ちない）。"""
        self.write_settings("doc_backend: {prefer: doc-advisor}\n")
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)

    def test_unreadable_file_is_settings_invalid(self):
        """読取失敗（`.forge.yaml` がディレクトリ等）も SettingsError = 設定不正。"""
        (self.root / ".claude" / ".forge.yaml").mkdir(parents=True)
        exit_code, payload = resolve_backend_order.run(self.root)
        self.assert_settings_invalid(exit_code, payload)


# --- CLI 契約 -----------------------------------------------------------------


class CliContractTest(_Base):
    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_default_order_exits_0_with_json_only(self):
        result = self._run_cli("--project-root", str(self.root))
        self.assertEqual(result.returncode, resolve_backend_order.EXIT_SUCCESS)
        payload = json.loads(result.stdout)  # stdout は JSON のみ
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["order"], ["doc-advisor", "doc-db"])
        self.assertEqual(payload["source"], "default")

    def test_prefer_doc_db_exits_0(self):
        self.write_settings("doc_backend:\n  prefer: doc-db\n")
        result = self._run_cli("--project-root", str(self.root))
        self.assertEqual(result.returncode, resolve_backend_order.EXIT_SUCCESS)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["order"], ["doc-db", "doc-advisor"])

    def test_invalid_settings_exits_20(self):
        self.write_settings("doc_backend:\n  preffer: doc-db\n")
        result = self._run_cli("--project-root", str(self.root))
        self.assertEqual(result.returncode, resolve_backend_order.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(payload["reason_code"], "settings_invalid")
        self.assertIsNone(payload["order"])


# --- 契約定数 -----------------------------------------------------------------


class ContractConstantsTest(unittest.TestCase):
    def test_default_order_is_doc_advisor_first(self):
        """既定値（doc-advisor 先位）の定義点は DEFAULT_ORDER の 1 箇所。"""
        self.assertEqual(
            resolve_backend_order.DEFAULT_ORDER, ("doc-advisor", "doc-db")
        )

    def test_exit_codes_and_status_values(self):
        self.assertEqual(resolve_backend_order.EXIT_SUCCESS, 0)
        self.assertEqual(resolve_backend_order.EXIT_OPERATION_ERROR, 20)
        self.assertEqual(resolve_backend_order.STATUS_SUCCESS, "success")
        self.assertEqual(
            resolve_backend_order.STATUS_OPERATION_ERROR, "operation_error"
        )
        self.assertEqual(
            resolve_backend_order.REASON_SETTINGS_INVALID, "settings_invalid"
        )
        self.assertEqual(resolve_backend_order.OPERATION, "resolve_backend_order")


if __name__ == "__main__":
    unittest.main()
