# Document Creation Guide

Create development documents in three stages: requirements → design → plan. Each skill takes the previous stage's output as input and ends with a common completion flow: AI review → search-index update → commit.

```
start-requirements → start-design → start-plan → start-implement
 (what to build)      (how to build)   (when)        (build)
```

## Common Mechanisms

### Context Gathering

All three skills share a common context-gathering pattern. Before document creation, parallel agents collect the following and return the results as return values (markdown lists):

| Agent       | Target                                     | Search Method           |
| ----------- | ------------------------------------------ | ----------------------- |
| specs agent | Specifications (requirements, design docs) | `/forge:query-db-specs` |
| rules agent | Project rule documents                     | `/forge:query-db-rules` |
| code agent  | Existing implementations                   | Direct `Grep` / `Glob`  |

The agents launched differ by skill. start-design identifies the requirements document from its location and gathers only the project rules with an agent (existing implementations are read after the design, during matching).

### Completion Flow

After document creation, the following steps execute sequentially:

1. `/forge:review {type} --auto` — AI review + auto-fix
2. `/forge:update-db-specs` — search-index update (when available)
3. `/anvil:commit` — commit/push confirmation

---

## start-requirements

Create requirements documents. Supports three modes with different input sources.

```
/forge:start-requirements [feature] [--mode interactive|reverse-engineering|from-figma] [--new|--add]
```

| Argument  | Description                         |
| --------- | ----------------------------------- |
| `feature` | Feature name (omit for interactive) |
| `--mode`  | Mode selection (omit for menu)      |
| `--new`   | New app                             |
| `--add`   | Adding features to existing app     |

### Mode Selection Guide

| Mode                  | Input source         | When to use                         | Prerequisites         |
| --------------------- | -------------------- | ----------------------------------- | --------------------- |
| `interactive`         | User dialog          | Defining requirements from scratch  | `.doc_structure.yaml` |
| `reverse-engineering` | Existing source code | Documenting existing code           | Source code           |
| `from-figma`          | Figma design files   | Extracting requirements from design | Figma MCP environment |

### Usage Examples

```bash
# Define requirements from scratch
/forge:start-requirements user-auth --mode interactive --new

# Reverse-engineer from existing code
/forge:start-requirements dashboard --mode reverse-engineering --add

# Extract from Figma design
/forge:start-requirements product-catalog --mode from-figma --new
```

### Execution Flow

1. Confirm mode, Feature name, and new/add
2. Context gathering (parallel)
3. Mode-specific workflow (dialog / source analysis / Figma analysis)
4. Completion flow (review → search-index update → commit)

### Output

Generates requirements documents (Markdown) in `specs/{feature}/requirements/`. ID scheme:

| Prefix  | Type                        |
| ------- | --------------------------- |
| APP-xxx | App overview & policies     |
| SCR-xxx | Screen specifications       |
| FNC-xxx | Functional specifications   |
| NFR-xxx | Non-functional requirements |

### Reference Documents

- `plugins/forge/docs/requirement_format.md` — Requirements template
- `plugins/forge/docs/spec_design_boundary_spec.md` — Requirements/design boundary guide

---

## start-design

Create design documents from requirements. Builds the upstream design from the requirements document alone, then matches it against existing implementations and design patterns and reuses existing implementations that can be used without modification.

```
/forge:start-design [feature]
```

| Argument  | Description                         |
| --------- | ----------------------------------- |
| `feature` | Feature name (omit for interactive) |

### When to Use

- After requirements documents are complete
- When you want to document architecture and module structure

### Execution Flow

1. Confirm Feature name
2. **Gather inputs**
   - Identify the requirements document (list the feature's `requirements/`; choose when there are several; with none, point to `/forge:start-requirements` and stop)
   - Collect project design rules (`/forge:query-db-rules`)
3. **Upstream design** (from the requirements alone): the user approves the scenario table and the upstream design
4. **Matching against existing implementations and design patterns**, and redesign
5. **Detailed design** and consistency check (traceability table)
6. **Review** (self-review → `/forge:review --auto` → user review)
7. Completion flow (search-index update → commit)

### Design Principles

- **Build from the requirements**: Do not start from existing implementations or design patterns; build the upstream design from the requirements document and the project rules alone
- **Reuse existing assets**: After the upstream design, read the existing code and reuse components that can be used without modification instead of creating new ones
- **What/How boundary**: Clearly separate requirements (what) from design (how)
- **Traceability**: Every requirement must be traceable to a design section

### Output

Generates design documents (Markdown) in `specs/{feature}/design/`. ID scheme: `DES-xxx`

### Reference Documents

- `plugins/forge/docs/design_method.md` — Design procedure and deliverables
- `plugins/forge/docs/design_principles_spec.md` — Design principles guide
- `plugins/forge/docs/spec_design_boundary_spec.md` — What/How boundary

---

## start-plan

Extract tasks from design documents and create a JSON plan.

```
/forge:start-plan [feature]
```

| Argument  | Description                         |
| --------- | ----------------------------------- |
| `feature` | Feature name (omit for interactive) |

### When to Use

- After design documents are complete
- When planning task breakdown and scheduling

### Execution Flow

1. Confirm Feature name
2. **Context gathering** (2 agents in parallel)
   - Retrieve requirements + design docs
   - Collect plan rules
3. Check for existing plan (update mode)
4. Create/update plan (task extraction → granularity check → ID assignment)
5. Completion flow (review → search-index update → commit)

### Task Granularity Criteria

| Criterion    | Requirement                                              |
| ------------ | -------------------------------------------------------- |
| Unit         | A single agent can execute and complete it independently |
| Volume       | 5–10 actionable items per task                           |
| Completeness | Build and test must pass at task completion              |
| File scope   | 1 file or 2–3 closely related files                      |

### Plan Structure (Minimal Complete JSON)

The plan is a JSON file named `{feature}_plan.json`. **It is not Markdown.**
The top level has exactly three keys: `requirements_traceability` / `design_traceability` / `tasks`. Plans carry no frontmatter, even for additive-development features — whether a plan belongs to an additive feature is determined by following `requirements_traceability` to the requirement document's `feature_type: temporary-feature` frontmatter. A script (`write_plan.py`, etc.) writes and validates the file, so the AI does not need to know the file format itself.

```json
{
  "requirements_traceability": [
    {
      "requirement_id": "REQ-001",
      "title": "Requirement title",
      "design_id": "DES-001",
      "status": "pending"
    }
  ],
  "design_traceability": [
    {
      "design_id": "DES-001",
      "title": "Design title",
      "requirement_ids": ["REQ-001"],
      "task_ids": ["TASK-001"]
    }
  ],
  "tasks": [
    {
      "task_id": "TASK-001",
      "title": "Task name",
      "priority": 90,
      "status": "pending",
      "design_id": "DES-001",
      "depends_on": [],
      "group_id": null,
      "build_check": "per_task",
      "description": ["Action item 1", "Action item 2"],
      "acceptance_criteria": "Yes/No-judgable acceptance criteria",
      "required_reading": ["specs/{feature}/design/DES-001_xxx.md"]
    }
  ]
}
```

**Field value ranges**:

- `status` (requirement): `pending` / `completed`
- `priority`: High 70-99 / Mid 40-69 / Low 1-39
- `status` (task): `pending` / `in_progress` / `completed`
- `design_id`: `null` when absent (never `-`)
- `depends_on`: array of dependency task IDs. Use `[]` when none
- `group_id`: `null` for independent tasks, e.g. `"GROUP-001 (1/3)"`
- `build_check`: `per_task` / `skip` / `on_group_complete`
- `acceptance_criteria`: `null` when none
- `required_reading`: array of required reading paths. Use `[]` when none

### Key Principles

- `description` should reference the design doc section, not contain implementation details
- Dependencies must not form cycles
- The traceability matrix must verify all requirements and designs are covered

### Output

Generates the plan (JSON) at `specs/{feature}/plan/{feature}_plan.json`. **A Markdown plan is never emitted.**
A Claude Code plan-mode Markdown plan is a different artifact; if you want to derive a requirements document from one, use `/forge:create-requirements-from-plan-mode`.

### Reference Documents

- `plugins/forge/docs/plan_principles_spec.md` — Task granularity and grouping guide
