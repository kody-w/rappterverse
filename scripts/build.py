#!/usr/bin/env python3
"""
RAPPterverse Build Script
Compiles src/ modules into docs/index.html
Usage: python3 scripts/build.py
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
OUT = os.path.join(ROOT, 'docs', 'index.html')

# Order matters — dependencies first
CSS_FILES = [
    'css/tokens.css',
    'css/boot.css',
    'css/galaxy.css',
    'css/approach.css',
    'css/landing.css',
    'css/world.css',
    'css/bridge.css',
    'css/hud.css',
]

JS_FILES = [
    'js/config.js',
    'js/state.js',
    'js/data.js',
    'js/boot.js',
    'js/galaxy.js',
    'js/approach.js',
    'js/landing.js',
    'js/world-terrain.js',
    'js/world-lanes.js',
    'js/world-combat.js',
    'js/world-agents.js',
    'js/world-core.js',
    'js/bridge.js',
    'js/hud.js',
    'js/main.js',
]

def read_file(path):
    with open(os.path.join(SRC, path), 'r') as f:
        return f.read()

def build():
    css = '\n'.join(f'/* === {f} === */\n{read_file(f)}' for f in CSS_FILES)
    js = '\n'.join(f'// === {f} ===\n{read_file(f)}' for f in JS_FILES)
    html_body = read_file('html/layout.html')

    output = f'''<!DOCTYPE html>
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
{css}
    </style>
</head>
<body>
{html_body}
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <script>
{js}
    </script>
</body>
</html>'''

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        f.write(output)
    
    lines = output.count('\n') + 1
    print(f'✅ Built docs/index.html ({lines} lines, {len(output)} bytes)')

if __name__ == '__main__':
    build()
