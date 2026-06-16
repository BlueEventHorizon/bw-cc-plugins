#!/usr/bin/env python3
"""evaluator の判定結果 (eval_{kind}.json) をバリデーション付きで書き出す。

evaluator から呼ばれ、stdin で受け取った JSON テキストをスキーマ検証してから
`{session_dir}/eval_{kind}.json` に書き出す。AI 直接 Write のフォーマット崩壊
(必須キー抜け / enum 違反 / id 重複) を防ぎ、後段 merge_evals.py のサイレント
脱落リスクを下げる。`write_interpretation.py` と対称的な設計とする (Issue #38)。

Usage:
    echo '<json>' | python3 write_eval.py <session_dir> --kind <value>

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
                                 #   fix          → 任意 (省略時 merge_evals が pending を補完)
                                 #   skip         → "skipped" 必須
                                 #   create_issue → 任意 (省略時 pending。present-findings が
                                 #                  issue 作成後に skipped へ遷移)
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
    (evaluator が全違反を一度に修正して再試行できるよう、最初の 1 件で
     打ち切らず全違反を収集して返す)

出力 (stdout JSON):
    {"status": "ok", "path": ".../eval_{kind}.json", "count": N}
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.store import SessionStore  # noqa: E402
from session.merge_evals import VALID_PRIORITIES  # noqa: E402
from session.update_plan import (  # noqa: E402
    VALID_RECOMMENDATIONS,
    VALID_STATUSES,
)
from session.write_interpretation import KIND_CHOICES  # noqa: E402

# skip_reason の値カタログ。本スクリプトをコード側の SSOT とする。
# 値を変更する場合は evaluator/SKILL.md §5-2 の skip_reason テーブルも同時に更新すること
# (逆に SKILL.md を先に変更した場合も本スクリプトを必ず追従させること)。
VALID_SKIP_REASONS = (
    "out_of_scope",
    "false_positive",
    "intentional_design",
    "already_addressed",
)


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

    # kind 整合 (存在する場合のみ。merge_evals は kind を使わないが
    # 取り違え検出のため --kind と一致を要求する)
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
                     status は任意 (省略時 merge_evals がデフォルト "pending" を補完)。
    - skip         → skip_reason 必須 (enum) / reason 必須 / status="skipped" 必須
    - create_issue → reason 必須 / status は任意 (省略時 pending。present-findings が
                     issue 作成後に skipped へ遷移。SKILL.md §5-2 参照)
    - needs_review → reason 必須 / status="needs_review" 必須
    """
    violations = []

    # recommendation/status 相関チェック
    # skip / needs_review は status の期待値が固定。省略すると merge_evals が "pending"
    # にデフォルトし summarize_plan の終了条件判定が正しく動かない。
    # create_issue は pending のまま (present-findings が遷移させる) なので除外。
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
                f"merge_evals が 'pending' にデフォルトし未処理扱いになります)"
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


def write_eval(session_dir, kind, data):
    """eval_{kind}.json を検証付きで書き出す。

    Args:
        session_dir: セッションディレクトリパス
        kind: 種別 (KIND_CHOICES のいずれか)
        data: パース済み JSON

    Returns:
        dict: {"path", "count"}

    Raises:
        ValueError: スキーマ検証に失敗 (args に違反リストを格納)
    """
    violations = validate_eval(data, kind)
    if violations:
        raise ValueError(violations)

    # 出力には正規の kind を必ず含める (入力に kind がなくても補完)
    payload = {"kind": kind, "updates": data["updates"]}
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    target_name = f"eval_{kind}.json"
    target = SessionStore(session_dir).write_text(target_name, content)

    return {"path": str(target), "count": len(data["updates"])}


def _emit_error(error, **extra):
    """エラー JSON を stderr に出力する (merge_evals.py / write_interpretation.py と統一)。"""
    payload = {"status": "error", "error": error}
    payload.update(extra)
    json.dump(payload, sys.stderr, ensure_ascii=False)
    sys.stderr.write("\n")


def main():
    parser = argparse.ArgumentParser(
        description="evaluator の判定結果 (eval_{kind}.json) を検証付きで書き出す"
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
        result = write_eval(args.session_dir, args.kind, data)
    except ValueError as e:
        violations = e.args[0] if e.args and isinstance(e.args[0], list) else [str(e)]
        _emit_error("eval JSON のスキーマ検証に失敗しました", violations=violations)
        sys.exit(1)

    json.dump({"status": "ok", **result}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
