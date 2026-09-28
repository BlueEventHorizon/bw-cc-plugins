#!/usr/bin/env python3
"""agenda_schema.py（DES-075 §5.1 の受理条件・決着の定義）のテスト。

検証する観点（DES-075 §9「`agenda_schema.py`」）:

- 構造判断が未記録の間は、項目へ値を加えるすべてのパッチが拒否されること
  （決着に限らない。agenda:REQ-019 FNC-012）
- `decision.*` を加えるパッチは `background`・`essence` の非空だけを要求し、
  残りの `decision` の値の未記入を不足として返さないこと（FNC-008）
- 決着（3 値そろい）の述語が、3 値すべて非空のときだけ真を返すこと
- 上記が不足フィールド名の列挙として返ること・不正な JSON 構造相当の入力を
  拒否すること（NFR-006）

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
        "identity": "review",
        "item_fields": [],
        "severity_field": "severity",
        "structural_judgment": {"recorded": True, "note": "同型の指摘は無い"},
    }
    config.update(overrides)
    return config


def _unrecorded_config(**overrides):
    return _valid_config(structural_judgment={"recorded": False, "note": None}, **overrides)


def _valid_item(**overrides):
    item = {
        "id": "01",
        "title": "テスト項目",
        "severity": "critical",
        "problem": "所見の本文",
        "background": "背景の記述",
        "essence": "本質の記述",
        "decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"},
        "last_changed_fields": ["decision.reason"],
    }
    item.update(overrides)
    return item


class StructuralJudgmentGateTest(unittest.TestCase):
    """FNC-012: 構造判断が記録されるまで、項目へ値を加えるパッチをすべて拒否する。"""

    def test_background_only_patch_is_blocked_while_unrecorded(self):
        # 受け入れ基準 1: decision を含まないパッチでも構造判断の未記録が不足になる。
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(
            item, {"background"}, _unrecorded_config()
        )
        self.assertIn("structural_judgment.recorded", missing)

    def test_unknown_field_patch_is_blocked_while_unrecorded(self):
        # 「どの値でも」: agenda が意味を知らない名前のパッチでも同じ条件が課される。
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"impact"}, _unrecorded_config()
        )
        self.assertIn("structural_judgment.recorded", missing)

    def test_decision_patch_is_blocked_while_unrecorded(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"decision.by"}, _unrecorded_config()
        )
        self.assertIn("structural_judgment.recorded", missing)

    def test_missing_structural_judgment_key_is_treated_as_unrecorded(self):
        config = _valid_config()
        del config["structural_judgment"]
        missing = agenda_schema.required_fields_for(_valid_item(), {"background"}, config)
        self.assertIn("structural_judgment.recorded", missing)

    def test_recorded_structural_judgment_accepts_value_patch(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"background"}, _valid_config()
        )
        self.assertEqual(missing, [])

    def test_empty_patch_keys_adds_no_value_and_is_accepted(self):
        # 構造判断だけを記す record は項目へ値を加えないため、いずれの条件も課さない
        # （課すと構造判断そのものを記録できず、以後すべての記録が詰む）。
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, set(), _unrecorded_config())
        self.assertEqual(missing, [])


class DecisionPatchAcceptanceTest(unittest.TestCase):
    """FNC-008: `decision.*` を加えるパッチは background/essence の非空だけを要求する。"""

    def test_decision_by_only_patch_reports_empty_background_and_essence(self):
        # 受け入れ基準 2 の前半: background / essence が空なら不足として返る。
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, {"decision.by"}, _valid_config())
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_decision_by_only_patch_is_accepted_when_background_and_essence_present(self):
        # 受け入れ基準 2 の後半: outcome / reason の欠落は不足にならない
        # （3 値は 1 つずつ積まれる）。
        item = _valid_item(decision={"by": "human"})
        missing = agenda_schema.required_fields_for(item, {"decision.by"}, _valid_config())
        self.assertEqual(missing, [])

    def test_decision_outcome_patch_does_not_require_reason(self):
        item = _valid_item(decision={"by": "human", "outcome": "adopt"})
        missing = agenda_schema.required_fields_for(
            item, {"decision.outcome"}, _valid_config()
        )
        self.assertEqual(missing, [])

    def test_decision_reason_patch_with_missing_background_is_reported(self):
        item = _valid_item(background="")
        missing = agenda_schema.required_fields_for(
            item, {"decision.reason"}, _valid_config()
        )
        self.assertEqual(missing, ["background"])

    def test_whitespace_only_essence_is_treated_as_empty(self):
        item = _valid_item(essence="   ")
        missing = agenda_schema.required_fields_for(item, {"decision.by"}, _valid_config())
        self.assertIn("essence", missing)

    def test_bare_decision_key_is_treated_as_decision_patch(self):
        # `decision` そのものは名前として受け付けない規則（store 側）だが、
        # 仮に届いた場合も FNC-008 の検証を素通りさせない（fail-closed）。
        item = _valid_item(background="", essence="")
        missing = agenda_schema.required_fields_for(item, {"decision"}, _valid_config())
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_non_decision_patch_does_not_require_background_and_essence(self):
        item = _valid_item(background="", essence="", decision=None)
        missing = agenda_schema.required_fields_for(item, {"title"}, _valid_config())
        self.assertEqual(missing, [])

    def test_patch_keys_accepts_list_and_tuple_and_frozenset(self):
        item = _valid_item(background="", essence="")
        for patch_keys in (["decision.by"], ("decision.by",), frozenset({"decision.by"})):
            with self.subTest(patch_keys=patch_keys):
                missing = agenda_schema.required_fields_for(
                    item, patch_keys, _valid_config()
                )
                self.assertIn("background", missing)
                self.assertIn("essence", missing)


class IsSettledTest(unittest.TestCase):
    """決着（3 値そろい）の述語（DES-075 §5.1）。"""

    def test_three_values_present_is_settled(self):
        # 受け入れ基準 3: 3 値すべて非空のときだけ真。
        self.assertTrue(agenda_schema.is_settled(_valid_item()))

    def test_two_values_are_not_settled(self):
        for decision in (
            {"by": "human", "outcome": "adopt"},
            {"by": "human", "reason": "妥当"},
            {"outcome": "adopt", "reason": "妥当"},
        ):
            with self.subTest(decision=decision):
                self.assertFalse(agenda_schema.is_settled(_valid_item(decision=decision)))

    def test_empty_string_value_is_not_settled(self):
        for field in ("by", "outcome", "reason"):
            with self.subTest(field=field):
                decision = {"by": "human", "outcome": "adopt", "reason": "妥当"}
                decision[field] = ""
                self.assertFalse(agenda_schema.is_settled(_valid_item(decision=decision)))

    def test_whitespace_only_value_is_not_settled(self):
        decision = {"by": "human", "outcome": "adopt", "reason": "  "}
        self.assertFalse(agenda_schema.is_settled(_valid_item(decision=decision)))

    def test_none_decision_is_not_settled(self):
        self.assertFalse(agenda_schema.is_settled(_valid_item(decision=None)))

    def test_absent_decision_key_is_not_settled(self):
        item = _valid_item()
        del item["decision"]
        self.assertFalse(agenda_schema.is_settled(item))

    def test_non_dict_decision_is_not_settled(self):
        self.assertFalse(agenda_schema.is_settled(_valid_item(decision="adopt")))

    def test_non_dict_item_is_not_settled(self):
        self.assertFalse(agenda_schema.is_settled("not-a-dict"))


class ValidateTest(unittest.TestCase):
    def test_accepted_patch_returns_ok_true(self):
        result = agenda_schema.validate(_valid_item(), {"decision.by"}, _valid_config())
        self.assertEqual(result, {"ok": True, "missing_fields": []})

    def test_rejected_patch_returns_ok_false_with_missing_fields(self):
        item = _valid_item(background="", essence="")
        result = agenda_schema.validate(item, {"decision.by"}, _unrecorded_config())
        self.assertFalse(result["ok"])
        self.assertEqual(
            sorted(result["missing_fields"]),
            ["background", "essence", "structural_judgment.recorded"],
        )

    def test_validate_does_not_raise(self):
        try:
            agenda_schema.validate(_valid_item(), {"decision.by"}, _valid_config())
        except Exception as exc:  # noqa: BLE001 - 例外を投げない契約自体の検証
            self.fail(f"validate() が例外を投げた: {exc}")


class MalformedInputRejectionTest(unittest.TestCase):
    """不正な JSON 構造相当の入力の拒否（agenda:REQ-019 NFR-006）。"""

    def test_unexpected_patch_keys_type_fails_closed(self):
        # patch_keys が set/list/tuple/frozenset のいずれでもない場合、検証を
        # 素通りさせず「値を加える decision パッチ」側へ倒す。
        item = _valid_item(background="", essence="")
        for bogus in (None, "decision.by", 123):
            with self.subTest(patch_keys=bogus):
                missing = agenda_schema.required_fields_for(item, bogus, _unrecorded_config())
                self.assertIn("background", missing)
                self.assertIn("essence", missing)
                self.assertIn("structural_judgment.recorded", missing)

    def test_item_not_a_dict_is_treated_as_missing_everything(self):
        missing = agenda_schema.required_fields_for(
            "not-a-dict", {"decision.by"}, _valid_config()
        )
        self.assertIn("background", missing)
        self.assertIn("essence", missing)

    def test_config_not_a_dict_is_treated_as_unrecorded(self):
        missing = agenda_schema.required_fields_for(
            _valid_item(), {"background"}, "not-a-dict"
        )
        self.assertIn("structural_judgment.recorded", missing)

    def test_background_wrong_type_is_treated_as_missing(self):
        item = _valid_item(background=123)
        missing = agenda_schema.required_fields_for(item, {"decision.by"}, _valid_config())
        self.assertIn("background", missing)

    def test_validate_on_malformed_input_returns_ok_false_without_raising(self):
        result = agenda_schema.validate("not-a-dict", {"decision.by"}, "also-not-a-dict")
        self.assertFalse(result["ok"])
        self.assertTrue(result["missing_fields"])


if __name__ == "__main__":
    unittest.main()
