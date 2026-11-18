#!/usr/bin/env bash
# Runs ink-verify on all example stories and writes results to results/.
# Reproduces the numbers cited in the README and community post.
set -euo pipefail
cd "$(dirname "$0")/.."

RESULTS=results
mkdir -p "$RESULTS"

echo "Running verification on test stories..."

# Test suite stories (compiled JSON, source alongside)
for story in tests/stories/*.ink.json; do
    name=$(basename "$story" .ink.json)
    ink-verify "$story" --source tests/stories/ --json \
        > "$RESULTS/${name}.json" 2>/dev/null || true
    ink-verify "$story" --source tests/stories/ \
        > "$RESULTS/${name}.txt" 2>/dev/null || true
    echo "  $name: done"
done

# Summary
echo ""
echo "=== Summary ==="
for f in "$RESULTS"/*.txt; do
    name=$(basename "$f" .txt)
    tail -1 "$f" | sed "s/^/  $name: /"
done

echo ""
echo "Results written to $RESULTS/"
echo "Produced by: scripts/verify_examples.sh"
