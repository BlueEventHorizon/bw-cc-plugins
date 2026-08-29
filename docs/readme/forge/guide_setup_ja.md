# セットアップ・ユーティリティガイド

プロジェクトの初期設定、バージョン管理、ルール整理などの運用系スキル。

## setup-doc-structure

プロジェクトのドキュメント配置場所と種別を宣言する `.doc_structure.yaml` を生成する。forge がドキュメントのパス解決に用いる基盤。

> 詳細は [文書構造ガイド](../guide_doc_structure_ja.md) を参照。

```
/forge:setup-doc-structure
```

引数なし。対話的にプロジェクトをスキャンし、推奨構成を提示する。

---

## setup-version-config

プロジェクトをスキャンしてバージョン管理対象を検出し、`.version-config.yaml` を生成する。`update-version` の前提条件。

```
/forge:setup-version-config
```

引数なし。

### いつ使うか

- プロジェクトで初めてバージョン管理を設定するとき
- プロジェクト構造を変更したとき（プラグイン追加、README フォーマット変更など）

### 実行フロー

1. 既存 `.version-config.yaml` の確認（更新 / 再生成 / キャンセル）
2. `scan_version_targets.py` でバージョンファイル・README・CHANGELOG を自動検出
3. 検出結果を表示し、対話的に設定を調整
4. `.version-config.yaml` を書き出し

### 設定の構造

`targets` / `changelog` / `git` の3セクションで構成される。スキーマの詳細は `DES-023` §2 または `setup-version-config` の Schema Reference を参照。

---

## update-version

`.version-config.yaml` に基づいてバージョンを一括更新する。CHANGELOG への git log 自動反映にも対応。

```
/forge:update-version [target] <patch | minor | major | X.Y.Z>
```

| 引数                        | 説明                                                                          |
| --------------------------- | ----------------------------------------------------------------------------- |
| `target`                    | ターゲット名（省略時は `scope` に一致する変更から自動検出。複数候補時は選択） |
| `patch` / `minor` / `major` | バンプ種別                                                                    |
| `X.Y.Z`                     | バージョン番号を直接指定                                                      |

### 使用例

```bash
/forge:update-version patch                # 変更が検出されたターゲットを自動選択してパッチバンプ
/forge:update-version forge 0.1.0          # forge を 0.1.0 に更新
/forge:update-version anvil minor          # anvil をマイナーバンプ
```

### 実行フロー

1. `.version-config.yaml` の読み込み
2. 対象ターゲットの決定（未指定なら `scope` に一致する変更から自動検出）
3. 現在のバージョン取得
4. main ブランチと比較（既にバンプ済みなら確認）
5. 新バージョンを計算
6. コミット履歴を収集（CHANGELOG 用）
   - 前バージョンのタグを、prefix の有無 × `v` の有無の 4 通りで検索する。単純な形式から順に見て最初に実在したものを採る（例: `1.2.3` → `v1.2.3` → `foo-1.2.3` → `foo-v1.2.3`）。見つからない場合は CHANGELOG の前エントリ日付で代替する
7. ファイル更新
   - `version_file`（plugin.json 等）を更新
   - `sync_files`（README 等）のバージョンを同期
8. カタログ（marketplace）のバンプ提案
9. CHANGELOG にエントリを挿入
10. README への影響を判定（必要なら更新）
11. テスト実行（`tests/` がある場合）
12. git 操作（commit / push / tag を確認。タグ名は既存タグの形式に合わせる）

### エラー時の対応

| 状況                          | 対応                                            |
| ----------------------------- | ----------------------------------------------- |
| `.version-config.yaml` がない | `/forge:setup-version-config` の実行を案内      |
| 指定ターゲットが存在しない    | 利用可能なターゲット一覧を表示                  |
| テスト失敗                    | バージョン更新は完了済み。テスト修正後に commit |

## help

forge スキル一覧を表示し、選択したスキルの引数をガイド付きで構成して実行する。

```
/forge:help
```

引数なし。

### ウィザードの流れ

1. **スキル選択**: 番号で選択
2. **引数構成**: 選択スキルに応じた対話形式の質問
3. **コマンド確認**: 構築されたコマンドを表示して実行確認

```
1.  review                            : コード・文書をレビュー。重大度 🔴🟡🟢 で分類
2.  consult                           : 議論を進行。論点を立て、討議ファイルに記録しながら 1 件ずつ
3.  start-requirements                : 要件定義書の作成。3モード対応
4.  start-design                      : 設計書の作成。レビュー+自動修正→commit
5.  start-plan                        : 計画書の作成。レビュー+自動修正→commit
6.  start-implement                   : 計画書から実装・レビュー・計画更新
7.  start-uxui-design                 : デザイントークン・UI 視覚仕様を創造
8.  create-feature-from-markdown-plan : Markdown plan から要件定義→設計書へ展開
9.  merge-specs                       : 2 つの仕様 DIR（基本 / 追加）の齟齬を内容単位で解消
10. setup-doc-structure               : .doc_structure.yaml を対話的に生成
11. setup-version-config              : .version-config.yaml を対話的に生成
12. update-version                    : バージョンを一括更新。CHANGELOG 自動反映
13. query-forge-rules                 : forge 内蔵知識ベースを ToC 検索
```
