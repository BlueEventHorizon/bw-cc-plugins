"""update_plan のテスト。"""

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

from session.update_plan import (
    read_plan, update_item, update_items_batch, write_plan,
)
from session.yaml_utils import write_nested_yaml, read_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "update_plan.py"
)


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plan(self, items):
        """テスト用の plan.yaml を書き出す。"""
        sections = [("items", items)]
        write_nested_yaml(
            str(self.session_dir / "plan.yaml"), sections
        )


def _sample_items():
    return [
        {"id": 1, "severity": "critical", "title": "問題1", "status": "pending"},
        {"id": 2, "severity": "major", "title": "問題2", "status": "pending"},
        {"id": 3, "severity": "minor", "title": "問題3", "status": "pending"},
    ]


class TestUpdateItem(unittest.TestCase):
    """update_item のテスト。"""

    def test_update_to_fixed(self):
        items = _sample_items()
        result = update_item(items, 1, {"status": "fixed", "files_modified": ["a.py"]})
        self.assertTrue(result)
        self.assertEqual(items[0]["status"], "fixed")
        self.assertEqual(items[0]["files_modified"], ["a.py"])
        # fixed_at が自動生成される
        self.assertIn("fixed_at", items[0])

    def test_update_to_skipped(self):
        items = _sample_items()
        result = update_item(items, 2, {"status": "skipped", "skip_reason": "FP"})
        self.assertTrue(result)
        self.assertEqual(items[1]["status"], "skipped")
        self.assertEqual(items[1]["skip_reason"], "FP")

    def test_update_to_in_progress(self):
        items = _sample_items()
        result = update_item(items, 1, {"status": "in_progress"})
        self.assertTrue(result)
        self.assertEqual(items[0]["status"], "in_progress")

    def test_update_to_needs_review(self):
        items = _sample_items()
        result = update_item(items, 3, {"status": "needs_review"})
        self.assertTrue(result)
        self.assertEqual(items[2]["status"], "needs_review")

    def test_explicit_fixed_at(self):
        items = _sample_items()
        ts = "2026-03-09T18:35:00Z"
        update_item(items, 1, {"status": "fixed", "fixed_at": ts})
        self.assertEqual(items[0]["fixed_at"], ts)

    def test_not_found(self):
        items = _sample_items()
        result = update_item(items, 99, {"status": "fixed"})
        self.assertFalse(result)

    def test_invalid_status(self):
        items = _sample_items()
        with self.assertRaises(ValueError):
            update_item(items, 1, {"status": "invalid"})


class TestUpdateItemsBatch(unittest.TestCase):
    """update_items_batch のテスト。"""

    def test_batch(self):
        items = _sample_items()
        updates = [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "skipped", "skip_reason": "FP"},
            {"id": 3, "status": "needs_review"},
        ]
        updated = update_items_batch(items, updates)
        self.assertEqual(updated, [1, 2, 3])
        self.assertEqual(items[1]["status"], "skipped")

    def test_missing_id(self):
        items = _sample_items()
        with self.assertRaises(ValueError):
            update_items_batch(items, [{"status": "fixed"}])

    def test_partial_match(self):
        items = _sample_items()
        updated = update_items_batch(items, [
            {"id": 1, "status": "fixed"},
            {"id": 99, "status": "skipped"},
        ])
        self.assertEqual(updated, [1])


class TestReadWritePlan(_FsTestCase):
    """read_plan / write_plan のラウンドトリップ。"""

    def test_roundtrip(self):
        items = _sample_items()
        self._write_plan(items)

        plan_data = read_plan(str(self.session_dir))
        self.assertEqual(len(plan_data["items"]), 3)

        # 更新して書き戻し
        update_item(plan_data["items"], 1, {
            "status": "fixed",
            "fixed_at": "2026-03-09T18:35:00Z",
            "files_modified": ["a.py", "b.py"],
        })
        write_plan(str(self.session_dir), plan_data)

        # 再読み込みで確認
        reloaded = read_plan(str(self.session_dir))
        item1 = reloaded["items"][0]
        self.assertEqual(item1["status"], "fixed")
        self.assertEqual(item1["fixed_at"], "2026-03-09T18:35:00Z")
        # files_modified は文字列リストとして読み込まれるはず
        self.assertIn("a.py", item1.get("files_modified", []))

    def test_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            read_plan(str(self.session_dir))


class TestCLI(_FsTestCase):
    """CLI 統合テスト。"""

    def test_single_update(self):
        self._write_plan(_sample_items())
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--id", "1", "--status", "fixed",
             "--files-modified", "a.py", "b.py"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["updated"], [1])

    def test_batch_update(self):
        self._write_plan(_sample_items())
        batch = {
            "updates": [
                {"id": 1, "status": "pending"},
                {"id": 2, "status": "skipped", "skip_reason": "FP"},
            ]
        }
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir), "--batch"],
            input=json.dumps(batch),
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["updated"], [1, 2])

    def test_missing_plan(self):
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--id", "1", "--status", "fixed"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_missing_args(self):
        self._write_plan(_sample_items())
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)

    def test_not_found_id(self):
        self._write_plan(_sample_items())
        proc = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir),
             "--id", "99", "--status", "fixed"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
