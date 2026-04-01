# doc-advisor Detailed Guide

AI-searchable document index (ToC) generator for Claude Code. Extracts AI metadata from documents to enable task-relevant discovery of rules and specs.

## Skill Details

### query-rules

```
/doc-advisor:query-rules [task description]
```

| Argument | Description |
|----------|-------------|
| `task description` | Description of the task to find relevant rule documents for |

Search the pre-analyzed ToC to identify rule documents (coding standards, architecture rules, workflow guides) relevant to a task. The ToC contains AI-extracted metadata (keywords, applicable_tasks) that enables discovery beyond simple file search.

### query-specs

```
/doc-advisor:query-specs [task description]
```

| Argument | Description |
|----------|-------------|
| `task description` | Description of the task to find relevant spec documents for |

Search the pre-analyzed ToC to identify specification documents (requirements, design docs) relevant to a task.

### create-rules-toc

```
/doc-advisor:create-rules-toc [--full]
```

| Argument | Description |
|----------|-------------|
| (none) | Incremental update (hash-based) or resume processing |
| `--full` | Full file scan (for initial creation or regeneration) |

Update the rules search index (ToC) after modifying, creating, or deleting rule documents.

### create-specs-toc

```
/doc-advisor:create-specs-toc [--full]
```

| Argument | Description |
|----------|-------------|
| (none) | Incremental update (hash-based) or resume processing |
| `--full` | Full file scan (for initial creation or regeneration) |

Update the specs search index (ToC) after modifying, creating, or deleting spec documents.

## Requirements

- `.doc_structure.yaml` in project root (generate with `/forge:setup-doc-structure`)
