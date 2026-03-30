---
name: update-version
description: |
  プロジェクトのバージョンを一括更新する。patch/minor/major/直接指定に対応。CHANGELOG 自動反映付き。
  トリガー: "バージョン更新", "バージョンアップ", "version bump"
user-invocable: true
argument-hint: "[target] <patch | minor | major | X.Y.Z>"
---

# /forge:update-version

## 概要

`.version-config.yaml` の設定に基づいて、プロジェクトのバージョンを複数ファイルにわたって一括更新する。

## コマンド構文

```
/forge:update-version [target] <new-version | patch | minor | major>
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
/forge:update-version patch              # 先頭 target をパッチバンプ
/forge:update-version forge 0.1.0       # forge を 0.1.0 に更新
/forge:update-version anvil minor        # anvil をマイナーバンプ
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

スクリプトで新バージョンを計算する:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/calculate_version.py {current_version} {version_spec}
```

JSON 出力から `new` を取得する。`status: "error"` の場合はエラー内容を表示して終了する。
`warning` フィールドが存在する場合は AskUserQuestion を使用して続行を確認する。

```
新バージョン ({target_name}): {new_version}
```

### Step 5: 変更内容の収集 [MANDATORY]

> **このステップはバージョンファイル更新（Step 6）より前に実行する。** バージョン番号を書き換える前にコミット履歴を収集することで、バージョン番号変更のノイズが混入しない。

`.version-config.yaml` の `changelog` セクションが存在する場合に実行する。存在しない場合は Step 6 へスキップする。

#### 5-1. コミット履歴の取得

前バージョンのタグから HEAD までのコミットを取得する:

```bash
# tag_format からタグ名を生成（例: "forge-v0.0.23"）
git log {prev_tag}..HEAD --pretty=format:"%s" --no-merges
```

タグが存在しない場合のフォールバック:

1. CHANGELOG.md を Read し、前バージョンのエントリ日付を取得する（例: `## [0.0.23] - 2026-03-16` → `2026-03-16`）
2. その日付以降のコミットを取得する:
   ```bash
   git log --after="2026-03-16" --pretty=format:"%s" --no-merges
   ```
3. CHANGELOG にも日付がない場合は `git log --oneline -30 --no-merges` で直近のコミットを取得し、AskUserQuestion で範囲を確認する

#### 5-2. CHANGELOG エントリの生成

コミットメッセージを Conventional Commits 形式で分類し、CHANGELOG エントリを AI が作成する:

- `feat:` → 新機能の説明
- `fix:` → 修正内容の説明
- `refactor:` → リファクタリング内容の説明
- 類似した変更はグループ化し、箇条書きの粒度を調整する（1コミット=1行ではなく、意味のある単位でまとめる）

> **注意**: 空のテンプレート（`-` のみ）で済ませない。必ずコミット履歴から内容を記入すること。

生成した CHANGELOG エントリはコンテキストに保持し、Step 7 で挿入する。

### Step 6: ファイルの更新 [MANDATORY]

#### 6-1. version_file の更新

スクリプトでバージョンフィールドを更新する:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/update_version_files.py {version_file} {current_version} {new_version} --version-path {version_path}
```

stdout に更新後の内容が出力される。Write でファイルに書き出す。
stderr の JSON で `status: "error"` の場合はエラー内容を報告して終了する。

#### 6-2. sync_files の更新

`sync_files` リストを順に処理する。各エントリについて:

1. `optional: true` でファイルが存在しない場合 → スキップ（警告なし）
   `optional: false`（デフォルト）でファイルが存在しない場合 → 警告を表示
2. スクリプトで置換を実行。`optional: true` のエントリには `--optional` フラグを付加する:
   - `filter` なし:
     ```bash
     python3 ${CLAUDE_SKILL_DIR}/scripts/update_version_files.py {path} {current_version} {new_version} [--optional]
     ```
   - `filter` あり:
     ```bash
     python3 ${CLAUDE_SKILL_DIR}/scripts/update_version_files.py {path} {current_version} {new_version} --filter "{filter}" [--optional]
     ```
   `--optional` 付きでパターン未マッチ時はスクリプトが `{"status": "skipped"}` を返して exit 0 で終了する。この場合は Write をスキップする。
3. stdout に更新後の内容が出力される。Write でファイルに書き出す。
   stderr の JSON で `status: "error"` の場合はエラー内容を報告して終了する。
   stderr の JSON で `status: "skipped"` の場合は Write をスキップする（optional のパターン未マッチ）。

#### 6-3. 更新完了メッセージ

```
### ✅ バージョン更新完了

| ファイル | 変更 |
|----------|------|
| {version_file} | {current_version} → {new_version} |
| {sync_file_1} | {current_version} → {new_version} |
| ...      |      |
```

### Step 7: CHANGELOG の挿入

Step 5 で生成した CHANGELOG エントリを CHANGELOG ファイルに挿入する。

CHANGELOG ファイルを Read して、最初の `## [` 行の直前にエントリを挿入する:

**keep-a-changelog 形式**（`format: keep-a-changelog`）:

```markdown
## [{new_version}] - {YYYY-MM-DD}

### {target_name}

- **feat**: [機能の説明]
- **fix**: [修正の説明]

```

**simple 形式**（`format: simple`）:

```markdown
## {new_version} - {YYYY-MM-DD}

- [変更の説明]

```

`section_per_target: true` の場合、各 target の変更を `### {target_name}` サブセクションに分ける。

### Step 8: テスト実行

`tests/` ディレクトリが存在する場合のみ実行する:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3
```

テストが失敗した場合は失敗内容を表示し、AskUserQuestion を使用して続行か否かを確認する。

### Step 9: git 操作（設定が有効な場合のみ）

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
  /anvil:commit（推奨）または:
  git add <更新したファイルのパス>
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
