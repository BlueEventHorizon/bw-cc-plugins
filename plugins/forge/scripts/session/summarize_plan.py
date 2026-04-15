#!/usr/bin/env python3
"""plan.yaml の未処理指摘を集計する。

/forge:review の Phase 5「終了確認」で、未処理（status が pending / needs_review）の
件数と概要を取得するために使用する。

「未処理」の定義:
    status が pending / needs_review の指摘。
    fixed / skipped は決着済みなので未処理ではない。

Usage:
    python3 summarize_plan.py <session_dir>

出力:
    stdout に JSON で集計結果を出力。
    {
      "total": 全件数,
      "fixed": 修正済み件数,
      "skipped": 対応しない件数,
      "unprocessed_total": 未処理件数,
      "by_severity": {"critical": N, "major": N, "minor": N},
      "by_status": {"pending": N, "needs_review": N},
      "unprocessed_ids": [未処理の id 一覧],
      "titles": [未処理タイトルの先頭10件]
    }
"""

import argparse
import json
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR.parent))

from session.yaml_utils import read_yaml

# 未処理とみなす status 値
UNPROCESSED_STATUSES = ("pending", "needs_review")

# 可視化時に表示する先頭タイトル件数
TITLE_PREVIEW_LIMIT = 10


def summarize_pending(plan_path):
    """plan.yaml の未処理指摘を集計する。

    Args:
        plan_path: plan.yaml のパス（str / Path）

    Returns:
        dict: 集計結果

    Raises:
        FileNotFoundError: plan.yaml が存在しない
    """
    plan_path = Path(plan_path)
    if not plan_path.exists():
        raise FileNotFoundError(f"plan.yaml が見つかりません: {plan_path}")

    plan = read_yaml(str(plan_path))
    items = plan.get("items") or []

    unprocessed = [
        i for i in items
        if i.get("status") in UNPROCESSED_STATUSES
    ]

    by_severity = {"critical": 0, "major": 0, "minor": 0}
    by_status = {"pending": 0, "needs_review": 0}
    for item in unprocessed:
        sev = item.get("severity")
        if sev in by_severity:
            by_severity[sev] += 1
        st = item.get("status")
        if st in by_status:
            by_status[st] += 1

    fixed = sum(1 for i in items if i.get("status") == "fixed")
    skipped = sum(1 for i in items if i.get("status") == "skipped")

    return {
        "total": len(items),
        "fixed": fixed,
        "skipped": skipped,
        "unprocessed_total": len(unprocessed),
        "by_severity": by_severity,
        "by_status": by_status,
        "unprocessed_ids": [i.get("id") for i in unprocessed if i.get("id") is not None],
        "titles": [i.get("title", "") for i in unprocessed[:TITLE_PREVIEW_LIMIT]],
    }


def main():
    parser = argparse.ArgumentParser(
        description="plan.yaml の未処理指摘を集計する"
    )
    parser.add_argument("session_dir", help="セッションディレクトリパス")
    args = parser.parse_args()

    plan_path = Path(args.session_dir) / "plan.yaml"

    try:
        result = summarize_pending(plan_path)
    except FileNotFoundError as e:
        json.dump({"status": "error", "error": str(e)}, sys.stderr, ensure_ascii=False)
        sys.stderr.write("\n")
        sys.exit(1)

    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
