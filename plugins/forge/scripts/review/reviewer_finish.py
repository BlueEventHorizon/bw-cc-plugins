#!/usr/bin/env python3
"""reviewer が所見の結果を封緘し、正常終了を表す終了の値 ``"0"`` を書く。

reviewer 用のラッパーである。呼ぶ主体から決定論的に決まるオプション（``--kind findings``。
``--exit`` は渡さないので ``"0"`` になる）を固定して ``seal_result.py`` を呼ぶだけで、処理を
持たない。標準出力と終了コードは基本の script のものがそのまま返る。受け取る引数は、基本の script
の引数から固定したオプションを除いたもの（``<project_root> <review_id> <round_number>``）である。
所見が 0 件でも呼ぶ。reviewer の定義に、所見以外を書く口が現れないようにするためにある。

本 script は REQ-029 の FNC-311・314 と REQ-027 の FNC-301・309 に沿う、DES-084 §6.6 の
実装である。

## 終了コード

基本の script の終了コードをそのまま返す。

| code | 意味                                                         |
| ---- | ------------------------------------------------------------ |
| 0    | 封緘した（標準出力は ``{}``）                                |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由。封緘済みを含む） |
| 2    | 引数を受理できない（``argparse``）                           |

Usage:
    python3 reviewer_finish.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import review_common  # noqa: E402
import seal_result  # noqa: E402


def run_cli(argv=None):
    return review_common.run_wrapper(seal_result.run_cli, ["--kind", "findings"], argv)


if __name__ == "__main__":
    raise SystemExit(run_cli())
