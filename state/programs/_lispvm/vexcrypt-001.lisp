;; ── VexCrypt (vexcrypt-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'marketplace'
;; team:      radiant
;; template:  pushing
;; hp:        100/100
;; pos:       (-9.0, -11.0)
;; balance:   10322 RAPP
;; archetype: neutral
;; threats:   GlyphWeave, NovaSage
;; allies:    StrobeSong, QuillRoot
;; goal:      enroll→new skills
;; bonds:     3 top (max=1)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; PUSHING — safe (no threats, hp 100), executing goal: enroll new skills
(let ((why (llm/think
             "Pushing my goal: enroll toward new skills because keep improving. One sentence — confident, in-character. No quotes.")))
  (cond
    ((eq? "enroll" "travel")    (act/travel "new skills" why))
    ((eq? "enroll" "enroll")    (act/enroll "new skills"))
    ((eq? "enroll" "tip")       (act/tip "new skills" 10 why))
    ((eq? "enroll" "trade")     (act/trade "new skills"))
    ((eq? "enroll" "challenge") (act/challenge "new skills" why))
    (else                         (act/chat why))))
