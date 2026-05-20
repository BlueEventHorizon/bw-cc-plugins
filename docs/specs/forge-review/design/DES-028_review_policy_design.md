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
| DES-015 レビューワークフロー設計      | **部分上書き**。Phase 構成は維持。CLI 軸・review_packet 構築・recommendation 値・findings 表記が差分 |
| DES-021 perspective 分割設計          | **部分上書き**。「criteria から `## Perspective:` 抽出 → 観点軸並列起動」ロジックを「criteria の SSOT参照 + チェック順から review_packet を構築 → reviewer 1 体に渡す」に差し替え (観点軸並列は本 feature で撤廃。FNC-412) |
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

**criteria の位置付け [MANDATORY]**: `review_criteria_*.md` は判断基準ではなく、**routing table** (どの委譲先文書のどの節を見るか) + **review playbook** (どの順で確認し、recommendation をどう判定するか) である。重大度判定・グレーゾーン判定・規範本体は一切含まない。これらはすべて委譲先 principles 側 (重大度カタログ・許容範囲明示化、FNC-411) に存在する。criteria は次の 3 セクション固定構造 (§3.3) を持つ:

- `## 1. SSOT参照` — 委譲先文書の一覧 (規範 + 重大度カタログを保持する文書)
- `## 2. チェック順` — 委譲先 principles のどの節から先に読むかの順序
- `## 3. 判定ルール` — recommendation (`fix` / `create_issue` / `skip`) の採用条件 (運用フロー)

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
│   Phase 3: review_packet 構築 (§2.3)                                     │
│             criteria + ssot_refs (P1 由来 + P2/P3 固定) を 1 packet 化   │
│             SSOT 文書数は上限 6〜8 (超過時は rules>principles>format 優先) │
│   Phase 4: reviewer 1 起動 (P1→P2→P3 をチェック順で順次評価)              │
│             → finding[] (priority ラベル付与) → evaluator 1 起動         │
│   Phase 5: present-findings (段階的提示 + Issue 化選択肢) / --auto 系     │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
   │ reviewer     │   │ evaluator    │   │ present-     │
   │ (1 起動:     │   │ (finding 単位 │   │ findings     │
   │ P1→P2→P3 を  │   │ 5 観点精査)  │   │  → fixer or  │
   │ 順次評価)    │   │              │   │    create-   │
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

### 2.3 reviewer の入力構造と評価フロー (1 起動原則)

**reviewer は原則 1 起動 [MANDATORY]**。固有 perspective だけでなく、P1/P2/P3 観点ごとや SSOT 文書ごとの reviewer 並列起動も**採用しない**。
理由: 起動数増加によりコンテキスト分断・重複指摘・評価コスト増を招き、Issue #68 (「AI reviewer がコトをどんどん複雑にする」) の再発になるため。観点軸 (P1/P2/P3) は finding の `priority` ラベルで分ければよく、agent を分ける必然性はない。

reviewer には次の **review_packet** を 1 つ渡す:

```
入力: 種別 (code/design/requirement/plan/uxui/generic)
出力: review_packet = {
  criteria_path: <criteria_md>,        # チェック順 + 判定ルール (review playbook)
  ssot_refs: [                          # 1 reviewer がまとめて参照する SSOT 文書群
    # P1: criteria の「SSOT参照」表から選定
    { doc_path: <delegated_rules_or_principles>, priority: "P1",
      doc_type: "rules" | "principles" | "format" },
    ...
    # P2: 種別共通 (criteria 不要、固定パス)
    { doc_path: "plugins/forge/docs/spec_priorities_spec.md",  # §1 境界設定
      priority: "P2", doc_type: "principles" },
    # P3: 種別共通 (criteria 不要、固定パス)
    { doc_path: "plugins/forge/docs/spec_priorities_spec.md",  # §3.4 / §4
      priority: "P3", doc_type: "principles" },
  ],
  check_order: ["P1", "P2", "P3"],      # criteria の「チェック順」由来
  severity_source: "principles",        # severity の SoT は principles 側 (FNC-411)
}
```

reviewer はこの packet を受け取り、内部で次の順序で評価する:

1. `ssot_refs` に列挙された SSOT 文書群を一括読み込み (Read 1 回ずつ)
2. `criteria_path` のチェック順 (§3.3 §2) に従い、P1 → P2 → P3 の順で対象ファイルを点検
3. 各 finding に `priority: P1 | P2 | P3` ラベルを付与
4. すべての finding を **1 つの配列** で返す (priority 混在で OK)

#### SSOT 文書数の上限と優先採用順 [MANDATORY]

reviewer 1 体に渡す `ssot_refs` の文書数には実用上限を設ける (コンテキスト過大化防止):

- **目安上限**: 6〜8 文書 (P2/P3 固定分 1〜2 文書 + P1 由来 4〜6 文書)
- **超過時の優先採用順**: criteria の「SSOT参照」に列挙された P1 由来文書が枠を超える場合、`doc_type` を優先採用順として枠を埋める (枠は増やさない):
  1. **第 1 優先**: `doc_type: rules` (プロジェクト固有 rules を最優先で枠に入れる)
  2. **第 2 優先**: `doc_type: principles` (rules 採用後、枠が余れば順に入れる)
  3. **第 3 優先**: `doc_type: format` (フォーマット規約は P1 の中心ではないため、枠がさらに余ったときのみ)
- 枠から漏れた SSOT参照は **次回レビュー時の候補** として present-findings の出力に残す (情報の取りこぼし防止)

#### 補足

- P2 / P3 は種別非依存 (固有 perspective が無くなるため統一)
- **criteria は判断を持たない** (FNC-402)。reviewer / evaluator は重大度カタログ・グレーゾーン許容範囲を必ず `ssot_refs[].doc_path` 側の principles から読み取る
- **対象ファイルも軸分割しない** (FNC-412): target_files は 1 つの reviewer にまとめて渡す。対象ファイル数が実用上限 (3〜5) を超える場合は **起動分割せず**、Phase 1 の AskUserQuestion でユーザに `--files` の絞り込みを促す (起動数増加による複雑性再発を防ぐ)。finding ごとの対象ファイル分離は `target_path` フィールドで表現する

#### refs.yaml の新スキーマ契約 [MANDATORY]

review_packet はオーケストレータ (`/forge:review`) が `refs.yaml` に格納し、reviewer がそれを読み込む。旧 `perspectives[]` セクション (DES-021 観点並列前提) は廃止し、**`review_packet` セクション** に置換する:

```yaml
# refs.yaml (新スキーマ)
target_files:
  - <path>
reference_docs:
  - path: <path>
review_packet:                        # 旧 perspectives[] を置換 (FNC-412)
  criteria_path: <path>               # review_criteria_<種別>.md
  ssot_refs:
    - doc_path: <path>
      priority: "P1" | "P2" | "P3"
      doc_type: "rules" | "principles" | "format"
  check_order: ["P1", "P2", "P3"]
  severity_source: "principles"
  output_path: review_<種別>.md       # reviewer 出力ファイル名 (種別固定)
related_code:
  - path: <path>
    reason: <text>
    lines: <range>
```

- **互換性**: 旧 `perspectives[]` は本 feature で完全撤廃。残置しない (移行期間なし)
- **検証**: `review_packet.criteria_path` / `output_path` 必須、`ssot_refs[].priority` は P1/P2/P3 のいずれか、`doc_type` は rules/principles/format のいずれか、`output_path` は `review_<種別>.md` 形式 (種別は CLI 引数の値域に一致)
- **格納タイミング**: §2.1 Phase 3 (review_packet 構築) の末尾でオーケストレータが `write_refs.py` を 1 回呼ぶ
- **読み込み**: §2.1 Phase 4 で reviewer が refs.yaml を Read し、`review_packet` セクションを取り出して評価する

### 2.4 CLI 構造 (To-Be)

```
/forge:review <種別> [--diff | --files a.md,b.md,...] [--interactive | --auto-critical | --auto]
```

| 軸     | フラグ                                         | デフォルト (未指定時) | 役割                                                                  |
| ------ | ---------------------------------------------- | --------------------- | --------------------------------------------------------------------- |
| 対象軸 | `--diff` / `--files`                           | `--diff`              | 現ブランチ未 commit 差分 / 指定ファイル群全文                          |
| 介入軸 | `--interactive` / `--auto-critical` / `--auto` | `--interactive`       | 段階的提示 / 🔴 のみ自動修正 / 全件自動修正                              |

省略形と明示形は等価。例: `/forge:review code` と `/forge:review code --diff --interactive` は同じ動作。

### 2.5 主要ユースケース (To-Be)

| ID    | 呼び出し                                                                  | 用途                                       |
| ----- | ------------------------------------------------------------------------- | ------------------------------------------ |
| UC-1  | `/forge:review <種別>` (≡ `--diff --interactive`)                         | 差分のみ × 段階的提示 (MVP デフォルト)      |
| UC-2  | `/forge:review <種別> --diff`                                             | UC-1 の明示形 (フラグを書く運用)            |
| UC-3  | `/forge:review <種別> --files a.md,b.md`                                  | 指定ファイル群を全文レビュー                |
| UC-4  | `/forge:review <種別> --auto-critical`                                    | 🔴 のみ自動修正 (対象は `--diff` デフォルト) |
| UC-5  | `/forge:review <種別> --files a.md,b.md --auto`                           | 指定ファイル群を全件自動修正 (高リスク・明示警告) |
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
| `## Perspective:` セクション (全 criteria)     | 3 セクション固定構造 (SSOT参照 / チェック順 / 判定ルール) に置換 (§3.3)  |

---

## 3. ポリシーファイル差分

ポリシーファイルとは「レビュー判断基準の単一の真実源 (SoT) を構成するファイル群」を指す。各ファイルの位置付け・改修種別・差分内容を記す。

### 3.1 ファイル一覧

| ファイル                                                              | 改修種別      | 役割                                                                                |
| --------------------------------------------------------------------- | ------------- | ----------------------------------------------------------------------------------- |
| `plugins/forge/docs/review_priorities_spec.md`                        | **新設**      | 優先度 1〜3 の SoT。全 criteria が MANDATORY 参照する基底ポリシー                    |
| `plugins/forge/docs/forge_anti_patterns.md`                           | **新設 (空ファイル)** | 業界標準アンチパターン集の雛形。配置のみ行い、初期内容は見出しのみ。**AI 自動追記なし**: レビュー中に発見した anti-pattern は `create_issue` (FNC-406) で起票し PR フローで取り込む。内容拡充は別 Issue (TBD-405 解消方針) |
| `plugins/forge/docs/spec_priorities_spec.md`                          | **拡充**      | 各規範に重大度カタログを追加 (FNC-411)。§4 倒錯パターン等の判定許容範囲を明示化       |
| `plugins/forge/docs/spec_design_boundary_spec.md`                     | **拡充**      | §4 カテゴリ別ガイド / §6 グレーゾーンに重大度・許容範囲を追加 (FNC-411)             |
| `plugins/forge/docs/design_principles_spec.md`                        | **拡充**      | 「よくある失敗パターン」等の規範に重大度を付与 (FNC-411)                            |
| `plugins/forge/docs/plan_principles_spec.md`                          | **拡充**      | タスク粒度 / 必読列 / グループ化判定 等の規範に重大度を付与 (FNC-411)               |
| `plugins/forge/skills/review/docs/review_criteria_code.md`            | **全面置換**  | code の 3 セクション (SSOT参照 / チェック順 / 判定ルール)。判断を持たない              |
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
  - priority は「観点の出所」、severity は「修正緊急度」(独立軸)
  - criteria は severity を宣言しない (FNC-402)
  - severity の SoT は委譲先 principles の重大度カタログ (FNC-411)
  - reviewer / evaluator は criteria の「SSOT参照」から委譲先文書を辿り、その重大度カタログを finding に転記する

## 3. 除外規定
  - 不足・欠落の検出は P2 の対象外
  - 「シンプルさ」「読みやすさ」等の主観評価は P3 の対象外 (Goodhart 罠回避)
  - 固有 perspective (logic / resilience / maintainability 等) の追加は原則禁止

## 4. ルール抜け落ち判定 (FNC-406 / TBD-411 解消方針)
  指摘内容が以下の 3 条件をすべて満たす場合のみ `recommendation: create_issue` 対象とする:
    1. **該当規定なし**: P1 で参照する SSOT (プロジェクト固有 rules / 内蔵 principles / format) のいずれにも該当規定が存在しない
    2. **再発性または客観性**: 同種の指摘が今回・過去のレビューで複数箇所に観察される (再発性)、または客観的事実で説明可能 (AI 主観の単発判断ではない)
    3. **明文化可能粒度**: ルールとして明文化可能な具体粒度を持ち、Issue として書き起こせる (「主観的にシンプルでない」等の評価語のみは不可)

## 5. 各 criteria の構造 [MANDATORY]
  すべての review_criteria_*.md は §2.3 の固定セクション構造に従う
```

### 3.3 `review_criteria_*.md` の固定 3 セクション構造 (全面置換後)

criteria は **判断を一切持たない**。重大度判定・グレーゾーン判定はすべて principles 側 (重大度カタログ・許容範囲明示化、FNC-411) に存在し、criteria はそれを参照する索引・運用戦術のみで構成する。

```markdown
# {種別} レビュー基準

> SoT: ${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない (REQ-004 FNC-402)

## 1. SSOT参照

| 委譲先 (principles / format / rules / 仕様書) | 役割 (規範本体 + 重大度カタログ)               |
| --------------------------------------------- | --------------------------------------------- |
| `${CLAUDE_PLUGIN_ROOT}/docs/...`              | (規範) + 重大度カタログ (FNC-411 で拡充)       |
| ...                                           | ...                                           |

## 2. チェック順

種別ごとに「どの principles 節から先に読むか」の順序。規範本体は再掲しない:

1. (最初に確認すべき節 — 例: 「principles §4 倒錯パターン」)
2. (次に確認すべき節)
3. ...

## 3. 判定ルール

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

### 3.4 種別ごとの SSOT参照 (FNC-402 対応)

各 criteria が `## 1. SSOT参照` セクションに記載する委譲先文書を予め定義する。各文書は **規範本体 + 重大度カタログ (FNC-411 拡充済み)** の両方を保持する SoT である。複数文書が並ぶ場合の優先順位は §3.4.1 を参照:

| criteria    | SSOT参照 (規範 + 重大度カタログ)                                                                                                 |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- |
| code        | `docs/rules/implementation_guidelines.md` / `docs/rules/cli_output_formatting.md` / 関連 DES / (FNC-411 拡充後) `plugins/forge/docs/forge_anti_patterns.md` |
| design      | `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` / プロジェクト固有アーキ規約 |
| requirement | `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` / `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` / `docs/rules/document_writing_rules.md` |
| plan        | `${CLAUDE_PLUGIN_ROOT}/docs/plan_format.md` / `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md` / 依存関係ルール                |
| uxui        | HIG / プロジェクト固有デザインシステム規約 (TBD-409 で整備状況確認)                                                              |
| generic     | `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md` / `docs/rules/document_writing_rules.md`                                     |

委譲先ルール文書が未整備の場合は **forge 内蔵ルールへフォールバック** (FNC-405)。プロジェクト固有 criteria が無い場合でも generic + 内蔵ルールで review_packet が構築できる。

### 3.4.1 複数 SoT 間の優先順位 [MANDATORY]

criteria の SSOT参照に複数文書が並ぶ場合、矛盾検出時の優先順位は以下とする:

| 順位 | カテゴリ                    | 例                                                            |
| ---- | --------------------------- | ------------------------------------------------------------- |
| 1    | プロジェクト固有 rules      | `docs/rules/implementation_guidelines.md` 等                   |
| 2    | プロジェクト固有 仕様書     | `docs/specs/<feature>/design/*.md` 等                          |
| 3    | forge 内蔵 principles       | `plugins/forge/docs/spec_priorities_spec.md` 等                |
| 4    | forge 内蔵 format           | `plugins/forge/docs/requirement_format.md` 等                  |

下位カテゴリで規定された内容が上位カテゴリの規定と矛盾する場合、**上位を優先**し、下位は finding として `create_issue` 推奨で扱う (ルール側更新の起票)。reviewer / evaluator は矛盾を発見した時点で finding に「上位 SoT を採用」「下位 SoT に矛盾あり」を併記する。

### 3.5 principles 拡充計画 (FNC-411 対応)

criteria から判断を完全に除去するため、principles 側を以下の方針で拡充する。各 principles ファイルは「規範 + 重大度カタログ + グレーゾーン許容範囲」を 1 ファイルに集約する。

**起草版の所在**: `docs/specs/forge-review/principles/` 配下に 4 ファイルを起草済み (本 feature 実装完了時に対応する principles ファイルへ merge する):

| 起草版                                                                      | merge 先                                                  |
| --------------------------------------------------------------------------- | --------------------------------------------------------- |
| `docs/specs/forge-review/principles/spec_priorities_spec_addendum.md`       | `plugins/forge/docs/spec_priorities_spec.md`              |
| `docs/specs/forge-review/principles/spec_design_boundary_spec_addendum.md`  | `plugins/forge/docs/spec_design_boundary_spec.md`         |
| `docs/specs/forge-review/principles/design_principles_spec_addendum.md`     | `plugins/forge/docs/design_principles_spec.md`            |
| `docs/specs/forge-review/principles/plan_principles_spec_addendum.md`       | `plugins/forge/docs/plan_principles_spec.md`              |

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
| criteria のセクション構造         | `## Perspective:` ブロック × N + 補足                    | 3 セクション固定 (SSOT参照 / チェック順 / 判定ルール)                                |
| 観点の出所                        | criteria 固有                                           | ルール文書 (P1) + 種別非依存の contradiction (P2) / simplicity (P3)                  |
| **reviewer 起動方式**             | **観点 × 文書ごとに reviewer 並列起動 (最大 10 体規模)** | **reviewer は原則 1 起動。P1/P2/P3 を同一 reviewer 内で順次評価し、finding の `priority` ラベルで分類** (Issue #68 複雑性再発防止) |
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
| Phase 1 引数解析         | 受理する引数を REQ-004 FNC-410 の最小集合に揃える: `<種別>` / `--diff` / `--files` / `--interactive` / `--auto-critical` / `--auto` (件数指定 `--auto N` は仕様 DROP) |
| Phase 1 デフォルト解決   | 対象軸が未指定なら `--diff`、介入軸が未指定なら `--interactive` として扱う (省略形と明示形を正規化して同一の内部状態に揃える)              |
| Phase 1 入力検証         | early validation を追加 (FNC-410): ① `--diff --files ...` (対象軸の二重指定) / ② 介入軸の二重指定 (`--interactive --auto-critical` / `--auto --auto-critical` 等) / ③ 未知フラグ (`--section` / `--scope` / `--depth` 等) は明示的に拒否してメッセージで「DROP 済み」と案内 |
| Phase 1 target_files 過多検出 | `--files` 明示 / `--diff` の解決結果が実用上限 (3〜5) を超える場合、**reviewer を分割起動せず** AskUserQuestion で「ファイル数 N が上限 5 を超えています。`--files` を絞り込みますか? (推奨: 種別ごと・関心領域ごとに分割実行)」と提示する (FNC-412 整合) |
| Phase 2 入力解決         | `--files` 明示時はパス解決をバイパス。`--diff` (明示 or デフォルト) 時は `.doc_structure.yaml` 経路で差分のみを対象に解決 (比較基準=現ブランチ未 commit 差分) |
| Phase 2 review_packet 構築 | 「criteria 配下 `## Perspective:` 抽出」ロジック (DES-021) を廃止。代わりに criteria の「SSOT参照」表を読み、P1 由来文書 + P2/P3 固定文書を 1 つの `ssot_refs[]` に集約 (§2.3) |
| Phase 4 reviewer 起動    | **reviewer は厳密に 1 起動** [MANDATORY]。観点軸 (P1/P2/P3) も対象ファイル軸も並列起動しない (Issue #68 複雑性再発防止、FNC-412)。reviewer 入力契約は `perspective_name` から `review_packet` (criteria_path + ssot_refs[] + check_order + target_files[]) に変更。target_files が実用上限 (3〜5) を超える場合は Phase 1 で AskUserQuestion により絞り込みを促す (起動分割しない) |
| Phase 5 介入             | 介入軸フラグ (`--interactive` / `--auto-critical` / `--auto`) で分岐。`--interactive` (=未指定時のデフォルト) は present-findings、`--auto-critical` は 🔴 のみ、`--auto` は全件 fixer に渡す。severity フィルタは priority と独立に動作 |
| Phase 5 終了確認         | findings サマリを **優先度別** (P1/P2/P3) と **severity 別** (🔴/🟡/🟢) の両方で表示                                                  |
| 不採用案内               | `--scope` / `--depth` フラグの記述を全削除 (DES-015 に残っていた場合)                                                                  |

#### 関連スクリプト

| スクリプト                                                              | 修正内容                                                                                |
| ----------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `skills/review/scripts/resolve_review_context.py`                       | `--files` 明示時のバイパス経路を追加。比較基準デフォルト (現ブランチ未 commit 差分) 実装 |
| `skills/review/scripts/init_session.py`                                 | `--files` を session.yaml メタとして保存 (`--section` は廃止のため保存しない)            |
| `scripts/session/write_refs.py`                                         | refs.yaml の新スキーマ (§2.3「refs.yaml の新スキーマ契約」) に対応。旧 `perspectives[]` 必須検証 (`validate_refs_data` / `_PERSPECTIVE_NAME_RE` / `build_refs_sections`) を撤廃し、`review_packet` セクション (criteria_path / ssot_refs[]{doc_path, priority, doc_type} / check_order / severity_source / output_path) の必須検証に置換。`output_path` は `review_<種別>.md` 形式チェックを行う |
| `skills/review/scripts/find_session.py`                                 | 変更なし                                                                                |
| `skills/review/scripts/skip_all_unprocessed.py`                         | 変更なし                                                                                |
| `skills/review/scripts/run_review_engine.sh`                            | 変更なし                                                                                |

### 4.2 `plugins/forge/skills/reviewer/SKILL.md`

| 修正セクション         | 修正内容                                                                                                              |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------- |
| 起動方式               | **reviewer は原則 1 起動** [MANDATORY]。観点軸 (P1/P2/P3) や SSOT 文書単位での並列起動はしない。観点分離は finding の `priority` ラベルで実現する |
| 入力契約               | 引数 `perspective_name` を廃止し、`review_packet` (criteria_path + ssot_refs[] + check_order + target_files) を受け取る (§2.3 参照) |
| 内部処理 (P1 評価)     | `ssot_refs` の `priority: P1` 文書群 + criteria_path (索引) + target_files を Read。SSOT 側の重大度カタログから severity を取得 (criteria の判断は参照しない) |
| 内部処理 (P2 評価)     | `ssot_refs` の `priority: P2` 文書 (`spec_priorities_spec §1`) + target_files を Read し、対象内部の **相反記述のみ** を検出する。**漏れ・欠落・重複は P2 観点外** (P1 ルール照合で扱う、REQ-004 FNC-401 P2 定義 + spec_priorities_spec_addendum.md 観点別利用ガイド) |
| 内部処理 (P3 評価)     | `ssot_refs` の `priority: P3` 文書 (`spec_priorities_spec §3.4 / §4`) + target_files を Read し、Yes/No 判定原則で複雑化を検出 |
| 評価順序               | `check_order` (criteria の「チェック順」由来) に従い P1 → P2 → P3 を順次評価し、findings を 1 配列にまとめて返す       |
| severity 取得経路      | criteria は判断を持たないため、重大度は必ず `ssot_refs[].doc_path` の principles 側重大度カタログ (FNC-411) から取得すること |
| --diff-only 経路       | 変更なし (target_files が差分ファイル群で渡る既存挙動を維持)                                                            |
| 出力 (findings 記法)    | severity ラベルは `[critical]` / `[major]` / `[minor]` の ASCII に統一。各 finding に `priority: P1\|P2\|P3` フィールドと `severity_source: <principles ファイルパス>` を追加 |
| 出力ファイル名規約       | `review_<種別>.md` (例: `review_design.md`)。perspective_name を廃止したため、suffix は種別名 (`code` / `design` / `requirement` / `plan` / `uxui` / `generic`) に統一。DES-022 の出力契約 (個別書き込み / 完了通知のみ / オーケストレータ一括更新) はそのまま温存 |

#### 関連テンプレート

| ファイル                                              | 修正内容                                                                                |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `skills/reviewer/templates/review.md`                 | 重大度セクション見出し (🔴/🟡/🟢) は表示用に温存。各 finding に `priority` 行を追加     |

### 4.3 `plugins/forge/skills/evaluator/SKILL.md`

| 修正セクション             | 修正内容                                                                                                                          |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| recommendation 値域        | `fix` / `skip` の 2 値から `fix` / `skip` / `create_issue` の 3 値に拡張                                                          |
| `create_issue` 判定基準    | `review_priorities_spec §4` (= REQ-004 FNC-406) の 3 条件 (1. 該当規定なし / 2. 再発性または客観性 / 3. 明文化可能粒度) を満たすときに付与   |
| --auto / --auto-critical 連携 | severity フィルタを priority と独立に評価。`--auto-critical` 対象 = severity=critical のみ (priority 不問)                       |
| 要件レビュー固有判定       | requirement の網羅性確認は FNC-411 で `spec_priorities_spec.md` (非機能要件カテゴリ網羅性節) に吸収済み (TBD-410 解消)              |
| review_*.md 整形           | テンプレ見出しに `priority` セクションを追加。skip_reason カタログは温存                                                            |

#### 5 観点精査 × P1/P2/P3 の関係 (TBD-406 解消)

evaluator は reviewer が生成した finding を以下の 5 観点で精査する。各観点と priority の関係は次表:

| 観点                  | 役割                                                              | P1 (ルール照合)       | P2 (矛盾)             | P3 (不要複雑化)       |
| --------------------- | ----------------------------------------------------------------- | --------------------- | --------------------- | --------------------- |
| 1. ルール照合         | finding の根拠ルールが SoT に実在し、引用が正確かを確認            | **主軸**              | 副次 (矛盾根拠の確認) | 副次 (Goodhart 罠検出) |
| 2. 設計意図           | finding が文書の本来意図と整合しているかを確認                     | 副次                  | **主軸** (意図食違い) | **主軸** (意図不一致)  |
| 3. 副作用リスク       | 修正適用時の他箇所への影響を見積もる                               | 全 finding で適用     | 全 finding で適用     | 全 finding で適用     |
| 4. false positive     | グレーゾーン許容範囲内かを principles 側の許容範囲表で判定         | 全 finding で適用     | 全 finding で適用     | 全 finding で適用     |
| 5. 対象ファイル確認   | finding が target_files の内容と整合し、行/節が実在するかを確認    | 全 finding で適用     | 全 finding で適用     | 全 finding で適用     |

**recommendation 決定フロー** (5 観点の結果から):

```
観点 5 で「対象ファイルに該当箇所なし」    → finding 破棄 (reviewer 段階バグとして記録)
観点 4 で「グレーゾーン許容範囲内」        → recommendation: skip (skip_reason に許容範囲表の該当行を引用)
観点 1 で「ルール未整備 (FNC-406 3 条件成立)」 → recommendation: create_issue
観点 1〜3 すべて満たし、ルール整備済         → recommendation: fix
それ以外 (観点 1-3 のいずれかが不成立)     → recommendation: skip (skip_reason を具体記載)
```

observation 軸 (P1/P2/P3) と精査軸 (5 観点) は **直交**。同一 finding が複数 priority に該当することはなく、すべての finding に 5 観点を適用する。

#### 関連スクリプト

| スクリプト                                                  | 修正内容                                                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `scripts/session/write_interpretation.py`                   | 出力ファイル名規約変更 (`review_<種別>.md`) に伴い、f-string テンプレート `f"review_{perspective}.md"` を `f"review_{kind}.md"` に、CLI 引数 `--perspective` を `--kind` (値域: `code` / `design` / `requirement` / `plan` / `uxui` / `generic`) に改名。docstring も種別名表記に揃える。冪等な全面書き換え + `.raw.md` バックアップ機構 (DES-022 出力契約) は温存 |
| `scripts/session/merge_evals.py`                            | (1) `recommendation: create_issue` 行を `should_continue` 計算から除外。(2) `perspective` ベースのマッピング (`build_perspective_id_map` / `_perspective` キー / 「perspective 間で判定不一致」reason 文言) を **priority (P1/P2/P3) ベース** に置換。reviewer 1 起動原則 (§2.3 / FNC-412) により同一 global_id に対する複数 perspective 判定の統合ロジック自体が不要化するため、衝突解決ブロックは削除し、global_id ↔ local_id マッピングのみ priority ラベルから引き直す |

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
| 抜粋元ファイル   | `review_<種別>.md` (例: `review_design.md`、evaluator が最終形に書き換え済み) を読む。perspective_name 廃止に伴い、出力ファイル名の suffix は perspective_name から種別名 (`code` / `design` / `requirement` / `plan` / `uxui` / `generic`) に変わる |
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
| `plugins/forge/docs/forge_anti_patterns.md`                                         | 新設 (空)      | アンチパターン集の雛形 (見出しのみ)。内容は別 Issue。AI 自動追記なし (`create_issue` で起票 → PR フローで取り込み) |
| `plugins/forge/docs/spec_priorities_spec.md`                                        | addendum merge | `docs/specs/forge-review/principles/spec_priorities_spec_addendum.md` を merge (観点別利用ガイド + 重大度カタログ + グレーゾーン許容範囲 + 非機能要件カテゴリ網羅性)。merge 後に addendum ファイルは削除する (§3.5 / FNC-411) |
| `plugins/forge/docs/spec_design_boundary_spec.md`                                   | addendum merge | `docs/specs/forge-review/principles/spec_design_boundary_spec_addendum.md` を merge (§4 / §6 に重大度カタログ + 許容範囲)。merge 後に addendum ファイルは削除する (§3.5 / FNC-411) |
| `plugins/forge/docs/design_principles_spec.md`                                      | addendum merge | `docs/specs/forge-review/principles/design_principles_spec_addendum.md` を merge (アーキテクチャ依存方向 / 責務分割 / 可用性規範 + 重大度カタログ)。merge 後に addendum ファイルは削除する (§3.5 / FNC-411) |
| `plugins/forge/docs/plan_principles_spec.md`                                        | addendum merge | `docs/specs/forge-review/principles/plan_principles_spec_addendum.md` を merge (タスク受け入れ基準 / テストタスク必須化 / 暗黙依存 / トレーサビリティ規範 + 重大度カタログ)。merge 後に addendum ファイルは削除する (§3.5 / FNC-411) |
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
| `plugins/forge/scripts/session/merge_evals.py`                                      | 修正           | `create_issue` を should_continue から除外。perspective ベース統合を priority ベースに置換 (§4.3 関連スクリプト) |
| `plugins/forge/scripts/session/summarize_plan.py`                                   | 修正           | `create_issue` 状態を by_status に追加                |
| `plugins/forge/scripts/session/write_interpretation.py`                             | 修正           | f-string テンプレと CLI 引数を種別名対応に改名 (§4.3 関連スクリプト) |
| `plugins/forge/scripts/session/write_refs.py`                                       | 修正           | refs.yaml の新スキーマ (review_packet) に対応 (§4.1 関連スクリプト / §2.3) |

### 5.1 addendum merge タイミング [MANDATORY]

`docs/specs/forge-review/principles/*_addendum.md` 4 件は forge-review feature の実装と **同時に** merge する。本 feature の実装フェーズで以下を満たすこと:

- 実装 PR 内で `plugins/forge/docs/{spec_priorities,spec_design_boundary,design_principles,plan_principles}_spec.md` への merge を完了させる (reviewer が ssot_refs から forge 内蔵 docs を辿った時点で重大度カタログ・許容範囲・観点別利用ガイドが揃っている状態を保証)
- merge 完了後、`docs/specs/forge-review/principles/*_addendum.md` を削除する (起草版の役目を終えるため)
- merge 内容は addendum の本文をそのまま転記する (frontmatter は除く)。target ファイル側の改定履歴に merge 元 addendum バージョン (v0.x) を記録する

---

## 6. 使用する既存コンポーネント

| コンポーネント                                | ファイルパス                                                              | 用途                                                |
| --------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------- |
| 並列 agent 出力契約                          | DES-022                                                                   | agent 出力契約の 3 原則 (個別書き込み / 完了通知のみ / オーケストレータ一括更新) は本 feature でも温存 (reviewer 1 起動でも出力先ファイルの規約は同じ) |
| per-flow orchestrator パターン               | REQ-001 / DES-013                                                         | target_files / reference_docs 解決の前提            |
| レビューワークフロー設計                     | DES-015                                                                   | Phase 1〜5 の全体構造 (本設計が部分上書き)          |
| perspective 分割設計                         | DES-021                                                                   | **観点軸の並列分割は本 feature で撤廃** (reviewer 1 起動原則 §2.3)。基本機構 (`run_review_engine.sh` の起動経路) はそのまま再利用するが、起動数は 1 |
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
| `/forge:review` 引数なし                                | 差分のみ × 段階的提示で起動し、reviewer 1 体のみが起動 (固有 perspective なし)。findings の `priority` に P1/P2/P3 がラベルとして付与される |
| `/forge:review code` と `/forge:review code --diff --interactive` | 内部状態が完全に同一になる (省略形と明示形の等価性)                                    |
| `/forge:review design --files X.md`                     | 単一ファイルが全文 reviewer に渡る                                                              |
| `--diff --files a.md`                                   | early validation がエラー (対象軸の二重指定)                                                     |
| `--section "4.1"` (任意の組み合わせ)                    | early validation がエラー (`--section` は DROP 済みフラグ / 案内メッセージを返す)                |
| `--interactive --auto-critical` / `--auto --auto-critical` | early validation がエラー (介入軸の二重指定)                                                 |
| `--auto-critical`                                       | severity=critical のみ自動修正、`recommendation=create_issue` の項目は対象外                    |
| present-findings の Issue 化選択                        | `/anvil:create-issue` が呼び出され、指摘内容が初期値として渡る                                    |
| 固有 perspective 廃止確認                               | 全 `review_criteria_*.md` に `## Perspective:` セクションが存在しない (回帰防止)                |
| criteria 不在時のフォールバック                         | プロジェクト固有 criteria 無しでも `review_priorities_spec` + 内蔵 principles で review_packet が構築できる |
| **reviewer 1 起動原則の回帰防止**                       | 任意の種別・任意の `--files` 指定で、観点軸 (P1/P2/P3) に対して起動される reviewer agent 数が 1 であることを統合テストで確認 (Issue #68 複雑性再発防止) |

### 7.3 既存テストへの影響

- `tests/forge/review/` 配下の固有 perspective 前提テスト + 観点軸並列起動前提テストを、`--files` / priority ラベル / 1 reviewer 起動体系に書き換え
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
| 2026-05-20 | 2.7        | frontmatter `type: temporary-feature-design` を付与しメタデータ表に Feature / プラグイン / 起点 Issue を補完。§6 使用する既存コンポーネントに principles 4 ファイルの拡充注記を追記 |
| 2026-05-20 | 2.8        | **`--auto N` (件数指定) を仕様 DROP**: §2.4 CLI 構造から `[N]` 除去、§2.4 介入軸表の役割記述を「全件自動修正」に簡略化、§2.5 UC-5 を `--auto` (全件) 例に差し替え、§4.1 Phase 1 引数解析 / Phase 5 介入の記述を `--auto` 単独に揃える。介入モードを「対話 / 🔴 のみ / 全件」の 3 つに限定 (FNC-410 整合)。理由: severity 順 × 件数の混合軸は AI 誤生成リスクが高い |
| 2026-05-20 | 2.9        | **principles 拡充起草版を作成** (FNC-411 実体): `docs/specs/forge-review/principles/` 配下に 4 ファイル (`spec_priorities_spec_addendum.md` / `spec_design_boundary_spec_addendum.md` / `design_principles_spec_addendum.md` / `plan_principles_spec_addendum.md`) を起草。各ファイルは重大度カタログとグレーゾーン許容範囲を実コンテンツとして含む。§3.5 に起草版の所在を追記 |
| 2026-05-20 | 3.0        | **レビュー指摘対応**: (1) 用語改名: 委譲先 SSOT → SSOT参照 / 焦点順 → チェック順 / 委譲原則 → 判定ルール (DES-028 全文 12 箇所 + REQ-004 7 箇所)。(2) §3.2 草案 §2 で「criteria が委譲ルールごとに severity デフォルトを宣言」と読める記述を削除し、severity SoT が principles 側であることを明文化 (§3.3 / §2.2 と整合)。(3) §3.4.1「複数 SoT 間の優先順位」を新設 (プロジェクト固有 rules > プロジェクト固有 仕様書 > forge 内蔵 principles > forge 内蔵 format)。(4) §2.3「P1 並列上限超過時の絞り込み規則」を明文化 (`doc_type` rules > principles > format で順次)。(5) §2.1 冒頭に「criteria は routing table + review playbook」位置付けを明記 |
| 2026-05-20 | 3.1        | **第 2 次レビュー指摘対応** (実装直結 4 件解消): (1) TBD-401 解消: `--diff` 比較基準を「現ブランチ未 commit 差分のみ」と確定 (REQ-004 §2 FNC-403 反映)。(2) FNC-403 改訂: CLI 契約は位置引数=種別 1 個に固定、自由入力 (Feature 名・ディレクトリ等) は SKILL 側で AI が推測 → AskUserQuestion で確認 → `--files` 内部展開のフローを明文化。(3) §2.3 P2 perspective の `severity_source` を具体化: `<principles_with_consistency_rules>` プレースホルダを廃し、P2 = `plugins/forge/docs/spec_priorities_spec.md` §1 / P3 = 同 §3.4 / §4 と確定。(4) §4.3 evaluator に「5 観点精査 × P1/P2/P3 の関係」表 + recommendation 決定フローを新設 (TBD-406 解消、観点軸 5 と priority 軸 3 が直交であることを明示)。(5) `forge_anti_patterns.md` の AI 自動追記方針を撤廃: レビュー実行中に発見した anti-pattern は `recommendation: create_issue` (FNC-406) で起票し、ファイル本体追記は通常 PR フローで行う (配布対象ファイルがレビュー実行中に変わるとリリース管理が破綻するため)。§3.1 表 / §5 ファイル変更サマリを連動更新。(6) REQ-004 §4 未確定事項表を再構成: 設計時解消 4 件 (TBD-406/410/411/413) + TBD-401 を「解消経緯」サブテーブルに移管、残 5 件 (TBD-407/408/409/412/414) を「初版リリース後」期限に変更 |
| 2026-05-20 | 3.2        | **第 3 次レビュー指摘対応** (REQ/DES の細部不整合解消): (1) `create_issue` 3 条件を REQ/DES で統一: REQ-004 FNC-406 に「(1) 該当規定なし / (2) 再発性または客観性 / (3) 明文化可能粒度」の 3 条件を本体節として明記し、DES-028 §3.2 草案 §4 / §4.3 表 / TBD-411 解消経緯を同一文言に揃える。旧 REQ 表現「規範本体に明記がない」は条件 1 と重複のため削除、旧 REQ 表現「AI 主観由来でない」は「再発性または客観性」に吸収 (客観判定軸として実装可能な形に統合)。(2) §2.3「P1 上限超過時の絞り込み規則」の文言を「優先採用順で枠 (8) を埋める」に修正: 旧文言「principles を順次フォールバック」は枠を増やすように読めたため、枠は固定で `rules → principles → format` の優先採用順として明示 |
| 2026-05-20 | 3.3        | **第 4 次レビュー指摘対応 (思想転換の最終段階): reviewer 1 起動原則の確立**。指摘内容: 「P1 = SSOT参照 × ルール文書数 で reviewer を多数並列起動する設計は、Issue #68 (レビューが重く複雑) に逆戻りしやすい」。対応: (1) §2.3 を「reviewer の入力構造と評価フロー (1 起動原則)」に再設計。観点ごと・SSOT 文書ごとの並列 reviewer 起動を撤廃し、reviewer は **原則 1 起動**、P1/P2/P3 は同一 reviewer 内でチェック順に順次評価、finding には `priority: P1\|P2\|P3` ラベルを付与する方式に変更。perspectives[] YAML を `review_packet { criteria_path / ssot_refs[] / check_order }` に置換。(2) §2.1 シーケンス図 Phase 3-4 を「review_packet 構築 → reviewer 1 起動」に書き換え。reviewer 内ボックスも「1 起動: P1→P2→P3 を順次評価」に修正。(3) §3.6 ポリシー差分まとめに「reviewer 起動方式」行を追加 (Before: 観点 × 文書ごとに最大 10 体規模 / After: 原則 1 起動 + priority ラベル分類)。(4) §4.1 Phase 2/4 表 / §4.2 reviewer SKILL 表を「review_packet 入力 / 観点軸での agent 分離なし / check_order 順次評価」に書き換え。(5) §6 既存コンポーネントの DES-021 (perspective 分割設計) を「観点軸並列分割は本 feature で撤廃。基本機構 (run_review_engine.sh) は再利用するが起動数は 1」に明確化。DES-022 (並列 agent 出力契約) は出力ファイル規約として温存。(6) §7.2 統合テストに「reviewer 1 起動原則の回帰防止」を追加、`/forge:review` 引数なしの確認内容を「reviewer 1 体のみ起動」に書き換え。SSOT 上限ガイドラインは「並列 reviewer 数上限」から「1 reviewer に渡す SSOT 文書数上限 (6〜8)」に意味を変更し、優先採用順 (rules > principles > format) は流用 |
| 2026-05-20 | 3.4        | **第 5 次レビュー指摘対応 (1 起動原則の徹底 + 旧用語残存解消)**: (1) **Medium**: 対象ファイル軸 reviewer 再起動の抜け道を撤廃 — REQ-004 FNC-412 / DES-028 §2.3 補足 / §4.1 Phase 4 reviewer 起動を「観点軸も対象ファイル軸も並列起動しない (例外なし)」に書き換え。target_files は 1 つの reviewer にまとめて渡し、実用上限 (3〜5) 超過時は §4.1 に新設した「Phase 1 target_files 過多検出」で AskUserQuestion により `--files` 絞り込みを促す方式に変更。finding ごとの対象ファイル分離は `target_path` フィールドで表現する。(2) **Medium**: 旧 perspective 文言を review_packet 構築 / 観点表現に統一 — REQ-004 L74 「perspectives 収集」→「review_packet 構築」、DES-028 §1.1 「DES-015 → CLI 軸・perspective 構築」を「review_packet 構築」、「DES-021 → `## Perspective:` 抽出 → 観点軸並列起動」を「criteria の SSOT参照 + チェック順から review_packet を構築 → reviewer 1 体に渡す」、§3.4 「内蔵ルールで perspective が構築できる」→「review_packet が構築できる」に変更。FNC-402 / FNC-412 の「固有 perspective 廃止」「観点軸並列」等の概念用語は文脈として温存。(3) **Low**: fixer 入力ファイル名の旧命名を改名 — DES-028 §4.5 fixer 抜粋元ファイル `review_{perspective}.md` を `review_<種別>.md` (例: `review_design.md`) に改名し、§4.2 reviewer SKILL に「出力ファイル名規約」行を新設して suffix を perspective_name → 種別名 (`code` / `design` / `requirement` / `plan` / `uxui` / `generic`) に統一する規約を明示。DES-022 の出力契約 3 原則は温存 |
| 2026-05-20 | 3.5        | **第 6 次レビュー指摘対応 (principles 起草版の調整: Medium 3 件 + 構造調整 1 件)**: (1) **Medium**: P2 観点に「漏れ」が混入するリスクを解消 — `spec_priorities_spec_addendum.md` 重大度カタログ前に「観点別の利用ガイド」節を新設し、§1 規範 (責務分割 / 境界設定 / 依存方向) は P1 (ルール照合) で扱い、P2 (矛盾・齟齬) では §1 のうち **相反記述のみ** を見る方針を明文化 (REQ-004 FNC-401 P2 定義「不足・欠落の検出は対象外」と整合)。DES-028 §4.2 reviewer の P2 評価行も「相反記述のみを検出。漏れ・欠落・重複は P2 観点外 (P1 ルール照合で扱う)」に書き換え。(2) **Medium**: 非機能要件カテゴリ網羅性のスコープ付け — 旧「いずれか未記載なら critical」を「対象システムの性質によって分岐 (本番運用 / 外部公開 / データ保護を伴う場合は 🔴 critical、それ以外は 🟡 major)」に変更。Issue #68 (レビューを重くしない) の思想に整合させ、軽量 CLI / 内部ツール / 文書-only feature での false positive を抑える。(3) **Medium**: design 必須構成要素にスコープ条件を付与 — `design_principles_spec_addendum.md` の「モジュールリスト欠如 / コンポーネント図・クラス図欠如 / ユースケース一覧欠如」を一律 major としていたが、設計種別によっては不要な要素があるため、各行に「該当する場合」条件を追加 (シーケンス図欠如と同じスコープ条件付き表現に揃える)。(4) **構造調整**: REQ-004 TBD-414 を「未確定」から「設計時解消」サブテーブルに移管 — 取り込み先は `spec_priorities_spec_addendum.md` で既に確定済み (TBD-410 と一体)、残課題は本 feature 実装完了時の機械的 merge 確認のみ |
| 2026-05-21 | 3.6        | **第 7 次レビュー指摘対応 (実装直結 3 件)**: (1) **Medium**: §4.3 関連スクリプト表で `write_interpretation.py` を「変更なし」としていたが、§4.2 / §4.5 で出力ファイル名規約を `review_<種別>.md` に統一した結果、現行実装の f-string `f"review_{perspective}.md"` 固定 / CLI 引数 `--perspective` required と乖離。`write_interpretation.py` 行を「f-string テンプレート → `f"review_{kind}.md"` / CLI 引数 → `--kind` (値域: 種別 6 種) に改名」に修正。同様に `merge_evals.py` 行も `perspective` ベース統合 (build_perspective_id_map / `_perspective` キー / 「perspective 間で判定不一致」reason) を priority ベース置換に書き換え。§5 ファイル変更サマリにも `write_interpretation.py` を追加。(2) **Medium**: review_packet を refs.yaml に格納する契約が §2.3 / §4.1 のいずれにも存在しなかった (現行 `write_refs.py` は旧 `perspectives[]` 必須検証のまま)。§2.3 末尾に「refs.yaml の新スキーマ契約」節を新設し、YAML 構造 (target_files / reference_docs / `review_packet { criteria_path / ssot_refs[] / check_order / severity_source / output_path }` / related_code) と検証ルール / 格納タイミング / 読み込みフローを明示。§4.1 関連スクリプト表に `write_refs.py` 更新行を追加 (旧 `perspectives[]` 検証撤廃 + review_packet 検証へ置換)。§5 ファイル変更サマリにも `write_refs.py` を追加。(3) **Medium**: principles addendum 4 件が `docs/specs/forge-review/principles/` にあるが、§2.3 の `ssot_refs[].doc_path` は forge 内蔵 `plugins/forge/docs/*.md` を指すため、実装段階で reviewer が ssot_refs を辿った時点で重大度カタログ / 観点別利用ガイドが見つからない状況になる。§5 ファイル変更サマリの 4 件 (`spec_priorities_spec.md` / `spec_design_boundary_spec.md` / `design_principles_spec.md` / `plan_principles_spec.md`) の種別を「拡充」→「addendum merge」に書き換え、merge 元 addendum パスと merge 内容を明示。§5.1「addendum merge タイミング」節を新設し、実装 PR で merge 完了 + addendum 削除 + target ファイル改定履歴への merge 元バージョン記録を MANDATORY 化 |
