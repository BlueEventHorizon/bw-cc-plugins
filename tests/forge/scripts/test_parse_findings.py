#!/usr/bin/env python3
"""
parse_findings.py のテスト（DES-046 §3.1 / §5 テスト設計）

実測フォーマット（数字付きリスト・複数行にわたる本文・マーカー無し逸脱）からの
抽出を検証する（`tests/forge/review/test_filter_review_history.py` の
importlib 直接ロードパターンを踏襲）。

実行:
  python3 -m unittest tests.forge.review.test_parse_findings -v
"""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "review" / "parse_findings.py"
)

_spec = importlib.util.spec_from_file_location("msg_review_parse_findings", _SCRIPT_PATH)
parse_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parse_mod)


class ParseFindingsTest(unittest.TestCase):
    """parse_findings(): 実測フォーマットからの重大度別抽出（DES-046 §3.1）。"""

    def test_extracts_single_finding_with_severity(self):
        body = (
            "[msg-review] generic review_id=abc round=2\n\n"
            "1. 🔴 critical `plugins/forge/skills/review/scripts/wake_codex.sh:58-59` "
            "— 検証なしにテキストを注入している\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertIn("wake_codex.sh:58-59", findings[0]["text"])
        self.assertEqual(
            findings[0]["location"],
            {
                "path": "plugins/forge/skills/review/scripts/wake_codex.sh",
                "line": 58,
                "end_line": 59,
            },
        )

    def test_extracts_multiple_findings_with_multiline_body(self):
        body = (
            "1. 🔴 critical `a.py:1` — 概要\n"
            "   詳細説明が複数行にわたる場合の2行目\n"
            "   3行目\n"
            "\n"
            "2. 🟡 major `b.sh:2` — 別の指摘\n"
            "\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual([f["severity"] for f in findings], ["critical", "major"])
        self.assertIn("2行目", findings[0]["text"])
        self.assertIn("3行目", findings[0]["text"])
        self.assertNotIn("major", findings[0]["text"])

    def test_completion_line_not_included_in_any_finding(self):
        body = "1. 🟢 minor `c.md:3` — 軽微な指摘\n\nREVIEW_RESULT: approved\n"
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("REVIEW_RESULT", findings[0]["text"])

    def test_returns_empty_list_when_approved_with_no_marker(self):
        """approved 宣言時はマーカー無し説明文があっても空リスト（DES-046 §3.1）。

        approved（指摘なし）と「finding が1件ある」は矛盾するため、承認時は
        fallback を適用しない。
        """
        body = "所見はありません。特に問題は見つかりませんでした。\n\nREVIEW_RESULT: approved\n"
        findings = parse_mod.parse_findings(body)
        self.assertEqual(findings, [])

    def test_does_not_invent_unclassified_finding_without_severity_marker(self):
        """低レベル抽出 API は severity のない本文を finding に変換しない。"""
        body = (
            "対象ファイルに問題があります。修正が必要です。\n\n"
            "REVIEW_RESULT: findings\n"
        )
        self.assertEqual(parse_mod.parse_findings(body), [])

    def test_low_level_extraction_stops_at_first_completion_line(self):
        """低レベル抽出は宣言後のテキストを finding 本文へ混入させない。"""
        body = (
            "1. 🟡 major `a.py:1` — 指摘\n\n"
            "REVIEW_RESULT: findings\n\n"
            "返信する場合:\n"
            "1. 返信本文を一時ファイルに書き出す\n"
            "2. 次のコマンドを実行する:\n"
            "   python3 send.py claude codex - --in-reply-to xxx\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("返信する場合", findings[0]["text"])
        self.assertNotIn("send.py", findings[0]["text"])

    def test_low_level_extraction_stops_at_first_of_multiple_declarations(self):
        body = (
            "1. 🔴 critical `a.py:1` — 指摘\n\n"
            "REVIEW_RESULT: approved\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "critical")

    def test_marker_in_fenced_code_block_is_not_a_finding_start(self):
        """フェンス（```）で囲まれたコード例中のマーカーは finding として抽出しない。

        実 Codex レビューで発見: 返信形式の例をコードブロックで示す際、その中の
        `🔴 critical ...` が誤って finding として抽出されていた。
        """
        body = (
            "返信形式の例:\n"
            "```\n"
            "1. 🔴 critical `example.py:1` — これは例示であり実所見ではない\n"
            "```\n\n"
            "1. 🟡 major `real.py:2` — 本物の指摘\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "major")
        self.assertIn("real.py:2", findings[0]["text"])

    def test_marker_inside_fence_within_finding_body_is_kept_as_continuation(self):
        """finding の本文中にあるコードブロックはその finding の継続として保持する。"""
        body = (
            "1. 🔴 critical `a.py:1` — 概要\n"
            "```python\n"
            "# 修正前のコード\n"
            "```\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertIn("修正前のコード", findings[0]["text"])

    def test_marker_in_indented_code_block_is_not_a_finding_start(self):
        """4スペース/タブインデントのコードブロック中のマーカーは finding として抽出しない。

        実 Codex レビューで発見: `.lstrip()` によってインデントが失われ、インデント
        コードブロック（Markdown のもう一つの標準的なコードブロック記法）内の
        例示マーカーが finding として誤抽出されていた。
        """
        body = (
            "返信形式の例:\n\n"
            "    1. 🔴 critical `example.py:1` — これは例示であり実所見ではない\n\n"
            "1. 🟡 major `real.py:2` — 本物の指摘\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "major")
        self.assertIn("real.py:2", findings[0]["text"])

    def test_marker_in_prose_is_not_a_finding_start(self):
        """行頭以外（説明文中）に出現するマーカーは finding として抽出しない。

        実 Codex レビューで発見の具体例: 「概要: 🟡 major の基準を参照しました。」
        という説明文中のマーカーが誤って finding 化されていた。
        """
        body = (
            "概要: 🟡 major の基準を参照しました。\n\n"
            "1. 🔴 critical `a.py:1` — 本物の指摘\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "critical")
        self.assertNotIn("概要", findings[0]["text"])

    def test_severity_heading_does_not_group_findings(self):
        """`## 🔴 critical` 見出しの配下に並べた所見は抽出しない。

        実測（agent-review 初回実行）: レビュアーが重大度を見出しでグループ化し、
        個々の所見にマーカーを付けなかったため 1 件も抽出されず、`findings` 宣言との
        矛盾でラウンド全体が `failure` になった。見出しから severity を継承させると
        「マーカーのない本文を推測で finding に変換しない」原則を破るため、この形は
        受理しない。マーカーの置き場は依頼テンプレートと Agent 定義が要求する。
        """
        body = (
            "## 🔴 critical\n\n"
            "**read-only が成立していない**\n"
            "`plugins/forge/agents/reviewer.md:4`\n\n"
            "REVIEW_RESULT: findings\n"
        )
        self.assertEqual(parse_mod.parse_findings(body), [])
        result = parse_mod.interpret_response(body)
        self.assertEqual(result["judgment"], "failure")

    def test_returns_empty_list_for_empty_body(self):
        self.assertEqual(parse_mod.parse_findings(""), [])

    def test_text_before_first_marker_is_not_a_finding(self):
        body = (
            "冒頭の前置き文（マーカー無し）\n"
            "1. 🔴 critical `a.py:1` — 指摘\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertNotIn("前置き", findings[0]["text"])


class LocationExtractionTest(unittest.TestCase):
    """path:line の path らしさを決定論的に検証する。"""

    def test_rejects_issue_label_with_or_without_backticks(self):
        self.assertIsNone(parse_mod._extract_location("Issue:123 の参照"))
        self.assertIsNone(parse_mod._extract_location("`Issue:123` の参照"))

    def test_rejects_numeric_pair_with_or_without_backticks(self):
        self.assertIsNone(parse_mod._extract_location("時刻 12:34"))
        self.assertIsNone(parse_mod._extract_location("`12:34`"))

    def test_accepts_relative_path_without_backticks(self):
        self.assertEqual(
            parse_mod._extract_location("src/a.py:12-14 に問題"),
            {"path": "src/a.py", "line": 12, "end_line": 14},
        )

    def test_accepts_absolute_and_windows_paths(self):
        self.assertEqual(
            parse_mod._extract_location("/tmp/project/a.py:8"),
            {"path": "/tmp/project/a.py", "line": 8},
        )
        self.assertEqual(
            parse_mod._extract_location(r"C:\repo\src\a.py:9-10"),
            {"path": r"C:\repo\src\a.py", "line": 9, "end_line": 10},
        )

    def test_accepts_filename_and_conventional_extensionless_names(self):
        cases = {
            "a.py:3": {"path": "a.py", "line": 3},
            "README:4": {"path": "README", "line": 4},
            "`Makefile:5`": {"path": "Makefile", "line": 5},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_mod._extract_location(text), expected)

    def test_conventional_extensionless_names_are_matched_case_insensitively(self):
        """慣用名は表記が揺れる。大文字小文字だけを理由に位置情報を捨てない。

        実測: 本リポジトリのルート直下は小文字の `makefile` であり、`Makefile` だけを
        許容していたため、実在ファイルを指した所見が「位置なし」と判定された。位置欠落は
        1 件でもラウンド全体を `failure` にするため、他の所見もすべて失われた。
        """
        cases = {
            "`makefile:37`": {"path": "makefile", "line": 37},
            "`MAKEFILE:1`": {"path": "MAKEFILE", "line": 1},
            "`readme:2`": {"path": "readme", "line": 2},
            "`dockerfile:9`": {"path": "dockerfile", "line": 9},
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_mod._extract_location(text), expected)

    def test_rejects_wrapping_brackets_and_path_punctuation(self):
        cases = (
            "(src/a.py:12)",
            "[src/a.py:12]",
            "src/a.py,:12",
            "src/a.py):12",
            "「src/a.py:12」",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(parse_mod._extract_location(text))

    def test_rejects_zero_line_and_reversed_range(self):
        self.assertIsNone(parse_mod._extract_location("src/a.py:0"))
        self.assertIsNone(parse_mod._extract_location("src/a.py:12-11"))

    def test_accepts_first_line_and_single_line_range(self):
        self.assertEqual(
            parse_mod._extract_location("src/a.py:1"),
            {"path": "src/a.py", "line": 1},
        )
        self.assertEqual(
            parse_mod._extract_location("src/a.py:12-12"),
            {"path": "src/a.py", "line": 12, "end_line": 12},
        )

    def test_accepts_location_followed_by_prose_punctuation(self):
        self.assertEqual(
            parse_mod._extract_location("src/a.py:12、問題があります"),
            {"path": "src/a.py", "line": 12},
        )


class InterpretResponseTest(unittest.TestCase):
    """interpret_response(): 共通の 3 値判定と fail-closed 契約。"""

    def test_approved(self):
        self.assertEqual(
            parse_mod.interpret_response("問題ありません。\nREVIEW_RESULT: approved\n"),
            {"judgment": "approved", "findings": []},
        )

    def test_findings_with_path_location(self):
        result = parse_mod.interpret_response(
            "1. 🟡 major `src/a.py:12` — 指摘\nREVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "findings")
        self.assertEqual(
            result["findings"][0]["location"], {"path": "src/a.py", "line": 12}
        )

    def test_findings_with_explicit_unknown_location(self):
        result = parse_mod.interpret_response(
            "1. 🟢 minor 位置未確定 — 横断的な指摘\nREVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "findings")
        self.assertEqual(result["findings"][0]["location"], {"unknown": True})

    def test_missing_location_is_accepted_as_unknown(self):
        """位置表記が無い所見は位置未確定として受理し、`warnings` で件数を返す。"""
        result = parse_mod.interpret_response(
            "1. 🔴 critical 位置のない指摘\nREVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "findings")
        self.assertEqual(result["findings"][0]["location"], {"unknown": True})
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("1", result["warnings"][0])

    def test_one_missing_location_does_not_discard_other_findings(self):
        """1 件の位置欠落で他の所見を捨てない。

        実測: 16 件の所見のうち 15 件が完全な位置情報を持っていたのに、1 件の表記が
        許容形と合わなかっただけでラウンド全体が `failure` になり全件失われた。
        """
        result = parse_mod.interpret_response(
            "1. 🔴 critical `src/a.py:1` — 位置のある指摘\n"
            "2. 🟡 major 位置のない指摘\n"
            "3. 🟢 minor `src/b.py:2` — 位置のある指摘\n"
            "REVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "findings")
        self.assertEqual(len(result["findings"]), 3)
        self.assertEqual(result["findings"][0]["location"], {"path": "src/a.py", "line": 1})
        self.assertEqual(result["findings"][1]["location"], {"unknown": True})
        self.assertEqual(result["findings"][2]["location"], {"path": "src/b.py", "line": 2})
        self.assertIn("2", result["warnings"][0])

    def test_no_warnings_key_when_every_finding_has_a_location(self):
        result = parse_mod.interpret_response(
            "1. 🟡 major `src/a.py:12` — 指摘\nREVIEW_RESULT: findings\n"
        )
        self.assertNotIn("warnings", result)

    def test_non_path_label_is_not_accepted_as_location(self):
        """`Issue:123` を位置として採用しない（位置未確定として受理する）。

        位置として採用しないことと、ラウンドを失敗させることは別である。所見自体は
        残し、位置が確定していないものとして人間の確認へ回す。
        """
        result = parse_mod.interpret_response(
            "1. 🔴 critical Issue:123 — 位置ではない参照\nREVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "findings")
        self.assertEqual(result["findings"][0]["location"], {"unknown": True})
        self.assertEqual(len(result["warnings"]), 1)

    def test_missing_completion_is_failure(self):
        result = parse_mod.interpret_response("1. 🔴 critical `a.py:1` — 指摘\n")
        self.assertEqual(result["judgment"], "failure")

    def test_unknown_completion_is_failure(self):
        result = parse_mod.interpret_response("REVIEW_RESULT: maybe\n")
        self.assertEqual(result["judgment"], "failure")

    def test_empty_findings_declaration_is_failure(self):
        result = parse_mod.interpret_response("REVIEW_RESULT: findings\n")
        self.assertEqual(result["judgment"], "failure")

    def test_missing_severity_marker_is_failure_even_with_location(self):
        result = parse_mod.interpret_response(
            "src/a.py:1 に問題があります。\nREVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "failure")
        self.assertEqual(result["findings"], [])
        self.assertIn("重大度マーカー", result["error"])

    def test_multiple_declarations_are_failure(self):
        result = parse_mod.interpret_response(
            "REVIEW_RESULT: approved\n"
            "1. 🟡 major `a.py:1` — 指摘\n"
            "REVIEW_RESULT: findings\n"
        )
        self.assertEqual(result["judgment"], "failure")
        self.assertIn("厳密に 1 行", result["error"])

    def test_text_after_declaration_is_failure(self):
        result = parse_mod.interpret_response(
            "REVIEW_RESULT: approved\n"
            "追加の説明です。\n"
        )
        self.assertEqual(result["judgment"], "failure")
        self.assertIn("宣言行の後", result["error"])

    def test_finding_after_approved_declaration_is_failure(self):
        result = parse_mod.interpret_response(
            "REVIEW_RESULT: approved\n"
            "1. 🔴 critical `a.py:1` — 宣言後の指摘\n"
        )
        self.assertEqual(result["judgment"], "failure")

    def test_approved_with_finding_before_declaration_is_failure(self):
        result = parse_mod.interpret_response(
            "1. 🟢 minor `a.py:1` — 承認と矛盾する指摘\n"
            "REVIEW_RESULT: approved\n"
        )
        self.assertEqual(result["judgment"], "failure")
        self.assertIn("矛盾", result["error"])

    def test_trailing_blank_lines_after_declaration_are_allowed(self):
        self.assertEqual(
            parse_mod.interpret_response(
                "問題ありません。\nREVIEW_RESULT: approved\n\n"
            ),
            {"judgment": "approved", "findings": []},
        )

    def test_completion_marker_inside_code_fence_does_not_count(self):
        result = parse_mod.interpret_response(
            "例:\n```\nREVIEW_RESULT: approved\n```\n"
        )
        self.assertEqual(result["judgment"], "failure")
        self.assertIn("完了宣言行がありません", result["error"])

    def test_indented_completion_marker_does_not_count(self):
        result = parse_mod.interpret_response("    REVIEW_RESULT: approved\n")
        self.assertEqual(result["judgment"], "failure")

    def test_invalid_locations_are_accepted_as_unknown(self):
        """位置として採用できない表記は、所見を捨てず位置未確定として受理する。

        これらは「位置を書いたつもりだが parser が採用しない形」である。採用しない判断は
        維持しつつ（推測で位置を確定させない）、所見そのものは残して人間の確認へ回す。
        `warnings` に件数が出るため、契約違反であることは可視化される。
        """
        cases = (
            "Issue:123",
            "12:34",
            "(src/a.py:1)",
            "src/a.py:0",
            "src/a.py:3-2",
        )
        for location in cases:
            with self.subTest(location=location):
                result = parse_mod.interpret_response(
                    f"1. 🟡 major {location} — 不正位置\n"
                    "REVIEW_RESULT: findings\n"
                )
                self.assertEqual(result["judgment"], "findings")
                self.assertEqual(result["findings"][0]["location"], {"unknown": True})
                self.assertEqual(len(result["warnings"]), 1)


class MainTest(unittest.TestCase):
    """main(): --body-file 読み込み・単一 JSON 出力（DES-046 §3.1）。"""

    def test_cli_reads_body_file_and_outputs_single_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            body_file = Path(tmpdir) / "body.txt"
            body_file.write_text(
                "1. 🔴 critical `a.py:1` — 指摘\n\nREVIEW_RESULT: findings\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["python3", str(_SCRIPT_PATH), "--body-file", str(body_file)],
                capture_output=True, text=True,
            )

        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["judgment"], "findings")
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(payload["findings"][0]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
