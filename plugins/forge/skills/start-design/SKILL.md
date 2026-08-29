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

要件定義書をもとにコンテキスト収集・設計書執筆・レビュー+自動修正・commit・完了案内まで完走すること。

## フロー継続

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

## 事前準備

### Feature の確定

対象 Feature を確定する。Feature が決まらないと、入力（どの要件定義書を設計するか）も出力先も決まらない。

**フィーチャー概念の把握**: フラグ問わず以下を Read し、フィーチャーとは何か・名前空間の原則を把握する。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §0 — フィーチャーの概念定義

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `design`（feature 未指定）で既存ファイルの有無を確認し、以下の3分岐で確定する:

- **引数あり** → **変更せずそのまま使用**（AI による置き換え禁止）
- **引数なし・既存ファイルが存在しない**（初回立ち上げ）→ フィーチャー名不要。同手順の対象ディレクトリに
  直接配置する（`additive_development_spec.md` §0 参照）
- **引数なし・既存ファイルが存在する** → AskUserQuestion で対象 Feature を確認する

### 新規/追加の確認

設計書が新規アプリ向けか、既存アプリへの追加開発（additive）向けかを確定する。追加開発の設計書には frontmatter の付与が必須となるため、設計書執筆前に判定する。

- `--new` 指定 → 新規アプリ・新規 feature として処理
- `--add` 指定 → 既存アプリへの機能追加（追加開発）として処理
- 未指定 → 対応する追加 feature 要件定義書（`feature_type: temporary-feature` frontmatter を持つ要件定義書）が入力に含まれるかで推定し、判断がつかなければ AskUserQuestion で確認する

**`--add`（追加開発）の場合**: 以下を Read し、判定基準・矛盾時の優先度・merge 手順を把握したうえで後続 Phase に進む。

- `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` — 追加開発ワークフロー仕様（§1 適用条件・対象外）
- `${CLAUDE_PLUGIN_ROOT}/docs/frontmatter_format.md` の §1.2 — `feature_type: temporary-feature` 定義

### 出力先の解決

設計書の出力先ディレクトリを特定する。入力文書（要件定義書）は Phase 1 で agent が特定する。

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/SKILL.md` の「出力先ディレクトリの解決」手順に従い、
doc_type `design`、feature `{feature}` で出力先ディレクトリを求める。

- `design` に対応するエントリが無い場合は AskUserQuestion で出力先を確認する

### モード判定

出力先ディレクトリの設計書ファイルを Glob で確認し、モードを決定:

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 設計書が存在しない | **新規作成モード** → Phase 1 へ  |
| 設計書が存在する   | AskUserQuestion でユーザーに確認 |

既存設計書がある場合、AskUserQuestion を使用して確認する:

- 既存設計書に追記・修正する → Phase 1 へ
- 新たな設計書ファイルを追加作成する → Phase 1 へ
- レビューのみ行う → Skill ツールで `/forge:review design --files {既存設計書パス}` を起動して終了

### プラグイン文書の読み込み

以下のプラグイン文書を**常に**読み込む:

- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md`** — ID分類カタログ（設計IDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`** — 設計書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`** — 設計原則・作成ガイドライン
- **`${CLAUDE_PLUGIN_ROOT}/docs/adr_principles_spec.md`** — ADR に何を書き何を書かないか（ADR を作成する場合）
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md`** — 要件・設計の境界ガイド
- **`${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`** — 要件・設計で優先する価値観（構造品質の定量化禁止など）
- **`${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`** — 文書スタイル指針（タグ・見出し・参照記法）

---

## Phase 1: コンテキスト収集

以下の 3 つを **Agent ツールで並列起動** し、各 agent の **return value** を main AI コンテキストに直接保持する。各 agent は markdown bullet list で返却し、エラー時は該当カテゴリなしで後続工程に進む。

### 1.1 要件定義書の収集

```
Agent ツール起動: 要件定義書収集
prompt:
  Feature "{feature}" に関連する要件定義書を検索する。

  `/forge:query-db-specs {feature}` を呼ぶ。

  各文書のタイトル行を Read で確認し、関連性を判断する。最大 10 件。
  return value として以下の markdown 形式で返す:

  ## 仕様書 (N 件)
  - `path/to/spec.md` — 関連理由を 1 行で
```

### 1.2 設計ルールの収集

```
Agent ツール起動: 設計ルール収集
prompt:
  Feature "{feature}" の設計書作成に適用するプロジェクト固有ルール・規約を検索する。

  `/forge:query-db-rules {feature} 設計` を呼ぶ。

  return value として以下の markdown 形式で返す:

  ## 設計ルール (N 件)
  - `path/to/rule.md` — 関連理由を 1 行で
```

### 1.3 既存実装の収集

```
Agent ツール起動: 既存実装収集
prompt:
  Feature "{feature}" に関連する既存実装資産 (再利用候補) を探索する。

  検索手順:
  - 機能名・コンポーネント名で `Grep` / `Glob: **/*{feature}*` を実行
  - 同一ディレクトリ・import 元・類似命名のファイルを分類

  return value として以下の markdown 形式で返す:

  ## 既存実装 (N 件)
  - `path/to/file.swift` — 関連理由 (再利用候補 / 参考実装 / テスト 等)
```

### 1.4 収集結果の確認

全 agent 完了後、3 つの return value をそのままユーザーに表示する。5 件以下は全件表示、6 件以上は先頭 3 件 + `... 他 N 件` で省略。

---

## Phase 2: 要件定義書の分析

### 2.1 収集済み文書の読み込み

Phase 1 の 3 agent の return value を起点に、必要なファイルを Read する:

- **仕様書 return value** → 要件定義書ファイルを Read
- **設計ルール return value** → プロジェクト固有の設計ルール・フォーマットを把握（プラグイン文書より優先）
- **既存実装 return value** → 再利用可能性を判断

該当 agent がエラー終了して return value を得られなかった場合 → 該当カテゴリなしで続行。
ただし **要件定義書 return value が空 (0 件) の場合** → AskUserQuestion:

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

Phase 1 の既存実装 return value に記載された既存実装を確認し、再利用可能性を判断する。

存在する場合は必ず再利用（新規作成禁止）。再利用したコンポーネントは Phase 3 で設計書に明記すること。

---

## Phase 3: 設計書の作成

### 3.1 設計書フォーマットの適用

フォーマットの優先順位:

1. **プロジェクト固有ルール**: Phase 1 の設計ルール return value に含まれるフォーマット定義
2. **プラグイン文書**: `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`

設計書に必須記載する項目:

- **使用する既存コンポーネント**: 再利用する既存実装のファイルパス
- 再利用しない判断をした場合はその理由

### 3.2 設計ID体系の確認・採番

プロジェクトのルールに従う（ルールがない場合は `DES-XXX` 形式を推奨）。

設計 ID を付与する際は、必ず以下のスクリプトで次の連番を取得する。手動での番号決定は禁止:

```bash
SCAN_SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/next-spec-id/scripts/scan_spec_ids.py"
python3 "$SCAN_SCRIPT" DES --share-prefixes ADR,DES
```

JSON 出力の `next_id` をファイル名・設計 ID として使用する。`duplicates` が空でない場合は警告を表示する（`duplicates` には「異なるファイルが同じ ID / 共有番号を主張している」実際の衝突のみが報告される。同一履歴由来の複数ブランチ出現はノイズとして除外済みのため、空でなければ必ずユーザーに提示する）。

**ADR（アーキテクチャ決定記録）を作成する場合**: 設計判断の根拠を ADR として新規作成する際も、ADR の ID は手動で決定せず、必ず `next-spec-id` で採番する（プレフィックスは `ADR`）。手動採番は並行ブランチでの番号衝突（同一 `ADR-NNN` が別内容で重複）の原因になる。ADR と DES は同一ディレクトリで通し番号を共有するため、必ず `--share-prefixes ADR,DES` を付与する:

```bash
python3 "$SCAN_SCRIPT" ADR --share-prefixes ADR,DES
```

ADR は設計書と同じディレクトリに配置するため、`.doc_structure.yaml` に ADR 専用ディレクトリを定義しなくても既存 ADR が git スキャンで検出される（ID 体系は `${CLAUDE_PLUGIN_ROOT}/docs/spec_format.md` の設計ID カタログを参照）。

### 3.3 設計書の作成

- **作成場所**: 事前準備「出力先の解決」で確定した出力先ディレクトリ
- **フォーマット**: Markdown (.md) ファイル
- **追加開発（`--add`）の場合**: `design_format.md`「追加 feature 用 frontmatter」が定義する `feature_type: temporary-feature` frontmatter を文書先頭（`# {設計ID} ...` 見出しより前）に付与する。feature_note の正本は対応する追加 feature 要件定義書（REQ-xxx）を指す。新規アプリ（`--new`）・既存設計書の追記更新時は付与しない。
- **ユーザーレビューは AI レビュー（Phase 4）の後に実施する** — AI レビューで品質問題を修正してからユーザー確認を行う方が効率的

**禁止事項・よくある失敗パターン**: `design_principles_spec.md`「記載してはいけない内容」「よくある失敗パターン」節に従う（事前準備で読み込み済み）。

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

commit/push の確認フローを担うスキル（例: `anvil:commit`）が available-skills にあれば呼び出す。無ければ `git add` → `git commit` の手順を案内する。

### 完了案内

作成したファイルパスとともに次のステップを案内する:

```
設計書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:start-plan {feature}    # 計画書作成へ進む
```
