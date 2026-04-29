#!/usr/bin/env bash
PERM="../decomp-permuter"

if [ $# -eq 1 ]; then
    FUNC="$1"
    FILE=$(grep -rl "^[a-zA-Z_].*\b$FUNC\b\s*(" src/melee/ --include='*.c' | head -1)
    if [ -z "$FILE" ]; then
        echo "Could not find function '$FUNC' in src/melee/"
        exit 1
    fi
else
    FILE="$1"
    FUNC="$2"
    [[ $FILE != *.c ]] && FILE="${FILE}.c"
    [[ $FILE != src/* ]] && FILE="src/melee/$FILE"
fi

rm -rf "nonmatchings/$FUNC/"
python "$PERM/import.py" "$FILE" --func="$FUNC"
python "$PERM/permuter.py" "nonmatchings/$FUNC/" -j64
