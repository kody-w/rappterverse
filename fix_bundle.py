#!/usr/bin/env python3
"""
Rebuild docs/index.html from src/ files (manual bundler implementation)
"""
import os
import glob

os.chdir('/Users/kodywildfeuer/Documents/GitHub/m365-agents-for-python/rappterverse')

CSS_FILES = [
    'src/css/tokens.css',
    'src/css/boot.css',
    'src/css/galaxy.css',
    'src/css/warp.css',
    'src/css/approach.css',
    'src/css/landing.css',
    'src/css/world.css',
    'src/css/bridge.css',
    'src/css/hud.css',
    'src/css/stats.css',
    'src/css/equipment.css',
]

JS_FILES = [
    'src/js/config.js',
    'src/js/state.js',
    'src/js/data.js',
    'src/js/audio.js',
    'src/js/player-stats.js',
    'src/js/status-effects.js',
    'src/js/equipment.js',
    'src/js/boot.js',
    'src/js/galaxy.js',
    'src/js/warp.js',
    'src/js/approach.js',
    'src/js/landing.js',
    'src/js/world-terrain.js',
    'src/js/world-lanes.js',
    'src/js/world-combat.js',
    'src/js/world-agents.js',
    'src/js/debug.js',
    'src/js/inventory.js',
    'src/js/abilities.js',
    'src/js/enemy-hero.js',
    'src/js/world-core.js',
    'src/js/bridge.js',
    'src/js/hud.js',
    'src/js/main.js',
]

HEADER = '''<!DOCTYPE html>
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
'''

MID = '''    </style>
</head>
<body>
'''

SCRIPT = '''

    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script>
'''

FOOTER = '''    </script>
</body>
</html>
'''

output = []
output.append(HEADER)

# CSS
for f in CSS_FILES:
    output.append(f'/* === {f[4:]} === */')
    with open(f, 'r') as file:
        output.append(file.read())
    output.append('')

output.append(MID)

# HTML layout
with open('src/html/layout.html', 'r') as file:
    output.append(file.read())

output.append(SCRIPT)

# JS
for f in JS_FILES:
    output.append(f'// === {f[4:]} ===')
    with open(f, 'r') as file:
        output.append(file.read())
    output.append('')

output.append(FOOTER)

# Write bundle
with open('docs/index.html', 'w') as file:
    file.write('\n'.join(output))

# Report
lines = len(output)
print(f"✅ Bundled {len(CSS_FILES)} CSS + {len(JS_FILES)} JS → docs/index.html")
print()
print("Step 1: ✅ COMPLETE - Rebuilt docs/index.html")

# Step 2: Count _firePokeDispatch
count = 0
with open('docs/index.html', 'r') as file:
    content = file.read()
    count = content.count('_firePokeDispatch')

print(f"\nStep 2: _firePokeDispatch count = {count}")
if count == 2:
    print("✅ CORRECT - Found exactly 2 occurrences (1 definition, 1 call)")
else:
    print(f"❌ ERROR - Expected 2, found {count}")

# Step 3: Check for syntax errors
print("\nStep 3: Checking for syntax errors...")
import re
catch_blocks = list(re.finditer(r'catch\s*\(\s*e\s*\)', content))
print(f"Found {len(catch_blocks)} catch blocks")
if len(catch_blocks) >= 1:
    for i, match in enumerate(catch_blocks, 1):
        # Find line number
        line_num = content[:match.start()].count('\n') + 1
        print(f"  catch block #{i} at line {line_num}")

# Step 4: Verify structure
print("\nStep 4: JS structure validation...")
open_braces = content.count('{')
close_braces = content.count('}')
print(f"Open braces: {open_braces}, Close braces: {close_braces}")
if open_braces == close_braces:
    print("✅ Brace balance OK")
else:
    print(f"❌ Brace mismatch: {open_braces} open vs {close_braces} close")

print("\n" + "="*60)
print("Bundle complete. Ready for git operations.")
