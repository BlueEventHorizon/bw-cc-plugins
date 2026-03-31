---
name: start-plan
description: |
  設計書から実装タスクを抽出し、計画書を作成・更新できる。
  トリガー: "計画書作成", "計画開始", "start planning"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, AskUserQuestion
---

# /forge:start-plan

設計書からタスクを抽出し、計画書を作成または更新する。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:start-plan [feature]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |

---

## 事前準備 [MANDATORY]

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの設計書から計画するか）も出力先も決まらない。

- **引数あり** → その Feature を使用
- **引数なし** → AskUserQuestion で対象 Feature を確認

### .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → AskUserQuestion を使用して確認する:
  ```
  .doc_structure.yaml が見つかりません。
  /forge:setup-doc-structure を実行してプロジェクト構造を定義する必要があります。今すぐ /forge:setup-doc-structure を実行しますか？
  ```
  - **はい** → `/forge:setup-doc-structure` を呼び出し、完了後に次のステップへ進む
  - **いいえ** → 終了
- **存在する** → 次のステップへ

### 出力先の解決

計画書の出力先を特定する。入力文書（設計書）は Phase 1 で agent が特定する。

- `doc-structure` スキルのスクリプトで Feature を検索:
  ```bash
  python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type plan
  ```
- 解決できない場合は AskUserQuestion で出力先を確認する

### モード判定 [MANDATORY]

出力先の計画書の存在を確認し、モードを決定する。

| 状況               | モード                                                        |
| ------------------ | ------------------------------------------------------------- |
| 計画書が存在しない | **新規作成モード** → Phase 1 へ                               |
| 計画書が存在する   | AskUserQuestion でユーザーに確認                              |

既存計画書がある場合、AskUserQuestion を使用して確認する:

- 既存計画書を更新する → 既存計画書を Read して現状を把握し Phase 1 へ
- レビューのみ行う → `/forge:review plan {既存計画書パス}` を起動して終了

### プラグイン文書の読み込み [MANDATORY]

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md`** — ID分類カタログ（タスクIDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/docs/plan_format.md`** — 計画書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`** — 計画書作成原則・タスク設計ガイドライン

---

## セッション管理 [MANDATORY]

残存セッション検出:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py find --skill start-plan
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-plan \
  --feature "{feature}" \
  --mode "{new|update}" \
  --output-dir "{計画書の出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## Phase 1: コンテキスト収集 [MANDATORY]

以下の2つの収集を **Agent ツールで並列起動** する。
各 agent がエラー終了した場合は該当カテゴリなしで後続工程に進む。

### 1.1 要件定義書・設計書の収集

Feature の要件定義書と設計書を検索・特定する agent を起動する。結果は `{session_dir}/refs/specs.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 仕様書調査
feature: "{feature}"
skill_type: "計画書作成"
```

### 1.2 計画書ルールの収集

プロジェクト固有の計画書フォーマット・タスク設計ルールを検索する agent を起動する。結果は `{session_dir}/refs/rules.yaml` に書き込まれる。

```yaml
session_dir: {session_dir}
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 実装ルール調査
feature: "{feature}"
skill_type: "計画書作成"
```

### 1.3 収集結果の確認

全 agent 完了後、`{session_dir}/refs/` 内のファイルを Read し表示する。5件以下は全件表示、6件以上は先頭3件+省略。

---

## Phase 2: 文書の読み込み [MANDATORY]

### 2.1 収集済み文書の読み込み

`{session_dir}/refs/` 内の全ファイルを Read する:

- **refs/specs.yaml** → 要件定義書・設計書を Read
- **refs/rules.yaml** → プロジェクト固有の計画書フォーマット・タスク設計ルールを把握（プラグイン文書より優先）

いずれかが存在しない場合（agent 失敗）→ 該当カテゴリなしで続行。
ただし **設計書が取得できない場合** → AskUserQuestion:
  - 設計書のパスを手動で指定する
  - 設計書なしで計画書作成を進める（リスクを理解した上で）

---

## Phase 3: 計画書の作成・更新 [MANDATORY]

### 3.1 更新モード: 既存作業の確認 [MANDATORY]

既存計画書がある場合（更新モード）、以下を必ず確認する:

1. **要件定義書への反映確認** — 変更内容が要件定義書に追記・修正されているか
2. **設計書への反映確認** — 設計変更を伴う場合、設計書に反映されているか
3. **未着手タスクの把握** — 既存計画書の未完了タスクを整理

上記に未反映がある場合は AskUserQuestion を使用して先に更新するか確認する。

### 3.2 設計書からタスクを抽出 [MANDATORY]

設計書のモジュール一覧・クラス図から実装対象を列挙し、タスクに分割する:

1. 各モジュールを「1 Agent 実行で完結する単位」に分割
2. 依存関係を整理（依存される側から先に実装）
3. 並列実行可能なタスクを識別（依存関係がないタスク群）

**タスクの粒度**:

| 基準   | 内容                                                   |
| ------ | ------------------------------------------------------ |
| 単位   | 1つのファイル、または密接に関連する2〜3つのファイル    |
| 量     | やるべき内容は5〜10項目程度                            |
| 完結性 | タスク完了時にビルド・テストが成功する規模 [MANDATORY] |

**タスクグループ化**: タスクを細かく分割すると途中でビルドが壊れることは普通に起きる。その場合は複数タスクをグループ化し、グループ完了時にビルドを確認する。

「タスクN完了時点でビルドが通るか？」→ No ならグループ化。グループは最大10タスクを目安とする。

### 3.3 計画書の作成・更新

**出力フォーマット [MANDATORY]**: `plan_format.md` の YAML スキーマに従って生成する。ファイル名: `{feature}_plan.yaml`

フォーマットの優先順位:

1. **プロジェクト固有ルール**: refs/rules.yaml に含まれるフォーマット定義
2. **プラグイン文書**: `${CLAUDE_PLUGIN_ROOT}/docs/plan_format.md`

**作成場所**: session.yaml の `output_dir`

**タスクID採番**: プロジェクトのフォーマットルールに従う。ルールがない場合は `TASK-001`, `TASK-002` 等の連番。

**優先度**: プロジェクトのフォーマットルールに従う。ルールがない場合は数値が大きいほど優先度が高い（例: 1〜99）。

**「やるべき内容」の記載原則** [MANDATORY]: 設計書を参照すればわかる実装詳細（プロパティ名、型、メソッドシグネチャ等）は計画書に書かない。設計書の該当セクションを特定できるレベルの記述にとどめること。計画書に実装詳細を転記すると設計書との二重管理になり、不整合の原因となる。

**依存関係マップ（作業メモ）**: タスク間の依存関係を整理するために作成してよいが、計画書本体には含めない。依存関係は各タスクの `depends_on` 配列に落とし込む。循環依存がないか確認すること。

### 3.4 完全性チェック [MANDATORY]

計画書作成後、以下を確認する:

- [ ] 要件トレーサビリティマトリクスが全要件を網羅しているか
- [ ] 設計トレーサビリティマトリクスが全設計書をカバーしているか
- [ ] 全設計書がタスクに反映されているか
- [ ] 依存関係に循環がないか
- [ ] 計画書がフォーマットに従っているか

---

## Phase 4: AIレビュー [MANDATORY]

計画書作成・更新後に `/forge:review plan` を `--auto` モードで実行する:

<!-- review は `review-XXXXXX` という別スキル名で独立したセッションを作成するため、start-plan のセッションとは干渉しない -->
```
/forge:review plan {作成した計画書のファイルパス} --auto
```

対象はこのワークフローで作成・変更したファイル（差分）のみ。
Skill が失敗した場合は Phase 3.4 のチェック項目を手動で確認し、人間にレビューを依頼する。

---

## 完了処理

### specs ToC 更新

`/doc-advisor:create-specs-index` が利用可能であれば実行する（利用不可の場合はスキップ）。

### commit/push 確認

`/anvil:commit` を実行して commit/push を確認する。

### セッション削除

セッションディレクトリを削除する:

```bash
rm -rf {session_dir}
```

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
計画書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:start-implement {feature}    # タスクの実行を開始
```
