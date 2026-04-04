#!/usr/bin/env python3
"""evaluator の結果（eval_*.json）を収集し、plan.yaml を一括更新する。

各 evaluator は perspective ごとに eval_{perspective}.json を出力する。
このスクリプトは:
1. session_dir 内の eval_*.json を glob で収集
2. plan.yaml から perspective ごとの項目 ID マッピングを動的に構築
3. eval JSON のローカル ID → plan.yaml のグローバル ID に変換
4. update_plan.py --batch 相当の一括更新を実行

Usage:
    python3 merge_evals.py <session_dir>

出力:
    stdout: {"status": "ok", "updated": [...], "fix_count": N, "skip_count": N,
             "needs_review_count": N, "should_continue": true/false,
             "not_auto_fixable": [...]}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.update_plan import read_plan, update_items_batch, write_plan


def build_perspective_id_map(items):
    """plan.yaml の items から perspective → [global_id, ...] のマッピングを構築する。

    Args:
        items: plan.yaml の items リスト

    Returns:
        dict[str, list[int]]: perspective 名 → グローバル ID リスト（出現順）
    """
    mapping = {}
    for item in items:
        p = item.get("perspective", "")
        if p not in mapping:
            mapping[p] = []
        mapping[p].append(item["id"])
    return mapping


def collect_eval_files(session_dir):
    """session_dir 内の eval_*.json を収集する。

    Args:
        session_dir: セッションディレクトリパス

    Returns:
        list[dict]: パース済み eval データのリスト
    """
    evals = []
    for path in sorted(Path(session_dir).glob("eval_*.json")):
        with open(path, encoding="utf-8") as f:
            evals.append(json.load(f))
    return evals


def merge_eval_updates(evals, perspective_id_map):
    """eval JSON のローカル ID を plan.yaml のグローバル ID に変換して統合する。

    Args:
        evals: eval_*.json のパース結果リスト
        perspective_id_map: perspective → [global_id, ...] のマッピング

    Returns:
        tuple: (combined_updates, not_auto_fixable_ids)
            combined_updates: plan.yaml 更新用の dict リスト
            not_auto_fixable_ids: auto_fixable=false かつ recommendation=fix の
                                  グローバル ID リスト
    """
    combined = []
    not_auto_fixable = []

    for eval_data in evals:
        perspective = eval_data.get("perspective", "")
        global_ids = perspective_id_map.get(perspective, [])
        updates = eval_data.get("updates", [])

        for u in updates:
            local_id = u.get("id")
            if local_id is None or local_id < 1:
                continue
            idx = local_id - 1  # 0-based
            if idx >= len(global_ids):
                continue

            global_id = global_ids[idx]
            entry = {
                "id": global_id,
                "status": u.get("status", "pending"),
            }
            if "recommendation" in u:
                entry["recommendation"] = u["recommendation"]
            if "auto_fixable" in u:
                entry["auto_fixable"] = u["auto_fixable"]
            if "skip_reason" in u:
                entry["skip_reason"] = u["skip_reason"]
            if "reason" in u:
                entry["reason"] = u["reason"]
            combined.append(entry)

            # auto_fixable=false かつ fix 推奨の項目を記録
            if u.get("recommendation") == "fix" and u.get("auto_fixable") is False:
                not_auto_fixable.append(global_id)

    return combined, not_auto_fixable


def main():
    if len(sys.argv) < 2:
        json.dump(
            {"status": "error", "error": "Usage: merge_evals.py <session_dir>"},
            sys.stdout, ensure_ascii=False,
        )
        print()
        sys.exit(1)

    session_dir = sys.argv[1]

    # plan.yaml 読み込み
    try:
        plan_data = read_plan(session_dir)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stdout, ensure_ascii=False)
        print()
        sys.exit(1)

    items = plan_data.get("items", [])

    # perspective → global ID マッピング構築
    perspective_id_map = build_perspective_id_map(items)

    # eval_*.json 収集
    evals = collect_eval_files(session_dir)
    if not evals:
        json.dump(
            {"status": "error", "error": "eval_*.json が見つかりません"},
            sys.stdout, ensure_ascii=False,
        )
        print()
        sys.exit(1)

    # ローカル ID → グローバル ID 変換・統合
    combined, not_auto_fixable = merge_eval_updates(evals, perspective_id_map)
    if not combined:
        json.dump(
            {"status": "error", "error": "更新対象がありません"},
            sys.stdout, ensure_ascii=False,
        )
        print()
        sys.exit(1)

    # plan.yaml 一括更新
    try:
        updated_ids = update_items_batch(items, combined)
    except ValueError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stdout, ensure_ascii=False)
        print()
        sys.exit(1)

    plan_data["items"] = items
    write_plan(session_dir, plan_data)

    # 統計
    fix_count = sum(1 for u in combined if u.get("recommendation") == "fix")
    skip_count = sum(1 for u in combined if u.get("recommendation") == "skip")
    needs_review_count = sum(
        1 for u in combined if u.get("recommendation") == "needs_review"
    )
    should_continue = fix_count > 0

    json.dump(
        {
            "status": "ok",
            "updated": updated_ids,
            "fix_count": fix_count,
            "skip_count": skip_count,
            "needs_review_count": needs_review_count,
            "should_continue": should_continue,
            "not_auto_fixable": not_auto_fixable,
        },
        sys.stdout, ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
