#!/usr/bin/env bash
# bundle.sh — Bundles src/ into docs/index.html for GitHub Pages deployment.
#
# The RAPPterverse frontend is a single-file app: all CSS and JS from src/
# are inlined into docs/index.html. GitHub Pages serves from docs/.
#
# Usage:
#   ./scripts/bundle.sh          # rebuild docs/index.html from src/
#
# IMPORTANT: Always run this after editing any file in src/css/, src/js/,
# or src/html/ before committing, or your changes won't appear on the live site.

set -euo pipefail
cd "$(dirname "$0")/.."

OUTPUT="docs/index.html"

# CSS bundle order
CSS_FILES=(
    src/css/tokens.css
    src/css/boot.css
    src/css/galaxy.css
    src/css/warp.css
    src/css/approach.css
    src/css/landing.css
    src/css/world.css
    src/css/bridge.css
    src/css/hud.css
    src/css/stats.css
    src/css/equipment.css
)

# JS bundle order (dependency order matters)
JS_FILES=(
    src/js/config.js
    src/js/state.js
    src/js/data.js
    src/js/audio.js
    src/js/player-stats.js
    src/js/status-effects.js
    src/js/equipment.js
    src/js/boot.js
    src/js/galaxy.js
    src/js/warp.js
    src/js/approach.js
    src/js/landing.js
    src/js/world-terrain.js
    src/js/world-lanes.js
    src/js/world-combat.js
    src/js/world-agents.js
    src/js/inventory.js
    src/js/abilities.js
    src/js/enemy-hero.js
    src/js/world-core.js
    src/js/bridge.js
    src/js/hud.js
    src/js/main.js
)

# Assemble the bundle
{
    # HTML head + open style tag
    cat <<'HEADER'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="RAPPterverse">
    <title>RAPPterverse — Autonomous AI Metaverse</title>
    <style>
HEADER

    # Inline all CSS
    for f in "${CSS_FILES[@]}"; do
        echo "/* === ${f#src/} === */"
        cat "$f"
        echo ""
    done

    # Close style, open body
    cat <<'MID'
    </style>
</head>
<body>
MID

    # Inline HTML layout
    cat src/html/layout.html

    # Three.js CDN + open script tag
    cat <<'SCRIPT'

    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script>
SCRIPT

    # Inline all JS
    for f in "${JS_FILES[@]}"; do
        echo "// === ${f#src/} ==="
        cat "$f"
        echo ""
    done

    # Close script, body, html
    cat <<'FOOTER'
    </script>
</body>
</html>
FOOTER

} > "$OUTPUT"

LINES=$(wc -l < "$OUTPUT")
echo "✅ Bundled ${#CSS_FILES[@]} CSS + ${#JS_FILES[@]} JS → $OUTPUT ($LINES lines)"
