#!/usr/bin/env python3
"""agenda_schema.py（TransitionRule・verification.action 固定語彙）のテスト。

DES-075 §5.1 の4条件（agenda:REQ-019 FNC-008/FNC-011/FNC-012）・
verification.action の固定語彙・不正な JSON 構造相当の入力の拒否を検証する
（TASK-001 acceptance_criteria）。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_schema -v
"""

import importlib.util
import sys
import unittest
from pathlib import Path

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "forge"
    / "scripts"
    / "agenda"
    / "agenda_schema.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_schema", _MODULE_PATH)
agenda_schema = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_schema"] = agenda_schema
_SPEC.loader.exec_module(agenda_schema)


def _valid_config(**overrides):
    config = {
        "identity": "20260819-agenda-design",
        "status_vocabulary": ["未着手", "進行中", "決着", "保留", "対象外", "取り下げ"],
        "terminal_statuses": ["決着", "対象外", "取り下げ"],
        "active_statuses": ["未着手", "進行中"],
        "item_fields": ["severity", "confidence"],
        "severity_field": "severity",
        "structural_judgment": {"recorded": True, "note": "同型の指摘は無い"},
    }
    config.update(overrides)
    return config


def _valid_item(**overrides):
    item = {
        "id": "01",
        "title": "テスト項目",
        "status": "進行中",
        "fields": {"severity": "critical", "confidence": "confirmed"},
        "background": "背景の記述",
        "essence": "本質の記述",
        "recommendation": "推奨の記述",
    }
    item.update(overrides)
    return item


class RequiredFieldsForTerminalTransitionTest(unittest.TestCase):
    """FNC-008: 終端状態遷移に background/essence 必須。"""

    def test_valid_item_has_no_missing_fields(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), "決着", _valid_config()
        )
        self.assertEqual(missing, [])

    def test_missing_background_is_reported(self):
        item = _valid_item(background="")
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("background", missing)

    def test_missing_essence_is_reported(self):
        item = _valid_item(essence="")
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("essence", missing)

    def test_background_key_absent_is_treated_as_missing(self):
        item = _valid_item()
        del item["background"]
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("background", missing)

    def test_non_terminal_transition_does_not_require_background_essence(self):
        item = _valid_item(background="", essence="")
        missing = agenda_schema.required_fields_for(item, "進行中", _valid_config())
        self.assertNotIn("background", missing)
        self.assertNotIn("essence", missing)


class RequiredFieldsForVerificationTest(unittest.TestCase):
    """FNC-011: 外部指摘由来項目は referenced 必須。action != adopt は reason 必須。"""

    def test_external_item_missing_referenced_is_reported(self):
        item = _valid_item(
            verification={"referenced": "", "action": "adopt", "reason": ""}
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("verification.referenced", missing)

    def test_external_item_with_referenced_and_adopt_needs_no_reason(self):
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "adopt",
                "reason": "",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertEqual(missing, [])

    def test_action_not_adopt_without_reason_is_reported(self):
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "reject",
                "reason": "",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("verification.reason", missing)

    def test_action_not_adopt_with_reason_is_satisfied(self):
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "reject",
                "reason": "採用しない理由",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertEqual(missing, [])

    def test_item_without_verification_key_is_not_external(self):
        item = _valid_item()
        self.assertNotIn("verification", item)
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertNotIn("verification.referenced", missing)
        self.assertNotIn("verification.reason", missing)

    def test_verification_referenced_required_regardless_of_action(self):
        # 採用する場合も検証を要求すること（FNC-011「指摘を認める方向へ倒すときこそ検証が要る」）
        item = _valid_item(
            verification={"referenced": "", "action": "adopt", "reason": "理由あり"}
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("verification.referenced", missing)


class RequiredFieldsForStructuralJudgmentTest(unittest.TestCase):
    """FNC-012: structural_judgment 未記録時は個別遷移拒否（target_status を問わない）。"""

    def test_unrecorded_structural_judgment_blocks_terminal_transition(self):
        config = _valid_config(structural_judgment={"recorded": False})
        missing = agenda_schema.required_fields_for(_valid_item(), "決着", config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_unrecorded_structural_judgment_blocks_non_terminal_transition(self):
        config = _valid_config(structural_judgment={"recorded": False})
        missing = agenda_schema.required_fields_for(_valid_item(), "進行中", config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_missing_structural_judgment_key_is_treated_as_unrecorded(self):
        config = _valid_config()
        del config["structural_judgment"]
        missing = agenda_schema.required_fields_for(_valid_item(), "進行中", config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_recorded_structural_judgment_does_not_block(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), "進行中", _valid_config()
        )
        self.assertNotIn("structural_judgment.recorded", missing)


class ValidateTest(unittest.TestCase):
    def test_valid_transition_returns_ok_true(self):
        result = agenda_schema.validate(_valid_item(), "決着", _valid_config())
        self.assertEqual(result, {"ok": True, "missing_fields": []})

    def test_invalid_transition_returns_ok_false_with_missing_fields(self):
        item = _valid_item(background="", essence="")
        result = agenda_schema.validate(item, "決着", _valid_config())
        self.assertFalse(result["ok"])
        self.assertIn("background", result["missing_fields"])
        self.assertIn("essence", result["missing_fields"])

    def test_validate_does_not_raise(self):
        try:
            agenda_schema.validate(_valid_item(), "決着", _valid_config())
        except Exception as exc:  # noqa: BLE001 - 例外を投げない契約自体の検証
            self.fail(f"validate() が例外を投げた: {exc}")


class VerificationActionVocabularyTest(unittest.TestCase):
    """verification.action の語彙が agenda_schema.py 内に固定定義され、
    呼び出し側から受け取らないこと。"""

    def test_vocabulary_is_fixed_to_adopt_and_reject(self):
        self.assertEqual(agenda_schema.VERIFICATION_ACTIONS, frozenset({"adopt", "reject"}))

    def test_vocabulary_is_not_read_from_config(self):
        # config に status_vocabulary 相当のキーで別の action 語彙を混入させても、
        # 判定はモジュール内の固定定数だけを見る（config からは受け取らない）。
        config = _valid_config(action_vocabulary=["approve", "deny"])
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "approve",
                "reason": "",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", config)
        # "approve" は固定語彙の adopt と一致しないため、reason が必須になる
        # （config 側にどう書かれていても固定語彙の判定は変わらない）。
        self.assertIn("verification.reason", missing)

    def test_action_outside_fixed_vocabulary_is_reported_as_missing(self):
        # 固定語彙（adopt/reject）に属さない値は、verification.action 自体が
        # 不足として報告される（VERIFICATION_ACTIONS を実際に検証対象にする）。
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "approve",
                "reason": "理由あり",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("verification.action", missing)

    def test_action_within_fixed_vocabulary_is_not_reported_as_missing(self):
        item = _valid_item(
            verification={
                "referenced": "plugins/x.py:1-2",
                "action": "reject",
                "reason": "理由あり",
            }
        )
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertNotIn("verification.action", missing)


class MalformedInputRejectionTest(unittest.TestCase):
    """不正な JSON 構造相当の入力の拒否（DES-075 §9）。"""

    def test_item_not_a_dict_is_treated_as_missing_everything(self):
        missing = agenda_schema.required_fields_for("not-a-dict", "決着", _valid_config())
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_config_not_a_dict_is_treated_as_potentially_terminal_and_unrecorded(self):
        # config 自体が不正な場合も、終端判定を「終端ではない」と楽観視しない
        # （NFR-006: 既定値で補って進行しない）。
        item = _valid_item(background="", essence="")
        missing = agenda_schema.required_fields_for(item, "決着", "not-a-dict")
        self.assertIn("background", missing)
        self.assertIn("essence", missing)
        # structural_judgment も得られないため未記録として拒否される
        self.assertIn("structural_judgment.recorded", missing)

    def test_terminal_statuses_malformed_is_treated_as_potentially_terminal(self):
        # terminal_statuses の型が不正で終端かどうか判定できない場合、
        # 「終端ではない」と楽観視せず background/essence の要求を維持する
        # （NFR-006: 既定値で補って進行しない）。
        config = _valid_config(terminal_statuses="決着")
        item = _valid_item(background="", essence="")
        missing = agenda_schema.required_fields_for(item, "決着", config)
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_verification_wrong_type_is_treated_as_malformed_external_item(self):
        # verification キーが存在するが型が不正な場合、内容を検証できないため
        # 全項目を不足として扱う（NFR-006: 既定値で補って進行しない）。
        item = _valid_item(verification="not-a-dict")
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("verification.referenced", missing)
        self.assertIn("verification.reason", missing)
        self.assertIn("verification.action", missing)

    def test_background_wrong_type_is_treated_as_missing(self):
        item = _valid_item(background=123)
        missing = agenda_schema.required_fields_for(item, "決着", _valid_config())
        self.assertIn("background", missing)

    def test_validate_on_malformed_input_returns_ok_false_without_raising(self):
        result = agenda_schema.validate("not-a-dict", "決着", "also-not-a-dict")
        self.assertFalse(result["ok"])
        self.assertTrue(result["missing_fields"])


if __name__ == "__main__":
    unittest.main()
