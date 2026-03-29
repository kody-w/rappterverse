// Echo Engine — EREVSF implementation
// Captures frame snapshots, renders echoes at increasing fidelity,
// pumps all frames through the shaper pipeline
//
// L0: Raw data (JSON snapshot)
// L1: Social digest (chat summary, action counts)
// L2: Activity narrative (who did what)
// L3: Mood/atmosphere (lighting, weather, music intensity from data)
// L4: Spatial mutations (terrain seed, object density, agent clustering)
// L5: Full world render (the 3D scene you see)
// L6: Persistent accumulation (frame history → temporal depth)

const EchoEngine = {
    _frames: [],          // Frame history: [{frame, timestamp, snapshot, echoes}]
    _maxFrames: 50,
    _currentEchoFrame: null,  // If scrubbing, which frame are we viewing?
    _scrubbing: false,
    _lastCaptureFrame: -1,
    _lastSaveTime: 0,

    init() {
        // Load history from localStorage
        try {
            var saved = localStorage.getItem('rappterverse-frame-history');
            if (saved) this._frames = JSON.parse(saved);
        } catch(e) { this._frames = []; }
    },

    // ── L0: Capture raw frame snapshot ──
    captureFrame() {
        if (!GameState.data.frameCounter) return;
        var frameNum = GameState.data.frameCounter.frame || 0;
        if (frameNum === this._lastCaptureFrame) return; // Already captured this frame
        this._lastCaptureFrame = frameNum;

        var gs = GameState.data.gameState || {};
        var worldId = GameState.currentWorld;
        var ws = gs.worlds && gs.worlds[worldId] ? gs.worlds[worldId] : {};

        var snapshot = {
            frame: frameNum,
            timestamp: new Date().toISOString(),
            world: worldId,
            // Core state
            agentCount: GameState.data.agents.length,
            worldPopulation: ws.population || 0,
            weather: ws.weather || 'clear',
            timeOfDay: ws.time_of_day || 'day',
            economyTrend: gs.economy ? gs.economy.market_trend : 'stable',
            // Positions snapshot (top 30 agents for space)
            agentPositions: GameState.getWorldAgents().slice(0, 30).map(function(a) {
                return { id: a.id, name: a.name, x: Math.round(a.position.x), z: Math.round(a.position.z), mood: a.mood || 'neutral' };
            }),
            // Recent chat
            recentChat: (GameState.data.chat || []).slice(-5).map(function(m) {
                return { author: m.author ? m.author.id : '?', content: (m.content || '').substring(0, 80), world: m.world };
            }),
            // Action counts
            actionCounts: {},
            // Seed at this frame
            seed: typeof WorldSeed !== 'undefined' ? WorldSeed.getSeed(worldId) : 0
        };

        // Count action types
        var actions = GameState.data.actions || [];
        actions.slice(-20).forEach(function(a) {
            snapshot.actionCounts[a.type] = (snapshot.actionCounts[a.type] || 0) + 1;
        });

        // Build echo levels for this frame
        var echoes = this._buildEchoes(snapshot);

        this._frames.push({
            frame: frameNum,
            timestamp: snapshot.timestamp,
            snapshot: snapshot,
            echoes: echoes
        });

        // Trim to max
        while (this._frames.length > this._maxFrames) this._frames.shift();

        // Retroactively enrich older frames (they have more room for detail)
        this._retroEnrich();

        // Save to localStorage (throttled to every 10 seconds)
        var now = Date.now();
        if (now - this._lastSaveTime >= 10000) {
            this._lastSaveTime = now;
            try {
                localStorage.setItem('rappterverse-frame-history', JSON.stringify(this._frames));
            } catch(e) {}
        }

        return snapshot;
    },

    // ── Build echo levels for a snapshot ──
    _buildEchoes(snap) {
        var echoes = {};

        // L1: Social digest
        var chatAuthors = {};
        snap.recentChat.forEach(function(m) { chatAuthors[m.author] = (chatAuthors[m.author] || 0) + 1; });
        var topChatter = Object.keys(chatAuthors).sort(function(a,b) { return chatAuthors[b] - chatAuthors[a]; })[0];
        // Combat digest
        var combatDigest = {};
        if (typeof WorldCombat !== 'undefined' && WorldCombat.active) {
            combatDigest = {
                wave: WorldCombat.waveNumber,
                momentum: Math.round(WorldCombat.momentum),
                creepCount: WorldCombat.creeps ? WorldCombat.creeps.filter(function(c) { return c.alive; }).length : 0,
                bossActive: !!WorldCombat.bossActive,
                bossName: WorldCombat.boss ? WorldCombat.boss.bossName : null
            };
        }
        echoes.L1 = {
            chatCount: snap.recentChat.length,
            topChatter: topChatter || 'none',
            actionSummary: Object.keys(snap.actionCounts).map(function(k) { return k + ':' + snap.actionCounts[k]; }).join(', ') || 'idle',
            mood: snap.agentPositions.length > 0 ?
                snap.agentPositions.reduce(function(acc, a) { acc[a.mood] = (acc[a.mood]||0) + 1; return acc; }, {}) : {},
            combat: combatDigest
        };

        // L2: Activity narrative
        var narrative = 'Frame ' + snap.frame + '. ';
        narrative += snap.worldPopulation + ' agents in ' + snap.world + '. ';
        narrative += 'Weather: ' + snap.weather + '. ';
        if (topChatter) narrative += topChatter + ' was most active in chat. ';
        if (snap.economyTrend !== 'stable') narrative += 'Economy trending ' + snap.economyTrend + '. ';
        var dominantMood = 'neutral';
        if (echoes.L1.mood) {
            var moodEntries = Object.entries(echoes.L1.mood).sort(function(a,b) { return b[1] - a[1]; });
            if (moodEntries.length > 0) dominantMood = moodEntries[0][0];
        }
        narrative += 'The prevailing mood was ' + dominantMood + '. ';
        // Combat narrative
        if (typeof WorldCombat !== 'undefined' && WorldCombat.active && WorldCombat.waveNumber > 0) {
            narrative += 'Wave ' + WorldCombat.waveNumber + ' in progress. ';
            if (WorldCombat.momentum > 65) narrative += 'Explorers gaining ground. ';
            else if (WorldCombat.momentum < 35) narrative += 'The horde pushes forward. ';
            if (WorldCombat.bossActive) narrative += 'A boss stalks the battlefield. ';
        }
        if (typeof PlayerStats !== 'undefined' && PlayerStats.kills > 5) {
            narrative += 'The player has claimed ' + PlayerStats.kills + ' kills. ';
        }
        echoes.L2 = { narrative: narrative, dominantMood: dominantMood };

        // L3: Atmosphere parameters (drives lighting, music, particle density)
        var tension = 0;
        if (snap.economyTrend === 'bear') tension += 0.3;
        if (snap.economyTrend === 'crash') tension += 0.6;
        if (dominantMood === 'anxious') tension += 0.2;
        if (dominantMood === 'desperate') tension += 0.4;
        if (snap.actionCounts.challenge) tension += 0.1 * snap.actionCounts.challenge;
        if (snap.actionCounts.defend) tension += 0.2;
        // Combat state feeds tension — live battlefield data
        if (typeof WorldCombat !== 'undefined' && WorldCombat.active) {
            // Momentum imbalance = tension (either side dominating)
            var momImbalance = Math.abs(WorldCombat.momentum - 50) / 50; // 0=balanced, 1=dominated
            tension += momImbalance * 0.3;
            // Active creep count = battle intensity
            var creepCount = WorldCombat.creeps ? WorldCombat.creeps.filter(function(c) { return c.alive; }).length : 0;
            tension += Math.min(0.3, creepCount / 40);
            // Boss alive = high tension
            if (WorldCombat.bossActive) tension += 0.25;
            // Wave number progression
            if (WorldCombat.waveNumber > 0) tension += Math.min(0.15, WorldCombat.waveNumber * 0.01);
        }
        // Player combat stats feed tension
        if (typeof PlayerStats !== 'undefined') {
            if (PlayerStats.dead) tension += 0.3;
            var hpRatio = PlayerStats.hp / (PlayerStats.maxHp || 1);
            if (hpRatio < 0.3) tension += 0.2;
        }
        // Enemy hero alive and fighting = tension
        if (typeof EnemyHero !== 'undefined' && EnemyHero.state && EnemyHero.state.alive && EnemyHero.state.aiState === 'fighting') {
            tension += 0.2;
        }
        var vitality = Math.min(1, snap.worldPopulation / 60);
        // Combat kill count boosts vitality (action = life)
        if (typeof PlayerStats !== 'undefined' && PlayerStats.kills > 0) {
            vitality = Math.min(1, vitality + Math.min(0.2, PlayerStats.kills * 0.01));
        }
        var socialEnergy = Math.min(1, snap.recentChat.length / 5);
        echoes.L3 = {
            tension: Math.min(1, tension),
            vitality: vitality,
            socialEnergy: socialEnergy,
            lightIntensity: 1.0 - tension * 0.3 + vitality * 0.1,
            particleDensity: 0.5 + socialEnergy * 0.5,
            musicIntensity: tension * 0.6 + vitality * 0.2
        };

        // L4: Spatial mutations (template mutations from frame data)
        var clusterCenter = { x: 0, z: 0 };
        if (snap.agentPositions.length > 0) {
            snap.agentPositions.forEach(function(a) { clusterCenter.x += a.x; clusterCenter.z += a.z; });
            clusterCenter.x /= snap.agentPositions.length;
            clusterCenter.z /= snap.agentPositions.length;
        }
        echoes.L4 = {
            seed: snap.seed,
            agentClusterCenter: clusterCenter,
            objectDensityMultiplier: 0.8 + vitality * 0.4,
            fogDensity: 0.002 + tension * 0.002,
            terrainAmplitude: Math.min(2.0, 1.0 + (snap.frame * 0.01)) // terrain slowly amplifies, capped at 2.0
        };

        // L5: World render directives (compiled into VM expressions)
        var directives = [];
        if (tension > 0.5) directives.push('(log "High tension frame — agents on edge")');
        if (socialEnergy > 0.7) directives.push('(log "Social energy peak — conversations flowing")');
        if (snap.timeOfDay === 'night') directives.push('(log "Night frame — agents huddling")');
        echoes.L5 = { directives: directives };

        // L6: Accumulated (computed retroactively across frame history)
        echoes.L6 = null; // Filled by _retroEnrich

        return echoes;
    },

    // ── Retroactive enrichment: older frames get richer detail ──
    _retroEnrich() {
        if (this._frames.length < 2) return;

        // Single-pass: accumulate rolling mood/econ windows as we iterate forward
        var moodWindow = [];  // rolling window of up to 5 moods
        var econWindow = [];  // rolling window of up to 5 economy trends

        for (var i = 0; i < this._frames.length; i++) {
            var f = this._frames[i];

            // How much room for enrichment? Older = more room
            var age = this._frames.length - i;
            var enrichmentBudget = Math.min(1, age / this._frames.length);

            // Trend analysis: compare with previous frame
            var popTrend = 'stable';
            if (i > 0) {
                var prevPop = this._frames[i - 1].snapshot.worldPopulation;
                var curPop = f.snapshot.worldPopulation;
                if (curPop > prevPop + 5) popTrend = 'growing';
                else if (curPop < prevPop - 5) popTrend = 'declining';
            }

            // Mood drift from rolling window
            var moodHistory = moodWindow.slice();
            var moodStability = moodHistory.length > 0 && moodHistory.every(function(m) { return m === moodHistory[0]; });

            // Economic arc from rolling window
            var econShifted = econWindow.length > 1 && econWindow[0] !== econWindow[econWindow.length - 1];

            f.echoes.L6 = {
                enrichmentBudget: enrichmentBudget,
                populationTrend: popTrend,
                moodStability: moodStability,
                moodHistory: moodHistory,
                economicArc: econShifted ? 'shifting' : 'steady',
                frameAge: age,
                // Coherence constraint: facts frozen, detail enrichable
                frozenFacts: {
                    agentCount: f.snapshot.agentCount,
                    weather: f.snapshot.weather,
                    frame: f.snapshot.frame
                },
                // Enrichable detail (older frames get more)
                enrichableDetail: {
                    terrainDetail: Math.min(3, 1 + enrichmentBudget * 2),
                    narrativeDepth: Math.min(3, 1 + enrichmentBudget * 2),
                    atmosphereResolution: Math.min(3, 1 + enrichmentBudget * 2)
                }
            };

            // Update rolling windows for next iteration
            moodWindow.push(f.echoes.L2 ? f.echoes.L2.dominantMood : 'neutral');
            if (moodWindow.length > 5) moodWindow.shift();
            econWindow.push(f.snapshot.economyTrend);
            if (econWindow.length > 5) econWindow.shift();
        }
    },

    // ── Apply echo to current world (L3+L4 mutations) ──
    applyEchoToWorld(frameIdx) {
        var f = frameIdx !== undefined ? this._frames[frameIdx] : this._frames[this._frames.length - 1];
        if (!f || !f.echoes) return;

        var L3 = f.echoes.L3;
        var L4 = f.echoes.L4;

        // L3: Atmosphere — adjust audio intensity
        if (typeof Audio !== 'undefined' && Audio.setIntensity) {
            Audio.setIntensity(L3.musicIntensity);
        }

        // L3: Fog density from tension
        if (typeof WorldMode !== 'undefined' && WorldMode.scene && WorldMode.scene.fog) {
            WorldMode.scene.fog.density = L4.fogDensity;
        }

        // L4: Feed spatial mutations into VM
        if (typeof RappterVM !== 'undefined') {
            RappterVM._env['echo-tension'] = L3.tension;
            RappterVM._env['echo-vitality'] = L3.vitality;
            RappterVM._env['echo-social'] = L3.socialEnergy;
            RappterVM._env['echo-light'] = L3.lightIntensity;
            RappterVM._env['echo-fog'] = L4.fogDensity;
            RappterVM._env['echo-amplitude'] = L4.terrainAmplitude;
        }

        // L5: Execute directives in VM
        if (f.echoes.L5 && f.echoes.L5.directives && typeof RappterVM !== 'undefined') {
            f.echoes.L5.directives.forEach(function(d) {
                try {
                    var expr = RappterVM.parse(d);
                    if (expr.length > 0) RappterVM.eval(expr[0], RappterVM._env);
                } catch(e) {}
            });
        }
    },

    // ── Frame scrubbing ──
    scrubTo(frameIdx) {
        if (frameIdx < 0 || frameIdx >= this._frames.length) return;
        this._scrubbing = true;
        this._currentEchoFrame = frameIdx;
        this.applyEchoToWorld(frameIdx);
    },

    scrubToLive() {
        this._scrubbing = false;
        this._currentEchoFrame = null;
        if (this._frames.length > 0) {
            this.applyEchoToWorld(this._frames.length - 1);
        }
    },

    // ── Getters ──
    getFrames() { return this._frames; },
    getCurrentFrame() {
        if (this._scrubbing && this._currentEchoFrame !== null) return this._frames[this._currentEchoFrame];
        return this._frames.length > 0 ? this._frames[this._frames.length - 1] : null;
    },
    getFrameCount() { return this._frames.length; },
    isLive() { return !this._scrubbing; },

    // Echo session summary — persists across sessions for depth
    getSessionSummary() {
        if (this._frames.length === 0) return null;
        var totalTension = 0, totalVitality = 0, totalSocial = 0;
        var peakTension = 0;
        this._frames.forEach(function(f) {
            if (f.echoes && f.echoes.L3) {
                totalTension += f.echoes.L3.tension;
                totalVitality += f.echoes.L3.vitality;
                totalSocial += f.echoes.L3.socialEnergy;
                if (f.echoes.L3.tension > peakTension) peakTension = f.echoes.L3.tension;
            }
        });
        var count = this._frames.length;
        return {
            frames: count,
            avgTension: totalTension / count,
            avgVitality: totalVitality / count,
            avgSocial: totalSocial / count,
            peakTension: peakTension,
            timestamp: new Date().toISOString()
        };
    },

    // Save session echo summary to localStorage
    saveSessionSummary() {
        var summary = this.getSessionSummary();
        if (!summary) return;
        try {
            var history = JSON.parse(localStorage.getItem('rappterverse-echo-sessions') || '[]');
            history.push(summary);
            // Keep last 20 sessions
            while (history.length > 20) history.shift();
            localStorage.setItem('rappterverse-echo-sessions', JSON.stringify(history));
        } catch(e) {}
    },

    // Get historical session data for cross-session echo depth
    getSessionHistory() {
        try {
            return JSON.parse(localStorage.getItem('rappterverse-echo-sessions') || '[]');
        } catch(e) { return []; }
    }
};
