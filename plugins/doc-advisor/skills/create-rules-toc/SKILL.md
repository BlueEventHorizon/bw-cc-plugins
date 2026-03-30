---
name: create-rules-toc
description: |
  Build or update the rules Embedding index for semantic document search.
  Extracts metadata from existing ToC YAML and vectorizes via OpenAI Embedding API.
  Trigger:
  - After editing, adding, or removing rule documents
  - "Rebuild the rules index"
allowed-tools: Bash, Read
user-invocable: true
argument-hint: "[--full]"
---

# create-rules-toc

Build/update the rules Embedding index for AI-searchable semantic document search.

## Usage

```
/doc-advisor:create-rules-toc [--full]
```

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| (none)   | Incremental update (hash-based diff)                  |
| `--full` | Full rebuild (for initial creation or regeneration)    |

## Execution Flow

Run the Embedding index builder:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/embed_docs.py --category rules [--full]
```

- If `$0` = `--full`: pass `--full` flag (rebuild entire index)
- Otherwise: run without `--full` (incremental diff update)

> **Migration note**: During the migration period, metadata is sourced from the existing ToC YAML. The ToC YAML will continue to be maintained alongside the Embedding index.

## Error Handling

If a script outputs `{"status": "config_required", ...}`, use AskUserQuestion to ask the user:
- "Document directories are not configured. Run /forge:setup-doc-structure to configure?"
  - Yes → invoke `/forge:setup-doc-structure`, then restart this skill
  - No → abort

If a script outputs `{"status": "error", ...}` with an OPENAI_API_KEY-related message, use AskUserQuestion to inform the user:
- "OPENAI_API_KEY is not set. Please run `export OPENAI_API_KEY='your-api-key'` and retry."

If a script outputs `{"status": "partial", ...}`, report the partial failure details to the user:
- Show the number of successfully processed and failed files
- Explain that failed files will be automatically reprocessed on the next incremental run

For other unexpected errors, report the error details clearly and use AskUserQuestion to ask the user how to proceed.
