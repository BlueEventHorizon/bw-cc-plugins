#!/usr/bin/env python3
"""agenda_render.py（単一公開関数 render_agenda_html()）のテスト。

DES-077 §5 が列挙する単体テスト対象を検証する（TASK-009 acceptance_criteria）。
current_item_id・agenda_state.js 関連の記述、`.state-dot.current` は新設計に
存在しないため、それらへの言及は行わず、存在しないことを積極的に検証する。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_render -v
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
    / "agenda_render.py"
)
_SPEC = importlib.util.spec_from_file_location("agenda_render", _MODULE_PATH)
agenda_render = importlib.util.module_from_spec(_SPEC)
sys.modules["agenda_render"] = agenda_render
_SPEC.loader.exec_module(agenda_render)


def _fixture_agenda(**overrides) -> dict:
    """agenda.json 相当の fixture（DES-075 §4 のスキーマ例に基づく。新スキーマのみ）。

    owner/created_at/current_item_id/status_vocabulary 等の廃止フィールドは含めない。
    """
    agenda = {
        "content_version": 3,
        "config": {
            "identity": "20260819-agenda-design",
            "item_fields": ["severity"],
            "severity_field": "severity",
        },
        "structural_judgment": {"recorded": True, "note": "同型の指摘は無い"},
        "items": [
            {
                "id": "01",
                "title": "第一項目",
                "fields": {"severity": "critical"},
                "background": "背景の記述",
                "essence": "本質の記述",
                "verification": {
                    "referenced": "plugins/forge/x.py:1-2",
                    "action": "adopt",
                    "reason": "",
                },
                "decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"},
                "last_changed_fields": ["decision"],
            },
            {
                "id": "02",
                "title": "第二項目",
                "fields": {"severity": "minor"},
                "background": "",
                "essence": "",
                "decision": None,
                "last_changed_fields": [],
            },
        ],
    }
    agenda.update(overrides)
    return agenda


class PublicApiTest(unittest.TestCase):
    """DES-077 §1: render_agenda_html() 単一の公開関数のみを持つ。"""

    def test_render_agenda_state_js_does_not_exist(self):
        self.assertFalse(hasattr(agenda_render, "render_agenda_state_js"))


class OldVocabularyAbsenceTest(unittest.TestCase):
    """旧設計（current_item_id/agenda_state.js/.state-dot.current）への言及が
    出力に一切含まれないこと。"""

    def test_html_does_not_reference_agenda_state_js(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("agenda_state.js", html_doc)

    def test_html_does_not_contain_data_current_attribute(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("data-current", html_doc)

    def test_html_does_not_contain_state_dot_current_class(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("state-dot current", html_doc)
        self.assertNotIn("state-dot.current", html_doc)

    def test_html_does_not_contain_polling_script(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("<script", html_doc)


class DataChangedAttributeTest(unittest.TestCase):
    """DES-077 §3.1: data-changed 属性の付与（data-current は持たない）。"""

    def test_item_with_last_changed_fields_gets_data_changed_true(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-01" data-changed="true"', html_doc)

    def test_item_without_last_changed_fields_gets_data_changed_false(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-02" data-changed="false"', html_doc)


class ThreeStateDerivationTest(unittest.TestCase):
    """DES-077 §3.3: background/essence/decision の記入有無から3状態を導出する。

    `_derive_status_label()` の出力先は `#agenda-summary` の「状態」列であり
    （`_item_section_html` は背景/本質/決着の3行のみで状態ラベル自体を持たない）、
    ここで導出結果を検証する。
    """

    def _summary_row(self, html_doc: str, item_id: str) -> str:
        table = html_doc.split('<table id="agenda-summary">')[1].split("</table>")[0]
        rows = table.split("<tr>")
        for row in rows:
            if f"<td>{item_id}</td>" in row:
                return row
        self.fail(f"item {item_id} の行が見つからない")

    def test_no_background_and_no_essence_is_not_started(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = ""
        agenda["items"][1]["essence"] = ""
        agenda["items"][1]["decision"] = None
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        self.assertIn("未着手", self._summary_row(html_doc, "02"))

    def test_background_only_is_in_progress(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = "背景だけ書いた"
        agenda["items"][1]["essence"] = ""
        agenda["items"][1]["decision"] = None
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        self.assertIn("進行中", self._summary_row(html_doc, "02"))

    def test_essence_only_is_in_progress(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = ""
        agenda["items"][1]["essence"] = "本質だけ書いた"
        agenda["items"][1]["decision"] = None
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        self.assertIn("進行中", self._summary_row(html_doc, "02"))

    def test_decision_present_shows_outcome_text(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = "背景"
        agenda["items"][1]["essence"] = "本質"
        agenda["items"][1]["decision"] = {"by": "human", "outcome": "取り下げ", "reason": "対応不要"}
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        self.assertIn("取り下げ", self._summary_row(html_doc, "02"))
        # 項目節（<section>）側の「決着」行にも outcome/reason が反映されること
        section = html_doc.split('<section id="item-02"')[1].split("<section")[0]
        self.assertIn("取り下げ", section)


class HtmlEscapeTest(unittest.TestCase):
    """DES-077 §3: 出力値は html.escape() を通す（機密情報・特殊文字を含む本文の安全な出力）。"""

    def test_special_characters_in_background_are_escaped(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["background"] = "<script>alert('x')</script> & \"quoted\""
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("<script>alert", html_doc)
        self.assertIn("&lt;script&gt;", html_doc)
        self.assertIn("&amp;", html_doc)

    def test_special_characters_in_title_are_escaped(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["title"] = "<b>強調</b>"
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn("<b>強調</b>", html_doc)
        self.assertIn("&lt;b&gt;強調&lt;/b&gt;", html_doc)

    def test_special_characters_in_severity_value_are_escaped(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"]["severity"] = '"><img src=x>'
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn('"><img src=x>', html_doc)


class GeneratedNoticeTest(unittest.TestCase):
    """DES-077 §2.1/§3 NFR-001: 生成物であることを示す注記の出力。"""

    def test_generated_notice_is_present(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T09:00:00"
        )
        self.assertIn('class="generated-notice"', html_doc)
        self.assertIn("agenda_render.py", html_doc)
        self.assertIn("2026-08-22T09:00:00", html_doc)
        self.assertIn("手編集しても保存されない", html_doc)

    def test_generated_at_defaults_when_not_provided(self):
        html_doc = agenda_render.render_agenda_html(_fixture_agenda())
        self.assertIn('class="generated-notice"', html_doc)


class SeverityBadgeTest(unittest.TestCase):
    """DES-077 §3.1a・agenda:REQ-019 FNC-009: severity_field 有無でのバッジ出力/非出力。"""

    def test_badge_rendered_when_severity_field_configured(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('class="severity-badge" data-severity="critical"', html_doc)

    def test_no_badge_when_severity_field_is_none(self):
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = None
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertNotIn('class="severity-badge"', html_doc)

    def test_no_badge_when_severity_field_points_to_missing_value(self):
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = "confidence"
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        # item 01/02 いずれも fields に "confidence" キーを持たない
        sections = html_doc.split('<section id="item-01"')[1].split("<section")[0]
        self.assertNotIn("severity-badge", sections)

    def test_no_badge_when_severity_value_is_empty_string(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"]["severity"] = ""
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        sections = html_doc.split('<section id="item-01"')[1].split("<section")[0]
        self.assertNotIn("severity-badge", sections)

    def test_badge_does_not_hardcode_severity_key_name(self):
        # config.severity_field を別のキー名にしても、その値がバッジに使われること
        # （agenda_render.py が "severity" という文字列を決め打ちしていないことの検証）
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = "confidence"
        agenda["items"][0]["fields"] = {"confidence": "confirmed"}
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('data-severity="confirmed"', html_doc)


class TypeValidationTest(unittest.TestCase):
    """config/items の型検証（不正な型で ValueError が送出されること。agenda:REQ-019 NFR-006）。"""

    def test_config_not_a_dict_raises_value_error(self):
        agenda = _fixture_agenda()
        agenda["config"] = "not-a-dict"
        with self.assertRaises(ValueError):
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")

    def test_missing_config_key_raises_value_error(self):
        agenda = _fixture_agenda()
        del agenda["config"]
        with self.assertRaises(ValueError):
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")

    def test_items_not_a_list_raises_value_error(self):
        agenda = _fixture_agenda()
        agenda["items"] = "not-a-list"
        with self.assertRaises(ValueError):
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")

    def test_missing_items_key_raises_value_error(self):
        agenda = _fixture_agenda()
        del agenda["items"]
        with self.assertRaises(ValueError):
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")

    def test_item_not_a_dict_raises_value_error(self):
        agenda = _fixture_agenda()
        agenda["items"][0] = "not-a-dict"
        with self.assertRaises(ValueError):
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")


if __name__ == "__main__":
    unittest.main()
