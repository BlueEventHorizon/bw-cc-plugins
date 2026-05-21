# レビュー優先度仕様 [MANDATORY]

レビューが検出する観点の優先度体系と、その判定における判断 (severity / グレーゾーン) の所在を定義する。
本文書は forge が配布する `/forge:review` 系 SKILL 群 (review / reviewer / evaluator / present-findings / fixer) と、各 `review_criteria_*.md` が **MANDATORY 参照する基底ポリシー** である。

**本文書のスコープ**:

- レビュー観点の優先度 (P1 / P2 / P3) の定義
- priority (観点の出所) と severity (修正緊急度) の関係
- criteria が判断を持たないことの宣言と、severity の SoT が委譲先 principles であることの明文化
- `recommendation: create_issue` の判定 3 条件
- 各 `review_criteria_*.md` の固定 3 セクション構造

**関連文書**:

- 要件: `docs/specs/forge-review/requirements/REQ-004_review_policy.md` (FNC-401 / FNC-402 / FNC-406 / FNC-409 / FNC-411)
- 設計: `docs/specs/forge-review/design/DES-028_review_policy_design.md` (差分設計)
- 文書スタイル: `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md`
- 委譲先 principles (severity の SoT / 重大度カタログ・グレーゾーン許容範囲の正規 SoT): `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`

---

## 1. 優先度の定義

レビューが検出する観点は以下の 3 つに限定する。各 `review_criteria_*.md` は固有 perspective を持たない (REQ-004 FNC-402)。

| 優先度 | 名称         | 役割                                                                                                       |
| ------ | ------------ | ---------------------------------------------------------------------------------------------------------- |
| **P1** | ルール合致   | 対象がプロジェクトルール・forge 内蔵ルール・関連仕様書に沿っているかを照合する                             |
| **P2** | 矛盾・齟齬   | 文書内 / コード内 / 文書とコードの間で相反する記述が存在するかを検出する                                   |
| **P3** | 不要な複雑化 | より少ない要素 (ステップ・クラス・抽象・分岐) で同じ目的を達成できる代替案が存在するかを Yes/No で判定する |

### 1.1 P1 — ルール合致

- 判定方法: 関連ルール文書を Read し、対象と照合する
- 対象ルール: `docs/rules/` (プロジェクト固有) / `${CLAUDE_PLUGIN_ROOT}/docs/` (forge 内蔵) / 関連仕様書 (`docs/specs/`)
- アーキテクチャ・コーディング規約・命名規則・設計原則・セキュリティ規約等、本来「品質を担保するためのルール」はすべて P1 で照合する
- 委譲先ルールが未整備の場合は forge 内蔵ルールへフォールバック (REQ-004 FNC-405)

### 1.2 P2 — 矛盾・齟齬

- 判定方法: 同一対象への異なる記述を突き合わせる
- **不足・欠落の検出は P2 の対象外** (網羅性確認は P1 ルール照合で扱う)。詳細は §3.1

### 1.3 P3 — 不要な複雑化

- 判定方法 (Yes/No): 代替案が存在 AND 既存案にそれを正当化する rationale が無い場合に Yes
- 「シンプルさ」「読みやすさ」等の主観評価には拡張しない (Goodhart の罠回避は `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` §3.2 に従う)。詳細は §3.2

---

## 2. priority と severity の関係

priority と severity は **独立した二軸** であり、互いに置き換わらない。

| 軸           | 役割                        | 値                                            | 用途                                      |
| ------------ | --------------------------- | --------------------------------------------- | ----------------------------------------- |
| **priority** | 観点の出所 (何で検出したか) | `P1` / `P2` / `P3`                            | finding の分類軸                          |
| **severity** | 修正の緊急度                | `critical` / `major` / `minor` (🔴 / 🟡 / 🟢) | `--auto-critical` / `--auto` の対象選定軸 |

### 2.1 独立軸であることの帰結

- P1 (ルール照合) で検出した違反が必ず critical とは限らない
- P3 (不要な複雑化) であっても critical となる場合がある (例: Goodhart の罠を誘発する数値目標化)
- finding は priority と severity の両方を持ち、`--auto-critical` は severity=critical のみを対象とする (priority 不問)

### 2.2 severity の SoT は委譲先 principles [MANDATORY]

severity の単一の真実源 (SoT) は **委譲先 principles の重大度カタログ** である (REQ-004 FNC-411)。

- 各 `review_criteria_*.md` は severity を宣言しない (§3 除外規定)
- reviewer / evaluator は criteria の「SSOT参照」から委譲先文書を辿り、その重大度カタログから severity を finding に転記する
- 執筆者は設計時点で principles の重大度カタログを参照できるため、「レビュアーだけが知っている判断基準」は存在しない (REQ-004 §1「設計時点での情報完全性」)

> **注**: addendum merge は完了済み (forge-review feature 実装フェーズ TASK-032〜036 で実施。DES-028 §5.1)。

---

## 3. 除外規定

本節は DES-028 §3.2 草案と整合する除外規定を §3.1〜§3.3 に集約する (5 セクション固定構造の読み手が §3 だけを辿っても取りこぼさないため)。§3.4 以降は criteria の内部規約 (判断除去) を規定する。

### 3.1 P2 の対象外

**不足・欠落の検出は P2 の対象外**。網羅性の確認は P1 のルール照合で扱う (§1.2 の運用規定はここに集約する)。

### 3.2 P3 の対象外

**「シンプルさ」「読みやすさ」等の主観評価は P3 の対象外** (Goodhart の罠回避は `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` §3.2 に従う、§1.3 の運用規定はここに集約する)。

### 3.3 固有 perspective の追加禁止

`logic` / `resilience` / `maintainability` / `architecture` / `completeness` 等の固有 perspective を criteria に追加することは原則禁止する (REQ-004 FNC-402)。品質特性 (保守性・堅牢性・アーキテクチャ整合性等) のレビューは P1 のルール照合に委譲する。

### 3.4 criteria は severity を宣言しない [MANDATORY]

各 `review_criteria_*.md` は **severity (🔴 / 🟡 / 🟢) を一切宣言しない**。

- 旧 criteria が持っていた `### 🔴致命的` / `### 🟡品質問題` / `### 🟢改善提案` 等のセクション分けは廃止
- severity デフォルト表 (perspective 単位での重大度割り当て表) も廃止
- severity は委譲先 principles の重大度カタログから取得する (§2.2)

### 3.5 criteria はグレーゾーン判定を持たない [MANDATORY]

各 `review_criteria_*.md` は **グレーゾーンの許容範囲判定を持たない**。

- 旧 criteria が持っていた `false positive に注意` 形式の警告ブロックは廃止
- 「どの解釈を許容し、どれを許容しないか」は委譲先 principles の「グレーゾーン許容範囲」節に断定形で明示する (REQ-004 FNC-411)
- evaluator の 5 観点精査 (観点 4: false positive) は criteria ではなく principles の許容範囲表を参照して判定する

### 3.6 委譲先 principles への全委譲

criteria が持つもの / 持たないものを以下のように整理する。判断 (severity / グレーゾーン) はすべて principles 側に集約する。

| 区分                                          | criteria が持つか     | 配置                                 |
| --------------------------------------------- | --------------------- | ------------------------------------ |
| 委譲先ルール文書 (SSOT参照)                   | **持つ**              | criteria                             |
| チェック順 (どこから読むか)                   | **持つ** (運用戦術)   | criteria                             |
| 判定ルール (fix / create_issue / skip の切替) | **持つ** (運用フロー) | criteria                             |
| 重大度マッピング (規範違反 → 🔴 / 🟡 / 🟢)    | 持たない              | principles (重大度カタログ、FNC-411) |
| グレーゾーン許容範囲 (How/What 境界の判定)    | 持たない              | principles (許容範囲明示化、FNC-411) |
| 規範本体 (執筆者が遵守すべき決まり)           | 持たない              | principles / format / style_guide    |
| 固有 perspective (logic / resilience 等)      | 持たない              | 廃止 (REQ-004 FNC-402)               |

---

## 4. `recommendation: create_issue` の判定 3 条件 [MANDATORY]

レビューが「明文ルールでカバーできないが指摘すべき問題」を発見した場合、`recommendation: create_issue` でルール追加を促す Issue を起票する (REQ-004 FNC-406)。
evaluator は finding が以下の **3 条件をすべて満たす場合のみ** `recommendation: create_issue` に分類する。

| # | 条件               | 内容                                                                                                                    |
| - | ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 1 | 該当規定なし       | P1 で参照する SSOT (プロジェクト固有 rules / forge 内蔵 principles / format) のいずれにも該当規定が存在しない           |
| 2 | 再発性または客観性 | 同種の指摘が今回・過去のレビューで複数箇所に観察される (再発性)、または客観的事実で説明可能 (AI 主観の単発判断ではない) |
| 3 | 明文化可能粒度     | ルールとして明文化可能な具体粒度を持ち、Issue として書き起こせる (「主観的にシンプルでない」等の評価語のみは不可)       |

3 条件のいずれかが不成立の場合は `recommendation: skip` (skip_reason に該当条件不成立の理由を記載) とする。

本節は REQ-004 FNC-406 の表と **同一文言** であり、本文書を 3 条件の SoT として参照する。

---

## 5. 各 `review_criteria_*.md` の構造 [MANDATORY]

すべての `review_criteria_*.md` は以下の 3 セクション固定構造を持つ (REQ-004 FNC-409)。3 セクション以外のセクションを追加してはならない。criteria は判断を持たず、principles を参照する索引と、レビュー運用上の戦術 (チェック順 / 判定ルール) のみで構成する。

### 5.1 固定 3 セクション

| # | セクション         | 役割                                                                                                                |
| - | ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| 1 | `## 1. SSOT参照`   | P1 で照合すべき principles / format / rules / 仕様書の文書一覧。各文書は「規範本体 + 重大度カタログ」を保持する SoT |
| 2 | `## 2. チェック順` | 「principles のどの節から先に読むか」の順序ガイド。規範本体は再掲しない                                             |
| 3 | `## 3. 判定ルール` | `recommendation: fix` / `create_issue` / `skip` の切替条件 (運用フロー)                                             |

### 5.2 雛形

```markdown
# {種別} レビュー基準

> SoT: ${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない (REQ-004 FNC-402)

## 1. SSOT参照

| 委譲先 (principles / format / rules / 仕様書) | 役割 (規範本体 + 重大度カタログ)         |
| --------------------------------------------- | ---------------------------------------- |
| `${CLAUDE_PLUGIN_ROOT}/docs/...`              | (規範) + 重大度カタログ (FNC-411 で拡充) |
| ...                                           | ...                                      |

## 2. チェック順

種別ごとに「どの principles 節から先に読むか」の順序。規範本体は再掲しない:

1. (最初に確認すべき節 — 例: 「principles §4 倒錯パターン」)
2. (次に確認すべき節)
3. ...

## 3. 判定ルール

| recommendation | 採用条件                                                              |
| -------------- | --------------------------------------------------------------------- |
| `fix`          | 規範違反であり、修正による副作用が限定的な場合                        |
| `create_issue` | ルール未整備で発見した場合 (本仕様 §4 の 3 条件をすべて満たす)        |
| `skip`         | false positive / グレーゾーン許容範囲内 (principles の許容範囲に該当) |
```

### 5.3 複数 SoT 間の優先順位

`## 1. SSOT参照` に複数文書が並ぶ場合、矛盾検出時の優先順位は DES-028 §3.4.1 (プロジェクト固有 > 内蔵) に従う。下位カテゴリで規定された内容が上位カテゴリの規定と矛盾する場合、上位を優先し、下位は finding として `create_issue` 推奨で扱う (ルール側更新の起票)。

### 5.4 廃止セクション

`review_criteria_*.md` から以下のセクションを廃止する (旧 criteria に残っていた場合は全面置換時に除去する):

- `## Perspective: <name> — <display>` 形式の固有観点ブロック
- 重大度判定 (`### 🔴致命的` / `### 🟡品質問題` / `### 🟢改善提案` のセクション分け、severity デフォルト表)
- グレーゾーン判定 (`false positive に注意` 形式の警告ブロック)
- 「保守性」「堅牢性」「アーキテクチャ整合性」等の品質特性をレビュー独自観点として記述する箇所

---

## 改定履歴

| 日付       | 変更者  | 内容                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-21 | k2moons | 初版作成 (DES-028 §3.2 草案を起点)。REQ-004 FNC-401 / FNC-402 / FNC-406 / FNC-409 / FNC-411 の SoT として確立                                                                                                                                                                                                                                                                                                                   |
| 2026-05-21 | k2moons | レビュー指摘対応: (1) §3 除外規定を DES-028 §3.2 草案構成に整合させ、冒頭 §3.1〜§3.3 に「P2 対象外 / P3 対象外 / 固有 perspective 追加禁止」を集約 (旧 §3.1〜§3.4 は §3.4〜§3.6 に番号繰り下げ、§1.2/§1.3 から §3.1/§3.2 参照を付与)。(2) §2.2 末尾に注記を追加し、FNC-411 addendum merge 完了までの一時 SoT として `docs/specs/forge-review/principles/*_addendum.md` 4 件を関連文書欄に併記 (DES-028 §5.1 merge 完了時に削除) |
| 2026-05-21 | k2moons | TASK-036 (GROUP-001 5/5) 完了: addendum merge 完了に伴い、関連文書欄の「FNC-411 addendum merge 完了までの一時参照先」行 (L20) と §2.2 末尾の一時 SoT 注記 (L76) を削除し、merge 後の正規 SoT 経路 (`plugins/forge/docs/*_spec.md` 4 ファイル) を「委譲先 principles」として明示する形に整理。改定履歴・DES-028 §5.1 表は merge 経路の歴史的記録として温存                                                                       |
