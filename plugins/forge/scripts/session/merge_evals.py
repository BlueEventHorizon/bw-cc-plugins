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
        dict[str, list[int]]: perspective 名 → グローバル ID リスト(出現順)
    """
    mapping = {}
    for item in items:
        p = item.get("perspective", "")
        if not p:
            # perspective 未指定の item はマッピングに登録しない
            # (空文字キーで登録すると perspective="" の eval と誤マッチする)
            continue
        mapping.setdefault(p, []).append(item["id"])
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


def _build_entry(global_id, update, perspective):
    """eval の update 1件を combined エントリに変換する。"""
    entry = {
        "id": global_id,
        "status": update.get("status", "pending"),
        "_perspective": perspective,
    }
    for key in ("recommendation", "auto_fixable", "skip_reason", "reason"):
        if key in update:
            entry[key] = update[key]
    return entry


def _reconcile_entries(entries):
    """同一 global_id への複数 entries を1つに統合する。

    - 全 entry の recommendation が一致 → 最後の entry をベースに reason を連結
    - 不一致 → recommendation: needs_review / status: needs_review に
      エスカレーションし、reason に各 perspective の判定を記録
    """
    if len(entries) == 1:
        merged = dict(entries[0])
        merged.pop("_perspective", None)
        return merged

    recs = {e.get("recommendation") for e in entries if "recommendation" in e}
    recs.discard(None)

    if len(recs) <= 1:
        base = dict(entries[-1])
        base.pop("_perspective", None)
        return base

    parts = []
    for e in entries:
        p = e.get("_perspective") or "?"
        rec = e.get("recommendation", "(未指定)")
        parts.append(f"{p}={rec}")
    merged = {
        "id": entries[0]["id"],
        "status": "needs_review",
        "recommendation": "needs_review",
        "reason": "perspective 間で判定不一致: " + " / ".join(parts),
    }
    return merged


def merge_eval_updates(evals, perspective_id_map):
    """eval JSON のローカル ID を plan.yaml のグローバル ID に変換して統合する。

    同一 global_id に対する複数 perspective の判定は次のルールで統合する:
      - 全 perspective の recommendation が一致 → 最後の eval を採用
      - 不一致 → recommendation: needs_review にエスカレーション

    Args:
        evals: eval_*.json のパース結果リスト
        perspective_id_map: perspective → [global_id, ...] のマッピング

    Returns:
        tuple: (combined_updates, not_auto_fixable_ids, dropped)
            combined_updates: plan.yaml 更新用の dict リスト(global_id の重複なし)
            not_auto_fixable_ids: auto_fixable=false かつ recommendation=fix の
                                  グローバル ID リスト
            dropped: ID 変換に失敗したエントリの一覧
                {"perspective", "local_id", "reason"} の dict リスト
                (呼び出し元が診断情報として出力するために使用)
    """
    buckets = {}  # global_id -> [entry, ...]
    order = []  # 出現順を保持
    dropped = []  # ID 変換失敗の診断情報

    for eval_data in evals:
        perspective = eval_data.get("perspective", "")
        global_ids = perspective_id_map.get(perspective, [])
        updates = eval_data.get("updates", [])

        if not global_ids and updates:
            # perspective が plan.yaml に存在しない(evaluator 側のバグ or 設定不整合)
            for u in updates:
                dropped.append({
                    "perspective": perspective,
                    "local_id": u.get("id"),
                    "reason": "perspective が plan.yaml に存在しない",
                })
            continue

        for u in updates:
            local_id = u.get("id")
            if local_id is None or local_id < 1:
                dropped.append({
                    "perspective": perspective,
                    "local_id": local_id,
                    "reason": "local_id が未指定または 1 未満",
                })
                continue
            idx = local_id - 1  # 0-based
            if idx >= len(global_ids):
                dropped.append({
                    "perspective": perspective,
                    "local_id": local_id,
                    "reason": (
                        f"local_id が範囲外: plan.yaml の {perspective} は "
                        f"{len(global_ids)} 件"
                    ),
                })
                continue

            global_id = global_ids[idx]
            if global_id not in buckets:
                buckets[global_id] = []
                order.append(global_id)
            buckets[global_id].append(_build_entry(global_id, u, perspective))

    combined = []
    not_auto_fixable = []
    for global_id in order:
        entries = buckets[global_id]
        merged = _reconcile_entries(entries)
        combined.append(merged)

        if (
            merged.get("recommendation") == "fix"
            and merged.get("auto_fixable") is False
        ):
            not_auto_fixable.append(global_id)

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

    # perspective → global ID マッピング構築
    perspective_id_map = build_perspective_id_map(items)

    # eval_*.json 収集
    evals = collect_eval_files(session_dir)
    if not evals:
        _emit_error("eval_*.json が見つかりません")
        sys.exit(1)

    # ローカル ID → グローバル ID 変換・統合
    combined, not_auto_fixable, dropped = merge_eval_updates(evals, perspective_id_map)

    # 空 combined の扱い:
    #   - dropped あり → ID 変換失敗(evaluator のローカル ID 順序契約違反 / 設定不整合)。hard error
    #   - dropped なし → 全 eval の updates が空(findings 0 件)。success 扱い (fix_count=0)
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
        write_plan(
            session_dir,
            plan_data,
            meta={
                "phase": "evaluation_merged",
                "phase_status": "completed",
                "active_artifact": "plan.yaml",
            },
        )
    else:
        updated_ids = []

    # 統計
    fix_count = sum(1 for u in combined if u.get("recommendation") == "fix")
    skip_count = sum(1 for u in combined if u.get("recommendation") == "skip")
    needs_review_count = sum(
        1 for u in combined if u.get("recommendation") == "needs_review"
    )
    should_continue = fix_count > 0

    response = {
        "status": "ok",
        "updated": updated_ids,
        "fix_count": fix_count,
        "skip_count": skip_count,
        "needs_review_count": needs_review_count,
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
