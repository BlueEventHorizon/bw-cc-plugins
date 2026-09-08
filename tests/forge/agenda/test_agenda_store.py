#!/usr/bin/env python3
"""agenda_store.py のテスト。

`start` / `record`（3 形）は関数呼び出し専用であり、`next` / `pending` / `finish`
だけが CLI を持つ（DES-075 §6）。検証の観点は DES-075 §9 が列挙する。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_store -v
"""

import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "forge"
    / "scripts"
    / "agenda"
    / "agenda_store.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_store", _MODULE_PATH)
agenda_store = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_store"] = agenda_store
_SPEC.loader.exec_module(agenda_store)


def _run(args_list):
    parser = agenda_store.build_parser()
    args = parser.parse_args(args_list)
    return agenda_store._HANDLERS[args.command](args)


class AgendaStoreTestCase(unittest.TestCase):
    """一時ディレクトリに agenda.json を置くテストの共通土台。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.agenda_dir = Path(self._tmp.name) / "test-agenda"
        self.agenda_dir.mkdir()
        self.agenda_path = str(self.agenda_dir / "agenda.json")

    def _start(self, *, config=None, items=None):
        return agenda_store.start(
            self.agenda_path,
            config=config if config is not None else {"item_fields": [], "severity_field": None},
            items=items if items is not None else [],
        )

    def _start_with_judgment(self, *, config=None, items=None, note="同型の指摘は無い"):
        """構造判断まで済ませた状態を作る（項目へ値を加える前提条件。§2.6）。"""
        result = self._start(config=config, items=items)
        agenda_store.record_structural_judgment(self.agenda_path, note)
        return result

    def _record(self, item_id, name, value):
        return agenda_store.record_item_value(self.agenda_path, item_id, name, value)

    def _load(self):
        return agenda_store.load_agenda(self.agenda_path)

    def _item(self, item_id):
        return next(i for i in self._load()["items"] if i["id"] == item_id)


class UnknownKeyPreservationTest(AgendaStoreTestCase):
    """DES-078 §2.2・DES-075 §6.1: agenda が知らないキーが落ちない・型で拒否しない。"""

    def test_start_preserves_unknown_item_keys(self):
        self._start(items=[{"id": "01", "title": "項目1", "text": "所見の本文", "rule_id": "R-3"}])
        item = self._item("01")
        self.assertEqual(item["text"], "所見の本文")
        self.assertEqual(item["rule_id"], "R-3")

    def test_start_preserves_values_that_would_violate_old_type_checks(self):
        # 既知キーに現行なら型違反となる値を渡しても拒否・変換されない（§2.3）。
        self._start(items=[{"id": "01", "fields": "not-an-object", "problem": 123}])
        item = self._item("01")
        self.assertEqual(item["fields"], "not-an-object")
        self.assertEqual(item["problem"], 123)

    def test_record_preserves_unknown_value_name(self):
        self._start_with_judgment(items=[{"id": "01"}])
        result = self._record("01", "confidence", "高")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._item("01")["confidence"], "高")

    def test_record_preserves_non_string_value(self):
        self._start_with_judgment(items=[{"id": "01"}])
        self._record("01", "weight", 3)
        self.assertEqual(self._item("01")["weight"], 3)

    def test_start_preserves_unknown_config_keys(self):
        self._start(config={"severity_field": "severity", "origin": "review"})
        self.assertEqual(self._load()["config"]["origin"], "review")


class TitleAndNumberingTest(AgendaStoreTestCase):
    """DES-078 §2.2・DES-075 §3.2: title を必須にせず、id を採番する。"""

    def test_start_accepts_item_without_title(self):
        result = self._start(items=[{"id": "01"}])
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("title", self._item("01"))

    def test_new_item_record_accepts_item_without_title(self):
        self._start(items=[])
        result = agenda_store.record_new_item(self.agenda_path, "追加後もなお構造的な誤りは無い")
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("title", self._item(result["item_id"]))

    def test_start_assigns_zero_padded_id_to_item_without_id(self):
        self._start(items=[{"title": "項目1"}, {"title": "項目2"}])
        self.assertEqual([i["id"] for i in self._load()["items"]], ["01", "02"])

    def test_assigned_id_does_not_collide_with_given_id(self):
        self._start(items=[{"title": "採番される"}, {"id": "01", "title": "渡された"}])
        ids = [i["id"] for i in self._load()["items"]]
        self.assertEqual(ids, ["02", "01"])

    def test_given_id_is_preserved(self):
        self._start(items=[{"id": "finding-7", "title": "項目"}])
        self.assertEqual(self._load()["items"][0]["id"], "finding-7")

    def test_start_fills_defaults_for_missing_agenda_keys(self):
        self._start(items=[{"id": "01"}])
        item = self._item("01")
        self.assertEqual(item["background"], "")
        self.assertEqual(item["essence"], "")
        self.assertEqual(item["recommendation"], "")
        self.assertEqual(item["problem"], "")
        self.assertEqual(item["fields"], {})
        self.assertIsNone(item["decision"])
        self.assertEqual(item["last_changed_fields"], [])

    def test_start_does_not_overwrite_existing_values(self):
        self._start(items=[{"id": "01", "background": "既にある背景"}])
        self.assertEqual(self._item("01")["background"], "既にある背景")

    def test_start_records_structural_judgment_as_not_recorded(self):
        # §2.1: start は構造判断を受け取らない。
        self._start()
        self.assertEqual(
            self._load()["structural_judgment"], {"recorded": False, "note": None}
        )

    def test_config_identity_is_derived_from_path_parent_directory_name(self):
        self._start()
        self.assertEqual(self._load()["config"]["identity"], "test-agenda")


class RecordNewItemTest(AgendaStoreTestCase):
    """DES-075 §6.1 の 3 形目: 新規項目を足す record。"""

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}])

    def test_response_contains_allocated_id(self):
        result = agenda_store.record_new_item(self.agenda_path, "追加後もなお構造的な誤りは無い")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["item_id"], "02")
        self.assertIn("02", [i["id"] for i in self._load()["items"]])

    def test_records_structural_judgment_at_record_level(self):
        agenda_store.record_new_item(self.agenda_path, "追加後もなお構造的な誤りは無い")
        judgment = self._load()["structural_judgment"]
        self.assertTrue(judgment["recorded"])
        self.assertEqual(judgment["note"], "追加後もなお構造的な誤りは無い")

    def test_new_item_is_not_marked_as_changed(self):
        # 構造判断は項目パッチではないため last_changed_fields に含まれない（§2.6）。
        result = agenda_store.record_new_item(self.agenda_path, "再判断")
        self.assertEqual(self._item(result["item_id"])["last_changed_fields"], [])

    def test_unknown_item_id_is_rejected(self):
        agenda_store.record_structural_judgment(self.agenda_path, "問題なし")
        result = self._record("99", "background", "背景")
        self.assertEqual(result["status"], "error")
        self.assertIn("99", result["message"])

    def test_unknown_item_id_does_not_create_item(self):
        agenda_store.record_structural_judgment(self.agenda_path, "問題なし")
        self._record("99", "background", "背景")
        self.assertEqual([i["id"] for i in self._load()["items"]], ["01"])


class RecordSingleValueTest(AgendaStoreTestCase):
    """DES-075 §6.1: 1 回の呼び出しで 1 つの値だけを受け取る。"""

    def setUp(self):
        super().setUp()
        self._start_with_judgment(items=[{"id": "01"}])

    def test_record_item_value_takes_exactly_one_value(self):
        # 複数の値を同時に渡す経路（可変長引数・値の集合）を持たない。
        parameters = inspect.signature(agenda_store.record_item_value).parameters
        self.assertEqual(list(parameters), ["path", "item_id", "name", "value"])
        self.assertFalse(
            any(
                p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in parameters.values()
            )
        )

    def test_earlier_value_survives_later_record(self):
        self._record("01", "background", "背景")
        self._record("01", "essence", "本質")
        item = self._item("01")
        self.assertEqual(item["background"], "背景")
        self.assertEqual(item["essence"], "本質")

    def test_decision_values_are_merged_one_by_one(self):
        self._record("01", "background", "背景")
        self._record("01", "essence", "本質")
        self._record("01", "decision.by", "human")
        self._record("01", "decision.outcome", "adopt")
        self._record("01", "decision.reason", "妥当")
        self.assertEqual(
            self._item("01")["decision"],
            {"by": "human", "outcome": "adopt", "reason": "妥当"},
        )

    def test_record_can_add_title(self):
        result = self._record("01", "title", "後から付けた名前")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._item("01")["title"], "後から付けた名前")

    def test_last_changed_fields_holds_the_given_name_as_is(self):
        self._record("01", "background", "背景")
        self._record("01", "essence", "本質")
        self._record("01", "decision.by", "human")
        self.assertEqual(self._item("01")["last_changed_fields"], ["decision.by"])

    def test_nested_name_under_fields_merges_without_dropping_siblings(self):
        self._record("01", "fields.severity", "critical")
        self._record("01", "fields.origin", "reviewer")
        self.assertEqual(
            self._item("01")["fields"], {"severity": "critical", "origin": "reviewer"}
        )


class ReservedValueNameTest(AgendaStoreTestCase):
    """DES-075 §6.1: agenda が自ら書くキー・構造を持つキーは名前として拒否する。"""

    def setUp(self):
        super().setUp()
        self._start_with_judgment(items=[{"id": "01"}])

    def test_id_is_rejected(self):
        result = self._record("01", "id", "99")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self._item("01")["id"], "01")

    def test_last_changed_fields_is_rejected(self):
        self.assertEqual(self._record("01", "last_changed_fields", ["x"])["status"], "error")

    def test_fields_is_rejected(self):
        self.assertEqual(self._record("01", "fields", {"severity": "x"})["status"], "error")

    def test_decision_is_rejected(self):
        result = self._record("01", "decision", {"by": "human"})
        self.assertEqual(result["status"], "error")
        self.assertIsNone(self._item("01")["decision"])

    def test_nested_name_under_id_is_rejected(self):
        """`id.x` で識別子を dict へ置き換えられない（§2.6 の拒否理由は入れ子でも同じ）。"""
        result = self._record("01", "id.x", "99")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self._item("01")["id"], "01")

    def test_nested_name_under_last_changed_fields_is_rejected(self):
        result = self._record("01", "last_changed_fields.0", "x")
        self.assertEqual(result["status"], "error")
        self.assertEqual(self._item("01")["last_changed_fields"], [])

    def test_nested_names_under_fields_and_decision_are_accepted(self):
        """`fields` / `decision` は構造を持つキーであり、その配下は受け付ける。"""
        self.assertEqual(self._record("01", "fields.severity", "major")["status"], "ok")
        self._record("01", "background", "背景")
        self._record("01", "essence", "本質")
        self.assertEqual(self._record("01", "decision.by", "human")["status"], "ok")


class StructuralJudgmentNoteTest(AgendaStoreTestCase):
    """DES-075 §4・§5.1a: 構造判断は非空の記述を伴う呼び出しでのみ記録される。"""

    def test_empty_note_does_not_record_structural_judgment(self):
        self._start(items=[{"id": "01"}])
        result = agenda_store.record_structural_judgment(self.agenda_path, "")
        self.assertEqual(result["status"], "error")
        self.assertIs(self._load()["structural_judgment"]["recorded"], False)

    def test_whitespace_only_note_does_not_record_structural_judgment(self):
        self._start(items=[{"id": "01"}])
        result = agenda_store.record_structural_judgment(self.agenda_path, "   \n  ")
        self.assertEqual(result["status"], "error")
        self.assertIs(self._load()["structural_judgment"]["recorded"], False)

    def test_empty_note_does_not_add_new_item(self):
        self._start_with_judgment(items=[{"id": "01"}])
        result = agenda_store.record_new_item(self.agenda_path, "")
        self.assertEqual(result["status"], "error")
        self.assertEqual(len(self._load()["items"]), 1)


class AcceptanceConditionTest(AgendaStoreTestCase):
    """DES-075 §5.1 の受理条件（agenda:REQ-019 FNC-008・FNC-012）。"""

    def test_any_value_is_rejected_before_structural_judgment(self):
        self._start(items=[{"id": "01"}])
        result = self._record("01", "background", "背景")
        self.assertEqual(result["status"], "error")
        self.assertIn("structural_judgment.recorded", result["missing_fields"])

    def test_rejected_value_is_not_persisted(self):
        self._start(items=[{"id": "01"}])
        self._record("01", "background", "背景")
        self.assertEqual(self._item("01")["background"], "")

    def test_value_is_accepted_after_structural_judgment(self):
        self._start_with_judgment(items=[{"id": "01"}])
        self.assertEqual(self._record("01", "background", "背景")["status"], "ok")

    def test_decision_is_rejected_while_background_and_essence_are_empty(self):
        self._start_with_judgment(items=[{"id": "01"}])
        result = self._record("01", "decision.by", "human")
        self.assertEqual(result["status"], "error")
        self.assertIn("background", result["missing_fields"])
        self.assertIn("essence", result["missing_fields"])

    def test_decision_is_accepted_after_background_and_essence(self):
        self._start_with_judgment(items=[{"id": "01"}])
        self._record("01", "background", "背景")
        self._record("01", "essence", "本質")
        self.assertEqual(self._record("01", "decision.by", "human")["status"], "ok")


class SettlementTest(AgendaStoreTestCase):
    """DES-075 §5.1: 決着は decision の 3 値そろい。"""

    def setUp(self):
        super().setUp()
        self._start_with_judgment(items=[{"id": "01"}, {"id": "02"}])
        for item_id in ("01", "02"):
            self._record(item_id, "background", "背景")
            self._record(item_id, "essence", "本質")

    def _settle(self, item_id, *, reason=True):
        self._record(item_id, "decision.by", "human")
        self._record(item_id, "decision.outcome", "adopt")
        if reason:
            self._record(item_id, "decision.reason", "妥当")

    def test_two_of_three_values_are_still_pending(self):
        self._settle("01", reason=False)
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["pending_item_ids"], ["01", "02"])

    def test_three_values_are_settled(self):
        self._settle("01")
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["pending_item_ids"], ["02"])
        self.assertEqual(result["remaining_count"], 1)

    def test_next_returns_first_unsettled_item(self):
        self._settle("01")
        self.assertEqual(_run(["next", "--path", self.agenda_path])["item_id"], "02")

    def test_next_returns_none_when_all_settled(self):
        self._settle("01")
        self._settle("02")
        self.assertIsNone(_run(["next", "--path", self.agenda_path])["item_id"])

    def test_finish_does_not_delete_while_two_of_three_values(self):
        self._settle("01", reason=False)
        self._settle("02", reason=False)
        result = _run(["finish", "--path", self.agenda_path])
        self.assertFalse(result["deleted"])
        self.assertEqual(result["remaining_count"], 2)
        self.assertTrue(Path(self.agenda_path).exists())

    def test_finish_deletes_when_all_items_settled(self):
        self._settle("01")
        self._settle("02")
        result = _run(["finish", "--path", self.agenda_path])
        self.assertTrue(result["deleted"])
        self.assertFalse(Path(self.agenda_path).exists())
        self.assertFalse((self.agenda_dir / "agenda.html").exists())
        self.assertFalse((self.agenda_dir / "agenda_state.js").exists())


class OlderRecordTest(AgendaStoreTestCase):
    """DES-078 §2.2: 変更前に保存された記録（キーがより少ない）をそのまま読める。"""

    def test_pending_reads_record_with_fewer_keys(self):
        legacy = {
            "content_version": 3,
            "config": {"identity": "test-agenda", "item_fields": ["severity"]},
            "structural_judgment": {"recorded": True, "note": "問題なし"},
            "items": [
                {"id": "01", "title": "項目1"},
                {
                    "id": "02",
                    "title": "項目2",
                    "decision": {"by": "human", "outcome": "adopt", "reason": "妥当"},
                },
            ],
        }
        Path(self.agenda_path).write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )
        record = agenda_store.load_agenda(self.agenda_path)
        self.assertEqual(agenda_store.pending_item_ids(record), ["01"])
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["pending_item_ids"], ["01"])


class CliSurfaceTest(unittest.TestCase):
    """DES-075 §6: start / record は CLI を持たず、pending / next / finish は残る。"""

    def test_start_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["start", "--path", "p"])

    def test_record_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["record", "--path", "p", "--item-id", "01"])

    def test_pending_next_finish_are_parsed(self):
        parser = agenda_store.build_parser()
        for command in ("pending", "next", "finish"):
            self.assertEqual(parser.parse_args([command, "--path", "p"]).command, command)


class RenderInvocationTest(AgendaStoreTestCase):
    """DES-075 §8.1: 書き込み成功直後に再描画が走り、失敗しても記録は巻き戻さない。"""

    def test_start_writes_agenda_html(self):
        self._start()
        self.assertTrue((self.agenda_dir / "agenda.html").exists())

    def test_start_writes_agenda_state_js_with_content_version(self):
        self._start()
        state_js = (self.agenda_dir / "agenda_state.js").read_text(encoding="utf-8")
        self.assertEqual(state_js, 'window.AGENDA_STATE = {"contentVersion": 1};\n')

    def test_record_triggers_render_html(self):
        self._start_with_judgment(items=[{"id": "01"}])
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            wraps=agenda_store.agenda_render.render_agenda_html,
        ) as html_spy:
            self._record("01", "background", "背景")
        html_spy.assert_called_once()

    def test_render_failure_still_persists_record_change(self):
        self._start_with_judgment(items=[{"id": "01"}])
        before_version = self._load()["content_version"]
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            side_effect=RuntimeError("boom"),
        ):
            result = self._record("01", "background", "背景")
        self.assertEqual(result["status"], "partial")
        self.assertIn("再描画に失敗", result["message"])
        record = self._load()
        self.assertEqual(record["content_version"], before_version + 1)
        self.assertEqual(self._item("01")["background"], "背景")


class IoFailureTest(AgendaStoreTestCase):
    """NFR-006: JSON 読み書き失敗時に既定値で補わず明示エラーを返す。"""

    def test_record_on_nonexistent_agenda_returns_error(self):
        missing_path = str(Path(self._tmp.name) / "does-not-exist" / "agenda.json")
        result = agenda_store.record_item_value(missing_path, "01", "background", "背景")
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_next_on_corrupt_json_returns_error(self):
        Path(self.agenda_path).write_text("{not-valid-json", encoding="utf-8")
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "error")

    def test_save_agenda_raises_on_write_failure(self):
        collide = Path(self._tmp.name) / "collide"
        collide.write_text("x", encoding="utf-8")
        bad_path = str(collide / "agenda.json")
        with self.assertRaises(agenda_store.AgendaStoreError):
            agenda_store.save_agenda(bad_path, {"a": 1})


class MainExitCodeTest(AgendaStoreTestCase):
    """main() の終了コード分岐（status: ok/partial → 0、error → 1）。"""

    def test_main_returns_zero_on_ok(self):
        self._start()
        self.assertEqual(agenda_store.main(["pending", "--path", self.agenda_path]), 0)

    def test_main_returns_one_on_error(self):
        exit_code = agenda_store.main(
            ["next", "--path", str(Path(self._tmp.name) / "missing.json")]
        )
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
