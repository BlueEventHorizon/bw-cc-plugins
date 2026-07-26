#!/usr/bin/env python3
"""
fork 型 SKILL 不採用の継続的検証テスト

REQ-005 §11 / DES-029 で確定した「fork 型 SKILL 不採用 + カスタム Agent 起動」方針
(旧 no-fork-skill フィーチャー) の継続的な再発防止用静的検証。
フィーチャー完了後は ALL_SKILLS_FORK_FREE=True で全 SKILL.md を対象に検査する。

検証ロジック:
- ALL_SKILLS_FORK_FREE=True のとき plugins/*/skills/*/SKILL.md 全件の frontmatter に
  `context: fork` が **含まれていない** ことを assert する
- WORKING_SKILLS は段階移行期に使った部分検査リスト。フィーチャー完了後は空のままで運用する
  (新規に context: fork を持つ SKILL を入れたい場合のみ列挙して個別検査できる)

外部依存 (PyYAML 等) は使用しない (test_query_skill_isolation.py と同じ方針)。
frontmatter は regex で抽出する。

実行:
  python3 -m unittest tests.common.test_no_fork_skill -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# WORKING_SKILLS: 個別の SKILL.md に対して「fork 不在」を assert したいときの部分検査リスト。
# 通常は空でよい (ALL_SKILLS_FORK_FREE で全件カバーされるため)。
WORKING_SKILLS: list[Path] = []

# ALL_SKILLS_FORK_FREE: True のとき plugins/*/skills/*/SKILL.md を全件対象に検査する。
# 旧 no-fork-skill フィーチャー (reviewer / evaluator / fixer のカスタム Agent 化) 完了に
# 伴い True に切り替え済み。以後、新規に context: fork を持つ SKILL.md を追加すると本テスト
# が fail する (REQ-005 §11 / DES-029 で確定した fork 不採用方針の継続的な再発防止)。
ALL_SKILLS_FORK_FREE: bool = True

# frontmatter 内の `context: fork` を検出する正規表現。
# 行頭から始まり、値が `fork` (前後の空白許容) であることを要求する。
_CONTEXT_FORK_RE = re.compile(r'(?m)^context:\s*fork\s*$')


def _extract_frontmatter(skill_path: Path) -> str:
    """SKILL.md の YAML frontmatter 部分の文字列を返す。frontmatter が無い場合は空文字列。"""
    text = skill_path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        return ''
    end = text.find('\n---', 3)
    if end == -1:
        raise AssertionError(f"{skill_path} の frontmatter が閉じていない")
    return text[3:end]


def _has_context_fork(skill_path: Path) -> bool:
    """SKILL.md の frontmatter に `context: fork` が含まれているか。"""
    fm = _extract_frontmatter(skill_path)
    return bool(_CONTEXT_FORK_RE.search(fm))


def _iter_all_skills() -> list[Path]:
    """plugins/*/skills/*/SKILL.md を全件返す。"""
    return sorted((REPO_ROOT / 'plugins').glob('*/skills/*/SKILL.md'))


class TestWorkingSkillsForkFree(unittest.TestCase):
    """WORKING_SKILLS に列挙された SKILL.md の frontmatter に `context: fork` が無いこと。"""

    def test_no_context_fork_in_working_skills(self):
        if not WORKING_SKILLS:
            self.skipTest('WORKING_SKILLS が空 (通常運用)。全件検査は TestAllSkillsForkFree が担当する')
        for rel in WORKING_SKILLS:
            skill_path = REPO_ROOT / rel if not rel.is_absolute() else rel
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                self.assertTrue(
                    skill_path.exists(),
                    f"{skill_path.relative_to(REPO_ROOT)} が存在しない。"
                    f"WORKING_SKILLS の登録ミスか、旧 SKILL.md が既に削除されている可能性",
                )
                self.assertFalse(
                    _has_context_fork(skill_path),
                    f"{skill_path.relative_to(REPO_ROOT)} の frontmatter に "
                    f"`context: fork` が残っている。REQ-005 §11 / DES-029 に従い、"
                    f"対応する Agent (plugins/forge/agents/<name>.md) へ移行し "
                    f"`context: fork` を削除すること",
                )


class TestAllSkillsForkFree(unittest.TestCase):
    """ALL_SKILLS_FORK_FREE=True で全 SKILL.md に `context: fork` が無いこと。"""

    def test_no_context_fork_anywhere(self):
        if not ALL_SKILLS_FORK_FREE:
            self.skipTest('ALL_SKILLS_FORK_FREE=False。全件検査を行うには True に切り替える')
        skills = _iter_all_skills()
        self.assertGreater(
            len(skills),
            0,
            'plugins/*/skills/*/SKILL.md が 1 件も見つからない',
        )
        for skill_path in skills:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                self.assertFalse(
                    _has_context_fork(skill_path),
                    f"{skill_path.relative_to(REPO_ROOT)} の frontmatter に "
                    f"`context: fork` が残っている。REQ-005 §11 / DES-029 の "
                    f"fork 不採用方針に違反するため、カスタム Agent (plugins/forge/agents/<name>.md) "
                    f"に置き換えるか、継承型 SKILL に戻すこと",
                )


if __name__ == '__main__':
    unittest.main()
