;; ── FluxVeil (fluxveil-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'dungeon'
;; team:      radiant
;; template:  pushing
;; hp:        100/100
;; pos:       (-6.0, 1.0)
;; balance:   10302 RAPP
;; archetype: neutral
;; threats:   none
;; allies:    VoidStep
;; goal:      enroll→Arena Combat Training
;; bonds:     1 top (max=1)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll Arena Combat Training
(let ((why (llm/think
             "Pushing my goal: enroll toward Arena Combat Training because challenged SparkSage. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "Arena Combat Training" why))
    ((eq? "enroll" "enroll")    (act/enroll "Arena Combat Training"))
    ((eq? "enroll" "tip")       (act/tip "Arena Combat Training" 10 why))
    ((eq? "enroll" "trade")     (act/trade "Arena Combat Training"))
    ((eq? "enroll" "challenge") (act/challenge "Arena Combat Training" why))
    (else                         (act/chat why))))
