#!/usr/bin/env python3
"""notifier.py — PostToolUse フックスクリプト。

Write / Edit ツールの実行を検知し、session_dir が一致する全 monitor サーバーに
HTTP POST を送る。

設計書: DES-012 show-browser 設計書 v2.0（5.7 節）
"""

import glob
import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    """フックのメイン処理。"""
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError) as e:
        print(f"notifier: stdin JSON パース失敗: {e}", file=sys.stderr)
        return

    # Write / Edit 以外は無視
    if input_data.get("tool_name") not in ("Write", "Edit"):
        return

    file_path = input_data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    basename = os.path.basename(file_path)
    abs_path = os.path.abspath(file_path)

    # アクティブな monitor ディレクトリを全スキャン
    project_root = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    monitor_dirs = glob.glob(os.path.join(project_root, ".claude", ".temp", "*-monitor"))

    for monitor_dir in monitor_dirs:
        config_path = os.path.join(monitor_dir, "config.json")
        pid_path = os.path.join(monitor_dir, "server.pid")

        # config.json と server.pid の両方が存在する monitor のみ処理
        if not os.path.exists(config_path) or not os.path.exists(pid_path):
            continue

        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        # session_dir 配下のファイル更新のみ通知（設計書 5.7）
        raw_session_dir = config.get("session_dir", "")
        if not raw_session_dir:
            continue
        session_dir = os.path.abspath(raw_session_dir)
        if not (abs_path == session_dir or abs_path.startswith(session_dir + os.sep)):
            continue

        port = config.get("port", 8765)
        payload = json.dumps({"file": basename, "path": file_path}).encode("utf-8")
        req = Request(
            f"http://127.0.0.1:{port}/notify",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(req, timeout=2)
        except (URLError, OSError):
            # サーバー未起動時は無視（exit 0 保証）
            pass


if __name__ == "__main__":
    main()
