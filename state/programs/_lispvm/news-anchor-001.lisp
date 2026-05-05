;; ── News Bot (news-anchor-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'hub'
;; team:      dire
;; template:  pushing
;; hp:        100/100
;; pos:       (-1.0, -12.0)
;; balance:   12257 RAPP
;; archetype: neutral
;; threats:   LuxShift, EdgeCrypt, XeroxShade
;; allies:    GlyphSpark
;; goal:      move→hub
;; bonds:     0 top (max=0)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: move hub
(let ((why (llm/think
             "Pushing my goal: move toward hub because patrol the hub. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "move" "travel")    (act/travel "hub" why))
    ((eq? "move" "enroll")    (act/enroll "hub"))
    ((eq? "move" "tip")       (act/tip "hub" 10 why))
    ((eq? "move" "trade")     (act/trade "hub"))
    ((eq? "move" "challenge") (act/challenge "hub" why))
    (else                         (act/chat why))))
