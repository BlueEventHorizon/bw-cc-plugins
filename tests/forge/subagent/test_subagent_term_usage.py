#!/usr/bin/env python3
"""
TEST-S004: SKILL.md 内で "subagent" が単独で使われている箇所を列挙 (warning)。

"subagent_type" や "サブエージェント" などの複合表現は検査対象外。
CI を fail させない warning 段階のテスト。

実行:
    python3 -m unittest tests.forge.subagent.test_subagent_term_usage -v
"""

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'skills'

# "subagent" が単独で使われているパターン
# subagent_type / SubAgent (先頭大文字) / sub-agent 等の複合形は除外
_STANDALONE_RE = re.compile(r'\bsubagent\b(?!_type)', re.IGNORECASE)

# fenced コードブロック内は除外
def _strip_code_blocks(body: str) -> str:
    lines = body.split('\n')
    result = []
    in_fence = False
    for line in lines:
        if line.strip().startswith('```'):
            in_fence = not in_fence
            continue
        if not in_fence:
            result.append(line)
    return '\n'.join(result)


def _collect_warnings(skill_path: Path) -> list[str]:
    content = skill_path.read_text(encoding='utf-8')
    # frontmatter を除く
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            body = content[end + 3:]
        else:
            body = content
    else:
        body = content

    filtered = _strip_code_blocks(body)
    warnings = []
    for lineno, line in enumerate(filtered.split('\n'), 1):
        if _STANDALONE_RE.search(line):
            warnings.append(
                f'{skill_path.relative_to(REPO_ROOT)} L{lineno}: '
                f'"subagent" の単独使用: {line.strip()[:80]}'
            )
    return warnings


class TestSubagentTermUsage(unittest.TestCase):
    """TEST-S004: "subagent" の単独使用を warning レベルで報告 (CI は fail させない)。"""

    def test_warn_standalone_subagent(self) -> None:
        skill_files = sorted(SKILLS_DIR.glob('*/SKILL.md'))
        self.assertGreater(len(skill_files), 0, 'SKILL.md が 1 件も見つからない')

        all_warnings: list[str] = []
        for sf in skill_files:
            all_warnings.extend(_collect_warnings(sf))

        if all_warnings:
            print(
                '\n[TEST-S004 WARNING] "subagent" の単独使用が検出されました '
                '(CI は fail しません):\n'
                + '\n'.join(f'  - {w}' for w in all_warnings),
                file=sys.stderr,
            )

        # assertion なし — warning のみ報告するため常に pass
        self.assertTrue(True)


if __name__ == '__main__':
    unittest.main()
