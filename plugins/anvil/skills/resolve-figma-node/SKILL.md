---
name: resolve-figma-node
description: Figma nodeId の発見・検証スキル。画面名/ID から Figma 内の正しい nodeId と URL を特定・検証する。画面設計書の nodeId を信頼せず、PAT（REST API）で Figma 側を実際に確認する。MCP は使用しない。
user-invocable: false
allowed-tools: Bash(curl -s -H *api.figma.com*), Bash(echo *), Bash(python3 *), Read, Glob, Grep, AskUserQuestion
---

# resolve-figma-node

Figma REST API（PAT）で対象フレームを特定し、nodeId と Figma URL を検証・返却する。

画面設計書に記載された nodeId は古い・間違っている可能性があるため、必ず Figma 側で確認する。
**MCP は使用しない**（精度が低い出力を誤って使うリスクを避けるため）。

## 前提条件

- `FIGMA_PAT` 環境変数が設定されていること
- PAT に `file_content:read` スコープが付与されていること
- 対象の `fileKey` が呼び出し元から渡されるか、Figma URL から抽出できること
- 上記が満たされない場合は**エラーで中断**（フォールバックなし）

### fileKey に既定値を持たない [MANDATORY]

本スキルは特定プロジェクトの `fileKey` を既定値として保持しない。`fileKey` は呼び出し元からの引数、または渡された Figma URL からの抽出のみで解決する。どちらからも解決できない場合は**エラーで中断**し、ユーザーに `fileKey` または Figma URL の指定を依頼する。

推測・既定値による代替は行わない（無関係な Figma ファイルへ API 問い合わせが飛ぶことを防ぐため）。

## 入力

以下のいずれかを受け取る:

- **画面名**（例: `{画面ID}_{画面名}_{バリエーション}`）
- **画面設計書の nodeId**（例: `1234:56789`）— 検証対象
- **Figma URL**（例: `https://www.figma.com/design/{fileKey}/{fileName}?node-id=1234-56789`）
- **fileKey**（Figma ファイルキー）— Figma URL を渡さない場合は必須（既定値なし）

## 出力

以下の情報を返却する:

- **nodeId**: 検証済み nodeId（コロン形式: `6467:232879`）
- **figmaUrl**: ブラウザで開ける Figma URL
- **frameName**: フレーム名（Figma 上の表示名）
- **frameSize**: フレームサイズ（width x height）
- **fileKey**: Figma ファイルキー

## ワークフロー

### Step 1: PAT の確認

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" "https://api.figma.com/v1/me"
```

- 成功 → Step 2 へ
- 失敗（403 / 空）→ **エラーで中断**。ユーザーに PAT の設定を依頼。

### Step 2: 入力情報の整理

1. 画面名、nodeId、Figma URL、fileKey を整理する
2. Figma URL が渡された場合:
   - fileKey を URL から抽出: `https://www.figma.com/design/{fileKey}/{fileName}?node-id={int1}-{int2}`
   - nodeId を URL から抽出: `node-id` パラメータのハイフンをコロンに変換（`1234-56789` → `1234:56789`）
3. fileKey が引数からも Figma URL からも解決できない場合:
   - **エラーで中断**。`AskUserQuestion` で fileKey または対象フレームの Figma URL の指定を依頼する
   - 既定値による代替は行わない（前提条件の「fileKey に既定値を持たない」参照）

### Step 3: nodeId の検証（既知の nodeId がある場合）

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/files/{fileKey}/nodes?ids={nodeId}" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data.get('status'):
    print(f'ERROR: {data[\"status\"]} - {data.get(\"err\", \"unknown\")}')
    sys.exit(1)
nodes = data.get('nodes', {})
for nid, node_data in nodes.items():
    doc = node_data.get('document') or {}
    bbox = doc.get('absoluteBoundingBox', {})
    print(json.dumps({
        'nodeId': nid,
        'name': doc.get('name', ''),
        'type': doc.get('type', ''),
        'width': bbox.get('width', 0),
        'height': bbox.get('height', 0),
    }, ensure_ascii=False))
"
```

検証結果:

- **フレーム名が期待と一致** → 検証OK、Step 5 へ
- **フレーム名が不一致** → ユーザーに報告し、Step 4 へ
- **エラー（403/404）** → **エラーで中断**

### Step 4: フレーム名による検索（nodeId 不明 or 検証失敗時）

```bash
curl -s -H "X-Figma-Token: $FIGMA_PAT" \
  "https://api.figma.com/v1/files/{fileKey}?depth=2" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
if data.get('status'):
    print(f'ERROR: {data[\"status\"]} - {data.get(\"err\", \"unknown\")}')
    sys.exit(1)
search_name = sys.argv[1]

def find_frames(node, results):
    if node.get('type') in ('FRAME', 'COMPONENT', 'COMPONENT_SET'):
        name = node.get('name', '')
        if search_name.lower() in name.lower():
            bbox = node.get('absoluteBoundingBox', {})
            results.append({
                'nodeId': node['id'],
                'name': name,
                'type': node['type'],
                'width': bbox.get('width', 0),
                'height': bbox.get('height', 0),
            })
    for child in node.get('children', []):
        find_frames(child, results)

results = []
find_frames(data.get('document', {}), results)
for r in results:
    print(json.dumps(r, ensure_ascii=False))
" "{画面名}"
```

候補の選択:

- **候補が 1 件** → そのまま採用
- **候補が複数** → ユーザーに候補一覧を提示し、`AskUserQuestion` で選択を求める
- **候補が 0 件** → **エラーで中断**。ユーザーに報告。

### Step 5: Figma URL の構築と結果返却

```
nodeId のハイフン形式: コロンをハイフンに変換（1234:56789 → 1234-56789）
Figma URL: https://www.figma.com/design/{fileKey}/{fileName}?node-id={ハイフン形式}
```

結果を返却（値はプレースホルダ。実際の値は Figma から取得したものを入れる）:

```yaml
nodeId: "{nodeId}"
figmaUrl: "https://www.figma.com/design/{fileKey}/{fileName}?node-id={ハイフン形式 nodeId}"
frameName: "{Figma 上のフレーム名}"
frameSize: "{width}x{height}"
fileKey: "{fileKey}"
```

## エラー対応

全てのエラーは**即座に中断**。フォールバックなし。

- **FIGMA_PAT が未設定** → エラー。ユーザーに PAT 設定を依頼。
- **PAT が 403（期限切れ/スコープ不足）** → エラー。PAT 再発行を依頼。
- **nodeId が存在しない** → エラー。ユーザーに報告。
- **API レート制限（429）** → エラー。待機後にリトライは 1 回のみ。
- **推測で進めない** → ノードが見つからない場合、仮の nodeId を使わない。

## 再利用先

- `prepare-figma`: デザイン仕様書作成時に nodeId を確定（impl-issue Phase 6）
- `impl-issue` Phase 11: UI 実装時に nodeId を再検証
- `impl-issue` Phase 12: 実装レビュー時に nodeId を再検証
