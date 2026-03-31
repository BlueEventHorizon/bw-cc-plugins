# bw-cc-plugins

A Claude Code plugin marketplace for AI-powered code & document review and project document structure management.

[Japanese README (README_ja.md)](README_ja.md)

## Plugins

| Plugin    | Version | Description                                                                                                   |
| --------- | ------- | ------------------------------------------------------------------------------------------------------------- |
| **forge** | 0.0.27  | AI-powered document lifecycle tool. Create, review, and auto-fix requirements/design/plan docs and code. |
| **anvil** | 0.0.4   | GitHub operations toolkit. Create PRs, manage issues, and automate GitHub workflows.                          |
| **xcode** | 0.0.1   | Xcode build and test toolkit. Build and test iOS/macOS projects with automatic platform detection.            |
| **doc-advisor** | 0.3.0 | Semantic search document index generator. Vectorizes document content via OpenAI Embedding API for task-relevant document discovery |

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

| Skill | Description | Trigger |
|-------|-------------|---------|
| [**query-rules**](#) | Semantic search for relevant rule documents using Embedding index | `"What rules apply?"` `"ルール確認"` |
| [**query-specs**](#) | Semantic search for relevant spec documents using Embedding index | `"What specs apply?"` `"仕様確認"` |
| [**create-rules-index**](#) | Build or update the rules Embedding index after modifying rule documents | `"Rebuild the rules index"` |
| [**create-specs-index**](#) | Build or update the specs Embedding index after modifying spec documents | `"Rebuild the specs index"` |

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
- `DOC_ADVISOR_OPENAI_API_KEY` environment variable (for doc-advisor semantic search)

### Setting up doc-advisor

doc-advisor requires an OpenAI API key for Embedding index generation and semantic search. Only the `/v1/embeddings` endpoint is used.

1. Go to [OpenAI API Keys](https://platform.openai.com/api-keys) and create a **restricted key**
2. Grant only **Embeddings** → **Write** permission (deny all others)
3. Set the environment variable:

```bash
export DOC_ADVISOR_OPENAI_API_KEY='sk-...'
```

Add this to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.) to persist across sessions. Model: `text-embedding-3-small` ($0.02/1M tokens — a full index rebuild of 600 docs costs less than $0.01).

## License

[MIT](LICENSE)
