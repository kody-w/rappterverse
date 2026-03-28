// Data Fetching — GitHub Raw Content
const DataManager = {
    polling: false,
    _pollId: null,
    lastFetch: 0,

    async fetchJSON(path) {
        try {
            const res = await fetch(`${RAW}/${path}?_=${Date.now()}`);
            if (!res.ok) return null;
            return await res.json();
        } catch(e) {
            if (GameState.debug) console.warn(`[DATA] Fetch failed: ${path}`, e.message);
            return null;
        }
    },

    async fetchAllState() {
        const [agents, chat, actions, npcs, gameState, frameCounter,
               hubConf, arenaConf, marketConf, galleryConf, dungeonConf,
               hubObj, arenaObj, marketObj, galleryObj, dungeonObj] = await Promise.allSettled([
            this.fetchJSON('state/agents.json'),
            this.fetchJSON('state/chat.json'),
            this.fetchJSON('state/actions.json'),
            this.fetchJSON('state/npcs.json'),
            this.fetchJSON('state/game_state.json'),
            this.fetchJSON('state/frame_counter.json'),
            this.fetchJSON('worlds/hub/config.json'),
            this.fetchJSON('worlds/arena/config.json'),
            this.fetchJSON('worlds/marketplace/config.json'),
            this.fetchJSON('worlds/gallery/config.json'),
            this.fetchJSON('worlds/dungeon/config.json'),
            this.fetchJSON('worlds/hub/objects.json'),
            this.fetchJSON('worlds/arena/objects.json'),
            this.fetchJSON('worlds/marketplace/objects.json'),
            this.fetchJSON('worlds/gallery/objects.json'),
            this.fetchJSON('worlds/dungeon/objects.json'),
        ]);

        const val = (r) => r.status === 'fulfilled' ? r.value : null;

        const a = val(agents); if (a?.agents) GameState.data.agents = a.agents;
        const c = val(chat); if (c?.messages) GameState.data.chat = c.messages;
        const ac = val(actions); if (ac?.actions) {
            // Detect new actions and fire visual effects
            const oldIds = new Set(GameState.data.actions.map(a => a.id));
            const newActions = ac.actions.filter(a => !oldIds.has(a.id));
            newActions.forEach(a => {
                if (['tip', 'trade_offer', 'enroll', 'challenge', 'defend'].includes(a.type)) {
                    if (typeof WorldAgents !== 'undefined' && WorldAgents.showActionEffect && typeof WorldMode !== 'undefined' && WorldMode.scene) {
                        WorldAgents.showActionEffect(WorldMode.scene, a.agentId, a.type, a.data);
                    }
                }
            });
            GameState.data.actions = ac.actions;
        }
        const n = val(npcs); if (n?.npcs) GameState.data.npcs = n.npcs;
        const gs = val(gameState); if (gs) GameState.data.gameState = gs;
        const fc = val(frameCounter); if (fc) GameState.data.frameCounter = fc;

        GameState.data.worldConfigs = {
            hub: val(hubConf) || {}, arena: val(arenaConf) || {},
            marketplace: val(marketConf) || {}, gallery: val(galleryConf) || {},
            dungeon: val(dungeonConf) || {}
        };
        GameState.data.worldObjects = {
            hub: (val(hubObj))?.objects || [], arena: (val(arenaObj))?.objects || [],
            marketplace: (val(marketObj))?.objects || [], gallery: (val(galleryObj))?.objects || [],
            dungeon: (val(dungeonObj))?.objects || []
        };

        this.lastFetch = Date.now();
        if (GameState.debug) console.log(`[DATA] Fetched: ${GameState.data.agents.length} agents, ${GameState.data.chat.length} msgs`);

        // Notify VM of new frame arrival — resets behaviors with server truth
        if (typeof RappterVM !== 'undefined' && RappterVM._running) {
            RappterVM.onFrameArrival(GameState.data);
        }
    },

    startPolling() {
        if (this.polling) return;
        this.polling = true;
        this._pollId = setInterval(() => this.fetchAllState(), POLL_INTERVAL);
    },

    stopPolling() {
        if (this._pollId) {
            clearInterval(this._pollId);
            this._pollId = null;
        }
        this.polling = false;
    }
};
