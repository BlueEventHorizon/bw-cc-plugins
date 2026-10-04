"""Foo 売上管理の売上レポート出力（経理向け CSV）。"""

import csv
from pathlib import Path

from foo.store_master import store_code_of

TAX_RATE = 0.10


def write_csv(totals: dict[str, int], path: Path) -> None:
    """店舗ごとの売上合計を、経理の書式（税抜・千円単位）の CSV に書く。"""
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["店舗コード", "店舗名", "売上（税抜・千円単位）"])
        for name, amount in sorted(totals.items()):
            excluded = round(amount / (1 + TAX_RATE))
            writer.writerow([store_code_of(name), name, excluded // 1000])
