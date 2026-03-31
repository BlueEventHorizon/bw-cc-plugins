---
name: query-specs
description: |
  Search the pre-analyzed document index (ToC) to identify specification
  documents needed for a task. The ToC contains AI-extracted
  metadata (keywords, applicable_tasks) that enables discovery beyond
  simple file search.
  Trigger:
  - "What specs apply to this task?"
  - Before starting implementation work
context: fork
agent: general-purpose
model: haiku
user-invocable: true
argument-hint: "[task description]"
---

## Role

Analyze task content and return a list of required specification document paths.

## Staleness Check

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/embed_docs.py --category specs --check
```

- `{"status": "fresh"}` → Proceed to Procedure
- `{"status": "stale", ...}` → Warn the user that the index is stale, recommend running `/doc-advisor:create-specs-toc` to rebuild. **Do NOT proceed with search while stale**

## Procedure

1. Run semantic search:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/search_docs.py --category specs --query "{task description}"
   ```
2. Review the results. If the query contains proper nouns or identifiers, run full-text search to supplement:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/grep_docs.py --category specs --keyword "{proper noun or identifier}"
   ```
3. Read each candidate document with the Read tool to confirm relevance
4. Return the confirmed path list

## Critical Rule

- ❌ PROHIBITED: Searching while the index is stale (staleness check returned `"stale"`)
- ✅ REQUIRED: Read each candidate document returned by search to confirm relevance before including it
- False negatives are strictly prohibited. When in doubt, include it

## Output Format

```
Required documents:
- specs/requirements/login_screen.md
- specs/requirements/user_authentication.md
- specs/design/login_screen_design.md
```

## Notes

- False negatives are strictly prohibited. When in doubt, include it

## Error Handling

If a script outputs `{"status": "config_required", ...}`, use AskUserQuestion to ask the user:
- "Document directories are not configured. Run /forge:setup-doc-structure to configure?"
  - Yes → invoke `/forge:setup-doc-structure`, then restart this skill
  - No → abort

If `search_docs.py` outputs `{"status": "error", ...}`, handle based on the error message:
- **"Index not found"** → Inform user to run `/doc-advisor:create-specs-toc` first
- **"Model mismatch"** → Inform user to run `/doc-advisor:create-specs-toc` with `--full` to rebuild
- **"Index is stale"** → Inform user to run `/doc-advisor:create-specs-toc` to update
- **"API error"** → Report the error details to the user
- **"DOC_ADVISOR_OPENAI_API_KEY not set"** → Ask user to set the `DOC_ADVISOR_OPENAI_API_KEY` environment variable
