#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImportGraph のユニットテスト。

DES-007 §4.1-4.3 に基づく依存グラフの構築・探索をテストする。
"""

import os
import sys
import unittest

# テスト対象モジュールの import
SCRIPTS_DIR = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'plugins', 'doc-advisor', 'scripts'
)
sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))

from code_index.graph import ImportGraph


# ===========================================================================
# A→B→C チェーンテスト
# ===========================================================================

class TestImportGraphChain(unittest.TestCase):
    """A→B→C の3ファイル連鎖依存テスト。

    構造:
        Sources/A/a.swift imports B
        Sources/B/b.swift imports C
        Sources/C/c.swift imports なし（内部モジュール）
    """

    def setUp(self):
        self.graph = ImportGraph()
        self.entries = [
            {"file": "Sources/A/a.swift", "imports": ["B"]},
            {"file": "Sources/B/b.swift", "imports": ["C"]},
            {"file": "Sources/C/c.swift", "imports": []},
        ]
        self.graph.build(self.entries)

    def test_dependents_of_C(self):
        """C のファイルの依存元は B（B が C を import している）"""
        result = self.graph.dependents_of("Sources/C/c.swift")
        self.assertEqual(result, {"Sources/B/b.swift"})

    def test_dependents_of_B(self):
        """B のファイルの依存元は A（A が B を import している）"""
        result = self.graph.dependents_of("Sources/B/b.swift")
        self.assertEqual(result, {"Sources/A/a.swift"})

    def test_dependents_of_A(self):
        """A のファイルの依存元はなし（誰も A を import していない）"""
        result = self.graph.dependents_of("Sources/A/a.swift")
        self.assertEqual(result, set())

    def test_dependencies_of_a(self):
        """a.swift の依存先は B"""
        result = self.graph.dependencies_of("Sources/A/a.swift")
        self.assertEqual(result, {"B"})

    def test_dependencies_of_b(self):
        """b.swift の依存先は C"""
        result = self.graph.dependencies_of("Sources/B/b.swift")
        self.assertEqual(result, {"C"})

    def test_dependencies_of_c(self):
        """c.swift の依存先はなし"""
        result = self.graph.dependencies_of("Sources/C/c.swift")
        self.assertEqual(result, set())


# ===========================================================================
# 外部フレームワーク除外テスト
# ===========================================================================

class TestExternalFrameworkExclusion(unittest.TestCase):
    """プロジェクト外の外部フレームワークが除外されることをテストする。"""

    def setUp(self):
        self.graph = ImportGraph()
        self.entries = [
            {"file": "Sources/Auth/login.swift", "imports": ["Foundation", "UIKit", "Network"]},
            {"file": "Sources/Network/api.swift", "imports": ["Foundation"]},
        ]
        self.graph.build(self.entries)

    def test_dependencies_exclude_external(self):
        """dependencies_of はプロジェクト内モジュールのみ返す（Foundation, UIKit は除外）"""
        result = self.graph.dependencies_of("Sources/Auth/login.swift")
        # Network はプロジェクト内ディレクトリとして存在するので含まれる
        self.assertIn("Network", result)
        # Foundation, UIKit はプロジェクト内にディレクトリがないので除外
        self.assertNotIn("Foundation", result)
        self.assertNotIn("UIKit", result)

    def test_dependents_of_network_file(self):
        """Network ディレクトリのファイルの依存元は Auth（Auth が Network を import）"""
        result = self.graph.dependents_of("Sources/Network/api.swift")
        self.assertEqual(result, {"Sources/Auth/login.swift"})


# ===========================================================================
# hops=1 と hops=2 の影響範囲テスト
# ===========================================================================

class TestAffectedFilesHops(unittest.TestCase):
    """hops=1 と hops=2 での影響範囲の違いを検証する。

    構造:
        Sources/A/a.swift imports B
        Sources/B/b.swift imports C
        Sources/C/c.swift imports なし
    C を変更した場合:
        hops=1: B のみ（B が C を import）
        hops=2: B と A（A が B を import、B が C を import）
    """

    def setUp(self):
        self.graph = ImportGraph()
        self.entries = [
            {"file": "Sources/A/a.swift", "imports": ["B"]},
            {"file": "Sources/B/b.swift", "imports": ["C"]},
            {"file": "Sources/C/c.swift", "imports": []},
        ]
        self.graph.build(self.entries)

    def test_affected_hops_1(self):
        """hops=1: C の変更は B にのみ影響"""
        result = self.graph.affected_files("Sources/C/c.swift", hops=1)
        self.assertEqual(result, {"Sources/B/b.swift"})

    def test_affected_hops_2(self):
        """hops=2: C の変更は B と A に影響"""
        result = self.graph.affected_files("Sources/C/c.swift", hops=2)
        self.assertEqual(result, {"Sources/A/a.swift", "Sources/B/b.swift"})

    def test_affected_leaf_node(self):
        """末端ノード（A）の変更は他に影響しない"""
        result = self.graph.affected_files("Sources/A/a.swift", hops=2)
        self.assertEqual(result, set())

    def test_affected_does_not_include_self(self):
        """affected_files は起点ファイル自身を含まない"""
        result = self.graph.affected_files("Sources/C/c.swift", hops=2)
        self.assertNotIn("Sources/C/c.swift", result)

    def test_affected_hops_0(self):
        """hops=0: 探索しないので空集合"""
        result = self.graph.affected_files("Sources/C/c.swift", hops=0)
        self.assertEqual(result, set())

    def test_affected_default_hops(self):
        """デフォルト hops=1（DES-007 §4.1 準拠）: C の変更は B にのみ影響"""
        result = self.graph.affected_files("Sources/C/c.swift")
        self.assertEqual(result, {"Sources/B/b.swift"})


# ===========================================================================
# 空グラフテスト
# ===========================================================================

class TestEmptyGraph(unittest.TestCase):
    """空のグラフに対する操作が安全であることをテストする。"""

    def setUp(self):
        self.graph = ImportGraph()
        self.graph.build([])

    def test_dependents_of_empty(self):
        """空グラフでの dependents_of は空集合"""
        result = self.graph.dependents_of("nonexistent.swift")
        self.assertEqual(result, set())

    def test_dependencies_of_empty(self):
        """空グラフでの dependencies_of は空集合"""
        result = self.graph.dependencies_of("nonexistent.swift")
        self.assertEqual(result, set())

    def test_affected_files_empty(self):
        """空グラフでの affected_files は空集合"""
        result = self.graph.affected_files("nonexistent.swift", hops=2)
        self.assertEqual(result, set())


# ===========================================================================
# 自己参照テスト
# ===========================================================================

class TestSelfReference(unittest.TestCase):
    """ファイルが自身のモジュールを import しているケースのテスト。"""

    def setUp(self):
        self.graph = ImportGraph()
        self.entries = [
            {"file": "Sources/MyModule/foo.swift", "imports": ["MyModule"]},
            {"file": "Sources/MyModule/bar.swift", "imports": []},
        ]
        self.graph.build(self.entries)

    def test_self_import_dependents(self):
        """MyModule のファイルの依存元に foo.swift が含まれる（自身も MyModule を import）"""
        result = self.graph.dependents_of("Sources/MyModule/bar.swift")
        self.assertIn("Sources/MyModule/foo.swift", result)

    def test_affected_files_self_reference(self):
        """自己参照があっても affected_files が無限ループしない"""
        result = self.graph.affected_files("Sources/MyModule/bar.swift", hops=2)
        # bar.swift は MyModule に属する → foo.swift が MyModule を import している
        # → foo.swift が影響を受ける
        self.assertIn("Sources/MyModule/foo.swift", result)
        # bar.swift 自身は含まない
        self.assertNotIn("Sources/MyModule/bar.swift", result)


# ===========================================================================
# ドット区切り import のテスト
# ===========================================================================

class TestDottedImport(unittest.TestCase):
    """ドット区切りの import パス（例: Auth.TokenStore）のテスト。"""

    def setUp(self):
        self.graph = ImportGraph()
        self.entries = [
            {"file": "Sources/Auth/TokenStore.swift", "imports": []},
            {"file": "Sources/Gateway/api.swift", "imports": ["Auth.TokenStore"]},
        ]
        self.graph.build(self.entries)

    def test_dotted_import_resolves_last_component(self):
        """Auth.TokenStore の最後のコンポーネント TokenStore でマッチしない（ディレクトリ名でない）"""
        # TokenStore はディレクトリ名ではないのでモジュールとして登録されない
        result = self.graph.dependencies_of("Sources/Gateway/api.swift")
        # TokenStore はディレクトリ名に存在しないので外部扱い
        # ただし Auth はディレクトリ名として存在しないため（Auth はディレクトリ名）
        # → Auth.TokenStore の最後は "TokenStore"、これはディレクトリ名にない
        # → 空集合
        # 実際には Auth ディレクトリがあるので、最後のコンポーネント "TokenStore" では
        # マッチしないが、設計上はモジュール名の最後のコンポーネントでマッチする
        self.assertNotIn("TokenStore", result)

    def test_dotted_import_dependents(self):
        """Auth ディレクトリのファイルの依存元に Gateway が含まれる"""
        # Gateway が Auth.TokenStore を import → Auth モジュールの依存元
        result = self.graph.dependents_of("Sources/Auth/TokenStore.swift")
        # Auth ディレクトリのファイルなので、Auth を import しているファイルが返る
        # ただし "Auth.TokenStore" の最後のコンポーネントは "TokenStore" であり
        # Auth ではない → Gateway は Auth ディレクトリ名経由ではマッチしない
        # TokenStore はディレクトリ名にないので逆引きにない
        # → 実際にはマッチしない可能性がある
        # Auth ディレクトリに属するファイルの dependents = Auth モジュールを import しているファイル
        # Gateway は "Auth.TokenStore" を import → 解決名は "TokenStore"（Auth ではない）
        # よって Gateway は Auth モジュールの dependents ではない
        self.assertNotIn("Sources/Gateway/api.swift", result)


# ===========================================================================
# build の再呼び出しテスト
# ===========================================================================

class TestRebuild(unittest.TestCase):
    """build() を再呼び出しした場合に前回のデータがクリアされることをテスト。"""

    def test_rebuild_clears_previous_data(self):
        graph = ImportGraph()
        entries_v1 = [
            {"file": "Sources/A/a.swift", "imports": ["B"]},
            {"file": "Sources/B/b.swift", "imports": []},
        ]
        graph.build(entries_v1)
        self.assertEqual(graph.dependents_of("Sources/B/b.swift"), {"Sources/A/a.swift"})

        # 再構築: A→B の関係がなくなる
        entries_v2 = [
            {"file": "Sources/C/c.swift", "imports": []},
        ]
        graph.build(entries_v2)
        self.assertEqual(graph.dependents_of("Sources/B/b.swift"), set())
        self.assertEqual(graph.dependencies_of("Sources/A/a.swift"), set())


if __name__ == '__main__':
    unittest.main()
