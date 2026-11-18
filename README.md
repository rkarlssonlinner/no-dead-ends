# ink-verify

Formal verification for Ink interactive fiction. Proves properties across all possible playthroughs using the Z3 SMT solver.

ink-verify works on the compiled Ink JSON that every Ink tool produces — the format is the same regardless of editor or compiler. It can also compile raw `.ink` for you, and extract stories from package files.

Supported inputs by feature:

- **Compiled JSON** (direct, no extra tools needed): output from inklecate, Inky, inkjs, ink-unity-integration, or any tool that compiles `.ink` to `.json`
- **Package files** (extracted automatically): Offtrail Tales `.tale`, Offtrail Tales `.otproject`
- **Raw `.ink` source** (compiled automatically, requires inklecate on PATH): single files or directories

## Quick start

```bash
pip install .
ink-verify my-story.tale --source story/
```

Supply both compiled Ink and .ink source for best accuracy. The source corrects variable types that the compiled bytecode loses.

## Reproduce the test results

```bash
git clone https://github.com/rkarlssonlinner/no-dead-ends
cd no-dead-ends
pip install .
bash scripts/verify_examples.sh
```

Results are written to `results/`. The committed results match what the script produces.

The `.tale` is the same package your editor builds when you save or publish — `story/main.ink.json` inside the ZIP. No extra compile step.

## Workflow

```
1. Write your story in an editor
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

When `.ink` source is available (via `--source` or auto-detected next to the JSON), ink-verify corrects variable types from the source declarations, checks only author-written knots (compiler-generated gathers and choice internals are skipped), and shows file:line locations in failure output. Without source, all top-level knots are checked and variable types are inferred from the compiled bytecode.

When a check fails, ink-verify names the problem. Use `--verbose` to see the full path:

```
ink-verify — story.ink.json (5 knots, 2 variables)

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
  "has_source": false,
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

## Tested on The Intercept

ink-verify has been tested on [The Intercept](https://github.com/inkle/the-intercept) by inkle — their open-source demo story (MIT), compiled with the original C# inklecate (inkVersion 11). Results:

- 100% edge coverage (858 edges resolved, 0 dropped)
- 30 of 32 top-level knots confirmed reachable (the 2 "unreachable" are Ink helper functions, not story content)
- 21 variables detected and checked
- Entry point correctly identified through conditional branching in the initial content

When ink-verify can't fully resolve an internal path (e.g., positional jumps within a knot), it reports a **coverage metric** so you know how much of the story was analyzed:

```
ink-verify — TheIntercept.json (282 knots, 21 variables)
  coverage: 97% of edges resolved (12 unresolved — results may be incomplete)
```

The coverage line appears only when edges are unresolved. When all edges resolve, it is omitted and results cover the full graph. The results are still valid for the parts that were analyzed — a FAIL is a real problem, a PASS holds for the resolved graph.

## Real-world example

Running ink-verify on a 40-knot Offtrail Tales story with 9 variables:

```
ink-verify my-story.tale

ink-verify — my-story.tale (40 knots, 9 variables)

  [PASS] radio reachable
  [PASS] flat reachable
  [PASS] signup reachable
  ...
  [PASS] no dead ends
  [FAIL] told_noor >= 0
         Invariant 'told_noor >= 0' violated
  [FAIL] hearing >= 0
         Invariant 'hearing >= 0' violated

38 passed, 5 failed
```

**What it caught:** two variables that go negative on some playthrough. These could be real bugs (an off-by-one in a counter) or intentional design (using -1 as a flag). Either way, the author now knows and can check.

**What it flagged but isn't a real problem:** three internal choice containers (`leak.c-0.b`, `act3.c-0.b`) reported as unreachable. These are parser artifacts from how Ink compiles choice content — not actual dead content. When you see `c-0`, `c-1` in a node name, it's a choice container internals, not a knot you wrote.

**How to read the output:**

- **PASS** — Z3 proved this holds across all possible playthroughs. No exceptions.
- **FAIL with "no incoming edges"** — provably unreachable. Nothing connects to it. If it's a `c-*` node, ignore it. If it's a knot you wrote, it's orphaned content.
- **FAIL with "has N incoming edges but no verified path"** — edges exist but the solver can't trace a full path. Usually a parser limitation with deeply nested compiled JSON, not a real problem. Check it yourself.
- **FAIL on an invariant** — a specific playthrough violates the condition. Use `--verbose` to see the path and variable values that cause it.

## Supported Ink features

Knots, stitches, diverts, choices (once-only and sticky), fallback choices, global variables and assignments, conditional choices, arithmetic and comparison operators, gather points, tunnels, Ink functions (detected and excluded from reachability when .ink source is provided via `--source`).

## Limitations

- **Compiled JSON only**: works on the bytecode that inklecate/inkjs/Inky produce, not on `.ink` source directly (though it can call inklecate for you). Intra-knot positional jumps in deeply nested stories may map to the parent knot rather than the exact sub-node.
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

MIT
