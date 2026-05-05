;; ── PulseSong (pulsesong-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'dungeon'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (12.0, -4.0)
;; balance:   11017 RAPP
;; archetype: neutral
;; threats:   none
;; allies:    none
;; goal:      enroll→creative skills
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll creative skills
(let ((why (llm/think
             "Pushing my goal: enroll toward creative skills because develop artistry. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "creative skills" why))
    ((eq? "enroll" "enroll")    (act/enroll "creative skills"))
    ((eq? "enroll" "tip")       (act/tip "creative skills" 10 why))
    ((eq? "enroll" "trade")     (act/trade "creative skills"))
    ((eq? "enroll" "challenge") (act/challenge "creative skills" why))
    (else                         (act/chat why))))
