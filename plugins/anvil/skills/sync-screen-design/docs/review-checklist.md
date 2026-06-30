# 修正レビュー・三点突合（sync-screen-design）

Figma に合わせて直した後、**正しく直っているか**を確認するための突合手順とチェックリスト。

## 目次

1. [三点突合](#三点突合)
2. [差分検証の観点](#差分検証の観点)
3. [実装ルール確認チェックリスト](#実装ルール確認チェックリスト)
4. [特に見落としやすい観点](#特に見落としやすい観点)
5. [よくある失敗](#よくある失敗)

---

## 三点突合

以下 3 点を突き合わせ、差異があれば修正 → 再突合する。

1. **Figma**（実描画スクショ + 構造データ）— 採用判断は**スクショが基準**。
2. **実装キャプチャ**（Emulator / Simulator。取得手順は `capture-emulator-screen` Skill）— 実機/シミュレータでの見た目。
3. **コード** — トークン・余白・構造・アクション。

いずれかが取得できない場合は、その旨を報告して中断する（不確かな情報で進めない）。

---

## 差分検証の観点

| 観点                   | 確認手順                                                                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 構造順序               | Figma の子要素順と `Column.children` / `Row.children` を 1 行ずつ目視照合                                                         |
| Typography             | 写っているテキストごとに `appTextTheme*` / `appTextColors.*` を Grep 照合（[typography-and-tokens.md](typography-and-tokens.md)） |
| 値の一致               | `font` / `color` / `size` / `padding` / `gap` / `radius` を Grep で照合                                                           |
| 条件分岐               | 仕様文言（「100 文字以上」等）と if 条件が 1:1                                                                                    |
| アクション             | タップ・遷移・トグルの全行が実装済み（空 onTap / TODO なし）                                                                      |
| 共用 Widget            | 共用部品が 1 画面の見た目に書き換わっていない                                                                                     |
| Figma 実値 vs トークン | Figma の `style`（fontSize/fontWeight/lineHeightPx/fills.color）と採用トークンの実体が一致、または乖離が明記されている            |
| 直書き禁止             | hex / 数値を直書きせず、トークン or `static const` 経由                                                                           |

---

## 実装ルール確認チェックリスト

| #  | ルール                        | 確認内容                                                                                   |
| -- | ----------------------------- | ------------------------------------------------------------------------------------------ |
| 1  | デザイントークン使用          | 色・フォントがハードコードされていない                                                     |
| 1b | トークン名の一致              | 採用トークン名が Figma 実値に対応（[typography-and-tokens.md](typography-and-tokens.md)）  |
| 1c | トークン実体まで突合          | 採用トークンの実体値（fontWeight/lineHeight/hex）が Figma `style` と一致、または乖離を明記 |
| 2  | CommonAssets 使用             | `IconData`（Icons.xxx）を使っていない                                                      |
| 3  | slang 使用                    | UI 文字列がハードコードされていない                                                        |
| 4  | 既存コンポーネント優先        | `docs/COMPONENT_TOC.md` のコンポーネントを使う                                             |
| 5  | Figma 値を使用                | 設計/スクショにない値を空想で実装していない                                                |
| 6  | 共用コンポーネント非改変      | 1 画面のために共用部品を書き換えていない                                                   |
| 7  | Spacing は const/トークン経由 | `EdgeInsets` / `SizedBox` の数値を直書きしていない                                         |

### 該当する規約ドキュメントの確認

修正対象に応じて以下を Read して準拠を確認:

- `docs/implementation/ui/ui_common_rules.md`（共通）, `bottom_sheet.md`, `list_view.md`, `filter_sheet.md`, `routing.md`
- `.cursor/rules/coding-standards.mdc` / `coding-guidelines.mdc` / `riverpod-guide.mdc` / `freezed-guide.mdc`

---

## 特に見落としやすい観点

### ❶ アイコン・要素の有無は必ずスクショで判断

node ツリーにあっても `visible=false` の隠しノードは実装しない。**実描画に写っているか**で判断する。

> 実例: ボタンの左右アイコンを node ツリーで判断 → 実描画はテキストのみで誤り（右アイコンは `visible=false`）。

### ❷ Figma の「画面外」メモ・コメント

- ページ直下 view 周辺フレームの `メモ` / `Memo` / `Note` / `仕様` / `件数` / `最大` を検索。
- `/v1/files/{key}/comments` で pinned コメントを精査。
- 隣接するバリエーション view（タブ切替後・状態違い）も確認。

### ❸ Figma 実値と採用トークン実体の突合

「`appTextThemeJP.body5_11R` を採用」と書いても、その実体（fontWeight/lineHeight/hex）が Figma 値と一致するとは限らない。実体ファイルを Read し、Figma `style` と突合。乖離があれば前例 PR と同じ判断で揃え、コメントに併記。

> 既知の乖離: `appTextColors.link`(#4699DC) ≠ テキストボタン色 `appButtonColors.textButton`(#49A4EC)。

### ❹ 件数（初期 / 追加 / 上限）の根拠

「最大 N 件」「追加 N 件」は書いてあっても**初期表示件数が不明**なことが多い。Figma のサンプル枚数（見た目）を件数指定と勘違いしない。値の出典（仕様書 / デザイナー / チケット）を残す。

### ❺ 同名フレーム・クリップ

同名フレームが複数あることがある（dev リンク優先・複数候補はユーザー確認）。クリップされたフレームで「要素が無い」と誤判定しない。

---

## よくある失敗

1. **スクショ未確認で node ツリーから有無を判断** → 必ず `get_screenshot` / REST レンダリングで確認
2. 色・フォントをハードコード → トークン使用
3. `IconData` 直接使用 → CommonAssets
4. UI 文字列ハードコード → slang
5. 共用コンポーネントを 1 画面の見た目に変更 → 画面専用 Widget 化
6. トークン名を推測で選ぶ → 実体ファイルで検証
7. Spacing を直書き / 独自命名 → トークン or 前例の `static const` を踏襲
8. アクション（遷移・トグル）を後回し → 見た目と同時に実装
9. 修正後にスクショ突合をしない → 再度突合し、`dart format` / lint / `melos run gen`
10. **編集前ビルドのスクショで裏取りした気になる** → `capture-emulator-screen` Skill でキャプチャ前に必ず最新コードを反映（リロード/リスタート、アセット・l10n はフル再ビルド）。反映の確証を取ってから比較する
