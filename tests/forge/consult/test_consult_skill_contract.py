"""consult/SKILL.md の暫定措置の契約テスト（DES-083 §4.3）。

実装期間中の consult は、記録・表示機構（agenda）へ記録せず、提示に必要な状態を会話コンテキストに持つ。
agenda を呼ぶ記述が戻ると、書き換えの途上にある agenda に依存して提示が成立しなくなる。
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "forge"
SKILL_PATH = PLUGIN_ROOT / "skills" / "consult" / "SKILL.md"
REVIEW_SKILL_PATH = PLUGIN_ROOT / "skills" / "review" / "SKILL.md"


class ConsultInterimContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.review = REVIEW_SKILL_PATH.read_text(encoding="utf-8")

    def test_does_not_call_agenda(self):
        for forbidden in ("agenda_wrapper", "scripts/agenda", "--origin", "agenda.json", "agenda.html"):
            self.assertNotIn(forbidden, self.text)
        # コマンドの呼び出し（コードブロック）を 1 つも持たない
        self.assertNotIn("```", self.text)
        self.assertNotIn("python3", self.text)

    def test_keeps_state_in_the_conversation(self):
        self.assertIn("状態は会話に持つ", self.text)
        self.assertIn("会話コンテキストにだけ持つ", self.text)
        self.assertIn("永続化されない", self.text)

    def test_keeps_the_presentation_principles(self):
        """論点ごとの背景・本質・推奨と、1 件ずつの進行は保つ（暫定措置は記録の置き場だけを変える）。"""
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/docs/consult_principles_spec.md", self.text)
        for phrase in (
            "背景と本質、推奨をコンソールへ述べる",
            "1 件ずつ入る",
            "「次はどれを見ますか」「これで進めてよいですか」と聞いてはならない",
            "未判断を「対応不要」へ畳み込まない",
            "自己呼び出しを行わない",
        ):
            self.assertIn(phrase, self.text)

    def test_does_not_resume_an_interrupted_presentation(self):
        self.assertIn("続きから再開する経路は持たない", self.text)

    def test_review_body_does_not_assume_a_consult_record(self):
        """review 本体の手順が、consult の記録（永続化された提示）を前提にしていない。"""
        self.assertNotIn("consult の記録", self.review)
        self.assertNotIn("記録から生成された", self.review)
        self.assertNotIn("固定の主題名", self.review)
        self.assertNotRegex(self.review, r"アジェンダの構造|記録の保存と表示")
        self.assertRegex(self.review, r"提示の状態は永続化されない")


if __name__ == "__main__":
    unittest.main()
