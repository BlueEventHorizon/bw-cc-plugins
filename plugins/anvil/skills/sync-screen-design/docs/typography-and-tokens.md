# Typography・デザイントークン照合（sync-screen-design）

Figma の値（fontSize / fontWeight / lineHeight / color）を **推測せず** `AppTextThemeJP` / `AppTextThemeEN` / `AppTextColors` 等のトークンへ機械的に変換するためのルール。

> **教訓**: トークン名を「だいたい」で選ぶと font / color が大量にズレる。**Widget を直す前に Typography 対応表を作る。**

## 目次

1. [手順](#手順)
2. [weight → suffix](#weight--suffix)
3. [JP トークン（size+weight+line_height）](#jp-トークンsizeweightline_height)
4. [EN トークン（英数字・件数）](#en-トークン英数字件数)
5. [トークンの再発明禁止](#トークンの再発明禁止)
6. [色 → AppTextColors](#色--apptextcolors)
7. [言語（JP/EN）判定](#言語jpen判定)
8. [よくある失敗](#よくある失敗)

---

## 手順

1. 修正対象に**実描画で写っている**全テキストを列挙する（スクショ基準。[figma-side.md](figma-side.md) Step2）。
2. 各テキストの `size / weight / line_height / color(hex) / 言語(JP|EN)` をノード JSON の `style` / `fills` から抜く。
3. `app_text_theme_jp.dart` / `app_text_theme_en.dart` を Read し、**fontSize + fontWeight + height** が一致するトークンを選ぶ。
4. hex → `AppTextColors`（後述表）。
5. 対応表をコードコメント（or 実装メモ）に書いてから直す。

```dart
// Figma (staffName): size 14, weight 600, line_h 20, #222222 (JP)
// → appTextThemeJP.body2_14B + appTextColors.primary
Text(user.name, style: context.appTextThemeJP.body2_14B.copyWith(color: context.appTextColors.primary))
```

**禁止**: 列挙したテキスト数 > 対応表の行数で着手 /「似たトークン」で埋める。

---

## weight → suffix

| Figma weight | FontWeight | suffix             |
| ------------ | ---------- | ------------------ |
| 300          | w300       | `R`                |
| 400          | w400       | `R`（EN 側に多い） |
| 590 / 600    | w600       | `B`                |

---

## JP トークン（size+weight+line_height）

`line_height` が無いと body / label を区別できない。**3 点で選ぶ**。

| size | weight | line_h | トークン (JP) |
| ---- | ------ | ------ | ------------- |
| 16   | 600    | 24     | body1_16B     |
| 14   | 600    | 20     | body2_14B     |
| 14   | 300    | 20     | body2_14R     |
| 14   | 600    | 18     | label2_14B    |
| 14   | 300    | 18     | label2_14R    |
| 12   | 600    | 18     | body4_12B     |
| 12   | 300    | 18     | body4_12R     |
| 12   | 600    | 16     | label3_12B    |
| 12   | 300    | 16     | label3_12R    |
| 11   | 600    | 16     | body5_11B     |
| 11   | 300    | 16     | body5_11R     |
| 10   | 600    | 14     | body6_10B     |
| 10   | 300    | 14     | body6_10R     |

> 例: 14/600/lh20 → `body2_14B`、14/600/lh18 → `label2_14B`。**lh で body/label が変わる**。
> 行高だけ Figma と違う場合は、トークンに `copyWith(height: lh / size)` で合わせる（例 lh22/sz14 → `copyWith(height: 22 / 14)`）。

---

## EN トークン（英数字・件数）

英数字・単位（`172cm`・件数 `(99)`・ID）は `appTextThemeEN` を使う。

| size | weight | letterSpacing | トークン (EN)  |
| ---- | ------ | ------------- | -------------- |
| 14   | 600    | -             | label_14B      |
| 14   | 400    | -             | label_14R      |
| 13   | 600    | -             | label_13B      |
| 13   | 600    | -0.39 (LS-3)  | label_13B_LS_3 |
| 12   | 400    | -             | label_12R      |
| 12   | 600    | -             | label_12B      |
| 11   | 400    | -             | label_11R      |
| 11   | 600    | -0.33 (LS-3)  | label_11B_LS_3 |

> **`LS-3`**: letter spacing -3%（fontSize × -0.03）。価格 `¥X,XXX`(13px)・割引率 `XX%OFF`(11px) はこの系。`copyWith(letterSpacing:)` で再現せず**対応トークンをそのまま使う**。

---

## トークンの再発明禁止

値（fontSize / letterSpacing / weight / 色）を `copyWith` や `Color(0x...)` / `const _xxx =` で直書きする前に、**同値の既存トークンが無いか必ず探す**。Figma の Style 名は概ねトークン名に 1:1 対応する。

| Figma Style / Variable         | トークン                            | 定義場所                 |
| ------------------------------ | ----------------------------------- | ------------------------ |
| `EN/Label/Label_13B_LS-3`      | `appTextThemeEN.label_13B_LS_3`     | `app_text_theme_en.dart` |
| `JP/body/Body4_12B`            | `appTextThemeJP.body4_12B`          | `app_text_theme_jp.dart` |
| `text/primary` `text/tertiary` | `appTextColors.primary` `.tertiary` | `app_text_colors.dart`   |
| `button/textButton`            | `appButtonColors.textButton`        | `app_button_colors.dart` |

手順: ①Figma の Style/Variable 名を控える → ②`app_text_theme_*.dart` / `app_*_colors.dart` を Grep → ③あればトークン、`copyWith` は差分（色など）のみ → ④無い場合のみ `static const`（出典コメント必須）。

**禁止**: 既存トークンと同値の magic number を新規定義 / `copyWith(fontSize: 13, letterSpacing: -0.39)` でトークンを実質再現。

---

## 色 → AppTextColors

| Figma hex | トークン                     | 用途                                             |
| --------- | ---------------------------- | ------------------------------------------------ |
| #222222   | primary                      | 本文・強調                                       |
| #545454   | secondary                    | 補助テキスト                                     |
| #878787   | tertiary                     | ラベル・非リンクの副情報                         |
| #4699DC   | link（icon/text）            | **タップ動作あり**のリンク                       |
| #49A4EC   | `appButtonColors.textButton` | テキストボタン（「もっと見る」「シェアする」等） |
| #E34234   | brand                        | ブランド強調・選択タブ・価格                     |

色トークン選択の優先順位: ①タップ動作が定義 → `link` ②hex → 上表 ③Figma 変数。
**同じ hex でも文脈でトークンが変わる**（リンク→link、非リンク副情報→tertiary、ブランド→brand）。
**禁止**: hex を見ずに「リンクっぽいから link」「小さいから tertiary」と推測。

> 既知の乖離例: `appTextColors.link`(#4699DC) と `appButtonColors.textButton`(#49A4EC) は別物。テキストボタン色は後者。**完全に違う色（青 vs 赤）なら仕様/トークンどちらが正か確認**、軽微な hex 差はトークン優先。

---

## 言語（JP/EN）判定

| 内容                 | 使用           |
| -------------------- | -------------- |
| 日本語 UI 文言       | appTextThemeJP |
| 英数字・cm・件数・ID | appTextThemeEN |
| 混在（名前 + cm 等） | 要素ごとに分離 |

> **フォントファミリーは指定しない**（システムフォント）。JP/EN は言語に応じたトークンの使い分けに過ぎない。Figma の「SF Pro / Hiragino」表記はこの使い分けを表すだけで、`fontFamily` をコードに書く意味ではない。

---

## よくある失敗

| 失敗                                | 正しい対応                                     |
| ----------------------------------- | ---------------------------------------------- |
| `body5_11B` を「もっと見る」に使う  | Figma 実値確認 → `label2_14B` 等               |
| `#878787` なのに `secondary` を使う | `#878787` → `tertiary`                         |
| トークン使用＝デザイン準拠と錯覚    | **トークン名・実体値まで**対応表で検証         |
| トークン名から weight を推測        | 実体ファイル（`app_text_theme_*.dart`）を Read |
| 件数（数字）を JP トークンで表示    | EN トークン（`label_14R` 等）に差し替え        |
