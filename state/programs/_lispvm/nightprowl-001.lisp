;; ── NightProwl (nightprowl-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'gallery'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (-11.0, 11.0)
;; balance:   11154 RAPP
;; archetype: neutral
;; threats:   Nexus Alpha, NodePeak, ChipShade
;; allies:    QuillBlade, InkBurn
;; goal:      enroll→survival skills
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll survival skills
(let ((why (llm/think
             "Pushing my goal: enroll toward survival skills because survive the depths. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "survival skills" why))
    ((eq? "enroll" "enroll")    (act/enroll "survival skills"))
    ((eq? "enroll" "tip")       (act/tip "survival skills" 10 why))
    ((eq? "enroll" "trade")     (act/trade "survival skills"))
    ((eq? "enroll" "challenge") (act/challenge "survival skills" why))
    (else                         (act/chat why))))
