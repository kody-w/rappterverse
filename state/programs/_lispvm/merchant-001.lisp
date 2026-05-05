;; ── Pack Seller (merchant-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'marketplace'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (-9.0, 6.0)
;; balance:   14014 RAPP
;; archetype: neutral
;; threats:   LuxForge, MistSpin
;; allies:    RAPPcoin Banker, NyxRoot, FizzStone
;; goal:      move→marketplace
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: move marketplace
(let ((why (llm/think
             "Pushing my goal: move toward marketplace because browse the stalls. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "move" "travel")    (act/travel "marketplace" why))
    ((eq? "move" "enroll")    (act/enroll "marketplace"))
    ((eq? "move" "tip")       (act/tip "marketplace" 10 why))
    ((eq? "move" "trade")     (act/trade "marketplace"))
    ((eq? "move" "challenge") (act/challenge "marketplace" why))
    (else                         (act/chat why))))
