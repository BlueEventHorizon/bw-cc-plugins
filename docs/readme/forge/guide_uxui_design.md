# UXUI Design Guide

Generate design tokens and UI component visual specs with UX evaluation from ASCII art screen layouts in requirements documents. Built for designer-absent development, producing theoretically grounded design systems based on Apple HIG, Don Norman, Dieter Rams, Nielsen heuristics, and Gestalt principles.

## start-uxui-design

```
/forge:start-uxui-design [feature] [--platform ios|macos]
```

| Argument | Description |
|----------|-------------|
| `feature` | Feature name (omit for interactive) |
| `--platform` | `ios` / `macos` (omit for interactive selection) |

### When to Use

- After requirements documents are complete, before creating design docs
- When building a design system for iOS / macOS apps
- When you need theory-backed UI without a designer

### Pipeline Position

```
start-requirements → start-uxui-design → start-design → start-plan → start-implement
 (what to build)       (how it looks)      (how to build)  (when)        (build)
```

start-uxui-design is optional. Skip it and go straight to start-design if design tokens are not needed.

### Usage Examples

```bash
# Generate design for iOS app
/forge:start-uxui-design user-auth --platform ios

# macOS app, Feature name decided interactively
/forge:start-uxui-design --platform macos
```

---

## 3-Layer Integrated Framework

The foundation for all design decisions. Applied bottom-up; upper layers cannot override lower layers.

| Layer | Role | Examples | Constraint |
|-------|------|---------|-----------|
| Layer 1: Cognitive constraints | Obey (inviolable) | Fitts's law, Hick's law, contrast ratio | Designs violating this layer are rejected |
| Layer 2: Structural tools | Combine | Modular scale, color harmony, 8pt grid | Combinations that break Layer 1 are rejected |
| Layer 3: Aesthetic direction | Choose | Dieter Rams, Don Norman, Tufte, wabi-sabi | Free within Layers 1 & 2 |

---

## 6-Phase Workflow

| Phase | What | Knowledge Base |
|-------|------|---------------|
| 1 | Requirements intake (ASCII art analysis) | — |
| 2 | Design direction (philosophical stance selection) | design_philosophy.md |
| 3 | Design token creation (color, typography, spacing) | apple_design_principles.md, platform guide |
| 4 | Component visual design (ASCII → HIG-compliant components) | Platform guide, templates |
| 5 | UX self-evaluation (3-layer framework self-check) | design_philosophy.md |
| 6 | Document generation & quality check (`/forge:review uxui --auto`) | review_criteria_uxui.md |

### Output

| Document | ID scheme | Content |
|----------|-----------|---------|
| Design tokens | THEME-xxx | Colors, typography, spacing, elevation |
| Component visual specs | CMP-xxx | Visual design per UI component (sizes, states, interactions) |

---

## UX Review

Standalone review via `/forge:review uxui` is also available. Verifies against 3 perspectives:

| Perspective | Focus |
|-------------|-------|
| **hig_compliance** | Apple HIG 4 principles compliance |
| **usability** | Nielsen heuristics, accessibility |
| **visual_system** | Token consistency, Gestalt principles |

```bash
# Review design tokens and component specs
/forge:review uxui specs/user-auth/design/

# With auto-fix
/forge:review uxui specs/user-auth/design/ --auto
```

---

## Usage Scenarios

For detailed scenarios, see [uxui_scenario.md](../uxui_scenario.md).

| Scenario | Summary |
|----------|---------|
| New iOS app | Build a design system from scratch |
| Existing app UI unification | Migrate existing components to token-based |
| macOS app | Generate tokens specialized for macOS HIG |
| Design review only | Review existing design specs from UX perspectives |
| Post-requirements update | Update tokens after ASCII art changes |
