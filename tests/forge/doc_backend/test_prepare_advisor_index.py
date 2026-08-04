#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prepare_advisor_index.py のユニットテスト。

検証項目は dprint 失敗伝播、dirs / exclude 出力、設定エラー。

外部コマンド（dprint runner）は `run_command()` の 1 境界へ差し替えて注入する。
設定解決は tempdir に組み立てた `.doc_structure.yaml` に対して実 resolver を
import 委譲で使う。本リポジトリの設定・実 dprint には依存しない。

実行:
  python3 -m unittest tests.forge.doc_backend.test_prepare_advisor_index -v
"""

import ast
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "doc_backend" / "prepare_advisor_index.py"
)

_spec = importlib.util.spec_from_file_location(
    "doc_backend_prepare_advisor_index", _SCRIPT_PATH
)
prepare_advisor_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare_advisor_index)


# --- fixture ------------------------------------------------------------------

#: exclude を持つ標準的な .doc_structure.yaml
DOC_STRUCTURE_YAML = """# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  patterns:
    target_glob: "**/*.md"
    exclude: [drafts, archive]

specs:
  root_dirs:
    - "docs/specs/**/design/"
    - "docs/specs/**/requirements/"
  patterns:
    target_glob: "**/*.md"
    exclude: [plan]
"""

#: exclude を持たない（patterns なし）設定
DOC_STRUCTURE_YAML_NO_EXCLUDE = """# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
"""

#: rules だけを持つ設定（specs セクションなし。全体としては valid）
DOC_STRUCTURE_YAML_RULES_ONLY = """# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  patterns:
    target_glob: "**/*.md"
    exclude: []
"""

#: root_dirs をどこにも持たない旧フォーマット相当（validate が invalid を返す）
DOC_STRUCTURE_YAML_INVALID = """# doc_structure_version: 2.0

rules:
  patterns:
    target_glob: "**/*.md"
"""

#: dprint runner の失敗出力
DPRINT_FAILURE_STDERR = "error: Formatting failed. Had 1 error(s).\n"


# --- 注入用 runner ------------------------------------------------------------


class _RecordingRunner:
    """`run_command()` と同じ signature で canned な結果を返す差し替え境界。"""

    def __init__(self, result=(0, "", "")):
        self._result = result
        self.calls = []

    def __call__(self, args, cwd, timeout):
        self.calls.append({"args": list(args), "cwd": Path(cwd), "timeout": timeout})
        return self._result


_DPRINT_OK = (0, "", "")


class _TempProject(unittest.TestCase):
    """tempdir に project root を組み立てる共通基盤。"""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name).resolve()

    def tearDown(self):
        self._tmpdir.cleanup()

    def write_config(self, content=DOC_STRUCTURE_YAML):
        (self.root / ".doc_structure.yaml").write_text(content, encoding="utf-8")


# --- dprint 失敗伝播 ------------------------------------------------------------


class DprintFailurePropagationTest(_TempProject):
    """dprint runner の失敗が operation 失敗として伝播すること。"""

    def test_nonzero_exit_raises_with_dprint_reason_code(self):
        self.write_config()
        runner = _RecordingRunner(result=(1, "", DPRINT_FAILURE_STDERR))
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError) as ctx:
            prepare_advisor_index.prepare("rules", self.root, runner=runner)
        self.assertEqual(
            ctx.exception.reason_code, prepare_advisor_index.REASON_DPRINT_FAILED
        )
        self.assertIn("Formatting failed", str(ctx.exception))

    def test_command_unavailable_is_also_a_dprint_failure(self):
        self.write_config()
        runner = _RecordingRunner(
            result=(
                prepare_advisor_index.COMMAND_UNAVAILABLE_RETURNCODE,
                "",
                "コマンドを実行できません: bash 不在",
            )
        )
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError) as ctx:
            prepare_advisor_index.prepare("rules", self.root, runner=runner)
        self.assertEqual(
            ctx.exception.reason_code, prepare_advisor_index.REASON_DPRINT_FAILED
        )

    def test_dprint_failure_precedes_config_resolution(self):
        """dprint → 設定解決の順序（dprint 失敗時は設定不備でも dprint_failed）。"""
        # 設定ファイルを置かない = 設定解決まで進めば doc_structure_invalid になる状況
        runner = _RecordingRunner(result=(1, "", DPRINT_FAILURE_STDERR))
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError) as ctx:
            prepare_advisor_index.prepare("rules", self.root, runner=runner)
        self.assertEqual(
            ctx.exception.reason_code, prepare_advisor_index.REASON_DPRINT_FAILED
        )

    def test_runner_invocation_shape(self):
        """既存 dprint runner を bash で project root を cwd として呼ぶこと。"""
        self.write_config()
        runner = _RecordingRunner(result=_DPRINT_OK)
        prepare_advisor_index.prepare("rules", self.root, runner=runner)
        self.assertEqual(len(runner.calls), 1)
        call = runner.calls[0]
        self.assertEqual(call["args"][0], "bash")
        self.assertTrue(call["args"][1].endswith("run_dprint_fmt.sh"), call["args"][1])
        self.assertEqual(call["cwd"], self.root)
        self.assertEqual(
            call["timeout"], prepare_advisor_index.DPRINT_TIMEOUT_SECONDS
        )

    def test_dprint_script_path_points_at_shared_runner(self):
        self.assertTrue(prepare_advisor_index.DPRINT_SCRIPT.is_file())
        self.assertEqual(prepare_advisor_index.DPRINT_SCRIPT.name, "run_dprint_fmt.sh")


# --- dirs / exclude 出力 ---------------------------------------------------------


class IndexInputsOutputTest(_TempProject):
    """root_dirs / exclude が設定記載順で JSON payload に載ること。"""

    def _prepare(self, category):
        return prepare_advisor_index.prepare(
            category, self.root, runner=_RecordingRunner(result=_DPRINT_OK)
        )

    def test_rules_root_dirs_and_exclude(self):
        self.write_config()
        payload = self._prepare("rules")
        self.assertEqual(payload["root_dirs"], ["docs/rules/"])
        self.assertEqual(payload["exclude"], ["drafts", "archive"])

    def test_specs_root_dirs_keep_config_order(self):
        self.write_config()
        payload = self._prepare("specs")
        self.assertEqual(
            payload["root_dirs"],
            ["docs/specs/**/design/", "docs/specs/**/requirements/"],
        )
        self.assertEqual(payload["exclude"], ["plan"])

    def test_missing_patterns_yields_empty_exclude(self):
        self.write_config(DOC_STRUCTURE_YAML_NO_EXCLUDE)
        payload = self._prepare("rules")
        self.assertEqual(payload["root_dirs"], ["docs/rules/"])
        self.assertEqual(payload["exclude"], [])

    def test_success_payload_contract_fields(self):
        """§4.4 の共通 JSON 契約 field と §5.2 の status を満たすこと。"""
        self.write_config()
        payload = self._prepare("rules")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["backend"], "doc-advisor")
        self.assertEqual(payload["operation"], "prepare_index")
        self.assertEqual(payload["startup"], "not_attempted")
        self.assertIsNone(payload["reason_code"])
        self.assertEqual(payload["category"], "rules")
        self.assertEqual(payload["project_root"], str(self.root))

    def test_no_file_expansion_is_performed(self):
        """展開は doc-advisor 側の責務であり、payload は展開前の dirs のままであること。"""
        self.write_config()
        docs = self.root / "docs" / "rules"
        docs.mkdir(parents=True)
        (docs / "alpha.md").write_text("# a\n", encoding="utf-8")
        payload = self._prepare("rules")
        self.assertEqual(payload["root_dirs"], ["docs/rules/"])
        self.assertNotIn("docs/rules/alpha.md", json.dumps(payload))


# --- 設定エラー -----------------------------------------------------------------


class ConfigErrorTest(_TempProject):
    """設定不備・入力不正が exit 20 相当の例外になること。"""

    def _assert_error(self, category, reason_code):
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError) as ctx:
            prepare_advisor_index.prepare(
                category, self.root, runner=_RecordingRunner(result=_DPRINT_OK)
            )
        self.assertEqual(ctx.exception.reason_code, reason_code)
        return ctx.exception

    def test_missing_config_file(self):
        exc = self._assert_error(
            "rules", prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )
        self.assertIn(".doc_structure.yaml", str(exc))

    def test_invalid_config_without_root_dirs(self):
        self.write_config(DOC_STRUCTURE_YAML_INVALID)
        exc = self._assert_error(
            "rules", prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )
        self.assertIn("root_dirs", str(exc))
        self.assertIn("setup-doc-structure", str(exc))

    def test_missing_category_section(self):
        """全体は valid でも当該 category が無ければ設定エラーであること。"""
        self.write_config(DOC_STRUCTURE_YAML_RULES_ONLY)
        exc = self._assert_error(
            "specs", prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )
        self.assertIn("specs", str(exc))

    def test_unknown_category_is_invalid_input(self):
        self.write_config()
        exc = self._assert_error(
            "readme", prepare_advisor_index.REASON_INVALID_INPUT
        )
        self.assertIn("readme", str(exc))

    def test_unknown_category_is_rejected_before_running_dprint(self):
        self.write_config()
        runner = _RecordingRunner(result=_DPRINT_OK)
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError):
            prepare_advisor_index.prepare("readme", self.root, runner=runner)
        self.assertEqual(runner.calls, [])

    def test_unreadable_config_is_doc_structure_invalid(self):
        if os.geteuid() == 0:
            self.skipTest("root ではパーミッションが無視される")
        self.write_config()
        config_path = self.root / ".doc_structure.yaml"
        os.chmod(config_path, 0o000)
        try:
            self._assert_error(
                "rules", prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
            )
        finally:
            os.chmod(config_path, 0o600)

    def test_non_utf8_config_is_doc_structure_invalid(self):
        (self.root / ".doc_structure.yaml").write_bytes(b"\xff\xfe\x00rules:\n")
        self._assert_error(
            "rules", prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )

    def test_nonexistent_project_root_is_invalid_input(self):
        missing = self.root / "no-such-dir"
        with self.assertRaises(prepare_advisor_index.PrepareAdvisorIndexError) as ctx:
            prepare_advisor_index.prepare(
                "rules", missing, runner=_RecordingRunner(result=_DPRINT_OK)
            )
        self.assertEqual(
            ctx.exception.reason_code, prepare_advisor_index.REASON_INVALID_INPUT
        )


# --- CLI 契約（exit code / JSON） -----------------------------------------------


class CliContractTest(_TempProject):
    """CLI として exit 0 / 20 と JSON status の契約を満たすこと。

    tempdir には dprint.jsonc が無いため、実 runner は正常スキップする（外部の
    dprint コマンドに依存しない）。
    """

    def _run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(_SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_success_exits_zero_with_status_success(self):
        self.write_config()
        result = self._run_cli("rules", "--project-root", str(self.root))
        self.assertEqual(result.returncode, prepare_advisor_index.EXIT_SUCCESS)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["root_dirs"], ["docs/rules/"])
        self.assertEqual(payload["exclude"], ["drafts", "archive"])

    def test_config_error_exits_20_with_operation_error(self):
        # 設定ファイルなし
        result = self._run_cli("rules", "--project-root", str(self.root))
        self.assertEqual(result.returncode, prepare_advisor_index.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(
            payload["reason_code"], prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )

    def test_invalid_category_exits_20_not_argparse_2(self):
        self.write_config()
        result = self._run_cli("readme", "--project-root", str(self.root))
        self.assertEqual(result.returncode, prepare_advisor_index.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(
            payload["reason_code"], prepare_advisor_index.REASON_INVALID_INPUT
        )

    def test_unreadable_config_exits_20_with_json(self):
        if os.geteuid() == 0:
            self.skipTest("root ではパーミッションが無視される")
        self.write_config()
        config_path = self.root / ".doc_structure.yaml"
        os.chmod(config_path, 0o000)
        try:
            result = self._run_cli("rules", "--project-root", str(self.root))
        finally:
            os.chmod(config_path, 0o600)
        self.assertEqual(result.returncode, prepare_advisor_index.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(
            payload["reason_code"], prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )

    def test_non_utf8_config_exits_20_with_json(self):
        (self.root / ".doc_structure.yaml").write_bytes(b"\xff\xfe\x00rules:\n")
        result = self._run_cli("rules", "--project-root", str(self.root))
        self.assertEqual(result.returncode, prepare_advisor_index.EXIT_OPERATION_ERROR)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "operation_error")
        self.assertEqual(
            payload["reason_code"], prepare_advisor_index.REASON_DOC_STRUCTURE_INVALID
        )

    def test_error_payload_keeps_common_contract_fields(self):
        result = self._run_cli("rules", "--project-root", str(self.root))
        payload = json.loads(result.stdout)
        self.assertEqual(payload["backend"], "doc-advisor")
        self.assertEqual(payload["operation"], "prepare_index")
        self.assertEqual(payload["startup"], "not_attempted")
        self.assertIn("message", payload)


# --- 二重実装の防止 --------------------------------------------------------------


class NoYamlReimplementationTest(unittest.TestCase):
    """`.doc_structure.yaml` の解釈を自前で持っていないこと（resolver へ委譲）。"""

    def test_no_yaml_parsing_is_reimplemented(self):
        tree = ast.parse(_SCRIPT_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        for forbidden in ("glob", "fnmatch", "yaml", "os"):
            self.assertNotIn(
                forbidden, imported, f"resolver の責務を再実装している: {forbidden}"
            )

        defined = {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }
        for forbidden in ("parse_config", "expand_globs", "collect_md_files", "is_excluded"):
            self.assertNotIn(
                forbidden, defined, f"resolver の責務を再実装している: {forbidden}"
            )

    def test_resolver_script_path_points_at_doc_structure_resolver(self):
        self.assertTrue(prepare_advisor_index.RESOLVER_SCRIPT.is_file())
        self.assertEqual(
            prepare_advisor_index.RESOLVER_SCRIPT.name, "resolve_doc_structure.py"
        )


if __name__ == "__main__":
    unittest.main()
