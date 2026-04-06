---
name: query-code
description: |
  コードインデックスを検索し、タスクに関連するソースファイルを特定する。
  2段階検索（キーワード絞り込み + AI評価）で精度を確保。
  トリガー:
  - "関連するソースコードは？"
  - "このタスクに関係するファイルを探して"
  - タスク実装前のコード調査
user-invocable: false
argument-hint: "<タスク説明 or キーワード>"
context: fork
agent: general-purpose
model: sonnet
---

## 役割

タスク説明またはキーワードからコードインデックスを検索し、関連するソースファイルのパスリストを返す。

## 鮮度チェック [MANDATORY]

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/code_index/build_code_index.py --check PROJECT_ROOT
```

`PROJECT_ROOT` は実際のプロジェクトルートパスに置き換えること。

### 結果の判定

- **`"status": "fresh"`** → そのまま「Stage 1: キーワード絞り込み」へ進む
- **`"status": "stale"`** → 以下の警告を表示し、検索は続行する:

  > ⚠️ インデックスが古くなっています。`/doc-advisor:create-code-index` で更新を推奨します。

- **`"status": "error"`**（インデックス未作成等） → AskUserQuestion を使用して確認する:
  - 「インデックスが未作成です。`/doc-advisor:create-code-index` を実行しますか？」
    - はい → `/doc-advisor:create-code-index` を呼び出し、完了後に「Stage 1: キーワード絞り込み」から検索を再開する
    - いいえ → 処理を終了する

## Stage 1: キーワード絞り込み

1. `$ARGUMENTS`（タスク説明）を分析し、検索に有効なキーワードを抽出する
   - 技術用語、クラス名、モジュール名、機能名などを優先
   - 助詞・一般的な動詞など情報量の低い語は除外
2. 抽出したキーワードを空白区切りで結合し、以下を実行する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/code_index/search_code.py --query "抽出したキーワード" PROJECT_ROOT
```

3. JSON 結果を取得する
   - `"status": "error"` の場合 → AskUserQuestion を使用してユーザーにエラー内容を報告し、処理を終了する
   - `"result_count": 0` の場合 → 「関連するソースファイルが見つかりませんでした」と表示して処理を終了する

## Stage 2: AI 評価・選別 [MANDATORY]

Stage 1 で候補が得られた場合、以下の手順で AI が最終判断を行う。

### 30KB メタデータ制限

Stage 1 の結果 JSON がすでに 30KB 以内に収まるよう `search_code.py` が制御しているが、
念のため候補のメタデータ合計が大きい場合はスコア上位から順に評価対象を絞り込む。

### 評価手順

1. Stage 1 の各候補について、以下のメタデータを確認する:
   - `exports`: シンボル名、アクセスレベル、ドキュメントコメント、プロトコル準拠
   - `imports`: 依存モジュール
   - `path`: ファイルパス（ディレクトリ構造から役割を推測）
   - `sections`: ファイル内のセクション構造
2. タスク説明（`$ARGUMENTS`）との関連性を以下の観点で評価する:
   - **直接的な関連**: タスクが言及する機能・クラス・モジュールを定義しているか
   - **間接的な関連**: タスクの実装に必要な依存先・ユーティリティであるか
   - **テストファイル**: タスク対象の機能をテストしているか
3. 関連性が低い候補を除外し、関連するファイルのみを選別する
4. 各ファイルについて選別理由を簡潔に記録する

## 出力形式 [MANDATORY]

最終結果は以下の形式で出力する（query-rules / query-specs スキルと統一）:

```
Required source files:
- path/to/file1.swift
  理由: JWT トークン検証ロジックを定義
- path/to/file2.swift
  理由: 認証モジュールの依存先ユーティリティ
- path/to/file3.py
  理由: 対象機能のテストファイル
```

パスはプロジェクトルート相対パスで記載する。

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| `build_code_index.py --check` がエラー（インデックス未作成） | AskUserQuestion で `/doc-advisor:create-code-index` 実行を確認 |
| `search_code.py` がエラー | AskUserQuestion でユーザーにエラー内容を報告 |
| 候補が 0 件 | 「関連するソースファイルが見つかりませんでした」と表示 |

## 注意事項

- Stage 1 のキーワード絞り込みは CLI（`search_code.py`）に委譲する。AI がインデックスを直接読むことはしない
- Stage 2 の AI 評価は、Stage 1 が返した JSON のメタデータのみを入力として判断する
- 偽陰性（関連ファイルの見落とし）を避けるため、迷ったら含める方針とする
