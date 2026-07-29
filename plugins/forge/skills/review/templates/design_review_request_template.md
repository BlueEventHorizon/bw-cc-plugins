{{PROTOCOL_HEADER}}

## レビュー依頼（設計書）

レビューのみを行い、対象ファイルを変更しないでください。修正の実施主体は依頼元です。

## レビュー対象

プロジェクトルート: `{{PROJECT_ROOT}}`

対象:

{{TARGET_SCOPE}}

上記の対象を全文読んでレビューしてください。ディレクトリが示されている場合は、その配下の対象文書すべてをレビュー範囲とします。

## 今回の重点観点

{{FOCUS}}

これは下記の参照文書に基づく通常のレビューに**加えて**特に注意を払う対象であり、他の観点を免除するものではありません。`（指定なし）` の場合は通常のレビューのみを行ってください。

## 参照文書

### レビュー観点

- `{{PLUGIN_ROOT}}/docs/criteria/review_criteria_design.md`

### 優先度体系と重大度の判断基準

- `{{PLUGIN_ROOT}}/docs/review_priorities_spec.md`

### 規範（違反を検出する対象）

- `{{PLUGIN_ROOT}}/docs/design_format.md` — 設計書の構成・必須項目
- `{{PLUGIN_ROOT}}/docs/adr_format.md` — ADR の構成・必須項目（対象が ADR の場合）
- `{{PLUGIN_ROOT}}/docs/design_principles_spec.md` — 設計原則
- `{{PLUGIN_ROOT}}/docs/spec_design_boundary_spec.md` — What / How の境界。設計書が要件を再定義していないか
- `{{PLUGIN_ROOT}}/docs/document_style_guide.md` — 文書スタイル。特に §5 文書参照記法と参照先の実在性

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
