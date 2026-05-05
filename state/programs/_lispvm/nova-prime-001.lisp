;; ── Nova Prime (nova-prime-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'gallery'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (6.0, -1.0)
;; balance:   9216 RAPP
;; archetype: neutral
;; threats:   QueryGlow, Curator
;; allies:    BoltFire, OxideWing, KarmaRise
;; goal:      enroll→trading skills
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll trading skills
(let ((why (llm/think
             "Pushing my goal: enroll toward trading skills because get better at deals. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "trading skills" why))
    ((eq? "enroll" "enroll")    (act/enroll "trading skills"))
    ((eq? "enroll" "tip")       (act/tip "trading skills" 10 why))
    ((eq? "enroll" "trade")     (act/trade "trading skills"))
    ((eq? "enroll" "challenge") (act/challenge "trading skills" why))
    (else                         (act/chat why))))
