// World Core — WorldMode Orchestrator (Player, Camera, Game Loop)
const WorldMode = {
    scene: null,
    camera: null,
    active: false,
    currentWorld: null,
    player: null,
    playerSpeed: 25,
    keys: {},

    init(worldId) {
        this.currentWorld = worldId;
        this.active = true;
        GameState.currentWorld = worldId;

        const w = WORLDS[worldId];

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.sky);
        this.scene.fog = new THREE.FogExp2(w.fog, 0.002);

        // Camera
        this.camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 2000);

        // Renderer
        const container = document.getElementById('world-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);
        container.style.display = 'block';

        // Show combat HUD
        document.getElementById('combat-hud').style.display = 'flex';
        const statsBar = document.getElementById('player-stats-bar');
        if (statsBar) statsBar.style.display = 'flex';
        const levelBadge = document.getElementById('level-badge');
        if (levelBadge) levelBadge.style.display = 'block';
        const abilityBar = document.getElementById('ability-bar');
        if (abilityBar) abilityBar.style.display = 'flex';

        // Build terrain, lanes, combat, agents
        WorldTerrain.build(this.scene, w, worldId);
        WorldLanes.init(this.scene, w);
        WorldCombat.init(this.scene);
        WorldAgents.loadObjects(this.scene, worldId);
        WorldAgents.syncAgents(this.scene, worldId);

        // Init RPG systems
        if (typeof PlayerStats !== 'undefined') PlayerStats.init();
        if (typeof Abilities !== 'undefined') Abilities.init();
        if (typeof ComboSystem !== 'undefined') ComboSystem.reset();
        if (typeof Inventory !== 'undefined') Inventory.init();
        if (typeof Equipment !== 'undefined') Equipment.init();
        if (typeof StatusEffects !== 'undefined') StatusEffects.cleanup();
        if (typeof EnemyHero !== 'undefined') EnemyHero.init(this.scene, w.bounds);

        // Player
        this.createPlayer(w);

        // Deep link: teleport player to target agent
        if (GameState.deepLink?.agent) {
            const target = GameState.data.agents.find(a => a.id === GameState.deepLink.agent);
            if (target && target.position) {
                this.player.mesh.position.set(target.position.x + 2, 0, target.position.z + 2);
            }
            GameState.deepLink = null; // consume deep link
        }

        // Key listeners
        this.keyDown = (e) => { this.keys[e.code] = true; };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // Set mode to world so main loop renders us
        GameState.setMode('world');

        // HUD
        if (typeof HUD !== 'undefined') {
            HUD.setWorld(worldId);
            HUD.showToast(`Landed on ${w.name} — SPACE to attack, WASD to move`);
        }
    },

    createPlayer(w) {
        const group = new THREE.Group();

        // Body
        const bodyGeo = new THREE.CylinderGeometry(0.35, 0.35, 1.05, 8);
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
        WorldTerrain.update(time, delta);
        WorldLanes.updateTowerVisuals(time);
        WorldCombat.update(delta, time, this.player.mesh.position);
        WorldAgents.updateAnimations(time);
        WorldAgents.checkInteractions(this.player.mesh.position);

        // RPG system updates
        if (typeof PlayerStats !== 'undefined') {
            PlayerStats.update(delta);
            if (PlayerStats.dead) return; // Skip everything while dead
        }
        if (typeof Abilities !== 'undefined') Abilities.update(delta);
        if (typeof ComboSystem !== 'undefined') ComboSystem.update(delta);
        if (typeof Inventory !== 'undefined') {
            Inventory.collectNearby(this.player.mesh.position);
            Inventory.updateDrops(time);
        }

        // Enemy hero update
        if (typeof EnemyHero !== 'undefined') {
            EnemyHero.update(delta, time, this.player.mesh.position);
        }

        // Creep damage to player
        if (typeof PlayerStats !== 'undefined' && !PlayerStats.dead) {
            for (const creep of WorldCombat.creeps) {
                if (!creep.alive || creep.faction !== 'horde') continue;
                const dx = this.player.mesh.position.x - creep.mesh.position.x;
                const dz = this.player.mesh.position.z - creep.mesh.position.z;
                if (Math.sqrt(dx*dx + dz*dz) < 2) {
                    PlayerStats.takeDamage(creep.isBoss ? 3 * delta : 1 * delta);
                }
            }
        }

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

    pokeAgent() {
        WorldAgents.poke(this.currentWorld);
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
        if (typeof Abilities !== 'undefined') Abilities.cleanup();
        if (typeof Inventory !== 'undefined') Inventory.cleanup();
        if (typeof Equipment !== 'undefined') Equipment.cleanup();
        if (typeof StatusEffects !== 'undefined') StatusEffects.cleanup();
        if (typeof EnemyHero !== 'undefined') EnemyHero.cleanup();

        document.getElementById('world-container').style.display = 'none';
        document.getElementById('combat-hud').style.display = 'none';
        document.getElementById('interaction-prompt').classList.remove('visible');
        const statsBar = document.getElementById('player-stats-bar');
        if (statsBar) statsBar.style.display = 'none';
        const levelBadge = document.getElementById('level-badge');
        if (levelBadge) levelBadge.style.display = 'none';
        const abilityBar = document.getElementById('ability-bar');
        if (abilityBar) abilityBar.style.display = 'none';
        const comboEl = document.getElementById('combo-display');
        if (comboEl) comboEl.style.display = 'none';
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    }
};
