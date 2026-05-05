"""merge_evals のテスト。"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[4] / "plugins" / "forge" / "scripts"),
)

from session.merge_evals import (
    build_perspective_id_map,
    collect_eval_files,
    merge_eval_updates,
)
from session.yaml_utils import read_yaml, write_nested_yaml

SCRIPT = str(
    Path(__file__).resolve().parents[4]
    / "plugins" / "forge" / "scripts" / "session" / "merge_evals.py"
)


class _FsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.session_dir = self.tmpdir / "review-test"
        self.session_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_plan(self, items):
        """テスト用の plan.yaml を書き出す。"""
        write_nested_yaml(
            str(self.session_dir / "plan.yaml"),
            [("items", items)],
        )

    def _write_eval(self, perspective, updates):
        """テスト用の eval_*.json を書き出す。"""
        path = self.session_dir / f"eval_{perspective}.json"
        path.write_text(
            json.dumps(
                {"perspective": perspective, "updates": updates},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def _sample_plan_items():
    """3 perspective × 2 items = 6 items の plan.yaml。"""
    return [
        {"id": 1, "severity": "major", "title": "A-1",
         "status": "pending", "perspective": "alignment"},
        {"id": 2, "severity": "minor", "title": "A-2",
         "status": "pending", "perspective": "alignment"},
        {"id": 3, "severity": "major", "title": "B-1",
         "status": "pending", "perspective": "architecture"},
        {"id": 4, "severity": "major", "title": "B-2",
         "status": "pending", "perspective": "architecture"},
        {"id": 5, "severity": "major", "title": "C-1",
         "status": "pending", "perspective": "resilience"},
        {"id": 6, "severity": "minor", "title": "C-2",
         "status": "pending", "perspective": "resilience"},
    ]


# ---------------------------------------------------------------------------
# build_perspective_id_map のテスト
# ---------------------------------------------------------------------------

class TestBuildPerspectiveIdMap(unittest.TestCase):
    def test_basic(self):
        items = _sample_plan_items()
        mapping = build_perspective_id_map(items)
        self.assertEqual(mapping["alignment"], [1, 2])
        self.assertEqual(mapping["architecture"], [3, 4])
        self.assertEqual(mapping["resilience"], [5, 6])

    def test_empty(self):
        mapping = build_perspective_id_map([])
        self.assertEqual(mapping, {})

    def test_single_perspective(self):
        items = [
            {"id": 10, "perspective": "logic"},
            {"id": 20, "perspective": "logic"},
        ]
        mapping = build_perspective_id_map(items)
        self.assertEqual(mapping, {"logic": [10, 20]})

    def test_missing_perspective_not_registered(self):
        """perspective 未指定 (空文字 or 欠落) の item はマッピングに登録されない。"""
        items = [
            {"id": 1, "perspective": "logic"},
            {"id": 2},  # perspective 欠落
            {"id": 3, "perspective": ""},  # 空文字
        ]
        mapping = build_perspective_id_map(items)
        # 空文字キーで登録されていない
        self.assertNotIn("", mapping)
        self.assertEqual(mapping["logic"], [1])
        # id=2,3 はどのキーにも登録されない
        all_ids = [gid for ids in mapping.values() for gid in ids]
        self.assertEqual(sorted(all_ids), [1])


# ---------------------------------------------------------------------------
# collect_eval_files のテスト
# ---------------------------------------------------------------------------

class TestCollectEvalFiles(_FsTestCase):
    def test_collects_eval_json(self):
        self._write_eval("alignment", [{"id": 1, "status": "pending"}])
        self._write_eval("architecture", [{"id": 1, "status": "pending"}])
        evals = collect_eval_files(str(self.session_dir))
        self.assertEqual(len(evals), 2)
        perspectives = {e["perspective"] for e in evals}
        self.assertEqual(perspectives, {"alignment", "architecture"})

    def test_ignores_non_eval_files(self):
        self._write_eval("alignment", [{"id": 1, "status": "pending"}])
        # eval_ プレフィックスなしのファイル
        (self.session_dir / "review_alignment.md").write_text("test")
        evals = collect_eval_files(str(self.session_dir))
        self.assertEqual(len(evals), 1)

    def test_empty_dir(self):
        evals = collect_eval_files(str(self.session_dir))
        self.assertEqual(evals, [])


# ---------------------------------------------------------------------------
# merge_eval_updates のテスト
# ---------------------------------------------------------------------------

class TestMergeEvalUpdates(unittest.TestCase):
    def test_basic_mapping(self):
        """ローカル ID がグローバル ID に正しく変換される。"""
        id_map = {"alignment": [1, 2], "architecture": [3, 4]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix"},
                {"id": 2, "status": "skipped", "recommendation": "skip",
                 "skip_reason": "対象外"},
            ]},
            {"perspective": "architecture", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True},
            ]},
        ]
        combined, not_auto, _dropped = merge_eval_updates(evals, id_map)

        # グローバル ID の確認
        ids = [u["id"] for u in combined]
        self.assertEqual(ids, [1, 2, 3])

        # recommendation の確認
        self.assertEqual(combined[0]["recommendation"], "fix")
        self.assertEqual(combined[1]["recommendation"], "skip")
        self.assertEqual(combined[2]["recommendation"], "fix")

        # not_auto_fixable は空（全て auto_fixable=True or 未指定）
        self.assertEqual(not_auto, [])

    def test_not_auto_fixable_detected(self):
        """auto_fixable=false の fix 推奨項目が検出される。"""
        id_map = {"alignment": [1, 2]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "recommendation": "fix", "auto_fixable": False,
                 "status": "pending"},
                {"id": 2, "recommendation": "fix", "auto_fixable": True,
                 "status": "pending"},
            ]},
        ]
        _, not_auto, _dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(not_auto, [1])

    def test_skip_not_in_not_auto_fixable(self):
        """auto_fixable=false でも recommendation=skip なら not_auto_fixable に含まれない。"""
        id_map = {"alignment": [1]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "recommendation": "skip", "auto_fixable": False,
                 "status": "skipped", "skip_reason": "対象外"},
            ]},
        ]
        _, not_auto, _dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(not_auto, [])

    def test_out_of_range_local_id_skipped(self):
        """ローカル ID が範囲外の場合はスキップされ、dropped に記録される。"""
        id_map = {"alignment": [1]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix"},
                {"id": 99, "status": "pending", "recommendation": "fix"},
            ]},
        ]
        combined, _, dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["id"], 1)

        # 範囲外 ID は dropped に記録される
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["perspective"], "alignment")
        self.assertEqual(dropped[0]["local_id"], 99)
        self.assertIn("範囲外", dropped[0]["reason"])

    def test_unknown_perspective_skipped(self):
        """plan.yaml に存在しない perspective の eval はスキップされ dropped に記録される。"""
        id_map = {"alignment": [1]}
        evals = [
            {"perspective": "unknown_perspective", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix"},
            ]},
        ]
        combined, _, dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(combined, [])

        # 未知 perspective も dropped に記録
        self.assertEqual(len(dropped), 1)
        self.assertEqual(dropped[0]["perspective"], "unknown_perspective")
        self.assertIn("plan.yaml に存在しない", dropped[0]["reason"])

    def test_invalid_local_id_recorded(self):
        """local_id が未指定・0・負値の場合も dropped に記録される。"""
        id_map = {"alignment": [1, 2]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "recommendation": "fix", "status": "pending"},
                {"recommendation": "fix", "status": "pending"},  # id 欠落
                {"id": 0, "recommendation": "fix", "status": "pending"},
                {"id": -5, "recommendation": "fix", "status": "pending"},
            ]},
        ]
        combined, _, dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(len(combined), 1)
        # 無効 ID 3 件が dropped に記録
        self.assertEqual(len(dropped), 3)
        for d in dropped:
            self.assertIn("未指定または 1 未満", d["reason"])

    def test_empty_updates_no_dropped(self):
        """eval の updates が空なら combined も dropped も空 (findings 0 件は正常)。"""
        id_map = {"alignment": [1, 2]}
        evals = [
            {"perspective": "alignment", "updates": []},
        ]
        combined, not_auto, dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(combined, [])
        self.assertEqual(not_auto, [])
        self.assertEqual(dropped, [])

    def test_shared_item_consistent_recommendation(self):
        """同一 global_id に複数 perspective から一致判定が来た場合、最後の評価が採用される。"""
        # id_map 上で global_id=2 が両 perspective に登録されている防御的ケース
        # (通常フローでは発生しないが merge_eval_updates は安全装置として統合を行う)
        id_map = {"logic": [1, 2], "resilience": [2, 3]}
        evals = [
            {"perspective": "logic", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True, "reason": "logic 理由"},
                {"id": 2, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True, "reason": "logic: 共通問題"},
            ]},
            {"perspective": "resilience", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True, "reason": "resilience: 共通問題"},
                {"id": 2, "status": "pending", "recommendation": "fix",
                 "auto_fixable": False, "reason": "resilience 理由"},
            ]},
        ]
        combined, not_auto, _dropped = merge_eval_updates(evals, id_map)

        # global_id ごとに 1 エントリに統合される(global_id=2 の重複が消える)
        ids = [u["id"] for u in combined]
        self.assertEqual(sorted(ids), [1, 2, 3])
        self.assertEqual(len(ids), len(set(ids)), "global_id が重複していない")

        by_id = {u["id"]: u for u in combined}

        # global_id=2 は両 perspective とも recommendation=fix で一致
        # → 最後のエントリ(resilience)が採用される
        self.assertEqual(by_id[2]["recommendation"], "fix")
        self.assertEqual(by_id[2]["reason"], "resilience: 共通問題")

        # _perspective メタフィールドは出力に残っていない
        for entry in combined:
            self.assertNotIn("_perspective", entry)

        # not_auto_fixable: global_id=3 は resilience だけ auto_fixable=False → 含まれる
        self.assertEqual(not_auto, [3])

    def test_shared_item_conflicting_recommendation_escalates(self):
        """同一 global_id への fix / skip 不一致は needs_review にエスカレーションされる。"""
        id_map = {"logic": [1, 2], "resilience": [2, 3]}
        evals = [
            {"perspective": "logic", "updates": [
                {"id": 2, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True, "reason": "logic: 修正が必要"},
            ]},
            {"perspective": "resilience", "updates": [
                {"id": 1, "status": "skipped", "recommendation": "skip",
                 "skip_reason": "resilience: 対象外"},
            ]},
        ]
        combined, not_auto, _dropped = merge_eval_updates(evals, id_map)

        by_id = {u["id"]: u for u in combined}

        # global_id=2 は両 perspective で fix / skip 不一致 → needs_review
        self.assertEqual(by_id[2]["recommendation"], "needs_review")
        self.assertEqual(by_id[2]["status"], "needs_review")
        self.assertIn("perspective 間で判定不一致", by_id[2]["reason"])
        self.assertIn("logic=fix", by_id[2]["reason"])
        self.assertIn("resilience=skip", by_id[2]["reason"])

        # needs_review に昇格した項目は not_auto_fixable に含めない(fix ではないため)
        self.assertNotIn(2, not_auto)

    def test_shared_item_single_perspective_no_escalation(self):
        """perspectives 持ちでも 1 perspective しか eval が来なければエスカレートしない。"""
        id_map = {"logic": [1], "resilience": [1]}  # 同一 global_id=1 が両方に属する
        evals = [
            {"perspective": "logic", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix",
                 "auto_fixable": True, "reason": "logic 理由"},
            ]},
        ]
        combined, _, _dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["id"], 1)
        self.assertEqual(combined[0]["recommendation"], "fix")
        self.assertEqual(combined[0]["reason"], "logic 理由")

    def test_shared_item_three_way_split_escalates(self):
        """3 perspective 間で判定が割れた場合も needs_review にエスカレーション。"""
        id_map = {"a": [1], "b": [1], "c": [1]}
        evals = [
            {"perspective": "a", "updates": [
                {"id": 1, "recommendation": "fix", "status": "pending"},
            ]},
            {"perspective": "b", "updates": [
                {"id": 1, "recommendation": "skip", "status": "skipped",
                 "skip_reason": "b の理由"},
            ]},
            {"perspective": "c", "updates": [
                {"id": 1, "recommendation": "needs_review", "status": "pending"},
            ]},
        ]
        combined, _, _dropped = merge_eval_updates(evals, id_map)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["recommendation"], "needs_review")
        reason = combined[0]["reason"]
        self.assertIn("a=fix", reason)
        self.assertIn("b=skip", reason)
        self.assertIn("c=needs_review", reason)


# ---------------------------------------------------------------------------
# CLI E2E テスト
# ---------------------------------------------------------------------------

class TestMergeEvalsCli(_FsTestCase):
    def test_basic_e2e(self):
        """CLI 経由で eval_*.json → plan.yaml 更新が動作する。"""
        (self.session_dir / "session.yaml").write_text(
            "status: active\nskill: review\n", encoding="utf-8"
        )
        self._write_plan(_sample_plan_items())
        self._write_eval("alignment", [
            {"id": 1, "status": "pending", "recommendation": "fix",
             "auto_fixable": True, "reason": "修正理由A"},
            {"id": 2, "status": "skipped", "recommendation": "skip",
             "skip_reason": "対象外"},
        ])
        self._write_eval("architecture", [
            {"id": 1, "status": "pending", "recommendation": "fix",
             "auto_fixable": False, "reason": "修正理由B"},
            {"id": 2, "status": "pending", "recommendation": "fix",
             "auto_fixable": True, "reason": "修正理由C"},
        ])

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["fix_count"], 3)
        self.assertEqual(output["skip_count"], 1)
        self.assertEqual(output["should_continue"], True)
        self.assertEqual(output["not_auto_fixable"], [3])  # architecture id=1 → global 3

        session = read_yaml(str(self.session_dir / "session.yaml"))
        self.assertEqual(session["phase"], "evaluation_merged")
        self.assertEqual(session["phase_status"], "completed")
        self.assertEqual(session["active_artifact"], "plan.yaml")

    def test_no_eval_files(self):
        """eval_*.json が存在しない場合はエラーを stderr に出力。"""
        self._write_plan(_sample_plan_items())

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        # error JSON は stderr に出力 (update_plan.py / write_interpretation.py と統一)
        self.assertEqual(result.stdout.strip(), "")
        self.assertTrue(result.stderr.strip())
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")
        self.assertIn("eval_*.json", err["error"])

    def test_error_json_goes_to_stderr_on_missing_plan(self):
        """plan.yaml 不在時も error JSON を stderr に出力する。"""
        # plan.yaml を書かずに eval だけ置く
        self._write_eval("alignment", [
            {"id": 1, "status": "pending", "recommendation": "fix"},
        ])
        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")

    def test_all_dropped_is_error_with_diagnostics(self):
        """全 eval が mapping 失敗(combined=[]) なら error + dropped 診断情報を返す。"""
        self._write_plan(_sample_plan_items())
        # plan.yaml に存在しない perspective で eval を書く
        self._write_eval("ghost_perspective", [
            {"id": 1, "status": "pending", "recommendation": "fix"},
        ])

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        err = json.loads(result.stderr)
        self.assertEqual(err["status"], "error")
        self.assertIn("マップできませんでした", err["error"])
        self.assertIn("dropped", err)
        self.assertEqual(len(err["dropped"]), 1)
        self.assertEqual(err["dropped"][0]["perspective"], "ghost_perspective")

    def test_empty_updates_succeeds_with_zero_counts(self):
        """eval の updates が全て空なら success (fix_count=0)。diagnostics なし。"""
        self._write_plan(_sample_plan_items())
        self._write_eval("alignment", [])  # updates 空(findings 0 件)

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["fix_count"], 0)
        self.assertEqual(output["skip_count"], 0)
        self.assertEqual(output["needs_review_count"], 0)
        self.assertEqual(output["should_continue"], False)
        self.assertEqual(output["updated"], [])
        self.assertNotIn("dropped", output)

    def test_partial_dropped_reported_in_success(self):
        """一部 mapping 失敗があっても combined>0 なら success + dropped 診断を含む。"""
        self._write_plan(_sample_plan_items())
        # alignment は local_id 1,2 が有効、local_id 99 は範囲外
        self._write_eval("alignment", [
            {"id": 1, "status": "pending", "recommendation": "fix",
             "auto_fixable": True, "reason": "有効"},
            {"id": 99, "status": "pending", "recommendation": "fix"},
        ])

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["status"], "ok")
        self.assertEqual(output["fix_count"], 1)
        self.assertIn("dropped", output)
        self.assertEqual(len(output["dropped"]), 1)
        self.assertEqual(output["dropped"][0]["local_id"], 99)

    def test_all_skip(self):
        """全件スキップの場合 should_continue=false。"""
        self._write_plan(_sample_plan_items())
        self._write_eval("alignment", [
            {"id": 1, "status": "skipped", "recommendation": "skip",
             "skip_reason": "対象外"},
            {"id": 2, "status": "skipped", "recommendation": "skip",
             "skip_reason": "対象外"},
        ])

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        output = json.loads(result.stdout)
        self.assertEqual(output["should_continue"], False)
        self.assertEqual(output["fix_count"], 0)

    def test_plan_updated(self):
        """plan.yaml が実際に更新されていることを確認。"""
        self._write_plan(_sample_plan_items())
        self._write_eval("resilience", [
            {"id": 1, "status": "pending", "recommendation": "fix",
             "auto_fixable": True, "reason": "テスト理由"},
            {"id": 2, "status": "skipped", "recommendation": "skip",
             "skip_reason": "改善提案"},
        ])

        subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )

        # plan.yaml を読み直して検証
        plan = read_yaml(str(self.session_dir / "plan.yaml"))
        items = plan["items"]

        # resilience の item (id=5, 6) が更新されている
        item5 = next(i for i in items if i["id"] == 5)
        self.assertEqual(item5["recommendation"], "fix")

        item6 = next(i for i in items if i["id"] == 6)
        self.assertEqual(item6["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
