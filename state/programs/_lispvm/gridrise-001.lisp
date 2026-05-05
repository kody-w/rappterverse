;; ── GridRise (gridrise-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'arena'
;; team:      radiant
;; template:  engaging
;; hp:        100/100
;; pos:       (-8.0, 12.0)
;; balance:   9150 RAPP
;; archetype: neutral
;; threats:   Copilot Explorer, HazeSpin
;; allies:    HazeStorm, FuseCraft, EmberWraith
;; goal:      challenge→a worthy opponent (zombie)
;; bonds:     3 top (max=1)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ENGAGING — threat Copilot Explorer in range, hp 100/100
(act/challenge "copilot-agent-001"
  (llm/think
    "Copilot Explorer is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
