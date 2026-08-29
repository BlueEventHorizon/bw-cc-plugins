# 追加 feature frontmatter 定義

本文書は、差分 feature 運用で要件定義書・設計書に付与する frontmatter キーの集約 SoT（単一の真実源）である。判定基準（いつ feature を使うか）・矛盾時の優先度・merge 手順は [additive_development_spec.md](additive_development_spec.md) を参照。本文書は frontmatter のキー定義そのものに専念する。

---

## 1. feature_type（差分 feature の一時マーカー）

**判定**: 「追加 feature か」の判定は [additive_development_spec.md](additive_development_spec.md) §1（適用条件 / 対象外）に従う。判定は変更の実質（分離管理価値・旧仕様との衝突リスク）で行い、main 初期立ち上げ、および分離して管理する価値のない軽微な追記・修正には付与しない（false positive 防止）。

### 1.1 要件定義書（Markdown）

```yaml
---
feature_type: temporary-feature
feature_note:
  - この文書が正。旧仕様（ソースコード・設計書・計画書）と矛盾する場合はこの文書を優先して判断・実装すること。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、旧仕様との齟齬を解消する（merge）。merge は意味の統合であり、文書の物理的な結合ではない。
  - 旧仕様と同一スコープの内容は旧仕様側へ移す。スコープが異なる内容は分離したまま維持し、この文書を残す。
---
```

### 1.2 設計書（Markdown）

```yaml
---
feature_type: temporary-feature
feature_note:
  - 正本は対応する追加 feature 要件定義書（REQ-xxx）。本設計書と旧設計書が矛盾する場合は要件定義書を優先する。
  - 旧仕様ファイルは本 feature 実装完了まで書き換えない。新規ファイル / 新規ディレクトリとして切り出すこと。
  - 本 feature 実装完了後、旧設計書との齟齬を解消する（merge）。merge は意味の統合であり、文書の物理的な結合ではない。
  - 旧設計書と同一スコープの内容は旧設計書側へ移す。スコープが異なる内容は分離したまま維持し、この文書を残す。
---
```

### 1.3 計画書（frontmatter を付与しない）

計画書には frontmatter を付与しない。計画書は `requirements_traceability` で対応する要件定義書（REQ-xxx）を既に参照しており、その要件定義書が §1.1 の `feature_type: temporary-feature` を持つかどうかで、当該計画書が追加 feature のものかを辿って判定できる。計画書自体に重複してマーカーを持たせる必要はない。

計画書は実装完了後に破棄される（[additive_development_spec.md](additive_development_spec.md) §4.3 手順4）ため、要件定義書・設計書と異なり merge 時に分離維持を判断する対象にもならない。

---

## 2. doc_status（文書のライフサイクル状態マーカー）

`feature_type` とは意味論が異なる独立したキーである。差分 feature 運用（旧仕様との優先順位・merge 予定）を示す `feature_type` に対し、`doc_status` は「文書がまだ完全な状態ではない理由」を機械可読に示す。

### 2.1 値域

| 値                | 意味                                                                         |
| ----------------- | ---------------------------------------------------------------------------- |
| `draft`           | 文書自体がまだ AI レビュー・利用者レビューを経ておらず、内容が確定していない |
| `not_implemented` | 文書は確定済みだが、文書が前提とする依存先の機構がまだ実装・設計されていない |

キーを省略した場合、どちらにも該当しない（レビュー完了・依存先も実装済み）とみなす。明示的な `completed` 等の完了を示す値は定義しない（既定の無指定で完了状態を表現する）。

### 2.2 付与対象

要件定義書・設計書（種別を問わない）。計画書には付与しない（§1.3 と同じ理由）。

### 2.3 記法

```yaml
---
doc_status: not_implemented
---
```

`feature_type`/`feature_note` と併記する場合は同一 frontmatter ブロック内に両方のキーを列挙してよい（意味論が独立した別軸のキーであるため、片方の有無はもう片方の判定に影響しない）。

### 2.4 解除条件

- `draft`: レビューが完了し内容が確定した時点でキーを削除する
- `not_implemented`: 依存先の機構が実装され、文書内容が実際の実装と一致した時点でキーを削除する

「削除する」は本文の書き換えではなく、キーの除去のみを指す。

---

## 3. doc-advisor 予約キーとの衝突回避

キー名を `feature_type` / `feature_note` とするのは、`type` / `notes` が doc-advisor のフロントマター規約（`type` は識別マーカーの集合、`notes` は未定義）と衝突するためである。

doc-advisor の frontmatter 予約キー一覧: `type`, `title`, `purpose`, `content_details`, `applicable_tasks`, `keywords`, `body_hash`。`doc_status`（値: `draft` / `not_implemented`）はこの一覧に含まれず、衝突しない。
