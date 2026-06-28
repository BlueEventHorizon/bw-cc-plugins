#!/usr/bin/env python3
"""plan.yaml から ✅一括対象 (`recommendation: fix` AND `auto_fixable: true` AND
`status: pending`) を抽出する。severity → priority の二段ソート済みで返す。

低レベル script。位置引数のみ (DES-024 §2.3 共通原則)。

Usage:
    python3 list_fixable_pending.py <session_dir>

出力 (stdout JSON):
    plan.yaml あり: {"status": "ok", "plan_present": true,  "count": N, "items": [...]}
    plan.yaml なし: {"status": "ok", "plan_present": false, "count": 0, "items": []}
"""

import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.update_plan import read_plan  # noqa: E402
from review.findings_renderer import PRIORITY_ORDER, SEVERITY_ORDER  # noqa: E402


def _sort_key(item):
    sev = item.get("severity")
    pri = item.get("priority")
    try:
        sev_idx = SEVERITY_ORDER.index(sev)
    except ValueError:
        sev_idx = len(SEVERITY_ORDER)
    try:
        pri_idx = PRIORITY_ORDER.index(pri)
    except ValueError:
        pri_idx = len(PRIORITY_ORDER)
    return (sev_idx, pri_idx)


def _is_fixable_pending(item):
    if not isinstance(item, dict):
        return False
    return (
        item.get("recommendation") == "fix"
        and item.get("auto_fixable") is True
        and item.get("status") == "pending"
    )


def main():
    if len(sys.argv) != 2:
        json.dump(
            {"status": "error", "error": "Usage: list_fixable_pending.py <session_dir>"},
            sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)

    session_dir = sys.argv[1]
    try:
        plan = read_plan(session_dir)
    except FileNotFoundError:
        json.dump(
            {"status": "ok", "plan_present": False, "count": 0, "items": []},
            sys.stdout, ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return

    items = plan.get("items") or []
    fixable = sorted([it for it in items if _is_fixable_pending(it)], key=_sort_key)
    json.dump(
        {"status": "ok", "plan_present": True, "count": len(fixable), "items": fixable},
        sys.stdout, ensure_ascii=False,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
