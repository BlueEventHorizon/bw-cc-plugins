#!/usr/bin/env python3
"""agenda 機構のスキーマ定義・状態遷移契約モジュール。

`plan_contract.py` と同型の「関数＋契約」構成（DES-075 §3.2 の注記どおり、
UML クラス（`TransitionRule`）をそのまま class 化しない）。状態遷移の必要条件
（DES-075 §5.1、agenda:REQ-019 FNC-008/FNC-011/FNC-012）を機械可読な定義として持ち、
不足フィールド名を列挙する判定結果を返す。

`config` 引数について: 呼び出し側（`agenda_store.py`）は、`AgendaRecord.config`
（DES-075 §4 の `terminal_statuses`/`active_statuses` 等）に加え、
`AgendaRecord.structural_judgment`（DES-075 §3.2・§4）を 1 フィールドとして
合わせた dict をこの引数へ渡す。個別項目への遷移可否の判定は record 全体の
構造判定状態（FNC-012）に依存するため、`item`（項目単位のデータ）ではなく
record レベルの状態を保持する `config` 側にこの情報を含める。
"""

from __future__ import annotations

#: 検証記録（`items[].verification`）の採否を表す固定語彙（agenda:REQ-019 FNC-011、
#: DES-075 §4・§5.1）。呼び出し側（consult）が自由に定義する `status_vocabulary`
#: とは独立した、agenda 機構固有のスキーマである。呼び出し側（config・引数）から
#: 受け取らず、本モジュール内の定数として固定する（FNC-009 の中立性の対象外）。
VERIFICATION_ACTIONS = frozenset({"adopt", "reject"})

#: `VERIFICATION_ACTIONS` のうち、`reason` の追加記入を要求しない唯一の値。
VERIFICATION_ACTION_ADOPT = "adopt"


def _non_empty(value) -> bool:
    """値が「空でない」文字列といえるかどうかを判定する。

    文字列以外（None・数値・想定外の型）は空とみなす。呼び出し側が不正な型を
    渡した場合もクラッシュせず「不足」として扱う（不正な JSON 構造の拒否）。
    """
    return isinstance(value, str) and value.strip() != ""


def required_fields_for(item, target_status, config) -> list:
    """`target_status` への遷移に必要なフィールドのうち、不足しているものを返す。

    DES-075 §5.1 の4条件（agenda:REQ-019 FNC-008/FNC-011/FNC-012）を順に判定する。

    1. `config.terminal_statuses` に `target_status` が含まれる場合、
       `background`・`essence` が空でないことを要求する（FNC-008）
    2. 上記かつ `item` が `verification` キー（dict）を持つ場合、
       `verification.referenced` が空でないことを追加で要求する（FNC-011）
    3. 上記かつ `verification.action` が `adopt` でない場合、
       `verification.reason` が空でないことを追加で要求する（FNC-011）
    4. 個別項目への遷移全般（`target_status` を問わない）で、
       `structural_judgment.recorded` が `True` であることを要求する（FNC-012）

    `item` / `config` が dict でない場合や、期待するキーの型が異なる場合も
    クラッシュせず、該当フィールドを不足として扱う（不正な JSON 構造の拒否）。
    型が不正で終端遷移かどうか判定できない場合は「終端ではない」と楽観視せず、
    判定不能を終端側とみなして要求を維持する（NFR-006「既定値で補って進行しない」）。
    同様に `verification` キーが存在するが型が不正な場合も、内容を検証できないため
    全項目を不足として扱う。

    `config.terminal_statuses` は役割マッピングとして参照するのみで、
    状態語彙そのものの意味（`"決着"` が何を意味するか等）には立ち入らない
    （FNC-009 の中立性）。
    """
    if not isinstance(item, dict):
        item = {}
    if not isinstance(config, dict):
        config = {}

    missing: list = []

    terminal_statuses = config.get("terminal_statuses")
    terminal_statuses_malformed = not isinstance(terminal_statuses, list)
    if terminal_statuses_malformed:
        terminal_statuses = []

    is_terminal = terminal_statuses_malformed or (target_status in terminal_statuses)

    if is_terminal:
        if not _non_empty(item.get("background")):
            missing.append("background")
        if not _non_empty(item.get("essence")):
            missing.append("essence")

        if "verification" in item:
            verification = item.get("verification")
            if isinstance(verification, dict):
                action = verification.get("action")
                if action not in VERIFICATION_ACTIONS:
                    missing.append("verification.action")

                if not _non_empty(verification.get("referenced")):
                    missing.append("verification.referenced")

                if action != VERIFICATION_ACTION_ADOPT:
                    if not _non_empty(verification.get("reason")):
                        missing.append("verification.reason")
            else:
                missing.append("verification.action")
                missing.append("verification.referenced")
                missing.append("verification.reason")

    structural_judgment = config.get("structural_judgment")
    recorded = (
        isinstance(structural_judgment, dict)
        and structural_judgment.get("recorded") is True
    )
    if not recorded:
        missing.append("structural_judgment.recorded")

    return missing


def validate(item, target_status, config) -> dict:
    """`required_fields_for()` の結果を `TransitionResult` 形式にまとめて返す。

    例外を投げず判定結果の dict（`{"ok": bool, "missing_fields": [...]}`）を返す
    （DES-075 §5.1・`TransitionRule.validate()` の契約）。呼び出し側（consult）は
    この dict をそのまま利用者・コンソールへ提示できる。
    """
    missing_fields = required_fields_for(item, target_status, config)
    return {"ok": not missing_fields, "missing_fields": missing_fields}
