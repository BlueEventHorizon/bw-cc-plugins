# UXUI デザインガイド

要件定義書の ASCII アート付き画面仕様を入力に、デザイントークンと UI コンポーネント視覚仕様を UX 評価付きで生成する。デザイナー不在の開発で、理論的根拠のあるデザインシステムを構築するためのスキル。

## start-uxui-design

```
/forge:start-uxui-design [feature] [--platform ios|macos]
```

| 引数 | 説明 |
|------|------|
| `feature` | Feature 名（省略時は対話で確定） |
| `--platform` | `ios` / `macos`（省略時は対話で選択） |

### いつ使うか

- 要件定義書が完成した後、設計書を作成する前
- iOS / macOS アプリのデザインシステムを構築したいとき
- デザイナーなしで理論に裏付けられた UI を作りたいとき

### パイプラインでの位置づけ

```
start-requirements → start-uxui-design → start-design → start-plan → start-implement
 (何を作るか)          (どう見せるか)       (どう作るか)     (いつ作るか)   (作る)
```

start-uxui-design はオプション。デザイントークンが不要な場合はスキップして start-design に進める。

### 使用例

```bash
# iOS アプリのデザイン生成
/forge:start-uxui-design user-auth --platform ios

# macOS アプリ、Feature 名は対話で決定
/forge:start-uxui-design --platform macos
```

---

## 3 層統合フレームワーク

全デザイン判断の基盤となる階層構造。下層から順に適用し、上層は下層を超えることができない。

| 層 | 役割 | 例 | 制約 |
|----|------|-----|------|
| 第 1 層: 認知の制約 | 従う（不可侵） | Fitts の法則、Hick の法則、コントラスト比 | 違反するデザインは不可 |
| 第 2 層: 構造の道具 | 組み合わせる | モジュラースケール、色彩調和、8pt グリッド | 第 1 層を破る組み合わせは不可 |
| 第 3 層: 美の方向性 | 選択する | Dieter Rams、Don Norman、Tufte、わびさび | 第 1・2 層の範囲内で自由 |

---

## 6 Phase ワークフロー

| Phase | 内容 | 知識ベース |
|-------|------|-----------|
| 1 | 要件の読み込み（ASCII アート解析） | — |
| 2 | デザイン方向性の決定（哲学的立場の選択） | design_philosophy.md |
| 3 | デザイントークン創造（色彩・タイポグラフィ・スペーシング） | apple_design_principles.md、プラットフォームガイド |
| 4 | コンポーネント視覚設計（ASCII → HIG 準拠コンポーネント） | プラットフォームガイド、テンプレート |
| 5 | UX 自己評価（3 層フレームワークでセルフチェック） | design_philosophy.md |
| 6 | 文書生成・品質確認（`/forge:review uxui --auto`） | review_criteria_uxui.md |

### 出力

| ドキュメント | ID 体系 | 内容 |
|-------------|---------|------|
| デザイントークン | THEME-xxx | 色彩、タイポグラフィ、スペーシング、エレベーション |
| コンポーネント視覚仕様 | CMP-xxx | 各 UI コンポーネントの視覚設計（サイズ、状態、インタラクション） |

---

## UX レビュー

`/forge:review uxui` で独立レビューも可能。3 つの perspectives で検証する:

| Perspective | 観点 |
|-------------|------|
| **hig_compliance** | Apple HIG 4 原則への適合 |
| **usability** | Nielsen ヒューリスティクス、アクセシビリティ |
| **visual_system** | トークンの一貫性、Gestalt 原則 |

```bash
# デザイントークンとコンポーネント仕様をレビュー
/forge:review uxui specs/user-auth/design/

# 自動修正付き
/forge:review uxui specs/user-auth/design/ --auto
```

---

## 適用シナリオ

詳細な適用シナリオは [uxui_scenario.md](../uxui_scenario.md) を参照。

| シナリオ | 概要 |
|---------|------|
| 新規 iOS アプリ | ゼロからデザインシステムを構築 |
| 既存アプリの UI 統一 | 既存コンポーネントをトークンベースに移行 |
| macOS アプリ | macOS HIG に特化したトークン生成 |
| デザインレビューのみ | 既存デザイン仕様を UX 観点でレビュー |
| 要件変更後の再生成 | ASCII アート変更に追従してトークンを更新 |
