// Planet Approach — Cinematic Zoom
const Approach = {
    active: false,
    targetWorld: null,
    progress: 0,
    duration: 3000, // ms
    startTime: 0,

    start(worldId) {
        this.targetWorld = worldId;
        this.active = true;
        this.progress = 0;
        this.startTime = Date.now();
        GameState.setMode('approach');
        GameState.currentWorld = worldId;

        Galaxy.hide();

        const w = WORLDS[worldId];
        const overlay = document.getElementById('approach-overlay');
        overlay.classList.add('active');

        // Letterbox
        setTimeout(() => {
            document.getElementById('letterbox-top').classList.add('active');
            document.getElementById('letterbox-bottom').classList.add('active');
        }, 100);

        // Info
        document.getElementById('approach-name').textContent = w.name;
        const biomeEl = document.getElementById('approach-biome');
        biomeEl.textContent = w.biome;
        biomeEl.style.background = `rgba(${Galaxy.hexToRgb(w.planetColor)}, 0.2)`;
        biomeEl.style.color = `#${w.planetColor.toString(16).padStart(6, '0')}`;

        // Stats update loop
        this.updateStats();

        // Buttons
        document.getElementById('approach-land-btn').onclick = () => this.initiateLanding();
        document.getElementById('approach-skip-btn').onclick = () => this.abort();
    },

    updateStats() {
        if (!this.active) return;
        const elapsed = Date.now() - this.startTime;
        this.progress = Math.min(elapsed / this.duration, 1);

        const distance = Math.max(0, (1 - this.progress) * 1000).toFixed(0);
        const velocity = (12 + this.progress * 8).toFixed(1);
        const eta = Math.max(0, ((1 - this.progress) * 3)).toFixed(1);

        document.getElementById('approach-distance').textContent = distance + ' km';
        document.getElementById('approach-velocity').textContent = velocity + ' km/s';
        document.getElementById('approach-eta').textContent = eta + 's';

        if (this.active) requestAnimationFrame(() => this.updateStats());
    },

    initiateLanding() {
        this.cleanup();
        Landing.start(this.targetWorld);
    },

    abort() {
        this.cleanup();
        GameState.setMode('galaxy');
        Galaxy.show();
    },

    cleanup() {
        this.active = false;
        const overlay = document.getElementById('approach-overlay');
        overlay.classList.remove('active');
        document.getElementById('letterbox-top').classList.remove('active');
        document.getElementById('letterbox-bottom').classList.remove('active');
    }
};
