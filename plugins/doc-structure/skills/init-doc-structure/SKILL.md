---
name: init-doc-structure
description: |
  Create or update .doc_structure.yaml for the current project.
  Scans directories, classifies them as rules/specs with doc_type, and generates the file interactively.
  Trigger: "init doc structure", "create doc structure", "setup document structure"
user-invocable: true
argument-hint: "[--auto] (skip confirmation prompts)"
---

# /doc-structure:init-doc-structure

## Overview

Interactively create or update `.doc_structure.yaml` at the project root.
This file declares where different types of documents live, enabling other tools
(Doc Advisor, kaizen, planning skills, etc.) to find and create documents.

## EXECUTION RULES
- Exit plan mode if active. Do NOT ask for confirmation about plan mode.
- If `.doc_structure.yaml` already exists, switch to **review mode** (show current, suggest changes).

## Procedure

### Step 1: Check existing file

Read `.doc_structure.yaml` at the project root.

- **Exists**: Show current content, ask if user wants to update or regenerate.
- **Not exists**: Proceed to Step 2.

### Step 2: Run classification script

Determine the plugin scripts directory:
- If running as a plugin: use the plugin's `scripts/` directory
- Fallback: search for `classify_dirs.py` in common locations

```bash
python3 <scripts_dir>/classify_dirs.py --format summary
```

Show the classification result to the user.

### Step 3: Interactive refinement

Present the detected structure and ask the user to confirm or adjust using AskUserQuestion:

1. **Category confirmation**: Are these directories correctly classified as rules/specs?
2. **Doc type confirmation**: Are the doc_type names correct? (requirement, design, plan, rule, etc.)
3. **Missing directories**: Are there additional document directories to include?
4. **Directories to remove**: Should any detected directories be excluded?

If `--auto` argument is provided, skip confirmation and use detected results directly.

### Step 4: Generate .doc_structure.yaml

Based on confirmed structure, generate the file:

```bash
python3 <scripts_dir>/classify_dirs.py --format doc_structure
```

Or construct manually from user's refined input.

Write the result to `.doc_structure.yaml` at the project root.

### Step 5: Show result

Display the generated file content and suggest next steps:

```
.doc_structure.yaml created successfully.

Next steps:
- Other skills can query document locations: /doc-structure:where specs requirement
- If using Doc Advisor: run /classify-docs to sync config.yaml
- Commit .doc_structure.yaml to version control
```

## Schema Reference

See: https://github.com/BlueEventHorizon/bw-cc-plugins/blob/main/docs/doc_structure_format.md

### Quick reference

```yaml
version: "1.0"

specs:
  <doc_type>:
    paths: [<dir_path>, ...]
    description: "<optional>"  # optional

rules:
  <doc_type>:
    paths: [<dir_path>, ...]
```

### Recommended doc_type names

| Category | Name | Description |
|----------|------|-------------|
| specs | requirement | Requirements documents |
| specs | design | Design documents |
| specs | plan | Implementation plans |
| rules | rule | Development rules and standards |
| rules | workflow | Workflow procedures |
| rules | guide | Best practices, how-to guides |
