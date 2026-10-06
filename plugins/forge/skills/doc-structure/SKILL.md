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

## `.doc_structure.yaml` が無い場合の共通ハンドオフ

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

## `doc_type` に対応するエントリが無い場合の共通ハンドオフ

`.doc_structure.yaml` は存在するが、求めた `doc_type` に対応するエントリが `doc_types_map` に無い場合は、この手順に従う。**呼び出し元スキルは独自の既定パスを持たず、ユーザーへ出力先を尋ねもしない**（本スキルに一本化する）。

配置はプロジェクトが `.doc_structure.yaml` で宣言するものであり、forge が決めるものではない。宣言が無いときに既定値を当てはめることも、他の `doc_type` のキーから導出することも、**宣言されていない配置を forge が発明する行為**である。当たっている保証が無く、外れたときは文書が想定外の場所に作られ、後続スキルはそれを見つけられない。

1. AskUserQuestion を使用して確認する:
   ```
   .doc_structure.yaml に doc_type `{doc_type}` に対応するエントリがありません。
   /forge:setup-doc-structure を実行して定義する必要があります。
   今すぐ /forge:setup-doc-structure を実行しますか？
   ```
2. **はい** → Skill ツールで `/forge:setup-doc-structure` を呼び出す。完了後、呼び出し元が要求した能力の手順を最初からやり直す
3. **いいえ** → 呼び出し元へ「`{doc_type}` に対応するエントリが無いため解決できません」と報告して終了する

## script のエラーの共通の扱い

script が終了コード 1 を返し、上記の 2 つの共通ハンドオフ（`.doc_structure.yaml` が無い／`doc_type` のエントリが無い）に
当たらないときは、次に従う。

- JSON の `message` を、そのままユーザーに伝える（AI が読むだけで終わらせない）
- 原因がキーの書き方（`.doc_structure.yaml`）のとき、ユーザーに回答させても解決しない。キーの修正
  （プロジェクトの管理者が行う）か、置き場の直接指定を促す
- 推測で置き場・feature を決めない

## feature の決定 [他スキルから参照する場合 MANDATORY]

作る文書の feature（と出力先）を決めたい他スキル（start-design / start-requirements / start-plan）は、
決定の分岐を自スキルの SKILL.md に書かず、本節に従う。分岐と、キーの解釈は script が行う。

### 入力

- `doc_type`（作る文書の種別。例: `design` / `requirement` / `plan`）
- `feature`（任意。引数で渡された feature 名。**渡されたものを置き換えない**）
- `source_path`（任意。入力の文書のパス。例: 設計書を作るときの要件定義書。分かっていれば渡す）
- `category`（省略時 `specs`）

### 手順

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py" \
  --decide-feature-for {doc_type} [--feature {feature}] [--source-path {source_path}] [--category {category}]
```

- **終了コード 0**: JSON の `decision` に従う。

  | `decision`    | 意味                                                                                                                | 呼び出し元の動作                                                                                                                                           |
  | ------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `argument`    | 引数の feature（`source_path` も渡されたときは、パスから求めた feature と食い違わない場合に限る。食い違えば `ask`） | `feature` と `dir`（出力先）を使う                                                                                                                         |
  | `path`        | `source_path` から求めた（`feature` が `null` なら feature なし）                                                   | `feature` と `dir` を使う                                                                                                                                  |
  | `no-existing` | その doc_type の既存ファイルが無い（完全新規）。feature なし                                                        | `dir` を使う                                                                                                                                               |
  | `ask`         | 決められない                                                                                                        | `reason` を添えて、AskUserQuestion で feature を確認する。`features` に既知の feature、`existing_count` に既存の件数がある。件数が多いときは全件を並べない |

  `feature_applied` が `false` のときは、キーに feature を置く場所が無く、feature は使われていない。呼び出し元へそのことを伝える。
- **終了コード 1**: JSON の `message` に従う。
  - `.doc_structure.yaml` が見つからない → 上記「`.doc_structure.yaml` が無い場合の共通ハンドオフ」
  - `doc_type` のエントリが無い → 上記「`doc_type` に対応するエントリが無い場合の共通ハンドオフ」
  - 置き場を一意に決められない（キーの書き方が未対応、複数のエントリ 等）→ 上記「script のエラーの共通の扱い」に従う

## ID・ファイル名から文書を探す [他スキルから参照する場合 MANDATORY]

パス・ファイル名・ID（`REQ-032` など）で示された文書の実体を求めたい他スキルは、本節に従う。
文書を列挙して選ばせない（件数が多いと成り立たない）。

### 手順

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/doc_structure/resolve_doc_structure.py" \
  --find-in {doc_type} --name {name} [--category {category}]
```

- **終了コード 0**: JSON の `count` と `matches` に従う。`count` が 1 ならその文書、0 なら見つからない、
  2 以上なら、どれかをユーザーに尋ねる（同じ ID が複数の feature にある場合など）
- **終了コード 1**: `doc_type` のエントリが無い。上記「共通ハンドオフ」に従う

## 出力先ディレクトリの解決 [他スキルから参照する場合 MANDATORY]

新規ドキュメントの出力先ディレクトリを求めたい他スキル（start-design 等）は、`.doc_structure.yaml`
の内部スキーマ（`doc_types_map` 等）を自スキルの SKILL.md に書かず、本節を Read して以下の手順に従う。
キーの解釈（`*`/`**` の置換・除去）は script が行う。AI が組み立てない。

### 入力

- `doc_type`（抽象カテゴリ名。例: `design` / `plan` / `requirement` / `rule`）
- `feature`（任意。既知の Feature 名）
- `category`（省略時 `specs`。ルール文書を扱う場合のみ `rules`）

### 手順

次を実行する（`SCRIPT` は下記「スクリプト」の `resolve_doc_structure.py`）。

```bash
python3 "$SCRIPT" --dir-of {doc_type} [--feature {feature}] [--category {category}]
```

- **終了コード 0**: JSON の `dir` が、解決済みの置き場である。`feature` を渡さなければ、feature なしの置き場である。
  `feature_applied` が `false` のときは、キーに feature を置く場所が無く、feature は使われていない。呼び出し元へそのことを伝える
- **終了コード 1**: JSON の `message` に従う。
  - `.doc_structure.yaml` が見つからない → 上記「`.doc_structure.yaml` が無い場合の共通ハンドオフ」
  - `doc_type` のエントリが無い → 上記「`doc_type` に対応するエントリが無い場合の共通ハンドオフ」
  - 置き場を一意に決められない → 上記「script のエラーの共通の扱い」に従う

`feature` を指定しないときの、既存ファイルの有無は、次で求める。

```bash
python3 "$SCRIPT" --doc-type {doc_type} [--category {category}]
```

JSON の `files` が空なら、既存ファイルは無い。

### 出力

- 解決済みディレクトリのパス（`feature` 未指定なら、feature なしの置き場）
- `feature` 未指定時は、既存ファイルの有無（と一致したファイル一覧）

## パスから feature を求める [他スキルから参照する場合 MANDATORY]

ファイルのパス（要件定義書など）から、そのファイルが属する feature を求めたい他スキルは、
`.doc_structure.yaml` のキーの解釈を自スキルの SKILL.md に書かず、本節に従う。解釈は script が行う。

### 入力

- `path`（ファイルのパス。プロジェクトルートからの相対、または絶対）
- `category`（省略時 `specs`）

### 手順

```bash
python3 "$SCRIPT" --feature-of {path} [--category {category}]
```

- **終了コード 0**: JSON の `doc_type` と `feature` を使う。`feature` が `null` のときは、feature なし
  （その種別のトップのディレクトリに置かれている）。feature の下にさらに階層がある場合は、最上位の feature を返す
- **終了コード 1**: `.doc_structure.yaml` が無ければ、上記「共通ハンドオフ」に従う。どのエントリにも一致しない場合は、
  上記「script のエラーの共通の扱い」に従う

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
本節を Read して以下の手順に従う。

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

# 置き場ディレクトリ（feature あり / なし）
python3 "$SCRIPT" --dir-of design --feature forge
python3 "$SCRIPT" --dir-of design

# ファイルのパスから doc_type と feature
python3 "$SCRIPT" --feature-of docs/specs/forge/requirements/REQ-001_x.md

# パスを 1 つ受け取り、doc_types_map の宣言から種別を返す（exclude は適用しない）
python3 "$SCRIPT" --match-path docs/specs/forge/design/DES-001.md
python3 "$SCRIPT" --match-path docs/rules/coding_standards.md --category rules

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

#### `--dir-of` の出力

```json
{
  "status": "ok",
  "category": "specs",
  "doc_type": "design",
  "feature": "forge",
  "dir": "docs/specs/forge/design/",
  "feature_applied": true
}
```

`feature` を渡さなければ `feature` と `feature_applied` は `null` で、`dir` は feature なしの置き場になる。
キーに `*`/`**` セグメントが無いときは、`feature` を渡しても `dir` はキーそのもので、`feature_applied` は `false` になる。
エントリが無い、または置き場を一意に決められない場合は、`status` が `error` で終了コードは `1` になる。

#### `--feature-of` の出力

```json
{
  "status": "ok",
  "category": "specs",
  "path": "docs/specs/forge/requirements/REQ-001_x.md",
  "doc_type": "requirement",
  "feature": "forge",
  "key": "docs/specs/**/requirements/"
}
```

feature なしの置き場にあるファイルは `feature` が `null` になる。どのキーにも一致しない場合は、
`status` が `error` で終了コードは `1` になる。

#### `--match-path` の出力

```json
{
  "status": "ok",
  "category": "specs",
  "path": "docs/specs/forge/design/some_design.md",
  "doc_type": "design"
}
```

`doc_type` は宣言の値（`design` / `plan` / `requirement` / `adr` 等）をそのまま返す。宣言に合わないパスと、プロジェクトルート外のパスは `null`（`--feature-of` はこの 2 つをエラーにする）。

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

## 他スキルからの呼び出し方

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
