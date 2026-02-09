// Landing Mini-Game — Ship Descent
const Landing = {
    active: false,
    scene: null,
    camera: null,
    ship: null,
    targetWorld: null,
    isManual: false,
    altitude: 60,
    velocity: { x: 0, y: -0.5, z: 0 },
    fuel: 100,
    landed: false,
    padPosition: { x: 0, z: 0 },
    keys: {},
    animFrame: null,

    config: {
        gravity: 0.015,
        thrustPower: 0.04,
        lateralSpeed: 0.2,
        fuelConsumption: 0.015,
        safeSpeed: 2.5,
        padSize: 12
    },

    start(worldId) {
        this.targetWorld = worldId;
        this.active = true;
        this.landed = false;
        this.isManual = false;
        this.altitude = 60;
        this.velocity = { x: 0, y: -0.5, z: 0 };
        this.fuel = 100;
        GameState.setMode('landing');

        const w = WORLDS[worldId];
        const overlay = document.getElementById('landing-overlay');
        overlay.classList.add('active');
        document.getElementById('landing-status').textContent = 'AUTOPILOT ENGAGED';

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.landingTerrain.sky);
        this.scene.fog = new THREE.Fog(w.landingTerrain.fog, 50, 200);

        // Camera (orthographic top-down-ish)
        this.camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 500);
        this.camera.position.set(0, 80, 40);
        this.camera.lookAt(0, 0, 0);

        // Lights
        this.scene.add(new THREE.AmbientLight(0x666666, 0.8));
        const dir = new THREE.DirectionalLight(0xffffff, 0.6);
        dir.position.set(10, 30, 10);
        this.scene.add(dir);

        // Terrain
        this.createTerrain(w);

        // Landing pad
        this.createLandingPad(w);

        // Ship
        this.createShip(w);

        // Renderer
        const container = document.getElementById('landing-canvas-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);

        // Controls
        const modeBtn = document.getElementById('landing-mode-btn');
        modeBtn.textContent = 'TAKE CONTROL';
        modeBtn.onclick = () => this.toggleManual();

        // Key listeners
        this.keyDown = (e) => { this.keys[e.code] = true; };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // Start loop
        this.lastTime = performance.now();
        this.animate();
    },

    createTerrain(w) {
        const geo = new THREE.PlaneGeometry(200, 200, 40, 40);
        const positions = geo.attributes.position.array;
        const rng = seededRandom(this.targetWorld + '-terrain');
        for (let i = 0; i < positions.length; i += 3) {
            // Don't displace center (landing pad area)
            const x = positions[i], z = positions[i + 1];
            const distFromCenter = Math.sqrt(x * x + z * z);
            const heightFactor = Math.min(distFromCenter / 30, 1);
            positions[i + 2] = rng() * 8 * heightFactor;
        }
        geo.computeVertexNormals();
        const mat = new THREE.MeshStandardMaterial({
            color: w.landingTerrain.ground, roughness: 0.9, metalness: 0.1,
            flatShading: true
        });
        const terrain = new THREE.Mesh(geo, mat);
        terrain.rotation.x = -Math.PI / 2;
        this.scene.add(terrain);
    },

    createLandingPad(w) {
        // Flat pad
        const padGeo = new THREE.CylinderGeometry(this.config.padSize / 2, this.config.padSize / 2, 0.3, 16);
        const padMat = new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.5, metalness: 0.5 });
        const pad = new THREE.Mesh(padGeo, padMat);
        pad.position.y = 0.15;
        this.scene.add(pad);

        // Beacon
        const beaconGeo = new THREE.CylinderGeometry(0.2, 0.2, 3, 8);
        const beaconMat = new THREE.MeshBasicMaterial({ color: 0x00ff88 });
        const beacon = new THREE.Mesh(beaconGeo, beaconMat);
        beacon.position.y = 1.5;
        this.scene.add(beacon);

        // Beacon light
        const beaconLight = new THREE.PointLight(0x00ff88, 1, 30);
        beaconLight.position.y = 3;
        this.scene.add(beaconLight);

        // Landing ring
        const ringGeo = new THREE.RingGeometry(this.config.padSize / 2 - 0.5, this.config.padSize / 2, 24);
        const ringMat = new THREE.MeshBasicMaterial({ color: WORLDS[this.targetWorld].accent, side: THREE.DoubleSide, transparent: true, opacity: 0.4 });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.35;
        this.scene.add(ring);
    },

    createShip(w) {
        const group = new THREE.Group();

        // Body
        const bodyGeo = new THREE.BoxGeometry(2, 1, 3);
        const bodyMat = new THREE.MeshStandardMaterial({ color: 0x8888aa, metalness: 0.7, roughness: 0.3 });
        group.add(new THREE.Mesh(bodyGeo, bodyMat));

        // Nose cone
        const noseGeo = new THREE.ConeGeometry(1, 2, 4);
        const noseMat = new THREE.MeshStandardMaterial({ color: 0xaaaacc, metalness: 0.7, roughness: 0.3 });
        const nose = new THREE.Mesh(noseGeo, noseMat);
        nose.rotation.x = Math.PI / 2;
        nose.position.z = -2.5;
        group.add(nose);

        // Wings
        const wingGeo = new THREE.BoxGeometry(5, 0.1, 1.5);
        const wingMat = new THREE.MeshStandardMaterial({ color: 0x666688, metalness: 0.6, roughness: 0.4 });
        const wing = new THREE.Mesh(wingGeo, wingMat);
        wing.position.z = 0.5;
        group.add(wing);

        // Thruster glow
        const thrustGeo = new THREE.ConeGeometry(0.5, 2, 8);
        const thrustMat = new THREE.MeshBasicMaterial({ color: w.accent || 0x00aaff, transparent: true, opacity: 0.6 });
        const thrust = new THREE.Mesh(thrustGeo, thrustMat);
        thrust.rotation.x = -Math.PI / 2;
        thrust.position.z = 2.5;
        thrust.position.y = -0.3;
        thrust.visible = true;
        group.add(thrust);
        this.thrustMesh = thrust;

        group.position.y = this.altitude;
        this.ship = group;
        this.scene.add(group);
    },

    toggleManual() {
        this.isManual = !this.isManual;
        const btn = document.getElementById('landing-mode-btn');
        btn.textContent = this.isManual ? 'ENGAGE AUTOPILOT' : 'TAKE CONTROL';
        document.getElementById('landing-status').textContent = this.isManual ? 'MANUAL CONTROL' : 'AUTOPILOT ENGAGED';
    },

    animate() {
        if (!this.active || this.landed) return;
        this.animFrame = requestAnimationFrame(() => this.animate());

        const now = performance.now();
        const delta = Math.min((now - this.lastTime) / 1000, 0.05);
        this.lastTime = now;

        // Gravity
        this.velocity.y -= this.config.gravity;

        if (this.isManual) {
            // Manual thrust
            if ((this.keys['Space'] || this.keys['ArrowUp'] || this.keys['KeyW']) && this.fuel > 0) {
                this.velocity.y += this.config.thrustPower;
                this.fuel = Math.max(0, this.fuel - this.config.fuelConsumption);
            }
            if (this.keys['ArrowLeft'] || this.keys['KeyA']) this.velocity.x -= this.config.lateralSpeed * delta;
            if (this.keys['ArrowRight'] || this.keys['KeyD']) this.velocity.x += this.config.lateralSpeed * delta;
            if (this.keys['ArrowDown'] || this.keys['KeyS']) this.velocity.z += this.config.lateralSpeed * delta;
        } else {
            // Autopilot — smooth descent toward pad center
            const targetVelY = -0.8 - (this.altitude / 60) * 0.5;
            this.velocity.y += (targetVelY - this.velocity.y) * 0.02;
            this.velocity.x *= 0.95; // dampen lateral
            this.velocity.z *= 0.95;
            // Steer toward center
            if (this.ship) {
                this.velocity.x += (0 - this.ship.position.x) * 0.001;
                this.velocity.z += (0 - this.ship.position.z) * 0.001;
            }
        }

        // Clamp velocity
        const maxSpeed = 3;
        this.velocity.x = Math.max(-maxSpeed, Math.min(maxSpeed, this.velocity.x));
        this.velocity.z = Math.max(-maxSpeed, Math.min(maxSpeed, this.velocity.z));

        // Update position
        if (this.ship) {
            this.ship.position.y += this.velocity.y;
            this.ship.position.x += this.velocity.x;
            this.ship.position.z += this.velocity.z;
            this.altitude = Math.max(0, this.ship.position.y);

            // Tilt ship based on lateral velocity
            this.ship.rotation.z = -this.velocity.x * 0.3;
            this.ship.rotation.x = this.velocity.z * 0.1;

            // Thrust visibility
            if (this.thrustMesh) {
                this.thrustMesh.visible = this.velocity.y > -0.3;
                this.thrustMesh.scale.y = 0.5 + Math.random() * 0.5;
            }
        }

        // Camera follow
        if (this.ship) {
            this.camera.position.x = this.ship.position.x;
            this.camera.position.y = this.ship.position.y + 20;
            this.camera.position.z = this.ship.position.z + 25;
            this.camera.lookAt(this.ship.position);
        }

        // Update HUD
        this.updateHUD();

        // Check landing
        if (this.altitude <= 0.5) {
            this.land();
        }

        // Render
        GameState.renderer.render(this.scene, this.camera);
    },

    updateHUD() {
        const speed = Math.sqrt(this.velocity.x ** 2 + this.velocity.y ** 2 + this.velocity.z ** 2);
        const altEl = document.getElementById('landing-altitude');
        const spdEl = document.getElementById('landing-speed');
        const fuelEl = document.getElementById('landing-fuel');
        const fuelBar = document.getElementById('landing-fuel-bar');

        altEl.textContent = this.altitude.toFixed(1);
        spdEl.textContent = speed.toFixed(1);
        fuelEl.textContent = Math.round(this.fuel) + '%';
        fuelBar.style.width = this.fuel + '%';

        // Color warnings
        altEl.className = 'landing-gauge-value' + (this.altitude < 10 ? ' warning' : '');
        spdEl.className = 'landing-gauge-value' + (speed > this.config.safeSpeed ? ' danger' : speed > 1.5 ? ' warning' : '');
    },

    land() {
        this.landed = true;
        const speed = Math.sqrt(this.velocity.x ** 2 + this.velocity.y ** 2 + this.velocity.z ** 2);
        const status = document.getElementById('landing-status');

        if (speed > this.config.safeSpeed) {
            status.textContent = '⚠️ HARD LANDING — HULL STRESS DETECTED';
            status.style.color = '#ff4444';
        } else {
            status.textContent = '✅ LANDING SUCCESSFUL';
            status.style.color = '#00ff88';
        }

        if (typeof HUD !== 'undefined' && HUD.showToast) {
            HUD.showToast(`Landed on ${WORLDS[this.targetWorld].name}`);
        }

        // Transition to world after delay
        setTimeout(() => this.transitionToWorld(), 2000);
    },

    transitionToWorld() {
        this.cleanup();
        GameState.setMode('world');
        WorldMode.init(this.targetWorld);
    },

    cleanup() {
        this.active = false;
        if (this.animFrame) cancelAnimationFrame(this.animFrame);
        window.removeEventListener('keydown', this.keyDown);
        window.removeEventListener('keyup', this.keyUp);
        this.keys = {};
        document.getElementById('landing-overlay').classList.remove('active');

        // Dispose scene
        if (this.scene) {
            this.scene.traverse(obj => {
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) {
                    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
                    else obj.material.dispose();
                }
            });
        }
        this.scene = null;
        this.ship = null;
    }
};
