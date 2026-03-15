---
name: start-implement
description: |
  計画書のタスクを選択し、コンテキスト収集・実装・レビュー・計画書更新を一連で実行する。
  トリガー: "実装開始", "タスク実行", "start implement", "/forge:start-implement"
user-invocable: true
argument-hint: "<feature> [--task TASK-ID[,TASK-ID,...]]"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion
---

# /forge:start-implement

計画書（`{feature}_plan.yaml`）からタスクを選択し、コンテキスト収集→実装→レビュー→計画書更新を実行する。

## コマンド構文

```
/forge:start-implement [feature] [--task TASK-ID[,TASK-ID,...]]
```

| 引数 | 内容 |
| --- | --- |
| feature | Feature 名（省略時は対話で確定） |
| --task | 実行するタスクID（カンマ区切りで複数指定可。省略時は優先度順で自動選択） |

---

## 重要原則 [MANDATORY]

- **文書は省略しない** — 関連する可能性のある文書は全て executor に渡す。「最小限」思考は禁止
- **具体的なファイルパスで指定** — glob 指定は禁止、セクション番号・行番号指定も禁止
- **計画書のチェックマーク更新はオーケストレーターの責務** — executor は更新しない
- **executor の SUCCESS/FAILURE 報告に基づいて次の行動を決定** — FAILURE 時は Phase 5 をスキップ

---

## Phase 1: 事前確認 [MANDATORY]

### 1.1 Feature の確定と計画書の読み込み

対象 Feature を確定し、計画書を特定する。Feature が決まらないと、どの計画書のタスクを実行するかが決まらない。

- **引数あり** → その Feature を使用
- **引数なし** → AskUserQuestion で対象 Feature を確認

計画書のパスを解決する:

1. `doc-structure` スキルのスクリプトで Feature を検索:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type plan
   ```
2. 見つからない場合 → `specs/{feature}/plan/{feature}_plan.yaml` をデフォルトとする
3. それでも見つからない → AskUserQuestion で手動指定

計画書（YAML）を Read し、全タスクの状態を把握する。

### 1.2 要件定義書・設計書の更新確認

Issue やバグ修正など計画書外のタスクを追加する場合:

1. **要件定義書への反映確認** — その内容が要件定義書に追記・修正されているか
2. **設計書への反映確認** — 設計変更を伴う場合、設計書に反映されているか
3. **未反映の場合** — AskUserQuestion: 「要件定義書/設計書への反映が必要です。先に更新しますか？」

---

## Phase 2: タスク選択

### 2.1 タスクの選択

**`--task` 指定あり（単一）**:
- 指定されたタスクを実行対象とする

**`--task` 指定あり（複数: カンマ区切り）**:
- 指定された全タスクを実行対象とする
- 例: `--task TASK-001,TASK-003`

**`--task` 指定なし**:
1. `tasks` 配列を `priority` 降順でソート
2. `status: pending` のタスクから最高優先度のものを1つ選択

### 2.2 実行可能性の確認

選択した全タスクについて以下を確認:

- **依存関係チェック**: `depends_on` 配列の全タスクが `status: completed` か確認。未完了の依存がある場合は AskUserQuestion で確認
- **設計書の存在**: 設計ID ≠ `-` の場合は対応する設計書が存在するか確認
- **タスクグループの確認**: グループ内タスクはグループ先頭から順次実行。グループ途中からの実行は不可

### 2.3 複数タスク指定時の依存関係チェック [MANDATORY]

複数タスクが指定された場合、タスク間の相互依存を検証する:

1. 指定されたタスク同士で依存関係がないか確認
2. **依存関係あり** → エラー終了:「TASK-002 は TASK-001 に依存しているため並列実行できません。逐次実行してください。」
3. **依存関係なし** → AskUserQuestion:「以下のタスクを並列実行します。よろしいですか？」とタスクリストを提示

---

## セッション管理 [MANDATORY]

<!-- DES-011 §3.2 準拠: start-implement は事前準備 Phase が多いため、セッション管理を Phase 間の独立セクションとして配置 -->

残存セッション検出:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill start-implement
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 無視して新規作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-implement \
  --feature "{feature}" \
  --task-id "{TASK-ID}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## Phase 3: コンテキスト収集 [MANDATORY]

### 3.1 文書の特定

以下の手順でタスクに必要な文書を特定する:

#### 3.1.1 設計書の特定

計画書の設計トレーサビリティマトリクスからタスクの設計IDに対応する設計書を特定する。

#### 3.1.2 要件定義書の特定

設計トレーサビリティマトリクスの要件IDから関連する要件定義書を特定する。

#### 3.1.3 実装ルールの収集

プロジェクト固有の実装ルール（レイヤー固有ルール等）を検索する agent を起動する。結果は `{session_dir}/refs/rules.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 実装ルール調査
feature: "{feature}"
skill_type: "{タスクのタイトル}"
```

#### 3.1.4 既存コードの収集

既存コード（類似実装、参照コード）を検索する agent を起動する。結果は `{session_dir}/refs/code.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 既存コード調査
feature: "{feature}"
skill_type: "{タスクのタイトル}"
```

> 3.1.3 と 3.1.4 は **Agent ツールで並列起動** する。エラー終了した場合は該当カテゴリなしで続行。

#### 3.1.5 計画書「必読」列の処理

計画書のタスク表に「必読」列がある場合、記載されたファイルパスを追加の必読文書とする。

### 3.2 refs/ 統合・表示

全 agent 完了後、`{session_dir}/refs/` 内のファイルと直接特定した文書を統合して表示する:

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
```

5件以下は全件表示、6件以上は先頭3件+省略。

---

## Phase 4: タスク実行 [MANDATORY]

### 4.1 検証要件の判定 [MANDATORY]

オーケストレーターが計画書を読んで検証要件を判定する:

**「ビルド確認」列がある場合**（列の値が最優先）:

| 値 | 検証要件 |
|----|---------|
| `タスクごと`（またはデフォルト） | ビルド確認必須 |
| `スキップ` | ビルド確認スキップ（代替検証推奨） |
| `グループ完了時` | グループ最終タスクでビルド確認必須 |

**「受け入れ基準」列がある場合**:
- 記載された基準を検証要件として executor に渡す

### 4.2 パラメータの構築 [MANDATORY]

以下のテンプレートで executor への指示を構築する:

```markdown
以下のタスクを実装してください。

## 実行ガイド
${CLAUDE_PLUGIN_ROOT}/docs/task_execution_spec.md を Read して手順に従うこと。

## タスク情報
- タスクID: {タスクID}
- タスク名: {タイトル}
- 優先度: {数値}
- 実装内容:
  {やるべき内容の箇条書き}

## 必読文書（全文読み込み必須）
- 設計書:
  - {設計書ファイルパス}
- 要件定義書:
  - {関連する全ての要件定義書}
- ルール文書:
  - {関連する全てのルール文書}
- 参照コード:
  - {関連する全ての既存実装}

## 実装指示
{タスク固有の実装指示}

## 検証要件
- ビルド確認: {必須 | スキップ}
- テスト実行: {必須 | 任意 | スキップ}
- スキップ理由: {理由 | -}
```

**パラメータは AskUserQuestion で人間に確認してから実行する** [MANDATORY]

### 4.3 executor 起動

```
Agent(subagent_type: general-purpose, prompt: {構築したパラメータ})
```

**並列実行時**: 独立タスクごとに別の executor を Agent ツールで同時起動する。

### 4.4 executor の結果受領

executor は以下のステータスで報告する:

| ステータス | 意味 | 次のアクション |
|-----------|------|--------------|
| SUCCESS | 実装完了 | Phase 5（AI レビュー）へ |
| FAILURE | 実装失敗 | Phase 6.4（エラー対応）へ |

---

## Phase 5: AI レビュー

> executor が FAILURE を報告した場合、本 Phase はスキップし Phase 6.4 へ進む。

### 5.1 レビューの実施

executor が作成・変更したファイルに対して `/forge:review code` を実行する:

```
/forge:review code {変更ファイル一覧}
```

`/forge:review` が利用できない場合は `git diff` で変更差分を人間に提示し、手動レビューを依頼する。

### 5.2 レビュー結果の確認

レビュー結果に基づき、人間が修正判断を行う。
修正が完了したら Phase 6 へ進む。

---

## 完了処理

### 6.1 結果判定

executor のステータスに基づいて分岐:
- **SUCCESS** → 6.2 へ
- **FAILURE** → 6.4 へ

### 6.2 計画書の更新 [MANDATORY]

レビュー完了後、計画書（YAML）を更新する:

1. **タスクのステータス**: `status: pending` → `status: completed`
2. **要件トレーサビリティ**: 関連する要件の全タスクが `completed` なら `status: completed` に更新

### 6.3 セッション削除・次タスク判定

```bash
rm -rf {session_dir}
```

次タスクの判定:
- 同一 Feature に未完了タスクがある → AskUserQuestion:「次のタスクに進みますか？」
  - **進む** → Phase 2 に戻る
  - **終了** → 完了案内を表示

### 6.4 エラー対応（FAILURE パス）

executor が FAILURE を報告した場合:

1. エラー内容を人間に提示（AskUserQuestion）
2. 人間の判断に基づいて対応:
   - **executor 再実行** → 前回の失敗情報を追加指示として含め、Phase 4 から再実行
   - **手動で修正** → オーケストレーターまたは人間が直接修正後、Phase 5 へ
   - **タスクをスキップ** → 計画書は更新せず、Phase 6.3 へ

**再実行上限: 1回**（初回 + 再実行1回 = 最大2回）。上限に達した場合は人間にエスカレーション。

---

## 完了案内

```
タスク実行が完了しました:
  → {タスクID}: {タイトル} ☑

残タスク: {未完了タスク数} / {全タスク数}
次のタスク候補: {次の最高優先度タスクID} — {タイトル}

次のステップ:
  /forge:start-implement {feature}                              # 次のタスクを実行
  /forge:start-implement {feature} --task {TASK-ID}             # 特定タスクを実行
  /forge:start-implement {feature} --task {ID1},{ID2},{ID3}     # 複数タスクを並列実行
```
