#!/usr/bin/env python3
"""evaluator の判定結果をバリデーション付きで plan.yaml に直接適用する。

write_eval.py（検証）と merge_evals.py（plan.yaml 更新・統計計算）を統合し、
中間ファイル eval_{kind}.json を不要にする。

evaluator から呼ばれ、stdin で受け取った JSON テキストを:
1. スキーマ検証（必須キー / enum 違反 / id 重複 / recommendation↔status 相関）
2. priority 順ソート (P1→P2→P3、同一 priority 内は id 昇順)
3. plan.yaml への一括更新
4. 統計計算（fix_count / should_continue 等）

Usage:
    echo '<json>' | python3 apply_eval.py <session_dir> --kind <value>

`--kind` の値域 (write_interpretation.py KIND_CHOICES と一致):
    code / design / requirement / plan / uxui / generic

入力 JSON スキーマ (evaluator SKILL.md §5-2 と一致):
    {
      "kind": "<kind>",          # 任意。存在する場合 --kind と一致必須
      "updates": [
        {
          "id": <int>=1>,        # 必須。1-based ローカル id。updates 内で一意
          "priority": "P1|P2|P3",# 必須
          "recommendation":      # 必須。fix|skip|create_issue|needs_review
            "<value>",
          "status": "<value>",   # recommendation ごとに必須値が決まる:
                                 #   fix          → 任意 (省略時 pending)
                                 #   skip         → "skipped" 必須
                                 #   create_issue → 任意 (省略時 pending)
                                 #   needs_review → "needs_review" 必須
          "auto_fixable": bool,  # recommendation=fix のとき必須 (bool 型)
          "skip_reason": "<v>",  # recommendation=skip のとき必須 (enum)
          "reason": "<text>"     # skip/create_issue/needs_review と
        }                        #   fix(auto_fixable=false) のとき必須
      ]
    }

バリデーション失敗時:
    非ゼロ exit。stderr に違反内容 JSON を出力する
    {"status": "error", "error": "...", "violations": [...]}
    (evaluator が全違反を一度に修正して再試行できるよう、全違反を収集して返す)

出力 (stdout JSON):
    {"status": "ok", "updated": [...], "fix_count": N, "skip_count": N,
     "needs_review_count": N, "create_issue_count": N,
     "should_continue": true/false, "not_auto_fixable": [...]}
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.update_plan import (  # noqa: E402
    VALID_PRIORITIES,
    VALID_RECOMMENDATIONS,
    VALID_STATUSES,
    read_plan,
    update_items_batch,
    write_plan,
)
from session.write_interpretation import KIND_CHOICES  # noqa: E402

# skip_reason の値カタログ。本スクリプトをコード側の SSOT とする。
# 値を変更する場合は evaluator/SKILL.md §5-2 の skip_reason テーブルも同時に更新すること。
VALID_SKIP_REASONS = (
    "out_of_scope",
    "false_positive",
    "intentional_design",
    "already_addressed",
)

# priority ソート用の重み (P1 が最優先)
_PRIORITY_ORDER = {"P1": 0, "P2": 1, "P3": 2}


def validate_eval(data, kind):
    """eval JSON をスキーマ検証し、違反メッセージのリストを返す。

    最初の違反で打ち切らず、全 update を走査して全違反を収集する
    (evaluator が一度の再試行で全件修正できるようにするため)。

    Args:
        data: パース済み JSON (任意の型)
        kind: --kind 引数の値 (KIND_CHOICES のいずれか)

    Returns:
        list[str]: 違反メッセージのリスト (空なら検証成功)
    """
    violations = []

    if not isinstance(data, dict):
        return [f"トップレベルは object である必要があります (実際: {type(data).__name__})"]

    json_kind = data.get("kind")
    if json_kind is not None and json_kind != kind:
        violations.append(
            f"JSON の kind={json_kind!r} が --kind={kind!r} と一致しません"
        )

    if "updates" not in data:
        violations.append("必須キー 'updates' がありません")
        return violations
    updates = data["updates"]
    if not isinstance(updates, list):
        violations.append(
            f"'updates' は配列である必要があります (実際: {type(updates).__name__})"
        )
        return violations

    seen_ids = set()
    for idx, update in enumerate(updates):
        loc = f"updates[{idx}]"
        if not isinstance(update, dict):
            violations.append(
                f"{loc}: object である必要があります (実際: {type(update).__name__})"
            )
            continue

        # id: 必須 / int / >=1 / 一意 (bool は int のサブクラスなので除外)
        item_id = update.get("id")
        if item_id is None:
            violations.append(f"{loc}: 必須キー 'id' がありません")
        elif isinstance(item_id, bool) or not isinstance(item_id, int) or item_id < 1:
            violations.append(
                f"{loc}: 'id' は 1 以上の整数が必要です (実際: {item_id!r})"
            )
        elif item_id in seen_ids:
            violations.append(
                f"{loc}: id={item_id} が updates 内で重複しています "
                f"(reviewer 1 起動原則のもとでは id は一意)"
            )
        else:
            seen_ids.add(item_id)

        id_label = f"id={item_id}" if item_id is not None else loc

        # priority: 必須 / enum
        priority = update.get("priority")
        if priority is None:
            violations.append(f"{id_label}: 必須キー 'priority' がありません")
        elif priority not in VALID_PRIORITIES:
            violations.append(
                f"{id_label}: 'priority' が不正です: {priority!r} "
                f"(許容値: {list(VALID_PRIORITIES)})"
            )

        # status: 任意 / 指定時は enum
        status = update.get("status")
        if status is not None and status not in VALID_STATUSES:
            violations.append(
                f"{id_label}: 'status' が不正です: {status!r} "
                f"(許容値: {sorted(VALID_STATUSES)})"
            )

        # recommendation: 必須 / enum
        recommendation = update.get("recommendation")
        if recommendation is None:
            violations.append(f"{id_label}: 必須キー 'recommendation' がありません")
        elif recommendation not in VALID_RECOMMENDATIONS:
            violations.append(
                f"{id_label}: 'recommendation' が不正です: {recommendation!r} "
                f"(許容値: {sorted(VALID_RECOMMENDATIONS)})"
            )

        violations.extend(_validate_recommendation_fields(update, recommendation, id_label))

    return violations


def _validate_recommendation_fields(update, recommendation, id_label):
    """recommendation 値に応じた条件付きフィールドを検証する。

    - fix          → auto_fixable 必須 (bool 型)。
                     auto_fixable=false のとき reason 必須 (fixer の修正方針根拠)。
                     status は任意 (省略時 pending)。
    - skip         → skip_reason 必須 (enum) / reason 必須 / status="skipped" 必須
    - create_issue → reason 必須 / status は任意 (省略時 pending)
    - needs_review → reason 必須 / status="needs_review" 必須
    """
    violations = []

    # recommendation/status 相関チェック
    _REQUIRED_STATUS = {
        "skip": "skipped",
        "needs_review": "needs_review",
    }
    if recommendation in _REQUIRED_STATUS:
        expected_status = _REQUIRED_STATUS[recommendation]
        actual_status = update.get("status")
        if actual_status is None:
            violations.append(
                f"{id_label}: recommendation={recommendation} には "
                f"'status: {expected_status}' が必須です (省略すると "
                f"'pending' にデフォルトし未処理扱いになります)"
            )
        elif actual_status != expected_status:
            violations.append(
                f"{id_label}: recommendation={recommendation} では "
                f"'status' は {expected_status!r} である必要があります "
                f"(実際: {actual_status!r})"
            )

    if recommendation == "fix":
        auto_fixable = update.get("auto_fixable")
        if auto_fixable is None:
            violations.append(
                f"{id_label}: recommendation=fix には 'auto_fixable' (bool) が必須です"
            )
        elif not isinstance(auto_fixable, bool):
            violations.append(
                f"{id_label}: 'auto_fixable' は bool 型が必要です "
                f"(実際: {type(auto_fixable).__name__})"
            )
        elif auto_fixable is False and not _has_text(update.get("reason")):
            violations.append(
                f"{id_label}: auto_fixable=false には 'reason' (修正方針) が必須です"
            )
    elif recommendation == "skip":
        skip_reason = update.get("skip_reason")
        if skip_reason is None:
            violations.append(
                f"{id_label}: recommendation=skip には 'skip_reason' が必須です"
            )
        elif skip_reason not in VALID_SKIP_REASONS:
            violations.append(
                f"{id_label}: 'skip_reason' が不正です: {skip_reason!r} "
                f"(許容値: {list(VALID_SKIP_REASONS)})"
            )
        if not _has_text(update.get("reason")):
            violations.append(
                f"{id_label}: recommendation=skip には 'reason' が必須です"
            )
    elif recommendation in ("create_issue", "needs_review"):
        if not _has_text(update.get("reason")):
            violations.append(
                f"{id_label}: recommendation={recommendation} には 'reason' が必須です"
            )

    return violations


def _has_text(value):
    """非空文字列なら True。"""
    return isinstance(value, str) and value.strip() != ""


def _build_entry(update):
    """eval の update 1件を plan.yaml 更新用エントリに変換する。

    status 省略時は "pending" をデフォルトとして補完する。
    """
    entry = {"id": update["id"], "status": update.get("status", "pending")}
    if "priority" in update:
        entry["priority"] = update["priority"]
    for key in ("recommendation", "auto_fixable", "skip_reason", "reason"):
        if key in update:
            entry[key] = update[key]
    return entry


def apply_eval(session_dir, kind, data):
    """eval JSON を検証し plan.yaml を直接更新する。

    Args:
        session_dir: セッションディレクトリパス
        kind: 種別 (KIND_CHOICES のいずれか)
        data: パース済み JSON

    Returns:
        dict: {"updated": [...], "fix_count": N, "skip_count": N,
               "needs_review_count": N, "create_issue_count": N,
               "should_continue": bool, "not_auto_fixable": [...]}

    Raises:
        ValueError: スキーマ検証に失敗 (args に違反リストを格納)
        FileNotFoundError: plan.yaml が存在しない
    """
    violations = validate_eval(data, kind)
    if violations:
        raise ValueError(violations)

    plan_data = read_plan(session_dir)
    items = plan_data.get("items", [])

    updates = data["updates"]

    # priority 順 (P1→P2→P3) でソート。同一 priority 内は id 昇順
    sorted_updates = sorted(
        updates,
        key=lambda u: (_PRIORITY_ORDER[u["priority"]], u["id"]),
    )

    # plan.yaml 更新用エントリに変換
    entries = [_build_entry(u) for u in sorted_updates]

    updated_ids = []
    if entries:
        updated_ids = update_items_batch(items, entries)
        plan_data["items"] = items
        write_plan(session_dir, plan_data)

    # 統計計算 (FNC-406: should_continue は recommendation=fix のみカウント)
    fix_count = sum(1 for u in updates if u.get("recommendation") == "fix")
    skip_count = sum(1 for u in updates if u.get("recommendation") == "skip")
    needs_review_count = sum(1 for u in updates if u.get("recommendation") == "needs_review")
    create_issue_count = sum(1 for u in updates if u.get("recommendation") == "create_issue")
    # should_continue: recommendation=fix が 1 件以上ある場合のみ true。
    # create_issue / skip / needs_review は fixer の対象外 (FNC-406)。
    should_continue = fix_count > 0

    not_auto_fixable = sorted(
        u["id"]
        for u in updates
        if u.get("recommendation") == "fix" and u.get("auto_fixable") is False
    )

    return {
        "updated": updated_ids,
        "fix_count": fix_count,
        "skip_count": skip_count,
        "needs_review_count": needs_review_count,
        "create_issue_count": create_issue_count,
        "should_continue": should_continue,
        "not_auto_fixable": not_auto_fixable,
    }


def _emit_error(error, **extra):
    """エラー JSON を stderr に出力する。"""
    payload = {"status": "error", "error": error}
    payload.update(extra)
    json.dump(payload, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="evaluator の判定結果を検証付きで plan.yaml に直接適用する"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    parser.add_argument(
        "--kind",
        required=True,
        choices=KIND_CHOICES,
        help="種別 (code / design / requirement / plan / uxui / generic)",
    )
    args = parser.parse_args()

    raw = sys.stdin.read()
    if not raw.strip():
        _emit_error("stdin が空です")
        sys.exit(1)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        _emit_error(f"JSON パースエラー: {e}")
        sys.exit(1)

    try:
        result = apply_eval(args.session_dir, args.kind, data)
    except FileNotFoundError as e:
        _emit_error(str(e))
        sys.exit(1)
    except ValueError as e:
        violations = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
        _emit_error("eval JSON のスキーマ検証に失敗しました", violations=violations)
        sys.exit(1)

    json.dump({"status": "ok", **result}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
