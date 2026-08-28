---
name: start-plan
description: |
  設計書から実装戦略を策定し、タスクを抽出して計画書を作成・更新する。レビュー+自動修正→commit まで一貫実行。
  トリガー: "計画書作成", "計画開始", "start plan", "start planning"
user-invocable: true
argument-hint: "<feature> [--new|--add]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, Skill, AskUserQuestion
---

# /forge:start-plan

設計書から実装戦略を策定し、タスクを抽出して計画書を作成または更新する。

## Goal

設計書からタスク抽出・計画書作成・レビュー+自動修正・commit まで完走すること。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:start-plan [feature] [--new|--add]
```

| 引数    | 内容                                       |
| ------- | ------------------------------------------ |
| feature | Feature 名（省略時は対話で確定）           |
| --new   | 新規アプリ・新規 feature（追加開発でない） |
| --add   | 既存アプリへの機能追加（追加開発）         |

---

## 事前準備 [MANDATORY]

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの設計書から計画するか）も出力先も決まらない。

**フィーチャー概念の把握 [MANDATORY]**: フラグ問わず以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `plan`（feature 未指定）で既存ファイルの有無を確認し、以下の3分岐で確定する:

- **引数あり** → **変更せずそのまま使用**（AI による置き換え禁止）
- **引数なし・既存ファイルが存在しない**（初回立ち上げ）→ フィーチャー名不要。同手順の対象ディレクトリに
  直接配置する（`additive_development_spec.md` §0 参照）
- **引数なし・既存ファイルが存在する** → AskUserQuestion で対象 Feature を確認する

### 新規/追加の確認 [MANDATORY]

計画書が新規アプリ向けか、既存アプリへの追加開発（additive）向けかを確定する。判定結果によって frontmatter_format.md §1.3 の扱い（frontmatter を付与しない）は変わらないが、後続の要件・設計文書の参照解決に影響するため、計画書作成前に判定する。

- `--new` 指定 → 新規アプリ・新規 feature として処理
- `--add` 指定 → 既存アプリへの機能追加（追加開発）として処理
- 未指定 → 入力の設計書・要件定義書が追加 feature 文書（`feature_type: temporary-feature` frontmatter を持つ）かで推定し、判断がつかなければ AskUserQuestion で確認する

**`--add`（追加開発）の場合 [MANDATORY]**: 以下を Read し、判定基準・矛盾時の優先度・merge 手順を把握したうえで後続 Phase に進む。計画書自体には frontmatter を付与しない（`frontmatter_format.md` §1.3）。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` — 追加開発ワークフロー仕様（§1 適用条件・対象外）
- `${CLAUDE_PLUGIN_ROOT}/docs/frontmatter_format.md` — frontmatter 定義一覧

### 出力先の解決

計画書の出力先を特定する。入力文書（設計書）は Phase 1 で agent が特定する。

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `plan`、feature `{feature}` で出力先ディレクトリを求める。

- `plan` に対応するエントリが無い場合は AskUserQuestion で出力先を確認する

### モード判定 [MANDATORY]

出力先の計画書の存在を確認し、モードを決定する。

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 計画書が存在しない | **新規作成モード** → Phase 1 へ  |
| 計画書が存在する   | AskUserQuestion でユーザーに確認 |

既存計画書がある場合、AskUserQuestion を使用して確認する:

- 既存計画書を更新する → 既存計画書を Read して現状を把握し Phase 1 へ
- レビューのみ行う → Skill ツールで `/forge:review plan --files {既存計画書パス}` を起動して終了

### プラグイン文書の読み込み [MANDATORY]

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md`** — ID分類カタログ（タスクIDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`** — 計画書作成原則・タスク設計ガイドライン（計画書ファイルの形式そのものは script が保証するため、AI が読む必要はない）
- **`${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`** — 文書スタイル指針（タグ・見出し・参照記法）

---

## Phase 1: コンテキスト収集 [MANDATORY]

以下の 2 つを **Agent ツールで並列起動** し、各 agent の **return value** を main AI コンテキストに直接保持する。エラー時は該当カテゴリなしで後続工程に進む。

### 1.1 要件定義書・設計書の収集

```
Agent ツール起動: 仕様書収集
prompt:
  Feature "{feature}" の計画書作成に必要な要件定義書と設計書 (`*_design.md`) を検索する。

  `/forge:query-db-specs {feature}` を呼ぶ。

  return value として以下の markdown 形式で返す:

  ## 仕様書 (N 件)
  - `path/to/design.md` — 関連理由 (要件定義書 / 設計書 等を明記)
```

### 1.2 計画書ルールの収集

```
Agent ツール起動: 計画書ルール収集
prompt:
  Feature "{feature}" の計画書作成に適用するフォーマット・タスク設計ルールを検索する。

  `/forge:query-db-rules {feature} 計画` を呼ぶ。

  return value として以下の markdown 形式で返す:

  ## 計画書ルール (N 件)
  - `path/to/rule.md` — 関連理由
```

### 1.3 収集結果の確認

全 agent 完了後、2 つの return value をそのままユーザーに表示する。5 件以下は全件表示、6 件以上は先頭 3 件 + `... 他 N 件`。

---

## Phase 2: 文書の読み込み [MANDATORY]

### 2.1 収集済み文書の読み込み

Phase 1 の 2 agent の return value を起点に、必要なファイルを Read する:

- **仕様書 return value** → 設計書 (`*_design.md`) と要件定義書を Read
- **計画書ルール return value** → プロジェクト固有の計画書フォーマット・タスク設計ルールを把握（プラグイン文書より優先）

該当 agent がエラー終了して return value を得られなかった場合 → 該当カテゴリなしで続行。
ただし **仕様書 return value に設計書が含まれていない場合** → AskUserQuestion:

- 設計書のパスを手動で指定する
- 設計書なしで計画書作成を進める（リスクを理解した上で）

---

## Phase 3: 実装戦略の策定 [MANDATORY]

タスク分割の前に、設計書全体を俯瞰し「どういうアプローチで実装に到達するか」を汎用 Agent (general-purpose) に策定させる。

### 3.0 既存の実装戦略書の確認 [MANDATORY]

`{output_dir}/{feature}_strategy.md`（命名規則に従う戦略書。特定の生成元を問わず、このパスに実装戦略書が既に存在するかで判定する）の存在を Glob 等で確認する。

- **存在する場合**: 削除・上書きせず `Read` する。設計フェーズ中の議論・レビュー往復で判明した移行方針・フェーズ分割等が既に記録されている可能性があるため、ゼロから策定し直さない。3.1 の Agent 起動時、既存戦略書の全文を prompt に含めて渡し、**既存内容を土台に、不足している観点（アプローチ選択・検証ポイント・リスク対策等）を補う・詳細化する**よう指示する（新規策定ではなく差分の追記・精緻化）
- **存在しない場合**: 3.1 へ進み、現行どおり新規に策定する

### 3.1 汎用 Agent の起動

Agent ツールで実装戦略 agent を起動する。Phase 1 で得た仕様書 return value から設計書パスを抽出し、agent 起動の引数として渡す。3.0 で既存戦略書を発見した場合は、その全文も渡す:

```
Agent ツール起動: 実装戦略策定 (subagent_type: general-purpose)
prompt:
  以下の設計書を読み、実装戦略を策定する。
  詳細手順は `${CLAUDE_PLUGIN_ROOT}/docs/strategy_formulation_spec.md` を Read して従うこと。

  - feature: {feature}
  - design_docs: [{設計書パス1}, {設計書パス2}, ...]  ← Phase 1 仕様書 return value から抽出
  - rules_docs: [{ルール文書パス1}, ...]              ← Phase 1 計画書ルール return value から抽出
  - existing_strategy: {既存戦略書の全文、または「なし」}  ← 3.0 の確認結果

  existing_strategy が「なし」でない場合、ゼロから策定せず、その内容を土台に不足を補う・詳細化すること。
  策定した実装戦略の markdown を return value として返すこと。
  (ファイルへの書き出しは不要。main AI が return value を受け取ってから配置する)
```

### 3.2 実装戦略書の配置 [MANDATORY]

Agent 完了後、return value (戦略書 markdown) を承認前にそのまま最終出力先へ Write する。チャットへの全文転記より先にファイルとして配置し、ユーザーが文書そのものを読んでレビューできるようにする:

- **配置先**: `{output_dir}/{feature}_strategy.md`
- **ライフサイクル**: 実装完了後に削除する ephemeral 文書
- 承認されなかった場合は 3.3 の修正結果でこのファイルを上書きする（配置は確定ではなく作業版の起点）

### 3.3 ユーザーレビューと承認

Write 完了後:

1. 配置したファイルパスを提示する（全文をチャットに転記しない。ユーザーはファイルを開いて読む）:
   ```
   実装戦略書を作成しました: {output_dir}/{feature}_strategy.md
   内容を確認してください。
   ```
2. AskUserQuestion でユーザーに確認する:
   - **承認** → Phase 4 へ
   - **修正要望あり** → 修正内容を反映して Agent を再起動（または orchestrator が直接修正）し、3.2 のファイルを再 Write してから本 Step を再実行

---

## Phase 4: 計画書の作成・更新 [MANDATORY]

### 4.1 更新モード: 既存作業の確認 [MANDATORY]

既存計画書がある場合（更新モード）、以下を必ず確認する:

1. **要件定義書への反映確認** — 変更内容が要件定義書に追記・修正されているか
2. **設計書への反映確認** — 設計変更を伴う場合、設計書に反映されているか
3. **未着手タスクの把握** — 既存計画書の未完了タスクを整理

上記に未反映がある場合は AskUserQuestion を使用して先に更新するか確認する。

### 4.2 実装戦略に基づきタスクを抽出 [MANDATORY]

`{output_dir}/{feature}_strategy.md` を Read し、実装戦略のフェーズ分割に従ってタスクを抽出・分割する:

1. 各フェーズ内のモジュールを「1 Agent 実行で完結する単位」に分割
2. フェーズ順序を尊重した優先度を設定（フェーズ1のタスク > フェーズ2のタスク）
3. 同一フェーズ内で依存関係を整理（依存される側から先に実装）
4. 並列実行可能なタスクを識別（依存関係がないタスク群）

**実装戦略書の必読化 [MANDATORY]**: すべてのタスクの `required_reading` に `{output_dir}/{feature}_strategy.md` を含める。executor が単一タスクだけを実装する場合でも、全体戦略・フェーズ意図・リスク対策を理解したうえで実装判断できるようにするため。

**タスクの粒度・グループ化**: タスク・グループとも「1つの Agent 実行で完結する」単位であることを基準とする。詳細な判定基準は `plan_principles_spec.md`「タスクの粒度」「タスクグループ」節に従う（事前準備で読み込み済み）。

### 4.3 計画書の作成・更新 [MANDATORY]

**出力方式**: AI はタスクの意味内容（`title` / `description` / `acceptance_criteria` 等）を決定するが、計画書ファイルへの書き込みと構造検証は script が行う（AI は計画書ファイルの形式・キー配置を意識する必要はない）。ファイル名は script が `{feature}_plan.json` として決定する（拡張子は `.json`）。

**タスクID採番** [MANDATORY]: プロジェクトのフォーマットルールに従う。ルールがない場合は `TASK-001`, `TASK-002` 等の連番。

タスク ID を付与する際は、必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" TASK
```

JSON 出力の `next_id` を起点に連番を使用する。`duplicates` が空でない場合は警告を表示する。

**優先度**: プロジェクトのフォーマットルールに従う。ルールがない場合は数値が大きいほど優先度が高い（例: 1〜99）。実装戦略のフェーズ順序を反映すること。

**「やるべき内容」の記載原則・依存関係管理** [MANDATORY]: `plan_principles_spec.md`「『やるべき内容』の記載原則」「依存関係管理」節に従う（事前準備で読み込み済み）。依存関係は各タスクの `depends_on` 配列に落とし込み、計画書本体には依存関係マップを含めない。

**候補 JSON の組み立てと書き込み [MANDATORY]**:

1. **候補 JSON を組み立てる**: `requirements_traceability` / `design_traceability` / `tasks` / `revision_history` の 4 キーを持つ object を組み立てる。追加開発（`--add`）の場合も frontmatter・予約キーは付与しない（`requirements_traceability` が参照する要件定義書の `feature_type: temporary-feature` frontmatter で追加 feature の計画書かを辿って判定できる。`frontmatter_format.md` §1.3 参照）
2. **候補 JSON を一時ファイルへ書く**: `Write` ツールで `.claude/.temp/plan-${CLAUDE_SESSION_ID}-{feature}.candidate.json` へ書く
3. **生成 script を 1 回実行する**。script が構造検証（4 キーのみ・`tasks[]` 必須フィールド・enum 値等）を行い、`{feature}_plan.json` へ書き出す。候補 JSON 側の入力ファイルは成否に関わらず script が自身で削除する:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/write_plan.py" \
     --input-file ".claude/.temp/plan-${CLAUDE_SESSION_ID}-{feature}.candidate.json" \
     --output-path "{出力先ディレクトリ}/{feature}_plan.json"
   ```

   exit code で分岐する:

   | exit code | 動作                                                                                                                                       |
   | --------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
   | 0         | stdout の `output_path` を確認し、4.4 へ進む                                                                                               |
   | 20        | stdout の `errors` に従って候補 JSON を訂正し、Write から同じ手順をもう 1 回だけ実行する。2 回目も失敗した場合はエラーとして報告し中断する |

**作成場所**: 事前準備「出力先の解決」で確定した出力先ディレクトリ

### 4.4 完全性チェック [MANDATORY]

計画書のスキーマ検査（4 キー構成・`tasks[]` 必須フィールド・enum 値）は 4.3 の script が行うため、AI は以下の**計画品質検査**（意味的な妥当性）のみを確認する:

- [ ] すべての `tasks[].required_reading` に `{output_dir}/{feature}_strategy.md` が含まれている
- [ ] 実装戦略のフェーズ分割がタスクの優先度に反映されているか
- [ ] 要件トレーサビリティマトリクスが全要件を網羅しているか
- [ ] 設計トレーサビリティマトリクスが全設計書をカバーしているか
- [ ] 全設計書がタスクに反映されているか
- [ ] 依存関係に循環がないか

---

## Phase 5: AIレビュー [MANDATORY]

計画書作成・更新後に Skill ツールで `/forge:review plan` を `--auto` モードで実行する:

<!-- review は `review-XXXXXX` という別スキル名で独立したセッションを作成するため、start-plan のセッションとは干渉しない -->

```
# Skill ツールで起動する
/forge:review plan --files {作成した計画書のファイルパス} --auto
```

対象はこのワークフローで作成・変更したファイル（差分）のみ。
Skill が失敗した場合は Phase 4.4 のチェック項目を手動で確認し、人間にレビューを依頼する。

---

## 完了処理

### specs ToC 更新

`/forge:update-db-specs` が利用可能であれば実行する（利用不可の場合はスキップ）。

### commit/push 確認

commit/push の確認フローを担うスキル（例: `anvil:commit`）が available-skills にあれば呼び出す。無ければ `git add` → `git commit` の手順を案内する。

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
計画書を作成しました:
  → {実装戦略書パス}
  → {計画書パス}

次のステップ:
  /forge:start-implement {feature}    # タスクの実行を開始

※ 実装戦略書・計画書は実装完了後に削除する ephemeral 文書です。
```
