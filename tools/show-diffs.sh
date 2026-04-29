#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 <name> [score]"
    exit 1
fi

# List all available scores
scores=$(ls -d nonmatchings/$1/output-*-*/ 2>/dev/null \
    | sed 's|.*/output-\([0-9]*\)-.*|\1|' \
    | sort -n \
    | uniq)

if [ -z "$scores" ]; then
    echo "No matching directories found for '$1'"
    exit 1
fi

echo "Available scores: $(echo $scores | tr '\n' ' ')"
echo ""

if [ -n "$2" ]; then
    lowest=$2
else
    lowest=$(echo "$scores" | head -1)
fi

for f in nonmatchings/$1/output-${lowest}-*/diff.diff; do
    echo "===== ${lowest}"
    cat "$f"
done
