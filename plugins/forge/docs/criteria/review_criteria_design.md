# design レビュー基準

> SoT: [review_priorities_spec.md](../review_priorities_spec.md) [MANDATORY]
> 重大度判定 / グレーゾーン許容範囲は委譲先 principles 側を参照すること。本ファイルは判断を持たない。
> severity は委譲先 principles の重大度カタログから取得する ([review_priorities_spec.md](../review_priorities_spec.md) §2.2)。

## 1. SSOT参照

P1 で照合すべき委譲先文書一覧。各文書は「規範本体 + 重大度カタログ (拡充済み)」を保持する SoT である。複数文書間の優先順位は「プロジェクト固有 > 内蔵」とする (review_priorities_spec.md)。

| priority | path                                                                                 | doc_type   | 役割                                                                                                                                                   |
| -------- | ------------------------------------------------------------------------------------ | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| P1       | [spec_design_boundary_spec.md](../spec_design_boundary_spec.md)                      | principles | 要件と設計の境界 (What/How 境界、§4 カテゴリ別ガイド / §6 グレーゾーン、規範本体 + 重大度カタログ)                                                     |
| P1       | [design_principles_spec.md](../design_principles_spec.md)                            | principles | 設計原則 (定量目標の扱い / よくある失敗パターン / 記載すべき内容、規範本体 + 重大度カタログ)                                                           |
| P1       | [design_format.md](../design_format.md)                                              | format     | 設計書フォーマット (追加 feature 用 frontmatter `feature_type: temporary-feature-design` の定義。severity は `design_principles_spec.md` 重大度カタログを参照) |
| P1       | [additive_development_spec.md](../additive_development_spec.md)                      | principles | 追加開発ワークフロー (`feature_type: temporary-feature-design` 文書の判定基準 §1 / 旧仕様優先度 §2 / P2 矛盾除外規定の前提を提供)                              |
| P1       | [adr_format.md](../adr_format.md)                                                    | format     | ADR 書式 (節の構成・必須構成・失効マーカーの記法。severity は宣言しない)                                                                               |
| P1       | [adr_principles_spec.md](../adr_principles_spec.md)                                  | principles | ADR 運用 (書く対象・可変性・失効の扱い・棄却理由の書き方、規範本体 + 重大度カタログ)                                                                   |
| P1       | [document_style_guide.md](../document_style_guide.md)                                | format     | 文書スタイル規約 (§5 文書参照記法・参照の実在性 / §8 関連文書セクション。規範本体 + §5.4 重大度カタログ)                                               |
| P1       | `(query-db-rules: "設計レビューに関するプロジェクト固有のアーキテクチャ・設計規約")` | rules      | プロジェクト固有のアーキテクチャ・設計規約 (存在する場合のみ、規範本体 + 重大度カタログ)                                                               |
| P2       | target ファイル内部 + 関連要件定義書                                                 | specs      | 矛盾検出 (target_files 内部の相反記述 + 関連 REQ との整合性を突合。追加 feature 除外規定は §2 P2 節を参照)                                             |
| P3       | [spec_priorities_spec.md](../spec_priorities_spec.md)                                | principles | 不要な複雑化判定 (§3.4 直接数値化禁止 / §4 倒錯パターン、Yes/No 判定原則)                                                                              |

委譲先ルールが未整備の場合は forge 内蔵ルールへフォールバックする。`(query-db-rules: "設計レビューに関するプロジェクト固有のアーキテクチャ・設計規約")` の解決結果が 0 件の場合は P1 を内蔵 principles のみで構成する。

## 2. チェック順

種別ごとに「どの委譲先文書から先に読むか」の順序。規範本体は再掲しない:

1. **P1 ルール合致**: [spec_design_boundary_spec.md](../spec_design_boundary_spec.md) (What/How 境界 / §4 カテゴリ別ガイド) → [design_principles_spec.md](../design_principles_spec.md) (設計原則 / 失敗パターン) → [design_format.md](../design_format.md) (追加 feature 用 frontmatter) → プロジェクト固有アーキテクチャ規約 (`(query-db-rules: "設計レビューに関するプロジェクト固有のアーキテクチャ・設計規約")` のうち存在するもの) の順で対象設計書と照合する
   - **追加 feature 文書の frontmatter 必須**: 対象が追加 feature の設計書 (判定基準: [additive_development_spec.md](../additive_development_spec.md) §1。判定は変更の実質 [分離管理価値・旧仕様との衝突リスク] で行い、文書操作の形式 [新規作成か追記か] では判定しない。**main 初期立ち上げ・分離して管理する価値のない軽微な追記・修正は対象外** = false positive 防止) の場合、`design_format.md`「追加 feature 用 frontmatter」が定義する `feature_type: temporary-feature-design` frontmatter が文書先頭に付与されているか照合する。欠如時の severity は `design_principles_spec.md` 重大度カタログに従う (本ファイルは severity を宣言しない)
   - **文書参照**: [document_style_guide.md](../document_style_guide.md) §5 / §8 と照合し、対象設計書が他文書へ張る参照の記法と実在性 (リンク先ファイル・見出しアンカーが実在するか、移動・改名・削除した文書を指す参照が残っていないか) を確認する。severity は同文書 §5.4 重大度カタログに従う
   - **ADR 運用**: target_files に ADR (`ADR-*.md`) が含まれる場合、[adr_format.md](../adr_format.md) の必須構成 (コンテキスト / 決定 / 検討した代替案)・節の構成 (`## 1.`〜`## 4.` の 4 節、`###` 小節は親節の番号を継ぐ)・失効マーカーの記法と照合する。あわせて、別 ADR が覆した決定に失効マーカーが付いているか、棄却理由に依拠する前提が書かれているかを確認する。また、対象設計書の変更が設計判断の転換 (選択肢 A → B) を含むのに、対応する ADR の新規作成・更新が伴わない場合も指摘する。severity はいずれも `adr_principles_spec.md` 重大度カタログに従う
2. **P2 矛盾・齟齬**: target ファイル内部の相反記述 (コンポーネント定義 / データフロー / インターフェース等) を突き合わせ、関連要件定義書 (`docs/specs/<feature>/requirements/*.md`) との整合性も併せて確認する (不足・欠落は P2 対象外)
   - **追加 feature 除外規定**: target が追加 feature の設計書 (frontmatter `feature_type: temporary-feature-design`) の場合、旧仕様 (旧 DES / 既存の設計書・要件定義書・計画書・コード) との相反記述は **差分宣言として意図的なもの** であり P2 矛盾扱いしない ([additive_development_spec.md](../additive_development_spec.md) §2 「追加開発の要件定義書は旧仕様より優先する正本として扱う」)。P2 対象は target 内部の設計矛盾、または対応する追加 feature の要件定義書・他の追加 feature 設計書との矛盾に限定する
3. **P3 不要な複雑化**: [spec_priorities_spec.md](../spec_priorities_spec.md) §3.4 (直接数値化禁止) / §4 (倒錯パターン) を参照し、より少ない要素で同じ目的を達成できる代替案の有無を Yes/No で判定する

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
