#!/usr/bin/env python3
"""対応を要する評価の件数を数える。何も書かない。

評価の結果が正常に封緘されていることを確かめ、``disposition`` が ``valid`` または
``flawed_premise`` の評価を数える。``invalid``・``misunderstanding``・``out_of_scope`` は
数えない。返すのは件数だけで、所見と評価の JSON 本文は返さない。

本 script は REQ-029 の FNC-318 の実装（DES-083 §6.5）である。

## 終了コード

| code | 意味                                                                           |
| ---- | ------------------------------------------------------------------------------ |
| 0    | 数えた（標準出力は ``{"actionable": n}``）                                     |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。評価の結果が無い、正常でない場合） |
| 2    | 引数を受理できない（``argparse``）                                             |

Usage:
    python3 count_actionable.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402

# 対応を要する disposition（REQ-029 FNC-318）
ACTIONABLE = ("valid", "flawed_premise")


def cmd_count(args):
    reason = review_common.missing_round(args.project_root, args.review_id, args.round_number)
    if reason:
        return review_common.error(reason)
    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    reason = review_common.result_problem(
        round_path, review_common.EVALUATION_FILE, "評価の結果", args.round_number
    )
    if reason:
        return review_common.error(reason)

    result = review_common.load_result(round_path, review_common.EVALUATION_FILE)
    count = sum(
        1 for e in result["evaluations"] if isinstance(e, dict) and e.get("disposition") in ACTIONABLE
    )
    review_common.emit({"actionable": count})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    return parser


def run_cli(argv=None):
    return cmd_count(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(run_cli())
