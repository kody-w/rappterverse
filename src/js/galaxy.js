// Galaxy View — Three.js Star System
const Galaxy = {
    scene: null,
    camera: null,
    active: false,
    planets: {},
    planetMeshes: [],
    starField: null,
    starMesh: null,
    orbitLines: [],
    cameraAngle: 0,
    selectedPlanetId: null,
    selectedIndex: 0,

    init() {
        this.active = true;

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x020208);

        // Camera
        this.camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 2000);
        this.camera.position.set(0, 60, 100);
        this.camera.lookAt(0, 0, 0);

        // Renderer (reuse or create)
        if (!GameState.renderer) {
            const isMobile = /iphone|ipad|android/i.test(navigator.userAgent);
            GameState.renderer = new THREE.WebGLRenderer({ antialias: !isMobile, powerPreference: isMobile ? 'low-power' : 'high-performance' });
            GameState.renderer.setSize(window.innerWidth, window.innerHeight);
            GameState.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
            GameState.renderer.toneMapping = THREE.ACESFilmicToneMapping;
            GameState.renderer.toneMappingExposure = 1.1;
            GameState.clock = new THREE.Clock();
        }

        const container = document.getElementById('galaxy-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);
        container.style.display = 'block';

        // Ambient light
        this.scene.add(new THREE.AmbientLight(0x222244, 0.5));

        // Central star
        this.createStar();

        // Starfield background
        this.createStarfield();

        // Planets
        this.createPlanets();

        // Orbit rings
        this.createOrbitRings();

        // Click handler
        GameState.renderer.domElement.addEventListener('click', (e) => this.onClick(e));

        // Planet info panel button
        document.getElementById('planet-approach-btn').addEventListener('click', () => {
            if (this.selectedPlanetId) {
                Approach.start(this.selectedPlanetId);
            }
        });

        // Show galaxy label
        document.querySelector('.galaxy-label').style.display = 'block';
    },

    createStar() {
        // Glowing central star
        const starGeo = new THREE.SphereGeometry(5, 32, 32);
        const starMat = new THREE.MeshBasicMaterial({
            color: 0xffffcc
        });
        this.starMesh = new THREE.Mesh(starGeo, starMat);
        this.scene.add(this.starMesh);

        // Star point light
        const light = new THREE.PointLight(0xffffaa, 2, 200);
        light.position.set(0, 0, 0);
        this.scene.add(light);

        // Star glow sprite
        const glowCanvas = document.createElement('canvas');
        glowCanvas.width = 128; glowCanvas.height = 128;
        const gctx = glowCanvas.getContext('2d');
        const gradient = gctx.createRadialGradient(64, 64, 0, 64, 64, 64);
        gradient.addColorStop(0, 'rgba(255,255,200,0.6)');
        gradient.addColorStop(0.3, 'rgba(255,220,100,0.3)');
        gradient.addColorStop(1, 'rgba(255,200,50,0)');
        gctx.fillStyle = gradient;
        gctx.fillRect(0, 0, 128, 128);
        const glowTexture = new THREE.CanvasTexture(glowCanvas);
        const glowMat = new THREE.SpriteMaterial({ map: glowTexture, transparent: true, blending: THREE.AdditiveBlending });
        const glow = new THREE.Sprite(glowMat);
        glow.scale.set(30, 30, 1);
        this.scene.add(glow);
    },

    createStarfield() {
        const count = 2500;
        const geo = new THREE.BufferGeometry();
        const positions = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);
        const rng = seededRandom('rappterverse-stars');

        for (let i = 0; i < count; i++) {
            // Distribute in sphere
            const theta = rng() * Math.PI * 2;
            const phi = Math.acos(2 * rng() - 1);
            const r = 300 + rng() * 500;
            positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
            positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
            positions[i * 3 + 2] = r * Math.cos(phi);

            // Slight color variation
            const brightness = 0.5 + rng() * 0.5;
            colors[i * 3] = brightness;
            colors[i * 3 + 1] = brightness * (0.8 + rng() * 0.2);
            colors[i * 3 + 2] = brightness;
        }

        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        const mat = new THREE.PointsMaterial({
            size: 0.8, vertexColors: true, transparent: true,
            opacity: 0.8, sizeAttenuation: true,
            blending: THREE.AdditiveBlending
        });
        this.starField = new THREE.Points(geo, mat);
        this.scene.add(this.starField);
    },

    createPlanets() {
        this.planetMeshes = [];
        WORLD_IDS.forEach((id, idx) => {
            const w = WORLDS[id];
            const group = new THREE.Group();

            // Planet sphere
            const geo = new THREE.SphereGeometry(3 + idx * 0.5, 24, 24);
            const mat = new THREE.MeshStandardMaterial({
                color: w.planetColor,
                roughness: 0.6, metalness: 0.3,
                emissive: w.planetColor,
                emissiveIntensity: 0.15
            });
            const mesh = new THREE.Mesh(geo, mat);
            group.add(mesh);

            // Atmosphere glow
            const atmoGeo = new THREE.SphereGeometry(3.5 + idx * 0.5, 24, 24);
            const atmoMat = new THREE.MeshBasicMaterial({
                color: w.planetColor, transparent: true, opacity: 0.1,
                side: THREE.BackSide
            });
            group.add(new THREE.Mesh(atmoGeo, atmoMat));

            // Name label sprite
            const labelCanvas = document.createElement('canvas');
            labelCanvas.width = 256; labelCanvas.height = 64;
            const lctx = labelCanvas.getContext('2d');
            lctx.font = 'bold 22px monospace';
            lctx.textAlign = 'center';
            lctx.fillStyle = '#ffffff';
            lctx.fillText(w.name, 128, 30);
            lctx.font = '14px monospace';
            lctx.fillStyle = '#aaaaaa';
            lctx.fillText(w.biome, 128, 50);
            const labelTex = new THREE.CanvasTexture(labelCanvas);
            const labelMat = new THREE.SpriteMaterial({ map: labelTex, transparent: true });
            const label = new THREE.Sprite(labelMat);
            label.position.y = 6;
            label.scale.set(8, 2, 1);
            group.add(label);

            // Set initial orbital position
            const angle = (idx / WORLD_IDS.length) * Math.PI * 2;
            group.position.x = Math.cos(angle) * w.orbitRadius;
            group.position.z = Math.sin(angle) * w.orbitRadius;

            group.userData = { worldId: id, orbitAngle: angle };
            this.scene.add(group);
            this.planetMeshes.push(group);
            this.planets[id] = group;
        });
    },

    createOrbitRings() {
        WORLD_IDS.forEach((id, idx) => {
            const w = WORLDS[id];
            const geo = new THREE.RingGeometry(w.orbitRadius - 0.1, w.orbitRadius + 0.1, 64);
            const mat = new THREE.MeshBasicMaterial({
                color: w.planetColor, transparent: true, opacity: 0.08, side: THREE.DoubleSide
            });
            const ring = new THREE.Mesh(geo, mat);
            ring.rotation.x = -Math.PI / 2;
            this.scene.add(ring);
            this.orbitLines.push(ring);
        });
    },

    selectPlanet(worldId) {
        this.selectedPlanetId = worldId;
        this.selectedIndex = WORLD_IDS.indexOf(worldId);
        GameState.selectedPlanet = worldId;

        const w = WORLDS[worldId];
        const agentCount = GameState.getAgentCount(worldId);
        const config = GameState.getWorldConfig(worldId);
        const objects = GameState.getWorldObjects(worldId);

        // Update info panel
        document.getElementById('planet-name').textContent = w.name;
        document.getElementById('planet-biome').textContent = w.biome;
        document.getElementById('planet-biome').style.background = `rgba(${this.hexToRgb(w.planetColor)}, 0.2)`;
        document.getElementById('planet-biome').style.color = `#${w.planetColor.toString(16).padStart(6, '0')}`;

        document.getElementById('planet-stats').innerHTML = `
            <div class="planet-info-stat"><span>Agents</span><span class="planet-info-value">${agentCount}</span></div>
            <div class="planet-info-stat"><span>Biome</span><span class="planet-info-value">${w.biome}</span></div>
            <div class="planet-info-stat"><span>Bounds</span><span class="planet-info-value">±${w.bounds.x} × ±${w.bounds.z}</span></div>
            <div class="planet-info-stat"><span>Objects</span><span class="planet-info-value">${objects.length}</span></div>
            <div class="planet-info-stat"><span>Chat</span><span class="planet-info-value">${config.features?.chat ? '✅' : '❌'}</span></div>
            <div class="planet-info-stat"><span>Trading</span><span class="planet-info-value">${config.features?.trading ? '✅' : '❌'}</span></div>
        `;

        document.getElementById('planet-info').classList.add('visible');

        // Highlight planet (increase emissive)
        this.planetMeshes.forEach(p => {
            const isSelected = p.userData.worldId === worldId;
            p.children[0].material.emissiveIntensity = isSelected ? 0.5 : 0.15;
            p.children[1].material.opacity = isSelected ? 0.25 : 0.1;
        });
    },

    deselectPlanet() {
        this.selectedPlanetId = null;
        GameState.selectedPlanet = null;
        document.getElementById('planet-info').classList.remove('visible');
        this.planetMeshes.forEach(p => {
            p.children[0].material.emissiveIntensity = 0.15;
            p.children[1].material.opacity = 0.1;
        });
    },

    browsePlanets(dir) {
        this.selectedIndex = (this.selectedIndex + dir + WORLD_IDS.length) % WORLD_IDS.length;
        this.selectPlanet(WORLD_IDS[this.selectedIndex]);
    },

    onClick(event) {
        if (GameState.mode !== 'galaxy') return;
        const mouse = new THREE.Vector2(
            (event.clientX / window.innerWidth) * 2 - 1,
            -(event.clientY / window.innerHeight) * 2 + 1
        );
        const raycaster = new THREE.Raycaster();
        raycaster.setFromCamera(mouse, this.camera);
        const intersects = raycaster.intersectObjects(this.planetMeshes, true);
        if (intersects.length > 0) {
            let obj = intersects[0].object;
            while (obj.parent && !obj.userData.worldId) obj = obj.parent;
            if (obj.userData.worldId) {
                // Click planet → start approach directly (like LEVIATHAN)
                Approach.start(obj.userData.worldId);
            }
        }
    },

    update(delta, time) {
        if (!this.active) return;

        // Orbit planets
        this.planetMeshes.forEach((group, idx) => {
            const w = WORLDS[WORLD_IDS[idx]];
            group.userData.orbitAngle += w.orbitSpeed * delta;
            group.position.x = Math.cos(group.userData.orbitAngle) * w.orbitRadius;
            group.position.z = Math.sin(group.userData.orbitAngle) * w.orbitRadius;
            // Slow planet rotation
            group.children[0].rotation.y += delta * 0.2;
        });

        // Camera orbit
        this.cameraAngle += delta * 0.05;
        this.camera.position.x = Math.cos(this.cameraAngle) * 110;
        this.camera.position.z = Math.sin(this.cameraAngle) * 110;
        this.camera.position.y = 50 + Math.sin(this.cameraAngle * 0.5) * 10;
        this.camera.lookAt(0, 0, 0);

        // Star pulse
        if (this.starMesh) {
            const pulse = 1 + Math.sin(time * 2) * 0.05;
            this.starMesh.scale.setScalar(pulse);
        }

        // Rotate starfield slowly
        if (this.starField) {
            this.starField.rotation.y += delta * 0.003;
        }
    },

    render() {
        if (!this.active) return;
        GameState.renderer.render(this.scene, this.camera);
    },

    hide() {
        this.active = false;
        document.getElementById('galaxy-container').style.display = 'none';
        document.querySelector('.galaxy-label').style.display = 'none';
        this.deselectPlanet();
    },

    show() {
        this.active = true;
        document.getElementById('galaxy-container').style.display = 'block';
        document.querySelector('.galaxy-label').style.display = 'block';
    },

    hexToRgb(hex) {
        return `${(hex >> 16) & 255}, ${(hex >> 8) & 255}, ${hex & 255}`;
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    }
};
