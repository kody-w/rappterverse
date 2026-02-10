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

        // Nebulae
        this.createNebulae();

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
        const count = 8000;
        const geo = new THREE.BufferGeometry();
        const positions = new Float32Array(count * 3);
        const colors = new Float32Array(count * 3);
        const rng = seededRandom('rappterverse-stars');

        for (let i = 0; i < count; i++) {
            const theta = rng() * Math.PI * 2;
            const phi = Math.acos(2 * rng() - 1);
            const r = 300 + rng() * 500;
            positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
            positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
            positions[i * 3 + 2] = r * Math.cos(phi);

            // Star color temperature variation
            const temp = rng();
            const brightness = 0.5 + rng() * 0.5;
            if (temp < 0.3) {
                // Blue-white hot stars
                colors[i * 3] = brightness * 0.7;
                colors[i * 3 + 1] = brightness * 0.8;
                colors[i * 3 + 2] = brightness;
            } else if (temp < 0.7) {
                // Yellow-white sun-like
                colors[i * 3] = brightness;
                colors[i * 3 + 1] = brightness * 0.95;
                colors[i * 3 + 2] = brightness * 0.7;
            } else {
                // Orange-red cool stars
                colors[i * 3] = brightness;
                colors[i * 3 + 1] = brightness * 0.5;
                colors[i * 3 + 2] = brightness * 0.3;
            }
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

    createNebulae() {
        const rng = seededRandom('rappterverse-nebulae');
        const nebulaColors = [
            [{ r: 80, g: 20, b: 120 }, { r: 40, g: 10, b: 80 }, { r: 20, g: 5, b: 50 }],
            [{ r: 20, g: 40, b: 120 }, { r: 10, g: 20, b: 80 }, { r: 5, g: 10, b: 50 }],
            [{ r: 100, g: 20, b: 80 }, { r: 60, g: 10, b: 50 }, { r: 30, g: 5, b: 30 }],
            [{ r: 20, g: 80, b: 100 }, { r: 10, g: 50, b: 60 }, { r: 5, g: 25, b: 35 }],
            [{ r: 60, g: 20, b: 100 }, { r: 30, g: 10, b: 60 }, { r: 15, g: 5, b: 35 }],
            [{ r: 20, g: 60, b: 120 }, { r: 10, g: 30, b: 80 }, { r: 5, g: 15, b: 45 }]
        ];
        for (let i = 0; i < 6; i++) {
            const canvas = document.createElement('canvas');
            canvas.width = 128; canvas.height = 128;
            const ctx = canvas.getContext('2d');
            const c = nebulaColors[i];
            const grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
            grad.addColorStop(0, `rgba(${c[0].r},${c[0].g},${c[0].b},0.4)`);
            grad.addColorStop(0.4, `rgba(${c[1].r},${c[1].g},${c[1].b},0.2)`);
            grad.addColorStop(0.7, `rgba(${c[2].r},${c[2].g},${c[2].b},0.08)`);
            grad.addColorStop(1, 'rgba(0,0,0,0)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, 128, 128);
            const texture = new THREE.CanvasTexture(canvas);
            const mat = new THREE.SpriteMaterial({
                map: texture, transparent: true,
                blending: THREE.AdditiveBlending,
                opacity: 0.08 + rng() * 0.07
            });
            const sprite = new THREE.Sprite(mat);
            const theta = rng() * Math.PI * 2;
            const phi = Math.acos(2 * rng() - 1);
            const dist = 200 + rng() * 300;
            sprite.position.set(
                dist * Math.sin(phi) * Math.cos(theta),
                dist * Math.sin(phi) * Math.sin(theta),
                dist * Math.cos(phi)
            );
            const scale = 80 + rng() * 70;
            sprite.scale.set(scale, scale, 1);
            this.scene.add(sprite);
        }
    },

    generatePlanetTexture(biome, color) {
        const canvas = document.createElement('canvas');
        canvas.width = 256; canvas.height = 256;
        const ctx = canvas.getContext('2d');
        const rng = seededRandom('planet-tex-' + biome);

        // Value noise with smoothstep interpolation
        function noiseGrid(gridSize) {
            const grid = [];
            for (let y = 0; y < gridSize; y++) {
                grid[y] = [];
                for (let x = 0; x < gridSize; x++) grid[y][x] = rng();
            }
            return grid;
        }
        function sampleNoise(grid, x, y) {
            const gs = grid.length;
            const gx = (x / 256) * gs;
            const gy = (y / 256) * gs;
            const x0 = Math.floor(gx) % gs, y0 = Math.floor(gy) % gs;
            const x1 = (x0 + 1) % gs, y1 = (y0 + 1) % gs;
            const fx = gx - Math.floor(gx), fy = gy - Math.floor(gy);
            const sfx = fx * fx * (3 - 2 * fx), sfy = fy * fy * (3 - 2 * fy);
            const top = grid[y0][x0] * (1 - sfx) + grid[y0][x1] * sfx;
            const bot = grid[y1][x0] * (1 - sfx) + grid[y1][x1] * sfx;
            return top * (1 - sfy) + bot * sfy;
        }
        const grids = [noiseGrid(4), noiseGrid(8), noiseGrid(16), noiseGrid(32)];
        function fbm(x, y) {
            return sampleNoise(grids[0], x, y) * 0.5 +
                   sampleNoise(grids[1], x, y) * 0.25 +
                   sampleNoise(grids[2], x, y) * 0.15 +
                   sampleNoise(grids[3], x, y) * 0.1;
        }

        const imgData = ctx.createImageData(256, 256);
        const d = imgData.data;
        for (let y = 0; y < 256; y++) {
            for (let x = 0; x < 256; x++) {
                const idx = (y * 256 + x) * 4;
                const n = fbm(x, y);
                const lat = Math.abs(y - 128) / 128;
                let r, g, b;
                switch (biome) {
                    case 'Terra':
                        if (lat > 0.85) {
                            r = 220 + n * 35; g = 230 + n * 25; b = 240;
                        } else if (n > 0.45) {
                            r = 40 + n * 60; g = 100 + n * 80; b = 30 + n * 30;
                        } else {
                            r = 20 + n * 30; g = 60 + n * 40; b = 140 + n * 60;
                        }
                        break;
                    case 'Volcanic':
                        r = 30 + n * 30; g = 15 + n * 15; b = 10 + n * 10;
                        if (n > 0.55 && n < 0.62) {
                            r = 200 + n * 55; g = 80 + n * 40; b = 10;
                        }
                        break;
                    case 'Desert':
                        r = 180 + n * 50; g = 150 + n * 40; b = 80 + n * 30;
                        if (n > 0.5 && n < 0.6) {
                            r *= 0.75; g *= 0.7; b *= 0.6;
                        }
                        break;
                    case 'Crystal':
                        r = 180 + n * 50; g = 200 + n * 40; b = 220 + n * 35;
                        if (n > 0.55) {
                            r = 50 + n * 60; g = 200 + n * 55; b = 220 + n * 35;
                        }
                        break;
                    case 'Abyss':
                        r = 15 + n * 20; g = 5 + n * 10; b = 25 + n * 30;
                        if (n > 0.58 && n < 0.65) {
                            r = 80 + n * 40; g = 20 + n * 20; b = 120 + n * 60;
                        }
                        break;
                    default:
                        r = ((color >> 16) & 255) * n;
                        g = ((color >> 8) & 255) * n;
                        b = (color & 255) * n;
                }
                d[idx] = Math.min(255, r);
                d[idx + 1] = Math.min(255, g);
                d[idx + 2] = Math.min(255, b);
                d[idx + 3] = 255;
            }
        }
        ctx.putImageData(imgData, 0, 0);
        return new THREE.CanvasTexture(canvas);
    },

    createPlanets() {
        this.planetMeshes = [];
        WORLD_IDS.forEach((id, idx) => {
            const w = WORLDS[id];
            const group = new THREE.Group();

            // Planet sphere with procedural texture
            const geo = new THREE.SphereGeometry(3 + idx * 0.5, 24, 24);
            const planetTexture = this.generatePlanetTexture(w.biome, w.planetColor);
            const mat = new THREE.MeshStandardMaterial({
                map: planetTexture,
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

            // Planet rings
            const planetRadius = 3 + idx * 0.5;
            if (id === 'hub') {
                // Saturn-like ring
                const ringGeo = new THREE.RingGeometry(planetRadius + 1.5, planetRadius + 4.5, 64);
                const ringMat = new THREE.MeshBasicMaterial({
                    color: w.planetColor, transparent: true, opacity: 0.3,
                    side: THREE.DoubleSide
                });
                const ring = new THREE.Mesh(ringGeo, ringMat);
                ring.rotation.x = -Math.PI / 2 + 0.35;
                group.add(ring);
            } else if (id === 'gallery') {
                // Thin ice ring
                const ringGeo = new THREE.RingGeometry(planetRadius + 1, planetRadius + 2, 64);
                const ringMat = new THREE.MeshBasicMaterial({
                    color: w.planetColor, transparent: true, opacity: 0.2,
                    side: THREE.DoubleSide
                });
                const ring = new THREE.Mesh(ringGeo, ringMat);
                ring.rotation.x = -Math.PI / 2 + 0.35;
                group.add(ring);
            }

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
                // Click planet → warp tunnel → approach (like LEVIATHAN)
                const wid = obj.userData.worldId;
                if (typeof Audio !== 'undefined') Audio.playClick();
                Warp.start(() => Approach.start(wid));
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
