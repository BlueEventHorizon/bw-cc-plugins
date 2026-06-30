---
name: sync-screen-design
description: 画面設計書・Figma・実装キャプチャの三点突合で、実装済み画面を仕様とデザインに同期する。Figma 側の対象ノード特定、スクリーンショットによる採用判断、visible 判定、色・フォント・余白の実値抽出、capture-emulator-screen による実装側キャプチャ、デザイントークン対応、差分修正までを扱う。「Figma 通りに直して」「デザイン差分を抽出して修正して」「この画面を設計とデザインに合わせて」と言われた時に使用する。
user-invocable: true
argument-hint: "<画面名 / Figma URL / node-id>"
allowed-tools: Bash(curl -s -H *api.figma.com*), Bash(curl -sL *), Bash(uv run *), Bash(python3 *), Bash(dart format *), Read, Glob, Grep, Edit, Write, AskUserQuestion, Skill(capture-emulator-screen)
---

# sync-screen-design

実装済みの画面を画面設計書・Figma・実装キャプチャで突き合わせ、仕様とデザインに同期する。

## 鉄則（これだけは外さない）

1. **スクリーンショットが採用判断の唯一の基準**。node ツリーに要素が存在しても、実描画に写っていなければ実装しない（`visible=false` の隠しノードがツリーに残る）。
2. **色・フォントは名前でなく実値で照合**。Variable / Style 名だけを根拠に変えない。
3. **フォントファミリーは指定しない**（システムフォント任せ）。Figma の「SF Pro / Hiragino」は EN/JP トークンの使い分けを意味するだけ。
4. **共有コンポーネント（2 画面以上で import）を 1 画面の Figma に合わせて書き換えない**。画面専用 Widget で対応する。
5. **値の直書き禁止**。デザイントークン or `static const` 経由。
6. **キャプチャ前に必ず最新コードを反映する**（ホットリロード／リスタート、アセット・l10n はフル再ビルド）。編集前ビルドのスクショで「直った」と判断しない（`capture-emulator-screen` Skill）。
7. **Figma は見た目の正、画面設計書・機能設計書は仕様/条件/遷移の正**として扱う。矛盾がある場合は勝手に決めず、差分としてユーザーに確認する。

## 必須実行フロー（UI 見た目差分）

UI の見た目差分を修正するときは、コード値だけで判断せず、必ず以下を実施する。

0. 対象画面の画面設計書・機能設計書を確認し、実装スコープ、表示条件、遷移、状態バリエーションを把握する。
1. Figma の対象ノードを特定し、画面設計書の nodeId が古くないか検証したうえで、Figma スクリーンショットを取得する。
2. 最新コードを Emulator / Simulator へ反映する（hot reload / restart / full rebuild を使い分ける）。
3. Emulator / Simulator のスクリーンキャプチャを取得する。
4. Figma SS / 実装 SS / コードの三点で比較する。
5. 差分を修正し、再キャプチャして確認する。

詳細手順は [docs/figma-side.md](docs/figma-side.md)、`capture-emulator-screen` Skill、[docs/review-checklist.md](docs/review-checklist.md) を参照する。

## ワークフロー

| # | フェーズ                                                | 参照                                                           |
| - | ------------------------------------------------------- | -------------------------------------------------------------- |
| 1 | Figma 側の扱い（対象特定・SS 取得・実値抽出・差分分類） | **[docs/figma-side.md](docs/figma-side.md)（必読）**           |
| 2 | Typography・トークン照合（推測せず実値→トークン）       | [docs/typography-and-tokens.md](docs/typography-and-tokens.md) |
| 3 | 実装側のキャプチャ取得（Emulator / Simulator）          | **`capture-emulator-screen` Skill（必読）**                    |
| 4 | 差分修正（実装ルールに従って直す）                      | [docs/implementation-rules.md](docs/implementation-rules.md)   |
| 5 | 三点突合（Figma SS ↔ 実装キャプチャ ↔ コード）＋検証    | [docs/review-checklist.md](docs/review-checklist.md)           |

> このスキルは **impl-issue に依存しない独立スキル**。実装側キャプチャは共通スキル `capture-emulator-screen` に委譲し、UI 実装・Typography・レビューの知見は本スキルの docs/ に取り込み済み。

## 進め方の要点

- Figma 側は **必ず [docs/figma-side.md](docs/figma-side.md) を読んでから**着手する。テキストを直す前に [docs/typography-and-tokens.md](docs/typography-and-tokens.md) で対応表を作る。
- 差分は **スコープ（余白/色/タイポ/配置/アセット/TODO）× 難易度（🟢 値変更 / 🟡 アセット追加・共有部品 / 🔴 モデル・API・新規セクション）** で分類し、🟢 の画面ローカルから着手する。
- 🟡🔴 や Figma に根拠が取り切れない項目（❓）は、勝手に変えずユーザーに確認する。
- 修正後は必ず [docs/review-checklist.md](docs/review-checklist.md) で三点突合する。
- 補足（任意）: 対象ノードの確定は [resolve-figma-node](../resolve-figma-node/SKILL.md)、Figma MCP/REST の一般仕様は [figma-mcp-guide](../figma-mcp-guide/SKILL.md) も参照できる（同等の手順は docs/figma-side.md に内包済み）。
