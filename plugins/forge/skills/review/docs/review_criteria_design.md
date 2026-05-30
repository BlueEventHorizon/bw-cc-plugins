# design レビュー基準

> SoT: `${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない (REQ-004 FNC-402)。
> severity は委譲先 principles の重大度カタログから取得する (`${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` §2.2)。

## 1. SSOT参照

P1 で照合すべき委譲先文書一覧。各文書は「規範本体 + 重大度カタログ (FNC-411 拡充済み)」を保持する SoT である。複数文書間の優先順位は DES-028 §3.4.1 (プロジェクト固有 > 内蔵) に従う。

| priority | path                                                      | doc_type   | 役割                                                                                               |
| -------- | --------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------- |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` | principles | 要件と設計の境界 (What/How 境界、§4 カテゴリ別ガイド / §6 グレーゾーン、規範本体 + 重大度カタログ) |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md`    | principles | 設計原則 (定量目標の扱い / よくある失敗パターン / 記載すべき内容、規範本体 + 重大度カタログ)       |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md`             | format     | 設計書フォーマット (追加 feature 用 frontmatter `type: temporary-feature-design` の定義)           |
| P1       | `docs/rules/*.md` (プロジェクト固有アーキテクチャ規約)    | rules      | プロジェクト固有のアーキテクチャ・設計規約 (存在する場合のみ、規範本体 + 重大度カタログ)           |
| P2       | target ファイル内部 + 関連要件定義書                      | specs      | 矛盾検出 (target_files 内部の相反記述 + 関連 REQ との整合性を突合)                                 |
| P3       | `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`      | principles | 不要な複雑化判定 (§3.4 直接数値化禁止 / §4 倒錯パターン、Yes/No 判定原則)                          |

委譲先ルールが未整備の場合は forge 内蔵ルールへフォールバック (REQ-004 FNC-405)。プロジェクト固有アーキテクチャ規約が `docs/rules/` に存在しない場合は P1 を内蔵 principles のみで構成する。

## 2. チェック順

種別ごとに「どの委譲先文書から先に読むか」の順序。規範本体は再掲しない:

1. **P1 ルール合致**: `${CLAUDE_PLUGIN_ROOT}/docs/spec_design_boundary_spec.md` (What/How 境界 / §4 カテゴリ別ガイド) → `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` (設計原則 / 失敗パターン) → `${CLAUDE_PLUGIN_ROOT}/docs/design_format.md` (追加 feature 用 frontmatter) → プロジェクト固有アーキテクチャ規約 (`docs/rules/*.md` のうち存在するもの) の順で対象設計書と照合する
   - **追加 feature 文書の frontmatter 必須**: 対象が追加 feature の設計書 (判定基準: `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §1。**main 初期立ち上げ・既存文書の追記更新は対象外** = false positive 防止) の場合、`design_format.md`「追加 feature 用 frontmatter」が定義する `type: temporary-feature-design` frontmatter が文書先頭に付与されているか照合する。欠如時の severity は `design_principles_spec.md` 重大度カタログに従う (本ファイルは severity を宣言しない: FNC-402)
2. **P2 矛盾・齟齬**: target ファイル内部の相反記述 (コンポーネント定義 / データフロー / インターフェース等) を突き合わせ、関連要件定義書 (`docs/specs/<feature>/requirements/*.md`) との整合性も併せて確認する (不足・欠落は P2 対象外)
3. **P3 不要な複雑化**: `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` §3.4 (直接数値化禁止) / §4 (倒錯パターン) を参照し、より少ない要素で同じ目的を達成できる代替案の有無を Yes/No で判定する

## 3. 判定ルール

| recommendation | 採用条件                                                                                                       |
| -------------- | -------------------------------------------------------------------------------------------------------------- |
| `fix`          | 規範違反であり、修正による副作用が限定的な場合                                                                 |
| `create_issue` | ルール未整備で発見した場合 (`${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` §4 の 3 条件をすべて満たす) |
| `skip`         | false positive / グレーゾーン許容範囲内 (principles の許容範囲に該当)                                          |

### `recommendation: create_issue` の 3 条件 (REQ-004 FNC-406)

| # | 条件               | 内容                                                                                                                    |
| - | ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 1 | 該当規定なし       | P1 で参照する SSOT (プロジェクト固有 rules / forge 内蔵 principles / format) のいずれにも該当規定が存在しない           |
| 2 | 再発性または客観性 | 同種の指摘が今回・過去のレビューで複数箇所に観察される (再発性)、または客観的事実で説明可能 (AI 主観の単発判断ではない) |
| 3 | 明文化可能粒度     | ルールとして明文化可能な具体粒度を持ち、Issue として書き起こせる (「主観的にシンプルでない」等の評価語のみは不可)       |

3 条件のいずれかが不成立の場合は `recommendation: skip` (skip_reason に該当条件不成立の理由を記載) とする。
