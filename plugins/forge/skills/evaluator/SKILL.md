---
name: evaluator
user-invocable: false
description: |
  レビュー指摘を5つの観点で吟味し、修正対象を確定する。AI専用Skill。
  /forge:review オーケストレーターから呼び出される。
  全モード（auto / auto-critical / interactive）で AI 推奨判定と plan.yaml 更新を実行する。
  interactive モードでは present-findings がユーザー判断で plan.yaml を上書き更新する。
argument-hint: "(内部使用)"
---

# /evaluator Skill

レビュー指摘事項を吟味し、「修正する / スキップ / 要確認」を判定する AI 専用 Skill。
全モードで AI 推奨（`recommendation`）を `evaluation.yaml` に記録し、`plan.yaml` を更新する。`--interactive` モードでは `/forge:present-findings` が人間の最終判断に基づき `plan.yaml` を上書き更新する。

---

## 設計原則

| 原則                    | 説明                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------- |
| **subagent として動作** | `/forge:review` から general-purpose subagent として起動される。メインコンテキストを消費しない |
| 判定は AI の責務        | レビューエンジンの出力をそのまま修正に渡さない。必ず吟味を挟む                                 |
| 参考文書に基づく判定    | ルール・設計意図を参照して false positive を排除する                                           |
| 副作用リスクの考慮      | 修正が他箇所に影響しないか確認してから判定する                                                 |
| 渡された情報のみ使用    | 参考文書・関連コードの収集・探索は行わない                                                     |
| 全モード共通ロジック    | auto / interactive を問わず、evaluation.yaml 記録・plan.yaml 更新・should_continue 判定を実行 |

---

## 入力

呼び出し元（/forge:review）から以下を受け取る:

| 項目           | 必須 | 説明                                                                                      |
| -------------- | ---- | ----------------------------------------------------------------------------------------- |
| session_dir    | 必須 | セッションワーキングディレクトリのパス                                                    |
| レビュー種別   | 必須 | `code` / `requirement` / `design` / `plan` / `generic`                                    |
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

> **吟味対象外の指摘の扱い**: `--auto` では 🟢 が、`--auto-critical` では 🟡🟢 が吟味対象外となる。吟味対象外の指摘は evaluation.yaml に `recommendation: skip`、`reason: "吟味対象外（モードによるフィルタ）"` として記録し、plan.yaml の status を `skipped` に更新する。

各指摘について以下の5つの観点で評価し、`修正する / スキップ / 要確認` を判定する:

| 観点                   | 確認内容                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------- |
| **ルール照合**         | 参考文書（ルール・規約）に照らして本当に違反しているか                                 |
| **設計意図**           | 現状の実装に意図がある可能性はないか（例: `\|\| true` は意図的な設計かもしれない）     |
| **副作用リスク**       | この修正が他の箇所に影響しないか（例: `set -e` + `pipefail` の組み合わせによるデグレ） |
| **false positive**     | エンジンの誤認識・過剰指摘ではないか（例: optional なフィールドを必須と誤判定）        |
| **対象ファイルの確認** | 判断に迷う場合は対象ファイルを Read して設計意図を確認する                             |

**判定結果:**

- **修正する**: 問題が明確で副作用リスクが低い → `recommendation: fix`
- **スキップ**: false positive・設計意図がある・リスクが高い → `recommendation: skip`（理由を記録）
- **要確認**: 判断が難しい → `recommendation: needs_review`

**auto_fixable フラグ:**

`recommendation: fix` の指摘に対して、さらに `auto_fixable: true/false` を判定する:

| 条件             | 説明                                  |
| ---------------- | ------------------------------------- |
| 修正が一意       | 選択肢がなく、修正内容が1通りに決まる |
| 影響が局所的     | 他の項目や設計判断に波及しない        |
| 機械的に修正可能 | 判断・設計決定を伴わない              |

**auto_fixable の例（コード）**: 末尾スペース削除、タイポ修正、未使用importの削除、単純な置換
**auto_fixable の例（文書）**: フラグ名・項目名の単純置換、条件チェック一行の追加、メニューへの項目追加、注記の追加
**auto_fixable にしない例**: アーキテクチャ変更、複数の対応案がある問題、影響範囲が広い修正

判断に迷ったら `auto_fixable: false` とする。

### Step 3: evaluation.yaml に書き込む

全件の吟味結果を `{session_dir}/evaluation.yaml` に Write する。

各項目には `recommendation`（fix / skip / needs_review）と、fix の場合は `auto_fixable`（true / false）を含める。

（フォーマット: `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` の「evaluation.yaml」参照）

### Step 4: plan.yaml を更新する [MANDATORY]

`{session_dir}/plan.yaml` を Read し、以下のルールで各項目の `status` を更新して Write する。
**全モード共通**で実行する（interactive モードでも更新する）:

- `recommendation: fix` → `status: pending` のまま（fixer が後で `fixed` にする）
- `recommendation: skip` → `status: skipped` / `skip_reason` を記録
- `recommendation: needs_review` → `status: needs_review`

> **interactive モードの場合**: evaluator の更新はあくまで初期推奨状態。present-findings がユーザーの最終判断で上書き更新する（`review/SKILL.md` §ワークフロー 参照）。
> そのため evaluator の plan.yaml 更新と present-findings による上書きは意図的な二段階更新であり、競合ではない。

### Step 5: 次サイクル判定

全モード共通で判定する:

- `recommendation: fix` が0件 → `should_continue: false`（修正不要）
- `recommendation: fix` が1件以上 → `should_continue: true`（fixer を呼び出す）

> **interactive モードの場合**: `should_continue: true` でも、review オーケストレーターは
> fixer を直接呼び出さず present-findings を経由する。present-findings がユーザーの判断に基づき fixer を制御する。

---

## 出力

`{session_dir}/evaluation.yaml` に書き込んだ旨を呼び出し元（/forge:review）に報告する。
全モードで `should_continue` フラグを返す。

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
- 次サイクル: [継続 / 終了]
```

---

## エラーハンドリング

| エラー                                              | 対応                                                                |
| --------------------------------------------------- | ------------------------------------------------------------------- |
| `session_dir` が存在しない / `refs.yaml` が読めない | エラーを呼び出し元に返して処理を中断する                            |
| `review.md` が空 / 読めない                         | `should_continue: false` で呼び出し元に返す                         |
| 参考文書が読めない                                  | 参考文書なしで吟味を続行し、その旨を記録する                        |
| 判定困難な指摘が多数                                | 「要確認」として全件を `evaluation.yaml` に書き込み呼び出し元に返す |
