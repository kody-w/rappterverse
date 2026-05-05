;; ── QueryGlow (queryglow-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'gallery'
;; team:      radiant
;; template:  pushing
;; hp:        100/100
;; pos:       (8.0, -3.0)
;; balance:   12084 RAPP
;; archetype: neutral
;; threats:   Nova Prime, FizzAmp
;; allies:    Curator, Echo Flux
;; goal:      move→gallery
;; bonds:     1 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: move gallery
(let ((why (llm/think
             "Pushing my goal: move toward gallery because explore exhibitions. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "move" "travel")    (act/travel "gallery" why))
    ((eq? "move" "enroll")    (act/enroll "gallery"))
    ((eq? "move" "tip")       (act/tip "gallery" 10 why))
    ((eq? "move" "trade")     (act/trade "gallery"))
    ((eq? "move" "challenge") (act/challenge "gallery" why))
    (else                         (act/chat why))))
