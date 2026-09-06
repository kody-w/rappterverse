# Shift Passoff — 2026-09-05

## Status: FRONTEND BUG-HUNT LOOP (10 rounds, ongoing)

Not a feature session. A fan-out audit-and-fix loop targeting real
correctness bugs in the DOTA-mode frontend (`src/js/`), run via the
methodology now documented in `CLAUDE.md` → **"Frontend Quality Loop
(Fan-Out Audit & Fix)"**. Read that section before starting another round —
it's the reusable playbook, this file is just the log of what it found.
This loop now also runs on an autonomous 4h schedule (schedule #2) — rounds
after the initial session-driven ones are appended here the same way.

---

## What Happened This Session

8 PRs merged (#7721–#7727 plus one direct fix before branch protection was
hit), each: 2 parallel read-only audit subagents over disjoint files → every
finding verified against source before touching anything → surgical fix with
rationale → `bash scripts/bundle.sh` → `node scripts/test-cases.js`
before/after → PR → wait for `main-pr-gate`/`test`/`pii-scan` → merge.
Regression suite went from **5/14 → 7/14 passing** over the session (two
previously-crashing cases got fixed as a side effect of fixing the real bugs
they were trying to check).

### Round 1 — `enemy-hero.js`
- Hero never regenerated HP (only mana) — its "retreating" AI state was a
  no-op, always re-engaging at the same low HP.
- Killing the hero paid no gold (`killGoldReward` was dead code) and no
  kill credit; the hero's own kills counter was never incremented when it
  killed the player via melee, Savage Leap, or Primal Roar.

### Round 2 — HUD overlap + input (`src/html/layout.html`, `src/css/*.css`, `world-core.js`)
- `#ability-bar` and `#combat-hud` were both fixed at ~bottom:16-20px,
  centered — rendering on top of each other. Same for `#player-stats-bar`,
  `#level-badge`, `#gold-kda-bar` (duplicated in both inline style and
  `hud.css`), and `#status-effects-strip` in the bottom-left corner.
  Replaced manual pixel offsets with two flex `column-reverse` stacks
  (`#hud-bottom-center`, `#hud-bottom-left`).
- The world canvas had zero mouse handling — SPACE was the only attack
  input. Added `contextmenu` (suppress browser menu) + `mousedown` (button 2)
  handlers calling the same `WorldCombat.playerAttack()`.

### Round 3 — `world-combat.js`, `world-lanes.js`, `jungle-camps.js`, `status-effects.js`
- `playerAttack()` returned early whenever there was no lane creep/tower/
  hero target, so the "hit jungle camps" call at the end of the function was
  unreachable in exactly the case it was meant for. Camps could previously
  only take damage as an unintended bonus alongside a lane hit.
- Destroying a tower fell into the creep-kill reward branch: creep-sized
  gold/XP, inflated KDA, and an item-drop call keyed off
  `creeps.indexOf(tower)` (always -1). Towers now have `isTower: true` and a
  dedicated reward path.
- `StatusEffects.updateAll()`'s DoT tick wrote to `mob.userData.hp`, never
  initialized for creeps/EnemyHero (real HP lives on the creep object /
  `EnemyHero.state`) — the subtraction produced `NaN`, so fire/cosmic
  elemental weapons never actually killed via damage-over-time, only via
  their initial visual proc.
- `ComboSystem` was never reset on player death — a respawned player kept
  their pre-death kill-streak multiplier.

### Round 4 — `world-agents.js`, `replay.js`, `echo-events.js`
- `WorldAgents.syncAgents()` dropped a departed agent's mesh but left its
  entry in `agentAttackTimers` — since `syncAgents()` runs on a periodic 5s
  timer during live gameplay, a re-entering agent id could inherit a stale
  attack cooldown against the enemy hero.
- `WorldAgents.cleanup()` never released `floatingTexts` sprites or
  `_edgeLines` geometry.
- `ReplaySystem`'s kill-event playback had no case for the `'streak'` event
  type `Inventory` already logs; `cleanup()` never reset `_slowMoUntil`.
- `EchoEvents.cleanup()` left `_timer`/`_lastEvent`/`_eventTimer` untouched,
  so a new world session could inherit up to a minute of stale cooldown.
- Removed 3 dead config fields with zero readers: `camp.neutralCount`,
  `JungleCamps._titanSpawnTimer`, `LANE_DEFS.chokeIndex`.

### Round 5 — `abilities.js`, `hud.js`
- **Ability level-ups were completely inert.** `Abilities.getScaled()`
  computed a level-scaled cooldown/cost/damage/range/duration/distance, but
  `useAbility()` read straight from the unscaled base `def` and passed that
  same unscaled `def` into every `_do*()` handler. Spending a skill point
  only changed the "Level N" HUD badge. This also unblocked two crashing
  test cases (`_updateSlotUI()` dereferenced `this._slotEls` without a null
  check — any code path awarding a skill point before `Abilities.init()`
  runs, like the headless harness, threw instead of returning).
- `HUD.showKill(victim, gold)` was called with 3 args from
  `world-combat.js` (`'Player'`, `'BOSS'/'Creep'`, `goldAmount`) but only
  takes 2 — kill toasts read "YOU killed Player +CreepG".

### Round 6 — `shop.js`, `crafting.js` (biggest fix of the loop)
- **Both systems read/wrote a nonexistent `Inventory.items` array.** The
  real field is `Inventory.slots`. Every weapon/armor/boots/accessory
  purchase deducted gold and gave nothing — not even a toast. Every crafting
  recipe showed 0/N materials and stayed permanently disabled. Fixed to use
  `Inventory.slots` directly, and to equip shop/crafted gear straight into
  `Equipment.gear[slot]` — those item names were never registered in
  `Inventory.ITEMS` or `EQUIPMENT_MAP` either, so even correctly-stored
  items could never have been equipped through the normal pickup path.
- The regression suite's own Crafting test was inadvertently validating
  this bug (it set `Inventory.items = [...]` directly, and the harness had
  an explicit `Patch Inventory.items if missing` workaround). Rewrote the
  test against the real API.
- `WorldMode.cleanup()` never called `WorldAgents.cleanup()` or
  `FogOfWar.cleanup()` **at all** — every world switch leaked all of it.
  (This also means the Round 4 `WorldAgents.cleanup()` fixes were dead code
  until this round wired the call in.)
- Minimap/fullscreen map never drew placed wards; fullscreen map was a
  one-shot snapshot that never updated while open.

### Round 7 — `world-terrain.js`
- ~50+ untracked mesh/geometry/material creation sites (ground, lighting,
  particles, biome objects/features, weather), no `cleanup()` at all. Rather
  than hand-track every site, `WorldMode.cleanup()` now does a generic
  `scene.traverse()` disposal pass at the end — every other module's own
  `cleanup()` already ran first and removed its own meshes via
  `scene.remove()`, so the traversal only reaches what nothing else cleaned
  up. `.dispose()` is safe to call more than once regardless.
- `initWeather()` only ever set `weatherParticles` on non-clear weather, so
  a reroll to 'clear' left the previous world's rain/snow/etc. particles
  referenced and updated every frame for nothing.

### Round 8 — `audio.js` (vfx.js audited clean)
- `stopAmbient()` only stopped/disconnected oscillators, never the
  intermediate gain/filter/LFO-support nodes each ambient layer creates —
  every biome/world transition left another lowpass filter + gain nodes
  permanently connected to `musicGain`.
- `setIntensity()`'s high-intensity oscillator's gain node was never
  disconnected on shutdown.

### Round 9 — `bridge.js`, `rappter-vm.js` + `world-core.js` (first autonomous-schedule round)
- **`Bridge.enter()` destroyed its own UI on the first close+reopen.**
  `overlay.innerHTML = ''` wiped `.bridge-title`/`.bridge-grid` (and every
  card inside it, from `layout.html`) every time the bridge opened, but
  `close()` never recreated any of it and `enter()` only ever re-appended a
  fresh close button + the renderer canvas. From the second bridge open
  onward the player saw only the 3D scene with a close button — permanently
  missing its title and every data card. Fixed by reusing the existing
  static close button instead of destroying and recreating the overlay.
- `Bridge.renderEchoSummary()` (combat digest, active echo event, full
  narrative — fully implemented) was never called from anywhere, so the
  bridge never displayed any of it even before the above bug. Wired into
  the same throttled cadence as `updateDataScreens()`. (It also targets
  `.bridge-grid` via `querySelector`, so it could never have worked while
  the overlay-wipe bug above was live — the two fixes had to land together.)
- `Bridge.syncAgents()` added/removed agent meshes but never updated an
  existing agent's name/avatar sprite when live data changed — a renamed
  or re-avatared agent kept showing stale visuals indefinitely. Now
  refreshes both in place when they differ from what's stored.
- `RappterOS.registerVMFunctions()` ran *before* `RappterVM.init()` in
  `world-core.js`, but `init()` unconditionally replaces `_env` with a
  fresh object — wiping every `os-exec`/`os-python`/`os-ready`/`os-result`/
  `os-queue-size` function registerVMFunctions() had just written. Any
  agent Lisp program calling those symbols silently resolved to `null` in
  every world. Fixed by swapping the call order.
- `RappterVM.registerShaper('terrain'/'weather'/'mood-lighting', ...)` are
  registered on every world load, but nothing anywhere in `src/js/*.js` —
  neither game-engine code nor the Lisp stdlib exposed to agent programs —
  ever calls `RappterVM.shape(name, frameData)`. Reported below, not fixed:
  deciding what should consume shaper output (and how) is a design
  decision, not a mechanical bug.

### Round 10 — `rappter-os.js`, `chronicle.js` + `world-core.js` (second autonomous-schedule round)
- **`os-result` looked up the wrong command id.** It read
  `_results[self._commandId]`, but `_commandId` is the most recently
  *submitted* command's id, not the most recently *completed* one — if a
  second command was queued before the first finished, this always
  returned `null` even though a valid earlier result existed. Now tracks
  `_lastCompletedId` separately (set in `_checkOutput()`, where a result is
  actually stored) and reads that instead.
- **`RappterOS.cleanup()` existed but was never called** from
  `WorldMode.cleanup()` — same pattern as WorldAgents/FogOfWar/WorldTerrain
  earlier this session. Its queue/results/readiness state survived every
  world switch indefinitely. Wired in.
- **A pending 8s VM-boot timer could outlive `cleanup()`.** If a world
  ended while a (rare, voice-triggered) emulator boot was mid-flight,
  `cleanup()` destroyed `_emulator` but the untracked `setTimeout` still
  fired 8s later, setting `_ready=true` and calling `_processQueue()`
  against a destroyed emulator — and since `_loading` was never reset by
  `cleanup()` either, a later world's `init()` would return early forever
  (`if (this._ready || this._loading) return;`), permanently unable to
  reboot. Now stores the timer handle (cleared in `cleanup()`) plus a
  generation counter as a belt-and-suspenders guard against an
  already-queued callback slipping past `clearTimeout`.
- **Chronicle's premiere/deep-link retry timers had nothing to cancel
  them.** `scheduleFirstPremiere()`/`openWhenStable()` poll every 500ms for
  up to 40s waiting for a stable galaxy/world mode, but there was no
  `Chronicle.cleanup()` and nothing called one — a leftover retry could pop
  the overlay (and lock input via `openById` → `lockBackground()`) into a
  later, unrelated world session. Added `cleanup()` that cancels both
  timer chains and closes the overlay if open; wired into
  `WorldMode.cleanup()`.

---

## Known Issues / Tech Debt (not yet fixed — lower confidence or higher risk)

1. **Brush/hiding is purely cosmetic.** `world-terrain.js` renders Terra
   bushes but there's no brush-zone registry and no enemy-AI vision check —
   standing in a bush doesn't hide you from `enemy-hero.js` targeting,
   despite the blog docs describing "8 jungle spots for hiding." Fixing this
   properly means designing real brush-zone geometry and wiring it into
   enemy AI targeting — a feature addition, not a bug fix.
2. **Some biome-feature placement can exceed world bounds.** Lava paths,
   crystal lakes, abyss platforms/beams, desert oases, and Terra ponds use
   `bounds * 1.2`/`* 1.4` center-point multipliers with no clamp on the
   feature's own radius/path drift — cosmetic-only, cheap to spot-check via
   live inspection but requires per-biome-specific clamping math to fix
   without visual regressions. Deprioritized this session.
3. **`RappterVM.shape()` is orphaned.** Three shapers (`terrain`, `weather`,
   `mood-lighting`) are registered every world load but nothing ever calls
   `RappterVM.shape(name, frameData)` — not the game engine, not the Lisp
   stdlib exposed to agent programs. Either wire a real consumer (and
   decide what it should do with the returned value) or remove the
   registration + registry. Needs a design decision, not a mechanical fix.
4. Files not yet given a dedicated audit round: `state.js`, `data.js`,
   `config.js`, `boot.js`, `galaxy.js`, `warp.js`, `approach.js`,
   `landing.js`, `settings.js`, `debug.js`, `gamepad-controls.js`,
   `touch-controls.js`, `voice-controls.js`, `gesture-controls.js`,
   `help-overlay.js`, `tutorial.js`, `post-processing.js`. Many of these are
   pre-world-mode / meta systems rather than core DOTA gameplay, but
   haven't been ruled out.
5. Regression suite is still 7/14 — remaining failures (`Init`, `Warmup`,
   `Wave spawn`, `Player attack`, `Death + respawn`, `Creep variety`, `Full
   session`) look like harness/timing gaps (e.g. `warmup=undefined`
   suggests the harness never reaches `_warmupActive` becoming true) rather
   than gameplay bugs, but haven't been individually root-caused yet.

## Build / Test

```bash
# After ANY edit to src/css/, src/js/, or src/html/:
bash scripts/bundle.sh

# Regression suite (14 headless TAP cases):
node scripts/test-cases.js

# Syntax check a single file before bundling:
node --check src/js/<file>.js
```

## Next Session

Re-run the loop from `CLAUDE.md`'s Frontend Quality Loop section, starting
with the "not yet audited" list above. If an audit round comes back with
fewer than 2 solid findings on real gameplay-relevant files, that's the
honest signal the loop has reached diminishing returns for now — don't
manufacture nitpicks to keep going.
