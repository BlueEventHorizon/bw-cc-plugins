---
name: bump
description: |
  .version-config.yaml の設定に従いプロジェクトのバージョンを一括更新する。
  patch / minor / major バンプまたは直接バージョン指定に対応。
  CHANGELOG への git log 自動反映、git commit/tag 作成オプション付き。
  前提条件: .version-config.yaml が存在すること（/forge:setup-version-config で生成）。
  トリガー: "バージョンアップ", "version bump", "バージョンを上げる", "/forge:bump", "patch リリース", "minor バンプ"
user-invocable: true
argument-hint: "[target] <patch | minor | major | X.Y.Z>"
---

# /forge:bump

## 概要

`.version-config.yaml` の設定に基づいて、プロジェクトのバージョンを複数ファイルにわたって一括更新する。

## コマンド構文

```
/forge:bump [target] <new-version | patch | minor | major>
```

| 引数            | 説明                                                       |
| --------------- | ---------------------------------------------------------- |
| `target`        | 対象 target 名（省略時: targets の先頭、または唯一の target）|
| `new-version`   | バージョン番号を直接指定（例: `1.2.3`）                    |
| `patch`         | パッチバージョンをインクリメント（`0.0.11` → `0.0.12`）    |
| `minor`         | マイナーバージョンをインクリメント（`0.0.11` → `0.1.0`）   |
| `major`         | メジャーバージョンをインクリメント（`0.0.11` → `1.0.0`）   |

### 使用例

```
/forge:bump patch              # 先頭 target をパッチバンプ
/forge:bump forge 0.1.0       # forge を 0.1.0 に更新
/forge:bump anvil minor        # anvil をマイナーバンプ
```

---

## ワークフロー

### Step 1: 設定ファイルの確認

`.version-config.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → エラーを表示して終了:
  ```
  エラー: .version-config.yaml が見つかりません。
  先に /forge:setup-version-config を実行してください。
  ```
- **存在する** → Read して内容を解析する

### Step 2: 引数解析

`$ARGUMENTS` を解析する:

- `targets` に含まれる名前 → `target_name` として使用し、残りを `version_spec` に
- バージョン番号またはバンプ種別のみ → `target_name` は targets の先頭を使用
- 引数なし → AskUserQuestion を使用して target と version_spec を確認する

既知の target 名は `.version-config.yaml` の `targets[].name` から取得する。

### Step 3: 現在のバージョンを読み取る

指定 target の `version_file` を Read し、`version_path` が指すフィールドからバージョンを取得する。

```
現在のバージョン (forge): 0.0.18
```

### Step 4: 新バージョンを決定する

| `version_spec`       | 計算方法               |
| -------------------- | ---------------------- |
| `patch`              | `X.Y.Z` → `X.Y.(Z+1)` |
| `minor`              | `X.Y.Z` → `X.(Y+1).0` |
| `major`              | `X.Y.Z` → `(X+1).0.0` |
| 数値（例: `1.2.3`）  | そのまま使用           |

バージョンが `major.minor.patch` 形式でない場合はエラーを表示して終了する。

新バージョンが現バージョン以下の場合は AskUserQuestion を使用して続行を確認する。

```
新バージョン (forge): 0.0.19
```

### Step 5: ファイルの更新 [MANDATORY]

#### 5-1. version_file の更新

対象 target の `version_file` を Read して、`version_path` のフィールドを `{current_version}` → `{new_version}` に Edit する。

#### 5-2. sync_files の更新

`sync_files` リストを順に処理する。各エントリについて:

1. `path` のファイルを Read する
   - `optional: true` でファイルが存在しない場合 → スキップ（警告なし）
   - `optional: false`（デフォルト）でファイルが存在しない場合 → 警告を表示
2. `filter` が指定されている場合:
   - `filter` 文字列が存在する行を起点に、同一ブロック（前後の空行区切り）内の `pattern` を特定する
   - 複数 target を含む JSON ファイルで特定 target の version のみを更新する用途
3. `pattern` の `{version}` を `{current_version}` → `{new_version}` に Edit する

#### 5-3. 更新完了メッセージ

```
### ✅ バージョン更新完了

| ファイル | 変更 |
|----------|------|
| {version_file} | {current_version} → {new_version} |
| {sync_file_1} | {current_version} → {new_version} |
| ...      |      |
```

### Step 6: CHANGELOG の更新

`.version-config.yaml` の `changelog` セクションが存在する場合に実行する。

#### `git_log_auto: false`（デフォルト）

CHANGELOG ファイルを Read して、最初の `## [` 行の直前に空テンプレートを挿入する:

**keep-a-changelog 形式**（`format: keep-a-changelog`）:

```markdown
## [{new_version}] - {YYYY-MM-DD}

### {target_name}

-

```

**simple 形式**（`format: simple`）:

```markdown
## {new_version} - {YYYY-MM-DD}

-

```

#### `git_log_auto: true`

前バージョンのタグから HEAD までのコミットを取得して CHANGELOG に反映する:

```bash
# 前バージョンタグを探す（tag_format に従って生成）
PREV_VERSION={current_version}
TAG_FORMAT={git.tag_format}  # 例: "{target}-v{version}" → "forge-v0.0.18"
git log {prev_tag}..HEAD --pretty=format:"%s" --no-merges
```

Conventional Commits の場合はタイプ別に分類して挿入する:
- `feat:` → `### Added`
- `fix:` → `### Fixed`
- `chore:`, その他 → `### Changed`

`section_per_target: true` の場合、各 target の変更を `### {target_name}` サブセクションに分ける。

### Step 7: テスト実行

`tests/` ディレクトリが存在する場合のみ実行する:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
```

テストが失敗した場合は失敗内容を表示し、AskUserQuestion を使用して続行か否かを確認する。

### Step 8: git 操作（設定が有効な場合のみ）

`.version-config.yaml` の `git` セクションに基づいて処理する。

`auto_commit: true` の場合: AskUserQuestion を使用して以下の git 操作を確認する:

```
git commit -m "{commit_message}"  # 例: "chore: bump forge to 0.0.19"
```

`auto_tag: true` かつコミット成功の場合: タグを作成する:

```bash
git tag {tag}  # 例: "forge-v0.0.19"
```

`auto_commit: false`（デフォルト）の場合: git 操作は行わず、以下のコマンドを案内する:

```
変更をコミットするには:
  git add .
  git commit -m "{commit_message}"
  git tag {tag}
```

---

## エラーハンドリング

| エラー                         | 対応                                                              |
| ------------------------------ | ----------------------------------------------------------------- |
| `.version-config.yaml` がない  | エラーを表示し `/forge:setup-version-config` の実行を案内        |
| 引数なし                       | AskUserQuestion を使用して target と version_spec を確認         |
| 不正な target 名               | 有効な target 名の一覧を表示して終了                              |
| 不正なバージョン形式           | 「バージョン形式が不正です（例: 1.2.3）」と表示して終了          |
| 新バージョン ≦ 現バージョン    | AskUserQuestion を使用して続行を確認                              |
| sync_file の pattern が見つからない | 警告を表示して次のファイルへ進む（処理は継続）                |
| テスト失敗                     | 内容を表示し AskUserQuestion を使用して続行を確認                 |
