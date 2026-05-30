#!/usr/bin/env python3
"""回帰防止テスト: Codex / Claude の reviewer 起動経路統一 (Issue #101)。

方針 A (Codex も reviewer fork 経由に統一) に対する**静的検査**。
SKILL.md の実行・agent 起動は runtime 計測できないため、文書・契約の静的検証で
起動経路の回帰を検出する。

検査対象 (Issue #101 受け入れ基準):
  1. review/SKILL.md の**コードブロック内**に run_review_engine.sh の直接起動が残っていない
     (散文での否定言及『orchestrator は run_review_engine.sh を直接起動しない』は許容)
  2. review/SKILL.md が reviewer fork に engine 引数 ({session_dir} {review_type} {engine}) を渡す
  3. reviewer/SKILL.md にのみ run_review_engine.sh の実行記述 (コードブロック) がある
  4. reviewer/SKILL.md の Bash 許可範囲 (散文) に run_review_engine.sh が含まれる
  5. DES-029 §4.2 シーケンス図に engine 分岐 (engine=codex / engine=claude) がある
  6. review / reviewer / DES-029 / DES-015 が reviewer 1 起動原則 (FNC-412) で一致している

実行:
  python3 -m unittest tests.forge.review.test_codex_launch_path -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

REVIEW_SKILL = REPO_ROOT / "plugins" / "forge" / "skills" / "review" / "SKILL.md"
REVIEWER_SKILL = REPO_ROOT / "plugins" / "forge" / "skills" / "reviewer" / "SKILL.md"
DES_029 = (
    REPO_ROOT / "docs" / "specs" / "forge" / "design"
    / "DES-029_skill_agent_launch_contract_design.md"
)
DES_015 = (
    REPO_ROOT / "docs" / "specs" / "forge" / "design"
    / "DES-015_review_workflow_design.md"
)

RUN_ENGINE = "run_review_engine.sh"


def _split_fence(text: str) -> tuple[list[str], list[str]]:
    """Markdown を (コードフェンス内の行, フェンス外の行) に分割する。

    ``` で始まる行はフェンスの開閉トグルとして扱い、どちらにも含めない
    (```mermaid / ```bash のような言語指定付きフェンスも ``` で始まるため拾える)。
    """
    in_fence_lines: list[str] = []
    out_fence_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        (in_fence_lines if in_fence else out_fence_lines).append(line)
    return in_fence_lines, out_fence_lines


class TestCodexLaunchPath(unittest.TestCase):
    """Issue #101: reviewer 起動経路 (Codex / Claude) 統一の静的回帰防止。"""

    @classmethod
    def setUpClass(cls) -> None:
        for path in (REVIEW_SKILL, REVIEWER_SKILL, DES_029, DES_015):
            if not path.is_file():
                raise unittest.SkipTest(f"必須ファイルが存在しない: {path}")
        cls.review = REVIEW_SKILL.read_text(encoding="utf-8")
        cls.reviewer = REVIEWER_SKILL.read_text(encoding="utf-8")
        cls.des029 = DES_029.read_text(encoding="utf-8")
        cls.des015 = DES_015.read_text(encoding="utf-8")

    # 1. review はコードブロックで run_review_engine.sh を直接起動しない
    def test_review_skill_no_direct_engine_launch_in_code_block(self) -> None:
        in_fence, _out = _split_fence(self.review)
        offending = [l.strip() for l in in_fence if RUN_ENGINE in l]
        self.assertEqual(
            offending,
            [],
            "review/SKILL.md のコードブロックに run_review_engine.sh の直接起動が残存:\n"
            + "\n".join(f"  {l}" for l in offending)
            + "\n→ Issue #101: Codex も /forge:reviewer fork 経由に統一し、"
            "orchestrator は run_review_engine.sh を直接起動しないこと",
        )

    # 2. review は reviewer fork に engine 引数を渡す
    def test_review_skill_forks_reviewer_with_engine_arg(self) -> None:
        in_fence, _out = _split_fence(self.review)
        joined = "\n".join(in_fence)
        self.assertIn(
            'args: "{session_dir} {review_type} {engine}"',
            joined,
            "review/SKILL.md の主起動 (reviewer fork) args が "
            '`args: "{session_dir} {review_type} {engine}"` 行になっていない '
            "(--diff-only 例やコマンド構文表の substring では pass させない)",
        )

    # 3. reviewer はコードブロックで run_review_engine.sh を起動する
    def test_reviewer_skill_runs_engine_in_code_block(self) -> None:
        in_fence, _out = _split_fence(self.reviewer)
        self.assertTrue(
            any(RUN_ENGINE in l for l in in_fence),
            "reviewer/SKILL.md のコードブロックに run_review_engine.sh の実行記述が無い "
            "(Codex 経路は reviewer 内の Bash subprocess で起動する)",
        )

    # 4. reviewer の Bash 許可範囲 (散文) に run_review_engine.sh が含まれる
    def test_reviewer_bash_scope_includes_engine(self) -> None:
        _in, out_fence = _split_fence(self.reviewer)
        out_text = "\n".join(out_fence)
        self.assertIn(
            RUN_ENGINE,
            out_text,
            "reviewer/SKILL.md の制約 (Bash 許可範囲) が run_review_engine.sh と整合していない",
        )

    # 5. DES-029 §4.2 シーケンス図に engine 分岐がある
    def test_des029_sequence_has_engine_branch(self) -> None:
        in_fence, _out = _split_fence(self.des029)
        fence_text = "\n".join(in_fence)
        for token in ("engine=codex", "engine=claude"):
            self.assertIn(
                token,
                fence_text,
                f"DES-029 のシーケンス図に {token} 分岐が無い "
                "(§4.2 UC-S1 に Codex CLI / Claude self-review の alt を表現すること)",
            )

    # 6. 4 文書が reviewer 1 起動原則 (FNC-412) で一致している
    def test_single_reviewer_invocation_consistency(self) -> None:
        docs = {
            "review/SKILL.md": self.review,
            "reviewer/SKILL.md": self.reviewer,
            "DES-029": self.des029,
            "DES-015": self.des015,
        }
        for name, text in docs.items():
            self.assertIn(
                "FNC-412",
                text,
                f"{name} が reviewer 1 起動原則 (FNC-412) を参照していない",
            )


if __name__ == "__main__":
    unittest.main()
