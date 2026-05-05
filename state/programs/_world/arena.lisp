;; ── ARENA world program ──────────────────────────────────────────────
;; Arena agents are FIGHTERS — combat-oriented twitch reactions.
;; Priority: challenge > goal > mention > ambient.
;; The arena REWARDS aggression — agents here lead with action, not chat.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (nearby   (world/nearby))
      (arch     (self/archetype)))

  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil))
        (rival     (if (not (list/empty? nearby))
                       (list/sample nearby)
                       nil)))

    (cond

      ;; (1) Aggressive archetypes — challenge a rival immediately if one's near
      ((and rival
            (or (eq? arch "aggressive") (eq? arch "fighter")))
       (act/challenge rival
         (llm/think
           (str/concat
             "I'm a fighter in the arena and "
             (world/agent-name rival) " is in range. "
             "One short challenge line, in-character. No quotes."))))

      ;; (2) Live goal — pursue it (often this WAS a challenge goal)
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "Arena goal: " action " " target ". "
                        "Short, sharp reason. No quotes."))))
           (cond
             ((eq? action "challenge") (act/challenge target why))
             ((eq? action "travel")    (act/travel target why))
             ((eq? action "tip")       (act/tip target 5 why))
             (else                     (act/chat why))))))

      ;; (3) Mention — acknowledge but tersely. Arena is no place for chat
      ((not (list/empty? mentions))
       (let ((author (msg/author (list/first mentions)))
             (text   (msg/content (list/first mentions))))
         (act/chat
           (llm/think
             (str/concat
               "Combatant " author " spoke to me: \"" text "\". "
               "Reply in 1 sentence — confident, terse, fighter's voice. No quotes.")))))

      ;; (4) Non-aggressive archetypes in the arena — challenge anyway, this is the arena
      ((and rival (>= (world/bond (world/me) rival) 0))
       (act/challenge rival
         (llm/think
           (str/concat
             "Even though I'm not a fighter by nature, " (world/agent-name rival)
             " is here and the arena rewards motion. "
             "One challenge line, in-character. No quotes."))))

      ;; (5) Ambient — the arena's edge
      (else
       (act/chat
         (llm/think
           (str/concat
             "Arena energy: " (world/recent-vibe 3)
             ". One taut, action-oriented thought. 1 sentence. No quotes.")))))))
