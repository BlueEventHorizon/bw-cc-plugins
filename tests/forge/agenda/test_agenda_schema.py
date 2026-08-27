#!/usr/bin/env python3
"""agenda_schema.py（decision トリガー方式の状態遷移契約）のテスト。

DES-075 §5.1 の判定条件（agenda:REQ-019 FNC-008/FNC-012）・
不正な JSON 構造相当の入力の拒否を検証する（TASK-009 acceptance_criteria）。

`required_fields_for(item, patch_keys, config)`/`validate(item, patch_keys, config)`
の新シグネチャを対象とする。旧シグネチャ（`target_status` を第2引数に取る／
`status_vocabulary`・`terminal_statuses`・`active_statuses` を含む config）への
言及は行わない（DES-075 §3.2「状態語彙は持たない」）。

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
        "item_fields": ["severity"],
        "severity_field": "severity",
        "structural_judgment": {"recorded": True, "note": "同型の指摘は無い"},
    }
    config.update(overrides)
    return config


def _valid_item(**overrides):
    item = {
        "id": "01",
        "title": "テスト項目",
        "fields": {"severity": "critical"},
        "background": "背景の記述",
        "essence": "本質の記述",
        "decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"},
        "last_changed_fields": ["decision"],
    }
    item.update(overrides)
    return item


class DecisionTriggerTest(unittest.TestCase):
    """判定のトリガーは patch_keys に "decision" を含むかどうかだけである（DES-075 §5.1）。"""

    def test_patch_without_decision_returns_no_missing(self):
        # background のみのパッチでは、background/essence/decision.* 等いずれの
        # 非空チェックも課さない（既に background/essence が空でも通る）。
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, {"background"}, _valid_config())
        self.assertEqual(missing, [])

    def test_patch_with_decision_triggers_full_validation(self):
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_patch_keys_accepts_list_and_tuple_and_frozenset(self):
        item = _valid_item()
        for patch_keys in (["decision"], ("decision",), frozenset({"decision"})):
            with self.subTest(patch_keys=patch_keys):
                missing = agenda_schema.required_fields_for(item, patch_keys, _valid_config())
                self.assertEqual(missing, [])

    def test_unexpected_patch_keys_type_fails_closed_as_triggered(self):
        # patch_keys が set/list/tuple/frozenset のいずれでもない場合、
        # 検証を素通りさせず「含む」側に倒す（NFR-006 と同じ fail-closed 方針）。
        item = _valid_item(background="", essence="", decision=None)
        for bogus in (None, "decision", 123):
            with self.subTest(patch_keys=bogus):
                missing = agenda_schema.required_fields_for(item, bogus, _valid_config())
                self.assertIn("background", missing)


class RequiredFieldsForDecisionTest(unittest.TestCase):
    """FNC-008: decision トリガー時に background/essence/decision.* が必須。"""

    def test_valid_item_has_no_missing_fields(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"decision"}, _valid_config()
        )
        self.assertEqual(missing, [])

    def test_missing_background_is_reported(self):
        item = _valid_item(background="")
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("background", missing)

    def test_missing_essence_is_reported(self):
        item = _valid_item(essence="")
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("essence", missing)

    def test_background_key_absent_is_treated_as_missing(self):
        item = _valid_item()
        del item["background"]
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("background", missing)

    def test_decision_key_absent_reports_all_decision_subfields(self):
        item = _valid_item()
        del item["decision"]
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("decision.by", missing)
        self.assertIn("decision.outcome", missing)
        self.assertIn("decision.reason", missing)

    def test_decision_none_reports_all_decision_subfields(self):
        item = _valid_item(decision=None)
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("decision.by", missing)
        self.assertIn("decision.outcome", missing)
        self.assertIn("decision.reason", missing)

    def test_decision_missing_by_is_reported(self):
        item = _valid_item(decision={"outcome": "adopt", "reason": "妥当"})
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("decision.by", missing)

    def test_decision_missing_outcome_is_reported(self):
        item = _valid_item(decision={"by": "human", "reason": "妥当"})
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("decision.outcome", missing)

    def test_decision_missing_reason_is_reported(self):
        item = _valid_item(decision={"by": "human", "outcome": "adopt"})
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("decision.reason", missing)


class RequiredFieldsForStructuralJudgmentTest(unittest.TestCase):
    """FNC-012: decision トリガー時、structural_judgment.recorded が True でなければ拒否する。

    本モジュールの実装は DES-075 §5.1表「個別項目への遷移全般」を decision トリガーと
    同一視する（agenda_schema.py 冒頭 docstring）。decision を含まないパッチでは
    structural_judgment の状態そのものを判定しない。
    """

    def test_unrecorded_structural_judgment_blocks_decision_transition(self):
        config = _valid_config(structural_judgment={"recorded": False})
        missing = agenda_schema.required_fields_for(_valid_item(), {"decision"}, config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_missing_structural_judgment_key_is_treated_as_unrecorded(self):
        config = _valid_config()
        del config["structural_judgment"]
        missing = agenda_schema.required_fields_for(_valid_item(), {"decision"}, config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_recorded_structural_judgment_does_not_block(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"decision"}, _valid_config()
        )
        self.assertNotIn("structural_judgment.recorded", missing)

    def test_non_decision_patch_does_not_check_structural_judgment(self):
        # decision を含まない呼び出しでは structural_judgment.recorded が
        # False でも missing に含めない（トリガー判定自体が入口のため）。
        config = _valid_config(structural_judgment={"recorded": False})
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, {"background"}, config)
        self.assertEqual(missing, [])


class ValidateTest(unittest.TestCase):
    def test_valid_transition_returns_ok_true(self):
        result = agenda_schema.validate(_valid_item(), {"decision"}, _valid_config())
        self.assertEqual(result, {"ok": True, "missing_fields": []})

    def test_invalid_transition_returns_ok_false_with_missing_fields(self):
        item = _valid_item(background="", essence="")
        result = agenda_schema.validate(item, {"decision"}, _valid_config())
        self.assertFalse(result["ok"])
        self.assertIn("background", result["missing_fields"])
        self.assertIn("essence", result["missing_fields"])

    def test_validate_does_not_raise(self):
        try:
            agenda_schema.validate(_valid_item(), {"decision"}, _valid_config())
        except Exception as exc:  # noqa: BLE001 - 例外を投げない契約自体の検証
            self.fail(f"validate() が例外を投げた: {exc}")


class MalformedInputRejectionTest(unittest.TestCase):
    """不正な JSON 構造相当の入力の拒否（DES-075 §9・agenda:REQ-019 NFR-006）。"""

    def test_item_not_a_dict_is_treated_as_missing_everything(self):
        missing = agenda_schema.required_fields_for("not-a-dict", {"decision"}, _valid_config())
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_config_not_a_dict_is_treated_as_unrecorded(self):
        item = _valid_item(background="", essence="")
        missing = agenda_schema.required_fields_for(item, {"decision"}, "not-a-dict")
        self.assertIn("background", missing)
        self.assertIn("essence", missing)
        self.assertIn("structural_judgment.recorded", missing)

    def test_background_wrong_type_is_treated_as_missing(self):
        item = _valid_item(background=123)
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("background", missing)

    def test_validate_on_malformed_input_returns_ok_false_without_raising(self):
        result = agenda_schema.validate("not-a-dict", {"decision"}, "also-not-a-dict")
        self.assertFalse(result["ok"])
        self.assertTrue(result["missing_fields"])


if __name__ == "__main__":
    unittest.main()
