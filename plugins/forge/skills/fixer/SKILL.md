---
name: fixer
user-invocable: false
description: |
  レビュー指摘事項に基づきコード・文書を修正する。
  /forge:present-findings からの対話的修正と /forge:review --auto からの自動修正で使用。
argument-hint: "<修正モード> (--single | --batch)"
---

# /fixer Skill

レビュー指摘事項に基づいてコード・文書を修正する AI 専用 Skill。
参考文書を収集し（DocAdvisor Skill または `.doc_structure.yaml` パスで Glob）、general-purpose subagent に修正を委譲する。

## 設計原則

| 原則                                                    | 説明                                                                              |
| ------------------------------------------------------- | --------------------------------------------------------------------------------- |
| 修正の実行は subagent                                   | メインコンテキストの消費を抑え、修正のコード Read/Edit を subagent 側で完結させる |
| 参考文書取得（DocAdvisor Skill or .doc_structure.yaml） | 設計意図・ルールを踏まえた修正を保証する                                          |
| 呼び出し元が入力に責任を持つ                            | 指摘事項・対象ファイル・種別を漏れなく渡す責務は呼び出し元にある                  |

## 入力・やりかた・Agent・出力

| 観点         | 内容                                                                                                                                                                       |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **入力**     | ① session_dir ② レビュー種別 ③ モード（--single / --batch）④ 対象項目の id（--single 必須）⑤ 修正方針（任意）                                                              |
| **やりかた** | plan.yaml（判定の真実）を自力 Read して `recommendation: fix` にフィルタ → `review_{perspective}.md`（最終系）から該当項目を抜粋 → refs.yaml の参考文書・関連コードと合わせて general-purpose subagent に修正を委譲 |
| **Agent**    | plan.yaml / refs.yaml / review_{perspective}.md Read: メインコンテキスト / 修正実行: general-purpose subagent                                                              |
| **出力**     | 修正サマリー（修正ファイル・修正内容・影響範囲）                                                                                                                           |

---

## 入力仕様 [MANDATORY]

### 修正モード

| `$ARGUMENTS` | モード   | 用途                                                                   |
| ------------ | -------- | ---------------------------------------------------------------------- |
| `--single`   | 1件修正  | /forge:present-findings の「段階的に解決」で 1 件ずつ修正              |
| `--batch`    | 一括修正 | /forge:present-findings の「✅を一括修正」、/forge:review の「--auto」 |

### 呼び出し元から受け取る情報 [MANDATORY]

呼び出し元（/forge:present-findings または /forge:review）は、以下を**漏れなく**提供する責務を持つ：

| 項目                       | 必須 | 説明                                                                                  |
| -------------------------- | ---- | ------------------------------------------------------------------------------------- |
| session_dir                | 必須 | セッションワーキングディレクトリのパス。fixer が plan.yaml / refs.yaml / review_{perspective}.md を自力 Read する |
| レビュー種別               | 必須 | `code` / `requirement` / `design` / `plan` / `generic`                                |
| モード                     | 必須 | `--single` または `--batch`                                                           |
| 対象項目の id              | 必須（--single）/ 任意（--batch） | --single: 処理対象の id 1 件 / --batch: 絞り込み用 id リスト（省略時は plan.yaml 全体からフィルタ） |
| ユーザーが選択した修正方針 | 任意 | AskUserQuestion の回答（A案/B案等）がある場合。通常 --single のみ                    |

> **指摘事項の詳細・対象ファイル・参考文書は呼び出し元からは渡さない**。
> fixer が session_dir から plan.yaml / refs.yaml / review_{perspective}.md を Read して自力で取得する。
> これにより親コンテキスト消費を抑え、plan.yaml の判定（recommendation）を fixer が直接尊重できる。

---

## ワークフロー

> **前提条件**: `.doc_structure.yaml` がプロジェクトルートに存在すること。
> 呼び出し元（`/forge:review` または `/forge:present-findings`）が事前に存在確認している前提で動作する。

### Step 1: 入力の受け取り

呼び出し元から指摘事項・対象ファイル・レビュー種別・参考文書パス・修正方針を受け取る。

入力が不足している場合は呼び出し元にエラーを返す（ユーザーに直接質問しない）。

### Step 2: 参考文書と plan.yaml の読み込み [MANDATORY]

1. **`{session_dir}/refs.yaml` を Read** して `reference_docs` / `related_code` を取得する。取得したパスをそのまま使用する。再収集は不要。

2. **`{session_dir}/plan.yaml` を Read** して各項目の `id` / `recommendation` / `auto_fixable` / `status` / `perspective` を取得する。

3. **モードに応じて処理対象をフィルタする**:

   #### `--batch` モード

   以下の条件を **AND** で満たす項目のみ処理する:

   - `recommendation: fix`
   - `status ∈ {pending, in_progress}`
   - 呼び出し元が id リストを渡した場合はそれと AND 条件で絞り込む

   **処理対象外**:

   - `recommendation: skip`（evaluator またはユーザーが却下した項目）
   - `recommendation: needs_review`（Claude の最終判断が必要な項目）
   - `status ∈ {fixed, skipped}`（処理済み）

   > evaluator / present-findings（ユーザー対話）の判定を**完全に尊重する**。
   > plan.yaml の recommendation を無視して修正するのは契約違反。

   #### `--single` モード

   - 呼び出し元から渡された `id` 1 件のみ処理
   - `status: in_progress` であることを確認（present-findings が修正選択時に更新済みの想定）
   - `recommendation: fix` でない id が渡された場合は呼び出し元にエラーを返す

4. **`{session_dir}/review_{perspective_name}.md`（最終系 = evaluator 整形済み）を Read** して、フィルタ後の id に対応する項目の詳細（箇所・該当コード・なぜ問題か・修正案）を抜粋する:

   - evaluator が**常に**書き換えている前提のため、parse 分岐は不要
   - **`.raw.md`（reviewer 原文）は読まない**（定常フローでは最終系のみ対象）
   - ユーザー対話後に更新された最新の内容を反映するため、ここで Read するタイミングを遅延させない

### Step 3: subagent 起動 [MANDATORY]

Fixer プロンプトテンプレートに従い、general-purpose subagent を起動する。

```
subagent_type: general-purpose
prompt: |
  [Fixer プロンプトテンプレートに基づいて構成]
```

subagent が全参考文書を Read し、修正を実行し、サマリーを報告する。

### Step 4: 結果を呼び出し元に返す

subagent の修正サマリーを呼び出し元に返す。呼び出し元（/forge:present-findings または /forge:review）がユーザーへの報告を担当する。

### Step 5: plan.yaml の更新

session_dir が提供されており、修正が成功した場合、スクリプトで更新する:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/update_plan.py {session_dir} \
  --id {修正した指摘事項のid} \
  --status fixed \
  --files-modified {修正したファイルパス一覧}
```

- `--fixed-at` は省略可能（省略時は現在時刻が自動設定される）

---

## Fixer プロンプトテンプレート [MANDATORY]

### --single モード（1件修正）

```
以下の指摘事項に基づいて修正を実行してください。

## 修正対象の指摘事項（id: {id}）
[`review_{perspective}.md`（最終系 = evaluator 整形済み）から該当項目を抜粋した詳細テキスト]
[該当箇所・該当コード・なぜ問題か・修正案を含む]

## ユーザーが選択した修正方針
[修正方針がある場合のみ記載。ない場合はこのセクションを省略]

## 対象ファイル（修正前に必ず Read すること）
[ファイルパスリスト]

## 参考文書（全て Read して理解すること）
### ルール文書
[収集したルール文書パスリスト]
### 要件定義書・設計書
[収集した仕様書パスリスト]

## 関連コード（実装パターン・規約の参考として Read すること）
[related_code のパスリストと関連性の説明]

## 指示
- 指摘事項に記載された問題のみを修正する
- 指摘事項に関係のない変更は一切行わない
- ユーザーが修正方針を選択している場合、その方針に従う
- 参考文書のルール・設計意図に従って修正する
- 関連コードの実装パターン・命名規則・スタイルに合わせて修正する
- 修正内容をサマリーで報告する

## 出力形式
### 修正サマリー
1. **[修正項目名]**
   - ファイル: [修正したファイルパス]
   - 内容: [何をどう変更したか 1-2行]
   - 影響: [他に確認が必要な箇所があれば記載、なければ「なし」]
```

> --batch では「修正方針」セクションを省略する。✅一括修正は修正が一意に決まる自明な項目のみ、--auto はユーザー介入なしのため。

### --batch モード（一括修正）

```
以下の指摘事項に基づいて修正を実行してください。
複数の指摘事項があります。全て修正してください。

## 修正対象の指摘事項
（plan.yaml で `recommendation: fix` AND `status ∈ {pending, in_progress}` にフィルタ後、
`review_{perspective}.md`（最終系）から該当項目を抜粋）

[指摘事項1の詳細テキスト（id: X）]

[指摘事項2の詳細テキスト（id: Y）]

...

## 対象ファイル
[全指摘事項に関連するファイルパスリスト]

## 参考文書（全て Read して理解すること）
### ルール文書
[収集したルール文書パスリスト]
### 要件定義書・設計書
[収集した仕様書パスリスト]

## 関連コード（実装パターン・規約の参考として Read すること）
[related_code のパスリストと関連性の説明]

## 指示
- 指摘事項に記載された問題のみを修正する
- 指摘事項に関係のない変更は一切行わない
- 参考文書のルール・設計意図に従って修正する
- 関連コードの実装パターン・命名規則・スタイルに合わせて修正する
- 各指摘事項ごとに修正内容をサマリーで報告する

## 出力形式
### 修正サマリー
1. **[修正項目名1]**
   - ファイル: [修正したファイルパス]
   - 内容: [何をどう変更したか 1-2行]
   - 影響: [他に確認が必要な箇所があれば記載、なければ「なし」]
2. **[修正項目名2]**
   - ファイル: ...
   ...
```

---

## エラーハンドリング

| エラー                                     | 対応                                                                                 |
| ------------------------------------------ | ------------------------------------------------------------------------------------ |
| 入力不足（session_dir なし・--single で id なし）        | 呼び出し元にエラーを返す。ユーザーに直接質問しない                     |
| refs.yaml / plan.yaml / review_{perspective}.md が存在しない・読み込み失敗 | エラー内容を呼び出し元に返す                                             |
| `--single` で渡された id が plan.yaml に存在しない / `recommendation ≠ fix` | エラー内容を呼び出し元に返す（skip / needs_review 項目の誤修正を防ぐ）  |
| `--batch` でフィルタ結果が 0 件                          | 正常終了扱いで「修正対象なし」を呼び出し元に返す                       |
| subagent 起動失敗                          | エラー内容を呼び出し元に返す                                                         |
| subagent が修正失敗を報告                  | エラー内容を呼び出し元に返す。呼び出し元がユーザーに報告                             |
| subagent が指摘事項と無関係な変更を報告    | 呼び出し元がサマリーを確認し、ユーザーに報告して判断を仰ぐ                           |
| plan.yaml の更新失敗                       | エラーを呼び出し元に報告するが、修正自体は成功扱いとする                             |

