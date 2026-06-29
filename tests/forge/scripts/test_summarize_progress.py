#!/usr/bin/env python3
"""summarize_progress.py のテスト。

実行:
    python3 -m unittest tests.forge.scripts.test_summarize_progress -v
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "summarize_progress.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )


class TestSummarizeProgress(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "sample"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plan(self, items_yaml):
        (self.session_dir / "plan.yaml").write_text(f"items:\n{items_yaml}")

    def test_plan_missing_next_action_present(self):
        r = _run(str(self.session_dir))
        self.assertEqual(r.returncode, 0)
        d = json.loads(r.stdout)
        self.assertFalse(d["plan_present"])
        self.assertEqual(d["next_action"], "present")

    def test_next_action_finish_when_all_resolved(self):
        self._write_plan("""  - id: 1
    severity: critical
    status: fixed
  - id: 2
    severity: minor
    status: skipped
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["unprocessed_total"], 0)
        self.assertEqual(d["next_action"], "finish")

    def test_next_action_present_when_all_pending_untouched(self):
        self._write_plan("""  - id: 1
    severity: critical
    status: pending
    recommendation: fix
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["next_action"], "present")

    def test_next_action_resume_prompt_with_in_progress(self):
        self._write_plan("""  - id: 1
    severity: critical
    status: in_progress
  - id: 2
    severity: minor
    status: pending
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["next_action"], "resume_prompt")

    def test_next_action_resume_prompt_when_some_done(self):
        self._write_plan("""  - id: 1
    severity: critical
    status: fixed
  - id: 2
    severity: minor
    status: pending
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["next_action"], "resume_prompt")

    def test_fixable_pending_and_create_issue_pending_counts(self):
        self._write_plan("""  - id: 1
    severity: critical
    status: pending
    recommendation: fix
    auto_fixable: true
  - id: 2
    severity: major
    status: pending
    recommendation: fix
    auto_fixable: false
  - id: 3
    severity: critical
    status: pending
    recommendation: create_issue
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["fixable_pending"], 1)
        self.assertEqual(d["create_issue_pending"], 1)

    def test_positional_only_rejects_flags(self):
        r = _run(str(self.session_dir), "--foo", "bar")
        self.assertNotEqual(r.returncode, 0)

    def test_next_action_present_when_evaluator_skipped_some(self):
        """evaluator が初期に一部 finding を skipped にしただけの状態は initial present。

        旧実装は skipped > 0 を「中断」と誤判定して resume_prompt を返した (Issue: 今回観測)。
        skipped は決着状態であり中断指標ではない。
        """
        self._write_plan("""  - id: 1
    severity: critical
    status: pending
    recommendation: fix
  - id: 2
    severity: minor
    status: skipped
    recommendation: skip
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["next_action"], "present")

    def test_next_action_finish_when_all_skipped(self):
        """全件 skipped で pending/in_progress 0 件なら finish。"""
        self._write_plan("""  - id: 1
    severity: major
    status: skipped
    recommendation: skip
  - id: 2
    severity: minor
    status: skipped
    recommendation: skip
""")
        r = _run(str(self.session_dir))
        d = json.loads(r.stdout)
        self.assertEqual(d["next_action"], "finish")


if __name__ == "__main__":
    unittest.main()
