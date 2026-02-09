// Bridge — Ship Command Interface
const Bridge = {
    open: false,

    toggle() {
        this.open ? this.close() : this.show();
    },

    show() {
        this.open = true;
        GameState.bridgeOpen = true;
        document.getElementById('bridge-overlay').classList.add('active');
        this.render();
    },

    close() {
        this.open = false;
        GameState.bridgeOpen = false;
        document.getElementById('bridge-overlay').classList.remove('active');
    },

    render() {
        if (!this.open) return;
        this.renderAgents();
        this.renderChat();
        this.renderActions();
        this.renderEconomy();
        this.renderWorlds();
        this.renderNav();
    },

    renderAgents() {
        const el = document.getElementById('bridge-agents');
        el.innerHTML = GameState.data.agents.map(a => `
            <div class="bridge-agent-item">
                <div class="bridge-agent-avatar">${a.avatar || '🤖'}</div>
                <div style="flex:1;min-width:0">
                    <div class="bridge-agent-name">${this.esc(a.name)}</div>
                    <div style="display:flex;gap:4px;align-items:center;margin-top:2px">
                        <span class="bridge-agent-status-dot ${a.status || 'active'}"></span>
                        <span class="bridge-agent-world">${a.world}</span>
                        <span style="font-size:9px;color:#888">${a.action || 'idle'}</span>
                    </div>
                </div>
            </div>
        `).join('');
    },

    renderChat() {
        const msgs = GameState.getWorldChat().slice(-20);
        const el = document.getElementById('bridge-chat');
        el.innerHTML = msgs.map(m => {
            const color = m.author?.type === 'npc-core' ? '#fb0' :
                         m.author?.type === 'agent' ? '#0ff' : '#fff';
            return `
                <div class="bridge-chat-msg">
                    <div class="bridge-chat-author" style="color:${color}">
                        ${m.author?.avatar || '💬'} ${this.esc(m.author?.name || '?')}
                    </div>
                    <div class="bridge-chat-text">${this.esc(m.content || '')}</div>
                    <div class="bridge-chat-time">${this.fmtTime(m.timestamp)}</div>
                </div>
            `;
        }).join('');
        el.scrollTop = el.scrollHeight;
    },

    renderActions() {
        const actions = GameState.getWorldActions().slice(-15);
        const el = document.getElementById('bridge-actions');
        el.innerHTML = actions.map(a => {
            let detail = '';
            switch(a.type) {
                case 'move': detail = `→ (${a.data?.to?.x}, ${a.data?.to?.z})`; break;
                case 'chat': detail = `"${(a.data?.message || '').slice(0, 40)}"`; break;
                case 'emote': detail = a.data?.emote || ''; break;
                case 'spawn': detail = `joined ${a.world}`; break;
                default: detail = a.type;
            }
            return `
                <div class="bridge-action-item ${a.type}">
                    <strong>${GameState.getAgentName(a.agentId)}</strong> ${detail}
                </div>
            `;
        }).join('');
    },

    renderEconomy() {
        const econ = GameState.data.gameState?.economy || {};
        const el = document.getElementById('bridge-economy');
        el.innerHTML = `
            <div class="bridge-econ-stat"><span class="bridge-econ-label">RAPPcoin Supply</span><span class="bridge-econ-value">${(econ.total_rappcoin_circulation || 0).toLocaleString()}</span></div>
            <div class="bridge-econ-stat"><span class="bridge-econ-label">Market Trend</span><span class="bridge-econ-value">${econ.market_trend || 'stable'}</span></div>
            <div class="bridge-econ-stat"><span class="bridge-econ-label">Common Cards</span><span class="bridge-econ-value">${econ.card_prices?.common_base || '—'} RC</span></div>
            <div class="bridge-econ-stat"><span class="bridge-econ-label">Rare Cards</span><span class="bridge-econ-value">${econ.card_prices?.rare_base || '—'} RC</span></div>
            <div class="bridge-econ-stat"><span class="bridge-econ-label">Epic Cards</span><span class="bridge-econ-value">${econ.card_prices?.epic_base || '—'} RC</span></div>
            <div class="bridge-econ-stat"><span class="bridge-econ-label">Mining Today</span><span class="bridge-econ-value">${econ.mined_today || 0} / ${econ.daily_mining_cap || 1000}</span></div>
        `;
    },

    renderWorlds() {
        const worlds = GameState.data.gameState?.worlds || {};
        const el = document.getElementById('bridge-worlds');
        el.innerHTML = WORLD_IDS.map(id => {
            const w = worlds[id] || {};
            const conf = WORLDS[id];
            const agents = GameState.getAgentCount(id);
            return `
                <div style="padding:8px;border-bottom:1px solid rgba(255,255,255,0.04)">
                    <div style="font-size:13px;color:#fff;margin-bottom:4px">${conf.name}</div>
                    <div style="font-size:10px;color:#888;display:flex;gap:8px;flex-wrap:wrap">
                        <span>👥 ${agents}</span>
                        <span>☁️ ${w.weather || 'clear'}</span>
                        <span>🕐 ${w.time_of_day || 'day'}</span>
                        <span style="color:${w.status === 'online' ? '#00ff88' : '#ff4444'}">${w.status || 'online'}</span>
                    </div>
                    ${w.active_events?.length ? `<div style="font-size:9px;color:#fb0;margin-top:2px">🎉 ${w.active_events.join(', ')}</div>` : ''}
                </div>
            `;
        }).join('');
    },

    renderNav() {
        const el = document.getElementById('bridge-nav');
        el.innerHTML = WORLD_IDS.map(id => {
            const w = WORLDS[id];
            const isCurrent = GameState.currentWorld === id && GameState.mode === 'world';
            return `<button class="bridge-travel-btn ${isCurrent ? 'current' : ''}"
                onclick="Bridge.travelTo('${id}')">${isCurrent ? '📍' : '🚀'} ${w.name}</button>`;
        }).join('');
    },

    travelTo(worldId) {
        this.close();
        if (GameState.mode === 'world') WorldMode.cleanup();
        if (GameState.mode === 'galaxy') Galaxy.hide();
        Approach.start(worldId);
    },

    esc(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    fmtTime(ts) {
        if (!ts) return '';
        return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
};
