# forge Detailed Guide

AI-powered document lifecycle tool. Create requirements/design/plan docs, review code & documents, and auto-fix issues.

## Feature

forge can optionally manage documents per **Feature** — a grouped unit of related specifications for development. Features are not required; forge works without them.

| Development Pattern | How Features are used |
|--------------------|-----------------------|
| Incremental development | Separate new capabilities from the existing main spec as individual Features |
| Agile development | Develop and deliver per Feature in each iteration |
| Small projects | Treat the entire project as a single Feature |

When using Features, each one shares a common directory structure:

```
specs/
  {feature}/
    requirements/   # Requirements documents
    design/         # Design documents
    plan/           # Implementation plan
```

## Review Types

| Type          | Target                                      |
| ------------- | ------------------------------------------- |
| `code`        | Source code files and directories           |
| `requirement` | Requirements documents                      |
| `design`      | Design documents                            |
| `plan`        | Development plans                           |
| `generic`     | Any document (rules, skills, READMEs, etc.) |

## Severity Levels

| Level    | Meaning                                                           |
| -------- | ----------------------------------------------------------------- |
| 🔴 Critical | Must fix. Bugs, security issues, data loss risks, spec violations |
| 🟡 Major    | Should fix. Coding standards, error handling, performance         |
| 🟢 Minor    | Nice to have. Readability, refactoring suggestions                |

## Review Criteria

Review criteria are accumulated from the following sources:

- **Plugin default** (always included): Perspectives from `skills/review/docs/review_criteria_{type}.md`
- **DocAdvisor** (additional perspectives): If `/query-rules` is available, project-specific rules are added as extra perspectives

---

## Skill Details

### review

```
/forge:review <type> [target] [--engine] [--auto [N]] [--auto-critical]
```

| Argument | Description |
|----------|-------------|
| `type` | `requirement` / `design` / `code` / `plan` / `generic` |
| `target` | File path(s) / feature name / directory / omit for interactive |
| `--codex` / `--claude` | Engine selection (default: codex) |
| `--auto [N]` | Auto review+fix for N cycles (default N=1) |
| `--auto-critical` | Auto-fix 🔴 critical issues only |

```bash
/forge:review code src/                    # Interactive mode
/forge:review code src/ --auto 3           # 3 auto-fix cycles
/forge:review requirement login            # By feature name
```

### setup-doc-structure

```
/forge:setup-doc-structure
```

No arguments. Interactively generates or updates `.doc_structure.yaml`.

### start-requirements

```
/forge:start-requirements [feature] [--mode interactive|reverse-engineering|from-figma] [--new|--add]
```

| Argument | Description |
|----------|-------------|
| `feature` | Feature name (omit for interactive) |
| `--mode` | `interactive` / `reverse-engineering` / `from-figma` |
| `--new` | New app |
| `--add` | Adding features to existing app |

### start-design

```
/forge:start-design [feature]
```

| Argument | Description |
|----------|-------------|
| `feature` | Feature name (omit for interactive) |

### start-plan

```
/forge:start-plan [feature]
```

| Argument | Description |
|----------|-------------|
| `feature` | Feature name (omit for interactive) |

### start-implement

```
/forge:start-implement [feature] [--task TASK-ID[,TASK-ID,...]]
```

| Argument | Description |
|----------|-------------|
| `feature` | Feature name (omit for interactive) |
| `--task` | Task ID(s) to execute (comma-separated, omit for priority-based auto-selection) |

### setup-version-config

```
/forge:setup-version-config
```

No arguments. Scans project and interactively generates/updates `.version-config.yaml`.

### update-version

```
/forge:update-version [target] <new-version | patch | minor | major>
```

| Argument | Description |
|----------|-------------|
| `target` | Target name (omit for first/only target) |
| `patch` / `minor` / `major` | Bump type |
| `new-version` | Direct version number (e.g. `1.2.3`) |

```bash
/forge:update-version patch              # Patch bump first target
/forge:update-version forge 0.1.0       # Set forge to 0.1.0
```

### clean-rules

```
/forge:clean-rules
```

No arguments. Analyzes and reorganizes project rules/ based on document taxonomy.

### help

```
/forge:help
```

No arguments. Interactive wizard to select a skill, fill in arguments, and execute.
