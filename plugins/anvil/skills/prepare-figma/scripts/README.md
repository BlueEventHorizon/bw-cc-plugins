# prepare-figma scripts

デザイン仕様書の JSON レイアウト定義から AI 理解プレビュー PNG を生成するためのスクリプト群。

## ファイル

| ファイル                  | 用途                                         |
| ------------------------- | -------------------------------------------- |
| `render_preview.sh`       | エントリポイント（MD → JSON → HTML → PNG）   |
| `extract_preview_json.py` | デザイン仕様書 MD から `preview` JSON を抽出 |
| `json_to_html.py`         | JSON を HTML/CSS に変換                      |
| `trim_screenshot.py`      | PNG 下部の余白を自動トリミング               |

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

- `specs/design/{id}/previews/preview.json` — 抽出された JSON
- `specs/design/{id}/previews/preview.html` — レンダリング用 HTML
- `specs/design/{id}/previews/preview.png` — 撮影された PNG（トリム済）

### JSON ファイル単体からの生成（テスト用）

入力ファイルが `.json` の場合、抽出ステップをスキップする。

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/prepare-figma/scripts/render_preview.sh" \
  path/to/layout.json \
  /tmp \
  preview
```

## 依存

| 依存              | 役割                                                                                                                                               | 入手方法                                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Google Chrome** | ヘッドレスでの PNG キャプチャ                                                                                                                      | macOS の場合は通常 `/Applications/Google Chrome.app` にインストール済み |
| **Python 3.10+**  | スクリプト実行                                                                                                                                     | mise でも `brew install python` でも可                                  |
| **uv** （推奨）   | Pillow 依存の `trim_screenshot.py` を PEP 723 で自己完結実行（`json_to_html.py`/`extract_preview_json.py` には不要。標準ライブラリのみで動作する） | `brew install uv` / [公式](https://github.com/astral-sh/uv)             |
| **Pillow**        | 画像トリミング（`trim_screenshot.py` 専用）                                                                                                        | `uv` を使えば不要（PEP 723 で自動取得）。手動なら `pip install pillow`  |

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

### "Pillow 入りの Python ランタイムが見つかりません"

`brew install uv` で `uv` を導入する（推奨）。
あるいはシステム Python に `pip install --user pillow` する。
（`json_to_html.py`/`extract_preview_json.py` はこのチェックと無関係に動作する）

### プレビューと Figma SS が大きくずれる

JSON の `width: fill / hug / Npx` が Figma のオートレイアウト設定と一致しているか確認する。
特に `hug` を使うべきところで `<N>px` を直書きしているとプレビューが歪む。
スキーマ詳細: [../references/preview-json-schema.md](../references/preview-json-schema.md)

### プレビューが下に余白で長く伸びる

`trim_screenshot.py` が動いていないか、`PREVIEW_WINDOW_HEIGHT` 不足でコンテンツが切れている可能性。
ログで `Trimming bottom padding...` が出ていない場合は uv/Pillow をチェック。

## .gitignore 推奨

中間生成物の HTML/JSON はリポジトリに含めない。PNG のみコミット。

```
specs/design/*/previews/*.html
specs/design/*/previews/*.json
```
