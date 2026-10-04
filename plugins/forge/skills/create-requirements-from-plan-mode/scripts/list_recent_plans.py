#!/usr/bin/env python3
"""Claude Code の plan mode が保存する plan ファイルを mtime 降順で列挙する。

既定の探索先は `~/.claude/plans/*.md`。`--plans-dir` で上書き可能（主にテスト用途）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _extract_title(path: Path, max_bytes: int = 4096) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(max_bytes)
    except OSError:
        return path.stem
    for line in head.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or path.stem
    return path.stem


def list_plans(plans_dir: Path, limit: int) -> dict:
    if not plans_dir.exists() or not plans_dir.is_dir():
        return {
            "status": "missing",
            "plans_dir": str(plans_dir),
            "count": 0,
            "plans": [],
            "latest": None,
        }

    files = [p for p in plans_dir.glob("*.md") if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    plans = []
    for p in files[:limit]:
        st = p.stat()
        plans.append({
            "path": str(p),
            "mtime": st.st_mtime,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds"),
            "size": st.st_size,
            "title": _extract_title(p),
        })

    return {
        "status": "found" if plans else "empty",
        "plans_dir": str(plans_dir),
        "count": len(plans),
        "plans": plans,
        "latest": plans[0]["path"] if plans else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plans-dir",
        default=os.environ.get("PLANS_DIR") or str(Path.home() / ".claude" / "plans"),
        help="plan ファイルの探索ディレクトリ (default: ~/.claude/plans)",
    )
    parser.add_argument("--limit", type=int, default=10, help="列挙する最大件数 (default: 10)")
    args = parser.parse_args(argv)

    result = list_plans(Path(args.plans_dir).expanduser(), max(args.limit, 1))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
