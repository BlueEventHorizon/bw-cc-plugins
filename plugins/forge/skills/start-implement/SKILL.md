---
name: start-implement
description: |
  計画書からタスクを選び、実装・レビュー・計画更新まで一貫して実行する。
  トリガー: "実装開始", "タスク実行", "start implement"
user-invocable: true
argument-hint: "<feature> [-n N]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, Skill, AskUserQuestion
---

# /forge:start-implement

計画書（`{feature}_plan.json`）からタスクを選択し、コンテキスト収集→実装→レビュー→計画書更新を実行する。

## Goal

計画書から選択したタスクの実装・AIレビュー・計画書更新・完了案内まで完走すること。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:start-implement [feature] [-n N]
```

| 引数    | 内容                                                                                         |
| ------- | -------------------------------------------------------------------------------------------- |
| feature | Feature 名（省略時は対話で確定）                                                             |
| -n      | 優先度順で選択するタスク数（省略時は1件。依存関係に基づいて並列/ウェーブ実行を自動決定する） |

---

## 重要原則 [MANDATORY]

- **文書は省略しない** — 関連する可能性のある文書は全て executor に渡す。「最小限」思考は禁止
- **具体的なファイルパスで指定** — glob 指定は禁止、セクション番号・行番号指定も禁止
- **計画書のチェックマーク更新はオーケストレーターの責務** — executor は更新しない
- **executor の SUCCESS/FAILURE 報告に基づいて次の行動を決定** — 単一タスク実行時、FAILURE 時は Phase 5 をスキップ（複数タスク実行時の一部 FAILURE は Phase 5 をスキップしない。詳細は Phase 5 参照）
- **実装中に設計書・要件定義書を変更しない** — 設計書自体が誤り・不足だと判断したら中断し、修正案をユーザーへ提示して承認を得る

---

## Phase 1: 事前確認 [MANDATORY]

### 1.1 Feature の確定と計画書パスの解決

対象 Feature を確定し、計画書を特定する。Feature が決まらないと、どの計画書のタスクを実行するかが決まらない。

- **引数あり** → その Feature を使用
- **引数なし** → AskUserQuestion で対象 Feature を確認

計画書のパスを解決する:

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `plan`、feature `{feature}` でディレクトリを求め、その配下の `{feature}_plan.json` を
計画書パスとする。

1. ファイルが存在する → そのパスを使用
2. `plan` に対応するエントリが無い、またはファイルが存在しない → `specs/{feature}/plan/{feature}_plan.json` をデフォルトとする
3. それでも見つからない → AskUserQuestion で手動指定

**計画書全体を Read しない [MANDATORY]**: タスク選択・依存関係判定は Phase 2 の script が行うため、AI が計画書ファイルを直接読み込む必要はない（REQ-020 FNC-003・FNC-007）。他タスクの内容は、選択されたタスクについて Phase 4.3 で生成される `tasks/{タスクID}.json` を通してのみ扱う。

### 1.2 要件定義書・設計書の更新確認

Issue やバグ修正など計画書外のタスクを追加する場合:

1. **要件定義書への反映確認** — その内容が要件定義書に追記・修正されているか
2. **設計書への反映確認** — 設計変更を伴う場合、設計書に反映されているか
3. **未反映の場合** — AskUserQuestion: 「要件定義書/設計書への反映が必要です。先に更新しますか？」

---

## Phase 2: タスク選択 [MANDATORY]

タスクの優先度ソート・`status: pending` 抽出・依存関係チェック・グループ原子的選択・実行可能/待機グループへの分割は AI ではなく script が行う（REQ-020 FNC-003）。

### 2.1 選択 script の実行

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/select_tasks.py" --plan-path "{計画書パス}" \
  [--count {N}]
```

- `-n N` 指定あり → `--count N` を渡す
- `-n` 未指定 → `--count` を省略する（script が既定で最高優先度 1 件を選ぶ）

exit code で分岐する:

| exit code | 動作                                                                                                                                     |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 0         | stdout の `selected_task_ids` / `executable_task_ids` / `waiting_task_ids` / `selected_tasks`（選択タスクのフィールド全体）を得て 2.2 へ |
| 20        | stdout の `errors` を人間に提示する（相互依存・未完了の依存タスク等）。AskUserQuestion で対応（再指定 / 中断）を確認する                 |

### 2.2 選択結果の提示

`selected_task_ids` をユーザーに提示する。

- `-n N` 指定時: 「以下のタスクを並列実行します」としてリストを提示する。**承認は求めず、提示したうえでそのまま次へ進む**（`-n` は優先度順の自動選択であり、選択結果を人間が把握できれば足りる）

**設計書の存在確認**: 選択された各タスクの `design_id` が `null` でない場合、対応する設計書が存在するか Phase 3 のコンテキスト収集で確認する（本 Phase では確認しない）。

### 2.3 ウェーブ実行（`-n N` 指定時）

`executable_task_ids` を Phase 4 へ渡して並列実行する。完了後、`waiting_task_ids` のうち依存が解決されたタスクを対象に Phase 2.1 を再実行し、次の実行可能グループを得る。全タスクの実行が完了したら完了処理へ進む。

---

## Phase 3: コンテキスト収集 [MANDATORY]

### 3.1 文書の特定

以下の手順でタスクに必要な文書を特定する:

#### 3.1.1 設計書の特定

計画書の設計トレーサビリティマトリクスからタスクの設計IDに対応する設計書を特定する。

#### 3.1.2 要件定義書の特定

設計トレーサビリティマトリクスの要件IDから関連する要件定義書を特定する。

#### 3.1.3 実装ルールの収集

```
Agent ツール起動: 実装ルール収集
prompt:
  タスク "{タスクのタイトル}" (feature: {feature}) の実装に適用するプロジェクト固有ルール (レイヤー固有ルール等) を検索する。

  `/forge:query-db-rules {feature} {タスクのタイトル}` を呼ぶ。

  return value として以下の markdown 形式で返す:

  ## 実装ルール (N 件)
  - `path/to/rule.md` — 関連理由
```

#### 3.1.4 既存コードの収集

```
Agent ツール起動: 既存コード収集
prompt:
  タスク "{タスクのタイトル}" (feature: {feature}) に関連する既存コード (類似実装、参照コード) を探索する。

  検索手順:
  - 機能名・コンポーネント名で `Grep` / `Glob: **/*{キーワード}*`
  - 同一ディレクトリ・import 元・類似命名・テストファイルを分類

  return value として以下の markdown 形式で返す:

  ## 既存コード (N 件)
  - `path/to/file.swift` — 関連理由
```

> 3.1.3 と 3.1.4 は **Agent ツールで並列起動** する。エラー終了した場合は該当カテゴリなしで続行。各 agent の **return value** を main AI コンテキストに直接保持する。

#### 3.1.5 計画書 `required_reading` フィールドの処理

Phase 2.1 の `selected_tasks` から該当タスクの `required_reading` 配列を取得する。空配列 `[]` でない場合、記載された各ファイルパスを追加の必読文書として executor に渡す。

`{feature}_strategy.md` が `required_reading` に含まれている場合は、**戦略書**として分類して executor に渡す。含まれていない場合でも、計画書と同じディレクトリに `{feature}_strategy.md` が存在するなら追加の必読文書として executor に渡す。executor は全体戦略・フェーズ意図・リスク対策を理解したうえで、指定された単一タスクだけを実装する。

### 3.2 統合・表示

全 agent 完了後、agent の return value (実装ルール / 既存コード) と直接特定した文書 (設計書 / 要件定義書) を統合して表示する:

```
### ✅ コンテキスト収集完了

**設計書**
- `specs/{feature}/design/xxx.md` — 対象設計書

**要件定義書**
- `specs/{feature}/requirements/xxx.md` — 関連要件

**rules (N件)**
- `rules/xxx.md` — 実装ルール

**code (N件)**
- `src/xxx/YYY.ts` — 既存実装

**戦略書**
- `specs/{feature}/plan/{feature}_strategy.md` — 実装戦略

**追加必読文書**
- `specs/{feature}/rules/extra_context.md` — 計画書 required_reading（戦略書以外）
```

5件以下は全件表示、6件以上は先頭3件+省略。

---

## Phase 4: タスク実行 [MANDATORY]

### 4.1 検証要件の判定 [MANDATORY]

オーケストレーターが Phase 2.1 の `selected_tasks` から該当タスクのフィールド値を取得し、検証要件を判定する:

**`build_check` フィールドの値による検証要件**（`build_check` の値が最優先）:

| 値                       | 検証要件                           |
| ------------------------ | ---------------------------------- |
| `per_task`（デフォルト） | タスク完了時にビルド確認必須       |
| `skip`                   | ビルド確認スキップ（代替検証推奨） |
| `on_group_complete`      | グループ最終タスクでビルド確認必須 |

**`acceptance_criteria` フィールドが `null` でない場合**:

- 記載された基準を検証要件として executor に渡す

### 4.2 スコープ境界の導出 [MANDATORY]

実行対象の各タスクについて、スコープ境界を Phase 2.1 の `selected_tasks` から導出する。**この導出は 1 回だけ行い、executor（4.3）と レビュー依頼（5.1 / 5.2）の両方に使う**。同じ情報を 2 回作ると片方だけが古くなる。

**範囲内（`scope_in`）**: タスクの `description` が到達すべき範囲そのものである。**単一行**に要約する。

**範囲外（`scope_out`）**: 以下を満たす他タスクを列挙し、1 件ごとに `item` / `owner_task_id` / `reason` を組む。

- `status` が `completed` でない
- 今回の実行対象に選択されていない（`-n N` で選ばれた集合の外）**か、同じグループの別メンバーである**（グループ内の他メンバーが担当する項目も、当該タスク単体では範囲外である。バッチ合算時の差し引きは 5.1 のスクリプトが行う）
- 対象タスクと同じ `design_id` を持つ、**または** 対象タスクを `depends_on` に含む

`reason`（分離されている理由）は対象タスクの `description` / 戦略書から読み取れる範囲で書く。読み取れない場合は「計画上分離」と書き、推測で埋めない。`item` / `owner_task_id` / `reason` はいずれも**単一行**であること（5.1 のスクリプトが改行・見出し行を fail-fast で拒否する。レビュー依頼本文の節構造を偽装できるため）。

該当タスクが 0 件の場合は `scope_out` を空配列にする。**executor プロンプトの節そのものは省略しない**（「（なし。このタスクで対象範囲は最終形に到達する）」と書く）— 空欄と「最終形である」の区別が付かなくなる。

導出結果は 5.1 の入力へそのまま渡せる形で保持する:

```json
{
  "task_id": "TASK-007",
  "scope_in": "fm_to_pending.py の新規作成とテストまで",
  "scope_out": [
    {
      "item": "_meta.extracted_by の追加",
      "owner_task_id": "TASK-011",
      "reason": "転記側だけ先に書くと読む側が存在しない死にフィールドになるため分離"
    }
  ]
}
```

### 4.3 タスクコンテキストの生成 [MANDATORY]

4.1（検証要件）・4.2（スコープ境界）・Phase 3.2（必読文書の統合結果）と、タスク固有の実装指示から、`{feature}_plan.json` と同じディレクトリに `tasks/{タスクID}.json` を生成する。executor へは、この生成済みファイルのパスと `task_id` だけを渡す（`plan.json` の値をインライン Markdown へ手で転記しない）。

1. **候補 JSON を組み立てる**（スキーマは `${CLAUDE_SKILL_DIR}/templates/task_context_input.json` を参照）:
   - `scope_in` / `scope_out`: 4.2 の導出結果をそのまま使う
   - `required_reading`: Phase 3.2 で統合した文書パスを `design_docs` / `requirement_docs` / `strategy_doc` / `rule_docs` / `reference_code` / `additional` へ分類する
   - `implementation_instructions`: タスク固有の実装方針（必読文書を踏まえて AI がその場で書く。従来の「実装指示」と同じ内容）
   - `verification`: 4.1 の判定結果（`build` は `required`/`skipped`、`tests` は `required`/`optional`/`skipped`。スキップ時のみ `_reason` を添える）
2. **候補 JSON を一時ファイルへ書く**: `Write` ツールで `.claude/.temp/task-context-${CLAUDE_SESSION_ID}-{タスクID}.candidate.json` へ書く（シェルコマンドへ直接埋め込まない。自由記述をシェル文字列に乗せると注入リスクを生むため）
3. **生成 script を 1 回実行する**。`plan.json` の該当タスクエントリと候補 JSON をマージして `tasks/{タスクID}.json` へ書き出す。候補 JSON 側の入力ファイルは成否に関わらず script が自身で削除する:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/build_task_context.py" \
     --plan-path "{計画書パス}" \
     --task-id "{タスクID}" \
     --input-file ".claude/.temp/task-context-${CLAUDE_SESSION_ID}-{タスクID}.candidate.json" \
     --output-path "{計画書と同じディレクトリ}/tasks/{タスクID}.json"
   ```

   exit code で分岐する:

   | exit code | 動作                                                                                                                                       |
   | --------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
   | 0         | stdout の `output_path` を確認し、4.4 へ進む                                                                                               |
   | 20        | stdout の `errors` に従って候補 JSON を訂正し、Write から同じ手順をもう 1 回だけ実行する。2 回目も失敗した場合はエラーとして報告し中断する |

### 4.4 executor 起動

以下のテンプレートで executor への指示を構築する:

```markdown
以下のタスクを実装してください。

## 実行ガイド

${CLAUDE_SKILL_DIR}/docs/task_execution_spec.md を Read して手順に従うこと。

## タスクコンテキスト

{4.3 で生成した tasks/{タスクID}.json のパス}

## result template

${CLAUDE_SKILL_DIR}/templates/executor_result.json

## producer validator

${CLAUDE_SKILL_DIR}/scripts/validate_executor_result.py

## producer input path

.claude/.temp/executor-result-${CLAUDE_SESSION_ID}-{タスクID}.producer.json

## 出力契約

単一実行・並列実行を問わず、実行ガイド Step 5 の JSON だけを Agent の return value として返すこと。
```

```
Agent(subagent_type: general-purpose, prompt: {構築したパラメータ})
```

**並列実行時**: 独立タスクごとに別の executor を Agent ツールで同時起動する。

### 4.5 executor の結果受領 [MANDATORY]

単一実行・並列実行を問わず、各 executor は `${CLAUDE_SKILL_DIR}/docs/task_execution_spec.md` Step 5 が定める JSON を return value として返す。Markdown 報告を受理しない。オーケストレーターは全 executor 完了後に return value を収集して処理する。

受領した各 return value は、内容を AI が解釈する前に consumer wrapper へ渡す。return value を heredoc・引用文字列・環境変数としてシェルコマンドへ埋め込まない。

1. Write ツールで return value **だけ**を `.claude/.temp/executor-result-${CLAUDE_SESSION_ID}-{起動したタスクID}.consumer.json` へ書く
2. 次のコマンドを 1 回実行する。consumer wrapper が検証・FAILURE 変換・入力ファイル削除を一括して行う

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/receive_executor_result.py" \
  --input-file ".claude/.temp/executor-result-${CLAUDE_SESSION_ID}-{起動したタスクID}.consumer.json" \
  --expected-task-id "{起動したタスクID}" \
  --expected-build "{4.1 の判定: required | skipped}" \
  --expected-tests "{4.1 の判定: required | optional | skipped}"
```

- exit 0 → stdout の正規化済み JSON で元の return value を置き換え、後続処理にはその JSON だけを使う
- 非ゼロ → validator 自体の実行失敗として Phase 6.5 へ進む

期待値は Phase 4.1 で executor へ渡した検証要件と同じ値を使う（必須=`required`、任意=`optional`、スキップ=`skipped`）。契約違反の return value は consumer wrapper が `status: FAILURE` の正規化済み JSON へ変換する。フィールドの補完・型変換・エラーからの FAILURE 生成を手作業で行わない。

| ステータス | 意味     | 次のアクション            |
| ---------- | -------- | ------------------------- |
| SUCCESS    | 実装完了 | Phase 5（AI レビュー）へ  |
| FAILURE    | 実装失敗 | Phase 6.5（エラー対応）へ |

**executor は計画書や共有リソースに直接書き込まない。** 各 executor は結果を **return value として JSON で返す**。orchestrator が全 executor 完了後に return value を収集して一括処理する。

後続処理は `task_id` / `status` / `files_modified` / `summary` / `error` を使う。`verification` / `pre_mortem` / `notes` はタスク結果の報告とエラー対応に保持し、`pre_mortem` を含む追加フィールドを削除して最小スキーマへ変換しない。

---

## Phase 5: AI レビュー

> 単一タスク実行時、executor が FAILURE を報告した場合は本 Phase をスキップし Phase 6.5 へ進む。複数タスク実行時に一部が FAILURE の場合はスキップしない（5.1 のグループ判定に FAILURE 結果も必要なため）。

### 5.1 レビュー対象のグルーピング [MANDATORY]

**タスク数 = レビュー起動回数ではない**。計画書 (`{feature}_plan.json`) の `group_id` が同一のタスク群は 1 回のレビューにまとめる（グループ単位バッチレビュー）。1 タスク = 1 レビュー起動だと、機械的に同型の編集をファイル数分繰り返すだけのグループ（例: 同一パターンの置換を N ファイルに適用する GROUP）でもレビュー往復が N 回発生し、タスク数に比例して所要時間が伸びるため。

`group_id` は通し番号付き（`"GROUP-001 (1/7)"` 等）で記録されるため、単純な文字列一致では同一グループの各タスクが別グループとして扱われてしまう。この正規化・グループ完全性判定・部分失敗時の保留・ファイル順序の決定・**スコープ境界の合算**は決定論的な処理であり、SKILL.md にインライン記述せず専用スクリプトに委譲する（`docs/rules/implementation_guidelines.md`「SKILL.md にインラインスクリプトを書かない」）:

`<input_json>` は Write ツールで `.claude/.temp/start-implement-review-batches-${CLAUDE_SESSION_ID}.json` へ書き、シェル構文へ埋め込まない。wrapper が処理後に入力ファイルを削除する。

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/group_review_batch.py" \
  --input-file ".claude/.temp/start-implement-review-batches-${CLAUDE_SESSION_ID}.json"
```

`<input_json>` は以下の 2 フィールドを持つ。`tasks` は計画書 `tasks[]` 全件から `task_id`/`group_id` を抽出し、**実行対象タスクには 4.2 で導出した `scope_in` / `scope_out` を添えたもの**（Phase 1 で計画書を読み込み済みのため抽出は容易）、`results` は今回の実行で得た **全 executor 結果（SUCCESS/FAILURE 問わず）**:

```json
{
  "tasks": [
    {
      "task_id": "TASK-001",
      "group_id": "GROUP-001 (1/7)",
      "scope_in": "fm_to_pending.py の新規作成とテストまで",
      "scope_out": [
        {
          "item": "_meta.extracted_by の追加",
          "owner_task_id": "TASK-011",
          "reason": "転記側だけ先に書くと死にフィールドになるため分離"
        }
      ]
    },
    "..."
  ],
  "results": [
    { "task_id": "TASK-001", "status": "SUCCESS", "files_modified": ["..."] },
    "..."
  ]
}
```

`scope_in` / `scope_out` を持たないタスク（今回の実行対象外のタスク等）はそのまま省略してよい。スクリプトは各バッチの `scope_text` を「全メンバーの `scope_out` の和集合 − 同じバッチのメンバーが `owner_task_id` として担当する項目」で組み立てる。**この差し引きを手で行わない** — グループ化の理由はまさに「TASK-A の範囲外項目が TASK-B の範囲内である」ことなので、単純連結すると今回実装済みの項目を「意図的な未実装」として宣言してしまう。

出力:

```json
{
  "status": "ok",
  "review_batches": [
    {
      "kind": "individual",
      "task_ids": ["TASK-010"],
      "files": ["..."],
      "scope_text": "..."
    },
    {
      "kind": "group",
      "group_key": "GROUP-001",
      "task_ids": ["TASK-001", "..."],
      "files": ["..."],
      "scope_text": "..."
    }
  ],
  "held_groups": [
    {
      "group_key": "GROUP-002",
      "task_ids": ["..."],
      "failed_task_ids": ["..."],
      "reason": "partial_failure"
    }
  ],
  "scope_missing_task_ids": ["TASK-020"]
}
```

判定ロジックの要点（詳細はスクリプト実装を正とする）:

- **`group_id: null`（独立タスク）**: 常に `kind: "individual"`（1 タスク = 1 レビュー、従来通り）
- **グループの全メンバーが今回の実行結果に揃っており、かつ全て SUCCESS**: `kind: "group"` として 1 回に合算（ファイルは重複除去・計画書順で決定論的に整列）
- **グループの一部メンバーしか今回の結果に含まれない**（過去の別起動で一部メンバーが先に `completed` になっていた等）: 揃っていない分は `kind: "individual"` にフォールバックする（累積グループ差分の追跡は複雑さに見合わないためスコープ外）。`-n N` 指定時は Phase 2.1「グループの原子的選択」により、今回の実行内では常に全メンバーが揃って選択される
- **グループの全メンバーが揃っているが 1 件以上 FAILURE**: グループ全体を `held_groups` へ回し、SUCCESS した同グループの他タスクも含めてレビュー対象にしない（中間状態の壊れたグループを合算レビューしたり、成功した一部だけを完了扱いにしたりしない）

`scope_missing_task_ids[]` が空でない場合、該当タスクのスコープ境界が 4.2 で導出されていない（＝レビュアーは対象を最終形として評価する）。**この事実を人間に提示してから 5.2 へ進む** — 段階分割されたタスクでこの状態のままレビューすると、後続タスクの未実装が欠陥として報告される。

### 5.2 レビューの実施 [MANDATORY]

`review_batches[]` を順に処理する（グループ内部・グループ間ともに並列化しない。**同時に複数のレビューを走らせられるかはバックエンドごとの性質であり、共通契約はこれを定義していない**。単一の常駐セッションとの往復で成立するバックエンドでは、並行した依頼が交錯して往復が混線する。契約に無い性質を呼び出し側が仮定しないため、直列で処理する）:

- `kind: "individual"` → 該当 `files` に対して Skill ツールで 1 回実行する
- `kind: "group"` → 該当 `files`（グループ全メンバー合算・重複除去済み）に対して **1 回だけ** 実行する
  - 合算ファイル数が多く、1 回のレビューでは精査が浅くなると判断した場合は、グループのメンバー境界で複数回に分割して実行してよい（1 回の呼び出しに固執しない）。**分割した場合は、各回に渡す `--scope` を分割後のメンバー集合で 5.1 から再取得する**（合算済みの `scope_text` をそのまま流用すると、分割後は別バッチのメンバーが担当する項目が範囲外として宣言されない）

```
# Skill ツールで起動する（kind 問わず同一構文）
/forge:review code --files {ファイル一覧(カンマ区切り)} --auto \
  --scope "{当該バッチの scope_text}（該当タスクの acceptance_criteria が null でなければ、その内容を追記する）" \
  --project-rules {Phase 3 で収集したルール文書(カンマ区切り)} \
  --project-specs {設計書・要件定義書(カンマ区切り)}
```

**Phase 3 で収集した文書と 4.2 で導出したスコープ境界をレビュー依頼へ渡す [MANDATORY]**。executor には渡してレビュアーには渡さない状態を作らない（実装者は範囲と規範を知っていて、検証者は知らないという非対称が往復を生む）。渡すもの・渡さないものは以下のとおり:

| 4.3 で executor へ渡した情報              | レビュー依頼へ | 理由                                                                                                                         |
| ----------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| スコープ境界（4.2 / 5.1 の `scope_text`） | 渡す           | 本 Phase の目的。`--scope` へ渡す                                                                                            |
| `acceptance_criteria`（4.1）              | 渡す           | 到達目標の一部。`scope_in`（`description` の要約であり `acceptance_criteria` を含まない）とは別に、`--scope` へ追記して渡す  |
| ルール文書のパス（3.1.3）                 | 渡す           | `--project-rules` へ渡す。レビュー側が同じ検索をやり直す二重実行を避ける                                                     |
| 設計書・要件定義書のパス（Phase 1 / 3.2） | 渡す           | `--project-specs` へ渡す。同上。**戦略書・`required_reading` は渡さない**（実装手順の指示であり規範ではない）                |
| 実装指示（4.3）                           | **渡さない**   | オーケストレーターの設計解釈である。渡すとレビューが「指示どおりか」の適合チェックに退化し、解釈自体の誤りを検出できなくなる |
| 参照コード（3.1.4 の類似実装）            | **渡さない**   | 「既存と同型だから妥当」という追認バイアスになる。既存側が誤っている場合に増幅する                                           |
| 検証要件（4.1 の `build_check` 等）       | **渡さない**   | `skip` を伝えると「テストがない」という正当な所見の免罪符になる                                                              |

`held_groups[]` は Phase 6.5（エラー対応）で扱う: グループ内の一部タスクが FAILURE の場合、SUCCESS した同グループの他タスクも含めてレビュー・完了マークを保留し、失敗タスクの解決後に同グループ全体を再実行・再レビューする。

`/forge:review` が利用できない場合は `git diff` で変更差分を人間に提示し、手動レビューを依頼する。

### 5.3 レビュー完了

レビュー+自動修正が完了したら Phase 6 へ進む。

---

## 完了処理

### 6.1 結果判定

executor のステータスに基づいて分岐:

- **SUCCESS** → 6.2 へ
- **FAILURE** → 6.5 へ

#### 複数タスク並列実行時

各 executor の return value JSON を収集し、SUCCESS / FAILURE を分類する:

- SUCCESS タスク → 6.2 で一括更新。**ただし Phase 5.1 の `held_groups[]` に含まれる task_id は除外する**（レビューが保留されており、まだ `completed` にしてはならない）
- FAILURE タスク → 6.5 で個別対応
- `held_groups[]` に含まれる task_id（SUCCESS だが同グループの他タスクが FAILURE のため保留） → 6.5 で扱う（グループ全体として、失敗タスクの解決を待ってから再実行・再レビューする対象。`status` は `pending`/`in_progress` のまま据え置く）

### 6.2 計画書の更新 [MANDATORY]

レビュー完了後、計画書を更新する。タスクのステータス変更・要件トレーサビリティの判定は AI ではなく script が行う（REQ-020 FNC-004）。

**`held_groups[]` の task_id は対象外**（レビュー未実施のため `completed` にしない）。`held_groups[]` を除いた全 SUCCESS タスクの task_id を**1 回の script 実行で一括指定**する。個別に実行しない。

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/update_plan_status.py" \
  --plan-path "{計画書パス}" \
  --task "TASK-001,TASK-002"
```

script は指定タスクを `status: completed` に更新し、`design_traceability` 経由で紐づく要件の全タスクが `completed` になった要件を `requirements_traceability[].status: completed` へ更新して計画書へ書き戻す。exit code 0 で `updated_count` を確認する。

### 6.3 commit/push 確認

commit/push の確認フローを担うスキル（例: `anvil:commit`）が available-skills にあれば呼び出す。無ければ `git add` → `git commit` の手順を案内する。

### 6.4 次タスク判定

次タスクの判定:

- 同一 Feature に未完了タスクがある → AskUserQuestion:「次のタスクに進みますか？」
  - **進む** → Phase 2 に戻る
  - **終了** → 「完了案内（未完了タスクあり）」を表示
- 同一 Feature に未完了タスクがない → 6.4.1 の完了処理へ

### 6.4.1 全タスク完了時の後処理 [MANDATORY]

全タスク完了時、計画書の扱いをユーザーに確認する。
**自動削除は禁止。必ず AskUserQuestion で確認する。**

AskUserQuestion:「全タスクが完了しました。計画書（plan）を削除しますか？」

`tasks/` ディレクトリ（4.3 で生成した `tasks/{タスクID}.json` の置き場）は計画書と同じライフサイクルとする。計画書を削除するときは必ず一緒に削除し、残すときは一緒に残す（個別に確認しない）。

- **削除する** → `rm {plan_path}` → `rm -rf {計画書と同じディレクトリ}/tasks/` → 完了案内（plan 削除パターン）
- **残す** → 計画書・`tasks/` ともそのまま残す → 完了案内（plan 残しパターン）

### 6.5 エラー対応（FAILURE パス）

executor が FAILURE を報告した場合:

1. エラー内容を人間に提示（AskUserQuestion）
2. 人間の判断に基づいて対応:
   - **executor 再実行** → 前回の失敗情報を追加指示として含め、Phase 4 から再実行
   - **手動で修正** → オーケストレーターまたは人間が直接修正後、Phase 5 へ
   - **タスクをスキップ** → 計画書は更新せず、Phase 6.4 へ

**再実行上限: 1回**（初回 + 再実行1回 = 最大2回）。上限に達した場合は人間にエスカレーションして終了する。

#### held_groups（グループの部分失敗）への対応

Phase 5.1 が `held_groups[]` を返した場合、FAILURE したタスクを 6.5 の通常フローで対応した後、**同グループ全体を Phase 4 から再実行する**（SUCCESS 済みメンバーも含めて再実行対象とする。差分がなければ executor は素通りで再度 SUCCESS を返す想定）。個別タスクの再実行上限（1回）とは別に、グループ再実行はグループ内 FAILURE タスクの再実行上限に従う。再実行後、Phase 5.1 のグループ判定を再度通し、全メンバー SUCCESS になった時点で初めてグループ合算レビューを実施する。

---

## 完了案内（未完了タスクあり）

```
タスク実行が完了しました:
  → {タスクID}: {タイトル} ☑

残タスク: {未完了タスク数} / {全タスク数}
次のタスク候補: {次の最高優先度タスクID} — {タイトル}

次のステップ:
  /forge:start-implement {feature}                              # 次のタスクを実行
  /forge:start-implement {feature} -n 3                         # 優先度順で3件を選択して実行
```

## 全タスク完了案内

```
{feature} の全タスクが完了しました。
  完了タスク: {完了タスク数} / {全タスク数}
```
