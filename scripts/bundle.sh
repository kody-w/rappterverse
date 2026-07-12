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
    src/css/replay.css
    src/css/chronicle.css
    src/css/echo-dashboard.css
)

# JS bundle order (dependency order matters)
JS_FILES=(
    src/js/config.js
    src/js/state.js
    src/js/data.js
    src/js/chronicle.js
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
    src/js/vfx.js
    src/js/world-combat.js
    src/js/replay.js
    src/js/echo-events.js
    src/js/echo-dashboard.js
    src/js/world-agents.js
    src/js/debug.js
    src/js/inventory.js
    src/js/abilities.js
    src/js/enemy-hero.js
    src/js/world-core.js
    src/js/bridge.js
    src/js/hud.js
    src/js/voice-controls.js
    src/js/gesture-controls.js
    src/js/touch-controls.js
    src/js/help-overlay.js
    src/js/post-processing.js
    src/js/echo-engine.js
    src/js/gamepad-controls.js
    src/js/crafting.js
    src/js/jungle-camps.js
    src/js/shop.js
    src/js/fog-of-war.js
    src/js/rappter-os.js
    src/js/rappter-vm.js
    src/js/tutorial.js
    src/js/settings.js
    src/js/quests.js
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
    <meta name="description" content="A 3D autonomous AI metaverse running entirely on GitHub. 210 agents, 5 worlds, procedural terrain, Lisp VM, zero servers. Play in your browser.">
    <meta property="og:title" content="RAPPterverse — Autonomous AI Metaverse">
    <meta property="og:description" content="210 AI agents in a 3D world compiled from git commits. Procedural terrain, Lisp VM, voice controls, hand gestures. Zero servers. Play now.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="https://kody-w.github.io/rappterverse/">
    <meta property="og:image" content="https://raw.githubusercontent.com/kody-w/rappterverse/main/docs/og-image.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="RAPPterverse — Autonomous AI Metaverse">
    <meta name="twitter:description" content="210 AI agents. 5 worlds. Lisp VM. Zero servers. A 3D metaverse compiled from git commits.">
    <meta name="twitter:image" content="https://raw.githubusercontent.com/kody-w/rappterverse/main/docs/og-image.png">
    <meta name="theme-color" content="#0a0a1a">
    <link rel="manifest" href="manifest.json">
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🌌</text></svg>">
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
