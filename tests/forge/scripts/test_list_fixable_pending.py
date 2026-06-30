#!/usr/bin/env python3
"""list_fixable_pending.py のテスト。

実行:
    python3 -m unittest tests.forge.scripts.test_list_fixable_pending -v
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "list_fixable_pending.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


class TestListFixablePending(unittest.TestCase):
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

    def test_filters_to_fixable_pending(self):
        self._write_plan("""  - id: 1
    severity: critical
    priority: P1
    status: pending
    recommendation: fix
    auto_fixable: true
  - id: 2
    severity: critical
    priority: P2
    status: pending
    recommendation: fix
    auto_fixable: false
  - id: 3
    severity: major
    priority: P1
    status: fixed
    recommendation: fix
    auto_fixable: true
  - id: 4
    severity: minor
    priority: P3
    status: pending
    recommendation: skip
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual([it["id"] for it in d["items"]], [1])

    def test_sorted_by_severity_then_priority(self):
        self._write_plan("""  - id: 1
    severity: major
    priority: P2
    status: pending
    recommendation: fix
    auto_fixable: true
  - id: 2
    severity: critical
    priority: P1
    status: pending
    recommendation: fix
    auto_fixable: true
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual([it["id"] for it in d["items"]], [2, 1])

    def test_positional_only_rejects_flags(self):
        r = _run(str(self.session_dir), "--filter", "x")
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
