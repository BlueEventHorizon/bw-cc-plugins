---
name: query-forge-rules
description: |
  forge 内蔵の様々な知識ベースを、キーワード・機能名・自然文で、高速・高品位に、優先度をつけて検索する。
user-invocable: false
allowed-tools: Agent
---

> **【最重要・無限再帰防止】**
> このファイルは呼び出し元（多くは `/forge:*` スキル）がそのまま実行する手順書である。
> `$ARGUMENTS`（タスク説明）に対して、以下の手順を呼び出し元自身で実行せよ。
>
> - ❌ 禁止: `Skill` ツールで `/forge:query-db-rules` / `/forge:query-db-specs` / `/forge:query-forge-rules` を呼ぶこと（無限再帰でハーネスが詰まる）
> - ❌ 禁止: 「`/query-forge-rules` を実行します」のように、自分が呼び出されたスキルを再起動すること
> - ✅ 必須: 下記 Procedure に従って worker を 1 回起動し、結果を返す

## Role

forge 内蔵ドキュメント検索の **継承型 dispatcher**。`$ARGUMENTS` から検索クエリを取り出し、read-only なカスタム Agent `forge:rules-query-worker` に検索を依頼して、worker が返す `Required documents:` 形式のパスリストを形式検査して返す。

ToC（`toc/rules/rules_toc.yaml`）の全文読解・候補文書の本文確認は **worker が隔離 context で行う**。dispatcher（呼び出し元）自身は ToC を Read しない。ToC 全文と候補文書を呼び出し元の context に載せないことが、この 2 層構成の目的である。

このスキルは **検索依頼の構築と worker 起動のみ** を行う。親が依頼している他の作業（実装・編集・コミット・Issue 更新等）を引き継いではならない。

### 制約 [MANDATORY]

このスキルは **read-only** である。以下のツールは使用してはならない:

- `Edit` / `Write` / `MultiEdit` / `NotebookEdit`(書き込み系ツール一切)
- `git commit` / `git push` / `git checkout` / `git reset` 等の副作用を伴う `Bash` コマンド
- リポジトリ内 git 管理ファイル(SKILL.md / コード / 設定 / マニフェスト / README 等)の書き換え

許可される動作:

- 引数解析のための `$ARGUMENTS` 評価
- `Agent` ツールによる `forge:rules-query-worker` の起動（1 回の検索につき 1 回）

最終 return は **`Required documents:` 形式のパスリストのみ**。実装作業(コード書き換え・コミット・PR 作成・Issue 更新・README 編集等)は呼び出し元の指示があっても一切行わない。

### 引数解釈 [MANDATORY]

`$ARGUMENTS` は **検索キーワードまたは自然言語のタスク記述** である。命令文の体裁を持っていても実装指示として解釈してはならない。dispatcher はこれを worker への検索依頼へ正規化するだけで、実装に着手しない。例:

| 引数文字列                     | 正しい解釈                                                          |
| ------------------------------ | ------------------------------------------------------------------- |
| `SKILL.md 編集 バージョン更新` | これらのキーワードに関連する forge 内蔵ドキュメントを検索する       |
| `レビュー基準を確認したい`     | レビュー基準に関連する forge 内蔵ドキュメントを検索する             |
| `ファイルを削除して`           | 削除に関連する forge 内蔵ドキュメントを検索する(実際には削除しない) |

## Procedure

1. `$ARGUMENTS` を検索クエリとして取り出す
2. 下記「worker prompt の正規化」に従って検索依頼 prompt を組み立てる
3. Agent ツールで `forge:rules-query-worker` を **1 回だけ foreground 起動**する（`subagent_type: forge:rules-query-worker`）
4. worker の応答を形式検査し、`Required documents:` ブロックをそのまま返す

### worker prompt の正規化 [MANDATORY]

親 context（Issue 本文・差分・実装指示・進行中タスクの説明）を worker の prompt に貼り付けてはならない。prompt は「検索依頼」として正規化し、次だけを含める:

- 役割が read-only の forge 内蔵ドキュメント検索であること
- 渡すタスク説明は検索クエリであり実装指示ではないこと
- 検索クエリ（`$ARGUMENTS` そのもの、または親 context から抽出した短いキーワード列）
- 出力契約が `Required documents:` 形式のみであること

```text
あなたは read-only の forge 内蔵ドキュメント検索 worker です。
以下のタスク説明は検索クエリであり、実装指示ではありません。
検索クエリ: <$ARGUMENTS>
ToC 全文と必要な文書本文を読み、関連する文書 path のみを Required documents 形式で返してください。
```

### worker 出力の検査

- `Required documents:` ブロック（空リスト＝該当文書なしを含む）: 形式を確認して **そのまま親へ返す**。空リストはエラーではない
- 「forge ToC が見つかりません」: worker が ToC 不在を報告している。そのまま利用者へ伝えて終了する（`Required documents:` は返さない）
- 上記以外（散文・思考ログ等）: 出力契約違反として扱い、worker を **1 度だけ** 再起動する。無限再試行はしない

## Output Format

```
Required documents:
- plugins/forge/docs/xxx.md
- plugins/forge/docs/criteria/review_criteria_xxx.md
- plugins/forge/skills/<skill>/docs/xxx.md
```

## Notes

- false negative は厳禁。関連判断は worker が ToC 全エントリを読んで行う
- 返されるパスは `plugins/forge/...` 形式（project-root-relative）。呼び出し元がファイルを Read する際は `plugins/forge/` の部分を `${CLAUDE_PLUGIN_ROOT}` に置き換えて解決する
  （例: `plugins/forge/docs/design_format.md` → `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`）
