# bw-cc-plugins

A Claude Code plugin marketplace for AI-powered code & document review and project document structure management.

[Japanese README (README_ja.md)](README_ja.md)

## Plugins

| Plugin    | Version | Description                                                                                                   |
| --------- | ------- | ------------------------------------------------------------------------------------------------------------- |
| **forge** | 0.0.23  | AI-powered document lifecycle tool. Create, review, and auto-fix requirements/design/plan docs and code. |
| **anvil** | 0.0.4   | GitHub operations toolkit. Create PRs, manage issues, and automate GitHub workflows.                          |
| **xcode** | 0.0.1   | Xcode build and test toolkit. Build and test iOS/macOS projects with automatic platform detection.            |

## Installation

### Option A: Marketplace (persistent)

Inside a Claude Code session:

```
/plugin marketplace add BlueEventHorizon/bw-cc-plugins
/plugin install forge@bw-cc-plugins
```

If you already installed, from your terminal:

```bash
claude plugin enable forge@bw-cc-plugins
```

`marketplace add` registers the GitHub repo as a plugin source (once per user). Once installed, the plugin is always available.

### Option B: Local directory (per session)

```bash
git clone https://github.com/BlueEventHorizon/bw-cc-plugins.git
claude --plugin-dir ./bw-cc-plugins/plugins/forge
```

> **Note**: `--plugin-dir` is session-only. You must specify it every time you start Claude Code. To unload, simply start without the flag.

### Update

From your terminal:

```bash
claude plugin update forge@bw-cc-plugins --scope local
```

## forge

AI-powered document lifecycle tool. Create requirements/design/plan docs, review code & documents, and auto-fix issues.

### Feature

forge manages documents per **Feature** — a grouped unit of related specifications for development.

| Development Pattern | How Features are used |
|--------------------|-----------------------|
| Incremental development | Separate new capabilities from the existing main spec as individual Features |
| Agile development | Develop and deliver per Feature in each iteration |
| Small projects | Treat the entire project as a single Feature |

Skills like `start-requirements`, `start-design`, `start-plan`, and `start-implement` operate on a Feature. Each Feature has its own requirements, design docs, and plan under a shared directory:

```
specs/
  {feature}/
    requirements/   # Requirements documents
    design/         # Design documents
    plan/           # Implementation plan
```

### Usage

```
/forge:review <type> [target] [--engine] [--auto [N]]
```

| Argument | Values                                                                              |
| -------- | ----------------------------------------------------------------------------------- |
| type     | `code` \| `requirement` \| `design` \| `plan` \| `generic`                          |
| target   | File path(s), directory, feature name, or omit for interactive                      |
| engine   | `--codex` (default) \| `--claude`                                                   |
| mode     | `--auto [N]` (review+fix N cycles, default 1) \| `--auto-critical` (🔴 only) |

### Examples

```bash
# Review source files in a directory
/forge:review code src/

# Review a specific file
/forge:review code src/services/auth.swift

# Review requirements by feature name
/forge:review requirement login

# Review a design document
/forge:review design specs/login/design/login_design.md

# Review a plan with 1 auto-fix cycle (default)
/forge:review plan specs/login/plan/login_plan.yaml --auto

# Review and auto-fix up to 3 cycles
/forge:review code src/ --auto 3

# Review only (no fix)
/forge:review code src/ --auto 0

# Review any document
/forge:review generic README.md

# Review branch diff (no target = current branch changes)
/forge:review code

# Use Claude engine instead of Codex
/forge:review code src/ --claude

# Create or update .doc_structure.yaml interactively
/forge:setup-doc-structure

# Create requirements document interactively
/forge:start-requirements

# Create requirements from existing app source code
/forge:start-requirements myfeature --mode reverse-engineering

# Review + auto-fix after creating a document
/forge:review requirement specs/login/requirements/requirements.md --auto
/forge:review requirement specs/login/requirements/requirements.md --auto 3
```

### Skills

| Skill                 | User-invocable | Description                                                                                                                                   |
| --------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `review`              | Yes            | Orchestrator: collects references, delegates to reviewer/evaluator/fixer, then commits                                                        |
| `setup-doc-structure` | Yes            | Scans project directories, classifies them as rules/specs, and generates `.doc_structure.yaml`                                                |
| `start-requirements` | Yes            | Creates requirements documents via interactive dialog, source code reverse-engineering, or Figma design                                       |
| `start-design`       | Yes            | Creates design documents from requirements. Auto-detects project workflow via /query-rules, falls back to built-in workflow                   |
| `start-plan`         | Yes            | Creates or updates implementation plan from design documents. Auto-detects project workflow via /query-rules, falls back to built-in workflow |
| `start-implement`     | Yes            | Orchestrator: selects tasks from a plan, gathers context, delegates to executor agent, reviews, and updates the plan                          |
| `setup-version-config`| Yes            | Scans project files and generates `.version-config.yaml` for version bump configuration. Re-run on project structure changes                  |
| `update-version`      | Yes            | Bumps version across all files defined in `.version-config.yaml`. Supports patch/minor/major/direct. Optionally auto-generates CHANGELOG      |
| `help`                | Yes            | Interactive help wizard. Select a skill, fill in arguments step-by-step, and execute directly                                                 |
| `present-findings`    | No (AI only)   | Presents review findings interactively, one item at a time (human acts as evaluator)                                                          |
| `reviewer`            | No (AI only)   | Executes review and collects reference documents. Returns findings + reference doc paths                                                      |
| `evaluator`           | No (AI only)   | Scrutinizes review findings with 5 criteria and determines what to fix/skip/confirm                                                           |
| `fixer`               | No (AI only)   | Fixes issues based on review findings. Accepts reference doc paths to avoid re-collection                                                     |

### Review Types

| Type          | Target                                      |
| ------------- | ------------------------------------------- |
| `code`        | Source code files and directories           |
| `requirement` | Requirements documents                      |
| `design`      | Design documents                            |
| `plan`        | Development plans                           |
| `generic`     | Any document (rules, skills, READMEs, etc.) |

### Severity Levels

| Level    | Meaning                                                           |
| -------- | ----------------------------------------------------------------- |
| Critical | Must fix. Bugs, security issues, data loss risks, spec violations |
| Major    | Should fix. Coding standards, error handling, performance         |
| Minor    | Nice to have. Readability, refactoring suggestions                |

### Review Criteria

The plugin includes review criteria in `docs/review_criteria_spec.md`. Projects can override this by:

1. **DocAdvisor**: If the project has DocAdvisor skills (`/query-rules`), the plugin queries them for project-specific review criteria
2. **Project config**: Save a custom path in `.claude/review-config.yaml`
3. **Plugin docs**: Falls back to the bundled `docs/review_criteria_spec.md`

### Document Structure (.doc_structure.yaml)

The `setup-doc-structure` skill scans project directories for markdown files, classifies them interactively, and generates `.doc_structure.yaml`. forge reads this file directly to collect reference documents during review and fix operations.

See [docs/specs/forge/design/doc_structure_format.md](docs/specs/forge/design/doc_structure_format.md) for the full schema specification.

```yaml
# doc_structure_version: 3.0

rules:
  root_dirs:
    - docs/rules/
  doc_types_map:
    docs/rules/: rule

specs:
  root_dirs:
    - "docs/specs/*/design/"
    - "docs/specs/*/requirement/"
  doc_types_map:
    "docs/specs/*/design/": design
    "docs/specs/*/requirement/": requirement
```

## xcode

Xcode build and test toolkit. Build and test iOS/macOS projects with automatic scheme and platform detection.

### Usage

```
/xcode:build [scheme-name]
/xcode:test [scheme-name] [test-target]
```

### Examples

```bash
# Build the project (auto-detect scheme and platform)
/xcode:build

# Build a specific scheme
/xcode:build MyApp

# Run all tests
/xcode:test

# Run a specific test target
/xcode:test MyApp LibraryTests/FooTests
```

### Skills

| Skill   | User-invocable | Description                                                                      |
| ------- | -------------- | -------------------------------------------------------------------------------- |
| `build` | Yes            | Full clean build with error reporting. Auto-detects iOS/macOS platform.          |
| `test`  | Yes            | Runs tests with simulator auto-detection for iOS. Reports failures with details. |

### Requirements

- Xcode with `xcodebuild` in PATH
- iOS testing: Xcode Simulator

---

## anvil

GitHub operations toolkit. Create PRs from the current branch with auto-generated titles and body from commit history.

### Usage

```
/anvil:create-pr [base-branch]
```

### Examples

```bash
# Create a draft PR from the current branch
/anvil:create-pr

# Specify a base branch explicitly
/anvil:create-pr develop
```

### Skills

| Skill       | User-invocable | Description                                                                                            |
| ----------- | -------------- | ------------------------------------------------------------------------------------------------------ |
| `create-pr` | Yes            | Creates a GitHub draft PR with title/body generated from commit diff. Requires `gh` CLI.               |
| `commit`    | Yes            | Generates a commit message from changes and commits & pushes. Auto-appends issue ref from branch name. |

### Requirements

- [gh CLI](https://cli.github.com/) (authenticated)

### Git Information Cache (.git_information.yaml)

On first run, `create-pr` detects GitHub owner/repo from `git remote` and offers to save `.git_information.yaml` to avoid repeating git commands:

```yaml
version: "1.0"
github:
  owner: "<org-or-user>"
  repo: "<repo-name>"
  remote_url: "<url>"
  default_base_branch: main
  pr_template: .github/PULL_REQUEST_TEMPLATE.md
```

## Requirements

- [Claude Code](https://claude.ai/code) CLI
- Python 3 (for setup scan)
- [Codex CLI](https://github.com/openai/codex) (optional, for Codex engine; falls back to Claude if unavailable)

## License

[MIT](LICENSE)
