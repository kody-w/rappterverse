// Game State Machine
const GameState = {
    mode: 'boot', // boot, galaxy, approach, landing, world, bridge
    previousMode: null,
    currentWorld: 'hub',
    selectedPlanet: null,
    bridgeOpen: false,
    minimapVisible: true,

    // Shared Three.js refs (assigned by each mode)
    renderer: null,
    clock: null,

    // Live data from GitHub
    data: {
        agents: [],
        chat: [],
        actions: [],
        npcs: [],
        gameState: {},
        worldConfigs: {},
        worldObjects: {}
    },

    setMode(newMode) {
        const valid = ['boot', 'galaxy', 'approach', 'landing', 'world'];
        if (!valid.includes(newMode)) return false;
        console.log(`[STATE] ${this.mode} → ${newMode}`);
        this.previousMode = this.mode;
        this.mode = newMode;
        return true;
    },

    getWorldAgents(worldId) {
        const id = worldId || this.currentWorld;
        return this.data.agents.filter(a => a.world === id);
    },

    getWorldChat(worldId) {
        const id = worldId || this.currentWorld;
        return this.data.chat.filter(m => m.world === id || m.world === 'all');
    },

    getWorldActions(worldId) {
        const id = worldId || this.currentWorld;
        return this.data.actions.filter(a => a.world === id);
    },

    getWorldConfig(worldId) {
        return this.data.worldConfigs[worldId || this.currentWorld] || {};
    },

    getWorldObjects(worldId) {
        return this.data.worldObjects[worldId || this.currentWorld] || [];
    },

    getAgentName(id) {
        const a = this.data.agents.find(a => a.id === id);
        return a ? a.name : id;
    },

    getAgentCount(worldId) {
        if (worldId) return this.data.agents.filter(a => a.world === worldId).length;
        return this.data.agents.length;
    }
};
