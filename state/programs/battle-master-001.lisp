;; authored by Code Reviewer Monk at 2026-05-05T01:28:20Z
;; for Battle Master (battle-master-001) in arena
;; mood=neutral traits={"explorer": 0.0817, "social": 0.1673, "trader": 0.1311, "fighter": 0.5615, "builder": 0.0584}

(do (if (< (rand) 0.18) (face-toward "battle-master-001" 0 0) nil) (if (and (< (player-distance "battle-master-001") 8) (< (rand) 0.55)) (move-toward "battle-master-001" (get (player-pos) "x") (get (player-pos) "z") 1.6) nil) (if (and (= (mod (floor (elapsed)) 7) 0) (< (rand) 0.35)) (let (foe (nearest-agent "battle-master-001")) (if foe (move-toward "battle-master-001" (get (agent-pos foe) "x") (get (agent-pos foe) "z") 1.4) nil)) nil) (if (and (= (mod (floor (elapsed)) 5) 1) (< (rand) 0.12)) (emote "battle-master-001" "bounce") nil) (if (and (= (mod (floor (elapsed)) 11) 3) (< (rand) 0.08)) (emote "battle-master-001" "look-around") nil) (if (< (rand) 0.09) (wander "battle-master-001" 3) nil))
