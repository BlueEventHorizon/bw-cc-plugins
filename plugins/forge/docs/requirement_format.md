# 要件定義書 デフォルトフォーマット

プロジェクト固有の「要件定義書 フォーマット」が見つからない場合に使用する汎用フォーマット。

作成原則: [spec_priorities_spec.md](spec_priorities_spec.md)
要件との境界: [spec_design_boundary_spec.md](spec_design_boundary_spec.md)

---

## 追加 feature 用 frontmatter

**[additive_development_spec.md](additive_development_spec.md) §1 の判定で追加 feature に該当する要件定義書を作成するときに限り**、文書先頭に以下の YAML frontmatter を含めること。判定は変更の実質（分離管理価値・旧仕様との衝突リスク）で行い、文書操作の形式（新規作成か追記か）では判定しない。分離して管理する価値のない軽微な追記・修正、および main の初期立ち上げ時は含めない。

この要件定義書は、旧仕様が古いまま据え置かれている期間の正本である。文書全体がこの性質を持つため、本文ブロックではなく frontmatter にメタ情報として宣言する。

`feature_type: temporary-feature` を付与し、feature_note に①この文書が正本であること②旧仕様ファイルは書き換えず新規ファイル・新規ディレクトリへ切り出すこと③実装完了後に旧仕様との齟齬を解消する（merge）こと④同一スコープの内容は旧仕様側へ移しスコープが異なる内容は分離維持すること、の4点を記載する。frontmatter の正式な文言は [frontmatter_format.md](frontmatter_format.md) §1.1 を参照。

全文書種別（要件・設計・計画）の frontmatter 集約 SoT: [frontmatter_format.md](frontmatter_format.md)
判定基準・矛盾時の優先度・merge 手順: [additive_development_spec.md](additive_development_spec.md) §1

---

## 本体フォーマット

```markdown
<!-- 追加 feature の場合、ここに上記 frontmatter を挿入する -->

# {要件ID} {機能名} 要件定義書

## 概要

{この要件の目的と対象ユーザーを1〜3文で記述}

## 前提条件

- {この機能が利用可能になる条件}

## 要件一覧

### 表示要件

- {画面に表示される要素}

### 操作要件

- {ユーザーが実行できるアクション}
- 入力: {入力値の制約}
- 出力/遷移先: {結果や画面遷移}

### エラーケース

| 条件 | エラーメッセージ / 動作 |
| ---- | ----------------------- |

## 未確定事項

| ID      | 内容 | 期限 |
| ------- | ---- | ---- |
| TBD-001 |      |      |
```

---

## 重大度カタログ

本フォーマットの各規範を、違反時の重大度に対応付ける。レビュー時の severity 判定はこの表を SoT とする。criteria 側で重大度を判定してはならない。

### 追加 feature 用 frontmatter

判定（追加 feature か否か）は [additive_development_spec.md](additive_development_spec.md) §1（適用条件 / 対象外）に従う。判定は変更の実質（分離管理価値・旧仕様との衝突リスク）で行い、main 初期立ち上げ、および分離して管理する価値のない軽微な追記・修正は対象外（false positive 防止）。

| 違反パターン                                                                 | 違反時の重大度 | 理由                                                                       |
| ---------------------------------------------------------------------------- | -------------- | -------------------------------------------------------------------------- |
| 追加 feature 要件定義書に `feature_type: temporary-feature` frontmatter 欠如 | 🟡 major       | 旧仕様との優先関係・merge 予定が宣言されず、生成経路を問わず取りこぼされる |
