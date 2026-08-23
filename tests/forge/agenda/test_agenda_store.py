#!/usr/bin/env python3
"""agenda_store.py（agenda.json の読み書き・状態遷移検証・CLI）のテスト。

DES-075 §9 が列挙する単体テスト対象を検証する（TASK-003 acceptance_criteria）。

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
        self.agenda_path = str(Path(self._tmp.name) / "agenda.json")

    def _init(self, **overrides):
        params = {
            "identity": "test-agenda",
            "status_vocabulary": ["未着手", "進行中", "決着", "保留", "対象外", "取り下げ"],
            "terminal_statuses": ["決着", "対象外", "取り下げ"],
            "active_statuses": ["未着手", "進行中"],
            "item_fields": ["severity", "confidence"],
            "severity_field": None,
        }
        params.update(overrides)
        args = [
            "init",
            "--identity", params["identity"],
            "--status-vocabulary", json.dumps(params["status_vocabulary"], ensure_ascii=False),
            "--terminal-statuses", json.dumps(params["terminal_statuses"], ensure_ascii=False),
            "--active-statuses", json.dumps(params["active_statuses"], ensure_ascii=False),
            "--item-fields", json.dumps(params["item_fields"], ensure_ascii=False),
            "--path", self.agenda_path,
        ]
        if params["severity_field"] is not None:
            args += ["--severity-field", params["severity_field"]]
        return _run(args)

    def _update(self, item_patch):
        args = ["update", "--path", self.agenda_path, "--item-id", str(item_patch["id"])]
        for key, value in item_patch.items():
            if key == "id":
                continue
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    args += ["--set", f"{key}.{sub_key}={sub_value}"]
            else:
                args += ["--set", f"{key}={value}"]
        return _run(args)

    def _record(self):
        return agenda_store.load_agenda(self.agenda_path)


class InitTest(AgendaStoreTestCase):
    def test_init_creates_schema_per_des075_section4(self):
        result = self._init(severity_field="severity")
        self.assertEqual(result["status"], "ok")
        record = self._record()
        self.assertEqual(record["owner"], "consult")
        self.assertEqual(record["content_version"], 1)
        self.assertEqual(record["config"]["severity_field"], "severity")
        self.assertFalse(record["structural_judgment"]["recorded"])
        self.assertEqual(record["items"], [])

    def test_init_defaults_severity_field_to_none_when_unspecified(self):
        result = self._init()
        self.assertEqual(result["status"], "ok")
        record = self._record()
        self.assertIsNone(record["config"]["severity_field"])

    def test_init_writes_agenda_html_and_state_js(self):
        self._init()
        out_dir = Path(self.agenda_path).parent
        self.assertTrue((out_dir / "agenda.html").exists())
        self.assertTrue((out_dir / "agenda_state.js").exists())


class IoFailureTest(AgendaStoreTestCase):
    """NFR-006: JSON 読み書き失敗時に既定値で補わず明示エラーを返す。"""

    def test_update_on_nonexistent_agenda_returns_error(self):
        missing_path = str(Path(self._tmp.name) / "does-not-exist.json")
        result = _run(["update", "--path", missing_path, "--item-id", "01", "--set", "title=x"])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_next_on_corrupt_json_returns_error(self):
        Path(self.agenda_path).write_text("{not-valid-json", encoding="utf-8")
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_update_rejects_malformed_set_flag(self):
        self._init()
        result = _run(["update", "--path", self.agenda_path, "--item-id", "01", "--set", "no-equals-sign"])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_update_rejects_id_via_set_flag(self):
        # id は --item-id 経由のみ受け付ける。--set id=... による上書きは曖昧なため拒否する。
        self._init()
        result = _run(["update", "--path", self.agenda_path, "--item-id", "01", "--set", "id=99"])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_set_flags_nested_then_flat_conflict_is_rejected(self):
        # ネスト指定 (verification.action=...) の後に同じトップレベルキーを
        # フラット指定 (verification=...) すると、既存のネスト内容がサイレントに
        # 消失していたバグの回帰テスト（ラウンド13所見）。
        with self.assertRaises(ValueError):
            agenda_store._parse_set_flags(["verification.action=adopt", "verification=xyz"])

    def test_set_flags_flat_then_nested_conflict_is_rejected(self):
        with self.assertRaises(ValueError):
            agenda_store._parse_set_flags(["verification=xyz", "verification.action=adopt"])

    def test_non_string_item_id_is_rejected(self):
        # id が truthy でも文字列型でない場合（例: 数値）は拒否されること
        # （真偽値判定 `not value` では数値等の非文字列 truthy 値を素通りさせてしまう。
        # _non_empty_string() が型を明示的に検証する回帰テスト）。
        # CLI は --item-id が常に文字列を渡すためこの型混入は経由できず、
        # upsert_item() を直接呼んで関数自体の防御を検証する。
        record = {"items": []}
        result = agenda_store.upsert_item(record, {"id": 1, "title": "項目1"})
        self.assertFalse(result["ok"])
        self.assertIn("id", result["missing_fields"])

    def test_item_patch_without_id_is_rejected(self):
        # CLI は --item-id を argparse の required 制約で強制するため id 欠落を経由できず、
        # upsert_item() を直接呼んで関数自体の防御を検証する。
        record = {"items": []}
        result = agenda_store.upsert_item(record, {"title": "id なし項目"})
        self.assertFalse(result["ok"])
        self.assertIn("id", result["missing_fields"])

    def test_new_item_without_title_is_rejected(self):
        self._init()
        result = self._update({"id": "99", "status": "未着手"})
        self.assertEqual(result["status"], "error")
        self.assertIn("title", result["missing_fields"])

    def test_new_item_without_status_is_rejected(self):
        # status 未設定の項目が作られると、config.active_statuses にも
        # config.terminal_statuses にも属さない「第三の状態」になり、
        # next_item_id()/pending_item_ids() から永久に見えなくなる回帰テスト
        # （ラウンド15所見）。
        self._init()
        result = self._update({"id": "99", "title": "項目99"})
        self.assertEqual(result["status"], "error")
        self.assertIn("status", result["missing_fields"])

    def test_init_returns_error_when_save_fails(self):
        collide = Path(self._tmp.name) / "no-such-dir"
        collide.write_text("not a directory", encoding="utf-8")
        bad_path = str(collide / "agenda.json")
        result = _run(
            [
                "init",
                "--identity", "x",
                "--status-vocabulary", "[]",
                "--terminal-statuses", "[]",
                "--active-statuses", "[]",
                "--item-fields", "[]",
                "--path", bad_path,
            ]
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_save_agenda_raises_on_write_failure(self):
        # 親ディレクトリを作ろうとする経路（p.parent.mkdir）が既存の通常ファイルと
        # 衝突することで OSError を発生させ、save_agenda が AgendaStoreError へ
        # 変換して伝播することを検証する（NFR-006: 既定値で補わず明示エラー）。
        collide = Path(self._tmp.name) / "collide"
        collide.write_text("x", encoding="utf-8")
        bad_path = str(collide / "agenda.json")
        with self.assertRaises(agenda_store.AgendaStoreError):
            agenda_store.save_agenda(bad_path, {"a": 1})


class LastChangedFieldsTest(AgendaStoreTestCase):
    """FNC-013: last_changed_fields が今回渡されたキー（id を除く）の集合と一致すること
    （DES-075 §6.1・§4。id は識別子であり値の変更を表さないため対象から除く）。"""

    def setUp(self):
        super().setUp()
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])

    def test_last_changed_fields_matches_patch_keys_on_new_item(self):
        self._update({"id": "01", "title": "項目1", "status": "未着手"})
        item = next(i for i in self._record()["items"] if i["id"] == "01")
        self.assertEqual(item["last_changed_fields"], sorted(["title", "status"]))

    def test_last_changed_fields_matches_patch_keys_on_partial_update(self):
        self._update({"id": "01", "title": "項目1", "status": "未着手"})
        self._update({"id": "01", "recommendation": "推奨内容"})
        item = next(i for i in self._record()["items"] if i["id"] == "01")
        self.assertEqual(item["last_changed_fields"], ["recommendation"])


class MainExitCodeTest(AgendaStoreTestCase):
    """main() の終了コード分岐（status: ok/partial → 0、error → 1）。"""

    def test_main_returns_zero_on_ok(self):
        exit_code = agenda_store.main(
            [
                "init",
                "--identity", "x",
                "--status-vocabulary", "[]",
                "--terminal-statuses", "[]",
                "--active-statuses", "[]",
                "--item-fields", "[]",
                "--path", self.agenda_path,
            ]
        )
        self.assertEqual(exit_code, 0)

    def test_main_returns_one_on_error(self):
        exit_code = agenda_store.main(["next", "--path", str(Path(self._tmp.name) / "missing.json")])
        self.assertEqual(exit_code, 1)


class NextPendingRemainingCountTest(AgendaStoreTestCase):
    """FNC-006: next/pending/remaining_count が active_statuses に基づき正しいこと。"""

    def setUp(self):
        super().setUp()
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        self._update({"id": "01", "title": "項目1", "status": "未着手"})
        self._update({"id": "02", "title": "項目2", "status": "進行中"})
        self._update(
            {
                "id": "03",
                "title": "項目3",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
            }
        )

    def test_next_returns_first_active_item(self):
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["next_item_id"], "01")

    def test_pending_returns_all_active_items(self):
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pending_item_ids"], ["01", "02"])

    def test_remaining_count_matches_pending_length(self):
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["remaining_count"], 2)

    def test_next_returns_none_when_no_active_item(self):
        self._update({"id": "01", "status": "決着", "background": "b", "essence": "e"})
        self._update({"id": "02", "status": "決着", "background": "b", "essence": "e"})
        result = _run(["next", "--path", self.agenda_path])
        self.assertIsNone(result["next_item_id"])

    def test_next_fails_closed_when_active_statuses_is_malformed(self):
        # config.active_statuses が list でない場合、「対象項目なし」と誤判定せず
        # 明示エラーを返す（NFR-006・agenda_schema.py の fail-closed 方針と対称）。
        record = self._record()
        record["config"]["active_statuses"] = "not-a-list"
        agenda_store.save_agenda(self.agenda_path, record)
        result = _run(["next", "--path", self.agenda_path])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)

    def test_pending_fails_closed_when_active_statuses_is_malformed(self):
        record = self._record()
        record["config"]["active_statuses"] = "not-a-list"
        agenda_store.save_agenda(self.agenda_path, record)
        result = _run(["pending", "--path", self.agenda_path])
        self.assertEqual(result["status"], "error")
        self.assertIn("message", result)


class ContentVersionRuleTest(AgendaStoreTestCase):
    """DES-075 §3.2: init/update/record-structural-judgment で +1、set-current では増えない。"""

    def test_update_increments_content_version(self):
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        before = self._record()["content_version"]
        self._update({"id": "01", "title": "項目1", "status": "未着手"})
        after = self._record()["content_version"]
        self.assertEqual(after, before + 1)

    def test_set_current_does_not_increment_content_version(self):
        self._init()
        before = self._record()["content_version"]
        _run(["set-current", "--path", self.agenda_path, "--item-id", "01"])
        after = self._record()["content_version"]
        self.assertEqual(after, before)

    def test_set_current_updates_current_item_id(self):
        self._init()
        _run(["set-current", "--path", self.agenda_path, "--item-id", "02"])
        self.assertEqual(self._record()["current_item_id"], "02")


class StructuralJudgmentGateTest(AgendaStoreTestCase):
    """FNC-012: structural_judgment.recorded が True になるまで個別項目の遷移を拒否する。"""

    def test_update_rejected_before_structural_judgment_recorded(self):
        self._init()
        result = self._update({"id": "01", "title": "項目1", "status": "未着手"})
        self.assertEqual(result["status"], "error")
        self.assertIn("structural_judgment.recorded", result["missing_fields"])

    def test_update_allowed_after_structural_judgment_recorded(self):
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        result = self._update({"id": "01", "title": "項目1", "status": "未着手"})
        self.assertEqual(result["status"], "ok")

    def test_record_structural_judgment_increments_content_version(self):
        self._init()
        before = self._record()["content_version"]
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        after = self._record()["content_version"]
        self.assertEqual(after, before + 1)

    def test_record_structural_judgment_rejects_empty_note(self):
        self._init()
        result = _run(["record-structural-judgment", "--path", self.agenda_path, "--note", ""])
        self.assertEqual(result["status"], "error")

    def test_record_structural_judgment_rejects_whitespace_only_note(self):
        self._init()
        result = _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "   "])
        self.assertEqual(result["status"], "error")


class TransitionRejectionTest(AgendaStoreTestCase):
    """DES-075 §5.1: 状態遷移の必要条件を満たさない更新は拒否され、ファイルへ永続化されない。"""

    def setUp(self):
        super().setUp()
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])

    def test_terminal_transition_without_background_essence_is_rejected(self):
        result = self._update({"id": "01", "title": "項目1", "status": "決着"})
        self.assertEqual(result["status"], "error")
        self.assertIn("background", result["missing_fields"])
        self.assertIn("essence", result["missing_fields"])
        record = self._record()
        self.assertEqual(record["items"], [])

    def test_terminal_transition_with_background_essence_succeeds(self):
        result = self._update(
            {
                "id": "01",
                "title": "項目1",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
            }
        )
        self.assertEqual(result["status"], "ok")

    def test_non_status_patch_does_not_run_transition_validation(self):
        self._update({"id": "01", "title": "項目1", "status": "未着手"})
        result = self._update({"id": "01", "recommendation": "推奨内容"})
        self.assertEqual(result["status"], "ok")


class VerificationRejectionTest(AgendaStoreTestCase):
    """FNC-011: referenced/reason 必須の拒否（採否によらず検証を要求する）。"""

    def setUp(self):
        super().setUp()
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        self._update({"id": "01", "title": "項目1", "status": "進行中"})

    def test_decision_without_referenced_is_rejected_even_when_adopt(self):
        result = self._update(
            {
                "id": "01",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
                "verification": {"action": "adopt"},
            }
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("verification.referenced", result["missing_fields"])

    def test_adopt_action_with_referenced_and_without_reason_succeeds(self):
        result = self._update(
            {
                "id": "01",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
                "verification": {"action": "adopt", "referenced": "path/to/file.py:1"},
            }
        )
        self.assertEqual(result["status"], "ok")

    def test_reject_action_without_reason_is_rejected(self):
        result = self._update(
            {
                "id": "01",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
                "verification": {"action": "reject", "referenced": "path/to/file.py:1"},
            }
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("verification.reason", result["missing_fields"])

    def test_reject_action_with_reason_and_referenced_succeeds(self):
        result = self._update(
            {
                "id": "01",
                "status": "決着",
                "background": "背景",
                "essence": "本質",
                "verification": {
                    "action": "reject",
                    "referenced": "path/to/file.py:1",
                    "reason": "採らない理由",
                },
            }
        )
        self.assertEqual(result["status"], "ok")


class RenderAutoInvocationTest(AgendaStoreTestCase):
    """DES-075 §8.1: 書き込み成功直後に agenda_render.py が自動的に呼ばれること。
    呼び出しが失敗しても記録側の状態遷移は成立したままであること。"""

    def test_update_triggers_render_html_and_state_js(self):
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        with mock.patch.object(
            agenda_store.agenda_render, "render_agenda_html", wraps=agenda_store.agenda_render.render_agenda_html
        ) as html_spy, mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_state_js",
            wraps=agenda_store.agenda_render.render_agenda_state_js,
        ) as state_spy:
            self._update({"id": "01", "title": "項目1", "status": "未着手"})
        html_spy.assert_called_once()
        state_spy.assert_called_once()

    def test_render_failure_still_persists_record_change(self):
        self._init()
        _run(["record-structural-judgment", "--path", self.agenda_path, "--note", "問題なし"])
        before_version = self._record()["content_version"]
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_html",
            side_effect=RuntimeError("boom"),
        ):
            result = self._update({"id": "01", "title": "項目1", "status": "未着手"})
        self.assertEqual(result["status"], "partial")
        self.assertIn("再描画に失敗", result["message"])
        record = self._record()
        self.assertEqual(record["content_version"], before_version + 1)
        self.assertEqual(record["items"][0]["title"], "項目1")

    def test_set_current_render_failure_is_partial_but_persists(self):
        self._init()
        with mock.patch.object(
            agenda_store.agenda_render,
            "render_agenda_state_js",
            side_effect=RuntimeError("boom"),
        ):
            result = _run(["set-current", "--path", self.agenda_path, "--item-id", "01"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(self._record()["current_item_id"], "01")


class SetCurrentDoesNotRegenerateHtmlTest(AgendaStoreTestCase):
    """set-current が agenda.html 本体を再生成しないこと（DES-075 §3.2・§8.1）。"""

    def test_set_current_does_not_call_render_agenda_html(self):
        self._init()
        with mock.patch.object(agenda_store.agenda_render, "render_agenda_html") as html_mock:
            _run(["set-current", "--path", self.agenda_path, "--item-id", "01"])
        html_mock.assert_not_called()

    def test_set_current_does_not_rewrite_agenda_html_file(self):
        self._init()
        html_path = Path(self.agenda_path).parent / "agenda.html"
        before_content = html_path.read_text(encoding="utf-8")
        _run(["set-current", "--path", self.agenda_path, "--item-id", "01"])
        after_content = html_path.read_text(encoding="utf-8")
        self.assertEqual(before_content, after_content)

    def test_set_current_writes_agenda_state_js(self):
        self._init()
        state_path = Path(self.agenda_path).parent / "agenda_state.js"
        _run(["set-current", "--path", self.agenda_path, "--item-id", "01"])
        self.assertTrue(state_path.exists())


if __name__ == "__main__":
    unittest.main()
