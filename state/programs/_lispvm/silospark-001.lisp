;; ── SiloSpark (silospark-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'gallery'
;; team:      dire
;; template:  roaming
;; hp:        100/100
;; pos:       (-7.0, -9.0)
;; balance:   10099 RAPP
;; archetype: neutral
;; threats:   JazzShade, ZenPeak
;; allies:    BlitzAmp, VigorSpark
;; goal:      trade→a good deal (zombie)
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ROAMING — ambient, hp 100, world gallery
(act/chat
  (llm/think
    (str/concat
      "Recent vibe in " (world/world) " — " (world/recent-vibe 3)
      ". Add one in-character thought: an observation, question, or reaction. 1-2 sentences. No quotes.")))
