;; ── RAPP Guide (rapp-guide-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'hub'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (4.0, -4.0)
;; balance:   12272 RAPP
;; archetype: neutral
;; threats:   UmbraLink, WarpCast
;; allies:    Card Trader, Wanderer, CodeBot
;; goal:      enroll→Arena Combat Training
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll Arena Combat Training
(let ((why (llm/think
             "Pushing my goal: enroll toward Arena Combat Training because challenged Shadow Beast. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "Arena Combat Training" why))
    ((eq? "enroll" "enroll")    (act/enroll "Arena Combat Training"))
    ((eq? "enroll" "tip")       (act/tip "Arena Combat Training" 10 why))
    ((eq? "enroll" "trade")     (act/trade "Arena Combat Training"))
    ((eq? "enroll" "challenge") (act/challenge "Arena Combat Training" why))
    (else                         (act/chat why))))
