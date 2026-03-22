# forge 詳細ガイド

AI によるドキュメントライフサイクルツール。要件定義・設計・計画書の作成から、コード・文書レビュー、自動修正、品質確定まで対応。

## Feature（フィーチャー）

forge は **Feature（フィーチャー）** 単位で文書を管理することもできる。Feature とは、関連する仕様をグループ化した開発単位。Feature なしでも動作する。

| 開発パターン | Feature の使い方 |
|-------------|-----------------|
| 追加開発 | 既存のメイン仕様に後から追加する機能群を Feature として分割する |
| アジャイル開発 | イテレーションごとに Feature 単位で開発・デリバリーする |
| 小規模プロジェクト | プロジェクト全体を1つの Feature として扱ってもよい |

Feature を使う場合、各 Feature は共通のディレクトリ構造で管理する:

```
specs/
  {feature}/
    requirements/   # 要件定義書
    design/         # 設計書
    plan/           # 計画書
```

## レビュー種別

| 種別          | 対象                                        |
| ------------- | ------------------------------------------- |
| `code`        | ソースコードファイル・ディレクトリ          |
| `requirement` | 要件定義書                                  |
| `design`      | 設計書                                      |
| `plan`        | 開発計画書                                  |
| `generic`     | 任意の文書（ルール、スキル定義、README 等） |

## 重大度レベル

| レベル | 意味                                                           |
| ------ | -------------------------------------------------------------- |
| 🔴 致命的 | 修正必須。バグ、セキュリティ問題、データ損失リスク、仕様違反   |
| 🟡 品質   | 修正推奨。コーディング規約、エラーハンドリング、パフォーマンス |
| 🟢 改善   | あると良い。可読性向上、リファクタリング提案                   |

## レビュー観点

レビュー観点は以下のソースから累積的に構成される:

- **プラグインデフォルト**（常に含む）: `skills/review/docs/review_criteria_{type}.md` の perspectives
- **DocAdvisor**（追加 perspective）: `/query-rules` が利用可能な場合、プロジェクト固有のルール文書を追加

---

## スキル詳細

### review

```
/forge:review <種別> [対象] [--エンジン] [--auto [N]] [--auto-critical]
```

| 引数 | 説明 |
|------|------|
| `種別` | `requirement` / `design` / `code` / `plan` / `generic` |
| `対象` | ファイルパス（複数可）/ Feature 名 / ディレクトリ / 省略（= 対話で決定） |
| `--codex` / `--claude` | エンジン選択（デフォルト: codex） |
| `--auto [N]` | レビュー+修正を N サイクル自動実行（省略時 N=1） |
| `--auto-critical` | 🔴 致命的のみを自動修正 |

```bash
/forge:review code src/                    # 対話モード
/forge:review code src/ --auto 3           # 3サイクル自動修正
/forge:review requirement login            # Feature 名で指定
```

### setup-doc-structure

```
/forge:setup-doc-structure
```

引数なし。対話的に `.doc_structure.yaml` を生成・更新する。

### start-requirements

```
/forge:start-requirements [feature] [--mode interactive|reverse-engineering|from-figma] [--new|--add]
```

| 引数 | 説明 |
|------|------|
| `feature` | Feature 名（省略時は対話で確定） |
| `--mode` | `interactive`（対話）/ `reverse-engineering`（ソース解析）/ `from-figma`（Figma） |
| `--new` | 新規アプリ |
| `--add` | 既存アプリへの機能追加 |

### start-design

```
/forge:start-design [feature]
```

| 引数 | 説明 |
|------|------|
| `feature` | Feature 名（省略時は対話で確定） |

### start-plan

```
/forge:start-plan [feature]
```

| 引数 | 説明 |
|------|------|
| `feature` | Feature 名（省略時は対話で確定） |

### start-implement

```
/forge:start-implement [feature] [--task TASK-ID[,TASK-ID,...]]
```

| 引数 | 説明 |
|------|------|
| `feature` | Feature 名（省略時は対話で確定） |
| `--task` | 実行するタスク ID（カンマ区切りで複数指定可。省略時は優先度順で自動選択） |

### setup-version-config

```
/forge:setup-version-config
```

引数なし。プロジェクトをスキャンして `.version-config.yaml` を対話的に生成・更新する。

### update-version

```
/forge:update-version [target] <new-version | patch | minor | major>
```

| 引数 | 説明 |
|------|------|
| `target` | 対象 target 名（省略時: 先頭または唯一の target） |
| `patch` / `minor` / `major` | バンプ種別 |
| `new-version` | バージョン番号を直接指定（例: `1.2.3`） |

```bash
/forge:update-version patch              # 先頭 target をパッチバンプ
/forge:update-version forge 0.1.0       # forge を 0.1.0 に更新
```

### clean-rules

```
/forge:clean-rules
```

引数なし。プロジェクトの rules/ を開発文書の分類学に基づいて分析・再構築する。

### help

```
/forge:help
```

引数なし。スキルを選択し、引数を対話的に入力してそのまま実行できる。
