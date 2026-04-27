#!/usr/bin/env python3
"""scan_feature.py のテスト

実行:
  python3 -m unittest tests.forge.merge-feature-specs.test_scan_feature -v
  （ハイフン入りパッケージ名のため loader 経由で実行する）
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "merge-feature-specs" / "scripts" / "scan_feature.py"
)
sys.path.insert(0, str(SCRIPT.parent))

from scan_feature import (  # noqa: E402
    DEFAULT_ID_PREFIXES,
    build_id_pattern,
    detect_id,
    detect_kind,
    extract_h1,
)

DEFAULT_PATTERN = build_id_pattern(DEFAULT_ID_PREFIXES)


class TestDetectKind(unittest.TestCase):
    def test_inventory_by_name(self):
        self.assertEqual(detect_kind(Path("requirements/inventory.md")), "inventory")
        self.assertEqual(detect_kind(Path("requirements/INV-001_x.md")), "inventory")

    def test_requirement_by_parent(self):
        self.assertEqual(detect_kind(Path("requirements/REQ-001_x.md")), "requirement")

    def test_design_by_parent(self):
        self.assertEqual(detect_kind(Path("design/DES-024_x.md")), "design")

    def test_plan_only_when_in_plan_dir(self):
        # plan ディレクトリ + yaml/yml のみが plan
        self.assertEqual(detect_kind(Path("plan/foo_plan.yaml")), "plan")
        self.assertEqual(detect_kind(Path("plan/foo_plan.yml")), "plan")

    def test_yaml_outside_plan_dir_not_plan(self):
        # plan ディレクトリ外の yaml は plan 判定されない
        # (Phase 3 の「plan 無条件削除」に巻き込まないため)
        self.assertEqual(detect_kind(Path("notes/config.yaml")), "other")
        self.assertEqual(detect_kind(Path("data/sample.yml")), "other")
        # design 配下の yaml は parent ディレクトリに従って design 判定 (plan ではない)
        self.assertEqual(detect_kind(Path("design/diagram_data.yaml")), "design")
        # requirements 配下の yaml も同様
        self.assertEqual(detect_kind(Path("requirements/schema.yml")), "requirement")

    def test_other_default(self):
        self.assertEqual(detect_kind(Path("notes/memo.md")), "other")


class TestDetectId(unittest.TestCase):
    def test_id_from_filename_priority(self):
        # ファイル名にあれば本文より優先
        self.assertEqual(
            detect_id(Path("REQ-005_x.md"), "# Foo\nDES-099 言及", DEFAULT_PATTERN),
            "REQ-005",
        )

    def test_id_from_body_when_name_missing(self):
        self.assertEqual(
            detect_id(Path("notes.md"), "# 概要\n\nDES-024 を扱う", DEFAULT_PATTERN),
            "DES-024",
        )

    def test_no_id_returns_none(self):
        self.assertIsNone(detect_id(Path("plain.md"), "# 概要\n\n本文", DEFAULT_PATTERN))

    def test_inv_id_detected(self):
        self.assertEqual(
            detect_id(Path("inventory.md"), "# 棚卸し\nINV-001 ...", DEFAULT_PATTERN),
            "INV-001",
        )

    def test_no_pattern_disables_detection(self):
        # ID 体系を持たないプロジェクトでは pattern=None を渡す
        self.assertIsNone(detect_id(Path("REQ-005_x.md"), "DES-024 を扱う", None))

    def test_custom_prefixes(self):
        # 別プロジェクトの ID 体系 (RFC / ADR 等) も拾える
        custom = build_id_pattern(["RFC", "ADR"])
        self.assertEqual(detect_id(Path("RFC-042_proposal.md"), "", custom), "RFC-042")
        self.assertEqual(detect_id(Path("notes.md"), "ADR-007 で決定", custom), "ADR-007")
        # forge 慣習の REQ は拾わない
        self.assertIsNone(detect_id(Path("REQ-001_x.md"), "", custom))


class TestBuildIdPattern(unittest.TestCase):
    def test_none_when_no_prefixes(self):
        self.assertIsNone(build_id_pattern(None))
        self.assertIsNone(build_id_pattern([]))
        self.assertIsNone(build_id_pattern(()))

    def test_default_prefixes_match(self):
        p = build_id_pattern(DEFAULT_ID_PREFIXES)
        for sample in ("REQ-001", "DES-024", "INV-100", "TASK-005", "FNC-001", "NFR-099"):
            self.assertIsNotNone(p.search(sample), sample)

    def test_special_char_in_prefix_escaped(self):
        # プレフィックスに記号が混じっても壊れない
        p = build_id_pattern(["A.B", "C"])
        self.assertIsNotNone(p.search("A.B-001"))
        # "AXB-001" は matchしない (`.` がリテラル扱いされている)
        self.assertIsNone(p.search("AXB-001"))


class TestExtractH1(unittest.TestCase):
    def test_first_h1(self):
        self.assertEqual(extract_h1("前置き\n# 主題\n## サブ\n"), "主題")

    def test_no_h1(self):
        self.assertIsNone(extract_h1("## サブのみ\n本文\n"))


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        # docs/specs/{plugin}/{feature}/ 構造を擬似的に作る
        self.feature_dir = root / "docs" / "specs" / "demo" / "myfeature"
        (self.feature_dir / "requirements").mkdir(parents=True)
        (self.feature_dir / "design").mkdir()
        (self.feature_dir / "plan").mkdir()
        (self.feature_dir / "requirements" / "REQ-001_myfeature.md").write_text(
            "# REQ-001 myfeature 要件\n\n本文\n", encoding="utf-8",
        )
        (self.feature_dir / "requirements" / "inventory.md").write_text(
            "# 棚卸し\n\nINV-001 ...\n", encoding="utf-8",
        )
        (self.feature_dir / "design" / "DES-024_myfeature_design.md").write_text(
            "# DES-024 myfeature 設計\n\n本文\n", encoding="utf-8",
        )
        (self.feature_dir / "plan" / "myfeature_plan.yaml").write_text(
            "tasks: []\n", encoding="utf-8",
        )
        # main 側の既存 ID
        plugin_root = self.feature_dir.parent
        (plugin_root / "requirements").mkdir()
        (plugin_root / "design").mkdir()
        (plugin_root / "requirements" / "REQ-002_existing.md").write_text(
            "# REQ-002\n", encoding="utf-8",
        )
        (plugin_root / "design" / "DES-010_existing.md").write_text(
            "# DES-010\n", encoding="utf-8",
        )

    def test_script_runs_and_outputs_json(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.feature_dir)],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["plugin"], "demo")
        self.assertEqual(payload["feature"], "myfeature")
        # ファイル一覧
        rels = {f["rel_path"] for f in payload["files"]}
        self.assertIn("requirements/REQ-001_myfeature.md", rels)
        self.assertIn("requirements/inventory.md", rels)
        self.assertIn("design/DES-024_myfeature_design.md", rels)
        self.assertIn("plan/myfeature_plan.yaml", rels)
        # kind 判定
        kinds = {f["rel_path"]: f["kind"] for f in payload["files"]}
        self.assertEqual(kinds["requirements/inventory.md"], "inventory")
        self.assertEqual(kinds["requirements/REQ-001_myfeature.md"], "requirement")
        self.assertEqual(kinds["design/DES-024_myfeature_design.md"], "design")
        self.assertEqual(kinds["plan/myfeature_plan.yaml"], "plan")
        # main 側既存 ID
        req_ids = {e["id"] for e in payload["main_existing_ids"]["requirements"]}
        des_ids = {e["id"] for e in payload["main_existing_ids"]["design"]}
        self.assertEqual(req_ids, {"REQ-002"})
        self.assertEqual(des_ids, {"DES-010"})
        self.assertTrue(payload["main_specs_dirs"]["requirements"])
        self.assertTrue(payload["main_specs_dirs"]["design"])
        self.assertFalse(payload["main_specs_dirs"]["plan"])

    def test_missing_dir_returns_json_error(self):
        # forge 慣習に従い、エラー時は JSON 形式 (status=error) で stdout に出力する
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.feature_dir / "nope")],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("not found", payload["message"])

    def test_no_id_option_disables_detection(self):
        # ID 体系を持たないプロジェクトを想定
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--no-id", str(self.feature_dir)],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        # 全ファイルの id が None
        ids = {f["id"] for f in payload["files"]}
        self.assertEqual(ids, {None})
        # main 側既存 ID も空 (採番衝突検査が無効化される)
        self.assertEqual(payload["main_existing_ids"]["requirements"], [])
        self.assertEqual(payload["main_existing_ids"]["design"], [])
        self.assertEqual(payload["id_prefixes"], [])

    def test_custom_id_prefixes(self):
        # 別プロジェクト慣習 (RFC / ADR) を指定
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--id-prefixes", "RFC,ADR", str(self.feature_dir)],
            capture_output=True, text=True, check=True,
        )
        payload = json.loads(result.stdout)
        # forge 慣習の REQ-001 は拾われない
        ids = {f["id"] for f in payload["files"]}
        self.assertEqual(ids, {None})
        self.assertEqual(payload["id_prefixes"], ["RFC", "ADR"])


if __name__ == "__main__":
    unittest.main()
