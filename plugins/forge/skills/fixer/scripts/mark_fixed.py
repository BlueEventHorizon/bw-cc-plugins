#!/usr/bin/env python3
"""mark_fixed — fixer 用に plan.yaml の対象項目を status=fixed に更新する薄いラッパー。

DES-024 §2.1.1 / §3.6.6 に従った透過ラッパー。位置引数を低レベル update_plan.py に
flag 変換して渡し、stdout / stderr / exit code を完全透過する。

位置引数: {session_dir} {id} [{file}...]
hardcoded: --status fixed
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LOW_LEVEL = (
    Path(__file__).resolve().parents[3] / "scripts" / "session" / "update_plan.py"
)


def main() -> int:
    session_dir = sys.argv[1]
    item_id = sys.argv[2]
    files_modified = sys.argv[3:]

    cmd = [
        sys.executable,
        str(LOW_LEVEL),
        session_dir,
        "--id", item_id,
        "--status", "fixed",
    ]
    if files_modified:
        cmd.append("--files-modified")
        cmd.extend(files_modified)

    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
