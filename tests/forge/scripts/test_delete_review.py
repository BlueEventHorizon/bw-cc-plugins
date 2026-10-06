#!/usr/bin/env python3
"""delete_review.py の契約テスト。

- <review_id>/ をディレクトリごと削除し、他のレビューは残す
- 置き場が無くても成功する
- review_id が .temp/review/ の外を指しうる値のときは、何も削除せず失敗する
- 削除できないときは失敗する
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "review" / "delete_review.py"


def run(*args):
    completed = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    payload = json.loads(completed.stdout) if completed.stdout.strip() else None
    return completed.returncode, payload


class DeleteReviewTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.base = self.root / ".temp" / "review"
        self.review = self.base / "rid"
        (self.review / "1").mkdir(parents=True)
        (self.review / "review_request.json").write_text("{}", encoding="utf-8")
        (self.review / "1" / "review_result.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_deletes_whole_directory(self):
        self.assertEqual(run(str(self.root), "rid"), (0, {}))
        self.assertFalse(self.review.exists())

    def test_keeps_other_reviews(self):
        (self.base / "other").mkdir()
        run(str(self.root), "rid")
        self.assertTrue((self.base / "other").is_dir())

    def test_succeeds_when_missing(self):
        self.assertEqual(run(str(self.root), "nope"), (0, {}))
        self.assertTrue(self.review.is_dir())

    def test_succeeds_twice(self):
        run(str(self.root), "rid")
        self.assertEqual(run(str(self.root), "rid"), (0, {}))

    def test_rejects_review_ids_outside_review_dir(self):
        victim = self.root / "victim"
        victim.mkdir()
        (self.root / ".temp" / "sibling").mkdir()
        for bad in ("..", ".", "", "../victim", "a/b", "../../victim", "a\\b"):
            with self.subTest(review_id=bad):
                code, payload = run(str(self.root), bad)
                self.assertEqual(code, 1)
                self.assertIn("不正", payload["errors"][0])
        self.assertTrue(victim.is_dir())
        self.assertTrue((self.root / ".temp" / "sibling").is_dir())
        self.assertTrue(self.review.is_dir())

    def test_rejects_symlink(self):
        target = self.root / "victim"
        target.mkdir()
        (target / "f.txt").write_text("x", encoding="utf-8")
        link = self.base / "link"
        link.symlink_to(target, target_is_directory=True)
        code, payload = run(str(self.root), "link")
        self.assertEqual(code, 1)
        self.assertIn("シンボリックリンク", payload["errors"][0])
        self.assertTrue((target / "f.txt").is_file())

    @unittest.skipIf(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), "権限による拒否を再現できない")
    def test_fails_when_cannot_delete(self):
        os.chmod(self.review, 0o500)
        try:
            code, payload = run(str(self.root), "rid")
        finally:
            os.chmod(self.review, 0o700)
        self.assertEqual(code, 1)
        self.assertIn("削除できません", payload["errors"][0])


if __name__ == "__main__":
    unittest.main()
