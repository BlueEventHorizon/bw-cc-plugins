#!/usr/bin/env python3
"""回帰防止テスト: `--auto` の対象 severity 一貫性 (Issue #117)。

canonical 決定 (Issue #117): `--auto` は **critical + major** を自動修正し、
**🟢 minor は対象外** とする。minor は「改善提案」であり不具合ではないため、
人間の確認なしに自動修正しない (REQ-004 FNC-404)。

過去、What 層 (REQ-004) / 設計 (DES-015 / DES-028) は `--auto` を「全件 (全指摘)」と
定義していた一方、実装 (review / evaluator SKILL) は「critical + major (minor 除外)」
としており矛盾していた。本テストは canonical 文言への回帰 (minor を含む「全件」記述の
復活) を静的に検出する。

実行:
  python3 -m unittest tests.forge.review.test_auto_severity_consistency -v
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# canonical を定義する文書群 (--auto の severity スコープを記述する SoT / 設計 / 周知)
CANONICAL_DOCS = {
    "REQ-004": "docs/specs/forge/requirements/REQ-004_review_policy.md",
    "DES-015": "docs/specs/forge/design/DES-015_review_workflow_design.md",
    "DES-028": "docs/specs/forge/design/DES-028_review_policy_design.md",
    "review/SKILL.md": "plugins/forge/skills/review/SKILL.md",
    "evaluator/SKILL.md": "plugins/forge/skills/evaluator/SKILL.md",
    "fixer/SKILL.md": "plugins/forge/skills/fixer/SKILL.md",
    "migration_notes": "docs/readme/forge/migration_notes/forge_review_v0.2.md",
}

# minor を含意する旧「全件」記述 (--auto の severity スコープ)。復活したら矛盾再発。
# 注意: `--interactive` の「全件 (AI 推奨 / 吟味)」や、recommendation: fix 件数を指す
# 「全件」は正しい用法のため、--auto の severity スコープに限定した文字列のみを禁止する。
FORBIDDEN_SUBSTRINGS = (
    "全件 (全指摘) 自動修正",   # 旧 --auto 定義 (REQ-004 / DES-015)
    "全件自動修正",             # 旧 --auto ラベル (DES-028 / migration_notes の介入軸表)
    "は全件を対象とする",       # 旧 DES-015 本文 (`--auto` は全件を対象とする)
    "`--auto`: 全件 ",          # 旧 DES-015 表セル (末尾空白で interactive と区別)
    "`--auto` (全件)",          # 旧 migration_notes 移行手順 (--auto を「全件」と注記)
    "🔴 のみ / 全件",           # 旧 3 モード略称 (対話 / 🔴 のみ / 全件)。新表記は「🔴 のみ / 🔴🟡」
)


class TestAutoSeverityConsistency(unittest.TestCase):
    """Issue #117: `--auto` = critical + major (🟢 minor 除外) の文書一貫性。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.texts: dict[str, str] = {}
        for name, rel in CANONICAL_DOCS.items():
            path = REPO_ROOT / rel
            if not path.is_file():
                raise unittest.SkipTest(f"必須ファイルが存在しない: {path}")
            cls.texts[name] = path.read_text(encoding="utf-8")

    def test_no_minor_inclusive_auto_wording(self) -> None:
        """minor を含意する旧「全件」記述が canonical 文書に残っていないこと。"""
        violations = []
        for name, text in self.texts.items():
            for bad in FORBIDDEN_SUBSTRINGS:
                if bad in text:
                    violations.append(f"{name}: {bad!r}")

        self.assertEqual(
            violations,
            [],
            "minor を含む旧『全件』記述 (--auto の severity スコープ) が残存しています。"
            "Issue #117 の canonical は『critical + major (🟢 minor 除外)』です:\n"
            + "\n".join(f"  - {v}" for v in violations),
        )

    def test_req004_states_minor_excluded(self) -> None:
        """REQ-004 (What 層 SoT) が --auto の minor 除外を明記していること。"""
        self.assertIn(
            "🟢 minor を対象外とする",
            self.texts["REQ-004"],
            "REQ-004 FNC-404 に `--auto` の minor 除外規定が明記されていない",
        )

    def test_skill_layer_consistent_critical_major(self) -> None:
        """review / evaluator / fixer SKILL が critical + major (minor 除外) で一貫していること。"""
        self.assertIn(
            "minor は対象外",
            self.texts["review/SKILL.md"],
            "review/SKILL.md に `--auto` の minor 除外記述がない",
        )
        self.assertIn(
            "out_of_scope",
            self.texts["evaluator/SKILL.md"],
            "evaluator/SKILL.md に minor の out_of_scope 記述がない",
        )

    def test_fixer_auto_row_is_critical_major(self) -> None:
        """fixer SKILL の介入軸フィルタ表で `--auto` = critical + major であること。

        fixer の severity フィルタ表は --auto の対象 severity の最終的な実装記述。
        ここが `critical` + `major` + `minor` に退行すると minor も自動修正対象に
        なり Issue #117 の canonical に反する。`--auto` 行が critical + major である
        ことを確認する (minor は (フラグなし) 行のみで許容)。
        """
        fixer = self.texts["fixer/SKILL.md"]
        # `--auto` 行のセル: `critical` + `major` (minor を含まない)
        self.assertIn(
            "`critical` + `major`",
            fixer,
            "fixer/SKILL.md の `--auto` 行が `critical` + `major` になっていない",
        )
        # `--auto` の直後に minor を含める退行 (`--auto` 行が全 severity 化) を弾く
        self.assertNotIn(
            "| `--auto`          | `critical` + `major` + `minor`",
            fixer,
            "fixer/SKILL.md の `--auto` 行に minor が含まれている (minor 除外に反する)",
        )


if __name__ == "__main__":
    unittest.main()
