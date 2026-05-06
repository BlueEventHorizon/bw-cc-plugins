"""session.store のテスト。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "forge" / "scripts"),
)

from session.store import SessionStore
from session.yaml_utils import read_yaml


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-abc123"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_session_yaml(self):
        (self.session_dir / "session.yaml").write_text(
            "\n".join([
                "skill: review",
                "started_at: 2026-05-06T00:00:00Z",
                "last_updated: 2026-05-06T00:00:00Z",
                "status: in_progress",
                "resume_policy: resume",
                "",
            ]),
            encoding="utf-8",
        )


class TestSessionStorePathSafety(_FsTestCase):
    def test_rejects_absolute_path(self):
        store = SessionStore(str(self.session_dir))
        with self.assertRaises(ValueError):
            store.write_text("/tmp/outside.yaml", "x", notify=False)

    def test_rejects_traversal(self):
        store = SessionStore(str(self.session_dir))
        with self.assertRaises(ValueError):
            store.write_text("../outside.yaml", "x", notify=False)

    def test_rejects_nested_traversal(self):
        store = SessionStore(str(self.session_dir))
        with self.assertRaises(ValueError):
            store.write_text("refs/../../outside.yaml", "x", notify=False)


class TestSessionStoreWrite(_FsTestCase):
    def test_write_text_creates_file(self):
        store = SessionStore(str(self.session_dir))
        path = store.write_text("refs.yaml", "target_files:\n  - a.py\n", notify=False)

        self.assertEqual(path, self.session_dir / "refs.yaml")
        self.assertEqual(
            (self.session_dir / "refs.yaml").read_text(encoding="utf-8"),
            "target_files:\n  - a.py\n",
        )

    def test_write_text_notifies_artifact(self):
        store = SessionStore(str(self.session_dir))
        with mock.patch("session.store.notify_session_update") as notify:
            store.write_text("refs.yaml", "x\n", notify=True)

        notify.assert_called_once_with(
            str(self.session_dir), str(self.session_dir / "refs.yaml")
        )

    def test_write_text_updates_meta_after_artifact(self):
        self._write_session_yaml()
        store = SessionStore(str(self.session_dir))

        store.write_text(
            "plan.yaml",
            "items:\n  - id: 1\n    status: pending\n",
            notify=False,
            meta={"active_artifact": "plan.yaml"},
        )

        session = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(session["active_artifact"], "plan.yaml")

    def test_write_nested_yaml(self):
        store = SessionStore(str(self.session_dir))

        path = store.write_nested_yaml(
            "refs.yaml",
            [("target_files", ["a.py"]), ("reference_docs", [{"path": "docs/r.md"}])],
        )

        self.assertEqual(path, self.session_dir / "refs.yaml")
        data = read_yaml(str(path))
        self.assertEqual(data["target_files"], ["a.py"])
        self.assertEqual(data["reference_docs"][0]["path"], "docs/r.md")

    def test_meta_failure_does_not_fail_artifact_write(self):
        store = SessionStore(str(self.session_dir))

        path = store.write_text(
            "refs.yaml",
            "target_files:\n  - a.py\n",
            notify=False,
            meta={"active_artifact": "refs.yaml"},
        )

        self.assertEqual(path, self.session_dir / "refs.yaml")
        self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
