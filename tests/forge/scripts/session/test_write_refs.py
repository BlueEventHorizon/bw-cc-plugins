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


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestValidateRefsData(unittest.TestCase):
    """validate_refs_data のテスト。"""

    def _base_data(self):
        return {
            "target_files": ["a.py"],
            "reference_docs": [{"path": "docs/r.md"}],
            "review_criteria_path": "docs/review.md",
        }

    def test_valid_minimal(self):
        validate_refs_data(self._base_data())

    def test_valid_with_related_code(self):
        data = self._base_data()
        data["related_code"] = [{"path": "src/x.py", "reason": "関連"}]
        validate_refs_data(data)

    def test_empty_target_files(self):
        data = self._base_data()
        data["target_files"] = []
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_missing_target_files(self):
        data = self._base_data()
        del data["target_files"]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_missing_review_criteria_path(self):
        data = self._base_data()
        data["review_criteria_path"] = ""
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_reference_docs_missing_path(self):
        data = self._base_data()
        data["reference_docs"] = [{"reason": "no path"}]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_related_code_missing_reason(self):
        data = self._base_data()
        data["related_code"] = [{"path": "x.py"}]
        with self.assertRaises(ValueError):
            validate_refs_data(data)

    def test_empty_reference_docs_allowed(self):
        data = self._base_data()
        data["reference_docs"] = []
        validate_refs_data(data)


class TestWriteRefs(_FsTestCase):
    """write_refs のテスト。"""

    def test_minimal(self):
        data = {
            "target_files": ["a.py", "b.py"],
            "reference_docs": [],
            "review_criteria_path": "docs/review.md",
        }
        path = write_refs(str(self.session_dir), data)
        self.assertTrue(Path(path).exists())
        result = read_yaml(path)
        self.assertEqual(result["target_files"], ["a.py", "b.py"])
        self.assertEqual(result["review_criteria_path"], "docs/review.md")

    def test_full(self):
        data = {
            "target_files": ["src/main.py"],
            "reference_docs": [
                {"path": "docs/rules.md"},
                {"path": "docs/spec.md"},
            ],
            "review_criteria_path": "docs/criteria.md",
            "related_code": [
                {"path": "src/util.py", "reason": "ヘルパー", "lines": "1-30"},
            ],
        }
        path = write_refs(str(self.session_dir), data)
        result = read_yaml(path)
        self.assertEqual(len(result["reference_docs"]), 2)
        self.assertEqual(result["related_code"][0]["reason"], "ヘルパー")
        self.assertEqual(result["related_code"][0]["lines"], "1-30")


class TestCLI(_FsTestCase):
    """CLI 統合テスト。"""

    def test_basic(self):
        data = {
            "target_files": ["a.py"],
            "reference_docs": [{"path": "r.md"}],
            "review_criteria_path": "c.md",
        }
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
