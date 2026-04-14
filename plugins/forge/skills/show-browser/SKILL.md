---
name: show-browser
description: |
  セッション進捗やレビュー指摘をブラウザでリアルタイム表示する。
  monitor ディレクトリを作成し、SSE サーバーをバックグラウンド起動してブラウザを開く。
  トリガー: "ブラウザで表示", "show browser", "show-browser", "モニター起動"
user-invocable: true
argument-hint: "--template review_list --session-dir <セッションディレクトリ>"
---

# /forge:show-browser Skill

セッション進捗・レビュー指摘をブラウザでリアルタイム表示するスキル。

PostToolUse フック（`notifier.py`）が YAML ファイルの更新を検知し、
SSE 経由でブラウザに Push する。

設計書: [DES-012 show-browser 設計書](${CLAUDE_PLUGIN_ROOT}/../../docs/specs/forge/design/DES-012_show_browser_design.md)

## コマンド構文

```
/forge:show-browser --template <テンプレート名> --session-dir <セッションディレクトリパス>
```

| 引数 | 必須 | 説明 |
|------|------|------|
| `--template` | - | テンプレート名（省略時: `review_list`） |
| `--session-dir` | ○ | 監視対象のセッションディレクトリ |
| `--port` | - | ポート番号（省略時: 8765 から自動検出） |
| `--no-open` | - | ブラウザを開かない |

## 利用可能テンプレート

| テンプレート | 用途 | 参照先 |
|------------|------|--------|
| `review_list` | レビュー指摘一覧 | `plan.yaml` の items |

## フェーズ

### Phase 1: 引数確認

`$ARGUMENTS` を確認し、`--session-dir` が省略されている場合は AskUserQuestion を使用して確認する:

- 監視対象のセッションディレクトリ（`.claude/.temp/` 配下）

### Phase 2: show_browser.py 実行

以下のスクリプトを実行する:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/show-browser/scripts/show_browser.py" \
  --template {template} \
  --session-dir {session_dir}
```

標準出力（JSON）:

```json
{"monitor_dir": ".claude/.temp/20260414-153022-review_list-monitor", "port": 8765, "url": "http://localhost:8765/"}
```

### Phase 3: 完了報告

AskUserQuestion を使用して結果を報告する:

- ブラウザが開いた URL
- monitor ディレクトリのパス
- セッションディレクトリの監視が開始されたことの確認

## エラーハンドリング

| エラー | 対処 |
|--------|------|
| `session_dir_not_found` | AskUserQuestion でセッションディレクトリの確認を促す |
| `server_start_failed` | AskUserQuestion でエラー内容を通知する |

## 注意事項

- `notifier.py` フックが `.claude/settings.json` に登録されている必要がある
- フックが未登録の場合、ブラウザは表示されるが自動更新は機能しない
- サーバーは session_dir が削除されると自動停止する（設計書 UC-004）

$ARGUMENTS
