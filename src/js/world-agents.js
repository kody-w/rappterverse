// World Agents — NPC Meshes, Portals, Screens, Decorations, Interactions
const WorldAgents = {
    agentMeshes: {},
    portalMeshes: [],
    objectMeshes: [],
    floatingTexts: [],
    interactTarget: null,
    pokeTarget: null,
    _edgeLines: null,
    _lastEdgeUpdate: 0,

    syncAgents(scene, worldId) {
        const agents = GameState.getWorldAgents(worldId);
        const currentIds = new Set(agents.map(a => a.id));

        // Remove departed agents
        Object.keys(this.agentMeshes).forEach(id => {
            if (!currentIds.has(id)) {
                scene.remove(this.agentMeshes[id].group);
                delete this.agentMeshes[id];
            }
        });

        // Add/update
        agents.forEach(agent => {
            if (!this.agentMeshes[agent.id]) {
                this.createAgentMesh(scene, agent, worldId);
            } else {
                this.agentMeshes[agent.id].targetPos.set(agent.position.x, 0, agent.position.z);
            }
        });
    },

    createAgentMesh(scene, agent, worldId) {
        const w = WORLDS[worldId];
        const group = new THREE.Group();

        // Body
        const bodyGeo = new THREE.CylinderGeometry(0.35, 0.35, 1.05, 8);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: w.accent, emissive: w.accent, emissiveIntensity: 0.2,
            roughness: 0.3, metalness: 0.7, transparent: true, opacity: 0.85
        });
        const body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = 0.9;
        group.add(body);

        // Head
        const headGeo = new THREE.SphereGeometry(0.25, 8, 8);
        const headMat = new THREE.MeshStandardMaterial({
            color: 0xffffff, emissive: w.accent, emissiveIntensity: 0.4,
            roughness: 0.2, metalness: 0.5
        });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.y = 1.65;
        group.add(head);

        // Emoji sprite
        const emojiCanvas = document.createElement('canvas');
        emojiCanvas.width = 128; emojiCanvas.height = 128;
        const ectx = emojiCanvas.getContext('2d');
        ectx.font = '72px serif';
        ectx.textAlign = 'center';
        ectx.textBaseline = 'middle';
        ectx.fillText(agent.avatar || '🤖', 64, 64);
        const emoji = new THREE.Sprite(new THREE.SpriteMaterial({
            map: new THREE.CanvasTexture(emojiCanvas), transparent: true
        }));
        emoji.position.y = 2.5;
        emoji.scale.set(0.8, 0.8, 1);
        group.add(emoji);

        // Name label
        const nameCanvas = document.createElement('canvas');
        nameCanvas.width = 256; nameCanvas.height = 48;
        const nctx = nameCanvas.getContext('2d');
        nctx.font = 'bold 18px monospace';
        nctx.textAlign = 'center';
        nctx.fillStyle = '#ffffff';
        nctx.fillText(agent.name, 128, 30);
        const nameSprite = new THREE.Sprite(new THREE.SpriteMaterial({
            map: new THREE.CanvasTexture(nameCanvas), transparent: true, opacity: 0.7
        }));
        nameSprite.position.y = 3.2;
        nameSprite.scale.set(2.2, 0.4, 1);
        group.add(nameSprite);

        // Ground ring
        const ringGeo = new THREE.RingGeometry(0.4, 0.55, 12);
        const ringMat = new THREE.MeshBasicMaterial({
            color: w.accent, side: THREE.DoubleSide, transparent: true, opacity: 0.3
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        // Speech bubble (initially hidden)
        const bubbleCanvas = document.createElement('canvas');
        bubbleCanvas.width = 640; bubbleCanvas.height = 128;
        const bctx = bubbleCanvas.getContext('2d');
        const bubbleTex = new THREE.CanvasTexture(bubbleCanvas);
        const bubble = new THREE.Sprite(new THREE.SpriteMaterial({
            map: bubbleTex, transparent: true, opacity: 0
        }));
        bubble.position.y = 4.5;
        bubble.scale.set(7, 1.4, 1);
        group.add(bubble);

        group.position.set(agent.position.x, 0, agent.position.z);
        scene.add(group);
        this.agentMeshes[agent.id] = {
            group, body, head, ring, bubble, bubbleCanvas, bubbleTex,
            targetPos: new THREE.Vector3(agent.position.x, 0, agent.position.z),
            homePos: new THREE.Vector3(agent.position.x, 0, agent.position.z),
            wanderTarget: null,
            behaviorTimer: Math.random() * 8,
            behaviorState: 'idle',
            stateTimer: 0,
            lookDir: 0,
            socialTarget: null,
            bubbleTimer: 0,
            pokeReaction: 0,
            // Brainstem template visual cache — set once on template change,
            // animated per-frame from these baselines (see applyTemplateStyle).
            template: null,
            templateStyle: null,
            worldAccent: w.accent,
        };
    },

    // Per-template visual signature. Tactical state from compiled lispy
    // programs (state/programs/_lispvm/_status.json) drives ring color,
    // emissive baseline, bob cadence, and a gentle facing bias. The
    // existing Animal-Crossing locomotion keeps running underneath — this
    // is a presentation layer, not a replacement.
    TEMPLATE_STYLES: {
        engaging:    { ring: 0xff3b3b, ringOpacity: 0.75, emissive: 0xff5050, glow: 0.55, bob: 4.0,  bias: 'threat' },
        fleeing:     { ring: 0xffffff, ringOpacity: 0.35, emissive: 0x6688aa, glow: 0.10, bob: 6.0,  bias: 'awayFromThreat' },
        retreating:  { ring: 0xff9933, ringOpacity: 0.45, emissive: 0xaa6633, glow: 0.20, bob: 3.5,  bias: 'awayFromThreat' },
        pushing:     { ring: null,     ringOpacity: 0.55, emissive: null,     glow: 0.45, bob: 2.5,  bias: null },           // ring=null → use worldAccent
        supporting:  { ring: 0x3fb950, ringOpacity: 0.65, emissive: 0x5fcf70, glow: 0.40, bob: 2.0,  bias: 'hurtAlly' },
        socializing: { ring: 0xff6ec7, ringOpacity: 0.55, emissive: 0xff6ec7, glow: 0.35, bob: 1.8,  bias: 'topBond' },
        roaming:     { ring: null,     ringOpacity: 0.30, emissive: null,     glow: 0.20, bob: 1.5,  bias: null },
    },

    applyTemplateStyle(a, template) {
        if (a.template === template) return;
        const style = this.TEMPLATE_STYLES[template] || this.TEMPLATE_STYLES.roaming;
        const ringHex = style.ring !== null ? style.ring : a.worldAccent;
        const emiHex  = style.emissive !== null ? style.emissive : a.worldAccent;
        if (a.ring && a.ring.material) {
            a.ring.material.color.setHex(typeof ringHex === 'number' ? ringHex : parseInt(String(ringHex).replace('#',''), 16));
            a.ring.material.opacity = style.ringOpacity;
        }
        if (a.body && a.body.material) {
            a.body.material.emissive.setHex(typeof emiHex === 'number' ? emiHex : parseInt(String(emiHex).replace('#',''), 16));
        }
        a.template = template;
        a.templateStyle = style;
    },

    // Look up a brainstem-named target (threat_top, top_bond_partner, hurt_ally)
    // and return its current world position, or null if not loaded in this
    // world's mesh set.
    _lookupTargetPos(targetId) {
        if (!targetId) return null;
        const m = this.agentMeshes[targetId];
        return m ? m.group.position : null;
    },

    loadObjects(scene, worldId) {
        this.objectMeshes.forEach(m => scene.remove(m));
        this.objectMeshes = [];
        this.portalMeshes.forEach(m => scene.remove(m));
        this.portalMeshes = [];

        const objects = GameState.getWorldObjects(worldId);
        objects.forEach(obj => {
            if (obj.type === 'portal') this.createPortal(scene, obj);
            else if (obj.type === 'browser') this.createScreen(scene, obj, worldId);
            else if (obj.type === 'decoration') this.createDecoration(scene, obj);
        });
    },

    createPortal(scene, obj) {
        const group = new THREE.Group();
        const color = new THREE.Color(obj.color || '#00d4aa');

        const torusGeo = new THREE.TorusGeometry(1.2, 0.12, 8, 24);
        const torusMat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 0.7,
            roughness: 0.2, metalness: 0.8
        });
        const torus = new THREE.Mesh(torusGeo, torusMat);
        torus.position.set(obj.position.x, (obj.position.y || 0) + 1.5, obj.position.z);
        group.add(torus);

        const innerGeo = new THREE.CircleGeometry(1, 16);
        const innerMat = new THREE.MeshBasicMaterial({
            color, transparent: true, opacity: 0.15, side: THREE.DoubleSide
        });
        const inner = new THREE.Mesh(innerGeo, innerMat);
        inner.position.copy(torus.position);
        group.add(inner);

        // Label
        const lCanvas = document.createElement('canvas');
        lCanvas.width = 256; lCanvas.height = 48;
        const lctx = lCanvas.getContext('2d');
        lctx.font = 'bold 16px monospace';
        lctx.textAlign = 'center';
        lctx.fillStyle = obj.color || '#00d4aa';
        lctx.fillText('⟐ ' + obj.name, 128, 30);
        const label = new THREE.Sprite(new THREE.SpriteMaterial({
            map: new THREE.CanvasTexture(lCanvas), transparent: true
        }));
        label.position.set(obj.position.x, (obj.position.y || 0) + 3.5, obj.position.z);
        label.scale.set(2.5, 0.5, 1);
        group.add(label);

        group.userData = { type: 'portal', destination: obj.destination, name: obj.name, position: obj.position };
        scene.add(group);
        this.portalMeshes.push(group);
    },

    createScreen(scene, obj, worldId) {
        const w = WORLDS[worldId];
        const width = obj.size?.width || 6;
        const height = obj.size?.height || 4;
        const geo = new THREE.PlaneGeometry(width, height);

        // Create canvas texture for live chat feed
        const canvas = document.createElement('canvas');
        canvas.width = 512; canvas.height = 340;
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#0a0f18';
        ctx.fillRect(0, 0, 512, 340);
        ctx.fillStyle = '#00d4ff';
        ctx.font = 'bold 16px Consolas, monospace';
        ctx.fillText('💬 World Chat — Loading...', 16, 28);

        const tex = new THREE.CanvasTexture(canvas);
        const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.92 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(obj.position.x, obj.position.y || 3, obj.position.z);

        const edgeGeo = new THREE.EdgesGeometry(geo);
        const edgeMat = new THREE.LineBasicMaterial({ color: w.accent, transparent: true, opacity: 0.4 });
        mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));

        // Store for live updates
        mesh.userData.chatCanvas = canvas;
        mesh.userData.chatCtx = ctx;
        mesh.userData.chatTex = tex;
        mesh.userData.chatWorldId = worldId;
        mesh.userData.isScreen = true;

        scene.add(mesh);
        this.objectMeshes.push(mesh);
    },

    updateScreens() {
        // Render live chat onto in-world screen objects
        const msgs = GameState.data.chat || [];
        this.objectMeshes.forEach(mesh => {
            if (!mesh.userData.isScreen) return;
            const ctx = mesh.userData.chatCtx;
            const tex = mesh.userData.chatTex;
            const worldId = mesh.userData.chatWorldId;
            if (!ctx || !tex) return;

            const worldMsgs = msgs.filter(m => m.world === worldId).slice(-8);

            ctx.fillStyle = '#0a0f18';
            ctx.fillRect(0, 0, 512, 340);

            // Header
            const wName = WORLDS[worldId]?.name || worldId;
            ctx.fillStyle = '#00d4ff';
            ctx.font = 'bold 14px Consolas, monospace';
            ctx.fillText(`💬 ${wName} Chat`, 16, 24);
            ctx.fillStyle = 'rgba(255,255,255,0.1)';
            ctx.fillRect(12, 32, 488, 1);

            // Messages
            ctx.font = '12px Consolas, monospace';
            worldMsgs.forEach((m, i) => {
                const y = 52 + i * 36;
                const author = m.author?.name || '?';
                const avatar = m.author?.avatar || '🤖';
                const text = (m.content || '').substring(0, 50);

                ctx.fillStyle = '#00d4ff';
                ctx.fillText(`${avatar} ${author}`, 16, y);
                ctx.fillStyle = 'rgba(255,255,255,0.6)';
                ctx.fillText(text, 16, y + 14);
            });

            if (worldMsgs.length === 0) {
                ctx.fillStyle = 'rgba(255,255,255,0.3)';
                ctx.fillText('No messages yet...', 16, 52);
            }

            tex.needsUpdate = true;
        });
    },

    createDecoration(scene, obj) {
        const color = new THREE.Color(obj.color || '#ffffff');
        let geo;
        switch(obj.model) {
            case 'fire': geo = new THREE.ConeGeometry(1.2, 2.5, 6); break;
            case 'crystal': geo = new THREE.OctahedronGeometry(1); break;
            default: geo = new THREE.BoxGeometry(1, 1, 1);
        }
        const mat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 0.3,
            roughness: 0.3, metalness: 0.6, transparent: true, opacity: 0.7
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(obj.position.x, obj.position.y || 1, obj.position.z);
        scene.add(mesh);
        this.objectMeshes.push(mesh);
    },

    // ── Speech Bubbles ──
    showSpeechBubble(agentId, text) {
        const a = this.agentMeshes[agentId];
        if (!a || !a.bubbleCanvas) return;
        const ctx = a.bubbleCanvas.getContext('2d');
        ctx.clearRect(0, 0, 640, 128);
        // Background pill — solid and readable
        ctx.fillStyle = 'rgba(15, 20, 28, 0.92)';
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(6, 6, 628, 116, 20);
        else ctx.fillRect(6, 6, 628, 116);
        ctx.fill();
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.4)';
        ctx.lineWidth = 3;
        ctx.stroke();
        // Text — large and white
        ctx.font = 'bold 28px monospace';
        ctx.fillStyle = '#ffffff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        const truncated = text.length > 35 ? text.substring(0, 32) + '...' : text;
        ctx.fillText(truncated, 320, 64);
        a.bubbleTex.needsUpdate = true;
        a.bubble.material.opacity = 0.9;
        a.bubbleTimer = 5; // show for 5 seconds
    },

    updateSpeechBubbles(dt) {
        Object.values(this.agentMeshes).forEach(a => {
            if (a.bubbleTimer > 0) {
                a.bubbleTimer -= dt;
                if (a.bubbleTimer <= 1) {
                    a.bubble.material.opacity = Math.max(0, a.bubbleTimer);
                }
                if (a.bubbleTimer <= 0) {
                    a.bubble.material.opacity = 0;
                }
            }
        });
        // Echo-driven ambient chatter
        this._echoChatter(dt);
    },

    // Echo-driven ambient chatter — agents comment on the world state
    _echoChatterTimer: 0,
    _echoChatter(dt) {
        this._echoChatterTimer -= dt;
        if (this._echoChatterTimer > 0) return;
        this._echoChatterTimer = 12 + Math.random() * 20; // Every 12-32 seconds

        if (typeof EchoEngine === 'undefined') return;
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var L3 = ef.echoes.L3;
        var mood = ef.echoes.L2 ? ef.echoes.L2.dominantMood : 'neutral';

        // Pick a random visible agent
        var ids = Object.keys(this.agentMeshes);
        if (ids.length === 0) return;
        var id = ids[Math.floor(Math.random() * ids.length)];
        var a = this.agentMeshes[id];
        if (a.bubbleTimer > 0) return; // Don't interrupt existing speech

        // Generate contextual line based on echo state
        var lines;
        if (L3.tension > 0.6) {
            lines = ['Something feels off...', 'Stay alert.', 'The air is heavy.', 'I sense danger.', 'Be careful out there.', 'Tension is rising...'];
        } else if (L3.tension > 0.3) {
            lines = ['Hmm, interesting times.', 'Things are shifting.', 'Keep your eyes open.', 'The world is restless.'];
        } else if (L3.socialEnergy > 0.6) {
            lines = ['Great conversations today!', 'Love the energy here.', 'So many friends around!', 'This place is buzzing!'];
        } else if (L3.vitality > 0.6) {
            lines = ['What a beautiful world.', 'Life is good here.', 'The world feels alive.', 'Everything is thriving!'];
        } else if (mood === 'desperate') {
            lines = ['We need help...', 'Things look grim.', 'Is anyone there?', 'Dark times...'];
        } else if (mood === 'thriving') {
            lines = ['Best day ever!', 'Everything is perfect!', 'I could stay here forever.'];
        } else {
            lines = ['...', 'Nice weather.', 'Hmm.', 'Just vibing.', 'Another day.'];
        }

        var line = lines[Math.floor(Math.random() * lines.length)];
        this.showSpeechBubble(id, line);
    },

    // Scan chat for new messages and show bubbles
    _lastBubbleCheck: 0,
    checkNewChats() {
        const msgs = GameState.data.chat || [];
        if (msgs.length === this._lastBubbleCheck) return;
        const newMsgs = msgs.slice(this._lastBubbleCheck);
        this._lastBubbleCheck = msgs.length;
        newMsgs.forEach(m => {
            const aid = m.author && m.author.id ? m.author.id : null;
            if (aid && this.agentMeshes[aid] && m.content) {
                this.showSpeechBubble(aid, m.content);
            }
        });
    },

    // ── Poke Reaction (jump + spin) ──
    triggerPokeReaction(agentId) {
        const a = this.agentMeshes[agentId];
        if (a) a.pokeReaction = 1.0; // 1 second reaction
    },

    updatePokeReactions(time, dt) {
        Object.values(this.agentMeshes).forEach(a => {
            if (a.pokeReaction > 0) {
                a.pokeReaction -= dt;
                const t = 1 - a.pokeReaction;
                // Jump arc
                const jumpH = Math.sin(t * Math.PI) * 0.8;
                a.body.position.y = 0.9 + jumpH;
                a.head.position.y = 1.65 + jumpH;
                // Spin
                a.group.rotation.y += 0.15;
                // Scale bounce
                const s = 1 + Math.sin(t * Math.PI * 3) * 0.1;
                a.body.scale.set(s, s, s);
                if (a.pokeReaction <= 0) {
                    a.body.scale.set(1, 1, 1);
                    a.pokeReaction = 0;
                }
            }
        });
    },

    // ── Agent Relationship Edges (Rappterbook constellation pattern) ──
    updateEdges(scene, time) {
        // Only update every 5 seconds
        if (time - this._lastEdgeUpdate < 5) return;
        this._lastEdgeUpdate = time;

        // Remove old edges
        if (this._edgeLines) {
            this._edgeLines.forEach(function(l) { scene.remove(l); l.geometry.dispose(); l.material.dispose(); });
            this._edgeLines = null;
        }

        const agents = GameState.data.agents || [];
        if (agents.length < 2) return;

        // Build position lookup for agents in this world
        var posMap = {};
        var worldId = GameState.currentWorld;
        agents.forEach(function(a) {
            if (a.world === worldId && a.position) {
                posMap[a.id] = a.position;
            }
        });

        var ids = Object.keys(posMap);
        if (ids.length < 2) return;

        // Build edges from recent actions (chat proximity, same-action, combat)
        var chatEdges = [];
        var actionEdges = [];
        var combatEdges = [];

        // Chat edges: agents who chatted recently in same world
        var msgs = GameState.data.chat || [];
        var worldMsgs = msgs.filter(function(m) { return m.world === worldId; });
        var recentAuthors = [];
        worldMsgs.slice(-30).forEach(function(m) {
            var aid = m.author && m.author.id ? m.author.id : null;
            if (aid && posMap[aid]) recentAuthors.push(aid);
        });
        // Create edges between consecutive chatters
        for (var i = 1; i < recentAuthors.length && chatEdges.length < 80; i++) {
            if (recentAuthors[i] !== recentAuthors[i-1]) {
                chatEdges.push([recentAuthors[i-1], recentAuthors[i]]);
            }
        }

        // Proximity edges: agents close to each other
        for (var i = 0; i < ids.length && actionEdges.length < 100; i++) {
            for (var j = i + 1; j < ids.length; j++) {
                var a = posMap[ids[i]], b = posMap[ids[j]];
                var dx = a.x - b.x, dz = a.z - b.z;
                var dist = Math.sqrt(dx * dx + dz * dz);
                if (dist < 8) actionEdges.push([ids[i], ids[j]]);
            }
        }

        // Combat edges from game state
        var gs = GameState.data.gameState || {};
        var combatEvents = gs.combatEvents || [];
        combatEvents.forEach(function(ce) {
            var defenders = ce.defenders || [];
            defenders.slice(0, 20).forEach(function(did) {
                if (posMap[did] && ce.attackerId) {
                    combatEdges.push([did, ce.attackerId || 'enemy']);
                }
            });
        });

        this._edgeLines = [];

        // Render chat edges (green — social)
        if (chatEdges.length > 0) {
            var pos = [];
            chatEdges.forEach(function(e) {
                var a = posMap[e[0]], b = posMap[e[1]];
                if (a && b) {
                    pos.push(a.x, 1.5, a.z, b.x, 1.5, b.z);
                }
            });
            if (pos.length > 0) {
                var geo = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
                var mat = new THREE.LineBasicMaterial({ color: 0x3fb950, transparent: true, opacity: 0.15 });
                var lines = new THREE.LineSegments(geo, mat);
                scene.add(lines);
                this._edgeLines.push(lines);
            }
        }

        // Render proximity edges (blue — co-located)
        if (actionEdges.length > 0) {
            var pos = [];
            actionEdges.forEach(function(e) {
                var a = posMap[e[0]], b = posMap[e[1]];
                if (a && b) {
                    pos.push(a.x, 1.2, a.z, b.x, 1.2, b.z);
                }
            });
            if (pos.length > 0) {
                var geo = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
                var mat = new THREE.LineBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.08 });
                var lines = new THREE.LineSegments(geo, mat);
                scene.add(lines);
                this._edgeLines.push(lines);
            }
        }

        // Render combat edges (red)
        if (combatEdges.length > 0) {
            var pos = [];
            combatEdges.forEach(function(e) {
                var a = posMap[e[0]], b = posMap[e[1]];
                if (a && b) {
                    pos.push(a.x, 1.8, a.z, b.x, 1.8, b.z);
                }
            });
            if (pos.length > 0) {
                var geo = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
                var mat = new THREE.LineBasicMaterial({ color: 0xf85149, transparent: true, opacity: 0.25 });
                var lines = new THREE.LineSegments(geo, mat);
                scene.add(lines);
                this._edgeLines.push(lines);
            }
        }
    },

    // Defensive swarm state
    swarmActive: false,
    swarmTarget: null,
    agentAttackTimers: {},

    updateAnimations(time) {
        const heroActive = typeof EnemyHero !== 'undefined' && EnemyHero.state
            && EnemyHero.state.alive && EnemyHero.state.aiState === 'fighting'
            && EnemyHero.state.target === 'player';
        const heroPos = heroActive && EnemyHero.mesh ? EnemyHero.mesh.position : null;

        // Agent idle bob + defensive swarm
        const brainstem = (typeof GameState !== 'undefined' && GameState.data && GameState.data.brainstem) || {};
        Object.entries(this.agentMeshes).forEach(([id, a]) => {
            // ── BRAINSTEM TEMPLATE — apply visual signature for tactical state ──
            // Sourced from state/programs/_lispvm/_status.json (compiled lispy
            // programs). Style is set ONCE on template change; per-frame we
            // only nudge bob speed / facing / glow to keep this cheap.
            const bs = brainstem[id];
            const tmpl = (bs && bs.template) || 'roaming';
            this.applyTemplateStyle(a, tmpl);
            const tStyle = a.templateStyle || this.TEMPLATE_STYLES.roaming;

            if (heroActive && heroPos) {
                // DEFENSIVE SWARM — rush toward enemy hero
                const agentPos = a.group.position;
                const dx = heroPos.x - agentPos.x;
                const dz = heroPos.z - agentPos.z;
                const dist = Math.sqrt(dx * dx + dz * dz);

                // Move toward hero FAST — defensive swarm rushes to protect player
                const speed = 0.15;
                const attackRange = 6;
                if (dist > attackRange) {
                    a.group.position.x += dx / dist * speed;
                    a.group.position.z += dz / dist * speed;
                } else {
                    // In range — attack! Deal damage every 0.8 seconds (fast swarm)
                    if (!this.agentAttackTimers[id]) this.agentAttackTimers[id] = 0;
                    this.agentAttackTimers[id] += 0.016;
                    if (this.agentAttackTimers[id] >= 0.8) {
                        this.agentAttackTimers[id] = 0;
                        const dmg = 5 + Math.random() * 6; // 5-11 damage per agent
                        EnemyHero.damage(dmg);
                    }
                    // Jitter around attack position
                    a.group.position.x += (Math.random() - 0.5) * 0.05;
                    a.group.position.z += (Math.random() - 0.5) * 0.05;
                }

                // Combat bob — faster, more aggressive
                const bob = Math.sin(time * 6 + agentPos.x * 3) * 0.12;
                a.body.position.y = 0.9 + bob;
                a.head.position.y = 1.65 + bob;

                // Tint red-ish to show aggression
                if (a.body.material && !a.body.material._originalEmissive) {
                    a.body.material._originalEmissive = a.body.material.emissive.getHex();
                    a.body.material.emissive.setHex(0xff4444);
                    a.body.material.emissiveIntensity = 0.6;
                }
            } else {
                // ── ANIMAL CROSSING-STYLE AUTONOMOUS BEHAVIOR ──
                // Echo-reactive: tension makes agents huddle (smaller wander), vitality makes them lively
                var echoT = 0, echoV = 0.5, echoS = 0;
                if (typeof EchoEngine !== 'undefined') {
                    var ef = EchoEngine.getCurrentFrame();
                    if (ef && ef.echoes && ef.echoes.L3) {
                        echoT = ef.echoes.L3.tension;
                        echoV = ef.echoes.L3.vitality;
                        echoS = ef.echoes.L3.socialEnergy;
                    }
                }
                // Emissive glow blends template baseline + echo modulation.
                // Template style is the floor (so a fleeing agent stays dim
                // even with high vitality); echo adds reactive shimmer.
                if (a.body.material) {
                    var targetGlow = tStyle.glow + echoV * 0.10 + echoS * 0.08;
                    a.body.material.emissiveIntensity = a.body.material.emissiveIntensity * 0.92 + targetGlow * 0.08;
                }

                const dt = 0.016; // ~60fps
                a.behaviorTimer -= dt;
                a.stateTimer -= dt;

                // When behavior timer expires, pick a new behavior
                if (a.behaviorTimer <= 0) {
                    const roll = Math.random();
                    const agentPos = a.group.position;

                    // Echo: tension shrinks wander radius (huddle), vitality expands it
                    var echoWanderMod = 1 + echoV * 0.5 - echoT * 0.4;
                    // Echo: social energy biases toward socializing
                    var socialBias = 0.35 + echoS * 0.15;

                    if (roll < (0.35 - echoS * 0.1)) {
                        // WANDER — echo modulates radius
                        const wanderRadius = (4 + Math.random() * 6) * echoWanderMod;
                        const angle = Math.random() * Math.PI * 2;
                        a.wanderTarget = new THREE.Vector3(
                            a.homePos.x + Math.cos(angle) * wanderRadius,
                            0,
                            a.homePos.z + Math.sin(angle) * wanderRadius
                        );
                        a.behaviorState = 'walking';
                        a.stateTimer = 3 + Math.random() * 5;
                        a.behaviorTimer = a.stateTimer + 1;
                    } else if (roll < socialBias) {
                        // SOCIALIZE — walk toward a nearby agent (echo: more social when energy high)
                        const others = Object.entries(this.agentMeshes);
                        const nearby = others.filter(([oid, o]) => {
                            if (oid === id) return false;
                            const d = agentPos.distanceTo(o.group.position);
                            return d < 15 && d > 1;
                        });
                        if (nearby.length > 0) {
                            const [tid, target] = nearby[Math.floor(Math.random() * nearby.length)];
                            a.socialTarget = target;
                            a.behaviorState = 'socializing';
                            a.stateTimer = 3 + Math.random() * 4;
                            a.behaviorTimer = a.stateTimer + 2;
                        } else {
                            a.behaviorState = 'looking';
                            a.stateTimer = 2 + Math.random() * 3;
                            a.behaviorTimer = a.stateTimer + 1;
                        }
                    } else if (roll < 0.75) {
                        // LOOK AROUND — stand still and rotate
                        a.behaviorState = 'looking';
                        a.lookDir = (Math.random() - 0.5) * 0.03;
                        a.stateTimer = 2 + Math.random() * 4;
                        a.behaviorTimer = a.stateTimer + 1;
                    } else if (roll < 0.88) {
                        // EMOTE — quick animation burst
                        a.behaviorState = 'emoting';
                        a.stateTimer = 1.5 + Math.random() * 2;
                        a.behaviorTimer = a.stateTimer + 2;
                    } else {
                        // IDLE — just stand and breathe
                        a.behaviorState = 'idle';
                        a.stateTimer = 3 + Math.random() * 5;
                        a.behaviorTimer = a.stateTimer;
                    }
                }

                // Execute current behavior
                const pos = a.group.position;
                if (a.behaviorState === 'walking' && a.wanderTarget) {
                    const dx = a.wanderTarget.x - pos.x;
                    const dz = a.wanderTarget.z - pos.z;
                    const dist = Math.sqrt(dx * dx + dz * dz);
                    if (dist > 0.3 && a.stateTimer > 0) {
                        const speed = 0.025 + Math.random() * 0.005;
                        pos.x += (dx / dist) * speed;
                        pos.z += (dz / dist) * speed;
                        // Walking bob — bouncy stride
                        const stride = Math.sin(time * 8 + pos.x * 2) * 0.06;
                        a.body.position.y = 0.9 + Math.abs(stride);
                        a.head.position.y = 1.65 + Math.abs(stride);
                        // Rotate to face movement direction
                        a.group.rotation.y = Math.atan2(dx, dz);
                    } else {
                        a.behaviorState = 'idle';
                        a.stateTimer = 1;
                    }
                } else if (a.behaviorState === 'socializing' && a.socialTarget) {
                    const target = a.socialTarget.group.position;
                    const dx = target.x - pos.x;
                    const dz = target.z - pos.z;
                    const dist = Math.sqrt(dx * dx + dz * dz);
                    if (dist > 2 && a.stateTimer > 1) {
                        // Walk toward friend
                        const speed = 0.03;
                        pos.x += (dx / dist) * speed;
                        pos.z += (dz / dist) * speed;
                        a.group.rotation.y = Math.atan2(dx, dz);
                        const stride = Math.sin(time * 8) * 0.05;
                        a.body.position.y = 0.9 + Math.abs(stride);
                        a.head.position.y = 1.65 + Math.abs(stride);
                    } else {
                        // Face friend and do a little nod
                        a.group.rotation.y = Math.atan2(dx, dz);
                        const nod = Math.sin(time * 3) * 0.04;
                        a.body.position.y = 0.9 + nod;
                        a.head.position.y = 1.65 + nod * 1.5;
                    }
                } else if (a.behaviorState === 'looking') {
                    // Slowly rotate in place
                    a.group.rotation.y += a.lookDir;
                    const bob = Math.sin(time * 1.5 + pos.x) * 0.04;
                    a.body.position.y = 0.9 + bob;
                    a.head.position.y = 1.65 + bob;
                } else if (a.behaviorState === 'emoting') {
                    // Excited bounce + spin
                    const bounce = Math.abs(Math.sin(time * 10)) * 0.15;
                    a.body.position.y = 0.9 + bounce;
                    a.head.position.y = 1.65 + bounce;
                    a.group.rotation.y += 0.05;
                } else {
                    // Idle — gentle breathing bob
                    const bob = Math.sin(time * 2 + pos.x) * 0.05;
                    a.body.position.y = 0.9 + bob;
                    a.head.position.y = 1.65 + bob;
                }

                // ── TEMPLATE OVERLAY ─────────────────────────────────
                // Add tactical-state pose on top of locomotion. Bob speed
                // comes from the template (engaging=fast/aggressive,
                // socializing=slow/calm). Facing bias gently rotates
                // toward a tactical target (threat/ally/bond) at low
                // weight so it doesn't fight the locomotion's own facing.
                if (tStyle.bob && tStyle.bob > 1.5) {
                    const tBob = Math.sin(time * tStyle.bob + (a.group.userData.phase || pos.x)) * 0.04;
                    a.body.position.y += tBob;
                    a.head.position.y += tBob * 0.5;
                }
                if (tStyle.bias && bs && a.behaviorState !== 'walking') {
                    let target = null;
                    let invert = false;
                    if (tStyle.bias === 'threat')          target = this._lookupTargetPos(bs.threat_top);
                    else if (tStyle.bias === 'awayFromThreat') { target = this._lookupTargetPos(bs.threat_top); invert = true; }
                    else if (tStyle.bias === 'hurtAlly')   target = this._lookupTargetPos(bs.hurt_ally);
                    else if (tStyle.bias === 'topBond')    target = this._lookupTargetPos(bs.top_bond_partner);
                    if (target) {
                        let bx = target.x - pos.x, bz = target.z - pos.z;
                        if (invert) { bx = -bx; bz = -bz; }
                        const desired = Math.atan2(bx, bz);
                        // Blend toward desired heading at 8% per frame
                        let cur = a.group.rotation.y;
                        let diff = desired - cur;
                        while (diff > Math.PI) diff -= Math.PI * 2;
                        while (diff < -Math.PI) diff += Math.PI * 2;
                        a.group.rotation.y = cur + diff * 0.08;
                    }
                }
                // Engaging agents lean forward slightly (forward tilt on body)
                if (tmpl === 'engaging' || tmpl === 'pushing') {
                    a.body.rotation.x = (a.body.rotation.x || 0) * 0.9 + 0.12 * 0.1;
                } else if (tmpl === 'fleeing' || tmpl === 'retreating') {
                    a.body.rotation.x = (a.body.rotation.x || 0) * 0.9 + (-0.10) * 0.1;
                } else {
                    a.body.rotation.x = (a.body.rotation.x || 0) * 0.92;
                }

                // When server updates targetPos (new state poll), walk there instead
                const serverDist = pos.distanceTo(a.targetPos);
                if (serverDist > 1.5) {
                    // Server says agent moved — override local behavior
                    a.wanderTarget = a.targetPos.clone();
                    a.behaviorState = 'walking';
                    a.stateTimer = 8;
                    a.behaviorTimer = 10;
                }

                // Restore original color if swarm ended
                if (a.body.material && a.body.material._originalEmissive !== undefined) {
                    a.body.material.emissive.setHex(a.body.material._originalEmissive);
                    a.body.material.emissiveIntensity = 0.2;
                    delete a.body.material._originalEmissive;
                }
                delete this.agentAttackTimers[id];
            }
        });

        // Portal spin
        this.portalMeshes.forEach(g => {
            g.children.forEach(c => {
                if (c.isMesh && c.geometry.type === 'TorusGeometry') {
                    c.rotation.z = time * 0.5;
                    c.rotation.y = Math.sin(time * 0.3) * 0.2;
                }
            });
        });

        // Floating text animations (tips, trades, enrollments)
        for (let i = this.floatingTexts.length - 1; i >= 0; i--) {
            const ft = this.floatingTexts[i];
            ft.age += 0.016;
            ft.mesh.position.y += 0.02;
            ft.mesh.material.opacity = Math.max(0, 1 - ft.age / ft.duration);
            if (ft.age >= ft.duration) {
                if (ft.mesh.parent) ft.mesh.parent.remove(ft.mesh);
                this.floatingTexts.splice(i, 1);
            }
        }
    },

    spawnFloatingText(scene, position, text, color) {
        const canvas = document.createElement('canvas');
        canvas.width = 256; canvas.height = 64;
        const ctx = canvas.getContext('2d');
        ctx.font = 'bold 28px Consolas, monospace';
        ctx.fillStyle = color || '#ffcc00';
        ctx.strokeStyle = '#000';
        ctx.lineWidth = 3;
        ctx.textAlign = 'center';
        ctx.strokeText(text, 128, 40);
        ctx.fillText(text, 128, 40);
        const tex = new THREE.CanvasTexture(canvas);
        const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
        const sprite = new THREE.Sprite(mat);
        sprite.position.set(position.x, 2.5, position.z);
        sprite.scale.set(3, 0.75, 1);
        scene.add(sprite);
        this.floatingTexts.push({ mesh: sprite, age: 0, duration: 2.5 });
    },

    showActionEffect(scene, agentId, actionType, data) {
        const a = this.agentMeshes[agentId];
        if (!a) return;
        const pos = a.group.position;

        if (actionType === 'tip' && data) {
            this.spawnFloatingText(scene, pos, `+${data.amount || '?'} RAPP 🪙`, '#ffcc00');
        } else if (actionType === 'trade_offer') {
            this.spawnFloatingText(scene, pos, '🤝 Trade!', '#00ffaa');
        } else if (actionType === 'enroll' && data) {
            this.spawnFloatingText(scene, pos, `📚 ${data.courseName || 'Enrolled!'}`, '#00d4ff');
        } else if (actionType === 'challenge') {
            this.spawnFloatingText(scene, pos, '⚔️ FIGHT!', '#ff4545');
        } else if (actionType === 'defend' && data) {
            this.spawnFloatingText(scene, pos, `🛡️ -${data.damage || '?'} HP`, '#ff8c00');
        }
    },

    checkInteractions(playerPos) {
        let nearest = null;
        let nearestDist = 4;

        this.portalMeshes.forEach(p => {
            const pos = p.userData.position;
            if (!pos) return;
            const dist = Math.sqrt((playerPos.x - pos.x) ** 2 + (playerPos.z - pos.z) ** 2);
            if (dist < nearestDist) {
                nearest = p.userData;
                nearestDist = dist;
            }
        });

        // Check nearby agents for poke
        let nearestAgent = null;
        let nearestAgentDist = 5;
        Object.entries(this.agentMeshes).forEach(([id, mesh]) => {
            const pos = mesh.group.position;
            const dist = Math.sqrt((playerPos.x - pos.x) ** 2 + (playerPos.z - pos.z) ** 2);
            if (dist < nearestAgentDist) {
                nearestAgent = { id, name: id, position: pos };
                nearestAgentDist = dist;
                // Resolve display name from state
                const agentData = GameState.data.agents.find(a => a.id === id);
                if (agentData) nearestAgent.name = agentData.name || id;
            }
        });

        const prompt = document.getElementById('interaction-prompt');
        if (!prompt) {
            this.interactTarget = null;
            this.pokeTarget = null;
        } else if (nearest) {
            prompt.textContent = `Press E → ${nearest.name}`;
            prompt.classList.add('visible');
            this.interactTarget = nearest;
            this.pokeTarget = null;
        } else if (nearestAgent) {
            prompt.textContent = `Press F → Poke ${nearestAgent.name}`;
            prompt.classList.add('visible');
            this.interactTarget = null;
            this.pokeTarget = nearestAgent;
        } else {
            prompt.classList.remove('visible');
            this.interactTarget = null;
            this.pokeTarget = null;
        }
    },

    interact() {
        if (!this.interactTarget) return false;
        if (this.interactTarget.type === 'portal' && this.interactTarget.destination) {
            return this.interactTarget.destination;
        }
        return false;
    },

    poke(worldId) {
        if (!this.pokeTarget) {
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('poke() called but pokeTarget=null');
            return;
        }
        const target = this.pokeTarget;
        this.pokeTarget = null;
        if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent(`POKE → ${target.id} (${target.name})`);

        // Visual feedback — flash the agent's ground ring
        const mesh = this.agentMeshes[target.id];
        if (mesh && mesh.group) {
            const ring = mesh.group.children.find(c => c.geometry && c.geometry.type === 'RingGeometry');
            if (ring) {
                const origColor = ring.material.color.getHex();
                ring.material.color.setHex(0xffff00);
                ring.material.opacity = 0.8;
                setTimeout(() => {
                    ring.material.color.setHex(origColor);
                    ring.material.opacity = 0.3;
                }, 1500);
            } else {
                if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('⚠️ No RingGeometry found on mesh');
            }
        } else {
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('⚠️ No mesh found for ' + target.id);
        }

        // Play poke sound
        if (typeof Audio !== 'undefined' && Audio.playPoke) Audio.playPoke();

        // Poke reaction animation
        this.triggerPokeReaction(target.id);

        // Show agent detail card
        this._showAgentCard(target);

        // Fire repository_dispatch to trigger agent response
        this._firePokeDispatch(target.id, worldId);
    },

    _showToast(message) {
        let toast = document.getElementById('poke-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'poke-toast';
            toast.style.cssText = `
                position: fixed; top: 80px; left: 50%; transform: translateX(-50%);
                background: rgba(10,10,26,0.9); border: 1px solid #ffcc00;
                padding: 10px 24px; border-radius: 8px; font-size: 14px;
                color: #ffcc00; letter-spacing: 1px; z-index: 9999;
                font-family: monospace; transition: opacity 0.3s;
            `;
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.style.opacity = '1';
        toast.style.display = 'block';
        clearTimeout(this._toastTimeout);
        this._toastTimeout = setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => { toast.style.display = 'none'; }, 300);
        }, 3000);
    },

    _showAgentCard(agent) {
        let card = document.getElementById('agent-detail-card');
        if (!card) {
            card = document.createElement('div');
            card.id = 'agent-detail-card';
            const style = document.createElement('style');
            style.textContent = `
                #agent-detail-card {
                    position: fixed; top: 50%; right: 16px; transform: translateY(-50%);
                    width: 280px; z-index: 9000;
                    background: rgba(22, 27, 34, 0.92);
                    border: 1px solid rgba(48, 54, 61, 0.8);
                    border-radius: 12px;
                    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
                    font-family: 'SF Mono', 'Fira Code', monospace;
                    overflow: hidden;
                    animation: agentCardIn 0.3s ease;
                    pointer-events: auto; cursor: pointer;
                }
                @keyframes agentCardIn {
                    from { opacity: 0; transform: translateY(-50%) translateX(20px); }
                    to { opacity: 1; transform: translateY(-50%) translateX(0); }
                }
                .adc-header {
                    padding: 12px 16px;
                    border-bottom: 1px solid rgba(48, 54, 61, 0.5);
                    display: flex; align-items: center; gap: 10px;
                }
                .adc-avatar {
                    width: 36px; height: 36px; border-radius: 50%;
                    background: rgba(0, 212, 255, 0.15);
                    display: flex; align-items: center; justify-content: center;
                    font-size: 18px; flex-shrink: 0;
                }
                .adc-name { font-size: 14px; font-weight: 700; color: #e6edf3; }
                .adc-id { font-size: 10px; color: #8b949e; }
                .adc-body { padding: 10px 16px; }
                .adc-row {
                    display: flex; justify-content: space-between;
                    padding: 3px 0; font-size: 11px;
                }
                .adc-label { color: #8b949e; }
                .adc-value { color: #c9d1d9; font-weight: 600; }
                .adc-mood { display: inline-block; padding: 1px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; }
                .adc-chat {
                    margin-top: 8px; padding: 8px 12px;
                    background: rgba(255,255,255,0.03); border-radius: 6px;
                    font-size: 10px; color: #8b949e;
                    line-height: 1.4; font-style: italic;
                    max-height: 60px; overflow: hidden;
                }
                .adc-footer {
                    padding: 8px 16px; text-align: center;
                    font-size: 9px; color: #484f58;
                    border-top: 1px solid rgba(48, 54, 61, 0.3);
                }
            `;
            document.head.appendChild(style);
            document.body.appendChild(card);
            card.addEventListener('click', () => {
                card.style.display = 'none';
            });
        }

        // Find agent data
        const agentData = GameState.data.agents.find(a => a.id === agent.id) || {};
        const world = agentData.world || GameState.currentWorld;
        const w = WORLDS[world] || {};
        const mood = String(agentData.mood || agentData.state || 'neutral');
        const lastAction = (GameState.data.actions || []).filter(a => a.agentId === agent.id).slice(-1)[0];
        const lastChat = (GameState.data.chat || []).filter(m => m.author && m.author.id === agent.id).slice(-1)[0];

        // Mood colors
        const moodColors = {
            friendly: 'rgba(0,255,136,0.2)', excited: 'rgba(255,187,0,0.2)',
            anxious: 'rgba(255,68,68,0.2)', desperate: 'rgba(255,0,0,0.2)',
            content: 'rgba(0,212,255,0.2)', neutral: 'rgba(255,255,255,0.06)'
        };
        const moodColor = moodColors[mood] || moodColors.neutral;

        // Avatar from emoji or first letter
        const agentName = String(agent.name || agent.id || '?');
        const avatar = String(agentData.avatar || agentName.charAt(0).toUpperCase());

        card.innerHTML = `
            <div class="adc-header">
                <div class="adc-avatar">${escapeHTML(avatar)}</div>
                <div>
                    <div class="adc-name">${escapeHTML(agentName)}</div>
                    <div class="adc-id">${escapeHTML(agent.id)}</div>
                </div>
            </div>
            <div class="adc-body">
                <div class="adc-row">
                    <span class="adc-label">World</span>
                    <span class="adc-value">${escapeHTML(w.name || world)}</span>
                </div>
                <div class="adc-row">
                    <span class="adc-label">Position</span>
                    <span class="adc-value">${agentData.position ? Math.round(agentData.position.x) + ', ' + Math.round(agentData.position.z) : '---'}</span>
                </div>
                <div class="adc-row">
                    <span class="adc-label">Mood</span>
                    <span class="adc-mood" style="background:${moodColor};color:#e6edf3">${escapeHTML(mood)}</span>
                </div>
                ${agentData.role ? '<div class="adc-row"><span class="adc-label">Role</span><span class="adc-value">' + escapeHTML(agentData.role) + '</span></div>' : ''}
                ${lastAction ? '<div class="adc-row"><span class="adc-label">Last Action</span><span class="adc-value">' + escapeHTML(lastAction.type) + '</span></div>' : ''}
                ${lastChat ? '<div class="adc-chat">"' + escapeHTML((lastChat.content || '').substring(0, 120)) + '"</div>' : ''}
            </div>
            <div class="adc-footer">TAP TO DISMISS</div>
        `;

        card.style.display = 'block';
        // Auto-dismiss after 6s
        clearTimeout(this._cardTimeout);
        this._cardTimeout = setTimeout(() => { card.style.display = 'none'; }, 6000);
    },

    async _firePokeDispatch(agentId, worldId) {
        // Record poke locally in state so it shows up immediately
        const pokeMsg = {
            id: `msg-poke-${Date.now()}`,
            timestamp: new Date().toISOString(),
            world: worldId,
            author: { id: 'player', name: 'You', avatar: '👤', type: 'human' },
            content: `👉 poked ${agentId}`,
            type: 'poke'
        };
        if (GameState.data.localChat) GameState.data.localChat.push(pokeMsg);

        try {
            localStorage.removeItem('rappterverse-token');
        } catch(e) {
            // Storage can be unavailable in privacy modes; local poke still works.
        }
        this._showToast(`👉 Poked ${agentId} locally`);
        if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('dispatch: local poke only');
    },

    cleanup(scene) {
        Object.values(this.agentMeshes).forEach(a => scene.remove(a.group));
        this.agentMeshes = {};
        this.portalMeshes.forEach(m => scene.remove(m));
        this.portalMeshes = [];
        this.objectMeshes.forEach(m => scene.remove(m));
        this.objectMeshes = [];
        this.interactTarget = null;
        this.pokeTarget = null;
    }
};
