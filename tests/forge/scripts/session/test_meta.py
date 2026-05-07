"""session.meta のテスト。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "forge" / "scripts"),
)

from session.meta import SESSION_FIELD_ORDER, update_session_meta, update_session_meta_warning
from session.yaml_utils import read_yaml


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()
        (self.session_dir / "session.yaml").write_text(
            "\n".join([
                "skill: review",
                "started_at: 2026-05-06T00:00:00Z",
                "last_updated: 2026-05-06T00:00:00Z",
                "status: in_progress",
                "resume_policy: resume",
                "phase: created",
                "phase_status: in_progress",
                "focus: \"\"",
                "waiting_type: none",
                "waiting_reason: \"\"",
                "active_artifact: \"\"",
                "custom_field: keep",
                "",
            ]),
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestUpdateSessionMeta(_FsTestCase):
    def test_updates_meta_fields(self):
        result = update_session_meta(
            str(self.session_dir),
            {
                "phase": "context_ready",
                "phase_status": "completed",
                "focus": "line1\nline2",
                "active_artifact": "refs.yaml",
            },
        )

        self.assertEqual(result["status"], "ok")
        data = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(data["phase"], "context_ready")
        self.assertEqual(data["phase_status"], "completed")
        self.assertEqual(data["focus"], "line1 line2")
        self.assertEqual(data["active_artifact"], "refs.yaml")
        self.assertEqual(data["custom_field"], "keep")

    def test_waiting_type_none_clears_reason(self):
        update_session_meta(
            str(self.session_dir),
            {"waiting_type": "user_input", "waiting_reason": "needs answer"},
        )
        update_session_meta(
            str(self.session_dir),
            {"waiting_type": "none"},
        )

        data = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(data["waiting_type"], "none")
        self.assertEqual(data["waiting_reason"], "")

    def test_completed_phase_completes_session_status(self):
        update_session_meta(
            str(self.session_dir),
            {"phase": "completed", "phase_status": "completed"},
        )

        data = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(data["status"], "completed")

    def test_invalid_phase_status_raises(self):
        with self.assertRaises(ValueError):
            update_session_meta(
                str(self.session_dir), {"phase_status": "done"}
            )

    def test_field_order_keeps_meta_before_extra_fields(self):
        update_session_meta(
            str(self.session_dir),
            {"active_artifact": "plan.yaml"},
        )

        lines = (self.session_dir / "session.yaml").read_text(
            encoding="utf-8"
        ).splitlines()
        keys = [line.split(":", 1)[0] for line in lines if line]
        for field in SESSION_FIELD_ORDER:
            self.assertIn(field, keys)
        self.assertGreater(keys.index("custom_field"), keys.index("active_artifact"))


class TestUpdateSessionMetaWarning(unittest.TestCase):
    def test_missing_session_yaml_is_skipped(self):
        tmpdir = Path(tempfile.mkdtemp())
        try:
            session_dir = tmpdir / "review-abc123"
            session_dir.mkdir()
            result = update_session_meta_warning(
                str(session_dir), {"active_artifact": "plan.yaml"}
            )
            self.assertEqual(result["status"], "skipped")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
