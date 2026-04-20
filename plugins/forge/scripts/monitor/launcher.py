#!/usr/bin/env python3
"""launcher.py — forge monitor のエントリーポイント。

monitor ディレクトリ作成・server.py の fork 起動・ブラウザ起動を担う。
session_manager.cmd_init() から自動呼び出しされることを想定する。

設計書: DES-012 show-browser 設計書 v3.0 (§5.1)
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

# デフォルトのポート検索開始番号(8765 優先取得、空きなければ 8766〜8775)
DEFAULT_PORT = 8765
DEFAULT_PORT_ATTEMPTS = 11  # 8765〜8775

# 環境変数: true/1/yes でブラウザ自動起動を抑制(CI/SSH リモート向け)
NO_OPEN_ENV = "FORGE_MONITOR_NO_OPEN"


# ---------------------------------------------------------------------------
# ポート検出
# ---------------------------------------------------------------------------

def find_free_port(start=DEFAULT_PORT, attempts=DEFAULT_PORT_ATTEMPTS):
    """start から順に空きポートを検索して返す。

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
    raise RuntimeError(
        f"空きポートが見つかりません({start}〜{start + attempts - 1})"
    )


# ---------------------------------------------------------------------------
# 孤立 monitor ディレクトリのクリーンアップ
# ---------------------------------------------------------------------------

def _is_process_alive(pid):
    """PID が生存しているか確認する(POSIX 専用)。"""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cleanup_orphan_monitors(project_root):
    """孤立した monitor ディレクトリを削除する。

    孤立判定ルール:
      - server.pid が存在しない → 孤立
      - server.pid の PID が生きていない → 孤立(クラッシュ)
    """
    pattern = os.path.join(project_root, ".claude", ".temp", "*-monitor")
    for monitor_dir in glob.glob(pattern):
        pid_path = os.path.join(monitor_dir, "server.pid")
        if not os.path.exists(pid_path):
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
            try:
                shutil.rmtree(monitor_dir)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# monitor ディレクトリ作成
# ---------------------------------------------------------------------------

def create_monitor_dir(project_root, skill, session_dir, port):
    """monitor ディレクトリを作成し config.json を書き込む。

    ディレクトリ名: .claude/.temp/{YYYYMMDD-HHmmss}-{skill}-monitor/

    Args:
        project_root: プロジェクトルートパス
        skill: skill 名(例: "review" / "start-requirements")
        session_dir: 監視対象セッションディレクトリ(絶対パス)
        port: 使用ポート番号

    Returns:
        str: 作成した monitor ディレクトリの絶対パス
    """
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dirname = f"{ts}-{skill}-monitor"
    monitor_dir = os.path.join(project_root, ".claude", ".temp", dirname)
    os.makedirs(monitor_dir, exist_ok=True)

    config = {
        "skill": skill,
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
    """server.py を fork 起動し、起動完了(server.pid の書き込み)を待つ。

    Args:
        monitor_dir: monitor ディレクトリパス
        port: リッスンポート
        timeout: 起動タイムアウト(秒)

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

    pid_path = os.path.join(monitor_dir, "server.pid")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.isfile(pid_path):
            return proc
        time.sleep(0.1)

    proc.terminate()
    raise RuntimeError(f"server.py の起動がタイムアウトしました({timeout}秒)")


# ---------------------------------------------------------------------------
# プロジェクトルート解決
# ---------------------------------------------------------------------------

def _resolve_project_root():
    """CLAUDE_PROJECT_DIR 環境変数 → スクリプト相対パスの順で解決する。

    monitor/launcher.py から 4 階層上がプロジェクトルート:
      plugins/forge/scripts/monitor/launcher.py
        → plugins/forge/scripts/monitor (../)
        → plugins/forge/scripts      (../../)
        → plugins/forge              (../../../)
        → plugins                    (../../../../)
        → <project_root>             (../../../../../) ← 計5階層上
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return os.path.abspath(env)
    return os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * 4))
    )


def _should_skip_open():
    """FORGE_MONITOR_NO_OPEN が有効値ならブラウザ起動をスキップ。"""
    val = os.environ.get(NO_OPEN_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def main():
    """CLI エントリーポイント。

    Usage:
      python3 launcher.py --skill <name> --session-dir <path> [--port N] [--no-open]

    標準出力 (JSON):
      {"monitor_dir": "...", "port": 8765, "url": "..."}
    """
    parser = argparse.ArgumentParser(
        description="forge monitor — セッション進捗をブラウザでリアルタイム表示する"
    )
    parser.add_argument(
        "--skill",
        required=True,
        help="skill 名(例: review / start-requirements / start-design / "
             "start-plan / start-implement / start-uxui-design)",
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
        help=f"ポート番号(省略時は {DEFAULT_PORT} から自動検出)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help=f"ブラウザを開かない(環境変数 {NO_OPEN_ENV} でも指定可)",
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

    project_root = _resolve_project_root()

    cleanup_orphan_monitors(project_root)

    try:
        port = args.port if args.port is not None else find_free_port()
    except RuntimeError as e:
        error = {"error": "port_unavailable", "message": str(e)}
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

    monitor_dir = create_monitor_dir(project_root, args.skill, session_dir, port)

    try:
        start_server(monitor_dir, port)
    except RuntimeError as e:
        error = {
            "error": "server_start_failed",
            "message": str(e),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        try:
            shutil.rmtree(monitor_dir)
        except OSError:
            pass
        sys.exit(1)

    url = f"http://localhost:{port}/"
    if not args.no_open and not _should_skip_open():
        try:
            webbrowser.open(url)
        except Exception:
            # CI/SSH 環境等で webbrowser が例外を投げても起動は成功扱いにする
            pass

    result = {
        "monitor_dir": monitor_dir,
        "port": port,
        "url": url,
        "skill": args.skill,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
