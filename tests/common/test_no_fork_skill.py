#!/usr/bin/env python3
"""
fork 型 SKILL 全廃の段階移行検証テスト

REQ-006 / DES-032 で確定した「fork 型 SKILL 全廃と Agent 起動への置き換え」フィーチャー
(no-fork-skill) の段階移行を補助する静的検証。

検証ロジック:
- WORKING_SKILLS に列挙された SKILL.md の frontmatter に `context: fork` が
  **含まれていない** ことを assert する
- WORKING_SKILLS は段階移行に従って拡張する。各段階で対応する Agent 化が完了した
  SKILL のみを追加する

段階移行と WORKING_SKILLS の対応 (DES-032 §3.7):
- F-2 開始時点 (本テスト新設): 空リスト。fork が消えた SKILL がまだ無いため
- F-2 完了時 (TASK-003 後): plugins/forge/skills/reviewer/SKILL.md を追加
- F-3 完了時 (TASK-006 後): plugins/forge/skills/evaluator/SKILL.md を追加
- F-4 完了時 (TASK-010 後): plugins/forge/skills/fixer/SKILL.md を追加
- F-5 完了時 (TASK-020 後): 旧 SKILL.md が削除され WORKING_SKILLS は不要に。
  ALL_SKILLS_FORK_FREE モード (全 SKILL.md を対象) に切り替える

WORKING_SKILLS が空のときも、ALL_SKILLS_FORK_FREE フラグを True にすると
plugins/*/skills/*/SKILL.md 全件を対象に検査できる (F-5 で True に切り替え)。

旧 tests/forge/subagent/test_fork_skill_frontmatter.py との並存を許容する。
旧テストは F-5 (TASK-020) で削除する。

外部依存 (PyYAML 等) は使用しない (test_query_skill_isolation.py と同じ方針)。
frontmatter は regex で抽出する。

実行:
  python3 -m unittest tests.common.test_no_fork_skill -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# WORKING_SKILLS: 段階移行で「fork 不在」を assert する SKILL.md の相対パス。
# F-2 開始時点では空。reviewer / evaluator / fixer の Agent 化が完了した段階で
# 該当の旧 SKILL.md を追加する。
WORKING_SKILLS: list[Path] = []

# ALL_SKILLS_FORK_FREE: True のとき plugins/*/skills/*/SKILL.md を全件対象に検査する。
# F-5 / TASK-016 で旧 SKILL.md (reviewer / evaluator / fixer) を削除し、本フラグを
# True に切り替えた。以後、新規に context: fork を持つ SKILL.md を追加すると本テストが
# fail する (no-fork-skill フィーチャー完了後の継続的な再発防止)。
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
            self.skipTest('WORKING_SKILLS が空 (F-2 開始時点の状態)。段階移行で拡張する')
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
                    f"`context: fork` が残っている。REQ-006 / DES-032 §3.1 に従い、"
                    f"対応する Agent (plugins/forge/agents/<name>.md) へ移行し "
                    f"`context: fork` を削除すること",
                )


class TestAllSkillsForkFree(unittest.TestCase):
    """F-5 完了後: ALL_SKILLS_FORK_FREE=True で全 SKILL.md に `context: fork` が無いこと。"""

    def test_no_context_fork_anywhere(self):
        if not ALL_SKILLS_FORK_FREE:
            self.skipTest(
                'ALL_SKILLS_FORK_FREE=False (F-5 未完了)。'
                '段階移行が F-5 (TASK-020) まで進んだら True に切り替える',
            )
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
                    f"`context: fork` が残っている。F-5 段階では全 SKILL.md から "
                    f"fork が削除されていなければならない",
                )


if __name__ == '__main__':
    unittest.main()
