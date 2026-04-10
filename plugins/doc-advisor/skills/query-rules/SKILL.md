---
name: query-rules
description: |
  Search document indexes to identify rule documents needed for a task.
  Supports ToC (keyword), Index (semantic), and hybrid (auto) modes.
  Trigger:
  - "What rules apply to this task?"
  - Before starting implementation work
context: fork
agent: general-purpose
model: sonnet
user-invocable: true
argument-hint: "[--toc|--index] task description"
---

## Role

タスク内容を分析し、関連するルール文書のパスリストを返す。

## 引数パース

`$ARGUMENTS` を解析する:
- `--toc` で始まる → `mode = toc`、残りを `{task}` とする
- `--index` で始まる → `mode = index`、残りを `{task}` とする
- フラグなし → `mode = auto`、全体を `{task}` とする

---

## mode = toc

`${CLAUDE_PLUGIN_ROOT}/docs/query_toc_workflow.md` を Read し、`category = rules` として手順に従う。

- ToC が存在しない場合: AskUserQuestion で `/doc-advisor:create-rules-toc` の実行を案内する。**Index にフォールバックしない**
- 候補あり → Step: 最終判定 へ

## mode = index

`${CLAUDE_PLUGIN_ROOT}/docs/query_index_workflow.md` を Read し、`category = rules` として手順に従う。

- Index 構築に失敗した場合（OPENAI_API_KEY 未設定等）: AskUserQuestion でエラー内容を通知する。**ToC にフォールバックしない**
- 候補あり → Step: 最終判定 へ

## mode = auto（デフォルト）

### Step 1: Index 候補生成

`${CLAUDE_PLUGIN_ROOT}/docs/query_index_workflow.md` を Read し、`category = rules` として手順に従う。
候補パスを内部保持する。失敗時は Index 候補 = 空。

### Step 2: ToC 候補生成

`${CLAUDE_PLUGIN_ROOT}/docs/query_toc_workflow.md` を Read し、`category = rules` として手順に従う。
候補パスを内部保持する。ToC 不在時は ToC 候補 = 空。

### Step 3: 統合

| Index | ToC | 動作 |
|-------|-----|------|
| あり | あり | union(Index候補, ToC候補) で重複排除 → Step: 最終判定 |
| あり | なし | Index 候補をそのまま使用 → Step: 最終判定 |
| なし | あり | ToC 候補をそのまま使用 → Step: 最終判定 |
| なし | なし | AskUserQuestion で通知（`/doc-advisor:create-rules-toc` 実行 or `OPENAI_API_KEY` 設定を案内） |

---

## Step: 最終判定

1. 統合された候補パスリストの各ファイルを Read して関連性を確認する
2. 確認済みのパスのみを最終リストに含める
3. **false negative 厳禁。迷ったら含める**

## Output Format

```
Required documents:
- rules/core/xxx.md
- rules/layer/domain/xxx.md
- rules/workflow/xxx/xxx.md
- rules/format/xxx.md
```

## Notes

- False negative 厳禁。迷ったら含める
- requirements, design documents, plans は対象外（/doc-advisor:query-specs を使う）
- 対象は `.doc_structure.yaml` の `rules.root_dirs` で設定されたルール文書のみ

## Error Handling

スクリプトが `{"status": "config_required", ...}` を出力した場合:
AskUserQuestion で `/forge:setup-doc-structure` の実行を案内する
