# .doc_structure.yaml フォーマット仕様

> config.yaml 互換フォーマット v4.4 | Created by: k_terada

## 概要

`.doc_structure.yaml` はプロジェクトレベルの設定ファイルで、ドキュメントの配置場所と種別を宣言する。
doc-advisor の `config.yaml` と完全互換のフォーマットを採用し、以下のツールが共通で参照する:

- **forge スキル** — ドキュメント作成先の特定、レビュー対象の解決、Feature 検出
- **Doc Advisor** — ToC 生成のスキャン対象・doc_type 判定
- **resolve_doc_structure.py** — プログラムからのパス解決（JSON 出力）

## ファイル配置

プロジェクトルート（`.git/` と同階層）に `.doc_structure.yaml` として配置する。

## スキーマ

```yaml
# .doc_structure.yaml
# doc_structure_version: 2.0

# === rules configuration ===
rules:
  root_dirs:
    - <directory_path>
  doc_types_map:
    <directory_path>: <doc_type>
  toc_file: <path>                    # doc-advisor 用（forge では無視）
  checksums_file: <path>              # doc-advisor 用（forge では無視）
  work_dir: <path>                    # doc-advisor 用（forge では無視）
  patterns:
    target_glob: "**/*.md"            # doc-advisor 用（forge では無視）
    exclude:
      - <dir_name>
  output:                             # doc-advisor 用（forge では無視）
    header_comment: "<string>"
    metadata_name: "<string>"

# === specs configuration ===
specs:
  root_dirs:
    - <directory_path>
  doc_types_map:
    <directory_path>: <doc_type>
  # ... 同構造

# === common configuration ===
common:                               # doc-advisor 用（forge では無視）
  parallel:
    max_workers: <integer>
    fallback_to_serial: <boolean>
```

### forge が使用するフィールド

| フィールド | 必須 | 型 | 説明 |
|-----------|------|------|------|
| `{category}.root_dirs` | Yes | array[string] | ドキュメントディレクトリ。glob パターン（`*`）対応 |
| `{category}.doc_types_map` | Yes | object | パス → doc_type のマッピング。glob パターン対応 |
| `{category}.patterns.exclude` | No | array[string] | 除外するディレクトリ名 |

### doc-advisor 専用フィールド（forge では無視）

| フィールド | 説明 |
|-----------|------|
| `toc_file` | ToC 出力ファイルパス |
| `checksums_file` | 差分検出用ハッシュファイル |
| `work_dir` | 中間ファイル格納ディレクトリ |
| `patterns.target_glob` | ファイル検索 glob パターン |
| `output.header_comment` | ToC ヘッダーコメント |
| `output.metadata_name` | ToC メタデータ名 |
| `common.parallel` | 並列処理設定 |

## root_dirs

ドキュメントが格納されるディレクトリの一覧。

- パスはプロジェクトルートからの相対パス
- 末尾 `/` 推奨
- glob パターン `*` で1レベルのディレクトリマッチが可能

```yaml
root_dirs:
  - docs/rules/                       # リテラルパス
  - "docs/specs/*/design/"            # glob パターン（全 Feature の design）
  - "docs/specs/*/plan/"              # glob パターン（全 Feature の plan）
```

## doc_types_map

パス → doc_type のマッピング。`root_dirs` の各エントリに対応する doc_type を宣言する。

```yaml
doc_types_map:
  docs/rules/: rule
  "docs/specs/*/design/": design
  "docs/specs/*/plan/": plan
  "docs/specs/*/requirement/": requirement
```

### 推奨 doc_type 名

#### specs カテゴリ

| 名前 | 説明 |
|------|------|
| `requirement` | 機能・非機能要件 |
| `design` | 技術設計書、アーキテクチャ仕様 |
| `plan` | 実装計画、ロードマップ、タスク分割 |
| `api` | API 仕様、エンドポイント定義 |
| `reference` | 参考資料、データ辞書 |

#### rules カテゴリ

| 名前 | 説明 |
|------|------|
| `rule` | 開発規約、コーディング標準 |
| `workflow` | ワークフロー手順 |
| `guide` | ベストプラクティス、ガイド |

## patterns.exclude

除外するディレクトリ名のリスト。

- ディレクトリ名の完全一致でマッチ（ファイル名は対象外）
- パス内の任意の深さでマッチ
- `/` を含むパターンはパス部分文字列としてマッチ

```yaml
patterns:
  exclude:
    - archived
    - _template

# docs/specs/auth/design/a.md         → 対象
# docs/specs/archived/design/a.md     → 除外（"archived" にマッチ）
# docs/specs/_template/design/a.md    → 除外（"_template" にマッチ）
```

## バージョン管理

コメント行でバージョンを管理する:

```yaml
# doc_structure_version: 2.0
```

- フォーマット: `X.Y`（X = メジャー、Y = マイナー）
- メジャーバージョン変更 = フォーマットの破壊的変更
- マイナーバージョン変更 = 後方互換のオプショナルフィールド追加
- 詳細は `doc_structure_version_management.md` を参照

## サンプル

### Flat Structure（単一プロジェクト）

```yaml
# doc_structure_version: 2.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  toc_file: .claude/doc-advisor/toc/rules/rules_toc.yaml
  checksums_file: .claude/doc-advisor/toc/rules/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/rules/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

specs:
  root_dirs:
    - docs/specs/design/
    - docs/specs/plan/
    - docs/specs/requirement/
  doc_types_map:
    docs/specs/design/: design
    docs/specs/plan/: plan
    docs/specs/requirement/: requirement
  toc_file: .claude/doc-advisor/toc/specs/specs_toc.yaml
  checksums_file: .claude/doc-advisor/toc/specs/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/specs/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
```

### Feature-Based Structure（複数 Feature）

```yaml
# doc_structure_version: 2.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  # ... doc-advisor フィールド省略

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/plan/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/plan/": plan
    "docs/specs/*/requirement/": requirement
  # ... doc-advisor フィールド省略
```

この形式では Feature 追加時に `.doc_structure.yaml` の変更は不要。
`docs/specs/payment/design/` ディレクトリを作成するだけで自動的に検出される。

### Feature-Based with Exclude

```yaml
specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/requirement/": requirement
  patterns:
    target_glob: "**/*.md"
    exclude:
      - archived
      - _template
```

## Consumer Guide

### forge スキルから（推奨）

`doc-structure` スキルの `resolve_doc_structure.py` を使用する:

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py"

# 全ファイル一覧
"$PYTHON" "$SCRIPT" --type all

# Feature 一覧
"$PYTHON" "$SCRIPT" --features

# 特定 doc_type のファイル
"$PYTHON" "$SCRIPT" --doc-type design
```

### Python スクリプトから（同一プラグイン内）

```python
from resolve_doc_structure import load_doc_structure, resolve_files

config, _ = load_doc_structure(project_root)
rules_files = resolve_files(config, 'rules', project_root)
specs_files = resolve_files(config, 'specs', project_root)
```

### Doc Advisor から

`.doc_structure.yaml` を `config.yaml` として直接読み込める（フォーマット互換）。
`import_doc_structure.py` による変換は不要。
