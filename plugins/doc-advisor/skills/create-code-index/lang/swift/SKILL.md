---
name: swift
description: |
  Swift ソースファイルから構造情報（imports/exports/sections）を抽出する。Swift-Selena MCP を使用。
  create-code-index オーケストレーターから呼び出される。
user-invocable: false
---

# swift

Swift ソースファイルから構造情報を抽出し、共通 JSON フォーマットで出力する言語 subagent。
Swift-Selena MCP（AST ベース）を使用して高精度な情報を取得する。

## パラメータ

オーケストレーター（create-code-index）から以下が渡される:

- **file_list**: Swift ファイルの相対パスリスト（プロジェクトルート相対）
- **project_root**: プロジェクトルートの絶対パス

## 処理フロー [MANDATORY]

### ステップ 1: Swift-Selena MCP の初期化

Swift-Selena MCP の `initialize_project` ツールを呼び出し、project_root でプロジェクトを初期化する。

```
initialize_project(path: <project_root>)
```

**MCP 接続失敗時**:
AskUserQuestion を使用して以下を報告:
「Swift-Selena MCP が利用できません。MCP サーバーの接続を確認してください。」
- 再試行
- スキップ（エラーとしてオーケストレーターに返す）

### ステップ 2: 各ファイルのメタデータ抽出

file_list の各ファイルに対して、以下の MCP ツールを呼び出す。

#### 2-1: import 抽出

```
analyze_imports(file_path: <project_root>/<相対パス>)
```

結果から import しているモジュール名のリストを取得する。

#### 2-2: シンボル抽出

```
list_symbols(file_path: <project_root>/<相対パス>)
```

結果から公開シンボル（Class / Struct / Enum / Protocol / Function 等）を取得する。
各シンボルから以下を抽出:
- `name`: シンボル宣言名
- `kind`: シンボル種別（Class / Struct / Enum / Protocol / Function 等）
- `line`: 定義行番号（整数）
- `access`: アクセスレベル（public / internal / private）
- `doc`: ドキュメントコメント（`///` や `/** */` から。なければ null）

#### 2-3: プロトコル準拠情報

```
list_protocol_conformances(file_path: <project_root>/<相対パス>)
```

結果から各シンボルが準拠しているプロトコル名を取得し、ステップ 2-2 の該当シンボルの `conforms_to` フィールドに設定する。

#### 2-4: Extension 情報

```
list_extensions(file_path: <project_root>/<相対パス>)
```

結果から Extension 情報を取得し、対象型の export に Extension 情報を付加する。
各 Extension は `{"file": "Extension 定義ファイルパス"}` の形式で `extensions` フィールドに追加する。

### ステップ 3: セクション抽出

各ファイルを Read ツールで読み込み、`// MARK: -` コメントからセクション名を抽出する。

抽出パターン: `// MARK: -` の後に続くテキスト（前後の空白を除去）。
`// MARK:` （ハイフンなし）も対象とする。

例:
```swift
// MARK: - Properties
// MARK: - Initialization
// MARK: Verification
```
→ `["Properties", "Initialization", "Verification"]`

### ステップ 4: 共通 JSON フォーマットへの変換

ステップ 2〜3 の結果を統合し、以下の共通 JSON フォーマットに変換する:

```json
{
  "<プロジェクトルート相対パス>": {
    "imports": ["Foundation", "UIKit"],
    "exports": [
      {
        "name": "JwtVerifier",
        "kind": "Class",
        "line": 15,
        "access": "public",
        "conforms_to": ["TokenVerifying", "Sendable"],
        "doc": "JWT 検証クラス",
        "extensions": [{"file": "Sources/Auth/JwtVerifier+Logging.swift"}]
      }
    ],
    "sections": ["Properties", "Initialization", "Verification"]
  }
}
```

フィールド仕様:
- `imports`: モジュール名の配列（空の場合は `[]`）
- `exports`: シンボル情報の配列（空の場合は `[]`）
  - `name`: シンボル宣言名（必須）
  - `kind`: シンボル種別（必須）
  - `line`: 定義行番号・整数（必須）
  - `access`: アクセスレベル（必須）
  - `conforms_to`: 準拠プロトコル名の配列（空の場合は `[]`）
  - `doc`: ドキュメントコメント（なければ `null`）
  - `extensions`: Extension 情報の配列（なければ `null`）
- `sections`: セクション名の配列（空の場合は `[]`）

### ステップ 5: 結果出力

ステップ 4 で構築した JSON をオーケストレーターに返す。

## エラーハンドリング [MANDATORY]

| エラー | 対応 |
|--------|------|
| Swift-Selena MCP 接続失敗 | AskUserQuestion で報告。再試行 or スキップを選択 |
| 個別ファイルの MCP 呼び出し失敗 | 該当ファイルをスキップし、残りのファイルの処理を継続する。スキップしたファイルのパスを記録する |
| ファイルが存在しない（Read 失敗） | 該当ファイルをスキップし、残りの処理を継続する |

## 重要事項

- この SKILL.md では Python スクリプトを実行しない。全ての処理は MCP ツール呼び出しと Read ツールで実行する
- `lines`（行数）フィールドは subagent の責務外。`build_code_index.py` が算出する
- `language`（言語名）フィールドも subagent の責務外。オーケストレーターが決定する
