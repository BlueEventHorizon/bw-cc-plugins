"""msg-review 固有の送信 wrapper テスト。"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "msg-review"
    / "scripts"
    / "send_review_and_await_reply.py"
)

spec = importlib.util.spec_from_file_location("msg_review_send_wrapper", SCRIPT_PATH)
send_wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(send_wrapper)


class SendReviewAndAwaitReplyTest(unittest.TestCase):
    def _args(self, body_file: Path, *extra: str):
        return send_wrapper.parse_args(
            [
                "claude",
                "codex",
                "--review-type",
                "code",
                "--review-id",
                "rid-1",
                "--round",
                "2",
                "--body-file",
                str(body_file),
                "--header-regex",
                r"review_id=(\S+)",
                *extra,
            ]
        )

    def test_adds_wire_header_delegates_once_and_removes_temporary_body(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "common.md"
            body_file.write_text("共通本文\n", encoding="utf-8")
            observed = {}

            def runner(command):
                wire_path = Path(command[command.index("--body-file") + 1])
                observed["command"] = command
                observed["wire_path"] = wire_path
                observed["wire_body"] = wire_path.read_text(encoding="utf-8")
                return SimpleNamespace(returncode=7)

            result = send_wrapper.run(self._args(body_file), runner=runner)

            self.assertEqual(result, 7)
            self.assertEqual(
                observed["wire_body"],
                "[msg-review] code review_id=rid-1 round=2\n共通本文\n",
            )
            self.assertFalse(observed["wire_path"].exists())
            self.assertEqual(observed["command"][0], send_wrapper.sys.executable)
            self.assertEqual(
                Path(observed["command"][1]),
                REPO_ROOT
                / "plugins"
                / "forge"
                / "scripts"
                / "msg-sys"
                / "send_and_await_reply.py",
            )
            self.assertEqual(observed["command"].count("--body-file"), 1)

    def test_reuses_wire_body_add_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "common.md"
            body_file.write_text("共通本文", encoding="utf-8")
            with mock.patch.object(
                send_wrapper.wire_body,
                "add_header",
                return_value="wire",
            ) as add_header:
                send_wrapper.run(
                    self._args(body_file),
                    runner=lambda command: SimpleNamespace(returncode=0),
                )

            add_header.assert_called_once_with("共通本文", "code", "rid-1", 2)

    def test_forwards_common_optional_arguments_without_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "common.md"
            body_file.write_text("共通本文", encoding="utf-8")
            observed = {}

            def runner(command):
                observed["command"] = command
                return SimpleNamespace(returncode=0)

            send_wrapper.run(
                self._args(
                    body_file,
                    "--in-reply-to",
                    "message 1",
                    "--project-root",
                    "/tmp/project root",
                    "--db-path",
                    "/tmp/project root/messages.db",
                    "--max-seconds",
                    "3",
                    "--progress-interval",
                    "1",
                    "--initial-interval",
                    "0.1",
                    "--backoff-factor",
                    "1.5",
                    "--max-interval",
                    "2",
                    "--no-wake",
                ),
                runner=runner,
            )

            command = observed["command"]
            self.assertIsInstance(command, list)
            self.assertIn("message 1", command)
            self.assertIn("/tmp/project root", command)
            self.assertIn("--no-wake", command)

    def test_removes_temporary_body_when_delegate_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "common.md"
            body_file.write_text("共通本文", encoding="utf-8")
            observed = {}

            def runner(command):
                observed["wire_path"] = Path(command[command.index("--body-file") + 1])
                raise OSError("delegate failed")

            with self.assertRaisesRegex(OSError, "delegate failed"):
                send_wrapper.run(self._args(body_file), runner=runner)

            self.assertFalse(observed["wire_path"].exists())


if __name__ == "__main__":
    unittest.main()
