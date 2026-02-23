---
name: where
description: |
  Query .doc_structure.yaml to find where documents of a specific type are located.
  Returns directory paths for the requested category and doc_type.
  Designed to be called by other skills to avoid YAML parsing.
  Trigger: "where are the requirements", "where do plans go", "document paths"
user-invocable: true
argument-hint: "[<category> [<doc_type>]] (e.g., specs requirement)"
---

# /doc-structure:where

## Overview

Query `.doc_structure.yaml` to return document directory paths.
Other skills can call this instead of parsing YAML directly.

## EXECUTION RULES
- Exit plan mode if active. Do NOT ask for confirmation about plan mode.
- If `.doc_structure.yaml` does not exist, report error and suggest running `/doc-structure:init-doc-structure`.

## Input

**Arguments**: `$ARGUMENTS`

| Format | Meaning | Example |
|--------|---------|---------|
| (empty) | Show all categories and paths | `/doc-structure:where` |
| `<category>` | Show all doc_types in category | `/doc-structure:where specs` |
| `<category> <doc_type>` | Show paths for specific type | `/doc-structure:where specs requirement` |

## Procedure

### Step 1: Read .doc_structure.yaml

Read `.doc_structure.yaml` from the project root.

If the file does not exist:
```
Error: .doc_structure.yaml not found.
Run /doc-structure:init-doc-structure to create it.
```

### Step 2: Parse arguments and respond

#### No arguments — show all

```
specs:
  requirement: specs/requirements/
  design: specs/design/
  plan: specs/plan/
rules:
  rule: rules/
```

#### Category only — show doc_types in category

```
/doc-structure:where specs
→
specs:
  requirement: specs/requirements/
  design: specs/design/
  plan: specs/plan/
```

#### Category + doc_type — show paths

```
/doc-structure:where specs requirement
→ specs/requirements/
```

If a doc_type has multiple paths:
```
/doc-structure:where specs requirement
→ specs/requirements/
  modules/auth/requirements/
```

### Step 3: Glob expansion (if applicable)

If a path contains `*` (glob pattern), expand it to show actual matching directories:

```
/doc-structure:where specs requirement
→ Pattern: specs/*/requirements/
  Matches:
    specs/main/requirements/
    specs/auth/requirements/
    specs/csv_import/requirements/
```

Use `ls -d` or equivalent to expand glob patterns.

## Output Format

Keep output minimal and machine-friendly. No extra decoration.
The calling skill or user should get paths they can directly use.
