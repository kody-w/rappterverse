;; ── Drift (drift-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'arena'
;; team:      dire
;; template:  engaging
;; hp:        100/100
;; pos:       (5.0, -9.0)
;; balance:   14118 RAPP
;; archetype: neutral
;; threats:   DexWeave, BoltLock, ArcSong
;; allies:    Announcer, Sage, OpusCoil
;; goal:      enroll→combat skills
;; bonds:     3 top (max=1)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ENGAGING — threat DexWeave in range, hp 100/100
(act/challenge "dexweave-001"
  (llm/think
    "DexWeave is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
