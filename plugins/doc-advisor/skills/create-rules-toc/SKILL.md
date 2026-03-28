---
name: create-rules-toc
description: |
  Update the rules search index (ToC) after modifying, creating, or deleting
  development documents such as coding standards, architecture rules,
  or workflow guides.
  Trigger:
  - After editing, adding, or removing rule documents
  - "Rebuild the rules ToC"
allowed-tools: Bash, Read, Task
user-invocable: true
argument-hint: "[--full]"
---

# create-rules-toc

Generate/update rules ToC (Table of Contents) for AI-searchable document index.

## Usage

```
/doc-advisor:create-rules-toc [--full]
```

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| (none)   | Incremental update (hash-based) or resume processing  |
| `--full` | Full file scan (for initial creation or regeneration) |

## Pre-check (MANDATORY - Run first)

Run the configuration check:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check_doc_structure.sh rules
```

- **No output** → Proceed to Execution Flow
- **Output present** → STOP. Run `/forge:setup-doc-structure` skill first to configure document directories, then restart this skill

## Execution Flow

1. Read `${CLAUDE_PLUGIN_ROOT}/docs/toc_orchestrator.md` for orchestrator workflow
2. Read `${CLAUDE_PLUGIN_ROOT}/docs/toc_format.md` for format definition
3. Execute the full orchestrator workflow as described in the document, with **category = rules**
   - If `$0` = `--full`: Execute in **full mode** (rebuild entire ToC)
   - Otherwise: Execute in **incremental mode** (process changes only)

## Error Handling

If an unexpected error occurs during processing, report the error details clearly and use AskUserQuestion to ask the user how to proceed.
