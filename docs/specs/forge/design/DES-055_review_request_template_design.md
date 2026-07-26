# DES-055 レビュー依頼テンプレート設計

## メタデータ

| 項目     | 値                               |
| -------- | -------------------------------- |
| 設計 ID  | DES-055                          |
| 関連要件 | REQ-013（FNC-1303 / FNC-1312）   |
| 作成日   | 2026-07-26                       |
| 対象     | forge プラグイン `/forge:review` |

---

## 1. 概要

レビュー依頼本文を、**レビューのパターンごとに 1 枚の自然言語テンプレート**として持ち、スクリプトは動的データの埋め込みと検証のみを行う設計。

得られるもの:

- **テンプレート自体が「レビュアーに何を渡すか」の仕様になる**。仕様と成果物が二重管理にならず、散文のままレビューできる
- パターンごとに固定されるため、パターン間で条件分岐する動的組み立てが不要になる
- 埋め込むデータが正しいかをスクリプトで検証できる（自然言語でありながらテスタブル）

## 2. 制約

### 2.1 スクリプトは散文を持たない [MANDATORY]

依頼本文の文言をスクリプトの文字列リテラルとして持たない。本文をリテラルで組み立てる構造は、レビュー観点に相当する指示文をスクリプトへ書き足せてしまう。観点は criteria / principles にあり、スクリプトにあってはならない。

依頼内容を変えるときはテンプレートを編集する。スクリプトには手を入れない。

### 2.2 対象軸ごとの条件分岐を持たない [MANDATORY]

依頼本文の組み立てに対象軸の分岐を持たない。各テンプレートは自身のパターンだけを完全に記述し、分岐は「どのテンプレートを選ぶか」の 1 段に閉じる。

---

## 3. テンプレート一覧

配置: `plugins/forge/skills/review/templates/`（review スキルのみが使うため skill-owned）

| # | ファイル                                 | パターン                | 対象軸 |
| - | ---------------------------------------- | ----------------------- | ------ |
| 1 | `diff_review_request_template.md`        | 未 commit 差分の全部    | diff   |
| 2 | `branch_review_request_template.md`      | base〜target の全変更   | branch |
| 3 | `code_review_request_template.md`        | 指定したソースコード    | files  |
| 4 | `requirement_review_request_template.md` | 指定した要件定義書      | files  |
| 5 | `design_review_request_template.md`      | 指定した設計書          | files  |
| 6 | `plan_review_request_template.md`        | 指定した計画書          | files  |
| 7 | `uxui_review_request_template.md`        | 指定した UI/UX 関連文書 | files  |

`diff` / `branch` は種別を問わない。未 commit 差分やブランチ差分にはコード・設計書・設定ファイル・`.gitignore` 等が混在するため、種別軸に載らない。

### 3.1 テンプレートが名指しする forge 内蔵観点

| テンプレート  | 名指しする観点文書                                                                                                                                                                                                                             |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `diff`        | criteria 6 種すべて、`review_priorities_spec.md`、`forge_anti_patterns.md`、`spec_design_boundary_spec.md`、`spec_priorities_spec.md`、`scope_proportionality_spec.md`、`design_principles_spec.md`、`plan_principles_spec.md`、各 format 文書 |
| `branch`      | 同上                                                                                                                                                                                                                                           |
| `code`        | `review_criteria_code.md`、`review_priorities_spec.md`、`forge_anti_patterns.md`                                                                                                                                                               |
| `requirement` | `review_criteria_requirement.md`、`review_priorities_spec.md`、`requirement_format.md`、`spec_design_boundary_spec.md`、`spec_priorities_spec.md`                                                                                              |
| `design`      | `review_criteria_design.md`、`review_priorities_spec.md`、`design_format.md`、`adr_format.md`、`design_principles_spec.md`、`spec_design_boundary_spec.md`                                                                                     |
| `plan`        | `review_criteria_plan.md`、`review_priorities_spec.md`、`plan_format.md`、`plan_principles_spec.md`、`scope_proportionality_spec.md`                                                                                                           |
| `uxui`        | `review_criteria_uxui.md`、`review_priorities_spec.md`、`start-uxui-design/docs/` 配下の設計原則                                                                                                                                               |

`diff` / `branch` に全観点を渡す理由: 対象の内容が混在しており、どの観点が必要かを事前に決められない。レビュアー側が対象を見て取捨選択する。

`document_style_guide.md` は含めない。文書執筆者向けの書式規範であり、レビュー観点ではない。

`code` の観点が薄い理由: forge 内蔵にはコード規範がほぼ無く（`forge_anti_patterns.md` 25 行のみ）、コーディング規約・アーキテクチャ規約はプロジェクト側にしかない。テンプレート本文にこの事実を明記し、`query-db-rules` の結果が空だった場合に「観点なしでレビューした」と気づける形にする。

---

## 4. プレースホルダ契約

### 4.1 記法

`{{TOKEN}}` を使う。Markdown のバッククォート・コードブロック・波括弧と衝突せず、埋め込み漏れを機械検出できる。

### 4.2 トークン一覧

| トークン              | 置換値                                               | 使うテンプレート |
| --------------------- | ---------------------------------------------------- | ---------------- |
| `{{PROTOCOL_HEADER}}` | `[msg-review] <種別> review_id=<id> round=<n>`       | 全部             |
| `{{REVIEW_TYPE}}`     | レビュー種別（`diff` / `branch` / `code` / …）       | 全部             |
| `{{PLUGIN_ROOT}}`     | forge プラグインの絶対パス                           | 全部             |
| `{{PROJECT_ROOT}}`    | プロジェクトルートの絶対パス                         | 全部             |
| `{{PROJECT_RULES}}`   | `query-db-rules` の結果パス一覧（Markdown 箇条書き） | 全部             |
| `{{PROJECT_SPECS}}`   | `query-db-specs` の結果パス一覧（Markdown 箇条書き） | 全部             |
| `{{BASE_BRANCH}}`     | 利用者が確認して確定した base ブランチ名             | `branch`         |
| `{{TARGET_BRANCH}}`   | target ブランチ名                                    | `branch`         |
| `{{TARGET_FILES}}`    | 対象ファイル一覧（Markdown 箇条書き）                | `code` 〜 `uxui` |

### 4.3 パスは絶対で渡す [MANDATORY]

`${CLAUDE_PLUGIN_ROOT}` は SKILL.md / agent.md がロードされるときにのみ実行時展開される変数であり、**テンプレートを Read したデータ本文の中では展開されない**。テンプレートに `${CLAUDE_PLUGIN_ROOT}/docs/...` と書いてもレビュアーは解決できない。

したがってテンプレートには `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_code.md` のように書き、スクリプトが `Path(__file__)` から算出した絶対パスへ置換する。プロジェクト文書も同様に `{{PROJECT_ROOT}}` で絶対化する。

**どのファイルを参照するかの決定はテンプレートに静的に残り、絶対パスへの解決だけが動的**になる。

### 4.4 検証（fail-closed）

| 検査                       | 失敗時                                                           |
| -------------------------- | ---------------------------------------------------------------- |
| 未消化トークンの残存       | 埋め込み後に `{{` が残っていたらエラー終了                       |
| 未知トークンの指定         | テンプレートに存在しないトークンを渡したらエラー終了             |
| 改行・CR の混入            | 埋め込む値に改行が含まれていたらエラー終了（プロトコル注入防止） |
| ファイルパスが絶対         | 対象ファイル一覧に絶対パスが混じっていたらエラー終了             |
| テンプレート必須項目の欠落 | `branch` でブランチ名が欠けていたらエラー終了                    |

---

## 5. スクリプトの責務

| スクリプト                | 責務                                                                                 |
| ------------------------- | ------------------------------------------------------------------------------------ |
| `build_review_request.py` | テンプレートを Read → トークン置換 → 検証 → 標準出力へ本文を書く。**散文を持たない** |
| `analyze_branch_point.py` | base ブランチ候補を分岐点解析で列挙する（採用は決めない）                            |
| `resolve_targets.py`      | `--files` の存在検証と、修正フェーズ用 allowlist の供給                              |

`resolve_targets.py` は依頼本文の生成に関与しない。範囲指定（`diff` / `branch`）をファイル一覧へ展開して渡すことは REQ-013 FNC-1312 が禁じている。

---

## 6. テンプレート選択

| 起動                                  | 選択されるテンプレート |
| ------------------------------------- | ---------------------- |
| `/forge:review diff` / 対象軸未指定   | `diff`                 |
| `/forge:review branch`                | `branch`               |
| `/forge:review code --files …`        | `code`                 |
| `/forge:review requirement --files …` | `requirement`          |
| `/forge:review design --files …`      | `design`               |
| `/forge:review plan --files …`        | `plan`                 |
| `/forge:review uxui --files …`        | `uxui`                 |

`--branch` は種別指定を無視する（混在するため）。種別と対象軸の組み合わせが上表に無い場合は、AskUserQuestion でどのパターンとして扱うかを確認する。

---

## 7. テスト設計

| 対象                               | 検証                                                                                         |
| ---------------------------------- | -------------------------------------------------------------------------------------------- |
| トークン置換                       | 全トークンが置換され、`{{` が残らない                                                        |
| 未消化トークン検出                 | データを渡さないとエラー終了する                                                             |
| 未知トークン検出                   | テンプレートに無いトークンを渡すとエラー終了する                                             |
| 改行注入                           | 値に改行を含めるとエラー終了する                                                             |
| 絶対パス解決                       | `{{PLUGIN_ROOT}}` が実在する forge プラグインの絶対パスへ置換される                          |
| テンプレートの網羅性（契約テスト） | 7 テンプレートが実在し、各テンプレートが使うトークンがスクリプトの供給トークン集合に含まれる |
| 観点文書の実在（契約テスト）       | テンプレートが名指しする `{{PLUGIN_ROOT}}` 配下の観点文書が実在する                          |

最後の 2 件は、テンプレートを人が編集したときに参照切れ・トークン不整合を検出するための契約テストである。テンプレートが仕様を兼ねる設計では、テンプレートの誤りがそのまま依頼の誤りになるため必要になる。

---

## 8. 設計判断の根拠

### 8.1 パターンごとにテンプレートを分ける理由

1 枚のテンプレートに条件分岐を持たせると、分岐条件が散文の中に埋もれて「このパターンでは何が渡るのか」が読み取れなくなる。パターンごとに 1 枚なら、そのファイルを読むだけで渡す内容が確定する。動的な組み立てが要らないため、組み立てロジックの誤りという故障モード自体が消える。

共通部分（返信形式契約など）が 7 枚に重複するが、これは許容する。重複を避けるために断片化すると、1 枚を読んで全体が分かるという利点を失う。テンプレートの整合は §7 の契約テストで担保する。

### 8.2 スクリプトを残す理由

散文を持たないなら SKILL 側の手作業で足りるように見えるが、以下は決定論的処理でありスクリプトに残す。

- `review_id` の生成（uuid4）
- プロトコルヘッダの形式（`parse_findings.py` / `wait_for_reply.py` / `filter_review_history.py` が同一形式を前提に噛み合う）
- 絶対パスの算出
- §4.4 の検証群
