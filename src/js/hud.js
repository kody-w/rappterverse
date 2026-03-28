// HUD — Persistent UI Elements
const HUD = {
    minimapVisible: false,

    show() {
        const el = document.getElementById('top-bar');
        if (el) el.classList.add('visible');
    },

    hide() {
        const el = document.getElementById('top-bar');
        if (el) el.classList.remove('visible');
    },

    setWorld(worldId) {
        const w = WORLDS[worldId];
        const el = document.getElementById('hud-world-name');
        if (el) el.textContent = w ? w.name : '';
    },

    updateAgentCount() {
        const el = document.getElementById('hud-agent-count');
        if (el) el.textContent = GameState.data.agents.length + ' agents';
    },

    toggleMinimap() {
        this.minimapVisible = !this.minimapVisible;
        const el = document.getElementById('minimap');
        if (el) el.classList.toggle('visible', this.minimapVisible);
        if (this.minimapVisible) this.renderMinimap();
    },

    _minimapTerrain: null,

    renderMinimap() {
        if (!this.minimapVisible || GameState.mode !== 'world') return;
        const canvas = document.getElementById('minimap-canvas');
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const worldId = GameState.currentWorld;
        const w = WORLDS[worldId];
        if (!w) return;

        const S = 220; // minimap pixel size
        canvas.width = S; canvas.height = S;
        const cx = S / 2, cz = S / 2;
        const maxB = Math.max(w.bounds.x, w.bounds.z) + 2;
        const scale = (S * 0.42) / maxB;

        // ── Terrain background (cached) ──
        if (!this._minimapTerrain || this._minimapTerrain.worldId !== worldId) {
            this._minimapTerrain = { worldId: worldId, img: null };
            var tCanvas = document.createElement('canvas');
            tCanvas.width = S; tCanvas.height = S;
            var tCtx = tCanvas.getContext('2d');
            var profile = typeof BIOME_PROFILES !== 'undefined' ? BIOME_PROFILES[w.biome] : null;
            var noise = typeof WorldTerrain !== 'undefined' && WorldTerrain._noise ? WorldTerrain._noise : null;
            if (profile && noise) {
                var terrainSize = typeof WorldTerrain !== 'undefined' ? WorldTerrain._terrainSize : maxB * 2;
                for (var py = 0; py < S; py += 2) {
                    for (var px = 0; px < S; px += 2) {
                        var wx = (px - cx) / scale;
                        var wz = (py - cz) / scale;
                        var nx = wx / terrainSize * profile.noiseScale;
                        var nz = wz / terrainSize * profile.noiseScale;
                        var h = noise.fbm(nx, nz, profile.octaves, profile.lacunarity, profile.gain) * profile.heightScale;
                        var maxH = profile.heightScale || 5;
                        var t = (h / maxH + 1) * 0.5;
                        var c = profile.color(t, h);
                        tCtx.fillStyle = 'rgb(' + Math.round(c[0]*255) + ',' + Math.round(c[1]*255) + ',' + Math.round(c[2]*255) + ')';
                        tCtx.fillRect(px, py, 2, 2);
                    }
                }
            } else {
                tCtx.fillStyle = '#' + w.floor.toString(16).padStart(6, '0');
                tCtx.fillRect(0, 0, S, S);
            }
            this._minimapTerrain.img = tCanvas;
        }
        ctx.drawImage(this._minimapTerrain.img, 0, 0);

        // ── Boundary ──
        var bx = w.bounds.x * scale, bz = w.bounds.z * scale;
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.strokeRect(cx - bx, cz - bz, bx * 2, bz * 2);

        // ── Lanes ──
        if (typeof WorldLanes !== 'undefined' && WorldLanes.lanes) {
            var laneColors = ['#58a6ff', '#f97316', '#3fb950'];
            WorldLanes.lanes.forEach(function(lane, li) {
                if (!lane.waypoints) return;
                ctx.strokeStyle = laneColors[li] || '#888';
                ctx.lineWidth = 1.5;
                ctx.globalAlpha = 0.4;
                ctx.beginPath();
                lane.waypoints.forEach(function(wp, i) {
                    var mx = cx + wp.x * scale, mz = cz + wp.z * scale;
                    if (i === 0) ctx.moveTo(mx, mz); else ctx.lineTo(mx, mz);
                });
                ctx.stroke();
                ctx.globalAlpha = 1;
            });
        }

        // ── Towers ──
        if (typeof WorldLanes !== 'undefined' && WorldLanes.towers) {
            WorldLanes.towers.forEach(function(t) {
                if (!t.mesh || !t.mesh.position) return;
                var mx = cx + t.mesh.position.x * scale;
                var mz = cz + t.mesh.position.z * scale;
                ctx.fillStyle = t.faction === 'explorer' ? '#58a6ff' : '#f85149';
                ctx.fillRect(mx - 2, mz - 2, 4, 4);
            });
        }

        // ── Portals ──
        if (typeof WorldAgents !== 'undefined' && WorldAgents.portalMeshes) {
            WorldAgents.portalMeshes.forEach(function(p) {
                if (!p.position) return;
                var mx = cx + p.position.x * scale;
                var mz = cz + p.position.z * scale;
                ctx.fillStyle = '#d29922';
                ctx.beginPath();
                ctx.arc(mx, mz, 3, 0, Math.PI * 2);
                ctx.fill();
            });
        }

        // ── Agents ──
        var agents = GameState.getWorldAgents();
        agents.forEach(function(a) {
            if (!a.position) return;
            var mx = cx + a.position.x * scale;
            var mz = cz + a.position.z * scale;
            ctx.fillStyle = 'rgba(255,255,255,0.6)';
            ctx.beginPath();
            ctx.arc(mx, mz, 1.5, 0, Math.PI * 2);
            ctx.fill();
        });

        // ── Enemy Hero ──
        if (typeof EnemyHero !== 'undefined' && EnemyHero.mesh && EnemyHero.state && EnemyHero.state.alive) {
            var hx = cx + EnemyHero.mesh.position.x * scale;
            var hz = cz + EnemyHero.mesh.position.z * scale;
            ctx.fillStyle = '#f85149';
            ctx.beginPath();
            ctx.arc(hx, hz, 3.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#ff0000';
            ctx.lineWidth = 1;
            ctx.stroke();
        }

        // ── Jungle Camps ──
        if (typeof JungleCamps !== 'undefined' && JungleCamps.camps) {
            JungleCamps.camps.forEach(function(camp) {
                if (!camp.alive) return;
                var mx = cx + camp.x * scale;
                var mz = cz + camp.z * scale;
                ctx.fillStyle = '#886644';
                ctx.beginPath();
                ctx.arc(mx, mz, camp.size === 'medium' ? 3 : 2, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = '#ffaa00';
                ctx.lineWidth = 0.5;
                ctx.stroke();
            });
        }

        // ── Player (arrow showing direction) ──
        if (typeof WorldMode !== 'undefined' && WorldMode.player && WorldMode.player.mesh) {
            var p = WorldMode.player.mesh.position;
            var px = cx + p.x * scale;
            var pz = cz + p.z * scale;
            var rot = WorldMode.player.mesh.rotation.y;

            ctx.save();
            ctx.translate(px, pz);
            ctx.rotate(-rot);
            ctx.fillStyle = '#00ffff';
            ctx.beginPath();
            ctx.moveTo(0, -5);
            ctx.lineTo(-3.5, 4);
            ctx.lineTo(0, 2);
            ctx.lineTo(3.5, 4);
            ctx.closePath();
            ctx.fill();
            ctx.strokeStyle = '#00ffff';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.restore();

            // Camera view cone
            ctx.save();
            ctx.translate(px, pz);
            ctx.rotate(-rot);
            ctx.fillStyle = 'rgba(0,212,255,0.06)';
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(-25, -50);
            ctx.lineTo(25, -50);
            ctx.closePath();
            ctx.fill();
            ctx.restore();
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

        const chatHeader = document.getElementById('chat-feed-header');
        if (chatHeader) chatHeader.addEventListener('click', () => {
            const feed = document.getElementById('chat-feed');
            if (feed) feed.classList.toggle('collapsed');
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
    },

    // ── Fullscreen Map ──────────────────────────────────────
    fullmapVisible: false,

    toggleFullmap() {
        this.fullmapVisible = !this.fullmapVisible;
        var el = document.getElementById('fullmap-overlay');
        if (el) el.classList.toggle('visible', this.fullmapVisible);
        if (this.fullmapVisible) this.renderFullmap();
    },

    renderFullmap() {
        var canvas = document.getElementById('fullmap-canvas');
        if (!canvas) return;
        var ctx = canvas.getContext('2d');
        var worldId = GameState.currentWorld;
        var w = WORLDS[worldId];
        if (!w) return;

        var S = 700;
        var cx = S / 2, cz = S / 2;
        var maxB = Math.max(w.bounds.x, w.bounds.z) + 2;
        var scale = (S * 0.42) / maxB;

        // Terrain
        var profile = typeof BIOME_PROFILES !== 'undefined' ? BIOME_PROFILES[w.biome] : null;
        var noise = typeof WorldTerrain !== 'undefined' && WorldTerrain._noise ? WorldTerrain._noise : null;
        if (profile && noise) {
            var terrainSize = typeof WorldTerrain !== 'undefined' ? WorldTerrain._terrainSize : maxB * 2;
            for (var py = 0; py < S; py += 3) {
                for (var px = 0; px < S; px += 3) {
                    var wx = (px - cx) / scale;
                    var wz = (py - cz) / scale;
                    var nx = wx / terrainSize * profile.noiseScale;
                    var nz = wz / terrainSize * profile.noiseScale;
                    var h = noise.fbm(nx, nz, profile.octaves, profile.lacunarity, profile.gain) * profile.heightScale;
                    var maxH = profile.heightScale || 5;
                    var t = (h / maxH + 1) * 0.5;
                    var c = profile.color(t, h);
                    ctx.fillStyle = 'rgb(' + Math.round(c[0]*255) + ',' + Math.round(c[1]*255) + ',' + Math.round(c[2]*255) + ')';
                    ctx.fillRect(px, py, 3, 3);
                }
            }
        } else {
            ctx.fillStyle = '#050510';
            ctx.fillRect(0, 0, S, S);
        }

        // Boundary
        var bx = w.bounds.x * scale, bz = w.bounds.z * scale;
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1;
        ctx.strokeRect(cx - bx, cz - bz, bx * 2, bz * 2);

        // Lanes
        if (typeof WorldLanes !== 'undefined' && WorldLanes.lanes) {
            var laneColors = ['#58a6ff', '#f97316', '#3fb950'];
            WorldLanes.lanes.forEach(function(lane, li) {
                if (!lane.waypoints) return;
                ctx.strokeStyle = laneColors[li] || '#888';
                ctx.lineWidth = 3;
                ctx.globalAlpha = 0.5;
                ctx.beginPath();
                lane.waypoints.forEach(function(wp, i) {
                    var mx = cx + wp.x * scale, mz = cz + wp.z * scale;
                    if (i === 0) ctx.moveTo(mx, mz); else ctx.lineTo(mx, mz);
                });
                ctx.stroke();
                ctx.globalAlpha = 1;
                // Lane name
                if (lane.waypoints.length > 2) {
                    var mid = lane.waypoints[Math.floor(lane.waypoints.length / 2)];
                    var lx = cx + mid.x * scale, lz = cz + mid.z * scale;
                    ctx.font = '10px monospace';
                    ctx.fillStyle = laneColors[li];
                    ctx.globalAlpha = 0.5;
                    ctx.textAlign = 'center';
                    ctx.fillText(lane.name || ('Lane ' + (li+1)), lx, lz - 8);
                    ctx.globalAlpha = 1;
                }
            });
        }

        // Towers
        if (typeof WorldLanes !== 'undefined' && WorldLanes.towers) {
            WorldLanes.towers.forEach(function(t) {
                if (!t.mesh || !t.mesh.position) return;
                var mx = cx + t.mesh.position.x * scale;
                var mz = cz + t.mesh.position.z * scale;
                ctx.fillStyle = t.faction === 'explorer' ? '#58a6ff' : '#f85149';
                ctx.fillRect(mx - 4, mz - 4, 8, 8);
                ctx.strokeStyle = 'rgba(255,255,255,0.3)';
                ctx.lineWidth = 1;
                ctx.strokeRect(mx - 4, mz - 4, 8, 8);
            });
        }

        // Portals
        if (typeof WorldAgents !== 'undefined' && WorldAgents.portalMeshes) {
            WorldAgents.portalMeshes.forEach(function(p) {
                if (!p.position) return;
                var mx = cx + p.position.x * scale;
                var mz = cz + p.position.z * scale;
                ctx.fillStyle = '#d29922';
                ctx.beginPath();
                ctx.arc(mx, mz, 6, 0, Math.PI * 2);
                ctx.fill();
                ctx.strokeStyle = 'rgba(210,153,34,0.5)';
                ctx.lineWidth = 2;
                ctx.stroke();
            });
        }

        // Agents with names
        var agents = GameState.getWorldAgents();
        ctx.font = '9px monospace';
        ctx.textAlign = 'center';
        agents.forEach(function(a) {
            if (!a.position) return;
            var mx = cx + a.position.x * scale;
            var mz = cz + a.position.z * scale;
            ctx.fillStyle = 'rgba(255,255,255,0.5)';
            ctx.beginPath();
            ctx.arc(mx, mz, 3, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = 'rgba(255,255,255,0.35)';
            ctx.fillText(a.name || a.id, mx, mz - 6);
        });

        // Enemy Hero
        if (typeof EnemyHero !== 'undefined' && EnemyHero.mesh && EnemyHero.state && EnemyHero.state.alive) {
            var hx = cx + EnemyHero.mesh.position.x * scale;
            var hz = cz + EnemyHero.mesh.position.z * scale;
            ctx.fillStyle = '#f85149';
            ctx.beginPath();
            ctx.arc(hx, hz, 7, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = '#ff0000';
            ctx.lineWidth = 2;
            ctx.stroke();
            ctx.fillStyle = '#fff';
            ctx.font = '10px monospace';
            ctx.fillText('RAVAGER', hx, hz - 10);
        }

        // Jungle Camps
        if (typeof JungleCamps !== 'undefined' && JungleCamps.camps) {
            JungleCamps.camps.forEach(function(camp) {
                var mx = cx + camp.x * scale;
                var mz = cz + camp.z * scale;
                if (camp.alive) {
                    ctx.fillStyle = '#886644';
                    ctx.beginPath();
                    ctx.arc(mx, mz, camp.size === 'medium' ? 6 : 4, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.strokeStyle = '#ffaa00';
                    ctx.lineWidth = 1;
                    ctx.stroke();
                    ctx.fillStyle = '#ffaa00';
                    ctx.font = '8px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(camp.size === 'medium' ? 'MED' : 'SM', mx, mz - 8);
                } else {
                    ctx.strokeStyle = 'rgba(136,102,68,0.3)';
                    ctx.beginPath();
                    ctx.arc(mx, mz, 4, 0, Math.PI * 2);
                    ctx.stroke();
                    ctx.fillStyle = 'rgba(255,170,0,0.3)';
                    ctx.font = '7px monospace';
                    ctx.textAlign = 'center';
                    ctx.fillText(Math.ceil(camp.respawnTimer) + 's', mx, mz + 3);
                }
            });
        }

        // Player
        if (typeof WorldMode !== 'undefined' && WorldMode.player && WorldMode.player.mesh) {
            var p = WorldMode.player.mesh.position;
            var px = cx + p.x * scale;
            var pz = cz + p.z * scale;
            var rot = WorldMode.player.mesh.rotation.y;

            // View cone
            ctx.save();
            ctx.translate(px, pz);
            ctx.rotate(-rot);
            ctx.fillStyle = 'rgba(0,212,255,0.05)';
            ctx.beginPath();
            ctx.moveTo(0, 0);
            ctx.lineTo(-60, -120);
            ctx.lineTo(60, -120);
            ctx.closePath();
            ctx.fill();
            ctx.restore();

            // Arrow
            ctx.save();
            ctx.translate(px, pz);
            ctx.rotate(-rot);
            ctx.fillStyle = '#00ffff';
            ctx.beginPath();
            ctx.moveTo(0, -8);
            ctx.lineTo(-5, 6);
            ctx.lineTo(0, 3);
            ctx.lineTo(5, 6);
            ctx.closePath();
            ctx.fill();
            ctx.restore();

            ctx.fillStyle = '#00ffff';
            ctx.font = 'bold 11px monospace';
            ctx.fillText('YOU', px, pz + 16);
        }

        // Header
        var headerEl = document.getElementById('fullmap-header');
        if (headerEl) headerEl.textContent = w.name.toUpperCase() + ' — WORLD MAP';
    },

    // ── Rappterbook-style panels ──────────────────────────

    showPanels() {
        const wp = document.getElementById('world-populations');
        if (wp) wp.classList.add('visible');
        const rt = document.getElementById('refresh-timer');
        if (rt) rt.classList.add('visible');
    },

    showWorldPanels() {
        this.showPanels();
        const uc = document.getElementById('universe-card');
        if (uc) uc.classList.add('visible');
        const rl = document.getElementById('relationship-legend');
        if (rl) rl.classList.add('visible');
    },

    hideWorldPanels() {
        const uc = document.getElementById('universe-card');
        if (uc) uc.classList.remove('visible');
        const rl = document.getElementById('relationship-legend');
        if (rl) rl.classList.remove('visible');
    },

    updateFrameCounter() {
        const el = document.getElementById('hud-frame');
        if (!el) return;
        const fc = GameState.data.frameCounter || {};
        el.textContent = 'Frame ' + (fc.frame || '---');
    },

    updateAgentDetail() {
        const el = document.getElementById('hud-agent-detail');
        if (!el) return;
        const worldId = GameState.currentWorld;
        const gs = GameState.data.gameState || {};
        const ws = gs.worlds && gs.worlds[worldId] ? gs.worlds[worldId] : {};
        const localPop = ws.population || GameState.getWorldAgents(worldId).length;
        const total = GameState.data.agents.length;
        el.textContent = localPop + '/' + total + ' agents';
    },

    updateWorldPopulations() {
        const el = document.getElementById('wp-list');
        if (!el) return;
        const gs = GameState.data.gameState || {};
        const worlds = gs.worlds || {};
        const biomeColors = {
            hub: '#4488ff', arena: '#ff4422', marketplace: '#ffaa00',
            gallery: '#00ddaa', dungeon: '#6a0dad'
        };
        el.innerHTML = WORLD_IDS.map(function(id) {
            const w = WORLDS[id];
            const pop = worlds[id] ? (worlds[id].population || 0) : 0;
            const color = biomeColors[id];
            const active = id === GameState.currentWorld ? ' wp-active' : '';
            return '<div class="wp-item' + active + '" data-world="' + id + '">' +
                '<span>' + w.name + ' (' + pop + ')</span>' +
                '<div class="wp-dot" style="background:' + color + ';box-shadow:0 0 6px ' + color + ';"></div>' +
                '</div>';
        }).join('');
    },

    updateUniverseCard() {
        const textEl = document.getElementById('uc-text');
        const metaEl = document.getElementById('uc-meta');
        if (!textEl || !metaEl) return;
        const gs = GameState.data.gameState || {};
        const fc = GameState.data.frameCounter || {};
        const worldId = GameState.currentWorld;
        const seed = typeof WorldSeed !== 'undefined' ? WorldSeed.getSeed(worldId) : '---';
        const w = WORLDS[worldId];
        const ws = gs.worlds && gs.worlds[worldId] ? gs.worlds[worldId] : {};
        const pop = ws.population || 0;
        const trend = (gs.economy && gs.economy.market_trend) ? gs.economy.market_trend : 'stable';
        const weather = ws.weather || 'clear';
        const totalAgents = GameState.data.agents.length;

        textEl.innerHTML = 'Seed <span class="uc-seed">' + seed + '</span> · ' +
            w.biome + ' biome · ' + pop + ' local / ' + totalAgents + ' total agents';

        // Echo enrichment layer
        var echoInfo = '';
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes) {
                var L3 = ef.echoes.L3 || {};
                var L6 = ef.echoes.L6 || {};
                echoInfo = '<span style="color:#d29922">Echo L' + Math.round((L6.enrichableDetail || {}).narrativeDepth || 1) + '</span>';
                echoInfo += '<span>T:' + ((L3.tension || 0) * 100).toFixed(0) + '%</span>';
                echoInfo += '<span>V:' + ((L3.vitality || 0) * 100).toFixed(0) + '%</span>';
            }
        }
        metaEl.innerHTML = echoInfo + '<span>Frame ' + (fc.frame || '---') + '</span>' +
            '<span>Economy: ' + trend + '</span>' +
            '<span>Weather: ' + weather + '</span>';
    },

    updateRefreshTimer() {
        const el = document.getElementById('refresh-timer');
        if (!el) return;
        const since = Date.now() - (DataManager.lastFetch || 0);
        const remaining = Math.max(0, Math.ceil((POLL_INTERVAL - since) / 1000));
        el.textContent = 'Next refresh: ' + remaining + 's';
    },

    // Update all Rappterbook-style panels at once
    updatePanels() {
        this.updateFrameCounter();
        this.updateAgentDetail();
        this.updateWorldPopulations();
        if (GameState.mode === 'world') {
            this.updateUniverseCard();
            if (typeof QuestTracker !== 'undefined') QuestTracker.update();
        }
        this.updateRefreshTimer();
    }
};
