---
name: evaluator
user-invocable: false
description: |
  レビュー指摘を5つの観点で吟味し、修正対象を確定する。AI専用Skill。
  /forge:review オーケストレーターから呼び出される。
  --auto / --auto-critical モードで AI が判定者として機能する。
  --interactive モードでは全件の AI 推奨判定を evaluation.yaml に記録し、人間が最終判断する。
argument-hint: "(内部使用)"
---

# /evaluator Skill

レビュー指摘事項を吟味し、「修正する / スキップ / 要確認」を判定する AI 専用 Skill。
`--auto` / `--auto-critical` モードでは AI が一括判定し、`--interactive` モードでは AI 推奨を `evaluation.yaml` に記録したうえで `/forge:present-findings` が人間の最終判断を仲介する。

---

## 設計原則

| 原則 | 説明 |
|------|------|
| **subagent として動作** | `/forge:review` から general-purpose subagent として起動される。メインコンテキストを消費しない |
| 判定は AI の責務 | レビューエンジンの出力をそのまま修正に渡さない。必ず吟味を挟む |
| 参考文書に基づく判定 | ルール・設計意図を参照して false positive を排除する |
| 副作用リスクの考慮 | 修正が他箇所に影響しないか確認してから判定する |
| 渡された情報のみ使用 | 参考文書・関連コードの収集・探索は行わない |
| 対話モードでも常時実行 | `--interactive` フラグで対話モード時も AI 推奨を `evaluation.yaml` に記録する |

---

## 入力

呼び出し元（/forge:review）から以下を受け取る:

| 項目 | 必須 | 説明 |
|------|------|------|
| session_dir | 必須 | セッションワーキングディレクトリのパス |
| レビュー種別 | 必須 | `code` / `requirement` / `design` / `plan` / `generic` |
| 修正対象フラグ | 必須 | `--auto`: 🔴+🟡を対象 / `--auto-critical`: 🔴のみ対象 / `--interactive`: 全件AIが推奨判定 |

※ レビュー結果・参考文書・対象ファイル・related_code はすべて `session_dir` 内のファイルから読む

---

## ワークフロー

### Step 1: session_dir からデータを読み込む

1. `{session_dir}/refs.yaml` を Read して `reference_docs` / `related_code` / `target_files` / `review_criteria_path` を取得
2. `{session_dir}/review.md` を Read してレビュー結果（指摘事項リスト）を取得
3. `refs.yaml` の `reference_docs` / `related_code` のパスを全て Read して内容を把握する

（収集・探索は行わない。`refs.yaml` に記載されたパスのみ使用する）

### Step 2: 各指摘を吟味する [MANDATORY]

修正対象フラグに応じて吟味対象を絞り込む:
- `--auto`: 🔴致命的 + 🟡品質問題
- `--auto-critical`: 🔴致命的のみ
- `--interactive`: 全件（🔴🟡🟢）

各指摘について以下の5つの観点で評価し、`修正する / スキップ / 要確認` を判定する:

| 観点 | 確認内容 |
|------|---------|
| **ルール照合** | 参考文書（ルール・規約）に照らして本当に違反しているか |
| **設計意図** | 現状の実装に意図がある可能性はないか（例: `\|\| true` は意図的な設計かもしれない） |
| **副作用リスク** | この修正が他の箇所に影響しないか（例: `set -e` + `pipefail` の組み合わせによるデグレ） |
| **false positive** | エンジンの誤認識・過剰指摘ではないか（例: optional なフィールドを必須と誤判定） |
| **対象ファイルの確認** | 判断に迷う場合は対象ファイルを Read して設計意図を確認する |

**判定結果:**

- **修正する**: 問題が明確で副作用リスクが低い → `decision: fix`
- **スキップ**: false positive・設計意図がある・リスクが高い → `decision: skip`（理由を記録）
- **要確認**: 判断が難しい → `decision: needs_review`

### Step 3: evaluation.yaml に書き込む

全件の吟味結果を `{session_dir}/evaluation.yaml` に Write する。

（フォーマット: `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` の「evaluation.yaml」参照）

### Step 4: plan.yaml を更新する

`{session_dir}/plan.yaml` を Read し、以下のルールで各項目の `status` を更新して Write する:

- `--auto` / `--auto-critical` モードの場合:
  - `decision: fix` → `status: pending` のまま（fixer が後で `fixed` にする）
  - `decision: skip` → `status: skipped` / `skip_reason` を記録
  - `decision: needs_review` → `status: needs_review`

- `--interactive` モードの場合:
  - `plan.yaml` は更新しない（`evaluation.yaml` に推奨を書くだけ）
  - `present-findings` がユーザー判断後に `plan.yaml` を更新する

### Step 5: 次サイクル判定

- 「修正する（`decision: fix`）」が0件 → `should_continue: false`（修正不要）
- 「修正する（`decision: fix`）」が1件以上 → `should_continue: true`（fixer を呼び出す）
- `--interactive` モードの場合は常に `should_continue: false`（次サイクルは present-findings が制御）

---

## 出力

`{session_dir}/evaluation.yaml` に書き込んだ旨を呼び出し元（/forge:review）に報告する。
`--auto` / `--auto-critical` モード時のみ `should_continue` フラグを返す。

```
## 吟味結果

evaluation.yaml に書き込みました: {session_dir}/evaluation.yaml

### 修正する（X件）
1. **[問題名]**
   - 判定理由: [なぜ修正すべきか]

### スキップ（Y件）
1. **[問題名]**
   - スキップ理由: [false positive / 設計意図 / リスク等]

### 要確認（Z件）
1. **[問題名]**
   - 確認理由: [判断が難しい理由]

### 判定サマリー
- 修正する: X件
- スキップ: Y件
- 要確認: Z件
- 次サイクル: [継続 / 終了]  ※ --interactive モードでは省略
```

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| `session_dir` が存在しない / `refs.yaml` が読めない | エラーを呼び出し元に返して処理を中断する |
| `review.md` が空 / 読めない | `should_continue: false` で呼び出し元に返す |
| 参考文書が読めない | 参考文書なしで吟味を続行し、その旨を記録する |
| 判定困難な指摘が多数 | 「要確認」として全件を `evaluation.yaml` に書き込み呼び出し元に返す |
