#!/usr/bin/env python3
"""notify.py — forge monitor サーバーへ更新通知を送る共通モジュール。

書き込みスクリプト(update_plan / extract_review_findings / write_interpretation /
write_refs 等)から呼ばれ、session_dir を監視している monitor サーバーへ
HTTP POST /notify を送る。

旧 `.claude/hooks/notifier.py` の置換。PostToolUse フックは Write/Edit ツールしか
捕捉できず、Bash 経由で実行される書き込みスクリプトでは発火しなかった。
そこで書き込みスクリプトから直接この関数を呼び、確実な通知を実現する。

設計書: DES-012 show-browser 設計書 v3.0 §5.11
"""

import argparse
import glob
import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


# 通知 HTTP タイムアウト(秒)。書き込みスクリプトを止めないため短めに設定する。
NOTIFY_TIMEOUT = 0.5


def _log(msg):
    """診断ログを stderr へ出す。`FORGE_NOTIFY_QUIET=1` で抑制できる。

    通知失敗の原因(プロセス死亡・port ずれ・session_dir 不一致・
    CLAUDE_PROJECT_DIR 未設定による monitor 未検出)は、握り潰すと browser に
    更新が届かない現象として遅れて表面化する。書き込みスクリプトを止めない
    fire-and-forget 原則を維持しつつ、原因追跡のため痕跡は必ず残す。
    """
    if os.environ.get("FORGE_NOTIFY_QUIET") == "1":
        return
    try:
        print(f"[forge notify] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _project_root():
    """プロジェクトルートを解決する。

    CLAUDE_PROJECT_DIR が設定されていればそれを使う。未設定時はカレント
    ディレクトリを使う(書き込みスクリプトは通常 `.claude/.temp/...` を
    絶対パスで扱うため cwd フォールバックでも実害は小さい)。
    """
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def _iter_monitors(project_root):
    """`.claude/.temp/*-monitor/` 配下の config を yield する。

    config.json と server.pid の両方が存在する monitor のみ対象にする。
    孤立 monitor(pid 死亡等)は launcher 起動時にクリーンアップされる前提。
    """
    pattern = os.path.join(project_root, ".claude", ".temp", "*-monitor")
    for monitor_dir in glob.glob(pattern):
        config_path = os.path.join(monitor_dir, "config.json")
        pid_path = os.path.join(monitor_dir, "server.pid")
        if not os.path.exists(config_path) or not os.path.exists(pid_path):
            continue
        try:
            with open(config_path, encoding="utf-8") as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        yield config, monitor_dir


def notify_session_update(session_dir, file_path):
    """session_dir を監視する monitor サーバーに更新通知を送る。

    Args:
        session_dir: セッションディレクトリのパス(絶対/相対どちらでも可)
        file_path: 更新されたファイルのパス

    Returns:
        int: 通知送信に成功した monitor 数。失敗・対象外は数えない。
             書き込みスクリプト側はこの値を気にしなくてよい(fire-and-forget)。
    """
    if not session_dir or not file_path:
        return 0

    abs_session = os.path.abspath(session_dir)
    abs_file = os.path.abspath(file_path)
    basename = os.path.basename(file_path)
    project_root = _project_root()

    notified = 0
    scanned = 0
    matched = 0
    mismatches = []
    for config, _monitor_dir in _iter_monitors(project_root):
        scanned += 1
        raw_session_dir = config.get("session_dir", "")
        if not raw_session_dir:
            continue
        monitor_session = os.path.abspath(raw_session_dir)

        # session_dir が完全一致する monitor のみ対象。
        # 呼び出し側が意図せず別セッションの monitor に通知するのを防ぐ。
        if abs_session != monitor_session:
            mismatches.append(monitor_session)
            continue

        # 更新ファイルが session_dir 配下にあることを検証(防御的)。
        if not (abs_file == abs_session or abs_file.startswith(abs_session + os.sep)):
            _log(
                f"file outside session_dir: session={abs_session} file={abs_file}"
            )
            continue

        matched += 1
        port = config.get("port", 8765)
        payload = json.dumps({"file": basename, "path": file_path}).encode("utf-8")
        req = Request(
            f"http://127.0.0.1:{port}/notify",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urlopen(req, timeout=NOTIFY_TIMEOUT)
            notified += 1
        except (URLError, OSError) as e:
            _log(
                f"POST /notify failed: port={port} session={abs_session} "
                f"file={basename} error={e!r}"
            )

    # 通知 0 件のまま終わった原因を可視化する。
    # ブラウザに更新が届かない問題を追跡できるようにするため、
    # scanned=0(monitor 未検出) / matched=0(session_dir 不一致)を区別してログ化。
    if notified == 0:
        if scanned == 0:
            _log(
                f"no monitor found: project_root={project_root} "
                f"session={abs_session}"
            )
        elif matched == 0 and mismatches:
            _log(
                f"no monitor matched session_dir={abs_session}: "
                f"scanned={scanned} other_sessions={mismatches}"
            )

    return notified


def main():
    """CLI エントリーポイント(手動検証・CI 用)。"""
    parser = argparse.ArgumentParser(
        description="session_dir を監視する monitor サーバーに更新通知を送る"
    )
    parser.add_argument("session_dir", help="セッションディレクトリ")
    parser.add_argument("file_path", help="更新されたファイル")
    args = parser.parse_args()
    count = notify_session_update(args.session_dir, args.file_path)
    json.dump({"status": "ok", "notified": count}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
