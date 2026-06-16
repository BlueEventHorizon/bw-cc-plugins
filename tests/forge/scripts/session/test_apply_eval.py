"""apply_eval のテスト。

write_eval.py（検証）と merge_evals.py（plan.yaml 更新・統計計算）の
両責務を引き継ぐ統合テスト。test_write_eval.py / test_merge_evals.py から
全ケースを移植する (Issue #103)。
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "plugins" / "forge" / "scripts"))

from session.apply_eval import (  # noqa: E402
    VALID_SKIP_REASONS,
    apply_eval,
    validate_eval,
)
from session.update_plan import VALID_PRIORITIES  # noqa: E402
from session.yaml_utils import read_yaml, write_nested_yaml  # noqa: E402

SCRIPT = str(_REPO_ROOT / "plugins" / "forge" / "scripts" / "session" / "apply_eval.py")


# ---------------------------------------------------------------------------
# テストフィクスチャ
# ---------------------------------------------------------------------------


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


def _sample_plan_items():
    """priority 混在の plan.yaml サンプル (global id 1..6)。"""
    return [
        {"id": 1, "priority": "P1", "severity": "major", "title": "A-1",
         "status": "pending"},
        {"id": 2, "priority": "P1", "severity": "minor", "title": "A-2",
         "status": "pending"},
        {"id": 3, "priority": "P2", "severity": "major", "title": "B-1",
         "status": "pending"},
        {"id": 4, "priority": "P2", "severity": "major", "title": "B-2",
         "status": "pending"},
        {"id": 5, "priority": "P3", "severity": "major", "title": "C-1",
         "status": "pending"},
        {"id": 6, "priority": "P3", "severity": "minor", "title": "C-2",
         "status": "pending"},
    ]


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-test"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plan(self, items=None):
        if items is None:
            items = _sample_plan_items()
        write_nested_yaml(
            str(self.session_dir / "plan.yaml"),
            [("items", items)],
        )


# ---------------------------------------------------------------------------
# VALID_PRIORITIES の定義値域
# ---------------------------------------------------------------------------


class TestValidPriorities(unittest.TestCase):
    def test_valid_priorities_are_p1_p2_p3(self):
        """priority の値域は P1/P2/P3 の 3 値のみ (REQ-004 FNC-401)。"""
        self.assertEqual(set(VALID_PRIORITIES), {"P1", "P2", "P3"})


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
        """create_issue は正当な recommendation (4 値)。"""
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
             "status": "skipped", "reason": "x"},
        ]}, "code")
        self.assertTrue(any("skip_reason" in m for m in v))

    def test_skip_reason_enum_validated(self):
        v = validate_eval({"updates": [
            {"id": 1, "priority": "P2", "recommendation": "skip",
             "status": "skipped", "skip_reason": "because", "reason": "x"},
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
             "status": "skipped", "skip_reason": "out_of_scope"},
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
        """recommendation=create_issue では status=pending が正常 (初期状態)。"""
        self.assertEqual(validate_eval({"updates": [_create_issue(1)]}, "code"), [])

    def test_create_issue_status_optional(self):
        """recommendation=create_issue では status を省略できる。"""
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
# apply_eval (plan.yaml 直接更新) のテスト
# ---------------------------------------------------------------------------


class TestApplyEval(_FsTestCase):
    def test_updates_plan_yaml_and_returns_stats(self):
        """正常な eval が plan.yaml に反映され統計が返る。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [_fix(1), _skip(2), _create_issue(3), _needs_review(4)]},
        )
        self.assertEqual(result["fix_count"], 1)
        self.assertEqual(result["skip_count"], 1)
        self.assertEqual(result["needs_review_count"], 1)
        self.assertEqual(result["create_issue_count"], 1)
        self.assertTrue(result["should_continue"])

        plan = read_yaml(str(self.session_dir / "plan.yaml"))
        items = {i["id"]: i for i in plan["items"]}
        self.assertEqual(items[1]["recommendation"], "fix")
        self.assertEqual(items[2]["status"], "skipped")
        self.assertEqual(items[3]["recommendation"], "create_issue")
        self.assertEqual(items[4]["status"], "needs_review")

    def test_empty_updates_succeeds_with_zero_counts(self):
        """updates が空なら success (fix_count=0、plan.yaml は更新されない)。"""
        self._write_plan()
        result = apply_eval(str(self.session_dir), "code", {"updates": []})
        self.assertEqual(result["fix_count"], 0)
        self.assertEqual(result["should_continue"], False)
        self.assertEqual(result["updated"], [])

    def test_invalid_eval_raises_value_error(self):
        """スキーマ検証失敗は ValueError (plan.yaml は書き込まない)。"""
        self._write_plan()
        with self.assertRaises(ValueError) as ctx:
            apply_eval(str(self.session_dir), "code",
                       {"updates": [{"id": 1}]})
        self.assertIsInstance(ctx.exception.args[0], list)

    def test_missing_plan_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            apply_eval(str(self.session_dir), "code",
                       {"updates": [_fix(1)]})

    def test_priority_sort_p1_p2_p3_then_id_asc(self):
        """plan.yaml 更新順序が priority (P1→P2→P3) → id 昇順になる。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [
                _fix(5, priority="P3"),
                _fix(2, priority="P1"),
                _fix(1, priority="P1"),
                _fix(3, priority="P2"),
            ]},
        )
        self.assertEqual(result["updated"], [1, 2, 3, 5])

    def test_should_continue_false_when_no_fix(self):
        """fix が 0 件なら should_continue=false。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [
                _skip(1), _create_issue(3),
                _needs_review(5, priority="P3"),
            ]},
        )
        self.assertFalse(result["should_continue"])
        self.assertEqual(result["fix_count"], 0)

    def test_create_issue_excluded_from_should_continue(self):
        """recommendation=create_issue は should_continue を true にしない (FNC-406)。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [_create_issue(1), _skip(3)]},
        )
        self.assertFalse(result["should_continue"])

    def test_not_auto_fixable_detected(self):
        """auto_fixable=False かつ recommendation=fix の id が検出される。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [
                _fix(1, auto_fixable=False),
                _fix(2, auto_fixable=True),
                _fix(3, priority="P2", auto_fixable=False),
            ]},
        )
        self.assertEqual(result["not_auto_fixable"], [1, 3])

    def test_skip_not_in_not_auto_fixable(self):
        """recommendation=skip は not_auto_fixable に含まれない。"""
        self._write_plan()
        result = apply_eval(
            str(self.session_dir), "design",
            {"updates": [_skip(1)]},
        )
        self.assertEqual(result["not_auto_fixable"], [])

    def test_status_defaulted_to_pending_for_fix(self):
        """fix で status 省略時は pending がデフォルトで plan.yaml に反映される。"""
        self._write_plan()
        apply_eval(
            str(self.session_dir), "code",
            {"updates": [
                {"id": 1, "priority": "P1", "recommendation": "fix",
                 "auto_fixable": True},
            ]},
        )
        plan = read_yaml(str(self.session_dir / "plan.yaml"))
        item1 = next(i for i in plan["items"] if i["id"] == 1)
        self.assertEqual(item1["status"], "pending")

    def test_kind_in_json_must_match_kind_arg(self):
        """JSON の kind が --kind と不一致なら ValueError。"""
        self._write_plan()
        with self.assertRaises(ValueError):
            apply_eval(str(self.session_dir), "code",
                       {"kind": "design", "updates": [_fix(1)]})


# ---------------------------------------------------------------------------
# CLI E2E テスト
# ---------------------------------------------------------------------------


class TestApplyEvalCli(_FsTestCase):
    def _run(self, kind, stdin):
        return subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir), "--kind", kind],
            input=stdin, capture_output=True, text=True,
        )

    def test_basic_e2e(self):
        """CLI 経由で eval JSON → plan.yaml 直接更新が動作する。"""
        (self.session_dir / "session.yaml").write_text(
            "status: active\nskill: review\n", encoding="utf-8"
        )
        self._write_plan()
        payload = json.dumps({"updates": [
            _fix(1, auto_fixable=True, reason="ルール違反"),
            _skip(2),
            _fix(3, priority="P2", auto_fixable=False),
            _fix(5, priority="P3", auto_fixable=True),
        ]}, ensure_ascii=False)

        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["fix_count"], 3)
        self.assertEqual(output["skip_count"], 1)
        self.assertEqual(output["needs_review_count"], 0)
        self.assertEqual(output["create_issue_count"], 0)
        self.assertTrue(output["should_continue"])
        self.assertEqual(output["not_auto_fixable"], [3])

    def test_create_issue_excluded_from_should_continue(self):
        """recommendation=create_issue は should_continue=true をトリガーしない (FNC-406)。"""
        self._write_plan()
        payload = json.dumps({"updates": [
            _create_issue(1),
            _skip(3),
            _needs_review(5, priority="P3"),
        ]}, ensure_ascii=False)

        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["fix_count"], 0)
        self.assertEqual(output["skip_count"], 1)
        self.assertEqual(output["needs_review_count"], 1)
        self.assertEqual(output["create_issue_count"], 1)
        self.assertFalse(output["should_continue"])

    def test_fix_triggers_should_continue(self):
        """recommendation=fix が 1 件でもあれば should_continue=true。"""
        self._write_plan()
        payload = json.dumps({"updates": [
            _fix(1), _create_issue(3),
        ]}, ensure_ascii=False)

        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertTrue(output["should_continue"])

    def test_empty_updates_succeeds_with_zero_counts(self):
        """updates が空なら success (fix_count=0)。"""
        self._write_plan()
        result = self._run("design", json.dumps({"updates": []}))
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["fix_count"], 0)
        self.assertFalse(output["should_continue"])
        self.assertEqual(output["updated"], [])
        self.assertNotIn("dropped", output)

    def test_all_skip(self):
        """全件スキップの場合 should_continue=false。"""
        self._write_plan()
        payload = json.dumps({"updates": [_skip(1), _skip(2)]}, ensure_ascii=False)
        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["should_continue"])
        self.assertEqual(output["skip_count"], 2)

    def test_plan_updated_with_priority(self):
        """plan.yaml の各 item に priority / recommendation が反映される (id ベース更新)。"""
        self._write_plan()
        payload = json.dumps({"updates": [
            _fix(5, priority="P3", auto_fixable=True, reason="テスト理由"),
            _skip(6, priority="P3"),
        ]}, ensure_ascii=False)

        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)

        plan = read_yaml(str(self.session_dir / "plan.yaml"))
        items = {i["id"]: i for i in plan["items"]}

        self.assertEqual(items[5]["priority"], "P3")
        self.assertEqual(items[5]["recommendation"], "fix")
        self.assertEqual(items[6]["status"], "skipped")

    def test_error_on_missing_plan(self):
        """plan.yaml 不在時は error JSON を stderr に出力する。"""
        payload = json.dumps({"updates": [_fix(1)]})
        result = self._run("code", payload)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")

    def test_validation_failure_nonzero_with_violations(self):
        """スキーマ検証失敗は非ゼロ exit + stderr violations。"""
        self._write_plan()
        payload = json.dumps({"updates": [{"id": 1, "priority": "P1"}]})
        result = self._run("code", payload)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), "")
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")
        self.assertIn("violations", err)
        self.assertGreaterEqual(len(err["violations"]), 1)

    def test_invalid_json_input(self):
        self._write_plan()
        result = self._run("code", "{not json")
        self.assertEqual(result.returncode, 1)
        err = json.loads(result.stderr)
        self.assertIn("パースエラー", err["error"])

    def test_empty_stdin(self):
        self._write_plan()
        result = self._run("code", "")
        self.assertEqual(result.returncode, 1)
        err = json.loads(result.stderr)
        self.assertIn("空", err["error"])

    def test_invalid_kind_value(self):
        result = self._run("invalid_value", json.dumps({"updates": []}))
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr.lower())

    def test_missing_kind_argument(self):
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            input=json.dumps({"updates": []}),
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--kind", result.stderr)

    def test_all_kinds_update_plan(self):
        """全 kind 値で plan.yaml 更新が動作する。"""
        from session.write_interpretation import KIND_CHOICES
        for kind in KIND_CHOICES:
            with self.subTest(kind=kind):
                sess = self.tmpdir / f"cli-{kind}"
                sess.mkdir()
                write_nested_yaml(
                    str(sess / "plan.yaml"),
                    [("items", [{"id": 1, "priority": "P1", "severity": "major",
                                 "title": "T", "status": "pending"}])],
                )
                result = subprocess.run(
                    [sys.executable, SCRIPT, str(sess), "--kind", kind],
                    input=json.dumps({"updates": [_fix(1)]}),
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                out = json.loads(result.stdout)
                self.assertEqual(out["status"], "ok")
                self.assertEqual(out["updated"], [1])

    def test_no_eval_json_files_created(self):
        """apply_eval は eval_{kind}.json を書き出さない (中間ファイル廃止)。"""
        self._write_plan()
        payload = json.dumps({"updates": [_fix(1)]}, ensure_ascii=False)
        result = self._run("design", payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        eval_files = list(self.session_dir.glob("eval_*.json"))
        self.assertEqual(eval_files, [])


if __name__ == "__main__":
    unittest.main()
