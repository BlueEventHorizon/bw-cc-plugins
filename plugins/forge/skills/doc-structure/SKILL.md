---
name: doc-structure
user-invocable: false
description: |
  .doc_structure.yaml（config.yaml 互換フォーマット）のパース・パス解決を行うユーティリティスキル。
  他スキルからの呼び出し専用。doc-advisor でもそのまま利用可能な自己完結設計。
argument-hint: ""
---

# doc-structure スキル

## 概要

`.doc_structure.yaml`（config.yaml 互換フォーマット）を読み込み、
ドキュメントのパス解決・Feature 検出・doc_type 判定を行う。

forge 内の他スキルからの呼び出し専用（`user-invocable: false`）。
doc-advisor がこのスキルをまるごとコピーして使える自己完結設計。

## スクリプト

`${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py`

### CLI インターフェース

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py"

# カテゴリ別のファイル一覧
"$PYTHON" "$SCRIPT" --type rules
"$PYTHON" "$SCRIPT" --type specs
"$PYTHON" "$SCRIPT" --type all

# Feature 一覧（specs の glob パターンから抽出）
"$PYTHON" "$SCRIPT" --features

# 特定 doc_type のファイル一覧
"$PYTHON" "$SCRIPT" --doc-type design
"$PYTHON" "$SCRIPT" --doc-type design --category specs
"$PYTHON" "$SCRIPT" --doc-type rule --category rules

# バージョン情報
"$PYTHON" "$SCRIPT" --version

# プロジェクトルート・ファイルパスの指定
"$PYTHON" "$SCRIPT" --type all --project-root /path/to/project
"$PYTHON" "$SCRIPT" --type all --doc-structure /path/to/.doc_structure.yaml
```

### 出力形式（JSON）

#### `--type` の出力

```json
{
  "status": "ok",
  "project_root": "/path/to/project",
  "rules": ["docs/rules/coding_standards.md", "docs/rules/git_workflow.md"],
  "specs": ["docs/specs/forge/design/doc_structure_format.md", "..."]
}
```

#### `--features` の出力

```json
{
  "status": "ok",
  "features": ["forge", "auth", "payment"]
}
```

#### `--doc-type` の出力

```json
{
  "status": "ok",
  "category": "specs",
  "doc_type": "design",
  "files": ["docs/specs/forge/design/doc_structure_format.md", "..."]
}
```

#### `--version` の出力

```json
{
  "status": "ok",
  "version": "4.4",
  "major_version": 4
}
```

#### エラー時の出力

```json
{
  "status": "error",
  "message": ".doc_structure.yaml が見つかりません: /path/to/.doc_structure.yaml"
}
```

## 他スキルからの呼び出し方 [MANDATORY]

### パターン 1: Bash でスクリプトを直接呼び出す

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
SCRIPT="${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py"
RESULT=$("$PYTHON" "$SCRIPT" --type all)
```

JSON 出力を受け取り、必要なフィールドを利用する。

### パターン 2: Python から import する（同一プラグイン内）

forge プラグイン内の Python スクリプトからは直接 import 可能:

```python
import sys
import os
# resolve_doc_structure.py のパスを追加
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'skills', 'doc-structure', 'scripts'
))
from resolve_doc_structure import (
    load_doc_structure,
    resolve_files,
    resolve_files_by_doc_type,
    detect_features,
    invert_doc_types_map,
    match_path_to_doc_type,
)
```

## .doc_structure.yaml フォーマット

config.yaml 完全互換。forge は `root_dirs`, `doc_types_map`, `patterns.exclude` のみ使用する。
他フィールド（toc_file, checksums_file, work_dir, output, common 等）は無視する。

```yaml
# doc_structure_version: 2.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  # ... doc-advisor 固有フィールド（forge では無視）

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/plan/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/plan/": plan
    "docs/specs/*/requirement/": requirement
  # ... doc-advisor 固有フィールド（forge では無視）
```

### forge が使用するフィールド

| フィールド | 用途 |
|-----------|------|
| `{category}.root_dirs` | ドキュメントディレクトリの一覧（glob パターン対応） |
| `{category}.doc_types_map` | パス → doc_type のマッピング |
| `{category}.patterns.exclude` | 除外パターン |

### バージョン管理

コメント行 `# doc_structure_version: X.Y` でバージョンを管理する。
メジャーバージョン変更はフォーマットの破壊的変更を意味する。
