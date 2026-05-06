"""write_refs のテスト。"""

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

from session.write_refs import validate_refs_data, build_refs_sections, write_refs
from session.yaml_utils import read_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "write_refs.py"
)


def _base_data():
    """テスト用の最小限の正常データを返す。"""
    return {
        "target_files": ["a.py"],
        "reference_docs": [{"path": "docs/r.md"}],
        "perspectives": [
            {
                "name": "correctness",
                "criteria_path": "review/docs/review_criteria_code.md",
                "output_path": "review_correctness.md",
            }
        ],
    }


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestValidateRefsData(unittest.TestCase):
    """validate_refs_data のテスト。"""

    def test_valid_minimal(self):
        validate_refs_data(_base_data())

    def test_valid_with_related_code(self):
        data = _base_data()
        data["related_code"] = [{"path": "src/x.py", "reason": "関連"}]
        validate_refs_data(data)

    def test_valid_with_section(self):
        """section フィールドが指定されていても正常に通る。"""
        data = _base_data()
        data["perspectives"][0]["section"] = "正確性 (Logic)"
        validate_refs_data(data)

    def test_valid_section_null(self):
        """section が null でも正常に通る。"""
        data = _base_data()
        data["perspectives"][0]["section"] = None
        validate_refs_data(data)

    def test_empty_target_files(self):
        data = _base_data()
        data["target_files"] = []
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_missing_target_files(self):
        data = _base_data()
        del data["target_files"]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_reference_docs_missing_path(self):
        data = _base_data()
        data["reference_docs"] = [{"reason": "no path"}]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_related_code_missing_reason(self):
        data = _base_data()
        data["related_code"] = [{"path": "x.py"}]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_empty_reference_docs_allowed(self):
        data = _base_data()
        data["reference_docs"] = []
        validate_refs_data(data)

    # -- perspectives 必須チェック --

    def test_missing_perspectives(self):
        """perspectives が存在しない場合はエラー。"""
        data = _base_data()
        del data["perspectives"]
        with self.assertRaises(ValueError, msg="perspectives は非空の配列が必須です"):
            validate_refs_data(data)

    def test_empty_perspectives(self):
        """perspectives が空配列の場合はエラー。"""
        data = _base_data()
        data["perspectives"] = []
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_perspectives_not_list(self):
        """perspectives がリストでない場合はエラー。"""
        data = _base_data()
        data["perspectives"] = "not a list"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    # -- perspectives[].name 検証 --

    def test_valid_name_with_hyphen(self):
        """ハイフンを含む name は許容。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "project-rules"
        validate_refs_data(data)

    def test_valid_name_with_underscore(self):
        """アンダースコアを含む name は許容。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "project_rules"
        validate_refs_data(data)

    def test_valid_name_with_digits(self):
        """数字を含む name は許容。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "rule01"
        validate_refs_data(data)

    def test_invalid_name_uppercase(self):
        """大文字を含む name はエラー。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "Correctness"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_invalid_name_space(self):
        """スペースを含む name はエラー。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "my rule"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_invalid_name_dot(self):
        """ドットを含む name はエラー。"""
        data = _base_data()
        data["perspectives"][0]["name"] = "my.rule"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_missing_name(self):
        """name が空文字の場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["name"] = ""
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    # -- perspectives[].criteria_path 検証 --

    def test_missing_criteria_path(self):
        """criteria_path が空文字の場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["criteria_path"] = ""
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    # -- perspectives[].output_path 検証 --

    def test_missing_output_path(self):
        """output_path が空文字の場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["output_path"] = ""
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_output_path_traversal(self):
        """output_path に ../ が含まれる場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["output_path"] = "../outside.md"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_output_path_traversal_middle(self):
        """output_path の中間に .. が含まれる場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["output_path"] = "sub/../outside.md"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_output_path_absolute(self):
        """output_path が絶対パスの場合はエラー。"""
        data = _base_data()
        data["perspectives"][0]["output_path"] = "/tmp/review.md"
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_output_path_valid_subdir(self):
        """output_path がサブディレクトリを含む相対パスは許容。"""
        data = _base_data()
        data["perspectives"][0]["output_path"] = "sub/review_correctness.md"
        validate_refs_data(data)

    # -- review_criteria_path の後方互換（無視される） --

    def test_review_criteria_path_ignored(self):
        """review_criteria_path が渡されてもエラーにならず無視される。"""
        data = _base_data()
        data["review_criteria_path"] = "docs/old_criteria.md"
        validate_refs_data(data)

    # -- 複数 perspectives --

    def test_multiple_perspectives(self):
        """複数の perspectives を持つデータが正常に通る。"""
        data = _base_data()
        data["perspectives"].append({
            "name": "resilience",
            "criteria_path": "review/docs/review_criteria_code.md",
            "section": "堅牢性 (Resilience)",
            "output_path": "review_resilience.md",
        })
        validate_refs_data(data)


class TestBuildRefsSections(unittest.TestCase):
    """build_refs_sections のテスト。"""

    def test_contains_perspectives(self):
        """sections に perspectives が含まれる。"""
        data = _base_data()
        sections = build_refs_sections(data)
        keys = [k for k, _ in sections]
        self.assertIn("perspectives", keys)
        self.assertNotIn("review_criteria_path", keys)

    def test_review_criteria_path_not_in_sections(self):
        """review_criteria_path が入力にあっても sections には含まれない。"""
        data = _base_data()
        data["review_criteria_path"] = "old/path.md"
        sections = build_refs_sections(data)
        keys = [k for k, _ in sections]
        self.assertNotIn("review_criteria_path", keys)


class TestWriteRefs(_FsTestCase):
    """write_refs のテスト。"""

    def test_minimal(self):
        data = _base_data()
        data["reference_docs"] = []
        path = write_refs(str(self.session_dir), data)
        self.assertTrue(Path(path).exists())
        result = read_yaml(path)
        self.assertEqual(result["target_files"], ["a.py"])
        self.assertEqual(len(result["perspectives"]), 1)
        self.assertEqual(result["perspectives"][0]["name"], "correctness")

    def test_full(self):
        data = {
            "target_files": ["src/main.py"],
            "reference_docs": [
                {"path": "docs/rules.md"},
                {"path": "docs/spec.md"},
            ],
            "perspectives": [
                {
                    "name": "correctness",
                    "criteria_path": "review/docs/review_criteria_code.md",
                    "section": "正確性 (Logic)",
                    "output_path": "review_correctness.md",
                },
                {
                    "name": "resilience",
                    "criteria_path": "review/docs/review_criteria_code.md",
                    "section": "堅牢性 (Resilience)",
                    "output_path": "review_resilience.md",
                },
            ],
            "related_code": [
                {"path": "src/util.py", "reason": "ヘルパー", "lines": "1-30"},
            ],
        }
        path = write_refs(str(self.session_dir), data)
        result = read_yaml(path)
        self.assertEqual(len(result["reference_docs"]), 2)
        self.assertEqual(len(result["perspectives"]), 2)
        self.assertEqual(result["perspectives"][1]["name"], "resilience")
        self.assertEqual(result["related_code"][0]["reason"], "ヘルパー")
        self.assertEqual(result["related_code"][0]["lines"], "1-30")

    def test_review_criteria_path_not_written(self):
        """review_criteria_path が入力にあっても出力 YAML には含まれない。"""
        data = _base_data()
        data["review_criteria_path"] = "old/criteria.md"
        path = write_refs(str(self.session_dir), data)
        result = read_yaml(path)
        self.assertNotIn("review_criteria_path", result)

    def test_updates_session_meta(self):
        """refs.yaml 書き出し後に session.yaml の浅い状態を更新する。"""
        (self.session_dir / "session.yaml").write_text(
            "status: active\nskill: review\n", encoding="utf-8"
        )

        write_refs(str(self.session_dir), _base_data())

        session = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(session["phase"], "context_ready")
        self.assertEqual(session["phase_status"], "completed")
        self.assertEqual(session["active_artifact"], "refs.yaml")


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


if __name__ == "__main__":
    unittest.main()
