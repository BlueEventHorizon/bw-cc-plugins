---
name: query-rules
description: |
  Search the pre-analyzed document index (ToC) to identify rule documents
  needed for a task. The ToC contains AI-extracted metadata (keywords,
  applicable_tasks) that enables discovery beyond simple file search.
  Trigger:
  - "What rules apply to this task?"
  - Before starting implementation work
context: fork
agent: general-purpose
model: sonnet
user-invocable: true
argument-hint: "[task description]"
---

## Role

Analyze task content and return a list of required development document paths.

## Staleness Check

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/create_pending_yaml.py --category rules --check
```

- **WARNING output present** → Inform user of the warning message, then proceed to Procedure
- **No output** → Proceed to Procedure directly

## Procedure

1. Read `.claude/doc-advisor/toc/rules/rules_toc.yaml` **completely**
   - **MANDATORY**: Read the entire file with the Read tool. Do NOT use Grep or search tools on ToC
   - **If not found**: Read `.doc_structure.yaml` to get `rules.root_dirs`, then search with Glob `<dir>/**/*.md` for each configured directory
2. Deeply understand all entries, then identify relevant candidates from task content
   - Find relevant entries (match by keywords, purpose, title, applicable_tasks)
3. If there's any chance of relevance, read the actual file to confirm (no false negatives allowed)
4. Return the confirmed path list

## Critical Rule

**ToC must be fully read and deeply understood before making decisions.**

- ❌ PROHIBITED: Using Grep/search tools on ToC content
- ❌ PROHIBITED: Partial reading or skimming the ToC
- ✅ REQUIRED: Read the entire ToC file with Read tool
- ✅ REQUIRED: Understand all entries before identifying relevant documents

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
- Requirements, design documents, and plans are out of scope (use /doc-advisor:query-specs instead)
- Target is rules documents only (directories configured in `.doc_structure.yaml` `rules.root_dirs`)

## Error Handling

If a script outputs `{"status": "config_required", ...}`, use AskUserQuestion to ask the user:
- "Document directories are not configured. Run /forge:setup-doc-structure to configure?"
  - Yes → invoke `/forge:setup-doc-structure`, then restart this skill
  - No → abort
