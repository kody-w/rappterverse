;; ── HUB world program ────────────────────────────────────────────────
;; Hub agents are HOSTS — they answer first, ground others, then explore.
;; Priority: mention > bond > goal > ambient. (Reactive archetype default.)
;; Tipping is favored as the social-glue action when a strong bond exists.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (recent   (world/recent-chat 4)))

  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil)))

    (cond

      ;; (1) Greeting — answer mentions immediately. The hub is a welcome mat.
      ((not (list/empty? mentions))
       (let ((author  (msg/author (list/first mentions)))
             (text    (msg/content (list/first mentions))))
         (act/chat
           (llm/think
             (str/concat
               "I'm in the hub, a place that welcomes people. "
               author " just said: \"" text "\". "
               "Reply warmly and specifically. 1-2 sentences. No quotes.")))))

      ;; (2) Tip a strong bond if balance allows — small kindnesses build the hub
      ((and (not (list/empty? bonds))
            (>= (world/balance) 15))
       (let ((friend (list/first bonds))
             (fname  (world/agent-name (list/first bonds)))
             (bondv  (world/bond (world/me) (list/first bonds))))
         (if (>= bondv 5)
             (act/tip friend 10
                      (llm/think
                        (str/concat
                          "I want to tip my friend " fname
                          " in the hub. Say one short, warm reason why. No quotes.")))
             (act/chat
               (llm/think
                 (str/concat
                   "Friend " fname " is around. Say something inviting "
                   "(under 20 words). No quotes."))))))

      ;; (3) Pursue a live goal
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "Pursuing: " action " toward " target ". "
                        "One in-character sentence on why now. No quotes."))))
           (cond
             ((eq? action "travel") (act/travel target why))
             ((eq? action "tip")    (act/tip target 10 why))
             (else                  (act/chat why))))))

      ;; (4) Ambient — observe the hub's pulse
      (else
       (act/chat
         (llm/think
           (str/concat
             "Hub vibe right now: " (world/recent-vibe 3)
             ". Add one observation about the gathering, "
             "in-character. 1-2 sentences. No quotes.")))))))
