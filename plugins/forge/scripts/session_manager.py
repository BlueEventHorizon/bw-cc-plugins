#!/usr/bin/env python3
"""forge セッションディレクトリ管理スクリプト。

オーケストレータースキルのセッション作成・更新・検索・削除を担う。
AI が YAML を手書きする代わりに、このスクリプトが正しいフォーマットで生成する。

使用例:
    # セッション作成
    python3 session_manager.py init --skill start-design --feature login --mode new

    # Phase 切替時に last_updated を更新
    python3 session_manager.py touch .claude/.temp/start-design-a3f7b2

    # 正常完了時に status を completed に遷移
    python3 session_manager.py complete .claude/.temp/start-design-a3f7b2

    # 残存セッション検索（自スキルのみ）
    python3 session_manager.py find --skill start-design

    # 残存セッション検索（全スキル横断）
    python3 session_manager.py find --all-skills

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
    """残存セッションを検索する。

    `--skill` 指定時は当該スキルのセッションのみ、
    `--all-skills` 指定時は全スキルのセッションを返す。
    """
    skill_filter = args.skill
    all_skills = getattr(args, "all_skills", False)
    pattern = os.path.join(TEMP_BASE, "*", "session.yaml")
    sessions = []

    for yaml_path in sorted(glob.glob(pattern)):
        try:
            data = read_yaml(yaml_path)
        except (IOError, OSError) as e:
            print(f"警告: セッションファイルの読み込みに失敗しました: {yaml_path}: {e}", file=sys.stderr)
            continue

        if not all_skills and data.get("skill") != skill_filter:
            continue

        session_dir = os.path.dirname(yaml_path)
        sessions.append({
            "path": session_dir,
            "skill": data.get("skill", ""),
            "started_at": data.get("started_at", ""),
            "last_updated": data.get("last_updated", ""),
            "status": data.get("status", ""),
        })

    if sessions:
        return {"status": "found", "sessions": sessions}
    return {"status": "none"}


def _update_session_yaml(session_dir, updates):
    """session.yaml を読み込み、指定フィールドを上書きして atomic に書き戻す。

    Args:
        session_dir: セッションディレクトリパス
        updates: 上書きするフィールドの dict（`last_updated` は常に now_iso() で更新する）

    Returns:
        dict: 成功時は読み込んだ最新データ、失敗時は ``status: error`` を持つ dict
    """
    if not validate_temp_path(session_dir):
        return {
            "status": "error",
            "error": f"安全でないパスです。{TEMP_BASE}/ 配下のみ操作できます: {session_dir}",
        }

    yaml_path = os.path.join(session_dir, "session.yaml")
    if not os.path.isfile(yaml_path):
        return {
            "status": "error",
            "error": f"session.yaml が見つかりません: {yaml_path}",
        }

    try:
        data = read_yaml(yaml_path)
    except (IOError, OSError) as e:
        return {
            "status": "error",
            "error": f"session.yaml の読み込みに失敗しました: {e}",
        }

    data.update(updates)
    data["last_updated"] = now_iso()
    write_flat_yaml(yaml_path, data, field_order=SESSION_FIELD_ORDER)
    return data


def cmd_touch(args):
    """session.yaml の last_updated を現在時刻に更新する。

    Phase 切替時にオーケストレータが呼ぶことで、cleanup-stale の
    時間基準が「最後に動きがあった時刻」を反映するようになる。
    """
    session_dir = args.session_dir
    data = _update_session_yaml(session_dir, {})
    if data.get("status") == "error":
        return data
    return {
        "status": "ok",
        "session_dir": session_dir,
        "last_updated": data.get("last_updated", ""),
    }


def cmd_complete(args):
    """session.yaml の status を completed に遷移させる。

    正常完了処理の 1 段目として呼ぶ。直後に `cleanup` を実行することで
    完了済みとマークされたまま残るセッションを cleanup-stale が即削除できる。
    """
    session_dir = args.session_dir
    data = _update_session_yaml(session_dir, {"status": "completed"})
    if data.get("status") == "error":
        return data
    return {
        "status": "ok",
        "session_dir": session_dir,
        "session_status": data.get("status", ""),
        "last_updated": data.get("last_updated", ""),
    }


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
    """期限切れの残骸セッションを一括削除する。

    判定ルール:
      - `status: completed` のセッションは `--older-than-hours` を無視して常に削除対象
        （正常完了したのに cleanup されなかったクラッシュ残骸を即回収するため）
      - `status: in_progress` のセッションは `started_at` と `last_updated` のうち
        新しい方を基準とし、`--older-than-hours N` より古いものを削除する

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

        session_status = data.get("status", "")
        is_completed = session_status == "completed"

        ts_started = _parse_iso_ts(data.get("started_at"))
        ts_updated = _parse_iso_ts(data.get("last_updated"))
        candidates = [t for t in (ts_started, ts_updated) if t is not None]
        if not candidates:
            skipped.append({"path": session_dir, "reason": "タイムスタンプ不正"})
            continue
        latest = max(candidates)
        age_hours = (now - latest).total_seconds() / 3600.0

        # completed は age に関わらず常に削除対象、それ以外は cutoff_hours で判定
        if not is_completed and age_hours < cutoff_hours:
            continue

        if not validate_temp_path(session_dir):
            skipped.append({"path": session_dir, "reason": "安全でないパス"})
            continue

        entry = {
            "path": session_dir,
            "skill": data.get("skill", ""),
            "session_status": session_status,
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
    find_filter = find_parser.add_mutually_exclusive_group(required=True)
    find_filter.add_argument("--skill", help="検索するスキル名")
    find_filter.add_argument(
        "--all-skills",
        action="store_true",
        help="全スキルのセッションを横断検出する",
    )

    # touch サブコマンド
    touch_parser = subparsers.add_parser(
        "touch",
        help="session.yaml の last_updated を現在時刻に更新（Phase 切替時に呼ぶ）",
    )
    touch_parser.add_argument("session_dir", help="更新するセッションディレクトリパス")

    # complete サブコマンド
    complete_parser = subparsers.add_parser(
        "complete",
        help="session.yaml の status を completed に遷移（正常完了処理の 1 段目）",
    )
    complete_parser.add_argument("session_dir", help="完了マークするセッションディレクトリパス")

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
    elif args.command == "touch":
        result = cmd_touch(args)
    elif args.command == "complete":
        result = cmd_complete(args)
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
