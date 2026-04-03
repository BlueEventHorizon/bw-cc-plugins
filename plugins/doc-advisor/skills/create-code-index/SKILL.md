---
name: create-code-index
description: |
  コードインデックスを作成・更新する。ソースファイルの構造（imports/exports/sections）を抽出しインデックスに登録する。
  トリガー: "コードインデックス更新", "create code index", "インデックス構築"
user-invocable: true
argument-hint: "[--full]"
---

# create-code-index

コードインデックスを作成・更新するオーケストレーター。
ソースファイルの構造情報（imports/exports/sections）を言語別 subagent で抽出し、インデックスに登録する。

## コマンド構文

```
/doc-advisor:create-code-index [--full]
```

| 引数 | 説明 |
|------|------|
| (なし) | 増分更新（変更ファイルのみ処理） |
| `--full` | 全ファイルを再スキャン（初回構築・再構築用） |

## 拡張子 → 言語テーブル [MANDATORY]

新言語追加時はこのテーブルに1行追加し、`lang/` に subagent を配置する。

| 拡張子 | 言語 | subagent パス |
|--------|------|--------------|
| `.swift` | swift | `${CLAUDE_SKILL_DIR}/lang/swift/SKILL.md` |

対応 subagent がない拡張子のファイルは **パス・行数のみ** をインデックスに含める（subagent 不要）。

## 処理フロー [MANDATORY]

### ステップ 1: --full 引数チェック

`$ARGUMENTS` に `--full` が含まれるかを確認する。

### ステップ 2: 差分検出

`--full` でない場合のみ実行する。

Bash で以下を実行:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/code_index/build_code_index.py --diff PROJECT_ROOT
```

> `PROJECT_ROOT` はプロジェクトルートの絶対パスに置き換える。

出力 JSON を解析する:

- `status` が `"fresh"` かつ `--full` でない場合:
  「コードインデックスは最新です。変更はありません。」と表示して **終了**。
- `status` が `"stale"` の場合:
  `new` + `modified` のファイルリストを取得する。これが subagent に渡す対象ファイルとなる。
- `status` が `"error"` の場合:
  AskUserQuestion を使用してエラー内容を報告し、続行するか確認する。

`--full` の場合はこのステップをスキップし、全ファイルを対象とする。全ファイルリストの取得には以下を使用する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/code_index/build_code_index.py --diff PROJECT_ROOT
```

出力の `new` + `modified` を使用する（`--full` では全ファイルが new として報告される）。

> **注**: `--full` でも `--diff` を実行する理由は、`build_code_index.py` がチェックサムファイル未存在時に全ファイルを `new` として報告するため。初回構築時もこのフローで統一できる。

### ステップ 3: 言語判定とファイル振り分け

対象ファイルを拡張子で振り分ける:

1. 上記の **拡張子 → 言語テーブル** に一致するファイル → 対応言語の subagent に渡すリストに追加
2. テーブルに一致しないファイル → 「未対応言語ファイルリスト」に追加（パス・行数のみ登録）

### ステップ 4: 言語 subagent 起動

各言語の subagent を **Agent ツール** で起動する（言語ごとに並列起動可能）。

Agent ツールに渡すプロンプト:

```
以下の Swift ファイルからコード構造を抽出してください。

プロジェクトルート: <PROJECT_ROOT>

対象ファイル:
<ファイルリスト（1行1パス、プロジェクトルート相対）>

結果は以下の JSON フォーマットで出力してください:
{
  "相対パス": {
    "imports": ["モジュール名"],
    "exports": [
      {"name": "シンボル名", "kind": "Class/Struct/Enum/Protocol/Function等", "line": 行番号, "access": "public/internal/private", "conforms_to": ["プロトコル名"], "doc": "ドキュメントコメントまたはnull", "extensions": [{"file": "Extension定義ファイル"}]}
    ],
    "sections": ["セクション名"]
  }
}
```

subagent の SKILL.md パスは拡張子→言語テーブルの `subagent パス` を参照する。

**subagent がエラーを返した場合**: 該当言語のファイルをスキップして続行する。スキップしたファイルはパス・行数のみでインデックスに登録する。

### ステップ 5: 未対応言語ファイルの処理

未対応言語ファイルリストが空でない場合、それらのファイルに対して最低限のメタデータ（空の imports/exports/sections）を JSON として構築する:

```json
{
  "path/to/file.xyz": {
    "imports": [],
    "exports": [],
    "sections": []
  }
}
```

この JSON を subagent 結果と統合する。

### ステップ 6: インデックス更新

subagent 出力（+ 未対応言語ファイルの JSON）を統合した JSON を stdin 経由で `build_code_index.py --mcp-data` に渡す:

```bash
echo '<統合JSON>' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/code_index/build_code_index.py --mcp-data PROJECT_ROOT
```

出力 JSON を確認:

- `status` が `"ok"` → ステップ 7 へ
- `status` が `"error"` → AskUserQuestion を使用してエラー内容を報告

### ステップ 7: 完了メッセージ

`build_code_index.py` の出力統計を使って完了メッセージを表示:

```
コードインデックスを更新しました。
- ファイル数: {file_count}
- 新規: {new}
- 更新: {modified}
- 削除: {deleted}
- スキップ: {skipped}
```

## エラーハンドリング [MANDATORY]

| エラー | 対応 |
|--------|------|
| `build_code_index.py` がエラーを返す | AskUserQuestion を使用してユーザーにエラー内容を報告し、続行するか確認する |
| 言語 subagent がエラーを返す | 該当言語をスキップして続行する。スキップした言語・ファイル数を完了メッセージに含める |
| 対象ファイルが0件 | 「対象ファイルがありません。」と表示して終了 |
