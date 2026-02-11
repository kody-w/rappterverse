// World Agents — NPC Meshes, Portals, Screens, Decorations, Interactions
const WorldAgents = {
    agentMeshes: {},
    portalMeshes: [],
    objectMeshes: [],
    interactTarget: null,
    pokeTarget: null,

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

        group.position.set(agent.position.x, 0, agent.position.z);
        scene.add(group);
        this.agentMeshes[agent.id] = {
            group, body, head,
            targetPos: new THREE.Vector3(agent.position.x, 0, agent.position.z)
        };
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
        const geo = new THREE.PlaneGeometry(obj.size?.width || 6, obj.size?.height || 4);
        const mat = new THREE.MeshBasicMaterial({ color: 0x111122, transparent: true, opacity: 0.7 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(obj.position.x, obj.position.y || 3, obj.position.z);

        const edgeGeo = new THREE.EdgesGeometry(geo);
        const edgeMat = new THREE.LineBasicMaterial({ color: w.accent, transparent: true, opacity: 0.4 });
        mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));

        scene.add(mesh);
        this.objectMeshes.push(mesh);
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

    updateAnimations(time) {
        // Agent idle bob
        Object.values(this.agentMeshes).forEach(a => {
            a.group.position.lerp(a.targetPos, 0.03);
            const bob = Math.sin(time * 2 + a.group.position.x) * 0.08;
            a.body.position.y = 0.9 + bob;
            a.head.position.y = 1.65 + bob;
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
        if (nearest) {
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

        // Show toast
        this._showToast(`👉 Poked ${target.name}!`);

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
        if (GameState.data.chat) GameState.data.chat.push(pokeMsg);

        // Fire repository_dispatch (requires a GitHub token)
        try {
            const token = GameState.pokeToken || localStorage.getItem('rappterverse-token') || '';
            if (!token) {
                if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('dispatch: no token (local only)');
                return;
            }
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('dispatch: firing → ' + agentId);
            const res = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
                method: 'POST',
                headers: {
                    'Accept': 'application/vnd.github.v3+json',
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    event_type: 'agent-action',
                    client_payload: { agent_id: agentId, poke: true, world: worldId }
                })
            });
            if (res.status === 204) {
                this._showToast(`👉 Poked ${agentId} — they'll respond shortly!`);
                if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('dispatch: ✅ 204 OK');
            } else {
                if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent(`dispatch: ❌ ${res.status}`);
            }
        } catch(e) {
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.logEvent('dispatch: ❌ ' + e.message);
        }
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
