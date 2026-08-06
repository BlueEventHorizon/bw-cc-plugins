"""msg-review 固有ワイヤヘッダの構築・分離テスト。"""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "plugins"
    / "forge"
    / "skills"
    / "msg-review"
    / "scripts"
    / "wire_body.py"
)

spec = importlib.util.spec_from_file_location("msg_review_wire_body", SCRIPT_PATH)
wire_body = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire_body)


class WireBodyTest(unittest.TestCase):
    def test_adds_expected_header_immediately_before_send(self):
        result = wire_body.add_header("## レビュー依頼\n", "diff", "rid", 2)
        self.assertEqual(
            result.splitlines()[0],
            "[msg-review] diff review_id=rid round=2",
        )
        self.assertIn("## レビュー依頼", result)

    def test_rejects_existing_header_anywhere(self):
        with self.assertRaises(ValueError):
            wire_body.add_header(
                "本文\n[msg-review] diff review_id=x round=1\n", "diff", "rid", 1
            )

    def test_add_allows_plain_msg_review_mention(self):
        body = "説明では `[msg-review]` を識別子として扱います。\n"
        result = wire_body.add_header(body, "diff", "rid", 1)
        self.assertEqual(result.splitlines()[1], body.strip())

    def test_rejects_header_field_injection(self):
        with self.assertRaises(ValueError):
            wire_body.add_header("本文", "diff\nrogue", "rid", 1)

    def test_strips_and_validates_response_header(self):
        body = "[msg-review] diff review_id=rid round=2\n所見\n"
        self.assertEqual(wire_body.strip_header(body, "diff", "rid", 2), "所見\n")

    def test_strip_keeps_response_without_repeated_header(self):
        body = "所見\nREVIEW_RESULT: approved\n"
        self.assertEqual(wire_body.strip_header(body, "diff", "rid", 2), body)

    def test_strip_rejects_malformed_repeated_header(self):
        with self.assertRaises(ValueError):
            wire_body.strip_header("[msg-review] malformed\n所見\n", "diff", "rid", 2)

    def test_strip_rejects_header_from_different_round(self):
        body = "[msg-review] diff review_id=rid round=1\n所見\n"
        with self.assertRaisesRegex(ValueError, "現在のラウンドと一致しません"):
            wire_body.strip_header(body, "diff", "rid", 2)

    def test_strip_rejects_header_with_different_review_id(self):
        body = "[msg-review] diff review_id=other round=2\n所見\n"
        with self.assertRaisesRegex(ValueError, "現在のラウンドと一致しません"):
            wire_body.strip_header(body, "diff", "rid", 2)

    def test_strip_rejects_header_with_different_pattern(self):
        body = "[msg-review] docs review_id=rid round=2\n所見\n"
        with self.assertRaisesRegex(ValueError, "現在のラウンドと一致しません"):
            wire_body.strip_header(body, "diff", "rid", 2)

    def test_cli_add_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.txt"
            output_file = Path(tmpdir) / "wire.txt"
            body_file.write_text("本文\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    "--mode",
                    "add",
                    "--pattern",
                    "code",
                    "--review-id",
                    "rid",
                    "--round",
                    "1",
                    "--body-file",
                    str(body_file),
                    "--output-file",
                    str(output_file),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output_file.read_text(encoding="utf-8").startswith("[msg-review]"))

    def test_cli_strip_requires_expected_header_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.txt"
            output_file = Path(tmpdir) / "pure.txt"
            body_file.write_text("所見\n", encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    "--mode",
                    "strip",
                    "--body-file",
                    str(body_file),
                    "--output-file",
                    str(output_file),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("strip には pattern、review-id、round が必要", result.stderr)

    def test_cli_strip_accepts_matching_expected_header_values(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.txt"
            output_file = Path(tmpdir) / "pure.txt"
            body_file.write_text(
                "[msg-review] code review_id=rid round=3\n所見\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_PATH),
                    "--mode",
                    "strip",
                    "--pattern",
                    "code",
                    "--review-id",
                    "rid",
                    "--round",
                    "3",
                    "--body-file",
                    str(body_file),
                    "--output-file",
                    str(output_file),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output_file.read_text(encoding="utf-8"), "所見\n")


if __name__ == "__main__":
    unittest.main()
