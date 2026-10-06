#!/usr/bin/env python3
"""結果を封緘する（終了の値 ``exit`` を書く）。

``--kind`` は次の 2 つである。

- ``findings`` — reviewer の所見の結果。``--exit`` に渡せる値は ``"0"``（省略時）と
  ``target_unreadable`` だけである
- ``evaluations`` — evaluator の評価の結果。``--exit`` に渡せる値は ``"0"`` だけである
  （evaluator が挙げうるエラー値は無い。REQ-026 FNC-319）。当該ラウンドの所見の結果が正常に
  封緘されていること、全所見がいずれかの評価に引かれていることを確かめる。引かれていない所見が
  残っていれば何も書かずに失敗し、その ``finding_id`` をすべて ``errors`` に入れる

``--exit`` が定義外の値のときは引数の誤りとして拒む。結果がまだ無ければ、空配列
（``findings`` / ``evaluations``）の結果を作ってから ``exit`` を書く（0 件のときも ``exit`` を
書けるようにする）。書き込みは一時ファイルを経由した 1 回の置き換えである。

封緘済みの結果は書き換えない。

本 script は REQ-029 の FNC-311・203 と REQ-027 の FNC-315、REQ-026 の FNC-319 の実装
（DES-084 §6.4、DES-083 §6.3）である。

## 終了コード

| code | 意味                                                                     |
| ---- | ------------------------------------------------------------------------ |
| 0    | 封緘した（標準出力は ``{}``）                                            |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。既に封緘済み、所見の結果が正常でない、引かれていない所見が残っている場合を含む） |
| 2    | 引数を受理できない（``argparse``。``--exit`` が ``--kind`` に対し定義外の値の場合を含む） |

Usage:
    python3 seal_result.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER --kind findings \\
        [--exit {0,target_unreadable}]
    python3 seal_result.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER --kind evaluations [--exit 0]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402

# --kind ごとの、結果の置き場・要素の配列名・受け付ける終了の値。エラー値は閉じた集合（REQ-027 FNC-315、REQ-026 FNC-319）
KINDS = {
    "findings": {"file": review_common.RESULT_FILE, "array": "findings", "label": "所見の結果", "exits": ["0", "target_unreadable"]},
    "evaluations": {"file": review_common.EVALUATION_FILE, "array": "evaluations", "label": "評価の結果", "exits": ["0"]},
}


def _referenced_ids(result):
    """評価の結果のいずれかの評価が引いている ``finding_id`` の集合。"""
    return {n for evaluation in result["evaluations"] for n in evaluation["finding_ids"]}


def _unreferenced_findings(round_path, evaluations_result):
    """当該ラウンドの所見のうち、どの評価にも引かれていない ``finding_id`` を昇順で返す。"""
    findings = review_common.load_result(round_path)["findings"]
    referenced = _referenced_ids(evaluations_result)
    return sorted(f["finding_id"] for f in findings if f["finding_id"] not in referenced)


def cmd_seal(args):
    spec = KINDS[args.kind]
    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    if not round_path.is_dir():
        return review_common.error(
            f"ラウンドの置き場がありません: review_id={args.review_id} round_number={args.round_number}"
        )

    if args.kind == "evaluations":
        reason = review_common.result_problem(
            round_path, review_common.RESULT_FILE, KINDS["findings"]["label"], args.round_number
        )
        if reason:
            return review_common.error(reason)

    try:
        result = review_common.load_result(round_path, spec["file"])
    except (OSError, ValueError) as exc:
        return review_common.error(f"{spec['label']}を読めません: {exc}")
    if result is None:
        result = {spec["array"]: []}
    elif review_common.is_sealed(result):
        return review_common.error(f"{spec['label']}は既に封緘済みです")

    if args.kind == "evaluations":
        unreferenced = _unreferenced_findings(round_path, result)
        if unreferenced:
            return review_common.error(
                *[f"評価に引かれていない所見があります: finding_id={n}" for n in unreferenced]
            )

    result["exit"] = args.exit
    try:
        review_common.publish_json(round_path / spec["file"], result)
    except OSError as exc:
        return review_common.error(f"{spec['label']}を書き込めません: {exc}")

    review_common.emit({})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    parser.add_argument("--kind", required=True, choices=list(KINDS))
    parser.add_argument("--exit", default="0")
    return parser


def run_cli(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    exits = KINDS[args.kind]["exits"]
    if args.exit not in exits:
        parser.error(f"argument --exit: --kind {args.kind} が受け付けるのは {exits} だけです: {args.exit!r}")
    return cmd_seal(args)


if __name__ == "__main__":
    raise SystemExit(run_cli())
