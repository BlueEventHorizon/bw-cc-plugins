"""write_eval のテスト。

CLI 引数は `--kind` のみを受け付け、値域は
{code, design, requirement, plan, uxui, generic} に固定される
(write_interpretation.py KIND_CHOICES と一致)。

stdin で受け取った eval JSON をフルスキーマ検証してから
`{session_dir}/eval_{kind}.json` に書き出す (Issue #38)。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# tests/forge/scripts/session/ → repo root (4 levels up)
_REPO_ROOT = Path(__file__).resolve().parents[4]

sys.path.insert(0, str(_REPO_ROOT / "plugins" / "forge" / "scripts"))

from session.write_eval import (  # noqa: E402
    VALID_SKIP_REASONS,
    validate_eval,
    write_eval,
)

SCRIPT = str(_REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "write_eval.py")


def _fix(item_id, priority="P1", auto_fixable=True, **extra):
    u = {"id": item_id, "priority": priority, "status": "pending",
         "recommendation": "fix", "auto_fixable": auto_fixable}
    if auto_fixable is False:
        u.setdefault("reason", "修正方針: ...")
    u.update(extra)
    return u


def _skip(item_id, priority="P2", skip_reason="out_of_scope", **extra):
    u = {"id": item_id, "priority": priority, "status": "skipped",
         "recommendation": "skip", "skip_reason": skip_reason,
         "reason": "スキップ理由"}
    u.update(extra)
    return u


def _create_issue(item_id, priority="P1", **extra):
    u = {"id": item_id, "priority": priority, "status": "pending",
         "recommendation": "create_issue", "reason": "FNC-406 3 条件成立"}
    u.update(extra)
    return u


def _needs_review(item_id, priority="P2", **extra):
    u = {"id": item_id, "priority": priority, "status": "needs_review",
         "recommendation": "needs_review", "reason": "観点 2 不成立"}
    u.update(extra)
    return u


# ---------------------------------------------------------------------------
# validate_eval (純粋関数) のテスト
# ---------------------------------------------------------------------------


class TestValidateEval(unittest.TestCase):
    def test_valid_full_eval_passes(self):
        """4 種の recommendation を含む正常な eval は違反なし。"""
        data = {"kind": "design", "updates": [
            _fix(1), _skip(2), _create_issue(3), _needs_review(4),
        ]}
        self.assertEqual(validate_eval(data, "design"), [])

    def test_empty_updates_is_valid(self):
        """updates が空 (findings 0 件) は正常。"""
        self.assertEqual(validate_eval({"kind": "code", "updates": []}, "code"), [])

    def test_kind_optional_when_absent(self):
        """JSON に kind がなくても検証は通る (--kind から補完するため)。"""
        self.assertEqual(validate_eval({"updates": [_fix(1)]}, "code"), [])

    def test_non_dict_toplevel_rejected(self):
        v = validate_eval([1, 2, 3], "code")
        self.assertEqual(len(v), 1)
        self.assertIn("object", v[0])

    def test_kind_mismatch_rejected(self):
        v = validate_eval({"kind": "design", "updates": []}, "code")
        self.assertTrue(any("kind" in m for m in v))

    def test_missing_updates_rejected(self):
        v = validate_eval({"kind": "code"}, "code")
        self.assertTrue(any("updates" in m for m in v))

    def test_updates_not_list_rejected(self):
        v = validate_eval({"updates": {"id": 1}}, "code")
        self.assertTrue(any("配列" in m for m in v))

    def test_missing_id_rejected(self):
        v = validate_eval({"updates": [
            {"priority": "P1", "recommendation": "fix", "auto_fixable": True},
        ]}, "code")
        self.assertTrue(any("'id'" in m for m in v))

    def test_invalid_id_types_rejected(self):
        """id が 0 / 負 / 文字列 / bool は不正。"""
        for bad in (0, -1, "1", True):
            with self.subTest(bad=bad):
                v = validate_eval({"updates": [
                    {"id": bad, "priority": "P1", "recommendation": "fix",
                     "auto_fixable": True},
                ]}, "code")
                self.assertTrue(any("'id'" in m for m in v), v)

    def test_duplicate_id_rejected(self):
        v = validate_eval({"updates": [_fix(1), _skip(1)]}, "code")
        self.assertTrue(any("重複" in m for m in v))

    def test_missing_priority_rejected(self):
        v = validate_eval({"updates": [
            {"id": 1, "recommendation": "fix", "auto_fixable": True},
        ]}, "code")
        self.assertTrue(any("'priority'" in m for m in v))

    def test_invalid_priority_rejected(self):
        for bad in ("P4", "p1", ""):
            with self.subTest(bad=bad):
                v = validate_eval({"updates": [_fix(1, priority=bad)]}, "code")
                self.assertTrue(any("'priority'" in m for m in v), v)

    def test_invalid_status_rejected(self):
        v = validate_eval({"updates": [_fix(1, status="done")]}, "code")
        self.assertTrue(any("'status'" in m for m in v))

    def test_missing_recommendation_rejected(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1"},
        ]}, "code")
        self.assertTrue(any("'recommendation'" in m for m in v))

    def test_invalid_recommendation_rejected(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "unknown"},
        ]}, "code")
        self.assertTrue(any("'recommendation'" in m for m in v))

    def test_create_issue_is_valid_recommendation(self):
        """Issue #38 本文の 3 値 enum と異なり create_issue は正当 (4 値)。"""
        self.assertEqual(validate_eval({"updates": [_create_issue(1)]}, "code"), [])

    def test_fix_requires_auto_fixable(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix"},
        ]}, "code")
        self.assertTrue(any("auto_fixable" in m for m in v))

    def test_fix_auto_fixable_must_be_bool(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix",
             "auto_fixable": "true"},
        ]}, "code")
        self.assertTrue(any("bool" in m for m in v))

    def test_fix_auto_fixable_false_requires_reason(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix",
             "auto_fixable": False},
        ]}, "code")
        self.assertTrue(any("reason" in m for m in v))

    def test_fix_auto_fixable_true_reason_optional(self):
        self.assertEqual(validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix",
             "auto_fixable": True},
        ]}, "code"), [])

    def test_skip_requires_skip_reason(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "reason": "x"},
        ]}, "code")
        self.assertTrue(any("skip_reason" in m for m in v))

    def test_skip_reason_enum_validated(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "skip_reason": "because", "reason": "x"},
        ]}, "code")
        self.assertTrue(any("skip_reason" in m for m in v))

    def test_all_skip_reasons_valid(self):
        for sr in VALID_SKIP_REASONS:
            with self.subTest(sr=sr):
                self.assertEqual(
                    validate_eval({"updates": [_skip(1, skip_reason=sr)]}, "code"),
                    [],
                )

    def test_skip_requires_reason(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "skip_reason": "out_of_scope"},
        ]}, "code")
        self.assertTrue(any("reason" in m for m in v))

    def test_create_issue_requires_reason(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "create_issue"},
        ]}, "code")
        self.assertTrue(any("reason" in m for m in v))

    def test_needs_review_requires_reason(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "needs_review"},
        ]}, "code")
        self.assertTrue(any("reason" in m for m in v))

    def test_collects_all_violations(self):
        """最初の違反で打ち切らず全件収集する。"""
        v = validate_eval({"updates": [
            {"id": 0, "priority": "P9", "recommendation": "bogus"},
            {"id": "x", "recommendation": "skip"},
        ]}, "code")
        # id / priority / recommendation × 2 件分の複数違反が含まれる
        self.assertGreaterEqual(len(v), 4)

    # --- recommendation/status 相関バリデーション ---

    def test_skip_requires_status_skipped(self):
        """recommendation=skip では status=skipped が必須。"""
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "skip_reason": "out_of_scope", "reason": "x"},
        ]}, "code")
        self.assertTrue(any("status" in m for m in v))

    def test_skip_rejects_wrong_status(self):
        """recommendation=skip で status=pending は不正。"""
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "skip_reason": "out_of_scope", "reason": "x", "status": "pending"},
        ]}, "code")
        self.assertTrue(any("skipped" in m for m in v))

    def test_create_issue_status_pending_valid(self):
        """recommendation=create_issue では status=pending が正常 (初期状態)。
        present-findings が issue 作成後に skipped へ遷移させる (SKILL.md §5-2)。"""
        self.assertEqual(validate_eval({"updates": [_create_issue(1)]}, "code"), [])

    def test_create_issue_status_optional(self):
        """recommendation=create_issue では status を省略できる (merge_evals が pending を補完)。"""
        self.assertEqual(validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "create_issue",
             "reason": "FNC-406 3 条件成立"},
        ]}, "code"), [])

    def test_needs_review_requires_status_needs_review(self):
        """recommendation=needs_review では status=needs_review が必須。"""
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "needs_review",
             "reason": "観点 2 不成立"},
        ]}, "code")
        self.assertTrue(any("status" in m for m in v))

    def test_needs_review_rejects_wrong_status(self):
        """recommendation=needs_review で status=pending は不正。"""
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "needs_review",
             "reason": "x", "status": "pending"},
        ]}, "code")
        self.assertTrue(any("needs_review" in m for m in v))

    def test_fix_status_optional(self):
        """recommendation=fix では status は任意 (省略可)。"""
        self.assertEqual(validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix", "auto_fixable": True},
        ]}, "code"), [])

    def test_fix_with_status_pending_valid(self):
        """recommendation=fix で status=pending は正常。"""
        self.assertEqual(validate_eval({"updates": [
            {"id": 1, "priority": "P1", "recommendation": "fix",
             "auto_fixable": True, "status": "pending"},
        ]}, "code"), [])


# ---------------------------------------------------------------------------
# write_eval (書き出し) のテスト
# ---------------------------------------------------------------------------


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-test"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestWriteEval(_FsTestCase):
    def test_writes_eval_kind_json(self):
        result = write_eval(
            str(self.session_dir), "design",
            {"updates": [_fix(1), _skip(2)]},
        )
        target = self.session_dir / "eval_design.json"
        self.assertEqual(result["path"], str(target))
        self.assertEqual(result["count"], 2)
        self.assertTrue(target.exists())

        written = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(written["kind"], "design")
        self.assertEqual(len(written["updates"]), 2)

    def test_kind_injected_when_absent(self):
        """入力に kind がなくても出力には正規 kind が補完される。"""
        write_eval(str(self.session_dir), "code", {"updates": [_fix(1)]})
        written = json.loads(
            (self.session_dir / "eval_code.json").read_text(encoding="utf-8")
        )
        self.assertEqual(written["kind"], "code")

    def test_invalid_raises_valueerror_with_violations(self):
        with self.assertRaises(ValueError) as ctx:
            write_eval(str(self.session_dir), "code",
                       {"updates": [{"id": 1}]})
        self.assertIsInstance(ctx.exception.args[0], list)
        self.assertFalse((self.session_dir / "eval_code.json").exists())

    def test_idempotent_same_content(self):
        data = {"updates": [_fix(1)]}
        write_eval(str(self.session_dir), "plan", data)
        write_eval(str(self.session_dir), "plan", data)
        reference = (self.session_dir / "eval_plan.json").read_text(encoding="utf-8")
        write_eval(str(self.session_dir), "plan", data)
        self.assertEqual(
            (self.session_dir / "eval_plan.json").read_text(encoding="utf-8"),
            reference,
        )

    def test_no_tmp_files_left(self):
        write_eval(str(self.session_dir), "uxui", {"updates": [_fix(1)]})
        self.assertEqual(list(self.session_dir.glob("*.tmp")), [])
        self.assertEqual(list(self.session_dir.glob(".*.tmp")), [])


# ---------------------------------------------------------------------------
# CLI E2E テスト
# ---------------------------------------------------------------------------


class TestWriteEvalCli(_FsTestCase):
    def _run(self, kind, stdin):
        return subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir), "--kind", kind],
            input=stdin, capture_output=True, text=True,
        )

    def test_cli_success(self):
        payload = json.dumps({"updates": [_fix(1), _skip(2)]}, ensure_ascii=False)
        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        out = json.loads(result.stdout)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["count"], 2)
        self.assertTrue((self.session_dir / "eval_design.json").exists())

    def test_cli_validation_failure_nonzero_with_violations(self):
        payload = json.dumps({"updates": [{"id": 1, "priority": "P1"}]})
        result = self._run("code", payload)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")
        self.assertIn("violations", err)
        self.assertTrue(len(err["violations"]) >= 1)
        # 検証失敗時はファイルを書かない
        self.assertFalse((self.session_dir / "eval_code.json").exists())

    def test_cli_invalid_json(self):
        result = self._run("code", "{not json")
        self.assertEqual(result.returncode, 1)
        err = json.loads(result.stderr)
        self.assertIn("パースエラー", err["error"])

    def test_cli_empty_stdin(self):
        result = self._run("code", "")
        self.assertEqual(result.returncode, 1)
        err = json.loads(result.stderr)
        self.assertIn("空", err["error"])

    def test_cli_invalid_kind_value(self):
        result = self._run("invalid_value", json.dumps({"updates": []}))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr.lower())

    def test_cli_missing_kind_argument(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps({"updates": []}),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--kind", result.stderr)

    def test_cli_all_kinds_emit_eval_kind_json(self):
        from session.write_interpretation import KIND_CHOICES
        for kind in KIND_CHOICES:
            with self.subTest(kind=kind):
                sess = self.tmpdir / f"cli-{kind}"
                sess.mkdir()
                result = subprocess.run(
                    [sys.executable, SCRIPT, str(sess), "--kind", kind],
                    input=json.dumps({"updates": [_fix(1)]}),
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                out = json.loads(result.stdout)
                self.assertEqual(out["path"], str(sess / f"eval_{kind}.json"))


if __name__ == "__main__":
    unittest.main()
