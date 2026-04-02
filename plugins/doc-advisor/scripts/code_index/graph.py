#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ImportGraph — import 依存関係グラフの構築・探索。

code_index.json の entries から依存グラフを構築し、
依存元（dependents）・依存先（dependencies）の取得、
および BFS による N ホップ影響範囲探索を提供する。

設計根拠: DES-007 §4.1-4.3
"""

class ImportGraph:
    """import 文から構築される依存関係グラフ。

    内部データ構造:
        _imports: dict[str, set[str]]
            ファイルパス → そのファイルが import しているモジュール名の集合
        _module_to_files: dict[str, set[str]]
            モジュール名 → そのモジュールに属するファイルパスの集合
    """

    def __init__(self):
        self._imports: dict[str, set[str]] = {}
        self._module_to_files: dict[str, set[str]] = {}
        # 逆引きインデックス: モジュール名 → そのモジュールを import しているファイル集合
        self._reverse_imports: dict[str, set[str]] = {}

    def build(self, entries: list[dict]) -> None:
        """code_index.json の entries から依存グラフを構築する。

        Args:
            entries: インデックスエントリのリスト。各要素は以下の形式:
                {
                    "file": "Sources/Auth/JwtVerifier.swift",
                    "imports": ["Foundation", "CryptoKit", "Auth.TokenStore"],
                    ...
                }

        モジュール解決（DES-007 §4.2）:
            ファイルパスの各ディレクトリ名をモジュール名として登録する。
            例: "Sources/Auth/JwtVerifier.swift" → "Sources", "Auth" を登録。
            import パスの最後のコンポーネントでディレクトリ名マッチングを行う。
            プロジェクト内に対応ディレクトリがなければ外部フレームワークと判定し除外。
        """
        self._imports.clear()
        self._module_to_files.clear()
        self._reverse_imports.clear()

        # 全ファイルのパスからディレクトリ名 → ファイル集合を構築
        all_files: set[str] = set()
        for entry in entries:
            file_path = entry.get("file", "")
            if not file_path:
                continue
            all_files.add(file_path)
            imports = entry.get("imports", [])
            self._imports[file_path] = set(imports)

        # ディレクトリ名マッチング: パスの各ディレクトリ名をモジュール名として登録
        for file_path in all_files:
            parts = file_path.replace("\\", "/").split("/")
            # ファイル名を除くディレクトリ部分をモジュール候補とする
            for part in parts[:-1]:
                if part:
                    self._module_to_files.setdefault(part, set()).add(file_path)

        # 逆引きインデックス構築: モジュール名 → import しているファイル集合
        for file_path, imports in self._imports.items():
            for imp in imports:
                resolved = imp.split(".")[-1]
                self._reverse_imports.setdefault(resolved, set()).add(file_path)

    def dependents_of(self, file_path: str) -> set[str]:
        """指定ファイルを import しているファイル一覧を返す（依存元）。

        DES-007 §4.1 準拠: file_path が属するモジュール（ディレクトリ名）を
        特定し、そのモジュールを import しているファイルを返す。

        Args:
            file_path: ファイルパス

        Returns:
            file_path が属するモジュールを import しているファイルパスの集合
        """
        modules = self._file_to_modules(file_path)
        result: set[str] = set()
        for mod in modules:
            result |= self._reverse_imports.get(mod, set())
        return result

    def _dependents_of_module(self, module: str) -> set[str]:
        """指定モジュール名を import しているファイル一覧を返す（内部用）。

        Args:
            module: モジュール名

        Returns:
            module を import しているファイルパスの集合
        """
        return set(self._reverse_imports.get(module, set()))

    def dependencies_of(self, file_path: str) -> set[str]:
        """指定ファイルが import しているモジュール一覧を返す（依存先）。

        外部フレームワーク（プロジェクト内に対応ディレクトリがないもの）は除外する。

        Args:
            file_path: ファイルパス

        Returns:
            プロジェクト内モジュール名の集合
        """
        imports = self._imports.get(file_path, set())
        result: set[str] = set()
        for imp in imports:
            # import パスの最後のコンポーネントで解決
            resolved = imp.split(".")[-1]
            if resolved in self._module_to_files:
                result.add(resolved)
        return result

    def affected_files(self, file_path: str, hops: int = 1) -> set[str]:
        """BFS で N ホップ以内の影響範囲を取得する（DES-007 §4.3）。

        指定ファイルを起点に、そのファイルが属するモジュールの依存元を
        幅優先探索で展開し、影響を受けるファイルを返す。

        Args:
            file_path: 起点ファイルパス
            hops: 探索する最大ホップ数（デフォルト: 1、DES-007 §4.1 準拠）

        Returns:
            影響を受けるファイルパスの集合（起点ファイル自身は含まない）
        """
        visited: set[str] = {file_path}
        frontier: set[str] = {file_path}

        for _ in range(hops):
            next_frontier: set[str] = set()
            for current in frontier:
                # current が属するモジュール名を特定
                modules = self._file_to_modules(current)
                for mod in modules:
                    dependents = self._dependents_of_module(mod)
                    next_frontier |= dependents - visited
            visited |= next_frontier
            frontier = next_frontier

        return visited - {file_path}

    def _file_to_modules(self, file_path: str) -> set[str]:
        """ファイルが属するモジュール名の集合を返す。

        ファイルパスのディレクトリ部分から、_module_to_files に登録済みの
        モジュール名を逆引きする。

        Args:
            file_path: ファイルパス

        Returns:
            ファイルが属するモジュール名の集合
        """
        parts = file_path.replace("\\", "/").split("/")
        result: set[str] = set()
        for part in parts[:-1]:
            if part and part in self._module_to_files:
                result.add(part)
        return result
