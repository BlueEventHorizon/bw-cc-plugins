#!/usr/bin/env python3
"""plan.yaml の進捗集計とルーティング判定を返す。

`summarize_plan.summarize_pending` を内部で呼び、以下を追加して返す:
- `fixable_pending`: ✅ 一括対象数 (recommendation:fix AND auto_fixable:true AND status:pending)
- `create_issue_pending`: 📌 一括対象数 (recommendation:create_issue AND status:pending)
- `in_progress`: status:in_progress の件数
- `next_action`: `"present"` | `"finish"` | `"resume_prompt"`

`next_action` 判定ルール:
- 未処理 (pending/needs_review) 0 件 + in_progress 0 件 → "finish"
  (全件 fixed / skipped で決着済み。skipped は決着状態であり中断指標ではない)
- in_progress > 0 → "resume_prompt" (真の中断)
- pending > 0 + fixed > 0 → "resume_prompt" (修正中断の続行)
- それ以外 (pending あり、fixed なし) → "present"
  (初回フロー: evaluator が一部を skipped にしただけの状態も含む)

低レベル script。位置引数のみ (DES-024 §2.3 共通原則)。

Usage:
    python3 summarize_progress.py <session_dir>

出力 (stdout JSON):
    plan.yaml あり: {... summarize_pending の全フィールド ..., "fixable_pending": N,
                    "create_issue_pending": N, "in_progress": N, "next_action": "..."}
    plan.yaml なし: {"status": "ok", "plan_present": false, "next_action": "present"}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.summarize_plan import summarize_pending  # noqa: E402
from session.update_plan import read_plan  # noqa: E402


def _classify(items):
    fixable_pending = 0
    create_issue_pending = 0
    in_progress = 0
    for it in items or []:
        if not isinstance(it, dict):
            continue
        st = it.get("status")
        rec = it.get("recommendation")
        if st == "in_progress":
            in_progress += 1
        if st == "pending" and rec == "fix" and it.get("auto_fixable") is True:
            fixable_pending += 1
        if st == "pending" and rec == "create_issue":
            create_issue_pending += 1
    return {
        "fixable_pending": fixable_pending,
        "create_issue_pending": create_issue_pending,
        "in_progress": in_progress,
    }


def _decide_next_action(base, extra):
    unprocessed = base["unprocessed_total"]
    if unprocessed == 0 and extra["in_progress"] == 0:
        return "finish"
    if extra["in_progress"] > 0:
        return "resume_prompt"
    if base["fixed"] > 0:
        return "resume_prompt"
    return "present"


def main():
    if len(sys.argv) != 2:
        json.dump(
            {"status": "error", "error": "Usage: summarize_progress.py <session_dir>"},
            sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)

    session_dir = sys.argv[1]
    plan_path = Path(session_dir) / "plan.yaml"
    if not plan_path.is_file():
        json.dump(
            {"status": "ok", "plan_present": False, "next_action": "present"},
            sys.stdout, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return

    try:
        base = summarize_pending(plan_path)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.stderr.write("\n")
        sys.exit(1)

    try:
        plan = read_plan(session_dir)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr)
        sys.stderr.write("\n")
        sys.exit(1)

    items = plan.get("items") or []
    extra = _classify(items)
    next_action = _decide_next_action(base, extra)

    result = {"status": "ok", "plan_present": True}
    result.update(base)
    result.update(extra)
    result["next_action"] = next_action
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
