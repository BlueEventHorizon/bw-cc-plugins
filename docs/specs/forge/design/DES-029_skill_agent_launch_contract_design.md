# DES-029 SKILL / Agent 起動契約 設計書

## メタデータ

| 項目       | 値                                                                                                                                                                                                                         |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 設計 ID    | DES-029                                                                                                                                                                                                                    |
| 関連要件   | REQ-005_skill_agent_launch_contract (§11 で REQ-006 を fold 済)                                                                                                                                                            |
| 関連設計   | common:COMMON-DES-001_skill_base_design, forge:DES-015_review_workflow_design, forge:DES-028_review_policy_design, forge:DES-022_parallel_agent_output_contract_design, doc-advisor:ADR-002_query_skill_subagent_isolation |
| 関連ルール | `docs/rules/skill_launch_paths_definitions.md`, `docs/rules/skill_authoring_notes.md`                                                                                                                                      |
| 作成日     | 2026-05-24 (初版) / 2026-06-22 (Agent 起動契約への全面改訂)                                                                                                                                                                |
| 適用範囲   | `/forge:review` 配下の reviewer / evaluator / fixer / present-findings / review (orchestrator)                                                                                                                             |

> **本書は 2026-06-22 に REQ-006 / DES-032 (no-fork-skill feature) の内容を fold して全面改訂した**。初版 (0.1) は方針 B-2「fork 型 SKILL」を採択していたが、Claude Code の `context: fork` 機構に 9 件の構造的不具合 (本書 §5.0 / REQ-005 §11.1) が確認されたため、reviewer / evaluator / fixer を **カスタム Agent** (`plugins/forge/agents/<name>.md`) に再実装した。本書はその Agent 起動契約を正本とする。fork 型 SKILL に関する旧記述は §5 (Agent 採用根拠) / §11 改定履歴 に履歴として残す。

---

## 1. 概要

`/forge:review` 配下の 5 worker の起動契約を整理する。reviewer / evaluator / fixer を **カスタム Agent** (`plugins/forge/agents/<name>.md`) として実装し、Agent ツール (`subagent_type: "forge:<name>"`) で起動する。present-findings と review (orchestrator) は継承型 SKILL のまま残す。これにより REQ-005 §5 / REQ-005 §11.2 (FNC-N01〜N10) を具体化し、`context: fork` 機構の構造的不具合 (本書 §5.0 / REQ-005 §11.1 — Issue #18394 / #34164 / #60720 / #55592 等) を構造的に回避する。

### 1.1 採用したアプローチ

- **カスタム Agent 3 種** (reviewer / evaluator / fixer): `plugins/forge/agents/<name>.md` に system prompt + frontmatter を置く。tools allowlist (C 層) は frontmatter `tools:` で担保
- **継承型 SKILL 2 種** (review / present-findings): orchestrator は親 context を活用、present-findings はユーザー対話 (AskUserQuestion) を伴うため (AskUserQuestion は fork 境界・Agent 境界の両方で機能制限あり)
- **修正経路は 2 種に縮約**: 軽量経路 (orchestrator 直接 Edit) と Agent 経由 fixer 経路 (id 単位ループ起動)。旧経路 (汎用 Agent fixer / fork 型 fixer) はいずれも廃止
- **fixer 4 安全境界** (§3.5): 単一 finding 起動 / 編集対象 allowlist / 無関係 refactor 禁止 / 構文検証。Role 制約として system prompt に常時適用
- **COMMON-DES-001 §6 改訂**: fork 型 SKILL 一覧を「採用しない (廃止)」へ転換し、旧 SKILL ↔ 置換先 Agent の対応表を §6.2 に残す
- **静的検証**: `tests/common/test_no_fork_skill.py` (全 SKILL から `context: fork` 不在を検証) + `tests/forge/agents/test_agent_frontmatter.py` + `tests/forge/agents/test_fixer_safety_prompt.py`

### 1.2 採用しなかったアプローチ (代替案)

| 代替案                                 | 不採用の理由                                                                                                                                                                                                  |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 方針 A (汎用 Agent + SKILL.md Read)    | 起動経路が複数残り、軽量経路 (FNC-413) との分岐表が複雑化。Issue #32 の誤読を文書側 (静的テスト) で塞ぐ必要がある。reviewer / evaluator は 6 種別 × P1/P2/P3 の playbook が大きく、毎回 prompt 構成は非現実的 |
| 方針 B-1 (継承型 SKILL を Skill 呼び)  | 親 context を消費するため、fixer の「メインコンテキスト消費を抑える」設計原則 (DES-028) と直接衝突                                                                                                            |
| 方針 B-2 (fork 型 SKILL) — 旧 0.1 採択 | **棄却 (2026-06)**: `context: fork` に 9 件の構造的不具合 (本書 §5.0 / REQ-005 §11.1 — `$ARGUMENTS` 不達 / 出力消失 / 95%+ fork 効かず / 無限再帰 等) が公式に報告され、A 層 (fork 境界) 自体が信頼できない   |
| 方針 C (Bash subprocess 化)            | reviewer の Codex エンジン経由のみ既存。fixer / evaluator / present-findings に拡張する合理性なし                                                                                                             |
| 親実装 (orchestrator が継承型で内包)   | reviewer / evaluator まで親に取り込むと `review/SKILL.md` の責務が爆発し、§3.5 の「メインコンテキスト消費を抑える」原則と直接衝突                                                                             |
| present-findings の Agent 化           | ユーザー対話 (AskUserQuestion) と対話履歴の活用が必要。Agent 境界で親対話履歴が遮断されると UX 品質が劣化                                                                                                     |
| review (orchestrator) の Agent 化      | session_dir 全体・全 Phase の状態管理を担う中心。orchestrator は継承型が必須                                                                                                                                  |

カスタム Agent は doc-advisor の `doc-advisor:query-worker` / `doc-advisor:toc-updater` で安定稼働している実績がある。`subagent_type: "forge:<name>"` の Agent ツール起動は `$ARGUMENTS` 不達 / return 消失 / fork 効かずといった 本書 §5.0 / REQ-005 §11.1 の核心バグを構造的に回避する。

---

## 2. アーキテクチャ概要

### 2.1 起動経路の全体図

```mermaid
flowchart TB
    User([ユーザー]) -->|/forge:review| Review

    subgraph InheritedContext [親 context 継承]
        Review["review (継承型)<br/>orchestrator"]
        PresentFindings["present-findings (継承型)<br/>ユーザー対話"]
    end

    subgraph AgentBoundary [Agent 境界 - 親 context 遮断]
        Reviewer["agents/reviewer.md<br/>(read-only カスタム Agent)<br/>レビュー実行"]
        Evaluator["agents/evaluator.md<br/>(read-only カスタム Agent)<br/>判定エンジン"]
        Fixer["agents/fixer.md<br/>(write カスタム Agent + 安全境界)<br/>単一 finding 修正実行"]
    end

    subgraph BashSubprocess [Bash subprocess]
        Codex["Codex CLI<br/>(reviewer Codex エンジンのみ)"]
    end

    Review -->|"Agent ツール<br/>subagent_type: forge:reviewer<br/>prompt: session_dir / kind / engine"| Reviewer
    Reviewer -.->|"Bash 経由<br/>(エンジン=codex 時)"| Codex
    Review -->|"Agent ツール<br/>subagent_type: forge:evaluator"| Evaluator
    Review -->|"AskUserQuestion 必要時"| PresentFindings
    Review -->|"軽量経路: Edit 直接"| EditTool[Edit/Write]
    Review -->|"Agent ツール<br/>subagent_type: forge:fixer<br/>id 単位ループ起動"| Fixer
    PresentFindings -->|"Agent ツール<br/>subagent_type: forge:fixer"| Fixer
    Fixer -->|"allowed_files 内で Edit/Write"| EditTool

    style InheritedContext fill:#fff3cd,stroke:#ffc107
    style AgentBoundary fill:#d1ecf1,stroke:#0c5460
    style BashSubprocess fill:#e2e3e5,stroke:#6c757d
```

### 2.2 旧構成 (As-Is) vs 本設計 (To-Be) の対比

| 観点                               | 旧構成 (fork 型 SKILL 期 / 2026-05〜2026-06)              | 本設計 (To-Be / 2026-06 以降)                                                                                                                                                      |
| ---------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| reviewer の起動経路                | fork 型 SKILL を Skill ツールで呼ぶ                       | **カスタム Agent** を Agent ツールで起動 (`subagent_type: "forge:reviewer"`)                                                                                                       |
| evaluator の起動経路               | fork 型 SKILL を Skill ツールで呼ぶ                       | **カスタム Agent** を Agent ツールで起動 (`subagent_type: "forge:evaluator"`)                                                                                                      |
| fixer の起動経路                   | fork 型 SKILL が自身で Edit/Write を実行                  | **カスタム Agent** を Agent ツールで起動 (`subagent_type: "forge:fixer"`、id 単位ループ起動)。allowed_files allowlist + 単一 finding 起動 + 無関係 refactor 禁止 + 構文検証 (§3.5) |
| 修正経路の数 (FNC-413 含む)        | 2 種 (orchestrator 直接 Edit / fork 型 fixer)             | **2 種** (orchestrator 直接 Edit / Agent 経由 fixer)                                                                                                                               |
| 起動契約の自己完結性               | SKILL.md 単独で完結                                       | カスタム Agent system prompt (`agents/<name>.md`) で完結                                                                                                                           |
| `$ARGUMENTS` 不達 (#34164)         | リスク残存                                                | **構造的に解消** (Agent ツールは prompt 文字列を直接渡すため `$ARGUMENTS` 置換に依存しない)                                                                                        |
| 出力消失 (#60720)                  | リスク残存                                                | **構造的に解消** (Agent 完了通知は親 context に確実に届く)                                                                                                                         |
| fork 効かず (#18394)               | リスク残存 (95%+ で効かない)                              | **構造的に解消** (Agent ツールは独立 context を確実に起動)                                                                                                                         |
| Issue #32 (`subagent_type` 誤指定) | review 配下の fixer 経路は Skill ツール経由で構造的に解消 | **review 配下の全 worker 起動経路で構造的に解消**: `subagent_type: "forge:<name>"` は正規の Agent 識別子で誤指定の余地がない                                                       |
| present-findings の起動            | 継承型                                                    | 継承型 (変更なし)                                                                                                                                                                  |
| review (orchestrator) の起動       | 継承型                                                    | 継承型 (変更なし)                                                                                                                                                                  |

### 2.3 多重防御の適用 (COMMON-DES-001 §8)

reviewer / evaluator / fixer は ADR-002 / COMMON-DES-001 §8 の多重防御を適用する。旧 A 層 (fork 境界) は **Agent 境界** に置き換わる:

| 層            | 役割                       | 実現方法                                               | 本設計の対象 Agent                                                                            |
| ------------- | -------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| A. Agent 境界 | 親 context 漏洩の遮断      | Agent ツール起動 (`subagent_type: "forge:<name>"`)     | reviewer / evaluator / fixer                                                                  |
| B. Role 制約  | AI 行動規範で逸脱抑止      | system prompt (`agents/<name>.md` 本文) に否定形で明記 | reviewer / evaluator / fixer                                                                  |
| C. allowlist  | 承認なしで使えるツール指定 | frontmatter `tools:` を最小集合に絞る                  | reviewer (`Read, Write, Bash`) / evaluator (`Read, Bash`) / fixer (`Read, Edit, Write, Bash`) |
| D. 物理 deny  | 書き込み系ツールの強制禁止 | `.claude/settings.json` (将来課題)                     | プラットフォーム提供待ち (現状は対象外)                                                       |

---

## 3. モジュール設計

### 3.1 モジュール一覧

| モジュール       | 種別                                | 起動経路                                                                                          | 責務                                                                                                           | 親 context | 主要依存                                                                   |
| ---------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- | ---------- | -------------------------------------------------------------------------- |
| review           | 継承型 SKILL                        | (ユーザー直接起動 / 他 SKILL から呼出)                                                            | レビューワークフロー全体のオーケストレーション。各 Phase の状態管理・session_dir 管理                          | 継承       | reviewer / evaluator / fixer (Agent ツール) / present-findings (Skill)     |
| reviewer         | カスタム Agent (read-only)          | review から Agent ツール (`subagent_type: "forge:reviewer"`) で起動                               | review_packet を入力に target_files をレビューし、findings を `review_<種別>.md` に書き出す                    | **遮断**   | session_dir / refs.yaml / target_files / criteria_path / ssot_refs[]       |
| evaluator        | カスタム Agent (read-only)          | review から Agent ツール (`subagent_type: "forge:evaluator"`) で起動                              | `review_<種別>.md` の findings を吟味し、`apply_eval.py` 経由で plan.yaml を直接更新する                       | **遮断**   | session_dir / `review_<種別>.md` / plan.yaml / principles (重大度カタログ) |
| fixer            | カスタム Agent (write + 4 安全境界) | review / present-findings から Agent ツール (`subagent_type: "forge:fixer"`) で id 単位ループ起動 | 単一 finding を allowed_files allowlist 内に限定して Edit/Write で修正。無関係 refactor 禁止 + 構文検証 (§3.5) | **遮断**   | session_dir / plan.yaml / `review_<種別>.md` / refs.yaml / allowed_files   |
| present-findings | 継承型 SKILL                        | review から Skill ツール (継承) で呼出                                                            | findings を 1 件ずつ提示し、ユーザー判断を受けて plan.yaml を更新                                              | 継承       | session_dir / plan.yaml / `review_<種別>.md`                               |

### 3.2 種別・起動経路の選定根拠

| worker           | 種別選定                                 | 根拠 (COMMON-DES-001 §3.2 の判断基準 + 本書 §5.0 / REQ-005 §11.1)                                                                                                                                                                                                                         |
| ---------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| review           | 継承型 SKILL                             | orchestrator は session_dir 全体・全 Phase の状態を保持。Agent 化 / fork 化すると親が状態を保持できず再開不可                                                                                                                                                                             |
| reviewer         | カスタム Agent (read-only)               | (1) 隔離 context が必要 (review_packet と target_files の読み込みを親 context に持ち込まない) / (2) 6 種別 × P1/P2/P3 の複雑な playbook を `agents/reviewer.md` system prompt に固定し、複数経路から同じロールで呼ばれる / (3) tools allowlist で書き込み禁止 (C 層 Read/Write/Bash 限定) |
| evaluator        | カスタム Agent (read-only)               | (1) 5 観点精査の review playbook を独立 context で実行 / (2) `review_<種別>.md` と plan.yaml を session_dir から自力 Read。親 context 不要 / (3) tools allowlist で `Read, Bash` 限定 (Write は `apply_eval.py` (Bash) 経由で実施)                                                        |
| fixer            | カスタム Agent (write + 4 安全境界 §3.5) | (1) Issue #32 で `subagent_type` 誤指定の温床だった起動経路を `subagent_type: "forge:fixer"` の正規 Agent 識別子で構造的に解消 / (2) 「メインコンテキスト消費を抑える」設計原則と Agent 境界が整合 / (3) 4 安全境界 (§3.5) を system prompt の Role 制約として常時拘束                    |
| present-findings | 継承型 SKILL                             | AskUserQuestion による対話・対話履歴の活用が必要。Agent 境界 / fork 境界で親対話履歴が遮断されると UX 品質が劣化                                                                                                                                                                          |

> **fork 型 SKILL を採用しない根拠**: `context: fork` には 9 件の構造的不具合 (本書 §5.0 / REQ-005 §11.1) が確認されている。reviewer / evaluator / fixer が fork 型だと、`$ARGUMENTS` 不達 / 出力消失 / 95%+ fork 効かず / 無限再帰 等が発生しうる。カスタム Agent への移行でこれらは構造的に回避される。

### 3.3 クラス図 (種別関係)

```mermaid
classDiagram
    class Worker {
        +frontmatter
        +Role制約
        +tools allowlist
    }

    class 継承型SKILL {
        +context: 未指定
        +親context継承
        +Skillツールで起動
    }

    class カスタムAgent {
        +plugins/forge/agents/<name>.md
        +Agent境界(親context遮断)
        +Agentツールで起動 (subagent_type)
        +引数解釈ガード [MANDATORY]
        +Role否定的制約 [MANDATORY]
        +自己再帰禁止 [MANDATORY]
    }

    class review {
        +session管理
        +Phase 1-7
        +子worker起動
    }

    class present_findings {
        +AskUserQuestion
        +対話履歴活用
    }

    class reviewer {
        +review_packet入力
        +findings出力
        +tools: Read/Write/Bash
    }

    class evaluator {
        +plan.yaml直接更新(apply_eval.py経由)
        +tools: Read/Bash
    }

    class fixer {
        +単一finding起動 [MANDATORY]
        +allowed_files allowlist [MANDATORY]
        +無関係refactor禁止 [MANDATORY]
        +構文検証 [MANDATORY]
        +tools: Read/Edit/Write/Bash
    }

    Worker <|-- 継承型SKILL
    Worker <|-- カスタムAgent
    継承型SKILL <|-- review
    継承型SKILL <|-- present_findings
    カスタムAgent <|-- reviewer
    カスタムAgent <|-- evaluator
    カスタムAgent <|-- fixer
```

### 3.5 fixer の 4 安全境界 [MANDATORY]

fixer カスタム Agent は書き込み副作用を持つため、以下を `agents/fixer.md` の system prompt に Role 制約 (否定形) として明記する。`tests/forge/agents/test_fixer_safety_prompt.py` が prompt に各制約が含まれることを検証する。

#### 3.5.1 単一 finding 起動

fixer Agent は 1 起動につき 1 finding を修正する。

- orchestrator は `subagent_type: "forge:fixer"` の prompt に `finding_id` を 1 個だけ渡す
- 一括修正 (`--batch`) は orchestrator 側で `for id in fix_ids: spawn fixer(id)` のループに置き換える。fixer Agent 内では複数 ID を扱わない
- 軽量経路 (FNC-413) との分岐は §7 修正経路分岐表を参照

#### 3.5.2 編集対象パスの allowlist

orchestrator は fixer Agent 起動時の prompt に **編集を許可するファイルパスの集合** を明示的に列挙する。fixer Agent はこの allowlist 外への書き込みを Role 制約として禁止される。

- allowlist は finding の `target_file` / `files_modified` / target_files に限定する
- 設計書・テスト・README などへの波及修正が必要な場合は **fixer ではなく orchestrator** が判断し、軽量経路または別 finding として処理する
- allowlist 違反を検知した場合、fixer Agent は `status: "error"` を return し書き込みを中止する

#### 3.5.3 無関係 refactor の禁止

fixer Agent は「指摘の修正以外の変更を加えない」を Role 制約として持つ。

- 修正対象 finding の説明・修正案セクションに記載された変更のみを実施する
- 周辺コードの整形・命名変更・import 整理などは禁止 (別 finding として起票する)
- diff の行数増加が見出し情報量に対して過大な場合は警告を return する

#### 3.5.4 修正後の構文検証

fixer Agent は修正後、対象ファイルに対して言語別の構文検査を実行し、結果を return に含める。

- Python: `python3 -m py_compile <file>` 相当
- Markdown: `dprint check <file>` 相当
- YAML: `python3 -c "import yaml; yaml.safe_load(open('<file>'))"` 相当
- JSON: `python3 -c "import json; json.load(open('<file>'))"` 相当 (manifest 系)
- Bash: `bash -n <file>` 相当 (`plugins/*/scripts/*.sh` 等)
- TOML: `python3 -c "import tomllib; tomllib.load(open('<file>', 'rb'))"` 相当
- 構文エラー検知時は `status: "error"` を return し、修正前の内容を保持する (rollback)

##### pre-existing 違反のスキップ判定 [MANDATORY]

`dprint check` はファイル全体の format 違反を列挙するため、fixer の修正と無関係な pre-existing 違反 (修正前から存在していた format 違反) も検出する。これに毎回 rollback すると修正完了率が低下し、fixer に pre-existing 立証責任を負わせることになる。

そこで以下のベースライン取り込みフローを採用する:

1. **review SKILL の Phase 3 Step 5** で `plugins/forge/scripts/session/check_baseline_violations.py` を実行し、`refs.yaml` の `target_files` 各ファイルに対する `dprint check` の結果 (`has_violations: bool`) を `{session_dir}/baseline_violations.json` に保存する
2. **fixer Agent の Step 5** は `baseline_violations.json` を Read し、`dprint check` が失敗したファイルについて:
   - `has_violations: true` (pre-existing 違反あり) → `syntax_check[file]: "skipped: pre-existing dprint violations"` を記録し、**rollback しない**
   - `has_violations: false` (修正による新規違反) → 従来通り rollback
   - baseline 未登録 / `tool: null` (dprint 不在環境) → 従来通り rollback

この判定は `dprint check` (`.md`) にのみ適用する。他の言語の構文検証 (`py_compile` / `yaml.safe_load` 等) は「ファイル全体の文法エラー」を返す性質のため、pre-existing と新規の区別が無意味であり、従来通り rollback する。

### 3.6 worktree isolation の検討

fixer に worktree isolation (`git worktree add` で隔離してから Edit) を採用するかは検討対象だったが、本設計では **採用しない**。

- worktree 作成・破棄のオーバーヘッド (~200-500ms + ディスク容量) が、想定する修正粒度 (1 finding / 数行) に対して過大
- 軽量経路 (FNC-413) との UX 差が大きくなる (軽量は即 Edit、fixer 経路は worktree 作成待ち)
- 実害 (無関係ファイルへの書き込み事故) は §3.5 の Role 制約 + 構文検証で検知可能

将来 fixer に「複数 finding をまとめて修正」「設計書を跨ぐ大規模変更」を委譲する設計拡張が来たときに再評価する。

---

## 4. ユースケース設計

### 4.1 ユースケース一覧

| ID    | ユースケース                                                                          | アクタ                       | 起動経路                                                  |
| ----- | ------------------------------------------------------------------------------------- | ---------------------------- | --------------------------------------------------------- |
| UC-S1 | ユーザーが `/forge:review` 実行 → review が reviewer Agent を起動                     | ユーザー → review → reviewer | Agent ツール (`subagent_type: "forge:reviewer"`)          |
| UC-S2 | review が evaluator Agent を起動                                                      | review → evaluator           | Agent ツール (`subagent_type: "forge:evaluator"`)         |
| UC-S3 | review が軽量経路で 5 件以下の auto_fixable を直接 Edit で修正                        | review                       | (起動なし、orchestrator が Edit)                          |
| UC-S4 | review が fixer Agent を id 単位ループで起動して 6 件以上または非 auto_fixable を修正 | review → fixer               | Agent ツール (`subagent_type: "forge:fixer"`、ループ起動) |
| UC-S5 | review が present-findings を継承で呼出 (`--interactive` モード)                      | review → present-findings    | Skill ツール (継承)                                       |
| UC-S6 | present-findings が ユーザー対話後に fixer Agent を起動                               | present-findings → fixer     | Agent ツール (`subagent_type: "forge:fixer"`)             |
| UC-S7 | reviewer が Codex エンジン経由で Bash subprocess を起動                               | reviewer → Codex CLI         | Bash (reviewer Agent 内から)                              |

### 4.2 シーケンス図 — UC-S1 (reviewer 起動)

```mermaid
sequenceDiagram
    actor User
    participant Review as review<br/>(継承型 SKILL)
    participant FS as ファイルシステム<br/>(session_dir)
    participant Reviewer as agents/reviewer.md<br/>(カスタム Agent)
    participant Codex as Codex CLI<br/>(run_review_engine.sh)

    User->>Review: /forge:review code --auto
    Review->>FS: init_session → session_dir 作成
    Review->>FS: write_refs.py → refs.yaml 書込 (review_packet)
    Review->>Reviewer: Agent(subagent_type: "forge:reviewer", prompt: session_dir + kind=code + engine={codex|claude})
    Note over Review,Reviewer: engine を問わず Agent 起動は 1 回のみ<br/>(FNC-412)。orchestrator は run_review_engine.sh を直接起動しない
    Note over Reviewer: Agent 境界:<br/>親 context 遮断 (確実)
    Reviewer->>FS: Read refs.yaml (review_packet 取得)
    Reviewer->>FS: Read target_files / ssot_refs[]
    alt engine=codex
        Reviewer->>Codex: Bash subprocess: run_review_engine.sh
        alt Codex 不在 (exit code=2)
            Reviewer->>Reviewer: reviewer 内で Claude 実行へ fallback (2 体目は起動しない)
            Reviewer->>FS: Write review_code.md (findings)
        else Codex 実行成功 (exit 0)
            Codex->>FS: review_code.md 書込 (Markdown 抽出)
        end
    else engine=claude
        Reviewer->>Reviewer: P1→P2→P3 順次評価
        Reviewer->>FS: Write review_code.md (findings)
    end
    Reviewer-->>Review: return: {status: ok, output_filename}
    Note over Review: 親 context 復帰<br/>session.yaml の last_updated 更新
```

### 4.3 シーケンス図 — UC-S3 / UC-S4 (修正経路分岐)

```mermaid
sequenceDiagram
    participant Review as review<br/>(継承型 SKILL)
    participant FS as ファイルシステム
    participant Fixer as agents/fixer.md<br/>(カスタム Agent)

    Note over Review: **前提: 介入軸 = `--auto` または `--auto-critical`**<br/>(review orchestrator 直接経路。`--interactive` は §4.4 UC-S5 → UC-S6 参照)
    Review->>FS: Read plan.yaml
    Note over Review: 軽量経路判定 (FNC-413):<br/>recommendation=fix AND<br/>status ∈ {pending, in_progress}<br/>件数 N, auto_fixable

    alt N ≤ 5 AND 全 auto_fixable=true [軽量経路]
        loop 各 finding
            Review->>FS: mark_in_progress.py
            Review->>FS: Read review_<種別>.md (該当 finding 抜粋)
            Review->>FS: Edit 対象ファイル
        end
        Note over Review: mark_fixed.py は呼び出し元の責務<br/>（単独修正レビュー後に実行）
    else N ≥ 6 OR 非 auto_fixable あり [Agent 経由 fixer 経路]
        loop 各 finding (id 単位)
            Review->>FS: mark_in_progress.py {id}
            Review->>Fixer: Agent(subagent_type: "forge:fixer",<br/>prompt: session_dir + kind + id={id} + allowed_files=[...])
            Note over Fixer: Agent 境界 (確実遮断)<br/>+ 4 安全境界 (§3.5)
            Fixer->>FS: Read plan.yaml / refs.yaml /<br/>review_<種別>.md (該当 finding のみ)
            Fixer->>FS: Edit (allowed_files 内に限定)
            Fixer->>FS: 構文検証 (py_compile / dprint / yaml / json / bash / toml)
            Fixer-->>Review: return: {status, patched_ids, files_modified, syntax_check, allowlist_violations}
        end
        Note over Review: mark_fixed.py は呼び出し元の責務<br/>（単独修正レビュー後に実行）
    end
```

### 4.4 ユースケース別の入出力契約

| UC    | 入力 (Skill args)                                                                                                                           | 出力 (return + 副作用)                                                                                                                                                      | 失敗時の挙動                                                               |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| UC-S1 | `session_dir`, `kind` (code/design/requirement/plan/uxui/generic), `engine` (codex/claude)                                                  | return: `{status, output_filename}` / 副作用: `review_<種別>.md` 書込                                                                                                       | return に error 詳細。`review_<種別>.md` 不在で停止                        |
| UC-S2 | `session_dir`, `kind`                                                                                                                       | return: `{status, fix_count, skip_count, create_issue_count, needs_review_count, should_continue}` / 副作用: plan.yaml 直接更新 + `review_<種別>.md` 整形書換               | return に error 詳細。`review_<種別>.md` 不在で停止                        |
| UC-S3 | (起動なし、orchestrator が直接 Edit)                                                                                                        | plan.yaml を `in_progress` に更新 + ファイル修正。`fixed` 遷移は単独修正レビュー後に呼び出し元の責務で実行                                                                  | orchestrator が継続判定                                                    |
| UC-S4 | `session_dir`, `kind`, モードフラグ (`--single`)                                                                                            | return: `{status, patched_ids, failed_ids, files_modified, error_message}` / 副作用: ファイル修正 + plan.yaml を `in_progress` に更新。`fixed` 遷移は呼び出し元の責務       | return に error 詳細。修正済み項目は plan.yaml に `in_progress` で保存済み |
| UC-S5 | `session_dir` のみ。COMMON-DES-001 §4 [MANDATORY] により親タスクの指示文・差分・Issue 本文を args に貼り付けない (継承型でも呼び出し側責務) | plan.yaml 更新 (対話結果反映)                                                                                                                                               | AskUserQuestion キャンセル時はサマリ表示で終了                             |
| UC-S6 | `session_dir`, `kind`, `--single`                                                                                                           | UC-S4 と同じ                                                                                                                                                                | UC-S4 と同じ                                                               |
| UC-S7 | (reviewer 内部、Bash で `run_review_engine.sh` を起動)                                                                                      | スクリプトが中間ファイル経由で Markdown を抽出し `output_filename` に書き出す。reviewer は exit code とファイル存在を検証して return する（stdout 直接 capture は行わない） | reviewer がエラーを return                                                 |

---

## 5. Agent 採用根拠 (COMMON-DES-001 §3.2 適合)

本設計はカスタム Agent (`plugins/forge/agents/<name>.md`) を採用する。fork 型 SKILL は採用しない (§1 / COMMON-DES-001 §6 / 本書 §5.0 / REQ-005 §11.1)。worker ごとの Agent 採用根拠を以下に示す。

### 5.0 fork 型 SKILL を採用しない構造的根拠 (REQ-005 §11.1 と同根拠)

Claude Code の `context: fork` には以下の公式バグが報告されており、`/forge:review` 経路でも「何もせずに終了する」現象が複数回再現していた:

| 公式 Issue                                                       | 内容 (一行)                                                               | reviewer/evaluator/fixer への影響                              |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------- |
| [#18394](https://github.com/anthropics/claude-code/issues/18394) | `context: fork` が 95%+ の確率で効かず、既存 context でそのまま実行される | A 層 (fork 境界) が成立しない                                  |
| [#34164](https://github.com/anthropics/claude-code/issues/34164) | `$ARGUMENTS` 置換が効かず、リテラルが渡る                                 | session_dir / kind / engine 引数が届かず fallback 動作         |
| [#60720](https://github.com/anthropics/claude-code/issues/60720) | fork 型 SKILL の出力が UI に届かず無音終了                                | return 値が親に届かず、finding 件数が取得できない              |
| [#55592](https://github.com/anthropics/claude-code/issues/55592) | fork 型 SKILL が無限再帰し、102+ fork / 5 分で手動停止                    | 自己再帰禁止 (B 層) を文書化しても根本的回避は不可             |
| [#34328](https://github.com/anthropics/claude-code/issues/34328) | fork 型 SKILL を起動しても `subagent` が立たない (回帰)                   | 起動自体が失敗する                                             |
| [#19751](https://github.com/anthropics/claude-code/issues/19751) | fork 型 SKILL 内で AskUserQuestion が機能しない                           | reviewer/evaluator/fixer は AskUserQuestion 不使用だが将来制約 |
| [#17283](https://github.com/anthropics/claude-code/issues/17283) | Skill ツール経由起動で `context: fork` / `agent:` が honor されない       | frontmatter の `context: fork` 指定自体が無視されうる          |
| [#17351](https://github.com/anthropics/claude-code/issues/17351) | nested skill が呼び出し元 skill context に戻らず main context に戻る      | review orchestrator 復帰時の状態管理が破綻しうる               |
| [#68233](https://github.com/anthropics/claude-code/issues/68233) | Fork-Subagent recursion guard が false-positive (OPEN)                    | top-level からの fork dispatch が失敗する                      |

A 層 (fork 境界) 自体が信頼できないため、SKILL.md 側の Role 制約 (B 層) や allowed-tools (C 層) を強化しても全体の信頼性は担保できない。**Agent ツール起動 (Agent 境界)** はこれらの構造的バグを構造的に回避する。

### 5.1 reviewer (カスタム Agent)

| 判断基準 (COMMON-DES-001 §3.2)                    | 適合 (カスタム Agent 採用根拠)                                                                                                                                       |
| ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 親 context 漏洩による具体的な実害                 | reviewer/SKILL.md 文面の誤読リスクは Agent 境界で構造的に解消。Agent system prompt 単独で完結し、親 context の `/forge:fixer` 等の文字列が混入しない                 |
| 同じロールが複数の独立タスクから呼ばれる          | review (`--auto` / `--auto-critical` / `--interactive`) × 6 種別の組み合わせで呼ばれる。ロール固定が強い                                                             |
| 複雑な playbook を system prompt として固定したい | 6 種別 × P1/P2/P3 の playbook + engine 分岐 (codex/claude) は `agents/reviewer.md` system prompt に固定する。呼び出し元 prompt 全体で毎回構成する汎用 Agent は不適合 |

### 5.2 evaluator (カスタム Agent)

| 判断基準                                      | 適合                                                                                                              |
| --------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 親 context 漏洩による具体的な実害             | 5 観点精査の review playbook を独立 context で実行することで、親に「判定ロジック」を持ち込まない                  |
| 同じロールが複数の独立タスクから呼ばれる      | 種別ごとに 1 体起動                                                                                               |
| read-only ロールを system prompt で固定したい | tools allowlist で `Read, Bash` のみ (Edit/Write/MultiEdit/NotebookEdit を含めない) ことで C 層書き込み禁止を担保 |

### 5.3 fixer (カスタム Agent + 4 安全境界)

| 判断基準                                         | 適合                                                                                                                                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 親 context 漏洩による具体的な実害                | **Issue #32 の構造的解消**: `subagent_type` 誤指定温床だった起動経路を `subagent_type: "forge:fixer"` の正規 Agent 識別子で物理的に閉鎖。fork 型 fixer も誤指定リスクは解消するが §5.0 の構造バグが残る |
| 同じロールが複数の独立タスクから呼ばれる         | review `--auto` / present-findings 一括修正 / present-findings 単独修正 の 3 経路から呼ばれる                                                                                                           |
| 「メインコンテキスト消費を抑える」設計原則と整合 | **強く適合**: Agent 境界 で 1 finding 分の context を分離し、orchestrator は patch_result.json のみを Read する                                                                                         |
| 書き込み副作用に対する Role 制約が必要           | §3.5 の 4 安全境界 (単一 finding / allowed_files allowlist / 無関係 refactor 禁止 / 構文検証) を `agents/fixer.md` system prompt に Role 制約として常時拘束する                                         |

---

## 6. カスタム Agent の共通設計

reviewer / evaluator / fixer は ADR-002 §A〜C / COMMON-DES-001 §6 / §8 に従い、以下を `plugins/forge/agents/<name>.md` に含める。

### 6.1 frontmatter

カスタム Agent の frontmatter は **`name` / `description` / `tools` / `model`** を持つ (Claude Code Subagents 公式仕様)。`context: fork` / `agent:` は SKILL の frontmatter キーであり、Agent 定義には含めない。

**reviewer 用** (`Edit` なし。`review_<種別>.md` を `Write` で書き出す):

```yaml
---
name: forge:reviewer
description: |
  ...
tools: Read, Write, Bash
model: inherit
---
```

**evaluator 用** (`Write` なし。plan.yaml は `apply_eval.py` (Bash) 経由で更新する):

```yaml
---
name: forge:evaluator
description: |
  ...
tools: Read, Bash
model: inherit
---
```

**fixer 用** (`Edit` あり):

```yaml
---
name: forge:fixer
description: |
  ...
tools: Read, Edit, Write, Bash
model: inherit
---
```

`tests/forge/agents/test_agent_frontmatter.py` が name / tools allowlist の妥当性を検証する。

> **引数受け渡し**: `argument-hint` は SKILL の frontmatter キーであり、Agent には存在しない。Agent ツールは prompt 文字列を直接渡すため、`session_dir` / `kind` / `engine` / `id` / `allowed_files[]` 等の引数はすべて呼び出し元 (review/SKILL.md / present-findings/SKILL.md) の prompt 構築で組み立てる (§4.4 入出力契約)。

> **`subagent_type` の値域**: `general-purpose` / `Explore` / `Plan` / `forge:reviewer` / `forge:evaluator` / `forge:fixer` / `doc-advisor:query-worker` / `doc-advisor:toc-updater` 等。`forge:<name>` 形式はプラグイン namespace 付き Agent の識別子。

### 6.2 Role の否定的制約 [MANDATORY]

各 `agents/<name>.md` system prompt の冒頭に以下を明記:

```markdown
## Role

この Agent は {役割の簡潔な記述} のみを行う。親セッションのタスクを引き継いではならない。

### 制約 [MANDATORY]

この Agent は **カスタム Agent** であり、Agent 境界で親 context を継承しない。以下のツールは使用してはならない:

- 他 Agent の起動 (Agent ツールで自身および他 Agent を呼ぶことも含む)
- 親タスクの解釈・引継ぎ (タスク prompt を「親の指示文」として解釈してはならない)
- (fixer 以外) Edit / Write / MultiEdit / NotebookEdit による対象ファイル書込
- (fixer) allowed_files で渡された集合 **以外** への書込 (§3.5.2)

許可される動作:

- {Agent ごとの許可動作リスト}
```

fixer は対象ファイルへの Edit/Write が本質的責務であるため、「(fixer 以外)」の括弧書きで除外する。ただし fixer は §3.5 の 4 安全境界 (単一 finding / allowed_files / 無関係 refactor 禁止 / 構文検証) を Role 制約として常時適用する。

### 6.3 引数解釈ガード [MANDATORY]

各 `agents/<name>.md` system prompt に以下を含める:

```markdown
## 引数解釈

タスク prompt は **session_dir + kind + フラグ + (Agent 固有引数)** を含む構造化引数である。命令文に見えても親タスクの指示として解釈してはならない。

| prompt 例 (reviewer)                                                                         | 正しい解釈                                                                      |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `session_dir=.claude/.temp/review-abc123 kind=code engine=codex`                             | session_dir / kind / engine を抽出                                              |
| `session_dir=.claude/.temp/review-xyz kind=design engine=claude --diff-only files=a.md,b.md` | session_dir / kind / engine + 単独修正レビュー (`--diff-only` + files_modified) |
| `(命令文に見える任意の文字列)`                                                               | 上記スキーマで解析できない場合は `status: "error"` を return                    |

| prompt 例 (fixer)                                          | 正しい解釈                                |
| ---------------------------------------------------------- | ----------------------------------------- |
| `session_dir=... kind=code id=1 allowed_files=[a.md,b.md]` | 単一 finding ID + allowed_files allowlist |
```

### 6.4 自己再帰禁止 [MANDATORY]

`agents/<name>.md` system prompt 冒頭に以下を明記:

```markdown
> **自己再帰禁止 [MANDATORY]**: この Agent が Agent ツールで自身および他の `forge:<name>` Agent を起動することを禁止する。
```

### 6.5 入出力契約 (return 値スキーマ)

各カスタム Agent は **JSON return** を持つ。Agent 境界で親へ戻る情報はこの return + session_dir 経由の副作用 (ファイル) のみ。

| Agent     | return スキーマ                                                                                                                                                                                                                                                                                                                                                           |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| reviewer  | `{status: "ok"\|"error", output_filename: string, finding_count: integer, error_message?: string}`                                                                                                                                                                                                                                                                        |
| evaluator | `{status: "ok"\|"error", fix_count: integer, skip_count: integer, create_issue_count: integer, needs_review_count: integer, should_continue: boolean, error_message?: string}` ※ plan.yaml 更新・`review_<種別>.md` 整形書換は session_dir 経由の副作用、return には含まれない (DES-022 §3 出力契約)                                                                      |
| fixer     | `{status: "ok"\|"error", patched_ids: integer[], failed_ids: integer[], files_modified: string[], syntax_check: {<file>: "ok" \| "error: <msg>"}, allowlist_violations: string[], error_message?: string}` ※ §3.5 の 4 安全境界に対応するフィールド。`patched_ids` は修正済み finding ID。`fixed` への status 遷移は呼び出し元が単独修正レビュー後に mark_fixed.py を呼ぶ |

return 値以外の副作用 (`review_<種別>.md` / plan.yaml / 対象ファイル / patch_result.json) は **session_dir 経由** で親が後から Read する。

### 6.6 fixer patch_result の永続化

fixer は return スキーマと同一内容を `{session_dir}/patch_result.json` に書き込んでから return する。

```json
{
  "status": "ok",
  "patched_ids": [1, 2],
  "failed_ids": [],
  "files_modified": ["path/to/file.md"],
  "completed_at": "2026-05-26T12:34:56Z"
}
```

**用途**: セッション中断後の再開時に orchestrator が `patch_result.json` を確認し、`patched_ids` に対応する plan.yaml の status が `in_progress` のままであれば**単独修正レビューが未完了**と判断して単独修正レビューから再開できる。

**書き込みタイミング**: return 直前（成否を問わず書き込む。`status: "error"` の場合は `failed_ids` に判明した分を記録し `patched_ids` は空配列）。

**複数起動**: 同一セッション内で fixer が複数回起動される場合は後の起動結果で上書きする。直近の `patch_result.json` が単独修正レビューの判断基準となる。

---

## 7. 修正経路分岐表 (REQ-005 FNC-S007)

REQ-005 FNC-S007 に基づき、修正経路を **1 箇所の表** に整理する。本表は `forge:DES-015_review_workflow_design` に追記する候補。

> **前提**: 本表は **介入軸 `--auto` / `--auto-critical`** での review orchestrator 直接経路を扱う。`--interactive` モードでは present-findings から軽量経路または Agent 経由 fixer に分岐する (詳細は §4.4 UC-S5 / UC-S6)。

| # | 経路名                | 起動方法                                                         | context 消費    | 用途                                                 | 適用条件                                                                                           |
| - | --------------------- | ---------------------------------------------------------------- | --------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 1 | 軽量経路 (FNC-413)    | (起動なし、Edit 直接)                                            | 親 context 消費 | 件数小・auto_fixable な finding の自動修正           | `recommendation: fix` AND `status ∈ {pending, in_progress}` の件数 ≤ 5 AND 全 `auto_fixable: true` |
| 2 | Agent 経由 fixer 経路 | Agent ツール (`subagent_type: "forge:fixer"`、id 単位ループ起動) | 遮断            | 件数多 (≥ 6) または非 auto_fixable な finding の修正 | 軽量経路の条件を満たさない場合                                                                     |

旧経路 (汎用 Agent 起動による fixer / Skill ツール fork 型 fixer) は本設計で **廃止**。REQ-005 §1.1 の「経路 3 種混在」問題は経路 2 種に縮約される。fork 型 fixer は §5.0 の構造的不具合により採用しない。

---

## 8. 使用する既存コンポーネント

| コンポーネント             | ファイルパス                                                        | 用途                                                                                                                                      |
| -------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| review orchestrator SKILL  | `plugins/forge/skills/review/SKILL.md`                              | Phase 構成・session 管理・子 worker 起動。Agent ツール (`subagent_type: "forge:<name>"`) で reviewer/evaluator/fixer Agent を起動         |
| reviewer Agent             | `plugins/forge/agents/reviewer.md`                                  | レビュー実行カスタム Agent (read-only)。本設計の §6 共通設計 + §6.1 frontmatter を適用                                                    |
| evaluator Agent            | `plugins/forge/agents/evaluator.md`                                 | 判定エンジンカスタム Agent (read-only)。本設計の §6 共通設計を適用                                                                        |
| fixer Agent                | `plugins/forge/agents/fixer.md`                                     | 修正実行カスタム Agent (write + §3.5 の 4 安全境界)。allowed_files allowlist + 単一 finding 起動 + 無関係 refactor 禁止 + 構文検証        |
| present-findings SKILL     | `plugins/forge/skills/present-findings/SKILL.md`                    | ユーザー対話。継承型 SKILL のまま (AskUserQuestion を伴うため Agent 化不可)                                                               |
| write_refs.py              | `plugins/forge/scripts/session/write_refs.py`                       | refs.yaml 書込 (review_packet)。fork 境界で reviewer が自力 Read。本設計で変更なし                                                        |
| write_interpretation.py    | `plugins/forge/scripts/session/write_interpretation.py`             | `review_<種別>.md` 書換 (`--kind` 引数)。evaluator/fixer が自力で呼ぶ。本設計で変更なし                                                   |
| apply_eval.py              | `plugins/forge/scripts/session/apply_eval.py`                       | 検証・priority ソート・plan.yaml 直接更新を 1 ステップで完結。evaluator が自力で呼ぶ (Issue #103 / merge_evals.py + write_eval.py を統合) |
| mark_in_progress.py        | `plugins/forge/skills/present-findings/scripts/mark_in_progress.py` | plan.yaml の status を `in_progress` に更新。軽量経路・fixer 経路ともに修正開始時に呼ぶ。本設計で変更なし                                 |
| mark_fixed.py              | `plugins/forge/scripts/fixer/mark_fixed.py`                         | plan.yaml の status を `fixed` に更新。呼び出し元（review / present-findings）が単独修正レビュー後に呼ぶ責務。fixer Agent 自身は呼ばない  |
| カスタム Agent 雛形 (参照) | `plugins/doc-advisor/agents/query-worker.md`                        | カスタム Agent の frontmatter / system prompt 構造の参照実装 (外部実績)                                                                   |

---

## 9. テスト設計

REQ-005 §4 TEST-S001 〜 TEST-S005 を `tests/forge/` 配下に実装する。

### 9.1 テストモジュール一覧

| テスト ID | モジュール                                                    | 検査内容                                                                                                                                                                                                                                                                                                                                                                                                                        |
| --------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TEST-S001 | `tests/forge/subagent/test_agent_allowedtools_consistency.py` | SKILL.md 本文に `Agent ツール` / `汎用 Agent を起動` / `カスタム Agent を起動` の語があれば、`allowed-tools` に `Agent` が含まれること。**除外スコープ**: (1) fenced コードブロック (`` ``` `` で囲まれた範囲全体)、(2) `### 制約` / `### 禁止事項` 見出し配下のセクション全体（次の同レベル以上の見出しまで）。※ `## Role` 配下丸ごとは除外対象外（責務記述にも使われるため）                                                  |
| TEST-S002 | `tests/forge/subagent/test_skill_allowedtools_consistency.py` | SKILL.md 本文に `/forge:<skill>` / `/anvil:<skill>` の Skill 呼出記述があれば、`allowed-tools` に `Skill` が含まれること。**除外スコープ**: (1) fenced コードブロック (`` ``` `` で囲まれた範囲全体)、(2) `### 制約` / `### 禁止事項` 見出し配下のセクション全体（次の同レベル以上の見出しまで）。※ `## Role` 配下丸ごとは除外対象外（責務記述にも使われるため）                                                                |
| TEST-S003 | `tests/forge/subagent/test_legacy_perspective_removed.py`     | `review_{perspective}.md` 文字列が `plugins/forge/` / `docs/readme/forge/` 配下に存在しないこと (OBSOLETE マーカー付きは除外)                                                                                                                                                                                                                                                                                                   |
| TEST-S004 | `tests/forge/subagent/test_subagent_term_usage.py`            | SKILL.md 内で `subagent` が単独で使われている箇所を列挙 (warning)                                                                                                                                                                                                                                                                                                                                                               |
| TEST-S005 | `tests/forge/subagent/test_slash_command_launch_context.py`   | Agent prompt として展開されるテキストブロック内に `/forge:<skill>` / `/anvil:<skill>` 表記がある場合、**近傍 5 行内** (前後 5 行) に起動経路 (`汎用 Agent` / `継承型 SKILL` / `fork 型 SKILL` / `Bash subprocess`) の明示があること。**テキストブロック境界 = ``` で囲まれたコードブロックまたは段落区切り (空行 2 つ)**。**誤検知許容度: warning 段階 (CI を fail させない) を許容する場合は `[KNOWN-FP]` マーカー付きで除外** |

> ※ TEST-S005 (および対応する要件 FNC-S009) の静的検証の射程は **review 配下以外の prompt block** (他 SKILL.md / 設計書中の prompt block に残る `/forge:*` 表記)。review 配下は構造的解消 (§2.2 参照) で経路が物理的に消えるため対象外。

### 9.2 SKILL / Agent frontmatter 検証

| テスト                                           | 検証項目                                                                                                                | 対象                                    |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `tests/common/test_no_fork_skill.py`             | すべての `plugins/*/skills/*/SKILL.md` の frontmatter に `context: fork` が **含まれない** こと                         | bw-cc-plugins 配下の全 SKILL.md         |
| `tests/forge/agents/test_agent_frontmatter.py`   | `plugins/forge/agents/{reviewer,evaluator,fixer}.md` の frontmatter (`name` / `description` / `tools` / `model`) 妥当性 | reviewer / evaluator / fixer (各 Agent) |
| `tests/forge/agents/test_fixer_safety_prompt.py` | fixer.md system prompt に §3.5 の 4 安全境界 (単一 finding / allowlist / 無関係 refactor 禁止 / 構文検証) が含まれる    | fixer Agent                             |
| `agents/<name>.md` system prompt の Role 制約    | 本文に「親タスクを引き継がない」「Edit / Write 等の使用可否」「自己再帰禁止」                                           | reviewer / evaluator / fixer            |

### 9.3 単体テスト対象

- 既存スクリプト (write_refs.py / write_interpretation.py / apply_eval.py / mark_*.py) の動作は変更なし → 既存テストを温存
- fork 境界での引数パースが `argparse` で正しく解釈されること (各 SKILL の Python ヘルパーが新設される場合のみ)

### 9.4 統合テスト対象

- review orchestrator が fork 型 reviewer / evaluator / fixer を起動して `review_<種別>.md` / plan.yaml が期待通り生成・更新されることを E2E で確認 (手動レビュー)

---

## 10. COMMON-DES-001 §6 との対応

本設計改訂 (2026-06) に伴い、COMMON-DES-001 §6 は「fork 型 SKILL 一覧」から「fork 型 SKILL は採用しない (廃止)」へ転換された。§6.2 旧 fork 型 SKILL ↔ 置換先カスタム Agent 対応表 に reviewer / evaluator / fixer の置換履歴が記録されている。

| COMMON-DES-001 §6.2 旧 fork 型 SKILL      | 本設計の置換先 (カスタム Agent)     |
| ----------------------------------------- | ----------------------------------- |
| `plugins/forge/skills/reviewer/SKILL.md`  | `plugins/forge/agents/reviewer.md`  |
| `plugins/forge/skills/evaluator/SKILL.md` | `plugins/forge/agents/evaluator.md` |
| `plugins/forge/skills/fixer/SKILL.md`     | `plugins/forge/agents/fixer.md`     |

旧 SKILL.md ファイルは F-5 (本設計 §11 改定履歴 0.2 / TASK-016) で削除済み。

---

## 11. 移行計画 (履歴)

本設計の移行は 2 段階で実施された:

### 11.1 第 1 移行 (2026-05): fork 型 SKILL 化

REQ-005 §5 方針 B-2 に従い、reviewer / evaluator / fixer を継承型 SKILL から fork 型 SKILL に変更した。COMMON-DES-001 §6 リストに 3 SKILL を追加し、`context: fork` / `agent: general-purpose` / Role 否定的制約 / 引数解釈ガード / 自己再帰禁止を frontmatter / SKILL.md 本文に実装した。

### 11.2 第 2 移行 (2026-06): カスタム Agent への再実装

REQ-006 / DES-032 に従い、reviewer / evaluator / fixer を fork 型 SKILL からカスタム Agent (`plugins/forge/agents/<name>.md`) に再実装した。fork 機構の構造的不具合 (本書 §5.0 / REQ-005 §11.1) を回避することが目的。実施 step (各段階で `python3 -m unittest discover -s tests` が pass することを必須とする):

| #   | フィーチャー              | 範囲                                                                                                                                                                                    |
| --- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F-1 | feature/no-fork-skill-adr | REQ-006 + DES-032 作成 (ADR)                                                                                                                                                            |
| F-2 | feature/no-fork-reviewer  | reviewer Agent 化 (`plugins/forge/agents/reviewer.md` 新設) + `tests/common/test_no_fork_skill.py` + `tests/forge/agents/test_agent_frontmatter.py` 新設 + review/SKILL.md Phase 3 改訂 |
| F-3 | feature/no-fork-evaluator | evaluator Agent 化 + review/SKILL.md Phase 5 改訂                                                                                                                                       |
| F-4 | feature/no-fork-fixer     | fixer Agent 化 + §3.5 4 安全境界実装 + `tests/forge/agents/test_fixer_safety_prompt.py` 新設 + present-findings/SKILL.md Step 2-B 改訂 + 軽量経路との分岐表更新                         |
| F-5 | feature/no-fork-cleanup   | COMMON-DES-001 §6 / `docs/rules/skill_launch_paths_definitions.md` / `docs/rules/skill_authoring_notes.md` の最終クリーンアップ + 旧 fork 型 SKILL ファイル削除                         |

第 2 移行は単一ブランチ `feature/no-fork-reviewer` で F-2〜F-5 を実施し、最後に REQ-006 / DES-032 を本書および COMMON-DES-001 / DES-015 / DES-028 に fold した (本書 §11.3)。

### 11.3 各段階の E2E 確認

各段階で `/forge:review code --files <小さなファイル> --auto` または `--auto-critical` が手動で完走することを確認した:

| 段階 | E2E チェック                                                                               |
| ---- | ------------------------------------------------------------------------------------------ |
| F-2  | `/forge:review code --files ... --auto-critical` が完走し `review_code.md` が生成される    |
| F-3  | `/forge:review code --files ... --auto` が完走し plan.yaml の evaluator 判定が付与される   |
| F-4  | `/forge:review code --files ... --auto` が finding を 1 件以上自動修正し commit 候補が出る |
| F-5  | `python3 -m unittest discover -s tests` が全 pass                                          |

---

## 12. リスク・既知の制約

### 12.1 Agent 境界での AskUserQuestion

Claude Code の仕様としてカスタム Agent 内で AskUserQuestion が機能するかは明示されていない (関連: 公式 Issue #19751 は fork 型 SKILL での不具合報告)。reviewer / evaluator / fixer は AskUserQuestion を使わない設計のため影響しない。想定外の入力エラー時は **return で error を返し orchestrator に判断を委ねる** 方針とする。

### 12.2 同時並列での Agent 起動

DES-028 / FNC-412 「reviewer 1 起動原則」により reviewer の並列起動は禁止。evaluator / fixer も種別ごとに 1 起動 (fixer は finding 単位ループ起動だが並列ではない直列ループ)。本設計では並列 Agent 起動を許容しない。

### 12.3 Agent ツール側のバグへの感受性

Agent ツールも `subagent_type` の解釈不能や nested skill コンテキスト戻り問題 (例: Issue #17351) が存在しうる。本設計の前提:

- `subagent_type: "forge:<name>"` の動作は doc-advisor で `doc-advisor:query-worker` / `doc-advisor:toc-updater` が安定稼働している実績がある
- 万一 Agent 機構が信頼できなくなった場合は、本設計の前提を再評価する (Bash subprocess + 中間ファイル契約 への代替案を検討)

### 12.4 二重 Agent 起動のリスク

review (継承型 SKILL) → reviewer (カスタム Agent) → (内部で別 Agent 起動) は本設計で禁止 (§6.4 自己再帰禁止)。Agent からの自身/他 forge:* Agent 起動は構造的に閉鎖する。

---

## 改定履歴

| 日付       | バージョン | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-24 | 0.1        | 初版作成。REQ-005 §5 方針 B-2 (fork 型 SKILL) を具体化。reviewer / evaluator / fixer の 3 SKILL を fork 型化し、COMMON-DES-001 §6 リストに追加。修正経路を軽量経路 + fork 型 fixer の 2 種に縮約。引数解釈ガード・Role 否定的制約・自己再帰禁止を共通設計として規定。静的検証 5 種 (TEST-S001〜S005) と fork 型 frontmatter 検証を `tests/forge/` 配下に追加                                                                                                                                                   |
| 2026-06-22 | 0.2        | REQ-006 / DES-032 (no-fork-skill feature) を fold。fork 型 SKILL から カスタム Agent (`plugins/forge/agents/<name>.md`) への全面再実装を反映。§1 〜 §12 を全面改訂し、§5 を「Agent 採用根拠」に転換 (§5.0 公式バグ 9 件追加)、§3.5 fixer 4 安全境界を新設、§3.6 worktree isolation 不採用を明記、§6 frontmatter 例を Agent 用に書き換え、§7 修正経路分岐表の経路 2 を「Agent 経由 fixer 経路」に更新、§11 移行計画を「履歴」化 (第 1 移行 fork 型化 / 第 2 移行 Agent 化)、§12 リスクを Agent 境界前提で再整理 |
| 2026-05-25 | 0.2        | 設計書バグ修正: §6.1 frontmatter と §9.2 検証から `disable-model-invocation: true` を削除 (公式仕様で AI 呼出禁止フラグ。reviewer/evaluator/fixer は AI 経由で呼ばれる経路のため設定すると運用が破綻する)。修正により finding #3 (frontmatter と雛形の整合性) / #11 (検証と雛形の乖離) は解決。                                                                                                                                                                                                                |
