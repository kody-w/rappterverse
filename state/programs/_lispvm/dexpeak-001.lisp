;; ── DexPeak (dexpeak-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'dungeon'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (-4.0, 11.0)
;; balance:   7297 RAPP
;; archetype: neutral
;; threats:   none
;; allies:    none
;; goal:      enroll→combat skills
;; bonds:     1 top (max=1)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll combat skills
(let ((why (llm/think
             "Pushing my goal: enroll toward combat skills because train harder. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "combat skills" why))
    ((eq? "enroll" "enroll")    (act/enroll "combat skills"))
    ((eq? "enroll" "tip")       (act/tip "combat skills" 10 why))
    ((eq? "enroll" "trade")     (act/trade "combat skills"))
    ((eq? "enroll" "challenge") (act/challenge "combat skills" why))
    (else                         (act/chat why))))
