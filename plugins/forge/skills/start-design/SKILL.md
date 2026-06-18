---
name: start-design
description: |
  要件定義書から設計書を作成する。コンテキスト収集→設計書執筆→レビュー+自動修正→commit を一貫実行。
  トリガー: "設計書作成", "設計開始", "start design"
user-invocable: true
argument-hint: "<feature> [--new|--add]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent, Skill, AskUserQuestion
---

# /forge:start-design

要件定義書から設計書を作成する。

## Goal

要件定義書をもとにコンテキスト収集・設計書執筆・レビュー+自動修正・commit・セッション削除・完了案内まで完走すること。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

---

## コマンド構文

```
/forge:start-design [feature] [--new|--add]
```

| 引数    | 内容                                       |
| ------- | ------------------------------------------ |
| feature | Feature 名（省略時は対話で確定）           |
| --new   | 新規アプリ・新規 feature（追加開発でない） |
| --add   | 既存アプリへの機能追加（追加開発）         |

---

## 事前準備 [MANDATORY]

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの要件定義書を設計するか）も出力先も決まらない。

**フィーチャー概念の把握 [MANDATORY]**: フラグ問わず以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

`.doc_structure.yaml` が定義する requirements ディレクトリ（`resolve_doc.py` が返すパス）を Glob して既存要件定義書の有無を確認し、以下の3分岐で確定する:

- **引数あり** → **変更せずそのまま使用**（AI による置き換え禁止）
- **引数なし・既存要件定義書が存在しない**（初回立ち上げ）→ フィーチャー名不要。`resolve_doc.py` が返すパスに直接配置する（`additive_development_spec.md` §0 参照）
- **引数なし・既存要件定義書が存在する** → AskUserQuestion で対象 Feature を確認する

### 新規/追加の確認 [MANDATORY]

設計書が新規アプリ向けか、既存アプリへの追加開発（additive）向けかを確定する。追加開発の設計書には frontmatter の付与が必須となるため、設計書執筆前に判定する。

- `--new` 指定 → 新規アプリ・新規 feature として処理
- `--add` 指定 → 既存アプリへの機能追加（追加開発）として処理
- 未指定 → 対応する追加 feature 要件定義書（`type: temporary-feature-requirement` frontmatter を持つ要件定義書）が入力に含まれるかで推定し、判断がつかなければ AskUserQuestion で確認する

**`--add`（追加開発）の場合 [MANDATORY]**: 以下を Read し、判定基準・矛盾時の優先度・merge 手順を把握したうえで後続 Phase に進む。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` — 追加開発ワークフロー仕様（§1 適用条件・対象外 / §6 frontmatter 定義一覧）
- `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md` の「追加 feature 用 frontmatter」節 — `type: temporary-feature-design` 定義

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

設計書の出力先ディレクトリを特定する。入力文書（要件定義書）は Phase 1 で agent が特定する。

- `doc-structure` スキルのスクリプトで Feature を検索:
  ```bash
  python3 "${CLAUDE_SKILL_DIR}/scripts/resolve_doc.py"
  ```
- 解決できない場合は AskUserQuestion で出力先を確認する

### モード判定 [MANDATORY]

出力先ディレクトリの設計書ファイルを Glob で確認し、モードを決定:

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 設計書が存在しない | **新規作成モード** → Phase 1 へ  |
| 設計書が存在する   | AskUserQuestion でユーザーに確認 |

既存設計書がある場合、AskUserQuestion を使用して確認する:

- 既存設計書に追記・修正する → Phase 1 へ
- 新たな設計書ファイルを追加作成する → Phase 1 へ
- レビューのみ行う → Skill ツールで `/forge:review design --files {既存設計書パス}` を起動して終了

### プラグイン文書の読み込み [MANDATORY]

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md`** — ID分類カタログ（設計IDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`** — 設計書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`** — 設計原則・作成ガイドライン
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md`** — 要件・設計の境界ガイド
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`** — 要件・設計で優先する価値観（構造品質の定量化禁止など）
- **`${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`** — 文書スタイル指針（タグ・見出し・参照記法）

---

## セッション管理 [MANDATORY]

### 自スキル残骸の検出

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py
```

- `status: "none"` → 「他スキル残骸の通告」へ
- `status: "found"` の場合、`sessions[]` を以下のルールで処理する:
  - **`status: "completed"`** → 正常完了したのに cleanup されなかった残骸として AskUserQuestion なしで自動回収する:
    ```bash
    python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {completed_session_path}
    ```
  - **`status: "in_progress"`** が残る場合 → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
    - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
    - **残す** → 残存ディレクトリを無視して新規セッション作成へ

### 他スキル残骸の通告

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py --all-skills
```

返却された `sessions[]` から自スキル分（既に処理済み）を除外し、`status: "completed"` は自動 cleanup する。残った `status: "in_progress"` が存在する場合は AskUserQuestion:「他スキルの残骸が N 件あります。今クリーンアップしますか？」

- **はい** → 各セッションを cleanup
- **いいえ** → そのまま新規セッション作成へ進む

### Phase 切替時の touch [MANDATORY]

各 Phase の開始時に session.yaml の `last_updated` を更新する。これにより `cleanup-stale` の時間基準が「最後に活動があった時刻」を正しく反映し、長時間タスクが誤削除されることを防ぐ。

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py touch {session_dir}
```

### セッション作成

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/init_session.py" "{feature}" "{new|update}" "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## Phase 1: コンテキスト収集 [MANDATORY]

以下の3つの収集を **Agent ツールで並列起動** する。
各 agent がエラー終了した場合は該当カテゴリなしで後続工程に進む。

### 1.1 要件定義書の収集

Feature の要件定義書を検索・特定する agent を起動する。結果は `{session_dir}/refs/specs.yaml` に書き込まれる。

```yaml
session_dir: { session_dir }
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 仕様書調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.2 設計ルールの収集

プロジェクト固有の設計ルール・ワークフローを検索する agent を起動する。結果は `{session_dir}/refs/rules.yaml` に書き込まれる。

```yaml
session_dir: { session_dir }
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 実装ルール調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.3 既存実装の収集

既存実装資産（再利用候補）を検索する agent を起動する。結果は `{session_dir}/refs/code.yaml` に書き込まれる。

```yaml
session_dir: { session_dir }
spec: ${CLAUDE_PLUGIN_ROOT}/docs/context_gathering_spec.md
tasks:
  - 既存コード調査
feature: "{feature}"
skill_type: "設計書作成"
```

### 1.4 収集結果の確認

全 agent 完了後、`{session_dir}/refs/` 内のファイルを Read し表示する。5件以下は全件表示、6件以上は先頭3件+省略。

---

## Phase 2: 要件定義書の分析 [MANDATORY]

### 2.1 収集済み文書の読み込み

`{session_dir}/refs/` 内の全ファイルを Read する:

- **refs/specs.yaml** → 要件定義書を Read
- **refs/rules.yaml** → プロジェクト固有の設計ルール・フォーマットを把握（プラグイン文書より優先）
- **refs/code.yaml** → 既存実装資産を確認（再利用可能性を判断）

いずれかが存在しない場合（agent 失敗）→ 該当カテゴリなしで続行。
ただし **要件定義書が取得できない場合** → AskUserQuestion:

- 要件定義書のパスを手動で指定する
- 要件定義書なしで設計を進める（リスクを理解した上で）

### 2.2 要件定義書の徹底確認

取得した要件定義書を Read して以下を確認する:

- 機能要件の完全性
- 非機能要件の明確性
- 制約条件と前提条件
- 用語定義と業務ルール

### 2.3 不明点の整理

要件に曖昧な点・矛盾がある場合は、質問リストを作成して AskUserQuestion を使用してユーザーに確認する。

仕様変更が発生した場合は、要件定義書を即座に更新すること（設計作業の前に不明点を解消すること）。

### 2.4 既存実装資産の確認

refs/code.yaml に記載された既存実装を確認し、再利用可能性を判断する。

存在する場合は必ず再利用（新規作成禁止）。再利用したコンポーネントは Phase 3 で設計書に明記すること。

---

## Phase 3: 設計書の作成 [MANDATORY]

### 3.1 設計書フォーマットの適用

フォーマットの優先順位:

1. **プロジェクト固有ルール**: refs/rules.yaml に含まれるフォーマット定義
2. **プラグイン文書**: `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`

設計書に必須記載する項目:

- **使用する既存コンポーネント**: 再利用する既存実装のファイルパス
- 再利用しない判断をした場合はその理由

### 3.2 設計ID体系の確認・採番 [MANDATORY]

プロジェクトのルールに従う（ルールがない場合は `DES-XXX` 形式を推奨）。

設計 ID を付与する際は、必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" DES
```

JSON 出力の `next_id` をファイル名・設計 ID として使用する。`duplicates` が空でない場合は警告を表示する。

**ADR（アーキテクチャ決定記録）を作成する場合 [MANDATORY]**: 設計判断の根拠を ADR として新規作成する際も、ADR の ID は手動で決定せず、必ず `next-spec-id` で採番する（プレフィックスは `ADR`）。手動採番は並行ブランチでの番号衝突（同一 `ADR-NNN` が別内容で重複）の原因になる。

```bash
python3 "$SCAN_SCRIPT" ADR
```

ADR は設計書と同じディレクトリに配置するため、`.doc_structure.yaml` に ADR 専用ディレクトリを定義しなくても既存 ADR が git スキャンで検出される（ID 体系は `${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md` の設計ID カタログを参照）。

### 3.3 設計書の作成

- **作成場所**: session.yaml の `output_dir`
- **フォーマット**: Markdown (.md) ファイル
- **追加開発（`--add`）の場合 [MANDATORY]**: `design_format.md`「追加 feature 用 frontmatter」が定義する `type: temporary-feature-design` frontmatter を文書先頭（`# {設計ID} ...` 見出しより前）に付与する。notes の正本は対応する追加 feature 要件定義書（REQ-xxx）を指す。新規アプリ（`--new`）・既存設計書の追記更新時は付与しない。
- **ユーザーレビューは AI レビュー（Phase 4）の後に実施する** — AI レビューで品質問題を修正してからユーザー確認を行う方が効率的

**禁止事項**:

- ❌ ソースコードの大量記載（説明用の小規模例は許容）
- ❌ 技術選択の理由を記載せずにフレームワークを指定
- ❌ 要件にない機能の追加
- ❌ レビュー未完了での次工程着手
- ❌ 設計IDの重複や欠番

**よくある失敗パターン（注意）**:

- 既存資産を1パターンの検索で諦め、重複実装してしまう → 複数キーワード・複数ツールで網羅的に検索
- プロジェクトの定数定義を無視して値をハードコードしてしまう → 定数定義・デザイントークンを必ず参照
- 同種の機能・画面の既存実装を確認せず独自設計してしまう → 既存の類似パターンを必ず確認
- 設計判断の根拠を記載しない → 技術選択の理由・代替案を設計書に文書化すること

---

## Phase 4: AIレビュー

作成した設計書に対して Skill ツールで `/forge:review` を `--auto` モードで実行する:

```
# Skill ツールで起動する
/forge:review design --files {作成ファイルパス} --auto
```

対象はこのワークフローで作成・変更したファイル（差分）のみ。

AI レビュー完了後、AskUserQuestion を使用して設計書のユーザーレビューを実施する。

---

## Phase 5: 品質保証

### 5.1 完全性チェック

設計書作成後、以下を確認する:

- [ ] 全要件が設計に反映されているか
- [ ] 設計IDが一意で適切に付与されているか
- [ ] 既存資産の活用が検討されているか
- [ ] 使用する既存コンポーネントが明記されているか

### 5.2 specs ToC 更新

設計書の作成・更新後、`/forge:update-db-specs` が利用可能であれば実行すること（利用不可の場合はスキップ）。

---

## 完了処理

### commit/push 確認

`/anvil:commit` を実行して commit/push を確認する。

### セッション削除

正常完了処理は **complete → cleanup の 2 段** で行う:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py complete {session_dir}
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {session_dir}
```

`complete` で `session.yaml` を `status: completed` に遷移させてから `cleanup` する。`cleanup` 直前にクラッシュしても、次回起動時または `cleanup-stale` が「完了済み残骸」として自動回収する。

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
設計書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:start-plan {feature}    # 計画書作成へ進む
```
