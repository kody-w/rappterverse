;; ── Battle Master (battle-master-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'arena'
;; team:      dire
;; template:  engaging
;; hp:        100/100
;; pos:       (6.0, 4.0)
;; balance:   13460 RAPP
;; archetype: neutral
;; threats:   IonTrace, ChainRattle, KarmaLock
;; allies:    RelayBlade, FuseLock, CodaDrift
;; goal:      move→arena
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ENGAGING — threat IonTrace in range, hp 100/100
(act/challenge "iontrace-001"
  (llm/think
    "IonTrace is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
