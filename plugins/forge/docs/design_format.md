# 設計書 デフォルトフォーマット

プロジェクト固有の「設計書 フォーマット」が見つからない場合に使用する汎用フォーマット。

作成原則: [design_principles_spec.md](design_principles_spec.md)
要件との境界: [spec_design_boundary_spec.md](spec_design_boundary_spec.md)

---

## 追加 feature 用 frontmatter

**追加 feature に属する設計書（判定は [additive_development_spec.md](additive_development_spec.md) §1）を作成するときに限り**、文書先頭に以下の YAML frontmatter を含めること。判定は変更の実質（分離管理価値・旧仕様との衝突リスク）で行い、文書操作の形式（新規作成か追記か）では判定しない。分離して管理する価値のない軽微な追記・修正、および既存仕様が存在しない初回立ち上げ時は含めない。

この設計書は、その対象範囲において旧設計書を置き換えている。旧設計書の記述はまだ更新されていないだけである。文書全体がこの性質を持つため、本文ブロックではなく frontmatter にメタ情報として宣言する。

`feature_type: temporary-feature` を付与し、feature_note に①本設計書が対象範囲における現在の設計であり旧設計書の記述は置き換わっていること（対応する追加 feature 要件定義書（REQ-xxx）と食い違う場合は要件定義書に従う）②旧仕様ファイルは書き換えず新規ファイル・新規ディレクトリへ切り出すこと③実装完了後に旧設計書との齟齬を解消する（merge）こと④同一スコープの内容は旧設計書側へ移しスコープが異なる内容は分離維持すること、の4点を記載する。frontmatter の正式な文言は [frontmatter_format.md](frontmatter_format.md) §1.2 を参照。

正式定義（全文書種別の集約 SoT）: [frontmatter_format.md](frontmatter_format.md)
判定基準・旧仕様の置き換え・merge 手順: [additive_development_spec.md](additive_development_spec.md) §1

---

## 設計ID

| ID prefix | 対象           | 主な用途                           |
| --------- | -------------- | ---------------------------------- |
| `DES-xxx` | 設計書（汎用） | モジュール設計・画面設計・機能設計 |

ADR（`ADR-xxx`）は別の文書型であり、書式は [adr_format.md](adr_format.md)、配置・採番・運用は [adr_principles_spec.md](adr_principles_spec.md) が定める。

---

## テンプレート

````markdown
<!-- 追加 feature の場合、ここに上記「追加 feature 用 frontmatter」を挿入する -->

# {設計ID} {機能名} 設計書

## 1. 概要

{この設計が解決する課題と採用したアプローチを1〜3文で記述}

## 2. アーキテクチャ概要

{コンポーネント図・レイヤー構成・責務の分担を記述}

## 3. モジュール設計

### 3.1 モジュール一覧

| モジュール名 | 責務 | 依存 |
| ------------ | ---- | ---- |

### 3.2 クラス図

{Mermaid 形式のクラス図}

## 4. ユースケース設計

### 4.1 ユースケース一覧

| ユースケース | 説明 |
| ------------ | ---- |

### 4.2 シーケンス図

```mermaid
sequenceDiagram
    actor User
    ...
```
````

**前提条件**: {このユースケースが成立する条件}
**正常フロー**: {主要なステップ}
**エラーフロー**: {エラー時の処理}

## 5. 使用する既存コンポーネント

| コンポーネント | ファイルパス | 用途 |
| -------------- | ------------ | ---- |

## 6. テスト設計

- **単体テスト対象**: {テストすべきモジュール・メソッド}
- **統合テスト対象**: {結合して確認すべきフロー}

```
```
