---
type: temporary-feature-requirement
notes:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、この文書は旧仕様書へ merge され削除される予定。
---

# REQ-004 レビューポリシー要件

## メタデータ

| 項目       | 値                                                     |
| ---------- | ------------------------------------------------------ |
| 要件 ID    | REQ-004                                                |
| プラグイン | forge                                                  |
| Feature    | forge-review (期間限定。完了後に既存仕様へ merge)      |
| 種別       | 要件定義                                               |
| 対象       | `/forge:review` および配下の reviewer/evaluator/fixer  |
| 起点 Issue | #68 「AI reviwer がコトをどんどん複雑にする」          |

---

## 1. 背景

forge の AI レビューは、検出対象の網羅性を優先するあまり、本質的でない指摘・改善提案を大量に生成する。具体的な問題:

1. **過剰提案**: 「修正必須」と「改善提案」が混在し、利用者が選別に消耗する
2. **複雑化への偏向**: 4 スキルを作るだけの計画に対して 27 ステップを生成する等、目的に対して過剰な構造を提案する
3. **緊急度の欠如**: 即時修正すべき項目と、将来的に検討すれば良い項目が同列に並ぶ
4. **二重検出**: ルールで担保されるべき品質特性 (保守性・堅牢性・アーキテクチャ整合性等) を、レビューの独自観点として別途検出することで、ルール違反を二重に指摘している

### 思想転換 — ドキュメント主義への純化

forge は SDD (仕様駆動開発) ベースのツール群であり、設計・実装・レビュー・テストすべてがドキュメント (要件定義書・設計書・ルール文書) を単一の真実源として駆動される。

この前提に立つと、**レビューだけに必要な独自観点が存在するということは、そのルールが設計段階で抜け落ちている証拠**である。レビューは「ドキュメントとの突合」に純化されるべきであり、ドキュメントでカバーできない問題は「ルール追加が必要なサイン」として Issue 化する流れが本来の rules 進化サイクルとなる。

本要件は、レビューを以下の純化された定義に再構築する:

```
レビュー = 優先度 1 (ルール合致)
        + 優先度 2 (内部矛盾検出)
        + 優先度 3 (不要な複雑化検出)
        + ルール抜け落ち発見時の Issue 化
```

これにより、各 criteria が固有に持っていた perspective (logic / resilience / maintainability / architecture / completeness 等) は原則として廃止し、対応するルールへ委譲する。デフォルト挙動は「変更差分のみ × 優先度 1〜3 × 段階的提示」とする。

### 設計時点での情報完全性 [MANDATORY]

レビュー時に適用する判断は、すべて執筆者が **設計時点で参照可能なドキュメント (principles / format / rules)** に明示されていなければならない。

- 「レビュアーだけが知っている判断基準」は許容しない (後出しの gotcha レビューは設計駆動を破壊する)
- 重大度判定 (どの規範違反が 🔴 / 🟡 / 🟢 か) は principles 側に明文化する
- グレーゾーン (How/What 境界の判定が割れやすい論点) の許容範囲も principles 側に明文化する
- criteria は判断を持たず、principles を参照する索引と、レビュー運用上の戦術 (焦点順 / 委譲原則) のみで構成する

criteria に判断が残っている状態 = 設計時点で執筆者から判断基準が隠されている状態。これを防ぐため、本要件は principles の拡充 (重大度カタログ化 + グレーゾーン許容範囲明示化) を併せて要求する (FNC-411)。

### 前提 — レビュー入力は per-flow orchestrator が整える

レビューはフロー固有の文脈 (新規機能 / 追加機能 / 設計監査 / 計画策定 / 実装直後 等) を持ち、入力 (target_files / reference_docs / 委譲先ルール) の集め方はフローによって異なる。

本要件はこの入力準備に立ち入らない。前段の per-flow orchestrator が以下の責務を既に負っている前提でレビューポリシーのみを定義する:

| orchestrator                  | フロー                              | 入力準備の責務                                                                |
| ----------------------------- | ----------------------------------- | ----------------------------------------------------------------------------- |
| `/forge:start-requirements`   | 要件定義書作成 (3 モード)            | Feature 確定 / モード判定 / 既存資産 (コード・Figma) との対応付け              |
| `/forge:start-design`         | 設計書作成                          | 入力要件定義書の特定 / アーキテクチャルール・spec_design_boundary の参照     |
| `/forge:start-plan`           | 計画書作成                          | 入力設計書の特定 / 計画フォーマット規約の参照                                 |
| `/forge:start-implement`      | タスク実装                          | タスク選択 / 関連コード探索 / 計画書更新                                       |
| `/forge:start-uxui-design`    | UXUI デザイン                       | 入力要件定義書の ASCII アート抽出 / HIG・デザインシステム規約の参照            |
| `/forge:review`               | 単体レビュー                        | `.doc_structure.yaml` 解決 → target_files / 関連コード / 参考文書 / perspectives 収集 |

これらは既存定義 (REQ-001 オーケストレータパターン要件 / 各 SKILL.md) に存在する責務であり、本要件で再定義しない。「新規 vs 追加」「ターゲットが何か」「どの文書を参照させるか」は呼び出し時に各 orchestrator が決める。

---

## 2. 要件

### FNC-401: レビュー観点の優先度体系

レビューが検出する観点は以下の 3 つに限定する。各 criteria は固有 perspective を原則として持たない。

#### 優先度 1: ルール合致

対象がプロジェクトルール・forge 内蔵ルール・関連仕様書に沿っているか。

- 判定方法: 関連ルール文書を Read し、対象と照合する
- 対象ルール: `docs/rules/` (プロジェクト固有) / `plugins/forge/docs/` (forge 内蔵) / 関連仕様書 (`docs/specs/`)
- アーキテクチャ・コーディング規約・命名規則・設計原則・セキュリティ規約等、本来「品質を担保するためのルール」はすべてここで照合される

#### 優先度 2: 矛盾・齟齬

文書内 / コード内 / 文書とコードの間で相反する記述が存在するか。

- 判定方法: 同一対象への異なる記述を突き合わせる
- **不足・欠落の検出は対象外** (網羅性確認のための観点ではない)

#### 優先度 3: 不要な複雑化

より少ない要素 (ステップ・クラス・抽象・分岐) で同じ目的を達成できる代替案が存在するか。

- 判定方法 (Yes/No): 代替案が存在 AND 既存案にそれを正当化する rationale が無い場合に Yes
- 「シンプルさ」「読みやすさ」等の主観評価には拡張しない (Goodhart の罠回避: `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` §3.2)

### FNC-402: 固有 perspective の廃止と criteria の判断除去

`review_criteria_*.md` が持っていた criteria 固有 perspective を廃止する。これに加えて、criteria は **一切の判断 (severity 判定 / グレーゾーン判定) を持たない** ことを必須とする。判断はすべて principles 側 (重大度カタログ化 + グレーゾーン許容範囲明示化、FNC-411) に集約する。

廃止対象 perspective (現状):

| criteria        | 廃止対象 perspective                                              | 委譲先 (ルール / 仕様)                                |
| --------------- | ----------------------------------------------------------------- | ----------------------------------------------------- |
| code            | logic / resilience / maintainability                              | コーディング規約 / セキュリティ規約 / 設計書          |
| design          | alignment / architecture / resilience                             | アーキテクチャルール / spec_design_boundary_spec      |
| requirement     | completeness / consistency / verifiability                        | requirement_format / spec_priorities_spec             |
| plan            | alignment / feasibility                                           | 計画フォーマット規約 / 依存関係ルール                 |
| uxui            | hig_compliance / usability / visual_system / distinctiveness      | HIG / デザインシステム規約 / UX 設計原則              |
| generic         | (分割なし)                                                        | 文書スタイル規約 / 汎用文書規約                       |

#### criteria が持つもの / 持たないもの

| 区分               | criteria が持つか | 配置                                |
| ------------------ | ----------------- | ----------------------------------- |
| 委譲先ルール文書 (SSOT 索引) | **持つ**            | criteria                            |
| 焦点順 (どこから読むか)      | **持つ** (運用戦術) | criteria                            |
| 委譲原則 (fix / Issue化 / skip の切替) | **持つ** (運用フロー) | criteria                            |
| 重大度マッピング (規範違反 → 🔴/🟡/🟢) | 持たない             | principles (重大度カタログ、FNC-411) |
| グレーゾーン許容範囲 (How/What 境界の判定) | 持たない             | principles (許容範囲明示、FNC-411)   |
| 規範本体 (執筆者が遵守すべき決まり) | 持たない             | principles / format / style_guide   |

委譲先ルールが未整備の場合は **FNC-405 (forge 内蔵ルールのフォールバック)** および **FNC-406 (ルール抜け落ち Issue 化)** が動作する。

### FNC-403: 対象指定 (対象軸)

レビュー対象は **対象軸フラグを明示する** ことで決定する。デフォルト (フラグ未指定) は `--diff` と同等。`scope` 軸 (diff / file / crossref の 3 段階) は採用しない。

| 呼び出し                                                  | 動作                                            |
| --------------------------------------------------------- | ----------------------------------------------- |
| `/forge:review <種別>`                                    | `--diff` と等価 (デフォルト・MVP)                |
| `/forge:review <種別> --diff`                             | 現ブランチ差分のみレビュー (明示形)              |
| `/forge:review <種別> --files a.md,b.md`                  | 指定ファイル群を全文レビュー (カンマ区切り)      |

#### フラグ定義

| フラグ        | 値             | 役割                                                                              |
| ------------- | -------------- | --------------------------------------------------------------------------------- |
| `--diff`      | (値なし)       | 現ブランチの未 commit 差分のみを対象とする。**未指定時のデフォルト**              |
| `--files`     | カンマ区切り   | 指定ファイル群を全文レビュー。`--diff` と排他                                     |

#### 制約

- `--diff` と `--files` は **排他** (同時指定はエラー)
- `--files` の値はカンマ区切り (`a.md,b.md,c.md`)
- 行範囲指定 (`a.md:30-50` 等) ・セクション限定指定は採用しない (運用が複雑化する / 行番号は変動するため AI 誤生成の温床になる)

#### Feature 名 / ディレクトリ指定の扱い

per-flow orchestrator (`/forge:start-design` 等) は Feature 名から該当ファイル群を解決して `--files` 値に展開し、`/forge:review` を呼ぶ。`/forge:review` 自体は「解決済みファイルリストを受け取る」責務のみ。

ユーザーが Feature 名・ディレクトリ等で直接 `/forge:review` を呼んだ場合は、`/forge:review` 内部で `.doc_structure.yaml` を経由して該当ファイル群に解決し、内部的に `--files` 相当として扱う (既存挙動を維持)。

#### `--diff` 時の比較基準

`--diff` (明示 or デフォルト) で差分レビューを行う場合、比較基準を以下のいずれかに確定する必要がある (TBD-401):

- 現ブランチの未 commit 差分のみ
- 現ブランチと `main` (デフォルトブランチ) の差分
- ユーザー指定 base との差分

### FNC-404: 介入軸 (interaction)

検出後の処理方法は **介入軸フラグを明示する** ことで決定する。デフォルト (フラグ未指定) は `--interactive` と同等。

| 介入モード          | CLI                            | デフォルト | 動作                                                |
| ------------------- | ------------------------------ | ---------- | --------------------------------------------------- |
| **--interactive**   | (引数なし) / `--interactive`   | ✅         | 段階的提示 (🔴 → 🟡 → 🟢 の順)。**未指定時のデフォルト** |
| **--auto-critical** | `--auto-critical`              |            | 🔴 のみ自動修正                                     |
| **--auto N**        | `--auto N`                     |            | **指摘件数 N 件** を severity 順で先頭から自動修正  |
| **--auto**          | `--auto`                       |            | 全件 (全指摘) 自動修正 (高リスク・明示警告を表示)    |

#### フラグ定義

| フラグ           | 値          | 役割                                                                                  |
| ---------------- | ----------- | ------------------------------------------------------------------------------------- |
| `--interactive`  | (値なし)    | 段階的提示 (present-findings) で人間判断を仲介。**未指定時のデフォルト**              |
| `--auto-critical` | (値なし)   | 🔴 (critical) のみ自動修正                                                            |
| `--auto`         | 整数 or なし | 整数 N: **指摘件数 N 件** を severity 順で先頭から自動修正 / なし: 全件 (全指摘) 自動修正 |

#### 制約

- `--interactive` / `--auto-critical` / `--auto` は **すべて相互排他**。複数指定はエラー (early validation で拒否)
- severity フィルタは介入軸でのみ機能する。検出段階では全 severity を出力する

### FNC-405: forge 内蔵ルールのフォールバック

プロジェクト固有ルール (`docs/rules/`) が未整備または不十分な場合、forge 内蔵ルール (`plugins/forge/docs/`) が基本ルール群として常に有効化される。

- 既存の rules_toc.yaml (32 エントリ) が土台となる
- 業界標準のアンチパターン集 (God Object・循環依存・ハードコード密結合・SQL インジェクション等) の **雛形ファイルを `plugins/forge/docs/forge_anti_patterns.md` として配置** する。本要件のスコープは「ファイルを作成・配置するのみ」に限定し、初期内容は空または見出しのみとする。各アンチパターンの説明は **1 エントリあたり簡潔に 2 行まで** とし、AI が運用過程で自動追記する。網羅範囲・粒度・具体内容の議論は **別 Issue** に切り出す
- プロジェクト固有ルールと内蔵ルールが衝突するときは、プロジェクト固有ルールを優先する

### FNC-406: ルール抜け落ち発見時の Issue 化

レビューが「明文ルールでカバーできないが指摘すべき問題」を発見した場合、**ルール追加を促す Issue を起票する**フローを提供する。これにより本来の rules 進化サイクルが回る。

- 検出した内容と、追加すべきルールの草案を Issue 本文に含める
- 既存の `/anvil:create-issue` に連携する
- `recommendation` 列に新値 `create_issue` を追加する
- ユーザーは present-findings 段階で「これは Issue 化する」を選択できる

### FNC-407: デフォルト挙動の明示

`/forge:review <種別>` (フラグなし) の挙動は以下と等価。デフォルトは「対象軸=`--diff`」「介入軸=`--interactive`」の組み合わせ:

```
/forge:review <種別>  ≡  /forge:review <種別> --diff --interactive
                      ≡  対象=変更差分のみ
                      × 介入=段階的提示 (present-findings)
                      × 検出=優先度 1〜3
```

Issue #68 で求められた「軽量レビュー」を最少コマンドで実現する。明示形 (`--diff --interactive`) と引数なしは等価であり、AI agent / 利用者が「デフォルト時の挙動」を取り違えないよう、フラグを書いた呼び出しも常にサポートする。

廃止する軸:

- **scope 軸 (diff / file / crossref)**: `--diff` / `--files` の二択で表現する (FNC-403)。crossref は per-flow orchestrator の reference_docs 収集責務に吸収
- **depth 軸**: 観点は優先度 1〜3 で固定。固有 perspective を持たないため、depth で段階的に観点を増減させる必要が無い

### FNC-408: デフォルト変更の周知

固有 perspective 廃止 + デフォルト挙動変更は破壊的変更であるため、利用者が認識できる仕組みを持つ。

- CHANGELOG / リリースノートで明示する
- `/forge:review` 初回実行時、または検出が以前より大幅に減ったセッションで、案内を 1 回表示する

> 別形式の移行ガイド (Markdown ドキュメント等) は作成しない (人間が読まない前提のため)

### FNC-409: criteria の固定 3 セクション構造

`review_criteria_*.md` の各ファイルは以下の 3 セクション固定構造を持つ。**判断 (severity / グレーゾーン判定) を持たない**ことが必須:

1. **委譲先 SSOT** — 優先度 1 で照合すべき principles / format / rules / 仕様書 文書一覧。重大度判定は principles 側 (FNC-411) を MANDATORY 参照
2. **焦点順** — 種別ごとの「principles のどの節から先に読むか」の順序ガイド。規範本体は principles に置き、criteria は索引と順序のみ
3. **委譲原則** — recommendation:fix / create_issue / skip の切替条件 (運用フロー)

廃止セクション:

- `## Perspective:` 形式の固有観点ブロック
- 重大度判定 (criteria 側で 🔴/🟡/🟢 を割り振っていた箇所)
- グレーゾーン判定 (criteria 側で false positive 警告を持っていた箇所)
- 「保守性」「堅牢性」「アーキテクチャ整合性」等の品質特性をレビュー独自観点として記述する箇所

単一の真実源 (SoT) として `review_priorities_spec.md` (新設) を `plugins/forge/docs/` に置き、各 criteria はこれを MANDATORY 参照する。

### FNC-411: principles 拡充 (重大度カタログ化 + グレーゾーン許容範囲明示化)

criteria から判断を除去するための前提として、principles 側を以下の通り拡充する。

#### 重大度カタログ化

各 principles 文書の規範ごとに、違反時の重大度 (🔴 致命的 / 🟡 品質問題 / 🟢 改善提案) を明示する。

| principles 文書                                          | 拡充内容                                                                       |
| --------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`      | §1 Yes/No判定 / §3 主目的禁止 / §4 倒錯パターン の各規範に重大度を付与          |
| `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` | §4 カテゴリ別ガイドの各項目 / §6 グレーゾーンの判定に重大度を付与               |
| `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`    | 「よくある失敗パターン」「定量目標の扱い」等の規範に重大度を付与                 |
| `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`      | タスク粒度 / 必読列 / グループ化判定 等の規範に重大度を付与                     |

#### グレーゾーン許容範囲の明示化

判定が割れやすい論点 (§6 グレーゾーン等) について、「どの解釈を許容し、どれを許容しないか」を断定で明示する。レビュー時の false positive 警告を criteria 側に持たせず、principles で執筆者にも見える形にする。

#### 拡充の入力資料

Issue #74 で抽出された 18 項目 (現行 criteria に含まれる「ルール化されるべき判断基準」と元 criteria 抜粋) を入力リストとして使う。各項目は以下のいずれかに分類して取り込む:

- (a) 既存 principles の規範に重大度を追加するだけで吸収できる項目
- (b) 既存 principles のグレーゾーン許容範囲として明示化する項目
- (c) 新規の principles 規範 (または新規 rule 文書) が必要な項目

詳細な分類と作業計画は設計書 (DES-028) の Appendix A に保全する。

### FNC-410: AI が誤判定しにくい CLI 構造

CLI の表現を以下の最小集合に限定する。対象軸・介入軸ともに **デフォルト相当のフラグ (`--diff` / `--interactive`) を明示形として提供** し、省略時の振る舞いを誤解させない:

```
/forge:review <種別> [--diff | --files a.md,b.md,...] [--interactive | --auto-critical | --auto [N]]
```

| 軸       | フラグ                                         | 既定値                       |
| -------- | ---------------------------------------------- | ---------------------------- |
| 対象軸   | `--diff` / `--files`                           | `--diff` (未指定時)          |
| 介入軸   | `--interactive` / `--auto-critical` / `--auto` | `--interactive` (未指定時)   |

設計指針:

- 位置引数は **種別 1 個のみ**。ファイル指定は `--files` フラグに統一 (位置引数とフラグの責務分離)
- **デフォルト挙動を明示するフラグ (`--diff` / `--interactive`) を必ず提供** する。省略形と明示形が等価であることを REQ-004 / DES-028 の両方で示し、AI 生成時に「省略時の挙動が何か」を取り違えないようにする
- 各フラグは独立。値の限定列挙 (`--files`: ファイル名カンマ列 / `--auto`: 整数 or なし / その他 boolean) で AI が型を誤らない
- 最頻ユースケース (差分のみ × 段階的提示) は **引数なしで動く**ようデフォルトを徹底する
- 不正な組み合わせは early validation で拒否する。代表例:
  - `--diff --files a.md` (対象軸の二重指定)
  - `--interactive --auto-critical` / `--auto --auto-critical` 等 (介入軸の二重指定)
- プリセット (例: `--audit`) は導入しない (新たな複雑化を生まないため)
- 行範囲指定 (`a.md:30-50` 等) ・セクション限定指定 (`--section "4.1"` 等) は採用しない (運用が複雑化する / 行番号や見出し構造は変動するため AI 誤生成の温床になる)

---

## 3. 適用対象

| 対象                                | 影響                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------- |
| `/forge:review` SKILL.md            | 2 軸フラグ (scope / interaction) の追加・デフォルト変更                             |
| `/forge:reviewer` SKILL.md          | 優先度 1〜3 に基づく検出制御 (固有 perspective ロジック削除)                        |
| `/forge:evaluator` SKILL.md         | 5 観点精査と優先度 1〜3 の関係明示                                                  |
| `/forge:present-findings` SKILL.md  | 段階的提示の severity 順制御、Issue 化選択肢追加                                    |
| `/forge:fixer` SKILL.md             | --auto-critical / --auto N / --auto への対応                                        |
| `review_criteria_*.md` (全 6 種)    | 固有 perspective 廃止、3 セクション固定構造 (委譲先 SSOT / 焦点順 / 委譲原則) に置換。判断 (severity / グレーゾーン) は持たない |
| `plugins/forge/docs/spec_priorities_spec.md`      | 各規範に重大度カタログを追加 (FNC-411)                              |
| `plugins/forge/docs/spec_design_boundary_spec.md` | §4 / §6 に重大度・グレーゾーン許容範囲を追加 (FNC-411)              |
| `plugins/forge/docs/design_principles_spec.md`    | 規範に重大度を追加 (FNC-411)                                        |
| `plugins/forge/docs/plan_principles_spec.md`      | 規範に重大度を追加 (FNC-411)                                        |
| `plugins/forge/docs/` (新設文書)    | `review_priorities_spec.md` を新規作成 (配置先: `plugins/forge/docs/` 直下)         |
| `plugins/forge/docs/` (新設・空)    | `forge_anti_patterns.md` を **空ファイル (見出しのみ) として新規作成**。内容拡充は別 Issue。AI が運用過程で 1 エントリ 2 行までで自動追記 |
| `/anvil:create-issue` 連携          | `recommendation: create_issue` 経由でレビュー結果を Issue 化                        |
| `session.yaml` / plan.yaml          | `recommendation` 列に `create_issue` 値を追加                                       |
| per-flow orchestrator (start-*)     | フロー固有の入力準備責務は本要件の前提として維持 (本要件では再定義しない)            |

---

## 4. 未確定事項

| ID      | 内容                                                                                                                          | 期限     |
| ------- | ----------------------------------------------------------------------------------------------------------------------------- | -------- |
| TBD-401 | `--diff` (明示 or 未指定時のデフォルト) の比較基準 (HEAD / main / 指定 base のどれをデフォルトにするか)                       | 設計時   |
| TBD-406 | evaluator が持つ 5 観点精査 (ルール照合・設計意図・副作用リスク・false positive・対象ファイル確認) と優先度 1〜3 の関係       | 設計時   |
| TBD-407 | `--auto` (全件無制限) を最終的に残すか撤去するか (現方針: 残すが明示警告。AI agent の誤用リスクを設計時に再評価)               | 設計時   |
| TBD-408 | 2 軸 × 介入 4 モードの組み合わせで AI agent が誤った指定を生成しないための CLI 設計手段                                       | 設計時   |
| TBD-409 | uxui の hig_compliance / usability / visual_system / distinctiveness を委譲する具体ルール文書の整備 (HIG・デザインシステム規約等) | 設計時   |
| TBD-410 | requirement criteria の completeness が担っていた「網羅性確認」(必須要件の欠落検出等) を、優先度 1 のどのルールで担保するか     | 設計時   |
| TBD-411 | レビューが「ルール抜け落ち」と判定する基準 (どこから Issue 化対象とするか) — 主観発散を防ぐ判定軸                              | 設計時   |
| TBD-412 | ルール未整備プロジェクトでの動作確認手段 (forge 内蔵ルールのみで一定の検出が成立するかを検証する方法)                          | 設計時   |
| TBD-413 | principles 拡充 (FNC-411) の段取り — 18 項目を一括取り込みか段階取り込みか、(a)(b)(c) 分類の確定方法                            | 設計時   |
| TBD-414 | TBD-410 (網羅性) は FNC-411 の principles 拡充に吸収される見込み。Issue #74 項目 10「非機能要件カテゴリ網羅性ルール」の取り込み先確定 | 設計時   |

---

## 5. 関連文書

- 起点 Issue: #68 「AI reviwer がコトをどんどん複雑にする」
- Feature: forge-review (`docs/specs/forge-review/`)
- 関連要件: REQ-001 オーケストレータパターン要件
- 関連設計 (既存): DES-015 レビューワークフロー設計 / DES-021 レビュー perspective 分割設計 / DES-022 並列 agent 出力契約
- 関連 forge 内部仕様 (FNC-411 で拡充対象): `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` / `${CLAUDE_PLUGIN_ROOT}/docs/plan_principles_spec.md`
- 設計書: `docs/specs/forge-review/design/DES-028_review_policy_design.md`
- 派生 Issue (close 済み・情報は DES-028 Appendix A に保全): #74 「レビュー観点をルール文書化する」

---

## 6. 変更履歴

| 日付       | 変更者   | 内容                                                                                                                      |
| ---------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-19 | k2moons  | 初版作成 (Issue #68 起点)                                                                                                  |
| 2026-05-19 | k2moons  | 3 軸直交設計に改訂 (depth/scope/interaction)。severity を depth から分離。--auto-critical 復活                              |
| 2026-05-19 | k2moons  | SDD 思想に純化。固有 perspective 原則廃止、depth 軸廃止 (2 軸構成)、Issue 化導線統合、内蔵ルールフォールバック明示          |
| 2026-05-19 | k2moons  | per-flow orchestrator (start-design/start-plan/start-implement/start-requirements/start-uxui-design/review) の入力準備責務を本要件の前提として明示 |
| 2026-05-19 | k2moons  | FNC-403 改訂: scope 軸 (diff/file/crossref) を撤廃し `--files a.md,b.md` + `--section "4.1"` に統一。crossref は orchestrator の reference_docs 責務に吸収。行範囲指定は不採用 |
| 2026-05-20 | k2moons  | デフォルト挙動を明示するフラグを追加: 対象軸に `--diff` (デフォルト) を、介入軸に `--user` (デフォルト=段階的提示) を導入。省略形と明示形が等価であることを FNC-403 / 404 / 407 / 410 で明文化 |
| 2026-05-20 | k2moons  | TBD-402 解消: `--auto N` の N を「指摘件数」と確定。FNC-404 / FNC-410 の文言を「先頭 N 件」から「指摘件数 N 件」に明確化し、未確定事項表から TBD-402 を削除 |
| 2026-05-20 | k2moons  | TBD-403 削除 (移行ガイドは作成しない / 人間が読まない前提)。TBD-404 解消: `review_priorities_spec.md` 配置先を `plugins/forge/docs/` 直下と確定。TBD-405 解消: アンチパターン集は `forge_anti_patterns.md` を空ファイル新設のみ、内容は別 Issue / AI が 2 行以内で自動追記 |
| 2026-05-20 | k2moons  | 介入軸フラグ名を `--user` → `--interactive` に改名 (元のフラグ名に整合)。`--section "4.1"` (セクション限定指定) を仕様 DROP (運用が複雑化するため)。FNC-403 / 404 / 407 / 410 を更新 |
| 2026-05-20 | k2moons  | forge-review feature 化 (`docs/specs/forge-review/` 配下に移動)。frontmatter `type: temporary-feature-requirement` を付与。§1 に「設計時点での情報完全性」原則を追加。FNC-402 を改訂し criteria が判断を持たないことを明文化。FNC-409 を 3 セクション固定構造 (委譲先 SSOT / 焦点順 / 委譲原則) に再定義。FNC-411 (principles 拡充: 重大度カタログ化 + グレーゾーン許容範囲明示化) を新設。Issue #74 を close し情報は DES-028 Appendix A に保全。TBD-413 / TBD-414 を追加 |
