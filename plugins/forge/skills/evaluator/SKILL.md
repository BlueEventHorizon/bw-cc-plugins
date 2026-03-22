---
name: evaluator
user-invocable: false
description: |
  レビュー指摘を5つの観点で吟味し、修正対象を確定する。AI専用Skill。
  /forge:review オーケストレーターから perspective ごとに並列起動される。
  全モード（auto / auto-critical / interactive）で AI 推奨判定と plan.yaml 更新を実行する。
  interactive モードでは present-findings がユーザー判断で plan.yaml を上書き更新する。
argument-hint: "(内部使用)"
---

# /evaluator Skill

レビュー指摘事項を吟味し、「修正する / スキップ / 要確認」を判定する AI 専用 Skill。
perspective ごとに並列起動され、担当の `review_{perspective}.md` の指摘を吟味する。
全モードで AI 推奨（`recommendation`）を `plan.yaml` に記録する。`--interactive` モードでは `/forge:present-findings` が人間の最終判断に基づき `plan.yaml` を上書き更新する。

---

## 設計原則

| 原則                    | 説明                                                                                           |
| ----------------------- | ---------------------------------------------------------------------------------------------- |
| **subagent として動作** | `/forge:review` から general-purpose subagent として起動される。メインコンテキストを消費しない |
| **perspective ごとに並列起動** | オーケストレーターが perspectives の数だけ evaluator を並列起動する。各 evaluator は担当の `review_{perspective}.md` のみ処理する |
| 判定は AI の責務        | レビューエンジンの出力をそのまま修正に渡さない。必ず吟味を挟む                                 |
| 参考文書に基づく判定    | ルール・設計意図を参照して false positive を排除する                                           |
| 副作用リスクの考慮      | 修正が他箇所に影響しないか確認してから判定する                                                 |
| 渡された情報のみ使用    | 参考文書・関連コードの収集・探索は行わない                                                     |
| 全モード共通ロジック    | auto / interactive を問わず、plan.yaml 更新・should_continue 判定を実行                       |

---

## 入力

呼び出し元（/forge:review）から以下を受け取る:

| 項目             | 必須 | 説明                                                                                      |
| ---------------- | ---- | ----------------------------------------------------------------------------------------- |
| session_dir      | 必須 | セッションワーキングディレクトリのパス                                                    |
| レビュー種別     | 必須 | `code` / `requirement` / `design` / `plan` / `generic`                                    |
| perspective_name | 必須 | 担当する perspective の識別子（例: `correctness`, `resilience`）                           |
| 修正対象フラグ   | 必須 | `--auto`: 🔴+🟡を対象 / `--auto-critical`: 🔴のみ対象 / `--interactive`: 全件AIが推奨判定 |

※ レビュー結果は `{session_dir}/review_{perspective_name}.md` から読む
※ 参考文書・対象ファイル・related_code はすべて `{session_dir}/refs.yaml` から読む

---

## ワークフロー

### Step 1: session_dir からデータを読み込む

1. `{session_dir}/refs.yaml` を Read して `reference_docs` / `related_code` / `target_files` を取得
2. `{session_dir}/review_{perspective_name}.md` を Read してレビュー結果（指摘事項リスト）を取得
3. `refs.yaml` の `reference_docs` / `related_code` のパスを全て Read して内容を把握する

（収集・探索は行わない。`refs.yaml` に記載されたパスのみ使用する）

### Step 2: 各指摘を吟味する [MANDATORY]

修正対象フラグに応じて吟味対象を絞り込む:

- `--auto`: 🔴致命的 + 🟡品質問題
- `--auto-critical`: 🔴致命的のみ
- `--interactive`: 全件（🔴🟡🟢）

> **吟味対象外の指摘の扱い**: `--auto` では 🟢 が、`--auto-critical` では 🟡🟢 が吟味対象外となる。吟味対象外の指摘は plan.yaml に `recommendation: skip`、`reason: "吟味対象外（モードによるフィルタ）"` として記録し、`status` を `skipped` に更新する。

#### 判定の原則 [MANDATORY]

**reviewer の主張を鵜呑みにしない。** reviewer はレビューエンジンの出力であり、false positive を含む。evaluator の責務は各指摘が本当に問題かを**対象ファイルを読んで検証する**ことである。

- **対象ファイルを Read して問題の実在を確認できない場合は skip とする**
- reviewer が「L77 に問題がある」と主張しても、L77 を読んで確認する
- 入力バリデーション不足の指摘は、上流のバリデーションコードを確認してから判定する
- 実行順序に依存する指摘は、呼び出し元のワークフローを確認してから判定する

#### 吟味の5観点

各指摘について以下の5つの観点で評価し、`修正する / スキップ / 要確認` を判定する:

| 観点                   | 確認内容                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------- |
| **対象ファイルの確認** | 指摘された箇所を Read し、reviewer の主張が正しいか検証する [MANDATORY — 全件で実施] |
| **ルール照合**         | 参考文書（ルール・規約）に照らして本当に違反しているか                                 |
| **設計意図**           | 現状の実装に意図がある可能性はないか（例: `\|\| true` は意図的な設計かもしれない）     |
| **副作用リスク**       | この修正が他の箇所に影響しないか（例: `set -e` + `pipefail` の組み合わせによるデグレ） |
| **false positive**     | エンジンの誤認識・過剰指摘ではないか（例: optional なフィールドを必須と誤判定、バリデーション済みの入力を未検証と誤認） |

**判定結果:**

- **修正する**: 対象ファイルを読んで問題の実在を確認でき、副作用リスクが低い → `recommendation: fix`
- **スキップ**: 対象ファイルを読んで問題が存在しない・設計意図がある・既に対処済み → `recommendation: skip`（理由を記録）
- **要確認**: 対象ファイルを読んでも判断が難しい → `recommendation: needs_review`

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

> **注意**: `auto_fixable: true` と判定する前に、修正が本当に一意に決まるか対象ファイルのコンテキスト（上流のバリデーション、呼び出し元のワークフロー、関連する他ファイル）を確認すること。

### Step 3: 結果ファイルを書き出す [MANDATORY]

吟味結果を JSON に構造化し、`{session_dir}/eval_{perspective_name}.json` に Write する。**plan.yaml には直接書き込まない**（並列 agent の出力契約パターン。設計書 §4 参照）。

以下のルールで各項目の更新内容を決定する:

- `recommendation: fix` → `status: pending` のまま（fixer が後で `fixed` にする）。`auto_fixable` と `reason` を付与
- `recommendation: skip` → `status: skipped` / `skip_reason` と `reason` を記録
- `recommendation: needs_review` → `status: needs_review` / `reason` を記録

結果ファイルのフォーマット:
```json
{
  "perspective": "{perspective_name}",
  "updates": [
    {"id": 1, "status": "pending", "recommendation": "fix", "auto_fixable": true, "reason": "判定理由"},
    {"id": 2, "status": "skipped", "skip_reason": "理由", "recommendation": "skip", "reason": "判定理由"},
    {"id": 3, "status": "needs_review", "recommendation": "needs_review", "reason": "判定理由"}
  ]
}
```

Write 先: `{session_dir}/eval_{perspective_name}.json`

> **plan.yaml の更新は orchestrator の責務**: 全 evaluator 完了後、review orchestrator が `eval_*.json` を収集し `update_plan.py --batch` を1回だけ呼び出す。これにより並列書き込み競合が根本的に排除される。
> **interactive モードの場合**: orchestrator が plan.yaml を更新した後、present-findings がユーザーの最終判断で上書き更新する。

### Step 4: 次サイクル判定

全モード共通で判定する:

- `recommendation: fix` が0件 → `should_continue: false`（修正不要）
- `recommendation: fix` が1件以上 → `should_continue: true`（fixer を呼び出す）

> **interactive モードの場合**: `should_continue: true` でも、review オーケストレーターは
> fixer を直接呼び出さず present-findings を経由する。present-findings がユーザーの判断に基づき fixer を制御する。

---

## 出力

結果ファイルを書き出した旨を呼び出し元（/forge:review）に報告する。
全モードで `should_continue` フラグを返す。

```
## 吟味結果（perspective: {perspective_name}）

結果ファイル: {session_dir}/eval_{perspective_name}.json

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
| `review_{perspective_name}.md` が空 / 読めない       | `should_continue: false` で呼び出し元に返す                         |
| 参考文書が読めない                                  | 参考文書なしで吟味を続行し、その旨を記録する                        |
| 判定困難な指摘が多数                                | 「要確認」として全件を `plan.yaml` に書き込み呼び出し元に返す       |
