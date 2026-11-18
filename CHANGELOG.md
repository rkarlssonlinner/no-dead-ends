# Changelog

## 2026-11-18

README audit against source code. Fixed 10 inaccuracies:
- Removed `--bound` from Options (no-op: `z3_encoder.encode()` accepts but ignores the parameter)
- Added `-s, --source` flag to Options table (was entirely undocumented)
- Fixed example output: counterexample paths require `--verbose`, split into two blocks
- Added `has_source`, `coverage`, `edges_resolved`, `edges_dropped` to JSON output example
- Fixed coverage example (100%/0 case never prints; changed to 97%/12)
- Removed false claim "Stories with cycles are detected and reported"
- Fixed "unresolved edges listed as warnings" to "coverage line appears only when edges are unresolved"
- Updated failure message phrasing to match actual code output
- Added short flags `-s`, `-p`, `-v` to Options table
- Added paragraph about `--source` behavior and Ink function exclusion qualifier

Files changed: `README.md`
