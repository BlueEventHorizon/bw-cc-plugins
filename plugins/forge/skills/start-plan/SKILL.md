---
name: start-plan
description: |
  設計書から実装戦略を策定し、タスクを抽出して計画書を作成・更新する。レビュー+自動修正→commit まで一貫実行。
  トリガー: "計画書作成", "計画開始", "start plan", "start planning"
user-invocable: true
argument-hint: "<feature> [--new|--add]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, Skill, AskUserQuestion
---

# /forge:start-plan

設計書から実装戦略を策定し、タスクを抽出して計画書を作成または更新する。

## Goal

設計書からタスク抽出・計画書作成・レビュー+自動修正・commit まで完走すること。

## フロー継続

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

## 事前準備

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの設計書から計画するか）も出力先も決まらない。

**フィーチャー概念の把握**: フラグ問わず以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `plan`（feature 未指定）で既存ファイルの有無を確認し、以下の3分岐で確定する:

- **引数あり** → **変更せずそのまま使用**（AI による置き換え禁止）
- **引数なし・既存ファイルが存在しない**（初回立ち上げ）→ フィーチャー名不要。同手順の対象ディレクトリに
  直接配置する（`additive_development_spec.md` §0 参照）
- **引数なし・既存ファイルが存在する** → AskUserQuestion で対象 Feature を確認する

### 新規/追加の確認

計画書が新規アプリ向けか、既存アプリへの追加開発（additive）向けかを確定する。判定結果によって frontmatter_format.md §1.3 の扱い（frontmatter を付与しない）は変わらないが、後続の要件・設計文書の参照解決に影響するため、計画書作成前に判定する。

- `--new` 指定 → 新規アプリ・新規 feature として処理
- `--add` 指定 → 既存アプリへの機能追加（追加開発）として処理
- 未指定 → 入力の設計書・要件定義書が追加 feature 文書（`feature_type: temporary-feature` frontmatter を持つ）かで推定し、判断がつかなければ AskUserQuestion で確認する

**`--add`（追加開発）の場合**: 以下を Read し、判定基準・旧仕様の置き換え・merge 手順を把握したうえで後続 Phase に進む。計画書自体には frontmatter を付与しない（`frontmatter_format.md` §1.3）。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` — 追加開発ワークフロー仕様（§1 適用条件・対象外）
- `${CLAUDE_PLUGIN_ROOT}/docs/frontmatter_format.md` — frontmatter 定義一覧

### 出力先の解決

計画書の出力先を特定する。入力文書（設計書）は Phase 1 で agent が特定する。

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `plan`、feature `{feature}` で出力先ディレクトリを求める。

エントリが無い場合の扱いは同手順が定める（本スキルは既定パスを持たず、出力先を独自に尋ねない）。

### モード判定

出力先の計画書の存在を確認し、モードを決定する。

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 計画書が存在しない | **新規作成モード** → Phase 1 へ  |
| 計画書が存在する   | AskUserQuestion でユーザーに確認 |

既存計画書がある場合、AskUserQuestion を使用して確認する:

- 既存計画書を更新する → 既存計画書を Read して現状を把握し Phase 1 へ
- レビューのみ行う → Skill ツールで `/forge:review plan --files {既存計画書パス}` を起動して終了

### プラグイン文書の読み込み

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`** — 計画書作成原則・タスク設計ガイドライン（計画書ファイルの形式そのものは script が保証するため、AI が読む必要はない）
- **`${CLAUDE_PLUGIN_ROOT}/docs/strategy_principles_spec.md`** — 実装戦略書の定義と原則（計画書との線引き・差分開発の扱いを含む）
- **`${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`** — 文書スタイル指針（タグ・見出し・参照記法）

---

## Phase 1: コンテキスト収集

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

## Phase 2: 文書の読み込み

### 2.1 収集済み文書の読み込み

Phase 1 の 2 agent の return value を起点に、必要なファイルを Read する:

- **仕様書 return value** → 設計書 (`*_design.md`) と要件定義書を Read
- **計画書ルール return value** → プロジェクト固有の計画書フォーマット・タスク設計ルールを把握（プラグイン文書より優先）

該当 agent がエラー終了して return value を得られなかった場合 → 該当カテゴリなしで続行。
ただし **仕様書 return value に設計書が含まれていない場合** → 設計書は実装戦略の前提であり欠かせないため、AskUserQuestion で設計書のパスを手動で指定してもらう。指定できなければ中止する。

要件定義書は任意である。要件定義書を持たないプロジェクトがあるため、見つからなくてもそのまま進む。

---

## Phase 3: 実装戦略の策定

タスク分割の前に、設計書全体を俯瞰し「どういうアプローチで実装に到達するか」をカスタム Agent `forge:plan-strategist` に策定させる。

**Agent との間で運ぶのは識別値（`output_dir` と `feature`）だけである。** 依頼の中身も戦略書の本文も prompt / return value に載せない。依頼は script が組み立てて置き、戦略書は Agent が直接書き、成否は script が終了の値で判定する。

```bash
SCRIPT="${CLAUDE_SKILL_DIR}/scripts/strategy_exchange.py"
```

### 3.1 依頼を置く

Phase 2 で読んだ設計書パス・要件定義書パス（あれば）と、計画書ルール return value のルール文書パスを script に渡して依頼を置く。パスは 1 件ごとにオプションを繰り返す:

```bash
python3 "$SCRIPT" open --output-dir "{output_dir}" --feature "{feature}" \
  --design-doc "{設計書パス1}" [--design-doc ...] \
  [--requirement-doc "{要件定義書パス1}" ...] \
  [--rules-doc "{ルール文書パス1}" ...]
```

`open` が失敗した場合（終了コードが 0 以外）は、標準出力の `errors` を利用者へ報告して止める。終了コードが 2（引数を受理できない）のときは標準出力が空なので、標準エラーの内容を報告する。

既存戦略書（`{output_dir}/{feature}_strategy.md`）の有無は script が判定して依頼に入れる。特定の生成元を問わず、このパスに実装戦略書が既にあれば、設計フェーズ中の議論・レビュー往復で判明した移行方針・フェーズ分割が記録されている可能性があり、Agent はそれを土台にする。

### 3.2 カスタム Agent の起動

Agent ツールで `forge:plan-strategist`（`${CLAUDE_PLUGIN_ROOT}/agents/plan-strategist.md`）を起動する。prompt に書くのは識別値だけである:

```
Agent ツール起動: 実装戦略策定 (subagent_type: forge:plan-strategist)
prompt:
  - output_dir: {output_dir}
  - feature: {feature}
```

必読文書、依頼の読み方、関連する既存の仕様書とコードを自ら読む手順、書いてよいのは戦略書だけという制約は agent 定義が持つ。**prompt で指示を重ねない。**

### 3.3 成否の判定

Agent の完了後、script で成否を判定する。return value の内容で判断しない:

```bash
python3 "$SCRIPT" check --output-dir "{output_dir}" --feature "{feature}"
```

- `status: ok` → 3.4 へ
- `status: error` → Agent が策定を終えられなかった。Agent の return value（何が起きたかの自然文）を添えて利用者へ報告し、AskUserQuestion で再実行か中止かを確認する。**再実行は 3.1 からやり直す**（`check` が依頼を削除しているため、3.2 だけをやり直すと Agent は依頼を読めない）

`check` は成否にかかわらず依頼と終了の値の記録を削除する。戦略書は残す。

- **配置先**: `{output_dir}/{feature}_strategy.md`
- **ライフサイクル**: 計画書と同じ。全タスク完了時に計画書とともに存廃を利用者が選択する（`${CLAUDE_PLUGIN_ROOT}/docs/strategy_principles_spec.md`）

### 3.4 ユーザーレビューと承認

**Agent が戦略書を書くのは 1 回だけである。以後、戦略書は本スキルを実行している主体が責任を持って管理する。**

戦略書のパスを提示し（全文をチャットに転記しない。利用者はファイルを開いて読む）、AskUserQuestion で承認を得る。修正要望があれば、利用者と確かめながら自ら Read・Edit で直し、承認を得たら Phase 4 へ進む。

---

## Phase 4: 計画書の作成・更新

### 4.1 更新モード: 既存作業の確認

既存計画書がある場合（更新モード）、以下を必ず確認する:

1. **要件定義書への反映確認** — 変更内容が要件定義書に追記・修正されているか
2. **設計書への反映確認** — 設計変更を伴う場合、設計書に反映されているか
3. **未着手タスクの把握** — 既存計画書の未完了タスクを整理

上記に未反映がある場合は AskUserQuestion を使用して先に更新するか確認する。

### 4.2 実装戦略に基づきタスクを抽出

`{output_dir}/{feature}_strategy.md` を Read し、実装戦略のフェーズ分割に従ってタスクを抽出・分割する:

1. 各フェーズ内のモジュールを「1 Agent 実行で完結する単位」に分割
2. フェーズ順序を尊重した優先度を設定（フェーズ1のタスク > フェーズ2のタスク）
3. 同一フェーズ内で依存関係を整理（依存される側から先に実装）
4. 並列実行可能なタスクを識別（依存関係がないタスク群）

**実装戦略書の必読化**: すべてのタスクの `required_reading` に `{output_dir}/{feature}_strategy.md` を含める。executor が単一タスクだけを実装する場合でも、全体戦略・フェーズ意図・リスク対策を理解したうえで実装判断できるようにするため。

**タスクの粒度・グループ化**: タスク・グループとも「1つの Agent 実行で完結する」単位であることを基準とする。詳細な判定基準は `plan_principles_spec.md`「タスクの粒度」「タスクグループ」節に従う（事前準備で読み込み済み）。

### 4.3 計画書の作成・更新

**出力方式**: AI はタスクの意味内容（`title` / `description` / `acceptance_criteria` 等）を決定するが、計画書ファイルへの書き込みと構造検証は script が行う（AI は計画書ファイルの形式・キー配置を意識する必要はない）。ファイル名は script が `{feature}_plan.json` として決定する（拡張子は `.json`）。

**タスクID採番**: プロジェクトのフォーマットルールに従う。ルールがない場合は `TASK-001`, `TASK-002` 等の連番。

タスク ID を付与する際は、必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" TASK
```

JSON 出力の `next_id` を起点に連番を使用する。`duplicates` が空でない場合は警告を表示する。

**優先度**: プロジェクトのフォーマットルールに従う。ルールがない場合は数値が大きいほど優先度が高い（例: 1〜99）。実装戦略のフェーズ順序を反映すること。

**「やるべき内容」の記載原則・依存関係管理**: `plan_principles_spec.md`「『やるべき内容』の記載原則」「依存関係管理」節に従う（事前準備で読み込み済み）。依存関係は各タスクの `depends_on` 配列に落とし込み、計画書本体には依存関係マップを含めない。

**候補 JSON の組み立てと書き込み**:

1. **候補 JSON を組み立てる**: `requirements_traceability` / `design_traceability` / `tasks` の 3 キーを持つ object を組み立てる。追加開発（`--add`）の場合も frontmatter・予約キーは付与しない（`requirements_traceability` が参照する要件定義書の `feature_type: temporary-feature` frontmatter で追加 feature の計画書かを辿って判定できる。`frontmatter_format.md` §1.3 参照）
2. **候補 JSON を一時ファイルへ書く**: `Write` ツールで `.claude/.temp/plan-${CLAUDE_SESSION_ID}-{feature}.candidate.json` へ書く
3. **生成 script を 1 回実行する**。script が構造検証（3 キーのみ・`tasks[]` 必須フィールド・enum 値等）を行い、`{feature}_plan.json` へ書き出す。候補 JSON 側の入力ファイルは成否に関わらず script が自身で削除する:

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

### 4.4 完全性チェック

計画書のスキーマ検査（3 キー構成・`tasks[]` 必須フィールド・enum 値）は 4.3 の script が行うため、AI は以下の**計画品質検査**（意味的な妥当性）のみを確認する:

- [ ] すべての `tasks[].required_reading` に `{output_dir}/{feature}_strategy.md` が含まれている
- [ ] 実装戦略のフェーズ分割がタスクの優先度に反映されているか
- [ ] 要件トレーサビリティマトリクスが全要件を網羅しているか
- [ ] 設計トレーサビリティマトリクスが全設計書をカバーしているか
- [ ] 全設計書がタスクに反映されているか
- [ ] 依存関係に循環がないか

---

## Phase 5: AIレビュー

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

※ 実装戦略書・計画書は一時文書です。全タスク完了時に、残すか削除するかを確認します。
```
