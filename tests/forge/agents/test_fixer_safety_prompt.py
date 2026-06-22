#!/usr/bin/env python3
"""
forge:fixer Agent (`plugins/forge/agents/fixer.md`) の安全境界 system prompt 検証

REQ-006 / DES-032 §3.5 で確定した fixer の安全境界 4 制約が、
fixer.md の system prompt 内に文字列として含まれることを assert する。

検証対象の 4 制約 (DES-032 §3.5):
1. 単一 finding 起動 (§3.5.1): 1 起動につき 1 finding を修正
2. 編集対象パスの allowlist (§3.5.2): orchestrator が prompt に allowed_files を列挙、
   Agent はそれ以外への書き込みを禁止
3. 無関係 refactor の禁止 (§3.5.3): 指摘の修正以外の変更を加えない
4. 修正後の構文検証 (§3.5.4): 言語別構文検査ツール群を呼び出す

`plugins/forge/agents/fixer.md` が未作成 (TASK-010 未完了) の場合は skipTest する。
作成後は assertion が走り、4 制約のいずれかが欠如している場合に fail する。

外部依存 (PyYAML 等) は使用しない (regex / 文字列マッチで判定)。

実行:
  python3 -m unittest tests.forge.agents.test_fixer_safety_prompt -v
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXER_AGENT = REPO_ROOT / 'plugins' / 'forge' / 'agents' / 'fixer.md'


# 各制約について、いずれか 1 つ以上の語が prompt に含まれていれば該当制約が
# 表現されていると見なす (語句のゆらぎを許容しつつ、概念の存在を強制する)。
CONSTRAINTS = {
    '§3.5.1 単一 finding 起動': [
        '単一 finding',
        '1 finding',
        '1 つの finding',
        'finding_id',
        '単一の finding',
        '1 起動につき 1',
    ],
    '§3.5.2 編集対象パスの allowlist': [
        'allowlist',
        'allowed_files',
        '編集対象パス',
        '編集を許可',
        'allowlist 外',
        '許可されたファイル',
    ],
    '§3.5.3 無関係 refactor の禁止': [
        '無関係 refactor',
        '無関係な refactor',
        '指摘の修正以外',
        '指摘の修正のみ',
        '関係ない refactor',
        '修正以外の変更',
    ],
    '§3.5.4 修正後の構文検証': [
        '構文検証',
        '構文チェック',
        'syntax_check',
        'py_compile',
        'dprint check',
        '構文エラー',
    ],
}


class TestFixerSafetyPrompt(unittest.TestCase):
    """fixer.md の system prompt に DES-032 §3.5 の 4 制約が含まれていることを検証。"""

    def setUp(self):
        if not FIXER_AGENT.exists():
            self.skipTest(
                f'{FIXER_AGENT.relative_to(REPO_ROOT)} が未作成 (F-4 / TASK-010 未完了)。'
                f'fixer.md 作成後に assertion が走る',
            )
        self.content = FIXER_AGENT.read_text(encoding='utf-8')

    def test_des032_4_constraints_present(self):
        missing = []
        for constraint_label, candidates in CONSTRAINTS.items():
            if not any(candidate in self.content for candidate in candidates):
                missing.append(
                    f'  - {constraint_label}: '
                    f'いずれかの語が必要 ({" / ".join(repr(c) for c in candidates)})'
                )
        self.assertEqual(
            missing,
            [],
            f'{FIXER_AGENT.relative_to(REPO_ROOT)} の system prompt に '
            f'DES-032 §3.5 の安全境界 4 制約が表現されていない:\n'
            + '\n'.join(missing),
        )


if __name__ == '__main__':
    unittest.main()
