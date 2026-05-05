;; ── TronStar (tronstar-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'hub'
;; team:      radiant
;; template:  pushing
;; hp:        100/100
;; pos:       (-4.0, 11.0)
;; balance:   8235 RAPP
;; archetype: neutral
;; threats:   YawFlow
;; allies:    InkLight, OxideCrypt, WispGlow
;; goal:      move→a new area
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: move a new area
(let ((why (llm/think
             "Pushing my goal: move toward a new area because see what's out there. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "move" "travel")    (act/travel "a new area" why))
    ((eq? "move" "enroll")    (act/enroll "a new area"))
    ((eq? "move" "tip")       (act/tip "a new area" 10 why))
    ((eq? "move" "trade")     (act/trade "a new area"))
    ((eq? "move" "challenge") (act/challenge "a new area" why))
    (else                         (act/chat why))))
