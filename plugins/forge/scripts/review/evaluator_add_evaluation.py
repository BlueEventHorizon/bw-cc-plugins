#!/usr/bin/env python3
"""evaluator が評価を 1 件追記する。

evaluator 用のラッパーである。呼ぶ主体から決定論的に決まるオプション（``--kind evaluations``）を
固定して ``append_result.py`` を呼ぶだけで、処理を持たない。標準出力と終了コードは基本の script の
ものがそのまま返る。受け取る引数は、基本の script の引数から固定したオプションを除いたもの
（``<project_root> <review_id> <round_number> --disposition D --severity V [--findings N ...]
[--new] [--location L ...] [--confidence C] [--fix-confident true|false]``。判定の根拠は標準入力）
である。値の検査（引く番号の実在、``location`` の有無、確信度の制約）は基本の script が行う。
evaluator の定義に、所見（``--kind findings``）を書く口が現れないようにするためにある。

本 script は REQ-029 の FNC-310・313・203・314 と REQ-026 の FNC-206 に沿う、DES-083 §6.1・§6.2 の
実装である。

## 終了コード

基本の script の終了コードをそのまま返す。

| code | 意味                                                                                                      |
| ---- | --------------------------------------------------------------------------------------------------------- |
| 0    | 追記した（標準出力は、``--new`` の評価は採った ``finding_id``、他は ``{}``）                              |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。何も書かない）                                              |
| 2    | 引数を受理できない（``argparse``。``--disposition`` や ``--severity`` が無い、``--kind`` を渡した場合を含む） |

Usage:
    python3 evaluator_add_evaluation.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER \\
        --disposition D --severity V [--findings N [N ...]] [--new] [--location L [L ...]] \\
        [--confidence C] [--fix-confident {true,false}] < reason.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import append_result  # noqa: E402
import review_common  # noqa: E402

# 基本の script がそのまま受け取るオプション（値域は基本の script と同じものを使う）
PASSED_OPTIONS = (
    ("--disposition", {"choices": append_result.DISPOSITIONS, "required": True}),
    ("--severity", {"choices": append_result.SEVERITIES, "required": True}),
    ("--findings", {"nargs": "+", "action": "extend", "type": int, "default": []}),
    ("--new", {"action": "store_true"}),
    ("--location", {"nargs": "+", "action": "extend"}),
    ("--confidence", {"choices": append_result.CONFIDENCES}),
    ("--fix-confident", {"choices": ["true", "false"]}),
)


def run_cli(argv=None):
    return review_common.run_wrapper(
        append_result.run_cli, ["--kind", "evaluations"], argv, passed_options=PASSED_OPTIONS
    )


if __name__ == "__main__":
    raise SystemExit(run_cli())
