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
from session.yaml_utils import write_nested_yaml

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
        combined, not_auto = merge_eval_updates(evals, id_map)

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
        _, not_auto = merge_eval_updates(evals, id_map)
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
        _, not_auto = merge_eval_updates(evals, id_map)
        self.assertEqual(not_auto, [])

    def test_out_of_range_local_id_skipped(self):
        """ローカル ID が範囲外の場合はスキップされる。"""
        id_map = {"alignment": [1]}
        evals = [
            {"perspective": "alignment", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix"},
                {"id": 99, "status": "pending", "recommendation": "fix"},
            ]},
        ]
        combined, _ = merge_eval_updates(evals, id_map)
        self.assertEqual(len(combined), 1)
        self.assertEqual(combined[0]["id"], 1)

    def test_unknown_perspective_skipped(self):
        """plan.yaml に存在しない perspective の eval はスキップされる。"""
        id_map = {"alignment": [1]}
        evals = [
            {"perspective": "unknown_perspective", "updates": [
                {"id": 1, "status": "pending", "recommendation": "fix"},
            ]},
        ]
        combined, _ = merge_eval_updates(evals, id_map)
        self.assertEqual(combined, [])


# ---------------------------------------------------------------------------
# CLI E2E テスト
# ---------------------------------------------------------------------------

class TestMergeEvalsCli(_FsTestCase):
    def test_basic_e2e(self):
        """CLI 経由で eval_*.json → plan.yaml 更新が動作する。"""
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

    def test_no_eval_files(self):
        """eval_*.json が存在しない場合はエラー。"""
        self._write_plan(_sample_plan_items())

        result = subprocess.run(
            [sys.executable, SCRIPT, str(self.session_dir)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)

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
        from session.yaml_utils import read_yaml
        plan = read_yaml(str(self.session_dir / "plan.yaml"))
        items = plan["items"]

        # resilience の item (id=5, 6) が更新されている
        item5 = next(i for i in items if i["id"] == 5)
        self.assertEqual(item5["recommendation"], "fix")

        item6 = next(i for i in items if i["id"] == 6)
        self.assertEqual(item6["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
