---
type: temporary-feature-design
notes:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、この文書は旧仕様書（DES-015 / DES-021 等）へ merge され削除される予定。
---

# DES-028 レビューポリシー設計書 (差分設計)

## メタデータ

| 項目     | 値                                                       |
| -------- | -------------------------------------------------------- |
| 設計 ID  | DES-028                                                  |
| プラグイン | forge                                                   |
| Feature  | forge-review (期間限定。完了後に既存仕様へ merge)        |
| 種別     | 差分設計 (既存 DES-015 / DES-021 への上書き)             |
| 関連要件 | REQ-004 レビューポリシー要件                             |
| 起点 Issue | #68 「AI reviwer がコトをどんどん複雑にする」          |
| 作成日   | 2026-05-19                                               |

---

## 1. 概要

本設計書は **差分設計書** である。レビューパイプラインの全体アーキテクチャ・並列契約・コンテキスト収集の枠組みは既存設計 (DES-013 / DES-015 / DES-021 / DES-022) を温存し、REQ-004 によって変化する部分のみを定義する。

ただし、差分だけを示すと「最終的にどこを目指しているか」が読者から見えなくなるため、§2 で **目指す姿 (To-Be)** を全体像として提示し、§3 以降で **そこに至るための差分** を「ポリシーファイル」「SKILL ファイル」の 2 点にフォーカスして記述する。

スコープを次の 2 点に限定する (差分の対象範囲):

1. **ポリシーファイルの差分** — `review_priorities_spec.md` (新設) と `review_criteria_*.md` (全面置換) を中心とする、レビュー判断基準を定義するファイル群の変更
2. **SKILL ファイルの修正箇所** — `/forge:review` / reviewer / evaluator / present-findings / fixer の SKILL.md と直配下スクリプトに対する、ポリシー変更に伴う修正点

CLI 文法・優先度体系の定義は REQ-004 §FNC-401〜410 を SoT として参照し、本設計では再掲しない (差分として上書きする内容のみ記す)。

### 1.1 既存設計との関係

| 既存設計                              | 本設計との関係                                                                                  |
| ------------------------------------- | ----------------------------------------------------------------------------------------------- |
| DES-013 コンテキスト収集設計          | **温存**。per-flow orchestrator の入力準備責務は本設計で再定義しない                              |
| DES-015 レビューワークフロー設計      | **部分上書き**。Phase 構成は維持。CLI 軸・perspective 構築・recommendation 値・findings 表記が差分 |
| DES-021 perspective 分割設計          | **部分上書き**。「criteria から `## Perspective:` 抽出」ロジックを「優先度宣言抽出」に差し替え   |
| DES-022 並列 agent 出力契約           | **温存**。3 原則 (個別書き込み / 完了通知のみ / オーケストレータ一括更新) はそのまま            |
| REQ-001 オーケストレータパターン要件  | **温存**。本設計はこの前提に従う                                                                |

### 1.2 差分の俯瞰

```
変化するもの:
  - ポリシーファイル群       → §3 ポリシーファイル差分
      review_priorities_spec.md (新設)
      review_criteria_*.md (全 6 ファイル、構造全面置換)
  - SKILL ファイル群         → §4 SKILL ファイル差分
      review / reviewer / evaluator / present-findings / fixer
  - 並行する補助スクリプト   → §4 内の各 SKILL に紐付けて記述

変化しないもの:
  - 並列 agent 出力契約 (DES-022)
  - per-flow orchestrator の入力準備責務 (DES-013 / 各 start-* SKILL)
  - session 管理パターン (DES-011 / DES-014)
  - 全体フェーズ構成 (DES-015 Phase 1〜5)
```

---

## 2. 目指す姿 (To-Be)

差分の出発点・到達点を一望できるよう、REQ-004 適用後の全体像をここに描く。詳細は §3 / §4 / 既存設計書 (DES-013 / DES-015 / DES-021 / DES-022) を参照。

### 2.1 全体構成 (To-Be)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ per-flow orchestrator (start-design / start-plan / start-implement / …)  │
│   役割: Feature 確定 / target_files 解決 / reference_docs 収集            │
│   → 解決済みファイル群を --files に展開して /forge:review を呼ぶ          │
│   (本設計の対象外。DES-013 / 各 start-* SKILL.md を温存)                  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ /forge:review (差分対象の中心オーケストレータ)                           │
│   Phase 1: 引数解析 (--diff / --files / --interactive / --auto[-critical])│
│   Phase 2: 入力解決 (--files 未指定時のみ .doc_structure.yaml 経路)       │
│   Phase 3: perspective 構築 (§2.3)                                       │
│             P1: 委譲ルール文書 × N 並列                                   │
│             P2: contradiction (種別共通) 1 並列                          │
│             P3: simplicity (種別共通) 1 並列                             │
│   Phase 4: reviewer / evaluator を perspective 単位で並列起動             │
│             (DES-022 並列契約を温存)                                      │
│   Phase 5: present-findings (段階的提示 + Issue 化選択肢) / --auto 系     │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ reviewer     │   │ evaluator    │   │ present-     │
   │ (P1/P2/P3    │   │ (perspective │   │ findings     │
   │  per-persp.) │   │  別精査)     │   │  → fixer or  │
   │              │   │              │   │    create-   │
   │              │   │              │   │    issue     │
   └──────────────┘   └──────────────┘   └──────────────┘
```

### 2.2 優先度 (priority) と severity の二軸

| 軸                  | 役割                       | 値                                  | 用途                  |
| ------------------- | -------------------------- | ----------------------------------- | --------------------- |
| **priority**        | 観点の出所 (何で検出したか) | `P1` / `P2` / `P3`                  | findings の分類軸     |
| **severity**        | 修正の緊急度               | `critical` / `major` / `minor` (🔴🟡🟢) | --auto 系の対象選定軸 |

両者は独立。例: P1 (ルール照合) で検出した違反が必ず critical とは限らない。

**severity デフォルトの SoT は principles 文書 (重大度カタログ、REQ-004 FNC-411)** であり、criteria 側は判断を持たない。criteria は重大度カタログを参照するだけ。これにより、執筆者が設計時点で「どの規範違反が 🔴 か」を完全に把握できる (REQ-004 §1「設計時点での情報完全性」)。

### 2.3 perspective の動的構築

固有 perspective を廃止し、perspective は次の規則で動的に構築する:

```
入力: 種別 (code/design/requirement/plan/uxui/generic)
出力: perspectives[] = [
        # P1: criteria の「委譲先 SSOT」表 × ルール文書数
        { perspective_name: "p1_<rule_doc_short_name>",
          priority: "P1",
          criteria_path: <criteria_md>,        # 焦点順 + 委譲原則 (運用のみ)
          rule_doc_path: <delegated_principles_or_rule>,  # 規範 + 重大度カタログ (判断の SoT)
          severity_source: "principles" },     # severity は principles 側を参照
        ...
        # P2: 種別共通の contradiction
        { perspective_name: "p2_contradiction",
          priority: "P2",
          criteria_path: <criteria_md>,
          rule_doc_path: <principles_with_consistency_rules>,
          severity_source: "principles" },
        # P3: 種別共通の simplicity
        { perspective_name: "p3_simplicity",
          priority: "P3",
          criteria_path: <criteria_md>,
          rule_doc_path: "${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md",
          severity_source: "principles" },
      ]
```

- 並列起動数の目安: DocAdvisor 追加分を含めても 8〜10 程度を上限ガイドラインとする
- P2 / P3 は種別非依存 (固有 perspective が無くなるため統一)
- **criteria は判断を持たない** (FNC-402)。reviewer / evaluator は重大度カタログ・グレーゾーン許容範囲を必ず `rule_doc_path` 側の principles から読み取る

### 2.4 CLI 構造 (To-Be)

```
/forge:review <種別> [--diff | --files a.md,b.md,...] [--interactive | --auto-critical | --auto [N]]
```

| 軸     | フラグ                                         | デフォルト (未指定時) | 役割                                                                  |
| ------ | ---------------------------------------------- | --------------------- | --------------------------------------------------------------------- |
| 対象軸 | `--diff` / `--files`                           | `--diff`              | 現ブランチ未 commit 差分 / 指定ファイル群全文                          |
| 介入軸 | `--interactive` / `--auto-critical` / `--auto` | `--interactive`       | 段階的提示 / 🔴 のみ自動修正 / **指摘件数 N 件** (severity 順) or 全件 |

省略形と明示形は等価。例: `/forge:review code` と `/forge:review code --diff --interactive` は同じ動作。

### 2.5 主要ユースケース (To-Be)

| ID    | 呼び出し                                                                  | 用途                                       |
| ----- | ------------------------------------------------------------------------- | ------------------------------------------ |
| UC-1  | `/forge:review <種別>` (≡ `--diff --interactive`)                         | 差分のみ × 段階的提示 (MVP デフォルト)      |
| UC-2  | `/forge:review <種別> --diff`                                             | UC-1 の明示形 (フラグを書く運用)            |
| UC-3  | `/forge:review <種別> --files a.md,b.md`                                  | 指定ファイル群を全文レビュー                |
| UC-4  | `/forge:review <種別> --auto-critical`                                    | 🔴 のみ自動修正 (対象は `--diff` デフォルト) |
| UC-5  | `/forge:review <種別> --files a.md --auto N`                              | 指定ファイルから **指摘件数 N 件** を severity 順で自動修正 |
| UC-6  | (per-flow orchestrator から) `/forge:review <種別> --files <展開済み>`    | フローからの自動呼び出し                    |
| UC-7  | present-findings で「Issue 化」を選択 → `/anvil:create-issue` 連携         | ルール抜け落ちを起票                       |

### 2.6 デフォルト挙動 (FNC-407)

```
/forge:review <種別>
  ≡ /forge:review <種別> --diff --interactive
  ≡ 対象=現ブランチ未 commit 差分 (TBD-401 解消)
    × 介入=段階的提示 (present-findings)
    × 検出=優先度 1〜3
```

引数なし呼び出しが「Issue #68 で求められた軽量レビュー」を最少コマンドで実現する。AI agent / 利用者が「省略時の挙動」を取り違えないよう、明示形 (`--diff --interactive`) も常にサポートする。

### 2.7 To-Be で廃止される概念

| 廃止対象                                       | 廃止理由                                                              |
| ---------------------------------------------- | --------------------------------------------------------------------- |
| 固有 perspective (logic / resilience / 等)     | ルール文書への委譲で代替 (FNC-402)                                    |
| criteria 側での重大度判定 (🔴/🟡/🟢 割り当て)  | 設計時点で執筆者から判断が隠れる。principles の重大度カタログに集約 (FNC-411) |
| criteria 側でのグレーゾーン判定 (false positive 警告) | 同上。principles の許容範囲明示化に集約 (FNC-411)                |
| scope 軸 (diff / file / crossref)              | `--files` フラグの有無で表現 (FNC-403)                                |
| depth 軸                                       | 優先度 1〜3 固定のため depth で段階増減する必要が無い (FNC-407)        |
| 行範囲指定 (`a.md:30-50`)                      | 行番号変動で意味が不安定 / 採用しない (FNC-410)                       |
| セクション限定指定 (`--section "4.1"`)         | 単一ファイル限定運用が複雑化する / 見出し構造変動で意味が不安定 (FNC-410) |
| `## Perspective:` セクション (全 criteria)     | 3 セクション固定構造 (委譲先 SSOT / 焦点順 / 委譲原則) に置換 (§3.3)  |

---

## 3. ポリシーファイル差分

ポリシーファイルとは「レビュー判断基準の単一の真実源 (SoT) を構成するファイル群」を指す。各ファイルの位置付け・改修種別・差分内容を記す。

### 3.1 ファイル一覧

| ファイル                                                              | 改修種別      | 役割                                                                                |
| --------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------- |
| `plugins/forge/docs/review_priorities_spec.md`                        | **新設**      | 優先度 1〜3 の SoT。全 criteria が MANDATORY 参照する基底ポリシー                    |
| `plugins/forge/docs/forge_anti_patterns.md`                           | **新設 (空ファイル)** | 業界標準アンチパターン集の雛形。配置のみ行い、初期内容は見出しのみ。各エントリは 2 行以内で AI が運用中に自動追記。内容拡充は別 Issue (TBD-405 解消方針) |
| `plugins/forge/docs/spec_priorities_spec.md`                          | **拡充**      | 各規範に重大度カタログを追加 (FNC-411)。§4 倒錯パターン等の判定許容範囲を明示化       |
| `plugins/forge/docs/spec_design_boundary_spec.md`                     | **拡充**      | §4 カテゴリ別ガイド / §6 グレーゾーンに重大度・許容範囲を追加 (FNC-411)             |
| `plugins/forge/docs/design_principles_spec.md`                        | **拡充**      | 「よくある失敗パターン」等の規範に重大度を付与 (FNC-411)                            |
| `plugins/forge/docs/plan_principles_spec.md`                          | **拡充**      | タスク粒度 / 必読列 / グループ化判定 等の規範に重大度を付与 (FNC-411)               |
| `plugins/forge/skills/review/docs/review_criteria_code.md`            | **全面置換**  | code の 3 セクション (委譲先 SSOT / 焦点順 / 委譲原則)。判断を持たない              |
| `plugins/forge/skills/review/docs/review_criteria_design.md`          | **全面置換**  | design の 3 セクション。判断を持たない                                              |
| `plugins/forge/skills/review/docs/review_criteria_requirement.md`     | **全面置換**  | requirement の 3 セクション (TBD-410: 網羅性は spec_priorities_spec 拡充で吸収)     |
| `plugins/forge/skills/review/docs/review_criteria_plan.md`            | **全面置換**  | plan の 3 セクション                                                                |
| `plugins/forge/skills/review/docs/review_criteria_uxui.md`            | **全面置換**  | uxui の 3 セクション (TBD-409: HIG/デザインシステム規約の整備状況に依存)            |
| `plugins/forge/skills/review/docs/review_criteria_generic.md`         | **全面置換**  | generic の 3 セクション (document_style_guide 委譲)                                  |

### 3.2 `review_priorities_spec.md` (新設) の構造

配置先: `plugins/forge/docs/review_priorities_spec.md` (TBD-404 解消済み・確定)

理由: `spec_priorities_spec.md` / `spec_design_boundary_spec.md` と並ぶ「forge 共通の判断基準 SoT」であり、`review/docs/` 配下に置くと criteria 個別ファイルと混同される。

固定セクション:

```markdown
# レビュー優先度仕様 [MANDATORY]

## 1. 優先度の定義
  優先度 1: ルール合致 (関連ルール文書との突合)
  優先度 2: 矛盾・齟齬 (同一対象への相反記述)
  優先度 3: 不要な複雑化 (Yes/No 判定原則)

## 2. 優先度と severity の関係
  - priority は「観点の出所」、severity は「修正緊急度」
  - 各 criteria が委譲ルールごとに severity デフォルトを宣言

## 3. 除外規定
  - 不足・欠落の検出は P2 の対象外
  - 「シンプルさ」「読みやすさ」等の主観評価は P3 の対象外 (Goodhart 罠回避)
  - 固有 perspective (logic / resilience / maintainability 等) の追加は原則禁止

## 4. ルール抜け落ち判定 (TBD-411 解消方針)
  指摘内容が以下のすべてを満たす場合のみ Issue 化対象とする:
    - 関連ルール文書のいずれにも該当規定が存在しない
    - 同種の指摘が今回・過去のレビューで複数回発生している (再発性)
    - 「ルールとして明文化可能な粒度」である (主観評価でない)

## 5. 各 criteria の構造 [MANDATORY]
  すべての review_criteria_*.md は §2.3 の固定セクション構造に従う
```

### 3.3 `review_criteria_*.md` の固定 3 セクション構造 (全面置換後)

criteria は **判断を一切持たない**。重大度判定・グレーゾーン判定はすべて principles 側 (重大度カタログ・許容範囲明示化、FNC-411) に存在し、criteria はそれを参照する索引・運用戦術のみで構成する。

```markdown
# {種別} レビュー基準

> SoT: ${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない (REQ-004 FNC-402)

## 1. 委譲先 SSOT

| 委譲先 (principles / format / rules / 仕様書) | 役割 (規範本体 + 重大度カタログ)               |
| --------------------------------------------- | --------------------------------------------- |
| `${CLAUDE_PLUGIN_ROOT}/docs/...`              | (規範) + 重大度カタログ (FNC-411 で拡充)       |
| ...                                           | ...                                           |

## 2. 焦点順

種別ごとに「どの principles 節から先に読むか」の順序。規範本体は再掲しない:

1. (最初に確認すべき節 — 例: 「principles §4 倒錯パターン」)
2. (次に確認すべき節)
3. ...

## 3. 委譲原則

| recommendation | 採用条件                                                                     |
| -------------- | ---------------------------------------------------------------------------- |
| `fix`          | 規範違反であり、修正による副作用が限定的な場合                                 |
| `create_issue` | ルール未整備で発見した場合 (review_priorities_spec §4 の 3 条件を満たす)       |
| `skip`         | false positive / グレーゾーン許容範囲内 (principles の許容範囲に該当)         |
```

削除セクション (廃止):

- `## Perspective: <name> — <display>` 形式の固有観点ブロック (全 criteria から削除)
- 重大度判定 (🔴/🟡/🟢 セクション分け / severity デフォルト表) — principles 重大度カタログに移管
- グレーゾーン判定 (false positive 警告) — principles 許容範囲明示化に移管
- 「保守性」「堅牢性」「アーキテクチャ整合性」等の品質特性をレビュー独自観点として記述する箇所

### 3.4 種別ごとの委譲先 SSOT (FNC-402 対応)

各 criteria が `## 1. 委譲先 SSOT` セクションに記載する委譲先文書を予め定義する。委譲先は **規範本体 + 重大度カタログ (FNC-411 拡充済み)** の両方を保持する単一の SoT である:

| criteria    | 委譲先 SSOT (規範 + 重大度カタログ)                                                                                              |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- |
| code        | `docs/rules/implementation_guidelines.md` / `docs/rules/cli_output_formatting.md` / 関連 DES / (FNC-411 拡充後) `plugins/forge/docs/forge_anti_patterns.md` |
| design      | `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` / プロジェクト固有アーキ規約 |
| requirement | `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` / `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` / `docs/rules/document_writing_rules.md` |
| plan        | `${CLAUDE_PLUGIN_ROOT}/docs/plan_format.md` / `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md` / 依存関係ルール                |
| uxui        | HIG / プロジェクト固有デザインシステム規約 (TBD-409 で整備状況確認)                                                              |
| generic     | `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md` / `docs/rules/document_writing_rules.md`                                     |

委譲先ルール文書が未整備の場合は **forge 内蔵ルールへフォールバック** (FNC-405)。プロジェクト固有 criteria が無い場合でも generic + 内蔵ルールで perspective が構築できる。

### 3.5 principles 拡充計画 (FNC-411 対応)

criteria から判断を完全に除去するため、principles 側を以下の方針で拡充する。各 principles ファイルは「規範 + 重大度カタログ + グレーゾーン許容範囲」を 1 ファイルに集約する。

#### 拡充対象と差分の方針

| principles 文書                                          | 重大度カタログの追加箇所                                                | グレーゾーン許容範囲の追加箇所                                 |
| -------------------------------------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------------------- |
| `plugins/forge/docs/spec_priorities_spec.md`             | §1 Yes/No判定 / §3 主目的禁止 / §4 倒錯パターン の各規範                 | §3.2 直接数値化禁止の許容範囲 (性能指標等は許容)               |
| `plugins/forge/docs/spec_design_boundary_spec.md`        | §4 カテゴリ別ガイド (データ/状態/処理/ビジネスルール/テスト/定量目標) の各項目 | §6 グレーゾーン (定量目標 / コアロジック等) を「許容 / 不許容」断定形に明示化 |
| `plugins/forge/docs/design_principles_spec.md`           | 「定量目標の扱い」「よくある失敗パターン」「記載すべき / してはいけない内容」 | (該当箇所が出てきたら追加)                                     |
| `plugins/forge/docs/plan_principles_spec.md`             | タスクの粒度 / 「やるべき内容」記載原則 / 「必読」列の仕様 / タスクグループ / 並列実行可能タスク | (該当箇所が出てきたら追加)                                     |

#### 重大度カタログの記載例

各 principles 文書末尾 (or 該当規範の直下) に以下のような表を追加する:

```markdown
## 重大度カタログ [MANDATORY]

| 規範                                | 違反時の重大度 | 理由                                                              |
| ----------------------------------- | -------------- | ----------------------------------------------------------------- |
| 直接数値化禁止 (§3.2)               | 🔴 critical    | 構造品質を数値化する Goodhart 罠は SDD 全体を破壊する             |
| 倒錯パターン: ストーリー先行 (§4.1) | 🔴 critical    | 実装の根拠が空想になる。後工程で矛盾が表面化する                 |
| ...                                 | ...            | ...                                                              |
```

#### グレーゾーン許容範囲の記載例

```markdown
## グレーゾーン許容範囲 [MANDATORY]

| 論点                              | 許容範囲                                                | 不許容                                          |
| --------------------------------- | ------------------------------------------------------- | ----------------------------------------------- |
| 数値化                            | 性能指標 / 可用性指標 / セキュリティ閾値 (機能的目標)   | 構造品質 (保守性スコア / 凝集度スコア等)        |
| 定量目標                          | 要件としての KPI / SLO                                   | 設計の評価軸として持ち込むこと                  |
```

#### 入力資料 (Issue #74 由来 18 項目)

詳細は **Appendix A**: 各項目を以下に分類して取り込む:

- **(a) 既存 principles の規範に重大度を追加するだけで吸収**: 多くの項目はここに該当
- **(b) 既存 principles のグレーゾーン許容範囲として明示化**: false positive 警告由来の項目
- **(c) 新規の principles 規範 / 新規 rule 文書が必要**: 該当があれば

### 3.6 ポリシー差分のまとめ

| 観点                              | Before                                                  | After                                                                                |
| --------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 単一真実源 (SoT)                  | なし (各 criteria が独立に観点を定義)                    | `review_priorities_spec.md` を新設し全 criteria が参照。判断は principles 側に集約    |
| criteria のセクション構造         | `## Perspective:` ブロック × N + 補足                    | 3 セクション固定 (委譲先 SSOT / 焦点順 / 委譲原則)                                   |
| 観点の出所                        | criteria 固有                                           | ルール文書 (P1) + 種別非依存の contradiction (P2) / simplicity (P3)                  |
| severity デフォルト               | criteria 全体で一律 or 不明 (執筆者に非開示)             | principles 側の重大度カタログ (FNC-411 拡充)。執筆者も設計時点で参照可能              |
| グレーゾーン判定                  | criteria 側の false positive 警告 (執筆者に非開示)       | principles 側の許容範囲明示化 (FNC-411 拡充)。執筆者も設計時点で参照可能              |
| 設計時点での情報完全性            | 一部判断が criteria に閉じ込められていた                  | レビュー判断はすべて principles に存在し、執筆者が事前に参照可能                       |
| Issue 化判定                      | 暗黙 (個別の評価者判断)                                  | `review_priorities_spec.md §4` で 3 条件を明文化                                     |

---

## 4. SKILL ファイル差分

SKILL ファイルごとに「修正セクション」と「修正内容」を記す。Phase 構成や全体フローは DES-015 に従い、本設計では差分のみを示す。

### 4.1 `plugins/forge/skills/review/SKILL.md`

| 修正セクション           | 修正内容                                                                                                                                |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Phase 1 引数解析         | 受理する引数を REQ-004 FNC-410 の最小集合に揃える: `<種別>` / `--diff` / `--files` / `--interactive` / `--auto-critical` / `--auto [N]`     |
| Phase 1 デフォルト解決   | 対象軸が未指定なら `--diff`、介入軸が未指定なら `--interactive` として扱う (省略形と明示形を正規化して同一の内部状態に揃える)              |
| Phase 1 入力検証         | early validation を追加 (FNC-410): ① `--diff --files ...` (対象軸の二重指定) / ② 介入軸の二重指定 (`--interactive --auto-critical` / `--auto --auto-critical` 等) / ③ 未知フラグ (`--section` / `--scope` / `--depth` 等) は明示的に拒否してメッセージで「DROP 済み」と案内 |
| Phase 2 入力解決         | `--files` 明示時はパス解決をバイパス。`--diff` (明示 or デフォルト) 時は `.doc_structure.yaml` 経路で差分のみを対象に解決 (比較基準=現ブランチ未 commit 差分) |
| Phase 2 perspective 構築 | 「criteria 配下 `## Perspective:` 抽出」ロジック (DES-021) を廃止。代わりに `## 優先度 1: 委譲ルール文書` 表を読み、P1 × N + P2 + P3 を動的構築 |
| Phase 4 reviewer 起動    | perspective 引数の意味を変更 (固有 perspective 名 → `p1_<rule_short>` / `p2_contradiction` / `p3_simplicity` のいずれか)                |
| Phase 5 介入             | 介入軸フラグ (`--interactive` / `--auto-critical` / `--auto [N]`) で分岐。`--interactive` (=未指定時のデフォルト) は present-findings、それ以外は severity フィルタ付き fixer。severity フィルタは priority と独立に動作 |
| Phase 5 終了確認         | findings サマリを **優先度別** (P1/P2/P3) と **severity 別** (🔴/🟡/🟢) の両方で表示                                                  |
| 不採用案内               | `--scope` / `--depth` フラグの記述を全削除 (DES-015 に残っていた場合)                                                                  |

#### 関連スクリプト

| スクリプト                                                              | 修正内容                                                                                |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `skills/review/scripts/resolve_review_context.py`                       | `--files` 明示時のバイパス経路を追加。比較基準デフォルト (現ブランチ未 commit 差分) 実装 |
| `skills/review/scripts/init_session.py`                                 | `--files` を session.yaml メタとして保存 (`--section` は廃止のため保存しない)            |
| `skills/review/scripts/find_session.py`                                 | 変更なし                                                                                |
| `skills/review/scripts/skip_all_unprocessed.py`                         | 変更なし                                                                                |
| `skills/review/scripts/run_review_engine.sh`                            | 変更なし                                                                                |

### 4.2 `plugins/forge/skills/reviewer/SKILL.md`

| 修正セクション         | 修正内容                                                                                                              |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 入力契約               | `perspective_name` の値域を `p1_<rule_short>` / `p2_contradiction` / `p3_simplicity` に限定                            |
| P1 reviewer 動作       | criteria_path (索引のみ) + 委譲先 SSOT (rule_doc_path = principles / format / rules) + target_files を Read。**重大度判定・グレーゾーン許容範囲は SSOT 側の重大度カタログから取得し、criteria の判断は参照しない** |
| P2 reviewer 動作       | criteria_path + target_files を Read し、対象内部の相反記述を検出 (網羅性確認は対象外)。重大度は principles から取得     |
| P3 reviewer 動作       | criteria_path + target_files を Read し、Yes/No 判定原則 (review_priorities_spec §3 / spec_priorities_spec §1) で複雑化を検出。重大度は spec_priorities_spec の重大度カタログから取得 |
| severity 取得経路      | criteria は判断を持たないため、重大度は必ず委譲先 principles の重大度カタログ (FNC-411) から取得すること                |
| --diff-only 経路       | 変更なし (target_files が差分ファイル群で渡る既存挙動を維持)                                                            |
| 出力 (findings 記法)    | severity ラベルは `[critical]` / `[major]` / `[minor]` の ASCII に統一。各 finding に `priority: P1\|P2\|P3` フィールドと `severity_source: <principles ファイルパス>` を追加 |

#### 関連テンプレート

| ファイル                                              | 修正内容                                                                                |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `skills/reviewer/templates/review.md`                 | 重大度セクション見出し (🔴/🟡/🟢) は表示用に温存。各 finding に `priority` 行を追加     |

### 4.3 `plugins/forge/skills/evaluator/SKILL.md`

| 修正セクション             | 修正内容                                                                                                                          |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| recommendation 値域        | `fix` / `skip` の 2 値から `fix` / `skip` / `create_issue` の 3 値に拡張                                                          |
| `create_issue` 判定基準    | `review_priorities_spec §4` の 3 条件 (該当規定なし / 再発性 / 明文化可能粒度) を満たすときに付与                                  |
| --auto / --auto-critical 連携 | severity フィルタを priority と独立に評価。`--auto-critical` 対象 = severity=critical のみ (priority 不問)                       |
| 要件レビュー固有判定       | TBD-xxx 委譲判定 (REQ-004 TBD-410 解消後) を `review_priorities_spec` と `spec_priorities_spec` から取得                          |
| review_*.md 整形           | テンプレ見出しに `priority` セクションを追加。skip_reason カタログは温存                                                            |

#### 関連スクリプト

| スクリプト                                                  | 修正内容                                                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `scripts/session/write_interpretation.py`                   | 変更なし (冪等な全面書き換え + `.raw.md` バックアップは温存)                          |
| `scripts/session/merge_evals.py`                            | `recommendation: create_issue` 行を `should_continue` 計算から除外                    |

### 4.4 `plugins/forge/skills/present-findings/SKILL.md`

| 修正セクション         | 修正内容                                                                                                                                                       |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 提示順序               | severity 順 (🔴 → 🟡 → 🟢) を温存。各セクション内では priority 順 (P1 → P2 → P3) でソート                                                                       |
| AskUserQuestion 選択肢 | 現在の「修正する / スキップする」に **「Issue 化する」** を追加。選択時は `recommendation` を `create_issue` に更新                                            |
| Issue 化フロー         | 選択時に `/anvil:create-issue [issue-title]` を呼び出す。指摘内容 (現象 / 期待 / 再現) と「追加すべきルールの草案」を初期値として渡す                          |
| AI 推奨判定の表示       | evaluator の recommendation 値 (fix / skip / create_issue) をラベル付きで表示                                                                                 |
| batch_update           | 既存の mark_in_progress / mark_skipped に加え、`create_issue` 状態への遷移を batch_update 経由で実行                                                           |

#### 関連スクリプト

| スクリプト                                                              | 修正内容                                                                                |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `skills/present-findings/scripts/mark_in_progress.py`                   | 変更なし (`in_progress` / `needs_review` / `skipped` の既存遷移を温存)                  |
| 同上 (新規追加が必要な場合)                                              | `create_issue` 状態遷移ヘルパを既存 batch_update の値域拡張で吸収 (新ファイル不要)      |

### 4.5 `plugins/forge/skills/fixer/SKILL.md`

| 修正セクション   | 修正内容                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------- |
| フィルタ条件     | `recommendation: fix` のみ対象。`create_issue` は **常に除外** (Issue 化済みは fixer の責務外)                       |
| 抜粋元ファイル   | `review_{perspective}.md` (evaluator が最終形に書き換え済み) を読む既存挙動を温存                                    |
| priority 表示    | 修正対象一覧の表示に priority を併記 (P1 → P2 → P3 の順)                                                            |

#### 関連スクリプト

| スクリプト                                       | 修正内容                                                |
| ------------------------------------------------ | ------------------------------------------------------- |
| `skills/fixer/scripts/mark_fixed.py`             | 変更なし                                                |

### 4.6 `/anvil:create-issue` (連携先)

| 項目                | 内容                                                                                                |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| 改修種別            | **改修なし** (引数互換のまま再利用)                                                                  |
| 呼び出し元 (新規)   | present-findings から `/anvil:create-issue [issue-title]` の形で呼ぶ                                |
| 初期値の引き継ぎ    | 指摘内容 (現象 / 期待 / 再現) + 追加すべきルールの草案を Issue 本文の下書きとして渡す                 |

---

## 5. ファイル単位の変更サマリ

| ファイル                                                                            | 種別           | 内容                                                  |
| ----------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------- |
| `plugins/forge/docs/review_priorities_spec.md`                                      | 新設           | 優先度 SoT (§3.2)                                     |
| `plugins/forge/docs/forge_anti_patterns.md`                                         | 新設 (空)      | アンチパターン集の雛形 (見出しのみ)。内容は別 Issue / AI が 2 行以内で自動追記 |
| `plugins/forge/docs/spec_priorities_spec.md`                                        | 拡充           | 重大度カタログ + グレーゾーン許容範囲を追加 (§3.5 / FNC-411) |
| `plugins/forge/docs/spec_design_boundary_spec.md`                                   | 拡充           | §4 / §6 に重大度カタログ + 許容範囲を追加 (§3.5 / FNC-411) |
| `plugins/forge/docs/design_principles_spec.md`                                      | 拡充           | 規範に重大度を付与 (§3.5 / FNC-411)                   |
| `plugins/forge/docs/plan_principles_spec.md`                                        | 拡充           | 規範に重大度を付与 (§3.5 / FNC-411)                   |
| `plugins/forge/skills/review/docs/review_criteria_code.md`                          | 全面置換       | §3.3 構造に変換                                       |
| `plugins/forge/skills/review/docs/review_criteria_design.md`                        | 全面置換       | §3.3 構造に変換                                       |
| `plugins/forge/skills/review/docs/review_criteria_requirement.md`                   | 全面置換       | §3.3 構造に変換                                       |
| `plugins/forge/skills/review/docs/review_criteria_plan.md`                          | 全面置換       | §3.3 構造に変換                                       |
| `plugins/forge/skills/review/docs/review_criteria_uxui.md`                          | 全面置換       | §3.3 構造に変換 (TBD-409 と並行)                      |
| `plugins/forge/skills/review/docs/review_criteria_generic.md`                       | 構造合わせ     | SoT 参照行を追加し見出しを統一                        |
| `plugins/forge/skills/review/SKILL.md`                                              | 修正           | §4.1                                                  |
| `plugins/forge/skills/reviewer/SKILL.md`                                            | 修正           | §4.2                                                  |
| `plugins/forge/skills/reviewer/templates/review.md`                                 | 修正           | §4.2 templates                                        |
| `plugins/forge/skills/evaluator/SKILL.md`                                           | 修正           | §4.3                                                  |
| `plugins/forge/skills/present-findings/SKILL.md`                                    | 修正           | §4.4                                                  |
| `plugins/forge/skills/fixer/SKILL.md`                                               | 修正           | §4.5                                                  |
| `plugins/forge/skills/review/scripts/resolve_review_context.py`                     | 修正           | §4.1 関連                                             |
| `plugins/forge/skills/review/scripts/init_session.py`                               | 修正           | §4.1 関連                                             |
| `plugins/forge/scripts/review/findings_parser.py`                                   | 修正           | priority タグ抽出を追加                               |
| `plugins/forge/scripts/review/findings_renderer.py`                                 | 修正           | priority セクション見出しを追加                       |
| `plugins/forge/scripts/session/merge_evals.py`                                      | 修正           | `create_issue` を should_continue から除外            |
| `plugins/forge/scripts/session/summarize_plan.py`                                   | 修正           | `create_issue` 状態を by_status に追加                |

---

## 6. 使用する既存コンポーネント

| コンポーネント                                | ファイルパス                                                              | 用途                                                |
| --------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------- |
| 並列 agent 出力契約                          | DES-022                                                                   | 並列 reviewer の出力契約 (温存)                     |
| per-flow orchestrator パターン               | REQ-001 / DES-013                                                         | target_files / reference_docs 解決の前提            |
| レビューワークフロー設計                     | DES-015                                                                   | Phase 1〜5 の全体構造 (本設計が部分上書き)          |
| perspective 分割設計                         | DES-021                                                                   | 並列分割の基本機構 (構築ロジックのみ差し替え)       |
| session_manager / write_refs / write_interpretation | `plugins/forge/scripts/session/`                                    | session 管理 (温存)                                 |
| `/anvil:create-issue`                        | `plugins/anvil/skills/create-issue/SKILL.md`                              | Issue 起票 (引数互換のまま再利用)                   |
| `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` | forge 内蔵                                                          | P3 (不要な複雑化) の判定原則の参照元 + 重大度カタログ / グレーゾーン許容範囲を追記 (FNC-411) |
| `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` | forge 内蔵                                                      | P1 (design 種別) の主要委譲ルール + 重大度カタログ / グレーゾーン許容範囲を追記 (FNC-411)    |
| `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`    | forge 内蔵                                                      | design 規範本体 + 重大度カタログ / グレーゾーン許容範囲を追記 (FNC-411)                    |
| `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`      | forge 内蔵                                                      | plan 規範本体 + 重大度カタログ / グレーゾーン許容範囲を追記 (FNC-411)                      |

---

## 7. テスト設計

差分に対応するテストのみを記す。

### 7.1 単体テスト対象

| 対象スクリプト                       | テスト観点                                                                                      |
| ------------------------------------ | ----------------------------------------------------------------------------------------------- |
| resolve_review_context.py            | `--files` 明示 / 未指定 (差分) の分岐                                                            |
| init_session.py                      | `--files` が session.yaml に保存される (`--section` 受理経路が無いこと)                          |
| findings_parser.py                   | `priority: P1\|P2\|P3` 行を含むレビュー出力をパースし、priority と severity を独立に抽出       |
| findings_renderer.py                 | review.md / plan.yaml に severity 別 + priority 別の二軸ソートが反映                            |
| merge_evals.py                       | `recommendation: create_issue` が `should_continue` の対象外になる                              |
| summarize_plan.py                    | `create_issue` 状態が `by_status` に出現し、`unprocessed_total` から除外される                  |

### 7.2 統合テスト対象

| シナリオ                                                | 確認内容                                                                                         |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `/forge:review` 引数なし                                | 差分のみ × 段階的提示で起動し、perspective に P1/P2/P3 のみが現れる (固有 perspective なし)      |
| `/forge:review code` と `/forge:review code --diff --interactive` | 内部状態が完全に同一になる (省略形と明示形の等価性)                                    |
| `/forge:review design --files X.md`                     | 単一ファイルが全文 reviewer に渡る                                                              |
| `--diff --files a.md`                                   | early validation がエラー (対象軸の二重指定)                                                     |
| `--section "4.1"` (任意の組み合わせ)                    | early validation がエラー (`--section` は DROP 済みフラグ / 案内メッセージを返す)                |
| `--interactive --auto-critical` / `--auto --auto-critical` | early validation がエラー (介入軸の二重指定)                                                 |
| `--auto-critical`                                       | severity=critical のみ自動修正、`recommendation=create_issue` の項目は対象外                    |
| present-findings の Issue 化選択                        | `/anvil:create-issue` が呼び出され、指摘内容が初期値として渡る                                    |
| 固有 perspective 廃止確認                               | 全 `review_criteria_*.md` に `## Perspective:` セクションが存在しない (回帰防止)                |
| criteria 不在時のフォールバック                         | プロジェクト固有 criteria 無しでも `review_priorities_spec` + 内蔵ルールで perspective が構築    |

### 7.3 既存テストへの影響

- `tests/forge/review/` 配下の固有 perspective 前提テストを `--files` / priority 体系に書き換え
- 新ファイル (review_priorities_spec.md / 改訂 criteria) はテスト対象外 (テキスト規約のため)。SKILL.md も既存方針どおりテスト対象外

---

## Appendix A: principles 拡充カタログ (Issue #74 由来 18 項目)

Issue #74 で抽出された 18 項目を **principles 拡充 (FNC-411)** の入力リストとして保全する。元 Issue は close 済み。元 criteria は本設計で全面置換されるため、各項目の「元 criteria 抜粋 2-3 行」を本 Appendix に残す。

優先度 (旧 Issue #74 表記):
- **A** = 横断的に頻出かつ AI 誤実装/誤設計を直接防げる
- **B** = 単一ファミリに閉じるが価値高
- **C** = 既存ルール / principles の拡張節として取り込む

分類 (本設計での吸収方針):
- **(a)** 既存 principles の規範に重大度を追加するだけで吸収できる
- **(b)** 既存 principles のグレーゾーン許容範囲として明示化する
- **(c)** 新規の principles 規範 / rule 文書が必要

### A.1 セキュリティ実装規約 (優先度 A / 分類 c)

- 出典: code/resilience 🔴 + design/resilience 🔴
- 配置 (新方針): `docs/rules/security_implementation.md` (新設) または `plugins/forge/docs/forge_anti_patterns.md` の Security 節
- 元 criteria 抜粋:
  - ユーザ入力の未サニタイズ / SQL・コマンドインジェクション可能なコード / ハードコードされたシークレット
  - 認証チェックの欠落、権限検証のバイパス可能な経路 (例: 管理者専用 API に権限チェックなし)
  - 機密データが暗号化されずに保存・転送される設計、認証バイパス可能な経路の存在
  - false positive 注意: ORM / パラメータ化クエリ使用時は SQLi 指摘不要

### A.2 エラーハンドリング実装規約 (優先度 A / 分類 c)

- 出典: code/resilience 🔴🟡
- 配置: `docs/rules/error_handling.md` 新設 or `implementation_guidelines.md` に節追加
- 元 criteria 抜粋:
  - `open` / `acquire` に対応する `close` / `release` がない、または例外パスでリソース未解放 (finally/defer なし)
  - HTTP クライアント / DB 接続にタイムアウト未設定
  - catch ブロックが空、ログのみでエラー握り潰し
  - false positive 注意: 呼び出し元で一括キャッチしている設計では個々の処理は不要なことがある

### A.3 入力バリデーション・境界値処理規約 (優先度 A / 分類 c)

- 出典: code/logic 🔴 + code/resilience 🟡
- 配置: `docs/rules/input_validation.md` (新設)
- 元 criteria 抜粋:
  - 入力値の境界条件 (null / 空配列 / 最大値 / ゼロ除算) に対するガード処理がない
  - 配列の長さを確認せずインデックスアクセスしている
  - 型チェック / 範囲チェック / フォーマット検証がないまま外部入力 (ユーザ入力 / API レスポンス / ファイル読み込み) を処理している

### A.4 可観測性 (ログ・メトリクス) 規約 (優先度 A / 分類 c)

- 出典: code/resilience 🟡 + design/resilience 🟡
- 配置: `docs/rules/observability.md` (新設)
- 元 criteria 抜粋:
  - エラー発生時にコンテキスト情報 (入力値・状態・操作内容) がログに含まれない
  - 設計レベルで障害発生時の原因特定に必要な情報が収集できない (ログ・メトリクス・トレースの設計なし)
  - 改善提案: 構造化ログの導入・エラーコンテキストを含むログフォーマットの統一

### A.5 並行処理・競合状態の扱い (優先度 B / 分類 c)

- 出典: code/logic 🟡 + design/resilience 🟡
- 配置: `docs/rules/concurrency.md` (新設)
- 元 criteria 抜粋:
  - 複数スレッド / タスクからアクセスされる変数に排他制御がない (Race Condition)
  - 複数コンポーネントが同一データを更新する場合に排他制御が未設計
  - データ整合性のリスク: 並行処理やトランザクション境界の設計が不十分

### A.6 DI / テスト容易性の構造原則 (優先度 A / 分類 a)

- 出典: code/maintainability 🔴
- 配置: `implementation_guidelines.md` に節追加 + 重大度カタログ
- 元 criteria 抜粋:
  - 依存関係がハードコードされ、テストでモックに差し替えられない構造
  - 例: `class FooService { private db = new Database() }` のようにコンストラクタ内で具体的な DB 接続を生成し、テスト時にインメモリ DB に差し替えられない
  - false positive 注意: シンプルなスクリプトやユーティリティ関数で DI が過剰設計になる場合は指摘不要 → (b) 許容範囲として明示化

### A.7 アーキテクチャ依存方向ルール (優先度 A / 分類 c)

- 出典: design/architecture 🔴
- 配置: `plugins/forge/docs/architecture_principles_spec.md` (新設) or `design_principles_spec.md` 拡張
- 元 criteria 抜粋:
  - 採用したアーキテクチャパターンの根本原則違反 (レイヤードで下位層が上位層に依存、クリーンアーキテクチャで Domain → Infrastructure 直接参照)
  - 循環依存: A → B → C → A のような依存の環
  - false positive 注意: 意図的な例外として設計書内に理由が記載されている場合は許容 → (b) 許容範囲として明示化

### A.8 責務分割・凝集度の原則 (優先度 A / 分類 a)

- 出典: design/architecture 🟡
- 配置: A.7 と同ファイルに統合
- 元 criteria 抜粋:
  - 責務の曖昧さ (低凝集): 1 コンポーネントが複数の異なる責務 (例: 「ユーザ認証とレポート生成を担当する Service」)
  - 密結合: インターフェースを介さない直接的な内部構造への依存
  - 過剰な抽象化: 現在の利用箇所が 1 つしかないのに汎用フレームワーク的な構造
  - false positive 注意: ファサードパターンのように意図的に複数操作をまとめる設計は正当 → (b) 許容範囲として明示化

### A.9 SPOF / 可用性設計の原則 (優先度 B / 分類 c)

- 出典: design/resilience 🔴🟡
- 配置: `plugins/forge/docs/availability_design_spec.md` 新設 or A.7 に統合
- 元 criteria 抜粋:
  - 単一障害点 (SPOF): 1 コンポーネント障害がシステム全体を停止させる構成で、冗長化や代替経路が未設計 (例: 単一 DB インスタンス依存、フェイルオーバ設計なし)
  - エラーハンドリング不足: 異常系のデータフローや障害時の振る舞いが未設計 (外部 API 連携でリトライ戦略やフォールバック未定義)

### A.10 非機能要件カテゴリ網羅性ルール (優先度 A / 分類 a)

- 出典: requirement/completeness 🔴
- 配置: `requirement_format.md` の必須セクション拡充 + `spec_priorities_spec.md` の網羅性チェック節 (REQ-004 TBD-410 / TBD-414 と整合)
- 元 criteria 抜粋:
  - 非機能要件カテゴリ (性能 / 可用性 / セキュリティ / 運用性) のいずれかが文書内に一切記載されていない
  - 例: 認証を必要とするシステムでセキュリティ要件が未定義
  - 例外系・異常系の考慮漏れ: 正常系のみ定義され、入力バリデーション / タイムアウト / リソース不足等の異常系要件がない

### A.11 トレーサビリティ規約 (優先度 A / 分類 c)

- 出典: requirement/consistency 🟡 + design/alignment 🟡 + plan/alignment 🔴🟡
- 配置: `plugins/forge/docs/traceability_spec.md` (新設)
- 元 criteria 抜粋:
  - 関連する要件が相互参照を持たない / 要件 ID と設計要素の対応表がない
  - 要件 ID に対応するタスクが計画書に存在しない、または除外理由が記載されていない (要件カバレッジ不足)
  - 要件・設計との不整合: タスクの内容が要件・設計と矛盾している

### A.12 タスク受け入れ基準・テストタスク必須化規約 (優先度 A / 分類 a)

- 出典: plan/feasibility 🔴🟡
- 配置: `plan_principles_spec.md` に節追加 + 重大度カタログ
- 元 criteria 抜粋:
  - タスクに受け入れ基準 (acceptance criteria) フィールドがない、または空 (例: 「パフォーマンス改善」タスクに具体的な目標値や測定方法なし)
  - 受け入れ基準の曖昧さ: 「適切に動作する」「問題なく処理できる」等の主観表現
  - 主要機能の実装タスクに対応するテスト・結合テストタスクが存在しない

### A.13 リスク管理規約 (優先度 B / 分類 c)

- 出典: plan/feasibility 🟡
- 配置: `plan_principles_spec.md` 拡張 or 独立 `risk_management_spec.md`
- 元 criteria 抜粋:
  - リスクが識別されているが対策 (回避 / 軽減 / 受容の判断と具体的アクション) が未記載
  - クリティカルパス上のリスクが識別されていない (複数タスクの依存先となるタスクが遅延した場合の影響が未評価)
  - 優先順位の不適切さ: 高リスクまたは高価値タスクが低優先度に設定されている

### A.14 暗黙依存の典型パターン集 (優先度 C / 分類 a)

- 出典: plan/alignment 🟡
- 配置: `plan_principles_spec.md` 補足 or A.7 に節
- 元 criteria 抜粋:
  - 依存関係フィールドに記載がないが、実装上は先行タスクの成果物が必要なタスク
  - 例: フロントエンド実装タスクが API 定義タスクへの依存を明示していない
  - 改善: タスク間の依存関係を視覚的に表現する依存関係図の追加

### A.15 HIG / Apple プラットフォーム実装規約 (優先度 A / 分類 c)

- 出典: uxui/hig_compliance 🔴🟡
- 配置: `docs/rules/uxui_hig_rules.md` (新設) or `plugins/forge/docs/uxui_rules_spec.md` (TBD-409)
- 元 criteria 抜粋:
  - iOS で TabBar が 5 タブ超過 / macOS でメニューバー未定義 / 標準ジェスチャー (戻るスワイプ等) のブロック / Safe Area 無視
  - Light/Dark モード対応が必要なのに固定 HEX 値のみ定義 (セマンティックカラー不在)
  - iOS 固有: TabBar にラベルがない、タッチターゲット 44pt 未満、Large Title 不適切
  - macOS 固有: ホバー状態未定義、キーボードショートカットなし、コンテキストメニュー未対応

### A.16 ユーザビリティ (Nielsen 10 原則) チェック規約 (優先度 A / 分類 c)

- 出典: uxui/usability 🔴🟡
- 配置: A.15 に統合
- 元 criteria 抜粋:
  - H3 違反: 破壊的操作 (削除・上書き等) に Undo も確認ダイアログもない (スワイプ削除が確認なしで即実行され Undo スナックバーもない)
  - H1 違反: 非同期処理にプログレスインジケーターやフィードバックがない (送信ボタン後に処理中かフリーズか区別できない)
  - H2 違反: ユーザー向けテキストに技術用語 (`ERR_NETWORK_TIMEOUT` 等) を露出
  - H9 違反: エラーの原因や回復方法が伝わらない (「問題が発生しました」等の曖昧メッセージ)

### A.17 アクセシビリティ規約 (優先度 A / 分類 c)

- 出典: uxui/visual_system 🔴
- 配置: A.15 の Accessibility 節
- 元 criteria 抜粋:
  - WCAG コントラスト: テキスト色と背景色のコントラスト比が 4.5:1 未満 (大テキスト 18pt 以上は 3:1)
  - 例: 薄いグレーテキスト (#CCCCCC) を白背景 (#FFFFFF) に配置 (コントラスト比 1.6:1)
  - インタラクティブ要素のサイズ: iOS で 44x44pt 未満、macOS で 20x20pt 未満
  - 例: 閉じるボタンが 24x24pt (iOS では 44pt 必要)

### A.18 デザイントークン参照規約・8pt グリッド (優先度 A / 分類 c+b)

- 出典: uxui/visual_system 🟡
- 配置: A.15 の Token Compliance 節
- 元 criteria 抜粋:
  - HEX 値 / ピクセル値が直接記述され、対応するデザイントークン名が参照されていない (例: 「背景色: #F5F5F5」→「背景色: color.background.secondary」を参照すべき)
  - 8pt グリッド非準拠: margin / padding / gap に 4pt 倍数でない値 (例: カード内パディングが 15pt → 16pt が適切)
  - タイポグラフィ階層: 見出し・本文・キャプションのサイズ差が 2pt 以下 (Title 16pt / Body 14pt 等)
  - false positive 注意: THEME-xxx がまだ定義されていない場合は指摘不要 → (b) 許容範囲として明示化

### A.x 集計と作業計画

| 分類 | 件数 | 該当項目                                                            | 取り込み手段                                                           |
| ---- | ---- | ------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| (a)  | 5    | A.6 / A.8 / A.10 / A.12 / A.14                                      | 既存 principles に節追加 + 重大度カタログ記載のみ                       |
| (b)  | 0 (純粋に b のみは該当なし。a/c の補助として false positive 注意を許容範囲化) | -    | (a)(c) の対応時に許容範囲として副次的に明示化                          |
| (c)  | 13   | A.1〜A.5, A.7, A.9, A.11, A.13, A.15〜A.18                          | 新規 rule 文書 (docs/rules/) または新規 principles (plugins/forge/docs/) |

TBD-413 の対象: (a) を最優先で取り込み (既存 principles 拡充で完結)、(c) は段階的に新規 rule 文書を整備。

## 改定履歴

| 日付       | バージョン | 内容                                                                                                |
| ---------- | ---------- | --------------------------------------------------------------------------------------------------- |
| 2026-05-19 | 1.0        | 初版。REQ-004 を How に翻訳した「フル版」DES-028                                                    |
| 2026-05-20 | 2.0        | 差分設計書として再構築。スコープを (1) ポリシーファイル差分 (2) SKILL ファイル修正箇所 の 2 点に限定 |
| 2026-05-20 | 2.1        | §2「目指す姿 (To-Be)」を追加。差分の到達点が一望できる構成に修正                                    |
| 2026-05-20 | 2.2        | デフォルト明示フラグ (`--diff` / `--user`) を導入。§2.4 CLI 構造を独立節として追加し、§4.1 の Phase 1 引数解析・early validation・§7.2 統合テストを連動更新 |
| 2026-05-20 | 2.3        | TBD-402 解消: `--auto N` の N を「指摘件数」と確定。§2.4 / §2.5 (UC-6) の表現を統一                                |
| 2026-05-20 | 2.4        | TBD-403 削除 (移行ガイドは作らない)。TBD-404 確定 (`plugins/forge/docs/` 直下)。TBD-405 解消: `forge_anti_patterns.md` を空ファイルで新設、§3.1 / §5 に追加 |
| 2026-05-20 | 2.5        | 介入軸フラグを `--user` → `--interactive` に改名 (元のフラグ名に整合)。`--section "4.1"` (セクション限定指定) を仕様 DROP し、§2.4 / §2.5 / §2.7 / §4.1 / §7.2 を連動更新 |
| 2026-05-20 | 2.6        | forge-review feature 化 (`docs/specs/forge-review/` 配下に移動)。criteria は判断を持たない方針を確立: §2.2 / §2.3 / §2.7 / §3.3 / §3.4 / §4.2 を更新。重大度カタログ・グレーゾーン許容範囲は principles 側に集約する §3.5 (principles 拡充計画) と §3.6 ポリシー差分まとめを新設。Issue #74 由来 18 項目を Appendix A として保全。§5 ファイル変更サマリに principles 拡充行を追加 |
