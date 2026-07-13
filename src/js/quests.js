// Quest Tracker — surfaces quests from game_state.json
const QuestTracker = {
    _el: null,
    _lastUpdate: 0,
    _visible: false,

    init() {
        if (this._el) return;
        const el = document.createElement('div');
        el.id = 'quest-tracker';
        el.innerHTML = `
            <div class="qt-header">
                <span class="qt-title">ACTIVE QUEST</span>
                <button class="qt-toggle" id="qt-toggle-btn">▼</button>
            </div>
            <div class="qt-body" id="qt-body"></div>
        `;
        const style = document.createElement('style');
        style.textContent = `
            #quest-tracker {
                position: fixed; top: 56px; left: 12px;
                width: 260px; z-index: 900;
                background: rgba(22, 27, 34, 0.88);
                border: 1px solid rgba(48, 54, 61, 0.6);
                border-radius: 10px;
                backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
                font-family: 'SF Mono', monospace;
                display: none; overflow: hidden;
                transition: max-height 0.3s ease;
            }
            #quest-tracker.visible { display: block; }
            #quest-tracker.collapsed .qt-body { display: none; }
            .qt-header {
                display: flex; justify-content: space-between; align-items: center;
                padding: 8px 12px; cursor: pointer;
            }
            .qt-title {
                font-size: 9px; font-weight: 700; letter-spacing: 1.5px;
                color: #d29922;
            }
            .qt-toggle {
                background: none; border: none; color: #8b949e;
                font-size: 10px; cursor: pointer; padding: 2px 6px;
            }
            #quest-tracker.collapsed .qt-toggle { transform: rotate(-90deg); }
            .qt-body { padding: 4px 12px 10px; }
            .qt-name {
                font-size: 12px; font-weight: 600; color: #e6edf3;
                margin-bottom: 4px;
            }
            .qt-desc {
                font-size: 10px; color: #8b949e;
                margin-bottom: 8px; line-height: 1.4;
            }
            .qt-step {
                display: flex; align-items: center; gap: 6px;
                padding: 2px 0; font-size: 10px; color: #8b949e;
            }
            .qt-check {
                width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid rgba(255,255,255,0.15);
                display: flex; align-items: center; justify-content: center;
                font-size: 9px; flex-shrink: 0;
            }
            .qt-check.done { background: rgba(0,255,136,0.2); border-color: rgba(0,255,136,0.4); color: #00ff88; }
            .qt-reward {
                margin-top: 8px; padding-top: 6px;
                border-top: 1px solid rgba(48,54,61,0.4);
                font-size: 9px; color: #8b949e;
            }
            .qt-reward span { color: #d29922; font-weight: 600; }
            .qt-empty {
                font-size: 10px; color: #484f58; font-style: italic;
                padding: 4px 0;
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(el);
        this._el = el;

        document.getElementById('qt-toggle-btn').addEventListener('click', (e) => {
            e.stopPropagation();
            el.classList.toggle('collapsed');
        });
        el.querySelector('.qt-header').addEventListener('click', () => {
            el.classList.toggle('collapsed');
        });
    },

    show() {
        if (!this._el) this.init();
        this._el.classList.add('visible');
        this._visible = true;
        this.update();
    },

    hide() {
        if (this._el) this._el.classList.remove('visible');
        this._visible = false;
    },

    update() {
        if (!this._visible || !this._el) return;
        const now = Date.now();
        if (now - this._lastUpdate < 3000) return;
        this._lastUpdate = now;

        const gs = GameState.data.gameState || {};
        const quests = gs.quests || {};
        const active = (quests.active || []);
        const body = document.getElementById('qt-body');
        if (!body) return;

        if (active.length === 0) {
            // Echo-generated quest suggestion when no quests exist
            var echoQuest = '';
            if (typeof EchoEngine !== 'undefined') {
                var ef = EchoEngine.getCurrentFrame();
                if (ef && ef.echoes && ef.echoes.L3) {
                    var L3 = ef.echoes.L3;
                    if (L3.tension > 0.6) echoQuest = 'The echo whispers: defeat the boss to calm the storm.';
                    else if (L3.socialEnergy > 0.6) echoQuest = 'The echo hums: agents are social — join the conversation.';
                    else if (L3.vitality > 0.6) echoQuest = 'The echo glows: the world thrives — explore new territory.';
                    else if (L3.tension < 0.2 && L3.vitality < 0.3) echoQuest = 'The echo is silent... something stirs.';
                    else echoQuest = 'The echo pulses gently. Seek your own path.';
                }
            }
            body.innerHTML = '<div class="qt-empty">' + (echoQuest || 'No active quests') + '</div>';
            return;
        }

        // Show the first active quest
        const q = active[0];
        const steps = (q.steps || []).map(function(s) {
            const done = s.completed;
            // Auto-detect completion from game state
            let autoComplete = false;
            if (s.action === 'visit_hub' && GameState.currentWorld === 'hub') autoComplete = true;
            if (s.action === 'talk_to_guide') {
                const poked = [
                    ...(GameState.data.chat || []),
                    ...(GameState.data.localChat || [])
                ].some(function(m) {
                    return m.type === 'poke' && m.content && m.content.includes('rapp-guide');
                });
                if (poked) autoComplete = true;
            }
            const completed = done || autoComplete;
            return '<div class="qt-step">' +
                '<div class="qt-check' + (completed ? ' done' : '') + '">' + (completed ? '✓' : '') + '</div>' +
                '<span>' + escapeHTML((s.action || '').replace(/_/g, ' ')) + '</span></div>';
        }).join('');

        const rewards = q.rewards || {};
        const rewardHtml = rewards.rappcoin ?
            '<div class="qt-reward">Canonical reward: <span>' + escapeHTML(rewards.rappcoin) + ' RAPP</span> (not awarded in local practice)</div>' : '';

        body.innerHTML = '<div class="qt-name">' + escapeHTML(q.name || 'Quest') + '</div>' +
            '<div class="qt-desc">' + escapeHTML(q.description || '') + '</div>' +
            steps + rewardHtml;
    }
};
