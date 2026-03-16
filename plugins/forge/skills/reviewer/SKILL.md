---
name: reviewer
user-invocable: false
description: |
  参考文書を読んでレビューを実行する。AI専用Skill。
  /forge:review オーケストレーターから呼び出される。
  参考文書収集・target_files 解決は呼び出し元（/forge:review）が担う。
  session_dir 経由でデータを受け渡し、結果は review.md / plan.yaml に書き出す。
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
| スコープ    | 任意 | `--diff-only {files}` — fixer の変更差分のみをレビュー |

target_files / reference_docs / related_code / review_criteria_path は `{session_dir}/refs.yaml` から読み取る。

### スコープ指定（`--diff-only`）

`--diff-only` が指定された場合、refs.yaml の target_files ではなく指定されたファイルの変更差分のみをレビューする。
これは fixer による修正が新たな問題を引き起こしていないか確認するための**単独修正レビュー**に使用する。

- レビュー対象: 指定されたファイルの変更差分（`git diff` 相当）
- 参考文書: refs.yaml の reference_docs / review_criteria_path をそのまま使用
- 出力: `{session_dir}/review.md` を**上書きせず**、修正起因の問題のみを呼び出し元に返す
- plan.yaml: 更新しない（呼び出し元が判断）

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

スクリプトでレビューを実行する:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/review/scripts/run_review_engine.sh {session_dir}/review.md <project_dir> "<prompt>"
```

| 終了コード | 意味 | 次のアクション |
|-----------|------|--------------|
| 0 | 成功（review.md に結果が書き出された） | Phase 2 完了 |
| 2 | Codex が見つからない | Claude フォールバックへ |
| 1 | Codex 実行エラー | エラー報告 |

スクリプトは `codex exec -o` で最終メッセージのみをファイルに書き出す（stdout リダイレクトではセッション全体が混入するため）。

#### Claude の場合（Codex 不在時のフォールバック含む）

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
`${CLAUDE_SKILL_DIR}/templates/review.md` を Read し、そのフォーマットをコピーして指摘を埋めること。
見出し形式（### 1. ...）ではなく、番号付きリスト（1. **[問題名]**: ...）で記述すること。
該当なしのセクションはセクションごと削除すること。

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

スクリプトで review.md から指摘事項を抽出し、plan.yaml を生成する:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/extract_review_findings.py {session_dir}/review.md {session_dir}/plan.yaml
```

JSON 出力でサマリーを確認:
```json
{"status": "ok", "total": 10, "critical": 3, "major": 5, "minor": 2}
```

`status: "error"` の場合はエラー内容を報告して終了する。

（フォーマット: `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` の「plan.yaml」参照）
