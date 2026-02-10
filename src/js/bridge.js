// Bridge — 3D First-Person Nexus Hub (Ship Command Center)
const Bridge = {
    open: false,
    scene: null,
    camera: null,
    player: null,
    portals: [],
    agentMeshes: {},
    dataScreens: [],
    crystals: [],
    animationId: null,
    clock: null,

    // Internal state
    _keys: {},
    _initialized: false,
    _savedMode: null,
    _interactTarget: null,
    _lastAgentSync: -1,
    _lastDataUpdate: -1,
    _hologram: null,
    _hologramInner: null,
    _centerRing: null,
    _centerLight: null,
    _boundKeyDown: null,
    _boundKeyUp: null,
    _boundResize: null,

    get active() { return this.open; },

    // ── Lifecycle ──────────────────────────────────────────────

    toggle() {
        this.open ? this.close() : this.enter();
    },

    enter() {
        if (this.open) return;
        this.open = true;
        GameState.bridgeOpen = true;
        this._savedMode = GameState.mode;

        // Hide current mode container
        const containers = { galaxy: 'galaxy-container', world: 'world-container' };
        const cId = containers[this._savedMode];
        if (cId) document.getElementById(cId).style.display = 'none';

        // Init scene once
        if (!this._initialized) this.initScene();

        // Show overlay and attach renderer
        const overlay = document.getElementById('bridge-overlay');
        overlay.innerHTML = '';
        const closeBtn = document.createElement('button');
        closeBtn.id = 'bridge-close';
        closeBtn.className = 'bridge-close';
        closeBtn.textContent = '\u00d7';
        closeBtn.addEventListener('click', () => this.close());
        overlay.appendChild(closeBtn);
        overlay.appendChild(GameState.renderer.domElement);
        overlay.classList.add('active');

        // Reset player
        this.player.x = 0; this.player.z = 0; this.player.yaw = 0;

        // Clock + input
        this.clock = new THREE.Clock();
        this._boundKeyDown = (e) => this._onKeyDown(e);
        this._boundKeyUp = (e) => { this._keys[e.code] = false; };
        this._boundResize = () => this.onResize();
        window.addEventListener('keydown', this._boundKeyDown);
        window.addEventListener('keyup', this._boundKeyUp);
        window.addEventListener('resize', this._boundResize);

        // Initial data
        this.syncAgents();
        this.updateDataScreens();
        this._lastAgentSync = -1;
        this._lastDataUpdate = -1;

        // Start render loop
        this.animationId = requestAnimationFrame(() => this._animate());

        if (typeof HUD !== 'undefined') HUD.showToast('Bridge activated — WASD move, Arrows look, E interact');
    },

    close() {
        if (!this.open) return;
        this.open = false;
        GameState.bridgeOpen = false;

        // Stop loop
        if (this.animationId) { cancelAnimationFrame(this.animationId); this.animationId = null; }

        // Remove input
        if (this._boundKeyDown) window.removeEventListener('keydown', this._boundKeyDown);
        if (this._boundKeyUp) window.removeEventListener('keyup', this._boundKeyUp);
        if (this._boundResize) window.removeEventListener('resize', this._boundResize);
        this._keys = {};

        // Hide overlay
        document.getElementById('bridge-overlay').classList.remove('active');

        // Hide interaction prompt
        const prompt = document.getElementById('interaction-prompt');
        if (prompt) prompt.classList.remove('visible');

        // Re-attach renderer to previous mode's container
        const mode = this._savedMode || GameState.mode;
        const target = mode === 'world' ? 'world-container' : 'galaxy-container';
        const container = document.getElementById(target);
        if (container) {
            container.appendChild(GameState.renderer.domElement);
            container.style.display = 'block';
        }
    },

    // ── Scene Init ─────────────────────────────────────────────

    initScene() {
        this._initialized = true;

        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x050510);
        this.scene.fog = new THREE.FogExp2(0x050510, 0.012);

        this.camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        this.player = { x: 0, y: 2, z: 0, yaw: 0 };

        this._buildSkybox();
        this._buildFloor();
        this._buildCenterPiece();
        this._buildPortals();
        this._buildDataScreens();
        this._buildCrystals();
        this._buildLighting();
    },

    _buildSkybox() {
        const c = document.createElement('canvas');
        c.width = 1024; c.height = 512;
        const ctx = c.getContext('2d');
        const grad = ctx.createLinearGradient(0, 0, 0, 512);
        grad.addColorStop(0, '#050520');
        grad.addColorStop(0.4, '#0a0a2e');
        grad.addColorStop(1, '#120520');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, 1024, 512);
        for (let i = 0; i < 500; i++) {
            const r = Math.random() * 1.6 + 0.2;
            const a = Math.random() * 0.6 + 0.4;
            ctx.beginPath();
            ctx.arc(Math.random() * 1024, Math.random() * 512, r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(200,220,255,${a})`;
            ctx.fill();
        }
        const tex = new THREE.CanvasTexture(c);
        const geo = new THREE.SphereGeometry(400, 32, 16);
        const mat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide });
        this.scene.add(new THREE.Mesh(geo, mat));
    },

    _buildFloor() {
        // Metallic disc
        const floorGeo = new THREE.CircleGeometry(50, 64);
        const floorMat = new THREE.MeshStandardMaterial({ color: 0x111122, roughness: 0.2, metalness: 0.8 });
        const floor = new THREE.Mesh(floorGeo, floorMat);
        floor.rotation.x = -Math.PI / 2;
        this.scene.add(floor);

        // Grid overlay
        const grid = new THREE.GridHelper(100, 50, 0x0088aa, 0x004466);
        grid.material.opacity = 0.3;
        grid.material.transparent = true;
        grid.position.y = 0.01;
        this.scene.add(grid);

        // Glowing center ring
        const ringGeo = new THREE.RingGeometry(4, 4.5, 64);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.6 });
        this._centerRing = new THREE.Mesh(ringGeo, ringMat);
        this._centerRing.rotation.x = -Math.PI / 2;
        this._centerRing.position.y = 0.02;
        this.scene.add(this._centerRing);
    },

    _buildCenterPiece() {
        // Wireframe icosahedron hologram
        const icoGeo = new THREE.IcosahedronGeometry(2, 0);
        const icoMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, wireframe: true, transparent: true, opacity: 0.7 });
        this._hologram = new THREE.Mesh(icoGeo, icoMat);
        this._hologram.position.set(0, 5, 0);
        this.scene.add(this._hologram);

        // Inner glow volume
        const glowGeo = new THREE.IcosahedronGeometry(1.4, 1);
        const glowMat = new THREE.MeshBasicMaterial({ color: 0x00aaff, transparent: true, opacity: 0.12 });
        this._hologramInner = new THREE.Mesh(glowGeo, glowMat);
        this._hologramInner.position.set(0, 5, 0);
        this.scene.add(this._hologramInner);
    },

    _buildPortals() {
        this.portals = [];
        const count = WORLD_IDS.length;

        for (let i = 0; i < count; i++) {
            const angle = (i / count) * Math.PI * 2 - Math.PI / 2;
            const px = Math.cos(angle) * 20;
            const pz = Math.sin(angle) * 20;
            const worldId = WORLD_IDS[i];
            const w = WORLDS[worldId];
            const color = new THREE.Color(w.accent);

            const group = new THREE.Group();
            group.position.set(px, 0, pz);

            // Torus frame
            const torusGeo = new THREE.TorusGeometry(2.5, 0.15, 8, 32);
            const torusMat = new THREE.MeshStandardMaterial({
                color, emissive: color, emissiveIntensity: 0.6,
                roughness: 0.2, metalness: 0.8
            });
            const torus = new THREE.Mesh(torusGeo, torusMat);
            torus.position.y = 3;
            group.add(torus);

            // Inner disc
            const discGeo = new THREE.CircleGeometry(2, 16);
            const discMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.15, side: THREE.DoubleSide });
            const disc = new THREE.Mesh(discGeo, discMat);
            disc.position.y = 3;
            group.add(disc);

            // Floating label
            const label = this._makeTextSprite(w.name, '#' + color.getHexString(), 22);
            label.position.y = 6.5;
            label.scale.set(4, 1, 1);
            group.add(label);

            // Portal accent light
            const pLight = new THREE.PointLight(w.accent, 1.2, 18);
            pLight.position.y = 3;
            group.add(pLight);

            group.userData = { worldId, torus };
            this.scene.add(group);
            this.portals.push(group);
        }
    },

    _buildDataScreens() {
        this.dataScreens = [];
        const configs = [
            { title: '\u{1F465} AGENT REGISTRY', pos: [-12, 3, -15], getData: () => this._getAgentData() },
            { title: '\u{1F4AC} CHAT LOG',       pos: [0, 3, -18],   getData: () => this._getChatData() },
            { title: '\u26A1 ACTION LOG',        pos: [12, 3, -15],  getData: () => this._getActionData() }
        ];

        configs.forEach(cfg => {
            const canvas = document.createElement('canvas');
            canvas.width = 512; canvas.height = 384;
            const tex = new THREE.CanvasTexture(canvas);

            const geo = new THREE.PlaneGeometry(6, 4.5);
            const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.92 });
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(cfg.pos[0], cfg.pos[1], cfg.pos[2]);

            // Edge glow
            const edgeGeo = new THREE.EdgesGeometry(geo);
            const edgeMat = new THREE.LineBasicMaterial({ color: 0x00ffff, transparent: true, opacity: 0.5 });
            mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));

            this.scene.add(mesh);
            this.dataScreens.push({ mesh, canvas, tex, title: cfg.title, getData: cfg.getData });
        });
    },

    _getAgentData() {
        return GameState.data.agents.slice(0, 12).map(a =>
            `${a.avatar || '\u{1F916}'} ${a.name} [${a.world}] ${a.status || 'active'}`
        );
    },

    _getChatData() {
        return GameState.data.chat.slice(-12).map(m =>
            `${m.author?.avatar || '\u{1F4AC}'} ${(m.author?.name || '?')}: ${(m.content || '').slice(0, 32)}`
        );
    },

    _getActionData() {
        return GameState.data.actions.slice(-12).map(a => {
            const name = GameState.getAgentName(a.agentId);
            const detail = a.data?.message ? ' "' + a.data.message.slice(0, 22) + '"' : '';
            return `${name}: ${a.type}${detail}`;
        });
    },

    updateDataScreens() {
        this.dataScreens.forEach(scr => {
            const ctx = scr.canvas.getContext('2d');
            const w = scr.canvas.width, h = scr.canvas.height;

            ctx.fillStyle = 'rgba(5,5,20,0.96)';
            ctx.fillRect(0, 0, w, h);
            ctx.strokeStyle = '#00aacc';
            ctx.lineWidth = 2;
            ctx.strokeRect(2, 2, w - 4, h - 4);

            ctx.font = 'bold 20px monospace';
            ctx.fillStyle = '#00ffff';
            ctx.fillText(scr.title, 16, 30);

            ctx.strokeStyle = '#004466';
            ctx.beginPath(); ctx.moveTo(16, 42); ctx.lineTo(w - 16, 42); ctx.stroke();

            const lines = scr.getData();
            ctx.font = '14px monospace';
            lines.forEach((line, i) => {
                ctx.fillStyle = i % 2 === 0 ? '#88ccdd' : '#66aacc';
                ctx.fillText(line.slice(0, 45), 16, 64 + i * 26);
            });
            if (lines.length === 0) {
                ctx.fillStyle = '#445566';
                ctx.font = '16px monospace';
                ctx.fillText('No data available', 16, 70);
            }
            scr.tex.needsUpdate = true;
        });
    },

    _buildCrystals() {
        this.crystals = [];
        const palette = [0xff00ff, 0x00ffff, 0xffaa00, 0x00ff88, 0xaa66ff,
                         0xff6644, 0x44aaff, 0x88ff44, 0xff4488, 0x44ffcc];

        for (let i = 0; i < 10; i++) {
            const size = 0.5 + Math.random() * 1.0;
            const color = palette[i];
            const geo = new THREE.OctahedronGeometry(size, 0);
            const mat = new THREE.MeshStandardMaterial({
                color, emissive: color, emissiveIntensity: 0.4,
                roughness: 0.2, metalness: 0.6, transparent: true, opacity: 0.7
            });
            const mesh = new THREE.Mesh(geo, mat);

            const a = Math.random() * Math.PI * 2;
            const r = 10 + Math.random() * 28;
            mesh.position.set(Math.cos(a) * r, 5 + Math.random() * 10, Math.sin(a) * r);
            mesh.userData.baseY = mesh.position.y;
            mesh.userData.phase = Math.random() * Math.PI * 2;
            mesh.userData.bobSpeed = 0.5 + Math.random();
            mesh.userData.rotSpeed = 0.2 + Math.random() * 0.8;

            this.scene.add(mesh);
            this.crystals.push(mesh);
        }
    },

    _buildLighting() {
        this.scene.add(new THREE.AmbientLight(0x222244, 0.5));

        this._centerLight = new THREE.PointLight(0x00ffff, 2, 50);
        this._centerLight.position.set(0, 5, 0);
        this.scene.add(this._centerLight);
    },

    // ── Agents ─────────────────────────────────────────────────

    syncAgents() {
        const agents = GameState.data.agents;
        const ids = new Set(agents.map(a => a.id));

        // Remove departed
        Object.keys(this.agentMeshes).forEach(id => {
            if (!ids.has(id)) {
                this.scene.remove(this.agentMeshes[id].group);
                delete this.agentMeshes[id];
            }
        });

        // Add new
        agents.forEach((agent, i) => {
            if (!this.agentMeshes[agent.id]) this._createAgentMesh(agent, i);
        });
    },

    _createAgentMesh(agent, index) {
        const group = new THREE.Group();

        // Body capsule
        const bodyGeo = new THREE.CylinderGeometry(0.35, 0.35, 1.05, 8);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: 0x6666aa, emissive: 0x3333aa, emissiveIntensity: 0.2,
            roughness: 0.3, metalness: 0.7, transparent: true, opacity: 0.85
        });
        const body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = 0.9;
        group.add(body);

        // Head
        const headGeo = new THREE.SphereGeometry(0.25, 8, 8);
        const headMat = new THREE.MeshStandardMaterial({
            color: 0xccccff, emissive: 0x6666cc, emissiveIntensity: 0.3,
            roughness: 0.2, metalness: 0.5
        });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.y = 1.65;
        group.add(head);

        // Emoji sprite
        const ec = document.createElement('canvas');
        ec.width = 128; ec.height = 128;
        const ectx = ec.getContext('2d');
        ectx.font = '72px serif';
        ectx.textAlign = 'center';
        ectx.textBaseline = 'middle';
        ectx.fillText(agent.avatar || '\u{1F916}', 64, 64);
        const emoji = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(ec), transparent: true }));
        emoji.position.y = 2.5;
        emoji.scale.set(0.8, 0.8, 1);
        group.add(emoji);

        // Name label
        const nameSprite = this._makeTextSprite(agent.name, '#ffffff', 18);
        nameSprite.position.y = 3.2;
        nameSprite.scale.set(2.2, 0.4, 1);
        group.add(nameSprite);

        // Ground ring
        const ringGeo = new THREE.RingGeometry(0.4, 0.55, 12);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.3 });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        // Scatter around hub
        const total = Math.max(GameState.data.agents.length, 1);
        const angle = (index / total) * Math.PI * 2 + 0.5;
        const radius = 8 + (index % 3) * 5;
        group.position.set(Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
        group.userData.phase = Math.random() * Math.PI * 2;

        this.scene.add(group);
        this.agentMeshes[agent.id] = { group, body, head };
    },

    // ── Input ──────────────────────────────────────────────────

    _onKeyDown(e) {
        if (!this.open) return;
        this._keys[e.code] = true;

        if (e.code === 'KeyE') {
            this._interactPortal();
        }
    },

    _interactPortal() {
        if (!this._interactTarget) return;
        const worldId = this._interactTarget;
        this.close();
        if (GameState.mode === 'world') WorldMode.cleanup();
        if (GameState.mode === 'galaxy') Galaxy.hide();
        Approach.start(worldId);
    },

    // ── Animation Loop ─────────────────────────────────────────

    _animate() {
        if (!this.open) return;
        this.animationId = requestAnimationFrame(() => this._animate());

        const delta = this.clock.getDelta();
        const time = this.clock.getElapsedTime();

        this._updatePlayer();
        this._updateAnimations(time);
        this._checkPortalProximity();

        // Periodic syncs
        const sec = Math.floor(time);
        if (sec % 5 === 0 && sec !== this._lastAgentSync) {
            this._lastAgentSync = sec;
            this.syncAgents();
        }
        if (sec % 3 === 0 && sec !== this._lastDataUpdate) {
            this._lastDataUpdate = sec;
            this.updateDataScreens();
        }

        GameState.renderer.render(this.scene, this.camera);
    },

    _updatePlayer() {
        const speed = 0.15;
        const sin = Math.sin(this.player.yaw);
        const cos = Math.cos(this.player.yaw);

        // Yaw rotation (arrow keys)
        if (this._keys['ArrowLeft'])  this.player.yaw += 0.03;
        if (this._keys['ArrowRight']) this.player.yaw -= 0.03;

        // Movement relative to facing direction
        if (this._keys['KeyW']) { this.player.x -= sin * speed; this.player.z -= cos * speed; }
        if (this._keys['KeyS']) { this.player.x += sin * speed; this.player.z += cos * speed; }
        if (this._keys['KeyA']) { this.player.x -= cos * speed; this.player.z += sin * speed; }
        if (this._keys['KeyD']) { this.player.x += cos * speed; this.player.z -= sin * speed; }

        // Clamp to floor radius
        const dist = Math.sqrt(this.player.x * this.player.x + this.player.z * this.player.z);
        if (dist > 48) {
            this.player.x = (this.player.x / dist) * 48;
            this.player.z = (this.player.z / dist) * 48;
        }

        // Camera follows player, looks in yaw direction
        this.camera.position.set(this.player.x, this.player.y, this.player.z);
        this.camera.lookAt(
            this.player.x - Math.sin(this.player.yaw) * 10,
            2,
            this.player.z - Math.cos(this.player.yaw) * 10
        );
    },

    _updateAnimations(time) {
        // Hologram rotation + hover
        if (this._hologram) {
            this._hologram.rotation.y = time * 0.5;
            this._hologram.rotation.x = Math.sin(time * 0.3) * 0.2;
            this._hologram.position.y = 5 + Math.sin(time * 0.8) * 0.5;
        }
        if (this._hologramInner) {
            this._hologramInner.rotation.y = -time * 0.3;
            this._hologramInner.position.y = this._hologram ? this._hologram.position.y : 5;
        }

        // Center ring pulse
        if (this._centerRing) {
            this._centerRing.material.opacity = 0.4 + Math.sin(time * 2) * 0.2;
        }

        // Center light pulse
        if (this._centerLight) {
            this._centerLight.intensity = 1.5 + Math.sin(time * 1.5) * 0.5;
        }

        // Portal torus spin
        this.portals.forEach(p => {
            const t = p.userData.torus;
            if (t) { t.rotation.z = time * 0.5; t.rotation.y = Math.sin(time * 0.3) * 0.2; }
        });

        // Crystals float and rotate
        this.crystals.forEach(c => {
            c.rotation.y = time * c.userData.rotSpeed;
            c.rotation.x = Math.sin(time * 0.5 + c.userData.phase) * 0.3;
            c.position.y = c.userData.baseY + Math.sin(time * c.userData.bobSpeed + c.userData.phase);
        });

        // Agent idle bob
        Object.values(this.agentMeshes).forEach(a => {
            const bob = Math.sin(time * 2 + (a.group.userData.phase || 0)) * 0.08;
            a.body.position.y = 0.9 + bob;
            a.head.position.y = 1.65 + bob;
        });
    },

    _checkPortalProximity() {
        this._interactTarget = null;
        let nearDist = 5;
        let nearName = null;

        this.portals.forEach(p => {
            const dx = this.player.x - p.position.x;
            const dz = this.player.z - p.position.z;
            const d = Math.sqrt(dx * dx + dz * dz);
            if (d < nearDist) {
                nearDist = d;
                this._interactTarget = p.userData.worldId;
                nearName = WORLDS[p.userData.worldId].name;
            }
        });

        const prompt = document.getElementById('interaction-prompt');
        if (prompt) {
            if (this._interactTarget) {
                prompt.textContent = 'Press E \u2192 ' + nearName;
                prompt.classList.add('visible');
            } else {
                prompt.classList.remove('visible');
            }
        }
    },

    // Called by main.js every ~3s — trigger data screen refresh
    render() {
        if (!this.open || !this.dataScreens.length) return;
        this.updateDataScreens();
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    },

    // ── Helpers ─────────────────────────────────────────────────

    _makeTextSprite(text, color, fontSize) {
        const c = document.createElement('canvas');
        c.width = 256; c.height = 64;
        const ctx = c.getContext('2d');
        ctx.font = `bold ${fontSize || 20}px monospace`;
        ctx.textAlign = 'center';
        ctx.fillStyle = color || '#ffffff';
        ctx.fillText(text, 128, 40);
        const tex = new THREE.CanvasTexture(c);
        return new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
    }
};
