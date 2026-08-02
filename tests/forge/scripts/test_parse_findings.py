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

    def test_unclassified_fallback_when_findings_declared_but_no_marker_found(self):
        """findings 宣言時にマーカーが一つも無い実所見は unclassified として fail-closed に返す。

        実 Codex レビューで発見: 空リストにすると受信モードがこの所見を黙って
        落としてしまう。
        """
        body = (
            "対象ファイルに問題があります。修正が必要です。\n\n"
            "REVIEW_RESULT: findings\n"
        )
        findings = parse_mod.parse_findings(body)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["severity"], "unclassified")
        self.assertIn("対象ファイルに問題があります", findings[0]["text"])

    def test_reply_hint_after_completion_line_not_included_in_finding(self):
        """完了宣言行より後（Stop フックの返信ヒント等）は finding の本文に混入しない。

        実 Codex レビューで発見: 本セッションで実際に観測した Stop フックの
        返信ヒント連結と同型の回帰。`continue` で完了宣言行自体だけを読み飛ばすと、
        宣言後の複数行が直前の finding の本文に連結されてしまっていた。
        """
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

    def test_last_completion_line_wins_when_multiple_present(self):
        """本文中に完了宣言行相当の文字列が複数出現する場合、最後の行を採用する。"""
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
        self.assertEqual(len(payload["findings"]), 1)
        self.assertEqual(payload["findings"][0]["severity"], "critical")


if __name__ == "__main__":
    unittest.main()
