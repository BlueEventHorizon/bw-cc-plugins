"""inspect_ci_status.py の単体テスト（anvil:create-pr Phase 6）。

`gh pr checks` の終了コードが 3 状態（成功 / 失敗 / 未登録）を同じ値へ畳み込むため、本 script は
状態を語で返す。そのため固定すべきは **bucket の組み合わせから状態語への写像** である。

とくに次は終了コードでは表せず、誤った分岐が静かに通る形であり、テストで固定しないと再発する。

- チェック未登録（`not_reported`）を失敗と区別すること（PR 作成直後に必ず通る状態）
- 失敗と実行中が混在するとき、失敗を優先すること
- キャンセルを失敗と別の語にすること
- スキップを成功に含めること
- 未知の bucket を黙って捨てず、エラーにすること

`gh` は呼ばない。stdout 相当の JSON 文字列を渡して写像だけを検証する。
"""

import importlib.util
import json
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "anvil" / "skills" / "create-pr" / "scripts" / "inspect_ci_status.py"
)

_spec = importlib.util.spec_from_file_location("anvil_inspect_ci_status", _SCRIPT_PATH)
ci_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci_mod)


def _checks(*buckets: str) -> str:
    """bucket の並びから `gh pr checks --json` 相当の stdout を組み立てる。"""
    return json.dumps(
        [
            {
                "name": f"check-{i}",
                "bucket": bucket,
                "state": bucket.upper(),
                "link": f"https://example.invalid/{i}",
            }
            for i, bucket in enumerate(buckets)
        ]
    )


def _status(stdout: str, returncode: int = 0) -> str:
    return ci_mod.inspect(stdout, "", returncode)["status"]


class StatusMappingTest(unittest.TestCase):
    def test_all_pass_is_succeeded(self):
        self.assertEqual(_status(_checks("pass", "pass")), "succeeded")

    def test_skipping_counts_as_succeeded(self):
        """workflow の条件分岐で実行されなかったチェックは失敗ではない。"""
        self.assertEqual(_status(_checks("pass", "skipping")), "succeeded")

    def test_only_skipping_is_succeeded(self):
        self.assertEqual(_status(_checks("skipping")), "succeeded")

    def test_any_fail_is_failed(self):
        self.assertEqual(_status(_checks("pass", "fail")), "failed")

    def test_fail_wins_over_pending(self):
        """失敗は確定した情報であり、残りを待っても覆らない。"""
        self.assertEqual(_status(_checks("fail", "pending")), "failed")

    def test_fail_wins_over_cancel(self):
        self.assertEqual(_status(_checks("cancel", "fail")), "failed")

    def test_cancel_is_its_own_status(self):
        """キャンセルは誰かが止めたことであり、failed と同じ語にすると誤読される。"""
        self.assertEqual(_status(_checks("pass", "cancel")), "cancelled")

    def test_cancel_wins_over_pending(self):
        self.assertEqual(_status(_checks("cancel", "pending")), "cancelled")

    def test_pending_when_nothing_settled_against_it(self):
        self.assertEqual(_status(_checks("pass", "pending")), "pending")


class NotReportedTest(unittest.TestCase):
    """チェック未登録は PR 作成直後に必ず通る状態であり、失敗と混同してはならない。"""

    def test_empty_array_is_not_reported(self):
        self.assertEqual(_status("[]"), "not_reported")

    def test_empty_stdout_is_not_reported(self):
        """未登録時に stdout が空になるか `[]` になるかは未実測のため、両方を受ける。"""
        self.assertEqual(_status(""), "not_reported")

    def test_whitespace_only_stdout_is_not_reported(self):
        self.assertEqual(_status("  \n "), "not_reported")

    def test_not_reported_is_independent_of_exit_code(self):
        """`gh` は未登録を非ゼロで返す。終了コードを判定に使わないことを固定する。"""
        self.assertEqual(_status("[]", returncode=1), "not_reported")


class ExitCodeIsNotUsedForJudgmentTest(unittest.TestCase):
    def test_success_payload_with_nonzero_exit_is_still_succeeded(self):
        self.assertEqual(_status(_checks("pass"), returncode=8), "succeeded")

    def test_exit_code_and_stderr_are_reported(self):
        """判定に使わないが握りつぶさない。"""
        result = ci_mod.inspect(_checks("pass"), "  some warning\n", 8)
        self.assertEqual(result["gh_exit_code"], 8)
        self.assertEqual(result["gh_stderr"], "some warning")


class UnknownBucketTest(unittest.TestCase):
    def test_unknown_bucket_raises(self):
        """黙って捨てると、残りが全て pass のとき succeeded を返してしまう。"""
        stdout = json.dumps([{"name": "t", "bucket": "surprise", "state": "?", "link": ""}])
        with self.assertRaises(ci_mod.UnknownBucketError):
            ci_mod.inspect(stdout, "", 0)

    def test_unknown_bucket_message_names_the_check_and_value(self):
        stdout = json.dumps([{"name": "lint", "bucket": "surprise", "state": "?", "link": ""}])
        with self.assertRaises(ci_mod.UnknownBucketError) as ctx:
            ci_mod.inspect(stdout, "", 0)
        self.assertIn("lint", str(ctx.exception))
        self.assertIn("surprise", str(ctx.exception))

    def test_missing_bucket_field_raises(self):
        stdout = json.dumps([{"name": "t", "state": "?", "link": ""}])
        with self.assertRaises(ci_mod.UnknownBucketError):
            ci_mod.inspect(stdout, "", 0)

    def test_unknown_bucket_is_not_hidden_by_passing_siblings(self):
        stdout = json.dumps(
            [
                {"name": "ok", "bucket": "pass", "state": "SUCCESS", "link": ""},
                {"name": "weird", "bucket": "surprise", "state": "?", "link": ""},
            ]
        )
        with self.assertRaises(ci_mod.UnknownBucketError):
            ci_mod.inspect(stdout, "", 0)


class CountsAndChecksTest(unittest.TestCase):
    def test_counts_cover_every_known_bucket(self):
        result = ci_mod.inspect(
            _checks("pass", "fail", "pending", "skipping", "cancel"), "", 0
        )
        self.assertEqual(
            result["counts"],
            {
                "pass": 1,
                "fail": 1,
                "pending": 1,
                "skipping": 1,
                "cancel": 1,
                "total": 5,
            },
        )

    def test_counts_total_is_zero_when_not_reported(self):
        self.assertEqual(ci_mod.inspect("[]", "", 1)["counts"]["total"], 0)

    def test_failed_checks_include_fail_and_cancel_only(self):
        result = ci_mod.inspect(_checks("pass", "fail", "cancel", "skipping"), "", 0)
        self.assertEqual(
            [c["bucket"] for c in result["failed_checks"]], ["fail", "cancel"]
        )

    def test_checks_preserve_name_state_and_link(self):
        result = ci_mod.inspect(_checks("fail"), "", 0)
        self.assertEqual(result["checks"][0]["name"], "check-0")
        self.assertEqual(result["checks"][0]["state"], "FAIL")
        self.assertEqual(result["checks"][0]["link"], "https://example.invalid/0")


class MalformedPayloadTest(unittest.TestCase):
    """検査そのものが成立しない入力は、状態語へ畳まずエラーにする。"""

    def test_non_json_stdout_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            ci_mod.inspect("no checks reported on the 'x' branch", "", 1)

    def test_json_object_instead_of_array_raises(self):
        with self.assertRaises(ValueError):
            ci_mod.inspect('{"bucket": "pass"}', "", 0)


class CliContractTest(unittest.TestCase):
    def test_pr_and_repo_are_required(self):
        with self.assertRaises(SystemExit):
            ci_mod.parse_args([])
        with self.assertRaises(SystemExit):
            ci_mod.parse_args(["--pr", "46"])
        with self.assertRaises(SystemExit):
            ci_mod.parse_args(["--repo", "o/r"])

    def test_pr_and_repo_are_parsed(self):
        args = ci_mod.parse_args(["--pr", "46", "--repo", "owner/repo"])
        self.assertEqual(args.pr, "46")
        self.assertEqual(args.repo, "owner/repo")

    def test_requested_json_fields_include_link_for_failure_reporting(self):
        self.assertIn("link", ci_mod._JSON_FIELDS)
        self.assertIn("bucket", ci_mod._JSON_FIELDS)


if __name__ == "__main__":
    unittest.main()
