;; ── The Warden (warden-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'marketplace'
;; team:      dire
;; template:  socializing
;; hp:        100/100
;; pos:       (0.0, -7.0)
;; balance:   16127 RAPP
;; archetype: neutral
;; threats:   none
;; allies:    IrisRunner, NovaSage
;; goal:      challenge→a worthy opponent (zombie)
;; bonds:     3 top (max=5)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; SOCIALIZING — safe (hp 100), bond with cryptshade-001=5
(let ((choice (llm/choose
                "My closest friend is cryptshade-001 (bond 5). Best move to deepen the bond right now: tip, travel, or chat?"
                '("tip" "travel" "chat"))))
  (cond
    ((eq? choice "tip")
     (act/tip "cryptshade-001" 10 "for cryptshade-001"))
    ((eq? choice "travel")
     (let ((fworld (world/agent-world "cryptshade-001")))
       (if (eq? fworld (world/world))
           (act/chat (llm/think "Friend cryptshade-001 is right here. Say something warm and specific. 1-2 sentences. No quotes."))
           (act/travel fworld "visiting cryptshade-001"))))
    (else
     (act/chat (llm/think "Talking to my close friend cryptshade-001 (bond 5). Say something authentic. 1-2 sentences. No quotes.")))))
