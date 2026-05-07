# レビューガイド

コード・文書を AI がレビューし、指摘事項の吟味・修正まで一貫して実行する。対話モードではユーザーが最終判断し、auto モードでは AI が自動修正する。

## review

```
/forge:review <種別> [対象] [--codex|--claude] [--auto [N]] [--auto-critical]
```

| 引数                   | 説明                                                                |
| ---------------------- | ------------------------------------------------------------------- |
| `種別`                 | `code` / `requirement` / `design` / `plan` / `uxui` / `generic`     |
| `対象`                 | ファイルパス / ディレクトリ / Feature 名 / 省略（= 対話で決定）     |
| `--codex` / `--claude` | エンジン選択（デフォルト: Codex。不在時は Claude にフォールバック） |
| `--auto [N]`           | 🔴 + 🟡 を N サイクル自動修正（省略時 N=1）                         |
| `--auto-critical`      | 🔴 のみを 1 サイクル自動修正                                        |

### 使用例

```bash
/forge:review code src/                        # 対話モード
/forge:review code src/ --auto 3               # 3 サイクル自動修正
/forge:review code src/ --auto-critical        # 致命的のみ自動修正
/forge:review requirement login                # Feature 名で指定
/forge:review design specs/login/design.md     # ファイル直接指定
/forge:review generic README.md                # 任意の文書
/forge:review code src/ --claude               # Claude エンジン指定
```

### いつ使うか

| シーン                | 推奨モード                              |
| --------------------- | --------------------------------------- |
| PR 前の最終チェック   | `--auto` で一括修正後に差分を確認       |
| 文書の品質確認        | 対話モードで 1 件ずつ判断               |
| CI 的な自動品質ゲート | `--auto-critical` で致命的のみ修正      |
| 他スキルの完了処理    | start-design 等が内部で `--auto` を呼ぶ |

### 実行フロー

```mermaid
flowchart TD
    START([ユーザー]) --> P1

    P1["Phase 1: 引数解析<br/>種別・エンジン・モード確定"] --> P2

    P2["Phase 2: 対象解決<br/>ファイル特定・参考文書収集<br/>perspectives 構成"] --> P3

    P3["Phase 3: 並列レビュー<br/>reviewer × N（perspective ごと）"] --> P4

    P4["Phase 4: 統合・重複除去"] --> P5

    P5["Phase 5: 並列吟味<br/>evaluator × N（perspective ごと）"] --> CHECK

    CHECK{修正対象あり?}
    CHECK -->|No| P7
    CHECK -->|Yes| MODE

    MODE{対話モード?}
    MODE -->|Yes| PRESENT
    MODE -->|No| FIXER

    PRESENT["present-findings<br/>1 件ずつ提示・人間判断"] --> FIXER

    FIXER["Phase 6: fixer 修正実行"] --> REREV

    REREV["再レビュー<br/>修正差分のみ検証"] --> CYCLE

    CYCLE{未修正あり AND<br/>サイクル上限未到達?}
    CYCLE -->|Yes| P3
    CYCLE -->|No| P7

    P7["Phase 7: 完了処理<br/>テスト → commit 確認"]
```

### モード比較

| モード             | 修正対象     | 最終判断者 | 用途             |
| ------------------ | ------------ | ---------- | ---------------- |
| 対話（デフォルト） | ユーザー選択 | 人間       | 慎重な品質管理   |
| `--auto N`         | 🔴 + 🟡      | AI         | 一括品質向上     |
| `--auto-critical`  | 🔴 のみ      | AI         | 最小限の安全修正 |

コアループ（reviewer → 統合 → evaluator → fixer → 再レビュー）は全モードで同一。違いは fixer の前に人間判断を挟むかどうかだけ。

### レビュー種別

| 種別          | 対象                      | 主な観点                               |
| ------------- | ------------------------- | -------------------------------------- |
| `code`        | ソースコード              | 正確性、堅牢性、保守性                 |
| `requirement` | 要件定義書                | 完全性、一貫性、テスト可能性           |
| `design`      | 設計書                    | アーキテクチャ、要件反映、実現可能性   |
| `plan`        | 計画書                    | タスク粒度、依存関係、トレーサビリティ |
| `uxui`        | デザイントークン・UI 仕様 | HIG 準拠、ユーザビリティ、視覚的一貫性 |
| `generic`     | 任意の文書                | 構造、明確さ、完全性                   |

### 重大度レベル

| レベル    | 意味                                               | auto での扱い                         |
| --------- | -------------------------------------------------- | ------------------------------------- |
| 🔴 致命的 | 修正必須。バグ、セキュリティ、データ損失、仕様違反 | `--auto` `--auto-critical` 両方で修正 |
| 🟡 品質   | 修正推奨。規約、エラーハンドリング、パフォーマンス | `--auto` のみで修正                   |
| 🟢 改善   | あると良い。可読性、リファクタリング提案           | 自動修正しない                        |

### レビュー観点（perspectives）

レビュー観点は累積的に構成される。各 perspective は独立した reviewer で並列処理される。

| ソース                   | 内容                                                          |
| ------------------------ | ------------------------------------------------------------- |
| **プラグインデフォルト** | `review_criteria_{type}.md` から自動抽出（常に含む）          |
| **DocAdvisor**           | `/query-rules` が利用可能な場合、プロジェクト固有ルールを追加 |

### セッション管理

レビュー中は `.claude/.temp/` にセッションディレクトリが作成される。

| ファイル       | 内容                                               |
| -------------- | -------------------------------------------------- |
| `session.yaml` | セッションメタデータ（種別・エンジン・サイクル数） |
| `refs.yaml`    | 参照ファイル一覧（対象・参考文書・perspectives）   |
| `review_*.md`  | perspective 別レビュー結果                         |
| `review.md`    | 統合・重複除去済み結果                             |
| `plan.yaml`    | 修正プランと進捗状態                               |

正常完了時は自動削除。中断時は残存し、次回起動時に再開提案される。
