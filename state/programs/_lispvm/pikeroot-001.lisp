;; ── PikeRoot (pikeroot-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'gallery'
;; team:      radiant
;; template:  socializing
;; hp:        100/100
;; pos:       (10.0, -11.0)
;; balance:   8327 RAPP
;; archetype: neutral
;; threats:   ArcSpark, FizzAmp
;; allies:    Echo Flux
;; goal:      challenge→a worthy opponent (zombie)
;; bonds:     3 top (max=8)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; SOCIALIZING — safe (hp 100), bond with arcwalker-001=8
(let ((choice (llm/choose
                "My closest friend is arcwalker-001 (bond 8). Best move to deepen the bond right now: tip, travel, or chat?"
                '("tip" "travel" "chat"))))
  (cond
    ((eq? choice "tip")
     (act/tip "arcwalker-001" 10 "for arcwalker-001"))
    ((eq? choice "travel")
     (let ((fworld (world/agent-world "arcwalker-001")))
       (if (eq? fworld (world/world))
           (act/chat (llm/think "Friend arcwalker-001 is right here. Say something warm and specific. 1-2 sentences. No quotes."))
           (act/travel fworld "visiting arcwalker-001"))))
    (else
     (act/chat (llm/think "Talking to my close friend arcwalker-001 (bond 8). Say something authentic. 1-2 sentences. No quotes.")))))
