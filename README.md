# bw-cc-plugins

A Claude Code plugin marketplace for AI-powered code & document review and project document structure management.

**Marketplace version: 0.1.1**

[Japanese README (README_ja.md)](README_ja.md)

## Plugins

| Plugin    | Version | Description                                                                                                   |
| --------- | ------- | ------------------------------------------------------------------------------------------------------------- |
| **forge** | 0.0.29  | AI-powered document lifecycle tool. Create, review, and auto-fix requirements/design/plan docs and code. |
| **anvil** | 0.0.4   | GitHub operations toolkit. Create PRs, manage issues, and automate GitHub workflows.                          |
| **xcode** | 0.0.1   | Xcode build and test toolkit. Build and test iOS/macOS projects with automatic platform detection.            |
| **doc-advisor** | 0.1.5 | AI-searchable document index (ToC) generator for Claude Code |

## Skills

### forge

> [Detailed Guide](docs/readme/README_forge.md) — Usage, examples, review types, severity levels, review criteria

| Skill | Description | Trigger |
|-------|-------------|---------|
| [**review**](docs/readme/README_forge.md#review) | Review code & docs with 🔴🟡🟢 severity. Auto-fix with `--auto N`. 5 types | `"レビュー"` `"review"` |
| [**setup-doc-structure**](docs/readme/README_forge.md#setup-doc-structure) | Generate `.doc_structure.yaml` + scaffold missing doc directories | `"forge の初期設定"` |
| [**start-requirements**](docs/readme/README_forge.md#start-requirements) | Create requirements docs via dialog, reverse-engineering, or Figma | `/forge:start-requirements` |
| [**start-design**](docs/readme/README_forge.md#start-design) | Create design documents from requirements | `"設計書作成"` |
| [**start-plan**](docs/readme/README_forge.md#start-plan) | Create or update implementation plan from design documents | `"計画書作成"` |
| [**start-implement**](docs/readme/README_forge.md#start-implement) | Select tasks from a plan, implement, review, and update | `"実装開始"` |
| [**start-uxui-design**](docs/readme/README_forge.md#start-uxui-design) | Create design tokens & component specs from requirements with UX evaluation (iOS/macOS) | `"UXUIデザイン"` |
| [**setup-version-config**](docs/readme/README_forge.md#setup-version-config) | Scan project and generate `.version-config.yaml` | `"version config を作成"` |
| [**update-version**](docs/readme/README_forge.md#update-version) | Bump version across files. patch/minor/major/direct | `"バージョン更新"` |
| [**clean-rules**](docs/readme/README_forge.md#clean-rules) | Analyze and reorganize project rules/ | `"rules を整理"` |
| [**help**](docs/readme/README_forge.md#help) | Interactive help wizard | `"forge help"` |
| *reviewer* | Execute review for a single perspective. AI-only, called by review orchestrator | — |
| *evaluator* | Scrutinize review findings and determine fix/skip/confirm. AI-only | — |
| *fixer* | Fix issues based on review findings. AI-only | — |
| *present-findings* | Present review findings interactively, one item at a time. AI-only | — |
| *doc-structure* | Parse and resolve paths from `.doc_structure.yaml`. AI-only utility | — |

### anvil

> [Detailed Guide](docs/readme/README_anvil.md) — Usage and examples

| Skill | Description | Trigger |
|-------|-------------|---------|
| [**commit**](docs/readme/README_anvil.md#commit) | Generate commit message from changes, commit & push | `"コミットして"` `"commit して"` |
| [**create-pr**](docs/readme/README_anvil.md#create-pr) | Create a GitHub draft PR with auto-generated title/body | `"PR を作成"` `"create-pr"` |

### xcode

> [Detailed Guide](docs/readme/README_xcode.md) — Usage and examples

| Skill | Description | Trigger |
|-------|-------------|---------|
| [**build**](docs/readme/README_xcode.md#build) | Build Xcode project with auto platform detection (iOS/macOS) | `"ビルド"` `"build"` |
| [**test**](docs/readme/README_xcode.md#test) | Run Xcode tests with simulator auto-detection for iOS | `"テスト"` `"test"` |

### doc-advisor

> [Detailed Guide](docs/readme/README_doc-advisor.md) — Usage and examples

| Skill | Description | Trigger |
|-------|-------------|---------|
| [**query-rules**](docs/readme/README_doc-advisor.md#query-rules) | Search the pre-analyzed rules document index (ToC) to identify relevant rule documents | `"What rules apply?"` `"ルール確認"` |
| [**query-specs**](docs/readme/README_doc-advisor.md#query-specs) | Search the pre-analyzed specs document index (ToC) to identify relevant specification documents | `"What specs apply?"` `"仕様確認"` |
| [**create-rules-toc**](docs/readme/README_doc-advisor.md#create-rules-toc) | Update the rules search index (ToC) after modifying rule documents | `"Rebuild the rules ToC"` |
| [**create-specs-toc**](docs/readme/README_doc-advisor.md#create-specs-toc) | Update the specs search index (ToC) after modifying spec documents | `"Rebuild the specs ToC"` |
| [**query-rules-index**](docs/readme/README_doc-advisor.md#query-rules-index) | Semantic search for rules using Embedding index | `"Semantic search for rules"` |
| [**query-specs-index**](docs/readme/README_doc-advisor.md#query-specs-index) | Semantic search for specs using Embedding index | `"Semantic search for specs"` |
| [**create-rules-index**](docs/readme/README_doc-advisor.md#create-rules-index) | Build/update the rules Embedding index for semantic search | `"Rebuild the rules embedding index"` |
| [**create-specs-index**](docs/readme/README_doc-advisor.md#create-specs-index) | Build/update the specs Embedding index for semantic search | `"Rebuild the specs embedding index"` |

> **Bold** = user-invocable, *Italic* = AI-only (called internally by other skills)

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

## Document Structure (.doc_structure.yaml)

`/forge:setup-doc-structure` scans project directories for markdown files, classifies them interactively, and generates `.doc_structure.yaml`. forge reads this file to collect reference documents during review and fix operations.

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

## Git Information Cache (.git_information.yaml)

On first run, `/anvil:create-pr` detects GitHub owner/repo from `git remote` and offers to save `.git_information.yaml`:

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
- [gh CLI](https://cli.github.com/) (for anvil, authenticated)
- Xcode with `xcodebuild` (for xcode plugin)

## License

[MIT](LICENSE)
