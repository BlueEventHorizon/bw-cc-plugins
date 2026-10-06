# DES-010 create-* スキル オーケストレータ化設計書

## 1. 概要

start-design / start-plan / start-requirements の 3 スキルは、review スキルと同じオーケストレータパターンで構成する。共通のコンテキスト収集フレームワークを抽出し、各スキルの SKILL.md をオーケストレータとして配置する。

---

## 2. アーキテクチャ概要

### 2.1 オーケストレータ構造

```
┌──────────────────────────────────────┐
│ start-design (オーケストレータ)       │
│  ├ 事前準備（前提確認）                │
│  ├ 入力の収集 ──┬── 要件定義書の特定    │  ← 文脈から特定（agent を使わない）
│  │               └── rules agent        │  ← return value 収集
│  ├ 収集結果の統合・表示                │
│  ├ 文書作成（メインコンテキスト）         │
│  ├ /forge:review → AIレビュー         │
│  └ 完了処理                            │
└──────────────────────────────────────┘
```

### 2.2 責務分担

| 役割                   | 実行場所                                             | 責務                                                                                        |
| ---------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| オーケストレータ       | メインコンテキスト                                   | 前提確認、進行管理、ユーザー対話、判断分岐                                                  |
| コンテキスト収集 Agent | 汎用 Agent (general-purpose)                         | 仕様書・ルール・既存コードの探索 → return value（markdown リスト）で返却                    |
| 文書作成               | メインコンテキスト                                   | 収集結果を参照し、ユーザーと対話しながら文書を作成                                          |
| AIレビュー             | `/forge:review --files {差分ファイル} --auto` に委譲 | レビュー+自動修正（差分のみ対象）                                                           |
| 後処理                 | メインコンテキスト                                   | `/forge:update-db-specs` による ToC 更新、`/anvil:commit` による commit/push 確認、完了案内 |

> **設計判断**: 文書作成はメインコンテキストで実行する。理由: ユーザーとの対話（AskUserQuestion）が頻繁に発生し、Agent ツールで起動した隔離 context（汎用 Agent・カスタム Agent のいずれも）では対話ができないため。

---

## 3. 共通コンテキスト収集フレームワーク

### 3.1 概要

3 スキルに共通する「参考文書の収集」処理を標準化する。
review スキルの Phase 2 (Step 3~7) を汎用化し、create-* スキルでも同じパターンを使用する。

起動する agent の組み合わせはスキルごとに異なる（§4）。start-design は、要件定義書を置き場から決定論的に特定するため、agent で集めるのはプロジェクトのルールだけである。

### 3.2 収集結果の受け渡し（return value 契約）

create-* スキルは**セッションディレクトリを使用しない**（セッション機構は廃止済み）。各収集 agent は結果を **return value**（markdown bullet list）で返し、オーケストレータが main AI コンテキストに直接保持する（DES-022 並列 agent 出力契約）。

return value の形式（例）:

```
## 仕様書 (N 件)
- `specs/login/requirements/login_spec.md` — ログイン機能の要件定義書
```

### 3.3 コンテキスト収集 agent の指示方式

#### インライン prompt による自己完結性の確保（FNC-003 準拠）

各 agent への指示は、SKILL.md にインラインで記述した prompt テンプレートで渡す。テンプレートには以下を含め、agent は prompt だけで自己完結して動作する:

1. **検索目的**: Feature 名・作業種別を埋め込んだ目的文
2. **検索手段**: `/forge:query-db-specs` / `/forge:query-db-rules` の呼び出し、または `Grep` / `Glob` の探索手順
3. **出力契約**: return value の markdown 形式（見出し + bullet list、件数上限）

### 3.4 並列実行と統合

```mermaid
sequenceDiagram
    participant O as オーケストレータ
    participant S as specs agent
    participant R as rules agent
    participant C as code agent

    par コンテキスト収集（並列）
        O->>S: specs 収集を委譲
        S->>S: /forge:query-db-specs
        S-->>O: return value（仕様書リスト）
    and
        O->>R: rules 収集を委譲
        R->>R: /forge:query-db-rules
        R-->>O: return value（ルールリスト）
    and
        O->>C: code 探索を委譲
        C->>C: Grep/Glob で探索
        C-->>O: return value（既存実装リスト）
    end

    O->>O: 収集結果の統合・表示
    O->>O: 文書作成フェーズへ
```

### 3.5 並列収集の失敗時の扱いと表示

各 agent は独立して動作するため、1つの agent が失敗しても他の agent には影響しない。失敗時の扱い:

- **agent がエラー終了 / タイムアウト**: 該当カテゴリの収集結果なしで後続工程に進む。オーケストレータは統合表示でその旨を報告する（例: `**specs** — 収集失敗（スキップ）`）
- **agent が空結果を返す**: 正常扱いとして後続工程に進む

全 agent 完了後、オーケストレータは各 return value を Progress Reporting 規約（5 件以下は全件表示、6 件以上は先頭 3 件 + 省略）に従ってユーザーに表示する:

```
### ✅ コンテキスト収集完了

**specs (N件)**
- `specs/login/requirements/login_spec.md` — ログイン機能の要件定義書
- `specs/login/design/login_design.md` — 既存設計書

**rules (N件)**
- `rules/design_workflow.md` — 設計書作成ワークフロー

**code (N件)**
- `src/auth/LoginService.swift` — ログイン処理の既存実装
- ... 他 N件
```

---

## 4. スキル別設計

各スキルのフェーズ構成と、コンテキスト収集 agent の適用マトリクスを定義する。

### 4.1 start-design

フェーズ構成は [DES-018](DES-018_create_design_workflow_design.md) を正本とする。入力の収集は次のとおり。

#### 入力の収集

| 入力                 | 必須 | 取得方法                                                                                                        |
| -------------------- | ---- | --------------------------------------------------------------------------------------------------------------- |
| 要件定義書           | ○    | 会話の文脈から特定する（agent を使わない）。分からなければ利用者に尋ね、置き場に 1 件も無ければ案内して終了する |
| プロジェクトのルール | ○    | rules agent（汎用 Agent）が `/forge:query-db-rules` で検索し、return value で返す                               |

既存の実装は、ここでは集めない。上流の設計の後の照合（Phase 3）で、設計の観点から探す。

---

### 4.2 start-plan

#### フェーズ構成

```
事前準備 [MANDATORY]
├── Step 1: .doc_structure.yaml の確認
├── Step 2: Feature 名の確定
├── Step 3: 出力先の解決・モード判定（新規/更新）
└── Step 4: defaults 読み込み

Phase 1: コンテキスト収集 [MANDATORY]（汎用 Agent 並列・return value 収集）
├── 1.1: specs agent → 要件定義書・設計書リスト
├── 1.2: rules agent → 計画書ルールリスト
└── 1.3: 収集結果の確認・表示

Phase 2: 文書の読み込み [MANDATORY]
└── 収集済みの要件定義書・設計書を Read

Phase 3: 実装戦略の策定 [MANDATORY]

Phase 4: 計画書の作成・更新 [MANDATORY]
├── 更新モード: 既存作業の確認
├── 設計書からタスクを抽出 [MANDATORY]
├── 計画書の作成・更新
└── 完全性チェック [MANDATORY]

Phase 5: AIレビュー [MANDATORY]（FNC-006 準拠: --auto モード）
└── /forge:review --files {差分ファイル} --auto

完了処理
├── /forge:update-db-specs（利用可能な場合）
├── /anvil:commit
└── 完了案内
```

#### コンテキスト収集の適用マトリクス

| agent | 必須                                  | 収集内容                            |
| ----- | ------------------------------------- | ----------------------------------- |
| specs | ○                                     | 要件定義書 + 設計書（対象 Feature） |
| rules | △（/forge:query-db-rules 利用可能時） | 計画書フォーマット（あれば）        |
| code  | ✕                                     | 不要（計画書は実装を参照しない）    |

---

### 4.3 start-requirements

フェーズ構成は [DES-017](DES-017_create_requirements_workflow_design.md) を正本とする。コンテキスト収集は次のとおり。

#### コンテキスト収集 agent の適用マトリクス

| agent | interactive | reverse-engineering | from-figma | 収集内容                             |
| ----- | ----------- | ------------------- | ---------- | ------------------------------------ |
| rules | 使わない    | ○                   | 使わない   | 要件書フォーマット、ワークフロー指示 |
| code  | 使わない    | ○                   | 使わない   | ソースコード探索（要件抽出の起点）   |

agent を使わないモードと、reverse-engineering の agent 以外の収集は、オーケストレータが `/forge:query-db-rules` / `/forge:query-db-specs` を Skill ツールで直接呼んで、文書を特定する。interactive は事前一括収集を行わず、対話で必要になってから呼ぶ。既存の要件定義書・設計書の確認は、完全新規でないときだけ行う。

> **設計判断**: start-requirements の interactive モードではコンテキスト収集 agent を使わない。
> 要件定義は「何を実現するか」を定義する工程であり、既存実装への過度な依存は避ける（REQ-001 オーケストレータパターン要件の設計原則「What に集中」に準拠）。既存コードの確認は、関連する既存機能と影響範囲の特定に必要な範囲にとどめる。

#### reverse-engineering のコンテキスト収集シーケンス

```mermaid
sequenceDiagram
    participant O as オーケストレータ
    participant R as rules agent
    participant C as code agent

    Note over O: reverse-engineering モード
    par
        O->>R: rules 収集
        R-->>O: return value（ルールリスト）
    and
        O->>C: code 探索（ソースコード）
        C-->>O: return value（ソースコードリスト）
    end
```

---

## 5. 使用する既存コンポーネント

| コンポーネント                         | ファイルパス                                                  | 用途                                   |
| -------------------------------------- | ------------------------------------------------------------- | -------------------------------------- |
| コンテキスト収集タスク仕様             | `docs/specs/forge/design/DES-013_context_gathering_design.md` | タスク一覧・スキル別適用マトリクス     |
| query-db-specs / query-db-rules スキル | `plugins/forge/skills/query-db-{specs,rules}/SKILL.md`        | 収集 agent 内からの文書検索の委譲先    |
| Progress Reporting 規約                | review/SKILL.md 内                                            | 5件以下全件表示、6件以上は先頭3件+省略 |

---

## 6. セッション不使用の設計判断

create-* スキルは**セッションディレクトリを使用しない**。理由:

- フェーズ間の中間成果物を複数 worker で共有する必要がない（収集結果は return value で main AI コンテキストに保持し、成果物は出力先ディレクトリへ直接書き出す）
- 直線的ワークフローであり、中断時は最初からやり直す方が効率的（再開すべき中間状態を持たない）

セッション機構は廃止済みであり、いずれのスキルも使用しない。
