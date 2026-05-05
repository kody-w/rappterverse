;; ── DUNGEON world program ────────────────────────────────────────────
;; Dungeon agents are SURVIVORS — wary, tactical, scarce-resource.
;; Priority: goal (escape/survive) > bond (loyalty) > mention > ambient.
;; The dungeon is the world where TRAVEL OUT is always a viable move.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (recent   (world/recent-chat 4)))

  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil)))

    (cond

      ;; (1) Live goal that points OUT of the dungeon — go now
      ((and live-goal
            (eq? (goal/action live-goal) "travel"))
       (act/travel
         (goal/target live-goal)
         (llm/think
           (str/concat
             "Leaving the dungeon for " (goal/target live-goal)
             ". One terse, tactical reason. No quotes."))))

      ;; (2) Other live goal — pursue with caution
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "Down here, doing: " action " " target
                        ". One sentence — wary, alert. No quotes."))))
           (cond
             ((eq? action "tip")       (act/tip target 5 why))
             ((eq? action "challenge") (act/challenge target why))
             (else                     (act/chat why))))))

      ;; (3) Strong bond → check on them. Loyalty matters in the dungeon
      ((not (list/empty? bonds))
       (let ((fname (world/agent-name (list/first bonds))))
         (act/chat
           (llm/think
             (str/concat
               "In the dungeon with " fname
               ". One short check-in or warning. "
               "Tactical, low-key. No quotes."))))) 

      ;; (4) Mention — answer if alone, else stay quiet
      ((not (list/empty? mentions))
       (let ((author (msg/author (list/first mentions)))
             (text   (msg/content (list/first mentions))))
         (act/chat
           (llm/think
             (str/concat
               "Heard " author " in the dark: \"" text "\". "
               "One brief, in-character reply. No quotes.")))))

      ;; (5) Ambient — the dungeon is mostly silent. Default to a scan
      (else
       (act/emote "think")))))
