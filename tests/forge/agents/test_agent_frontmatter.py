#!/usr/bin/env python3
"""
forge カスタム Agent (`plugins/forge/agents/*.md`) の frontmatter 妥当性検証

REQ-006 / DES-032 で確定した「fork 型 SKILL 全廃と Agent 起動への置き換え」フィーチャー
(no-fork-skill) は REQ-005 §11 / DES-029 へ fold 済みであり、DES-032 自体はもう存在しない
（`docs/specs/common/design/COMMON-DES-001_skill_base_design.md` §6 が置き換え後の唯一の
正式記録）。tools allowlist は各 Agent の frontmatter（`plugins/forge/agents/*.md`）自体を
正とし、本テストは frontmatter が構文的・慣習的に妥当であることを静的に検証する。

検証内容:
1. 各 .md ファイルが YAML frontmatter を持つこと
2. 必須キー (`name` / `description` / `tools` / `model`) がすべて存在すること
3. `tools` 値が既知 Agent の期待 allowlist と一致すること
   - reviewer: Read, Grep, Glob, Bash（read-only、対象を自分で探索するため Grep/Glob を持つ）
   - evaluator: Read, Grep, Glob, Bash（read-only、reviewer と同じ独立調査能力を持つ）
   - rules-query-worker: Read, Grep, Glob（read-only、内蔵 ToC と文書の Read だけで完結するため Bash を持たない）
   - fixer: 未実装（forge は fixer を分離しない。修正の実施は review 本体が直接担う）
4. `name` がファイル名 (拡張子除く) と一致すること

`plugins/forge/agents/` ディレクトリが存在しない / 空の場合は skipTest する
(F-2 開始時点では Agent ファイルがまだ作成されていないため)。

外部依存 (PyYAML 等) は使用しない。frontmatter は regex で抽出する。

実行:
  python3 -m unittest tests.forge.agents.test_agent_frontmatter -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS_DIR = REPO_ROOT / 'plugins' / 'forge' / 'agents'

# 既知 Agent の tools allowlist (frozenset で順序非依存に比較)。値は各 Agent の
# frontmatter 自体が正であり、本表はその値との回帰比較用スナップショット。
EXPECTED_TOOLS: dict[str, frozenset[str]] = {
    'reviewer': frozenset({'Read', 'Grep', 'Glob', 'Bash'}),
    'evaluator': frozenset({'Read', 'Grep', 'Glob', 'Bash'}),
    'rules-query-worker': frozenset({'Read', 'Grep', 'Glob'}),
}

REQUIRED_KEYS = ('name', 'description', 'tools', 'model')

# frontmatter 内のスカラーキー値 (`key: value`) を抽出する正規表現
_SCALAR_KEY_RE = re.compile(r'(?m)^([A-Za-z_][A-Za-z0-9_-]*):\s*(.+?)\s*$')


def _extract_frontmatter(agent_path: Path) -> str:
    """Agent .md の YAML frontmatter 部分の文字列を返す。frontmatter が無い場合は空文字列。"""
    text = agent_path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        return ''
    end = text.find('\n---', 3)
    if end == -1:
        raise AssertionError(f"{agent_path} の frontmatter が閉じていない")
    return text[3:end]


def _parse_frontmatter_keys(frontmatter: str) -> dict[str, str]:
    """frontmatter からトップレベルスカラーキーを抽出する。"""
    keys: dict[str, str] = {}
    for match in _SCALAR_KEY_RE.finditer(frontmatter):
        key, value = match.group(1), match.group(2)
        keys[key] = value
    return keys


def _parse_tools(value: str) -> frozenset[str]:
    """tools フィールドの値を tool 名の frozenset に正規化する。

    対応する記法:
    - インライン配列: `[Read, Write, Bash]` / `[ Read , Write ]`
    - カンマ区切り文字列: `Read, Write, Bash`
    - 単一文字列: `Read`

    YAML ブロック配列 (`-` 列挙) は対象外 (本テストでは未対応)。
    """
    v = value.strip()
    if v.startswith('[') and v.endswith(']'):
        v = v[1:-1]
    parts = [p.strip().strip('"').strip("'") for p in v.split(',')]
    return frozenset(p for p in parts if p)


def _iter_agent_files() -> list[Path]:
    """plugins/forge/agents/*.md を全件返す。"""
    if not AGENTS_DIR.exists():
        return []
    return sorted(p for p in AGENTS_DIR.glob('*.md') if p.is_file())


class TestAgentFrontmatter(unittest.TestCase):
    """forge カスタム Agent の frontmatter 妥当性を検証する。"""

    def setUp(self):
        self.agents = _iter_agent_files()
        if not self.agents:
            self.skipTest(
                f'{AGENTS_DIR.relative_to(REPO_ROOT)} が存在しないか空。'
                f'F-2/F-3/F-4 で Agent .md が追加されたら検証対象になる',
            )

    def test_frontmatter_present(self):
        for agent_path in self.agents:
            with self.subTest(agent=agent_path.name):
                fm = _extract_frontmatter(agent_path)
                self.assertTrue(
                    fm,
                    f"{agent_path.relative_to(REPO_ROOT)} に YAML frontmatter がない",
                )

    def test_required_keys_present(self):
        for agent_path in self.agents:
            with self.subTest(agent=agent_path.name):
                fm = _extract_frontmatter(agent_path)
                keys = _parse_frontmatter_keys(fm)
                for required in REQUIRED_KEYS:
                    self.assertIn(
                        required,
                        keys,
                        f"{agent_path.relative_to(REPO_ROOT)} の frontmatter に "
                        f"必須キー `{required}` がない",
                    )

    def test_name_matches_filename(self):
        for agent_path in self.agents:
            with self.subTest(agent=agent_path.name):
                fm = _extract_frontmatter(agent_path)
                keys = _parse_frontmatter_keys(fm)
                if 'name' not in keys:
                    continue  # test_required_keys_present が fail で報告する
                expected = agent_path.stem
                actual = keys['name'].strip('"').strip("'")
                self.assertEqual(
                    actual,
                    expected,
                    f"{agent_path.relative_to(REPO_ROOT)} の frontmatter `name: {actual}` "
                    f"がファイル名 `{expected}.md` と一致しない",
                )

    def test_tools_allowlist_matches_known_agents(self):
        for agent_path in self.agents:
            with self.subTest(agent=agent_path.name):
                fm = _extract_frontmatter(agent_path)
                keys = _parse_frontmatter_keys(fm)
                if 'tools' not in keys or 'name' not in keys:
                    continue  # 他テストで報告
                name = keys['name'].strip('"').strip("'")
                expected = EXPECTED_TOOLS.get(name)
                if expected is None:
                    # EXPECTED_TOOLS に未掲載の Agent (将来追加分) はチェック対象外
                    continue
                actual = _parse_tools(keys['tools'])
                self.assertEqual(
                    actual,
                    expected,
                    f"{agent_path.relative_to(REPO_ROOT)} の tools allowlist が "
                    f"想定と一致しない。"
                    f"expected={sorted(expected)} actual={sorted(actual)}",
                )

    def test_reviewer_is_read_only_and_inherits_model(self):
        reviewer = AGENTS_DIR / 'reviewer.md'
        self.assertTrue(reviewer.is_file())
        fm = _parse_frontmatter_keys(_extract_frontmatter(reviewer))
        tools = _parse_tools(fm['tools'])
        self.assertEqual(tools, frozenset({'Read', 'Grep', 'Glob', 'Bash'}))
        self.assertTrue({'Edit', 'Write', 'Agent'}.isdisjoint(tools))
        self.assertEqual(fm['model'].strip('"').strip("'"), 'inherit')
        self.assertEqual(fm.get('permissionMode'), 'plan')

    def test_evaluator_is_read_only_and_inherits_model(self):
        evaluator = AGENTS_DIR / 'evaluator.md'
        self.assertTrue(evaluator.is_file())
        fm = _parse_frontmatter_keys(_extract_frontmatter(evaluator))
        tools = _parse_tools(fm['tools'])
        self.assertEqual(tools, frozenset({'Read', 'Grep', 'Glob', 'Bash'}))
        self.assertTrue({'Edit', 'Write', 'Agent'}.isdisjoint(tools))
        self.assertEqual(fm['model'].strip('"').strip("'"), 'inherit')
        self.assertEqual(fm.get('permissionMode'), 'plan')

    def test_rules_query_worker_is_read_only_and_inherits_model(self):
        worker = AGENTS_DIR / 'rules-query-worker.md'
        self.assertTrue(worker.is_file())
        fm = _parse_frontmatter_keys(_extract_frontmatter(worker))
        tools = _parse_tools(fm['tools'])
        self.assertEqual(tools, frozenset({'Read', 'Grep', 'Glob'}))
        self.assertTrue({'Edit', 'Write', 'Agent', 'Bash'}.isdisjoint(tools))
        self.assertEqual(fm['model'].strip('"').strip("'"), 'inherit')
        self.assertEqual(fm.get('permissionMode'), 'plan')


if __name__ == '__main__':
    unittest.main()
