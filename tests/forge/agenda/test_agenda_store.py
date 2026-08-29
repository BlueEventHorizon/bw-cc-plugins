#!/usr/bin/env python3
"""agenda_store.py（start/record/next/pending/finish の5コマンド）のテスト。

DES-075 §9 が列挙する単体テスト対象・TASK-009 implementation_instructions が
挙げる境界ケースを検証する。旧CLI契約（init/update --set/record-structural-judgment/
set-current）への言及は行わない。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_store -v
"""

import importlib.util
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
        self._candidate_counter = 0

    def _write_candidate(self, candidate: dict) -> str:
        self._candidate_counter += 1
        path = Path(self._tmp.name) / f"candidate-{self._candidate_counter}.json"
        path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _start(
        self,
        *,
        note="同型の指摘は無い",
        item_fields=None,
        severity_field=None,
        items=None,
    ):
        config = {
            "item_fields": item_fields if item_fields is not None else ["severity"],
            "severity_field": severity_field,
        }
        candidate = {
            "structural_judgment": {"note": note},
            "config": config,
            "items": items if items is not None else [],
        }
        return _run(
            [
                "start",
                "--path", self.agenda_path,
                "--input-file", self._write_candidate(candidate),
            ]
        )

    def _record(self, item_id, patch):
        return _run(
            [
                "record",
                "--path", self.agenda_path,
                "--item-id", item_id,
                "--input-file", self._write_candidate(patch),
            ]
        )

    def _load(self):
        return agenda_store.load_agenda(self.agenda_path)


class StartCandidateValidationTest(AgendaStoreTestCase):
    """start の候補JSON検証（DES-075 §6・実装指示）。"""

    def test_unknown_top_level_key_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
            "bogus": True,
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("bogus", result["message"])

    def test_missing_structural_judgment_note_is_rejected(self):
        candidate = {
            "structural_judgment": {},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_empty_structural_judgment_note_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "   "},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_config_identity_in_candidate_is_rejected(self):
        # config.identity は --path の親ディレクトリ名から自動導出する。
        # 候補JSONから受け付けない（DES-075 §4）。
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"identity": "hand-crafted", "item_fields": [], "severity_field": None},
            "items": [],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("identity", result["message"])

    def test_item_missing_id_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [{"title": "id なし項目"}],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_item_missing_title_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [{"id": "01"}],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_duplicate_item_id_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [{"id": "01", "title": "項目1"}, {"id": "01", "title": "項目1重複"}],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_item_unknown_key_is_rejected(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [{"id": "01", "title": "項目1", "status": "未着手"}],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")

    def test_structural_judgment_recorded_key_is_rejected(self):
        # DES-075 §4 / TASK-009: recorded は呼び出し側が渡さない（渡すと未知フィールドとして拒否される）。
        candidate = {
            "structural_judgment": {"note": "問題なし", "recorded": True},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("recorded", result["message"])

    def test_structural_judgment_recorded_at_key_is_rejected(self):
        # DES-075 §4: recorded_at のようなタイムスタンプは設計しない。候補JSONに含めると拒否される。
        candidate = {
            "structural_judgment": {"note": "問題なし", "recorded_at": "2026-08-26T00:00:00Z"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
        }
        result = _run(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("recorded_at", result["message"])


class StartSuccessTest(AgendaStoreTestCase):
    """start 成功時のスキーマ（DES-075 §4）。"""

    def test_start_creates_record_matching_des075_section4(self):
        result = self._start(
            note="同型の指摘は無い",
            item_fields=["severity"],
            severity_field="severity",
            items=[{"id": "01", "title": "項目1", "fields": {"severity": "critical"}}],
        )
        self.assertEqual(result["status"], "ok")
        record = self._load()
        self.assertEqual(record["content_version"], 1)
        self.assertEqual(record["config"]["item_fields"], ["severity"])
        self.assertEqual(record["config"]["severity_field"], "severity")
        self.assertTrue(record["structural_judgment"]["recorded"])
        self.assertEqual(record["structural_judgment"]["note"], "同型の指摘は無い")
        self.assertEqual(len(record["items"]), 1)
        item = record["items"][0]
        self.assertEqual(item["id"], "01")
        self.assertEqual(item["title"], "項目1")
        self.assertEqual(item["fields"], {"severity": "critical"})
        self.assertEqual(item["background"], "")
        self.assertEqual(item["essence"], "")
        self.assertIsNone(item["decision"])

    def test_config_identity_is_derived_from_path_parent_directory_name(self):
        self._start()
        record = self._load()
        self.assertEqual(record["config"]["identity"], "test-agenda")

    def test_structural_judgment_recorded_true_without_recorded_at_key(self):
        # DES-075 §4: recorded_at のようなタイムスタンプは設計しない。
        self._start()
        record = self._load()
        self.assertNotIn("recorded_at", record["structural_judgment"])

    def test_start_writes_agenda_html(self):
        self._start()
        self.assertTrue((self.agenda_dir / "agenda.html").exists())

    def test_start_writes_agenda_state_js_with_content_version(self):
        # DES-077 §4.2: 書き込み成功のたびに世代番号ファイルを再生成する。
        self._start()
        state_js = (self.agenda_dir / "agenda_state.js").read_text(encoding="utf-8")
        self.assertEqual(state_js, 'window.AGENDA_STATE = {"contentVersion": 1};\n')

    def test_start_stores_problem_and_defaults_recommendation(self):
        # DES-075 §4: problem は start で項目とともに渡す。recommendation は空で初期化する。
        self._start(items=[{"id": "01", "title": "項目1", "problem": "何が問題か"}])
        item = self._load()["items"][0]
        self.assertEqual(item["problem"], "何が問題か")
        self.assertEqual(item["recommendation"], "")

    def test_start_without_problem_defaults_to_empty(self):
        self._start(items=[{"id": "01", "title": "項目1"}])
        self.assertEqual(self._load()["items"][0]["problem"], "")

    def test_start_rejects_non_string_problem(self):
        result = self._start(items=[{"id": "01", "title": "項目1", "problem": 123}])
        self.assertEqual(result["status"], "error")
        self.assertIn("problem", result["message"])


class RecordProblemRecommendationTest(AgendaStoreTestCase):
    """DES-075 §6.1: problem / recommendation を差分パッチとして受け付ける。"""

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}])

    def test_record_patches_recommendation(self):
        result = self._record(
            "01", {"background": "背景", "essence": "本質", "recommendation": "案Aを推奨（確信度: 中）"}
        )
        self.assertEqual(result["status"], "ok")
        item = self._load()["items"][0]
        self.assertEqual(item["recommendation"], "案Aを推奨（確信度: 中）")
        self.assertIn("recommendation", item["last_changed_fields"])

    def test_record_patches_problem(self):
        result = self._record("01", {"problem": "後から言語化した問題"})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(self._load()["items"][0]["problem"], "後から言語化した問題")

    def test_record_rejects_non_string_recommendation(self):
        result = self._record("01", {"recommendation": 123})
        self.assertEqual(result["status"], "error")
        self.assertIn("recommendation", result["message"])


class RecordCandidateValidationTest(AgendaStoreTestCase):
    """record の候補JSON検証。"""

    def setUp(self):
        super().setUp()
        self._start()

    def test_id_key_in_candidate_is_rejected(self):
        result = self._record("01", {"id": "99", "title": "新規項目"})
        self.assertEqual(result["status"], "error")
        self.assertIn("id", result["message"])

    def test_unknown_top_level_key_is_rejected(self):
        result = self._record("01", {"title": "項目1", "bogus": True})
        self.assertEqual(result["status"], "error")
        self.assertIn("bogus", result["message"])

    def test_new_item_requires_structural_judgment_note(self):
        # §5.1a: 新規追加時は structural_judgment.note の同時指定が必須。
        result = self._record("99", {"title": "新規項目"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["ok"], False)
        self.assertIn("structural_judgment.note", result["missing_fields"])

    def test_new_item_requires_title(self):
        result = self._record(
            "99", {"structural_judgment": {"note": "追加後もなお構造的な誤りは無い"}}
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("title", result["missing_fields"])

    def test_new_item_with_note_and_title_succeeds(self):
        result = self._record(
            "99",
            {
                "title": "新規項目",
                "structural_judgment": {"note": "追加後もなお構造的な誤りは無い"},
            },
        )
        self.assertEqual(result["status"], "ok")
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "99")
        self.assertEqual(item["title"], "新規項目")

    def test_existing_item_update_does_not_require_structural_judgment_note(self):
        self._record("01", {"title": "項目1", "structural_judgment": {"note": "追加後も問題なし"}})
        result = self._record("01", {"background": "背景の記述"})
        self.assertEqual(result["status"], "ok")

    def test_structural_judgment_wrong_type_is_rejected(self):
        result = self._record("01", {"structural_judgment": "not-an-object"})
        self.assertEqual(result["status"], "error")

    def test_structural_judgment_recorded_key_is_rejected(self):
        # DES-075 §4 / TASK-009: recorded は呼び出し側が渡さない（渡すと未知フィールドとして拒否される）。
        result = self._record(
            "01", {"structural_judgment": {"note": "再判定した", "recorded": True}}
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("recorded", result["message"])

    def test_structural_judgment_recorded_at_key_is_rejected(self):
        # DES-075 §4: recorded_at のようなタイムスタンプは設計しない。候補JSONに含めると拒否される。
        result = self._record(
            "01",
            {"structural_judgment": {"note": "再判定した", "recorded_at": "2026-08-26T00:00:00Z"}},
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("recorded_at", result["message"])


class StructuralJudgmentTwoPathMergeTest(AgendaStoreTestCase):
    """DES-075 §6.1: structural_judgment はレコード直下へ、他キーは項目へ振り分ける。"""

    def setUp(self):
        super().setUp()
        self._start()

    def test_structural_judgment_note_updates_record_level_field(self):
        self._record(
            "99",
            {
                "title": "新規項目",
                "structural_judgment": {"note": "新しい判定内容"},
            },
        )
        record = self._load()
        self.assertEqual(record["structural_judgment"]["note"], "新しい判定内容")

    def test_structural_judgment_key_is_not_merged_into_item(self):
        self._record(
            "99",
            {
                "title": "新規項目",
                "structural_judgment": {"note": "新しい判定内容"},
            },
        )
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "99")
        self.assertNotIn("structural_judgment", item)

    def test_structural_judgment_only_patch_on_existing_item_does_not_touch_item_fields(self):
        self._record("01", {"title": "項目1", "structural_judgment": {"note": "初期判定"}})
        before = self._load()
        self._record("01", {"structural_judgment": {"note": "再判定した"}})
        after = self._load()
        item_before = next(i for i in before["items"] if i["id"] == "01")
        item_after = next(i for i in after["items"] if i["id"] == "01")
        self.assertEqual(item_before, item_after)
        self.assertEqual(after["structural_judgment"]["note"], "再判定した")


class FieldsReplacementTest(AgendaStoreTestCase):
    """DES-075 §6.1: fields のようなネストキーはトップレベル単位で丸ごと置換する。"""

    def setUp(self):
        super().setUp()
        self._start(
            items=[{"id": "01", "title": "項目1", "fields": {"severity": "critical", "other": "x"}}]
        )

    def test_fields_patch_replaces_entire_dict_not_merges(self):
        self._record("01", {"fields": {"severity": "major"}})
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item["fields"], {"severity": "major"})
        self.assertNotIn("other", item["fields"])


class DecisionTransitionTest(AgendaStoreTestCase):
    """DES-075 §5.1: decision を含む record 呼び出しでのみ終端検証を課す。"""

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}])

    def test_background_essence_only_patch_does_not_require_decision(self):
        result = self._record("01", {"background": "背景", "essence": "本質"})
        self.assertEqual(result["status"], "ok")

    def test_decision_patch_without_background_essence_is_rejected(self):
        result = self._record(
            "01", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当"}}
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("background", result["missing_fields"])
        self.assertIn("essence", result["missing_fields"])
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertIsNone(item["decision"])

    def test_decision_patch_after_background_essence_succeeds(self):
        self._record("01", {"background": "背景", "essence": "本質"})
        result = self._record(
            "01", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当"}}
        )
        self.assertEqual(result["status"], "ok")
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item["decision"], {"by": "human", "outcome": "adopt", "reason": "妥当"})

    def test_decision_with_missing_by_is_rejected(self):
        self._record("01", {"background": "背景", "essence": "本質"})
        result = self._record("01", {"decision": {"outcome": "adopt", "reason": "妥当"}})
        self.assertEqual(result["status"], "error")
        self.assertIn("decision.by", result["missing_fields"])


class DecisionTriggerLoopholeTest(AgendaStoreTestCase):
    """agenda_strategy.md リスク表「decisionトリガー検証の抜け穴」対応。

    既に decision が記録済みの項目へ decision を含まない差分パッチ（background のみ等）
    で record を呼んだ場合の実装の実際の挙動（許可）を固定化する。挙動そのものは
    変更しない（テストのみで固定する）。
    """

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}])
        self._record("01", {"background": "背景", "essence": "本質"})
        self._record(
            "01", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"}}
        )

    def test_non_decision_patch_on_decided_item_is_permitted(self):
        result = self._record("01", {"background": "背景を書き直した"})
        self.assertEqual(result["status"], "ok")

    def test_non_decision_patch_on_decided_item_leaves_decision_intact(self):
        # decision を含まないパッチは decision フィールド自体を触らないため、
        # 既存の decision がそのまま残る（upsert_item() は渡されたキーのみ上書きする）。
        self._record("01", {"background": "背景を書き直した"})
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item["decision"], {"by": "human", "outcome": "adopt", "reason": "妥当と判断"})

    def test_decided_item_no_longer_appears_in_pending_after_non_decision_patch(self):
        self._record("01", {"background": "背景を書き直した"})
        result = _run(["pending", "--path", self.agenda_path])
        self.assertNotIn("01", result["pending_item_ids"])

    def test_emptying_background_on_decided_item_leaves_inconsistent_state(self):
        # decision トリガーが成立していれば拒否されたはずの「background 空」を、
        # decision を含まないパッチとしてなら通してしまう（抜け穴の具体例）。
        # 決着済みかつ background が空という、decision トリガー経路なら
        # 起こり得ない状態が生じることを固定化する（挙動は変更しない）。
        result = self._record("01", {"background": ""})
        self.assertEqual(result["status"], "ok")
        record = self._load()
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item["background"], "")
        self.assertIsNotNone(item["decision"])


class EmptyPatchTest(AgendaStoreTestCase):
    """空の差分パッチ（{}）でも content_version は増え、保存される（既存挙動の固定化）。"""

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}])

    def test_empty_patch_still_increments_content_version(self):
        before = self._load()["content_version"]
        result = self._record("01", {})
        self.assertEqual(result["status"], "ok")
        after = self._load()["content_version"]
        self.assertEqual(after, before + 1)

    def test_empty_patch_does_not_change_last_changed_fields(self):
        self._record("01", {"background": "背景"})
        before_item = next(i for i in self._load()["items"] if i["id"] == "01")
        self._record("01", {})
        after_item = next(i for i in self._load()["items"] if i["id"] == "01")
        self.assertEqual(after_item["last_changed_fields"], before_item["last_changed_fields"])


class LastChangedFieldsTest(AgendaStoreTestCase):
    """FNC-013: last_changed_fields が今回渡されたキー（id を除く）の集合と一致すること。"""

    def setUp(self):
        super().setUp()
        self._start()

    def test_last_changed_fields_matches_patch_keys_on_new_item(self):
        self._record(
            "01",
            {
                "title": "項目1",
                "background": "背景",
                "structural_judgment": {"note": "問題なし"},
            },
        )
        item = next(i for i in self._load()["items"] if i["id"] == "01")
        # structural_judgment はレコード直下へのパッチであり item のパッチキーには含まれない。
        self.assertEqual(item["last_changed_fields"], sorted(["title", "background"]))

    def test_last_changed_fields_matches_patch_keys_on_partial_update(self):
        self._record(
            "01", {"title": "項目1", "structural_judgment": {"note": "問題なし"}}
        )
        self._record("01", {"essence": "本質の記述"})
        item = next(i for i in self._load()["items"] if i["id"] == "01")
        self.assertEqual(item["last_changed_fields"], ["essence"])


class NextPendingTest(AgendaStoreTestCase):
    """FNC-006: decision の値ベース判定（dict型でoutcomeが非空か）に基づく next/pending。"""

    def setUp(self):
        super().setUp()
        self._start(
            items=[
                {"id": "01", "title": "項目1"},
                {"id": "02", "title": "項目2"},
                {"id": "03", "title": "項目3"},
            ]
        )
        self._record("01", {"background": "背景", "essence": "本質"})
        self._record("03", {"background": "背景", "essence": "本質"})
        self._record(
            "03", {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当"}}
        )

    def test_next_returns_first_pending_item(self):
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["item_id"], "01")

    def test_pending_returns_all_pending_items_excluding_decided(self):
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pending_item_ids"], ["01", "02"])

    def test_remaining_count_matches_pending_length(self):
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["remaining_count"], 2)

    def test_next_returns_none_when_no_pending_item(self):
        self._record("01", {"decision": {"by": "human", "outcome": "adopt", "reason": "x"}})
        self._record("02", {"background": "背景", "essence": "本質"})
        self._record("02", {"decision": {"by": "human", "outcome": "adopt", "reason": "x"}})
        result = _run(["next", "--path", self.agenda_path])
        self.assertIsNone(result["item_id"])

    def test_decision_dict_with_empty_outcome_is_still_pending(self):
        # decision が dict 型でも outcome が空なら「未対応」のまま
        # （DES-075 §4「状態の表現」）。
        record = self._load()
        for item in record["items"]:
            if item["id"] == "02":
                item["decision"] = {"by": "human", "outcome": "", "reason": ""}
        agenda_store.save_agenda(self.agenda_path, record)
        result = _run(["pending", "--path", self.agenda_path])
        self.assertIn("02", result["pending_item_ids"])


class FinishTest(AgendaStoreTestCase):
    """DES-075 §7: 全項目に decision が記録されていれば削除、残っていれば残件数を返す。"""

    def setUp(self):
        super().setUp()
        self._start(items=[{"id": "01", "title": "項目1"}, {"id": "02", "title": "項目2"}])

    def test_finish_does_not_delete_when_items_pending(self):
        result = _run(["finish", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["deleted"])
        self.assertEqual(result["remaining_count"], 2)
        self.assertTrue(Path(self.agenda_path).exists())

    def test_finish_deletes_when_all_items_decided(self):
        for item_id in ("01", "02"):
            self._record(item_id, {"background": "背景", "essence": "本質"})
            self._record(
                item_id, {"decision": {"by": "human", "outcome": "adopt", "reason": "妥当"}}
            )
        result = _run(["finish", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["deleted"])
        self.assertFalse(Path(self.agenda_path).exists())
        self.assertFalse((self.agenda_dir / "agenda.html").exists())
        self.assertFalse((self.agenda_dir / "agenda_state.js").exists())


class IoFailureTest(AgendaStoreTestCase):
    """NFR-006: JSON 読み書き失敗時に既定値で補わず明示エラーを返す。"""

    def test_record_on_nonexistent_agenda_returns_error(self):
        missing_path = str(Path(self._tmp.name) / "does-not-exist" / "agenda.json")
        result = _run(
            [
                "record",
                "--path", missing_path,
                "--item-id", "01",
                "--input-file", self._write_candidate({"background": "背景"}),
            ]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_next_on_corrupt_json_returns_error(self):
        Path(self.agenda_path).write_text("{not-valid-json", encoding="utf-8")
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_start_with_malformed_input_file_returns_error(self):
        bogus_path = Path(self._tmp.name) / "bogus.json"
        bogus_path.write_text("not-valid-json{", encoding="utf-8")
        result = _run(["start", "--path", self.agenda_path, "--input-file", str(bogus_path)])
        self.assertEqual(result["status"], "error")

    def test_input_file_that_is_not_an_object_is_rejected(self):
        path = self._write_candidate(["not", "an", "object"])
        result = _run(["start", "--path", self.agenda_path, "--input-file", path])
        self.assertEqual(result["status"], "error")

    def test_save_agenda_raises_on_write_failure(self):
        collide = Path(self._tmp.name) / "collide"
        collide.write_text("x", encoding="utf-8")
        bad_path = str(collide / "agenda.json")
        with self.assertRaises(agenda_store.AgendaStoreError):
            agenda_store.save_agenda(bad_path, {"a": 1})


class RenderAutoInvocationTest(AgendaStoreTestCase):
    """DES-075 §8.1: 書き込み成功直後に agenda_render.py が自動的に呼ばれること。
    呼び出しが失敗しても記録側の状態遷移は成立したままであること。"""

    def test_start_triggers_render_html(self):
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            wraps=agenda_store.agenda_render.render_agenda_html,
        ) as html_spy:
            self._start()
        html_spy.assert_called_once()

    def test_record_triggers_render_html(self):
        self._start(items=[{"id": "01", "title": "項目1"}])
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            wraps=agenda_store.agenda_render.render_agenda_html,
        ) as html_spy:
            self._record("01", {"background": "背景"})
        html_spy.assert_called_once()

    def test_render_failure_still_persists_record_change(self):
        self._start(items=[{"id": "01", "title": "項目1"}])
        before_version = self._load()["content_version"]
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            side_effect=RuntimeError("boom"),
        ):
            result = self._record("01", {"background": "背景"})
        self.assertEqual(result["status"], "partial")
        self.assertIn("再描画に失敗", result["message"])
        record = self._load()
        self.assertEqual(record["content_version"], before_version + 1)
        item = next(i for i in record["items"] if i["id"] == "01")
        self.assertEqual(item["background"], "背景")


class MainExitCodeTest(AgendaStoreTestCase):
    """main() の終了コード分岐（status: ok/partial → 0、error → 1）。"""

    def test_main_returns_zero_on_ok(self):
        candidate = {
            "structural_judgment": {"note": "問題なし"},
            "config": {"item_fields": [], "severity_field": None},
            "items": [],
        }
        exit_code = agenda_store.main(
            ["start", "--path", self.agenda_path, "--input-file", self._write_candidate(candidate)]
        )
        self.assertEqual(exit_code, 0)

    def test_main_returns_one_on_error(self):
        exit_code = agenda_store.main(
            ["next", "--path", str(Path(self._tmp.name) / "missing.json")]
        )
        self.assertEqual(exit_code, 1)


class OldCliArgumentRejectionTest(unittest.TestCase):
    """旧CLI契約（サブコマンド・引数）を渡すと argparse が明確に拒否すること。"""

    def test_old_init_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["init", "--identity", "x", "--path", "p"])

    def test_old_update_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["update", "--path", "p", "--item-id", "01", "--set", "title=x"])

    def test_old_set_current_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["set-current", "--path", "p", "--item-id", "01"])

    def test_old_record_structural_judgment_subcommand_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["record-structural-judgment", "--path", "p", "--note", "x"])

    def test_status_vocabulary_flag_on_start_is_rejected(self):
        parser = agenda_store.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "start",
                    "--path", "p",
                    "--input-file", "f",
                    "--status-vocabulary", "[]",
                ]
            )


if __name__ == "__main__":
    unittest.main()
