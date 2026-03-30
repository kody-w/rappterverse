# Shift Passoff — 2026-03-29

## Status: V1 FEATURE FREEZE

No new features. Only bug fixes, performance optimization, and polish.

---

## What Happened This Session

18 commits across one long session. Two phases:

### Phase 1: Echo Engine Megabuild (14 commits)
Built three new systems and wired the Echo Engine into every corner of the frontend:

**New Files Created (6):**
| File | Lines | Purpose |
|------|-------|---------|
| `src/js/vfx.js` | 475 | GPU particle system — 20 presets, pooled, 3 emission modes (burst/emit/trail) |
| `src/js/replay.js` | 802 | Cinematic battle replay — 5 camera modes, slow-mo kills, VHS overlay, echo-aware |
| `src/js/echo-events.js` | 182 | Procedural world events triggered by echo thresholds (5 event types) |
| `src/js/echo-dashboard.js` | 147 | Full echo engine readout overlay (~ key) |
| `src/css/replay.css` | 211 | Replay overlay styling |
| `src/css/echo-dashboard.css` | 130 | Dashboard overlay styling |

**Systems Modified (25+):**
Every major system now reacts to the Echo Engine's L3 atmosphere data (tension, vitality, socialEnergy):

| System | File | What Echo Does |
|--------|------|---------------|
| Post-processing | `post-processing.js` | Bloom 0.3-0.9, vignette tightens with tension |
| Audio music | `audio.js` | LFO tremolo 1-4x speed, gain modulated |
| Audio ambient | `audio.js` | Chirp/crackle intervals speed up 50% |
| Enemy Hero AI | `enemy-hero.js` | Engages from further, braver retreat, faster movement |
| Terrain/sky | `world-terrain.js` | Sky red-shifts, weather intensifies, day/night cycle (8 min) |
| Tower/throne | `world-lanes.js` | Orb pulse 3-7Hz, crystal/crown speed, river tints red |
| Galaxy | `galaxy.js` | Star throbs harder, planets breathe |
| Fog of war | `fog-of-war.js` | Denser + redder fog, vision radius shrinks |
| Agent behavior | `world-agents.js` | Glow scales, wander radius contracts, social bias increases |
| Agent speech | `world-agents.js` | Echo-contextual ambient chatter every 12-32s |
| VFX particles | `vfx.js` | 3 ambient echo presets, burst count/size +60% |
| Replay camera | `replay.js` | Tighter shots, faster cuts, atmosphere overlay + narrative |
| Shop prices | `shop.js` | +25% war tax during tension, -15% social discount |
| Crafting | `crafting.js` | 3 echo-only recipes (Echo Blade, Harmony Shield, Vitality Core) |
| Jungle camps | `jungle-camps.js` | Glow intensity, +30% gold/xp during tension, Echo Titan boss |
| Abilities | `abilities.js` | +20% damage during tension, Echo Storm 1.5x, shield bubble mesh |
| Combat difficulty | `world-combat.js` | Creep HP +15%, speed +20% during tension |
| Projectiles | `world-combat.js` | VFX trails, tension-scaled size |
| Camera | `world-core.js` | Micro-shake during tension, scroll wheel zoom (0.4x-2.5x) |
| Player ring | `world-core.js` | Pulse speed/color echo-reactive |
| Minimap | `hud.js` | Heat map, tension pulse ring, mood-colored agent dots, ping system |
| HUD | `hud.js` | Tension sparkline in universe card, echo event display |
| Death/victory | `player-stats.js`, `world-combat.js` | Echo narrative, echo score grading (S+ through D) |
| Quests | `quests.js` | Echo-generated quest hints when no quests active |
| Gamepad | `gamepad-controls.js` | Echo rumble during tension, kill haptics |
| Tutorial | `tutorial.js` | New step explaining Echo Engine |
| Settings | `settings.js` | Echo effects toggle |
| Bridge | `bridge.js` | Combat digest, active echo event display |
| Approach | `approach.js` | Echo narrative on planet approach |

**Key Gameplay Additions:**
- **Battle Replay** (R key): records combat, plays back with cinematic camera, slow-mo on kills
- **Echo Titan**: Roshan-style 500HP river boss, spawns at wave 3, 200 gold + 150 XP
- **Kill Streaks**: KILLING SPREE (3) through BEYOND GODLIKE (20) with escalating VFX
- **Last-Hit Gold**: bonus gold for killing blows
- **Minimap Pings**: click minimap to place 3D gold beam + minimap marker
- **Wave Cinematics**: letterbox overlay on milestone waves
- **Combo VFX**: escalating particle effects at 3/5/10 kill combos
- **Echo Events**: 5 procedural world events (Battle Fury, Social Bloom, Vitality Surge, Echo Storm, Calm Before Storm)
- **Echo Score**: end-of-match grade based on session dynamics
- **Session Memory**: echo summaries persist to localStorage across sessions

### Phase 2: Stabilization (4 commits)
Comprehensive audit and fix pass:

- **9 bug fixes**: memory leaks (replay cleanup, setInterval), stale state (XP bonus persisting through death), shader overflow (bloom/vignette unbounded), resource leaks (shield bubble), pool corruption (VFX reusing alive particles), terrain amplitude growing forever
- **8 perf fixes**: O(n^2) retroEnrich -> O(n), localStorage throttled to 10s, ghost lerp skipped when paused, echo intensity cached 500ms, nova shake timer reused, audio resume {once:true}, creep/projectile cleanup uses reverse splice instead of filter()
- **15 UX fixes**: transitions on all buttons (HUD, approach, landing, ability slots, echo dashboard), hover states, z-index cleanup (death overlay raised, victory lowered), camera lerp 0.05->0.1, toast stacking capped at 5, interaction prompt smooth fade
- **6 final fixes**: echo event buff stacking guard, streak banner DOM reuse, wave/boss overlay timeout cleanup, death timer throttled to 1/sec, CSS token consistency

---

## Architecture: The Echo Feedback Loop

```
Combat (kills, momentum, boss, waves, player HP)
    |
    v
Echo Engine L0-L6 (captures frame, builds echoes)
    |
    +---> L1: Social + combat digest
    +---> L2: Narrative text
    +---> L3: Atmosphere (tension, vitality, socialEnergy)
    +---> L4: Spatial mutations (fog, terrain amplitude)
    +---> L6: Temporal depth (trends, mood stability)
    |
    v
38 reactive systems consume L3
    |
    +---> Visuals darken, bloom increases, fog thickens
    +---> Music intensifies, chirps speed up
    +---> AI gets bolder, creeps move faster
    +---> Particles multiply, trails appear
    +---> Agents huddle, chatter changes
    +---> Shop prices rise, crafting recipes unlock
    |
    v
More intense combat --> loops back to Echo Engine
```

---

## Known Issues / Tech Debt

1. **Agent canvas textures**: each agent creates its own canvas for emoji + name sprite. 100 agents = 100 canvases. Should use texture atlas.
2. **Minimap heat map**: `createRadialGradient()` called per-creep per-frame. Could pre-compute or batch.
3. **Echo dashboard innerHTML**: replaces entire body on every render. Should diff-update.
4. **Echo engine localStorage**: still writes full frame history (throttled to 10s now, but could compress).
5. **Three.js r128**: using CDN-loaded r128. Modern features (instanced mesh for particles, etc.) not available.

---

## Build / Test

```bash
# After ANY edit to src/css/, src/js/, or src/html/:
bash scripts/bundle.sh

# Syntax check:
node -e "
const fs = require('fs');
const html = fs.readFileSync('docs/index.html','utf8');
const js = html.match(/<script>[\s\S]*<\/script>/)[0].replace(/<\/?script>/g,'');
try { new Function(js); console.log('OK'); }
catch(e) { console.log('ERROR:', e.message); }
"

# Bundle is currently: 13 CSS + 44 JS -> 19,301 lines
```

---

## Key Files to Know

| File | What it does | Watch out for |
|------|-------------|---------------|
| `src/js/echo-engine.js` | Heart of the system. Captures frames, builds L0-L6 echoes | Tension can come from many sources now (combat, economy, mood). Check Math.min(1, tension) is preserved. |
| `src/js/vfx.js` | Particle pools. 300 per preset max. | Pool exhaustion silently reuses oldest. If you see particle glitches, check pool sizes. |
| `src/js/replay.js` | Records snapshots every 1s + events. | _shakeInterval must be cleared. Check cleanup() if adding new timers. |
| `src/js/echo-events.js` | 5 event types with buff/debuff. | Buff stacking guard relies on _orig* fields. Don't delete them outside onEnd(). |
| `src/js/world-combat.js` | Creep spawning, combat, victory. | _overlayTimeouts array must be cleared in cleanup(). Wave cinematic + boss intro both use it. |
| `scripts/bundle.sh` | Concatenates everything. Order matters. | New JS files go between their dependencies. CSS order less critical but check. |

---

## Feature Freeze Rules

- NO new features
- Bug fixes: yes
- Performance: yes
- Polish (visual tweaks, timing): yes
- Test coverage: yes
- Doc updates: yes
