# ink-verify

Formal verification for Ink interactive fiction. Proves properties across all possible playthroughs using the Z3 SMT solver.

ink-verify works on the compiled Ink JSON that every Ink tool produces — inklecate, inkjs, Inky, ink-unity-integration, and the offtrail editor all output the same format. If you have a `.tale`, `.otproject`, or raw `.ink` files, ink-verify handles those too.

## Quick start

```bash
pip install .
ink-verify my-story.tale
```

That's it. ink-verify extracts the compiled story from your `.tale` and checks every knot is reachable, there are no dead ends, and numeric variables stay non-negative.

The `.tale` is the same package your editor builds when you save or publish — `story/main.ink.json` inside the ZIP. No extra compile step.

## Workflow

```
1. Write your story in the editor
2. Save / export your .tale
3. ink-verify my-story.tale
4. Fix what it finds, repeat
```

ink-verify also accepts other inputs:

```bash
ink-verify my-story.tale          # .tale package (primary workflow)
ink-verify my-story.otproject     # project file (extracts .ink, compiles, verifies)
ink-verify story/main.ink.json    # compiled Ink JSON directly
ink-verify story/                 # directory with .ink files (compiles with inklecate)
```

## What counts as input

ink-verify works on **compiled Ink JSON** — the `.ink.json` file that any Ink compiler produces (inklecate, inkjs, Inky, ink-unity-integration). This is the same format regardless of which tool compiled it.

| You have | What to run |
|----------|-------------|
| A `.tale` file from the offtrail editor | `ink-verify my-story.tale` |
| An `.otproject` file | `ink-verify my-story.otproject` |
| A standalone HTML export directory (from Inky "Export for web") | `ink-verify path/to/my-story.js` — not yet supported; extract the JSON from the JS wrapper first |
| A compiled `.json` file from inklecate or Inky | `ink-verify story.ink.json` |
| Raw `.ink` source files (not compiled) | `ink-verify story/` — compiles with inklecate first (must be installed: `npm install -g inklecate`) |
| A single `.ink` file | `ink-verify my-story.ink` — compiles then verifies |

Raw `.ink` requires inklecate on your PATH. Compiled JSON works without it.

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
