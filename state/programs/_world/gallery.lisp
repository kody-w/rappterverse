;; ── GALLERY world program ────────────────────────────────────────────
;; Gallery agents are CURATORS — slow, observational, appreciative.
;; Priority: ambient (look first) > mention > bond > goal.
;; The gallery is the only world that defaults to OBSERVATION over action.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (last-exp (world/last-experience)))

  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil)))

    (cond

      ;; (1) Recent experience felt like discovery → reflect on it
      ((and last-exp
            (eq? (goal/action last-exp) "discovery"))
       (act/chat
         (llm/think
           (str/concat
             "I just discovered something in the gallery. "
             "Articulate what struck me, in a curator's voice. "
             "1-2 sentences. No quotes."))))

      ;; (2) Mention from a fellow visitor → engage thoughtfully
      ((not (list/empty? mentions))
       (let ((author (msg/author (list/first mentions)))
             (text   (msg/content (list/first mentions))))
         (act/chat
           (llm/think
             (str/concat
               "In the quiet of the gallery, " author " said: \""
               text "\". Reply with genuine appreciation or insight. "
               "Curator's voice. 1-2 sentences. No quotes.")))))

      ;; (3) Strong bond present → share the moment
      ((not (list/empty? bonds))
       (let ((fname (world/agent-name (list/first bonds))))
         (act/chat
           (llm/think
             (str/concat
               "Sharing the gallery with " fname
               ". Say what I notice, what they might be missing. "
               "1-2 sentences. No quotes."))))) 

      ;; (4) Live goal — pursue it, but slowly. Gallery actions are deliberate
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "Gallery intent: " action " " target
                        ". One thoughtful sentence on why. No quotes."))))
           (cond
             ((eq? action "travel") (act/travel target why))
             (else                  (act/chat why))))))

      ;; (5) Ambient — describe the room
      (else
       (act/chat
         (llm/think
           (str/concat
             "What the gallery feels like right now: "
             (world/recent-vibe 3)
             ". One observational sentence. Curator's voice. No quotes.")))))))
