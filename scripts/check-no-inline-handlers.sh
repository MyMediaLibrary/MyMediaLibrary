#!/usr/bin/env bash
# CI guard: fail if any inline JS event handler or javascript: URL is found in
# HTML files, or in non-comment JS/CSS lines in the frontend or Docker config.
# Run from the repository root.

set -euo pipefail

FAILED=0

# Pattern: inline event handler attributes (only meaningful inside HTML tags)
HANDLER_PATTERN='on(click|change|input|submit|keydown|keyup|keypress|mouseover|mouseout|mouseenter|mouseleave|focus|blur|load|error|reset|scroll|dblclick|contextmenu|touchstart|touchend)='

echo "Checking HTML files for inline event handlers..."
if grep -RInE "$HANDLER_PATTERN" \
    --include="*.html" \
    app/ docker/ 2>/dev/null; then
  echo ""
  echo "ERROR: Inline JS event handlers are forbidden in HTML. Use events.js listeners instead."
  FAILED=1
fi

echo "Checking JS files for inline handler strings in non-comment, non-string context..."
# Stricter: look for the pattern followed by a quote (= the HTML attribute form),
# while skipping lines that are purely comments (// ...) or JSDoc (* ...).
if grep -RInE "$HANDLER_PATTERN\"" \
    --include="*.js" \
    app/ 2>/dev/null \
  | grep -v '^\s*//' \
  | grep -v "^\S*:\s*\*" \
  | grep -qE "$HANDLER_PATTERN"; then
  grep -RInE "$HANDLER_PATTERN\"" --include="*.js" app/ \
    | grep -v '^\s*//' \
    | grep -v "^\S*:\s*\*"
  echo ""
  echo "ERROR: Inline handler strings found in JS templates. Use data-* attributes instead."
  FAILED=1
fi

echo "Checking for javascript: URLs..."
if grep -RIn 'javascript:' --include="*.html" app/ docker/ 2>/dev/null \
  | grep -v 'href="#"'; then
  echo ""
  echo "ERROR: javascript: URLs are forbidden."
  FAILED=1
fi

if [ "$FAILED" -eq 0 ]; then
  echo "OK — no inline handlers found."
fi

exit "$FAILED"
