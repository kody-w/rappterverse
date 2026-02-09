// World Mode — On-Planet Exploration
const WorldMode = {
    scene: null,
    camera: null,
    active: false,
    currentWorld: null,

    // Player
    player: null,
    playerSpeed: 8,
    playerMesh: null,

    // Other agents
    agentMeshes: {},

    // World objects
    objectMeshes: [],
    portalMeshes: [],

    // State
    keys: {},
    interactTarget: null,

    init(worldId) {
        this.currentWorld = worldId;
        this.active = true;
        GameState.currentWorld = worldId;

        const w = WORLDS[worldId];

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.sky);
        this.scene.fog = new THREE.FogExp2(w.fog, 0.015);

        // Camera
        this.camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 500);

        // Renderer
        const container = document.getElementById('world-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);
        container.style.display = 'block';

        // Lighting
        const ambient = new THREE.AmbientLight(0x404060, 0.6);
        this.scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(10, 20, 10);
        this.scene.add(dirLight);

        const pointLight = new THREE.PointLight(w.accent, 1.5, 60);
        pointLight.position.set(0, 10, 0);
        this.scene.add(pointLight);

        // Apply day/night from game state
        const worldState = GameState.data.gameState?.worlds?.[worldId];
        if (worldState?.time_of_day === 'night') {
            ambient.intensity = 0.2;
            dirLight.intensity = 0.3;
            dirLight.color.set(0x6666aa);
        }

        // Ground
        this.buildGround(w);

        // Particles
        this.spawnParticles(w);

        // Player
        this.createPlayer(w);

        // Load world objects
        this.loadObjects();

        // Load agents
        this.syncAgents();

        // Key listeners
        this.keyDown = (e) => { this.keys[e.code] = true; };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // Update HUD
        if (typeof HUD !== 'undefined') {
            HUD.setWorld(worldId);
        }
    },

    buildGround(w) {
        // Ground plane
        const groundGeo = new THREE.PlaneGeometry(w.bounds.x * 2 + 4, w.bounds.z * 2 + 4);
        const groundMat = new THREE.MeshStandardMaterial({
            color: w.floor, roughness: 0.9, metalness: 0.1,
            transparent: true, opacity: 0.8
        });
        const ground = new THREE.Mesh(groundGeo, groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.05;
        this.scene.add(ground);

        // Grid
        const gridSize = Math.max(w.bounds.x, w.bounds.z) * 2 + 2;
        const grid = new THREE.GridHelper(gridSize, gridSize, w.grid, new THREE.Color(w.grid).multiplyScalar(0.3));
        grid.material.opacity = 0.2;
        grid.material.transparent = true;
        this.scene.add(grid);

        // Boundary wireframe
        const bGeo = new THREE.BoxGeometry(w.bounds.x * 2, 4, w.bounds.z * 2);
        const bMat = new THREE.MeshBasicMaterial({ color: w.accent, wireframe: true, transparent: true, opacity: 0.06 });
        const boundary = new THREE.Mesh(bGeo, bMat);
        boundary.position.y = 2;
        this.scene.add(boundary);
    },

    spawnParticles(w) {
        const count = 150;
        const geo = new THREE.BufferGeometry();
        const pos = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
            pos[i * 3] = (Math.random() - 0.5) * w.bounds.x * 4;
            pos[i * 3 + 1] = Math.random() * 12 + 1;
            pos[i * 3 + 2] = (Math.random() - 0.5) * w.bounds.z * 4;
        }
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const mat = new THREE.PointsMaterial({
            color: w.accent, size: 0.12,
            transparent: true, opacity: 0.35,
            blending: THREE.AdditiveBlending, sizeAttenuation: true
        });
        this.particles = new THREE.Points(geo, mat);
        this.scene.add(this.particles);
    },

    createPlayer(w) {
        const group = new THREE.Group();

        // Body (capsule)
        const bodyGeo = new THREE.CapsuleGeometry(0.35, 0.7, 4, 8);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: 0x8888cc, emissive: 0x4444aa, emissiveIntensity: 0.2,
            roughness: 0.3, metalness: 0.7
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

        // Eyes (two small emissive spheres)
        const eyeGeo = new THREE.SphereGeometry(0.05, 6, 6);
        const eyeMat = new THREE.MeshBasicMaterial({ color: 0x00ffff });
        const eyeL = new THREE.Mesh(eyeGeo, eyeMat);
        eyeL.position.set(-0.1, 1.68, 0.2);
        group.add(eyeL);
        const eyeR = new THREE.Mesh(eyeGeo, eyeMat);
        eyeR.position.set(0.1, 1.68, 0.2);
        group.add(eyeR);

        // Arms
        const armGeo = new THREE.BoxGeometry(0.12, 0.5, 0.12);
        const armMat = new THREE.MeshStandardMaterial({ color: 0x7777aa, metalness: 0.6, roughness: 0.4 });
        const armL = new THREE.Mesh(armGeo, armMat);
        armL.position.set(-0.5, 0.85, 0);
        group.add(armL);
        const armR = new THREE.Mesh(armGeo, armMat);
        armR.position.set(0.5, 0.85, 0);
        group.add(armR);

        // Legs
        const legGeo = new THREE.BoxGeometry(0.14, 0.45, 0.14);
        const legMat = new THREE.MeshStandardMaterial({ color: 0x6666aa, metalness: 0.6, roughness: 0.4 });
        const legL = new THREE.Mesh(legGeo, legMat);
        legL.position.set(-0.15, 0.22, 0);
        group.add(legL);
        const legR = new THREE.Mesh(legGeo, legMat);
        legR.position.set(0.15, 0.22, 0);
        group.add(legR);

        // Ground ring
        const ringGeo = new THREE.RingGeometry(0.4, 0.55, 16);
        const ringMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.3 });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        group.position.set(0, 0, 5);
        this.player = { mesh: group, velocity: new THREE.Vector3(), body, head, armL, armR, legL, legR, ring };
        this.scene.add(group);
    },

    createAgentMesh(agent) {
        const w = WORLDS[this.currentWorld];
        const group = new THREE.Group();

        // Body
        const bodyGeo = new THREE.CapsuleGeometry(0.35, 0.7, 4, 8);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: w.accent, emissive: w.accent, emissiveIntensity: 0.2,
            roughness: 0.3, metalness: 0.7, transparent: true, opacity: 0.85
        });
        group.add(new THREE.Mesh(bodyGeo, bodyMat));
        group.children[0].position.y = 0.9;

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
        const emojiTex = new THREE.CanvasTexture(emojiCanvas);
        const emojiMat = new THREE.SpriteMaterial({ map: emojiTex, transparent: true });
        const emoji = new THREE.Sprite(emojiMat);
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
        const nameTex = new THREE.CanvasTexture(nameCanvas);
        const nameMat = new THREE.SpriteMaterial({ map: nameTex, transparent: true, opacity: 0.7 });
        const nameSprite = new THREE.Sprite(nameMat);
        nameSprite.position.y = 3.2;
        nameSprite.scale.set(2.2, 0.4, 1);
        group.add(nameSprite);

        // Ground ring
        const ringGeo = new THREE.RingGeometry(0.4, 0.55, 12);
        const ringMat = new THREE.MeshBasicMaterial({ color: w.accent, side: THREE.DoubleSide, transparent: true, opacity: 0.3 });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        group.position.set(agent.position.x, 0, agent.position.z);
        this.scene.add(group);
        this.agentMeshes[agent.id] = {
            group, body: group.children[0], head,
            targetPos: new THREE.Vector3(agent.position.x, 0, agent.position.z)
        };
    },

    syncAgents() {
        const agents = GameState.getWorldAgents(this.currentWorld);
        const currentIds = new Set(agents.map(a => a.id));

        // Remove gone
        Object.keys(this.agentMeshes).forEach(id => {
            if (!currentIds.has(id)) {
                this.scene.remove(this.agentMeshes[id].group);
                delete this.agentMeshes[id];
            }
        });

        // Add/update
        agents.forEach(agent => {
            if (!this.agentMeshes[agent.id]) {
                this.createAgentMesh(agent);
            } else {
                this.agentMeshes[agent.id].targetPos.set(agent.position.x, 0, agent.position.z);
            }
        });
    },

    loadObjects() {
        // Clear old
        this.objectMeshes.forEach(m => this.scene.remove(m));
        this.objectMeshes = [];
        this.portalMeshes.forEach(m => this.scene.remove(m));
        this.portalMeshes = [];

        const objects = GameState.getWorldObjects(this.currentWorld);
        objects.forEach(obj => {
            if (obj.type === 'portal') this.createPortal(obj);
            else if (obj.type === 'browser') this.createScreen(obj);
            else if (obj.type === 'decoration') this.createDecoration(obj);
        });
    },

    createPortal(obj) {
        const group = new THREE.Group();
        const color = new THREE.Color(obj.color || '#00d4aa');

        // Torus ring
        const torusGeo = new THREE.TorusGeometry(1.2, 0.12, 8, 24);
        const torusMat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 0.7,
            roughness: 0.2, metalness: 0.8
        });
        const torus = new THREE.Mesh(torusGeo, torusMat);
        torus.position.set(obj.position.x, (obj.position.y || 0) + 1.5, obj.position.z);
        group.add(torus);

        // Inner disc
        const innerGeo = new THREE.CircleGeometry(1, 16);
        const innerMat = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.15, side: THREE.DoubleSide });
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
        const lTex = new THREE.CanvasTexture(lCanvas);
        const lMat = new THREE.SpriteMaterial({ map: lTex, transparent: true });
        const label = new THREE.Sprite(lMat);
        label.position.set(obj.position.x, (obj.position.y || 0) + 3.5, obj.position.z);
        label.scale.set(2.5, 0.5, 1);
        group.add(label);

        group.userData = { type: 'portal', destination: obj.destination, name: obj.name, position: obj.position };
        this.scene.add(group);
        this.portalMeshes.push(group);
    },

    createScreen(obj) {
        const w = WORLDS[this.currentWorld];
        const geo = new THREE.PlaneGeometry(obj.size?.width || 6, obj.size?.height || 4);
        const mat = new THREE.MeshBasicMaterial({ color: 0x111122, transparent: true, opacity: 0.7 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(obj.position.x, obj.position.y || 3, obj.position.z);

        // Edge glow
        const edgeGeo = new THREE.EdgesGeometry(geo);
        const edgeMat = new THREE.LineBasicMaterial({ color: w.accent, transparent: true, opacity: 0.4 });
        mesh.add(new THREE.LineSegments(edgeGeo, edgeMat));

        // Label
        const c = document.createElement('canvas');
        c.width = 512; c.height = 64;
        const ctx = c.getContext('2d');
        ctx.font = 'bold 24px monospace';
        ctx.textAlign = 'center';
        ctx.fillStyle = '#00ffcc';
        ctx.fillText('📺 ' + obj.name, 256, 40);
        const tex = new THREE.CanvasTexture(c);
        const lMat = new THREE.SpriteMaterial({ map: tex, transparent: true });
        const label = new THREE.Sprite(lMat);
        label.position.y = (obj.size?.height || 4) / 2 + 0.6;
        label.scale.set(3.5, 0.5, 1);
        mesh.add(label);

        this.scene.add(mesh);
        this.objectMeshes.push(mesh);
    },

    createDecoration(obj) {
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
        this.scene.add(mesh);
        this.objectMeshes.push(mesh);
    },

    update(delta, time) {
        if (!this.active || !this.player) return;

        // Player movement
        const moveDir = new THREE.Vector3();
        if (this.keys['KeyW'] || this.keys['ArrowUp']) moveDir.z -= 1;
        if (this.keys['KeyS'] || this.keys['ArrowDown']) moveDir.z += 1;
        if (this.keys['KeyA'] || this.keys['ArrowLeft']) moveDir.x -= 1;
        if (this.keys['KeyD'] || this.keys['ArrowRight']) moveDir.x += 1;

        if (moveDir.length() > 0) {
            moveDir.normalize();
            this.player.mesh.position.x += moveDir.x * this.playerSpeed * delta;
            this.player.mesh.position.z += moveDir.z * this.playerSpeed * delta;

            // Face movement direction
            this.player.mesh.rotation.y = Math.atan2(moveDir.x, moveDir.z);

            // Walk animation
            const walkCycle = Math.sin(time * 8);
            this.player.armL.rotation.x = walkCycle * 0.4;
            this.player.armR.rotation.x = -walkCycle * 0.4;
            this.player.legL.rotation.x = -walkCycle * 0.3;
            this.player.legR.rotation.x = walkCycle * 0.3;
        } else {
            // Idle bob
            this.player.body.position.y = 0.9 + Math.sin(time * 2) * 0.05;
            this.player.head.position.y = 1.65 + Math.sin(time * 2) * 0.05;
            this.player.armL.rotation.x *= 0.9;
            this.player.armR.rotation.x *= 0.9;
            this.player.legL.rotation.x *= 0.9;
            this.player.legR.rotation.x *= 0.9;
        }

        // Clamp to bounds
        const w = WORLDS[this.currentWorld];
        this.player.mesh.position.x = Math.max(-w.bounds.x, Math.min(w.bounds.x, this.player.mesh.position.x));
        this.player.mesh.position.z = Math.max(-w.bounds.z, Math.min(w.bounds.z, this.player.mesh.position.z));

        // Camera follow (third person)
        const camTarget = this.player.mesh.position.clone().add(new THREE.Vector3(0, 8, 12));
        this.camera.position.lerp(camTarget, 0.05);
        this.camera.lookAt(this.player.mesh.position.x, 1, this.player.mesh.position.z);

        // Animate agents
        Object.values(this.agentMeshes).forEach(a => {
            a.group.position.lerp(a.targetPos, 0.03);
            a.body.position.y = 0.9 + Math.sin(time * 2 + a.group.position.x) * 0.08;
            a.head.position.y = 1.65 + Math.sin(time * 2 + a.group.position.x) * 0.08;
        });

        // Animate portals
        this.portalMeshes.forEach(g => {
            g.children.forEach(c => {
                if (c.isMesh && c.geometry.type === 'TorusGeometry') {
                    c.rotation.z = time * 0.5;
                    c.rotation.y = Math.sin(time * 0.3) * 0.2;
                }
            });
        });

        // Rotate particles
        if (this.particles) this.particles.rotation.y = time * 0.015;

        // Player ground ring pulse
        if (this.player.ring) {
            this.player.ring.material.opacity = 0.2 + Math.sin(time * 3) * 0.1;
        }

        // Check interaction proximity
        this.checkInteractions();

        // Periodic agent sync
        if (Math.floor(time) % 5 === 0 && Math.floor(time) !== this._lastSync) {
            this._lastSync = Math.floor(time);
            this.syncAgents();
        }
    },

    checkInteractions() {
        if (!this.player) return;
        const pPos = this.player.mesh.position;
        let nearest = null;
        let nearestDist = 4; // interaction range

        this.portalMeshes.forEach(p => {
            const pos = p.userData.position;
            if (!pos) return;
            const dist = Math.sqrt((pPos.x - pos.x) ** 2 + (pPos.z - pos.z) ** 2);
            if (dist < nearestDist) {
                nearest = p.userData;
                nearestDist = dist;
            }
        });

        const prompt = document.getElementById('interaction-prompt');
        if (nearest) {
            prompt.textContent = `Press E → ${nearest.name}`;
            prompt.classList.add('visible');
            this.interactTarget = nearest;
        } else {
            prompt.classList.remove('visible');
            this.interactTarget = null;
        }
    },

    interact() {
        if (!this.interactTarget) return;
        if (this.interactTarget.type === 'portal' && this.interactTarget.destination) {
            this.cleanup();
            Approach.start(this.interactTarget.destination);
        }
    },

    render() {
        if (!this.active) return;
        GameState.renderer.render(this.scene, this.camera);
    },

    cleanup() {
        this.active = false;
        window.removeEventListener('keydown', this.keyDown);
        window.removeEventListener('keyup', this.keyUp);
        this.keys = {};
        this.agentMeshes = {};
        this.objectMeshes = [];
        this.portalMeshes = [];
        document.getElementById('world-container').style.display = 'none';
        document.getElementById('interaction-prompt').classList.remove('visible');
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    }
};
