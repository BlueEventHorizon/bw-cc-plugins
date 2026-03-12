---
name: present-findings
user-invocable: false
description: |
  項目の段階的・対話的提示。AI専用Skill。
  項目（レビュー指摘、検証結果、調査結果、質問への回答等）を対話3原則に従って丁寧に提示する。
  1件でも有効（提示品質の向上）。2件以上では段階的に1件ずつ提示。
  用途1: /forge:review Skill からのレビュー結果ファイル提示（session_dir ベース）
  用途2: AI が分析・調査・回答で項目を提示する場合（--inline）
argument-hint: "<session_dir> | --inline"
---

# /present-findings Skill

複数項目を段階的・対話的にユーザーに提示する AI 専用 Skill。
セッションディレクトリ入力（レビュー結果等）とコンテキスト入力（--inline）の両方に対応し、内容に応じて適切に提示する。

## 設計原則

| 原則                         | 説明                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| **メインコンテキストで実行** | ユーザーとの対話が必要なため、`/forge:review` からスキルとして呼び出され、メインコンテキストで実行する |
| **fixer は subagent 経由**   | 修正実行時は `/forge:fixer` を general-purpose subagent として起動する                                 |

## 入力仕様 [MANDATORY]

### 入力方法

| `$ARGUMENTS` | 入力方法                                          |
| ------------ | ------------------------------------------------- |
| session_dir  | セッションディレクトリのパスから各ファイルを Read |
| `--inline`   | 直前の会話コンテキストから取得（後方互換）        |

### session_dir 入力

`$ARGUMENTS` = セッションディレクトリのパス

セッションディレクトリには以下のファイルが含まれる:

**session.yaml** (review が書く):

```yaml
review_type: code
engine: codex
auto_count: 0
current_cycle: 0
started_at: "2026-03-09T18:30:00Z"
last_updated: "2026-03-09T18:30:00Z"
status: in_progress
```

**refs.yaml** (review が書く):

```yaml
target_files:
  - path/to/file.md
reference_docs:
  - path: docs/rules/foo.md
review_criteria_path: plugins/forge/defaults/review_criteria.md
related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: 同種AIスキルのfrontmatter参考
    lines: "1-30"
```

**review.md** (reviewer が書く): 🔴🟡🟢 指摘事項リストの Markdown

**evaluation.yaml** (evaluator が書く):

```yaml
cycle: 1
items:
  - id: 1
    severity: critical
    title: "問題タイトル"
    recommendation: fix # fix / skip / needs_review
    auto_fixable: true  # recommendation: fix の場合のみ（一意・局所的・機械的な修正か）
    reason: "判定理由（AI の判断根拠）"
```

**plan.yaml** (reviewer が初期作成 → evaluator が推奨で更新 → present-findings がユーザー判断で上書き):

```yaml
items:
  - id: 1
    severity: critical
    title: "問題タイトル"
    status: pending # pending / in_progress / fixed / skipped / needs_review
    fixed_at: ""
    files_modified: []
    skip_reason: ""
```

### コンテキスト入力

`$ARGUMENTS` = `--inline`

呼び出し元AIが直前の会話コンテキストに項目リストを保持している前提で動作する。
ファイルの読み込みは不要。

項目リストの推奨形式:

```markdown
1. **[項目タイトル]**: [説明]
2. **[項目タイトル]**: [説明]
   ...
```

> コンテキスト入力でもレビュー結果（🔴🟡🟢マーカー付き）を扱える。内容に応じて重大度列の表示や並び順が自動的に適用される。

---

## 提示ワークフロー

### Step 0: 入力の正規化 [MANDATORY]

入力方法に応じてデータを取得し、コンテンツ属性を判定する。

#### session_dir の場合

1. `{session_dir}/session.yaml` を Read してメタデータを取得（review_type, engine, auto_count, current_cycle, status 等）
2. `{session_dir}/refs.yaml` を Read して target_files / reference_docs / related_code を取得
3. `{session_dir}/plan.yaml` を Read して項目リストを取得（status で処理済みをフィルタ可能）
4. `{session_dir}/review.md` を Read して各項目の詳細説明を取得
5. `{session_dir}/evaluation.yaml` を Read して AI 推奨判定を取得（存在する場合のみ）

**既存セッションの再開:**
plan.yaml に `status: pending` でない項目が存在する場合、「前回の続きから再開しますか？」を AskUserQuestion で確認する。

- **再開する** → `status: pending` の項目のみを処理対象とする
- **最初からやり直す** → 全件を `status: pending` にリセットして plan.yaml を Write

#### --inline の場合

1. 直前の会話コンテキストから項目リストを取得する

#### コンテンツ属性の判定 [MANDATORY]

入力方法に関わらず、項目の内容から以下の属性を判定する:

| 属性             | 判定方法                                                                                     | 影響                             |
| ---------------- | -------------------------------------------------------------------------------------------- | -------------------------------- |
| `has_severity`   | plan.yaml の severity フィールドから判定（--inline の場合は各項目の内容から AI が判断）      | サマリー表の重大度列表示、並び順 |
| `has_metadata`   | session.yaml の存在で判定（--inline の場合は利用可能なメタデータの有無）                     | サマリーヘッダ表示               |
| `is_code_review` | session.yaml の review_type = "code" で判定（--inline の場合はコードファイル参照等から判断） | Step 4（Gemini補助）の提案       |

`has_severity = true` の場合、AIは各項目の内容から以下の重大度を付与する:

| 重大度   | 表示 | 基準                                                                 |
| -------- | ---- | -------------------------------------------------------------------- |
| Critical | 🔴   | 放置すると重大な問題を引き起こす（バグ、セキュリティ、データ損失等） |
| Major    | 🟡   | 品質・保守性に影響するが、即座の問題にはならない                     |
| Minor    | 🟢   | 改善が望ましいが、現状でも許容範囲                                   |

> 入力に明示的なマーカーやラベル（🔴、[高]、致命的 等）が含まれていれば判断材料の一つとして活用するが、マーカーの有無自体は `has_severity` の判定条件ではない。🔴🟡🟢 はAIの判断結果を人間に伝える表示用マーカーである。

- session_dir 入力: `has_metadata` は session.yaml の存在から判定。他の属性は plan.yaml / session.yaml から判断
- コンテキスト入力: 全属性を内容から判断

> エラー時: ファイル不在・パースエラー・項目なし → ユーザーに報告して終了

### Step 1: 理解と評価 [MANDATORY]

1. 各項目を**深く理解する**
2. evaluation.yaml から各項目の `auto_fixable` フラグを取得し、✅ マークに使用する
3. `has_severity` の場合: 各項目に重大度（Critical🔴 / Major🟡 / Minor🟢）を付与し、重大度順に並べ替え。ない場合: 番号順を維持
4. evaluation.yaml が存在する場合: 各項目の AI 推奨判定（recommendation / reason）を把握する
   これを提示時の「AI推奨」として活用する（最終判断は人間）
5. `has_metadata` で reference_docs がある場合: Read で読み込み、レビュー観点やルールを把握
6. target_files がある場合: 一覧を把握するのみ（各問題の提示時に該当箇所を Read）
7. 項目数をカウントし、提示準備

### Step 2: サマリー提示と進め方の選択

#### 1件の場合

Step 2 をスキップし、直接 Step 3 へ進む。
提示の原則に従って丁寧に提示し、「選択肢の提示方法」に従い AskUserQuestion で判断を仰ぐ。

#### 2件以上の場合

サマリーを提示し、ユーザーに進め方を確認する。

`has_metadata` がある場合、サマリーヘッダにメタデータを表示:

```
- レビュー種別: {review_type}
- エンジン: {engine}
```

`has_severity = true` の場合（evaluation.yaml ありの場合は AI推奨列を含む）:

```
| # | 重大度 | 項目 | AI推奨 | |
|---|--------|------|--------|---|
| 1 | 🔴 | {問題1のタイトル} | 修正 | |
| 2 | 🔴 | {問題2のタイトル} | 修正 | ✅ |
| 3 | 🟡 | {問題3のタイトル} | 却下 | ✅ |
| 4 | 🟢 | {問題4のタイトル} | 要確認 | |
```

AI推奨の表示: `修正` / `却下` / `要確認`（evaluation.yaml の recommendation から変換）/ （空欄: evaluation.yaml なし）

`has_severity = false` の場合:

```
| # | 項目 | |
|---|------|----|
| 1 | {項目1のタイトル} | ✅ |
| 2 | {項目2のタイトル} | |
| 3 | {項目3のタイトル} | ✅ |
```

共通:

```
✅ = evaluator が auto_fixable: true と判定した修正（一意・局所的・機械的）
```

全 {N} 件の項目があります。進め方を選択してください。

---

AskUserQuestion で進め方を確認する:

| # | 選択肢                       | 説明                                                              |
| - | ---------------------------- | ----------------------------------------------------------------- |
| 1 | 段階的に解決                 | 1件ずつ丁寧に説明し、判断を仰ぐ。`(Recommended)` を付加           |
| 2 | ✅を一括修正、残りは段階的に | ✅付き項目を自動修正し、残りは段階的に解決。✅が0件の場合は非表示 |
| 3 | 一覧で見る                   | 全項目の詳細を一括表示                                            |

### Step 3: 選択に応じた提示・解決フロー

#### 「段階的に解決」の場合

項目を順に**1件ずつ**提示する（`has_severity` なら🔴→🟡→🟢順、なければ番号順）。各項目で:

1. 項目を丁寧に説明する（提示の原則に従う）
2. 「選択肢の提示方法」に従い AskUserQuestion で判断を仰ぐ
3. ユーザーの選択に応じて:
   - **修正を選択**（A案/B案）→ `/forge:fixer --single` を呼び出し、修正を委譲（後述「/forge:fixer 呼び出し時の責務」参照）
   - **このまま（対応しない）** → Step 5 へ
   - **一覧に戻る** → Step 2 へ
4. fixer の修正サマリーをユーザーに報告
   3.5. plan.yaml を更新する:
   - 修正した場合: status を `in_progress` に変更（fixer が `fixed` にする）
   - スキップした場合: status を `skipped` に変更 / skip_reason を記録
   - 対応しない場合: status を `needs_review` に変更
     plan.yaml を Write で上書き保存
     3.6. `/forge:show-report --silent` を呼び出して report.html を再生成する
5. 次の項目へ進む

全項目の提示・解決が完了したら、修正サマリーを報告して終了。

#### 「✅を一括修正」の場合

1. ✅付き項目を収集し、`/forge:fixer --batch` を呼び出し、修正を委譲（後述「/forge:fixer 呼び出し時の責務」参照）
2. fixer の修正サマリーをユーザーに報告（項目ごとに何をしたか1行ずつ）
3. ✅なし項目が残っている場合、「段階的に解決」フローに移行
4. 全て✅だった場合は修正サマリーを報告して終了

#### 「一覧で見る」の場合

1. 全項目の詳細を一括表示
2. Step 2 のサマリー（進め方の選択）に戻る

### Step 4: 補助（オプション）

Step 3 完了後、`is_code_review` の場合に「最新のベストプラクティスを Web 検索で確認しますか？」を提案。
`ask-gemini` MCP を使用して Web 検索。`ask-gemini` が未接続の場合はこの Step をスキップする。

---

## /forge:fixer 呼び出し時の責務 [MANDATORY]

fixer に修正を委譲する際、以下を**漏れなく**渡すこと：

| 項目                       | 必須   | 取得元                              |
| -------------------------- | ------ | ----------------------------------- |
| session_dir                | 必須   | $ARGUMENTS で受け取ったパス         |
| 指摘事項の詳細             | 必須   | review.md から該当箇所を抜粋        |
| モード                     | 必須   | `--single` または `--batch`         |
| 対象項目の id              | 必須   | plan.yaml 更新に使う                |
| ユーザーが選択した修正方針 | あれば | AskUserQuestion の回答（A案/B案等） |

> fixer は session_dir を受け取り、refs.yaml から target_files / reference_docs / related_code を自前で読み込む。個別に渡す必要はない。

> fixer の入力仕様の詳細は `${CLAUDE_PLUGIN_ROOT}/skills/fixer/SKILL.md` を参照。

> **--inline モードの場合**: session_dir が存在しないため、review_type / reference_docs / related_code はコンテキストから判断する。review_type が不明の場合は `generic` をフォールバックとして使用する。reference_docs / related_code が不明の場合は fixer が自前で収集する（fixer の Step 2 参照）。

---

## セッション状態管理

present-findings は plan.yaml を状態ストアとして使用する。
evaluator が推奨に基づく初期状態を書き込み済みなので、present-findings はユーザーの最終判断で上書き更新する。

| ファイル        | 役割                                                                                     |
| --------------- | ---------------------------------------------------------------------------------------- |
| plan.yaml       | 各項目の処理状態（evaluator の推奨で初期化済み → ユーザー判断で上書き更新）              |
| evaluation.yaml | AI推奨判定（recommendation / auto_fixable を参照のみ、更新しない）                       |
| report.html     | /forge:show-report --silent で随時再生成                                                 |

### 再開の仕組み

セッション再開時は plan.yaml の status から前回の進捗を復元する:

- status: pending → 未処理（処理対象）
- status: fixed / skipped / needs_review → 処理済み（スキップ）
- status: in_progress → 前回中断（処理対象に含める）

---

## 提示の原則 [MANDATORY]

元の情報を**そのまま転記してはならない**。

`/present-findings` はプレゼンターである。各項目を**自分で理解した上で**、ユーザーが納得できるよう丁寧に説明する。

内容が不明確な場合は、その旨をユーザーに伝え、一緒に確認する提案をする。推測で説明しない。

### 具体的なプレゼン手法

| 手法               | 説明                                                 | いつ使うか           |
| ------------------ | ---------------------------------------------------- | -------------------- |
| コード表示         | 該当箇所を Read で読み込み、問題のあるコードを表示   | コードに関する項目   |
| 比較表             | 修正前/修正後、オプションA/Bを表で対比               | 比較・選択がある場合 |
| 影響範囲の説明     | 影響・リスク・メリットを説明                         | 全ての項目           |
| ルール・根拠の引用 | reference_docs やソースから根拠を引用                | 根拠が必要な場合     |
| 正しいパターン     | プロジェクトの既存コードから正しい実装例を探して提示 | コードレビュー時     |

### 選択肢の提示方法 [MANDATORY]

ユーザーに選択を求める全ての場面で **AskUserQuestion ツール** を使用する。
テキストで「A / B」のように選択肢を記述しない。

#### テキスト出力と AskUserQuestion の分離 [MANDATORY]

AskUserQuestion の UI はテキスト出力の末尾に重なって表示される。
以下のルールで重要情報の可読性を確保すること:

1. **説明テキストの末尾は短い要約文（1-2行）で締める** — コードブロック・表・引用で終わらせない
2. **要約文の後に `---`（区切り線）を入れる** — 視覚的にテキストと UI を分離
3. **AskUserQuestion は区切り線の後に呼び出す**

構成:

```
詳細説明（コードブロック、表、根拠の引用など）
↓
短い要約文（推奨アクションを1-2行で）
↓
---（区切り線）
↓
AskUserQuestion 呼び出し
```

#### 対応判断が必要な項目の場合

| # | 選択肢                 | 説明                                                 |
| - | ---------------------- | ---------------------------------------------------- |
| 1 | A案の内容              | 推奨する対応案。1番目に配置し `(Recommended)` を付加 |
| 2 | B案の内容              | 代替案がある場合のみ追加                             |
| 3 | 一覧に戻る             | サマリー一覧を再表示し、別の項目を選択可能にする     |
| 4 | このまま（対応しない） | この項目をスキップして次へ進む                       |

- 代替案がない場合は A案 + 一覧に戻る + このまま の3択
- 「Other」が自動提供されるため、質問・別案の提示はそこでカバーされる

#### 情報確認のみの項目の場合

| # | 選択肢     | 説明                           |
| - | ---------- | ------------------------------ |
| 1 | 次へ       | 次の項目へ進む                 |
| 2 | 一覧に戻る | サマリー一覧を再表示           |
| 3 | 終了       | 残り項目数を案内して提示を終了 |

### ✅自明マークについて

✅ マークは **evaluator が判定した `auto_fixable: true`** の項目に付与する。
present-findings は独自に ✅ を判定しない（evaluator の判定を信頼する）。

evaluation.yaml の各項目で `recommendation: fix` かつ `auto_fixable: true` の場合に ✅ を表示する。

### 段階的解決の提示例

````markdown
## 🔴 問題 1/3: Actor 隔離違反

`FooViewModel` の `fetchItems()` が `@MainActor` 上で重い処理を実行しています。

### 該当箇所

`App/ViewModel/FooViewModel.swift:42-58`

```swift
@MainActor
func fetchItems() async throws {
    let items = try await repository.fetchItems()  // ← ここでUIスレッドがブロック
    self.items = items
}
```

### なぜ問題か

UIスレッドがブロックされ、ユーザー操作が固まります。
プロジェクトのアーキテクチャルール「Actor 隔離原則」に違反しています:

> 重い処理は非UIスレッドで実行し、結果のみ @MainActor で受け取る

### 修正案

| 現在                           | 修正後                                         |
| ------------------------------ | ---------------------------------------------- |
| `@MainActor` で直接API呼び出し | Service で処理し、結果のみ `@MainActor` で反映 |

```swift
// 修正後
func fetchItems() async throws {
    let items = try await service.fetchItems()  // Service で処理
    await MainActor.run {
        self.items = items  // UIスレッドで結果のみ反映
    }
}
```

Service レイヤーに処理を移し、`@MainActor` では結果反映のみとする修正を推奨します。

---

→ AskUserQuestion で判断を仰ぐ（「選択肢の提示方法」参照）
````

---

## 対話3原則

1. **不明確なことは勝手に決めない** → AskUserQuestion を使用して確認する
2. **問題や提案の比較・経緯を丁寧に説明する**
3. **全ての問題を一度に提示しない** → 段階的に説明して判断を仰ぐ

---

## 提示数制限

| 条件                      | 上限 | 超過時の対応                                                          |
| ------------------------- | ---- | --------------------------------------------------------------------- |
| `has_severity` — 🔴致命的 | 10件 | 超過分は次回レビューへ                                                |
| `has_severity` — 🟡品質   | 10件 | 超過分は次回レビューへ                                                |
| `has_severity` — 🟢改善   | 5件  | 超過分は省略                                                          |
| 重大度なし                | 20件 | AskUserQuestion を使用して「残りN件あります。続けますか？」と確認する |

> 項目は全件保存される（カットしない）。
> 上限を超える場合は、提示時に超過分の案内をする。

---

## エラーハンドリング

| エラー                           | 対応                                                                |
| -------------------------------- | ------------------------------------------------------------------- |
| ファイルが存在しない             | 「ファイルが見つかりません: {path}」と表示して終了                  |
| YAML frontmatter パースエラー    | 「ファイルの形式が不正です」と表示して終了                          |
| frontmatter の必須フィールド不足 | 不足フィールドを報告し、利用可能な情報で続行                        |
| 項目が0件                        | 「提示する項目がありません」と表示して終了                          |
| コンテキストに項目が見つからない | 「提示する項目が見つかりません」と表示して終了                      |
| fixer がエラーを返した           | エラー内容をユーザーに報告し、手動対応するか確認（AskUserQuestion） |
