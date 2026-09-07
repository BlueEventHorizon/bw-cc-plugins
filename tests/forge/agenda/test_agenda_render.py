#!/usr/bin/env python3
"""agenda_render.py（render_agenda_html() / render_agenda_state_js()）のテスト。

DES-077 §5 が列挙する単体テスト対象を検証する。current_item_id・
`.state-dot.current`（旧設計の対話中表示）は存在しないことを積極的に検証する。
自動追従（DES-077 §4.2・§4.3）は、スクリプトの埋め込み・世代番号の一致・
`agenda_state.js` の生成内容を検証する。

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


class FollowScriptTest(unittest.TestCase):
    """DES-077 §4.2・§4.3: 自動追従スクリプトの埋め込みと agenda_state.js の生成。"""

    def test_html_contains_follow_script_with_known_version(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn("agenda_state.js", html_doc)
        self.assertIn("var known = 3;", html_doc)
        self.assertIn("location.reload()", html_doc)

    def test_html_contains_scroll_restore(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-22T00:00:00"
        )
        self.assertIn("sessionStorage", html_doc)
        self.assertIn("agendaScrollY", html_doc)

    def test_html_embeds_null_when_content_version_missing(self):
        agenda = _fixture_agenda()
        del agenda["content_version"]
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-22T00:00:00")
        self.assertIn("var known = null;", html_doc)

    def test_render_agenda_state_js_contains_only_content_version(self):
        state_js = agenda_render.render_agenda_state_js(3)
        self.assertEqual(state_js, 'window.AGENDA_STATE = {"contentVersion": 3};\n')

    def test_render_agenda_state_js_non_int_becomes_null(self):
        state_js = agenda_render.render_agenda_state_js("3")
        self.assertEqual(state_js, 'window.AGENDA_STATE = {"contentVersion": null};\n')


class ProblemRecommendationRowTest(unittest.TestCase):
    """DES-077 §3: problem / recommendation は記入があるときだけ行を出す。"""

    def test_problem_row_rendered_when_filled(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["problem"] = "何が問題かの記述"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-29T00:00:00")
        self.assertIn("<dt>問題</dt><dd>何が問題かの記述</dd>", html_doc)

    def test_problem_row_absent_when_missing_or_empty(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["problem"] = ""
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-29T00:00:00")
        self.assertNotIn("<dt>問題</dt>", html_doc)

    def test_recommendation_row_rendered_with_label_class(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["recommendation"] = "案Aを推奨（確信度: 中）"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-29T00:00:00")
        self.assertIn(
            '<dt class="label-recommend">推奨</dt><dd>案Aを推奨（確信度: 中）</dd>', html_doc
        )

    def test_recommendation_row_absent_when_missing(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-08-29T00:00:00"
        )
        self.assertNotIn("推奨</dt>", html_doc)

    def test_problem_and_recommendation_are_escaped(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["problem"] = "<i>問題</i>"
        agenda["items"][0]["recommendation"] = "<i>推奨</i>"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-08-29T00:00:00")
        self.assertNotIn("<i>問題</i>", html_doc)
        self.assertNotIn("<i>推奨</i>", html_doc)
        self.assertIn("&lt;i&gt;問題&lt;/i&gt;", html_doc)
        self.assertIn("&lt;i&gt;推奨&lt;/i&gt;", html_doc)


class OldVocabularyAbsenceTest(unittest.TestCase):
    """旧設計（current_item_id/.state-dot.current の対話中表示）への言及が
    出力に一切含まれないこと。"""

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


class SeverityLookupTest(unittest.TestCase):
    """DES-080 §4.1: 重大度は `fields` の中を先に、無ければ項目の直下を探索する。"""

    def _section(self, html_doc: str, item_id: str) -> str:
        return html_doc.split(f'<section id="item-{item_id}"')[1].split("<section")[0]

    def test_badge_rendered_when_severity_is_inside_fields(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-09-05T00:00:00"
        )
        self.assertIn('data-severity="critical"', self._section(html_doc, "01"))

    def test_badge_rendered_when_severity_is_directly_on_item(self):
        # wrapper が config.item_fields を空にするため、重大度は項目の直下に来る
        agenda = _fixture_agenda()
        agenda["config"]["item_fields"] = []
        agenda["items"][0]["fields"] = {}
        agenda["items"][0]["severity"] = "major"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn('data-severity="major"', self._section(html_doc, "01"))

    def test_item_level_value_is_used_when_fields_value_is_empty(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"] = {"severity": ""}
        agenda["items"][0]["severity"] = "minor"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn('data-severity="minor"', self._section(html_doc, "01"))

    def test_fields_value_wins_over_item_level_value(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["severity"] = "minor"
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        section = self._section(html_doc, "01")
        self.assertIn('data-severity="critical"', section)
        self.assertNotIn('data-severity="minor"', section)

    def test_no_badge_when_neither_fields_nor_item_has_the_value(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"] = {}
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertNotIn("severity-badge", self._section(html_doc, "01"))

    def test_item_level_value_is_escaped(self):
        agenda = _fixture_agenda()
        agenda["items"][0]["fields"] = {}
        agenda["items"][0]["severity"] = '"><img src=x>'
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertNotIn('"><img src=x>', html_doc)


class TitleFallbackTest(unittest.TestCase):
    """DES-080 §4.2: `title` は必須ではなく、空なら一覧行・見出しに `id` を出す。"""

    def test_summary_row_shows_id_when_title_is_empty(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["title"] = ""
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        table = html_doc.split('<table id="agenda-summary">')[1].split("</table>")[0]
        self.assertIn("<td>02</td><td>02</td>", table)

    def test_summary_row_shows_id_when_title_key_is_absent(self):
        agenda = _fixture_agenda()
        del agenda["items"][1]["title"]
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        table = html_doc.split('<table id="agenda-summary">')[1].split("</table>")[0]
        self.assertIn("<td>02</td><td>02</td>", table)

    def test_item_heading_shows_id_when_title_is_empty(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["title"] = ""
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        section = html_doc.split('<section id="item-02"')[1].split("<section")[0]
        self.assertIn('<span class="item-no">[02]</span>02', section)

    def test_title_is_kept_when_present(self):
        html_doc = agenda_render.render_agenda_html(
            _fixture_agenda(), generated_at="2026-09-05T00:00:00"
        )
        self.assertIn('<span class="item-no">[02]</span>第二項目', html_doc)


class SettlementJudgmentTest(unittest.TestCase):
    """DES-080 §4.4: 決着は decision.by / outcome / reason の 3 値そろい。"""

    def _summary_row(self, html_doc: str, item_id: str) -> str:
        table = html_doc.split('<table id="agenda-summary">')[1].split("</table>")[0]
        for row in table.split("<tr>"):
            if f"<td>{item_id}</td>" in row:
                return row
        self.fail(f"item {item_id} の行が見つからない")

    def _section(self, html_doc: str, item_id: str) -> str:
        return html_doc.split(f'<section id="item-{item_id}"')[1].split("<section")[0]

    def _render_with_decision(self, decision: dict | None) -> str:
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = "背景"
        agenda["items"][1]["essence"] = "本質"
        agenda["items"][1]["decision"] = decision
        return agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")

    def test_only_by_is_undecided(self):
        html_doc = self._render_with_decision({"by": "human"})
        self.assertIn("進行中", self._summary_row(html_doc, "02"))
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_by_and_outcome_is_undecided(self):
        html_doc = self._render_with_decision({"by": "human", "outcome": "adopt"})
        row = self._summary_row(html_doc, "02")
        self.assertIn("進行中", row)
        self.assertNotIn("adopt", row)
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_outcome_and_reason_without_by_is_undecided(self):
        html_doc = self._render_with_decision({"outcome": "adopt", "reason": "妥当"})
        self.assertIn("進行中", self._summary_row(html_doc, "02"))
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_three_values_are_settled(self):
        html_doc = self._render_with_decision(
            {"by": "human", "outcome": "adopt", "reason": "妥当"}
        )
        row = self._summary_row(html_doc, "02")
        self.assertIn("adopt", row)
        self.assertIn("adopt: 妥当", row)
        section = self._section(html_doc, "02")
        self.assertIn("adopt（妥当）", section)
        self.assertNotIn("undecided", section)

    def test_empty_string_in_one_of_three_values_is_undecided(self):
        html_doc = self._render_with_decision(
            {"by": "human", "outcome": "adopt", "reason": ""}
        )
        self.assertIn("進行中", self._summary_row(html_doc, "02"))
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_whitespace_only_value_is_undecided(self):
        """記録側（agenda_schema）は空白のみを空として扱う。提示もそれに揃える。"""
        html_doc = self._render_with_decision(
            {"by": "human", "outcome": "adopt", "reason": "   \n  "}
        )
        self.assertIn("進行中", self._summary_row(html_doc, "02"))
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_non_string_value_is_undecided(self):
        html_doc = self._render_with_decision({"by": "human", "outcome": "adopt", "reason": 1})
        self.assertIn("進行中", self._summary_row(html_doc, "02"))
        self.assertIn('<span class="undecided">(未定)</span>', self._section(html_doc, "02"))

    def test_partial_decision_without_background_and_essence_is_not_started(self):
        agenda = _fixture_agenda()
        agenda["items"][1]["background"] = ""
        agenda["items"][1]["essence"] = ""
        agenda["items"][1]["decision"] = {"by": "human"}
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn("未着手", self._summary_row(html_doc, "02"))


class UnknownKeysTest(unittest.TestCase):
    """DES-080 §2.4・REQ-022 FNC-003: agenda が知らないキーが保存されていても生成できる。"""

    def test_render_succeeds_with_unknown_keys_on_item(self):
        agenda = _fixture_agenda()
        agenda["items"][0].update(
            {
                "text": "所見の本文",
                "location": "plugins/forge/x.py:10",
                "evaluation": {"confidence": "high", "labels": ["a", "b"]},
                "suggested_fix": None,
            }
        )
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn('id="item-01"', html_doc)

    def test_render_succeeds_with_unknown_keys_on_record_root(self):
        agenda = _fixture_agenda(origin="review", extra_metadata={"round": 1})
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn('id="item-01"', html_doc)


class StructuralJudgmentUnrecordedTest(unittest.TestCase):
    """DES-080 §2.1: `start` 直後は構造判断が未記録。その記録でも生成が失敗しない。"""

    def test_render_succeeds_when_structural_judgment_note_is_none(self):
        agenda = _fixture_agenda()
        agenda["structural_judgment"] = {"recorded": False, "note": None}
        html_doc = agenda_render.render_agenda_html(agenda, generated_at="2026-09-05T00:00:00")
        self.assertIn('id="item-01"', html_doc)

    def test_state_js_generation_is_unaffected_by_unrecorded_structural_judgment(self):
        agenda = _fixture_agenda()
        agenda["structural_judgment"] = {"recorded": False, "note": None}
        state_js = agenda_render.render_agenda_state_js(agenda.get("content_version"))
        self.assertEqual(state_js, 'window.AGENDA_STATE = {"contentVersion": 3};\n')


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
