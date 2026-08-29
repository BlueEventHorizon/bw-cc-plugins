#!/usr/bin/env python3
"""agenda 機構のスキーマ定義・状態遷移契約モジュール。

`plan_contract.py` と同型の「関数＋契約」構成（DES-075 §3.2 の注記どおり、
UML クラス（`TransitionRule`）をそのまま class 化しない）。状態遷移の必要条件
（DES-075 §5.1、agenda:REQ-019 FNC-008/FNC-012）を機械可読な定義として持ち、
不足フィールド名を列挙する判定結果を返す。

**状態語彙は持たない（DES-075 §3.2・§4「状態の表現」）**。`status_vocabulary`/
`terminal_statuses`/`active_statuses`/`target_status`/`is_terminal` 判定は
本モジュールに存在しない。判定のトリガーは「今回の `record` 呼び出しが渡した
差分パッチのキー集合（`patch_keys`）に `decision` を含むかどうか」だけであり、
遷移先の値そのものは解釈しない（DES-075 §5.1）。

`patch_keys` 引数について: 呼び出し側（`agenda_store.py`）が渡すのは、今回の
`record` 呼び出しで実際に渡されたトップレベルキーの集合のうち**項目パッチ側**
のものだけである。`structural_judgment` はレコード直下へのパッチでありこの
集合に含まれない（DES-075 §6.1）。

`item` 引数について: `decision` トリガー成立時の必須フィールド判定は、今回の
差分パッチ単独ではなく、`upsert_item()` が既存項目へ差分パッチを適用した後の
**項目全体**に対して行う（DES-075 §5.1本文）。呼び出し側はマージ後の項目を渡す。

`config` 引数について: 呼び出し側（`agenda_store.py`）は、`AgendaRecord.config`
に加え、`AgendaRecord.structural_judgment`（DES-075 §3.2・§4）を 1 フィールドとして
合わせた dict をこの引数へ渡す。個別項目への遷移可否の判定は record 全体の
構造判定状態（FNC-012）に依存するため、`item`（項目単位のデータ）ではなく
record レベルの状態を保持する `config` 側にこの情報を含める。
"""

from __future__ import annotations


def _non_empty(value) -> bool:
    """値が「空でない」文字列といえるかどうかを判定する。

    文字列以外（None・数値・想定外の型）は空とみなす。呼び出し側が不正な型を
    渡した場合もクラッシュせず「不足」として扱う（不正な JSON 構造の拒否）。
    """
    return isinstance(value, str) and value.strip() != ""


def _decision_triggered(patch_keys) -> bool:
    """`patch_keys` に `decision` を含むかどうかを判定する。

    `patch_keys` が `set`/`list`/`tuple`/`frozenset` のいずれでもない場合
    （呼び出し側の不正な型混入）は、含む/含まないを判定できない。楽観的に
    「含まない」とみなして検証を素通りさせると FNC-008 の必須フィールド検証を
    丸ごと迂回できてしまうため、判定不能な場合は「含む」側（検証を課す側）に
    倒す（NFR-006「既定値で補って進行しない」と同じ fail-closed 方針）。
    """
    if isinstance(patch_keys, (set, frozenset)):
        return "decision" in patch_keys
    if isinstance(patch_keys, (list, tuple)):
        return "decision" in patch_keys
    return True


def required_fields_for(item, patch_keys, config) -> list:
    """今回の `record` 呼び出しに必要なフィールドのうち、不足しているものを返す。

    DES-075 §5.1 の判定条件（agenda:REQ-019 FNC-008/FNC-012）を順に判定する。

    1. `patch_keys` に `decision` を含む（＝決着させる `record` 呼び出し）場合、
       `background`・`essence`・`decision.by`・`decision.outcome`・`decision.reason`
       が空でないことを要求する（FNC-008）
    2. 個別項目への遷移全般（＝`decision` を含む呼び出し。DES-075 §5.1表の
       「個別項目への遷移全般」は本モジュールの実装上 `decision` トリガーと
       同じ呼び出しを指す）で、`structural_judgment.recorded` が `True`
       であることを要求する（FNC-012）

    `patch_keys` に `decision` を含まない呼び出し（`background`/`essence` のみ等）
    では、上記のいずれの非空チェックも課さない（空リストを返す）。

    `item` / `config` が dict でない場合や、期待するキーの型が異なる場合も
    クラッシュせず、該当フィールドを不足として扱う（不正な JSON 構造の拒否）。
    """
    if not isinstance(item, dict):
        item = {}
    if not isinstance(config, dict):
        config = {}

    missing: list = []

    if not _decision_triggered(patch_keys):
        return missing

    if not _non_empty(item.get("background")):
        missing.append("background")
    if not _non_empty(item.get("essence")):
        missing.append("essence")

    decision = item.get("decision")
    if isinstance(decision, dict):
        if not _non_empty(decision.get("by")):
            missing.append("decision.by")
        if not _non_empty(decision.get("outcome")):
            missing.append("decision.outcome")
        if not _non_empty(decision.get("reason")):
            missing.append("decision.reason")
    else:
        missing.append("decision.by")
        missing.append("decision.outcome")
        missing.append("decision.reason")

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
