// World Core — WorldMode Orchestrator (Player, Camera, Game Loop)
const WorldMode = {
    scene: null,
    camera: null,
    active: false,
    currentWorld: null,
    player: null,
    playerSpeed: 8,
    keys: {},

    init(worldId) {
        this.currentWorld = worldId;
        this.active = true;
        GameState.currentWorld = worldId;

        const w = WORLDS[worldId];

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.sky);
        this.scene.fog = new THREE.FogExp2(w.fog, 0.012);

        // Camera
        this.camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 500);

        // Renderer
        const container = document.getElementById('world-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);
        container.style.display = 'block';

        // Show combat HUD
        document.getElementById('combat-hud').style.display = 'flex';

        // Build terrain, lanes, combat, agents
        WorldTerrain.build(this.scene, w, worldId);
        WorldLanes.init(this.scene, w);
        WorldCombat.init(this.scene);
        WorldAgents.loadObjects(this.scene, worldId);
        WorldAgents.syncAgents(this.scene, worldId);

        // Player
        this.createPlayer(w);

        // Key listeners
        this.keyDown = (e) => { this.keys[e.code] = true; };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // HUD
        if (typeof HUD !== 'undefined') {
            HUD.setWorld(worldId);
            HUD.showToast(`Landed on ${w.name} — SPACE to attack, WASD to move`);
        }
    },

    createPlayer(w) {
        const group = new THREE.Group();

        // Body
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

        // Eyes
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
        const ringMat = new THREE.MeshBasicMaterial({
            color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.3
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        group.position.set(0, 0, 5);
        this.player = { mesh: group, velocity: new THREE.Vector3(), body, head, armL, armR, legL, legR, ring };
        this.scene.add(group);
    },

    update(delta, time) {
        if (!this.active || !this.player) return;
        const w = WORLDS[this.currentWorld];

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

        // Player attack (SPACE)
        if (this.keys['Space']) {
            WorldCombat.playerAttack(this.player.mesh.position);
        }

        // Clamp to bounds
        this.player.mesh.position.x = Math.max(-w.bounds.x, Math.min(w.bounds.x, this.player.mesh.position.x));
        this.player.mesh.position.z = Math.max(-w.bounds.z, Math.min(w.bounds.z, this.player.mesh.position.z));

        // Camera follow
        const camTarget = this.player.mesh.position.clone().add(new THREE.Vector3(0, 8, 12));
        this.camera.position.lerp(camTarget, 0.05);
        this.camera.lookAt(this.player.mesh.position.x, 1, this.player.mesh.position.z);

        // Ground ring pulse
        if (this.player.ring) {
            this.player.ring.material.opacity = 0.2 + Math.sin(time * 3) * 0.1;
        }

        // Sub-system updates
        WorldTerrain.update(time);
        WorldLanes.updateTowerVisuals(time);
        WorldCombat.update(delta, time, this.player.mesh.position);
        WorldAgents.updateAnimations(time);
        WorldAgents.checkInteractions(this.player.mesh.position);

        // Periodic agent sync
        if (Math.floor(time) % 5 === 0 && Math.floor(time) !== this._lastSync) {
            this._lastSync = Math.floor(time);
            WorldAgents.syncAgents(this.scene, this.currentWorld);
        }
    },

    interact() {
        const dest = WorldAgents.interact();
        if (dest) {
            this.cleanup();
            Approach.start(dest);
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

        WorldCombat.cleanup();
        WorldLanes.cleanup();

        document.getElementById('world-container').style.display = 'none';
        document.getElementById('combat-hud').style.display = 'none';
        document.getElementById('interaction-prompt').classList.remove('visible');
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    }
};
