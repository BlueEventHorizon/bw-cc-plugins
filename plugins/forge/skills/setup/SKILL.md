---
name: setup
description: |
  forge スキルがプロジェクト文書を参照するための .doc_structure.yaml を対話的に生成する。
  初回セットアップ時または文書構造変更時に実行。他の forge スキル（review/create-requirements 等）の前提条件。
  トリガー: "forge の初期設定", "doc structure を作成", "setup document structure"
user-invocable: true
argument-hint: ""
---

# /forge:setup

## 概要

対話的に `.doc_structure.yaml` をプロジェクトルートに作成・更新する。
このファイルはドキュメントの所在を宣言し、他のツール（Doc Advisor, forge 等）がドキュメントを参照できるようにする。

## 実行規則

- プランモードが有効な場合は解除すること。プランモードの解除についてユーザーへの確認は不要。
- `.doc_structure.yaml` がすでに存在する場合は**レビューモード**に切り替えること（現在の内容を表示し、変更を提案する）。

## Procedure

### Step 1: 既存ファイルの確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在する** → 現在の内容を表示し、更新するか再生成するか AskUserQuestion を使用して確認する。
- **存在しない** → Step 2 へ。

### Step 2: ディレクトリスキャン

スクリプトのディレクトリを特定する:

- プラグインとして実行中: プラグインの `scripts/` ディレクトリを使用
- フォールバック: `classify_dirs.py` を一般的な場所から検索

```bash
PYTHON=$(/usr/bin/which python3 2>/dev/null || echo "python3")
"$PYTHON" ${CLAUDE_PLUGIN_ROOT}/scripts/classify_dirs.py
```

スキャン結果（JSON）を取得する。`readme_only: true`（`classify_dirs.py` が出力するメタデータフラグ）のディレクトリは分類対象外としてスキップする。

**空ディレクトリの補完**: スキャン結果に含まれないディレクトリも分類候補に加える。
ドキュメント系の親ディレクトリ（`docs/`, `rules/`, `specs/` 等）配下のサブディレクトリを Glob で探索し、スキャン結果にないものを「空ディレクトリ候補」として追加する。ユーザーに確認するため、スキップしない。

### Step 3: AI による分類判定 [MANDATORY]

同ディレクトリの `classification_rules.md` を Read し、そのルールに従ってスキャン結果の各ディレクトリに category と doc_type を割り当てる。

**進捗表示 [MANDATORY]**: 各ディレクトリの判定ごとに結果をユーザーに表示すること。

```
分類中...
  rules/                   → [category]: rules  [doc_type]: rule
  specs/core/requirements/ → [category]: specs  [doc_type]: requirement
  specs/core/design/       → [category]: specs  [doc_type]: design
  ...
```

### Step 4: 対話的確認

分類結果をユーザーに提示し、確認・調整を求める:

分類結果を番号付き一覧で提示する。glob パスは展開結果も表示する。

提示例:

```
分類結果:
  1. [category]: rules  [doc_type]: rule        → rules/
  2. [category]: specs  [doc_type]: requirement  → specs/*/requirements/
     - specs/login/requirements/
     - specs/auth/requirements/
     - specs/archived/requirements/ *exclude*
     - specs/_template/requirements/
  3. [category]: specs  [doc_type]: design       → specs/*/design/
     - specs/login/design/
     - specs/auth/design/
  4. [category]: specs  [doc_type]: plan         → specs/*/plan/
  5. [category]: specs  [doc_type]: reference    → specs/shared/, specs/issues/

修正・除外したいものはありますか？（例: "archived除外", "5をspecに変更"）
```

AskUserQuestion を使用して確認する（修正・除外の指示がなければそのまま次へ進む）。

- ディレクトリ名（例: "archived除外"）→ 該当する glob パスの `exclude` に追加
- 分類番号（例: "5をspecに変更"）→ category や doc_type を修正
- 問題なければそのまま次へ進む

### Step 5: .doc_structure.yaml の生成

確定した分類結果から `.doc_structure.yaml` を config.yaml 互換フォーマットで生成し、プロジェクトルートに書き出す。
doc-advisor 固有フィールドはデフォルト値で生成する（Quick reference のテンプレートを参照）。

### Step 6: 結果表示

生成したファイルの内容を表示し、次のステップを案内する:

```
.doc_structure.yaml created successfully.

Next steps:
- forge が .doc_structure.yaml を直接参照してレビュー・修正時の参考文書を収集します
- Commit .doc_structure.yaml to version control
```

---

## Schema Reference

See: `docs/specs/forge/design/doc_structure_format.md`

### Quick reference（config.yaml 互換フォーマット）

```yaml
# doc_structure_version: 2.0

# === rules configuration ===
rules:
  root_dirs:
    - <dir_path>
  doc_types_map:
    <dir_path>: <doc_type>
  toc_file: .claude/doc-advisor/toc/rules/rules_toc.yaml
  checksums_file: .claude/doc-advisor/toc/rules/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/rules/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Development documentation search index for query-rules skill"
    metadata_name: "Development Documentation Search Index"

# === specs configuration ===
specs:
  root_dirs:
    - <dir_path>
  doc_types_map:
    <dir_path>: <doc_type>
  toc_file: .claude/doc-advisor/toc/specs/specs_toc.yaml
  checksums_file: .claude/doc-advisor/toc/specs/.toc_checksums.yaml
  work_dir: .claude/doc-advisor/toc/specs/.toc_work/
  patterns:
    target_glob: "**/*.md"
    exclude: []
  output:
    header_comment: "Project specification document search index for query-specs skill"
    metadata_name: "Project Specification Document Search Index"

# === common configuration ===
common:
  parallel:
    max_workers: 5
    fallback_to_serial: true
```

### 生成例（Feature-Based）

```yaml
# doc_structure_version: 2.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule
  # ... doc-advisor フィールド（テンプレートから）

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/plan/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/plan/": plan
    "docs/specs/*/requirement/": requirement
  # ... doc-advisor フィールド（テンプレートから）
```

glob パターン（`*`）を使う場合、root_dirs と doc_types_map の両方に同じパターンを記述する。

### doc_type 定義（固定。全プロジェクト・全プラグインで共通）

| category | doc_type    | 意味                                   | 含まれる文書の例                                                                      |
| -------- | ----------- | -------------------------------------- | ------------------------------------------------------------------------------------- |
| rules    | rule        | 開発プロセスのルール・規約・手順       | コーディング規約、命名規則、Git ワークフロー、レビュー手順、CI/CD ルール              |
| specs    | requirement | 「何を実現するか」のゴール定義         | ユーザーストーリー、機能要件、非機能要件、ビジネスルール、受入条件                    |
| specs    | design      | 「どう構成するか」の技術的構造         | アーキテクチャ設計、DB スキーマ設計、画面設計、シーケンス図、状態遷移図               |
| specs    | plan        | 「どの順で作るか」の作業計画           | タスク分割、実装順序、マイルストーン、スプリント計画、移行計画                        |
| specs    | api         | 外部インターフェースの契約             | REST エンドポイント定義、リクエスト/レスポンス仕様、OpenAPI/Swagger、GraphQL スキーマ |
| specs    | reference   | 判断の根拠となる補助文書               | 技術調査メモ、比較検討資料、外部仕様の要約、議事録、用語集                            |
| specs    | spec        | 上記に該当しない仕様文書（デフォルト） | 分類不明な仕様文書の一時的な受け皿                                                    |
