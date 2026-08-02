#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forge_settings.py のユニットテスト。

検証項目は DES-061 §3 の表に対応する:
ファイル不在 / 複数セクションの併記 / 未知セクション / 解析不能な構文 /
コメント・空行 / 対象外構文（アンカー・エイリアス・複数行文字列・flow style）。

fixture はすべて本ファイル内の文字列定数で持ち、一時ディレクトリへ
`.claude/.forge.yaml` として書き出して検証する。

実行:
  python3 -m unittest tests.forge.scripts.test_forge_settings -v
"""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest
import warnings
from pathlib import Path

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins" / "forge" / "scripts" / "forge_settings.py"
)

_spec = importlib.util.spec_from_file_location("forge_settings", _SCRIPT_PATH)
forge_settings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(forge_settings)

SettingsError = forge_settings.SettingsError


# --- fixture ------------------------------------------------------------------

#: 複数セクションの併記（DES-061 §2.1 の記述例に相当）
MULTI_SECTION = """\
doc_backend:
  prefer: doc-advisor

foo_feature:
  bar: value
  items:
    - one
    - two
"""

#: コメント・空行・行内コメントを含む設定
COMMENTED = """\
# ファイル先頭のコメント

doc_backend:
  # セクション内のコメント
  prefer: doc-db  # 行内コメント

"""

#: ネストした mapping とスカラー型（文字列・整数・真偽値・quote）
NESTED_AND_SCALARS = """\
alpha:
  nested:
    deep: 3
    flag: true
    off: false
  name: "hash # inside"
  plain: doc-advisor
"""

#: 解析不能: mapping の行として読めない行を含む（4 行目）
BROKEN_LINE = """\
doc_backend:
  prefer: doc-db

this line is not yaml at all SECRET_MARKER_BODY
"""

#: 対象外構文: アンカー
ANCHOR = """\
doc_backend:
  prefer: &anchor doc-db
"""

#: 対象外構文: エイリアス
ALIAS = """\
doc_backend:
  prefer: *anchor
"""

#: 対象外構文: 複数行文字列（literal）
MULTILINE_LITERAL = """\
doc_backend:
  prefer: |
    doc-db
"""

#: 対象外構文: 複数行文字列（folded）
MULTILINE_FOLDED = """\
doc_backend:
  prefer: >
    doc-db
"""

#: 対象外構文: flow style（sequence）
FLOW_SEQUENCE = """\
doc_backend:
  items: [one, two]
"""

#: 対象外構文: flow style（mapping）
FLOW_MAPPING = """\
doc_backend: {prefer: doc-db}
"""

#: 対象外構文: リスト要素の mapping（文字列リストの範囲外）
LIST_OF_MAPPINGS = """\
doc_backend:
  items:
    - name: one
"""

#: インデントにタブを含む
TAB_INDENT = "doc_backend:\n\tprefer: doc-db\n"

#: インデント幅が周囲と一致しない
BAD_INDENT = """\
doc_backend:
  prefer: doc-db
    orphan: value
"""

#: リストと mapping の混在
MIXED_LIST_MAPPING = """\
doc_backend:
  items:
    - one
    prefer: doc-db
"""

#: セクションが mapping ではない（スカラー）
SCALAR_SECTION = """\
doc_backend: doc-db
"""

#: 空のセクション（キーのみ）
EMPTY_SECTION = """\
doc_backend:
"""


# --- helper -------------------------------------------------------------------


class ForgeSettingsTestBase(unittest.TestCase):
    """一時 project root へ `.claude/.forge.yaml` を書いて検証する基底クラス。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project_root = Path(self._tmp.name)

    def write_settings(self, content: str) -> None:
        settings_path = self.project_root / ".claude" / ".forge.yaml"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(content, encoding="utf-8")


# --- ファイル不在 ---------------------------------------------------------------


class TestFileAbsent(ForgeSettingsTestBase):
    """ファイル不在は正常。空 dict を返し、エラー・警告を出さない。"""

    def test_load_returns_empty_dict(self):
        self.assertEqual(forge_settings.load(self.project_root), {})

    def test_section_returns_empty_dict(self):
        self.assertEqual(
            forge_settings.section(self.project_root, "doc_backend"), {}
        )

    def test_no_warning_and_no_output(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                forge_settings.load(self.project_root)
                forge_settings.section(self.project_root, "doc_backend")
        self.assertEqual(caught, [])
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


# --- 不在以外の読取失敗 -----------------------------------------------------------


class TestUnreadableFile(ForgeSettingsTestBase):
    """不在以外の読取失敗は SettingsError へ正規化する（未捕捉の OSError を漏らさない）。"""

    def _settings_path(self) -> Path:
        return self.project_root / ".claude" / ".forge.yaml"

    def test_permission_denied_raises_settings_error(self):
        if os.geteuid() == 0:
            self.skipTest("root ではパーミッションが無視される")
        self.write_settings("doc_backend:\n  prefer: doc-db\n")
        path = self._settings_path()
        os.chmod(path, 0o000)
        self.addCleanup(os.chmod, path, 0o600)
        with self.assertRaises(SettingsError) as ctx:
            forge_settings.load(self.project_root)
        self.assertNotIn(str(self.project_root), str(ctx.exception))

    def test_path_is_directory_raises_settings_error(self):
        self._settings_path().mkdir(parents=True)
        with self.assertRaises(SettingsError) as ctx:
            forge_settings.load(self.project_root)
        self.assertNotIn(str(self.project_root), str(ctx.exception))


# --- 複数セクションの併記 / 未知セクション ----------------------------------------


class TestSections(ForgeSettingsTestBase):
    def test_multi_sections_are_independent(self):
        """各セクションが独立に取り出せる。他セクションの内容が混入しない。"""
        self.write_settings(MULTI_SECTION)

        doc_backend = forge_settings.section(self.project_root, "doc_backend")
        foo_feature = forge_settings.section(self.project_root, "foo_feature")

        self.assertEqual(doc_backend, {"prefer": "doc-advisor"})
        self.assertEqual(
            foo_feature, {"bar": "value", "items": ["one", "two"]}
        )
        # 混入しないこと
        self.assertNotIn("bar", doc_backend)
        self.assertNotIn("items", doc_backend)
        self.assertNotIn("prefer", foo_feature)

    def test_unknown_section_does_not_affect_known(self):
        """未知セクションが書かれていても既知セクションの読み取りは成功する。"""
        self.write_settings(MULTI_SECTION)
        # foo_feature を「未知セクション」とみなし doc_backend だけを読む
        self.assertEqual(
            forge_settings.section(self.project_root, "doc_backend"),
            {"prefer": "doc-advisor"},
        )

    def test_missing_section_returns_empty_dict(self):
        self.write_settings(MULTI_SECTION)
        self.assertEqual(
            forge_settings.section(self.project_root, "no_such_section"), {}
        )

    def test_empty_section_returns_empty_dict(self):
        """キーだけのセクション（`doc_backend:`）は空 dict として読める。"""
        self.write_settings(EMPTY_SECTION)
        self.assertEqual(
            forge_settings.section(self.project_root, "doc_backend"), {}
        )

    def test_non_mapping_section_raises(self):
        """mapping でないセクションは黙って空 dict へ丸めず明示エラーとする。"""
        self.write_settings(SCALAR_SECTION)
        with self.assertRaises(SettingsError) as ctx:
            forge_settings.section(self.project_root, "doc_backend")
        self.assertIn("doc_backend", str(ctx.exception))

    def test_load_returns_whole_dict(self):
        self.write_settings(MULTI_SECTION)
        self.assertEqual(
            forge_settings.load(self.project_root),
            {
                "doc_backend": {"prefer": "doc-advisor"},
                "foo_feature": {"bar": "value", "items": ["one", "two"]},
            },
        )


# --- コメント・空行 --------------------------------------------------------------


class TestCommentsAndBlankLines(ForgeSettingsTestBase):
    def test_comments_and_blank_lines_are_ignored(self):
        self.write_settings(COMMENTED)
        self.assertEqual(
            forge_settings.load(self.project_root),
            {"doc_backend": {"prefer": "doc-db"}},
        )


# --- サブセット内の構文 -----------------------------------------------------------


class TestSupportedSyntax(ForgeSettingsTestBase):
    def test_nested_mapping_and_scalars(self):
        self.write_settings(NESTED_AND_SCALARS)
        self.assertEqual(
            forge_settings.load(self.project_root),
            {
                "alpha": {
                    "nested": {"deep": 3, "flag": True, "off": False},
                    "name": "hash # inside",
                    "plain": "doc-advisor",
                }
            },
        )

    def test_string_list_items_stay_strings(self):
        """文字列リストの要素は数値・真偽値に見えても文字列のまま返す。"""
        self.write_settings("s:\n  items:\n    - 42\n    - true\n    - plain\n")
        self.assertEqual(
            forge_settings.section(self.project_root, "s"),
            {"items": ["42", "true", "plain"]},
        )

    def test_quoted_list_item(self):
        self.write_settings('s:\n  items:\n    - "a: b"\n')
        self.assertEqual(
            forge_settings.section(self.project_root, "s"),
            {"items": ["a: b"]},
        )


# --- 解析不能な構文 --------------------------------------------------------------


class TestParseErrors(ForgeSettingsTestBase):
    def assert_settings_error(self, content, expected_lineno):
        """SettingsError になり、行位置を含み、本文の全文を含まないことを検証する。"""
        self.write_settings(content)
        with self.assertRaises(SettingsError) as ctx:
            forge_settings.load(self.project_root)
        message = str(ctx.exception)
        self.assertIn(f"{expected_lineno} 行目", message)
        self.assertIn(".claude/.forge.yaml", message)
        # 設定本文（各行の内容）をメッセージへ流していないこと
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped:
                self.assertNotIn(stripped, message)
        return message

    def test_unparsable_line(self):
        message = self.assert_settings_error(BROKEN_LINE, expected_lineno=4)
        self.assertNotIn("SECRET_MARKER_BODY", message)

    def test_section_raises_too(self):
        """解析不能なファイルでは section も SettingsError になる。"""
        self.write_settings(BROKEN_LINE)
        with self.assertRaises(SettingsError):
            forge_settings.section(self.project_root, "doc_backend")

    def test_tab_indent(self):
        self.assert_settings_error(TAB_INDENT, expected_lineno=2)

    def test_bad_indent(self):
        self.assert_settings_error(BAD_INDENT, expected_lineno=3)

    def test_list_and_mapping_mixed(self):
        self.assert_settings_error(MIXED_LIST_MAPPING, expected_lineno=4)


# --- 対象外構文（アンカー・複数行文字列・flow style） --------------------------------


class TestUnsupportedSyntax(ForgeSettingsTestBase):
    def assert_settings_error(self, content, expected_lineno):
        self.write_settings(content)
        with self.assertRaises(SettingsError) as ctx:
            forge_settings.load(self.project_root)
        self.assertIn(f"{expected_lineno} 行目", str(ctx.exception))

    def test_anchor(self):
        self.assert_settings_error(ANCHOR, expected_lineno=2)

    def test_alias(self):
        self.assert_settings_error(ALIAS, expected_lineno=2)

    def test_multiline_literal(self):
        self.assert_settings_error(MULTILINE_LITERAL, expected_lineno=2)

    def test_multiline_folded(self):
        self.assert_settings_error(MULTILINE_FOLDED, expected_lineno=2)

    def test_flow_sequence(self):
        self.assert_settings_error(FLOW_SEQUENCE, expected_lineno=2)

    def test_flow_mapping(self):
        self.assert_settings_error(FLOW_MAPPING, expected_lineno=1)

    def test_list_of_mappings(self):
        self.assert_settings_error(LIST_OF_MAPPINGS, expected_lineno=3)


if __name__ == "__main__":
    unittest.main()
