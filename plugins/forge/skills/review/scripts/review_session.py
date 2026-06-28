#!/usr/bin/env python3
"""review SKILL のセッション動詞 wrapper。

SKILL.md が schema や JSON 分岐を直接持たなくて済むよう、状態機械レベルの
動詞 (probe / start / resume / finish / status) で会話できるようにする。

内部では session_manager.py (低レベル CRUD) と write_refs.py / SessionStore
を組み合わせ、review 固有の知識 (review_packet schema, review_<種別>.md の
位置, plan.yaml 集計) を吸収する。

使用例:
    # 中断判定 (completed 残骸も内部で自動回収)
    python3 review_session.py probe
    # → {"state": "none"} または {"state": "resumable", "session_dir": "...", ...}

    # 新規開始 (refs JSON を stdin から受け取り、session 作成 + refs.yaml 書き込みを原子化)
    echo '<refs_json>' | python3 review_session.py start \
        --review-type code --engine claude --interaction auto
    # → {"session_dir": "..."}

    # 再開 (last_updated 更新 + 次に実行すべき Phase を返す)
    python3 review_session.py resume {session_dir}
    # → {"session_dir": "...", "next_phase": "reviewer|evaluator|present|finish"}

    # 進捗集計 (plan.yaml を読み、ルーティング判定用の集計を返す)
    python3 review_session.py status {session_dir}
    # → {"unprocessed_total": N, "by_severity": {...}, "next_action": "fix|present|finish"}

    # 完了 (complete + cleanup を 1 動詞で)
    python3 review_session.py finish {session_dir}
    # → {"status": "finished"}
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SKILL = "review"
_SKILL_SCRIPTS_DIR = Path(__file__).resolve().parent
_PLUGIN_ROOT = _SKILL_SCRIPTS_DIR.parents[2]
_LOW_LEVEL = _PLUGIN_ROOT / "scripts" / "session_manager.py"
_WRITE_REFS = _PLUGIN_ROOT / "scripts" / "session" / "write_refs.py"

# session 内に置かれる検出対象ファイル
REFS_NAME = "refs.yaml"
PLAN_NAME = "plan.yaml"
SESSION_NAME = "session.yaml"


# ---------------------------------------------------------------------------
# 低レベル呼び出し helper
# ---------------------------------------------------------------------------

def _run_session_manager(*args, input_data=None):
    """session_manager.py を subprocess で呼び、JSON をパースして返す。"""
    proc = subprocess.run(
        [sys.executable, str(_LOW_LEVEL), *args],
        input=input_data,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {
            "status": "error",
            "error": (proc.stderr or proc.stdout or "session_manager.py 失敗").strip(),
        }
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"JSON パース失敗: {e}: {proc.stdout!r}"}


def _read_yaml_simple(path):
    """plan.yaml / session.yaml を読むため最小限の YAML reader を委譲。

    session_manager のヘルパを再利用する。
    """
    sys.path.insert(0, str(_PLUGIN_ROOT / "scripts"))
    from session.yaml_utils import read_yaml  # noqa: WPS433
    return read_yaml(path)


# ---------------------------------------------------------------------------
# 動詞: probe
# ---------------------------------------------------------------------------

def cmd_probe(args):
    """中断判定 + completed 残骸の自動回収。

    session_manager.py probe をそのまま透過する。SKILL 側は state フィールド
    だけで分岐できる。
    """
    return _run_session_manager("probe", "--skill", SKILL)


# ---------------------------------------------------------------------------
# 動詞: start
# ---------------------------------------------------------------------------

def cmd_start(args):
    """新規 review セッションを作成し、refs.yaml を書き込む。

    init (session.yaml 作成) と write_refs (refs.yaml 書き込み) を 1 動詞に
    まとめる。stdin から refs JSON を受け取る。
    """
    # 1. init で session 作成 + メタデータ保存
    init_args = ["init", "--skill", SKILL]
    if args.review_type:
        init_args += ["--review-type", args.review_type]
    if args.engine:
        init_args += ["--engine", args.engine]
    if args.interaction:
        init_args += ["--interaction", args.interaction]
    if args.auto_count is not None:
        init_args += ["--auto-count", str(args.auto_count)]
    if args.current_cycle is not None:
        init_args += ["--current-cycle", str(args.current_cycle)]
    if args.files:
        init_args += ["--files"] + args.files

    init_result = _run_session_manager(*init_args)
    if init_result.get("status") == "error":
        return init_result
    session_dir = init_result["session_dir"]

    # 2. stdin から refs JSON を読み、write_refs.py に渡す
    refs_raw = sys.stdin.read()
    if not refs_raw.strip():
        # refs なしでも session は作成済み (テスト等)
        return {"session_dir": session_dir, "refs_written": False}

    proc = subprocess.run(
        [sys.executable, str(_WRITE_REFS), session_dir],
        input=refs_raw,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        # session は作成済みだが refs 書き込みに失敗 → session を片付けて error
        _run_session_manager("cleanup", session_dir)
        return {
            "status": "error",
            "error": (proc.stderr or proc.stdout or "write_refs 失敗").strip(),
        }

    return {"session_dir": session_dir, "refs_written": True}


# ---------------------------------------------------------------------------
# 動詞: resume
# ---------------------------------------------------------------------------

def _detect_next_phase(session_dir):
    """セッション内のファイル状況から次に実行すべき Phase を判定する。

    判定順 (上から順に評価):
      1. refs.yaml がない                → "start"  (異常状態。新規作成へ誘導)
      2. review_<type>.md が未生成        → "reviewer"
      3. plan.yaml がない or 空          → "evaluator"
      4. plan.yaml に pending あり        → "present"
      5. 全件処理済み                     → "finish"
    """
    session_path = Path(session_dir)
    if not (session_path / REFS_NAME).is_file():
        return "start"

    # review_<type>.md の発見: session.yaml から review_type を読む
    session_yaml = session_path / SESSION_NAME
    review_type = None
    if session_yaml.is_file():
        try:
            sdata = _read_yaml_simple(str(session_yaml))
            review_type = sdata.get("review_type")
        except (IOError, OSError):
            pass

    review_md_present = False
    if review_type:
        review_md_present = (session_path / f"review_{review_type}.md").is_file()
    else:
        # review_type 未確定: review_*.md があるか走査
        review_md_present = any(session_path.glob("review_*.md"))

    if not review_md_present:
        return "reviewer"

    plan_yaml = session_path / PLAN_NAME
    if not plan_yaml.is_file():
        return "evaluator"

    try:
        plan = _read_yaml_simple(str(plan_yaml))
    except (IOError, OSError):
        return "evaluator"

    items = plan.get("items") if isinstance(plan, dict) else None
    if not items:
        return "evaluator"

    has_pending = any(
        (it.get("status") in ("pending", "in_progress"))
        for it in items if isinstance(it, dict)
    )
    return "present" if has_pending else "finish"


def cmd_resume(args):
    """中断セッションを再開し、次に実行すべき Phase を返す。"""
    raw = _run_session_manager("resume", args.session_dir)
    if raw.get("status") != "ok":
        return raw
    next_phase = _detect_next_phase(args.session_dir)
    return {
        "status": "ok",
        "session_dir": args.session_dir,
        "session": raw.get("session", {}),
        "next_phase": next_phase,
    }


# ---------------------------------------------------------------------------
# 動詞: finish
# ---------------------------------------------------------------------------

def cmd_finish(args):
    """正常完了処理 (session_manager.py finish の透過)。"""
    return _run_session_manager("finish", args.session_dir)


# ---------------------------------------------------------------------------
# 動詞: status
# ---------------------------------------------------------------------------

def _classify_items(items):
    """plan.yaml の items[] を集計する。"""
    by_severity = {"critical": 0, "warning": 0, "info": 0, "unknown": 0}
    by_status = {"pending": 0, "in_progress": 0, "fixed": 0, "skipped": 0, "other": 0}
    by_recommendation = {"fix": 0, "skip": 0, "create_issue": 0, "needs_review": 0, "unset": 0}
    unprocessed_total = 0
    fixable_pending = 0  # recommendation: fix AND auto_fixable: true AND status: pending

    for it in items or []:
        if not isinstance(it, dict):
            continue
        sev = (it.get("severity") or "").lower()
        if sev in by_severity:
            by_severity[sev] += 1
        else:
            by_severity["unknown"] += 1

        st = it.get("status") or "pending"
        if st in by_status:
            by_status[st] += 1
        else:
            by_status["other"] += 1

        rec = it.get("recommendation")
        if rec in by_recommendation:
            by_recommendation[rec] += 1
        else:
            by_recommendation["unset"] += 1

        if st in ("pending", "in_progress"):
            unprocessed_total += 1
            if rec == "fix" and it.get("auto_fixable") is True and st == "pending":
                fixable_pending += 1

    return {
        "unprocessed_total": unprocessed_total,
        "by_severity": by_severity,
        "by_status": by_status,
        "by_recommendation": by_recommendation,
        "fixable_pending": fixable_pending,
    }


def _decide_next_action(summary):
    """集計結果から次に取るべきアクションを決める。"""
    if summary["unprocessed_total"] == 0:
        return "finish"
    if summary["fixable_pending"] > 0:
        return "fix"
    return "present"


def cmd_status(args):
    """plan.yaml を集計し、ルーティング判定用の値を返す。"""
    plan_yaml = Path(args.session_dir) / PLAN_NAME
    if not plan_yaml.is_file():
        return {
            "status": "ok",
            "session_dir": args.session_dir,
            "plan_present": False,
            "unprocessed_total": 0,
            "next_action": "evaluator",
        }
    try:
        plan = _read_yaml_simple(str(plan_yaml))
    except (IOError, OSError) as e:
        return {"status": "error", "error": f"plan.yaml 読み込み失敗: {e}"}

    items = plan.get("items") if isinstance(plan, dict) else None
    summary = _classify_items(items)
    return {
        "status": "ok",
        "session_dir": args.session_dir,
        "plan_present": True,
        **summary,
        "next_action": _decide_next_action(summary),
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="review SKILL セッション動詞 wrapper")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("probe", help="中断判定 + completed 残骸の自動回収")

    sp_start = sub.add_parser(
        "start", help="新規 review セッションを作成し refs.yaml を書く",
        # SKILL レベルのフラグ (--auto / --interactive / --auto-critical 等) が
        # `--auto-count` 等への prefix-match で誤って消費されないよう、prefix 省略を無効化。
        allow_abbrev=False,
    )
    sp_start.add_argument("--review-type", required=True)
    sp_start.add_argument("--engine", default=None)
    sp_start.add_argument("--interaction", default=None)
    sp_start.add_argument("--auto-count", type=int, default=None)
    sp_start.add_argument("--current-cycle", type=int, default=None)
    sp_start.add_argument("--files", nargs="*", default=None,
                          help="レビュー対象ファイル群 (review 専用予約キー)")

    sp_resume = sub.add_parser("resume", help="中断セッションを再開し next_phase を返す")
    sp_resume.add_argument("session_dir")

    sp_finish = sub.add_parser("finish", help="正常完了 (complete + cleanup)")
    sp_finish.add_argument("session_dir")

    sp_status = sub.add_parser("status", help="plan.yaml 集計とルーティング判定")
    sp_status.add_argument("session_dir")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "probe": cmd_probe,
        "start": cmd_start,
        "resume": cmd_resume,
        "finish": cmd_finish,
        "status": cmd_status,
    }
    result = dispatch[args.command](args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
