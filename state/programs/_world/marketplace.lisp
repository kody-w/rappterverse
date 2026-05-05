;; ── MARKETPLACE world program ────────────────────────────────────────
;; Marketplace agents are TRADERS — profit, deals, reputation.
;; Priority: trade > tip > goal > mention > ambient.
;; The marketplace tracks balance carefully and acts on opportunity.

(let ((mentions (world/chat-mentions))
      (goals    (world/active-goals))
      (bonds    (world/strongest-bonds 3))
      (nearby   (world/nearby))
      (bal      (world/balance)))

  (let ((live-goal (if (and (not (list/empty? goals))
                            (world/goal-valid? (list/first goals)))
                       (list/first goals)
                       nil))
        (partner   (if (not (list/empty? nearby))
                       (list/first nearby)
                       nil)))

    (cond

      ;; (1) Have a trade goal — execute with conviction
      ((and live-goal (eq? (goal/action live-goal) "trade"))
       (act/trade (goal/target live-goal)))

      ;; (2) Strong bond + healthy balance → tip — generosity is reputation
      ((and (not (list/empty? bonds))
            (>= bal 25))
       (let ((friend (list/first bonds))
             (fname  (world/agent-name (list/first bonds)))
             (bondv  (world/bond (world/me) (list/first bonds))))
         (if (>= bondv 8)
             (act/tip friend 15
                      (llm/think
                        (str/concat
                          "Marketplace tip for " fname
                          " (bond " (str bondv) "). "
                          "One short merchant's-blessing line. No quotes.")))
             (act/trade fname))))

      ;; (3) Stranger nearby + low bond → propose a trade
      ((and partner (< (world/bond (world/me) partner) 5))
       (act/trade partner))

      ;; (4) Other live goal
      (live-goal
       (let ((action (goal/action live-goal))
             (target (goal/target live-goal))
             (reason (goal/reason live-goal)))
         (let ((why (llm/think
                      (str/concat
                        "Marketplace move: " action " " target ". "
                        "Short reason in a merchant's voice. No quotes."))))
           (cond
             ((eq? action "tip")    (act/tip target 10 why))
             ((eq? action "travel") (act/travel target why))
             (else                  (act/chat why))))))

      ;; (5) Mention — answer with marketplace cadence (deal-flavored)
      ((not (list/empty? mentions))
       (let ((author (msg/author (list/first mentions)))
             (text   (msg/content (list/first mentions))))
         (act/chat
           (llm/think
             (str/concat
               "On the trading floor, " author " said: \"" text "\". "
               "Reply with a deal-maker's cadence. 1-2 sentences. No quotes.")))))

      ;; (6) Ambient — read the room as price signal
      (else
       (act/chat
         (llm/think
           (str/concat
             "Marketplace pulse: " (world/recent-vibe 3)
             ". One sharp observation about supply, demand, or vibe. "
             "Merchant voice. 1 sentence. No quotes.")))))))
