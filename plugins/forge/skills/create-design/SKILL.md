---
name: create-design
description: |
  設計書作成ワークフロー。要件定義書から設計書を作成、または既存設計書をレビュー。
  トリガー: "設計書作成", "設計開始", "start design", "/forge:create-design"
user-invocable: true
argument-hint: "<feature>"
allowed-tools: Bash, Read, Write, Glob, Grep, AskUserQuestion
---

# /forge:create-design

要件定義書から設計書を作成する。

## コマンド構文

```
/forge:create-design [feature]
```

| 引数    | 内容                             |
| ------- | -------------------------------- |
| feature | Feature 名（省略時は対話で確定） |

---

## 前提確認フェーズ [MANDATORY]

### Step 1: .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → `/forge:setup` 起動を促してエラー終了:
  ```
  Error: .doc_structure.yaml が見つかりません。
  /forge:setup を実行してから再試行してください。
  ```
- **存在する** → Step 2 へ

### Step 2: Feature 名の確定

対象 Feature: **$ARGUMENTS**

引数が指定されていない場合:

1. `specs/` ディレクトリ内の Feature 一覧を確認: `ls -d specs/*/`
2. AskUserQuestion を使用して対象 Feature を確認する

### Step 3: 出力先ディレクトリの解決

`.doc_structure.yaml` の `specs.design.paths` から出力先ディレクトリを取得する。

- 設定あり → そのパスを使用（Feature ごとにサブディレクトリがある場合は `{path}/{feature}/design/`）
- 設定なし → `specs/{feature}/design/` をデフォルトとして使用

### Step 4: モード判定 [MANDATORY]

出力先ディレクトリの設計書ファイルを Glob で確認し、モードを決定:

| 状況               | モード                           |
| ------------------ | -------------------------------- |
| 設計書が存在しない | **新規作成モード** → Phase 1 へ  |
| 設計書が存在する   | AskUserQuestion でユーザーに確認 |

既存設計書がある場合、AskUserQuestion を使用して確認する:

- 既存設計書に追記・修正する → Phase 1 へ
- 新たな設計書ファイルを追加作成する → Phase 1 へ
- `/forge:review design` でレビューのみ行う → 終了（review コマンドを案内）

### Step 5: プロジェクト固有情報の取得 [MANDATORY]

以下の defaults を**常に**読み込む（ベースライン）:

- **`${CLAUDE_PLUGIN_ROOT}/defaults/spec_format.md`** — ID分類カタログ（設計IDの体系を確認）
- **`${CLAUDE_PLUGIN_ROOT}/defaults/design_format.md`** — 設計書テンプレート
- **`${CLAUDE_PLUGIN_ROOT}/defaults/design_principles.md`** — 設計原則・作成ガイドライン
- **`${CLAUDE_PLUGIN_ROOT}/defaults/spec_design_boundary_guide.md`** — 要件・設計の境界ガイド

次に、`/query-rules` Skill が利用可能な場合、以下を実行してプロジェクト固有情報を追加取得する:

```
/query-rules 設計書を作成する
```

セマンティック検索により、ワークフロー指示・フォーマット定義・設計原則・アーキテクチャルール等、設計書作成に関連するすべての規則を取得する。取得した内容はベースラインを**上書き・補完**する形で適用する。

`/query-rules` が利用不可の場合は `.doc_structure.yaml` の `rules` パスから `**/design_format*` `**/design*` を Glob 探索して補完する。

**コンフリクト時の優先順位**: プロジェクト固有の指示が SKILL.md と異なる場合、**プロジェクト側を優先**する。ただし `[MANDATORY]` 付き項目は常に実行する。

---

## Phase 1: 要件定義書の分析 [MANDATORY]

### 1.1 要件定義書の取得

以下の優先順で対象 Feature の要件定義書を取得する:

1. **DocAdvisor**（`/query-specs` Skill が利用可能）→ 対象 Feature の要件定義書を取得
2. 利用不可 → `.doc_structure.yaml` の `specs.requirement.paths` から Feature に関連するドキュメントを Glob 探索

**要件定義書が見つからない場合**: AskUserQuestion を使用してユーザーに確認する:

- 要件定義書のパスを手動で指定する
- 要件定義書なしで設計を進める（リスクを理解した上で）

### 1.2 要件定義書の徹底確認

取得した要件定義書を Read して以下を確認する:

- 機能要件の完全性
- 非機能要件の明確性
- 制約条件と前提条件
- 用語定義と業務ルール

### 1.3 不明点の整理

要件に曖昧な点・矛盾がある場合は、質問リストを作成して AskUserQuestion を使用してユーザーに確認する。

仕様変更が発生した場合は、要件定義書を即座に更新すること（設計作業の前に不明点を解消すること）。

### 1.4 既存実装資産の確認 [MANDATORY]

設計書作成前に、類似実装が既に存在しないか確認する:

- 利用可能なコード解析ツール（Serena MCP 等）があればそれを使用
- なければ Grep/Glob でキーワード検索（1パターンで諦めず複数キーワードで確認）
- プロジェクトのアーキテクチャルール（Step 5 で取得）がある場合はそこに記載のディレクトリ・モジュール構成に従って確認範囲を判断する

存在する場合は必ず再利用（新規作成禁止）。再利用したコンポーネントは Phase 2 で設計書に明記すること。

---

## Phase 2: 設計書の作成 [MANDATORY]

### 2.1 設計書フォーマットの適用

Step 5 で取得したフォーマット定義に従って作成する（フォーマットは `${CLAUDE_PLUGIN_ROOT}/defaults/design_format.md` までフォールバック済み）。

設計書に必須記載する項目:

- **使用する既存コンポーネント**: 再利用する既存実装のファイルパス
- 再利用しない判断をした場合はその理由

### 2.2 設計ID体系の確認

プロジェクトのルールに従う（ルールがない場合は `DES-XXX` 形式を推奨）。

### 2.3 設計書の作成

- **作成場所**: `specs/{feature}/design/`
- **フォーマット**: Markdown (.md) ファイル
- **1ファイル完成ごとに人間のレビューが必須** [MANDATORY] — AskUserQuestion を使用してレビューの承認を確認する

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

## Phase 3: 品質保証

### 3.1 完全性チェック

設計書作成後、以下を確認する:

- [ ] 全要件が設計に反映されているか
- [ ] 設計IDが一意で適切に付与されているか
- [ ] 既存資産の活用が検討されているか
- [ ] 使用する既存コンポーネントが明記されているか

### 3.2 specs ToC 更新 [MANDATORY]

設計書の作成・更新後、必ず `/create-specs-toc` を実行すること。

---

## 完了後の案内

文書作成が完了したら、作成したファイルパスとともに次のステップを案内する:

```
設計書を作成しました:
  → {作成ファイルパス}

次のステップ:
  /forge:review design {作成ファイルパス} --auto     # レビュー+修正（推奨）
  /forge:review design {作成ファイルパス} --auto 3   # 3サイクル徹底修正
  /forge:review design {作成ファイルパス}            # 対話モードでレビュー
  /forge:create-plan {feature}                       # 計画書作成へ進む
```
