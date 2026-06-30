# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。2 プラグインを格納・配布する。

- **forge** (v0.3.0) — ドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正に対応
- **anvil** — GitHub 連携（commit / PR / Issue 作成・実装）（`/anvil:commit`, `/anvil:create-pr`, `/anvil:create-issue`, `/anvil:impl-issue`）

> **文書検索バックエンド（doc-advisor）は外部依存**: AI 検索可能なドキュメントインデックスは別リポジトリ
> [BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor)（doc-advisor / `index-docs`・`query-docs`）が提供する。
> forge の `/forge:query-db-rules` 等はこの外部 doc-advisor へ転送する。

全体像・スキル一覧・ワークフロー図は [README.md](README.md) を参照。

## 重要規約 [MANDATORY]

- プロジェクトルール文書の参照には `query-db-rules` SKILL を使う
- プロジェクトルール文書の更新後には `update-db-rules` SKILL を使う
- プロジェクト仕様の参照には `query-db-specs` SKILL を使う
- プロジェクト仕様の更新後には `update-db-specs` SKILL を使う
- **ルールは `docs/rules/` で管理**: CLAUDE.md にルールを詰め込まない（コンテキスト肥大化防止）
- **設計文書は `docs/specs/**/{requirements,design}/` に保存**: plan モードで作成した重要設計は ID プレフィックス（REQ-, DES-, ADR-）で命名
- **プラグインランタイム文書の境界**: `plugins/doc-advisor/{workflows,formats}/` 配下は SKILL.md がランタイム Read する配布物。リポジトリルートの `docs/` 配下はプロジェクト自身のメタ文書（配布物に含めない）
- **文書間参照にパスを焼き込まない**: 「どのタスクで何を読むべきか」をタスク記述から動的に発見すること（＝パス参照の保守コスト爆発を無くすこと）こそ doc-advisor の存在意義。文書には「何に依存するか（概念・ID）」だけ残し、`docs/...md` のようなディレクトリパス直書きの "ここを見ろ" 参照は書かない（パスは改訂で腐り、ToC の動的発見を無意味化する）。参照先の発見は `query-docs` に委ねる
- **feature/fix PR では CHANGELOG.md・version 関連ファイルを編集しない**。リリースコミットでまとめて更新（`/forge:update-version` を使う）
- **`.toc_work/` 等の消えるべき一時物は `.gitignore` に入れない**。残存が `git status` に untracked として出ることで異常を検知できる
- **`docs/specs/base/design/` の ADR と DES は通し番号を共有**。`forge:next-spec-id` の出力を鵜呑みにせず ADR/DES 横断の最大番号+1 を使う
- **決定論的な定型処理（列挙・転記・集計・ファイル生成）は script 化する**。AI は判断のみ担い、手転記・手列挙をしない
- **agent/SKILL のプロンプト指示は混入点でなく出力構築点に 1 箇所だけ置く**。近接した複数箇所への同一指示は重複であり追記しない
- **`/forge:merge-specs` で一時 feature 文書を統合するときは fold が正（promote は誤り）**。一時文書（REQ-_/DES-_/計画書）は既存文書へ反映して削除する（`additive_development_spec.md` §4）

## Repository Layout

| Path                                              | 役割                                                                      |
| ------------------------------------------------- | ------------------------------------------------------------------------- |
| `.claude-plugin/marketplace.json`                 | マーケットプレイスマニフェスト                                            |
| `plugins/{plugin}/.claude-plugin/plugin.json`     | 各プラグインマニフェスト                                                  |
| `plugins/{plugin}/skills/{skill}/SKILL.md`        | スキル定義（frontmatter + 本文）                                          |
| `plugins/{plugin}/scripts/`                       | スキルから呼ばれる Python / Bash                                          |
| `plugins/{plugin}/docs/`                          | プラグイン内部仕様（forge は `/forge:query-forge-rules` 対象）            |
| `plugins/forge/toc/rules/rules_toc.yaml`          | forge 内蔵知識ベースの ToC                                                |
| `docs/rules/`                                     | プロジェクトルール（`/forge:query-db-rules` 対象）                        |
| `docs/specs/{plugin}/{requirements,design,plan}/` | プラグインごとの仕様文書（`/forge:query-db-specs` 対象）                  |
| `docs/readme/`                                    | ユーザー向けガイド（日英併記、`guide_*_ja.md`）                           |
| `docs/references/`                                | 外部参考資料                                                              |
| `tests/{common,forge}/`                           | プラグイン別テスト                                                        |
| `meta/`                                           | 研究・評価・ゴールデンセット（git 管理外、下記ルール参照）                |
| `.claude/settings.json`                           | 権限・hooks 設定（プロジェクトレベル）                                    |
| `.claude/skills/`                                 | ローカル限定 skill（配布対象外、`update-forge-toc` 等）                   |
| `.agents/skills/`                                 | agent 向け skill                                                          |
| `.doc_structure.yaml`                             | rules/specs のパス解決設定                                                |
| `.version-config.yaml`                            | バージョン一括更新の対象設定                                              |
| `dprint.jsonc`                                    | フォーマッタ設定（JSON/TOML/Markdown/YAML）                               |
| `AGENTS.md`                                       | `CLAUDE.md` へのシンボリックリンク（Codex 向け、内容は CLAUDE.md と同一） |

### meta/ ディレクトリのルール [MANDATORY]

`meta/` は研究・評価・ゴールデンセット用の作業領域であり、**いつでも削除される可能性がある**。

- `plugins/` / `tests/` / `docs/` 配下のコード・文書は `meta/` 内のファイルに依存してはならない
- `meta/` 内のスクリプトが `plugins/` のモジュールを呼び出すのは許容される（逆方向は禁止）
- SKILL として配布しない（ユーザー環境に `meta/` は存在しない）

## Information Sources

タスクに応じて以下の入口を使う:

| 対象                                                       | 入口                                                                                                               |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| プロジェクト全体の鳥瞰                                     | `README.md`（ワークフロー図 + 全スキル一覧 + トリガー句）                                                          |
| 仕様駆動開発の思想・What/How 境界                          | `docs/readme/guide_sdd_ja.md`                                                                                      |
| 各スキルの挙動・引数・使用例                               | `docs/readme/forge/guide_{create_docs,implement,review,setup,uxui_design}_ja.md` / `docs/readme/guide_anvil_ja.md` |
| プロジェクトルール（実装・文書・CLI・SKILL 作成）          | `/forge:query-db-rules` → `docs/rules/`                                                                            |
| プロジェクト仕様（要件/設計/計画）                         | `/forge:query-db-specs` → `docs/specs/`                                                                            |
| forge 内部仕様（ID体系・フォーマット・原則・レビュー基準） | `/forge:query-forge-rules` → `plugins/forge/docs/`                                                                 |
| Claude Code / SDK / API 仕様                               | `claude-code-guide` agent                                                                                          |
| 最新の変更意図                                             | `git log main..HEAD` / `CHANGELOG.md`                                                                              |

## Development

ビルドシステム・パッケージマネージャーは使用していない。Python スクリプトは標準ライブラリのみで動作する（外部依存なし）。

### フォーマット

JSON / TOML / Markdown / YAML は [dprint](https://dprint.dev/) でフォーマット。設定は `dprint.jsonc`。

```bash
dprint fmt          # フォーマット適用
dprint check        # チェックのみ
```

### プラグインのローカルテスト

詳細な手順は [DEVELOPMENT.md](DEVELOPMENT.md) を参照。

```bash
# 両プラグインを同時にロード（推奨）
claude --plugin-dir ./plugins/forge --plugin-dir ./plugins/anvil

# セッション限定でプラグインをロード
claude --plugin-dir ./plugins/forge

# マーケットプレイス経由
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install forge@bw-cc-plugins
```

### スクリプト動作確認

```bash
# レビュー対象の自動検出
python3 plugins/forge/skills/review/scripts/resolve_review_context.py [対象パス]

# ディレクトリスキャン（メタデータ JSON 出力）
python3 plugins/forge/scripts/doc_structure/classify_dirs.py [プロジェクトルート]
```

## Debugging [MANDATORY]

コード読解による推論で 2〜3 回修正しても解決しない場合は、**ログ挿入で実際の状態を観測する**。推測に基づく修正を繰り返さず、`print()` / 変数ダンプで実際に何が起こっているかを確認してから次の修正を行う。観測後にログを除去すること。

### 外部プラグインの実体確認 [MANDATORY]

外部プラグイン（doc-advisor 等）のスクリプトを調査・テストする前に、**実際に動いている実体パスを必ず特定してから読む**。

```bash
# 起動引数から --plugin-dir を確認
ps -axo args | grep 'plugin-dir'

# PATH から bin の所在を確認（実体ディレクトリが判明する）
echo $PATH | tr ':' '\n' | grep -iE 'advisor|plugin'
```

キャッシュ版（`~/.claude/plugins/cache/`）とローカル開発版（`--plugin-dir` 指定）は**同じバージョン番号でも実装が異なる**場合がある。キャッシュ版を実測した結果をローカル版に適用すると誤った結論になる。

## Testing [MANDATORY]

`plugins/` 配下の Python スクリプトにはテストが必須。SKILL.md はテスト困難なため例外。
`.claude/` 配下のローカルスキル・スクリプトはテスト対象外。

### テストの配置

`tests/` にプラグイン名・スキル名で分類:

```
tests/
├── common/                 # プラグイン横断（マニフェスト整合性等）
├── forge/
│   ├── review/
│   └── scripts/
└── {plugin}/               # 新プラグイン追加時も同構造
```

### テスト実行

```bash
# 一括実行
python3 -m unittest discover -s tests -p 'test_*.py' -v

# 特定モジュールのみ
python3 -m unittest tests.forge.review.test_xxx -v
```

### 品質評価テスト

ユニットテストはバグがないことを保証する。**検索品質**（精度・再現率）は `meta/test_docs/` で測定する（git 管理外、ローカルのみ）。

- doc-advisor の ToC 検索品質を同一ゴールデンセットで測定
- 評価スクリプト: `meta/test_docs/` 配下（`run_search_test.py` / `evaluate_toc_results.py` 等）
- 詳細・実行手順は `meta/test_docs/README.md`
