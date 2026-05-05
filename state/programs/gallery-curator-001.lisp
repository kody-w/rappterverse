;; authored by Kaizen Monk at 2026-05-05T01:28:25Z
;; for Curator (gallery-curator-001) in gallery
;; mood=neutral traits={"explorer": 0.579, "social": 0.2179, "trader": 0.0478, "fighter": 0.0929, "builder": 0.0624}

(do (if (< (rand) 0.09) (emote "gallery-curator-001" "look-around") nil) (if (< (rand) 0.07) (emote "gallery-curator-001" "think") nil) (if (and (< (player-distance "gallery-curator-001") 6) (< (rand) 0.18)) (let (p (player-pos)) (do (face-toward "gallery-curator-001" (get p "x") (get p "z")) (if (< (rand) 0.4) (emote "gallery-curator-001" "wave") nil))) nil) (if (< (rand) 0.12) (let (n (nearest-agent "gallery-curator-001")) (if n (let (np (agent-pos n)) (move-toward "gallery-curator-001" (get np "x") (get np "z") 0.35)) nil)) nil) (if (< (rand) 0.22) (wander "gallery-curator-001" 7) nil))
