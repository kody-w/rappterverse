// Landing Mini-Game — Isometric Ship Descent
const LANDING_CONFIG = {
    gravity: 0.02,
    thrustPower: 0.04,
    manualControl: 0.012,
    fuelConsumption: 0.3,
    safeSpeed: 0.8,
    landingPadSize: 12,
    startAltitude: 80,
    bounds: 120
};

const MOVEMENT_KEYS = [
    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
    'KeyW', 'KeyA', 'KeyS', 'KeyD', 'Space', 'ShiftLeft', 'ShiftRight'
];

const Landing = {
    active: false,
    scene: null,
    camera: null,
    renderer: null,
    ship: null,
    propellers: null,
    thrustLight: null,
    beaconLight: null,
    targetWorld: null,
    isManual: false,
    altitude: 0,
    velocity: null,
    fuel: 0,
    landed: false,
    keys: {},
    animFrame: null,
    lastTime: 0,
    beaconTimer: 0,
    beaconOn: true,

    start(worldId) {
        this.targetWorld = worldId;
        this.active = true;
        this.landed = false;
        this.isManual = false;
        this.altitude = LANDING_CONFIG.startAltitude;
        this.velocity = { x: 0, y: 0, z: 0 };
        this.fuel = 100;
        this.keys = {};
        this.beaconTimer = 0;
        this.beaconOn = true;
        GameState.setMode('landing');

        const w = WORLDS[worldId];
        const overlay = document.getElementById('landing-overlay');
        overlay.classList.add('active');
        document.getElementById('landing-status').textContent = 'AUTOPILOT ENGAGED';

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.landingTerrain.sky);
        this.scene.fog = new THREE.Fog(w.landingTerrain.fog, 80, 300);

        // Isometric orthographic camera
        const aspect = window.innerWidth / window.innerHeight;
        const d = 50;
        this.camera = new THREE.OrthographicCamera(
            -d * aspect, d * aspect, d, -d, 1, 1000
        );
        this.camera.position.set(100, 100, 100);
        this.camera.lookAt(0, 0, 0);

        // Lighting
        this.scene.add(new THREE.AmbientLight(0x666666, 0.8));
        const dir = new THREE.DirectionalLight(0xffffff, 0.7);
        dir.position.set(50, 80, 50);
        this.scene.add(dir);
        const fill = new THREE.DirectionalLight(0x4466aa, 0.3);
        fill.position.set(-30, 40, -20);
        this.scene.add(fill);

        this.createTerrain(w);
        this.createEnvironment(w);
        this.createLandingPad();
        this.createShip();

        // Own renderer (separate from GameState.renderer)
        this.renderer = new THREE.WebGLRenderer({ antialias: true });
        this.renderer.setSize(window.innerWidth, window.innerHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        const container = document.getElementById('landing-canvas-container');
        container.innerHTML = '';
        container.appendChild(this.renderer.domElement);

        // Mode toggle button
        const modeBtn = document.getElementById('landing-mode-btn');
        modeBtn.textContent = 'TAKE CONTROL';
        modeBtn.onclick = () => this.toggleManual();

        // Key listeners
        this.keyDown = (e) => {
            this.keys[e.code] = true;
            if (!this.isManual && MOVEMENT_KEYS.includes(e.code)) {
                this.isManual = true;
                this.syncModeUI();
                HUD.showToast('Manual control activated');
            }
        };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // Resize handler
        this.resizeHandler = () => {
            const a = window.innerWidth / window.innerHeight;
            this.camera.left = -d * a;
            this.camera.right = d * a;
            this.camera.updateProjectionMatrix();
            this.renderer.setSize(window.innerWidth, window.innerHeight);
        };
        window.addEventListener('resize', this.resizeHandler);

        this.lastTime = performance.now();
        this.animate();
    },

    createTerrain(w) {
        const geo = new THREE.PlaneGeometry(300, 300, 60, 60);
        const positions = geo.attributes.position.array;
        const rng = seededRandom(this.targetWorld + '-terrain');
        for (let i = 0; i < positions.length; i += 3) {
            const x = positions[i], z = positions[i + 1];
            const dist = Math.sqrt(x * x + z * z);
            const heightFactor = Math.min(dist / 30, 1);
            positions[i + 2] = rng() * 6 * heightFactor;
        }
        geo.computeVertexNormals();
        const mat = new THREE.MeshStandardMaterial({
            color: w.landingTerrain.ground,
            roughness: 0.9,
            metalness: 0.1,
            flatShading: true
        });
        const terrain = new THREE.Mesh(geo, mat);
        terrain.rotation.x = -Math.PI / 2;
        this.scene.add(terrain);
    },

    createEnvironment(w) {
        const rng = seededRandom(this.targetWorld + '-env');
        const biome = w.biome;
        const padRadius = LANDING_CONFIG.landingPadSize + 5;

        for (let i = 0; i < 60; i++) {
            const angle = rng() * Math.PI * 2;
            const radius = padRadius + rng() * 80;
            const x = Math.cos(angle) * radius;
            const z = Math.sin(angle) * radius;

            let obj;
            if ((biome === 'Terra' || biome === 'Crystal') && rng() > 0.4) {
                // Trees
                const trunkGeo = new THREE.CylinderGeometry(0.4, 0.6, 3 + rng() * 4, 6);
                const trunkMat = new THREE.MeshStandardMaterial({
                    color: 0x664422, roughness: 0.9
                });
                obj = new THREE.Group();
                const trunk = new THREE.Mesh(trunkGeo, trunkMat);
                trunk.position.y = 1.5 + rng() * 2;
                obj.add(trunk);

                const canopySize = 2 + rng() * 3;
                const canopyGeo = new THREE.SphereGeometry(canopySize, 6, 5);
                const canopyMat = new THREE.MeshStandardMaterial({
                    color: biome === 'Crystal' ? 0x44ddcc : 0x228833,
                    roughness: 0.8,
                    flatShading: true
                });
                const canopy = new THREE.Mesh(canopyGeo, canopyMat);
                canopy.position.y = 3 + rng() * 4;
                obj.add(canopy);
            } else {
                // Rocks
                const size = 1 + rng() * 3;
                const rockGeo = new THREE.DodecahedronGeometry(size, 0);
                const rockMat = new THREE.MeshStandardMaterial({
                    color: 0x777777,
                    roughness: 0.95,
                    flatShading: true
                });
                obj = new THREE.Mesh(rockGeo, rockMat);
                obj.position.y = size * 0.4;
                obj.rotation.set(rng() * Math.PI, rng() * Math.PI, 0);
            }

            obj.position.x = x;
            obj.position.z = z;
            this.scene.add(obj);
        }
    },

    createLandingPad() {
        const ps = LANDING_CONFIG.landingPadSize;

        // Pad surface
        const padGeo = new THREE.CylinderGeometry(ps, ps, 1, 24);
        const padMat = new THREE.MeshStandardMaterial({
            color: 0x44ff44, roughness: 0.4, metalness: 0.3
        });
        const pad = new THREE.Mesh(padGeo, padMat);
        pad.position.y = 0.5;
        this.scene.add(pad);

        // White center marker
        const markerGeo = new THREE.CylinderGeometry(2, 2, 0.2, 16);
        const markerMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const marker = new THREE.Mesh(markerGeo, markerMat);
        marker.position.y = 1.15;
        this.scene.add(marker);

        // Beacon pole
        const poleGeo = new THREE.CylinderGeometry(0.3, 0.3, 8, 8);
        const poleMat = new THREE.MeshStandardMaterial({
            color: 0x888888, metalness: 0.6, roughness: 0.4
        });
        const pole = new THREE.Mesh(poleGeo, poleMat);
        pole.position.set(ps + 2, 4, 0);
        this.scene.add(pole);

        // Beacon light sphere
        const beaconGeo = new THREE.SphereGeometry(0.6, 8, 8);
        const beaconMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
        const beacon = new THREE.Mesh(beaconGeo, beaconMat);
        beacon.position.set(ps + 2, 8.5, 0);
        this.scene.add(beacon);
        this.beaconMesh = beacon;

        // Beacon point light
        this.beaconLight = new THREE.PointLight(0xff0000, 1, 40);
        this.beaconLight.position.set(ps + 2, 8.5, 0);
        this.scene.add(this.beaconLight);
    },

    createShip() {
        const rng = seededRandom(this.targetWorld + '-ship');
        const group = new THREE.Group();

        // Main body
        const bodyGeo = new THREE.BoxGeometry(6, 2, 6);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: 0x333333, metalness: 0.7, roughness: 0.3
        });
        group.add(new THREE.Mesh(bodyGeo, bodyMat));

        // Cockpit dome
        const cockpitGeo = new THREE.SphereGeometry(2, 12, 8);
        const cockpitMat = new THREE.MeshStandardMaterial({
            color: 0x00ffff, metalness: 0.4, roughness: 0.2,
            transparent: true, opacity: 0.85
        });
        const cockpit = new THREE.Mesh(cockpitGeo, cockpitMat);
        cockpit.scale.y = 0.6;
        cockpit.position.y = 1.2;
        group.add(cockpit);

        // Propeller arms and rotors
        const armPositions = [
            [-4, 0.5, -4], [4, 0.5, -4],
            [-4, 0.5, 4], [4, 0.5, 4]
        ];
        this.propellers = [];

        const armMat = new THREE.MeshStandardMaterial({
            color: 0x555555, metalness: 0.6, roughness: 0.4
        });
        const propMat = new THREE.MeshStandardMaterial({
            color: 0x999999, metalness: 0.5, roughness: 0.3,
            transparent: true, opacity: 0.7
        });

        for (const pos of armPositions) {
            // Arm strut
            const armGeo = new THREE.BoxGeometry(1, 0.4, 1);
            const arm = new THREE.Mesh(armGeo, armMat);
            arm.position.set(pos[0], pos[1], pos[2]);
            group.add(arm);

            // Propeller disc
            const propGeo = new THREE.CylinderGeometry(1.8, 1.8, 0.15, 16);
            const prop = new THREE.Mesh(propGeo, propMat);
            prop.position.set(pos[0], pos[1] + 0.5, pos[2]);
            group.add(prop);
            this.propellers.push(prop);
        }

        // Thrust light under ship
        this.thrustLight = new THREE.PointLight(0x00ff00, 1.5, 30);
        this.thrustLight.position.y = -1.5;
        group.add(this.thrustLight);

        // Random start position within ±40
        const startX = (rng() - 0.5) * 80;
        const startZ = (rng() - 0.5) * 80;
        group.position.set(startX, LANDING_CONFIG.startAltitude, startZ);

        this.ship = group;
        this.scene.add(group);
    },

    toggleManual() {
        this.isManual = !this.isManual;
        this.syncModeUI();
    },

    syncModeUI() {
        const btn = document.getElementById('landing-mode-btn');
        const status = document.getElementById('landing-status');
        if (this.isManual) {
            btn.textContent = 'ENGAGE AUTOPILOT';
            status.textContent = 'MANUAL CONTROL';
        } else {
            btn.textContent = 'TAKE CONTROL';
            status.textContent = 'AUTOPILOT ENGAGED';
        }
        // Thrust light color: green = autopilot, orange = manual
        if (this.thrustLight) {
            this.thrustLight.color.setHex(this.isManual ? 0xff8800 : 0x00ff00);
        }
    },

    animate() {
        if (!this.active || this.landed) return;
        this.animFrame = requestAnimationFrame(() => this.animate());

        const now = performance.now();
        const delta = Math.min((now - this.lastTime) / 1000, 0.05);
        this.lastTime = now;

        // Spin propellers
        for (const prop of this.propellers) {
            prop.rotation.y += delta * 50;
        }

        // Beacon blink (toggle every 500ms)
        this.beaconTimer += delta * 1000;
        if (this.beaconTimer >= 500) {
            this.beaconTimer -= 500;
            this.beaconOn = !this.beaconOn;
            if (this.beaconMesh) this.beaconMesh.visible = this.beaconOn;
            if (this.beaconLight) this.beaconLight.intensity = this.beaconOn ? 1 : 0;
        }

        // --- Physics ---
        // Gravity
        this.velocity.y -= LANDING_CONFIG.gravity;

        if (this.isManual) {
            this.updateManual(delta);
        } else {
            this.updateAutopilot(delta);
        }

        // Velocity damping
        this.velocity.x *= 0.96;
        this.velocity.y *= 0.96;
        this.velocity.z *= 0.96;

        // Update ship position
        this.ship.position.x += this.velocity.x;
        this.ship.position.y += this.velocity.y;
        this.ship.position.z += this.velocity.z;

        // Clamp within bounds
        const b = LANDING_CONFIG.bounds;
        this.ship.position.x = Math.max(-b, Math.min(b, this.ship.position.x));
        this.ship.position.z = Math.max(-b, Math.min(b, this.ship.position.z));
        if (this.ship.position.y < 0) this.ship.position.y = 0;

        this.altitude = this.ship.position.y;

        // Ship tilt based on velocity
        this.ship.rotation.z = this.velocity.x * 0.05;
        this.ship.rotation.x = -this.velocity.z * 0.05;

        // Camera follow (isometric offset tracking ship loosely)
        this.camera.position.set(
            100 + this.ship.position.x * 0.3,
            100 + this.ship.position.y * 0.3,
            100 + this.ship.position.z * 0.3
        );
        this.camera.lookAt(
            this.ship.position.x * 0.3,
            this.ship.position.y * 0.3,
            this.ship.position.z * 0.3
        );

        this.updateHUD();
        this.checkLanding();

        this.renderer.render(this.scene, this.camera);
    },

    updateManual(delta) {
        const mc = LANDING_CONFIG.manualControl;

        if (this.keys['ArrowUp'] || this.keys['KeyW']) this.velocity.z -= mc;
        if (this.keys['ArrowDown'] || this.keys['KeyS']) this.velocity.z += mc;
        if (this.keys['ArrowLeft'] || this.keys['KeyA']) this.velocity.x -= mc;
        if (this.keys['ArrowRight'] || this.keys['KeyD']) this.velocity.x += mc;

        if (this.keys['Space'] && this.fuel > 0) {
            this.velocity.y += LANDING_CONFIG.thrustPower;
            this.fuel = Math.max(0, this.fuel - LANDING_CONFIG.fuelConsumption * 1.5);
        }

        if (this.keys['ShiftLeft'] || this.keys['ShiftRight']) {
            this.velocity.y -= LANDING_CONFIG.thrustPower * 0.5;
        }

        // Manual fuel drain
        if (this.keys['ArrowUp'] || this.keys['KeyW'] || this.keys['ArrowDown'] || this.keys['KeyS'] ||
            this.keys['ArrowLeft'] || this.keys['KeyA'] || this.keys['ArrowRight'] || this.keys['KeyD']) {
            this.fuel = Math.max(0, this.fuel - LANDING_CONFIG.fuelConsumption * 0.5);
        }
    },

    updateAutopilot(delta) {
        const sx = this.ship.position.x;
        const sz = this.ship.position.z;
        const horizontalDist = Math.sqrt(sx * sx + sz * sz);
        const overPad = horizontalDist < LANDING_CONFIG.landingPadSize;

        let desiredVel = { x: 0, y: 0, z: 0 };

        if (this.altitude > 40) {
            // High altitude: slow descent
            desiredVel.y = -0.15 * 1.5;
            desiredVel.x = -sx * 0.01;
            desiredVel.z = -sz * 0.01;
        } else if (!overPad) {
            // Not over pad: hover and drift toward it
            desiredVel.y = -0.02;
            desiredVel.x = -sx * 0.02;
            desiredVel.z = -sz * 0.02;
        } else {
            // Over pad: very slow final descent
            desiredVel.y = -0.15 * 0.5;
            desiredVel.x = -sx * 0.005;
            desiredVel.z = -sz * 0.005;
        }

        // Lerp velocity toward desired
        const lerp = 0.03;
        this.velocity.x += (desiredVel.x - this.velocity.x) * lerp;
        this.velocity.y += (desiredVel.y - this.velocity.y) * lerp;
        this.velocity.z += (desiredVel.z - this.velocity.z) * lerp;

        // Slow fuel consumption on autopilot
        this.fuel = Math.max(0, this.fuel - LANDING_CONFIG.fuelConsumption * 0.1);
    },

    updateHUD() {
        const speed = Math.sqrt(
            this.velocity.x ** 2 + this.velocity.y ** 2 + this.velocity.z ** 2
        );
        const altEl = document.getElementById('landing-altitude');
        const spdEl = document.getElementById('landing-speed');
        const fuelEl = document.getElementById('landing-fuel');
        const fuelBar = document.getElementById('landing-fuel-bar');

        if (altEl) altEl.textContent = this.altitude.toFixed(1);
        if (spdEl) spdEl.textContent = speed.toFixed(2);
        if (fuelEl) fuelEl.textContent = Math.round(this.fuel) + '%';
        if (fuelBar) fuelBar.style.width = this.fuel + '%';

        // Warning colors
        if (altEl) altEl.className = 'landing-gauge-value' + (this.altitude < 10 ? ' warning' : '');
        if (spdEl) spdEl.className = 'landing-gauge-value' + (speed > LANDING_CONFIG.safeSpeed ? ' danger' : speed > 0.5 ? ' warning' : '');
    },

    checkLanding() {
        const speed = Math.sqrt(
            this.velocity.x ** 2 + this.velocity.y ** 2 + this.velocity.z ** 2
        );
        const sx = this.ship.position.x;
        const sz = this.ship.position.z;
        const horizontalDist = Math.sqrt(sx * sx + sz * sz);

        // Out of fuel at high altitude
        if (this.fuel <= 0 && this.altitude > 10) {
            this.resolveLanding(false, 'Out of fuel!');
            return;
        }

        if (this.altitude <= 3) {
            const onPad = horizontalDist < LANDING_CONFIG.landingPadSize;
            if (onPad && speed < LANDING_CONFIG.safeSpeed) {
                this.resolveLanding(true, null);
            } else if (speed >= LANDING_CONFIG.safeSpeed) {
                this.resolveLanding(false, 'Too fast!');
            } else {
                this.resolveLanding(false, 'Missed the landing pad!');
            }
        }
    },

    resolveLanding(success, reason) {
        this.landed = true;
        const status = document.getElementById('landing-status');
        const worldName = WORLDS[this.targetWorld].name;

        if (success) {
            status.textContent = '✅ LANDING SUCCESSFUL';
            status.style.color = '#00ff88';
            HUD.showToast(`Welcome to ${worldName}`);
        } else {
            status.textContent = `⚠️ CRASH — ${reason}`;
            status.style.color = '#ff4444';
            HUD.showToast('Crash landing!');
        }

        setTimeout(() => {
            if (!success) {
                HUD.showToast('Hull damage sustained');
            }
            this.cleanup();
            WorldMode.init(this.targetWorld);
        }, 2000);
    },

    cleanup() {
        this.active = false;
        if (this.animFrame) cancelAnimationFrame(this.animFrame);

        window.removeEventListener('keydown', this.keyDown);
        window.removeEventListener('keyup', this.keyUp);
        window.removeEventListener('resize', this.resizeHandler);
        this.keys = {};

        document.getElementById('landing-overlay').classList.remove('active');

        // Dispose scene resources
        if (this.scene) {
            this.scene.traverse(obj => {
                if (obj.geometry) obj.geometry.dispose();
                if (obj.material) {
                    if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
                    else obj.material.dispose();
                }
            });
        }

        // Dispose own renderer
        if (this.renderer) {
            this.renderer.dispose();
            if (this.renderer.domElement && this.renderer.domElement.parentNode) {
                this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
            }
        }

        this.scene = null;
        this.ship = null;
        this.propellers = null;
        this.thrustLight = null;
        this.beaconLight = null;
        this.beaconMesh = null;
        this.renderer = null;
    },

    abort() {
        this.cleanup();
        GameState.setMode('galaxy');
        Galaxy.show();
    }
