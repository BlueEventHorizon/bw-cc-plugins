#!/usr/bin/env python3
"""group_review_batch.py のユニットテスト。

Issue #220 三次レビュー指摘への回帰防止:
- 通し番号付き group_id ("GROUP-001 (1/7)") の正規化・集約
- グループの一部メンバーが FAILURE の場合はグループ全体を保留（部分完了状態のレビュー禁止）
- 合算ファイルの重複除去・計画書順の維持
"""

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "skills" / "start-implement" / "scripts"
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from group_review_batch import InvalidInputError, build_review_batches, normalize_group_key


class TestNormalizeGroupKey(unittest.TestCase):
    def test_strips_serial_number_suffix(self):
        self.assertEqual(normalize_group_key("GROUP-001 (1/7)"), "GROUP-001")
        self.assertEqual(normalize_group_key("GROUP-001 (7/7)"), "GROUP-001")

    def test_none_passthrough(self):
        self.assertIsNone(normalize_group_key(None))

    def test_no_parenthesis_returns_as_is(self):
        self.assertEqual(normalize_group_key("GROUP-001"), "GROUP-001")


class TestFullGroupSuccess(unittest.TestCase):
    """全メンバーが同一起動で SUCCESS した場合、1回のグループ合算レビューになること"""

    def test_serial_numbered_group_ids_are_aggregated_into_one_batch(self):
        tasks = [
            {"task_id": "TASK-001", "group_id": "GROUP-001 (1/3)"},
            {"task_id": "TASK-002", "group_id": "GROUP-001 (2/3)"},
            {"task_id": "TASK-003", "group_id": "GROUP-001 (3/3)"},
        ]
        results = [
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["a.md"]},
            {"task_id": "TASK-002", "status": "SUCCESS", "files_modified": ["b.md"]},
            {"task_id": "TASK-003", "status": "SUCCESS", "files_modified": ["c.md"]},
        ]
        out = build_review_batches({"tasks": tasks, "results": results})

        self.assertEqual(out["held_groups"], [])
        self.assertEqual(len(out["review_batches"]), 1, "3つの同一グループタスクは1バッチに集約されるべき")
        batch = out["review_batches"][0]
        self.assertEqual(batch["kind"], "group")
        self.assertEqual(batch["group_key"], "GROUP-001")
        self.assertEqual(batch["task_ids"], ["TASK-001", "TASK-002", "TASK-003"])
        self.assertEqual(batch["files"], ["a.md", "b.md", "c.md"])

    def test_duplicate_files_across_group_members_are_deduplicated_preserving_plan_order(self):
        tasks = [
            {"task_id": "TASK-001", "group_id": "GROUP-001 (1/2)"},
            {"task_id": "TASK-002", "group_id": "GROUP-001 (2/2)"},
        ]
        results = [
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["shared.md", "a.md"]},
            {"task_id": "TASK-002", "status": "SUCCESS", "files_modified": ["shared.md", "b.md"]},
        ]
        out = build_review_batches({"tasks": tasks, "results": results})

        batch = out["review_batches"][0]
        self.assertEqual(batch["files"], ["shared.md", "a.md", "b.md"], "重複は初出のみ残り、計画書順を維持する")


class TestPartialFailureHeldGroup(unittest.TestCase):
    """グループの一部が FAILURE の場合、グループ全体を保留し誰もレビューしないこと"""

    def test_group_with_one_failure_is_held_not_reviewed(self):
        tasks = [
            {"task_id": "TASK-001", "group_id": "GROUP-002 (1/2)"},
            {"task_id": "TASK-002", "group_id": "GROUP-002 (2/2)"},
        ]
        results = [
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["a.md"]},
            {"task_id": "TASK-002", "status": "FAILURE", "files_modified": []},
        ]
        out = build_review_batches({"tasks": tasks, "results": results})

        self.assertEqual(out["review_batches"], [], "失敗を含むグループはSUCCESS側も含めてレビュー対象外")
        self.assertEqual(len(out["held_groups"]), 1)
        held = out["held_groups"][0]
        self.assertEqual(held["group_key"], "GROUP-002")
        self.assertEqual(held["failed_task_ids"], ["TASK-002"])
        self.assertEqual(held["task_ids"], ["TASK-001", "TASK-002"])


class TestPartialGroupFallsBackToIndividual(unittest.TestCase):
    """グループの一部メンバーしか今回の実行に含まれない場合、個別レビューにフォールバックすること"""

    def test_group_with_missing_member_reviews_present_task_individually(self):
        tasks = [
            {"task_id": "TASK-001", "group_id": "GROUP-003 (1/2)"},
            {"task_id": "TASK-002", "group_id": "GROUP-003 (2/2)"},
        ]
        # TASK-002 は今回の実行結果に含まれない（別起動で実行済み・または未実行）
        results = [
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["a.md"]},
        ]
        out = build_review_batches({"tasks": tasks, "results": results})

        self.assertEqual(out["held_groups"], [])
        self.assertEqual(len(out["review_batches"]), 1)
        batch = out["review_batches"][0]
        self.assertEqual(batch["kind"], "individual")
        self.assertEqual(batch["task_ids"], ["TASK-001"])
        self.assertEqual(batch["files"], ["a.md"])


class TestIndependentTasks(unittest.TestCase):
    """group_id: null の独立タスクは常に個別レビューになること"""

    def test_null_group_id_tasks_are_individual(self):
        tasks = [
            {"task_id": "TASK-010", "group_id": None},
            {"task_id": "TASK-011", "group_id": None},
        ]
        results = [
            {"task_id": "TASK-010", "status": "SUCCESS", "files_modified": ["x.md"]},
            {"task_id": "TASK-011", "status": "SUCCESS", "files_modified": ["y.md"]},
        ]
        out = build_review_batches({"tasks": tasks, "results": results})

        self.assertEqual(out["held_groups"], [])
        self.assertEqual(len(out["review_batches"]), 2)
        for batch in out["review_batches"]:
            self.assertEqual(batch["kind"], "individual")

    def test_failed_independent_task_produces_no_batch(self):
        tasks = [{"task_id": "TASK-020", "group_id": None}]
        results = [{"task_id": "TASK-020", "status": "FAILURE", "files_modified": []}]
        out = build_review_batches({"tasks": tasks, "results": results})

        self.assertEqual(out["review_batches"], [])
        self.assertEqual(out["held_groups"], [])


class TestInputValidation(unittest.TestCase):
    """results の task_id 一意性・計画書所属を検証し、異常時は fail-fast すること"""

    def test_duplicate_task_id_in_results_raises(self):
        tasks = [{"task_id": "TASK-001", "group_id": None}]
        results = [
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["a.md"]},
            {"task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["a.md"]},
        ]
        with self.assertRaises(InvalidInputError):
            build_review_batches({"tasks": tasks, "results": results})

    def test_unknown_task_id_in_results_raises(self):
        tasks = [{"task_id": "TASK-001", "group_id": None}]
        results = [
            {"task_id": "TASK-999", "status": "SUCCESS", "files_modified": ["a.md"]},
        ]
        with self.assertRaises(InvalidInputError):
            build_review_batches({"tasks": tasks, "results": results})


if __name__ == "__main__":
    unittest.main()
