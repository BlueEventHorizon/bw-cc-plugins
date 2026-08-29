#!/usr/bin/env python3
"""索引整備の入口が `update-db-*` に一本化されていることの静的検査。

REQ-014 FNC-002 は query wrapper が索引を書き換えないことを定め、DES-057 §5.3 は未整備時の
整備を `update-db-*` への委譲で行うと定める。query 側に同期・索引入力準備の wrapper が
復活すると、索引を整備する経路が 2 つになり、次のいずれかが静かに起こる。

- query が確定させた backend とは別の索引を整備する（DES-057 §5.3 の乖離）
- 検索が読み取り操作の内側で索引を書き換える（REQ-014 BL-002）

いずれもエラーにならないため、ファイルの不在と SKILL.md の記述順で構造的に検査する。
検査項目は DES-057 §9.4 が定める。

**本ファイルの主題は「ファイル構成と記述順」である [MANDATORY]**。SKILL.md 本文が何を書いている / 書いて
いないかという記述内容の契約は `test_advisor_contract.py` が持つ。境界を守らないと、同じ契約が 2 ファイルへ
重複して書かれ、失敗時にどちらの契約が壊れたのかが判別できなくなる（実際に 3 組の重複を作り、レビューで
指摘されて解消した）。新しい検査を足すときは、先に `test_advisor_contract.py` を読んで所在を決める。

実行:
    python3 -m unittest tests.forge.doc_backend.test_index_maintenance_boundary -v
"""

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILLS_ROOT = REPO_ROOT / "plugins" / "forge" / "skills"

QUERY_SKILLS = ("query-db-rules", "query-db-specs")
UPDATE_SKILLS = ("update-db-rules", "update-db-specs")

#: 索引整備を担う wrapper。query 側に存在してはならない。
MAINTENANCE_WRAPPERS = ("sync_documents.py", "prepare_advisor_index.py")

#: 対象文書数を数える wrapper。母集団を所有しない側の件数を数えないため、どの SKILL にも存在してはならない
#: （REQ-014 BL-007 / DES-057 §5.1）。
COUNT_WRAPPER = "count_documents.py"


class TestQuerySkillsHaveNoMaintenanceWrappers(unittest.TestCase):
    def test_query_skills_do_not_own_maintenance_wrappers(self):
        for skill in QUERY_SKILLS:
            for wrapper in MAINTENANCE_WRAPPERS:
                path = SKILLS_ROOT / skill / "scripts" / wrapper
                self.assertFalse(
                    path.is_file(),
                    f"{skill} に索引整備の wrapper が存在する: {wrapper}。"
                    "整備は update-db-* へ委譲する（DES-057 §5.3）",
                )

    def test_query_skills_keep_the_query_wrapper(self):
        """委譲の副作用で検索そのものの入口まで失われていないことを確かめる。"""
        for skill in QUERY_SKILLS:
            path = SKILLS_ROOT / skill / "scripts" / "query_documents.py"
            self.assertTrue(path.is_file(), f"{skill} に query wrapper が無い")

    def test_no_skill_owns_a_document_count_wrapper(self):
        """件数を数える wrapper が復活していないこと（REQ-014 BL-007 / DES-057 §5.1）。

        doc-advisor 経路で索引される文書の集合を決めるのは doc-advisor 側であり、forge が数えた値は
        その件数と一致する保証を持たない。長さだけを取り出す用途でも数えない。
        """
        for skill in QUERY_SKILLS + UPDATE_SKILLS:
            path = SKILLS_ROOT / skill / "scripts" / COUNT_WRAPPER
            self.assertFalse(
                path.is_file(),
                f"{skill} に件数を数える wrapper が存在する: {COUNT_WRAPPER}。"
                "母集団を所有しない側の件数を数えない（REQ-014 BL-007）",
            )

    def test_update_skills_own_maintenance_wrappers(self):
        for skill in UPDATE_SKILLS:
            for wrapper in MAINTENANCE_WRAPPERS:
                path = SKILLS_ROOT / skill / "scripts" / wrapper
                self.assertTrue(
                    path.is_file(),
                    f"{skill} に索引整備の wrapper が無い: {wrapper}",
                )


class TestSkillMdContracts(unittest.TestCase):
    def setUp(self):
        self.query_texts = {
            skill: (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
            for skill in QUERY_SKILLS
        }
        self.update_texts = {
            skill: (SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
            for skill in UPDATE_SKILLS
        }

    def test_query_skills_do_not_count_documents_themselves(self):
        """SKILL.md に件数を数える手順が残っていないこと（REQ-014 BL-007）。"""
        for skill, text in self.query_texts.items():
            self.assertNotIn(
                COUNT_WRAPPER,
                text,
                f"{skill} が件数を数えている（REQ-014 BL-007 / DES-057 §5.1）",
            )

    def test_session_change_check_precedes_backend_resolution(self):
        """セッション内変更の確認が backend 選択より前に置かれること（DES-057 §9.4）。

        後ろに置くと、backend を確定させた後に `update-db-*` へ再入することになり、
        DES-057 §5.1 が禁じる「検索の途中での再入」に当たる。
        """
        for skill, text in self.query_texts.items():
            check_at = text.find("セッション内で")
            resolve_at = text.find("resolve_backend_order.py")
            self.assertNotEqual(check_at, -1, f"{skill} にセッション内変更の確認が無い")
            self.assertNotEqual(resolve_at, -1, f"{skill} に backend 解決の手順が無い")
            self.assertLess(
                check_at,
                resolve_at,
                f"{skill} でセッション内変更の確認が backend 選択より後にある（DES-057 §5.1）",
            )

    def test_advisor_response_is_not_matched_by_wording(self):
        """doc-advisor の応答の文面に一致させて種別を判定していないこと（DES-057 §5.1）。

        `query-docs` が出力形式として規定しているのは `Required documents:` だけである。
        索引未整備時の案内は dispatcher が自分の言葉で組み立てるため文面の保証が無く、
        文字列一致で判定すると成立しない（実測: worker は `- code: TOC_NOT_FOUND` の 2 行ブロックを
        返し、`Query error: TOC_NOT_FOUND` という 1 行はどこにも現れない）。
        """
        for skill, text in self.query_texts.items():
            self.assertNotIn(
                "TOC_NOT_FOUND",
                text,
                f"{skill} が doc-advisor の応答の文面に依存している（DES-057 §5.1）",
            )

    def test_search_success_is_recognized_positively_before_delegation(self):
        """`Required documents:` 形式の肯定的な認識が `update-db-*` の起動より前にあること。

        DES-057 §9.4 の契約項目。順序が逆になると、検索が成立したかを判定する前に整備を起動する
        （不要な整備が走る）ことになり、backend 指定を欠くと update 側が選び直して
        別の索引を整備する（§5.3 の乖離）。
        """
        for skill, text in self.query_texts.items():
            update_skill = skill.replace("query-", "update-")
            invocation = f"/forge:{update_skill} --backend"
            recognize_at = text.find("`Required documents:` 形式であれば")
            invoke_at = text.find(invocation)
            self.assertNotEqual(
                recognize_at,
                -1,
                f"{skill} に検索成功の肯定的な認識が無い（DES-057 §5.1）",
            )
            self.assertNotEqual(
                invoke_at,
                -1,
                f"{skill} に backend 指定つきの委譲（{invocation}）が無い（DES-057 §5.3）",
            )
            self.assertLess(
                recognize_at,
                invoke_at,
                f"{skill} で検索成功の判定が委譲より後にある（DES-057 §5.1）",
            )


if __name__ == "__main__":
    unittest.main()
