#!/usr/bin/env python3
"""次のラウンドの置き場を作る。依頼も、採番のための状態も作らない。

当該ラウンドの所見の結果と評価の結果が、どちらも正常に封緘されていることを確かめ、
``<round_number + 1>/`` を作る。どちらかが正常でなければ、理由をすべて ``errors`` に入れて失敗する
（``resolve_review_path.py --kind inputs`` と同じ方針）。次のラウンドの置き場が既に存在すれば、
上書きせず失敗する（``mkdir`` の ``FileExistsError`` で判定する）。

本 script は REQ-029 の FNC-302・313 の実装（DES-083 §6.6）である。

## 終了コード

| code | 意味                                                                                       |
| ---- | ------------------------------------------------------------------------------------------ |
| 0    | 作った（標準出力は ``{"round_number": <次の値>}``）                                        |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。結果が正常でない、次の置き場が既にある場合） |
| 2    | 引数を受理できない（``argparse``）                                                         |

Usage:
    python3 advance_round.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402


def cmd_advance(args):
    reason = review_common.missing_round(args.project_root, args.review_id, args.round_number)
    if reason:
        return review_common.error(reason)
    round_path = review_common.round_dir(args.project_root, args.review_id, args.round_number)
    reasons = [
        r
        for r in (
            review_common.result_problem(round_path, review_common.RESULT_FILE, "所見の結果", args.round_number),
            review_common.result_problem(round_path, review_common.EVALUATION_FILE, "評価の結果", args.round_number),
        )
        if r
    ]
    if reasons:
        return review_common.error(*reasons)

    next_number = args.round_number + 1
    next_path = review_common.round_dir(args.project_root, args.review_id, next_number)
    try:
        next_path.mkdir()
    except FileExistsError:
        return review_common.error(
            f"次のラウンドの置き場が既にあります: review_id={args.review_id} round_number={next_number}"
        )
    except OSError as exc:
        return review_common.error(f"次のラウンドの置き場を作れません: {exc}")

    review_common.emit({"round_number": next_number})
    return 0


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_root")
    parser.add_argument("review_id")
    parser.add_argument("round_number", type=int)
    return parser


def run_cli(argv=None):
    return cmd_advance(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(run_cli())
