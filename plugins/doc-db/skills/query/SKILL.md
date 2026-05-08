---
name: query
description: |
  doc-db index を検索する薄いラッパー。
  トリガー: "/doc-db:query", "doc-db で検索"
user-invocable: true
argument-hint: "--category rules|specs --query <text> [--mode emb|lex|hybrid|rerank] [--top-n N] [--doc-type ...]"
allowed-tools: Bash
---

# /doc-db:query

`plugins/doc-db/scripts/search_index.py` を呼び出して検索する。

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/search_index.py" "$@"
```
