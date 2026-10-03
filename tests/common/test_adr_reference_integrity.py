#!/usr/bin/env python3
"""回帰防止テスト: ADR の参照と書式の整合。

ADR は仕様を書かず参照で示すため、参照が沈黙して腐ると ADR 自体が誤った根拠になる。
ADR は「その提案は検討済みで、こういう理由で採らなかった」と答えるために読まれるので、
宛先を失った参照は誤った見送り判断を生む。

本テストが検査するもの:

- 参照の実在: マークダウンリンクのリンク先ファイル、リンクに添えた `§X.Y`、
  および `ADR-NNN §X.Y` 形式の参照の宛先
- 書式の維持: feature ごとに 1 つの ADR ファイル、決定ごとの節（`## N.`）と
  4 つの小節（`### N.1`〜`### N.4`）、旧書式（メタデータ表・ステータス履歴節）と
  失効マーカーへの逆戻り

`ADR-NNN §X.Y` は ADR の外（コード・テスト・他の文書）からも書かれうるため、
リポジトリ全体を走査する。節番号が動けば、そうした参照は宛先を失う。

ADR が 1 件も無い状態では走査対象が空になり、実ファイルへの検査はすべて通る。
書式の検査そのものが働くことは、合成した ADR ファイルで確かめる。

実行:
  python3 -m unittest tests.common.test_adr_reference_integrity -v
"""

from __future__ import annotations

import re
import tempfile
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

#: 決定の節が持つ 4 つの小節（番号の下 1 桁と名前）。
DECISION_SUBSECTIONS = ((1, "コンテキスト"), (2, "決定"), (3, "検討した代替案"), (4, "影響"))


def adr_files() -> list[Path]:
    return sorted(SPECS_DIR.rglob("ADR-*.md"))


def strip_code(text: str) -> str:
    """フェンス済みコードブロックとインラインコードを空行・空文字へ潰す。

    記法の説明でリンク構文そのものを例示することがあり（`[design_format.md](design_format.md)`
    のような例）、これを実リンクとして扱うと存在しないファイルを指しているように
    見える。行番号を保つため、フェンス内は行ごと空行に置き換える。
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


def structure_violations(path: Path) -> list[str]:
    """ADR ファイルの構成が adr_format.md「ファイルの構成」に反する箇所を返す。

    - `#` 見出しはファイルのタイトル 1 つだけ
    - `##` は `## N. ` の形で、N は昇順（決定を足すときは末尾に追加する）
    - `###` は、直近の `## N.` の下の `### N.1`〜`### N.4` の形
    - 各決定の節は、4 つの小節を番号順に過不足なく持つ
    - 旧書式の節（メタデータ・ステータス履歴）を持たない
    """
    violations: list[str] = []
    current: int | None = None
    previous: int = 0
    seen: list[tuple[int, str]] = []
    titles = 0

    def close_section(lineno: int) -> None:
        if current is not None and seen != [
            (num, name) for num, name in DECISION_SUBSECTIONS
        ]:
            violations.append(
                f"{path.name}: `## {current}.` の小節が 4 つの定義と一致しない: {seen}"
            )

    for lineno, line in enumerate(
        strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
    ):
        rel = f"{path.name}:{lineno}"
        if line.startswith("# "):
            titles += 1
            continue
        if line.startswith("## メタデータ") or line.startswith("## ステータス履歴"):
            violations.append(f"{rel} 旧書式の節: {line}")
            continue
        if line.startswith("## "):
            close_section(lineno)
            m = re.match(r"^## (\d+)\. ", line)
            if not m:
                violations.append(f"{rel} 決定の節の見出しが `## N. ` の形ではない: {line}")
                current = None
                seen = []
                continue
            number = int(m.group(1))
            if number <= previous:
                violations.append(f"{rel} 節番号が昇順ではない: {line}")
            previous = number
            current = number
            seen = []
            continue
        if line.startswith("### "):
            m = re.match(r"^### (\d+)\.(\d+) (.+)$", line)
            if current is None or not m or int(m.group(1)) != current:
                violations.append(f"{rel} 小節が直近の `## N.` の `### N.M ` の形ではない: {line}")
                continue
            seen.append((int(m.group(2)), m.group(3).strip()))
    close_section(0)

    if titles != 1:
        violations.append(f"{path.name}: `#` 見出し（ファイルのタイトル）が 1 つではない: {titles}")
    return violations


def invalidation_marker_violations(path: Path) -> list[str]:
    """失効マーカーは廃止した。ADR に `⚠️失効` が現れたら違反とする。"""
    return [
        f"{path.name}:{lineno} {line}"
        for lineno, line in enumerate(
            strip_code(path.read_text(encoding="utf-8")).splitlines(), 1
        )
        if INVALIDATION_RE.search(line)
    ]


def adr_dirs_with_multiple_files(specs_dir: Path) -> list[str]:
    """同じ feature の ADR は 1 つのファイルに書く。`adr/` に ADR ファイルが複数あれば返す。"""
    found: list[str] = []
    for adr_dir in sorted(p for p in specs_dir.rglob("adr") if p.is_dir()):
        files = sorted(adr_dir.glob("ADR-*.md"))
        if len(files) > 1:
            found.append(f"{adr_dir}: {', '.join(f.name for f in files)}")
    return found


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

    def test_real_adr_files_follow_the_structure(self):
        violations = [v for path in adr_files() for v in structure_violations(path)]
        self.assertEqual(
            [],
            violations,
            "ファイルの構成が adr_format.md「ファイルの構成」に反する:\n"
            + "\n".join(violations),
        )

    def test_real_adr_files_have_no_invalidation_marker(self):
        violations = [
            v for path in adr_files() for v in invalidation_marker_violations(path)
        ]
        self.assertEqual(
            [],
            violations,
            "失効マーカーは廃止した（adr_principles_spec.md「決定の否決」）:\n"
            + "\n".join(violations),
        )

    def test_one_adr_file_per_feature(self):
        self.assertEqual(
            [],
            adr_dirs_with_multiple_files(SPECS_DIR),
            "同じ feature の ADR は 1 つのファイルに書く（adr_principles_spec.md「配置と ID 採番」）",
        )


GOOD_ADR = """\
# ADR-001 foo の決定記録

## 1. 最初の決定

### 1.1 コンテキスト

背景。

### 1.2 決定

決定の内容。

### 1.3 検討した代替案

| 代替案 | 棄却理由 |
| ------ | -------- |
| 案 A   | 理由     |

### 1.4 影響

帰結。

## 2. 次の決定

### 2.1 コンテキスト

背景。

### 2.2 決定

決定の内容。

### 2.3 検討した代替案

| 代替案 | 棄却理由 |
| ------ | -------- |

### 2.4 影響

帰結。
"""


class TestFormatChecksDetectViolations(unittest.TestCase):
    """書式の検査そのものが働くこと（実ファイルが 0 件でも空振りしないことの担保）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _adr(self, text, name="ADR-001_foo.md"):
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_good_file_passes(self):
        self.assertEqual([], structure_violations(self._adr(GOOD_ADR)))

    def test_multiple_decisions_in_one_file_are_allowed(self):
        """1 つのファイルに、決定の節が複数並ぶ。"""
        self.assertEqual(2, GOOD_ADR.count("\n## "))
        self.assertEqual([], structure_violations(self._adr(GOOD_ADR)))

    def test_legacy_metadata_section_is_detected(self):
        text = GOOD_ADR.replace("## 1. 最初の決定", "## メタデータ\n\n| ID | x |\n\n## 1. 最初の決定", 1)
        self.assertTrue(structure_violations(self._adr(text)))

    def test_section_without_number_is_detected(self):
        text = GOOD_ADR.replace("## 2. 次の決定", "## 次の決定")
        self.assertTrue(structure_violations(self._adr(text)))

    def test_non_ascending_section_number_is_detected(self):
        text = GOOD_ADR.replace("## 2. 次の決定", "## 1. 次の決定").replace("### 2.", "### 1.")
        self.assertTrue(structure_violations(self._adr(text)))

    def test_missing_subsection_is_detected(self):
        text = GOOD_ADR.replace("### 2.4 影響\n\n帰結。\n", "")
        self.assertTrue(structure_violations(self._adr(text)))

    def test_subsection_without_number_is_detected(self):
        text = GOOD_ADR.replace("### 1.4 影響", "### 影響")
        self.assertTrue(structure_violations(self._adr(text)))

    def test_subsection_of_another_section_is_detected(self):
        text = GOOD_ADR.replace("### 2.1 コンテキスト", "### 1.5 コンテキスト")
        self.assertTrue(structure_violations(self._adr(text)))

    def test_second_title_is_detected(self):
        self.assertTrue(structure_violations(self._adr(GOOD_ADR + "\n# 別のタイトル\n")))

    def test_invalidation_marker_is_detected(self):
        text = GOOD_ADR.replace("## 1. 最初の決定", "## 1. 最初の決定 ⚠️失効（別の決定が置き換えた）")
        self.assertTrue(invalidation_marker_violations(self._adr(text)))

    def test_invalidation_marker_in_code_is_not_a_violation(self):
        """記法の説明として、コードの中で言及することは違反ではない。"""
        text = GOOD_ADR + "\n廃止した記法は `⚠️失効` である。\n"
        self.assertEqual([], invalidation_marker_violations(self._adr(text)))

    def test_multiple_adr_files_in_one_adr_dir_are_detected(self):
        adr_dir = self.root / "docs" / "specs" / "foo" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "ADR-001_foo.md").write_text(GOOD_ADR, encoding="utf-8")
        self.assertEqual([], adr_dirs_with_multiple_files(self.root))
        (adr_dir / "ADR-002_foo.md").write_text(GOOD_ADR, encoding="utf-8")
        self.assertEqual(1, len(adr_dirs_with_multiple_files(self.root)))


if __name__ == "__main__":
    unittest.main()
