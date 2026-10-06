# レビュー対象の種別と読む文書

reviewer が、レビュー対象 1 件ごとに target 種別を判定し、種別に応じて読む文書を選ぶための文書である。持つのは判定の手順と、種別ごとの文書の対応だけである。規範の本文・レビュー観点の中身は各文書が持つので、ここへ写さない。観点文書から規範への委譲は観点文書の側が持つ。

target 種別は **code / requirement / design / plan / uxui** の 5 つである。ADR は design として扱う。

## 1. 種別の判定

先に設定を引いて種別を決め、決まらないものと細分が要るものだけファイルを読む。設定ファイル `.doc_structure.yaml` を自分で読まない。設定の解釈は script が行う。

### 1.1 設定を引く

対象 1 件につき、`resolve_doc_structure.py` にパスを 1 つ渡す（絶対パス、またはプロジェクトルートからの相対パス。呼び方は reviewer の定義が持つ）。

標準出力は JSON であり、`doc_type` に `plan` / `requirement` / `design` / `adr` のいずれか、または `null`（宣言に合わないパス）が入る。`status` が `ok` でないときは設定を引けていないので、種別を決めずに、レビューを続けず止まる（区別のない失敗として終える）。

### 1.2 返った値から種別を決める

| `doc_type`                       | 次の動作                                          | 種別                                                   |
| -------------------------------- | ------------------------------------------------- | ------------------------------------------------------ |
| `plan`                           | 細分は無い                                        | plan                                                   |
| `requirement` / `design` / `adr` | ファイルを読み、UI を扱う文書か（下記）を見分ける | UI を扱う文書なら uxui。そうでなければ返った種別       |
| `null`                           | ファイルを読み、ソースコードか否かを見分ける      | ソースコードなら code。そうでなければ決まらない（1.3） |

- `adr` は design として扱う。この読み替えは reviewer が行う。script は返さない
- UI を扱う文書とは、デザイントークン・UI コンポーネント・画面・UX 評価を扱う文書、および設計書の UI 設計である。UI を扱う requirement / design も、設定の上では requirement / design の置き場にある
- 名前（ファイル名・ディレクトリ名）だけで種別を当てない。設定が宣言している対応を使うことは、これに当たらない

### 1.3 決まらない対象

設定にもファイルの実体にも当たらず、種別が決まらない対象は、次節の「全 target 種別に共通」の文書だけで見る。推測で 1 つに寄せない。種別が決まらないことは、所見にもエラーにもしない。

## 2. 全 target 種別に共通の文書

すべての対象に適用する。種別が決まった対象には、次節の文書を上乗せする。

| 文書                                                              | 役割                                                                       |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------- |
| [review_criteria_generic.md](review_criteria_generic.md)          | すべての対象に適用するレビュー観点                                         |
| [review_priorities_spec.md](../review_priorities_spec.md)         | 重大度の判断基準                                                           |
| [scope_proportionality_spec.md](../scope_proportionality_spec.md) | 比例性の原則（過剰設計の抑止）                                             |
| [error_classification_spec.md](../error_classification_spec.md)   | エラーとして定義するものと、しないもの（バグ・障害・判定できるもの）の区別 |

## 3. 種別ごとに上乗せする文書

「プロジェクト固有」の欄は、依頼の `references` が運ぶ文書のうち、その種別で用いるものを示す。内蔵の文書はここに挙げたものを直接読む。

### 3.1 code（ソースコード）

| 区分             | 内容                                                                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| レビュー観点     | [review_criteria_code.md](review_criteria_code.md)                                                                            |
| 内蔵規範         | [deterministic_generation_spec.md](../deterministic_generation_spec.md) / [forge_anti_patterns.md](../forge_anti_patterns.md) |
| プロジェクト固有 | 実装・コーディング・出力フォーマット規約                                                                                      |
| 突き合わせ対象   | 対象に対応する関連設計書                                                                                                      |

### 3.2 requirement（要件定義書）

| 区分             | 内容                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| レビュー観点     | [review_criteria_requirement.md](review_criteria_requirement.md)                                                                                                                                                                                                                                                                                                                                                                |
| 内蔵規範         | [requirement_principles_spec.md](../requirement_principles_spec.md) / [requirement_format.md](../requirement_format.md) / [spec_design_boundary_spec.md](../spec_design_boundary_spec.md) / [spec_priorities_spec.md](../spec_priorities_spec.md) / [additive_development_spec.md](../additive_development_spec.md) / [frontmatter_format.md](../frontmatter_format.md) / [document_style_guide.md](../document_style_guide.md) |
| プロジェクト固有 | 文書記述・仕様記述規約                                                                                                                                                                                                                                                                                                                                                                                                          |
| 突き合わせ対象   | 対象ファイル内部 / 関連設計書                                                                                                                                                                                                                                                                                                                                                                                                   |

### 3.3 design（設計書・ADR）

| 区分             | 内容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| レビュー観点     | [review_criteria_design.md](review_criteria_design.md)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| 内蔵規範         | [spec_design_boundary_spec.md](../spec_design_boundary_spec.md) / [design_principles_spec.md](../design_principles_spec.md) / [design_method.md](../design_method.md) / [additive_development_spec.md](../additive_development_spec.md) / [frontmatter_format.md](../frontmatter_format.md) / [adr_format.md](../adr_format.md) / [adr_principles_spec.md](../adr_principles_spec.md) / [document_style_guide.md](../document_style_guide.md) / [deterministic_generation_spec.md](../deterministic_generation_spec.md) / [spec_priorities_spec.md](../spec_priorities_spec.md) |
| プロジェクト固有 | アーキテクチャ・設計規約                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| 突き合わせ対象   | 対象ファイル内部 / 関連要件定義書                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

### 3.4 plan（計画書）

| 区分             | 内容                                                                                                                                                                                                                                |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| レビュー観点     | [review_criteria_plan.md](review_criteria_plan.md)                                                                                                                                                                                  |
| 内蔵規範         | [plan_principles_spec.md](../plan_principles_spec.md) / [additive_development_spec.md](../additive_development_spec.md) / [frontmatter_format.md](../frontmatter_format.md) / [spec_priorities_spec.md](../spec_priorities_spec.md) |
| プロジェクト固有 | 依存関係・ワークフロー規約                                                                                                                                                                                                          |
| 突き合わせ対象   | 対象の計画書内部 / 関連設計書・要件定義書                                                                                                                                                                                           |

### 3.5 uxui（UI / UX に関わる文書）

| 区分             | 内容                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------- |
| レビュー観点     | [review_criteria_uxui.md](review_criteria_uxui.md)                                                            |
| 内蔵規範         | [document_style_guide.md](../document_style_guide.md) / [spec_priorities_spec.md](../spec_priorities_spec.md) |
| プロジェクト固有 | デザインシステム・HIG 準拠規約                                                                                |
| 突き合わせ対象   | 対象ファイル内部 / 関連要件定義書・設計書                                                                     |
