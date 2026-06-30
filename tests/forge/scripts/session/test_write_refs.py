"""write_refs のテスト (ADR-032 path schema unification 後の新スキーマ)。

ADR-032 で以下を変更:
- target_files: string[] → object[] (path フィールド必須)
- ssot_refs[].doc_path → path (Issue #99 改名を覆す)
- review_packet.output_path → output_filename
- 旧キー名は明示的 ValueError で reject
"""

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "forge" / "scripts"),
)

from session.write_refs import (
    build_refs_text,
    validate_review_packet,
    write_refs,
)
from session.yaml_utils import read_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "write_refs.py"
)


def _base_data():
    """テスト用の最小限の正常データを返す (ADR-032 新スキーマ)。"""
    return {
        "target_files": [{"path": "a.py"}],
        "reference_docs": [{"path": "docs/r.md"}],
        "review_packet": {
            "criteria_path": "review/docs/review_criteria_code.md",
            "ssot_refs": [
                {
                    "path": "docs/rules/implementation_guidelines.md",
                    "priority": "P1",
                    "doc_type": "rules",
                },
                {
                    "path": "plugins/forge/docs/spec_priorities_spec.md",
                    "priority": "P2",
                    "doc_type": "principles",
                },
            ],
            "check_order": ["P1", "P2", "P3"],
            "severity_source": "plugins/forge/docs/review_priorities_spec.md",
            "output_filename": "review_code.md",
        },
    }


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# validate_review_packet: 正常系 + 既存 (target_files / reference_docs / related_code)
# ---------------------------------------------------------------------------


class TestValidateReviewPacketBasics(unittest.TestCase):
    """validate_review_packet の基本テスト。"""

    def test_valid_minimal(self):
        validate_review_packet(_base_data())

    def test_valid_with_related_code(self):
        data = _base_data()
        data["related_code"] = [{"path": "src/x.py", "reason": "関連"}]
        validate_review_packet(data)

    def test_valid_with_related_code_lines(self):
        data = _base_data()
        data["related_code"] = [
            {"path": "src/x.py", "reason": "関連", "lines": "10-50"}
        ]
        validate_review_packet(data)

    def test_empty_reference_docs_allowed(self):
        data = _base_data()
        data["reference_docs"] = []
        validate_review_packet(data)

    # -- target_files (ADR-032: dict 配列必須) --

    def test_empty_target_files(self):
        data = _base_data()
        data["target_files"] = []
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_missing_target_files(self):
        data = _base_data()
        del data["target_files"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_target_files_item_not_dict(self):
        """target_files[] の各要素は dict 必須 (ADR-032)。"""
        data = _base_data()
        data["target_files"] = ["a.py"]  # 旧 schema (string array)
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        self.assertIn("target_files", str(ctx.exception))

    def test_target_files_missing_path(self):
        data = _base_data()
        data["target_files"] = [{"reason": "no path"}]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_target_files_empty_path(self):
        data = _base_data()
        data["target_files"] = [{"path": ""}]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    # -- reference_docs --

    def test_reference_docs_missing_path(self):
        data = _base_data()
        data["reference_docs"] = [{"reason": "no path"}]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_reference_docs_item_not_dict(self):
        """reference_docs[] の各要素は dict 必須 (bb0a85a で型チェック追加)。"""
        data = _base_data()
        data["reference_docs"] = ["docs/r.md"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    # -- related_code --

    def test_related_code_missing_reason(self):
        data = _base_data()
        data["related_code"] = [{"path": "x.py"}]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_related_code_missing_path(self):
        data = _base_data()
        data["related_code"] = [{"reason": "関連"}]
        with self.assertRaises(ValueError):
            validate_review_packet(data)


# ---------------------------------------------------------------------------
# validate_review_packet: review_packet 必須キー
# ---------------------------------------------------------------------------


class TestReviewPacketRequiredKeys(unittest.TestCase):
    """review_packet の必須キー検証テスト。"""

    def test_missing_review_packet(self):
        data = _base_data()
        del data["review_packet"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_review_packet_not_dict(self):
        data = _base_data()
        data["review_packet"] = "not a dict"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_missing_criteria_path(self):
        data = _base_data()
        del data["review_packet"]["criteria_path"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_empty_criteria_path(self):
        data = _base_data()
        data["review_packet"]["criteria_path"] = ""
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_missing_severity_source(self):
        data = _base_data()
        del data["review_packet"]["severity_source"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_empty_severity_source(self):
        data = _base_data()
        data["review_packet"]["severity_source"] = ""
        with self.assertRaises(ValueError):
            validate_review_packet(data)


# ---------------------------------------------------------------------------
# validate_review_packet: ssot_refs (ADR-032: path に改名)
# ---------------------------------------------------------------------------


class TestReviewPacketSsotRefs(unittest.TestCase):
    """ssot_refs の検証テスト。"""

    def test_missing_ssot_refs(self):
        data = _base_data()
        del data["review_packet"]["ssot_refs"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_empty_ssot_refs(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"] = []
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_not_list(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"] = {"path": "x.md"}
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_item_not_dict(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"] = ["not a dict"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_missing_path(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0].pop("path")
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_empty_path(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["path"] = ""
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    # -- priority --

    def test_ssot_refs_priority_p1(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["priority"] = "P1"
        validate_review_packet(data)

    def test_ssot_refs_priority_p2(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["priority"] = "P2"
        validate_review_packet(data)

    def test_ssot_refs_priority_p3(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["priority"] = "P3"
        validate_review_packet(data)

    def test_ssot_refs_priority_invalid(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["priority"] = "P4"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_priority_lowercase(self):
        """小文字 p1 は不可。"""
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["priority"] = "p1"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_priority_missing(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0].pop("priority")
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    # -- doc_type --

    def test_ssot_refs_doc_type_rules(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["doc_type"] = "rules"
        validate_review_packet(data)

    def test_ssot_refs_doc_type_principles(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["doc_type"] = "principles"
        validate_review_packet(data)

    def test_ssot_refs_doc_type_format(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["doc_type"] = "format"
        validate_review_packet(data)

    def test_ssot_refs_doc_type_invalid(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0]["doc_type"] = "spec"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_ssot_refs_doc_type_missing(self):
        data = _base_data()
        data["review_packet"]["ssot_refs"][0].pop("doc_type")
        with self.assertRaises(ValueError):
            validate_review_packet(data)


# ---------------------------------------------------------------------------
# validate_review_packet: check_order
# ---------------------------------------------------------------------------


class TestReviewPacketCheckOrder(unittest.TestCase):
    """check_order の検証テスト。"""

    def test_missing_check_order(self):
        data = _base_data()
        del data["review_packet"]["check_order"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_empty_check_order(self):
        data = _base_data()
        data["review_packet"]["check_order"] = []
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_check_order_not_list(self):
        data = _base_data()
        data["review_packet"]["check_order"] = "P1,P2,P3"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_check_order_non_string_element(self):
        data = _base_data()
        data["review_packet"]["check_order"] = ["P1", 2, "P3"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_check_order_empty_string_element(self):
        data = _base_data()
        data["review_packet"]["check_order"] = ["P1", "", "P3"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)


# ---------------------------------------------------------------------------
# validate_review_packet: output_filename (ADR-032 で output_path から改名)
# ---------------------------------------------------------------------------


class TestReviewPacketOutputFilename(unittest.TestCase):
    """output_filename の検証テスト (^review_<種別>.md$ 形式)。"""

    def test_missing_output_filename(self):
        data = _base_data()
        del data["review_packet"]["output_filename"]
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_empty_output_filename(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = ""
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_valid_output_filename_code(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "review_code.md"
        validate_review_packet(data)

    def test_valid_output_filename_design(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "review_design.md"
        validate_review_packet(data)

    def test_invalid_output_filename_no_prefix(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_invalid_output_filename_wrong_ext(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "review_code.txt"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_invalid_output_filename_uppercase(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "review_Code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_invalid_output_filename_with_subdir(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "sub/review_code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_output_filename_traversal(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "../review_code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_output_filename_traversal_middle(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "sub/../review_code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)

    def test_output_filename_absolute(self):
        data = _base_data()
        data["review_packet"]["output_filename"] = "/tmp/review_code.md"
        with self.assertRaises(ValueError):
            validate_review_packet(data)


# ---------------------------------------------------------------------------
# validate_review_packet: 旧 perspectives[] スキーマの拒否 (回帰防止)
# ---------------------------------------------------------------------------


class TestRejectLegacyPerspectives(unittest.TestCase):
    """旧 perspectives[] キーが含まれる入力を明示的に拒否する。"""

    def test_reject_legacy_perspectives_present(self):
        data = _base_data()
        data["perspectives"] = [
            {
                "name": "correctness",
                "criteria_path": "review/docs/review_criteria_code.md",
                "output_filename": "review_correctness.md",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        msg = str(ctx.exception)
        self.assertIn("perspectives", msg)
        self.assertIn("review_packet", msg)

    def test_reject_legacy_perspectives_even_when_review_packet_absent(self):
        data = _base_data()
        del data["review_packet"]
        data["perspectives"] = [
            {
                "name": "correctness",
                "criteria_path": "x.md",
                "output_filename": "review_x.md",
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        self.assertIn("perspectives", str(ctx.exception))


# ---------------------------------------------------------------------------
# ADR-032 回帰防止: 旧キー名 (doc_path / output_path) の拒否
# ---------------------------------------------------------------------------


class TestRejectLegacyAdr032Keys(unittest.TestCase):
    """ADR-032 で改名された旧キー名が拒否されることを検証する。"""

    def test_ssot_refs_legacy_doc_path_rejected(self):
        """ssot_refs[].doc_path は ADR-032 で path に統一されたため拒否される。"""
        data = _base_data()
        data["review_packet"]["ssot_refs"][0].pop("path")
        data["review_packet"]["ssot_refs"][0]["doc_path"] = "docs/x.md"
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        msg = str(ctx.exception)
        # メッセージに「path」必須が出る (doc_path を明示的に reject する必要は必ずしも無いが、
        # 「path フィールド必須」として fail することは保証される)
        self.assertIn("path", msg)

    def test_review_packet_legacy_output_path_rejected(self):
        """review_packet.output_path は ADR-032 で output_filename に改名されたため拒否される。"""
        data = _base_data()
        data["review_packet"].pop("output_filename")
        data["review_packet"]["output_path"] = "review_code.md"
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        msg = str(ctx.exception)
        self.assertIn("output_filename", msg)

    def test_target_files_legacy_string_array_rejected(self):
        """target_files string array は ADR-032 で [{path}] dict 配列に統一されたため拒否される。"""
        data = _base_data()
        data["target_files"] = ["a.py", "b.py"]
        with self.assertRaises(ValueError) as ctx:
            validate_review_packet(data)
        msg = str(ctx.exception)
        self.assertIn("target_files", msg)


# ---------------------------------------------------------------------------
# build_refs_text / write_refs / read_yaml ラウンドトリップ
# ---------------------------------------------------------------------------


class TestBuildRefsText(unittest.TestCase):
    """build_refs_text のテスト (順序とネスト構造)。"""

    def test_section_order(self):
        data = _base_data()
        data["related_code"] = [{"path": "src/x.py", "reason": "関連"}]
        text = build_refs_text(data)
        idx_target = text.find("target_files:")
        idx_ref = text.find("reference_docs:")
        idx_packet = text.find("review_packet:")
        idx_related = text.find("related_code:")
        self.assertGreaterEqual(idx_target, 0)
        self.assertGreater(idx_ref, idx_target)
        self.assertGreater(idx_packet, idx_ref)
        self.assertGreater(idx_related, idx_packet)

    def test_no_perspectives_in_output(self):
        text = build_refs_text(_base_data())
        self.assertNotIn("perspectives:", text)

    def test_review_packet_nested(self):
        text = build_refs_text(_base_data())
        self.assertIn("review_packet:", text)
        for key in (
            "criteria_path:",
            "ssot_refs:",
            "check_order:",
            "severity_source:",
            "output_filename:",
        ):
            self.assertIn(key, text)

    def test_output_path_not_in_output(self):
        """ADR-032: 旧 output_path キー名で書き出してはならない。"""
        text = build_refs_text(_base_data())
        self.assertNotIn("output_path:", text)

    def test_ssot_refs_doc_path_not_in_output(self):
        """ADR-032: ssot_refs[] は path で書き出される (旧 doc_path 不可)。"""
        text = build_refs_text(_base_data())
        # ssot_refs セクション内に doc_path: が出てはならない
        self.assertNotIn("doc_path:", text)

    def test_target_files_dict_format(self):
        """ADR-032: target_files は [{path: ...}] dict 配列で書き出される。"""
        text = build_refs_text(_base_data())
        # "- path:" の形式が含まれる (target_files セクション)
        self.assertIn("target_files:", text)
        # 旧 string array 形式 "- a.py" は無い (path: プレフィックスありで書かれる)
        self.assertNotRegex(text, r"target_files:\s*\n\s+-\s+a\.py\s*\n")

    def test_skip_reference_docs_when_empty(self):
        data = _base_data()
        data["reference_docs"] = []
        text = build_refs_text(data)
        self.assertNotIn("reference_docs:", text)


class TestWriteRefs(_FsTestCase):
    """write_refs (ファイル書き出し + read_yaml ラウンドトリップ)。"""

    def test_minimal(self):
        data = _base_data()
        data["reference_docs"] = []
        path = write_refs(str(self.session_dir), data)
        self.assertTrue(Path(path).exists())
        result = read_yaml(path)
        # ADR-032: target_files は dict 配列
        self.assertEqual(result["target_files"], [{"path": "a.py"}])
        packet = result["review_packet"]
        self.assertIsInstance(packet, dict)
        self.assertEqual(
            packet["criteria_path"], "review/docs/review_criteria_code.md"
        )
        self.assertEqual(
            packet["severity_source"],
            "plugins/forge/docs/review_priorities_spec.md",
        )
        # ADR-032: output_filename
        self.assertEqual(packet["output_filename"], "review_code.md")
        self.assertNotIn("output_path", packet)
        self.assertEqual(packet["check_order"], ["P1", "P2", "P3"])
        self.assertEqual(len(packet["ssot_refs"]), 2)
        self.assertEqual(packet["ssot_refs"][0]["priority"], "P1")
        self.assertEqual(packet["ssot_refs"][0]["doc_type"], "rules")
        # ADR-032: ssot_refs は path
        self.assertEqual(
            packet["ssot_refs"][0]["path"],
            "docs/rules/implementation_guidelines.md",
        )
        self.assertNotIn("doc_path", packet["ssot_refs"][0])

    def test_full(self):
        data = copy.deepcopy(_base_data())
        data["reference_docs"] = [
            {"path": "docs/rules.md"},
            {"path": "docs/spec.md"},
        ]
        data["review_packet"]["ssot_refs"].append(
            {
                "path": "plugins/forge/docs/spec_priorities_spec.md",
                "priority": "P3",
                "doc_type": "principles",
            }
        )
        data["related_code"] = [
            {"path": "src/util.py", "reason": "ヘルパー", "lines": "1-30"},
        ]
        path = write_refs(str(self.session_dir), data)
        result = read_yaml(path)
        self.assertEqual(len(result["reference_docs"]), 2)
        self.assertEqual(len(result["review_packet"]["ssot_refs"]), 3)
        self.assertEqual(
            result["review_packet"]["ssot_refs"][2]["priority"], "P3"
        )
        self.assertEqual(result["related_code"][0]["reason"], "ヘルパー")
        self.assertEqual(result["related_code"][0]["lines"], "1-30")
        # ADR-032 ラウンドトリップ: target_files も dict 配列で保持
        self.assertEqual(len(result["target_files"]), 1)
        self.assertEqual(result["target_files"][0]["path"], "a.py")


# ---------------------------------------------------------------------------
# CLI 統合テスト
# ---------------------------------------------------------------------------


class TestCLI(_FsTestCase):
    """CLI 統合テスト。"""

    def test_basic(self):
        data = _base_data()
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(data),
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(Path(result["path"]).exists())

    def test_invalid_json(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input="not json",
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_validation_error(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps({"target_files": []}),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_reject_legacy_perspectives(self):
        data = _base_data()
        data["perspectives"] = [
            {
                "name": "correctness",
                "criteria_path": "x.md",
                "output_filename": "review_x.md",
            }
        ]
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(data),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_reject_legacy_output_path(self):
        """ADR-032: CLI 経由でも旧 output_path キーは reject される。"""
        data = _base_data()
        data["review_packet"].pop("output_filename")
        data["review_packet"]["output_path"] = "review_code.md"
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(data),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_reject_legacy_ssot_refs_doc_path(self):
        """ADR-032: CLI 経由でも旧 ssot_refs[].doc_path は reject される。"""
        data = _base_data()
        data["review_packet"]["ssot_refs"][0].pop("path")
        data["review_packet"]["ssot_refs"][0]["doc_path"] = "docs/x.md"
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(data),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_reject_legacy_target_files_string_array(self):
        """ADR-032: CLI 経由でも target_files の string array は reject される。"""
        data = _base_data()
        data["target_files"] = ["a.py"]
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(data),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)


# ---------------------------------------------------------------------------
# 旧 perspectives キー拒否 (subprocess 経由回帰防止)
# ---------------------------------------------------------------------------


class TestRejectLegacyPerspectivesRegression(_FsTestCase):
    """DES-028 §2.3 / REQ-004 FNC-412 回帰防止テスト。"""

    LEGACY_PERSPECTIVE = {
        "name": "logic",
        "criteria_path": "review/docs/review_criteria_code.md",
        "section": "Perspective: logic",
        "output_filename": "review_logic.md",
    }

    def _run_cli(self, payload):
        return subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def test_legacy_perspectives_exits_nonzero(self):
        payload = _base_data()
        payload["perspectives"] = [self.LEGACY_PERSPECTIVE]
        proc = self._run_cli(payload)
        self.assertNotEqual(
            proc.returncode, 0,
            f"perspectives キー入力で 0 終了は不可: stdout={proc.stdout!r}",
        )

    def test_legacy_perspectives_error_message_mentions_key_and_deprecation(self):
        payload = _base_data()
        payload["perspectives"] = [self.LEGACY_PERSPECTIVE]
        proc = self._run_cli(payload)
        self.assertTrue(proc.stderr, "stderr が空: エラーメッセージ未出力")
        try:
            err = json.loads(proc.stderr)
        except json.JSONDecodeError:
            self.fail(
                f"stderr が JSON 形式でない: {proc.stderr!r}"
            )
        self.assertEqual(err.get("status"), "error")
        msg = err.get("error", "")
        self.assertIn("perspectives", msg)
        self.assertTrue(
            any(token in msg for token in ("撤廃", "廃止", "使用不可", "deprecated")),
            f"エラーメッセージに廃止文言が無い: {msg!r}",
        )
        self.assertIn("review_packet", msg)

    def test_legacy_perspectives_does_not_create_refs_yaml(self):
        payload = _base_data()
        payload["perspectives"] = [self.LEGACY_PERSPECTIVE]
        refs_path = self.session_dir / "refs.yaml"
        self.assertFalse(refs_path.exists())
        proc = self._run_cli(payload)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(refs_path.exists())

    def test_new_schema_succeeds_and_creates_refs_yaml(self):
        payload = _base_data()
        self.assertNotIn("perspectives", payload)
        refs_path = self.session_dir / "refs.yaml"
        proc = self._run_cli(payload)
        self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr!r}")
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(refs_path.exists())
        text = refs_path.read_text(encoding="utf-8")
        self.assertNotIn("perspectives:", text)


if __name__ == "__main__":
    unittest.main()
