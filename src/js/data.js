// Data Fetching — one staged snapshot from canonical main
const DataManager = {
    polling: false,
    _pollId: null,
    _inFlight: null,
    _abortController: null,
    _generation: 0,
    lastFetch: 0,
    lastSuccessfulFetch: 0,

    _resources: [
        ['agents', 'state/agents.json', true],
        ['chat', 'state/chat.json', true],
        ['actions', 'state/actions.json', true],
        ['npcs', 'state/npcs.json', false],
        ['gameState', 'state/game_state.json', true],
        ['frameCounter', 'state/frame_counter.json', false],
        ['brainstem', 'state/programs/_lispvm/_status.json', false],
        ['chronicles', 'state/chronicles.json', false],
        ['hubConf', 'worlds/hub/config.json', true],
        ['arenaConf', 'worlds/arena/config.json', true],
        ['marketConf', 'worlds/marketplace/config.json', true],
        ['galleryConf', 'worlds/gallery/config.json', true],
        ['dungeonConf', 'worlds/dungeon/config.json', true],
        ['hubObj', 'worlds/hub/objects.json', true],
        ['arenaObj', 'worlds/arena/objects.json', true],
        ['marketObj', 'worlds/marketplace/objects.json', true],
        ['galleryObj', 'worlds/gallery/objects.json', true],
        ['dungeonObj', 'worlds/dungeon/objects.json', true]
    ],

    async fetchJSON(path, signal, requestId) {
        const res = await fetch(`${RAW}/${path}?_=${requestId}`, {
            signal: signal,
            cache: 'no-store'
        });
        if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
        try {
            return await res.json();
        } catch(e) {
            throw new Error(`${path}: invalid JSON`);
        }
    },

    _showStatus(msg, isError) {
        var el = document.getElementById('connection-status');
        if (!el) {
            el = document.createElement('div');
            el.id = 'connection-status';
            el.style.cssText = 'position:fixed;top:50px;left:50%;transform:translateX(-50%);z-index:9999;font-size:11px;padding:4px 16px;border-radius:6px;font-family:monospace;pointer-events:none;transition:opacity 0.3s;';
            document.body.appendChild(el);
        }
        if (msg) {
            el.textContent = msg;
            el.style.background = isError ? 'rgba(248,81,73,0.15)' : 'rgba(0,212,255,0.1)';
            el.style.border = '1px solid ' + (isError ? 'rgba(248,81,73,0.3)' : 'rgba(0,212,255,0.2)');
            el.style.color = isError ? '#f85149' : '#8b949e';
            el.style.opacity = '1';
        } else {
            el.style.opacity = '0';
        }
    },

    _setLiveState(label, color) {
        var text = document.querySelector('.status-text');
        var dot = document.querySelector('.status-dot');
        if (text) text.textContent = label;
        if (dot) {
            dot.style.background = color;
            dot.style.boxShadow = '0 0 8px ' + color;
        }
    },

    async _loadSnapshot(signal) {
        const requestId = Date.now();
        const settled = await Promise.allSettled(
            this._resources.map(resource => this.fetchJSON(resource[1], signal, requestId))
        );
        const snapshot = {};
        const requiredFailures = [];
        const optionalFailures = [];

        settled.forEach((result, index) => {
            const resource = this._resources[index];
            if (result.status === 'fulfilled') {
                snapshot[resource[0]] = result.value;
            } else {
                const failure = `${resource[1]} (${result.reason?.message || 'fetch failed'})`;
                if (resource[2]) requiredFailures.push(failure);
                else optionalFailures.push(failure);
            }
        });

        if (requiredFailures.length) {
            throw new Error(`required state unavailable: ${requiredFailures.join(', ')}`);
        }
        if (!Array.isArray(snapshot.agents?.agents)) throw new Error('state/agents.json: missing agents array');
        if (!Array.isArray(snapshot.chat?.messages)) throw new Error('state/chat.json: missing messages array');
        if (!Array.isArray(snapshot.actions?.actions)) throw new Error('state/actions.json: missing actions array');
        if (!snapshot.gameState || typeof snapshot.gameState !== 'object') throw new Error('state/game_state.json: invalid object');

        ['hub', 'arena', 'marketplace', 'gallery', 'dungeon'].forEach((world, index) => {
            const confKey = ['hubConf', 'arenaConf', 'marketConf', 'galleryConf', 'dungeonConf'][index];
            const objKey = ['hubObj', 'arenaObj', 'marketObj', 'galleryObj', 'dungeonObj'][index];
            if (!snapshot[confKey] || typeof snapshot[confKey] !== 'object') {
                throw new Error(`worlds/${world}/config.json: invalid object`);
            }
            if (!Array.isArray(snapshot[objKey]?.objects)) {
                throw new Error(`worlds/${world}/objects.json: missing objects array`);
            }
        });

        return { snapshot: snapshot, optionalFailures: optionalFailures };
    },

    _applySnapshot(snapshot) {
        const oldIds = new Set((GameState.data.actions || []).map(action => action.id));
        const newActions = snapshot.actions.actions.filter(action => !oldIds.has(action.id));

        GameState.data.agents = snapshot.agents.agents;
        GameState.data.chat = snapshot.chat.messages;
        GameState.data.actions = snapshot.actions.actions;
        GameState.data.gameState = snapshot.gameState;
        GameState.data.worldConfigs = {
            hub: snapshot.hubConf,
            arena: snapshot.arenaConf,
            marketplace: snapshot.marketConf,
            gallery: snapshot.galleryConf,
            dungeon: snapshot.dungeonConf
        };
        GameState.data.worldObjects = {
            hub: snapshot.hubObj.objects,
            arena: snapshot.arenaObj.objects,
            marketplace: snapshot.marketObj.objects,
            gallery: snapshot.galleryObj.objects,
            dungeon: snapshot.dungeonObj.objects
        };

        if (Array.isArray(snapshot.npcs?.npcs)) GameState.data.npcs = snapshot.npcs.npcs;
        if (snapshot.frameCounter) GameState.data.frameCounter = snapshot.frameCounter;
        if (snapshot.brainstem?.agents) GameState.data.brainstem = snapshot.brainstem.agents;
        if (Array.isArray(snapshot.chronicles?.chronicles)) {
            GameState.data.chronicles = snapshot.chronicles;
            if (typeof Chronicle !== 'undefined') Chronicle.onData(snapshot.chronicles);
        }

        newActions.forEach(action => {
            if (['tip', 'trade_offer', 'enroll', 'challenge', 'defend'].includes(action.type)) {
                if (typeof WorldAgents !== 'undefined' && WorldAgents.showActionEffect && typeof WorldMode !== 'undefined' && WorldMode.scene) {
                    WorldAgents.showActionEffect(WorldMode.scene, action.agentId, action.type, action.data);
                }
            }
        });
    },

    async _fetchAndApply(generation, signal) {
        this._showStatus('Syncing...');
        this._setLiveState('SYNCING', '#00d4ff');
        try {
            const loaded = await this._loadSnapshot(signal);
            if (generation !== this._generation) return { ok: false, superseded: true };

            this._applySnapshot(loaded.snapshot);
            this.lastFetch = Date.now();
            this.lastSuccessfulFetch = this.lastFetch;

            if (loaded.optionalFailures.length) {
                this._showStatus('Degraded — optional state unavailable', true);
                this._setLiveState('DEGRADED', '#d29922');
            } else {
                this._showStatus(null);
                this._setLiveState('LIVE', '#00ff88');
            }

            if (GameState.debug) {
                console.log(`[DATA] Fetched from main: ${GameState.data.agents.length} agents, ${GameState.data.chat.length} msgs`);
            }

            if (typeof RappterVM !== 'undefined' && RappterVM._running) {
                RappterVM.onFrameArrival(GameState.data);
            }

            if (typeof EchoEngine !== 'undefined') {
                EchoEngine.captureFrame();
                if (EchoEngine.isLive()) EchoEngine.applyEchoToWorld();
                var slider = document.getElementById('timeline-slider');
                if (slider) {
                    slider.max = Math.max(0, EchoEngine.getFrameCount() - 1);
                    if (EchoEngine.isLive()) slider.value = slider.max;
                }
            }

            return { ok: true, degraded: loaded.optionalFailures.length > 0 };
        } catch(e) {
            if (generation !== this._generation) return { ok: false, superseded: true };
            const hasSnapshot = this.lastSuccessfulFetch > 0;
            this._showStatus(hasSnapshot ? 'Stale — using last known state' : 'Offline — state unavailable', true);
            this._setLiveState(hasSnapshot ? 'STALE' : 'OFFLINE', '#f85149');
            if (GameState.debug) console.warn('[DATA] Snapshot rejected:', e.message);
            return { ok: false, error: e };
        }
    },

    fetchAllState() {
        if (this._inFlight) return this._inFlight;

        const generation = ++this._generation;
        const controller = new AbortController();
        this._abortController = controller;
        const timeoutId = setTimeout(() => controller.abort(), 12000);

        const operation = this._fetchAndApply(generation, controller.signal).finally(() => {
            clearTimeout(timeoutId);
            if (this._inFlight === operation) this._inFlight = null;
            if (this._abortController === controller) this._abortController = null;
        });
        this._inFlight = operation;
        return operation;
    },

    _runPoll() {
        if (!this.polling) return;
        this.fetchAllState().finally(() => {
            if (this.polling) {
                this._pollId = setTimeout(() => this._runPoll(), POLL_INTERVAL);
            }
        });
    },

    startPolling() {
        if (this.polling) return;
        this.polling = true;
        this._runPoll();
    },

    stopPolling() {
        this.polling = false;
        if (this._pollId) {
            clearTimeout(this._pollId);
            this._pollId = null;
        }
        this._generation++;
        if (this._abortController) this._abortController.abort();
    }
};
