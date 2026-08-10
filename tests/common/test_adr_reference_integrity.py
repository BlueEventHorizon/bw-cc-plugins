#!/usr/bin/env python3
"""回帰防止テスト: ADR の参照と書式の整合。

ADR は仕様を書かず参照で示すため、参照が沈黙して腐ると ADR 自体が誤った根拠になる。
ADR は「その提案は検討済みで、こういう理由で採らなかった」と答えるために読まれるので、
宛先を失った参照は誤った見送り判断を生む。

本テストが検査するもの:

- 参照の実在: マークダウンリンクのリンク先ファイル、リンクに添えた `§X.Y`、
  および `ADR-NNN §X.Y` 形式の参照の宛先
- 書式の維持: 旧書式（メタデータ表・ステータス履歴節）への逆戻り、
  節番号の欠落、失効マーカーの誤記

`ADR-NNN §X.Y` は ADR の外（コード・テスト・他の文書）からも書かれるため、
リポジトリ全体を走査する。実際に `check_cmux_available.py` が `ADR-067 §2.1` を
参照しており、節番号が動けば宛先を失う。

実行:
  python3 -m unittest tests.common.test_adr_reference_integrity -v
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECS_DIR = REPO_ROOT / "docs" / "specs"

#: `ADR-NNN §X.Y` 形式の参照を走査する対象。`.claude/` は生成物なので除く。
CROSS_REF_ROOTS = ("docs", "plugins", "tests")
CROSS_REF_SUFFIXES = (".md", ".py", ".sh")

MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+\.md)(?:#[^)]*)?\)")
#: リンク直後に続く `§X.Y`（`§5.2 / §5.6` のように複数続くことがある）。
TRAILING_SECTION_RE = re.compile(r"\A(?:\s*§\d+(?:\.\d+)*(?:\s*/)?)+")
SECTION_RE = re.compile(r"§(\d+(?:\.\d+)*)")
ADR_SECTION_REF_RE = re.compile(r"ADR-(\d{3})\s*§(\d+(?:\.\d+)*)")
HEADING_NUM_RE = re.compile(r"^#{2,6}\s+(\d+(?:\.\d+)*)\.?\s")
INVALIDATION_RE = re.compile(r"⚠️失効")


def adr_files() -> list[Path]:
    return sorted(SPECS_DIR.rglob("ADR-*.md"))


def strip_code(text: str) -> str:
    """フェンス済みコードブロックとインラインコードを空行・空文字へ潰す。

    記法の説明でリンク構文そのものを例示することがあり（`ADR-052 §2.1` が
    `[design_format.md](design_format.md)` を例に挙げている）、これを実リンクとして
    扱うと存在しないファイルを指しているように見える。行番号を保つため、
    フェンス内は行ごと空行に置き換える。
    """
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else re.sub(r"`[^`]*`", "", line))
    return "\n".join(out)


def heading_numbers(path: Path) -> set[str]:
    """文書内の見出しが持つ節番号の集合（`## 1. 概要` → `1`、`### 2.4 …` → `2.4`）。"""
    numbers: set[str] = set()
    for line in strip_code(path.read_text(encoding="utf-8")).splitlines():
        m = HEADING_NUM_RE.match(line)
        if m:
            numbers.add(m.group(1))
    return numbers


class TestADRReferenceIntegrity(unittest.TestCase):
    """ADR が張る参照の宛先が実在すること。"""

    def test_markdown_link_targets_exist(self):
        """マークダウンリンクのリンク先ファイルが実在すること。"""
        broken: list[str] = []
        for path in adr_files():
            for lineno, line in enumerate(
                strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                for m in MD_LINK_RE.finditer(line):
                    target = (path.parent / m.group(1)).resolve()
                    if not target.is_file():
                        rel = path.relative_to(REPO_ROOT)
                        broken.append(f"{rel}:{lineno} -> {m.group(1)}")
        self.assertEqual(
            [],
            broken,
            "ADR のマークダウンリンクが実在しないファイルを指している:\n"
            + "\n".join(broken),
        )

    def test_section_suffix_of_links_exists_in_target(self):
        """リンクに添えた `§X.Y` が参照先文書に実在する見出しであること。"""
        broken: list[str] = []
        for path in adr_files():
            for lineno, line in enumerate(
                strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                for m in MD_LINK_RE.finditer(line):
                    target = (path.parent / m.group(1)).resolve()
                    if not target.is_file():
                        continue  # 上のテストが報告する
                    tail = TRAILING_SECTION_RE.match(line[m.end() :])
                    if not tail:
                        continue
                    available = heading_numbers(target)
                    for number in SECTION_RE.findall(tail.group(0)):
                        if number not in available:
                            rel = path.relative_to(REPO_ROOT)
                            broken.append(
                                f"{rel}:{lineno} -> {m.group(1)} §{number}"
                            )
        self.assertEqual(
            [],
            broken,
            "リンクに添えた節番号が参照先に存在しない:\n" + "\n".join(broken),
        )

    def test_adr_section_references_resolve(self):
        """`ADR-NNN §X.Y` 形式の参照の宛先が実在すること（リポジトリ全体）。"""
        by_number: dict[str, Path] = {}
        for path in adr_files():
            m = re.match(r"ADR-(\d{3})_", path.name)
            if m:
                by_number[m.group(1)] = path

        headings_cache: dict[str, set[str]] = {}
        self_path = Path(__file__).resolve()
        broken: list[str] = []

        for root in CROSS_REF_ROOTS:
            for path in sorted((REPO_ROOT / root).rglob("*")):
                if not path.is_file() or path.suffix not in CROSS_REF_SUFFIXES:
                    continue
                if path.resolve() == self_path:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for lineno, line in enumerate(text.splitlines(), 1):
                    for number, section in ADR_SECTION_REF_RE.findall(line):
                        target = by_number.get(number)
                        rel = path.relative_to(REPO_ROOT)
                        if target is None:
                            broken.append(f"{rel}:{lineno} -> ADR-{number}（不在）")
                            continue
                        if number not in headings_cache:
                            headings_cache[number] = heading_numbers(target)
                        if section not in headings_cache[number]:
                            broken.append(
                                f"{rel}:{lineno} -> ADR-{number} §{section}"
                            )
        self.assertEqual(
            [],
            broken,
            "`ADR-NNN §X.Y` 形式の参照が宛先を失っている:\n" + "\n".join(broken),
        )


class TestADRFormat(unittest.TestCase):
    """ADR が現行書式を保っていること（旧書式への逆戻りの検出）。"""

    def test_no_legacy_sections(self):
        """`## メタデータ` / `## 5. ステータス履歴` が存在しないこと。"""
        found: list[str] = []
        for path in adr_files():
            for lineno, line in enumerate(
                strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                if line.startswith("## メタデータ") or line.startswith(
                    "## 5. ステータス履歴"
                ):
                    found.append(f"{path.relative_to(REPO_ROOT)}:{lineno} {line}")
        self.assertEqual(
            [],
            found,
            "旧書式の節が残っている（adr_format.md「節の構成」）:\n" + "\n".join(found),
        )

    def test_section_numbering(self):
        """`##` は `1.`〜`4.` のみ、`###` は必ず `N.M ` で始まること。

        番号を持たない `###` を許すと、後から採番したときに名前で指していた記述が
        取り残される（実際に ADR-052 の「問題 1」参照で起きた）。番号を必須にすることが
        その再発経路を塞ぐ。
        """
        violations: list[str] = []
        for path in adr_files():
            for lineno, line in enumerate(
                strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                rel = f"{path.relative_to(REPO_ROOT)}:{lineno}"
                if line.startswith("## ") and not re.match(r"^## [1-4]\. ", line):
                    violations.append(f"{rel} {line}")
                if line.startswith("### ") and not re.match(
                    r"^### [1-4]\.\d+ ", line
                ):
                    violations.append(f"{rel} {line}")
        self.assertEqual(
            [],
            violations,
            "節構成が adr_format.md「節の構成」に反する:\n" + "\n".join(violations),
        )

    def test_invalidation_marker_placement(self):
        """`⚠️失効` が見出し行にのみ出現し、括弧が閉じていること。"""
        violations: list[str] = []
        for path in adr_files():
            for lineno, line in enumerate(
                strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
            ):
                if not INVALIDATION_RE.search(line):
                    continue
                rel = f"{path.relative_to(REPO_ROOT)}:{lineno}"
                if not line.startswith("#"):
                    violations.append(f"{rel} 見出し行ではない: {line}")
                    continue
                marker = line[line.index("⚠️失効") :]
                if marker.count("（") != marker.count("）"):
                    violations.append(f"{rel} 括弧が閉じていない: {line}")
        self.assertEqual(
            [],
            violations,
            "失効マーカーの記法が adr_format.md「失効マーカー」に反する:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()
