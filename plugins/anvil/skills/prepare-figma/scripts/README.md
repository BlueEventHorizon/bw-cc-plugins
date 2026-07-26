# prepare-figma scripts

デザイン仕様書の YAML レイアウト定義から AI 理解プレビュー PNG を生成するためのスクリプト群。

## ファイル

| ファイル                  | 用途                                          |
| ------------------------- | --------------------------------------------- |
| `render_preview.sh`       | エントリポイント（MD → YAML → HTML → PNG）    |
| `extract_preview_yaml.py` | デザイン仕様書 MD から `preview:` YAML を抽出 |
| `yaml_to_html.py`         | YAML を HTML/CSS に変換                       |
| `trim_screenshot.py`      | PNG 下部の余白を自動トリミング                |

## 使い方

### デザイン仕様書 MD からプレビュー生成

1 画面 = 1 ディレクトリ（`specs/design/{id}/`）の構成。

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" \
  specs/design/{id}/デザイン仕様書.md \
  specs/design/{id}/previews \
  preview
```

出力（プレビュー名固定 `preview`）:

- `specs/design/{id}/previews/preview.yaml` — 抽出された YAML
- `specs/design/{id}/previews/preview.html` — レンダリング用 HTML
- `specs/design/{id}/previews/preview.png` — 撮影された PNG（トリム済）

### YAML ファイル単体からの生成（テスト用）

入力ファイルが `.yaml` / `.yml` の場合、抽出ステップをスキップする。

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" \
  path/to/layout.yaml \
  /tmp \
  preview
```

## 依存

| 依存                   | 役割                          | 入手方法                                                                      |
| ---------------------- | ----------------------------- | ----------------------------------------------------------------------------- |
| **Google Chrome**      | ヘッドレスでの PNG キャプチャ | macOS の場合は通常 `/Applications/Google Chrome.app` にインストール済み       |
| **uv** （推奨）        | PEP 723 スクリプト実行        | `brew install uv` / [公式](https://github.com/astral-sh/uv)                   |
| **Python 3.10+**       | スクリプト実行                | mise でも `brew install python` でも可                                        |
| **PyYAML**, **Pillow** | YAML 解釈 / 画像トリミング    | `uv` を使えば不要（PEP 723 で自動取得）。手動なら `pip install pyyaml pillow` |

> **AI エージェントへの注意**: これらの依存が無い場合、**スクリプトや AI が勝手にインストールしてはならない**。
> 必ず prepare-figma SKILL の Step 0（前提条件チェック）でユーザーに尋ねてから実行する。

Chrome の場所を変更したい場合は環境変数 `CHROME_BIN` を指定する:

```bash
CHROME_BIN=/path/to/chromium bash render_preview.sh ...
```

ウィンドウサイズ（高さ）を変更したい場合:

```bash
PREVIEW_WINDOW_HEIGHT=5000 bash render_preview.sh ...
```

## トラブルシュート

### "Chrome/Chromium が見つかりません"

Google Chrome をインストールするか、`CHROME_BIN` を指定する。

### "PyYAML 入りの Python ランタイムが見つかりません"

`brew install uv` で `uv` を導入する（推奨）。
あるいはシステム Python に `pip install --user pyyaml pillow` する。

### プレビューと Figma SS が大きくずれる

YAML の `width: fill / hug / Npx` が Figma のオートレイアウト設定と一致しているか確認する。
特に `hug` を使うべきところで `<N>px` を直書きしているとプレビューが歪む。
スキーマ詳細: [../references/preview-yaml-schema.md](../references/preview-yaml-schema.md)

### プレビューが下に余白で長く伸びる

`trim_screenshot.py` が動いていないか、`PREVIEW_WINDOW_HEIGHT` 不足でコンテンツが切れている可能性。
ログで `Trimming bottom padding...` が出ていない場合は uv/Pillow をチェック。

## .gitignore 推奨

中間生成物の HTML/YAML はリポジトリに含めない。PNG のみコミット。

```
specs/design/*/previews/*.html
specs/design/*/previews/*.yaml
```
