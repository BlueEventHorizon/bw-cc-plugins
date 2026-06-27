# 実装ルール（sync-screen-design）

Figma に合わせて実装コードを直すときに守るルール。差分を「正しく」コードへ落とすための知見。

## 目次

1. [実装ポリシー](#実装ポリシー)
2. [共用コンポーネントの変更禁止](#共用コンポーネントの変更禁止)
3. [既存流用時の差分照合](#既存流用時の差分照合)
4. [レイアウト落とし込みノウハウ](#レイアウト落とし込みノウハウ)
5. [インタラクション同時実装](#インタラクション同時実装)
6. [トークン・アセット・文言の使い方](#トークンアセット文言の使い方)
7. [状態管理の選択](#状態管理の選択)
8. [修正後セルフチェック](#修正後セルフチェック)

---

## 実装ポリシー

- **Figma（実描画）= 正**。順序・サイズ・色・padding・font・条件分岐をそのまま転記する。
- **既存パターンより Figma 優先**（Figma と整合しない既存構造を無批判に流用しない）。
- **フォントファミリーのみ例外**（システムフォント）。
- **トークン使用 ≠ デザイン準拠** — トークン**名・実体値**まで Figma 実値と照合する（[typography-and-tokens.md](typography-and-tokens.md)）。
- **直書き禁止** — 色 hex・数値はトークン or `static const` 経由。

---

## 共用コンポーネントの変更禁止 [最重要]

2 画面以上から import される Widget を、**1 画面の見た目に合わせて書き換えない**。

- **判断基準**: `search-code-toc` / Grep で **2 画面以上**から import されていたら共用。
- 共用部品のフォント/サイズ/余白が Figma と不一致でも、その部品本体を直さない。

| 状況                                      | 対応                                                |
| ----------------------------------------- | --------------------------------------------------- |
| 共用部品の typography 等が Figma と不一致 | 画面専用 `components/` Widget を新規作成            |
| 共用部品で十分                            | 既存値と Figma の diff を明示し、一致を確認して流用 |
| 1 画面だけ特殊                            | `components/` 配下に画面専用 Widget                 |

> 例: `AppSecondaryButton` の高さ 48→47、`AppItemLabel` のフォント、`AppContentCard` のハートサイズ等は**共用部品**。1 画面の Figma 差のために本体を変えない。変えると他画面が崩れる。これらは「共有部品改修＝影響大」として切り出し、ユーザー確認のうえ別対応にする。

---

## 既存流用時の差分照合

1. Figma（実値）の `font` / `color` / `size` / `padding` を抜く。
2. 既存 Widget の対応値を Grep で確認。
3. 差分があれば: 画面専用 Widget で Figma に揃える / 派生 factory 追加 / 例外理由をコメント。

「既存流用＝仕様準拠」ではない。近似色（`#545454` vs `#878787`）も完全一致させる。

---

## レイアウト落とし込みノウハウ

### 寸法・サイズ

- **スクロール領域を固定高さで囲まない**: `SizedBox(height: N) + ListView` ではなく `SingleChildScrollView + Row/Column` で内在高さに任せる（フォント/画像スケール誤差で常にズレる）。
- **`SingleChildScrollView` は `physics: AlwaysScrollableScrollPhysics()` を明示**、`padding` に `MediaQuery.paddingOf(context).bottom` を加味（BottomNavigationBar の重なり分）。
- **コンテナ高は積算で検算**: `親.height == 子の height 合計 + gap + padding`。
- **行高（line_height）を必ず加算**。`fontSize × 1.4` で推測しない。
- **スケール対象を区別**: 画像幅/カードサイズ（390px 基準の絶対値）は `AppDesignScale` 対象。フォント/gap/padding/border は非対象。混在固定 `SizedBox(height: 166)` はオーバーフロー/隙間の原因。
- `width/height: fill → Expanded / double.infinity`、`hug → mainAxisSize.min`。

### フォントサイズが異なる横並び（baseline 揃え）

価格 `¥1,990`(13px) + `20%OFF`(11px) のように**サイズ違いの兄弟テキストを同じ行**に並べる（Figma `items-baseline`）場合:

- `Wrap` + `WrapCrossAlignment.end` は使わない（小さい文字が下にずれる）。
- `Row` + `CrossAxisAlignment.baseline` + `textBaseline: TextBaseline.alphabetic` を使う。
- 折り返しは諦める（`Flexible` + `TextOverflow.ellipsis` でフォールバック）。

```dart
Row(
  mainAxisSize: MainAxisSize.min,
  crossAxisAlignment: CrossAxisAlignment.baseline,
  textBaseline: TextBaseline.alphabetic,
  children: [Flexible(child: priceWidget), const SizedBox(width: 3), discountWidget],
)
```

### Padding / Gap

- **`padding {top,right,bottom,left}` → `EdgeInsets.fromLTRB(left, top, right, bottom)`**（引数順注意）。
- `layout: vertical` の `gap: N` → `SizedBox(height: N)` / Column `spacing`。`horizontal` → `SizedBox(width: N)` / Row `spacing` / `ListView.separated`。
- **左右非対称 padding**（例: 横スクロールで右だけ 0）を `all` / `symmetric` で雑に潰さない。

### 色・条件分岐・区切り線

- 同じ hex でも文脈でトークンが変わる（[typography-and-tokens.md](typography-and-tokens.md)）。
- 仕様文言（「100 文字以上で表示」等）はコードの if 条件と 1:1 で照合。状態テーブル（「アンバサダー時非表示」等）はすべて実装、空 onPressed / TODO で放置しない。
- 名前/身長間・統計項目間などの縦線は `VerticalDivider`（`staff_card.dart` 参照）。`SizedBox(gap)` だけで代用しない。

---

## インタラクション同時実装

見た目だけ直して動作を後回し / TODO にしない。

| アクション種別             | 実装例                                       |
| -------------------------- | -------------------------------------------- |
| リンクタップ               | `InkWell` + `AdaptivePush` / `launchUrl`     |
| お気に入り（コンテンツ系） | `AppFavoriteButton.bubble`                   |
| お気に入り（商品）         | `AppFavoriteButton` + トースト               |
| データ未取得               | `ErrorScreen` / セクション非表示（仕様通り） |

---

## トークン・アセット・文言の使い方

```dart
// 色
context.appBackgroundColors.primary / appButtonColors.primary / appTextColors.primary / appIconColors.primary
// テキスト（JP/EN を区別）
context.appTextThemeJP.body2_14B   // 日本語
context.appTextThemeEN.label_14R   // 英数字・件数
```

- **CommonAssets 使用**（`IconData`=`Icons.xxx` 禁止）:

```dart
CommonAssets.res.assets.filter.svg(width: 24, height: 24,
  colorFilter: ColorFilter.mode(context.appIconColors.primary, BlendMode.srcIn))
```

- **slang 使用**（UI 文字列ハードコード禁止）。翻訳ファイル: `packages/design_ui/res/i18n/ja.i18n.json`。

```dart
import 'package:internal_design_ui/i18n.dart';
Text(context.t.myFeature.title)
```

> 文言を増やす（例: 件数の「件」）場合は ja.i18n.json にキー追加 → `melos run gen` が必要。生成前に新キーを参照するとビルドが壊れるので注意。

---

## 状態管理の選択

| ケース                                          | 使用                                   |
| ----------------------------------------------- | -------------------------------------- |
| シート/ダイアログ内の一時状態・フォーム一時入力 | `flutter_hooks`                        |
| API 取得データ・画面間共有                      | `Riverpod`（`@riverpod` でコード生成） |

---

## 修正後セルフチェック

- [ ] 写っている要素のみ実装（`visible=false` を実装していない。スクショ基準）
- [ ] Typography 対応表の行数 = 写っているテキスト数。各行を実体ファイルで検証
- [ ] font / color / size / padding / gap が Figma 実値と一致（推測トークン禁止）
- [ ] 共用コンポーネントを 1 画面のために書き換えていない（画面専用 Widget 化）
- [ ] `IconData` 直書きなし（CommonAssets）／UI 文言ハードコードなし（slang）
- [ ] 色 hex・数値の直書きなし（トークン / `static const`）
- [ ] アクション（タップ・遷移・トグル）を見た目と同時に実装（空 onTap / TODO なし）
- [ ] 修正後に**再度スクショと突合**／`dart format`／lint／必要なら `melos run gen`
