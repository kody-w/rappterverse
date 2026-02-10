// World Terrain — Ground, Biome Objects, Particles, Lighting
const WorldTerrain = {
    particles: null,

    weatherType: null,
    weatherParticles: null,

    build(scene, w, worldId) {
        this.buildGround(scene, w);
        this.buildLighting(scene, w);
        this.particles = this.spawnParticles(scene, w);
        this.spawnBiomeObjects(scene, w, worldId);
        this.initWeather(scene, w, worldId);
    },

    buildGround(scene, w) {
        // Terrain plane with displacement
        const size = Math.max(w.bounds.x, w.bounds.z) * 2 + 40;
        const geo = new THREE.PlaneGeometry(size, size, 128, 128);
        const positions = geo.attributes.position.array;
        const rng = seededRandom(w.name + '-ground');
        for (let i = 0; i < positions.length; i += 3) {
            const x = positions[i], z = positions[i + 1];
            const dist = Math.sqrt(x * x + z * z);
            const edge = Math.min(dist / (size * 0.3), 1);
            positions[i + 2] = rng() * 4 * edge;
        }
        geo.computeVertexNormals();

        const mat = new THREE.MeshStandardMaterial({
            color: w.floor, roughness: 0.9, metalness: 0.1,
            transparent: true, opacity: 0.85, flatShading: true
        });
        const ground = new THREE.Mesh(geo, mat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.05;
        scene.add(ground);

        // Grid
        const gridSize = Math.max(w.bounds.x, w.bounds.z) * 2 + 2;
        const divisions = Math.min(gridSize, 200);
        const grid = new THREE.GridHelper(gridSize, divisions, w.grid, new THREE.Color(w.grid).multiplyScalar(0.3));
        grid.material.opacity = 0.15;
        grid.material.transparent = true;
        scene.add(grid);

        // Boundary wireframe
        const bGeo = new THREE.BoxGeometry(w.bounds.x * 2, 4, w.bounds.z * 2);
        const bMat = new THREE.MeshBasicMaterial({ color: w.accent, wireframe: true, transparent: true, opacity: 0.06 });
        const boundary = new THREE.Mesh(bGeo, bMat);
        boundary.position.y = 2;
        scene.add(boundary);
    },

    buildLighting(scene, w) {
        const ambient = new THREE.AmbientLight(0x404060, 0.6);
        scene.add(ambient);

        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(50, 80, 50);
        scene.add(dirLight);

        const pointLight = new THREE.PointLight(w.accent, 1.5, 300);
        pointLight.position.set(0, 30, 0);
        scene.add(pointLight);

        // Day/night from game state
        const worldState = GameState.data.gameState?.worlds?.[GameState.currentWorld];
        if (worldState?.time_of_day === 'night') {
            ambient.intensity = 0.2;
            dirLight.intensity = 0.3;
            dirLight.color.set(0x6666aa);
        }
    },

    spawnParticles(scene, w) {
        const count = 800;
        const geo = new THREE.BufferGeometry();
        const pos = new Float32Array(count * 3);
        const rng = seededRandom(w.name + '-particles');
        for (let i = 0; i < count; i++) {
            pos[i * 3] = (rng() - 0.5) * w.bounds.x * 4;
            pos[i * 3 + 1] = rng() * 40 + 1;
            pos[i * 3 + 2] = (rng() - 0.5) * w.bounds.z * 4;
        }
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const mat = new THREE.PointsMaterial({
            color: w.accent, size: 0.12,
            transparent: true, opacity: 0.35,
            blending: THREE.AdditiveBlending, sizeAttenuation: true
        });
        const particles = new THREE.Points(geo, mat);
        scene.add(particles);
        return particles;
    },

    spawnBiomeObjects(scene, w, worldId) {
        const rng = seededRandom(worldId + '-biome');
        const count = 200;
        const laneExclusion = 8; // Don't place objects on lanes

        for (let i = 0; i < count; i++) {
            const x = (rng() - 0.5) * w.bounds.x * 2;
            const z = (rng() - 0.5) * w.bounds.z * 2;

            // Skip if too close to any lane path
            if (typeof WorldLanes !== 'undefined' && WorldLanes.isNearLane(x, z, laneExclusion)) continue;

            let obj;
            if (w.biome === 'Terra' || w.biome === 'Crystal') {
                if (rng() > 0.4) {
                    // Trees
                    obj = new THREE.Group();
                    const trunkGeo = new THREE.CylinderGeometry(0.3, 0.5, 2 + rng() * 3, 6);
                    const trunkMat = new THREE.MeshStandardMaterial({ color: 0x664422, roughness: 0.9 });
                    const trunk = new THREE.Mesh(trunkGeo, trunkMat);
                    trunk.position.y = 1 + rng();
                    obj.add(trunk);
                    const canopySize = 1.5 + rng() * 2;
                    const canopyGeo = new THREE.SphereGeometry(canopySize, 6, 5);
                    const canopyMat = new THREE.MeshStandardMaterial({
                        color: w.biome === 'Crystal' ? 0x44ddcc : 0x228833,
                        roughness: 0.8, flatShading: true
                    });
                    const canopy = new THREE.Mesh(canopyGeo, canopyMat);
                    canopy.position.y = 2.5 + rng() * 2;
                    obj.add(canopy);
                } else {
                    const size = 0.5 + rng() * 1.5;
                    const rockGeo = new THREE.DodecahedronGeometry(size, 0);
                    const rockMat = new THREE.MeshStandardMaterial({ color: 0x777777, roughness: 0.95, flatShading: true });
                    obj = new THREE.Mesh(rockGeo, rockMat);
                    obj.position.y = size * 0.3;
                }
            } else if (w.biome === 'Volcanic') {
                // Lava rocks and spires
                const size = 0.8 + rng() * 2;
                const geo = rng() > 0.5
                    ? new THREE.ConeGeometry(size * 0.5, size * 2, 5)
                    : new THREE.DodecahedronGeometry(size, 0);
                const mat = new THREE.MeshStandardMaterial({
                    color: 0x332211, emissive: 0xff4400,
                    emissiveIntensity: rng() * 0.3, roughness: 0.95, flatShading: true
                });
                obj = new THREE.Mesh(geo, mat);
                obj.position.y = size * 0.4;
            } else {
                // Desert — sand dunes / cacti
                const size = 0.6 + rng() * 1.5;
                const geo = new THREE.CylinderGeometry(size * 0.3, size * 0.5, size * 2, 6);
                const mat = new THREE.MeshStandardMaterial({ color: 0xaaaa66, roughness: 0.95, flatShading: true });
                obj = new THREE.Mesh(geo, mat);
                obj.position.y = size;
            }

            obj.position.x = x;
            obj.position.z = z;
            obj.rotation.y = rng() * Math.PI * 2;
            scene.add(obj);
        }
    },

    update(time, delta) {
        if (this.particles) this.particles.rotation.y = time * 0.015;
        if (delta) this.updateWeather(delta);

        // Update weather label
        const weatherEl = document.getElementById('weather-label');
        if (weatherEl && this.weatherType) weatherEl.textContent = this.weatherType.toUpperCase();
    },

    initWeather(scene, w, worldId) {
        const rng = seededRandom(worldId + '-weather');
        const roll = rng();
        let type = 'clear';

        if (w.biome === 'Terra') {
            if (roll < 0.4) type = 'clear';
            else if (roll < 0.7) type = 'rain';
            else if (roll < 0.9) type = 'fog';
            else type = 'storm';
        } else if (w.biome === 'Volcanic') {
            if (roll < 0.5) type = 'ash';
            else if (roll < 0.8) type = 'clear';
            else type = 'ember';
        } else if (w.biome === 'Desert') {
            if (roll < 0.4) type = 'clear';
            else if (roll < 0.8) type = 'sandstorm';
            else type = 'heat shimmer';
        } else if (w.biome === 'Crystal') {
            if (roll < 0.5) type = 'clear';
            else if (roll < 0.8) type = 'snow';
            else type = 'aurora';
        } else if (w.biome === 'Abyss') {
            if (roll < 0.4) type = 'fog';
            else if (roll < 0.7) type = 'clear';
            else type = 'void particles';
        }

        this.weatherType = type;
        if (type !== 'clear') {
            this.weatherParticles = this.createWeatherParticles(scene, w, type);
        }
    },

    createWeatherParticles(scene, w, type) {
        const configs = {
            rain:           { count: 1000, color: 0xaaccff, size: 0.15, opacity: 0.5 },
            storm:          { count: 1000, color: 0x8899cc, size: 0.2,  opacity: 0.6 },
            snow:           { count: 800,  color: 0xffffff, size: 0.25, opacity: 0.6 },
            sandstorm:      { count: 900,  color: 0xccaa66, size: 0.3,  opacity: 0.45 },
            ash:            { count: 600,  color: 0x555555, size: 0.2,  opacity: 0.4 },
            ember:          { count: 500,  color: 0xff6600, size: 0.18, opacity: 0.5 },
            fog:            { count: 500,  color: 0xffffff, size: 2.0,  opacity: 0.15 },
            'heat shimmer': { count: 600,  color: 0xffddaa, size: 0.3,  opacity: 0.2 },
            aurora:         { count: 700,  color: 0x44ffaa, size: 0.4,  opacity: 0.35 },
            'void particles': { count: 600, color: 0x6600aa, size: 0.25, opacity: 0.4 }
        };
        const cfg = configs[type] || configs.rain;
        const count = cfg.count;
        const geo = new THREE.BufferGeometry();
        const pos = new Float32Array(count * 3);
        const rng = seededRandom(type + '-weather-particles');
        const bx = w.bounds.x, bz = w.bounds.z;
        const maxY = (type === 'fog') ? 5 : (type === 'sandstorm' || type === 'heat shimmer') ? 8 : 30;

        for (let i = 0; i < count; i++) {
            pos[i * 3]     = (rng() - 0.5) * bx * 2;
            pos[i * 3 + 1] = rng() * maxY;
            pos[i * 3 + 2] = (rng() - 0.5) * bz * 2;
        }
        geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));

        const mat = new THREE.PointsMaterial({
            color: cfg.color, size: cfg.size,
            transparent: true, opacity: cfg.opacity,
            blending: THREE.AdditiveBlending, sizeAttenuation: true,
            depthWrite: false
        });
        const points = new THREE.Points(geo, mat);
        points.userData.weatherType = type;
        points.userData.bounds = { x: bx, z: bz, maxY };
        scene.add(points);
        return points;
    },

    updateWeather(delta) {
        if (!this.weatherParticles) return;
        const pts = this.weatherParticles;
        const pos = pts.geometry.attributes.position.array;
        const count = pos.length / 3;
        const type = pts.userData.weatherType;
        const b = pts.userData.bounds;
        const t = performance.now() * 0.001;

        for (let i = 0; i < count; i++) {
            const ix = i * 3, iy = i * 3 + 1, iz = i * 3 + 2;
            if (type === 'rain' || type === 'storm') {
                const speed = type === 'storm' ? 25 : 18;
                pos[iy] -= speed * delta;
                if (type === 'storm') pos[ix] += 3 * delta;
                if (pos[iy] < 0) { pos[iy] = b.maxY; pos[ix] = (Math.random() - 0.5) * b.x * 2; }
            } else if (type === 'snow') {
                pos[iy] -= 3 * delta;
                pos[ix] += Math.sin(t + i * 0.1) * 0.5 * delta;
                if (pos[iy] < 0) { pos[iy] = b.maxY; pos[ix] = (Math.random() - 0.5) * b.x * 2; }
            } else if (type === 'sandstorm' || type === 'heat shimmer') {
                pos[ix] += 8 * delta;
                pos[iy] += Math.sin(t + i) * 0.3 * delta;
                if (pos[ix] > b.x) pos[ix] = -b.x;
            } else if (type === 'ash') {
                pos[iy] += 1.5 * delta;
                pos[ix] += Math.sin(t * 0.5 + i) * 0.2 * delta;
                if (pos[iy] > b.maxY) pos[iy] = 0;
            } else if (type === 'ember') {
                pos[iy] += 2.5 * delta;
                pos[ix] += Math.sin(t + i * 0.3) * 0.4 * delta;
                if (pos[iy] > b.maxY) { pos[iy] = 0; pos[ix] = (Math.random() - 0.5) * b.x * 2; }
            } else if (type === 'fog') {
                pos[ix] += Math.sin(t * 0.3 + i * 0.7) * 0.3 * delta;
                pos[iz] += Math.cos(t * 0.2 + i * 0.5) * 0.3 * delta;
            } else if (type === 'aurora') {
                pos[ix] += Math.sin(t * 0.4 + i * 0.2) * 0.6 * delta;
                pos[iy] += Math.cos(t * 0.3 + i * 0.1) * 0.2 * delta;
            } else if (type === 'void particles') {
                pos[ix] += Math.sin(t + i) * 1.5 * delta;
                pos[iy] += Math.cos(t * 0.7 + i * 0.4) * 1.0 * delta;
                pos[iz] += Math.sin(t * 0.5 + i * 0.9) * 1.5 * delta;
                if (pos[iy] < 0) pos[iy] = b.maxY;
                if (pos[iy] > b.maxY) pos[iy] = 0;
            }
            // Wrap horizontal bounds
            if (pos[ix] > b.x) pos[ix] = -b.x;
            if (pos[ix] < -b.x) pos[ix] = b.x;
            if (pos[iz] > b.z) pos[iz] = -b.z;
            if (pos[iz] < -b.z) pos[iz] = b.z;
        }
        pts.geometry.attributes.position.needsUpdate = true;
    }
};
