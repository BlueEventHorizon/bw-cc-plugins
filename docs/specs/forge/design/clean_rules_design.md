# clean-rules スキル設計書

> 対象プラグイン: forge | スキル: `/forge:clean-rules`

---

## 1. 概要

forge をインストールしたターゲットプロジェクトで、プロジェクトの `rules/` を開発文書の分類学に基づいて分析し、forge 内蔵知識も含めてプロジェクト内で読める形に体系的に再構築するスキル。

### 動機

- forge 導入前の rules/ が未整理で、関心事が混在したファイルや分類不明なルールが散在している
- forge 内蔵 docs はプラグインキャッシュ内にありユーザーには見えない。forge が持つルール・フォーマット知識もプロジェクトの rules/ に読める形で組み込むべき
- 単なる重複削除ではなく、「全ルールを分類学に基づいて体系的に整理し、forge 提供元を明記した上でプロジェクトに統合する」

### 重要な原則

- forge がカバーしている内容でも削除しない。forge から抽出してプロジェクトの rules/ に適切な分類で配置する
- forge 提供元のマーキングは不要。スキルを再実行すれば再分析されるため、追跡情報は冗長
- スキルは冪等。何度実行しても同じ分類結果に収束する

---

## 2. 開発文書の分類学（Taxonomy）

スキルの判定基準となる分類体系。Diátaxis、SWEBOK、ADR、AI エージェント向けドキュメント設計の知見を統合。

### 次元 1: 内容の種類（Content Type）

| 種類 | 機能 | 判別基準 | 例 |
|------|------|---------|-----|
| **Constraint** | MUST/MUST NOT の硬いルール。違反はバグ | 「〜してはならない」「〜は禁止」 | セキュリティ制約、外部依存禁止 |
| **Convention** | SHOULD の合意事項。チームが変更可能 | 「〜を推奨」「〜に統一する」 | 命名規則、コードスタイル |
| **Format** | 成果物の構造テンプレート | 「〜のフォーマット」「テンプレート」 | 設計書テンプレート、要件定義書フォーマット |
| **Process** | ステップバイステップの手順 | 「Step 1:〜」「〜のワークフロー」 | レビュー手順、デプロイ手順 |
| **Decision** | 選択の根拠。ADR 相当 | 「〜を選んだ理由」「なぜ〜か」 | 技術選定理由、アーキテクチャ判断 |
| **Reference** | 参照情報。変更は事実の反映 | 一覧表、カタログ、マッピング | API 一覧、用語集、ID 分類カタログ |

### 次元 2: 権威源（Authority Source）

| 源 | 管理者 | 変更タイミング | プロジェクト rules/ に置くべきか |
|---|--------|-------------|-------------------------------|
| **Tool-provided** | forge プラグイン | プラグインバージョン更新時 | ユーザーが読める形で配置（forge 内蔵は不可視のため） |
| **Project-defined** | チーム合意 | チームが随時変更可能 | ✅ 必要 |
| **External standard** | 標準団体・言語仕様 | 外部で変更 | △ 参照リンクのみ |

### 次元 3: スコープ

| スコープ | 適用範囲 | 例 |
|---------|---------|-----|
| **Universal** | forge を使う全プロジェクト共通 | forge のレビュー観点、文書フォーマット |
| **Project-specific** | このプロジェクトのみ | 命名規則、Git ワークフロー、アーキテクチャ判断 |

### forge と プロジェクトの責務分離

| Content Type | forge が担う（Tool-provided） | プロジェクトが担う |
|-------------|------------------------------|------------------|
| **Constraint** | レビュー観点（review_criteria_spec） | プロジェクト固有の制約 |
| **Convention** | — | 命名規則、コードスタイル、用語統一 |
| **Format** | 文書テンプレート（*_format.md） | — |
| **Process** | ワークフロー（SKILL.md 内蔵） | デプロイ手順、リリースフロー |
| **Decision** | — | アーキテクチャ判断（ADR） |
| **Reference** | ID 分類カタログ（spec_format） | プロジェクト固有の参照情報 |

---

## 3. ファイル構成

```
plugins/forge/skills/clean-rules/
  SKILL.md
  docs/
    taxonomy.md              # 上記分類学の定義（AI が参照する判定基準）
  scripts/
    list_forge_docs.py       # forge 内蔵 docs のメタデータ一覧を JSON 出力

tests/forge/clean-rules/
  __init__.py
  test_list_forge_docs.py
```

---

## 4. ワークフロー

### Phase 1: 情報収集

1. `.doc_structure.yaml` の存在確認（なければ `/forge:setup-doc-structure` を案内しエラー終了）
2. ルール文書一覧を取得（`resolve_doc_structure.py --type rules`）
3. forge 内蔵 docs のメタデータを取得（`list_forge_docs.py`）
4. 分類学定義を Read（`taxonomy.md`）
5. ルール文書（ターゲット側）と forge docs（`internal: false` のもの）を全て Read

### Phase 2: 分類・分析（AI）

`taxonomy.md` の分類学に基づき、各ルール文書のセクション単位で以下を判定:

- **A. Content Type の分類**: Constraint / Convention / Format / Process / Decision / Reference
- **B. Authority Source の判定**: Tool-provided（forge） / Project-defined / External standard
- **C. forge 対応の特定**: Tool-provided セクションが forge のどの内蔵 docs に対応するか
- **D. プロジェクト固有部分の抽出**: Project-defined のセクション

### Phase 3: 再構築案の提示と承認

分類結果に基づき再構築案を提示:

1. **forge 知識の組み込み**: プロジェクトに存在しない forge 内蔵ルールを読める形で配置
2. **既存ルールの再編成**: 混在した関心事を Content Type ごとに分離
3. **統合**: 同じ関心事をカバーする forge 知識と既存ルールを 1 ファイルに統合
4. **変更なし**: プロジェクト固有で forge カバーなし

AskUserQuestion で承認を取得。

### Phase 4: 実行

承認に基づきファイル操作を実行。マーキングやメタデータコメントは付与しない。

### Phase 5: 完了処理

- 結果サマリー出力
- `.doc_structure.yaml` 更新確認
- DocAdvisor ToC 更新
- `/anvil:commit` で commit 確認

---

## 5. `list_forge_docs.py` 仕様

- 引数: `docs_dir`（`${CLAUDE_PLUGIN_ROOT}/docs`）
- 出力: JSON（`status`, `docs[]` — 各 doc の `path`, `full_path`, `title`, `topics[]`, `content_type`, `internal`）
- `internal: true` の対象: `session_format.md`, `doc_structure_format.md`, `context_gathering_spec.md`, `task_execution_spec.md`

---

## 6. 関連ファイル

| ファイル | 役割 |
|---------|------|
| `plugins/forge/skills/doc-structure/scripts/resolve_doc_structure.py` | rules 一覧取得に直接使用 |
| `plugins/forge/docs/review_criteria_spec.md` | forge 内蔵 docs の代表例 |
| `plugins/forge/skills/setup-doc-structure/SKILL.md` | Phase 構成パターン参考 |

---

## 7. 調査 Sources

- [How to write a good spec for AI agents - Addy Osmani](https://addyosmani.com/blog/good-spec/)
- [Writing a good CLAUDE.md - HumanLayer](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Spec-driven development - Thoughtworks](https://thoughtworks.medium.com/spec-driven-development-d85995a81387)
- [CLAUDE.md Best Practices - UX Planet](https://uxplanet.org/claude-md-best-practices-1ef4f861ce7c)
- [Best Practices for Claude Code](https://code.claude.com/docs/en/best-practices)
- [Taxonomies in Software Engineering - ScienceDirect](https://www.sciencedirect.com/science/article/pii/S0950584917300472)
