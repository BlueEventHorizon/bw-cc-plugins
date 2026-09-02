#!/usr/bin/env python3
"""
検索系 SKILL の subagent 隔離 / read-only 制約テスト

COMMON-DES-001 §4 (docs/specs/common/design/COMMON-DES-001_skill_base_design.md)
で採択された以下の制約が、対象 SKILL.md に反映されていることを検証する:

- fork 型 SKILL の frontmatter に `context: fork` が含まれている (§4 規定リスト)
- 全 query-* SKILL の Role 章に read-only 制約 (Edit/Write/MultiEdit/NotebookEdit 禁止) が
  明記されている (B 層: AI 行動規範での逸脱抑止)
- Role 章に git 管理ファイル書き換え禁止が明記されている
- 引数解釈ガード ([MANDATORY]) が含まれている

対象:
- 継承型 dispatcher として Role 制約を維持する SKILL (COMMON-DES-001 §6.3):
  - plugins/forge/skills/query-forge-rules/SKILL.md
- その dispatcher が Agent ツールで起動する read-only worker (COMMON-DES-001 §6.2 の共通設計):
  - plugins/forge/agents/rules-query-worker.md

注: forge の query-db-rules / query-db-specs は doc-advisor:query-docs へ転送する薄いラッパー
（Role 制約・fork を持たない）であり、隔離契約は転送先の doc-advisor が担保するため本検証の対象外。

実行:
  python3 -m unittest tests.common.test_query_skill_isolation -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# COMMON-DES-001 §4 規定リスト: fork 型 SKILL（context: fork 必須）。
# doc-advisor の fork 型 query skill は外部リポジトリへ分離されたため、本リポジトリには
# 配布される fork 型 query skill は存在しない（空リスト）。
FORK_TARGET_SKILLS: list[Path] = []

# Role 制約・引数解釈ガード・出力契約を維持する全 query-* SKILL と、その worker Agent
# (fork 型 + COMMON-DES-001 §6.3 で継承型 dispatcher に再分類された SKILL + 実検索を担う read-only Agent)
CONSTRAINT_TARGET_SKILLS = FORK_TARGET_SKILLS + [
    REPO_ROOT / 'plugins' / 'forge' / 'skills' / 'query-forge-rules' / 'SKILL.md',
    REPO_ROOT / 'plugins' / 'forge' / 'agents' / 'rules-query-worker.md',
]

# dispatcher SKILL と worker Agent の対応。dispatcher が起動する subagent_type と
# worker の frontmatter name が一致していることを検証する
DISPATCHER_WORKER_PAIRS = [
    (
        REPO_ROOT / 'plugins' / 'forge' / 'skills' / 'query-forge-rules' / 'SKILL.md',
        REPO_ROOT / 'plugins' / 'forge' / 'agents' / 'rules-query-worker.md',
        'forge:rules-query-worker',
    ),
]


def _split_frontmatter_body(skill_path: Path):
    """SKILL.md を frontmatter 文字列と本文に分割する。"""
    text = skill_path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        raise AssertionError(f"{skill_path} に YAML frontmatter がない")
    end = text.find('\n---', 3)
    if end == -1:
        raise AssertionError(f"{skill_path} の frontmatter が閉じていない")
    fm = text[3:end]
    body = text[end + 4:]
    return fm, body


class TestQuerySkillFrontmatterFork(unittest.TestCase):
    """fork 型 SKILL の frontmatter に `context: fork` が含まれていることを検証

    対象は COMMON-DES-001 §4 規定リスト（fork 型）のみ。継承型に再分類された
    SKILL（§4.2）は本検証の対象外。
    """

    def test_context_fork_present(self):
        for skill_path in FORK_TARGET_SKILLS:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                fm, _ = _split_frontmatter_body(skill_path)
                self.assertRegex(
                    fm,
                    r'(?m)^context:\s*fork\s*$',
                    f"{skill_path.relative_to(REPO_ROOT)} の frontmatter に "
                    f"`context: fork` がない (COMMON-DES-001 §4 規定リスト違反)"
                )


class TestQuerySkillRoleReadonlyConstraint(unittest.TestCase):
    """Role 章に read-only 制約が明記されていることを検証 (ADR-002 §B / 多重防御 B 層)"""

    REQUIRED_PHRASES = [
        # read-only であることの明記
        'read-only',
        # 禁止される書き込み系ツール (列挙)
        'Edit',
        'Write',
        'MultiEdit',
        'NotebookEdit',
        # git 副作用を伴うコマンド禁止
        'git commit',
        # git 管理ファイル書き換え禁止
        'git 管理ファイル',
        # MANDATORY タグ (制約セクションの強制力を担保)
        '[MANDATORY]',
    ]

    def test_role_section_has_constraints(self):
        for skill_path in CONSTRAINT_TARGET_SKILLS:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                _, body = _split_frontmatter_body(skill_path)
                for phrase in self.REQUIRED_PHRASES:
                    self.assertIn(
                        phrase, body,
                        f"{skill_path.relative_to(REPO_ROOT)} に制約文言 "
                        f"'{phrase}' がない (ADR-002 §B 違反)"
                    )


class TestQuerySkillArgumentGuard(unittest.TestCase):
    """引数解釈ガードが含まれていることを検証 (ADR-002 §C)"""

    def test_argument_interpretation_section(self):
        for skill_path in CONSTRAINT_TARGET_SKILLS:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                _, body = _split_frontmatter_body(skill_path)
                # `### 引数解釈` または `## 引数解釈` 見出しが存在する
                self.assertRegex(
                    body,
                    r'(?m)^#{2,3}\s*引数解釈',
                    f"{skill_path.relative_to(REPO_ROOT)} に "
                    f"`引数解釈` セクションがない (ADR-002 §C 違反)"
                )
                # 命令文を実装指示として解釈しない旨の明記
                self.assertIn(
                    '実装指示として解釈してはならない', body,
                    f"{skill_path.relative_to(REPO_ROOT)} の引数解釈に "
                    f"命令文の解釈ガードがない (ADR-002 §C 違反)"
                )


class TestDispatcherWorkerWiring(unittest.TestCase):
    """dispatcher SKILL が起動する worker と、worker Agent の定義が対応していることを検証

    dispatcher 側は ToC を自分で読まず Agent へ委譲する構成（COMMON-DES-001 §6.3）なので、
    - dispatcher の frontmatter `allowed-tools` に `Agent` がある
    - dispatcher 本文が worker の subagent_type を名指ししている
    - worker の frontmatter `name` が subagent_type の `<plugin>:` 以降と一致する
    - worker の `tools` に書き込み系・Agent が含まれない（read-only worker）
    """

    def test_dispatcher_launches_declared_worker(self):
        for skill_path, agent_path, subagent_type in DISPATCHER_WORKER_PAIRS:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                fm, body = _split_frontmatter_body(skill_path)
                self.assertRegex(
                    fm, r'(?m)^allowed-tools:.*\bAgent\b',
                    f"{skill_path.relative_to(REPO_ROOT)} の allowed-tools に Agent がない",
                )
                self.assertIn(
                    subagent_type, body,
                    f"{skill_path.relative_to(REPO_ROOT)} が worker `{subagent_type}` を名指ししていない",
                )
                self.assertTrue(
                    agent_path.is_file(),
                    f"worker 定義 {agent_path.relative_to(REPO_ROOT)} が存在しない",
                )
                agent_fm, _ = _split_frontmatter_body(agent_path)
                name_match = re.search(r'(?m)^name:\s*(\S+)\s*$', agent_fm)
                self.assertIsNotNone(name_match, f"{agent_path.relative_to(REPO_ROOT)} に name がない")
                self.assertEqual(
                    name_match.group(1), subagent_type.split(':', 1)[1],
                    f"{agent_path.relative_to(REPO_ROOT)} の name が subagent_type と一致しない",
                )
                tools_match = re.search(r'(?m)^tools:\s*(.+?)\s*$', agent_fm)
                self.assertIsNotNone(tools_match, f"{agent_path.relative_to(REPO_ROOT)} に tools がない")
                tools = {t.strip() for t in tools_match.group(1).strip('[]').split(',')}
                self.assertTrue(
                    {'Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'Agent', 'Bash'}.isdisjoint(tools),
                    f"{agent_path.relative_to(REPO_ROOT)} の tools に read-only worker に不要なツールがある: {sorted(tools)}",
                )


class TestQuerySkillReturnContract(unittest.TestCase):
    """最終 return が `Required documents:` 形式に限定されていることを検証"""

    def test_return_contract_documented(self):
        for skill_path in CONSTRAINT_TARGET_SKILLS:
            with self.subTest(skill=str(skill_path.relative_to(REPO_ROOT))):
                _, body = _split_frontmatter_body(skill_path)
                self.assertIn(
                    'Required documents:', body,
                    f"{skill_path.relative_to(REPO_ROOT)} に "
                    f"`Required documents:` 出力契約の記載がない"
                )


if __name__ == '__main__':
    unittest.main()
