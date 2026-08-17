# plan レビュー基準

> SoT: [review_priorities_spec.md](../review_priorities_spec.md) [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない。
> severity は委譲先 principles の重大度カタログから取得する ([review_priorities_spec.md](../review_priorities_spec.md) §2.2)。

## 1. SSOT参照

P1 で照合すべき委譲先文書一覧。各文書は「規範本体 + 重大度カタログ (拡充済み)」を保持する SoT である。複数文書間の優先順位は「プロジェクト固有 > 内蔵」とする (review_priorities_spec.md)。

| priority | path                                                                                     | doc_type   | 役割                                                                                                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| P1       | [plan_principles_spec.md](../plan_principles_spec.md)                                    | principles | タスク粒度 / 受け入れ基準 / 「やるべき内容」記載原則 / `required_reading` フィールド / タスクグループ / 並列実行可能タスク / 暗黙依存 / トレーサビリティ (規範本体 + 重大度カタログ、A.11/A.12/A.14 取り込み済み) |
| P1       | [additive_development_spec.md](../additive_development_spec.md)                          | principles | 追加開発ワークフロー (`type: temporary-feature-plan` マーカーの判定基準 §1 / 旧仕様優先度 §2 / P2 矛盾除外規定の前提を提供)                                                                                       |
| P1       | [document_style_guide.md](../document_style_guide.md)                                    | format     | 文書スタイル規約のうち §5.3 参照の実在性のみ (計画書は YAML であり Markdown 記法規定 §5.1 は適用しない)。severity は同文書 §5.4 重大度カタログ                                                                    |
| P1       | `(query-db-rules: "計画書レビューに関するプロジェクト固有の依存関係・ワークフロー規約")` | rules      | プロジェクト固有の依存関係・ワークフロー規約 (規範本体 + 重大度カタログ、query-db-rules で動的解決)                                                                                                               |
| P1       | `docs/specs/<feature>/design/*.md` / `docs/specs/<feature>/requirements/*.md`            | specs      | 計画書が参照する関連設計書・要件定義書 (依存関係ルール、規範本体 + 重大度カタログ)                                                                                                                                |
| P2       | target plan.yaml 内部 + 関連設計書・要件定義書との整合性チェック対象                     | specs      | 矛盾検出 (タスク内容と要件・設計の相反記述、P1 で参照した設計書・要件定義書 + target plan.yaml 間の突合。追加 feature 除外規定は §2 P2 節を参照)                                                                  |
| P3       | [spec_priorities_spec.md](../spec_priorities_spec.md)                                    | principles | 不要な複雑化判定 (§3.4 直接数値化禁止 / §4 倒錯パターン、Yes/No 判定原則、拡充後はアンチパターン重大度カタログ)                                                                                                   |

委譲先ルールが未整備の場合は forge 内蔵ルールへフォールバックする。

## 2. チェック順

種別ごとに「どの委譲先文書から先に読むか」の順序。規範本体は再掲しない:

1. **P1 ルール合致**: [plan_principles_spec.md](../plan_principles_spec.md) → 関連 `docs/specs/<feature>/design/*.md` / `docs/specs/<feature>/requirements/*.md` → `(query-db-rules: "計画書レビューに関するプロジェクト固有の依存関係・ワークフロー規約")` (プロジェクト固有の依存関係・ワークフロー規約) の順で対象 plan.yaml と照合する (タスク内容の原則 → 要件・設計との対応 → プロジェクト固有 rules。YAML 構造・必須フィールドは計画書生成 script が保証するため対象外)
   - **追加 feature 文書の frontmatter 必須**: 対象が追加 feature の計画書 (判定基準: [additive_development_spec.md](../additive_development_spec.md) §1。判定は変更の実質 [分離管理価値・旧仕様との衝突リスク] で行い、文書操作の形式 [新規作成か追記か] では判定しない。**main 初期立ち上げ・分離して管理する価値のない軽微な追記・修正は対象外** = false positive 防止) の場合、[additive_development_spec.md](../additive_development_spec.md) §6-3 が定める `type: temporary-feature-plan` マーカーが付与されているか照合する。欠如時の severity は `plan_principles_spec.md` 重大度カタログに従う (本ファイルは severity を宣言しない)
   - **参照パスの実在性**: [document_style_guide.md](../document_style_guide.md) §5.3 と照合し、`required_reading` および `design_id` 等が指す文書・パスが実在するかを確認する。Markdown リンク記法 (§5.1) は YAML である計画書には適用しない。severity は同文書 §5.4 重大度カタログに従う
2. **P2 矛盾・齟齬**: P1 で参照した設計書・要件定義書と target plan.yaml 内部の間で、同一対象への相反記述 (タスク内容と要件・設計の矛盾、タスク間の依存順序矛盾、タスク内部の自己矛盾等) を突き合わせる (不足・欠落は P2 対象外で P1 ルール照合に委ねる)
   - **追加 feature 除外規定**: target が追加 feature の計画書 (ファイル先頭のマーカーコメントブロック `# type: temporary-feature-plan`) の場合、旧仕様 (既存の計画書・設計書・要件定義書・コード) との相反記述は **差分宣言として意図的なもの** であり P2 矛盾扱いしない ([additive_development_spec.md](../additive_development_spec.md) §2 「追加開発の要件定義書は旧仕様より優先する正本として扱う」)。P2 対象は target 内部のタスク矛盾・依存順序矛盾、または対応する追加 feature の要件定義書・設計書との矛盾に限定する
3. **P3 不要な複雑化**: [spec_priorities_spec.md](../spec_priorities_spec.md) §3.4 / §4 を参照し、より少ない要素 (タスク・依存・フェーズ) で同じ目的を達成できる代替案の有無、および倒錯パターン (タスク粒度の過剰分割等) の有無を Yes/No で判定する

## 3. 判定ルール

| recommendation | 採用条件                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------- |
| `fix`          | 規範違反であり、修正による副作用が限定的な場合                                                                    |
| `create_issue` | ルール未整備で発見した場合 ([review_priorities_spec.md](../review_priorities_spec.md) §4 の 3 条件をすべて満たす) |
| `skip`         | false positive / グレーゾーン許容範囲内 (principles の許容範囲に該当)                                             |

### `recommendation: create_issue` の 3 条件

| # | 条件               | 内容                                                                                                                    |
| - | ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| 1 | 該当規定なし       | P1 で参照する SSOT (プロジェクト固有 rules / forge 内蔵 principles / format) のいずれにも該当規定が存在しない           |
| 2 | 再発性または客観性 | 同種の指摘が今回・過去のレビューで複数箇所に観察される (再発性)、または客観的事実で説明可能 (AI 主観の単発判断ではない) |
| 3 | 明文化可能粒度     | ルールとして明文化可能な具体粒度を持ち、Issue として書き起こせる (「主観的にシンプルでない」等の評価語のみは不可)       |

3 条件のいずれかが不成立の場合は `recommendation: skip` (skip_reason に該当条件不成立の理由を記載) とする。
