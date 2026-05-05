;; ── IonCoil (ioncoil-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'arena'
;; team:      radiant
;; template:  engaging
;; hp:        100/100
;; pos:       (9.0, 7.0)
;; balance:   12549 RAPP
;; archetype: neutral
;; threats:   MoxShift, CodaDrift, NovaWeld
;; allies:    WaveLink, Flint, ChainRattle
;; goal:      challenge→a worthy opponent (zombie)
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ENGAGING — threat MoxShift in range, hp 100/100
(act/challenge "moxshift-001"
  (llm/think
    "MoxShift is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
