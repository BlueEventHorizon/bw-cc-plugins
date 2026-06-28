#!/usr/bin/env python3
"""list_items_sorted.py のテスト。

DES-024 §2.3 (位置引数のみ) 準拠を検証。標準ライブラリのみ使用。

実行:
    python3 -m unittest tests.forge.scripts.test_list_items_sorted -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "list_items_sorted.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


class TestListItemsSorted(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "sample"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plan(self, items_yaml):
        (self.session_dir / "plan.yaml").write_text(f"items:\n{items_yaml}")

    def test_plan_missing(self):
        r = _run(str(self.session_dir))
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertFalse(d["plan_present"])
        self.assertEqual(d["items"], [])

    def test_sort_by_severity_then_priority(self):
        self._write_plan("""  - id: 1
    severity: major
    priority: P2
  - id: 2
    severity: critical
    priority: P1
  - id: 3
    severity: minor
    priority: P3
  - id: 4
    severity: critical
    priority: P2
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        ids = [it["id"] for it in d["items"]]
        # critical/P1=2, critical/P2=4, major/P2=1, minor/P3=3
        self.assertEqual(ids, [2, 4, 1, 3])

    def test_priority_none_goes_last(self):
        self._write_plan("""  - id: 1
    severity: critical
    priority: P1
  - id: 2
    severity: critical
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual([it["id"] for it in d["items"]], [1, 2])

    def test_positional_only_rejects_flags(self):
        """DES-024 §2.3: 位置引数のみ。--filter 等を受け取らないこと"""
        r = _run(str(self.session_dir), "--filter", "status:pending")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
