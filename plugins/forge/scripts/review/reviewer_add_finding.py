#!/usr/bin/env python3
"""reviewer が所見を 1 件追記する。

reviewer 用のラッパーである。呼ぶ主体から決定論的に決まるオプション（``--kind findings``）を
固定して ``append_result.py`` を呼ぶだけで、処理を持たない。標準出力と終了コードは基本の script の
ものがそのまま返る。受け取る引数は、基本の script の引数から固定したオプションを除いたもの
（``<project_root> <review_id> <round_number> --location L [L ...]``。所見の本文は標準入力）である。
reviewer の定義に、所見以外を書く口が現れないようにするためにある。

本 script は REQ-029 の FNC-310・313・314 と REQ-027 の FNC-301・309 に沿う、DES-084 §6.6 の
実装である。

## 終了コード

基本の script の終了コードをそのまま返す。

| code | 意味                                                                    |
| ---- | ----------------------------------------------------------------------- |
| 0    | 追記した（標準出力に採った ``finding_id``）                             |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由）                          |
| 2    | 引数を受理できない（``argparse``。``--location`` が無い場合を含む）    |

Usage:
    python3 reviewer_add_finding.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER \\
        --location L [L ...] < body.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import append_result  # noqa: E402
import review_common  # noqa: E402


def run_cli(argv=None):
    return review_common.run_wrapper(
        append_result.run_cli, ["--kind", "findings"], argv, takes_location=True
    )


if __name__ == "__main__":
    raise SystemExit(run_cli())
