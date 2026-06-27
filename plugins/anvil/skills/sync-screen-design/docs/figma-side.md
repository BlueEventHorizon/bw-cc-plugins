# Figma 側の扱い（sync-screen-design）

実装画面を Figma に合わせて直すとき、**Figma の何を・どの順で見て、どの値を採用し、どうコードへ落とすか**の詳細手順。
実装側のキャプチャ取得（Emulator / Simulator）は `capture-emulator-screen` Skill で扱う。

## 目次

1. [全体方針](#1-全体方針)
2. [前提条件と Figma ファイル構成](#2-前提条件と-figma-ファイル構成)
3. [Step 1: 対象ノードの特定（resolve）](#step-1-対象ノードの特定resolve)
4. [Step 2: スクリーンショット取得（採用判断の唯一の基準）](#step-2-スクリーンショット取得採用判断の唯一の基準)
5. [Step 3: 構造・実値の抽出（ノード JSON ダンプ）](#step-3-構造実値の抽出ノード-json-ダンプ)
6. [Step 4: 色・フォント・余白の実値照合](#step-4-色フォント余白の実値照合)
7. [Step 5: デザイントークンへのマッピング](#step-5-デザイントークンへのマッピング)
8. [Step 6: 画面外メモ・コメントの確認](#step-6-画面外メモコメントの確認)
9. [Step 7: 差分の分類とどう直すか](#step-7-差分の分類とどう直すか)
10. [アンチパターン（実例つき）](#アンチパターン実例つき)
11. [付録: 便利スクリプト](#付録-便利スクリプト)

---

## 1. 全体方針

- **Figma = 正**。ただし「正」とするのは **実描画（スクリーンショット）に写っているもの** だけ。
- **node ツリーの存在 ≠ 採用**。コンポーネント流用により `visible=false` の未使用子ノードがツリーに残る。ツリーの値は「写っている要素の寸法・色・フォントを引くための辞書」として使い、有無の判断には使わない。
- **MCP が使えない環境でも REST API（PAT）で代替可能**。本プロジェクトでは Figma MCP がエラーになることがあるため、REST を主経路として記述する。

優先順位:

```
実描画スクリーンショット（写っているか）
  └→ 写っている要素について、ノード JSON から実値（色/フォント/余白）を取得
       └→ 実値をプロジェクトのデザイントークンへマッピング
```

---

## 2. 前提条件と Figma ファイル構成

- 環境変数 `FIGMA_PAT` が設定済みであること（`file_content:read` スコープ）。
- 疎通確認:

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me" \
  | python3 -c "import json,sys;d=json.load(sys.stdin);print(d.get('email') or d)"
```

| ファイル                    | fileKey                  | 用途                                |
| --------------------------- | ------------------------ | ----------------------------------- |
| DaytonaPark_APP_Design_共有 | `Yg2pMkry4klPFTMHxcM63F` | デザイン（メイン）。UI 実装はこちら |
| アプリワイヤー              | `AgUnNptCnqo85esjicl2ne` | 仕様・WF 参照                       |

URL からの抽出: `https://www.figma.com/design/{fileKey}/{name}?node-id={int1}-{int2}` → `fileKey` と `nodeId`（ハイフン→コロン。`11068-110463` → `11068:110463`）。

---

## Step 1: 対象ノードの特定（resolve）

詳細手順は [resolve-figma-node](../../resolve-figma-node/SKILL.md) に従う。要点:

- **dev リンク（`?node-id=...&m=dev`）の node-id を最優先**。画面設計書記載の nodeId は古いことがある。
- **同名フレームが複数存在しうる**。例: 「jb-cyi_商品詳細画面_レビュー」は `11068:110463`（高さ 4867）と `22812:28309`（高さ 2380 にクリップ）が併存。
  - 候補が複数出たら **`AskUserQuestion` でどれが正かを確認**する。勝手に 1 つに決めない。
- 画面名で検索する場合（`depth=2` でページ直下フレームを走査）:

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/files/Yg2pMkry4klPFTMHxcM63F?depth=2" \
  | python3 -c "
import json,sys
d=json.load(sys.stdin); q='jb-cyi'
def walk(n,r):
    if n.get('type') in ('FRAME','COMPONENT','COMPONENT_SET') and q.lower() in n.get('name','').lower():
        b=n.get('absoluteBoundingBox',{}); r.append((n['id'],n.get('name'),round(b.get('width',0)),round(b.get('height',0))))
    for c in n.get('children',[]) or []: walk(c,r)
r=[]; walk(d.get('document',{}),r)
[print(x) for x in r]
"
```

確定したら nodeId / Figma URL / frameName / frameSize を控える。

---

## Step 2: スクリーンショット取得（採用判断の唯一の基準）

**最重要ステップ。** これを飛ばすと「ツリーにあるが実際は非表示」の要素を実装してしまう。

### 取得（REST）

```bash
# 画像 URL を取得（scale=2 推奨）
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/Yg2pMkry4klPFTMHxcM63F?ids=11068:110463&format=png&scale=2" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['images']['11068:110463'])"
# 返ってきた S3 URL を保存
curl -sL "<上で得た URL>" -o figma_screen.png
```

> MCP が使える環境なら `get_screenshot` でも可（[figma-mcp-guide](../../figma-mcp-guide/SKILL.md)）。出力は同じく「実描画」として扱う。

### 巨大フレームは分割して読む

商品詳細などは縦に長い（4000〜10000px）。`Read` で 1 枚は潰れるので、Pillow で縦分割 or 領域クロップして読む（[付録](#付録-便利スクリプト)）。

### 採用判断のルール

- **写っている要素のみ実装対象**。写っていなければ YAML/コード/差分一覧に含めない。
- ボタンのアイコン有無・条件付き要素・状態バリエーションは **必ずスクショで確認**してから差分計上する。
- 疑わしい要素は領域を高解像度でクロップして拡大確認する（小さいアイコン・シェブロン等）。

---

## Step 3: 構造・実値の抽出（ノード JSON ダンプ）

スクショで「写っている」と確認した要素について、寸法・色・フォント・余白をノード JSON から引く。

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/files/Yg2pMkry4klPFTMHxcM63F/nodes?ids=11068:110463" -o node.json
```

`node.json` をツリーへ整形して読む（[付録の dump_tree.py](#付録-便利スクリプト)）。各行で確認できる:

- `type` / `name` / `幅x高`
- レイアウト: `layoutMode`（VERTICAL/HORIZONTAL）, `padding[top,right,bottom,left]`, `itemSpacing`(=gap)
- `fills`（SOLID は RGB→hex、GRADIENT / IMAGE）
- TEXT: `style.fontSize` / `fontWeight` / `lineHeightPx` / `characters`

### visible 判定（必須）

「写っていないのにツリーにある」要素を弾くため、対象ノードの `visible` を確認する。`false` なら不採用。
ただし `visible=true` でも色が背景と同化・opacity 0 等で**見えない**ことがあるため、**最終判断は必ずスクショ**。

```bash
python3 -c "
import json
d=json.load(open('node.json')); root=list(d['nodes'].values())[0]['document']
def walk(n,p=''):
    if n.get('visible') is False: print('HIDDEN', n.get('type'), repr(n.get('name')), '<-', p[-40:])
    for c in n.get('children',[]) or []: walk(c, p+'/'+n.get('name',''))
walk(root)
"
```

### フレームのクリップに注意

外形 `absoluteBoundingBox` の高さが内部コンテンツより小さい場合、フレームがクリップされている（例: `22812:28309` は 2380 にクリップされ、下部のボタン/ボトムバーは枠外＝レンダリングに写らない）。クリップ版を見て「要素が無い」と誤判定しない。全体像は非クリップの同等フレームで確認する。

---

## Step 4: 色・フォント・余白の実値照合

### 色（名前で判断しない）

1. スクショで実際の色味を確認する。
2. 対象ノードの `fills` の RGB を hex 化して控える。必要なら `get_variable_defs`（MCP）/ 変数も取得。
3. スクショの見た目と hex を突き合わせ、実際に Fill / SVG に bind されている値を特定する。
4. 採用根拠をコードコメントに残す（例: `// Figma fill #FFCB45 準拠。Variable 名 Star-Dark は別用途`）。

> 悪い例: レスポンス末尾に出てきた `Star-Dark: #DFB300` を根拠に星色を変更 → 実描画は `#FFCB45` で誤り。**名前ではなく実値とスクショで判断**。

### フォント

- `style.fontSize` / `fontWeight` / `lineHeightPx` を取得。
- **フォントファミリー（SF Pro / Hiragino）は実装で指定しない**。これは「英数字・件数 → `appTextThemeEN`」「日本語 → `appTextThemeJP`」というトークンの言語使い分けを意味するだけ。
- weight: 300/400 → `R`、600/590 → `B`。

### 余白

- `padding` は `{top,right,bottom,left}`。コードへは `EdgeInsets.fromLTRB(left, top, right, bottom)`（**引数順に注意**）。
- 左右非対称（例: 横スクロールで右だけ 0）を `EdgeInsets.all` / `symmetric` で雑に潰さない。
- `itemSpacing` は `gap` → `SizedBox` / `Column`・`Row` の `spacing`。

---

## Step 5: デザイントークンへのマッピング

実値をプロジェクトのトークンへ変換する。**詳細表・手順は [typography-and-tokens.md](typography-and-tokens.md)（本スキル内）** に取り込み済み。要点のみ:

### 色 → トークン（実体ファイルで値を確認すること）

| Figma hex | トークン                                                                                      |
| --------- | --------------------------------------------------------------------------------------------- |
| #222222   | `appTextColors.primary`                                                                       |
| #545454   | `appTextColors.secondary`                                                                     |
| #878787   | `appTextColors.tertiary`（gray/500）                                                          |
| #4699DC   | `appTextColors.link` / `appIconColors.link`（blue/600）                                       |
| #49A4EC   | `appButtonColors.textButton` / `appSeparatorColors.quaternary`（blue/500）                    |
| #E34234   | `appTextColors.brand` / `appBackgroundColors.tertiary` / `appIconColors.secondary`（red/600） |
| #FFCB45   | 星 filled / #EDEDED 星 empty・`background.disable`                                            |

> **同じ hex でも文脈でトークンが変わる**: タップ動作あり→`link`、非リンクの副情報→`tertiary`、ブランド強調→`brand`。
> 実体ファイル: `packages/design_theme/lib/src/theme_extensions/app_*_colors.dart`。

### テキスト → JP/EN トークン

- `fontSize + fontWeight + lineHeightPx` の 3 点一致でトークンを選ぶ。size+weight だけでは body / label を区別できない。
- 英数字・件数・cm・ID → `appTextThemeEN`（例: 件数 `(99)` は `appTextThemeEN.label_14R` = 14/w400/lh14）。
- 日本語 → `appTextThemeJP`。
- 実体: `app_text_theme_jp.dart` / `app_text_theme_en.dart`。**トークン名から weight を推測しない**（実体を Read）。

### 余白・サイズ

- Spacing 用トークンは存在しない → Widget 内 `static const` で命名（前例 PR の命名・値を踏襲）か、トークンが無い旨をコメントして直書きを最小化。
- 画像幅・カードサイズなど 390px 基準の絶対寸法は `AppDesignScale` のスケール対象。フォント/gap/padding/border は非対象。

---

## Step 6: 画面外メモ・コメントの確認

デザイナーがフレーム外に置いた作業メモ・指示を見落とさない。

- ページ直下の view 周辺フレームで `メモ` / `Memo` / `Note` / `仕様` / `件数` / `最大` 等の名前を検索。
- Figma コメント: `curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/files/{key}/comments"` で pinned コメントを精査。
- 隣接するバリエーション view（タブ切替後・状態違い）も確認。

---

## Step 7: 差分の分類とどう直すか

### 分類軸

- **スコープ**: 余白 / 色 / タイポ / 配置 / アセット / TODO
- **難易度**: 🟢 値変更のみ（画面ローカル） / 🟡 アセット追加・共有部品改修 / 🔴 モデル・API・新規セクション
- **❓ 要確認**: Figma ツリー/スコープに根拠が無い（取消線・枠線・透明度・遷移先など）

### 修正方針

- **Figma（実描画）= 正**。順序・サイズ・色・padding・font をそのまま転記する。詳細ルールは [implementation-rules.md](implementation-rules.md)。
- **🟢 画面ローカルから着手**。色トークン差し替え・余白・行高（`copyWith(height: lh/size)`）など、他画面に影響しないものを先に。
- **共有コンポーネント（2 画面以上で import）は書き換えない**。`search-code-toc` / Grep で import 元を数え、2 画面以上なら画面専用 Widget を作る（→ [implementation-rules.md](implementation-rules.md)「共用コンポーネントの変更禁止」）。
  - 例: ボタン高さ 48→47、`AppItemLabel` のフォント、`AppContentCard` のハートサイズ等は共有部品 → 1 画面のために変えない。
- **🟡/🔴 と ❓ は勝手に進めず `AskUserQuestion` で確認**。アセット追加（SVG エクスポート）やモデル/API 変更は影響範囲を明示する。
- テキストを直す前に [typography-and-tokens.md](typography-and-tokens.md) で対応表を作る。
- 修正後は [review-checklist.md](review-checklist.md) の三点突合を行い、`dart format` / lint / 必要なら `melos run gen`。

### アセットが無い（ダウンロード漏れ）場合

スクショに写っているのにプロジェクト（`packages/design_ui/res/assets/`）に SVG が無いアイコンは、Figma からエクスポートして追加する:

```bash
# SVG エクスポート URL を取得
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/images/{key}?ids={iconNodeId}&format=svg" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['images']['{iconNodeId}'])"
```

ただし「ボタンに右シェブロン等」は **多くの場合アセットは既存**（`chevron_right.svg` 等）で、不足しているのは**部品側のアイコンスロット**であることが多い。SVG 不足か部品 API 不足かを切り分ける。

---

## アンチパターン（実例つき）

| やってはいけない                           | 正しい対応                                     |
| ------------------------------------------ | ---------------------------------------------- |
| **node ツリーの存在でアイコン有無を判断**  | スクショで実描画を確認。`visible=false` を弾く |
| Variable/Style 名だけで色を変更            | スクショ + fills の実 hex で照合               |
| フォントファミリーを指定                   | システムフォント任せ。JP/EN トークンの選択のみ |
| 共有コンポーネントを 1 画面のために改修    | 画面専用 Widget を作る                         |
| 同名フレームを確認せず片方で進める         | dev リンク優先 + 複数候補はユーザー確認        |
| クリップ版フレームで「要素が無い」と誤判定 | 非クリップの全体フレームで確認                 |
| 値の直書き                                 | トークン / `static const`                      |

> **実例（本プロジェクト 2026-06）**: 「店舗在庫 / 取置申込」「すべてのレビューをみる」ボタンに左右アイコンが付くと node ツリーから判断したが、**実レンダリングではテキストのみ**だった（右アイコンノードは `visible=false`）。スクショ確認を飛ばした典型的な誤り。

---

## 付録: 便利スクリプト

### ノードツリーのダンプ（dump_tree.py 相当）

各ノードの `type / name / 幅x高 / layoutMode / padding / gap / fills(hex) / TEXT style` を 1 行で出力する Python を一時ディレクトリに作成して使う（`uv run --with pillow` は不要、標準 `python3` で可）。色は `round(r*255)` で hex 化、TEXT は `style` から `fontSize/fontWeight/lineHeightPx/characters` を抜く。

### スクショの縦分割・領域クロップ（Pillow）

```python
# uv run --with pillow python crop.py <src.png> <prefix> <seg_height>
import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB")
w, h = im.size
# 幅 390 に縮小して読みやすく
nw = 390; nh = int(h * nw / w); im = im.resize((nw, nh), Image.LANCZOS)
seg = int(sys.argv[3]); y = 0; i = 1
while y < nh:
    b = min(y + seg, nh); im.crop((0, y, nw, b)).save(f"{sys.argv[2]}_{i}.png")
    if b >= nh: break
    y = b - 120; i += 1   # 120px オーバーラップ
```

領域クロップ（特定ボタン等を高解像度で確認）:

```python
# uv run --with pillow python cropbox.py <src.png> <out.png> <top> <bottom>
import sys; from PIL import Image
im = Image.open(sys.argv[1]).convert("RGB"); w, h = im.size
im.crop((0, int(sys.argv[3]), w, min(int(sys.argv[4]), h))).save(sys.argv[2])
```

> 一時ファイルはワークスペース直下の gitignore 済みディレクトリ（例: `.figma_tmp/`）に置き、コミット対象にしない。
