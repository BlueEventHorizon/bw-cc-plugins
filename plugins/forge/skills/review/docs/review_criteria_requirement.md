# requirement レビュー基準

> SoT: `${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない (REQ-004 FNC-402)。
> severity は委譲先 principles の重大度カタログから取得する (`${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md` §2.2)。

## 1. SSOT参照

P1 で照合すべき委譲先文書一覧。各文書は「規範本体 + 重大度カタログ (FNC-411 拡充済み)」を保持する SoT である。複数文書間の優先順位は DES-028 §3.4.1 (プロジェクト固有 > 内蔵) に従う。

| priority | path                                                      | doc_type   | 役割                                                                                                                           |
| -------- | --------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------ |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md`        | format     | 要件定義書フォーマット (メタデータ・未確定事項表・必須項目等の規範本体 + 重大度カタログ)                                       |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`      | principles | 仕様優先度・非機能要件カテゴリ網羅性・主目的禁止・倒錯パターン (規範本体 + 重大度カタログ)                                     |
| P1       | `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` | principles | 追加開発ワークフロー (`type: temporary-feature-requirement` 文書の判定基準 §1 / 旧仕様優先度 §2 / P2 矛盾除外規定の前提を提供) |
| P1       | `docs/rules/document_writing_rules.md`                    | rules      | プロジェクト固有の文書記述ルール (規範本体 + 重大度カタログ)                                                                   |
| P2       | target ファイル内部 + 関連設計書との整合性チェック対象    | specs      | 矛盾検出 (要件間の相反記述 / 関連設計書と target_files 間の相反記述を突合。追加 feature 除外規定は §2 P2 節を参照)             |
| P3       | `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md`      | principles | 不要な複雑化判定 (§3.4 直接数値化禁止の許容範囲 / §4 倒錯パターン、Yes/No 判定原則 + 重大度カタログ)                           |

委譲先ルールが未整備の場合は forge 内蔵ルールへフォールバック (REQ-004 FNC-405)。`docs/rules/document_writing_rules.md` が存在しないプロジェクトでは forge 内蔵 (`requirement_format.md` / `spec_priorities_spec.md`) のみで P1 照合を成立させる。

## 2. チェック順

要件定義書種別に合わせ「どの委譲先文書から先に読むか」の順序。規範本体は再掲しない:

1. **P1 ルール合致**: `${CLAUDE_PLUGIN_ROOT}/docs/requirement_format.md` (フォーマット・必須項目・未確定事項表の構造) → `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` (非機能要件カテゴリ網羅性・主目的禁止・倒錯パターン) → `docs/rules/document_writing_rules.md` (プロジェクト固有の文書記述ルール) の順で要件定義書本文と照合する
   - **追加 feature 文書の frontmatter 必須**: 対象が追加 feature の要件定義書 (判定基準: `${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §1。**main 初期立ち上げ・既存文書の追記更新は対象外** = false positive 防止) の場合、`requirement_format.md`「追加 feature 用 frontmatter」が定義する `type: temporary-feature-requirement` frontmatter が文書先頭に付与されているか照合する。欠如時の severity は `requirement_format.md` 重大度カタログに従う (本ファイルは severity を宣言しない: FNC-402)
2. **P2 矛盾・齟齬**: target ファイル内部の要件間 (FNC-xxx 相互参照 / 用語定義 / 優先度) と、関連設計書 (`docs/specs/<feature>/design/*.md`) との間で、同一対象への相反記述 (機能定義 / データモデル / ビジネスゴール紐付け等) を突き合わせる (不足・欠落は P2 対象外、P1 で扱う)
   - **追加 feature 除外規定**: target が追加 feature の要件定義書 (frontmatter `type: temporary-feature-requirement`) の場合、旧仕様 (旧 FNC / 旧 DES / 既存の要件定義書・設計書・計画書・コード) との相反記述は **差分宣言として意図的なもの** であり P2 矛盾扱いしない (`${CLAUDE_PLUGIN_ROOT}/docs/additive_development_spec.md` §2 「追加開発の要件定義書は旧仕様より優先する正本として扱う」)。P2 対象は target 内部の要件間矛盾、または同 feature 内の他の追加文書 (追加 feature の設計書・計画書) との矛盾に限定する
3. **P3 不要な複雑化**: `${CLAUDE_PLUGIN_ROOT}/docs/spec_priorities_spec.md` §3.4 / §4 を参照し、構造品質の直接数値化・ストーリー先行等の倒錯パターン、より少ない要件で同じ目的を達成できる代替案の有無を Yes/No で判定する

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
