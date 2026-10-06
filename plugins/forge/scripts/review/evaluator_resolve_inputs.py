#!/usr/bin/env python3
"""evaluator が依頼と所見の絶対パスを得る。

evaluator 用のラッパーである。呼ぶ主体から決定論的に決まるオプション（``--kind inputs``）を
固定して ``resolve_review_path.py`` を呼ぶだけで、処理を持たない。標準出力と終了コードは基本の
script のものがそのまま返る。受け取る引数は、基本の script の引数から固定したオプションを除いた
もの（``<project_root> <review_id> <round_number>``）である。依頼と所見は常に対で要るので、2 つの
絶対パス（``request``、``findings``）を 1 回で返す。所見が正常に終えていなければどちらも返らない。

本 script は REQ-029 の FNC-302・311・314 と REQ-026 の DM-202 に沿う、DES-083 §6.1 の実装である。

## 終了コード

基本の script の終了コードをそのまま返す。

| code | 意味                                                                       |
| ---- | -------------------------------------------------------------------------- |
| 0    | 読み出せる（標準出力に ``request`` と ``findings``）                       |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。片方でも失敗すれば失敗）     |
| 2    | 引数を受理できない（``argparse``）                                         |

Usage:
    python3 evaluator_resolve_inputs.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolve_review_path  # noqa: E402
import review_common  # noqa: E402


def run_cli(argv=None):
    return review_common.run_wrapper(resolve_review_path.run_cli, ["--kind", "inputs"], argv)


if __name__ == "__main__":
    raise SystemExit(run_cli())
