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
    },

    // ── Live Chat Feed ──────────────────────────────────────
    chatFeedVisible: true,
    chatFeedLastCount: 0,

    initChatFeed() {
        // Create chat feed panel if it doesn't exist
        if (document.getElementById('chat-feed')) return;
        const panel = document.createElement('div');
        panel.id = 'chat-feed';
        panel.innerHTML = `
            <div id="chat-feed-header">
                <span>💬 World Chat</span>
                <button id="chat-feed-toggle" title="Toggle chat">▼</button>
            </div>
            <div id="chat-feed-messages"></div>
        `;
        document.body.appendChild(panel);

        // Style it
        const style = document.createElement('style');
        style.textContent = `
            #chat-feed {
                position: fixed; bottom: 80px; left: 12px; width: 360px; max-height: 280px;
                background: rgba(10, 15, 20, 0.85); border: 1px solid rgba(255,255,255,0.1);
                border-radius: 8px; font-family: 'Consolas','Monaco',monospace; font-size: 12px;
                z-index: 90; overflow: hidden; pointer-events: auto;
                backdrop-filter: blur(8px); transition: max-height 0.3s ease;
            }
            #chat-feed.collapsed { max-height: 32px; }
            #chat-feed-header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 6px 10px; color: #00d4ff; font-weight: bold; font-size: 11px;
                border-bottom: 1px solid rgba(255,255,255,0.05); cursor: pointer;
            }
            #chat-feed-toggle {
                background: none; border: none; color: rgba(255,255,255,0.4);
                font-size: 10px; cursor: pointer; padding: 2px 6px;
            }
            #chat-feed.collapsed #chat-feed-toggle { transform: rotate(-90deg); }
            #chat-feed-messages {
                padding: 6px 10px; max-height: 240px; overflow-y: auto;
                scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.1) transparent;
            }
            #chat-feed-messages::-webkit-scrollbar { width: 4px; }
            #chat-feed-messages::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 2px; }
            .chat-msg {
                margin-bottom: 6px; line-height: 1.4; animation: chatFadeIn 0.3s ease;
            }
            .chat-msg .chat-author {
                color: #00d4ff; font-weight: bold; margin-right: 4px;
            }
            .chat-msg .chat-world {
                font-size: 9px; padding: 1px 4px; border-radius: 4px;
                background: rgba(255,255,255,0.06); color: rgba(255,255,255,0.35);
                margin-right: 4px;
            }
            .chat-msg .chat-text { color: rgba(255,255,255,0.7); }
            .chat-msg .chat-time { color: rgba(255,255,255,0.2); font-size: 10px; margin-left: 6px; }
            @keyframes chatFadeIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }
        `;
        document.head.appendChild(style);

        document.getElementById('chat-feed-header').addEventListener('click', () => {
            document.getElementById('chat-feed').classList.toggle('collapsed');
        });
    },

    updateChatFeed() {
        const container = document.getElementById('chat-feed-messages');
        if (!container) return;

        const currentWorld = GameState.currentWorld;
        // Show all worlds, highlight current
        const msgs = (GameState.data.chat || []).slice(-20);

        if (msgs.length === this.chatFeedLastCount) return;
        this.chatFeedLastCount = msgs.length;

        container.innerHTML = msgs.map(m => {
            const author = m.author?.name || m.author?.id || '?';
            const avatar = m.author?.avatar || '🤖';
            const world = m.world || '?';
            const text = (m.content || '').substring(0, 120);
            const isCurrentWorld = world === currentWorld;
            const opacity = isCurrentWorld ? '1' : '0.5';
            const ts = m.timestamp ? this._chatTimeAgo(m.timestamp) : '';
            return `<div class="chat-msg" style="opacity:${opacity}">
                <span class="chat-world">${world}</span>
                <span class="chat-author">${avatar} ${author}</span>
                <span class="chat-text">${text}</span>
                <span class="chat-time">${ts}</span>
            </div>`;
        }).join('');

        container.scrollTop = container.scrollHeight;
    },

    _chatTimeAgo(iso) {
        try {
            const diff = (Date.now() - new Date(iso).getTime()) / 1000;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h';
            return Math.floor(diff / 86400) + 'd';
        } catch(e) { return ''; }
    }
};
