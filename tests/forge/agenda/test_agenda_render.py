#!/usr/bin/env python3
"""agenda_render.py（agenda.html / agenda_state.js 生成）のテスト。

DES-077 §5 が列挙する単体テスト対象を検証する（TASK-002 acceptance_criteria）。
agenda_store.py（TASK-003）の完成を待たず、agenda.json 相当の fixture を
手作りして単体で動作確認する。

実行:
  python3 -m unittest tests.forge.agenda.test_agenda_render -v
"""

import importlib.util
import json
import re
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
    """agenda.json 相当の fixture（DES-075 §4 のスキーマ例に基づく）。"""
    agenda = {
        "owner": "consult",
        "created_at": "2026-08-19T10:00:00",
        "content_version": 7,
        "current_item_id": "02",
        "config": {
            "identity": "20260819-agenda-design",
            "status_vocabulary": ["未着手", "進行中", "決着", "保留", "対象外", "取り下げ"],
            "terminal_statuses": ["決着", "対象外", "取り下げ"],
            "active_statuses": ["未着手", "進行中"],
            "item_fields": ["severity", "confidence"],
            "severity_field": "severity",
        },
        "structural_judgment": {
            "recorded": True,
            "note": "同型の指摘は無い",
            "recorded_at": "2026-08-19T10:05:00",
        },
        "items": [
            {
                "id": "01",
                "title": "第一項目",
                "status": "決着",
                "fields": {"severity": "critical", "confidence": "confirmed"},
                "background": "背景の記述",
                "essence": "本質の記述",
                "recommendation": "推奨の記述",
                "verification": {
                    "referenced": "plugins/forge/x.py:1-2",
                    "action": "adopt",
                    "reason": "",
                },
                "decision": {"by": "human", "outcome": "adopt", "reason": "妥当と判断"},
                "last_changed_fields": ["status", "decision"],
            },
            {
                "id": "02",
                "title": "第二項目",
                "status": "進行中",
                "fields": {"severity": "minor", "confidence": "unconfirmed"},
                "background": "背景2",
                "essence": "本質2",
                "recommendation": "推奨2",
                "verification": None,
                "decision": None,
                "last_changed_fields": [],
            },
        ],
    }
    agenda.update(overrides)
    return agenda


class DataAttributeTest(unittest.TestCase):
    """DES-077 §3.1: data-changed/data-current 属性の付与。"""

    def test_item_with_last_changed_fields_gets_data_changed_true(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-01" data-changed="true" data-current="false"', html_doc)

    def test_item_without_last_changed_fields_gets_data_changed_false(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-02" data-changed="false" data-current="true"', html_doc)

    def test_item_matching_current_item_id_gets_data_current_true(self):
        agenda = _fixture_agenda(current_item_id="01")
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-01" data-changed="true" data-current="true"', html_doc)

    def test_no_current_item_id_gets_data_current_false_for_all(self):
        agenda = _fixture_agenda(current_item_id=None)
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-01" data-changed="true" data-current="false"', html_doc)
        self.assertIn('id="item-02" data-changed="false" data-current="false"', html_doc)

    def test_both_changed_and_current_can_coexist(self):
        agenda = _fixture_agenda(current_item_id="01")
        agenda["items"][0]["last_changed_fields"] = ["status"]
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('id="item-01" data-changed="true" data-current="true"', html_doc)


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


class AgendaStateJsTest(unittest.TestCase):
    """DES-077 §4.2: agenda_state.js の各フィールドが agenda.json と一致すること。"""

    def _parse_state(self, js_text: str) -> dict:
        prefix = "window.AGENDA_DATA = "
        self.assertTrue(js_text.strip().startswith(prefix))
        body = js_text.strip()[len(prefix) :].rstrip(";")
        return json.loads(body)

    def test_content_version_matches_input(self):
        agenda = _fixture_agenda(content_version=42)
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        )
        self.assertEqual(state["contentVersion"], 42)

    def test_current_item_id_matches_input(self):
        agenda = _fixture_agenda(current_item_id="02")
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        )
        self.assertEqual(state["currentItemId"], "02")

    def test_current_item_id_null_is_preserved(self):
        agenda = _fixture_agenda(current_item_id=None)
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        )
        self.assertIsNone(state["currentItemId"])

    def test_changed_item_ids_matches_items_with_non_empty_last_changed_fields(self):
        agenda = _fixture_agenda()
        # item 01 has non-empty last_changed_fields, item 02 has empty list
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        )
        self.assertEqual(state["changedItemIds"], ["01"])

    def test_changed_item_ids_empty_when_no_item_changed(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["last_changed_fields"] = []
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        )
        self.assertEqual(state["changedItemIds"], [])

    def test_updated_at_uses_provided_generated_at(self):
        agenda = _fixture_agenda()
        state = self._parse_state(
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T12:34:56")
        )
        self.assertEqual(state["updatedAt"], "2026-08-22T12:34:56")


class SeverityBadgeTest(unittest.TestCase):
    """DES-077 §3.1a・FNC-009: severity_field 有無でのバッジ出力/非出力。"""

    def test_badge_rendered_when_severity_field_configured(self):
        agenda = _fixture_agenda()
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('class="severity-badge" data-severity="critical"', html_doc)
        self.assertIn('class="severity-badge" data-severity="minor"', html_doc)

    def test_no_badge_when_severity_field_is_none(self):
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = None
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        # CSS 側は常に .severity-badge セレクタを定義してよい（未使用でも害はない）。
        # 検証対象は「バッジ要素自体が出力されないこと」であり、実際の <span> 要素の
        # 有無を見る（class 属性値の文字列一致で判定する）。
        self.assertNotIn('class="severity-badge"', html_doc)

    def test_no_badge_when_severity_field_points_to_missing_value(self):
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = "confidence"
        agenda["items"][0]["fields"] = {}
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        # item 01 has no "confidence" key in fields -> no badge for that item
        sections = html_doc.split('<section id="item-01"')[1].split("<section")[0]
        self.assertNotIn("severity-badge", sections)

    def test_no_badge_when_severity_value_is_empty_string(self):
        # 空文字列は「重要度」列（_summary_row_html）が "-" と表示する判定と
        # 揃え、バッジ側（_severity_badge_html）でも「値なし」として扱う。
        agenda = _fixture_agenda()
        agenda["config"]["severity_field"] = "confidence"
        agenda["items"][0]["fields"]["confidence"] = ""
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
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('data-severity="confirmed"', html_doc)
        self.assertIn('data-severity="unconfirmed"', html_doc)

    def test_critical_major_minor_have_distinct_colors(self):
        # DES-077 §3.1a: 重大度ごとのパステル配色（TASK-008）。
        # critical/major/minor それぞれに専用の CSS ルールがあり、背景色が重複しないこと。
        agenda = _fixture_agenda()
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        colors = {}
        for severity in ("critical", "major", "minor"):
            selector = f'.severity-badge[data-severity="{severity}"]'
            self.assertIn(selector, html_doc)
            rule_start = html_doc.index(selector)
            rule = html_doc[rule_start : rule_start + 200]
            match = re.search(r"background:\s*(#[0-9a-fA-F]{3,6})", rule)
            self.assertIsNotNone(match, f"{severity} 用の background 値が見つからない")
            colors[severity] = match.group(1)
        self.assertEqual(
            len(set(colors.values())), 3, "critical/major/minor の背景色が重複している"
        )

    def test_unknown_severity_value_falls_back_to_default_color(self):
        # DES-077 §3.1a・FNC-009: 中立性。critical/major/minor 以外の値は
        # 呼び出し側が渡した任意の文字列であり、専用の配色ルールを持たず
        # 既定（.severity-badge の共通スタイル）にフォールバックする。
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"]["severity"] = "unknown_value"
        html_doc = agenda_render.render_agenda_html(
            agenda, generated_at="2026-08-22T00:00:00"
        )
        self.assertIn('data-severity="unknown_value"', html_doc)
        self.assertNotIn('.severity-badge[data-severity="unknown_value"]', html_doc)


class MalformedInputTest(unittest.TestCase):
    """不正な入力（items 欠落等）でも例外を投げないこと。"""

    def test_missing_items_key_does_not_raise(self):
        agenda = _fixture_agenda()
        del agenda["items"]
        try:
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
            agenda_render.render_agenda_state_js(agenda, generated_at="2026-08-22T00:00:00")
        except Exception as exc:  # noqa: BLE001 - 例外を投げないことの検証
            self.fail(f"予期しない例外: {exc}")

    def test_missing_config_key_does_not_raise(self):
        agenda = _fixture_agenda()
        del agenda["config"]
        try:
            agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"予期しない例外: {exc}")


if __name__ == "__main__":
    unittest.main()
