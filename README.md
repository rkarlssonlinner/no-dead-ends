# ink-verify

Formal verification for Ink interactive fiction. Proves properties across all possible playthroughs using the Z3 SMT solver.

## Quick start

```bash
pip install .
ink-verify your-story.ink.json
```

That's it. With no config, ink-verify checks every knot is reachable, there are no dead ends, and numeric variables stay non-negative. It prints PASS/FAIL for each check.

## Workflow

```
1. Write your story             your-story.ink
2. Compile it                   inklecate -o story.ink.json your-story.ink
3. Verify it                    ink-verify story.ink.json
4. Fix what it finds            (edit your .ink, recompile, re-verify)
```

Or skip step 2 — ink-verify also accepts `.tale` packages, `.otproject` files, and directories with `.ink` files:

```bash
ink-verify my-story.tale          # extracts compiled JSON from .tale ZIP
ink-verify my-story.otproject     # extracts .ink, compiles, verifies
ink-verify story/                 # compiles main.ink in directory
```

## What it checks (auto-detect)

| Check | What it means |
|-------|---------------|
| Reachability | Can every knot be reached by some sequence of choices? |
| No dead ends | Does every reachable non-terminal node have at least one available choice? |
| Numeric bounds | Do integer variables stay non-negative? |

When a check fails, ink-verify shows the specific path that causes the problem:

```
ink-verify — story.ink.json (5 knots, 2 variables)

  [PASS] start reachable
  [PASS] shop reachable
  [FAIL] no dead ends
         Dead end at 'shop'
         Path:
           start  (gold=3)
           shop  (gold=1)
  [PASS] gold >= 0

3 passed, 1 failed
```

## Custom properties

For checks beyond the defaults, write a YAML file:

```yaml
properties:
  - name: "ending is reachable"
    type: reachable
    knot: "good_ending"

  - name: "health never negative"
    type: invariant
    expr: "health >= 0"

  - name: "boss fight requires sword"
    type: implication
    if_knot: "boss_fight"
    then_expr: "has_sword == True"

  - name: "no dead ends"
    type: no_dead_ends
```

```bash
ink-verify story.ink.json --properties checks.yaml
```

**Property types:**

- **reachable** — at least one playthrough reaches the named knot
- **invariant** — expression holds at every reachable node (Python syntax: `gold >= 0`, `health > 0 and stamina > 0`)
- **implication** — whenever a knot is reached, the expression holds
- **no_dead_ends** — every reachable non-terminal has at least one satisfiable exit

## JSON output

For editor or CI integration:

```bash
ink-verify story.ink.json --json
```

```json
{
  "story": "story.ink.json",
  "knots": 5,
  "variables": ["gold", "has_key"],
  "results": [
    {"name": "no dead ends", "type": "no_dead_ends", "passed": false,
     "reason": "Dead end at 'shop'",
     "counterexample": {"path": ["start", "shop"], "choices": ["Buy sword"],
       "variables_at_violation": {"gold": 0}}}
  ]
}
```

## Options

| Flag | Description |
|------|-------------|
| `--properties FILE` | YAML file with custom checks |
| `--json` | Structured JSON output |
| `--bound N` | Visit count bound for loops (default: 3) |
| `--verbose` | Show full counterexample paths |

## Supported Ink features

Knots, stitches, diverts, choices (once-only and sticky), fallback choices, global variables and assignments, conditional choices, arithmetic and comparison operators, gather points, tunnels.

## Limitations

- Loops are verified up to a configurable visit bound (default 3)
- Ink threads (`<-`), lists (`LIST`), external functions, and string operations are not supported
- Stories with cycles are detected and reported

## Installation

Requires Python 3.10+. Dependencies (z3-solver, pyyaml, click) install automatically.

```bash
pip install .
```

To compile `.ink` source files, install inklecate:

```bash
npm install -g inklecate
```

## License

MIT
