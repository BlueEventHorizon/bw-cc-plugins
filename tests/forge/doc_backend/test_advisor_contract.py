#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-advisor 契約テスト（DES-057 §9.3 統合テスト・SKILL.md の静的検証）。

doc-advisor は外部 SKILL であり、`Skill` ツール起動を伴う経路はユニットテストで
実行できないため、SKILL.md の記述を静的に検証して doc-advisor I/F への依拠を機械検証する。

検証項目:

- query 経路が prepare → `index-docs` → `query-docs` の順であること
- index が成功した場合だけ検索へ進むこと
- 検索前の索引更新を**常に**行い、更新の要否を forge が判定しないこと
- doc-advisor 経路の query で検索母集団の相違を通知し、doc-db 経路では通知しないこと
- 可用性判定に必要な SKILL が `index-docs` / `query-docs` の 2 つであること

**復活を防ぐ検証** — 次はいずれも「索引の正しさを別の指標で代用する」誤りであり、
再導入されていないことを機械検査する（REQ-014 BL-002 / DES-057 §2.4・§5.1）:

- 経過時間による鮮度判定（閾値・`--max-age` 相当の引数）を持たないこと
- 更新要否の判定を外部 SKILL へ委譲する経路を持たないこと
- バージョン番号、および特定の成果物の有無からバージョンを推測する判定を持たないこと

実行:
  python3 -m unittest tests.forge.doc_backend.test_advisor_contract -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_DIR = REPO_ROOT / "plugins" / "forge" / "skills"

# query 系 SKILL: category → SKILL.md（category は index-docs / query-docs の --key 値）
QUERY_SKILLS = {
    "rules": _SKILLS_DIR / "query-db-rules" / "SKILL.md",
    "specs": _SKILLS_DIR / "query-db-specs" / "SKILL.md",
}

UPDATE_SKILLS = {
    "rules": _SKILLS_DIR / "update-db-rules" / "SKILL.md",
    "specs": _SKILLS_DIR / "update-db-specs" / "SKILL.md",
}

ALL_SKILLS = {**{f"query-{k}": v for k, v in QUERY_SKILLS.items()},
              **{f"update-{k}": v for k, v in UPDATE_SKILLS.items()}}


def _read_body(skill_path):
    """SKILL.md の frontmatter を除いた本文を返す。"""
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError(f"{skill_path} に YAML frontmatter がない")
    end = text.find("\n---", 3)
    if end == -1:
        raise AssertionError(f"{skill_path} の frontmatter が閉じていない")
    return text[end + 4:]


class _ContractBase(unittest.TestCase):
    """query 系 SKILL.md 本文を category ごとに検証する基盤。"""

    def each_query_skill(self):
        for category, path in QUERY_SKILLS.items():
            with self.subTest(skill=path.parent.name):
                yield category, path, _read_body(path)

    def each_skill(self):
        for name, path in ALL_SKILLS.items():
            with self.subTest(skill=name):
                yield name, path, _read_body(path)


class TestUpdateThenQueryOrdering(_ContractBase):
    """query 経路は prepare → index-docs → query-docs の順であること。"""

    def _positions(self, body, path):
        markers = {
            "prepare": "prepare_advisor_index.py",
            "index_docs": "/doc-advisor:index-docs",
            "query_docs": "/doc-advisor:query-docs",
        }
        pos = {}
        for name, marker in markers.items():
            idx = body.find(marker)
            self.assertNotEqual(idx, -1, f"{path.parent.name}: {marker} の記述がない")
            self.assertEqual(
                body.find(marker, idx + 1), -1,
                f"{path.parent.name}: {marker} の起動記述が複数ある（1 回だけ呼ぶ契約）",
            )
            pos[name] = idx
        return pos

    def test_order_is_prepare_index_query(self):
        for _category, path, body in self.each_query_skill():
            pos = self._positions(body, path)
            self.assertLess(pos["prepare"], pos["index_docs"],
                            f"{path.parent.name}: prepare が index-docs より先であること")
            self.assertLess(pos["index_docs"], pos["query_docs"],
                            f"{path.parent.name}: index-docs が query-docs より先であること")

    def test_query_runs_only_after_index_success(self):
        """index が成功した場合だけ検索へ進み、失敗時は検索を続行しないこと。"""
        for _category, path, body in self.each_query_skill():
            self.assertRegex(
                body, r"index 成功 → Step 4\.3",
                f"{path.parent.name}: index 成功時のみ検索へ進む記述がない",
            )
            self.assertIn(
                "index 失敗 → 検索を続行せず、明示エラーとして終了する", body,
                f"{path.parent.name}: index 失敗時に検索を続行しない記述がない",
            )


class TestUpdateIsUnconditional(_ContractBase):
    """検索前の索引更新は常に行い、要否を forge が判定しないこと。

    要否を判定する仕掛けを戻すと、判定の指標（経過時間・外部への委譲）を再び持つことになる。
    """

    def test_update_step_declares_unconditional(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "更新の要否を判定しない", body,
                f"{path.parent.name}: 更新の要否を判定しない旨の明示がない",
            )

    def test_no_conditional_wording_on_update_step(self):
        """更新 Step の見出しが条件付き（「〜のみ」等）でないこと。"""
        for _category, path, body in self.each_query_skill():
            heading = re.search(r"(?m)^#### Step 4\.2:.*$", body)
            self.assertIsNotNone(heading, f"{path.parent.name}: Step 4.2 見出しがない")
            for forbidden in ("のみ", "stale", "鮮度"):
                self.assertNotIn(
                    forbidden, heading.group(0),
                    f"{path.parent.name}: 索引更新 Step の見出しが条件付きになっている",
                )


class TestAvailabilityRequiresTwoSkills(_ContractBase):
    """可用性判定に必要な doc-advisor SKILL は index-docs / query-docs の 2 つ。"""

    def test_query_path_requires_index_and_query(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn("`doc-advisor:index-docs` と `doc-advisor:query-docs` の 2 つ", body,
                          f"{path.parent.name}: 必要 SKILL が 2 つである旨の記述がない")


class TestNoElapsedTimeFreshnessJudgement(unittest.TestCase):
    """経過時間で索引の正しさを判定する仕掛けを持たないこと（復活防止）。

    ToC が正しいかどうかは対象文書が変わったかどうかで決まり、経過時間では決まらない。
    経過時間を指標にすると、文書が変わっていないのに更新を促し、文書が変わっているのに
    更新を省く二方向の誤りが生じる（REQ-014 BL-002）。
    """

    #: 経過時間による判定・その外部委譲を示すトークン
    FORBIDDEN = ("--max-age", "max_age", "86400", "check-toc", "check_toc",
                 "freshness", "advisor_outdated")

    def test_no_forbidden_tokens_in_skills(self):
        for name, path in ALL_SKILLS.items():
            body = _read_body(path)
            for token in self.FORBIDDEN:
                with self.subTest(skill=name, token=token):
                    self.assertNotIn(
                        token, body,
                        f"{name}: 経過時間による鮮度判定に関わる記述（{token}）が復活している",
                    )


class TestNoVersionInference(unittest.TestCase):
    """バージョンを条件にせず、成果物の有無からバージョンを推測しないこと（復活防止）。

    「どの版で何が入ったか」は提供側のリリース履歴であり、forge が抱える情報ではない。
    成果物の有無はバージョンではなく、fork・部分インストール・提供側の改名で推測が誤る。
    """

    def test_no_version_number_conditions(self):
        for name, path in ALL_SKILLS.items():
            body = _read_body(path)
            with self.subTest(skill=name):
                self.assertNotIn(
                    "0.4.6", body,
                    f"{name}: DocAdvisor のバージョン番号が判定・案内に現れている",
                )
                self.assertNotIn(
                    "最小対応バージョン", body,
                    f"{name}: 最小対応バージョンによる判定が復活している",
                )

    def test_version_inference_is_explicitly_forbidden(self):
        """推測しない旨が明文で書かれていること（黙って消えていないこと）。"""
        for name, path in ALL_SKILLS.items():
            body = _read_body(path)
            with self.subTest(skill=name):
                self.assertIn(
                    "バージョンを推測", body,
                    f"{name}: バージョンを推測しない旨の明示がない",
                )


class TestPopulationDifferenceNotice(_ContractBase):
    """doc-advisor 経路の query では検索母集団の相違を通知し、doc-db 経路では通知しないこと。"""

    def test_notice_present_for_advisor_path_and_absent_for_docdb_path(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "検索母集団", body,
                f"{path.parent.name}: 検索母集団の相違に関する通知の記述がない",
            )
            self.assertIn(
                "doc-db 経路で完了した検索では出さない", body,
                f"{path.parent.name}: doc-db 経路では通知しない旨の記述がない",
            )


class TestNoDependenceOnAdvisorInternalRules(unittest.TestCase):
    """doc-advisor の内部判断に依存する assert を本テスト自身が持たないこと。

    索引の差分検出規則・ToC の探索方法・生成時刻の解釈は doc-advisor の内部判断であり、
    依存すると提供側の内部変更で forge のテストが壊れる。
    """

    FORBIDDEN_TOKENS = ("skew", "境界値", "generated_at", "mtime")

    def test_no_forbidden_tokens_in_contract_related_tests(self):
        source = Path(__file__).read_text(encoding="utf-8")
        # 本 guard 自身の定義行は検査対象から外す
        body = source.replace('FORBIDDEN_TOKENS = ("skew", "境界値", "generated_at", "mtime")', "")
        for token in self.FORBIDDEN_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(
                    token, body,
                    f"doc-advisor の内部判断（{token}）に依存する記述がある",
                )


if __name__ == "__main__":
    unittest.main()
