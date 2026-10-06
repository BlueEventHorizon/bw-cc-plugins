#!/usr/bin/env python3
"""本体が評価の絶対パスを得る。

本体用のラッパーである。呼ぶ主体から決定論的に決まるオプション（``--kind evaluations``）を
固定して ``resolve_review_path.py`` を呼ぶだけで、処理を持たない。標準出力と終了コードは基本の
script のものがそのまま返る。受け取る引数は、基本の script の引数から固定したオプションを除いた
もの（``<project_root> <review_id> <round_number>``）である。

本 script は REQ-029 の FNC-302・311 に沿う、DES-083 §6.8 の実装である。

## 終了コード

基本の script の終了コードをそのまま返す。

| code | 意味                                                         |
| ---- | ------------------------------------------------------------ |
| 0    | 読み出せる（標準出力に ``path``）                            |
| 1    | 区別のない失敗（標準出力の ``errors`` に理由）               |
| 2    | 引数を受理できない（``argparse``）                           |

Usage:
    python3 body_resolve_evaluations.py PROJECT_ROOT REVIEW_ID ROUND_NUMBER
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import resolve_review_path  # noqa: E402
import review_common  # noqa: E402


def run_cli(argv=None):
    return review_common.run_wrapper(resolve_review_path.run_cli, ["--kind", "evaluations"], argv)


if __name__ == "__main__":
    raise SystemExit(run_cli())
