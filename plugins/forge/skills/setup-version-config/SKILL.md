---
name: setup-version-config
description: |
  プロジェクトの構造をスキャンして .version-config.yaml を対話的に生成・更新する。
  /forge:bump を使う前提条件として実行する。初回セットアップ時またはプロジェクト構造変更時（プラグイン追加、README フォーマット変更など）に再実行して設定を更新する。
  トリガー: "version config を作成", "バージョン設定を初期化", "setup version config", ".version-config.yaml を作る", "バージョン管理の設定"
user-invocable: true
argument-hint: ""
---

# /forge:setup-version-config

## 概要

プロジェクトをスキャンして `.version-config.yaml` をプロジェクトルートに生成・更新する。
このファイルは `/forge:bump` がどのファイルをどのように更新するかを定義する。

- **初回実行**: バージョンファイル・README・CHANGELOG を自動検出し、設定草案を生成
- **再実行時**: 既存設定とスキャン結果を差分比較し、追加・変更された項目のみ更新

## 実行規則

- プランモードが有効な場合は解除すること。解除のユーザー確認は不要。
- ユーザーへの質問・確認はすべて AskUserQuestion を使用すること。

---

## Procedure

### Step 1: 既存ファイルの確認

`.version-config.yaml` がプロジェクトルートに存在するか確認する。

- **存在する** → 内容を表示し、AskUserQuestion を使用して「更新する / 再生成する / キャンセル」を確認する。
- **存在しない** → Step 2 へ。

### Step 2: プロジェクトスキャン

以下のコマンドでバージョン関連ファイルを検出する:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_version_targets.py"
```

スキャン結果（JSON）を取得し、以下の情報を確認する:

- `version_files`: バージョンを持つファイル一覧（path / type / detected_name / current_version）
- `catalog_files`: マーケットプレイスや一括管理ファイル（marketplace.json 等）
- `readme_files`: ルートの README ファイル
- `changelog`: CHANGELOG ファイルと形式（keep-a-changelog / simple / unknown）

**進捗表示**: スキャン完了後に検出結果を表示する。

```
スキャン完了:
  バージョンファイル: 3件 (forge, anvil, xcode)
  カタログ: .claude-plugin/marketplace.json
  README: README.md, README_ja.md
  CHANGELOG: CHANGELOG.md (keep-a-changelog 形式)
```

### Step 3: 設定草案の生成 [MANDATORY]

スキャン結果を解析して `.version-config.yaml` の草案を生成する。

#### targets の生成ルール

各バージョンファイル（type: plugin.json 等）を1つの target として定義する。

```yaml
targets:
  - name: {detected_name}
    version_file: {path}
    version_path: version           # JSON/TOML の version フィールドパス
```

**catalog_files がある場合**: 各 target の `sync_files` に追加する。
marketplace.json のように複数のエントリを含む場合は `filter` で絞り込む。

```yaml
    sync_files:
      - path: .claude-plugin/marketplace.json
        pattern: '"version": "{version}"'
        filter: '"name": "{name}"'  # 同ブロック内に存在する文字列
```

**readme_files がある場合**: README に含まれるバージョンパターンを推定して追加する。
README の内容を Read してバージョン記載パターンを確認すること。

典型的なテーブルパターン（`| **{name}** | {version} |`）を検出した場合:

```yaml
      - path: README.md
        pattern: '| **{name}** | {version} |'
```

パターンが不明な場合は AI が判断し、設定草案に含めるかをユーザーに確認する。

**optional ファイル**: README_ja.md 等、存在しない可能性があるファイルには `optional: true` を付ける。

```yaml
      - path: README_ja.md
        pattern: '| **{name}** | {version} |'
        optional: true
```

#### changelog の生成ルール

CHANGELOG が検出された場合:

```yaml
changelog:
  file: {changelog.file}
  format: {changelog.format}    # keep-a-changelog / simple / unknown
  git_log_auto: false           # true に変更するとgit logから自動生成
  section_per_target: true      # true: target ごとに ### サブセクション
```

#### git 設定の生成ルール

デフォルト設定を生成する:

```yaml
git:
  tag_format: "{target}-v{version}"    # マルチターゲットの場合。単一は "v{version}"
  commit_message: "chore: bump {target} to {version}"
  auto_tag: false
  auto_commit: false
```

ターゲットが1つのみの場合は `tag_format: "v{version}"` を使用する。

### Step 4: 対話的確認 [MANDATORY]

生成した草案を表示し、AskUserQuestion を使用してユーザーに確認する。

確認すべき事項:
1. 各 target の sync_files が正しいか（不要なファイルがあれば除外）
2. CHANGELOG の `git_log_auto` を有効にするか（git log から自動生成するか）

`git_log_auto: true` を選択した場合は、AskUserQuestion を使用してコミットメッセージ形式を確認する:
- Conventional Commits 形式（`feat:`, `fix:`, `chore:` 等）
- その他（ユーザーが例を提示）

### Step 5: .version-config.yaml の書き出し

確定した設定をプロジェクトルートに `.version-config.yaml` として書き出す。

ファイルの先頭にバージョンマーカーを含める:

```yaml
# version_config_version: 1.0
```

**再実行時（Step 1 で「更新する」を選択した場合）**:
- 既存設定を読み込む
- スキャン結果と差分を比較し、新規追加・変更の項目を AskUserQuestion で確認してから更新する
- 既存の手動カスタマイズは保持する

### Step 6: 結果表示

生成したファイルの内容を表示し、次のステップを案内する:

```
.version-config.yaml を生成しました。

次のステップ:
- /forge:bump [target] patch  でバージョンをバンプできます
- プロジェクト構造が変わった場合は /forge:setup-version-config を再実行してください
- .version-config.yaml をバージョン管理に追加することをお勧めします
```

---

## .version-config.yaml スキーマ

```yaml
# version_config_version: 1.0

targets:
  - name: forge                            # target の論理名（/forge:bump の引数に使う）
    version_file: plugins/forge/.claude-plugin/plugin.json  # バージョン値の読み取り元
    version_path: version                  # JSON/TOML のフィールドパス（ネストは "a.b.c"）
    sync_files:                            # バージョンを同期するファイルリスト
      - path: .claude-plugin/marketplace.json
        pattern: '"version": "{version}"'  # {version} が新バージョンに置換される
        filter: '"name": "forge"'          # 同一コンテキストブロック内に存在すべき文字列（絞り込み）
      - path: README.md
        pattern: '| **forge** | {version} |'
      - path: README_ja.md
        pattern: '| **forge** | {version} |'
        optional: true                     # true: ファイルが存在しない場合はスキップ

changelog:
  file: CHANGELOG.md
  format: keep-a-changelog                # keep-a-changelog / simple
  git_log_auto: false                     # true: git log から変更内容を自動生成
  section_per_target: true                # true: target ごとに ### サブセクション

git:
  tag_format: "{target}-v{version}"       # タグ名のフォーマット。"v{version}" も可
  commit_message: "chore: bump {target} to {version}"
  auto_tag: false                         # true: バージョン更新後に自動タグ作成
  auto_commit: false                      # true: AskUserQuestion で確認後に自動コミット
```
