#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""msg-review: 起床手段（cmux）の可用性を判定する read-only CLI（可用性検査の軸 A）。

`cmux` コマンドが実行可能かどうかだけを判定する。判定は PATH の探索のみで行い、
**cmux を一度も起動しない**（副作用を持たない）。

## なぜ軸を分けるか（DES-045 §3.5.2 / ADR-068 §2.1）

可用性検査の前提は「起床手段が使えること」と「相手セッションが常駐していること」の
2 軸からなる。現時点では往復の成立に両方が必要だが（起床手段が無ければ、相手が
常駐していてもターンを起こす契機が生まれず往復が止まる）、将来 cmux を必要としない
起床経路が成立すれば常駐の判定だけで足りるようになる。両者を 1 つの判定に畳むと
その変化に対して判定ロジックの解体が必要になるため、軸ごとに独立したスクリプトに
分ける。本 CLI は軸 A（起床手段）だけを担い、常駐の判定（軸 B）は
`find_codex_pane.py` が担う。

## 判定を PATH 探索に留める理由

`cmux --version` 等でコマンドを実際に起動して健全性まで確かめる案は採らない。

- 可用性検査は候補バックエンドを順に検査するため安価でなければならない
  （forge:ADR-067 §2.1）
- cmux が存在するが壊れている場合は、軸 B（`find_codex_pane.py`）が cmux への
  問い合わせ失敗として検出する。軸 A で二重に検出する必要がない

## exit code / JSON 契約

終了コードは常に 0 である（可用性の有無は異常ではなく検査結果であり、
`status` で表す）。標準出力に単一 JSON を書く。

| `status`      | 意味                             |
| ------------- | -------------------------------- |
| `available`   | `cmux` が実行可能               |
| `unavailable` | `cmux` が見つからない（`reason`） |

## 依存

Python 標準ライブラリのみ。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys

#: 起床に使う外部コマンド名
CMUX_COMMAND = "cmux"

#: JSON contract の `status` 値
STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"


def check_cmux_available(*, which=shutil.which) -> dict:
    """`cmux` コマンドの可用性を判定する（read-only・副作用なし）。

    `which` はテストの差し替え境界。既定は `shutil.which`（PATH 探索のみを行い
    プロセスを起動しない）。
    """
    path = which(CMUX_COMMAND)
    if not path:
        return {
            "status": STATUS_UNAVAILABLE,
            "reason": (
                f"{CMUX_COMMAND} コマンドが PATH 上に見つかりません"
                "（端末多重化ツール cmux が未導入か、PATH に含まれていません）"
            ),
        }
    return {"status": STATUS_AVAILABLE, "path": path}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="起床手段（cmux）の可用性を判定する（read-only）",
    )
    parser.parse_args(argv)


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parse_args(argv)
    print(json.dumps(check_cmux_available(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
