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
import sys
from datetime import datetime, timezone

from session.yaml_utils import now_iso, read_yaml, write_flat_yaml

# セッションディレクトリのベースパス
TEMP_BASE = ".claude/.temp"

# session.yaml の出力フィールド順（共通4フィールド + スキル固有の追加フィールド）
SESSION_FIELD_ORDER = ["skill", "started_at", "last_updated", "status"]


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


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
    }

    # 残余引数からスキル固有フィールドを追加
    extra = parse_extra_args(remaining)
    data.update(extra)

    # session.yaml 書き出し
    yaml_path = os.path.join(session_dir, "session.yaml")
    write_flat_yaml(yaml_path, data, field_order=SESSION_FIELD_ORDER)

    return {
        "status": "created",
        "session_dir": session_dir,
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


def _parse_iso_ts(ts):
    """ISO 8601 (Z 表記または +00:00 表記) を aware datetime に変換する。

    yaml_utils.now_iso() の出力 (`%Y-%m-%dT%H:%M:%SZ`) との往復に加え、
    手書きセッションへの後方互換として `+00:00` も受理する。
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def cmd_cleanup_stale(args):
    """期限切れの in_progress セッションを一括削除する。

    `started_at` と `last_updated` のうち新しい方を基準とし、
    `--older-than-hours N` より古いセッションを削除する。
    `--skill` 指定時は該当スキルのみが対象。
    `--dry-run` 時は削除予定一覧のみを返す。
    """
    cutoff_hours = args.older_than_hours
    skill_filter = args.skill
    dry_run = args.dry_run

    if cutoff_hours < 0:
        return {
            "status": "error",
            "error": f"--older-than-hours は 0 以上を指定してください: {cutoff_hours}",
        }

    now = datetime.now(timezone.utc)
    pattern = os.path.join(TEMP_BASE, "*", "session.yaml")
    deleted = []
    skipped = []

    for yaml_path in sorted(glob.glob(pattern)):
        session_dir = os.path.dirname(yaml_path)
        try:
            data = read_yaml(yaml_path)
        except (IOError, OSError) as e:
            skipped.append({"path": session_dir, "reason": f"読み込み失敗: {e}"})
            continue

        if skill_filter and data.get("skill") != skill_filter:
            continue

        ts_started = _parse_iso_ts(data.get("started_at"))
        ts_updated = _parse_iso_ts(data.get("last_updated"))
        candidates = [t for t in (ts_started, ts_updated) if t is not None]
        if not candidates:
            skipped.append({"path": session_dir, "reason": "タイムスタンプ不正"})
            continue
        latest = max(candidates)

        age_hours = (now - latest).total_seconds() / 3600.0
        if age_hours < cutoff_hours:
            continue

        if not validate_temp_path(session_dir):
            skipped.append({"path": session_dir, "reason": "安全でないパス"})
            continue

        entry = {
            "path": session_dir,
            "skill": data.get("skill", ""),
            "age_hours": round(age_hours, 2),
        }

        if dry_run:
            deleted.append(entry)
            continue

        try:
            shutil.rmtree(session_dir)
        except OSError as e:
            skipped.append({"path": session_dir, "reason": f"削除失敗: {e}"})
            continue
        deleted.append(entry)

    return {
        "status": "dry-run" if dry_run else "ok",
        "cutoff_hours": cutoff_hours,
        "deleted": deleted,
        "skipped": skipped,
    }


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

    # cleanup-stale サブコマンド
    stale_parser = subparsers.add_parser(
        "cleanup-stale",
        help="期限切れセッションを一括削除（中断・クラッシュ後の残骸を回収）",
    )
    stale_parser.add_argument(
        "--older-than-hours",
        type=int,
        default=48,
        help="この時間 (時間単位) より古いセッションを削除対象とする。デフォルト 48",
    )
    stale_parser.add_argument(
        "--skill",
        default=None,
        help="特定スキルのセッションのみ対象にする（省略時は全スキル）",
    )
    stale_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="削除せず、削除予定の一覧のみを出力する",
    )

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
    elif args.command == "cleanup-stale":
        result = cmd_cleanup_stale(args)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
