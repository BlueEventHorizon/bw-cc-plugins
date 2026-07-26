---
name: doc-structure
user-invocable: false
description: |
  Feature 名から specs / rules ドキュメントの実パスを解決する。
  他スキルが Feature に紐づくドキュメントの場所を特定したいときに呼び出す。
argument-hint: ""
---

# doc-structure スキル

## 概要

`.doc_structure.yaml`（config.yaml 互換フォーマット）を読み込み、
ドキュメントのパス解決・Feature 検出・doc_type 判定を行う。

forge 内の他スキルからの呼び出し専用（`user-invocable: false`）。
`.doc_structure.yaml` のパス解決を担う自己完結設計（外部依存なし）。

## `.doc_structure.yaml` が無い場合の共通ハンドオフ [MANDATORY]

以下の各能力の手順中で `.doc_structure.yaml` が見つからない場合は、この手順に従う。
**呼び出し元スキルは個別に存在確認を行わない**（本スキルに一本化する。設定ファイルの
生成自体は責務が大きく異なるため `setup-doc-structure` スキルのまま分離するが、not-found 時の
ハンドオフはここで一元化する）。

1. AskUserQuestion を使用して確認する:
   ```
   .doc_structure.yaml が見つかりません。
   /forge:setup-doc-structure を実行してプロジェクト構造を定義する必要があります。
   今すぐ /forge:setup-doc-structure を実行しますか？
   ```
2. **はい** → Skill ツールで `/forge:setup-doc-structure` を呼び出す。完了後、呼び出し元が
   要求した能力の手順を最初からやり直す（`.doc_structure.yaml` が生成されているはず）。
3. **いいえ** → 呼び出し元へ「`.doc_structure.yaml` が無いため解決できません」と報告して終了する。

## 出力先ディレクトリの解決 [他スキルから参照する場合 MANDATORY]

新規ドキュメントの出力先ディレクトリを求めたい他スキル（start-design 等）は、`.doc_structure.yaml`
の内部スキーマ（`doc_types_map` 等）を自スキルの SKILL.md に書かず、本節を Read して以下の手順に従う。

### 入力

- `doc_type`（抽象カテゴリ名。例: `design` / `plan` / `requirement` / `rule`）
- `feature`（任意。既知の Feature 名。未指定なら Step 3 の存在確認モードになる）
- `category`（省略時 `specs`。ルール文書を扱う場合のみ `rules`）

### 手順

1. `.doc_structure.yaml` を `Read` する。存在しない場合は上記「共通ハンドオフ」に従う。
2. `{category}.doc_types_map` から、値が入力 `doc_type` と一致するエントリ（キー）を1つ探す。
   見つからない場合は「`{doc_type}` に対応するエントリがありません」と報告して終了する。
3. **`feature` が指定されている場合**: エントリのキー（例: `docs/specs/**/design/`）の `*`/`**`
   セグメントを `feature` に置換し、解決済みディレクトリとする（例: `docs/specs/{feature}/design/`）。
4. **`feature` が指定されていない場合**: エントリのキーをそのまま `Glob` パターンとして使い
   （例: `docs/specs/**/design/*.md`）、一致する既存ファイルの有無を確認する。

### 出力

- `feature` 指定時: 解決済みディレクトリのパス
- `feature` 未指定時: 既存ファイルの有無（と一致したファイル一覧）

## 検索対象ディレクトリの解決 [他スキルから参照する場合 MANDATORY]

文書検索（Grep 等）や外部インデックス転送のために対象ディレクトリ一覧を求めたい他スキル
（query-db-rules / update-db-rules 等）は、`.doc_structure.yaml` の `root_dirs`/`patterns.exclude`
を自スキルの SKILL.md に書かず、本節を Read して以下の手順に従う。

### 入力

- `category`（`rules` または `specs`）

### 手順

1. `.doc_structure.yaml` を `Read` する。存在しない場合は上記「共通ハンドオフ」に従う。
2. `{category}.root_dirs` と `{category}.patterns.exclude` を取得する。

### 出力

- `dirs`: `root_dirs` の配列（そのまま）
- `exclude`: `patterns.exclude` の配列
- `filtered_dirs`（参考値）: `dirs` のうち、末尾ディレクトリ名が `exclude` のいずれかに一致するエントリを
  除いた配列（自前でツールに渡す前に除外したい consumer 向け。ネストした除外ディレクトリの混入は
  許容する）

`dirs`/`exclude` をそのまま下流ツール（doc-advisor の `--dirs-json`/`--exclude-json` 等）へ転送する
consumer は `filtered_dirs` を使わず `dirs`/`exclude` を使う。自前で Grep 等に渡す consumer は
`filtered_dirs` を使う。

## spec ルート・短縮名の解決 [他スキルから参照する場合 MANDATORY]

短縮名（例: `main`）・相対パス・絶対パスのいずれかを実ディレクトリへ解決したい他スキル
（merge-specs 等）は、`.doc_structure.yaml` の `root_dirs` を自スキルの SKILL.md に書かず、
本節を Read して以下の手順に従う。**外部ライブラリ（PyYAML 等）は使わない**（プロジェクト規約:
Python は標準ライブラリのみで動作する）。

### 入力

- `alias`（短縮名 / 相対パス / 絶対パスのいずれか）

### 手順

1. `alias` がそのまま存在するディレクトリなら、それを解決結果として終了する。
2. `.doc_structure.yaml` を `Read` する（存在しない場合は上記「共通ハンドオフ」に従う）。
   `specs.root_dirs` の各エントリについて、最初の `*`（または `**`）より前の部分を
   「spec ルート候補」として抽出し、重複を除いて列挙する（例: `specs/*/design/` → spec ルート候補
   `specs/`）。
3. 各 spec ルート候補について `<spec_root>/<alias>/` が存在するか（`Glob` または `Bash`
   `[ -d ... ]` で）確認する。存在すればそれを解決結果とする。
4. いずれの候補にも該当しなければ、「解決できない」ことを呼び出し元へ報告する（呼び出し元が
   AskUserQuestion 等で対応する）。

### 出力

- 解決済みディレクトリパス、または「該当なし」

## スクリプト

`${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py`

### CLI インターフェース

```bash
SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py"

# カテゴリ別のファイル一覧
python3 "$SCRIPT" --type rules
python3 "$SCRIPT" --type specs
python3 "$SCRIPT" --type all

# Feature 一覧（specs の glob パターンから抽出）
python3 "$SCRIPT" --features

# 特定 doc_type のファイル一覧
python3 "$SCRIPT" --doc-type design
python3 "$SCRIPT" --doc-type design --category specs
python3 "$SCRIPT" --doc-type rule --category rules

# バージョン情報
python3 "$SCRIPT" --version

# プロジェクトルート・ファイルパスの指定
python3 "$SCRIPT" --type all --project-root /path/to/project
python3 "$SCRIPT" --type all --doc-structure /path/to/.doc_structure.yaml
```

### 出力形式（JSON）

#### `--type` の出力

```json
{
  "status": "ok",
  "project_root": "/path/to/project",
  "rules": ["docs/rules/coding_standards.md", "docs/rules/git_workflow.md"],
  "specs": ["docs/specs/forge/design/some_design.md", "..."]
}
```

#### `--features` の出力

```json
{
  "status": "ok",
  "features": ["<feature>", "<feature>"]
}
```

#### `--doc-type` の出力

```json
{
  "status": "ok",
  "category": "specs",
  "doc_type": "design",
  "files": ["docs/specs/forge/design/some_design.md", "..."]
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
SCRIPT="${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py"
RESULT=$(python3 "$SCRIPT" --type all)
```

JSON 出力を受け取り、必要なフィールドを利用する。

### パターン 2: Python から import する（同一プラグイン内）

forge プラグイン内の Python スクリプトからは直接 import 可能:

```python
import sys
import os
# resolve_doc_structure.py のパスを追加
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'scripts', 'doc_structure'
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
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  # ... doc-advisor 固有フィールド（forge では無視）

specs:
  root_dirs:
    - "docs/specs/**/design/"
    - "docs/specs/**/plan/"
    - "docs/specs/**/requirement/"
  doc_types_map:
    "docs/specs/**/design/": design
    "docs/specs/**/plan/": plan
    "docs/specs/**/requirement/": requirement
  # ... doc-advisor 固有フィールド（forge では無視）
```

`*` は1階層のみ、`**` は任意の深さにマッチする。サブ Feature（`forge/review-PR/design/` 等）がある場合は `**` を使用する。

### forge が使用するフィールド

| フィールド                    | 用途                                                           |
| ----------------------------- | -------------------------------------------------------------- |
| `{category}.root_dirs`        | ドキュメントディレクトリの一覧（glob パターン `*`, `**` 対応） |
| `{category}.doc_types_map`    | パス → doc_type のマッピング                                   |
| `{category}.patterns.exclude` | 除外パターン                                                   |

### バージョン管理

コメント行 `# doc_structure_version: X.Y` でバージョンを管理する。
メジャーバージョン変更はフォーマットの破壊的変更を意味する。
