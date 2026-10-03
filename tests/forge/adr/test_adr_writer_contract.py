#!/usr/bin/env python3
"""ADR ライター（write-adr SKILL / adr-writer Agent）の契約テスト。

呼び出しの配線、書き込みの範囲、設計フローが ADR の規範を抱えないことを検証する
（REQ-030 FNC-009・FNC-010・FNC-011）。SKILL.md と agent 定義は AI の振る舞いを記述する
文書であり、意味の検査はレビューが担う。本テストは、文面に残る契約の取りこぼしを検出する。

実行:
  python3 -m unittest tests.forge.adr.test_adr_writer_contract -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN = REPO_ROOT / "plugins" / "forge"
WRITE_ADR = PLUGIN / "skills" / "write-adr" / "SKILL.md"
ADR_WRITER = PLUGIN / "agents" / "adr-writer.md"
START_DESIGN = PLUGIN / "skills" / "start-design" / "SKILL.md"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    end = text.find("\n---", 3)
    fields: dict = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.strip().startswith("-"):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


class WriteAdrSkillTest(unittest.TestCase):
    def setUp(self):
        self.text = WRITE_ADR.read_text(encoding="utf-8")
        self.fm = _frontmatter(WRITE_ADR)

    def test_launches_the_declared_agent_with_identification_values_only(self):
        self.assertIn("forge:adr-writer", self.text)
        self.assertIn("adr_dir: {adr_dir}", self.text)
        self.assertIn("request_id: {request_id}", self.text)

    def test_allowed_tools_include_agent(self):
        tools = {t.strip() for t in self.fm["allowed-tools"].split(",")}
        self.assertIn("Agent", tools)

    def test_is_an_inheriting_skill(self):
        """context: fork は採用しない（リファレンスの不具合の記録）。"""
        self.assertNotIn("context", self.fm)
        self.assertNotIn("agent", self.fm)

    def test_is_user_invocable(self):
        self.assertEqual(self.fm.get("user-invocable"), "true")

    def test_states_that_it_does_not_take_over_other_work(self):
        self.assertIn("親が依頼している他の作業を引き継いではならない", self.text)

    def test_does_not_read_adr_norms_itself(self):
        """ADR の書式・規範は、ADR ライターが読む。入口は読まない。"""
        self.assertNotRegex(self.text, r"\$\{CLAUDE_PLUGIN_ROOT\}/docs/adr_(format|principles_spec)\.md")

    def test_passes_free_text_through_files_not_arguments(self):
        for name in ("decision", "change", "context", "alternatives", "approval-quote"):
            self.assertIn(f"adr-${{CLAUDE_SESSION_ID}}-{name}.md", self.text)

    def test_has_defer_finish_and_completion_phase(self):
        self.assertIn("--defer-finish", self.text)
        self.assertIn("/forge:review design", self.text)


class AdrWriterAgentTest(unittest.TestCase):
    def setUp(self):
        self.text = ADR_WRITER.read_text(encoding="utf-8")

    def test_limits_writing_to_the_adr_file(self):
        self.assertIn("書いてよいのは、依頼の `adr_path` が指す ADR ファイルだけ", self.text)

    def test_does_not_ask_the_user(self):
        self.assertIn("利用者に質問しない", self.text)

    def test_reads_the_norms_instead_of_copying_them(self):
        for doc in ("adr_principles_spec.md", "adr_format.md"):
            self.assertIn(f"${{CLAUDE_PLUGIN_ROOT}}/docs/{doc}", self.text)

    def test_returns_nothing_but_the_verdict_for_created(self):
        self.assertIn("「作成した」の一言", self.text)

    def test_records_the_verdict_once_through_the_script(self):
        self.assertIn("adr_exchange.py", self.text)
        self.assertIn("--verdict {created|rejected|insufficient}", self.text)

    def test_one_adr_file_per_feature(self):
        self.assertIn("新しい ADR ファイルを作らない", self.text)

    def test_overturning_rewrites_the_same_section(self):
        self.assertIn("同じ節の「検討した代替案」へ", self.text)
        self.assertIn("失効の印も付けない", self.text)


class StartDesignDoesNotCarryAdrNormsTest(unittest.TestCase):
    """REQ-030 FNC-011: 設計フローが ADR の規範・書式・採番手順を抱えない。"""

    def setUp(self):
        self.text = START_DESIGN.read_text(encoding="utf-8")

    def test_does_not_read_adr_documents(self):
        self.assertNotIn("adr_principles_spec.md", self.text)
        self.assertNotIn("adr_format.md", self.text)

    def test_does_not_hold_adr_numbering_procedure(self):
        self.assertNotRegex(self.text, r"scan_spec_ids\.py\"?\s+ADR")
        self.assertNotIn("ADR --share-prefixes", self.text)

    def test_requests_an_approval_record_through_write_adr(self):
        self.assertIn("/forge:write-adr", self.text)
        self.assertRegex(self.text, r"approval-record")
        self.assertIn("--defer-finish", self.text)


if __name__ == "__main__":
    unittest.main()
