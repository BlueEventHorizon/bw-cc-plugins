#!/usr/bin/env python3
"""参照切れのうち、索引で移動先が決まるものを置換する（REQ-023 FNC-011 の報告を入力とする）。

**置換先も完全一致で導く。探索しない**（DES-081 §3.3.1）。索引が完全一致で答えられる類型は
1 つだけである。

| 種別              | 索引が完全一致で答えるもの             | 決まるか            |
| ----------------- | -------------------------------------- | ------------------- |
| `moved_link`      | `names`（ファイル名 → 実在パス一覧）   | 候補 1 件なら決まる |
| `missing_anchor`  | 見出し集合（完全一致は既に外れている） | 決まらない          |
| `missing_section` | 現在の節番号（旧→新の対応は無い）      | 決まらない          |

`missing_anchor` と `missing_section` を決めないのは、**書かれたキーが索引に完全一致しなかった
という事実そのものが所見だから**である。索引に無いキーは「無い」で終端する（§3.3.1）。そこから
別のキーを探すのは推定であり、当たっても正しさの根拠を持たない。

**同名の衝突は対応範囲外である。** 同じ文書 ID が複数パスに現れた場合、`build_code_index()`
が索引の構築時点で `ambiguous` へ落とすため、ここへは届かない（DES-081 §3.3a）。
"""

from __future__ import annotations

import posixpath

#: 移動先が索引で決まる唯一の種別
DETERMINABLE_KINDS = ("moved_link",)


def determine_moved_link(referrer: str, ref: str, candidates) -> str | None:
    """`moved_link` の新しい destination を返す。決まらなければ `None`。

    Args:
        referrer: 参照を書いているファイルのパス（プロジェクトルート基準）
        ref: 書かれた destination（アンカーを含みうる）
        candidates: `names` 索引が返した、同じ basename を持つ実在パスの一覧

    **候補が 1 件でなければ決めない。** 2 件以上あるとき、どれが正しいかは参照元の意図に
    依存し、決定論的に決まらない（NFR-001）。0 件は名前ごと実在しない状態（`broken_link`）
    であり、移動ではない。

    **位置指定は保存する。** アンカーは参照元が何を指したいかの表明であり、パスの修正で
    落としてよいものではない。
    """
    if len(candidates) != 1:
        return None
    target, sep, anchor = ref.partition("#")
    new_path = posixpath.relpath(candidates[0], posixpath.dirname(referrer))
    return new_path + sep + anchor


def determine_rewrite(finding: dict, *, slugs=None) -> dict | None:
    """所見 1 件に対する書き換えを返す。決まらなければ `None`。

    置換先を返すのは `moved_link` だけである。`slugs` 引数は呼び出し側が材料を
    渡せるようにする口であり、渡されても置換先は返さない。

    `missing_anchor` を決めないのは、見出し索引を完全一致で引くためである
    （DES-081 §3.3.1）。`missing_anchor` は**その完全一致が外れた**という所見であり、
    書かれた文字列はその時点でキーではない。キーでないものを起点に別のキーを探すことは
    推定であり、当たっても正しさの根拠を持たない。所見が運ぶ `slugs` は利用者へ候補を
    示すための材料であって、置換の根拠ではない。

    `missing_section` を決めないのは、索引が現在の節番号しか持たず、旧番号から現番号への
    対応を保持しないためである。対応を知っているのは節を動かした当人だけである
    （REQ-023 FNC-008）。

    **置換対象は `ref` ではなく `dest` である。** `ref` は利用者へ見せる表示であり、
    参照定義行（`[label]: dest`）ではラベルを含む行全体になる。これを置換対象に
    すると定義行からラベルが消え、その文書の `[表示][label]` がすべて参照先を失う。
    `dest` を持たない所見（手書き・旧形式）では `ref` へ退避する。

    Returns:
        dict: `file` / `line` / `old`（書かれた参照先）/ `new`（置換後）
    """
    if finding.get("kind") != "moved_link":
        return None
    old = finding.get("dest", finding["ref"])
    new = determine_moved_link(
        finding["file"], old, finding.get("candidates") or []
    )
    if new is None or new == old:
        return None
    return {
        "file": finding["file"],
        "line": finding["line"],
        "old": old,
        "new": new,
    }
