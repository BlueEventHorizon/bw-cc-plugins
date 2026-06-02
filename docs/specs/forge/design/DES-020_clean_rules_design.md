# DES-020 clean-rules スキル設計書

## メタデータ

| 項目   | 値         |
| ------ | ---------- |
| 設計ID | DES-020    |
| 作成日 | 2026-03-19 |

---

> 対象プラグイン: forge | スキル: `/forge:clean-rules`

---

## 1. 概要

forge をインストールしたターゲットプロジェクトで、プロジェクトの `rules/` を開発文書の分類学に基づいて分析し、forge 内蔵 docs との重複を検出・削除し、残る文書を体系的に再構築するスキル。

### 動機

- forge 導入前の rules/ が未整理で、関心事が混在したファイルや分類不明なルールが散在している
- forge 内蔵 docs はプラグインキャッシュ内にあり、forge 自身がレビュー等で参照する。プロジェクト側に同内容のコピーがあると二重管理になり、バージョン不整合が発生する
- 旧設計は「forge docs をプロジェクトにコピー」だったが、forge バージョン更新でコピーが陳腐化する問題があった。新設計は逆に「forge がカバーする内容はプロジェクトから削除」し、forge に委ねる

### 重要な原則

- **forge 優先**: forge 内蔵 docs でカバーされる内容はプロジェクト rules/ から削除する。forge が責任を持って管理する領域を二重管理しない
- **Project-defined を保護**: プロジェクト固有の取り決め（命名規則、Git ワークフロー等）は絶対に削除しない
- **安全性**: 破壊的操作の前に `git stash` で退避し、ロールバック可能にする
- **段階的実行**: デフォルトは分析のみ（ドライラン）。`--delete` / `--rebuild` で明示的に操作を指定する

---

## 2. モード構成

```
/forge:clean-rules                     # 分析のみ（何を削除/再構築すべきか報告）
/forge:clean-rules --delete            # forge 重複部分をセクション単位で削除
/forge:clean-rules --rebuild           # taxonomy に基づく再構築
/forge:clean-rules --delete --rebuild  # 削除してから再構築
```

| モード                 | 操作                                   | 安全性                       |
| ---------------------- | -------------------------------------- | ---------------------------- |
| デフォルト（引数なし） | 分析レポート出力のみ。ファイル変更なし | リスクなし                   |
| `--delete`             | forge 重複セクションの削除             | git stash + カテゴリ単位承認 |
| `--rebuild`            | taxonomy に基づくファイル分割・統合    | git stash + カテゴリ単位承認 |
| `--delete --rebuild`   | 削除 → 再構築を順次実行                | git stash + カテゴリ単位承認 |

---

## 3. 開発文書の分類学（Taxonomy）

スキルの判定基準となる分類体系。詳細は `plugins/forge/skills/clean-rules/docs/taxonomy.md` を参照。

### 次元 1: 内容の種類（Content Type）

| 種類           | 機能                                   |
| -------------- | -------------------------------------- |
| **Constraint** | MUST/MUST NOT の硬いルール。違反はバグ |
| **Convention** | SHOULD の合意事項。チームが変更可能    |
| **Format**     | 成果物の構造テンプレート               |
| **Process**    | ステップバイステップの手順             |
| **Decision**   | 選択の根拠。ADR 相当                   |
| **Reference**  | 参照情報。変更は事実の反映             |

### 次元 2: 権威源（Authority Source）

| 源                    | 管理者             | --delete での扱い          |
| --------------------- | ------------------ | -------------------------- |
| **Tool-provided**     | forge プラグイン   | 削除対象（forge に委ねる） |
| **Project-defined**   | チーム合意         | 保護（絶対に削除しない）   |
| **External standard** | 標準団体・言語仕様 | 保護                       |

### forge とプロジェクトの責務分離

| Content Type   | forge が担う（Tool-provided）        | プロジェクトが担う                 |
| -------------- | ------------------------------------ | ---------------------------------- |
| **Constraint** | レビュー観点（review_criteria_*.md） | プロジェクト固有の制約             |
| **Convention** | —                                    | 命名規則、コードスタイル、用語統一 |
| **Format**     | 文書テンプレート（*_format.md）      | —                                  |
| **Process**    | ワークフロー（SKILL.md 内蔵）        | デプロイ手順、リリースフロー       |
| **Decision**   | —                                    | アーキテクチャ判断（ADR）          |
| **Reference**  | ID 分類カタログ（spec_format）       | プロジェクト固有の参照情報         |

---

## 4. split_doc_sections.py

forge docs とプロジェクト rules を `##` 見出し単位のセクションに分割し、構造化して
出力するスクリプト。重複の判定そのものは行わず、AI（Phase 2）が各セクションの本文を
読み比べて対応関係を判断するための前処理を担う。

**外部 API・Embedding は使用しない（標準ライブラリのみ）**。これにより外部 API への
文書送信・API コスト・cross-plugin 依存を排除する。
対応関係の判定精度は、数値スコアではなく AI による内容理解で担保する。

### インターフェース

```
python3 split_doc_sections.py \
  --project-rules file1.md file2.md ... \
  --forge-docs forge1.md forge2.md ...
```

`--forge-docs` には、`rules_toc.yaml` のキーワード・要約で一次絞り込みした forge docs を渡す
（無関係な docs を除外し、Phase 2 の精読コストを抑える）。

### 処理フロー

1. 各ファイルを `##` 見出しでセクション分割（行番号付き）
2. project / forge それぞれのセクションを `file` / `heading` / `text` / `line` で構造化
3. JSON で出力（重複判定は行わない。判定は Phase 2 の AI が担当）

### 出力フォーマット

```json
{
  "status": "ok",
  "project_section_count": 12,
  "forge_section_count": 34,
  "project_sections": [{
    "file": "docs/rules/version_migration_design.md",
    "heading": "## 2. 失敗するアンチパターン",
    "text": "...",
    "line": 42
  }],
  "forge_sections": [{
    "file": "plugins/forge/docs/version_migration_spec.md",
    "heading": "## Migration function contracts",
    "text": "...",
    "line": 18
  }]
}
```

### 前提条件

- 外部 API・API キーは不要。標準ライブラリのみで動作する

---

## 5. ワークフロー

### Phase 1: 情報収集

1. `.doc_structure.yaml` の存在確認（なければ `/forge:setup-doc-structure` を案内しエラー終了）
2. ルール文書一覧を取得（`resolve_rules.py`）
3. forge 内蔵 docs のパスを `rules_toc.yaml` から全件取得
4. `split_doc_sections.py` でセクション分割（`rules_toc.yaml` のキーワードで forge docs を一次絞り込み）
5. 分類学定義を Read（`taxonomy.md`）
6. ルール文書と forge docs を全て Read

### Phase 2: 分類・分析（AI）

`taxonomy.md` の分類学に基づき、各ルール文書のセクション（`##` 見出し）単位で以下を判定:

- **A. Content Type**: Constraint / Convention / Format / Process / Decision / Reference
- **B. Authority Source**: Tool-provided / Project-defined / External standard
- **C. forge 対応**: 分割した各セクションの本文を forge docs と読み比べ、Tool-provided セクションの forge docs 対応先と根拠を特定
- **D. モード別推奨**: 各セクションに対する `--delete` / `--rebuild` の推奨アクション

分析結果を JSON 形式で出力。デフォルトモード（引数なし）はここで終了。

### Phase 3: 安全確保

`--delete` または `--rebuild` が指定された場合のみ実行:

- `git stash` で作業状態を退避
- 変更計画をカテゴリ単位で AskUserQuestion で承認

### Phase 4-D: 削除実行（--delete）

- 分析結果から `delete_recommendation: "delete"` のセクションを処理
- ファイル全体が削除対象 → ファイル削除
- 一部セクションのみ削除対象 → 該当セクションを除去し、残りを保存
- 相互参照の検出と更新

### Phase 4-R: 再構築実行（--rebuild）

- 分割: Content Type が 3 種以上混在 AND 100 行超のファイルのみ
- 統合: 同一 Content Type + 同一関心事の小ファイル群をまとめる
- 各操作後に markdown 構文チェック（見出し階層の整合性）

### Phase 5: 完了処理

- 結果サマリー出力
- `.doc_structure.yaml` の自動更新
- 相互参照の更新レポート
- ルール ToC 更新（`/forge:update-db-rules` が利用可能な場合）
- `/anvil:commit` で commit 確認
- ロールバック手段の提示（`git stash pop`）

---

## 6. ファイル構成

```
plugins/forge/skills/clean-rules/
  SKILL.md                        # スキル定義（3モード構成）
  docs/
    taxonomy.md                   # 分類学の定義（AI 判定基準）
  scripts/
    split_doc_sections.py         # セクション分割（AI 判定の前処理。外部 API 不使用）

plugins/forge/toc/
  rules/rules_toc.yaml            # forge 内蔵 docs の検索インデックス

tests/forge/clean-rules/
  test_split_doc_sections.py      # セクション分割スクリプトのテスト
```

---

## 7. 関連ファイル

| ファイル                                                              | 役割                               |
| --------------------------------------------------------------------- | ---------------------------------- |
| `plugins/forge/skills/doc-structure/scripts/resolve_doc_structure.py` | rules 一覧取得に使用               |
| `plugins/forge/skills/review/docs/review_criteria_{type}.md`          | forge 内蔵レビュー観点（種別ごと） |

---

## 8. 調査 Sources

- [How to write a good spec for AI agents - Addy Osmani](https://addyosmani.com/blog/good-spec/)
- [Writing a good CLAUDE.md - HumanLayer](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Spec-driven development - Thoughtworks](https://thoughtworks.medium.com/spec-driven-development-d85995a81387)
- [CLAUDE.md Best Practices - UX Planet](https://uxplanet.org/claude-md-best-practices-1ef4f861ce7c)
- [Best Practices for Claude Code](https://code.claude.com/docs/en/best-practices)
- [Taxonomies in Software Engineering - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
