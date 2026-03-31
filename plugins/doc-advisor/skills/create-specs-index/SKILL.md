---
name: create-specs-index
description: |
  Build or update the specs Embedding index for semantic document search.
  Reads full file content (max 7500 characters) and vectorizes via OpenAI Embedding API.
  No external dependencies except DOC_ADVISOR_OPENAI_API_KEY.
  Trigger:
  - After editing, adding, or removing spec documents
  - "Rebuild the specs index"
allowed-tools: Bash, Read
user-invocable: true
argument-hint: "[--full]"
---

# create-specs-index

Build/update the specs Embedding index for AI-searchable semantic document search.

## Usage

```
/doc-advisor:create-specs-index [--full]
```

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| (none)   | Incremental update (hash-based diff)                  |
| `--full` | Full rebuild (for initial creation or regeneration)    |

## Execution Flow

Run the Embedding index builder:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/embed_docs.py --category specs [--full]
```

- If `$0` = `--full`: pass `--full` flag (rebuild entire index)
- Otherwise: run without `--full` (incremental diff update)

### Processing Details

**Embedding テキスト構成**:
- Source: 各 .md ファイル全文（フロントマター含む）
- Encoding: UTF-8
- Truncation: 最初 7500 文字で自動切り詰め（テキスト全体の意味情報を保持しつつ、token コスト削減のため）
- API: OpenAI text-embedding-3-small（1536 dimensions）

**出力フォーマット**:
- File: `.claude/doc-advisor/toc/specs/specs_index.json`
- Schema: `{"metadata": {"category": "specs", "model": "text-embedding-3-small", ...}, "entries": {"path/to/file.md": {"title": "...", "embedding": [...], "checksum": "..."}}}`

## Error Handling

If a script outputs `{"status": "config_required", ...}`, use AskUserQuestion to ask the user:
- "Document directories are not configured. Run /forge:setup-doc-structure to configure?"
  - Yes → invoke `/forge:setup-doc-structure`, then restart this skill
  - No → abort

If a script outputs `{"status": "error", ...}` with an DOC_ADVISOR_OPENAI_API_KEY-related message, use AskUserQuestion to inform the user:
- "DOC_ADVISOR_OPENAI_API_KEY is not set. Please run `export DOC_ADVISOR_OPENAI_API_KEY='your-api-key'` and retry."

If a script outputs `{"status": "partial", ...}`, report the partial failure details to the user:
- Show the number of successfully processed and failed files
- Explain that failed files will be automatically reprocessed on the next incremental run

For other unexpected errors, report the error details clearly and use AskUserQuestion to ask the user how to proceed.
