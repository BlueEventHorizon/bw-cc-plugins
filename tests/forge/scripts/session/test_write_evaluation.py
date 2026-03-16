"""write_evaluation のテスト。"""

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

from session.write_evaluation import (
    validate_evaluation_data,
    build_evaluation_sections,
    summarize_evaluation,
    write_evaluation,
)
from session.yaml_utils import read_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "write_evaluation.py"
)


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


def _base_data():
    return {
        "cycle": 1,
        "items": [
            {
                "id": 1, "severity": "critical", "title": "問題1",
                "recommendation": "fix", "auto_fixable": True, "reason": "理由1",
            },
            {
                "id": 2, "severity": "major", "title": "問題2",
                "recommendation": "skip", "reason": "理由2",
            },
        ],
    }


class TestValidateEvaluationData(unittest.TestCase):
    """validate_evaluation_data のテスト。"""

    def test_valid(self):
        validate_evaluation_data(_base_data())

    def test_cycle_zero(self):
        data = _base_data()
        data["cycle"] = 0
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_cycle_missing(self):
        data = _base_data()
        del data["cycle"]
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_empty_items(self):
        data = _base_data()
        data["items"] = []
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_missing_required_field(self):
        data = _base_data()
        del data["items"][0]["reason"]
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_invalid_recommendation(self):
        data = _base_data()
        data["items"][0]["recommendation"] = "invalid"
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_invalid_severity(self):
        data = _base_data()
        data["items"][0]["severity"] = "low"
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_fix_without_auto_fixable(self):
        data = _base_data()
        del data["items"][0]["auto_fixable"]
        with self.assertRaises(ValueError):
            validate_evaluation_data(data)

    def test_skip_without_auto_fixable_ok(self):
        """skip の場合は auto_fixable 不要。"""
        data = {
            "cycle": 1,
            "items": [
                {"id": 1, "severity": "major", "title": "t",
                 "recommendation": "skip", "reason": "r"},
            ],
        }
        validate_evaluation_data(data)


class TestSummarizeEvaluation(unittest.TestCase):
    """summarize_evaluation のテスト。"""

    def test_basic(self):
        items = _base_data()["items"]
        result = summarize_evaluation(items)
        self.assertEqual(result["fix"], 1)
        self.assertEqual(result["skip"], 1)
        self.assertEqual(result["needs_review"], 0)


class TestWriteEvaluation(_FsTestCase):
    """write_evaluation のテスト。"""

    def test_basic(self):
        data = _base_data()
        path = write_evaluation(str(self.session_dir), data)
        self.assertTrue(Path(path).exists())
        result = read_yaml(path)
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["items"][0]["recommendation"], "fix")
        self.assertTrue(result["items"][0]["auto_fixable"])

    def test_field_order(self):
        """フィールドが正しい順序で出力される。"""
        data = _base_data()
        path = write_evaluation(str(self.session_dir), data)
        content = Path(path).read_text()
        # id が severity より前にある
        id_pos = content.index("id:")
        severity_pos = content.index("severity:")
        self.assertLess(id_pos, severity_pos)


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
        self.assertEqual(result["summary"]["fix"], 1)

    def test_validation_error(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps({"cycle": 0, "items": []}),
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
