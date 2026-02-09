// HUD — Persistent UI Elements
const HUD = {
    minimapVisible: false,

    show() {
        document.getElementById('top-bar').classList.add('visible');
    },

    hide() {
        document.getElementById('top-bar').classList.remove('visible');
    },

    setWorld(worldId) {
        const w = WORLDS[worldId];
        document.getElementById('hud-world-name').textContent = w ? w.name : '';
    },

    updateAgentCount() {
        document.getElementById('hud-agent-count').textContent = GameState.data.agents.length + ' agents';
    },

    toggleMinimap() {
        this.minimapVisible = !this.minimapVisible;
        document.getElementById('minimap').classList.toggle('visible', this.minimapVisible);
        if (this.minimapVisible) this.renderMinimap();
    },

    renderMinimap() {
        if (!this.minimapVisible || GameState.mode !== 'world') return;
        const canvas = document.getElementById('minimap-canvas');
        const ctx = canvas.getContext('2d');
        const w = WORLDS[GameState.currentWorld];
        if (!w) return;

        ctx.fillStyle = '#050510';
        ctx.fillRect(0, 0, 160, 160);

        // Grid
        ctx.strokeStyle = 'rgba(255,255,255,0.04)';
        for (let i = 0; i <= 8; i++) {
            ctx.beginPath();
            ctx.moveTo(i * 20, 0); ctx.lineTo(i * 20, 160);
            ctx.moveTo(0, i * 20); ctx.lineTo(160, i * 20);
            ctx.stroke();
        }

        // Boundary
        const cx = 80, cz = 80;
        const maxB = Math.max(w.bounds.x, w.bounds.z) + 2;
        const sx = w.bounds.x / maxB * 70;
        const sz = w.bounds.z / maxB * 70;
        const accentHex = '#' + w.accent.toString(16).padStart(6, '0');
        ctx.strokeStyle = accentHex;
        ctx.globalAlpha = 0.25;
        ctx.strokeRect(cx - sx, cz - sz, sx * 2, sz * 2);
        ctx.globalAlpha = 1;

        // Agents
        const agents = GameState.getWorldAgents();
        agents.forEach(a => {
            const mx = cx + (a.position.x / maxB) * 70;
            const mz = cz + (a.position.z / maxB) * 70;
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(mx, mz, 2, 0, Math.PI * 2);
            ctx.fill();
        });

        // Player
        if (WorldMode.player) {
            const p = WorldMode.player.mesh.position;
            const px = cx + (p.x / maxB) * 70;
            const pz = cz + (p.z / maxB) * 70;
            ctx.fillStyle = '#00ffff';
            ctx.beginPath();
            ctx.arc(px, pz, 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#00ffff';
            ctx.lineWidth = 1;
            ctx.stroke();
        }
    },

    showToast(msg) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = msg;
        container.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(-10px)';
            toast.style.transition = 'all 0.3s ease';
            setTimeout(() => toast.remove(), 300);
        }, 3700);
    }
};
