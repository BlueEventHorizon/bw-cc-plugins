---
name: query-rules-index
description: |
  Search the Embedding index to identify rule documents needed for a task.
  Uses semantic search (OpenAI Embedding + cosine similarity) for
  high-accuracy discovery beyond keyword matching.
  Trigger:
  - "Semantic search for rules"
  - Before starting implementation work
context: fork
agent: general-purpose
model: sonnet
user-invocable: true
argument-hint: "[task description]"
---

## Role

Analyze task content and return a list of required development document paths using semantic search.

## Auto-update

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/embed_docs.py --category rules
```

- `{"status": "ok", ...}` → Proceed to Procedure
- `{"status": "partial", ...}` → Warn the user about partial failure, then proceed to Procedure
- `{"status": "error", ...}` → Go to Error Handling

## Procedure

1. Run semantic search:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/search_docs.py --category rules --skip-stale-check --query "{task description}"
   ```
2. Review the results. If the query contains proper nouns or identifiers, run full-text search to supplement:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/grep_docs.py --category rules --keyword "{proper noun or identifier}"
   ```
3. Read each candidate document with the Read tool to confirm relevance
4. Return the confirmed path list

## Critical Rule

- ✅ REQUIRED: Read each candidate document returned by search to confirm relevance before including it
- False negatives are strictly prohibited. When in doubt, include it

## Output Format

```
Required documents:
- rules/core/xxx.md
- rules/layer/domain/xxx.md
- rules/workflow/xxx/xxx.md
- rules/format/xxx.md
```

## Notes

- False negatives are strictly prohibited. When in doubt, include it
- Requirements, design documents, and plans are out of scope (use /doc-advisor:query-specs-index instead)
- Target is rules documents only (directories configured in `.doc_structure.yaml` `rules.root_dirs`)

## Error Handling

If a script outputs `{"status": "config_required", ...}`, use AskUserQuestion to ask the user:
- "Document directories are not configured. Run /forge:setup-doc-structure to configure?"
  - Yes → invoke `/forge:setup-doc-structure`, then restart this skill
  - No → abort

If `search_docs.py` outputs `{"status": "error", ...}`, handle based on the error message:
- **"Model mismatch"** → Re-run with `--full`: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/embed_docs.py --category rules --full`, then retry search
- **"API error"** → Report the error details to the user
- **"OPENAI_API_KEY not set"** → Ask user to set the `OPENAI_API_KEY` environment variable
