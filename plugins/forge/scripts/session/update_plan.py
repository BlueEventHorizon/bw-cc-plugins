#!/usr/bin/env python3
"""plan.yaml のステータスを更新する。

evaluator / present-findings / fixer から呼び出され、
plan.yaml 内の特定項目の status を更新して書き戻す。

Usage（単一項目更新）:
    python3 update_plan.py <session_dir> --id 1 --status fixed \
        [--fixed-at "2026-03-09T18:35:00Z"] \
        [--files-modified file1.py file2.py] \
        [--skip-reason "理由"]

Usage（バッチ更新）:
    echo '<json>' | python3 update_plan.py <session_dir> --batch

出力:
    stdout: {"status": "ok", "updated": [1, 2], "plan_path": "..."}
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import read_yaml, write_nested_yaml, now_iso

VALID_STATUSES = {"pending", "in_progress", "fixed", "skipped", "needs_review"}
VALID_RECOMMENDATIONS = {"fix", "skip", "needs_review"}

# plan.yaml items のフィールド出力順序
ITEM_FIELD_ORDER = [
    "id", "severity", "title", "status",
    "recommendation", "auto_fixable", "reason",
    "fixed_at", "files_modified", "skip_reason",
]


def read_plan(session_dir):
    """plan.yaml を読み込む。

    Args:
        session_dir: セッションディレクトリパス

    Returns:
        dict: パース結果（items キーを含む）

    Raises:
        FileNotFoundError: plan.yaml が存在しない
    """
    plan_path = Path(session_dir) / "plan.yaml"
    if not plan_path.exists():
        raise FileNotFoundError(f"plan.yaml が見つかりません: {plan_path}")
    return read_yaml(str(plan_path))


def update_item(items, item_id, updates):
    """単一項目を更新する。

    Args:
        items: plan.yaml の items リスト
        item_id: 更新対象の id（整数）
        updates: 更新内容の dict（status, fixed_at, files_modified, skip_reason）

    Returns:
        bool: 更新成功なら True

    Raises:
        ValueError: 不正な status 値
    """
    status = updates.get("status")
    if status and status not in VALID_STATUSES:
        raise ValueError(f"不正な status です: {status}（許容値: {VALID_STATUSES}）")

    recommendation = updates.get("recommendation")
    if recommendation and recommendation not in VALID_RECOMMENDATIONS:
        raise ValueError(
            f"不正な recommendation です: {recommendation}"
            f"（許容値: {VALID_RECOMMENDATIONS}）"
        )

    for item in items:
        if item.get("id") == item_id:
            if status:
                item["status"] = status
            if "recommendation" in updates:
                item["recommendation"] = updates["recommendation"]
            if "auto_fixable" in updates:
                item["auto_fixable"] = updates["auto_fixable"]
            if "reason" in updates:
                item["reason"] = updates["reason"]
            if "fixed_at" in updates:
                item["fixed_at"] = updates["fixed_at"]
            elif status == "fixed" and not item.get("fixed_at"):
                item["fixed_at"] = now_iso()
            if "files_modified" in updates:
                item["files_modified"] = updates["files_modified"]
            if "skip_reason" in updates:
                item["skip_reason"] = updates["skip_reason"]
            return True
    return False


def update_items_batch(items, updates_list):
    """複数項目を一括更新する。

    Args:
        items: plan.yaml の items リスト
        updates_list: 更新内容の list[dict]（各要素に id, status 必須）

    Returns:
        list[int]: 更新した id のリスト

    Raises:
        ValueError: 不正なデータ
    """
    updated_ids = []
    for upd in updates_list:
        item_id = upd.get("id")
        if item_id is None:
            raise ValueError("バッチ更新の各要素には id が必須です")
        if update_item(items, item_id, upd):
            updated_ids.append(item_id)
    return updated_ids


def write_plan(session_dir, plan_data):
    """plan.yaml を書き戻す。

    Args:
        session_dir: セッションディレクトリパス
        plan_data: items を含む dict

    Returns:
        str: 書き出したファイルのパス
    """
    # フィールド順序を揃える
    ordered_items = []
    for item in plan_data["items"]:
        ordered = {}
        for key in ITEM_FIELD_ORDER:
            if key in item:
                val = item[key]
                # 空文字・空リスト・None はスキップ（yaml_utils が処理）
                ordered[key] = val
        # 残りのフィールド
        for key in item:
            if key not in ordered:
                ordered[key] = item[key]
        ordered_items.append(ordered)

    sections = [("items", ordered_items)]
    output_path = Path(session_dir) / "plan.yaml"
    write_nested_yaml(str(output_path), sections)
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="plan.yaml のステータスを更新する"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    parser.add_argument("--batch", action="store_true",
                        help="stdin JSON によるバッチ更新モード")
    parser.add_argument("--id", type=int, help="更新対象の項目 ID")
    parser.add_argument("--status", help="新しいステータス")
    parser.add_argument("--fixed-at", help="修正完了日時（省略時は自動生成）")
    parser.add_argument("--files-modified", nargs="*",
                        help="修正ファイルパス一覧")
    parser.add_argument("--skip-reason", help="スキップ理由")
    parser.add_argument("--recommendation",
                        help="evaluator の推奨（fix / skip / needs_review）")
    parser.add_argument("--auto-fixable", type=str,
                        help="自動修正可能か（true / false）")
    parser.add_argument("--reason", help="evaluator の判定理由")
    args = parser.parse_args()

    try:
        plan_data = read_plan(args.session_dir)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.exit(1)

    items = plan_data.get("items", [])

    if args.batch:
        # バッチ更新: stdin から JSON を読み込み
        try:
            batch_data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            json.dump({"status": "error", "error": f"JSON パースエラー: {e}"}, sys.stderr)
            sys.exit(1)

        # {"updates": [...]} 形式と [...] 形式の両方を受け付ける
        if isinstance(batch_data, list):
            updates_list = batch_data
        else:
            updates_list = batch_data.get("updates", [])
        if not updates_list:
            json.dump({"status": "error", "error": "updates が空です"}, sys.stderr)
            sys.exit(1)

        try:
            updated_ids = update_items_batch(items, updates_list)
        except ValueError as e:
            json.dump({"status": "error", "error": str(e)}, sys.stderr)
            sys.exit(1)
    else:
        # 単一項目更新
        if args.id is None or args.status is None:
            json.dump(
                {"status": "error", "error": "--id と --status は必須です（--batch 未指定時）"},
                sys.stderr,
            )
            sys.exit(1)

        updates = {"status": args.status}
        if args.recommendation:
            updates["recommendation"] = args.recommendation
        if args.auto_fixable is not None:
            updates["auto_fixable"] = args.auto_fixable.lower() == "true"
        if args.reason:
            updates["reason"] = args.reason
        if args.fixed_at:
            updates["fixed_at"] = args.fixed_at
        if args.files_modified:
            updates["files_modified"] = args.files_modified
        if args.skip_reason:
            updates["skip_reason"] = args.skip_reason

        try:
            found = update_item(items, args.id, updates)
        except ValueError as e:
            json.dump({"status": "error", "error": str(e)}, sys.stderr)
            sys.exit(1)

        if not found:
            json.dump(
                {"status": "error", "error": f"id={args.id} が見つかりません"},
                sys.stderr,
            )
            sys.exit(1)

        updated_ids = [args.id]

    plan_data["items"] = items
    plan_path = write_plan(args.session_dir, plan_data)

    json.dump(
        {"status": "ok", "updated": updated_ids, "plan_path": plan_path},
        sys.stdout, ensure_ascii=False,
    )
    print()


if __name__ == "__main__":
    main()
