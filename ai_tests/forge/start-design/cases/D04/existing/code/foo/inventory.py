"""Foo 在庫管理の在庫台帳。"""

from foo.storage import load_stock, save_stock


class StockShortage(Exception):
    """在庫数が足りない。"""


def update_stock(item_code: str, delta: int) -> int:
    """品目の在庫数を増減し、更新後の在庫数を返す。足りなければ StockShortage を送出する。"""
    stock = load_stock()
    current = stock[item_code]
    if current + delta < 0:
        raise StockShortage(item_code)
    stock[item_code] = current + delta
    save_stock(stock)
    return stock[item_code]
