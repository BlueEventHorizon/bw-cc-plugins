---
name: reviewer
user-invocable: false
description: |
  参考文書を読んでレビューを実行する。AI専用Skill。
  /forge:review オーケストレーターから呼び出される。
  参考文書収集・target_files 解決は呼び出し元（/forge:review）が担う。
argument-hint: "<種別> [--エンジン]"
---

# /reviewer Skill

参考文書を読み、対象ファイルをレビューして結果をファイルに書き出す AI 専用 Skill。
参考文書収集・対象ファイル解決は `/forge:review` オーケストレーターが事前に実施する。

## 設計原則

| 原則                         | 説明                                                                                           |
| ---------------------------- | ---------------------------------------------------------------------------------------------- |
| **subagent として動作**      | `/forge:review` から general-purpose subagent として起動される。メインコンテキストを消費しない |
| レビュー実行も subagent      | Codex または Claude subagent にレビューを委譲する                                              |
| ファイル経由のデータ受け渡し | 入力は `session_dir` の refs.yaml から読み取り、出力は review.md / plan.yaml に書き出す        |

---

## 入力

呼び出し元（/forge:review）から以下を受け取る:

| 項目        | 必須 | 説明                                                   |
| ----------- | ---- | ------------------------------------------------------ |
| session_dir | 必須 | セッションワーキングディレクトリのパス                 |
| 種別        | 必須 | `code` / `requirement` / `design` / `plan` / `generic` |
| エンジン    | 必須 | `codex` / `claude`                                     |

target_files / reference_docs / related_code / review_criteria_path は `{session_dir}/refs.yaml` から読み取る。

---

## ワークフロー

### Phase 1: refs.yaml を読んで参考文書・関連コードを取得する

1. `{session_dir}/refs.yaml` を Read する
2. `refs.yaml` から以下を取得する:
   - `target_files`: レビュー対象ファイルパス一覧
   - `reference_docs`: 参考文書パス一覧
   - `review_criteria_path`: レビュー観点ファイルのパス
   - `related_code`: 関連コードのパスと関連性の説明（任意）
3. 取得した `reference_docs` のパスを全て Read して、ルール・設計意図を把握する
4. 取得した `related_code` のパスも Read して、既存実装のパターン・規約を把握する
   （参考文書・関連コードの収集・探索は行わない。refs.yaml に記載されたパスのみ使用する）

### Phase 2: レビュー実行

#### 種別と review_criteria の観点セクション対応

| 種別          | review_criteria のセクション                                    |
| ------------- | --------------------------------------------------------------- |
| `requirement` | 「1. 要件定義書レビュー観点」                                   |
| `design`      | 「2. 設計書レビュー観点」                                       |
| `plan`        | 「3. 計画書レビュー観点」                                       |
| `code`        | 「4. コードレビュー観点」                                       |
| `generic`     | 「5. 汎用文書レビュー観点」（なければフォールバック観点を使用） |

#### Codex の場合

```bash
codex exec --full-auto --sandbox read-only --cd <project_dir> "<prompt>" > {session_dir}/review.md
```

シェルリダイレクトにより、レビュー結果をコンテキストに乗せずに直接ファイルへ保存する。

#### Claude の場合

general-purpose subagent を起動し、レビュー結果を `{session_dir}/review.md` に Write するよう指示する。

#### プロンプト構成

```
以下をレビューしてください。

## レビュー対象
<target_files のパス>

## レビュー種別
<要件定義書 / 設計書 / 計画書 / コード / 汎用文書レビュー（generic）>

## 参考文書（必ず読んでからレビュー）
- {review_criteria_path} の「{観点セクション名}」
- <reference_docs のパス>

## 追加指示（generic 種別の場合のみ付加）
- 対象ファイルが参照するファイルパス・コマンド構文が実際に有効か検証すること
- 必要に応じて関連ファイルを自発的に探索し、整合性を確認すること

## 出力形式
### 🔴致命的問題
1. **[問題名]**: [説明]
   - 箇所: [ファイル:行]
   - 修正案: [具体的な修正]

### 🟡品質問題
1. **[問題名]**: [説明]
   - 箇所: [ファイル:行]

### 🟢改善提案
1. **[提案名]**: [説明]

### サマリー
- 🔴致命的: X件
- 🟡品質: X件
- 🟢改善: X件

確認や質問は不要です。具体的な指摘と修正案を出力してください。
```

**フォールバック観点**（review_criteria にセクションがない場合、プロンプトに埋め込む）:

```
🔴致命的: 事実の誤り、論理矛盾、参照切れ、必須情報の欠落
🟡品質: 構成の一貫性、用語の不統一、責務の曖昧さ、記述の重複
🟢改善: 表現の明確化、構成改善、不足情報の補完
```

---

## 出力

### review.md の書き出し

レビュー完了後、結果は `{session_dir}/review.md` に保存済みの状態となる（Codex はリダイレクト、Claude は subagent が Write）。

### plan.yaml の初期作成

**注意**: YAML フォーマットを厳密に遵守すること（`session_format.md` のスキーマ参照）。フィールド漏れ・インデントミスに注意。将来的にはスクリプト化を検討。

`{session_dir}/review.md` から指摘事項を解析し、`{session_dir}/plan.yaml` を初期作成する:

1. review.md 内の 🔴🟡🟢 マーカー付き指摘事項を全て抽出してリスト化する
2. 各指摘事項に対して以下のフィールドを設定する:
   - `id`: 1 からの連番
   - `severity`: 🔴 → `critical` / 🟡 → `major` / 🟢 → `minor`
   - `title`: 指摘事項の問題名（`**[問題名]**` から抽出）
   - `status`: `pending`（全件）
   - `fixed_at`: `""`
   - `files_modified`: `[]`
   - `skip_reason`: `""`
3. plan.yaml を Write で書き出す

（フォーマット: `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` の「plan.yaml」参照）
