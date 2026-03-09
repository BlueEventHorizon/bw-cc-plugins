---
name: update-version
description: |
  プラグインのバージョンを一括更新する。
  plugin.json / marketplace.json / README.md の3ファイルを同期し、テストで整合性を確認する。
  トリガー: "バージョン更新", "version bump", "update-version"
user-invocable: true
argument-hint: "[plugin-name] <new-version | patch | minor | major>"
---

# /update-version Skill

プラグインのバージョン番号を複数ファイルにわたって一括更新する。

## コマンド構文

```
/update-version [plugin-name] <new-version | patch | minor | major>
```

| 引数 | 説明 |
|------|------|
| `plugin-name` | 対象プラグイン名（省略時: `forge`） |
| `new-version` | バージョン番号を直接指定（例: `0.0.12`） |
| `patch` | パッチバージョンをインクリメント（`0.0.11` → `0.0.12`） |
| `minor` | マイナーバージョンをインクリメント（`0.0.11` → `0.1.0`） |
| `major` | メジャーバージョンをインクリメント（`0.0.11` → `1.0.0`） |

### 使用例

```bash
/update-version 0.0.12            # forge を 0.0.12 に更新
/update-version patch             # forge をパッチバンプ
/update-version forge 0.0.12     # forge を明示的に指定して 0.0.12 に更新
/update-version forge minor       # forge をマイナーバンプ
```

---

## ワークフロー

### Step 1: 引数解析

`$ARGUMENTS` を解析する:
- 第1引数が既知のプラグイン名（`forge` / `anvil` / `xcode`）→ `plugin_name` として使用し、残りを `version_spec` に
- 第1引数がバージョン番号またはバンプ種別 → `plugin_name = "forge"`（デフォルト）、第1引数を `version_spec` に

既知のプラグイン名は `.claude-plugin/marketplace.json` の `plugins[].name` から取得する。

### Step 2: 現在のバージョンを読み取る

`plugins/{plugin_name}/.claude-plugin/plugin.json` を Read し、`version` フィールドを取得する。

```
現在のバージョン: {current_version}
```

### Step 3: 新バージョンを決定する

| `version_spec` | 計算方法 |
|----------------|---------|
| `patch` | `X.Y.Z` → `X.Y.(Z+1)` |
| `minor` | `X.Y.Z` → `X.(Y+1).0` |
| `major` | `X.Y.Z` → `(X+1).0.0` |
| 数値（例: `0.0.12`） | そのまま使用 |

バージョン番号が `major.minor.patch` の形式でない場合はエラーを報告して終了する。

```
新バージョン: {new_version}
```

### Step 4: ファイルの更新 [MANDATORY]

以下の3ファイルを順に更新する:

#### 4-1. `plugins/{plugin_name}/.claude-plugin/plugin.json`

Read して `"version"` フィールドを `{current_version}` → `{new_version}` に Edit する。

#### 4-2. `.claude-plugin/marketplace.json`

Read して `plugins` 配列の中の `name == plugin_name` のエントリの `"version"` を Edit する。

#### 4-3. `README.md`

Read して plugins テーブルの `| **{plugin_name}** | {current_version} |` を `{new_version}` に Edit する。

更新完了後、以下を出力する:

```
### ✅ バージョン更新完了

| ファイル | 変更 |
|----------|------|
| plugins/{plugin_name}/.claude-plugin/plugin.json | {current_version} → {new_version} |
| .claude-plugin/marketplace.json | {current_version} → {new_version} |
| README.md | {current_version} → {new_version} |
```

### Step 5: テスト実行

```bash
python3 tests/test_plugin_integrity.py
```

- **全テスト通過** → 完了メッセージを出力
- **失敗あり** → 失敗内容を表示し、ユーザーに対応を確認する

---

## エラーハンドリング

| エラー | 対応 |
|--------|------|
| 引数なし | 使用方法を表示して終了 |
| 不正なプラグイン名 | 「対象プラグインが見つかりません: {name}」と表示して終了 |
| 不正なバージョン形式 | 「バージョン形式が不正です（例: 0.0.12）」と表示して終了 |
| 新バージョン ≦ 現バージョン | 警告を表示し、続行するか確認する |
| テスト失敗 | 失敗内容を表示し、手動修正を促す |
