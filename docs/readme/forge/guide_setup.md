# Setup & Utility Guide

Project setup, version management, rule cleanup, and other operational skills.

## setup-doc-structure

Generate `.doc_structure.yaml`, which declares where documents live and what types they are. The foundation forge uses to resolve document paths.

> For details, see the [Document Structure Guide](../guide_doc_structure.md).

```
/forge:setup-doc-structure
```

No arguments. Interactively scans the project and proposes a recommended structure.

---

## setup-version-config

Scan the project to detect version targets and generate `.version-config.yaml`. Prerequisite for `update-version`.

```
/forge:setup-version-config
```

No arguments.

### When to Use

- First time setting up version management in a project
- After structural changes (new plugins, README format changes, etc.)

### Execution Flow

1. Check for existing `.version-config.yaml` (update / regenerate / cancel)
2. `scan_version_targets.py` auto-detects version files, READMEs, and CHANGELOGs
3. Display results and interactively adjust settings
4. Write `.version-config.yaml`

### Configuration Structure

```yaml
targets:
  - name: forge # Target name
    version_file: plugins/forge/.claude-plugin/plugin.json # Version file
    version_path: version # JSON path
    sync_files: # Files to sync
      - path: README.md
        pattern: "| **forge** | {version} |"
        filter: "| **forge**"

changelog:
  file: CHANGELOG.md
  format: keep-a-changelog
  git_log_auto: false

git:
  tag_format: "{target}-v{version}"
  commit_message: "chore: bump {target} to {version}"
  auto_tag: false
  auto_commit: false
```

---

## update-version

Update versions across multiple files based on `.version-config.yaml`. Supports automatic CHANGELOG generation from git log.

```
/forge:update-version [target] <patch | minor | major | X.Y.Z>
```

| Argument                    | Description                         |
| --------------------------- | ----------------------------------- |
| `target`                    | Target name (omit for first target) |
| `patch` / `minor` / `major` | Bump type                           |
| `X.Y.Z`                     | Direct version number               |

### Usage Examples

```bash
/forge:update-version patch                # Auto-detect changed targets and patch bump them
/forge:update-version forge 0.1.0          # Set forge to 0.1.0
/forge:update-version anvil minor          # Minor bump anvil
```

### Execution Flow

1. Load `.version-config.yaml`
2. Determine the target (auto-detected from changes matching `scope` when omitted)
3. Read current version
4. Compare with main branch (confirm if already bumped)
5. Calculate new version
6. Collect commit history (for CHANGELOG)
   - Look up the previous version's tag across all four combinations of prefix (present / absent) and `v` (present / absent), starting from the simplest form and taking the first one that exists: `1.2.3` → `v1.2.3` → `foo-1.2.3` → `foo-v1.2.3`. Fall back to the previous CHANGELOG entry's date when none exists
7. Update files
   - `version_file` (plugin.json, etc.)
   - `sync_files` (README, etc.) version sync
8. Offer to bump the catalog (marketplace) target
9. Insert CHANGELOG entry
10. Judge whether the change affects README (update it when it does)
11. Run tests (if `tests/` exists)
12. Git operations (confirm commit / push / tag; the tag name follows the format of existing tags)

### Error Handling

| Situation                      | Response                                        |
| ------------------------------ | ----------------------------------------------- |
| `.version-config.yaml` missing | Suggest running `/forge:setup-version-config`   |
| Target not found               | Show available targets                          |
| Test failure                   | Version update complete. Fix tests, then commit |

## help

Display forge skill list, build arguments via a guided wizard, and execute.

```
/forge:help
```

No arguments.

### Wizard Flow

1. **Skill selection**: Choose by number
2. **Argument builder**: Interactive prompts for the selected skill
3. **Command confirmation**: Show the built command and confirm execution

```
1. review              : Review code & documents
2. start-uxui-design   : Generate design tokens & UI component specs
3. start-requirements  : Create requirements documents
4. start-design        : Create design documents
5. start-plan          : Create implementation plans
6. start-implement     : Execute tasks from a plan
7. setup               : Initial setup
```
