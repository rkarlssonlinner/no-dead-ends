# ink-verify

Formal verification for Ink interactive fiction. Proves properties across all possible playthroughs using the Z3 SMT solver. Passes are true negatives. Failures are a mixture of true and false positives for human review. Although imperfect, this reduces the need for brute-force tracing or human review of all paths.

ink-verify needs both your `.ink` source and the compiled JSON. The source gives accurate variable types (the compiled bytecode loses the difference between strings, booleans, and integers). The compiled JSON gives the runtime graph that Z3 verifies.

## Quick start

```bash
pip install .
ink-verify story.ink.json --source story/
```

Supply both: the compiled JSON (from inklecate, Inky, inkjs, or any Ink compiler) and `--source` pointing to your `.ink` files.

For Offtrail Tales:

```bash
ink-verify my-story.tale --source story/
ink-verify my-story.otproject
```

## Reproduce the test results

```bash
git clone https://github.com/rkarlssonlinner/no-dead-ends
cd no-dead-ends
pip install .
bash scripts/verify_examples.sh
```

Results are written to `results/`. The committed results match what the script produces.

## Workflow

```
1. Write your story in an editor (Inky, VS Code, etc.)
2. Compile it (inklecate, Inky export, or your build tool)
3. ink-verify story.ink.json --source story/
4. Fix what it finds, repeat
```

For Offtrail Tales:

```
1. Write your story in the editor
2. Save / export your .tale or .otproject
3. ink-verify my-story.tale --source story/
4. Fix what it finds, repeat
```

Always supply both compiled JSON and `--source` pointing to your `.ink` files:

```bash
ink-verify story.ink.json --source story/     # compiled JSON + source (primary)
ink-verify my-story.tale --source story/      # .tale + source directory
ink-verify my-story.otproject                 # .otproject contains both
```

## What counts as input

ink-verify needs **compiled Ink JSON** (the `.ink.json` file any Ink compiler produces) **plus** your `.ink` source files (via `--source`). The `.otproject` format contains both. A directory with `.ink` files compiles and verifies in one step.

| You have | What to run |
|----------|-------------|
| A `.tale` + source directory | `ink-verify my-story.tale --source story/` |
| An `.otproject` file | `ink-verify my-story.otproject` (contains both) |
| A compiled `.json` + source | `ink-verify story.ink.json --source story/` |
| A directory with `.ink` files | `ink-verify story/` (compiles with inklecate, requires `npm install -g inklecate`) |

## What it checks (auto-detect)

| Check | What it means |
|-------|---------------|
| Reachability | Can every knot be reached by some sequence of choices? |
| No dead ends | Does every reachable non-terminal node have at least one available choice? |
| Numeric bounds | Do integer variables stay non-negative? |

The `.ink` source (via `--source`) corrects variable types from the source declarations, checks only author-written knots (compiler-generated gathers and choice internals are skipped), and shows file:line locations in failure output.

When a check fails, ink-verify names the problem. Use `--verbose` to see the full path:

```
ink-verify — story.ink.json (5 knots, 2 variables + source)

  [PASS] start reachable
  [PASS] shop reachable
  [FAIL] no dead ends
         Dead end at 'shop'
  [PASS] gold >= 0

3 passed, 1 failed
```

With `--verbose`, failures include the path and variable values at each step:

```
  [FAIL] no dead ends
         Dead end at 'shop'
         Path:
           start  (gold=3)
           shop -> "Buy sword"  (gold=1)
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
ink-verify story.ink.json --source story/ --properties checks.yaml
```

**Property types:**

- **reachable** — at least one playthrough reaches the named knot
- **invariant** — expression holds at every reachable node (Python syntax: `gold >= 0`, `health > 0 and stamina > 0`)
- **implication** — whenever a knot is reached, the expression holds
- **no_dead_ends** — every reachable non-terminal has at least one satisfiable exit

## JSON output

For editor or CI integration:

```bash
ink-verify story.ink.json --source story/ --json
```

```json
{
  "story": "story.ink.json",
  "knots": 5,
  "variables": ["gold", "has_key"],
  "has_source": true,
  "coverage": 100.0,
  "edges_resolved": 12,
  "edges_dropped": 0,
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
| `-s, --source PATH` | Path to .ink source (directory, .otproject, or .ink file) for accurate variable types and source locations in errors |
| `-p, --properties FILE` | YAML file with custom checks |
| `--json` | Structured JSON output |
| `-v, --verbose` | Show full counterexample paths |

## Tested on

| Story | Author knots | Variables | Result |
|-------|-------------|-----------|--------|
| Own story (Offtrail Tales) | 28 | 9 | 29 passed, 0 failed |
| [The Intercept](https://github.com/inkle/the-intercept) by inkle | 60 | 21 | 45 passed, 18 failed |

Breakdown of The Intercept's 18 failures:

| Count | Type | Verdict | Explanation |
|-------|------|---------|-------------|
| 15 | Stitch reachability | Review manually | Graph chain incomplete — edges exist but the solver can't trace a full path through compiled bytecode |
| 1 | Dead end | Review manually | Dead end detected at `start` |
| 1 | `forceful >= 0` | True positive | Integer variable decremented 12 times without a floor check — certain playthroughs push it below zero |
| 1 | `evasive >= 0` | False positive | Flagged, but the source shows `evasive` is never decremented — encoder limitation |

174 compiler-generated internal nodes were skipped. 45 checks passed.

When ink-verify can't fully trace an internal path, it says so and reports a coverage metric. A PASS is proven. A FAIL names the reason — check whether it's a real problem or a parser limitation.

## Real-world example

Running ink-verify on a 28-knot Offtrail Tales story with 9 variables:

```
ink-verify my-story.tale --source story/

ink-verify — my-story.tale (40 knots, 9 variables + source)

  [PASS] radio reachable
  [PASS] flat reachable
  [PASS] signup reachable
  ...
  [INFO] Skipped 38 compiler-generated nodes. Checked 28 author-written knots.
  [PASS] no dead ends

29 passed, 0 failed
```

**How to read the output:**

- **PASS** — Z3 proved this holds across all possible playthroughs.
- **FAIL with "no incoming edges"** — provably unreachable. Nothing connects to this knot.
- **FAIL with "has N incoming edges but no verified path"** — edges exist but the solver can't trace a full path. Parser limitation with deeply nested compiled JSON. Review manually.
- **FAIL on an invariant** — a specific playthrough violates the condition. Use `--verbose` to see the path.

## Supported Ink features

Knots, stitches, diverts, choices (once-only and sticky), fallback choices, global variables and assignments, conditional choices, arithmetic and comparison operators, gather points, tunnels, Ink functions (detected and excluded from reachability when .ink source is provided via `--source`).

## Limitations

- **Positional resolution**: the compiled bytecode uses positional jumps within knots that have no names. In deeply nested stories, some of these map to the parent knot rather than the exact sub-node, which can break the edge chain for certain stitches.
- **No loop bound**: the Z3 model encodes one pass through each path; there is no configurable visit bound yet. Violations that require many loop iterations may be missed.
- **Not yet supported**: Ink threads (`<-`), lists (`LIST`), external functions, string operations, sequences/cycles.

## Installation

Requires Python 3.10+. Dependencies (z3-solver, pyyaml, click) install automatically.

```bash
pip install .
```

To compile `.ink` source files, install inklecate:

```bash
npm install -g inklecate
```

## Comparison with Story Solver

[Story Solver](https://yarnspinner.dev/storysolver/) by the Yarn Spinner team applies the same idea — formal verification of branching narratives — to the Yarn scripting language. This is the equivalent for Ink.

| Feature | No Dead Ends | Story Solver |
|---------|-------------|-------------|
| Narrative language | Ink | Yarn |
| Verification method | SMT solver (Z3) | Automated theorem provers |
| Reachability checks | Yes | Yes |
| Dead-end / soft-lock detection | Yes | Yes |
| Variable bound checking | Yes | Planned |
| Custom property assertions | Yes (YAML) | Unknown |
| Counterexample paths | Yes | Unknown |
| Save-file generation | No | Planned |
| Open source | Yes (MIT) | Unknown |
| Status | Prototype | Closed alpha (late 2026) |

## License

MIT. See [LICENSE](LICENSE).

All test stories are original. No third-party Ink stories or reference material are shipped.

Runtime dependencies (installed by pip, not bundled): z3-solver (MIT), pyyaml (MIT), click (BSD-3-Clause).
