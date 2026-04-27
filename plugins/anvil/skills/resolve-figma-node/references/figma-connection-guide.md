# Figma 接続ガイド

## プロジェクトの Figma ファイル

fileKey はプロジェクトローカルの `.claude/figma.yaml` から取得する。

```yaml
# .claude/figma.yaml の例
files:
  design:
    key: "<fileKey>" # メインデザインファイルの fileKey
    name: "<FileName>" # Figma 上のファイル名（URL 構築用）
  wireframe: # 任意
    key: "<fileKey>"
    name: "<FileName>"
```

- ファイルが存在する場合: `files.design.key` をデフォルト fileKey として使用する
- ファイルが存在しない場合: 入力された Figma URL から fileKey を抽出して使用する
- どちらもない場合: AskUserQuestion で fileKey を確認する

## 接続方法: 2 系統

### 1. Desktop MCP（推奨・メイン）

PAT スコープに依存せず、Figma Desktop アプリ経由でローカル接続する。

**前提条件**:

- Figma Desktop アプリが起動している
- 対象ファイルが Figma Desktop で開かれている
- Dev Mode が有効（Dev Mode タブに切り替え）

**接続確認**:

```bash
# MCP サーバーが応答するか確認
# Claude Code で以下の MCP ツールが利用可能であること:
# - mcp__figma-dev-mode-mcp-server__get_metadata
# - mcp__figma-dev-mode-mcp-server__get_design_context
# - mcp__figma-dev-mode-mcp-server__get_screenshot
# - mcp__figma-dev-mode-mcp-server__get_variable_defs
```

**利用可能な操作**:

- nodeId 指定でフレーム情報取得
- デザインコンテキスト取得（React+Tailwind 形式）
- スクリーンショット取得
- デザイントークン取得

**制限**:

- Figma Desktop が閉じていると使えない
- アセット（SVG/PNG）のエクスポートは不可

### 2. PAT（REST API）

Figma REST API に Personal Access Token で直接アクセスする。

**前提条件**:

- `FIGMA_PAT` 環境変数が設定されている
- PAT に `file_content:read` スコープが付与されている

**PAT の発行手順**:

1. Figma にログイン
2. Settings > Account > Personal access tokens
3. 「Generate new token」をクリック
4. トークン名を入力（例: `claude-code`）
5. **スコープ**: 以下を全て有効にする
   - `File content` — Read（ノード内容の読み取りに必須）
   - `Files` — Read
6. 「Generate token」をクリック
7. トークンをコピー

**環境変数の設定**:

```bash
# .zshrc や .env に追加
export FIGMA_PAT="figd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

**接続確認**:

```bash
# ユーザー情報の確認（スコープ不問）
curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
# → {"id":"...","email":"...","handle":"..."} が返れば OK

# ファイル内容の確認（file_content:read スコープ必須）
# fileKey は .claude/figma.yaml から取得した値を使用
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/files/{fileKey}/nodes?ids={nodeId}" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('err', 'OK'))"
# → "OK" が返れば file_content:read も有効
# → "Invalid token" が返れば PAT 期限切れ or スコープ不足
```

**利用可能な操作**:

- ノード情報取得（`/files/{fileKey}/nodes?ids=...`）
- ファイル構造取得（`/files/{fileKey}?depth=N`）
- 画像エクスポート（`/images/{fileKey}?ids=...&format=svg`）
- スタイル・コンポーネント一覧取得

## トラブルシューティング

| 症状                             | 原因                                    | 対処                                           |
| -------------------------------- | --------------------------------------- | ---------------------------------------------- |
| MCP ツールが見つからない         | Figma Desktop が未起動 or Dev Mode 無効 | Figma Desktop を起動し Dev Mode タブに切り替え |
| PAT `/me` で 403                 | トークン期限切れ                        | PAT を再発行                                   |
| PAT `/nodes` で 403、`/me` は OK | `file_content:read` スコープ不足        | PAT を全スコープで再発行                       |
| PAT `/nodes` で `null` データ    | nodeId が存在しないファイル             | `.claude/figma.yaml` の fileKey を確認         |
| MCP で大量データ（数MB）が返る   | nodeId なしで呼び出した                 | nodeId を指定して絞り込む                      |

## node-id 形式の変換

| 形式     | 例            | 用途                                  |
| -------- | ------------- | ------------------------------------- |
| URL 形式 | `6467-232879` | Figma URL の `?node-id=` パラメータ   |
| API 形式 | `6467:232879` | REST API / MCP の `nodeId` パラメータ |

変換: ハイフン `-` ↔ コロン `:`
