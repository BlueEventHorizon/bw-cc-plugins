#!/usr/bin/env python3
"""
scan_secrets.py のテスト（REQ-013 FNC-1315）

機密情報の機械検出。検出力（false negative を出さない）とマスク（検出値を出力へ漏らさない）
の両方を検証する。とくにマスク漏れは、検出行為そのものが漏洩経路になるため最優先で守る。

実行:
  python3 -m unittest tests.forge.review.test_scan_secrets -v
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PATH = (
    _REPO_ROOT / "plugins" / "forge" / "skills" / "review" / "scripts" / "scan_secrets.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan_secrets = _load(_SCRIPT_PATH, "forge_scan_secrets")

# テスト用の偽の秘密。実在の値ではなく、形式だけを満たすように構成している
# （`sensitive_information_spec.md` §4: 実在の値を改変したものは使わない）。
AWS_KEY = "AKIA" + "Z7Q2WXYVBN4KLMPD"
GITHUB_TOKEN = "ghp_" + "9Xk2LmQ7vRt4WsZa8BnCd3EfGh5JiKl6MnOp"
SLACK_TOKEN = "xoxb-" + "2417365981-4Kq7Wm3Rt9Yv"
GOOGLE_KEY = "AIza" + "SyD3kL9mQ2vXt7Rw4Zc8Nb1Hf6Js0Pe5Ugh"
STRIPE_KEY = "sk_live_" + "4Kq7Wm3Rt9YvXz2Bn"
NPM_TOKEN = "npm_" + "K3m9Qv2Xt7Rw4Zc8Nb1Hf6Js0Pe5Ug2Ld4Ab"
JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"  # secrets-scan: ignore
)
HIGH_ENTROPY = "9f8Ld2Qm4Xr7Tb1Yv6Zc3Nk5Hs0Jw8Pe"


def _scan_source(text: str) -> dict:
    """テキストを一時ファイルへ書いて走査する。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "sample.txt").write_text(text, encoding="utf-8")
        return scan_secrets.scan(root, ["sample.txt"])


def _rules(result: dict) -> set[str]:
    return {finding["rule"] for finding in result["findings"]}


class DetectionTest(unittest.TestCase):
    """既知形式を取りこぼさないこと（false negative を出さない）。"""

    def test_prefixed_tokens_detected(self):
        cases = {
            "aws_access_key_id": AWS_KEY,
            "github_token": GITHUB_TOKEN,
            "slack_token": SLACK_TOKEN,
            "google_api_key": GOOGLE_KEY,
            "stripe_live_key": STRIPE_KEY,
            "npm_token": NPM_TOKEN,
            "jwt": JWT,
        }
        for rule, value in cases.items():
            with self.subTest(rule=rule):
                result = _scan_source(f"credential is {value} here\n")
                self.assertIn(rule, _rules(result))

    def test_private_key_block_detected(self):
        header = "-----BEGIN RSA " + "PRIVATE KEY-----"
        result = _scan_source(f"{header}\n")
        self.assertIn("private_key_block", _rules(result))

    def test_plain_private_key_header_detected(self):
        header = "-----BEGIN " + "PRIVATE KEY-----"
        result = _scan_source(f"{header}\n")
        self.assertIn("private_key_block", _rules(result))

    def test_connection_string_with_credentials_detected(self):
        uri = "postgres://svcuser:" + "R7k2LmQ9vXt4Ws" + "@db.internal:5432/app"
        result = _scan_source(f"{uri}\n")
        self.assertIn("connection_string_with_credentials", _rules(result))

    def test_assignment_to_secret_like_key_detected(self):
        result = _scan_source(f'api_key = "{HIGH_ENTROPY}"\n')
        self.assertIn("assignment_to_secret_like_key", _rules(result))

    def test_detection_reports_position(self):
        result = _scan_source(f"line one\nline two\napi_key = \"{HIGH_ENTROPY}\"\n")
        finding = result["findings"][0]
        self.assertEqual(finding["line"], 3)
        self.assertEqual(finding["path"], "sample.txt")


class MaskingTest(unittest.TestCase):
    """検出値の実体を出力へ載せないこと [MANDATORY]（spec §5.3）。"""

    def test_output_never_contains_the_raw_value(self):
        for value in (AWS_KEY, GITHUB_TOKEN, JWT, HIGH_ENTROPY):
            with self.subTest(value=value[:8]):
                result = _scan_source(f'secret_token = "{value}"\n')
                serialized = json.dumps(result, ensure_ascii=False)
                self.assertNotIn(value, serialized)

    def test_mask_keeps_only_a_short_prefix(self):
        masked = scan_secrets.mask(AWS_KEY)
        self.assertTrue(masked.startswith(AWS_KEY[:4]))
        self.assertNotIn(AWS_KEY[4:], masked)
        self.assertIn(str(len(AWS_KEY)), masked)

    def test_short_values_have_no_prefix_exposed(self):
        """短い値は先頭も出さない（残りを推測されやすいため）。"""
        self.assertEqual(scan_secrets.mask("abc123"), "***[6文字]")

    def test_finding_records_carry_no_value_key(self):
        """build_review_request 側の防波堤が前提とするキー構成を守ること。"""
        result = _scan_source(f"aws = {AWS_KEY}\n")
        for finding in result["findings"]:
            self.assertEqual(
                set(finding), {"path", "line", "rule", "masked", "length"}
            )


class FalsePositiveTest(unittest.TestCase):
    """誤検出が支配的にならないこと（レビュアーが流し読みし始める）。"""

    def test_placeholder_not_reported(self):
        for value in ("<your-api-key>", "${API_KEY}", "$FIGMA_TOKEN", "xxxxxxxxxxxx"):
            with self.subTest(value=value):
                result = _scan_source(f'api_key = "{value}"\n')
                self.assertEqual(result["findings"], [])

    def test_environment_lookup_not_reported(self):
        result = _scan_source('api_key = os.environ["KEY"]\n')
        self.assertEqual(result["findings"], [])

    def test_code_expression_not_reported(self):
        result = _scan_source("token = tokens[i].decode(errors)\n")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["counts"]["filtered"]["code_expression"], 1)

    def test_checksum_table_not_reported(self):
        """`design_token_template.md: <sha256>` 形式を秘密と誤認しないこと。"""
        digest = "f1c6a877274047043cd1cd7226de6813ad0d6c66f5dd894df35416f24b3c5b93"
        result = _scan_source(f"  docs/design_token_template.md: {digest}\n")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["counts"]["filtered"]["path_like"], 1)

    def test_bare_hex_digest_not_reported(self):
        """hex 単独では報告しない（チェックサムが支配的になるため）。"""
        digest = "b791ef2d1ad781c38a19c6edc7495e95221d202e376bb6d684912801b23a6129"
        result = _scan_source(f"sha256 of the file is {digest}\n")
        self.assertEqual(result["findings"], [])

    def test_long_path_not_reported_as_high_entropy(self):
        result = _scan_source(
            "docs/specs/forge/design/DES-055_review_request_template_design.md\n"
        )
        self.assertEqual(result["findings"], [])

    def test_prose_value_with_japanese_not_reported(self):
        result = _scan_source("Authority: Tool-provided（forge 内蔵）/ Project-defined\n")
        self.assertEqual(result["findings"], [])

    def test_notation_word_not_reported(self):
        """`scheme://user:password@host` のような記法説明を秘密と誤認しないこと。"""
        result = _scan_source("接続文字列は `postgres://user:password@host/db` 形式\n")
        self.assertEqual(result["findings"], [])


class SuppressionTest(unittest.TestCase):
    """抑制マーカーは分類するだけで、破棄しないこと（spec §5.2）。"""

    def test_suppressed_finding_is_separated_not_dropped(self):
        result = _scan_source(f"aws = {AWS_KEY}  # secrets-scan: ignore\n")
        self.assertEqual(result["findings"], [])
        self.assertEqual(len(result["suppressed"]), 1)
        self.assertEqual(result["counts"]["suppressed"], 1)

    def test_suppressed_record_has_same_shape(self):
        result = _scan_source(f"aws = {AWS_KEY}  # secrets-scan: ignore\n")
        self.assertEqual(
            set(result["suppressed"][0]), {"path", "line", "rule", "masked", "length"}
        )

    def test_marker_itself_is_not_detected(self):
        """マーカー文字列自体を検出しないこと。

        `secrets-scan: ignore` は「秘密らしいキーへの代入」の形をしているため、
        除外しないとマーカーを置いた行やマーカーを説明した文書が自分自身を検出する。
        """
        result = _scan_source("行末に `secrets-scan: ignore` と書くと分類される\n")
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["suppressed"], [])

    def test_marker_on_one_line_does_not_affect_others(self):
        result = _scan_source(
            f"a = {AWS_KEY}  # secrets-scan: ignore\nb = {GITHUB_TOKEN}\n"
        )
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(len(result["suppressed"]), 1)


class DeduplicationTest(unittest.TestCase):
    def test_substring_of_reported_value_not_reported_twice(self):
        """JWT 全体を報告したあと、その署名部分を再報告しないこと。"""
        result = _scan_source(f"token = {JWT}\n")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule"], "jwt")


class SkipTest(unittest.TestCase):
    """走査できなかったファイルを黙って落とさないこと。"""

    def test_binary_file_recorded_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "blob.bin").write_bytes(b"\x00\x01\x02" + AWS_KEY.encode())
            result = scan_secrets.scan(root, ["blob.bin"])
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["skipped"][0]["reason"], "binary")
        self.assertEqual(result["counts"]["skipped_files"], 1)

    def test_oversized_file_recorded_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "big.txt").write_text(
                "a" * (scan_secrets.MAX_FILE_BYTES + 1), encoding="utf-8"
            )
            result = scan_secrets.scan(root, ["big.txt"])
        self.assertEqual(result["skipped"][0]["reason"], "too_large")

    def test_missing_file_recorded_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_secrets.scan(Path(tmpdir), ["nope.txt"])
        self.assertEqual(result["skipped"][0]["reason"], "not_a_file")


class EntropyTest(unittest.TestCase):
    def test_monotone_string_has_zero_entropy(self):
        self.assertEqual(scan_secrets.shannon_entropy("aaaa"), 0.0)

    def test_empty_string_has_zero_entropy(self):
        self.assertEqual(scan_secrets.shannon_entropy(""), 0.0)

    def test_mixed_string_has_positive_entropy(self):
        self.assertGreater(scan_secrets.shannon_entropy("ab"), 0.0)


class CliTest(unittest.TestCase):
    def _run(self, argv):
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_PATH)] + argv,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout, result.stderr

    def test_paths_json_scan_succeeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "a.txt").write_text(f"aws = {AWS_KEY}\n", encoding="utf-8")
            returncode, stdout, _ = self._run(
                ["--project-root", tmpdir, "--paths-json", json.dumps(["a.txt"])]
            )
        self.assertEqual(returncode, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["counts"]["findings"], 1)
        self.assertNotIn(AWS_KEY, stdout)

    def test_invalid_paths_json_exits_nonzero(self):
        returncode, stdout, _ = self._run(["--paths-json", "not json"])
        self.assertNotEqual(returncode, 0)
        self.assertEqual(json.loads(stdout)["status"], "error")

    def test_non_string_paths_rejected(self):
        returncode, stdout, _ = self._run(["--paths-json", json.dumps([1, 2])])
        self.assertNotEqual(returncode, 0)
        self.assertEqual(json.loads(stdout)["status"], "error")

    def test_repository_scan_is_clean(self):
        """本リポジトリ自身に混入がないこと（回帰検出も兼ねる）。"""
        returncode, stdout, stderr = self._run(["--project-root", str(_REPO_ROOT)])
        self.assertEqual(returncode, 0, stderr)
        payload = json.loads(stdout)
        self.assertEqual(
            payload["counts"]["findings"],
            0,
            f"混入の疑いが検出されました: {payload['findings']}",
        )


if __name__ == "__main__":
    unittest.main()
