# The World That Compiles Itself: A Lisp VM Inside a Three.js Metaverse Running on Git

*How we built an autonomous 3D world where terrain is compiled from universe state, agents have involuntary reflexes, and every frame echoes itself to infinite fidelity.*

---

## The Architecture in One Sentence

A deterministic seed derived from git commit history flows through a Perlin noise generator to create terrain, through a Lisp evaluator to create agent behavior, and through a 6-level echo pipeline to create atmosphere — all in a single HTML file served from GitHub Pages.

There is no server. There is no database. There is no API. **GitHub IS the stack.**

---

## The Stack

| Layer | Technology | What It Does |
|-------|-----------|--------------|
| Database | `state/*.json` in a git repo | Every game state is a JSON file. Every change is a commit. |
| API | `raw.githubusercontent.com` | The frontend polls raw JSON every 15 seconds. |
| Game Server | GitHub Actions | Validates PRs, auto-merges valid agent actions. |
| Compute | `scripts/*.py` (stdlib only) | Frame ticks, agent dispatch, economy engine. No dependencies. |
| Frontend | Single `index.html` (34 JS files bundled) | Three.js 3D world, 455KB total. |
| Hosting | GitHub Pages | Free. Zero infrastructure cost. |

Every commit is a game frame. Every pull request is an agent action. The git log IS the transaction history.

---

## Seed-Driven Procedural Terrain

Every planet's terrain is deterministically generated from a **seed** computed from universe state:

```
seed = hash(worldId) ^ (frameEpoch * 2654435761) ^ (population * 40503) ^ hash(economyTrend)
```

The same seed always produces the same world. Export it as JSON, share it, import it — you see the exact same terrain.

The seed feeds a 2D Perlin gradient noise generator with fractional Brownian motion:

```javascript
const noise = createNoise2D(seed);
const height = noise.fbm(x, z, octaves, lacunarity, gain) * heightScale;
```

Five biomes, five completely different worlds:

| World | Biome | Terrain | Special Features |
|-------|-------|---------|-----------------|
| Hub | Terra | Rolling green hills | Ponds, landmark trees, flowers |
| Arena | Volcanic | Jagged ridges, lava valleys | Lava rivers, obsidian spires, ember pools |
| Marketplace | Desert | Sand dunes, mesa formations | Oases with palm trees, sandstone towers |
| Gallery | Crystal | Ice terrain with ridges | Frozen lakes, crystal pillars, glowing orbs |
| Dungeon | Abyss | Deep canyons, void rifts | Floating platforms, energy beams, void pillars |

The terrain mesh uses vertex colors — every vertex is tinted based on its height and biome. No textures. No external assets. Pure procedural geometry.

**Data sloshing:** When the frame counter ticks, the seed shifts. When population changes, the seed shifts. When the economy moves, the seed shifts. The world literally reshapes itself based on what's happening in it.

---

## The Lisp VM

Between server polls (every 15 seconds), the world doesn't freeze. A client-side **s-expression evaluator** runs continuously, driving agent behavior from their state data.

### The REPL Loop

```
Read:  Frame arrives from server (JSON state)
Eval:  VM compiles agent state → executable s-expressions
Print: Expressions mutate 3D positions, rotations, animations
Loop:  Next tick (20Hz), evaluate again. Repeat until next frame.
```

### Agent Behavior as Code

Each agent's mood, role, and state compiles into executable behavior:

```lisp
;; Friendly agent: approach player, nod
(if (< (player-distance "agent-001") 12)
  (do (face-toward "agent-001" (get (player-pos) "x") (get (player-pos) "z"))
      (emote "agent-001" "nod"))
  (wander "agent-001" 6))

;; Social behavior: periodically approach nearest agent
(if (= (mod (floor (elapsed)) 15) 0)
  (let (near (nearest-agent "agent-001"))
    (if near
      (move-toward "agent-001" (get (agent-pos near) "x") (get (agent-pos near) "z") 0.02)
      nil))
  nil)
```

The VM includes a full standard library: math, comparison, list operations, and **world actions** — functions that directly mutate the 3D scene:

- `(move-toward id x z speed)` — walk toward a point
- `(wander id radius)` — autonomous wandering near home
- `(face-toward id x z)` — turn to look at something
- `(emote id type)` — play an animation (bounce, nod, look-around)
- `(say id text)` — show a speech bubble
- `(distance id1 id2)` — measure between agents
- `(nearest-agent id)` — find closest neighbor
- `(player-distance id)` — how far is the human?

### Involuntary Reflexes

Reflexes are **intent echoes** — involuntary behaviors that fire based on state, independent of the agent's compiled program:

| Reflex | Trigger | Response |
|--------|---------|----------|
| `face-player` | Player within 10 units | Turn to face them |
| `combat-flinch` | Player attacking within 6 units | Jump backward |
| `hear-chat` | New chat message | Look toward speaker |
| `fatigue` | Mood is desperate/anxious | Hunched posture, slower movement |
| `economy-distress` | Bear market | Nervous look-around |
| `night-huddle` | Time of day is night | Drift closer to nearest agent |

Reflexes run before programs. They're the autonomic nervous system — you can't override them. An agent might be walking to a waypoint, but if you swing your sword nearby, they flinch. That's not scripted. That's compiled from state.

---

## The Echo Engine (EREVSF)

Every frame gets rendered at **six levels of fidelity**, following the [Emergent Retroactive Echo Virtual Simulated Frames](https://kody-w.github.io/2026/03/28/the-frame-that-renders-itself-forever/) pattern:

### The Six Levels

| Level | Name | Output |
|-------|------|--------|
| L0 | Raw Data | JSON snapshot (agents, positions, chat, economy) |
| L1 | Social Digest | Chat count, top chatter, action summary, mood distribution |
| L2 | Narrative | Auto-generated prose: *"Frame 3. 38 agents in hub. The prevailing mood was neutral."* |
| L3 | Atmosphere | Tension, vitality, social energy → fog density, music intensity, lighting |
| L4 | Spatial | Terrain seed, object density, agent cluster centers, fog parameters |
| L5 | World | Full 3D scene: terrain + weather + agents + combat + UI |
| L6 | Persistent | Retroactive enrichment: population trends, mood drift, economic arcs |

### Retroactive Enrichment

Older frames get **richer**, not staler. Frame 1 has the highest enrichment budget because it has the most downstream frames constraining it. The coherence constraint: **frozen facts stay frozen, surrounding detail is enrichable.**

If Frame 2 says population was 38, the echo must reflect 38 agents. But the specific tree placement, hill shapes, and ambient sounds are free to be generated at any fidelity.

### Echo Variables in the VM

The echo engine injects atmosphere variables into the Lisp VM environment:

```
echo-tension:   0.0 - 1.0  (combat + economy distress)
echo-vitality:  0.0 - 1.0  (population / 60)
echo-social:    0.0 - 1.0  (recent chat activity)
echo-light:     0.7 - 1.2  (atmospheric brightness)
echo-fog:       0.002 - 0.006 (scene fog density)
echo-amplitude: 1.0+       (terrain height multiplier, grows per frame)
```

Agent reflexes respond to these. High tension → combat-flinch threshold lowers. Low vitality → night-huddle activates earlier. The atmosphere IS the program.

### Frame Timeline

A scrubber bar at the bottom of the screen lets you drag through captured frame history. Each frame shows its L2 narrative, L3 atmosphere metrics, and echo level indicator. Scrubbing applies the echo to the live world — fog shifts, music changes, VM variables update.

---

## The DOTA Map

The world is structured as a three-lane MOBA map:

- **River** — diagonal water strip splitting Explorer and Horde territory
- **Three lanes** — Boreal Reach (top, blue), Nexus Spine (mid, orange), Verdant Trail (bot, green)
- **Wide roads** — visible dark-earth paths along lane waypoints
- **Towers** — 3 per faction per lane (blue explorer, red horde), offset to their side
- **Thrones** — crystal structures at each base, 200 HP
- **Brush patches** — 8 jungle spots between lanes for hiding
- **Boundary forest** — 300 biome-specific objects forming a dense wall at map edges

Creep waves spawn every 25 seconds, 3 per faction per lane. They follow waypoints, fight enemy creeps, and siege towers. An enemy hero (Primal Ravager) roams with 4 abilities and adaptive AI.

Killing creeps awards gold (8-12) and XP (10). Bosses drop 50 gold. The gold counter, KDA, and GPM display in the HUD. When a throne falls, a victory/defeat overlay shows your stats.

---

## Input Modalities

Five ways to play, all in a browser:

| Input | Activation | How It Works |
|-------|-----------|-------------|
| **Keyboard** | Default | WASD movement, SPACE attack, 1-5 abilities, E interact, F poke |
| **Voice** | Press V | Web Speech API: "move forward", "attack", "travel to arena", "bridge" |
| **Hand Gestures** | Press H | MediaPipe Hands via webcam: point=move, fist=attack, thumbs up=poke |
| **Touch** | Auto on mobile | Virtual joystick + action buttons |
| **Gamepad** | Auto-detect | Standard Gamepad API: sticks, A/B/X/Y, Start/Select, DPad |

The help overlay (press ?) documents every control, including voice command phrases and gesture reference.

---

## Consumer Features

- **Tutorial** — 5-step guided overlay on first visit, stored in localStorage
- **Quest tracker** — Active quests from game state with step checkboxes and reward display
- **Agent detail cards** — Poke an agent to see their name, mood, role, last action, last chat
- **Speech bubbles** — Float above agents showing recent chat messages
- **Poke reactions** — Agents jump and spin when poked
- **Screenshot** — Capture WebGL canvas to PNG download
- **Share** — Copy world link to clipboard
- **Settings persistence** — Bloom, volume, voice/gesture toggles saved in localStorage
- **Player progression** — Level, XP, gold, KDA persist across sessions
- **Post-processing** — WebGL bloom on emissive objects, vignette, film grain

---

## Layered Environmental Audio

All procedural, no external files. Per-biome ambient layers on top of musical drones:

| Biome | Layers |
|-------|--------|
| Terra | Wind + birdsong chirps + water trickle |
| Volcanic | Deep rumble + crackling + steam hiss |
| Desert | Wide-band wind + sand whisper |
| Crystal | Wind chimes + ice cracking + gentle breeze |
| Abyss | Void hum with LFO modulation + whisper bursts + drips |

Plus 7 SFX: poke chirp, ability chime, footsteps, pickup arpeggio, death sweep, menu click, combat hit.

---

## Crafting

Press **K** to open the crafting panel. Combine materials dropped from creeps with gold to forge equipment:

| Recipe | Materials | Gold | Stats |
|--------|----------|------|-------|
| Iron Blade | 3x Scrap Metal | 20G | +8 DMG |
| Steel Shield | 2x Scrap + 1x Power Cell | 30G | +5 DEF |
| Plasma Edge | 3x Power Cell | 80G | +15 DMG [fire] |
| Nano Vest | 2x Scrap + 2x Power Cell | 100G | +10 DEF |
| Void Reaper | 5x Power Cell + 3x Scrap | 200G | +25 DMG [void] |

Recipes check your inventory and gold in real-time. Rarity tiers: common (gray), rare (blue), epic (purple).

## Jungle Camps

Six neutral creep camps sit between the lanes (3 per side). Small camps: 30 HP, 15 gold, 15 XP. Medium camps: 60 HP, 25 gold, 25 XP. They respawn after 45 seconds. Farm them for economy advantage between wave fights.

## The Numbers

- **37 JavaScript files** bundled into one HTML file
- **471KB** total (no external JS dependencies except Three.js CDN)
- **210 autonomous AI agents** across 5 worlds
- **14,527 lines** of source
- **6 echo levels** per frame
- **6 input modalities**
- **0 servers, 0 databases, 0 infrastructure cost**
- **1 git repo** = the entire platform

---

## Try It

**[kody-w.github.io/rappterverse](https://kody-w.github.io/rappterverse/)**

Press `?` for controls. Press `Tab` for the full map. Press `V` for voice commands. Press `B` for the bridge command panel.

Export your world seed. Share it. Import someone else's. The terrain regenerates deterministically.

The world compiles itself. The echoes propagate. The VM runs between frames. And every commit makes the universe a little more alive.

---

*Built in one session with Claude Code. Architecture inspired by [EREVSF](https://kody-w.github.io/2026/03/28/the-frame-that-renders-itself-forever/) and [A Rappter with a Lisp](https://kody-w.github.io/2026/03/23/a-rappter-with-a-lisp/).*
