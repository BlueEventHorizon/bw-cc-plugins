---
name: present-findings
user-invocable: false
description: |
  レビュー結果や調査結果を1件ずつ段階的に提示し、ユーザーの判断を仰ぐ。
  /forge:review の対話モードまたは --inline で呼び出される。
argument-hint: "<session_dir> | --inline"
allowed-tools: Read, Write, Bash, AskUserQuestion, Skill
---

# /present-findings Skill

複数項目を段階的・対話的にユーザーに提示する AI 専用 Skill。
セッションディレクトリ入力（レビュー結果等）とコンテキスト入力（--inline）の両方に対応し、内容に応じて適切に提示する。

## 設計原則

| 原則                         | 説明                                                                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------ |
| **メインコンテキストで実行** | ユーザーとの対話が必要なため、`/forge:review` からスキルとして呼び出され、メインコンテキストで実行する |
| **fixer は汎用 Agent 経由**  | 修正実行時は `/forge:fixer` を汎用 Agent (general-purpose) として起動する                              |

## 入力仕様 [MANDATORY]

> セッションディレクトリ内ファイルのスキーマ詳細は `${CLAUDE_PLUGIN_ROOT}/docs/session_format.md` を参照。

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
review_packet:
  criteria_path: plugins/forge/skills/review/docs/review_criteria_code.md
  ssot_refs:
    - path: docs/rules/foo.md
      priority: P1
      doc_type: rules
  check_order: ["P1", "P2", "P3"]
  severity_source: principles
  output_path: review_code.md
related_code:
  - path: plugins/forge/skills/reviewer/SKILL.md
    reason: 同種AIスキルのfrontmatter参考
    lines: "1-30"
```

**review.md** (reviewer が書く): 🔴🟡🟢 指摘事項リストの Markdown

**plan.yaml** (reviewer が初期作成 → evaluator が推奨で更新 → present-findings がユーザー判断で上書き):

```yaml
items:
  - id: 1
    severity: critical
    priority: P1 # P1 / P2 / P3 / なし(None) — reviewer が付与
    title: "問題タイトル"
    status: pending # pending / in_progress / fixed / skipped / needs_review
    recommendation: fix # fix / skip / create_issue / needs_review（evaluator が付与）
    auto_fixable: true # recommendation: fix の場合のみ
    reason: "判定理由" # evaluator の判断根拠
    fixed_at: ""
    files_modified: []
    skip_reason: ""
```

> `recommendation: create_issue` は FNC-406 の 3 条件 (該当規定なし / 再発性または客観性 / 明文化可能粒度) を満たす指摘に evaluator が付与する。present-findings はこの値を維持しつつ、ユーザーの選択 (「Issue 化する」) によって `/anvil:create-issue` を呼び出し、起票完了後は `status: skipped` + `skip_reason: "Issue 化済み: #<番号>"` で plan.yaml に記録する。

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
2. `{session_dir}/refs.yaml` を Read して target_files / reference_docs / related_code の**一覧を把握のみ**取得
   （パスリストの把握のみ。中身の Read は「追加質問フロー」で必要になった場合のみ行う）
3. `{session_dir}/plan.yaml` を Read して項目リストと**判定メタ情報（recommendation / auto_fixable / reason）を取得**
4. `{session_dir}/review_<種別>.md`（最終系 = evaluator 整形済み）を Read して各項目の詳細を取得
   - evaluator が常に書き換える前提のため、該当コード抜粋・ルール引用・修正案が含まれている
   - `.raw.md`（reviewer 原文）は**読まない**（監査・デバッグ用）
   - `review.md`（統合サマリー）は参考情報として必要に応じて Read

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

### Step 1: データ取得と提示準備 [MANDATORY]

present-findings は**プレゼンター**として動作する。段階的・対話的な提示フォーマットは
現状どおり維持する。ただし**情報源は以下に限定**し、定常フローで追加 Read は行わない。

1. **plan.yaml を判定の真実として扱う**
   - recommendation / auto_fixable / reason / severity を提示時の「AI判定」として表示
   - auto_fixable フラグは ✅ マークに使用
2. **`review_<種別>.md`（最終系）から各項目の詳細を取得**
   - evaluator が常に整形済みの状態で書き込んでいる
     （該当コード抜粋・ルール引用・修正案を含む）
   - 読み手は分岐不要（常に最終系を読む）
   - `.raw.md` は**読まない**（監査・デバッグ用）
3. 項目ごとに以下を整理し、提示用に保持する:
   - 問題名・該当箇所（ファイル:行）
   - 該当コード抜粋（review.md に含まれている前提）
   - なぜ問題か（ルール・根拠の引用）
   - 修正案（比較表 / 修正後コード）
   - AI判定（recommendation / auto_fixable / reason）
4. `has_severity` なら **severity 順 → priority 順の二段ソート** で並べ替え (詳細は次節)。ない場合は番号順を維持
5. 項目数をカウントし、提示準備

#### severity 順 → priority 順の二段ソート [MANDATORY]

DES-028 §3.5 / §4.1 / REQ-004 FNC-401 に従い、finding は **第一キー: severity / 第二キー: priority** で安定ソートして提示する。連番は severity セクションごとにリセットする (findings_renderer.py と整合)。

| 軸                  | 並び順                                                                  |
| ------------------- | ----------------------------------------------------------------------- |
| 第一キー (severity) | `critical` (🔴) → `major` (🟡, high) → `minor` (🟢, low) — DES-028 §3.5 |
| 第二キー (priority) | `P1` → `P2` → `P3` → なし(None) — review_priorities_spec §1             |
| 連番                | severity セクションごとにリセット (`🔴 1, 2, 3` → `🟡 1, 2, ...`)       |

- priority は **観点の出所** (P1=ルール照合 / P2=矛盾 / P3=不要な複雑化)、severity は **修正の緊急度** (critical/major/minor)。両軸は独立 (REQ-004 §2.2 / DES-028 §2.2 / §4.1)
- plan.yaml の `priority` フィールドを参照し、未設定 (None) の finding は同 severity セクション内の最後尾に配置
- `recommendation: skip` (却下) は severity を `❌` 扱いで別グループ表示する既存ルールを保持 (Step 2 サマリ参照)

> findings_renderer.py の `SEVERITY_ORDER` / `PRIORITY_ORDER` 定数が SoT。present-findings は同順序を踏襲する。

> **定常フローで target_files / reference_docs を再 Read しない**。
> evaluator が書き換えで必要情報を `review_<種別>.md` に含めているため再取得は不要。
> 却下項目は review.md の「❌却下」セクションに記載されている（plan.yaml の `recommendation: skip` / `reason` と整合）。
> 情報が不足する場合のみ「追加質問フロー」（後述）で親 Claude が対象ファイルを直接 Read する。

### Step 1.5: 意味的重複の自動統合 [MANDATORY]

reviewer は perspective ごとに独立実行されるため、同じ問題を**異なる文言**で複数項目として
指摘することがある（例: logic が「null チェック漏れ」、resilience が「防御的プログラミング不足」）。
機械的な重複検出（title / location 一致）は信頼できないため、**Claude が意味的に判定して自動統合する**。

> **ユーザー確認は行わない**。判定基準を厳格にして false positive を避けているため、
> 逐一確認するとユーザーの負担の方が大きい。統合結果は Step 2 の直前に事後通知する。

#### 適用条件

- **session_dir 入力時のみ**実行する。`--inline` では plan.yaml が存在しないためスキップ。
- 再開セッションで既に統合済みの場合（`skip_reason` が `"重複: id=... に統合"` で始まる項目が存在する）は再判定しない。

#### 対象

`status: pending` かつ `recommendation: fix` の項目のみ。
`recommendation: skip` / `needs_review` は対象外（evaluator 判定を尊重）。

#### 判定基準 [MANDATORY]

次の**全て**を満たす場合のみ重複と判定する:

- 同一箇所（同じファイル + 近接する行範囲）を指している
- 根本原因が同じ（修正案が実質的に同一になる）
- 表面的なキーワード類似ではなく**実施すべき修正が一致**する

> 判定に迷う場合は**重複としない**（false positive より false negative を許容）。
> perspective が異なる = 視点が異なるので、同じ箇所でも別問題であることが多い。
> 誤統合は情報損失につながるため、判定は保守的に倒す。

#### 代表項目の選定

重複グループ内で以下の優先順位で代表を決定する（決定論的・再現可能）:

1. severity が高いもの（critical > major > minor）
2. reason が具体的なもの（情報量が多いもの）
3. id が小さいもの

#### 統合実行

検出された重複グループについて、代表以外の項目を **1 回の `batch_update.py`** で一括更新する:

```bash
echo '{"updates": [
  {"id": 7, "status": "skipped", "recommendation": "skip",
   "skip_reason": "重複: id=3 に統合"}
]}' | python3 ${CLAUDE_SKILL_DIR}/scripts/batch_update.py {session_dir}
```

- 代表項目は**変更しない**（元の recommendation: fix のまま）
- 統合対象は `recommendation: skip` + `status: skipped` + `skip_reason` を付与
- browser は `skip_reason` を表示し、`status: skipped` はフィルタで除外可能

#### 事後通知

統合が発生した場合のみ、Step 2 のサマリー表示の直前に簡潔に通知する（AskUserQuestion ではなく平文）:

```
重複を自動統合しました:
  - id=3 ← id=7 (logic / resilience から同一箇所の null チェック漏れを指摘)

統合理由は plan.yaml の skip_reason に記録済みです。
```

統合が 0 件の場合は通知せず Step 2 に進む。

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

`has_severity = true` の場合（plan.yaml の recommendation フィールドがある場合は AI推奨列を含む）:

```
| # | 重大度 | Pri | 項目 | AI推奨 | AF |
|---|--------|-----|------|--------|-----|
| 1 | 🔴 | P1 | {問題1のタイトル} | 修正 |     |
| 2 | 🔴 | P2 | {問題2のタイトル} | 修正 | ✅ |
| 3 | 🟡 | P1 | {問題3のタイトル} | 📌 Issue化 |  |
| 4 | ❌ | P3 | {問題4のタイトル} | 却下 | ✅ |
| 5 | 🟢 | P1 | {問題5のタイトル} | 要確認 |     |
```

AI推奨の表示: `修正` (fix) / `📌 Issue化` (create_issue) / `却下` (skip) / `要確認` (needs_review)（plan.yaml の recommendation から変換）/ （空欄: recommendation 未設定）

> 行の並び順は **severity → priority の二段ソート**。`Pri` 列は plan.yaml の priority (P1/P2/P3/None) を表示する。priority=None の項目は同 severity セクション末尾に配置する。

**重大度列のルール [MANDATORY]**: plan.yaml の `recommendation: skip` の項目は重大度を **❌** で表示する。
却下 = evaluator が「実際には問題ではない」と判断済みであるため、🔴🟡🟢 で表示し続けると誤解を招く。

`has_severity = false` の場合:

```
| # | 項目 | AF |
|---|------|-----|
| 1 | {項目1のタイトル} | ✅ |
| 2 | {項目2のタイトル} |     |
| 3 | {項目3のタイトル} | ✅ |
```

共通:

```
✅ = evaluator が auto_fixable: true と判定した修正（一意・局所的・機械的）
```

全 {N} 件の項目があります。進め方を選択してください。

---

AskUserQuestion で進め方を確認する:

| # | 選択肢                             | 説明                                                                                                              |
| - | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1 | 段階的に解決                       | 1件ずつ丁寧に説明し、判断を仰ぐ。`(Recommended)` を付加                                                           |
| 2 | ✅を一括修正、残りは段階的に       | ✅付き項目を自動修正し、残りは段階的に解決。✅が0件の場合は非表示                                                 |
| 3 | 📌 を一括 Issue 化、残りは段階的に | `recommendation: create_issue` の項目を `/anvil:create-issue` 経由で一括起票し、残りは段階的に解決。0件なら非表示 |
| 4 | 一覧で見る                         | 全項目の詳細を一括表示                                                                                            |

> batch_update の値域には `fix` / `skip` / `needs_review` に加え **`create_issue`** が含まれる (DES-028 §4.4 / update_plan.py の `VALID_RECOMMENDATIONS`)。一括処理 (`-a all-fix` / 「📌 を一括 Issue 化」等) で `create_issue` 値を batch_update.py 経由で plan.yaml に反映できる。

### Step 3: 選択に応じた提示・解決フロー

#### 「段階的に解決」の場合

> **fixer 完了は修正完了ではない。** reviewer の単独修正レビューが完了して初めて修正完了とする。

項目を順に**1件ずつ**提示する（`has_severity` なら **severity 順 → priority 順の二段ソート** (🔴→🟡→🟢 / 各 severity 内で P1→P2→P3→None)、なければ番号順）。各項目で:

1. 項目を丁寧に説明する（提示の原則に従う）
2. 「選択肢の提示方法」に従い AskUserQuestion で判断を仰ぐ
3. ユーザーの選択に応じて:
   - **修正を選択**（A 案 = 推奨案）→ `python3 ${CLAUDE_SKILL_DIR}/scripts/mark_in_progress.py {session_dir} {id}` で更新 → **軽量経路判定 (FNC-413)** へ進む（後述「修正実行時の経路分岐」参照）
   - **修正を選択**（B 案 / Other 独自方針）→ `python3 ${CLAUDE_SKILL_DIR}/scripts/mark_in_progress.py {session_dir} {id}` で更新 → 修正方針の解釈が必要なため軽量経路に入らず `/forge:fixer --single` を呼び出し、修正を委譲（後述「/forge:fixer 呼び出し時の責務」参照）
   - **Issue 化する** → 後述「Issue 化フロー (`/anvil:create-issue` 呼び出し経路)」に従い `/anvil:create-issue` Skill を呼び出して起票 → 起票完了後に `batch_update.py` 経由で `recommendation: create_issue` / `status: skipped` / `skip_reason: "Issue 化済み: #<issue 番号>"` を plan.yaml に反映 → 次の項目へ進む
   - **このまま（対応しない）** → `python3 ${CLAUDE_SKILL_DIR}/scripts/mark_needs_review.py {session_dir} {id}` で更新
   - **一覧に戻る** → Step 2 へ
   - **スキップ** → `python3 ${CLAUDE_SKILL_DIR}/scripts/mark_skipped.py {session_dir} {id} "理由"` で更新 → 次の項目へ進む

#### 修正実行時の経路分岐 [REQ-004 FNC-413] [MANDATORY]

A 案 (推奨案) を選択した場合、plan.yaml の該当項目を見て以下を判定する:

| 条件                  | 経路           | 動作                                                                                                                                                                                                                                              |
| --------------------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `auto_fixable: true`  | **軽量経路**   | orchestrator がそのまま `review_<種別>.md` から該当 finding の修正案を Read で抜粋 → `Edit` で対象ファイルを直接修正 → `python3 ${CLAUDE_PLUGIN_ROOT}/skills/fixer/scripts/mark_fixed.py {session_dir} {id} {files_modified}` で plan.yaml を更新 |
| `auto_fixable: false` | **fixer 経路** | `/forge:fixer --single` を呼び出し、修正を委譲（後述「/forge:fixer 呼び出し時の責務」参照）                                                                                                                                                       |

軽量経路は fixer (汎用 Agent) を起動せず、汎用 Agent 起動オーバーヘッドを回避する。判定段階で `review_<種別>.md` 全文を読まず、軽量経路に入ったときのみ該当 finding の修正案セクションを抜粋 Read する。

その後、いずれの経路でも **単独修正レビュー** (`/forge:reviewer --diff-only`) を実行する（次節）。

#### 単独修正レビュー [MANDATORY]

**修正を実行した場合、必ずこのステップを実行する。スキップ禁止。** 軽量経路 / fixer 経路のいずれでも実行する。

修正完了直後に、修正差分のみを対象にレビューを実施する:

1. `/forge:reviewer` を `--diff-only {修正されたファイル}` で呼び出し、修正差分のみをレビュー
2. 修正起因の問題が見つかった場合 → `/forge:fixer --diff-only` を呼び出して修正 → 再レビュー（上限: 3回）。**`--diff-only` サイクルでの再修正は常に fixer 経路** (FNC-413 除外規定)
3. 問題なし → 修正サマリーをユーザーに報告（軽量経路では orchestrator 自身の修正、fixer 経路では fixer の修正サマリー）
4. plan.yaml を `fixed` に更新（単独修正レビュー完了後に初めて `fixed` にする）

> **注意**: plan.yaml の `status: fixed` への更新は、修正実行時ではなく**単独修正レビュー完了後**に行う。

5. （上記ステップ完了後）次の項目へ進む

全項目の提示・解決が完了したら、最終サマリーを報告して終了。

#### 最終サマリーの形式 [MANDATORY]

```
| # | 重大度 | 項目 | 結果 |
|---|--------|------|------|
| 1 | 🟡 | {修正した項目} | ✅ 修正済み |
| 2 | ❌ | {却下した項目} | ❌ 却下 |
| 3 | 🟢 | {修正した項目} | ✅ 修正済み |
```

**重大度列のルール:**

- 修正した項目（`status: fixed`）→ レビュー時の重大度（🔴 / 🟡 / 🟢）をそのまま表示
- 却下した項目（`status: skipped`）→ **❌** を表示する

**理由**: 却下 = evaluator またはユーザーが「実際には問題ではない」と判断した。重大度がある問題として表示し続けると誤解を招く。❌ により「false positive だった」ことを明示する。

#### 「✅を一括修正」の場合

> **修正完了は単独修正レビュー完了をもって確定する。** orchestrator 直接修正・fixer いずれの経路でも、reviewer の単独修正レビューが完了して初めて修正完了とする。

1. ✅付き項目を収集する（plan.yaml の `recommendation: fix` AND `auto_fixable: true` AND `status ∈ {pending, in_progress}`）
2. **軽量経路判定 [REQ-004 FNC-413] [MANDATORY]**: ✅付き項目数を見て経路を分岐する

   | 条件                      | 経路           | 動作                                                                                                                                                                                                                  |
   | ------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | ✅付き項目数 **3 件以下** | **軽量経路**   | orchestrator が各項目について `mark_in_progress.py {session_dir} {id}` → `review_<種別>.md` から該当 finding の修正案を抜粋 Read → `Edit` で直接修正 → `mark_fixed.py {session_dir} {id} {files_modified}` を順に実行 |
   | ✅付き項目数 **4 件以上** | **fixer 経路** | `/forge:fixer --batch` を呼び出し、修正を委譲（後述「/forge:fixer 呼び出し時の責務」参照）                                                                                                                            |

   判定段階で `review_<種別>.md` は読まない。軽量経路に入った場合のみ、各 finding の修正案セクションを抜粋 Read する。

3. **一括修正後の単独修正レビュー [MANDATORY]** — 軽量経路 / fixer 経路いずれも完了直後に必ず実行する。サマリー報告や次フローへの移行より先に実施する。スキップ禁止。
   1. `/forge:reviewer` を `--diff-only {修正されたファイル一覧}` で呼び出し、修正差分のみをレビュー
   2. 修正起因の問題が見つかった場合 → fixer を再度呼び出して修正 → 再レビュー（上限: 3回）。**`--diff-only` サイクルでの再修正は常に fixer 経路** (FNC-413 除外規定)
   3. 問題なし → 次へ
   4. plan.yaml を `fixed` に更新（単独修正レビュー完了後に初めて `fixed` にする）
   > **注意**: plan.yaml の `status: fixed` への更新は、修正実行時 (orchestrator 直接 or fixer 委譲) ではなく**単独修正レビュー完了後**に行う。
4. 修正サマリーをユーザーに報告（項目ごとに何をしたか 1 行ずつ。軽量経路では orchestrator 自身の出力、fixer 経路では fixer の修正サマリーをそのまま転載）
5. ✅なし項目が残っている場合、「段階的に解決」フローに移行
6. 全て✅だった場合は修正サマリーを報告して終了

#### 「一覧で見る」の場合

1. 全項目の詳細を一括表示
2. Step 2 のサマリー（進め方の選択）に戻る

### Step 4: 補助（オプション）

Step 3 完了後、`is_code_review` の場合に「最新のベストプラクティスを Web 検索で確認しますか？」を提案。
`ask-gemini` MCP を使用して Web 検索。`ask-gemini` が未接続の場合はこの Step をスキップする。

---

## /forge:fixer 呼び出し時の責務 [MANDATORY]

fixer に修正を委譲する際、以下を**漏れなく**渡すこと：

| 項目                       | 必須   | 取得元                                                                                                |
| -------------------------- | ------ | ----------------------------------------------------------------------------------------------------- |
| session_dir                | 必須   | $ARGUMENTS で受け取ったパス                                                                           |
| 指摘事項の詳細             | 必須   | review.md から該当箇所を抜粋                                                                          |
| モード                     | 必須   | `--single` または `--batch`                                                                           |
| 対象項目の id              | 必須   | 指摘事項の詳細テキスト冒頭に `id: {id}` の形式で含めて渡す（fixer が plan.yaml の status 更新に使用） |
| ユーザーが選択した修正方針 | あれば | AskUserQuestion の回答（A案/B案等）                                                                   |

> fixer は session_dir を受け取り、refs.yaml から target_files / reference_docs / related_code を自前で読み込む。個別に渡す必要はない。

> fixer の入力仕様の詳細は `${CLAUDE_PLUGIN_ROOT}/skills/fixer/SKILL.md` を参照。

> **--inline モードの場合**: session_dir が存在しないため、review_type / reference_docs / related_code はコンテキストから判断する。review_type が不明の場合は `generic` をフォールバックとして使用する。reference_docs / related_code が不明の場合は fixer が自前で収集する（fixer の Step 2 参照）。

---

## Issue 化フロー (`/anvil:create-issue` 呼び出し経路) [MANDATORY]

ユーザーが選択肢「Issue 化する」を選んだ場合、または「📌 を一括 Issue 化」で `recommendation: create_issue` の項目を一括処理する場合、`/anvil:create-issue` Skill を呼び出して GitHub Issue を起票する。

### 適用条件 (REQ-004 FNC-406 / DES-028 §3.5 §4 / criteria §3)

`recommendation: create_issue` は evaluator が以下の 3 条件をすべて満たすと判定した場合に付与している:

1. **該当規定なし**: P1 で参照する SSOT (プロジェクト固有 rules / forge 内蔵 principles / format) に該当規定が存在しない
2. **再発性または客観性**: 同種の指摘が複数箇所で観察される、または客観的事実で説明可能
3. **明文化可能粒度**: ルールとして明文化可能な具体粒度を持つ

ユーザーがそれ以外の項目で「Issue 化する」を選んだ場合 (evaluator が `fix` / `skip` を付与していた項目) も許容するが、Issue 本文に「ユーザー判断による Issue 化」と注記する。

### 呼び出し手順

1. **対象 finding の情報を収集**: `review_<種別>.md` の「📌 Issue 化」セクション (evaluator が起草済み) または対象 finding の本文から以下を抽出する:
   - 問題名 (title)
   - priority (P1 / P2 / P3)
   - severity (critical / major / minor)
   - rule (該当ルール、無ければ「該当規定なし」)
   - target (対象ファイル + 行番号)
   - 指摘内容 (現象 / 期待 / 再現)
   - 追加すべきルールの草案 (FNC-406 3 条件成立根拠 + ルール文案)

2. **Issue タイトルを構築**: `<種別> レビュー: <問題名>` 形式 (`/anvil:create-issue` 側でプレフィックス `[Bug]` / `[Feature]` が付与される)

3. **Issue 本文の下書きを構築**: 以下の必須要素を含む Markdown を組み立てる。`/anvil:create-issue` の Phase 2 で `AskUserQuestion` の初期値として渡す:

   ```markdown
   ## 背景 / コンテキスト

   forge レビューにより検出された指摘 (FNC-406 3 条件成立: ルール未整備)。

   - **priority**: P1 / P2 / P3
   - **severity**: 🔴 critical / 🟡 major / 🟢 minor
   - **rule**: <該当ルール or 「該当規定なし」>
   - **target**: <対象ファイル:行>

   ## 現象 (実際の動作)

   <reviewer/evaluator が記録した指摘の本文>

   ## 期待動作 / 追加すべきルール草案

   <evaluator が起草した「追加すべきルール草案」 — FNC-406 3 条件成立根拠を含む>

   ## 再現手順

   <対象ファイル + 該当箇所の引用>
   ```

4. **`/anvil:create-issue` Skill を呼び出す**: Skill ツール経由で起動する。`/anvil:create-issue` 側では Bug Report か Feature Request かの種別選択・タイトル承認・本文プレビュー・Issue 作成が対話的に行われる。

   ```text
   Skill: anvil:create-issue
   args: "<Issue タイトル候補>"
   ```

   呼び出し前に対象 finding の本文を直前のテキスト出力で簡潔に要約し、`/anvil:create-issue` の Phase 2 / Phase 3 で再入力される際の参考情報を提示する。

5. **起票完了後の plan.yaml 更新**: `/anvil:create-issue` の出力から Issue 番号 (`#N`) を取得し、`batch_update.py` 経由で plan.yaml を更新する:

   ```bash
   echo '{"updates": [
     {"id": <id>,
      "recommendation": "create_issue",
      "status": "skipped",
      "skip_reason": "Issue 化済み: #<N>"}
   ]}' | python3 ${CLAUDE_SKILL_DIR}/scripts/batch_update.py {session_dir}
   ```

   - `recommendation` は `create_issue` を維持 (FNC-406 判定の事実を残す)
   - `status` は `skipped` を採用 (`issued` は plan.yaml の status enum に存在しないため。update_plan.py `VALID_STATUSES` 参照)
   - `skip_reason` で「Issue 化済み: #<番号>」を記録し、後続レビューで再評価しない

6. **review.md には反映しない**: Issue 化は plan.yaml の状態遷移のみ。`write_interpretation.py` は呼ばない (evaluator が「📌 Issue 化」セクションを既に整形済みのため)。

### --inline モード時の扱い

session_dir が存在しないため plan.yaml 更新はスキップする。`/anvil:create-issue` 呼び出しは可能 (Skill ツール経由)。起票結果の Issue URL はテキスト出力でユーザーに報告する。

### batch_update の値域拡張 [MANDATORY]

batch_update.py (update_plan.py --batch の透過ラッパー) は以下の `recommendation` 値を受理する。`create_issue` を含む値域は update_plan.py の `VALID_RECOMMENDATIONS = {"fix", "skip", "create_issue", "needs_review"}` で定義されており、本 Skill が一括処理 (`-a all-fix` / 「📌 を一括 Issue 化」等) で `create_issue` を反映する経路の SoT となる:

| 一括処理コマンド      | 対象選定                                        | batch_update の `recommendation` 値                              |
| --------------------- | ----------------------------------------------- | ---------------------------------------------------------------- |
| `-a all-fix`          | `recommendation: fix` の全項目                  | `fix` を維持 (status: in_progress → fixer 起動)                  |
| `-a all-skip`         | `severity` または `priority` で絞り込んだ全項目 | `skip` (status: skipped + skip_reason)                           |
| `-a all-issue` (新設) | `recommendation: create_issue` の全項目         | **`create_issue`** (status: skipped + skip_reason: Issue 化済み) |
| `-a all-needs-review` | 残りの全項目                                    | `needs_review` (status: needs_review)                            |

batch 指示の例:

- 「全 critical を Issue 化」 → severity=critical の項目を抽出し `recommendation: create_issue` で batch_update → 各項目に対し `/anvil:create-issue` を順次呼び出す
- 「全 P3 を skip」 → priority=P3 の項目を抽出し `recommendation: skip` + `skip_reason: "P3 一括 skip (ユーザー指示)"` で batch_update

---

## セッション状態管理

present-findings は plan.yaml を状態ストアとして使用する。
evaluator が推奨に基づく初期状態を書き込み済みなので、present-findings はユーザーの最終判断で上書き更新する。

| ファイル  | 役割                                                                                                                    |
| --------- | ----------------------------------------------------------------------------------------------------------------------- |
| plan.yaml | 各項目の処理状態と AI推奨判定を統合管理（evaluator が初期推奨を書き込み → present-findings がユーザー判断で上書き更新） |

### 再開の仕組み

セッション再開時は plan.yaml の status から前回の進捗を復元する:

- status: pending → 未処理（処理対象）
- status: fixed / skipped / needs_review → 処理済み（スキップ）
- status: in_progress → 前回中断（処理対象に含める）

---

## 追加質問フロー [MANDATORY]

AskUserQuestion の「Other」でユーザーから追加質問が来た場合の対応手順:

1. **`review_<種別>.md`（最終系）から回答可能か判定**
   - 答えが `review_<種別>.md` に含まれる → 該当箇所を引用して回答し、再度 AskUserQuestion で判断を仰ぐ
   - 含まれない → ステップ 2 へ

2. **親 Claude が直接 Read して回答**
   - `refs.yaml` から target_files / reference_docs のパスを確認
   - 質問に関連するファイルのみを最小限 Read する（**全件 Read しない**）
   - 汎用 Agent には委譲しない（直接親 Claude が Read する）
   - 読み取り結果をもとに回答し、再度 AskUserQuestion で判断を仰ぐ

3. **情報不足のシグナル**
   - `review_<種別>.md`（最終系）に本来含まれるべき情報が不足していた場合、
     「AI判定情報が不十分でした」をユーザーに簡潔に伝える（evaluator の品質改善シグナル）

> 追加 Read は「追加質問フロー」のみで許可される例外処理。定常フローでは実行しない。

---

## ユーザー対話後の review.md 更新フロー [MANDATORY]

ユーザーとの対話（AskUserQuestion の結果）で**指摘内容・修正方針・判定に変更があった場合**、
Claude は `write_interpretation.py` 経由で `review_<種別>.md` を更新する。
これにより Fixer には常に最終系（ユーザー対話反映後）が伝わる。

**更新が必要なケース:**

- ユーザーが A案 / B案と異なる独自の修正方針を提示した（Other 選択）
- ユーザーの質疑で指摘の前提が誤っていることが判明した
- ユーザーが却下すべきと判断した項目（`recommendation` を変更）

**更新手順:**

```bash
cat <<'EOF' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session/write_interpretation.py \
  {session_dir} --kind {種別}
# evaluator 評価（種別: {種別}） — ユーザー対話反映版

（対話で確定した最新の指摘・修正方針を記述）
EOF
```

**重要な契約:**

- `.raw.md`（reviewer 原文のバックアップ）は**保護される**（再作成しない）
- `review_<種別>.md` のみが stdin 内容で上書きされる
- plan.yaml の `recommendation` / `status` などはユーザー判断に応じて `mark_* / batch_update` ラッパーで別途更新する
  （`write_interpretation.py` は plan.yaml を変更しない）

**なぜ必要か:**

Fixer は `review_<種別>.md`（最終系）のみを読む。対話後に更新しないと、
Fixer は古い内容（対話前の evaluator 初回評価）を参照して修正してしまう。

---

## 提示の原則 [MANDATORY]

`/present-findings` はプレゼンターである。**提示の丁寧さ・対話性は現状維持**。
変更点は「情報源の限定」のみ。

**提示スタイル（維持）:**

- 項目を 1 件ずつ段階的に提示する
- 「該当箇所」「該当コード」「なぜ問題か」「修正案」「推奨要約」を構造化して説明する
- AskUserQuestion で丁寧に選択肢を提示する
- 比較表・コードブロックを活用する（「段階的解決の提示例」参照）

**情報源の限定（新ルール）:**

- 情報源は **`review_<種別>.md`（最終系）+ plan.yaml** に限定する
- 対象ファイル（target_files）・参考文書（reference_docs）を**定常フローで Read しない**
- 該当コード抜粋・ルール引用は `review_<種別>.md` に含まれているものを使用する
- `.raw.md` は**定常フローで Read しない**（監査・デバッグ用のみ）
- 推測で補完しない（情報不足時は「追加質問フロー」へ）

**例外（追加質問時のみ）:**
AskUserQuestion の「Other」で review.md に答えがない質問が来た場合のみ、
親 Claude が対象ファイルを直接 Read して回答する。汎用 Agent への委譲はしない。

内容が不明確な場合は、その旨をユーザーに伝え、一緒に確認する提案をする。推測で説明しない。

### 対象ファイルの明示 [MANDATORY]

各項目の提示時に、**問題の対象ファイルと修正対象ファイル**を必ず明示すること。
ユーザーが「どのファイルの話か」を即座に把握できるようにする。

- `file_path:line_number` 形式でファイルパスと該当行を表示する
- 複数ファイルに関わる場合は全ファイルを列挙する
- 修正案がある場合は、修正対象ファイルも明示する

### 具体的なプレゼン手法

| 手法               | 説明                                                        | 情報源（定常フロー）                                  | いつ使うか                  |
| ------------------ | ----------------------------------------------------------- | ----------------------------------------------------- | --------------------------- |
| 対象ファイル表示   | 問題・修正の対象ファイルパスを `path:line` 形式で表示       | `review_<種別>.md`（最終系）の「箇所」欄              | **全ての項目（必須）**      |
| コード表示         | 該当箇所のコードを表示                                      | `review_<種別>.md`（最終系）の「該当コード」欄        | コードに関する項目          |
| 比較表             | 修正前/修正後、オプションA/Bを表で対比                      | `review_<種別>.md`（最終系）の「修正案」欄            | 比較・選択がある場合        |
| 影響範囲の説明     | 影響・リスク・メリットを説明                                | `review_<種別>.md`（最終系）の「なぜ問題か」欄        | 全ての項目                  |
| ルール・根拠の引用 | 規約・設計意図からの根拠を引用                              | `review_<種別>.md`（最終系）の「なぜ問題か」欄の引用  | 根拠が必要な場合            |
| 正しいパターン     | 正しい実装例・修正後コードを提示                            | `review_<種別>.md`（最終系）の「修正案」欄            | コードレビュー時            |
| AI判定表示         | 推奨 / 自動修正可能 / 判定根拠を表示                        | plan.yaml の recommendation / auto_fixable / reason   | 全ての項目（末尾に表示）    |
| 重大度マーク       | 🔴🟡🟢 / ❌（却下）/ 📌（create_issue）/ ✅（auto_fixable） | plan.yaml の severity / recommendation / auto_fixable | 全ての項目                  |
| priority マーク    | P1 / P2 / P3 を表示                                         | plan.yaml の priority                                 | 全ての項目 (二段ソート連動) |

> **定常フローでは target_files / reference_docs を再 Read しない**。
> コード・ルールの引用は `review_<種別>.md`（最終系）に含まれている内容を使用する。
> `.raw.md`（reviewer 原文）は定常フローで読まない（監査・デバッグ用のみ）。
> 情報が不足している場合は「追加質問フロー」（後述）で親 Claude が対象ファイルを直接 Read する。

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

| # | 選択肢                 | 説明                                                                                                                                        |
| - | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 | A案の内容              | 推奨する対応案。1番目に配置し `(Recommended)` を付加                                                                                        |
| 2 | B案の内容              | 代替案がある場合のみ追加                                                                                                                    |
| 3 | Issue 化する           | `/anvil:create-issue` を呼び出し GitHub Issue として起票する。`recommendation: create_issue` の項目で **推奨表示** にする (REQ-004 FNC-406) |
| 4 | 一覧に戻る             | サマリー一覧を再表示し、別の項目を選択可能にする                                                                                            |
| 5 | このまま（対応しない） | `needs_review` として記録し、次の項目へ進む                                                                                                 |
| 6 | スキップ               | 選択後に別の AskUserQuestion で理由を入力させ、`skipped` として次の項目へ進む                                                               |

- 代替案がない場合は A案 + Issue 化する + 一覧に戻る + このまま + スキップ の5択
- evaluator が `recommendation: create_issue` を付与した項目では「Issue 化する」を 1 番目に配置し `(Recommended)` を付加する (修正案より優先)
- 「Other」は追加質問・別案提示の入口として従来どおり扱う（スキップ理由の入力には使わない）
- 「スキップ」を選んだ場合は、選択肢提示直後に別 AskUserQuestion で理由入力を求め、得た文字列を `mark_skipped.py {session_dir} {id} "理由"` に渡す
- 「Issue 化する」を選んだ場合は後述「Issue 化フロー (`/anvil:create-issue` 呼び出し経路)」に従う
- 「このまま」と「スキップ」と「Issue 化する」は plan.yaml 上のセマンティクスが異なる（`needs_review` は後続レビューで再判断 / `skipped` は理由付きで却下 / Issue 化は `recommendation: create_issue` + `status: skipped` + `skip_reason: "Issue 化済み: #<番号>"`）

#### 情報確認のみの項目の場合

| # | 選択肢     | 説明                           |
| - | ---------- | ------------------------------ |
| 1 | 次へ       | 次の項目へ進む                 |
| 2 | 一覧に戻る | サマリー一覧を再表示           |
| 3 | 終了       | 残り項目数を案内して提示を終了 |

### ✅自明マークについて

✅ マークは **evaluator が判定した `auto_fixable: true`** の項目に付与する。
present-findings は独自に ✅ を判定しない（evaluator の判定を信頼する）。

plan.yaml の各項目で `recommendation: fix` かつ `auto_fixable: true` の場合に ✅ を表示する。

### 段階的解決の提示例

> **情報の取得元**: 以下の例の「該当コード」「なぜ問題か」「修正案」は全て `review_<種別>.md`（最終系）から引用する。
> 定常フローで target_files / reference_docs を再 Read しない。
> 末尾の「AI判定」は plan.yaml の recommendation / auto_fixable / reason から取得する。

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

### AI判定

- **推奨**: 修正（recommendation: fix）
- **自動修正**: 可能 ✅（auto_fixable: true）
- **判定根拠**: Actor 隔離原則への明確な違反。一意な修正パターンが存在するため自動修正可能。

---

→ AskUserQuestion で判断を仰ぐ（「選択肢の提示方法」参照）
````

> **AI判定セクションは提示の末尾に必ず表示する**。plan.yaml の recommendation / auto_fixable / reason / priority を
> そのまま転記する（日本語訳: `fix` → 修正 / `create_issue` → 📌 Issue 化 / `skip` → 却下 / `needs_review` → 要確認）。
> ユーザーが「AI がなぜそう判定したか」を確認でき、必要なら Other で追加質問できる。
> `recommendation: create_issue` の項目は FNC-406 3 条件成立根拠 (該当規定なし / 再発性または客観性 / 明文化可能粒度) を AI判定セクションに含めて表示し、ユーザーが「Issue 化する」を選んだ場合の `/anvil:create-issue` 本文下書きと整合させる。

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
