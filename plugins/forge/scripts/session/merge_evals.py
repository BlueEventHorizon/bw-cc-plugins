#!/usr/bin/env python3
"""evaluator の結果（eval_*.json）を収集し、plan.yaml を一括更新する。

reviewer 1 起動原則 (REQ-004 FNC-412 / DES-028 §2.3) のもと、evaluator は
単一 reviewer の findings を集約した 1 ファイル (eval_<種別>.json) を出力する。
このスクリプトは:
1. session_dir 内の eval_*.json を glob で収集
2. 各 finding の priority (P1|P2|P3) を検証
3. global id をキーに plan.yaml を一括更新 (priority 順にソート)
4. update_plan.py --batch 相当の一括更新を実行

旧 perspective ベース統合 (build_perspective_id_map / _perspective キー /
「perspective 間で判定不一致」reason) は撤廃した。reviewer は 1 起動のため
同一 finding に対する複数 perspective からの判定衝突は発生しない。

Usage:
    python3 merge_evals.py <session_dir>

出力:
    stdout: {"status": "ok", "updated": [...], "fix_count": N, "skip_count": N,
             "needs_review_count": N, "create_issue_count": N,
             "should_continue": true/false, "not_auto_fixable": [...]}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.update_plan import (
    VALID_RECOMMENDATIONS,
    read_plan,
    update_items_batch,
    write_plan,
)

# review_priorities_spec.md / DES-028 で定義された優先度値域
VALID_PRIORITIES = ("P1", "P2", "P3")
# 優先度ソート用の重み (P1 が最優先)
_PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}

# update_plan.VALID_RECOMMENDATIONS への create_issue 追加 (FNC-406 / DES-028 §4.3)。
# TASK-038 と同期する idempotent な追加。
VALID_RECOMMENDATIONS.add("create_issue")


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


def _build_entry(update):
    """eval の update 1件を plan.yaml 更新用エントリに変換する。

    各 finding は global id を持つ前提 (reviewer 1 起動原則)。priority は
    P1/P2/P3 のいずれかでなければならない。
    """
    entry = {"id": update["id"], "status": update.get("status", "pending")}
    if "priority" in update:
        entry["priority"] = update["priority"]
    for key in ("recommendation", "auto_fixable", "skip_reason", "reason"):
        if key in update:
            entry[key] = update[key]
    return entry


def merge_eval_updates(evals):
    """eval JSON の findings を集約し plan.yaml 更新用エントリに整形する。

    reviewer 1 起動原則のもと、各 eval JSON の updates[].id は plan.yaml の
    global id である前提。priority は P1/P2/P3 のいずれかで、不正値や欠落は
    dropped に記録してスキップする。

    Args:
        evals: eval_*.json のパース結果リスト (各要素は {"updates": [...]})

    Returns:
        tuple: (combined_updates, not_auto_fixable_ids, dropped)
            combined_updates: plan.yaml 更新用エントリの list[dict]
                              (priority 昇順 P1>P2>P3、同一 priority 内は id 昇順)
            not_auto_fixable_ids: auto_fixable=False かつ recommendation=fix の id list
            dropped: 検証に失敗したエントリの一覧
                {"id", "reason"} の dict リスト
    """
    combined = []
    not_auto_fixable = []
    dropped = []
    seen_ids = set()

    for eval_data in evals:
        for update in eval_data.get("updates", []):
            item_id = update.get("id")
            if not isinstance(item_id, int) or item_id < 1:
                dropped.append({
                    "id": item_id,
                    "reason": "id が未指定または不正です (1 以上の整数が必要)",
                })
                continue
            if item_id in seen_ids:
                dropped.append({
                    "id": item_id,
                    "reason": (
                        f"id={item_id} が eval 内で重複しています "
                        f"(reviewer 1 起動原則のもとでは findings の id は一意)"
                    ),
                })
                continue

            priority = update.get("priority")
            if priority not in VALID_PRIORITIES:
                dropped.append({
                    "id": item_id,
                    "reason": (
                        f"priority が不正です: {priority!r} "
                        f"(許容値: {list(VALID_PRIORITIES)})"
                    ),
                })
                continue

            recommendation = update.get("recommendation")
            if recommendation is not None and recommendation not in VALID_RECOMMENDATIONS:
                dropped.append({
                    "id": item_id,
                    "reason": (
                        f"recommendation が不正です: {recommendation!r} "
                        f"(許容値: {sorted(VALID_RECOMMENDATIONS)})"
                    ),
                })
                continue

            entry = _build_entry(update)
            combined.append(entry)
            seen_ids.add(item_id)

            if (
                entry.get("recommendation") == "fix"
                and entry.get("auto_fixable") is False
            ):
                not_auto_fixable.append(item_id)

    # priority 順 (P1 > P2 > P3) でソート。同一 priority 内は id 昇順
    combined.sort(key=lambda e: (_PRIORITY_ORDER[e["priority"]], e["id"]))
    not_auto_fixable.sort()

    return combined, not_auto_fixable, dropped


def _emit_error(error, **extra):
    """エラー JSON を stderr に出力する(update_plan.py / write_interpretation.py と統一)。"""
    payload = {"status": "error", "error": error}
    payload.update(extra)
    json.dump(payload, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


def main():
    if len(sys.argv) < 2:
        _emit_error("Usage: merge_evals.py <session_dir>")
        sys.exit(1)

    session_dir = sys.argv[1]

    # plan.yaml 読み込み
    try:
        plan_data = read_plan(session_dir)
    except FileNotFoundError as e:
        _emit_error(str(e))
        sys.exit(1)

    items = plan_data.get("items", [])

    # eval_*.json 収集
    evals = collect_eval_files(session_dir)
    if not evals:
        _emit_error("eval_*.json が見つかりません")
        sys.exit(1)

    # findings 集約・検証
    combined, not_auto_fixable, dropped = merge_eval_updates(evals)

    # 空 combined の扱い:
    #   - dropped あり → 検証失敗 (priority 不正 / id 不正等)。hard error
    #   - dropped なし → 全 eval の updates が空(findings 0 件)。success 扱い
    if not combined and dropped:
        _emit_error(
            "eval の更新を plan.yaml にマップできませんでした",
            dropped=dropped,
        )
        sys.exit(1)

    # plan.yaml 一括更新
    if combined:
        try:
            updated_ids = update_items_batch(items, combined)
        except ValueError as e:
            _emit_error(str(e))
            sys.exit(1)

        plan_data["items"] = items
        write_plan(session_dir, plan_data)
    else:
        updated_ids = []

    # 統計 (FNC-406: should_continue は recommendation=fix のみカウント)
    fix_count = sum(1 for u in combined if u.get("recommendation") == "fix")
    skip_count = sum(1 for u in combined if u.get("recommendation") == "skip")
    needs_review_count = sum(
        1 for u in combined if u.get("recommendation") == "needs_review"
    )
    create_issue_count = sum(
        1 for u in combined if u.get("recommendation") == "create_issue"
    )
    # should_continue: recommendation=fix が 1 件以上ある場合のみ true。
    # create_issue / skip / needs_review は fixer の対象外のためカウントしない (FNC-406)。
    should_continue = fix_count > 0

    response = {
        "status": "ok",
        "updated": updated_ids,
        "fix_count": fix_count,
        "skip_count": skip_count,
        "needs_review_count": needs_review_count,
        "create_issue_count": create_issue_count,
        "should_continue": should_continue,
        "not_auto_fixable": not_auto_fixable,
    }
    # dropped は部分成功の診断情報として含める(combined>0 + dropped>0 のケース)
    if dropped:
        response["dropped"] = dropped

    json.dump(response, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
