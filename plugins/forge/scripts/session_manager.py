#!/usr/bin/env python3
"""forge セッションディレクトリ管理スクリプト。

オーケストレータースキルのセッション作成・検索・削除を担う。
AI が YAML を手書きする代わりに、このスクリプトが正しいフォーマットで生成する。

使用例:
    # セッション作成
    python3 session_manager.py init --skill start-design --feature login --mode new

    # 残存セッション検索
    python3 session_manager.py find --skill start-design

    # セッション削除
    python3 session_manager.py cleanup .claude/.temp/start-design-a3f7b2
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

from session.meta import (
    COMMON_FIELDS,
    SESSION_FIELD_ORDER,
    SESSION_META_FIELDS,
    VALID_PHASE_STATUSES,
    VALID_WAITING_TYPES,
    update_session_meta,
    update_session_meta_warning,
)
from session.yaml_utils import now_iso, read_yaml, write_flat_yaml

# セッションディレクトリのベースパス
TEMP_BASE = ".claude/.temp"

# スキルごとの resume_policy デフォルト値（未登録は "none"）
DEFAULT_RESUME_POLICY = {
    "review": "resume",
}

# monitor launcher.py 起動の既定タイムアウト
MONITOR_LAUNCH_TIMEOUT = 5.0

# テスト / 特殊環境向け: monitor 起動を抑止する環境変数
SKIP_MONITOR_ENV = "FORGE_SESSION_SKIP_MONITOR"


def _should_skip_monitor():
    val = os.environ.get(SKIP_MONITOR_ENV, "").strip().lower()
    return val in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def ensure_monitor_running(session_dir, skill, timeout=MONITOR_LAUNCH_TIMEOUT):
    """monitor/launcher.py を起動して server.py を fork 起動する。

    非ブロッキング設計: 失敗しても init 自体は成功させる。
    launcher.py は server.py を start_new_session=True で fork し、
    server.pid の出現を短時間待ってから同期的に終了するため、
    ここでは launcher.py の exit を待てば monitor 起動の成否が判る。

    Args:
        session_dir: セッションディレクトリの絶対パス
        skill: skill 名(launcher.py の --skill に渡す)
        timeout: launcher.py の最大実行時間(秒)

    Returns:
        dict: {"ok": True, "monitor_dir", "port", "url"} or
              {"ok": False, "reason": <str>}
    """
    launcher = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "monitor", "launcher.py"
    )
    if not os.path.isfile(launcher):
        print(f"警告: monitor launcher.py が見つかりません: {launcher}",
              file=sys.stderr)
        return {"ok": False, "reason": "launcher_not_found"}

    try:
        proc = subprocess.Popen(
            [sys.executable, launcher,
             "--skill", skill,
             "--session-dir", session_dir],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as e:
        print(f"警告: monitor launcher.py の起動に失敗: {e}", file=sys.stderr)
        return {"ok": False, "reason": "popen_failed", "error": str(e)}

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        print(
            f"警告: monitor 起動が {timeout}s 以内に完了しませんでした",
            file=sys.stderr,
        )
        return {"ok": False, "reason": "launcher_timeout"}

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        print(
            f"警告: monitor 起動失敗(exit={proc.returncode}): {err}",
            file=sys.stderr,
        )
        return {
            "ok": False,
            "reason": "launcher_exit_error",
            "returncode": proc.returncode,
        }

    try:
        info = json.loads(stdout.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, ValueError) as e:
        print(
            f"警告: monitor launcher の JSON 出力パース失敗: {e}",
            file=sys.stderr,
        )
        return {"ok": False, "reason": "json_parse_error"}

    return {"ok": True, **info}


def generate_session_name(skill):
    """{skill_name}-{random6} 形式のセッション名を生成する。

    スキル名がディレクトリ名に含まれるため、.claude/.temp/ を一覧した時に
    どのスキルのセッションかが一目でわかる。
    """
    random_hex = os.urandom(3).hex()
    return f"{skill}-{random_hex}"


def validate_temp_path(path):
    """パスが TEMP_BASE 配下であることを検証する。

    パストラバーサル攻撃を防ぐため、realpath で正規化してからチェックする。
    """
    real_path = os.path.realpath(path)
    real_base = os.path.realpath(TEMP_BASE)
    return real_path.startswith(real_base + os.sep) or real_path == real_base


def parse_extra_args(remaining):
    """残余引数から --key value ペアを dict に変換する。

    ハイフン付きキー (--output-dir) はアンダースコア (output_dir) に変換する。
    """
    extra = {}
    i = 0
    while i < len(remaining):
        arg = remaining[i]
        if arg.startswith("--") and i + 1 < len(remaining):
            key = arg[2:].replace("-", "_")
            val = remaining[i + 1]
            # 整数値の変換
            if val.lstrip("-").isdigit():
                val = int(val)
            extra[key] = val
            i += 2
        else:
            i += 1
    return extra


# ---------------------------------------------------------------------------
# サブコマンド
# ---------------------------------------------------------------------------

def cmd_init(args, remaining):
    """セッションディレクトリを作成し、session.yaml を書き出す。"""
    skill = args.skill

    # セッションディレクトリ作成
    session_name = generate_session_name(skill)
    session_dir = os.path.join(TEMP_BASE, session_name)
    refs_dir = os.path.join(session_dir, "refs")
    os.makedirs(refs_dir, exist_ok=True)

    # session.yaml のデータ構築
    ts = now_iso()
    data = {
        "skill": skill,
        "started_at": ts,
        "last_updated": ts,
        "status": "in_progress",
        "resume_policy": DEFAULT_RESUME_POLICY.get(skill, "none"),
        "phase": "created",
        "phase_status": "in_progress",
        "focus": "",
        "waiting_type": "none",
        "waiting_reason": "",
        "active_artifact": "",
    }

    # 残余引数からスキル固有フィールドを追加
    extra = parse_extra_args(remaining)

    # resume_policy が明示指定されていれば上書き
    if "resume_policy" in extra:
        data["resume_policy"] = extra.pop("resume_policy")

    data.update(extra)

    # session.yaml 書き出し
    yaml_path = os.path.join(session_dir, "session.yaml")
    write_flat_yaml(yaml_path, data, field_order=SESSION_FIELD_ORDER)

    # monitor(ブラウザ進捗表示)の自動起動 — 失敗しても init は成功させる
    if _should_skip_monitor():
        monitor_result = {"ok": False, "reason": "skipped_by_env"}
    else:
        try:
            monitor_result = ensure_monitor_running(
                os.path.abspath(session_dir), skill
            )
        except Exception as e:  # noqa: BLE001 - init を絶対に失敗させない
            print(f"警告: monitor 起動中に予期せぬ例外: {e}", file=sys.stderr)
            monitor_result = {"ok": False, "reason": "unexpected_error",
                              "error": str(e)}

    return {
        "status": "created",
        "session_dir": session_dir,
        "monitor": monitor_result,
    }


def cmd_find(args):
    """指定スキルの残存セッションを検索する。"""
    skill = args.skill
    pattern = os.path.join(TEMP_BASE, "*", "session.yaml")
    sessions = []

    for yaml_path in sorted(glob.glob(pattern)):
        try:
            data = read_yaml(yaml_path)
        except (IOError, OSError) as e:
            print(f"警告: セッションファイルの読み込みに失敗しました: {yaml_path}: {e}", file=sys.stderr)
            continue

        if data.get("skill") == skill:
            session_dir = os.path.dirname(yaml_path)
            sessions.append({
                "path": session_dir,
                "skill": data.get("skill", ""),
                "started_at": data.get("started_at", ""),
                "status": data.get("status", ""),
            })

    if sessions:
        return {"status": "found", "sessions": sessions}
    return {"status": "none"}


def cmd_cleanup(args):
    """セッションディレクトリを削除する。"""
    session_dir = args.session_dir

    if not validate_temp_path(session_dir):
        return {
            "status": "error",
            "error": f"安全でないパスです。{TEMP_BASE}/ 配下のみ削除できます: {session_dir}",
        }

    if not os.path.exists(session_dir):
        return {
            "status": "error",
            "error": f"ディレクトリが存在しません: {session_dir}",
        }

    shutil.rmtree(session_dir)
    return {"status": "deleted", "session_dir": session_dir}


def cmd_update_meta(args):
    """session.yaml の浅い進行状態を更新する。"""
    updates = {
        "phase": args.phase,
        "phase_status": args.phase_status,
        "focus": args.focus,
        "waiting_type": args.waiting_type,
        "waiting_reason": args.waiting_reason,
        "active_artifact": args.active_artifact,
    }
    try:
        return update_session_meta(args.session_dir, updates, notify=True)
    except (FileNotFoundError, ValueError, OSError) as e:
        return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="forge セッションディレクトリ管理")
    subparsers = parser.add_subparsers(dest="command")

    # init サブコマンド
    init_parser = subparsers.add_parser("init", help="セッション作成")
    init_parser.add_argument("--skill", required=True, help="スキル名")

    # find サブコマンド
    find_parser = subparsers.add_parser("find", help="既存セッション検索")
    find_parser.add_argument("--skill", required=True, help="検索するスキル名")

    # cleanup サブコマンド
    cleanup_parser = subparsers.add_parser("cleanup", help="セッション削除")
    cleanup_parser.add_argument("session_dir", help="削除するセッションディレクトリパス")

    # update-meta サブコマンド
    update_parser = subparsers.add_parser("update-meta", help="セッションメタデータ更新")
    update_parser.add_argument("session_dir", help="セッションディレクトリパス")
    update_parser.add_argument("--phase", help="現在の粗いフェーズ")
    update_parser.add_argument("--phase-status", help="phase の状態")
    update_parser.add_argument("--focus", help="現在の作業焦点")
    update_parser.add_argument("--waiting-type", help="待機種別")
    update_parser.add_argument("--waiting-reason", help="待機理由")
    update_parser.add_argument("--active-artifact", help="直近更新成果物パス")

    # parse_known_args で init の任意フィールドに対応
    args, remaining = parser.parse_known_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        result = cmd_init(args, remaining)
    elif args.command == "find":
        result = cmd_find(args)
    elif args.command == "cleanup":
        result = cmd_cleanup(args)
    elif args.command == "update-meta":
        result = cmd_update_meta(args)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
