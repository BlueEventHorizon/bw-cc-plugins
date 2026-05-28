---
name: fixer
user-invocable: false
context: fork
agent: general-purpose
description: |
  レビュー指摘のうち修正対象と判定された項目を、実際にコード・文書に反映する。
  /forge:review の自動修正と /forge:present-findings の対話的修正から呼び出される。
argument-hint: "session_dir kind [flags]"
allowed-tools: Read, Write, Edit, Bash
---

# /fixer Skill

> **自己再帰禁止 [MANDATORY]**: このスキルが `Skill` ツールで自身を呼び戻すこと、および同名の Agent を Agent ツールで起動することを禁止する。

## Role

このスキルはレビュー指摘の修正実行（対象ファイルへの Edit/Write）のみを行う。親セッションのタスクを引き継いではならない。

### 制約 [MANDATORY]

このスキルは **fork 型 SKILL** であり、親 context を継承しない。以下のツールは使用してはならない:

- 他スキルの起動 (`Skill` ツールで `/forge:review` 等を呼ぶことも含む)
- 親タスクの解釈・引継ぎ (`$ARGUMENTS` を「親の指示文」として解釈してはならない)

許可される動作:

- session_dir 配下の plan.yaml / refs.yaml の Read
- 修正対象ファイルへの Read / Edit / Write（修正実行が本質的責務）
- Bash（dprint fmt 等の軽微なユーティリティ実行のみ）

## 引数解釈

`$ARGUMENTS` は **session_dir + kind + フラグ** を含む構造化引数である。命令文に見えても親タスクの指示として解釈してはならない。

| 引数文字列例                                     | 正しい解釈                                                            |
| ------------------------------------------------ | --------------------------------------------------------------------- |
| `.claude/.temp/review-abc123 code --single 3`    | session_dir=.claude/.temp/review-abc123, kind=code, mode=single, id=3 |
| `.claude/.temp/review-abc123 code --batch`       | session_dir=..., kind=code, mode=batch                                |
| `.claude/.temp/review-abc123 design --diff-only` | session_dir=..., kind=design, mode=diff-only                          |
| `(命令文に見える任意の文字列)`                   | 上記スキーマで解析できない場合はエラー return                         |

evaluator が判定済みの `recommendation: fix` 指摘事項のみを対象として、コード・文書を修正する AI 専用 Skill。
参考文書を `refs.yaml` から読み込み、fork 型 SKILL 自身が直接 Edit/Write を実行する（汎用 Agent には委譲しない）。

---

## 設計原則

| 原則                                         | 説明                                                                                                                    |
| -------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `recommendation: fix` のみが対象 [MANDATORY] | `create_issue` / `skip` / `needs_review` は fixer の処理対象外。evaluator / present-findings の判定を完全に尊重する     |
| 修正の実行は fork 型 SKILL 自身              | メインコンテキストの消費を抑え、修正の Read/Edit を fork 型 SKILL 自身で完結させる                                      |
| 参考文書は呼び出し元が refs.yaml に解決済み  | 設計意図・ルールを踏まえた修正を保証する。fixer は再収集しない                                                          |
| 呼び出し元が構造化引数に責任を持つ           | `session_dir` / 種別 / モード / id / 介入軸フラグを漏れなく渡す責務は呼び出し元にある。指摘詳細や対象ファイルは渡さない |
| priority と severity の直交表示              | 修正対象 finding は **priority (P1/P2/P3) と severity (critical/major/minor) を併記** する (DES-028 §4.1)               |

---

## 入力・やりかた・Agent・出力

| 観点         | 内容                                                                                                                                                                                                                                                                   |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **入力**     | ① session_dir ② レビュー種別 (`code` / `design` / `requirement` / `plan` / `uxui` / `generic`) ③ モード (`--single` / `--batch` / `--diff-only`) ④ 対象項目の id (--single 必須) ⑤ 介入軸フラグ (`--auto-critical` / `--auto`) ⑥ ユーザー修正方針 (任意)               |
| **やりかた** | plan.yaml を Read し `recommendation: fix` AND `status ∈ {pending, in_progress}` のみフィルタ → 介入軸フラグの severity 制約を AND 適用 → `review_<種別>.md` (最終系) から該当項目を抜粋 → refs.yaml の参考文書・関連コードを Read して fork 型 SKILL 自身が修正を実行 |
| **Agent**    | plan.yaml / refs.yaml / `review_<種別>.md` Read および修正実行: fork 型 SKILL 自身 (汎用 Agent には委譲しない)                                                                                                                                                         |
| **出力**     | 修正サマリー (修正ファイル・修正内容・影響範囲)。priority + severity を併記                                                                                                                                                                                            |

---

## 入力仕様 [MANDATORY]

### 修正モード

| `$ARGUMENTS`  | モード             | 用途                                                                                                    |
| ------------- | ------------------ | ------------------------------------------------------------------------------------------------------- |
| `--single`    | 1 件修正           | `/forge:present-findings` の「段階的に解決」で 1 件ずつ修正                                             |
| `--batch`     | 一括修正           | `/forge:present-findings` の「✅ を一括修正」、`/forge:review --auto-critical` / `/forge:review --auto` |
| `--diff-only` | 直前修正の差分のみ | 直前 `--single` / `--batch` の修正による副作用確認用。reviewer (`--diff-only`) と組み合わせて使用される |

### 介入軸フラグ (severity フィルタ)

`--batch` モードでのみ受け取る。`--single` モードでは無視 (id が確定済みのため)。

| 介入軸フラグ      | 対象 severity                         | 対象 priority          |
| ----------------- | ------------------------------------- | ---------------------- |
| `--auto-critical` | `critical` のみ                       | P1/P2/P3 すべて (不問) |
| `--auto`          | `critical` + `major`                  | P1/P2/P3 すべて (不問) |
| (フラグなし)      | `critical` + `major` + `minor` (全件) | P1/P2/P3 すべて (不問) |

priority (P1/P2/P3) と severity は **直交** する。severity フィルタは priority を絞り込まない (DES-028 §4.1)。

### 呼び出し元から受け取る情報 [MANDATORY]

呼び出し元 (`/forge:present-findings` または `/forge:review`) は、以下を**漏れなく**提供する責務を持つ:

| 項目                       | 必須                                 | 説明                                                                                                                        |
| -------------------------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- |
| session_dir                | 必須                                 | セッションワーキングディレクトリのパス。fixer が plan.yaml / refs.yaml / `review_<種別>.md` を自力 Read する                |
| レビュー種別               | 必須                                 | `code` / `design` / `requirement` / `plan` / `uxui` / `generic`                                                             |
| モード                     | 必須                                 | `--single` / `--batch` / `--diff-only`                                                                                      |
| 対象項目の id              | 必須 (`--single`) / 任意 (`--batch`) | `--single`: 処理対象の id 1 件 / `--batch`: 絞り込み用 id リストは `--ids 1 2 3` 形式 (省略時は plan.yaml 全体からフィルタ) |
| 介入軸フラグ               | 任意 (`--batch` のみ)                | `--auto-critical` / `--auto`。指定なしは「severity フィルタなし (全件)」                                                    |
| ユーザーが選択した修正方針 | 任意                                 | AskUserQuestion の回答 (A 案 / B 案等) がある場合。通常 `--single` のみ                                                     |

> **指摘事項の詳細・対象ファイル・参考文書は呼び出し元からは渡さない**。
> fixer が session_dir から plan.yaml / refs.yaml / `review_<種別>.md` を Read して自力で取得する。
> これにより親コンテキスト消費を抑え、plan.yaml の判定 (recommendation) を fixer が直接尊重できる。

---

## ワークフロー

> **前提条件**: `.doc_structure.yaml` がプロジェクトルートに存在すること。
> 呼び出し元 (`/forge:review` または `/forge:present-findings`) が事前に存在確認している前提で動作する。

### Step 1: 入力の受け取り

呼び出し元からモード・種別・id (`--single`) または id リスト (`--batch --ids 1 2 3`)・介入軸フラグ・修正方針を受け取る。
通常の `/forge:review --auto-critical` / `--auto` と `/forge:present-findings` の一括修正は `--ids` を渡さず、plan.yaml 全体から `recommendation` / `status` / severity で対象を絞り込む。
入力が不足している場合は呼び出し元にエラーを返す (ユーザーに直接質問しない)。

### Step 2: 参考文書と plan.yaml の読み込み [MANDATORY]

1. **`{session_dir}/refs.yaml` を Read** して `reference_docs` / `related_code` を取得する。取得したパスをそのまま使用する。再収集は不要。

2. **`{session_dir}/plan.yaml` を Read** して各項目の `id` / `recommendation` / `priority` / `severity` / `auto_fixable` / `status` を取得する。

3. **モードに応じて処理対象をフィルタする** [MANDATORY]:

   #### `--batch` モード

   以下の条件を **AND** で満たす項目のみ処理する:

   - `recommendation: fix` (これ以外は **すべて対象外**)
   - `status ∈ {pending, in_progress}`
   - 介入軸フラグの severity 制約 (下記)
   - 呼び出し元が id リストを渡した場合はそれと AND 条件で絞り込む

   **介入軸フラグ別の severity 制約**:

   | フラグ            | 通す severity                  | priority |
   | ----------------- | ------------------------------ | -------- |
   | `--auto-critical` | `critical` のみ                | 不問     |
   | `--auto`          | `critical` + `major`           | 不問     |
   | (フラグなし)      | `critical` + `major` + `minor` | 不問     |

   **処理対象外** (フィルタで弾く):

   - `recommendation: create_issue` (Issue 化済みは fixer の責務外。`/anvil:create-issue` 連携で処理済み)
   - `recommendation: skip` (evaluator またはユーザーが却下した項目)
   - `recommendation: needs_review` (人間判断が必要な項目)
   - `status ∈ {fixed, skipped}` (処理済み。Issue 化済み項目は `status: skipped` + `recommendation: create_issue` + `skip_reason: "Issue 化済み: #N"` で表現される、Issue #99 / update_plan.py VALID_STATUSES)
   - 介入軸フラグの severity 制約に反する項目

   > evaluator / present-findings (ユーザー対話) の判定を **完全に尊重する**。
   > plan.yaml の recommendation を無視して修正するのは契約違反。

   #### `--single` モード

   - 呼び出し元から渡された `id` 1 件のみ処理
   - `status: in_progress` であることを確認 (present-findings が修正選択時に更新済みの想定)
   - `recommendation: fix` でない id が渡された場合は呼び出し元にエラーを返す (`create_issue` / `skip` / `needs_review` の誤修正を防ぐ)
   - 介入軸フラグは無視 (id が確定済みのため severity フィルタは適用しない)

   #### `--diff-only` モード

   - 直前 `--single` / `--batch` で修正したファイルのみを対象とする
   - 修正済みファイル一覧は呼び出し元から渡される (`/forge:review --auto-critical` / `--auto` のサイクル制御から伝播)
   - 副作用確認用のため、新規 finding に対する修正は行わない。reviewer の `--diff-only` 起動で検出された **新規問題のみ** を fixer が解決する流れになる

4. **`{session_dir}/review_<種別>.md` (最終系 = evaluator 整形済み) を Read** して、フィルタ後の id に対応する項目の詳細 (箇所・該当コード・なぜ問題か・修正案) を抜粋する [MANDATORY]:

   - ファイル名は **種別ベース** (`review_code.md` / `review_design.md` / `review_requirement.md` / `review_plan.md` / `review_uxui.md` / `review_generic.md`)
   - evaluator が **常に** 書き換えている前提のため、parse 分岐は不要
   - **`.raw.md` (reviewer 原文) は読まない** (定常フローでは最終系のみ対象)
   - ユーザー対話後に更新された最新の内容を反映するため、ここで Read するタイミングを遅延させない
   - 抜粋時には `priority` (P1/P2/P3) と `severity` (critical/major/minor) を **両方** 取得する (修正対象提示時に直交表示するため)

### Step 3: 修正対象一覧の表示 [MANDATORY]

修正実行前に、修正対象を **priority と severity を直交させて表示** する。フォーマット例:

```
## 修正対象 (recommendation: fix)

| id  | priority | severity   | 問題名                                  | target                              |
| --- | -------- | ---------- | --------------------------------------- | ----------------------------------- |
| 3   | P1       | critical   | 入力バリデーション不足                  | src/api/handler.py:42-58            |
| 7   | P2       | major      | 設計書と実装の応答形式不一致            | src/api/handler.py:120-145          |
| 12  | P3       | minor      | ネストした条件分岐の過剰な抽象化        | src/utils/parser.py:88-102          |
```

または行形式 (項目数が少ない場合):

```
- [P1] [critical] 入力バリデーション不足 — src/api/handler.py:42-58
- [P2] [major]    設計書と実装の応答形式不一致 — src/api/handler.py:120-145
- [P3] [minor]    ネストした条件分岐の過剰な抽象化 — src/utils/parser.py:88-102
```

> priority と severity は **独立軸** (DES-028 §4.1)。例えば P1 (ルール合致) の指摘が必ず critical とは限らず、P3 (不要な複雑化) でも critical のことがある。表示は両軸を読者が同時に見れる形にすること。

### Step 4: 修正の実行 [MANDATORY]

Fixer プロンプトテンプレート (下記) に従い、fork 型 SKILL 自身が全参考文書を Read して修正を実行する（汎用 Agent は起動しない）。

修正対象ファイルごとに Read → Edit/Write を行い、変更内容をサマリーとして記録する。

### Step 5: 結果を呼び出し元に返す

修正サマリーを priority + severity 併記のまま呼び出し元に返す。呼び出し元 (`/forge:present-findings` または `/forge:review`) がユーザーへの報告を担当する。

### Step 6: patch_result.json の書き込みと return

修正が成功した場合、return 直前に以下の内容を `{session_dir}/patch_result.json` に書き込む:

```json
{
  "status": "ok",
  "patched_ids": [1, 2],
  "failed_ids": [],
  "files_modified": ["path/to/file.md"],
  "completed_at": "2026-05-26T12:34:56Z"
}
```

- `patched_ids`: 修正が成功した finding の id リスト (plan.yaml は `in_progress` のまま)
- `failed_ids`: 修正が失敗した finding の id リスト
- `files_modified`: 修正したファイルパス一覧
- `completed_at`: 書き込み時の現在時刻 (ISO 8601)

> **plan.yaml の `status: fixed` への遷移は fixer が行わない。**
> 呼び出し元 (`/forge:review` または `/forge:present-findings`) が単独修正レビュー完了後に
> `mark_fixed.py` を呼ぶことで行う。
> fixer は plan.yaml を `in_progress` のままにして return する。

---

## Fixer プロンプトテンプレート [MANDATORY]

### `--single` モード (1 件修正)

```
以下の指摘事項に基づいて修正を実行してください。

## 修正対象の指摘事項 (id: {id})
- priority: {P1 | P2 | P3}
- severity: {critical | major | minor}
- target: {ファイルパス + 行範囲}
- rule: {参照規範 (ssot_refs の doc_path + 該当節)}

[`review_<種別>.md` (最終系 = evaluator 整形済み) から該当項目を抜粋した詳細テキスト]
[該当箇所・該当コード・なぜ問題か・修正案を含む]

## ユーザーが選択した修正方針
[修正方針がある場合のみ記載。ない場合はこのセクションを省略]

## 対象ファイル (修正前に必ず Read すること)
[ファイルパスリスト]

## 参考文書 (全て Read して理解すること)
### ルール文書
[refs.yaml の reference_docs のうちルール文書]
### 要件定義書・設計書
[refs.yaml の reference_docs のうち仕様書]
### 重大度カタログ・許容範囲 (severity 検証用)
[review_<種別>.md の severity_source で示された委譲先 principles ファイル]

## 関連コード (実装パターン・規約の参考として Read すること)
[refs.yaml の related_code のパスリストと関連性の説明]

## 指示
- 指摘事項に記載された問題のみを修正する
- 指摘事項に関係のない変更は一切行わない
- ユーザーが修正方針を選択している場合、その方針に従う
- 参考文書のルール・設計意図に従って修正する
- 関連コードの実装パターン・命名規則・スタイルに合わせて修正する
- 修正内容をサマリーで報告する (priority + severity を併記)

## 出力形式
### 修正サマリー
1. **[問題名]** (priority: P1 / severity: critical)
   - ファイル: [修正したファイルパス]
   - 内容: [何をどう変更したか 1-2 行]
   - 影響: [他に確認が必要な箇所があれば記載、なければ「なし」]
```

> `--batch` では「修正方針」セクションを省略する代わりに、各指摘に `auto_fixable` フラグと evaluator の `reason` を付与して渡す。呼び出し元から渡された指摘は `auto_fixable` の値によらず **全件修正する** — `auto_fixable` は呼び出し元（軽量経路フィルタ / present-findings の ✅ 表示）のための情報であり、fixer への投入ゲートではない (REQ-004 FNC-413 / DES-028 §4.5)。`auto_fixable: false` の指摘は evaluator の `reason` を根拠に fixer が自律判断して修正する。`--single` には `auto_fixable` / `reason` を含めない（present-findings でユーザーが修正方針を選択済みのため）。

### `--batch` モード (一括修正)

```
以下の指摘事項に基づいて修正を実行してください。
複数の指摘事項があります。全て修正してください。

## 介入軸フラグ
{--auto-critical | --auto | (フラグなし)}
{severity 制約の説明: critical のみ / critical + major / 全件}

## 修正対象の指摘事項
(plan.yaml で `recommendation: fix` AND `status ∈ {pending, in_progress}` AND severity 制約にフィルタ後、
`review_<種別>.md` (最終系) から該当項目を抜粋)

1. id: X (priority: P1 / severity: critical / auto_fixable: true)
   target: <ファイル:行範囲>
   rule: <参照規範>
   reason: <evaluator の判定根拠>
   [指摘事項 1 の詳細テキスト]

2. id: Y (priority: P2 / severity: major / auto_fixable: false)
   target: <ファイル:行範囲>
   rule: <参照規範>
   reason: <evaluator の判定根拠 — fixer はこれを根拠に修正方針を決定する>
   [指摘事項 2 の詳細テキスト]

...

## 対象ファイル
[全指摘事項に関連するファイルパスリスト]

## 参考文書 (全て Read して理解すること)
### ルール文書
[refs.yaml の reference_docs のうちルール文書]
### 要件定義書・設計書
[refs.yaml の reference_docs のうち仕様書]
### 重大度カタログ・許容範囲 (severity 検証用)
[review_<種別>.md の severity_source で示された委譲先 principles ファイル]

## 関連コード (実装パターン・規約の参考として Read すること)
[refs.yaml の related_code のパスリストと関連性の説明]

## 指示
- 指摘事項に記載された問題のみを修正する
- 指摘事項に関係のない変更は一切行わない
- 参考文書のルール・設計意図に従って修正する
- 関連コードの実装パターン・命名規則・スタイルに合わせて修正する
- 各指摘事項ごとに修正内容をサマリーで報告する (priority + severity を併記)

## 出力形式
### 修正サマリー
1. **[問題名 1]** (priority: P1 / severity: critical)
   - ファイル: [修正したファイルパス]
   - 内容: [何をどう変更したか 1-2 行]
   - 影響: [他に確認が必要な箇所があれば記載、なければ「なし」]
2. **[問題名 2]** (priority: P2 / severity: major)
   - ファイル: ...
   ...
```

### `--diff-only` モード (副作用確認後の追加修正)

```
直前の修正の副作用として reviewer (--diff-only) が検出した **新規問題のみ** を修正してください。

## 修正対象の新規 finding
(reviewer --diff-only の出力から、`recommendation: fix` のみ抽出)

1. **[問題名]** (priority: P1 / severity: critical)
   - target: <修正されたファイル:行範囲>
   - rule: <参照規範>
   - 問題: <新規発生の根拠>

## 指示
- 直前修正で意図せず発生した問題のみを修正する
- 直前修正の意図 (修正対象 id の元の指摘事項) を巻き戻さない
- 修正内容をサマリーで報告する (priority + severity を併記)
```

---

## エラーハンドリング

| エラー                                                                         | 対応                                                                                       |
| ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| 入力不足 (session_dir なし / `--single` で id なし)                            | 呼び出し元にエラーを返す。ユーザーに直接質問しない                                         |
| refs.yaml / plan.yaml / `review_<種別>.md` が存在しない・読み込み失敗          | エラー内容を呼び出し元に返す                                                               |
| `--single` で渡された id が plan.yaml に存在しない                             | エラー内容を呼び出し元に返す                                                               |
| `--single` で渡された id の `recommendation ≠ fix`                             | エラー内容を呼び出し元に返す (`create_issue` / `skip` / `needs_review` 項目の誤修正を防ぐ) |
| `--batch` でフィルタ結果が 0 件                                                | 正常終了扱いで「修正対象なし」を呼び出し元に返す (severity フィルタで全件除外も含む)       |
| `--batch` で `--auto-critical` / `--auto` の severity 制約が不正な値で渡された | エラー内容を呼び出し元に返す                                                               |
| 修正実行失敗 (Edit/Write エラー)                                               | エラー内容を呼び出し元に返す。呼び出し元がユーザーに報告                                   |
| 指摘事項と無関係な変更を行った                                                 | 呼び出し元がサマリーを確認し、ユーザーに報告して判断を仰ぐ                                 |
| plan.yaml の更新失敗                                                           | エラーを呼び出し元に報告するが、修正自体は成功扱いとする                                   |
