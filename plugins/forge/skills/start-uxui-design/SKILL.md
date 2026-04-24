---
name: start-uxui-design
description: |
  要件定義書の ASCII アートからデザイントークンと UI コンポーネントの視覚仕様を創造する。
  Apple HIG / Norman / Rams / Nielsen / Gestalt の知見に基づく UX 評価付き。iOS / macOS 対応。
  トリガー: "UXUIデザイン", "デザイントークン作成", "start uxui design"
user-invocable: true
argument-hint: "[feature-name] [--platform ios|macos]"
---

# /forge:start-uxui-design

要件定義書（ASCII アート付きの画面仕様）を入力に、デザイントークンと UI コンポーネントの視覚仕様を創造する。Apple HIG・Don Norman の感情デザイン・Dieter Rams の 10 原則・Nielsen ヒューリスティクス・ゲシュタルト原則の知識ベースに基づき、デザイン意図を理論的根拠とともに設計する。

## 位置づけ

本スキルは `/forge:start-requirements` の **Figma なし時の補完** として位置づけられる。ゼロから UI を設計する必要があり、Figma デザインも既存 UI もない場合に使用する。

デザイン方向性は Phase 2.0（Design Intent の取得）で要件本文・既存コードから読み取りまたは推定し、AskUserQuestion で確認する。プロジェクト全体に挙動モードを固定する設定ファイル（`.uxui-config.yaml` 等）は持たない。

> **Figma デザインの場合**: `/forge:start-requirements {feature} --mode from-figma` で要件抽出に進む。本スキルは不要。Figma デザインの UX 品質を検証したい場合は `/forge:review uxui` を使用する。

## フロー継続 [MANDATORY]

Phase 完了後は立ち止まらず次の Phase に自動で進む。不明点がある場合のみ AskUserQuestion で確認する。

## コマンド構文

```
/forge:start-uxui-design [feature] [--platform ios|macos]
```

| 引数 | 内容 |
| --- | --- |
| feature | Feature 名（省略時は対話で確定） |
| --platform | 対象プラットフォーム（省略時は選択肢提示） |

---

## 前提確認 [MANDATORY]

### Step 1: .doc_structure.yaml の確認

`.doc_structure.yaml` がプロジェクトルートに存在するか確認する。

- **存在しない** → AskUserQuestion を使用して確認する:
  ```
  .doc_structure.yaml が見つかりません。
  /forge:setup-doc-structure を実行してプロジェクト構造を定義する必要があります。今すぐ /forge:setup-doc-structure を実行しますか？
  ```
  - **はい** → `/forge:setup-doc-structure` を呼び出し、完了後に Step 2 へ進む
  - **いいえ** → 終了
- **存在する** → Step 2 へ

### Step 2: プラットフォーム選択

`--platform` 未指定時、AskUserQuestion を使用して選択肢を提示する:

```
対象プラットフォームを選択してください:
1. iOS     — iPhone / iPad アプリのデザイン
2. macOS   — Mac アプリのデザイン
```

### Step 3: Feature 名の確定

- 引数で指定済み → そのまま使用
- 未指定 → AskUserQuestion を使用して入力を求める

### Step 4: 出力先ディレクトリの解決

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/doc-structure/scripts/resolve_doc_structure.py" --doc-type requirement
```

- 結果あり → そのパスを使用
- 結果なし → `specs/{feature}/requirements/` をデフォルトとして使用

---

## セッション管理 [MANDATORY]

残存セッション検出:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/find_session.py
```

- `status: "none"` → セッション作成へ
- `status: "found"` → AskUserQuestion:「前回の未完了セッションがあります。削除しますか？」
  - **削除** → `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py cleanup {sessions[0].path}`
  - **残す** → 残存ディレクトリを無視して新規セッション作成へ

セッション作成:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/session_manager.py init \
  --skill start-uxui-design \
  --feature "{feature}" \
  --mode "{ios|macos}" \
  --output-dir "{出力先ディレクトリ}"
```

JSON 出力の `session_dir` をコンテキストに保持する。

---

## 知識ベースの読み込み [MANDATORY]

**常駐知識**として以下を **必ず** Read する。この文書は全 Phase を通じてコンテキスト内に保持する:

- `${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/design_philosophy.md` — デザイン哲学の統合フレームワーク（3 層モデル）。全てのデザイン判断の基盤

その他の知識ベース（`apple_design_principles.md`、プラットフォームガイド、テンプレート）はワークフロー内で Phase 別に JIT 読み込みする。一括読み込みしない。

---

## ワークフローの実行 [MANDATORY]

知識ベースの読み込み後、ワークフローファイルを **Read** し、そのファイルの指示に従って作業を実行する:

```
${CLAUDE_PLUGIN_ROOT}/skills/start-uxui-design/docs/uxui_analysis_workflow.md
```

Read 後、ワークフローファイルの Phase 1 から開始する。ワークフローは完了処理（AI レビュー・ToC 更新・commit 確認・セッション削除）まで自己完結している。SKILL.md に戻る必要はない。
