---
name: impl-ui
description: |
  UI Issue の Figma ベース実装フロー。`design` 段階では Figma からデザイン仕様書を作成してユーザーレビューを受け、実装設計書（Typography 対応表・アクション一覧を含む）を作る。`implement` 段階ではデザイン仕様書・実装設計書に従って UI を実装し、Figma SS・実機キャプチャ・コードの三点突合でレビューする。
  `anvil:impl-issue` が UI Issue と判定した Issue に対して Skill ツール経由で起動する（ユーザーからの直接起動は不可）。
user-invocable: false
argument-hint: "<issue番号> --stage design|implement"
allowed-tools: Bash(git *), Bash(gh issue view *), Bash(gh api *), Bash(python3 *), Bash(curl -s -H *api.figma.com*), AskUserQuestion, Agent, Skill, Read, Write, Edit, Grep, Glob
---

# anvil:impl-ui

UI Issue のうち **Figma を情報源とする設計・実装・レビュー**を担うスキル。`anvil:impl-issue` から `--stage` を指定して 2 回起動される。

このスキルは UI 設計・実装・レビューのみを行う。ブランチ操作・Issue 更新・commit・PR 作成は `impl-issue` の責務であり、本スキルは行わない。親が依頼している他の作業を引き継いではならない。

> [!NOTE]
> Figma 以外のデザインソース（別のデザインツール、画面設計書のみ等）に対応する場合は、本スキルと同じ `--stage` 契約を持つ別スキルを用意し、`impl-issue` 側の委譲先を差し替える。`impl-issue` は Figma 固有の手順を持たない。

## 入出力契約

| 段階        | 入力（impl-issue から）                                                                                | 出力（impl-issue へ返す）                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `design`    | Issue 番号、画面 ID・画面名、画面設計書パス、確認・調整事項パス（任意）、Figma URL、既存コード調査結果 | デザイン仕様書パス、実装設計書パス、ユーザー承認の結果                       |
| `implement` | Issue 番号、デザイン仕様書パス、実装設計書パス                                                         | 実装したファイル一覧、レビュー結果（差異件数・対応有無・実機キャプチャ有無） |

入力は同一セッションの親 context から得る。不足していれば `AskUserQuestion` で確認する（推測で埋めない）。

Phase を追加・改番するときは、本文の見出しと `references/` 内の Phase 番号を同時に更新する。

## Phase 0: 前処理（両段階共通）

1. `--stage` を解析する。`design` / `implement` 以外、または未指定なら `AskUserQuestion` で確認する
2. **Figma PAT 疎通確認**:

   ```bash
   curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
   ```

   失敗した場合はサイレントスキップしない。`AskUserQuestion` で「PAT を設定し直して再試行 / 中断」を確認する
3. **依存ツール確認**（`design` 段階のみ）: `/anvil:prepare-figma` の前提条件セクションに列挙されたツールの有無を確認する。**AI は依存ツールを勝手にインストールしない**。不足していれば `AskUserQuestion` で次を提示する:

   | 選択肢                                   | AI の次アクション                                                                                             |
   | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
   | AI が必要ツールをインストールする        | インストール実行 → 完了後に続行                                                                               |
   | 手動でインストールするので待機           | 中断し、ユーザー作業完了の合図を待つ                                                                          |
   | プレビュー生成をスキップし仕様書のみ作成 | Phase 1 の Agent prompt に「prepare-figma の Step 0 では『C. プレビュー生成をスキップ』を選ぶ」旨を含めて続行 |
   | 中断                                     | 本スキルを終了し、impl-issue へ中断を返す                                                                     |

## `--stage design`

### Phase 1: デザイン仕様書を作成する

`/anvil:prepare-figma` を **汎用 Agent**（`Agent` ツール、`subagent_type: general-purpose`）で実行する。メインコンテキストで Figma MCP は呼ばない（コンテキスト効率のため）。

Agent の prompt には次だけを渡す（親 context の Issue 本文・調査結果を貼り付けない）:

```text
Skill ツールで anvil:prepare-figma（スキル名。Agent の subagent_type の値ではない）を起動し、以下の入力でデザイン仕様書を作成してください。
- 画面 ID: <画面 ID>
- 画面設計書パス: <パス>
- 確認・調整事項パス: <パス。無ければ「なし」>
- Figma URL: <URL>
（Phase 0 で「プレビュー生成をスキップし仕様書のみ作成」を選んだ場合のみ次の行を含める）
- prepare-figma の Step 0 では「C. プレビュー生成をスキップ」を選んでください
完了したら、作成したデザイン仕様書のパスと、視覚比較セクション（Figma SS と AI プレビュー）の所在を報告してください。
```

`/anvil:prepare-figma` は画面設計書の読み込み、nodeId の検証と Figma URL 確定、MCP による詳細取得と PAT による補完、デザイン仕様書の作成、AI 理解プレビューの生成と自己検証ループ、三点突合（デザイン仕様書 vs 画面設計書 vs Figma）を行う。出力先は `specs/design/{画面 ID}/`（1 画面 = 1 ディレクトリ）。

### Phase 2: デザイン仕様書をレビューする

**必須チェックポイント**: Phase 3 に進む前にユーザーの承認を得る。レビューは「視覚比較」を中心に行い、AI の構造理解の誤りを暴く。

1. 生成されたデザイン仕様書を Read し、視覚比較セクションの 2 枚（Figma SS と AI プレビュー）を確認する
2. `AskUserQuestion` で確認する:

   ```text
   デザイン仕様書を確認してください。視覚比較セクションの 2 枚（Figma と AI プレビュー）を必ず見比べてください。
   - 承認: 構造が一致している。実装設計書の作成へ進みます
   - 修正要求: 差異があるのでレイアウト定義を修正して再レンダリングします
   - 中断: ここで中断し、後日再開します
   ```

修正要求の場合は Phase 1 の Agent を再実行し、レイアウト定義の修正と再レンダリングを行ってから再度確認する。

### Phase 3: 実装設計書を作成する

**作成前に必ず [`references/impl-design.md`](references/impl-design.md) を読む。**

デザイン仕様書と、impl-issue から受け取った既存コード調査結果（共通コンポーネント・デザイントークン定義・兄弟画面の実装）を照合し、実装設計書（How）を作成する。出力先はデザイン仕様書と同じ `specs/design/{画面 ID}/`。

必ず含めるもの:

- **Typography 対応表**: デザイン仕様書の全テキストノードをトークンまで確定させる（[`references/typography-mapping.md`](references/typography-mapping.md) に従う。行数 = テキストノード数）
- **アクション一覧**: デザイン仕様書「アクション一覧」の全行に実装方針を付ける
- パーツ対応表・使用コンポーネント・状態管理・API 連携・既存実装との整合性

完了したら、デザイン仕様書パス・実装設計書パス・承認結果を impl-issue へ返す。

## `--stage implement`

### Phase 4: UI 実装を行う

**実装前に必ず [`references/ui-implementation.md`](references/ui-implementation.md) と [`references/typography-mapping.md`](references/typography-mapping.md) を読む。**

> [!IMPORTANT]
> **デザイン仕様書 = 構造の正 / Figma = ビジュアル詳細の正**。仕様書の値（順序・サイズ・色・padding・font・条件分岐）をそのままコードに転記する。設計書に無い値は Figma MCP で取得し、推測で埋めない。

手順:

1. デザイン仕様書と実装設計書を Read する
2. 実装設計書の Typography 対応表を確認する（欠けていれば Phase 3 の規律で先に埋める）
3. アクション一覧・状態表を読み、タップ挙動を見た目と**同時に**実装する計画を立てる
4. 実装コードを書く前に、対応する仕様書ノード + Typography 行をコードコメントへ転記する
5. 既存コンポーネント流用時は Grep で値差分（font / color / size / padding）を照合する
6. **共用コンポーネント（2 画面以上から参照）を 1 画面の typography に書き換えない**。不一致なら画面専用コンポーネントを作る
7. 実装完了後、`references/ui-implementation.md` の「実装後セルフチェック」を通す。不合格があれば修正してから Phase 5 へ。妥協する場合は `AskUserQuestion` で確認する

### Phase 5: 実装レビューを行う

**レビュー前に必ず [`references/ui-review.md`](references/ui-review.md) を読む。** サイレントスキップ禁止。

1. デザイン仕様書と実装設計書を Read する
2. Figma MCP でデザインを確認する（`get_design_context` → `get_screenshot` → `get_metadata`）
3. **実装後キャプチャ**を取得する。プロジェクトのキャプチャ SKILL（`/forge:query-db-rules` で「キャプチャ」「screenshot」を検索し、ヒットすれば `Skill` ツールで委譲。例: `anvil:capture-emulator-screen`）を優先し、無ければプラットフォームに応じた手段を選ぶ。AI 単独で取れない場合は `AskUserQuestion` で「ユーザーがキャプチャして画像パスを返す / スキップ（レビュー結果に未実施を明記）/ 中断」を確認する
4. **三点突合**: Figma SS・実装キャプチャ・コード/設計書を突き合わせ、差異を洗い出す（`references/ui-review.md` の差分検証表と観点 ❶〜❺）
5. 類似画面との実装パターン比較、実装ルール確認チェックリストを実施する
6. 差異があれば修正し、再度突合する
7. 完了後、プロジェクトのコード生成コマンドを実行し（必要な場合）、新規コンポーネントを作ったならカタログとコンポーネント一覧文書を更新する

レビュー結果（差異件数・対応有無・実機キャプチャの有無）を impl-issue へ返す。impl-issue はこれを commit メッセージ・PR 本文に反映する。

## Figma MCP エラー時の対応

1. 必ずユーザーに報告する（何が起きたかを明示する）
2. 不確かな情報で進めない（MCP が失敗した場合、推測で設計・実装・レビューしない）
3. 代替手段（REST API）を試す
4. 検証が不十分なら中断し、「Figma 情報を取得できませんでした」と impl-issue へ返す
