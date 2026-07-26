#!/usr/bin/env python3
"""実装完了タスクを、レビュー単位（個別 / グループ合算）に振り分ける。

`group_id` は通し番号付き ("GROUP-001 (1/7)" 等) で記録されるため、単純な文字列一致では
同一グループの各タスクが別グループとして扱われてしまう。本スクリプトは通し番号を除去した
グループキーで正規化したうえで、以下を決定論的に判定する:

- グループの全メンバーが今回の実行結果 (`results`) に揃っており、かつ全て SUCCESS の場合
  → 1 回のグループ合算レビュー対象 (`kind: "group"`)
- グループの一部メンバーしか今回の結果に含まれない場合（過去の別起動で分割実行された等）
  → 揃っていない分は個別レビュー対象として扱う (`kind: "individual"`)。グループとして
    集約するのは「同一起動で全メンバーが success した」場合に限る
- グループの全メンバーが揃っているが 1 件以上 FAILURE の場合
  → グループ全体を保留 (`held_groups`)。中間状態の壊れたグループを合算レビューしたり、
    成功した一部メンバーだけを完了扱いにしたりしない
- `group_id: null`（独立タスク）→ 常に個別レビュー対象

Usage:
    echo '<input_json>' | python3 group_review_batch.py

Input JSON:
    {
      "tasks": [{"task_id": "TASK-001", "group_id": "GROUP-001 (1/7)"}, ...],
      "results": [{"task_id": "TASK-001", "status": "SUCCESS", "files_modified": [...]}, ...]
    }

Output JSON:
    {
      "status": "ok",
      "review_batches": [
        {"kind": "individual", "task_ids": ["TASK-010"], "files": [...]},
        {"kind": "group", "group_key": "GROUP-001", "task_ids": [...], "files": [...]}
      ],
      "held_groups": [
        {"group_key": "GROUP-002", "task_ids": [...], "failed_task_ids": [...], "reason": "partial_failure"}
      ]
    }
"""

import json
import re
import sys

_GROUP_KEY_RE = re.compile(r"^(.*?)\s*\(")


def normalize_group_key(group_id):
    """通し番号付き group_id ("GROUP-001 (1/7)") からグループキー ("GROUP-001") を抽出する。

    括弧を含まない場合はそのまま返す（フォーマットの揺れに対する保守的なフォールバック）。
    """
    if group_id is None:
        return None
    match = _GROUP_KEY_RE.match(group_id)
    if match:
        key = match.group(1).strip()
        return key if key else group_id
    return group_id


class InvalidInputError(Exception):
    """入力の整合性検証に失敗した場合に送出する（呼び出し元は status: error として扱う）"""


def validate_results(tasks, results):
    """results の task_id が一意であり、かつ全て tasks（計画書）に存在することを検証する。

    重複 task_id を許すと同一タスクを複数回レビューする不具合につながり、未知 task_id を
    許すと計画書に存在しないタスクが誤ってレビュー対象に紛れ込む。いずれも fail-fast する。
    """
    known_task_ids = {t["task_id"] for t in tasks}
    seen = set()
    duplicates = set()
    unknown = set()
    for r in results:
        task_id = r["task_id"]
        if task_id in seen:
            duplicates.add(task_id)
        seen.add(task_id)
        if task_id not in known_task_ids:
            unknown.add(task_id)

    if duplicates:
        raise InvalidInputError(
            f"results に重複した task_id が含まれています: {sorted(duplicates)}"
        )
    if unknown:
        raise InvalidInputError(
            f"results に計画書に存在しない task_id が含まれています: {sorted(unknown)}"
        )


def build_review_batches(payload):
    tasks = payload.get("tasks", [])
    results = payload.get("results", [])

    validate_results(tasks, results)

    # task_id -> group_id（計画書の全件から抽出済みの投影）
    task_group_id = {t["task_id"]: t.get("group_id") for t in tasks}

    # グループキー -> そのグループに属する全 task_id（計画書順を維持）
    group_members = {}
    for t in tasks:
        key = normalize_group_key(t.get("group_id"))
        if key is None:
            continue
        group_members.setdefault(key, []).append(t["task_id"])

    # 今回の実行結果を task_id -> result にインデックス
    result_by_task = {r["task_id"]: r for r in results}

    # 今回の結果に現れたグループキーごとに、実行結果を集計
    groups_in_results = {}
    for r in results:
        task_id = r["task_id"]
        group_id = task_group_id.get(task_id)
        key = normalize_group_key(group_id)
        if key is None:
            continue
        groups_in_results.setdefault(key, []).append(r)

    handled_task_ids = set()
    review_batches = []
    held_groups = []

    # 計画書順を維持したまま、グループキーごとに完全性を判定する
    for key, member_task_ids in group_members.items():
        if key not in groups_in_results:
            continue  # 今回の実行に一切登場しないグループはスキップ

        present_results = groups_in_results[key]
        present_task_ids = {r["task_id"] for r in present_results}
        all_members_present = set(member_task_ids) <= present_task_ids

        if not all_members_present:
            # 部分実行（過去の別起動と分割されている等）→ 個別レビューへフォールバック
            continue

        failed_task_ids = [r["task_id"] for r in present_results if r["status"] != "SUCCESS"]
        if failed_task_ids:
            held_groups.append({
                "group_key": key,
                "task_ids": list(member_task_ids),
                "failed_task_ids": failed_task_ids,
                "reason": "partial_failure",
            })
            handled_task_ids.update(member_task_ids)
            continue

        # 全メンバーが今回の実行に揃い、かつ全て SUCCESS → グループ合算レビュー
        files = []
        seen = set()
        for task_id in member_task_ids:
            for f in result_by_task[task_id].get("files_modified", []):
                if f not in seen:
                    seen.add(f)
                    files.append(f)
        review_batches.append({
            "kind": "group",
            "group_key": key,
            "task_ids": list(member_task_ids),
            "files": files,
        })
        handled_task_ids.update(member_task_ids)

    # グループとして処理されなかった SUCCESS タスク（独立タスク・部分実行グループの残り）は個別レビュー
    for r in results:
        task_id = r["task_id"]
        if task_id in handled_task_ids:
            continue
        if r["status"] != "SUCCESS":
            continue
        review_batches.append({
            "kind": "individual",
            "task_ids": [task_id],
            "files": list(r.get("files_modified", [])),
        })

    return {
        "status": "ok",
        "review_batches": review_batches,
        "held_groups": held_groups,
    }


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "message": f"invalid JSON input: {e}"}))
        sys.exit(1)

    if "tasks" not in payload or "results" not in payload:
        print(json.dumps({"status": "error", "message": "tasks / results は必須フィールドです"}))
        sys.exit(1)

    try:
        output = build_review_batches(payload)
    except InvalidInputError as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
