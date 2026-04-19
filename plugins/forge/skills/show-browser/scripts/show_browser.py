#!/usr/bin/env python3
"""show_browser.py — forge:show-browser スキルのエントリーポイント。

monitor ディレクトリの作成・server.py の fork 起動・ブラウザ起動を担う。
起動完了後に標準出力へ JSON を出力する。

設計書: DES-012 show-browser 設計書 v2.0（5.1 節 / 5.10 節）
"""

import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

# デフォルトのポート検索開始番号
DEFAULT_PORT = 8765


# ---------------------------------------------------------------------------
# ポート検出
# ---------------------------------------------------------------------------

def find_free_port(start=DEFAULT_PORT, attempts=100):
    """8765 から順に空きポートを検索して返す。

    Args:
        start: 検索開始ポート番号
        attempts: 最大試行回数

    Returns:
        int: 使用可能なポート番号

    Raises:
        RuntimeError: 空きポートが見つからない場合
    """
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"空きポートが見つかりません（{start}〜{start + attempts - 1}）")


# ---------------------------------------------------------------------------
# 孤立 monitor ディレクトリのクリーンアップ
# ---------------------------------------------------------------------------

def _is_process_alive(pid):
    """PID が生存しているか確認する（POSIX 専用）。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cleanup_orphan_monitors(project_root):
    """孤立した monitor ディレクトリを削除する。

    孤立判定ルール（設計書 5.10）:
      - server.pid が存在しない → 孤立
      - server.pid の PID が生きていない → 孤立（クラッシュ）

    Args:
        project_root: プロジェクトルートパス
    """
    pattern = os.path.join(project_root, ".claude", ".temp", "*-monitor")
    for monitor_dir in glob.glob(pattern):
        pid_path = os.path.join(monitor_dir, "server.pid")
        if not os.path.exists(pid_path):
            # server.pid なし → 孤立
            try:
                shutil.rmtree(monitor_dir)
            except OSError:
                pass
            continue
        try:
            pid = int(Path(pid_path).read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            try:
                shutil.rmtree(monitor_dir)
            except OSError:
                pass
            continue
        if not _is_process_alive(pid):
            # プロセス死亡 → 孤立
            try:
                shutil.rmtree(monitor_dir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# monitor ディレクトリ作成
# ---------------------------------------------------------------------------

def create_monitor_dir(project_root, template, session_dir, port):
    """monitor ディレクトリを作成し config.json を書き込む。

    ディレクトリ名: .claude/.temp/{YYYYMMDD-HHmmss}-{template}-monitor/

    Args:
        project_root: プロジェクトルートパス
        template: テンプレート名（例: "review_list"）
        session_dir: 監視対象セッションディレクトリ（絶対パス）
        port: 使用ポート番号

    Returns:
        str: 作成した monitor ディレクトリの絶対パス
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dirname = f"{ts}-{template}-monitor"
    monitor_dir = os.path.join(project_root, ".claude", ".temp", dirname)
    os.makedirs(monitor_dir, exist_ok=True)

    config = {
        "template": template,
        "session_dir": os.path.abspath(session_dir),
        "port": port,
    }
    config_path = os.path.join(monitor_dir, "config.json")
    Path(config_path).write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return monitor_dir


# ---------------------------------------------------------------------------
# server.py 起動
# ---------------------------------------------------------------------------

def start_server(monitor_dir, port, timeout=5.0):
    """server.py を fork 起動し、起動完了を待つ。

    Args:
        monitor_dir: monitor ディレクトリパス
        port: リッスンポート
        timeout: 起動タイムアウト（秒）

    Returns:
        subprocess.Popen: 起動したサーバープロセス

    Raises:
        RuntimeError: タイムアウト内に起動しなかった場合
    """
    server_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "server.py"
    )
    proc = subprocess.Popen(
        [sys.executable, server_script, "--dir", monitor_dir, "--port", str(port)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # server.pid が書き込まれるまで待機
    pid_path = os.path.join(monitor_dir, "server.pid")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isfile(pid_path):
            return proc
        time.sleep(0.1)

    proc.terminate()
    raise RuntimeError(f"server.py の起動がタイムアウトしました（{timeout}秒）")


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    """CLI エントリーポイント。

    設計書 5.1 節:
      python3 show_browser.py --template review_list --session-dir <path> [--port N] [--no-open]

    標準出力（JSON）:
      {"monitor_dir": "...", "port": 8765}
    """
    parser = argparse.ArgumentParser(
        description="forge:show-browser — セッション進捗をブラウザでリアルタイム表示する"
    )
    parser.add_argument(
        "--template",
        default="review_list",
        help="テンプレート名（templates/ 配下の HTML ファイル名、拡張子なし）",
    )
    parser.add_argument(
        "--session-dir",
        required=True,
        metavar="PATH",
        help="監視対象セッションディレクトリ",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="ポート番号（省略時は 8765 から自動検出）",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="ブラウザを開かない",
    )
    args = parser.parse_args()

    session_dir = os.path.abspath(args.session_dir)
    if not os.path.isdir(session_dir):
        error = {
            "error": "session_dir_not_found",
            "session_dir": session_dir,
            "message": f"セッションディレクトリが見つかりません: {session_dir}",
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    # プロジェクトルート: CLAUDE_PROJECT_DIR 環境変数を優先、未設定時は相対パスでフォールバック
    project_root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."]*5))
    )

    # 孤立 monitor の掃除（設計書 5.10）
    cleanup_orphan_monitors(project_root)

    # 空きポート検出
    port = args.port if args.port is not None else find_free_port()

    # monitor ディレクトリ作成
    monitor_dir = create_monitor_dir(project_root, args.template, session_dir, port)

    # server.py 起動
    try:
        start_server(monitor_dir, port)
    except RuntimeError as e:
        error = {
            "error": "server_start_failed",
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        # monitor_dir を後始末
        try:
            shutil.rmtree(monitor_dir)
        except OSError:
            pass
        sys.exit(1)

    # ブラウザ起動
    url = f"http://localhost:{port}/"
    if not args.no_open:
        webbrowser.open(url)

    # 結果を JSON で出力（設計書 5.1 節）
    result = {
        "monitor_dir": monitor_dir,
        "port": port,
        "url": url,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
