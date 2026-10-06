#!/usr/bin/env python3
"""結果へ 1 件追記する。``finding_id`` を採る。

``--kind`` は次の 2 つである。

- ``findings`` — reviewer の所見。所見の本文は標準入力の全体を、加工せずに 1 つの値として
  受け取る。位置（``--location``）は渡された順に保持する
- ``evaluations`` — evaluator の評価。判定の根拠（``reason``）は標準入力の全体を加工せずに
  受け取る。``--findings`` で引く番号を、``--new`` で新規指摘の番号を渡す。所見との関係
  （引く番号の実在、``location`` の有無、確信度の制約）を書く時点で確かめ、満たさなければ
  何も書かずに失敗する

``finding_id`` は、そのレビューの全ラウンドの所見と評価に現れる ``finding_id`` の最大値の次
（どれにも無ければ ``1``）である。reviewer と evaluator が 1 本の連番を分け合う。採番の状態を
別に持たず、採番と書き込みは 1 回の操作（一時ファイルを経由した置き換え）なので、採った番号が
書かれないまま残ることはない。

追記先は ``<project_root>/.temp/review/<review_id>/<round_number>/`` の ``review_result.json``
（所見）と ``evaluate_result.json``（評価）である。ファイルが無ければ空の配列から始める。
封緘済み（``exit`` を持つ）なら追記しない。

本 script は REQ-029 の FNC-310・313・203 と DM-201・302・304・305 の実装
（DES-084 §6.3、DES-083 §6.2）である。

## 終了コード

| code | 意味                                                                     |
| ---- | ------------------------------------------------------------------------ |
| 0    | 追記した（標準出力に、``--new`` の評価と所見は採った ``finding_id``、他は ``{}``） |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。何も書かない）             |
| 2    | 引数を受理できない（``argparse``。``--kind`` に必要な引数が無い、``--kind`` に属さない引数がある場合を含む） |

Usage:
    python3 append_result.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER --kind findings \\
        --location L [L ...] < body.txt
    python3 append_result.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER --kind evaluations \\
        --disposition D --severity V [--findings N [N ...]] [--new] [--location L [L ...]] \\
        [--confidence C] [--fix-confident {true,false}] < reason.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402

# 位置を特定できないとき、位置として持つ唯一の値（DM-304）
UNKNOWN_LOCATION = "位置未確定"

DISPOSITIONS = ["invalid", "misunderstanding", "out_of_scope", "flawed_premise", "valid"]
SEVERITIES = ["critical", "major", "minor"]
CONFIDENCES = ["confirmed", "inferred", "unverified"]

# --kind evaluations だけが受け取る引数（findings で渡されたら引数の誤りとする）
_EVALUATION_ONLY = {
    "disposition": "--disposition",
    "severity": "--severity",
    "findings": "--findings",
    "new": "--new",
    "confidence": "--confidence",
    "fix_confident": "--fix-confident",
}


def next_finding_id(review_path):
    """そのレビューの全ラウンドの所見と評価に現れる ``finding_id`` の最大値の次を返す。無ければ 1。"""
    highest = 0
    for round_path in review_path.iterdir():
        if not (round_path.is_dir() and round_path.name.isdigit()):
            continue
        for finding in (review_common.load_result(round_path) or {}).get("findings", []):
            highest = max(highest, finding["finding_id"])
        evaluations = review_common.load_result(round_path, review_common.EVALUATION_FILE)
        for evaluation in (evaluations or {}).get("evaluations", []):
            highest = max([highest, *evaluation["finding_ids"]])
    return highest + 1


def _take_finding_id(review_path):
    """``(finding_id, error)`` を返す。他ラウンドの結果が読めない・壊れているときは採番せず理由を返す。"""
    try:
        return next_finding_id(review_path), None
    except (OSError, ValueError, KeyError) as exc:
        return None, f"finding_id を採るための結果を読めません: {exc!r}"


def _location_errors(locations):
    """位置の誤りを理由の一覧で返す。無ければ空配列。"""
    bad = review_common.non_absolute([loc for loc in locations if loc != UNKNOWN_LOCATION])
    if bad:
        return [f"--location は絶対パスで渡してください: {', '.join(bad)}"]
    return []


def _read_stdin(label):
    """標準入力の全体を、加工せずに UTF-8 の文字列として読む。``(text, error)`` を返す。"""
    try:
        text = sys.stdin.buffer.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, f"標準入力を UTF-8 として読めません: {exc}"
    if not text.strip():
        return None, f"{label}が空です（標準入力で渡してください）"
    return text, None


def cmd_append_findings(args):
    errors = _location_errors(args.location)
    if errors:
        return review_common.error(*errors)

    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    if not round_path.is_dir():
        return review_common.error(
            f"ラウンドの置き場がありません: review_id={args.review_id} round_number={args.round_number}"
        )

    try:
        result = review_common.load_result(round_path)
    except (OSError, ValueError) as exc:
        return review_common.error(f"所見の結果を読めません: {exc}")
    if result is not None and review_common.is_sealed(result):
        return review_common.error("所見の結果は封緘済みです。追記できません")

    body, problem = _read_stdin("所見の本文")
    if problem:
        return review_common.error(problem)

    finding_id, problem = _take_finding_id(round_path.parent)
    if problem:
        return review_common.error(problem)
    findings = [] if result is None else result["findings"]
    findings.append({"finding_id": finding_id, "location": list(args.location), "body": body})
    try:
        review_common.publish_json(round_path / review_common.RESULT_FILE, {"findings": findings})
    except OSError as exc:
        return review_common.error(f"所見の結果を書き込めません: {exc}")

    review_common.emit({"finding_id": finding_id})
    return 0


def _evaluation_argument_errors(args):
    """評価の引数だけから分かる誤りを、理由の一覧で返す（所見の結果は読まない）。"""
    errors = []
    if not args.findings and not args.new:
        errors.append("--findings も --new も渡されていません（評価は 1 個以上の所見を引きます）")
    if args.new and args.disposition != "valid":
        errors.append(f"--new の評価の --disposition は valid だけです: {args.disposition}")
    if args.disposition == "valid":
        if args.confidence is None:
            errors.append("--disposition valid には --confidence が必要です")
        if args.fix_confident is None:
            errors.append("--disposition valid には --fix-confident が必要です")
    else:
        if args.confidence is not None:
            errors.append(f"--disposition {args.disposition} は --confidence を持てません（valid だけが持ちます）")
        if args.fix_confident is not None:
            errors.append(f"--disposition {args.disposition} は --fix-confident を持てません（valid だけが持ちます）")
    if args.fix_confident == "true" and args.confidence != "confirmed":
        errors.append("--fix-confident true には --confidence confirmed が必要です")
    return errors


def cmd_append_evaluations(args):
    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    if not round_path.is_dir():
        return review_common.error(
            f"ラウンドの置き場がありません: review_id={args.review_id} round_number={args.round_number}"
        )

    reason = review_common.result_problem(
        round_path, review_common.RESULT_FILE, "所見の結果", args.round_number
    )
    if reason:
        return review_common.error(reason)
    try:
        result = review_common.load_result(round_path, review_common.EVALUATION_FILE)
    except (OSError, ValueError) as exc:
        return review_common.error(f"評価の結果を読めません: {exc}")
    if result is not None and review_common.is_sealed(result):
        return review_common.error("評価の結果は封緘済みです。追記できません")

    errors = _evaluation_argument_errors(args)
    errors += _location_errors(args.location or [])

    reason_text, problem = _read_stdin("判定の根拠")
    if problem:
        errors.append(problem)

    evaluations = [] if result is None else result["evaluations"]
    reviewer_ids = {f["finding_id"] for f in review_common.load_result(round_path)["findings"]}
    # 当該ラウンドの評価に既にある番号のうち、所見に無いものが evaluator の新規指摘（REQ-029 FNC-313）
    in_evaluations = {n for e in evaluations for n in e["finding_ids"]}
    new_ids = in_evaluations - reviewer_ids

    missing = [n for n in args.findings if n not in reviewer_ids and n not in new_ids]
    if missing:
        errors.append(
            "--findings の番号が、当該ラウンドの所見にも新規指摘にもありません: "
            + ", ".join(str(n) for n in missing)
        )

    includes_new = args.new or any(n in new_ids for n in args.findings)
    if includes_new and not args.location:
        errors.append("新規指摘の番号を含む評価には --location が必要です")
    if not includes_new and args.location:
        errors.append("新規指摘の番号を含まない評価は --location を持てません（位置は所見が持ちます）")

    if errors:
        return review_common.error(*errors)

    finding_ids = list(args.findings)
    new_id = None
    if args.new:
        new_id, problem = _take_finding_id(round_path.parent)
        if problem:
            return review_common.error(problem)
        finding_ids.append(new_id)

    evaluation = {
        "finding_ids": finding_ids,
        "disposition": args.disposition,
        "severity": args.severity,
        "reason": reason_text,
    }
    if args.disposition == "valid":
        evaluation["confidence"] = args.confidence
        evaluation["fix_confident"] = args.fix_confident == "true"
    if includes_new:
        evaluation["location"] = list(args.location)
    evaluations.append(evaluation)
    try:
        review_common.publish_json(
            round_path / review_common.EVALUATION_FILE, {"evaluations": evaluations}
        )
    except OSError as exc:
        return review_common.error(f"評価の結果を書き込めません: {exc}")

    review_common.emit({} if new_id is None else {"finding_id": new_id})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    parser.add_argument("--kind", required=True, choices=["findings", "evaluations"])
    parser.add_argument("--location", nargs="+", action="extend")
    parser.add_argument("--disposition", choices=DISPOSITIONS)
    parser.add_argument("--severity", choices=SEVERITIES)
    parser.add_argument("--findings", nargs="+", action="extend", type=int, default=[])
    parser.add_argument("--new", action="store_true")
    parser.add_argument("--confidence", choices=CONFIDENCES)
    parser.add_argument("--fix-confident", dest="fix_confident", choices=["true", "false"])
    return parser


def run_cli(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.kind == "findings":
        if not args.location:
            parser.error("--kind findings には --location が必要です")
        stray = [flag for dest, flag in _EVALUATION_ONLY.items() if getattr(args, dest) not in (None, False, [])]
        if stray:
            parser.error(f"--kind findings は {', '.join(stray)} を受け取りません")
        return cmd_append_findings(args)
    missing = [flag for dest, flag in _EVALUATION_ONLY.items() if dest in ("disposition", "severity") and getattr(args, dest) is None]
    if missing:
        parser.error(f"--kind evaluations には {', '.join(missing)} が必要です")
    return cmd_append_evaluations(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
