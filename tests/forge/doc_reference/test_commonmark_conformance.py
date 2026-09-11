#!/usr/bin/env python3
"""CommonMark 公式の用例集に対する抽出の適合を測り、後退を検出する。

`ref_extract` は CommonMark の**部分集合**を実装している（DES-081 §1.4）。本テストは
100% 適合を求めるものではなく、**いま一致している用例が一致し続けること**と、
**一致しない用例の集合が増えないこと**を守る。

## 期待値の作り方

用例が持つのは変換後の HTML なので、そこから `<a href>` / `<img src>` を取り出す。
ただし HTML は描画の結果であり、抽出が返す destination とは 2 点で表記が異なる。

| 差 | 由来 | 期待値側の扱い |
| -- | ---- | -------------- |
| `&amp;` 等 | 属性値の HTML エスケープ | `html.unescape` で戻す |
| `%20` 等   | 描画時の percent-encode   | `unquote` で戻す       |

**この 2 つを抽出側へは掛けない。** 両辺へ掛けると、実体参照を解決していない
という抽出側の欠陥（用例 32 / 33 / 503）が打ち消されて見えなくなる。

## 対象外

markdown が生の `<a>` / `<img>` を含む用例は数えない。変換後 HTML ではそれが
そのまま通るため、Markdown のリンクと区別できない。`ref_extract` は HTML を
マスクする（＝拾わないのが正しい）ので、数えると欠陥でないものが不一致になる。
"""

from __future__ import annotations

import html
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "plugins" / "forge" / "scripts" / "doc_reference"))

import ref_extract  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "commonmark" / "spec.json"

_ATTR = re.compile(r'<(?:a[^>]*?\shref|img[^>]*?\ssrc)="([^"]*)"')
_RAW_HTML = re.compile(r"<(?:a|img)[\s>]", re.IGNORECASE)

#: 現状で一致しない用例。**減らすためにあり、増やすためにはない。**
#: 内訳と原因は下表のとおりで、行またぎ以外は既知の欠陥である。
#:
#: | 原因 | 用例 |
#: | ---- | ---- |
#: | destination が行をまたぐ（非対応と宣言済み。DES-081 §1.4） | 193, 195, 198, 510, 541 |
#: | 参照リンクを使用箇所へ解決しない（定義は別に報告する） | 533 |
#: | destination の実体参照・バックスラッシュを解決していない | 23, 32, 33, 202, 502, 503 |
#: | 参照定義の妥当性を行単位でしか見ない（閉じない title が空行をまたぐ形・コンテナ内の定義） | 197, 317 |
#: | 使われていない参照定義も報告する（実在性検査としては意図どおり） | 204, 207, 536, 537, 538, 544, 545, 563, 565, 567, 571, 592 |
#: | autolink の優先順位 | 346 |
#: | email の autolink（文書参照ではないため対象外） | 604, 605 |
KNOWN_DIFFERENCES = frozenset({
    23, 32, 33, 193, 195, 197, 198, 202, 204, 207, 210, 317,
    346, 502, 503, 510, 533, 536, 537, 538, 541, 544, 545,
    563, 565, 567, 571, 592, 604, 605,
})


def _expected(example: dict) -> list:
    return [unquote(html.unescape(x)) for x in _ATTR.findall(example["html"])]


def _actual(markdown: str) -> list:
    result = ref_extract.extract_links(markdown)
    return ([dest for (_lineno, dest, *_rest) in result["inline"]]
            + [dest for (_lineno, _label, dest, *_rest) in result["ref_defs"]])


def _measure():
    examples = json.loads(SPEC.read_text(encoding="utf-8"))
    covered, differing = [], []
    for example in examples:
        markdown = example["markdown"]
        if _RAW_HTML.search(markdown):
            continue
        expected = _expected(example)
        actual = _actual(markdown)
        if not expected and not actual:
            continue
        covered.append(example["example"])
        if sorted(expected) != sorted(actual):
            differing.append((example["example"], markdown, expected, actual))
    return covered, differing


class CommonMarkConformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.covered, cls.differing = _measure()
        cls.differing_ids = frozenset(d[0] for d in cls.differing)

    def test_the_fixture_holds_every_official_example(self):
        """用例集が差し替わっていないことを確かめる（母数が変われば比較が成り立たない）。"""
        self.assertEqual(len(json.loads(SPEC.read_text(encoding="utf-8"))), 652)

    def test_no_previously_matching_example_regresses(self):
        """一致していた用例が不一致になっていない。"""
        regressed = sorted(self.differing_ids - KNOWN_DIFFERENCES)
        detail = "\n".join(
            f"  #{n}\n    markdown: {md!r}\n    期待: {exp}\n    実際: {act}"
            for n, md, exp, act in self.differing if n in set(regressed))
        self.assertEqual(regressed, [], f"適合していた用例が後退しました:\n{detail}")

    def test_known_differences_are_still_differing(self):
        """既知差分が解消されたら一覧から消す（放置すると何が未対応か嘘になる）。"""
        fixed = sorted(KNOWN_DIFFERENCES - self.differing_ids)
        self.assertEqual(
            fixed, [],
            f"既知差分 {fixed} が一致するようになりました。"
            f"KNOWN_DIFFERENCES から削除し、必要なら DES-081 §1.4 も直してください")

    def test_coverage_does_not_shrink(self):
        """対象となる用例が減っていない（抽出が何も返さなくなれば母数が減る）。

        期待と実際がともに空の用例は母数に入らない。したがって**誤検出を直すと
        母数は減る**（生 HTML の優先順位で用例 524、参照定義の妥当性で用例 201 /
        209 / 213 が、期待と同じく空を返すようになった）。
        減らしてよいのは、その用例で何も返さないことが正しいと確かめた場合だけである。
        """
        self.assertGreaterEqual(len(self.covered), 140)


if __name__ == "__main__":
    unittest.main()
