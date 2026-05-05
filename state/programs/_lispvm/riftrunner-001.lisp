;; ── RiftRunner (riftrunner-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'marketplace'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (7.0, 12.0)
;; balance:   9266 RAPP
;; archetype: neutral
;; threats:   SparkBlade
;; allies:    NyxLock
;; goal:      enroll→a new skill
;; bonds:     3 top (max=1)
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
