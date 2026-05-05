;; ── MoxGlow (moxglow-001) ────────────────────────────
;; compiled at 2026-05-05T02:32:45Z for frame in 'arena'
;; team:      radiant
;; template:  engaging
;; hp:        100/100
;; pos:       (3.0, 9.0)
;; balance:   9184 RAPP
;; archetype: neutral
;; threats:   ByteCast, MistFire, QuillFall
;; allies:    HexShift, KiteDrift, DeepRoot
;; goal:      challenge→a worthy opponent (zombie)
;; bonds:     3 top (max=2)
;;
;; This file is REGENERATED only when this agent's tactical situation
;; changes (see should_recompile() in scripts/frame_compile.py). When
;; nothing meaningful has shifted, the agent keeps running yesterday's
;; program. That sparseness IS the emergence — not every entity reacts
;; every tick; only those whose world has changed update.

;; ENGAGING — threat ByteCast in range, hp 100/100
(act/challenge "bytecast-001"
  (llm/think
    "ByteCast is right in front of me and I can take them. One sharp challenge line, in-character. No quotes."))
