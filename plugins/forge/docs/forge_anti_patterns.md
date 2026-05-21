# forge アンチパターン集

本文書は forge が配布する `/forge:review` 系 SKILL が **P1 (ルール合致) 照合の fallback として参照する基底アンチパターン集** である。
プロジェクト固有ルール (`docs/rules/`) が未整備または不十分な場合に reviewer が参照し、業界標準のアンチパターン (God Object・循環依存・ハードコード密結合・SQL インジェクション等) との照合に利用する。
本ファイルのスコープは「配布物としての雛形を配置すること」に限定し、初期内容は見出しのみとする。

## AI 自動追記禁止方針 [MANDATORY]

本文書への **AI による自動追記は行わない**。レビュー実行中に新規アンチパターンを発見した場合は、必ず以下のフローに従う:

1. evaluator が `recommendation: create_issue` を付与 (REQ-004 FNC-406 の 3 条件成立時)
2. present-findings から `/anvil:create-issue` 経由で Issue を起票
3. 通常の PR フロー (人によるレビュー + commit + ToC 更新 + テスト) でファイル本体に追記

理由: 配布対象ファイルがレビュー実行中に変わるとリリース管理が破綻するため。網羅範囲・粒度・具体内容の議論は別 Issue に切り出す。

## 関連文書

- 要件: `docs/specs/forge-review/requirements/REQ-004_review_policy.md` (FNC-405 / FNC-406)
- 設計: `docs/specs/forge-review/design/DES-028_review_policy_design.md` (§3.1 / §3.4)
- レビュー優先度 SoT: `${CLAUDE_PLUGIN_ROOT}/docs/review_priorities_spec.md`

## カテゴリ別アンチパターン

### コード

### 設計

### 計画

### 文書
