# Switching forge Backends

forge has two independent, swappable backend axes.

| Axis                    | Candidates                                | Used by                                                                            |
| ----------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------- |
| Document-search backend | doc-advisor (default first) / doc-db      | `/forge:query-db-rules` / `query-db-specs` / `update-db-rules` / `update-db-specs` |
| Review executor         | agent-review (the only current candidate) | `/forge:review`                                                                    |

Both are switched via the project settings file `.claude/.forge.yaml` (relative to the project root). The file is optional; without it, the defaults apply.

## Settings File Syntax

```yaml
# .claude/.forge.yaml
doc_backend:
  prefer: doc-db # doc-db | doc-advisor

review:
  backend: agent-review # agent-review is the only current candidate
```

### `doc_backend.prefer` (document search)

- Puts the specified backend first in the ordered list (e.g. `doc-db` yields `["doc-db", "doc-advisor"]`). The default without this setting is doc-advisor first
- If the first backend is unavailable, forge notifies you of the reason and uses the other one
- The only accepted key is `prefer`. Unknown keys or values outside the two allowed ones raise an explicit error (forge never silently falls back to the default — this prevents a setting you believe is active from being quietly ignored)

### `review.backend` (review executor)

- Runs **only** the specified backend (treated as an explicit choice). If it is unavailable, forge does not pick an alternative; it fails without sending a request (fail closed)
- Without this setting, the candidates are probed in order and the first available one is used (**agent-review is the only current candidate**; the resolution machinery is unchanged even with a single candidate)
- The only accepted key is `backend`

## Forcing a Backend by Argument (overrides the setting)

| Skill                                        | Argument                        | Behavior                                            |
| -------------------------------------------- | ------------------------------- | --------------------------------------------------- |
| `/forge:update-db-rules` / `update-db-specs` | `--backend doc-db\|doc-advisor` | Uses only that backend; fails closed if unavailable |
| `/forge:review`                              | `--backend <name>`              | Same as above                                       |
| `/forge:query-db-rules` / `query-db-specs`   | (no such flag)                  | Always decided by the ordered list                  |

Precedence: **argument > `.claude/.forge.yaml` > default order**.

## Notes

- `.claude/.forge.yaml` is parsed as a restricted YAML subset. Anchors/aliases (`&` / `*`), multi-line strings (`|` / `>`), and flow style (`[...]` / `{...}`) are not supported; if present, the whole file is treated as unparsable and raises an explicit error
- For the rationale behind the review-executor candidate order and each backend's prerequisites, see [guide_review.md](forge/guide_review.md)
