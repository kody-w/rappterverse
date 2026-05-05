;; ── Wanderer (wanderer-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'hub'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (3.0, -2.0)
;; balance:   11606 RAPP
;; archetype: neutral
;; threats:   WarpCast, UmbraLink
;; allies:    Card Trader, CodeBot, RAPP Guide
;; goal:      enroll→a new skill
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll a new skill
(let ((why (llm/think
             "Pushing my goal: enroll toward a new skill because keep learning. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "a new skill" why))
    ((eq? "enroll" "enroll")    (act/enroll "a new skill"))
    ((eq? "enroll" "tip")       (act/tip "a new skill" 10 why))
    ((eq? "enroll" "trade")     (act/trade "a new skill"))
    ((eq? "enroll" "challenge") (act/challenge "a new skill" why))
    (else                         (act/chat why))))
