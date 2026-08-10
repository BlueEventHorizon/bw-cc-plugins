# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

配布先プロジェクトの CLAUDE.md はほぼ空であり、汎用規範の主たる担い手は `/forge:onboarding` である。本ファイルはその写しではない。本ファイルに汎用規範を重複させるのは、onboarding が起動されない会話直の作業で規範が 0 になることを防ぐためである。

## Project Overview

Claude Code プラグインのマーケットプレイスリポジトリ。2 プラグインを格納・配布する。

- **forge** (v0.4.2) — ドキュメントライフサイクルツール。要件定義・設計・計画書の作成、コード・文書レビュー、自動修正に対応。レビューは交換可能なバックエンドで実行し、既定は外部依存を持たない `agent-review`（`review` / `agent-review` / `msg-review`）。相談は常駐 Codex セッションとの往復で行う（`talk-to-codex`）
- **anvil** (v0.1.1) — GitHub 連携（commit / PR / Issue 作成・トリアージ・実装）

> 上記 2 つの版数は `.version-config.yaml` が CLAUDE.md を同期対象として宣言している箇所であり、`/forge:update-version` が機械的に書き換える。手で消したり書式を変えたりしない（`tests/common/test_version_sync_drift.py` が検証する）。

全体像・スキル一覧・ワークフロー図は [README.md](README.md) を参照。

forge の文書検索は doc-advisor / doc-db の 2 backend 構成で、**どちらも本リポジトリの外にある**。doc-advisor の原本は別リポジトリ [BlueEventHorizon/DocAdvisor](https://github.com/BlueEventHorizon/DocAdvisor)、doc-db はローカル稼働の文書検索サーバである。backend 側の不具合を本リポジトリで回避してはならない（下記 SoT 項）。

## ドッグフーディング

本リポジトリは forge / anvil の原本であると同時に、**その 2 プラグインに管理される利用プロジェクトでもある**。

この二重性は、**自分の設定を製品の仕様と取り違える**という固有の罠を生む。プラグインが規定しているのは仕組み（`.doc_structure.yaml` による rules / specs のパス解決）だけで、**パスそのものは各プロジェクトの設定値**である。本リポジトリが `docs/rules/` / `docs/specs/**/` を使うのは設定の結果に過ぎず、他プロジェクトは `rules/` / `specs/*/` 等の別の配置を取る。

## 重要規約 [MANDATORY]

- **記述を事実の証拠にしない**: 文書・設定の記載内容、未コミットの作業中成果物、未合意の前提を根拠に判断・報告しない。実体を確認してから述べる
- **認識した不整合・疑問は必ず出す**: 自分で気づいた矛盾・非対称・判断の分岐点を、現状維持や省略の理由にしない。黙って進めたものは報告漏れではなく隠蔽である
- **破棄を伴う操作は現状確認から**: 差し戻し・上書き・削除を提案または実行する前に、対象の未コミット変更を確認する
- **プロジェクトの不具合は担当と無関係に最優先**: スキル・スクリプト・テストの異常を見つけたら、自分が作った箇所か否かを問わず、進行中の作業を直ちに中断して修正に全力を当てる。「自分の変更とは無関係」「担当外」は放置の理由にならない。AI の責任はこのプロジェクトのすべての要素が正しく動くことにある
- **設計文書は `docs/specs/**/{requirements,design}/` に保存**: plan モードで作成した重要設計も ID プレフィックス（`REQ-` / `DES-` / `ADR-`）で命名する
- **プラグインランタイム文書の境界**: `plugins/*/docs/`（現状 forge のみ）は SKILL.md がランタイム Read する配布物。リポジトリルートの `docs/` 配下はプロジェクト自身のメタ文書（配布物に含めない）
- **配布物（`plugins/` 配下）に具体パスを書かない**: rules / specs のパスは常に `.doc_structure.yaml` 経由で解決する。本リポジトリ固有の事情（`forge` / `anvil` という具体名、`meta/`、worktree 配置、原本 SoT である立場）も埋め込まない
- **配布物（`plugins/` 配下）のうち利用者環境で読まれるもの（SKILL.md / agents / commands / 内蔵 docs）からプロジェクト開発文書（`docs/` 配下）を参照しない**: パス直書きも spec ID 参照（`DES-028 §3.4.1 に従う` 等）も禁止。**script のコメント・docstring は対象外**。規範は配布物側に持たせる。置き場は「参照元に本文を書く」か「配布物内に別文書を作って参照する」のどちらでもよい（[implementation_guidelines.md](docs/rules/implementation_guidelines.md)）
- **`docs/` 配下では必要でない参照リンクを書かない**: 参照先の発見は検索に委ねる。文書には「何に依存するか（概念・ID）」だけ残す。**書かなければ本文の意味が通じない場合に限り**マークダウンリンク方式（`[表示名](相対パス)`）で書く。地の文でのパス直書き・リンクなしのファイル名言及は使わない。**配布物は対象外**（決定論的に閉じた木として配布されるため開発者責任で内部リンクを書く。記法は forge の `document_style_guide.md` §5.1）
- **本リポジトリは下流プロジェクトを導く SoT である**。配布された SKILL / agent / script を使っている最中に不具合・不足を発見したら、`~/.claude/plugins/cache/` のキャッシュ実体や下流プロジェクトでの回避策で済ませず、必ず本リポジトリ（`plugins/{anvil,forge}/...`）の原本を直す。キャッシュは次回 install で再生成されるため、原本を直すことが下流すべてへの正しい伝播経路になる。「刹那的に今のセッションで動くようにする」ではなく「プロジェクトを正しいものに完遂し、すべての他のプロジェクトを正しく導く」が目的。memory に回避策を保存するのは原本修正の代替にならない
- **決定論的な定型処理（列挙・転記・集計・ファイル生成）は script 化する**。AI は判断のみ担い、手転記・手列挙をしない
- **agent/SKILL のプロンプト指示は混入点でなく出力構築点に 1 箇所だけ置く**。近接した複数箇所への同一指示は重複であり追記しない

## meta/ ディレクトリ（現在不在）

`meta/` は研究・評価・ゴールデンセット用の作業領域であり、**いつでも削除される**。現時点ではこのワークツリーにもメインワークツリーにも存在しない。

- `plugins/` / `tests/` / `docs/` 配下のコード・文書は `meta/` 内のファイルに依存してはならない（`meta/` から `plugins/` のモジュールを呼ぶ逆方向は許容）
- SKILL として配布しない（ユーザー環境に `meta/` は存在しない）
- 検索品質（精度・再現率）の評価スクリプトとゴールデンセットの置き場。ユニットテストはバグの不在を保証するが、検索品質はここで測る

## Development

ビルド・パッケージ管理のシステムは無い。**Python スクリプトは標準ライブラリのみで動作する（外部依存を追加しない）**。`makefile` はビルドではなくインストール・外部接続用（`make install-forge` / `install-anvil` / `install-all`、Codex 向けは `install-*-codex`）。

- **CI（`.github/workflows/ci.yml`）のゲートは 2 つ**: `python3 -m unittest discover -s tests -p 'test_*.py'` と `dprint check`。JSON / TOML / Markdown / YAML を編集したら [dprint](https://dprint.dev/) で `dprint fmt` を通す（設定は `dprint.jsonc`）。通さないと CI が落ちる
- ローカル読み込み: `claude --plugin-dir ./plugins/forge --plugin-dir ./plugins/anvil`。詳細は [DEVELOPMENT.md](DEVELOPMENT.md)
- `AGENTS.md` は `CLAUDE.md` へのシンボリックリンク（Codex 向け）。どちらを編集しても同一実体が変わる

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

**実体パスを特定したら、次に「どのブランチか」を確認する。** ローカル開発版は作業中の feature ブランチがチェックアウトされていることがあり、そこでは**リリース済みの契約が既に書き換えられている**。ここを確認せずに読むと、未リリースの変更を「現在の仕様」と誤認し、正しい自プロジェクトの記述を不具合として報告してしまう（実際に、doc-advisor の `index-docs` 引数契約で発生した）。契約の正本は当該リポジトリの `main` である。

```bash
# 実体ディレクトリのブランチと、契約の正本（main）との差を確認する
git -C <実体パス> branch --show-current
git -C <実体パス> show main:<契約を定める SKILL.md やスクリプト> | grep <対象の引数名>
```

## Testing [MANDATORY]

`plugins/` 配下の Python スクリプトにはテストが必須。SKILL.md はテスト困難なため例外。
`.claude/` 配下のローカルスキル・スクリプトはテスト対象外。

テストは `tests/` にプラグイン名・スキル名で分類して配置する。

```bash
# 一括実行
python3 -m unittest discover -s tests -p 'test_*.py' -v

# 特定モジュールのみ
python3 -m unittest tests.forge.review.test_xxx -v
```

<!-- FORGE_ONBOARDING_START hash=d2d3c6b51826 -->

> このブロックは forge の onboarding スキルが生成する。手で編集しない（次回実行で上書きされる）。
> `${CLAUDE_PLUGIN_ROOT}` は forge プラグインの配置先を指すプレースホルダであり、この文脈では実パスに解決されない。実体を読むには onboarding スキルを起動する。

## forge 必読文書 [MANDATORY]

**NEVER skip.** 下記を全て読み込み、深く理解すること。

- `${CLAUDE_PLUGIN_ROOT}/docs/document_style_guide.md` — 文書を書く・直すときの記述スタイル
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_format.md` — ADR を直接起票するときの書式
- `${CLAUDE_PLUGIN_ROOT}/docs/design_principles_spec.md` — 設計書の保守と歴史的記録の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/adr_principles_spec.md` — ADR に何を書き何を書かないか、可変性と失効の扱い
- `${CLAUDE_PLUGIN_ROOT}/docs/forge_anti_patterns.md` — 実装・文書で踏んではならないアンチパターン
- `${CLAUDE_PLUGIN_ROOT}/docs/sensitive_information_spec.md` — リポジトリに含めてはならない情報
- `${CLAUDE_PLUGIN_ROOT}/docs/scope_proportionality_spec.md` — 比例性の原則（過剰設計の抑止）

## forge プロジェクト文書 [MANDATORY]

- プロジェクトルール文書の参照には `query-db-rules` SKILL を使う
- プロジェクトルール文書の更新後には `update-db-rules` SKILL を使う
- プロジェクト仕様の参照には `query-db-specs` SKILL を使う
- プロジェクト仕様の更新後には `update-db-specs` SKILL を使う

## forge 重要規約 [MANDATORY]

- **実装・文書改編に着手する前に `/forge:query-forge-rules`・`/forge:query-db-rules` で関連する原則・ルールを特定して読む**（スキル経由の作業は各スキルの調査 Phase がこれを担う。会話直の作業でも省略しない）
- **ルールはルール文書管理**: コンテキスト肥大化防止のため、CLAUDE.md にルールを詰め込まないことを推奨する
- **一般の作業で CHANGELOG.md・version 関連ファイルを編集しない**。リリースコミットでまとめて更新（`/forge:update-version` を使う）
- **`.toc_work/` 等の消えるべき一時物は `.gitignore` に入れない**。残存が `git status` に untracked として出ることで異常を検知できる

<!-- FORGE_ONBOARDING_END -->
