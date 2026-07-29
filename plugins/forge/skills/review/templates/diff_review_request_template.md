{{PROTOCOL_HEADER}}

## レビュー依頼（未 commit 差分）

レビューのみを行い、対象ファイルを変更しないでください。修正の実施主体は依頼元です。

## レビュー対象

作業ツリーの未 commit 変更（staged / unstaged）および未追跡ファイルのすべてが対象です。

**対象ファイルの一覧は渡しません。追加・変更・削除・リネームのすべてを、あなた自身が差分から確定してレビューしてください。**

削除とリネームも変更の一部です。特に次を見てください。

- 削除された文書・コードへの参照が、残ったファイルに生きていないか
- リネームされたファイルの旧パスを指す参照が残っていないか
- 消してはいけないものが消えていないか（規範・契約・テストの喪失）

対象にはコード・設計文書・要件定義書・計画書・設定ファイル・`.gitignore` 等が混在します。種別ごとの観点は下記からその対象に該当するものを選んで適用してください。

プロジェクトルート: `{{PROJECT_ROOT}}`

## 今回の重点観点

{{FOCUS}}

これは下記の参照文書に基づく通常のレビューに**加えて**特に注意を払う対象であり、他の観点を免除するものではありません。`（指定なし）` の場合は通常のレビューのみを行ってください。

## 参照文書

### レビュー観点（種別別。対象に該当するものを使う）

- コード: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_code.md`
- 設計書: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_design.md`
- 要件定義書: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_requirement.md`
- 計画書: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_plan.md`
- UI/UX: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_uxui.md`
- 上記に当てはまらないもの: `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_generic.md`

### 優先度体系と重大度の判断基準

- `{{PLUGIN_ROOT}}/docs/review_priorities_spec.md`

### 規範（違反を検出する対象）

- `{{PLUGIN_ROOT}}/docs/forge_anti_patterns.md`
- `{{PLUGIN_ROOT}}/docs/spec_design_boundary_spec.md`
- `{{PLUGIN_ROOT}}/docs/spec_priorities_spec.md`
- `{{PLUGIN_ROOT}}/docs/scope_proportionality_spec.md`
- `{{PLUGIN_ROOT}}/docs/design_principles_spec.md`
- `{{PLUGIN_ROOT}}/docs/plan_principles_spec.md`

### 文書フォーマット

- `{{PLUGIN_ROOT}}/docs/requirement_format.md`
- `{{PLUGIN_ROOT}}/docs/design_format.md`
- `{{PLUGIN_ROOT}}/docs/adr_format.md`
- `{{PLUGIN_ROOT}}/docs/plan_format.md`
- `{{PLUGIN_ROOT}}/docs/spec_format.md`
- `{{PLUGIN_ROOT}}/docs/document_style_guide.md`

### プロジェクト固有のルール文書

{{PROJECT_RULES}}

### 関連するプロジェクト仕様書

{{PROJECT_SPECS}}

## 返信形式契約

所見は自由記述 markdown で記述し、各所見に重大度マーカー（🔴 critical / 🟡 major / 🟢 minor）と `ファイルパス:行` の位置情報を付与してください。

返信の最終行には、次のいずれかの完了宣言行を必ず 1 行だけ置いてください。

- `REVIEW_RESULT: approved`（指摘なし・承認）
- `REVIEW_RESULT: findings`（指摘あり）

この完了宣言行は受信側の完了判定で機械的に照合される唯一の契約です。それ以外の本文は自由記述で構いません。

改めて明記します: 対象ファイルを変更しないでください。ファイルの変更は禁止です。
