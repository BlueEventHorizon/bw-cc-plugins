# ToC 候補生成ワークフロー

ToC（キーワード/メタデータ）ベースで関連文書の候補パスを生成する。
**候補パスの生成まで**が責務。ファイル内容の Read・最終判定は呼び出し元が行う。

## パラメータ

| 変数 | 説明 |
|------|------|
| `{category}` | `rules` または `specs` |
| `{task}` | 検索対象タスクの説明 |

## Procedure

1. `.claude/doc-advisor/toc/{category}/{category}_toc.yaml` を Read する
   - **ファイルが存在しない場合**: 候補なし（空リスト）として返す。エラーにしない
   - **ファイルが存在する場合**: **全文を Read ツールで読み込む**
2. 全エントリを深く理解し、タスク内容から関連候補を特定する
   - keywords, purpose, title, applicable_tasks を照合
3. 関連の可能性があるパスを候補リストとして保持する

## Critical Rule

**ToC は全文を読んで深く理解してから判断する。**

- PROHIBITED: Grep/検索ツールで ToC を検索すること
- PROHIBITED: ToC を部分的にしか読まないこと
- REQUIRED: Read ツールで ToC ファイル全体を読み込むこと
- REQUIRED: 全エントリを理解してから関連文書を特定すること
- False negative 厳禁。迷ったら含める
