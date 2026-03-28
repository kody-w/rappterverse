// Debug Overlay — Hidden diagnostics panel (Ctrl+Shift+D to toggle)
// Shows real-time interaction state for troubleshooting poke/interact issues.
// Completely invisible when off. No performance cost when disabled.

const DebugOverlay = {
    active: false,
    el: null,
    log: [],

    toggle() {
        this.active = !this.active;
        GameState.debug = this.active;
        if (this.active) {
            this._create();
            this.el.style.display = 'block';
            console.log('[DEBUG] Overlay ON — verbose logging enabled');
        } else if (this.el) {
            this.el.style.display = 'none';
            console.log('[DEBUG] Overlay OFF');
        }
    },

    _create() {
        if (this.el) return;
        this.el = document.createElement('div');
        this.el.id = 'debug-overlay';
        this.el.style.cssText = `
            position: fixed; bottom: 10px; left: 10px; z-index: 99999;
            background: rgba(0,0,0,0.85); border: 1px solid #333;
            padding: 8px 12px; border-radius: 6px; font-family: monospace;
            font-size: 11px; color: #0f0; line-height: 1.6;
            pointer-events: none; max-width: 380px; white-space: pre;
        `;
        document.body.appendChild(this.el);
    },

    // Call every frame from WorldMode.update when active
    update(playerPos) {
            // Echo VM stats
            var vmEl = document.getElementById('debug-vm');
            if (!vmEl) {
                vmEl = document.createElement('div');
                vmEl.id = 'debug-vm';
                vmEl.style.cssText = 'margin-top:4px;font-size:9px;color:#d29922;';
                var panel = document.getElementById('debug-overlay');
                if (panel) panel.appendChild(vmEl);
            }
            if (vmEl && typeof RappterVM !== 'undefined') {
                vmEl.textContent = 'VM ticks: ' + RappterVM._tickCount + ' | Programs: ' + Object.keys(RappterVM._programs).length + ' | Reflexes: ' + RappterVM._reflexes.length;
                if (typeof EchoEngine !== 'undefined') {
                    vmEl.textContent += ' | Frames: ' + EchoEngine.getFrameCount() + ' | ' + (EchoEngine.isLive() ? 'LIVE' : 'SCRUBBING');
                }
            }
        if (!this.active || !this.el) return;

        const meshCount = Object.keys(WorldAgents.agentMeshes || {}).length;
        const pokeT = WorldAgents.pokeTarget;
        const interT = WorldAgents.interactTarget;
        const prompt = document.getElementById('interaction-prompt');
        const promptVisible = prompt ? prompt.classList.contains('visible') : false;
        const promptText = prompt ? prompt.textContent : '(none)';

        // Find nearest agent distance for display
        let nearestId = '—';
        let nearestDist = '—';
        if (playerPos) {
            let best = Infinity;
            Object.entries(WorldAgents.agentMeshes || {}).forEach(([id, mesh]) => {
                const p = mesh.group.position;
                const d = Math.sqrt((playerPos.x - p.x) ** 2 + (playerPos.z - p.z) ** 2);
                if (d < best) { best = d; nearestId = id; nearestDist = d.toFixed(2); }
            });
        }

        const px = playerPos ? playerPos.x.toFixed(1) : '?';
        const pz = playerPos ? playerPos.z.toFixed(1) : '?';

        const lines = [
            `🔧 DEBUG OVERLAY`,
            `mode:     ${GameState.mode}`,
            `world:    ${GameState.currentWorld || '—'}`,
            `player:   (${px}, ${pz})`,
            `meshes:   ${meshCount}`,
            `nearest:  ${nearestId} @ ${nearestDist}`,
            `pokeTarget:    ${pokeT ? pokeT.id + ' "' + pokeT.name + '"' : 'null'}`,
            `interTarget:   ${interT ? (interT.name || interT.type) : 'null'}`,
            `prompt:   ${promptVisible ? '✅' : '❌'} ${promptText}`,
            `lastKey:  ${this._lastKey || '—'}`,
            ``,
            ...this.log.slice(-5),
        ];

        this.el.textContent = lines.join('\n');
    },

    // Log a debug event (keeps last 10)
    logEvent(msg) {
        const ts = new Date().toISOString().slice(11, 19);
        this.log.push(`[${ts}] ${msg}`);
        if (this.log.length > 10) this.log.shift();
        console.log(`[DEBUG] ${msg}`);
    },

    // Track last keypress
    recordKey(code) {
        this._lastKey = code;
    },
};
