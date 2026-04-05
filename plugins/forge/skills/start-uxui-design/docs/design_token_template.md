---
name: design_token_template
description: デザイントークン出力テンプレート（UX ノート付き）
---

# デザイントークンテンプレート

以下のテンプレートに従ってデザイントークン文書を生成する。`{...}` は実際の値に置換すること。

---

````markdown
# THEME-001 {Feature名} デザイントークン

## メタデータ

| 項目 | 値 |
| --- | --- |
| ID | THEME-001 |
| Feature | {Feature名} |
| プラットフォーム | {iOS / macOS} |
| 作成日 | {YYYY-MM-DD} |
| 入力ソース | {画像 / Figma / URL / 手動記述} |

⚠ {画像分析の場合}色の HEX 値は画像からの推定値です。正確な値はデザインファイルで確認してください。

---

## 1. カラーパレット

### 1.1 ベースカラー（第1層: 原子的な値）

| トークン名 | HEX (Light) | HEX (Dark) | 用途 | UX ノート |
| --- | --- | --- | --- | --- |
| color.primary | {#XXXXXX} | {#XXXXXX} | {主要アクセント色} | {HIG/Nielsen 根拠} |
| color.secondary | {#XXXXXX} | {#XXXXXX} | {補助アクセント色} | {HIG/Nielsen 根拠} |
| color.background.primary | {#XXXXXX} | {#XXXXXX} | {主背景色} | {HIG/Nielsen 根拠} |
| color.background.secondary | {#XXXXXX} | {#XXXXXX} | {副背景色} | {HIG/Nielsen 根拠} |
| color.text.primary | {#XXXXXX} | {#XXXXXX} | {主テキスト色} | {HIG/Nielsen 根拠} |
| color.text.secondary | {#XXXXXX} | {#XXXXXX} | {副テキスト色} | {HIG/Nielsen 根拠} |

### 1.2 ステータスカラー

| トークン名 | HEX (Light) | HEX (Dark) | 用途 | コントラスト比 |
| --- | --- | --- | --- | --- |
| color.status.success | {#XXXXXX} | {#XXXXXX} | {成功状態} | {X.X:1} |
| color.status.warning | {#XXXXXX} | {#XXXXXX} | {警告状態} | {X.X:1} |
| color.status.error | {#XXXXXX} | {#XXXXXX} | {エラー状態} | {X.X:1} |
| color.status.info | {#XXXXXX} | {#XXXXXX} | {情報状態} | {X.X:1} |

### 1.3 セマンティックカラー（第2層: 意味的定義）

| セマンティック名 | 参照トークン | 用途 |
| --- | --- | --- |
| button.primary.background | color.primary | プライマリボタンの背景 |
| button.primary.text | color.text.onPrimary | プライマリボタンのテキスト |
| button.secondary.background | color.secondary | セカンダリボタンの背景 |
| button.destructive.background | color.status.error | 破壊的操作ボタン |
| surface.card | color.background.secondary | カード背景 |
| surface.overlay | {定義} | オーバーレイ背景 |
| separator | {定義} | 区切り線 |

### 1.4 コントラスト比検証

| 組み合わせ | 比率 | 基準 (4.5:1) | 判定 |
| --- | --- | --- | --- |
| text.primary / background.primary | {X.X:1} | 4.5:1 | {✅ / ❌} |
| text.secondary / background.primary | {X.X:1} | 4.5:1 | {✅ / ❌} |
| button.primary.text / button.primary.bg | {X.X:1} | 4.5:1 | {✅ / ❌} |

---

## 2. タイポグラフィ

### 2.1 フォントファミリー

| 用途 | フォント | UX ノート |
| --- | --- | --- |
| 見出し | {SF Pro Display / カスタム} | {HIG 準拠度} |
| 本文 | {SF Pro Text / カスタム} | {可読性評価} |
| 等幅 | {SF Mono / カスタム} | {用途の適切性} |

### 2.2 テキストスタイル

| トークン名 | サイズ | ウェイト | 行高 | 用途 | UX ノート |
| --- | --- | --- | --- | --- | --- |
| typography.largeTitle | {Xpt} | {Bold} | {X.Xpt} | {画面タイトル} | {HIG テキストスタイルとの対応} |
| typography.title1 | {Xpt} | {Bold} | {X.Xpt} | {セクション見出し} | {} |
| typography.title2 | {Xpt} | {Bold} | {X.Xpt} | {小見出し} | {} |
| typography.headline | {Xpt} | {Semibold} | {X.Xpt} | {強調テキスト} | {} |
| typography.body | {Xpt} | {Regular} | {X.Xpt} | {本文} | {} |
| typography.callout | {Xpt} | {Regular} | {X.Xpt} | {補足情報} | {} |
| typography.caption | {Xpt} | {Regular} | {X.Xpt} | {キャプション} | {} |

---

## 3. スペーシング

### 3.1 スペーシングスケール

| トークン名 | 値 | 8pt 準拠 | 用途 |
| --- | --- | --- | --- |
| spacing.xxs | {4pt} | {✅} | {最小間隔} |
| spacing.xs | {8pt} | {✅} | {密接要素間} |
| spacing.sm | {12pt} | {✅} | {関連要素間} |
| spacing.md | {16pt} | {✅} | {セクション内} |
| spacing.lg | {24pt} | {✅} | {セクション間} |
| spacing.xl | {32pt} | {✅} | {大セクション間} |
| spacing.xxl | {48pt} | {✅} | {画面レベル} |

### 3.2 レイアウトスペーシング

| トークン名 | 値 | 用途 | UX ノート |
| --- | --- | --- | --- |
| layout.screenMargin | {16pt} | {画面端マージン} | {HIG 推奨値との比較} |
| layout.cardPadding | {16pt} | {カード内パディング} | {} |
| layout.sectionGap | {24pt} | {セクション間距離} | {} |

---

## 4. ボーダー半径

| トークン名 | 値 | 用途 | UX ノート |
| --- | --- | --- | --- |
| radius.sm | {4pt} | {小要素（バッジ等）} | {} |
| radius.md | {8pt} | {ボタン、入力フィールド} | {} |
| radius.lg | {12pt} | {カード} | {} |
| radius.xl | {16pt} | {モーダル、シート} | {} |
| radius.full | {9999pt} | {完全円形（アバター等）} | {} |

---

## 5. シャドウ

| トークン名 | オフセット X/Y | ブラー | 色 | 用途 | UX ノート |
| --- | --- | --- | --- | --- | --- |
| shadow.sm | {0/1pt} | {2pt} | {#000 @ 0.05} | {軽微な浮き} | {Depth 原則} |
| shadow.md | {0/2pt} | {8pt} | {#000 @ 0.1} | {カード} | {} |
| shadow.lg | {0/4pt} | {16pt} | {#000 @ 0.15} | {モーダル} | {} |

---

## 6. UX 評価ノート

### デザイントークン全体の評価

| 観点 | 評価 | コメント |
| --- | --- | --- |
| HIG 準拠度 | {高/中/低} | {具体的な根拠} |
| 色数の適切性 | {適切/過多/不足} | {パレットの複雑さ} |
| スペーシング一貫性 | {一貫/不一致あり} | {8pt グリッド準拠度} |
| タイポグラフィ階層 | {明確/不明瞭} | {コントラスト段階数} |
| Light/Dark 対応 | {対応済/未対応/部分対応} | {両モードの考慮状況} |
| アクセシビリティ | {良好/要改善/不十分} | {コントラスト比等} |

### 改善提案

{知識ベースに基づく改善提案を重要度順に 3-5 件記載}

````
