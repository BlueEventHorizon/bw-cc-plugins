#!/usr/bin/env python3
"""
TEST-S001: SKILL.md 本文に Agent ツール / 汎用 Agent を起動 / カスタム Agent を起動 の語があれば
allowed-tools に Agent が含まれること。

実行:
    python3 -m unittest tests.forge.subagent.test_agent_allowedtools_consistency -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'skills'

AGENT_TRIGGERS = [
    'Agent ツール',
    '汎用 Agent を起動',
    'カスタム Agent を起動',
]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """frontmatter を解析して (fields, body) を返す。"""
    if not content.startswith('---'):
        return {}, content
    end = content.find('---', 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end]
    result: dict = {}
    for line in fm_text.split('\n'):
        if ':' in line and not line.strip().startswith('-'):
            key, _, val = line.partition(':')
            result[key.strip()] = val.strip()
    return result, content[end + 3:]


def _strip_exclusions(body: str) -> str:
    """除外スコープを取り除いた本文を返す。
    除外対象:
    1. fenced コードブロック (``` で囲まれた範囲)
    2. ### 制約 / ### 禁止事項 見出し配下 (次の同レベル以上の見出しまで)
    3. blockquote 行 (> で始まる行) — 禁止事項・MANDATORY 注記に使われるため
    """
    lines = body.split('\n')
    result = []
    in_fence = False
    in_excluded_section = False
    excluded_level = 0

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('```'):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        heading_match = re.match(r'^(#{1,6})\s+(.*)', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2)
            if level >= 3 and ('制約' in title or '禁止事項' in title):
                in_excluded_section = True
                excluded_level = level
                continue
            elif in_excluded_section and level <= excluded_level:
                in_excluded_section = False

        if in_excluded_section:
            continue
        if stripped.startswith('>'):
            continue

        result.append(line)

    return '\n'.join(result)


def _check_skill(skill_path: Path) -> list[str]:
    """一貫性違反のメッセージリストを返す (空 = 問題なし)。"""
    content = skill_path.read_text(encoding='utf-8')
    fm, body = _parse_frontmatter(content)

    allowed_tools_raw = fm.get('allowed-tools', '')
    if not allowed_tools_raw:
        return []  # allowed-tools 未定義は全ツール許可とみなしてスキップ

    allowed_tools = {t.strip() for t in allowed_tools_raw.split(',')}
    has_agent = 'Agent' in allowed_tools

    filtered = _strip_exclusions(body)
    violations = []
    for lineno, line in enumerate(filtered.split('\n'), 1):
        for trigger in AGENT_TRIGGERS:
            if trigger in line:
                if not has_agent:
                    violations.append(
                        f'{skill_path.relative_to(REPO_ROOT)} L{lineno}: '
                        f'"{trigger}" が本文にあるが allowed-tools に Agent がない'
                    )
                break

    return violations


class TestAgentAllowedToolsConsistency(unittest.TestCase):
    """TEST-S001: Agent ツール使用宣言と allowed-tools の整合性検証。"""

    def test_all_forge_skills(self) -> None:
        skill_files = sorted(SKILLS_DIR.glob('*/SKILL.md'))
        self.assertGreater(len(skill_files), 0, 'SKILL.md が 1 件も見つからない')

        all_violations: list[str] = []
        for sf in skill_files:
            all_violations.extend(_check_skill(sf))

        self.assertEqual(
            all_violations,
            [],
            'Agent ツール使用宣言と allowed-tools の不整合:\n'
            + '\n'.join(f'  - {v}' for v in all_violations),
        )


if __name__ == '__main__':
    unittest.main()
