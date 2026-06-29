#!/usr/bin/env python3
"""review_session.py wrapper のテスト。

5 動詞 (probe / start / resume / finish / status) を CLI 経由でテストする。
標準ライブラリのみ使用。

実行:
    python3 -m unittest tests.forge.review.test_review_session -v
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
WRAPPER = REPO_ROOT / "plugins" / "forge" / "skills" / "review" / "scripts" / "review_session.py"

VALID_REFS = {
    "target_files": ["src/foo.py"],
    "reference_docs": [{"path": "docs/rules.md"}],
    "review_packet": {
        "criteria_path": "review/docs/review_criteria_code.md",
        "ssot_refs": [
            {"doc_path": "docs/rules/implementation_guidelines.md",
             "priority": "P1", "doc_type": "rules"},
        ],
        "check_order": ["P1", "P2", "P3"],
        "severity_source": "principles",
        "output_path": "review_code.md",
    },
}


class ReviewSessionTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".claude" / ".temp").mkdir(parents=True, exist_ok=True)
        self.orig_cwd = os.getcwd()
        os.chdir(self.tmpdir)

    def tearDown(self):
        os.chdir(self.orig_cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_wrapper(self, *args, input_data=None):
        return subprocess.run(
            [sys.executable, str(WRAPPER), *args],
            input=input_data,
            capture_output=True,
            text=True,
            cwd=self.tmpdir,
        )


class TestProbe(ReviewSessionTestBase):
    def test_state_none_when_no_session(self):
        r = self.run_wrapper("probe")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["state"], "none")

    def test_state_resumable_after_start(self):
        # start で session 作成
        r = self.run_wrapper(
            "start", "--review-type", "code", "--engine", "claude",
            input_data=json.dumps(VALID_REFS),
        )
        self.assertEqual(r.returncode, 0, r.stderr)

        # probe で検出
        r = self.run_wrapper("probe")
        data = json.loads(r.stdout)
        self.assertEqual(data["state"], "resumable")
        self.assertIn("session_dir", data)


class TestStart(ReviewSessionTestBase):
    def test_creates_session_with_refs(self):
        r = self.run_wrapper(
            "start", "--review-type", "code",
            input_data=json.dumps(VALID_REFS),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertIn("session_dir", data)
        self.assertTrue(data["refs_written"])

        # ファイル実在確認
        session_dir = self.tmpdir / data["session_dir"]
        self.assertTrue((session_dir / "session.yaml").is_file())
        self.assertTrue((session_dir / "refs.yaml").is_file())

    def test_invalid_refs_rolls_back_session(self):
        """refs バリデーション失敗時は作成した session を片付ける"""
        bad_refs = {"target_files": [], "review_packet": {}}  # target_files 空 = invalid
        r = self.run_wrapper(
            "start", "--review-type", "code",
            input_data=json.dumps(bad_refs),
        )
        self.assertNotEqual(r.returncode, 0)
        # session が残っていないこと
        leftovers = list((self.tmpdir / ".claude" / ".temp").glob("review-*"))
        self.assertEqual(leftovers, [])

    def test_review_metadata_persisted(self):
        r = self.run_wrapper(
            "start", "--review-type", "design", "--engine", "gemini",
            "--interaction", "auto", "--auto-count", "5",
            input_data=json.dumps({
                **VALID_REFS,
                "review_packet": {**VALID_REFS["review_packet"], "output_path": "review_design.md"},
            }),
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        session_dir = self.tmpdir / json.loads(r.stdout)["session_dir"]

        # session.yaml にメタが書かれている
        text = (session_dir / "session.yaml").read_text()
        self.assertIn("review_type: design", text)
        self.assertIn("engine: gemini", text)
        self.assertIn("interaction: auto", text)
        self.assertIn("auto_count: 5", text)


class TestResume(ReviewSessionTestBase):
    def _start(self):
        r = self.run_wrapper(
            "start", "--review-type", "code",
            input_data=json.dumps(VALID_REFS),
        )
        return json.loads(r.stdout)["session_dir"]

    def test_resume_returns_next_phase_reviewer_when_no_review_md(self):
        session_dir = self._start()
        r = self.run_wrapper("resume", session_dir)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["next_phase"], "reviewer")

    def test_resume_returns_evaluator_when_review_md_exists(self):
        session_dir = self._start()
        # reviewer 出力を模擬
        (self.tmpdir / session_dir / "review_code.md").write_text("# review\n")
        r = self.run_wrapper("resume", session_dir)
        data = json.loads(r.stdout)
        self.assertEqual(data["next_phase"], "evaluator")

    def test_resume_returns_present_when_pending_items(self):
        session_dir = self._start()
        (self.tmpdir / session_dir / "review_code.md").write_text("# review\n")
        # plan.yaml に pending を 1 件含める (簡易 YAML)
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: pending\n"
            "    severity: warning\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("resume", session_dir)
        data = json.loads(r.stdout)
        self.assertEqual(data["next_phase"], "present")

    def test_resume_returns_finish_when_all_processed(self):
        session_dir = self._start()
        (self.tmpdir / session_dir / "review_code.md").write_text("# review\n")
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: fixed\n"
            "    severity: warning\n"
            "  - id: F2\n"
            "    status: skipped\n"
            "    severity: info\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("resume", session_dir)
        data = json.loads(r.stdout)
        self.assertEqual(data["next_phase"], "finish")


class TestFinish(ReviewSessionTestBase):
    def test_finish_removes_session(self):
        r = self.run_wrapper(
            "start", "--review-type", "code",
            input_data=json.dumps(VALID_REFS),
        )
        session_dir = json.loads(r.stdout)["session_dir"]
        self.assertTrue((self.tmpdir / session_dir).exists())

        r = self.run_wrapper("finish", session_dir)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["status"], "finished")
        self.assertFalse((self.tmpdir / session_dir).exists())


class TestStatus(ReviewSessionTestBase):
    def _start(self):
        r = self.run_wrapper(
            "start", "--review-type", "code",
            input_data=json.dumps(VALID_REFS),
        )
        return json.loads(r.stdout)["session_dir"]

    def test_status_no_plan(self):
        session_dir = self._start()
        r = self.run_wrapper("status", session_dir)
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertFalse(data["plan_present"])
        self.assertEqual(data["next_action"], "evaluator")

    def test_status_fixable_pending_routes_to_fix(self):
        session_dir = self._start()
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: pending\n"
            "    severity: warning\n"
            "    recommendation: fix\n"
            "    auto_fixable: true\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("status", session_dir)
        data = json.loads(r.stdout)
        self.assertTrue(data["plan_present"])
        self.assertEqual(data["unprocessed_total"], 1)
        self.assertEqual(data["fixable_pending"], 1)
        self.assertEqual(data["next_action"], "fix")

    def test_status_pending_without_auto_fix_routes_to_present(self):
        session_dir = self._start()
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: pending\n"
            "    severity: warning\n"
            "    recommendation: needs_review\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("status", session_dir)
        data = json.loads(r.stdout)
        self.assertEqual(data["next_action"], "present")

    def test_status_all_processed_routes_to_finish(self):
        session_dir = self._start()
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: fixed\n"
            "    severity: major\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("status", session_dir)
        data = json.loads(r.stdout)
        self.assertEqual(data["unprocessed_total"], 0)
        self.assertEqual(data["next_action"], "finish")

    def test_status_by_severity_uses_critical_major_minor_domain(self):
        """by_severity の集計 dict が critical/major/minor ドメインを使うこと。

        旧実装は warning/info を集計対象としていたため、plan.yaml の major/minor が
        unknown に分類されていた。findings_renderer.py SEVERITY_ORDER と一致させる。
        """
        session_dir = self._start()
        plan_text = (
            "items:\n"
            "  - id: F1\n"
            "    status: pending\n"
            "    severity: critical\n"
            "  - id: F2\n"
            "    status: pending\n"
            "    severity: major\n"
            "  - id: F3\n"
            "    status: pending\n"
            "    severity: major\n"
            "  - id: F4\n"
            "    status: pending\n"
            "    severity: minor\n"
        )
        (self.tmpdir / session_dir / "plan.yaml").write_text(plan_text)
        r = self.run_wrapper("status", session_dir)
        data = json.loads(r.stdout)
        self.assertIn("critical", data["by_severity"])
        self.assertIn("major", data["by_severity"])
        self.assertIn("minor", data["by_severity"])
        self.assertEqual(data["by_severity"]["critical"], 1)
        self.assertEqual(data["by_severity"]["major"], 2)
        self.assertEqual(data["by_severity"]["minor"], 1)
        self.assertEqual(data["by_severity"]["unknown"], 0)


if __name__ == "__main__":
    unittest.main()
