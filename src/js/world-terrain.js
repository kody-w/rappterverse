// World Terrain — Seed-Driven Procedural Ground, Biome Objects, Particles, Lighting
const WorldTerrain = {
    particles: null,
    weatherType: null,
    weatherParticles: null,
    _noise: null,
    _biome: null,
    _terrainSize: 0,
    _profile: null,

    build(scene, w, worldId) {
        const seed = WorldSeed.getSeed(worldId);
        this._noise = createNoise2D(seed);
        this._biome = w.biome;
        this._terrainSize = Math.max(w.bounds.x, w.bounds.z) * 2 + 40;
        this._profile = BIOME_PROFILES[w.biome];

        this.buildGround(scene, w, worldId);
        this.buildLighting(scene, w, worldId);
        this.particles = this.spawnParticles(scene, w);
        this.spawnBiomeObjects(scene, w, worldId);
        this.spawnBiomeFeatures(scene, w, worldId);
        this.initWeather(scene, w, worldId);
    },

    // ── Height sampling for player terrain following ──
    getHeight(wx, wz) {
        if (!this._noise || !this._profile) return 0;
        const p = this._profile, s = this._terrainSize;
        const nx = wx / s * p.noiseScale, nz = wz / s * p.noiseScale;
        let h = this._rawHeight(nx, nz);
        const d = Math.sqrt(wx * wx + wz * wz);
        h *= Math.min(1, Math.max(0, (d - 12) / 20));
        h *= Math.max(0, 1 - Math.max(Math.abs(wx), Math.abs(wz)) / (s * 0.48));
        return h;
    },

    _rawHeight(nx, nz) {
        const n = this._noise, p = this._profile, b = this._biome;
        const base = n.fbm(nx, nz, p.octaves, p.lacunarity, p.gain);
        if (b === 'Volcanic') return Math.abs(base) * p.heightScale;
        if (b === 'Abyss') return (base - n.ridged(nx * 0.5, nz * 0.5, 3) * 0.5) * p.heightScale;
        if (b === 'Desert') return (base * 0.5 + 0.5) * p.heightScale;
        if (b === 'Crystal') return (base + n.ridged(nx * 1.5, nz * 1.5, 3) * 0.3) * p.heightScale;
        return base * p.heightScale;
    },

    // ── Ground mesh with vertex-colored height map ──
    buildGround(scene, w, worldId) {
        const size = this._terrainSize;
        const seg = 160;
        const geo = new THREE.PlaneGeometry(size, size, seg, seg);
        const pos = geo.attributes.position.array;
        const vc = pos.length / 3;
        const colors = new Float32Array(vc * 3);
        const p = this._profile;

        let maxH = 0.01;
        for (let i = 0; i < vc; i++) {
            const x = pos[i * 3], y = pos[i * 3 + 1];
            const nx = x / size * p.noiseScale, ny = y / size * p.noiseScale;
            let h = this._rawHeight(nx, ny);
            const dist = Math.sqrt(x * x + y * y);
            h *= Math.min(1, Math.max(0, (dist - 12) / 20));
            h *= Math.max(0, 1 - Math.max(Math.abs(x), Math.abs(y)) / (size * 0.48));
            pos[i * 3 + 2] = h;
            if (Math.abs(h) > maxH) maxH = Math.abs(h);
        }

        for (let i = 0; i < vc; i++) {
            const h = pos[i * 3 + 2];
            const t = (h / maxH + 1) * 0.5;
            const c = p.color(t, h);
            colors[i * 3] = c[0]; colors[i * 3 + 1] = c[1]; colors[i * 3 + 2] = c[2];
        }

        geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        geo.computeVertexNormals();

        const mat = new THREE.MeshStandardMaterial({
            vertexColors: true, roughness: 0.92, metalness: 0.08, flatShading: true
        });
        const ground = new THREE.Mesh(geo, mat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.y = -0.05;
        scene.add(ground);

        // Subtle grid
        const gridSize = Math.max(w.bounds.x, w.bounds.z) * 2 + 2;
        const divisions = Math.min(gridSize, 200);
        const grid = new THREE.GridHelper(gridSize, divisions, w.grid, new THREE.Color(w.grid).multiplyScalar(0.3));
        grid.material.opacity = 0.08;
        grid.material.transparent = true;
        scene.add(grid);

        // Boundary wireframe
        const bGeo = new THREE.BoxGeometry(w.bounds.x * 2, 4, w.bounds.z * 2);
        const bMat = new THREE.MeshBasicMaterial({ color: w.accent, wireframe: true, transparent: true, opacity: 0.06 });
        const boundary = new THREE.Mesh(bGeo, bMat);
        boundary.position.y = 2;
        scene.add(boundary);
    },

    // ── Lighting (biome-tuned) ──
    buildLighting(scene, w, worldId) {
        const ambient = new THREE.AmbientLight(0x404060, 0.6);
        scene.add(ambient);
        const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight.position.set(50, 80, 50);
        scene.add(dirLight);
        const pointLight = new THREE.PointLight(w.accent, 1.5, 300);
        pointLight.position.set(0, 30, 0);
        scene.add(pointLight);

        if (w.biome === 'Volcanic') {
            const lava = new THREE.PointLight(0xff4400, 1.0, 200);
            lava.position.set(0, 2, 0);
            scene.add(lava);
            dirLight.color.set(0xffaa88);
        } else if (w.biome === 'Abyss') {
            ambient.intensity = 0.3;
            dirLight.intensity = 0.4;
            dirLight.color.set(0x6644aa);
        } else if (w.biome === 'Crystal') {
            const glow = new THREE.PointLight(0x00ffaa, 0.8, 250);
            glow.position.set(0, 15, 0);
            scene.add(glow);
        } else if (w.biome === 'Desert') {
            dirLight.color.set(0xffeedd);
            dirLight.intensity = 1.0;
            ambient.color.set(0x605040);
        }

        const worldState = GameState.data.gameState?.worlds?.[GameState.currentWorld];
        if (worldState?.time_of_day === 'night') {
            ambient.intensity *= 0.4;
            dirLight.intensity *= 0.4;
            dirLight.color.set(0x6666aa);
        }
    },

    // ── Ambient particles ──
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
        const pts = new THREE.Points(geo, mat);
        scene.add(pts);
        return pts;
    },

    // ──────────────────────────────────────────────────────
    //  BIOME OBJECTS — unique per biome, seed-driven
    // ──────────────────────────────────────────────────────
    spawnBiomeObjects(scene, w, worldId) {
        const seed = WorldSeed.getSeed(worldId);
        const rng = seededRandom(seed + '-objects');
        const count = 250;
        const laneExclusion = 14; // Keep biome objects off lanes

        for (let i = 0; i < count; i++) {
            const x = (rng() - 0.5) * w.bounds.x * 2;
            const z = (rng() - 0.5) * w.bounds.z * 2;
            if (typeof WorldLanes !== 'undefined' && WorldLanes.isNearLane && WorldLanes.isNearLane(x, z, laneExclusion)) continue;
            if (Math.sqrt(x * x + z * z) < 10) continue;

            const y = this.getHeight(x, z);
            let obj;
            if (w.biome === 'Terra') obj = this._terraObj(rng);
            else if (w.biome === 'Volcanic') obj = this._volcanicObj(rng);
            else if (w.biome === 'Desert') obj = this._desertObj(rng);
            else if (w.biome === 'Crystal') obj = this._crystalObj(rng);
            else if (w.biome === 'Abyss') obj = this._abyssObj(rng);
            if (!obj) continue;

            obj.position.x = x;
            obj.position.y = y;
            obj.position.z = z;
            obj.rotation.y = rng() * Math.PI * 2;
            scene.add(obj);
        }
    },

    // ── Terra: trees, rocks, bushes, flowers, grass ──
    _terraObj(rng) {
        const roll = rng();
        if (roll < 0.35) {
            const g = new THREE.Group();
            const trunkH = 2 + rng() * 4;
            const trunk = new THREE.Mesh(
                new THREE.CylinderGeometry(0.15 + rng() * 0.15, 0.2 + rng() * 0.2, trunkH, 6),
                new THREE.MeshStandardMaterial({ color: 0x5a3a1a, roughness: 0.95 })
            );
            trunk.position.y = trunkH / 2;
            g.add(trunk);
            const canopyR = 1.2 + rng() * 2.5;
            const ct = rng();
            const geo = ct < 0.4 ? new THREE.SphereGeometry(canopyR, 7, 5)
                      : ct < 0.7 ? new THREE.ConeGeometry(canopyR, canopyR * 2, 6)
                      : new THREE.DodecahedronGeometry(canopyR, 0);
            const greens = [0x1a6630, 0x228833, 0x2a7744, 0x1a5528, 0x338844];
            const canopy = new THREE.Mesh(geo,
                new THREE.MeshStandardMaterial({ color: greens[(rng() * greens.length) | 0], roughness: 0.85, flatShading: true })
            );
            canopy.position.y = trunkH + canopyR * 0.3;
            g.add(canopy);
            return g;
        }
        if (roll < 0.52) {
            const s = 0.4 + rng() * 1.8;
            const grays = [0x667766, 0x778877, 0x556655, 0x889988];
            const rock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({ color: grays[(rng() * 4) | 0], roughness: 0.95, flatShading: true })
            );
            rock.position.y = s * 0.3;
            return rock;
        }
        if (roll < 0.68) {
            const s = 0.6 + rng() * 1.2;
            const bush = new THREE.Mesh(
                new THREE.SphereGeometry(s, 5, 4),
                new THREE.MeshStandardMaterial({ color: [0x2a6633, 0x338844, 0x227733][(rng() * 3) | 0], roughness: 0.9, flatShading: true })
            );
            bush.position.y = s * 0.4; bush.scale.y = 0.6;
            return bush;
        }
        if (roll < 0.84) {
            const g = new THREE.Group();
            const n = 2 + (rng() * 4) | 0;
            const fc = [0xff4488, 0xffcc00, 0xff8844, 0xaa44ff, 0xff6666, 0x44aaff];
            for (let j = 0; j < n; j++) {
                const sh = 0.3 + rng() * 0.5;
                const stem = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.02, 0.02, sh, 3),
                    new THREE.MeshStandardMaterial({ color: 0x336622 })
                );
                stem.position.set((rng() - 0.5) * 0.8, sh / 2, (rng() - 0.5) * 0.8);
                g.add(stem);
                const petal = new THREE.Mesh(
                    new THREE.SphereGeometry(0.08 + rng() * 0.1, 4, 3),
                    new THREE.MeshStandardMaterial({ color: fc[(rng() * fc.length) | 0], emissive: 0x220000, emissiveIntensity: 0.1 })
                );
                petal.position.copy(stem.position); petal.position.y += sh / 2 + 0.05;
                g.add(petal);
            }
            return g;
        }
        // Grass tuft
        const g = new THREE.Group();
        const n = 3 + (rng() * 5) | 0;
        for (let j = 0; j < n; j++) {
            const blade = new THREE.Mesh(
                new THREE.ConeGeometry(0.03, 0.3 + rng() * 0.4, 3),
                new THREE.MeshStandardMaterial({ color: 0x44aa44, flatShading: true })
            );
            blade.position.set((rng() - 0.5) * 0.4, 0.15, (rng() - 0.5) * 0.4);
            blade.rotation.z = (rng() - 0.5) * 0.3;
            g.add(blade);
        }
        return g;
    },

    // ── Volcanic: obsidian spires, basalt columns, lava rocks, ember pools ──
    _volcanicObj(rng) {
        const roll = rng();
        if (roll < 0.28) {
            const h = 2 + rng() * 6;
            const spire = new THREE.Mesh(
                new THREE.ConeGeometry(0.3 + rng() * 0.8, h, 5),
                new THREE.MeshStandardMaterial({
                    color: 0x111118, emissive: 0xff4400,
                    emissiveIntensity: rng() * 0.25, roughness: 0.3, metalness: 0.7, flatShading: true
                })
            );
            spire.position.y = h / 2;
            return spire;
        }
        if (roll < 0.48) {
            const h = 1 + rng() * 3;
            const col = new THREE.Mesh(
                new THREE.CylinderGeometry(0.4 + rng() * 0.4, 0.5 + rng() * 0.4, h, 6),
                new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.95, flatShading: true })
            );
            col.position.y = h / 2;
            return col;
        }
        if (roll < 0.68) {
            const s = 0.5 + rng() * 1.5;
            const rock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({
                    color: 0x221100, emissive: 0xff3300,
                    emissiveIntensity: rng() * 0.2, roughness: 0.9, flatShading: true
                })
            );
            rock.position.y = s * 0.4;
            return rock;
        }
        if (roll < 0.84) {
            const r = 1 + rng() * 2;
            const pool = new THREE.Mesh(
                new THREE.CircleGeometry(r, 8),
                new THREE.MeshBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.5 + rng() * 0.3, side: THREE.DoubleSide })
            );
            pool.rotation.x = -Math.PI / 2;
            pool.position.y = 0.02;
            return pool;
        }
        // Smoke vent
        const vent = new THREE.Mesh(
            new THREE.CylinderGeometry(0.3, 0.6, 0.8, 6),
            new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.95, flatShading: true })
        );
        vent.position.y = 0.4;
        return vent;
    },

    // ── Desert: cacti, sandstone, dead trees, tumbleweeds, rocks ──
    _desertObj(rng) {
        const roll = rng();
        if (roll < 0.25) {
            const g = new THREE.Group();
            const h = 1.5 + rng() * 3;
            const trunk = new THREE.Mesh(
                new THREE.CylinderGeometry(0.18, 0.22, h, 6),
                new THREE.MeshStandardMaterial({ color: 0x3a7733, roughness: 0.9 })
            );
            trunk.position.y = h / 2;
            g.add(trunk);
            if (rng() > 0.4) {
                const aH = 0.8 + rng() * 1.2;
                const arm = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.1, 0.13, aH, 5),
                    new THREE.MeshStandardMaterial({ color: 0x3a7733, roughness: 0.9 })
                );
                arm.position.set(0.28, h * 0.45, 0); arm.rotation.z = -0.8 - rng() * 0.5;
                g.add(arm);
            }
            if (rng() > 0.5) {
                const aH = 0.6 + rng();
                const arm = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.08, 0.11, aH, 5),
                    new THREE.MeshStandardMaterial({ color: 0x3a7733, roughness: 0.9 })
                );
                arm.position.set(-0.22, h * 0.35, 0); arm.rotation.z = 0.7 + rng() * 0.5;
                g.add(arm);
            }
            return g;
        }
        if (roll < 0.45) {
            const g = new THREE.Group();
            const layers = 2 + (rng() * 3) | 0;
            let y = 0;
            const cols = [0xbb8844, 0xcc9955, 0xaa7733];
            for (let j = 0; j < layers; j++) {
                const bw = 0.8 + rng() * 2 - j * 0.2;
                const bh = 0.5 + rng();
                const block = new THREE.Mesh(
                    new THREE.BoxGeometry(bw, bh, bw * (0.6 + rng() * 0.6)),
                    new THREE.MeshStandardMaterial({ color: cols[(rng() * 3) | 0], roughness: 0.95, flatShading: true })
                );
                block.position.y = y + bh / 2; block.rotation.y = rng() * 0.3;
                g.add(block); y += bh;
            }
            return g;
        }
        if (roll < 0.6) {
            const g = new THREE.Group();
            const h = 1.5 + rng() * 3;
            const trunk = new THREE.Mesh(
                new THREE.CylinderGeometry(0.08, 0.18, h, 5),
                new THREE.MeshStandardMaterial({ color: 0x998877, roughness: 0.95 })
            );
            trunk.position.y = h / 2; g.add(trunk);
            for (let j = 0; j < 2 + (rng() * 3 | 0); j++) {
                const bLen = 0.5 + rng();
                const branch = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.03, 0.06, bLen, 3),
                    new THREE.MeshStandardMaterial({ color: 0x887766, roughness: 0.95 })
                );
                branch.position.y = h * (0.4 + rng() * 0.5);
                branch.rotation.z = (rng() - 0.5) * 1.5; branch.rotation.x = (rng() - 0.5) * 0.5;
                g.add(branch);
            }
            return g;
        }
        if (roll < 0.78) {
            const s = 0.3 + rng() * 0.6;
            const tw = new THREE.Mesh(
                new THREE.IcosahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({ color: 0x887744, roughness: 0.95, flatShading: true, transparent: true, opacity: 0.8 })
            );
            tw.position.y = s;
            return tw;
        }
        // Desert rock
        const s = 0.5 + rng() * 1.5;
        const rock = new THREE.Mesh(
            new THREE.DodecahedronGeometry(s, 0),
            new THREE.MeshStandardMaterial({ color: [0xaa8855, 0xbb9966, 0x997744][(rng() * 3) | 0], roughness: 0.95, flatShading: true })
        );
        rock.position.y = s * 0.3;
        return rock;
    },

    // ── Crystal: pillars, clusters, ice blocks, snow rocks, glowing orbs ──
    _crystalObj(rng) {
        const roll = rng();
        if (roll < 0.28) {
            const h = 2 + rng() * 5;
            const r = 0.3 + rng() * 0.6;
            const cols = [0x44ddff, 0xff44dd, 0xaaffcc, 0x88ccff, 0xddaaff];
            const pillar = new THREE.Mesh(
                new THREE.CylinderGeometry(r * 0.3, r, h, 6),
                new THREE.MeshStandardMaterial({
                    color: cols[(rng() * cols.length) | 0], emissive: 0x224466, emissiveIntensity: 0.2,
                    roughness: 0.2, metalness: 0.6, flatShading: true, transparent: true, opacity: 0.85
                })
            );
            pillar.position.y = h / 2;
            return pillar;
        }
        if (roll < 0.48) {
            const g = new THREE.Group();
            const n = 3 + (rng() * 4) | 0;
            const cols = [0x44eeff, 0xcc44ff, 0x88ffaa, 0xff88cc];
            for (let j = 0; j < n; j++) {
                const sh = 0.5 + rng() * 2;
                const sr = 0.15 + rng() * 0.3;
                const shard = new THREE.Mesh(
                    new THREE.OctahedronGeometry(sr, 0),
                    new THREE.MeshStandardMaterial({
                        color: cols[(rng() * cols.length) | 0], emissive: 0x113355, emissiveIntensity: 0.15,
                        roughness: 0.15, metalness: 0.7, flatShading: true, transparent: true, opacity: 0.8
                    })
                );
                shard.scale.y = sh / sr;
                shard.position.set((rng() - 0.5), sh * 0.4, (rng() - 0.5));
                shard.rotation.set(rng() * 0.3, rng() * Math.PI, rng() * 0.3);
                g.add(shard);
            }
            return g;
        }
        if (roll < 0.63) {
            const s = 0.5 + rng() * 1.5;
            const block = new THREE.Mesh(
                new THREE.BoxGeometry(s, s * (0.5 + rng()), s * (0.5 + rng())),
                new THREE.MeshStandardMaterial({ color: 0x88ccff, roughness: 0.1, metalness: 0.3, transparent: true, opacity: 0.5 + rng() * 0.3 })
            );
            block.position.y = s * 0.3; block.rotation.y = rng() * Math.PI;
            return block;
        }
        if (roll < 0.8) {
            const s = 0.4 + rng() * 1.3;
            const rock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({ color: 0xccddee, roughness: 0.85, flatShading: true })
            );
            rock.position.y = s * 0.3;
            return rock;
        }
        // Glowing orb
        const s = 0.2 + rng() * 0.5;
        const cols = [0x00ffaa, 0xff00ff, 0x44aaff, 0xffaa00];
        const orb = new THREE.Mesh(
            new THREE.SphereGeometry(s, 8, 6),
            new THREE.MeshStandardMaterial({
                color: cols[(rng() * cols.length) | 0],
                emissive: cols[(rng() * cols.length) | 0], emissiveIntensity: 0.5, roughness: 0.1
            })
        );
        orb.position.y = 0.5 + rng() * 2;
        return orb;
    },

    // ── Abyss: void pillars, shadow stones, monoliths, wisps, broken pillars ──
    _abyssObj(rng) {
        const roll = rng();
        if (roll < 0.25) {
            const h = 3 + rng() * 6;
            const r = 0.3 + rng() * 0.5;
            const pillar = new THREE.Mesh(
                new THREE.CylinderGeometry(r * 0.5, r, h, 5),
                new THREE.MeshStandardMaterial({
                    color: 0x110022, emissive: 0x6600aa,
                    emissiveIntensity: 0.2 + rng() * 0.3, roughness: 0.5, metalness: 0.5, flatShading: true
                })
            );
            pillar.position.y = h / 2;
            return pillar;
        }
        if (roll < 0.45) {
            const s = 0.5 + rng() * 1.5;
            const stone = new THREE.Mesh(
                new THREE.BoxGeometry(s, s * (1 + rng()), s * (0.5 + rng() * 0.5)),
                new THREE.MeshStandardMaterial({
                    color: 0x0d0d15, roughness: 0.95, flatShading: true, emissive: 0x220044, emissiveIntensity: 0.05
                })
            );
            stone.position.y = s * 0.5; stone.rotation.y = rng() * Math.PI;
            return stone;
        }
        if (roll < 0.6) {
            const h = 2 + rng() * 4;
            const slab = new THREE.Mesh(
                new THREE.BoxGeometry(0.6 + rng() * 0.4, h, 0.15),
                new THREE.MeshStandardMaterial({
                    color: 0x1a1a22, emissive: 0x3300aa,
                    emissiveIntensity: 0.3, roughness: 0.7, flatShading: true
                })
            );
            slab.position.y = h / 2;
            return slab;
        }
        if (roll < 0.8) {
            const s = 0.1 + rng() * 0.3;
            const cols = [0x9900ff, 0x00ff99, 0xff0066, 0x00ccff];
            const wisp = new THREE.Mesh(
                new THREE.SphereGeometry(s, 6, 5),
                new THREE.MeshBasicMaterial({
                    color: cols[(rng() * cols.length) | 0], transparent: true, opacity: 0.6 + rng() * 0.3
                })
            );
            wisp.position.y = 1 + rng() * 4;
            return wisp;
        }
        // Broken pillar
        const h = 0.8 + rng() * 2;
        const pillar = new THREE.Mesh(
            new THREE.CylinderGeometry(0.4 + rng() * 0.3, 0.5 + rng() * 0.3, h, 5),
            new THREE.MeshStandardMaterial({ color: 0x15151f, roughness: 0.9, flatShading: true })
        );
        pillar.position.y = h / 2;
        return pillar;
    },

    // ──────────────────────────────────────────────────────
    //  BIOME FEATURES — large-scale unique landmarks
    // ──────────────────────────────────────────────────────
    spawnBiomeFeatures(scene, w, worldId) {
        const seed = WorldSeed.getSeed(worldId);
        const rng = seededRandom(seed + '-features');
        const n = this._noise;

        if (w.biome === 'Volcanic') {
            // Lava rivers following noise valleys
            for (let i = 0; i < 6; i++) {
                const pts = [];
                let px = (rng() - 0.5) * w.bounds.x * 1.4;
                let pz = (rng() - 0.5) * w.bounds.z * 1.4;
                for (let j = 0; j < 15; j++) {
                    pts.push(new THREE.Vector3(px, 0.08, pz));
                    px += (n.noise(px * 0.02, pz * 0.02)) * 6;
                    pz += (n.noise(px * 0.02 + 50, pz * 0.02)) * 6;
                }
                if (pts.length > 3) {
                    const curve = new THREE.CatmullRomCurve3(pts);
                    const tube = new THREE.Mesh(
                        new THREE.TubeGeometry(curve, 24, 0.4 + rng() * 0.8, 6, false),
                        new THREE.MeshBasicMaterial({ color: 0xff4400, transparent: true, opacity: 0.65 })
                    );
                    scene.add(tube);
                }
            }
        }

        if (w.biome === 'Crystal') {
            // Frozen lake patches
            for (let i = 0; i < 5; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 1.2;
                const z = (rng() - 0.5) * w.bounds.z * 1.2;
                if (Math.sqrt(x * x + z * z) < 18) continue;
                const r = 3 + rng() * 6;
                const lake = new THREE.Mesh(
                    new THREE.CircleGeometry(r, 12),
                    new THREE.MeshStandardMaterial({ color: 0x88ccff, roughness: 0.05, metalness: 0.8, transparent: true, opacity: 0.5 })
                );
                lake.rotation.x = -Math.PI / 2;
                lake.position.set(x, 0.1, z);
                scene.add(lake);
            }
        }

        if (w.biome === 'Abyss') {
            // Floating platforms
            for (let i = 0; i < 10; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 1.4;
                const z = (rng() - 0.5) * w.bounds.z * 1.4;
                const y = 3 + rng() * 8;
                const s = 2 + rng() * 4;
                if (Math.sqrt(x * x + z * z) < 15) continue;
                const plat = new THREE.Mesh(
                    new THREE.BoxGeometry(s, 0.3, s * (0.5 + rng() * 0.8)),
                    new THREE.MeshStandardMaterial({
                        color: 0x1a1a25, emissive: 0x220044,
                        emissiveIntensity: 0.15, roughness: 0.85, flatShading: true
                    })
                );
                plat.position.set(x, y, z); plat.rotation.y = rng() * Math.PI;
                scene.add(plat);
            }
            // Void energy beams
            for (let i = 0; i < 5; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 1.2;
                const z = (rng() - 0.5) * w.bounds.z * 1.2;
                if (Math.sqrt(x * x + z * z) < 20) continue;
                const beam = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.1, 0.1, 25, 6),
                    new THREE.MeshBasicMaterial({ color: 0x6600aa, transparent: true, opacity: 0.25 })
                );
                beam.position.set(x, 12.5, z);
                scene.add(beam);
            }
        }

        if (w.biome === 'Desert') {
            // Oasis patches with palm trees
            for (let i = 0; i < 3; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 1.2;
                const z = (rng() - 0.5) * w.bounds.z * 1.2;
                if (Math.sqrt(x * x + z * z) < 20) continue;
                const r = 2 + rng() * 3;
                const water = new THREE.Mesh(
                    new THREE.CircleGeometry(r, 10),
                    new THREE.MeshStandardMaterial({ color: 0x2288aa, roughness: 0.1, metalness: 0.5, transparent: true, opacity: 0.6 })
                );
                water.rotation.x = -Math.PI / 2;
                water.position.set(x, 0.08, z);
                scene.add(water);
                // Palm tree
                const palm = new THREE.Group();
                const trunk = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.12, 0.2, 3, 6),
                    new THREE.MeshStandardMaterial({ color: 0x7a5a2a, roughness: 0.9 })
                );
                trunk.position.y = 1.5; trunk.rotation.z = 0.15;
                palm.add(trunk);
                for (let j = 0; j < 5; j++) {
                    const frond = new THREE.Mesh(
                        new THREE.ConeGeometry(0.7, 1.4, 4),
                        new THREE.MeshStandardMaterial({ color: 0x338833, roughness: 0.85, flatShading: true })
                    );
                    frond.position.y = 3.1; frond.rotation.z = 0.8;
                    frond.rotation.y = j * Math.PI * 2 / 5;
                    palm.add(frond);
                }
                palm.position.set(x + r * 0.8, 0, z);
                scene.add(palm);
            }
        }

        if (w.biome === 'Terra') {
            // Ponds
            for (let i = 0; i < 4; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 1.2;
                const z = (rng() - 0.5) * w.bounds.z * 1.2;
                if (Math.sqrt(x * x + z * z) < 20) continue;
                const r = 2 + rng() * 4;
                const pond = new THREE.Mesh(
                    new THREE.CircleGeometry(r, 10),
                    new THREE.MeshStandardMaterial({ color: 0x2266aa, roughness: 0.15, metalness: 0.3, transparent: true, opacity: 0.55 })
                );
                pond.rotation.x = -Math.PI / 2;
                pond.position.set(x, 0.06, z);
                scene.add(pond);
            }
            // Large landmark trees (2-3 massive trees)
            for (let i = 0; i < 2; i++) {
                const x = (rng() - 0.5) * w.bounds.x * 0.8;
                const z = (rng() - 0.5) * w.bounds.z * 0.8;
                if (Math.sqrt(x * x + z * z) < 25) continue;
                const g = new THREE.Group();
                const h = 8 + rng() * 4;
                const trunk = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.4, 0.8, h, 8),
                    new THREE.MeshStandardMaterial({ color: 0x4a2a10, roughness: 0.95 })
                );
                trunk.position.y = h / 2; g.add(trunk);
                const cr = 4 + rng() * 3;
                const canopy = new THREE.Mesh(
                    new THREE.SphereGeometry(cr, 8, 6),
                    new THREE.MeshStandardMaterial({ color: 0x1a5528, roughness: 0.85, flatShading: true })
                );
                canopy.position.y = h + cr * 0.2; canopy.scale.y = 0.6;
                g.add(canopy);
                g.position.set(x, this.getHeight(x, z), z);
                scene.add(g);
            }
        }
    },

    // ──────────────────────────────────────────────────────
    //  WEATHER SYSTEM (preserved from original)
    // ──────────────────────────────────────────────────────
    update(time, delta) {
        if (this.particles) this.particles.rotation.y = time * 0.015;
        if (delta) this.updateWeather(delta);
        if (delta) this._updateEchoAtmosphere(delta, time);
        const weatherEl = document.getElementById('weather-label');
        if (weatherEl && this.weatherType) weatherEl.textContent = this.weatherType.toUpperCase();
    },

    // Dynamic weather shift — echo tension can trigger weather transitions
    _weatherShiftTimer: 0,
    _lastWeatherTension: 0,
    _checkWeatherShift(tension) {
        if (!this.weatherParticles || !WorldMode.scene) return;
        this._weatherShiftTimer -= 0.3;
        if (this._weatherShiftTimer > 0) return;
        this._weatherShiftTimer = 10; // Check every 10 seconds

        // Tension spike detection — if tension jumps significantly, shift weather
        var delta = tension - this._lastWeatherTension;
        this._lastWeatherTension = tension;

        if (delta > 0.2 && tension > 0.5 && this.weatherType !== 'storm') {
            // High tension spike — intensify weather
            this.weatherParticles.material.size *= 1.2;
            this.weatherParticles.material.opacity = Math.min(0.8, this.weatherParticles.material.opacity + 0.1);
        } else if (tension < 0.2 && this._lastWeatherTension > 0.4) {
            // Tension dropped — calm weather
            this.weatherParticles.material.size *= 0.9;
            this.weatherParticles.material.opacity = Math.max(0.2, this.weatherParticles.material.opacity - 0.1);
        }
    },

    // Echo-reactive atmosphere: weather intensity, sky color, particle speed
    _echoAtmoTimer: 0,
    _updateEchoAtmosphere(delta, time) {
        if (typeof EchoEngine === 'undefined') return;
        this._echoAtmoTimer -= delta;
        if (this._echoAtmoTimer > 0) return;
        this._echoAtmoTimer = 0.3;

        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var L3 = ef.echoes.L3;
        var scene = WorldMode.scene;
        if (!scene) return;

        // Sky color shift — tension darkens and reddens, vitality brightens
        if (scene.background && scene.background.isColor) {
            var base = scene.background;
            var tensionTint = L3.tension * 0.05;
            var vitalityBright = L3.vitality * 0.02;
            // Subtle red shift during tension, blue shift during calm
            base.r = Math.min(1, base.r + (tensionTint - vitalityBright * 0.5) * delta);
            base.g = Math.max(0, base.g - tensionTint * 0.5 * delta);
            base.b = Math.max(0, base.b + (vitalityBright - tensionTint * 0.3) * delta);
            // Clamp to prevent runaway
            base.r = Math.max(0.02, Math.min(0.15, base.r));
            base.g = Math.max(0.02, Math.min(0.12, base.g));
            base.b = Math.max(0.05, Math.min(0.2, base.b));
        }

        // Weather particle opacity and speed react to tension
        if (this.weatherParticles && this.weatherParticles.material) {
            var baseTension = 0.5 + L3.tension * 0.4;
            this.weatherParticles.material.opacity = Math.min(0.8, this.weatherParticles.material.opacity * 0.95 + baseTension * 0.05);
        }

        // Check for weather shift on tension spikes
        this._checkWeatherShift(L3.tension);

        // Ambient particle rotation speed reacts to social energy
        if (this.particles) {
            var pulseScale = 1 + Math.sin(time * (1 + L3.socialEnergy * 2)) * L3.socialEnergy * 0.02;
            this.particles.scale.setScalar(pulseScale);
        }

        // Day/night cycle — driven by elapsed game time + echo frame depth
        this._updateDayNight(time, L3);
    },

    // Day/night cycle: smooth transitions based on play time
    _dayNightPhase: 0,
    _updateDayNight(time, L3) {
        if (!WorldMode.scene) return;
        // One full day/night cycle every 8 minutes of play
        this._dayNightPhase = (time % 480) / 480; // 0-1 over 8 min
        var phase = this._dayNightPhase;

        // Sinusoidal brightness: 0=midnight, 0.25=dawn, 0.5=noon, 0.75=dusk
        var sunHeight = Math.sin(phase * Math.PI * 2 - Math.PI / 2) * 0.5 + 0.5; // 0=night, 1=noon
        // Tension darkens the day
        sunHeight *= (1 - L3.tension * 0.3);

        // Adjust directional light
        for (var i = 0; i < WorldMode.scene.children.length; i++) {
            var child = WorldMode.scene.children[i];
            if (child.isDirectionalLight) {
                var targetIntensity = 0.3 + sunHeight * 0.6;
                child.intensity += (targetIntensity - child.intensity) * 0.02;
                // Warm sunrise/sunset tint when sun is low
                if (sunHeight < 0.3 && sunHeight > 0.05) {
                    child.color.lerp(new THREE.Color(0xffaa44), 0.01);
                } else if (sunHeight > 0.3) {
                    child.color.lerp(new THREE.Color(0xffffff), 0.01);
                } else {
                    child.color.lerp(new THREE.Color(0x4466aa), 0.01);
                }
            }
            if (child.isAmbientLight) {
                var ambTarget = 0.25 + sunHeight * 0.4;
                child.intensity += (ambTarget - child.intensity) * 0.02;
            }
        }

        // Fog darkens at night
        if (WorldMode.scene.fog) {
            var fogTarget = 0.002 + (1 - sunHeight) * 0.001 + L3.tension * 0.002;
            WorldMode.scene.fog.density += (fogTarget - WorldMode.scene.fog.density) * 0.02;
        }
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
        if (type !== 'clear') this.weatherParticles = this.createWeatherParticles(scene, w, type);
    },

    createWeatherParticles(scene, w, type) {
        const configs = {
            rain:             { count: 1000, color: 0xaaccff, size: 0.15, opacity: 0.5 },
            storm:            { count: 1000, color: 0x8899cc, size: 0.2,  opacity: 0.6 },
            snow:             { count: 800,  color: 0xffffff, size: 0.25, opacity: 0.6 },
            sandstorm:        { count: 900,  color: 0xccaa66, size: 0.3,  opacity: 0.45 },
            ash:              { count: 600,  color: 0x555555, size: 0.2,  opacity: 0.4 },
            ember:            { count: 500,  color: 0xff6600, size: 0.18, opacity: 0.5 },
            fog:              { count: 500,  color: 0xffffff, size: 2.0,  opacity: 0.15 },
            'heat shimmer':   { count: 600,  color: 0xffddaa, size: 0.3,  opacity: 0.2 },
            aurora:           { count: 700,  color: 0x44ffaa, size: 0.4,  opacity: 0.35 },
            'void particles': { count: 600,  color: 0x6600aa, size: 0.25, opacity: 0.4 }
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
            blending: THREE.AdditiveBlending, sizeAttenuation: true, depthWrite: false
        });
        const points = new THREE.Points(geo, mat);
        points.userData.weatherType = type;
        points.userData.bounds = { x: bx, z: bz, maxY: maxY };
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
                pos[iy] -= (type === 'storm' ? 25 : 18) * delta;
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
            if (pos[ix] > b.x) pos[ix] = -b.x;
            if (pos[ix] < -b.x) pos[ix] = b.x;
            if (pos[iz] > b.z) pos[iz] = -b.z;
            if (pos[iz] < -b.z) pos[iz] = b.z;
        }
        pts.geometry.attributes.position.needsUpdate = true;
    }
};
