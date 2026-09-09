#!/usr/bin/env python3
"""参照切れのうち、索引で移動先が決まるものを置換する（REQ-023 FNC-011 の報告を入力とする）。

**決まるものだけを直す。** 索引が移動先を答えられる類型は 1 つだけである。

| 種別              | 索引が持つもの                     | 決まるか            |
| ----------------- | ---------------------------------- | ------------------- |
| `moved_link`      | `names`（basename → 実在パス一覧） | 候補 1 件なら決まる |
| `missing_section` | 現在の節番号だけ（旧→新の対応なし）| 決まらない          |

`missing_section` を決めないのは、旧節番号から現節番号への対応をどの索引も保持しないためで
ある。番号の近さや残った節の数を根拠に張り替えると、参照は解決するのに指し先が誤っている
状態——検査が「正しい」と保証する嘘——になる。参照切れは壊れていることが見える状態だが、
誤った先へ張り替えた参照は正しく見える。後者のほうが有害である。

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


def determine_anchor(anchor: str, slugs) -> str | None:
    """`missing_anchor` の新しいアンカーを返す。決まらなければ `None`。

    見出しの末尾が変わって（タグの付加等）アンカーが解決しなくなった場合、書かれた
    アンカーは真の slug の**前方一致**になる。区切り（`-`）を伴う前方一致が 1 件だけの
    ときに限り決まる。

    区切りを要求するのは、語の途中までの一致（`design` に対する `designer`）を移動と
    見なさないためである。完全一致は所見にならないため、渡された場合も書き換えない。
    """
    if anchor in slugs:
        return None
    prefix = anchor + "-"
    matched = [s for s in slugs if s.startswith(prefix)]
    return matched[0] if len(matched) == 1 else None


def determine_section(ref: str, sections) -> None:
    """節参照は決めない。常に `None` を返す。

    索引は現在の節番号しか持たず、旧番号から現番号への対応を保持しない。対応を知って
    いるのは節を動かした当人だけである（REQ-023 FNC-008）。本関数が存在するのは、
    「決めない」ことを呼び出し側から明示的に参照できるようにするためである。
    """
    return None


def determine_rewrite(finding: dict, *, slugs=None) -> dict | None:
    """所見 1 件に対する書き換えを返す。決まらなければ `None`。

    Returns:
        dict: `file` / `line` / `old`（書かれた参照）/ `new`（置換後）
    """
    kind = finding.get("kind")
    if kind == "moved_link":
        new = determine_moved_link(
            finding["file"], finding["ref"], finding.get("candidates") or []
        )
    elif kind == "missing_anchor" and slugs is not None:
        _, sep, anchor = finding["ref"].partition("#")
        if not sep:
            return None
        new_anchor = determine_anchor(anchor, slugs)
        new = None if new_anchor is None else finding["ref"].replace(
            sep + anchor, sep + new_anchor
        )
    else:
        return None
    if new is None or new == finding["ref"]:
        return None
    return {
        "file": finding["file"],
        "line": finding["line"],
        "old": finding["ref"],
        "new": new,
    }
