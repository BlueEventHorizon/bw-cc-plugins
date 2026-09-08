#!/usr/bin/env python3
"""agenda 機構のスキーマ定義・受理条件モジュール。

`plan_contract.py` と同型の「関数＋契約」構成（DES-075 §3.2 の注記どおり、
UML クラス（`TransitionRule`）をそのまま class 化しない）。項目へ値を加える
呼び出しの受理条件（DES-075 §5.1 の表。agenda:REQ-019 FNC-008/FNC-012）と
決着（`decision` の 3 値そろい）の定義を機械可読な形で持ち、不足フィールド名を
列挙する判定結果を返す。

**状態語彙は持たない（DES-075 §3.2・§4「状態の表現」）**。`status_vocabulary`/
`terminal_statuses`/`active_statuses`/`target_status`/`is_terminal` 判定は
本モジュールに存在しない。

受理条件（DES-075 §5.1）:

| 呼び出し                            | 受理の条件                                                      |
| ----------------------------------- | --------------------------------------------------------------- |
| 項目へ値を加える（どの値でも）      | 構造判断が記録済みであること（FNC-012）                         |
| `decision.*` のいずれかを加える     | 上に加えて `background` と `essence` が空でないこと（FNC-008）  |
| 決着として扱う（残件の計算・終了）  | `decision` の 3 値がすべて空でないこと（`is_settled()`）        |

`decision` の 3 値は 1 つずつ加えるため、`decision.*` を加える呼び出しでは
`outcome`/`reason` の未記入を不足として返さない（揃うまでの間は部分的な
`decision` が保存され、未決着として扱われる）。

`patch_keys` 引数について: 呼び出し側（`agenda_store.py`）が渡すのは、今回の
`record` 呼び出しで実際に渡された**項目パッチ側**の名前の集合である。名前は
ドット区切りの入れ子表記（`decision.by` 等）で渡る（DES-075 §6.1）。
`structural_judgment` はレコード直下へのパッチでありこの集合に含まれない
（DES-075 §6.1）。集合が空の呼び出し（構造判断だけを記す `record`）は項目へ
値を加えないため、いずれの条件も課さない。

`item` 引数について: 必須フィールドの非空判定は、今回の差分パッチ単独ではなく、
`upsert_item()` が既存項目へ差分パッチを適用した後の**項目全体**に対して行う
（DES-075 §5.1本文）。呼び出し側はマージ後の項目を渡す。

`config` 引数について: 呼び出し側（`agenda_store.py`）は、`AgendaRecord.config`
に加え、`AgendaRecord.structural_judgment`（DES-075 §3.2・§4）を 1 フィールドとして
合わせた dict をこの引数へ渡す。項目へ値を加えてよいかの判定は record 全体の
構造判断の状態（FNC-012）に依存するため、`item`（項目単位のデータ）ではなく
record レベルの状態を保持する `config` 側にこの情報を含める。
"""

from __future__ import annotations

_DECISION_FIELDS = ("by", "outcome", "reason")


def is_non_empty(value) -> bool:
    """値が「空でない」文字列といえるかどうかを判定する。

    文字列以外（None・数値・想定外の型）は空とみなす。呼び出し側が不正な型を
    渡した場合もクラッシュせず「不足」として扱う（不正な JSON 構造の拒否）。

    構造判断の記述が非空であることを求める側（`agenda_store`）も同じ規則で
    判定する必要があるため公開している（判定が割れると、記録側で受理された値が
    受理条件の側では空と見なされる）。
    """
    return isinstance(value, str) and value.strip() != ""



def _patch_key_names(patch_keys):
    """`patch_keys` を名前の列として取り出す。判定不能なら `None` を返す。

    `set`/`frozenset`/`list`/`tuple` 以外（呼び出し側の不正な型混入）は、
    どの名前が渡されたのかを判定できない。楽観的に「何も渡されていない」と
    みなして検証を素通りさせると FNC-008/FNC-012 の受理条件を丸ごと迂回できて
    しまうため、判定不能を呼び出し元へ返し、検証を課す側へ倒す
    （NFR-006「既定値で補って進行しない」と同じ fail-closed 方針）。
    """
    if isinstance(patch_keys, (set, frozenset, list, tuple)):
        return [key for key in patch_keys if isinstance(key, str)]
    return None


def _is_decision_key(name: str) -> bool:
    """名前が `decision` の値を指すかどうかを判定する。

    入れ子表記（`decision.by` 等）に加え、`decision` そのものも decision を
    加える呼び出しとして扱う（fail-closed。`decision` を名前として受け付けない
    のは `agenda_store.py` 側の規則（DES-075 §6.1）であり、仮に届いた場合に
    FNC-008 の検証を素通りさせない）。
    """
    return name == "decision" or name.startswith("decision.")


def is_settled(item) -> bool:
    """項目が決着しているか（`decision` の 3 値がすべて非空か）を判定する。

    DES-075 §5.1 が定める決着の述語（`is_settled()`）。`decision.by`/
    `decision.outcome`/`decision.reason` の 3 つがすべて非空の文字列のときだけ
    真を返す。2 値までしか揃っていない・空文字・`None`・`decision` が dict で
    ない場合はいずれも偽である（部分的な `decision` は未決着として扱う）。

    残件の列挙・`next`・`finish` の判定は、記録側と提示側で食い違わせないため
    この述語を単一の定義として参照する。
    """
    if not isinstance(item, dict):
        return False
    decision = item.get("decision")
    if not isinstance(decision, dict):
        return False
    return all(is_non_empty(decision.get(field)) for field in _DECISION_FIELDS)


def required_fields_for(item, patch_keys, config) -> list:
    """今回の `record` 呼び出しに必要なフィールドのうち、不足しているものを返す。

    DES-075 §5.1 の受理条件（agenda:REQ-019 FNC-008/FNC-012）を判定する。

    1. 項目へ値を加える呼び出し（`patch_keys` が空でない）では、
       `structural_judgment.recorded` が `True` であることを要求する（FNC-012）。
       加える値の種類は問わない
    2. そのうち `decision.*` を含む呼び出しでは、加えて項目全体の `background`・
       `essence` が空でないことを要求する（FNC-008）。`decision` の 3 値は 1 つ
       ずつ積まれるため、未記入の残りの値を不足として返さない

    項目へ値を加えない呼び出し（`patch_keys` が空。構造判断だけを記す `record`）
    では、いずれの条件も課さない（空リストを返す）。

    `item` / `config` が dict でない場合や、期待するキーの型が異なる場合も
    クラッシュせず、該当フィールドを不足として扱う（不正な JSON 構造の拒否）。
    """
    if not isinstance(item, dict):
        item = {}
    if not isinstance(config, dict):
        config = {}

    missing: list = []

    names = _patch_key_names(patch_keys)
    if names is None:
        # 判定不能: 値を加える呼び出しであり、かつ decision を含むものとして扱う
        adds_value = True
        decision_triggered = True
    else:
        adds_value = bool(names)
        decision_triggered = any(_is_decision_key(name) for name in names)

    if not adds_value:
        return missing

    if decision_triggered:
        if not is_non_empty(item.get("background")):
            missing.append("background")
        if not is_non_empty(item.get("essence")):
            missing.append("essence")

    structural_judgment = config.get("structural_judgment")
    recorded = (
        isinstance(structural_judgment, dict)
        and structural_judgment.get("recorded") is True
    )
    if not recorded:
        missing.append("structural_judgment.recorded")

    return missing


def validate(item, patch_keys, config) -> dict:
    """`required_fields_for()` の結果を `{"ok": bool, "missing_fields": [...]}`
    形式にまとめて返す。

    例外を投げず判定結果の dict を返す（DES-075 §5.1）。呼び出し側（consult）は
    この dict をそのまま利用者・コンソールへ提示できる。
    """
    missing_fields = required_fields_for(item, patch_keys, config)
    return {"ok": not missing_fields, "missing_fields": missing_fields}
