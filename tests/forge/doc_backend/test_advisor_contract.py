#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doc-advisor 契約テスト（設計書 テスト設計「統合テスト」後半・SKILL.md の静的検証）。

doc-advisor は外部 SKILL であり、`Skill` ツール起動を伴う経路はユニットテストで
実行できないため、query 系 SKILL.md の記述を静的に検証して doc-advisor I/F への
依拠を機械検証する。契約テストは固定した版（DocAdvisor 0.4.6）の I/F に対して書く。
I/F の所有は DocAdvisor 側にあるため、契約が改訂された場合は固定点の更新と
本テストの追従を同じ変更で行う。

検証項目:

- `check-toc` へ `--key <category>` と `--max-age 86400`（秒）を渡すこと
- `freshness=fresh` / `freshness=stale` / `status=error` の 3 応答に対する後続分岐
- `stale` 時（索引更新が必要なとき）だけ prepare → `index-docs` → `query-docs` の順になること
- exit code ではなく `status` / `freshness`（応答内容）で分岐すること
  （`stale` × exit code `0` を失敗と誤認しない）
- `reason` 等の補助 field に依存しないこと
- 応答を解析できない、または `status` / `freshness` が既知値以外の場合に
  query を呼ばず失敗すること（防御）
- doc-advisor 経路の query で検索母集団の相違を通知し、doc-db 経路では通知しないこと
- update 経路では `check-toc` を呼ばないこと

書かないもの（acceptance criteria）:

- 鮮度判定規則の内部値に依存する assert。すなわち境界値（差がちょうど閾値のとき）・
  未来時刻の許容幅・ToC 生成時刻の解析可否に結果が依存するテスト。
  これらは doc-advisor の内部判断であり、依存すると doc-advisor 側の内部変更で
  forge のテストが壊れる。末尾の guard テストがこの禁止を機械検査する。

実行:
  python3 -m unittest tests.forge.doc_backend.test_advisor_contract -v
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILLS_DIR = REPO_ROOT / "plugins" / "forge" / "skills"

# query 系 SKILL: category → SKILL.md（category は check-toc / index-docs / query-docs の --key 値）
QUERY_SKILLS = {
    "rules": _SKILLS_DIR / "query-db-rules" / "SKILL.md",
    "specs": _SKILLS_DIR / "query-db-specs" / "SKILL.md",
}

# update 系 SKILL: check-toc を呼ばないことを検証する対象
UPDATE_SKILLS = {
    "rules": _SKILLS_DIR / "update-db-rules" / "SKILL.md",
    "specs": _SKILLS_DIR / "update-db-specs" / "SKILL.md",
}

# 鮮度閾値（24 時間）。forge が所有する方針値で、check-toc へ秒で渡す
MAX_AGE_SECONDS = 86400


def _read_body(skill_path):
    """SKILL.md の frontmatter を除いた本文を返す。"""
    text = skill_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AssertionError(f"{skill_path} に YAML frontmatter がない")
    end = text.find("\n---", 3)
    if end == -1:
        raise AssertionError(f"{skill_path} の frontmatter が閉じていない")
    return text[end + 4:]


def _branch_row_cell(body, skill_path, status_value, freshness_value):
    """check-toc 応答分岐表から `status` / `freshness` に対応する動作セルを返す。

    表の行は `| `<status>` | `<freshness>` | <動作> |` の形。空白量には依存しない。
    """
    if freshness_value is None:
        # error 行の freshness 列は `（`null`）` 表記。列の中身には依存しない
        pattern = r"(?m)^\|\s*`error`\s*\|[^|\n]*\|([^|\n]*)\|"
    else:
        pattern = (
            r"(?m)^\|\s*`" + re.escape(status_value)
            + r"`\s*\|\s*`" + re.escape(freshness_value) + r"`\s*\|([^|\n]*)\|"
        )
    m = re.search(pattern, body)
    if m is None:
        raise AssertionError(
            f"{skill_path.name} に status={status_value} / freshness={freshness_value} "
            f"の分岐行がない（3 応答分岐表の欠落）"
        )
    return m.group(1)


class _ContractBase(unittest.TestCase):
    """query 系 SKILL.md 本文を category ごとに検証する基盤。"""

    def each_query_skill(self):
        for category, path in QUERY_SKILLS.items():
            with self.subTest(skill=path.parent.name):
                yield category, path, _read_body(path)


class TestCheckTocInvocationArgs(_ContractBase):
    """鮮度確認へ渡す引数と閾値: `--key <category> --max-age 86400`（秒）。"""

    def test_check_toc_called_with_key_and_max_age(self):
        for category, path, body in self.each_query_skill():
            invocations = re.findall(r"(?m)^/doc-advisor:check-toc\s+(.*)$", body)
            self.assertEqual(
                len(invocations), 1,
                f"{path.parent.name}: check-toc の起動記述は 1 箇所（1 回だけ呼ぶ）であること",
            )
            args = invocations[0].strip()
            self.assertEqual(
                args, f"--key {category} --max-age {MAX_AGE_SECONDS}",
                f"{path.parent.name}: check-toc へ --key {category} と "
                f"--max-age {MAX_AGE_SECONDS}（秒）を渡すこと",
            )

    def test_max_age_is_owned_by_forge_and_passed_explicitly(self):
        """閾値は forge の方針であり、省略せず毎回明示的に渡す記述があること。"""
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "`--max-age` として毎回明示的に渡す", body,
                f"{path.parent.name}: 閾値を毎回明示的に渡す方針の記述がない",
            )


class TestThreeResponseBranching(_ContractBase):
    """check-toc の 3 応答（fresh / stale / error）に対する後続分岐。"""

    def test_fresh_searches_without_toc_update(self):
        for _category, path, body in self.each_query_skill():
            cell = _branch_row_cell(body, path, "ok", "fresh")
            self.assertIn(
                "ToC を更新せず", cell,
                f"{path.parent.name}: fresh 時は ToC を更新せず検索へ進むこと",
            )

    def test_stale_routes_to_toc_update_step(self):
        for _category, path, body in self.each_query_skill():
            cell = _branch_row_cell(body, path, "ok", "stale")
            self.assertIn(
                "Step 4.3", cell,
                f"{path.parent.name}: stale 時は ToC 更新 Step へ進むこと",
            )
            # ToC 不在は stale に含まれる（不在専用の分岐を持たない）
            self.assertIn(
                "ToC 不在も `stale` に含まれる", cell,
                f"{path.parent.name}: ToC 不在を stale へ畳む契約の記述がない",
            )

    def test_error_fails_without_query_and_without_backend_switch(self):
        for _category, path, body in self.each_query_skill():
            cell = _branch_row_cell(body, path, "error", None)
            self.assertIn(
                "検索を実行せず明示エラー", cell,
                f"{path.parent.name}: status=error 時は検索せず明示エラーとすること",
            )
            self.assertIn(
                "backend を切り替えない", cell,
                f"{path.parent.name}: status=error を backend 切替の事由にしないこと",
            )


class TestStaleOnlyUpdateOrdering(_ContractBase):
    """索引更新が必要なとき（stale）だけ prepare → index-docs → query-docs の順になること。"""

    def _positions(self, body, path):
        """check-toc / prepare / index-docs / query-docs の起動記述の位置と、Step 見出しの位置。"""
        markers = {
            "check_toc": "/doc-advisor:check-toc",
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

    def test_order_is_check_toc_prepare_index_query(self):
        for _category, path, body in self.each_query_skill():
            pos = self._positions(body, path)
            self.assertLess(pos["check_toc"], pos["prepare"],
                            f"{path.parent.name}: 鮮度確認が索引入力準備より先であること")
            self.assertLess(pos["prepare"], pos["index_docs"],
                            f"{path.parent.name}: prepare が index-docs より先であること")
            self.assertLess(pos["index_docs"], pos["query_docs"],
                            f"{path.parent.name}: index-docs が query-docs より先であること")

    def test_prepare_and_index_are_inside_stale_only_step(self):
        """prepare と index-docs は stale 時のみの Step に閉じ、検索 Step には現れないこと。"""
        for _category, path, body in self.each_query_skill():
            stale_step = re.search(r"(?m)^#### Step 4\.3:.*$", body)
            search_step = re.search(r"(?m)^#### Step 4\.4:.*$", body)
            self.assertIsNotNone(stale_step, f"{path.parent.name}: Step 4.3 見出しがない")
            self.assertIsNotNone(search_step, f"{path.parent.name}: Step 4.4 見出しがない")
            self.assertIn(
                "stale 時のみ", stale_step.group(0),
                f"{path.parent.name}: ToC 更新 Step が stale 時のみと明示されていること",
            )
            pos = self._positions(body, path)
            self.assertTrue(
                stale_step.start() < pos["prepare"] < search_step.start(),
                f"{path.parent.name}: prepare は stale 時のみの Step 内にあること",
            )
            self.assertTrue(
                stale_step.start() < pos["index_docs"] < search_step.start(),
                f"{path.parent.name}: index-docs は stale 時のみの Step 内にあること",
            )
            self.assertGreater(
                pos["query_docs"], search_step.start(),
                f"{path.parent.name}: query-docs は検索 Step（Step 4.4）にあること",
            )

    def test_query_runs_only_after_index_success(self):
        """index が成功した場合だけ検索へ進み、失敗時は stale ToC で検索を続行しないこと。"""
        for _category, path, body in self.each_query_skill():
            self.assertRegex(
                body, r"index 成功 → Step 4\.4",
                f"{path.parent.name}: index 成功時のみ検索へ進む記述がない",
            )
            self.assertIn(
                "index 失敗 → stale な ToC で検索を続行せず、明示エラーとして終了する", body,
                f"{path.parent.name}: index 失敗時に検索を続行しない記述がない",
            )


class TestBranchOnResponseContentNotExitCode(_ContractBase):
    """exit code ではなく応答内容（status / freshness）で分岐すること。"""

    def test_branches_on_status_and_freshness_only(self):
        for _category, path, body in self.each_query_skill():
            self.assertRegex(
                body,
                r"`status` / `freshness` \*\*だけ\*\* で分岐する",
                f"{path.parent.name}: status / freshness だけで分岐する宣言がない",
            )

    def test_exit_code_branching_is_forbidden(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "**exit code では分岐しない**", body,
                f"{path.parent.name}: exit code で分岐しない宣言がない",
            )

    def test_stale_with_exit_zero_is_not_treated_as_failure(self):
        """`stale` は正常な判定結果（exit code 0）であり、失敗と誤認しない根拠の明記。"""
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "`stale` は正常な判定結果であり exit code `0` で返る", body,
                f"{path.parent.name}: stale × exit 0 を失敗と誤認しない根拠の記述がない",
            )
            self.assertIn(
                "exit code で分岐すると `stale` を失敗と誤認する", body,
                f"{path.parent.name}: exit code 分岐の誤りの説明がない",
            )


class TestNoAuxiliaryFieldDependence(_ContractBase):
    """`reason` 等の補助 field に依存しないこと。"""

    def test_auxiliary_fields_are_excluded_from_routing_and_judgement(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "`reason` 等の補助 field は診断として", body,
                f"{path.parent.name}: 補助 field の位置づけ（診断のみ）の記述がない",
            )
            self.assertIn(
                "経路選択にも成否判定にも使用しない", body,
                f"{path.parent.name}: 補助 field を経路選択・成否判定に使わない宣言がない",
            )

    def test_no_auxiliary_field_names_in_procedure(self):
        """check-toc の補助 field 名が手順に現れないこと（値が未知でも経路が変わらない）。

        補助 field 名を手順に書くと、その値域追加が forge 側の破壊的変更になる。
        `reason` は「依存しない」宣言の中でのみ言及されるため対象外とする。
        """
        aux_fields = ["`toc_path`", "`age_seconds`", "`max_age_seconds`", "`generated" + "_at`"]
        for _category, path, body in self.each_query_skill():
            for field in aux_fields:
                self.assertNotIn(
                    field, body,
                    f"{path.parent.name}: 補助 field {field} が手順に現れている"
                    f"（補助 field への依存の兆候）",
                )


class TestUnparseableResponseDefense(_ContractBase):
    """応答が解釈できない場合に検索を実行せず失敗すること（縮退しない防御）。"""

    def test_unparseable_or_unknown_values_fail_without_query(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "応答が JSON として解析できない場合、または `status` / `freshness` が既知値以外の場合",
                body,
                f"{path.parent.name}: 解析不能・既知値以外の防御条件の記述がない",
            )
            self.assertIn(
                "**`fresh` とみなす縮退も ToC 作り直し経路への縮退も行わず**", body,
                f"{path.parent.name}: 縮退禁止の記述がない",
            )
            self.assertRegex(
                body,
                r"応答が JSON として解析できない場合[^#]*?検索を実行せず明示エラー",
                f"{path.parent.name}: 解釈不能時に検索せず失敗する記述がない",
            )


class TestPopulationDifferenceNotice(_ContractBase):
    """検索母集団の相違通知は doc-advisor 経路だけに出ること。"""

    def test_notice_present_for_advisor_path_and_absent_for_docdb_path(self):
        for _category, path, body in self.each_query_skill():
            self.assertIn(
                "doc-advisor 経路で検索した場合", body,
                f"{path.parent.name}: doc-advisor 経路の通知条件の記述がない",
            )
            normalized = re.sub(r"\s+", " ", body)
            self.assertIn(
                "検索母集団が doc-db 経路と一致しない可能性があることを通知する", normalized,
                f"{path.parent.name}: 検索母集団相違の通知内容の記述がない",
            )
            self.assertIn(
                "doc-db 経路で完了した検索では出さない", body,
                f"{path.parent.name}: doc-db 経路で通知を出さない限定の記述がない",
            )


class TestUpdatePathDoesNotCallCheckToc(unittest.TestCase):
    """update 経路では check-toc を呼ばないこと（索引の再構築が目的のため）。"""

    def test_update_skills_have_no_check_toc_invocation(self):
        for _category, path in UPDATE_SKILLS.items():
            with self.subTest(skill=path.parent.name):
                body = _read_body(path)
                self.assertNotIn(
                    "/doc-advisor:check-toc", body,
                    f"{path.parent.name}: update 経路に check-toc の起動記述がある",
                )
                # 可用性判定にも check-toc を要求しない（update 経路は index-docs のみ）
                self.assertIn(
                    "`check-toc` の有無は判定に使わない", body,
                    f"{path.parent.name}: update 経路の可用性判定から check-toc を"
                    f"除外する記述がない",
                )


class TestNoDependenceOnAdvisorInternalRules(unittest.TestCase):
    """guard: 判定規則の内部値に依存するテストが本ディレクトリに存在しないこと。

    境界値（差がちょうど閾値）・未来時刻の許容幅・ToC 生成時刻の解析可否は
    doc-advisor の内部判断であり、forge のテストが依存してはならない。
    禁止トークンの検出対象は doc-advisor 契約に関わるテスト群
    （tests/forge/doc_backend と query wrapper テスト）とする。
    トークンは自己一致を避けるため連結で構築する。
    """

    # 内部値依存の兆候となるトークン:
    # - ToC 生成時刻 field 名（解析可否への依存）
    # - 時刻のずれの許容幅の英名（許容幅への依存）
    # - 閾値 86400 秒の境界前後値（境界値への依存）
    FORBIDDEN_TOKENS = [
        "generated" + "_at",
        "sk" + "ew",
        "86" + "399",
        "86" + "401",
    ]

    SCAN_DIRS = [
        REPO_ROOT / "tests" / "forge" / "doc_backend",
        REPO_ROOT / "tests" / "forge" / "query-db-rules",
        REPO_ROOT / "tests" / "forge" / "query-db-specs",
    ]

    def test_no_forbidden_tokens_in_contract_related_tests(self):
        scanned = 0
        for scan_dir in self.SCAN_DIRS:
            self.assertTrue(scan_dir.is_dir(), f"{scan_dir} が存在しない")
            for test_file in sorted(scan_dir.glob("test_*.py")):
                scanned += 1
                content = test_file.read_text(encoding="utf-8")
                for token in self.FORBIDDEN_TOKENS:
                    with self.subTest(file=test_file.name, token=token):
                        self.assertNotIn(
                            token, content,
                            f"{test_file.relative_to(REPO_ROOT)} が doc-advisor の"
                            f"内部判定値に依存する可能性のあるトークン '{token}' を含む",
                        )
        self.assertGreater(scanned, 0, "検査対象のテストファイルが 1 つも見つからない")


if __name__ == "__main__":
    unittest.main()
