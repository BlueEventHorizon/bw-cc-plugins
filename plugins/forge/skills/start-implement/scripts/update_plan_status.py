#!/usr/bin/env python3
"""計画書のタスクステータス・要件トレーサビリティを一括更新する。

`/forge:start-implement` Phase 6.2 のローカル操作入口。レビュー完了後の `status: pending` →
`status: completed` への一括変更と、要件トレーサビリティの判定・更新は AI ではなく本 script
が行う（REQ-020 FNC-004）。`held_groups[]` に含まれる task_id は呼び出し側（AI）が対象から
除外して渡す。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "plan"))
from plan_contract import load_plan, save_plan, PlanContractError  # noqa: E402


def update_plan_status(plan_data, completed_task_ids):
    """指定タスクを completed にし、要件トレーサビリティを判定・更新する。

    (updated_plan, errors, updated_count) を返す。
    """
    tasks = plan_data.get("tasks")
    if not isinstance(tasks, list):
        return None, ["計画書に tasks 配列がありません"], 0

    by_id = {t["task_id"]: t for t in tasks if isinstance(t, dict) and "task_id" in t}
    unknown = [t for t in completed_task_ids if t not in by_id]
    if unknown:
        return None, [f"計画書に存在しない task_id が指定されました: {unknown}"], 0

    updated_count = 0
    for task_id in completed_task_ids:
        if by_id[task_id].get("status") != "completed":
            by_id[task_id]["status"] = "completed"
            updated_count += 1

    design_traceability = plan_data.get("design_traceability") or []
    requirement_to_task_ids = {}
    for entry in design_traceability:
        if not isinstance(entry, dict):
            continue
        task_ids = entry.get("task_ids") or []
        for requirement_id in entry.get("requirement_ids") or []:
            requirement_to_task_ids.setdefault(requirement_id, set()).update(task_ids)

    requirements = plan_data.get("requirements_traceability") or []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        requirement_id = requirement.get("requirement_id")
        linked_task_ids = requirement_to_task_ids.get(requirement_id, set())
        if not linked_task_ids:
            continue
        all_completed = all(
            by_id.get(task_id, {}).get("status") == "completed" for task_id in linked_task_ids
        )
        if all_completed and requirement.get("status") != "completed":
            requirement["status"] = "completed"

    return plan_data, [], updated_count


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def run_cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-path", required=True)
    parser.add_argument("--task", required=True, help="completed にするカンマ区切りの task_id 一覧")
    args = parser.parse_args(argv)

    try:
        plan_data = load_plan(args.plan_path)
    except PlanContractError as exc:
        _emit({"status": "error", "errors": [str(exc)]})
        return 20

    completed_task_ids = args.task.split(",")
    updated_plan, errors, updated_count = update_plan_status(plan_data, completed_task_ids)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    save_plan(args.plan_path, updated_plan)
    _emit({"status": "ok", "updated_count": updated_count})
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
