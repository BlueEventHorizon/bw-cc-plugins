#!/usr/bin/env python3
"""計画書からタスクを選択し、依存関係・グループ原子性を判定する。

`/forge:start-implement` Phase 2 のローカル操作入口。優先度順ソート・`status: pending`
抽出・依存関係チェック・グループ原子的選択・実行可能/待機グループ分割は AI ではなく本 script
が行う（REQ-020 FNC-003）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "plan"))
from plan_contract import load_plan, normalize_group_key, PlanContractError  # noqa: E402


def _pending_tasks_by_priority(tasks):
    pending = [t for t in tasks if t.get("status") == "pending"]
    return sorted(pending, key=lambda t: t.get("priority", 0), reverse=True)


def _expand_group_members(selected_ids, tasks):
    """選択済みタスクの中にグループタスクがあれば、同じグループの pending 他メンバーを追加する。"""
    by_id = {t["task_id"]: t for t in tasks}
    selected_group_keys = set()
    for task_id in selected_ids:
        group_id = by_id[task_id].get("group_id")
        key = normalize_group_key(group_id)
        if key is not None:
            selected_group_keys.add(key)

    expanded = list(selected_ids)
    seen = set(selected_ids)
    for task in tasks:
        if task.get("status") != "pending":
            continue
        key = normalize_group_key(task.get("group_id"))
        if key in selected_group_keys and task["task_id"] not in seen:
            expanded.append(task["task_id"])
            seen.add(task["task_id"])
    return expanded


def _split_executable_waiting(selected_ids, tasks):
    """選択済みタスクを、依存関係が選択集合内で解決済み(実行可能)か否か(待機)かに分ける。

    計画書全体で `status: completed` の依存は無条件で解決済みとして扱う。選択集合外の
    未完了タスクへの依存は待機扱いにする。
    """
    by_id = {t["task_id"]: t for t in tasks}
    executable = []
    waiting = []
    for task_id in selected_ids:
        depends_on = by_id[task_id].get("depends_on", [])
        has_incomplete_dependency = any(
            by_id.get(dep, {}).get("status") != "completed" for dep in depends_on
        )
        if has_incomplete_dependency:
            waiting.append(task_id)
        else:
            executable.append(task_id)
    return executable, waiting


def select_tasks(plan_data, task_ids=None, count=None):
    """(result | None, errors) を返す。"""
    errors = []
    tasks = plan_data.get("tasks")
    if not isinstance(tasks, list):
        return None, ["計画書に tasks 配列がありません"]
    by_id = {t["task_id"]: t for t in tasks if isinstance(t, dict) and "task_id" in t}

    if task_ids is not None:
        unknown = [t for t in task_ids if t not in by_id]
        if unknown:
            errors.append(f"計画書に存在しない task_id が指定されました: {unknown}")
            return None, errors
        selected = list(task_ids)
        if len(selected) > 1:
            for task_id in selected:
                depends_on = by_id[task_id].get("depends_on", [])
                conflicting = [d for d in depends_on if d in selected]
                if conflicting:
                    errors.append(
                        f"{task_id} は {conflicting} に依存しているため並列実行できません。"
                        "逐次実行してください。"
                    )
        if errors:
            return None, errors
        executable, waiting = _split_executable_waiting(selected, tasks)
        return {
            "selected_task_ids": selected,
            "executable_task_ids": executable,
            "waiting_task_ids": waiting,
            "selected_tasks": [by_id[t] for t in selected],
        }, []

    pending_sorted = _pending_tasks_by_priority(tasks)
    if not pending_sorted:
        return {
            "selected_task_ids": [],
            "executable_task_ids": [],
            "waiting_task_ids": [],
            "selected_tasks": [],
        }, []

    if count is None:
        count = 1

    top_n_ids = [t["task_id"] for t in pending_sorted[:count]]
    selected = _expand_group_members(top_n_ids, tasks)

    for task_id in selected:
        depends_on = by_id[task_id].get("depends_on", [])
        incomplete_external = [
            d for d in depends_on if by_id.get(d, {}).get("status") != "completed"
        ]
        if incomplete_external:
            unresolved_still_pending = [d for d in incomplete_external if d not in selected]
            if unresolved_still_pending:
                errors.append(
                    f"{task_id} は未完了の依存タスクがあります: {unresolved_still_pending}"
                )
    if errors:
        return None, errors

    executable, waiting = _split_executable_waiting(selected, tasks)
    return {
        "selected_task_ids": selected,
        "executable_task_ids": executable,
        "waiting_task_ids": waiting,
        "selected_tasks": [by_id[t] for t in selected],
    }, []


def _emit(payload):
    json.dump(payload, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


def run_cli(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-path", required=True)
    parser.add_argument("--task", help="カンマ区切りの task_id 一覧")
    parser.add_argument("--count", type=int, help="優先度順で選択するタスク数")
    args = parser.parse_args(argv)

    if args.task and args.count:
        _emit({"status": "error", "errors": ["--task と --count は同時に指定できません"]})
        return 20

    try:
        plan_data = load_plan(args.plan_path)
    except PlanContractError as exc:
        _emit({"status": "error", "errors": [str(exc)]})
        return 20

    task_ids = args.task.split(",") if args.task else None
    result, errors = select_tasks(plan_data, task_ids=task_ids, count=args.count)
    if errors:
        _emit({"status": "error", "errors": errors})
        return 20

    _emit({"status": "ok", **result})
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
