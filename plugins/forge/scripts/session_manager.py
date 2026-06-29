#!/usr/bin/env python3
"""forge セッションディレクトリ管理スクリプト。

オーケストレータースキルのセッション作成・更新・検索・削除を担う。
AI が YAML を手書きする代わりに、このスクリプトが正しいフォーマットで生成する。

使用例（動詞レベル API、推奨）:
    # 中断判定（completed 残骸を自動回収しつつ自スキルの resumable を返す）
    python3 session_manager.py probe --skill review

    # 再開（last_updated 更新 + session.yaml 全体を返却）
    python3 session_manager.py resume .claude/.temp/review-a3f7b2

    # 正常完了（complete + cleanup を 1 動詞）
    python3 session_manager.py finish .claude/.temp/review-a3f7b2

使用例（低レベル CRUD、後方互換）:
    # セッション作成（作成前に completed 残骸を全スキル横断で自動回収する。#93）
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

    # completed 残骸のみを回収（in_progress は温存。init の自動回収が内部で使用）
    python3 session_manager.py cleanup-stale --completed-only
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


# review 専用の予約キー。`--key value` の scalar 契約に乗らない可変長 list 値
# (レビュー対象ファイル群) を受けるため、parse_extra_args とは別経路で処理する。
# DES-011 §5.1/§5.2 の「任意 --key value」契約に対する明示的例外。
FILES_FLAG = "--files"


def _normalize_files(raw_values):
    """``--files`` の生値を flat な list[str] に正規化する。

    各値はカンマ区切りを許容し、空白を strip して空文字を除外する::

        ["a.md", "b.md"]          -> ["a.md", "b.md"]
        ["a.md,b.md"]             -> ["a.md", "b.md"]
        ["a.md,b.md", "c.md"]     -> ["a.md", "b.md", "c.md"]
    """
    result = []
    for v in raw_values:
        for part in v.split(","):
            p = part.strip()
            if p:
                result.append(p)
    return result


def extract_files(remaining):
    """残余引数から ``--files`` とその可変長値を抽出する。

    ``--files`` 以降のトークンを **次の ``--xxx`` または末尾まで** 値として集める
    (空白区切り)。抽出した ``--files`` と値は残余から取り除き、それ以外を
    ``cleaned_remaining`` として返す。これを parse_extra_args に渡すことで、
    ``files`` が scalar として再解釈・上書きされる事故を防ぐ。

    Returns:
        tuple[bool, list[str], list[str]]:
            (files_present, files, cleaned_remaining)
    """
    files_present = False
    raw_values = []
    cleaned = []
    i = 0
    n = len(remaining)
    while i < n:
        tok = remaining[i]
        if tok == FILES_FLAG:
            files_present = True
            i += 1
            while i < n and not remaining[i].startswith("--"):
                raw_values.append(remaining[i])
                i += 1
        else:
            cleaned.append(tok)
            i += 1
    return files_present, _normalize_files(raw_values), cleaned


# ---------------------------------------------------------------------------
# サブコマンド
# ---------------------------------------------------------------------------

def cmd_init(args, remaining):
    """セッションディレクトリを作成し、session.yaml を書き出す。

    作成に先立ち、completed 残骸を全スキル横断で自動回収する（#93）。
    in_progress 残骸は再開価値があり得るため対象にしない。

    review の ``--files``（レビュー対象ファイル群）は可変長 list として受け、
    session.yaml に ``files`` フィールドとして保存する。``--files`` の抽出と
    validation は、後続の副作用（残骸回収・ディレクトリ作成）より前に完了させる
    ことで、invalid 入力時に副作用ゼロで reject する。
    """
    skill = args.skill

    # --files の抽出と validation は全副作用より前に行う（invalid 時に副作用ゼロ）
    files_present, files, cleaned_remaining = extract_files(remaining)
    if files_present and skill != "review":
        return {
            "status": "error",
            "error": f"--files は review skill 専用の予約キーです（skill={skill}）",
        }

    # 新規作成前に completed 残骸を回収（in_progress には触れない、#93）
    auto_cleanup = _auto_cleanup_on_init()

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

    # 残余引数からスキル固有フィールドを追加（--files は除外済み）
    extra = parse_extra_args(cleaned_remaining)
    data.update(extra)

    # --files 指定時のみ files フィールドを書く（値 0 個でも空配列を明示記録する）
    # ADR-032: files は [{path: ...}] dict 配列で保存する。
    if files_present:
        data["files"] = [{"path": p} for p in files]

    # session.yaml 書き出し
    yaml_path = os.path.join(session_dir, "session.yaml")
    write_flat_yaml(yaml_path, data, field_order=SESSION_FIELD_ORDER)

    return {
        "status": "created",
        "session_dir": session_dir,
        "auto_cleanup": auto_cleanup,
    }


def _auto_cleanup_on_init():
    """新規セッション作成前に completed 残骸のみを全スキル横断で回収する（#93）。

    `status: completed` は正常完了をマーク済みなのに cleanup されなかった
    クラッシュ残骸であり、価値がないため即時回収して安全。
    `status: in_progress` は中断中で再開価値があり得るため対象にしない
    （誤削除防止）。in_progress の時間ベース回収は手動 `cleanup-stale` に委ねる。

    cleanup に失敗しても init 本体を妨げないよう、例外は捕捉して warning を返す。
    回収は best-effort であり、セッション作成（ユーザー作業）を絶対にブロックしない契約のため、
    捕捉範囲は意図的に広い（壊れた session.yaml 由来の予期しない例外も握りつぶす）。
    """
    try:
        return _cleanup_stale_core(
            cutoff_hours=0,
            skill_filter=None,
            dry_run=False,
            completed_only=True,
        )
    except Exception as e:  # noqa: BLE001 - fail-open 契約のため意図的に広く捕捉
        msg = f"自動 cleanup に失敗しました: {e}"
        print(f"[forge session] warning: {msg}", file=sys.stderr)
        return {"error": msg}


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


def cmd_probe(args):
    """中断判定: completed 残骸を自動回収し、自スキルの resumable を返す。

    SKILL 側から「中断があったか / 再開できるか」だけを問えるよう、find の生 JSON
    分岐を内部に隠蔽する。返却は以下のいずれか:

      - {"state": "none"}                                        — 再開対象なし
      - {"state": "resumable", "session_dir": ..., "started_at": ..., "last_updated": ...}

    副作用: 全スキル横断で `status: completed` の残骸を自動 cleanup する（init と
    同じ「完了済みなのに残っている = 価値ゼロ」の方針）。
    """
    skill = args.skill

    # completed 残骸を全スキル横断で best-effort 回収（_auto_cleanup_on_init と同じ動作）
    _auto_cleanup_on_init()

    # 自スキルの in_progress を検索
    pattern = os.path.join(TEMP_BASE, "*", "session.yaml")
    candidates = []
    for yaml_path in sorted(glob.glob(pattern)):
        try:
            data = read_yaml(yaml_path)
        except (IOError, OSError):
            continue
        if data.get("skill") != skill:
            continue
        if data.get("status") != "in_progress":
            continue
        candidates.append({
            "session_dir": os.path.dirname(yaml_path),
            "started_at": data.get("started_at", ""),
            "last_updated": data.get("last_updated", ""),
        })

    if not candidates:
        return {"state": "none"}

    # 複数残っている場合は最新の last_updated を選ぶ（古いものは手動 cleanup-stale 待ち）
    candidates.sort(key=lambda c: c["last_updated"], reverse=True)
    top = candidates[0]
    return {
        "state": "resumable",
        "session_dir": top["session_dir"],
        "started_at": top["started_at"],
        "last_updated": top["last_updated"],
    }


def cmd_resume(args):
    """中断セッションを再開する。last_updated を更新し、session.yaml の内容を返す。

    SKILL 側はこの返却 dict をそのままコンテキストとして使える（skill / feature /
    review_type など、init 時に保存された任意フィールドを含む）。
    """
    session_dir = args.session_dir
    data = _update_session_yaml(session_dir, {})
    if data.get("status") == "error":
        return data
    return {
        "status": "ok",
        "session_dir": session_dir,
        "session": data,
    }


def cmd_finish(args):
    """正常完了処理: complete → cleanup を 1 動詞で行う。

    SKILL 側の "2 段呼び" を集約する。complete 段でクラッシュしても次回起動時の
    auto-cleanup が拾うため、安全性は 2 段呼びと等価。
    """
    session_dir = args.session_dir

    # complete (status: completed に遷移)
    data = _update_session_yaml(session_dir, {"status": "completed"})
    if data.get("status") == "error":
        return data

    # cleanup (rmtree)
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
    return {"status": "finished", "session_dir": session_dir}


def _parse_iso_ts(ts):
    """ISO 8601 (Z 表記または +00:00 表記) を aware datetime に変換する。

    yaml_utils.now_iso() の出力 (`%Y-%m-%dT%H:%M:%SZ`) との往復に加え、
    手書きセッションへの後方互換として `+00:00` も受理する。

    tz 情報のない naive 文字列（例: 手書き `2026-01-01T00:00:00`）は UTC とみなす。
    これを怠ると aware な `datetime.now(timezone.utc)` との減算で TypeError になり、
    `cleanup-stale` / `init` 自動回収が落ちる（#93 レビュー指摘）。
    """
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cleanup_stale_core(cutoff_hours, skill_filter, dry_run, completed_only=False):
    """期限切れの残骸セッションを走査し、対象を削除するコアロジック。

    判定ルール:
      - `completed_only=True` の場合、`status: in_progress` は一切対象にしない（#93）
      - `status: completed` のセッションは `cutoff_hours` を無視して常に削除対象
        （正常完了したのに cleanup されなかったクラッシュ残骸を即回収するため）
      - `status: in_progress` のセッションは `started_at` と `last_updated` のうち
        新しい方を基準とし、`cutoff_hours` より古いものを削除する

    Returns:
        dict: ``{"deleted": [...], "skipped": [...]}``
    """
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

        # completed_only モードでは in_progress を一切対象にしない（誤削除防止、#93）
        if completed_only and not is_completed:
            continue

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

    return {"deleted": deleted, "skipped": skipped}


def cmd_cleanup_stale(args):
    """期限切れの残骸セッションを一括削除する。

    判定ルール:
      - `status: completed` のセッションは `--older-than-hours` を無視して常に削除対象
        （正常完了したのに cleanup されなかったクラッシュ残骸を即回収するため）
      - `status: in_progress` のセッションは `started_at` と `last_updated` のうち
        新しい方を基準とし、`--older-than-hours N` より古いものを削除する
      - `--completed-only` 指定時は `in_progress` を一切対象にしない（誤削除防止、#93）

    `--skill` 指定時は該当スキルのみが対象。
    `--dry-run` 時は削除予定一覧のみを返す。
    """
    cutoff_hours = args.older_than_hours

    if cutoff_hours < 0:
        return {
            "status": "error",
            "error": f"--older-than-hours は 0 以上を指定してください: {cutoff_hours}",
        }

    result = _cleanup_stale_core(
        cutoff_hours=cutoff_hours,
        skill_filter=args.skill,
        dry_run=args.dry_run,
        completed_only=getattr(args, "completed_only", False),
    )
    return {
        "status": "dry-run" if args.dry_run else "ok",
        "cutoff_hours": cutoff_hours,
        "deleted": result["deleted"],
        "skipped": result["skipped"],
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

    # probe サブコマンド
    probe_parser = subparsers.add_parser(
        "probe",
        help="中断判定（completed 残骸を自動回収し、自スキルの resumable を返す）",
    )
    probe_parser.add_argument("--skill", required=True, help="判定対象のスキル名")

    # resume サブコマンド
    resume_parser = subparsers.add_parser(
        "resume",
        help="中断セッションを再開（last_updated 更新 + session.yaml 全体を返却）",
    )
    resume_parser.add_argument("session_dir", help="再開するセッションディレクトリパス")

    # finish サブコマンド
    finish_parser = subparsers.add_parser(
        "finish",
        help="正常完了処理（complete + cleanup を 1 動詞に統合）",
    )
    finish_parser.add_argument("session_dir", help="完了処理するセッションディレクトリパス")

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
    stale_parser.add_argument(
        "--completed-only",
        action="store_true",
        help="status: completed の残骸のみを対象にする（in_progress は削除しない）",
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
    elif args.command == "probe":
        result = cmd_probe(args)
    elif args.command == "resume":
        result = cmd_resume(args)
    elif args.command == "finish":
        result = cmd_finish(args)
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
