"""Foo 売上管理の売上集計。"""

import datetime
from dataclasses import dataclass

from foo.store_master import list_store_names


@dataclass
class SaleRecord:
    store: str
    sold_on: datetime.date
    amount: int


def aggregate_by_store(
    records: list[SaleRecord], start: datetime.date, end: datetime.date
) -> dict[str, int]:
    """集計期間の店舗ごとの売上合計を返す。売上の無い店舗も 0 で含める。"""
    if start > end:
        raise ValueError("開始日が終了日より後です")
    totals = {name: 0 for name in list_store_names()}
    for record in records:
        if start <= record.sold_on <= end:
            totals[record.store] = totals.get(record.store, 0) + record.amount
    return totals
