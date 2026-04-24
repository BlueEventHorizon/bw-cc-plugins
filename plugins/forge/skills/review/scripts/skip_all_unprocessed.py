#!/usr/bin/env python3
"""skip_all_unprocessed — 未処理指摘を一括で status=skipped に更新する複合ラッパー。

DES-024 §2.1.0（複合ラッパー = 例外層）に該当する唯一のラッパー。R7 [MANDATORY]
（低レベル変更禁止）は本ラッパーでも厳守し、subprocess 呼び出しのみで実装する。

内部は DES-024 §3.4 の 3 手順:
    1. summarize_plan.py {session_dir} を呼び unprocessed_ids を取得
    2. [{"id": i, "status": "skipped", "skip_reason": "ユーザー判断: 全件対応しない"}]
       を組み立て（低レベル update_plan.py --batch の既存 stdin スキーマを再利用）
    3. update_plan.py {session_dir} --batch に stdin JSON として流す

read-modify-write race の扱い: 呼び出し元（review/SKILL.md Phase 5 Step 2b）が
review サイクル終了直前の同期処理で直列実行することを前提とする（DES-024 §3.4）。

stderr 契約（DES-024 §3.4）:
    失敗時は stderr 先頭行に `stage={識別子} exit={子プロセスの exit code}` を付け、
    子プロセスの stderr をその後にそのまま透過して非 0 終了する。
      - stage=summarize_plan: 手順 1 の非 0 終了
      - stage=json_build:     手順 2 の JSON parse 失敗（exit=-1）
      - stage=update_plan:    手順 3 の非 0 終了

位置引数: {session_dir}
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_FORGE_ROOT = Path(__file__).resolve().parents[3]
SUMMARIZE_PLAN = _FORGE_ROOT / "scripts" / "session" / "summarize_plan.py"
UPDATE_PLAN = _FORGE_ROOT / "scripts" / "session" / "update_plan.py"

SKIP_REASON = "ユーザー判断: 全件対応しない"


def main() -> int:
    session_dir = sys.argv[1]

    # 手順 1: summarize_plan.py で unprocessed_ids を取得
    proc = subprocess.run(
        [sys.executable, str(SUMMARIZE_PLAN), session_dir],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"stage=summarize_plan exit={proc.returncode}\n")
        sys.stderr.write(proc.stderr)
        return proc.returncode

    # 手順 2: updates 配列組立
    try:
        summary = json.loads(proc.stdout)
        unprocessed_ids = summary["unprocessed_ids"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        sys.stderr.write("stage=json_build exit=-1\n")
        sys.stderr.write(f"{type(e).__name__}: {e}\n")
        return 1

    updates_json = json.dumps({
        "updates": [
            {"id": i, "status": "skipped", "skip_reason": SKIP_REASON}
            for i in unprocessed_ids
        ]
    })

    # 手順 3: update_plan.py --batch に stdin JSON を流す
    proc2 = subprocess.run(
        [sys.executable, str(UPDATE_PLAN), session_dir, "--batch"],
        input=updates_json,
        capture_output=True,
        text=True,
        check=False,
    )
    sys.stdout.write(proc2.stdout)
    if proc2.returncode != 0:
        sys.stderr.write(f"stage=update_plan exit={proc2.returncode}\n")
        sys.stderr.write(proc2.stderr)
        return proc2.returncode

    sys.stderr.write(proc2.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
