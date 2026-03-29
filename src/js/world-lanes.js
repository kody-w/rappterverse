// World Lanes — DOTA-Style Map: Lanes, River, Roads, Brush, Towers, Thrones
const LANE_DEFS = {
    top: {
        name: 'Boreal Reach', color: 0x4488ff,
        waypoints: [
            { x: -1, z: -1 }, { x: -1, z: -0.6 }, { x: -1, z: -0.2 },
            { x: -1, z: 0.2 }, { x: -1, z: 0.6 }, { x: -1, z: 1 },
            { x: -0.5, z: 1 }, { x: 0, z: 1 }, { x: 0.5, z: 1 }, { x: 1, z: 1 }
        ],
        chokeIndex: 7
    },
    mid: {
        name: 'Nexus Spine', color: 0xffaa00,
        waypoints: [
            { x: -1, z: -1 }, { x: -0.75, z: -0.75 }, { x: -0.5, z: -0.5 },
            { x: -0.25, z: -0.25 }, { x: 0, z: 0 }, { x: 0.25, z: 0.25 },
            { x: 0.5, z: 0.5 }, { x: 0.75, z: 0.75 }, { x: 1, z: 1 }
        ],
        chokeIndex: 4
    },
    bot: {
        name: 'Verdant Trail', color: 0x44ff88,
        waypoints: [
            { x: -1, z: -1 }, { x: -0.5, z: -1 }, { x: 0, z: -1 },
            { x: 0.5, z: -1 }, { x: 1, z: -1 }, { x: 1, z: -0.6 },
            { x: 1, z: -0.2 }, { x: 1, z: 0.2 }, { x: 1, z: 0.6 }, { x: 1, z: 1 }
        ],
        chokeIndex: 2
    }
};

const WorldLanes = {
    towers: [],
    thrones: {},
    lanePaths: [],
    lanes: [],
    scaledWaypoints: {},

    init(scene, w) {
        this.towers = [];
        this.thrones = {};
        this.lanePaths = [];
        this.lanes = [];
        this.scaledWaypoints = {};

        const sx = w.bounds.x * 0.9;
        const sz = w.bounds.z * 0.9;

        // Scale waypoints
        for (const [laneKey, lane] of Object.entries(LANE_DEFS)) {
            const scaled = lane.waypoints.map(wp => ({ x: wp.x * sx, z: wp.z * sz }));
            this.scaledWaypoints[laneKey] = scaled;
            this.lanes.push({ name: lane.name, color: lane.color, key: laneKey, waypoints: scaled });
        }

        // Build map features in order
        this.buildRiver(scene, sx, sz, w);
        this.buildRoads(scene, w);
        this.buildBrush(scene, sx, sz, w);

        // Towers + Thrones
        for (const [laneKey, lane] of Object.entries(LANE_DEFS)) {
            this.createTowersForLane(scene, laneKey, lane, sx, sz);
        }
        this.createThrones(scene, sx, sz);
    },

    // ── RIVER (wide diagonal water with banks and shimmer) ──
    buildRiver(scene, sx, sz, w) {
        const riverWidth = Math.max(sx, sz) * 0.14; // Wide river
        const segments = 30;
        const points = [];
        for (let i = 0; i <= segments; i++) {
            const t = i / segments;
            const x = -sx + t * sx * 2;
            const z = sz - t * sz * 2;
            const wave = Math.sin(t * Math.PI * 4) * riverWidth * 0.2;
            const wave2 = Math.sin(t * Math.PI * 7) * riverWidth * 0.08;
            points.push({ x: x + wave + wave2, z: z + wave * 0.4 });
        }

        // Muddy riverbanks (wider, dark brown)
        for (let i = 0; i < points.length - 1; i++) {
            const a = points[i], b = points[i + 1];
            const dx = b.x - a.x, dz = b.z - a.z;
            const len = Math.sqrt(dx * dx + dz * dz) || 1;
            const bankW = riverWidth * 1.3;
            const nx = -dz / len * bankW, nz = dx / len * bankW;
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.01, a.z-nz, a.x+nx, 0.01, a.z+nz, b.x+nx, 0.01, b.z+nz,
                a.x-nx, 0.01, a.z-nz, b.x+nx, 0.01, b.z+nz, b.x-nx, 0.01, b.z-nz,
            ]), 3));
            const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
                color: 0x4a3a20, roughness: 0.95, metalness: 0.05
            }));
            scene.add(mesh);
            this.lanePaths.push(mesh);
        }

        // Deep water (main river body)
        for (let i = 0; i < points.length - 1; i++) {
            const a = points[i], b = points[i + 1];
            const dx = b.x - a.x, dz = b.z - a.z;
            const len = Math.sqrt(dx * dx + dz * dz) || 1;
            const nx = -dz / len * riverWidth, nz = dx / len * riverWidth;
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.03, a.z-nz, a.x+nx, 0.03, a.z+nz, b.x+nx, 0.03, b.z+nz,
                a.x-nx, 0.03, a.z-nz, b.x+nx, 0.03, b.z+nz, b.x-nx, 0.03, b.z-nz,
            ]), 3));
            const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
                color: 0x1a5588, roughness: 0.08, metalness: 0.6,
                transparent: true, opacity: 0.7
            }));
            scene.add(mesh);
            this.lanePaths.push(mesh);
        }

        // Shallow highlight (center strip — lighter blue)
        for (let i = 0; i < points.length - 1; i++) {
            const a = points[i], b = points[i + 1];
            const dx = b.x - a.x, dz = b.z - a.z;
            const len = Math.sqrt(dx * dx + dz * dz) || 1;
            const hw = riverWidth * 0.4;
            const nx = -dz / len * hw, nz = dx / len * hw;
            const geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.04, a.z-nz, a.x+nx, 0.04, a.z+nz, b.x+nx, 0.04, b.z+nz,
                a.x-nx, 0.04, a.z-nz, b.x+nx, 0.04, b.z+nz, b.x-nx, 0.04, b.z-nz,
            ]), 3));
            const mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
                color: 0x3399cc, roughness: 0.05, metalness: 0.7,
                transparent: true, opacity: 0.5
            }));
            scene.add(mesh);
            this.lanePaths.push(mesh);
        }

        // Rocks along riverbanks
        const rng = typeof seededRandom !== 'undefined' ? seededRandom('river-rocks') : Math.random;
        for (let i = 0; i < 40; i++) {
            const t = rng();
            const pi = Math.floor(t * (points.length - 1));
            const p = points[pi];
            const next = points[Math.min(pi + 1, points.length - 1)];
            const lt = t * (points.length - 1) - pi;
            const rx = p.x + (next.x - p.x) * lt;
            const rz = p.z + (next.z - p.z) * lt;
            // Offset to bank edge
            const side = rng() > 0.5 ? 1 : -1;
            const dx = next.x - p.x, dz = next.z - p.z;
            const len = Math.sqrt(dx * dx + dz * dz) || 1;
            const ox = (-dz / len) * riverWidth * (0.9 + rng() * 0.4) * side;
            const oz = (dx / len) * riverWidth * (0.9 + rng() * 0.4) * side;
            const s = 0.3 + rng() * 0.8;
            const rock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({
                    color: 0x555555 + Math.floor(rng() * 0x222222),
                    roughness: 0.9, flatShading: true
                })
            );
            rock.position.set(rx + ox, s * 0.3, rz + oz);
            rock.rotation.set(rng(), rng() * Math.PI, rng());
            scene.add(rock);
            this.lanePaths.push(rock);
        }

        // Water shimmer particles (more, brighter)
        const count = 400;
        const pGeo = new THREE.BufferGeometry();
        const pos = new Float32Array(count * 3);
        for (let i = 0; i < count; i++) {
            const t = rng();
            const pi = Math.floor(t * (points.length - 1));
            const p = points[pi];
            const next = points[Math.min(pi + 1, points.length - 1)];
            const lt = t * (points.length - 1) - pi;
            pos[i * 3] = p.x + (next.x - p.x) * lt + (rng() - 0.5) * riverWidth * 1.8;
            pos[i * 3 + 1] = 0.06 + rng() * 0.2;
            pos[i * 3 + 2] = p.z + (next.z - p.z) * lt + (rng() - 0.5) * riverWidth * 1.8;
        }
        pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        const shimmer = new THREE.Points(pGeo, new THREE.PointsMaterial({
            color: 0xaaddff, size: 0.2, transparent: true, opacity: 0.4,
            blending: THREE.AdditiveBlending, sizeAttenuation: true
        }));
        scene.add(shimmer);
        this.lanePaths.push(shimmer);
    },

    // ── ROADS (wide paths along lane waypoints) ──
    buildRoads(scene, w) {
        const roadWidth = 6;           // Wide dirt paths
        const roadColor = 0x8B7355;    // Worn brown dirt

        for (const [laneKey, lane] of Object.entries(LANE_DEFS)) {
            const wps = this.scaledWaypoints[laneKey];
            if (!wps || wps.length < 2) continue;

            for (let i = 0; i < wps.length - 1; i++) {
                const a = wps[i], b = wps[i + 1];
                const dx = b.x - a.x, dz = b.z - a.z;
                const len = Math.sqrt(dx * dx + dz * dz);
                if (len < 0.1) continue;
                const nx = -dz / len * roadWidth, nz = dx / len * roadWidth;

                const geo = new THREE.BufferGeometry();
                const verts = new Float32Array([
                    a.x - nx, 0.04, a.z - nz,
                    a.x + nx, 0.04, a.z + nz,
                    b.x + nx, 0.04, b.z + nz,
                    a.x - nx, 0.04, a.z - nz,
                    b.x + nx, 0.04, b.z + nz,
                    b.x - nx, 0.04, b.z - nz,
                ]);
                geo.setAttribute('position', new THREE.BufferAttribute(verts, 3));
                geo.computeVertexNormals();
                const mat = new THREE.MeshStandardMaterial({
                    color: roadColor, roughness: 0.95, metalness: 0.05,
                    transparent: true, opacity: 0.7
                });
                const mesh = new THREE.Mesh(geo, mat);
                scene.add(mesh);
                this.lanePaths.push(mesh);
            }

            // Lane color edge lines
            const points = wps.map(wp => new THREE.Vector3(wp.x, 0.08, wp.z));
            const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
            const lineMat = new THREE.LineBasicMaterial({
                color: lane.color, transparent: true, opacity: 0.35
            });
            const line = new THREE.Line(lineGeo, lineMat);
            scene.add(line);
            this.lanePaths.push(line);

            // Choke point
            const choke = wps[lane.chokeIndex];
            if (choke) {
                const ringGeo = new THREE.RingGeometry(2, 2.5, 16);
                const ringMat = new THREE.MeshBasicMaterial({
                    color: lane.color, side: THREE.DoubleSide, transparent: true, opacity: 0.2
                });
                const ring = new THREE.Mesh(ringGeo, ringMat);
                ring.rotation.x = -Math.PI / 2;
                ring.position.set(choke.x, 0.06, choke.z);
                scene.add(ring);
                this.lanePaths.push(ring);
            }
        }
    },

    // ── DENSE FOREST (fill everything, carve out lanes + river) ──
    buildBrush(scene, sx, sz, w) {
        const rng = typeof seededRandom !== 'undefined' ? seededRandom('brush-' + (GameState.currentWorld || 'hub')) : Math.random;
        const biome = w.biome || 'Terra';
        const laneCarveRadius = 14; // Wide clear space around lanes
        const riverCarveRadius = 16; // Wide clear space around river
        const baseCarveRadius = 25;  // Clear space around team bases

        // Fill the ENTIRE map with forest — 600 objects on a grid
        const gridStep = Math.max(sx, sz) * 2 / 15; // ~15x15 grid
        for (let gx = -sx; gx <= sx; gx += gridStep) {
            for (let gz = -sz; gz <= sz; gz += gridStep) {
                const x = gx + (rng() - 0.5) * gridStep * 0.8;
                const z = gz + (rng() - 0.5) * gridStep * 0.8;

                // CARVE: skip if near any lane
                if (this.isNearLane(x, z, laneCarveRadius)) continue;

                // CARVE: skip if near river (diagonal from -sx,sz to sx,-sz)
                const riverDist = Math.abs(x + z) / Math.sqrt(2);
                if (riverDist < riverCarveRadius) continue;

                // CARVE: skip if near team bases
                if (Math.sqrt((x+sx)*(x+sx)+(z+sz)*(z+sz)) < baseCarveRadius) continue;
                if (Math.sqrt((x-sx)*(x-sx)+(z-sz)*(z-sz)) < baseCarveRadius) continue;

            const h = 2 + rng() * 4;
            const r = 1 + rng() * 2;
            const g = new THREE.Group();

            if (biome === 'Terra' || biome === 'Crystal') {
                // Dense trees
                const trunk = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.2, 0.3, h, 5),
                    new THREE.MeshStandardMaterial({ color: 0x3a2a10, roughness: 0.95 })
                );
                trunk.position.y = h / 2;
                g.add(trunk);
                const canopy = new THREE.Mesh(
                    new THREE.SphereGeometry(r, 5, 4),
                    new THREE.MeshStandardMaterial({
                        color: biome === 'Crystal' ? 0x225544 : 0x1a4420,
                        roughness: 0.9, flatShading: true
                    })
                );
                canopy.position.y = h + r * 0.3;
                g.add(canopy);
            } else if (biome === 'Volcanic') {
                // Lava rock walls
                const rock = new THREE.Mesh(
                    new THREE.DodecahedronGeometry(r, 0),
                    new THREE.MeshStandardMaterial({
                        color: 0x1a1010, roughness: 0.95, flatShading: true,
                        emissive: 0xff2200, emissiveIntensity: 0.05
                    })
                );
                rock.position.y = r * 0.5;
                g.add(rock);
            } else if (biome === 'Desert') {
                // Sand dune walls
                const dune = new THREE.Mesh(
                    new THREE.SphereGeometry(r * 1.5, 6, 4),
                    new THREE.MeshStandardMaterial({ color: 0xaa8844, roughness: 0.95, flatShading: true })
                );
                dune.position.y = r * 0.3;
                dune.scale.y = 0.4;
                g.add(dune);
            } else {
                // Abyss — void walls
                const pillar = new THREE.Mesh(
                    new THREE.CylinderGeometry(0.3, 0.5, h * 1.5, 5),
                    new THREE.MeshStandardMaterial({
                        color: 0x0a0a12, roughness: 0.8,
                        emissive: 0x330066, emissiveIntensity: 0.1, flatShading: true
                    })
                );
                pillar.position.y = h * 0.75;
                g.add(pillar);
            }

            g.position.set(x, 0, z);
            g.rotation.y = rng() * Math.PI * 2;
            scene.add(g);
            this.lanePaths.push(g);
            }
        }

        // Jungle brush patches (between lanes — hide spots)
        const brushPatches = [
            // Between top and mid (explorer jungle)
            { cx: -0.6, cz: 0.3, r: 0.15 },
            { cx: -0.4, cz: 0.6, r: 0.12 },
            // Between mid and bot (explorer jungle)
            { cx: -0.3, cz: -0.6, r: 0.12 },
            { cx: -0.6, cz: -0.3, r: 0.15 },
            // Between top and mid (horde jungle)
            { cx: 0.6, cz: -0.3, r: 0.15 },
            { cx: 0.4, cz: -0.6, r: 0.12 },
            // Between mid and bot (horde jungle)
            { cx: 0.3, cz: 0.6, r: 0.12 },
            { cx: 0.6, cz: 0.3, r: 0.15 },
        ];

        brushPatches.forEach(function(patch) {
            const bx = patch.cx * sx, bz = patch.cz * sz;
            const br = patch.r * Math.max(sx, sz);
            // Green bush circle on ground
            const bushGeo = new THREE.CircleGeometry(br, 10);
            const bushMat = new THREE.MeshStandardMaterial({
                color: biome === 'Volcanic' ? 0x2a1a1a : biome === 'Desert' ? 0x667744 : biome === 'Abyss' ? 0x110022 : 0x1a3a1a,
                roughness: 0.95, transparent: true, opacity: 0.6
            });
            const bush = new THREE.Mesh(bushGeo, bushMat);
            bush.rotation.x = -Math.PI / 2;
            bush.position.set(bx, 0.03, bz);
            scene.add(bush);
            this.lanePaths.push(bush);

            // Brush objects inside
            for (var j = 0; j < 8; j++) {
                var angle = rng() * Math.PI * 2;
                var dist = rng() * br * 0.8;
                var ox = bx + Math.cos(angle) * dist;
                var oz = bz + Math.sin(angle) * dist;
                var s = 0.5 + rng() * 1;
                var bushObj = new THREE.Mesh(
                    new THREE.SphereGeometry(s, 4, 3),
                    new THREE.MeshStandardMaterial({
                        color: biome === 'Volcanic' ? 0x332211 : biome === 'Abyss' ? 0x110022 : 0x225522,
                        roughness: 0.9, flatShading: true, transparent: true, opacity: 0.7
                    })
                );
                bushObj.position.set(ox, s * 0.4, oz);
                bushObj.scale.y = 0.5;
                scene.add(bushObj);
                this.lanePaths.push(bushObj);
            }
        }.bind(this));
    },

    // ── TOWERS ──
    createTowersForLane(scene, laneKey, lane, sx, sz) {
        const wps = this.scaledWaypoints[laneKey];
        const total = wps.length;

        const explorerIndices = [1, 2, Math.floor(total * 0.35)];
        const hordeIndices = [total - 2, total - 3, Math.ceil(total * 0.65)];

        explorerIndices.forEach((idx, i) => {
            const wp = wps[Math.min(idx, total - 1)];
            this.createTower(scene, wp.x, wp.z, 'explorer', lane.color, laneKey, i);
        });
        hordeIndices.forEach((idx, i) => {
            const wp = wps[Math.min(idx, total - 1)];
            this.createTower(scene, wp.x, wp.z, 'horde', 0xff4488, laneKey, i + 3);
        });
    },

    createTower(scene, x, z, faction, color, lane, index) {
        const group = new THREE.Group();
        const teamColor = faction === 'explorer' ? 0x00ccff : 0xff4444;

        const baseGeo = new THREE.CylinderGeometry(1.5, 2, 1.5, 8);
        const baseMat = new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 });
        group.add(new THREE.Mesh(baseGeo, baseMat));
        group.children[0].position.y = 0.75;

        const colGeo = new THREE.CylinderGeometry(0.6, 0.8, 5, 8);
        const colMat = new THREE.MeshStandardMaterial({
            color: teamColor, emissive: teamColor, emissiveIntensity: 0.15,
            roughness: 0.4, metalness: 0.6
        });
        const col = new THREE.Mesh(colGeo, colMat);
        col.position.y = 4;
        group.add(col);

        const orbGeo = new THREE.SphereGeometry(0.8, 12, 12);
        const orbMat = new THREE.MeshStandardMaterial({
            color: teamColor, emissive: teamColor, emissiveIntensity: 0.5,
            roughness: 0.2, metalness: 0.8
        });
        const orb = new THREE.Mesh(orbGeo, orbMat);
        orb.position.y = 7;
        group.add(orb);

        const rangeGeo = new THREE.RingGeometry(14.5, 15, 24);
        const rangeMat = new THREE.MeshBasicMaterial({
            color: teamColor, side: THREE.DoubleSide, transparent: true, opacity: 0.06
        });
        const rangeRing = new THREE.Mesh(rangeGeo, rangeMat);
        rangeRing.rotation.x = -Math.PI / 2;
        rangeRing.position.y = 0.02;
        group.add(rangeRing);

        const hpGeo = new THREE.PlaneGeometry(3, 0.3);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = 8.5;
        group.add(hpBar);

        // Offset towers to their side of the road
        const offset = faction === 'explorer' ? -3 : 3;
        group.position.set(x + offset, 0, z);
        scene.add(group);

        this.towers.push({
            mesh: group, orb, hpBar,
            hp: 100, maxHp: 100,
            lane, faction, index,
            attackTimer: 0, target: null,
            attackRange: 15, attackDamage: 12, attackCooldown: 1.5
        });
    },

    // ── THRONES ──
    createThrones(scene, sx, sz) {
        this.thrones.explorer = this._buildThrone(scene, -sx, -sz, 'explorer', 0x00ccff);
        this.thrones.horde = this._buildThrone(scene, sx, sz, 'horde', 0xff4444);
    },

    _buildThrone(scene, x, z, faction, color) {
        const group = new THREE.Group();
        const baseGeo = new THREE.CylinderGeometry(4, 5, 1.5, 16);
        const baseMat = new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 });
        group.add(new THREE.Mesh(baseGeo, baseMat));
        group.children[0].position.y = 0.75;

        const ringGeo = new THREE.TorusGeometry(3, 0.3, 8, 24);
        const ringMat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.3, roughness: 0.3, metalness: 0.7 });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = Math.PI / 2; ring.position.y = 1.8;
        group.add(ring);

        const crystalGeo = new THREE.OctahedronGeometry(2, 0);
        const crystalMat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.5, roughness: 0.1, metalness: 0.9, transparent: true, opacity: 0.9 });
        const crystal = new THREE.Mesh(crystalGeo, crystalMat);
        crystal.position.y = 5;
        group.add(crystal);

        for (let i = 0; i < 4; i++) {
            const a = (i / 4) * Math.PI * 2;
            const pillar = new THREE.Mesh(
                new THREE.CylinderGeometry(0.5, 0.7, 6, 8),
                new THREE.MeshStandardMaterial({ color: 0x222233, roughness: 0.5, metalness: 0.5 })
            );
            pillar.position.set(Math.cos(a) * 3, 3, Math.sin(a) * 3);
            group.add(pillar);
        }

        const crownGeo = new THREE.TorusGeometry(1.5, 0.2, 8, 16);
        const crownMat = new THREE.MeshStandardMaterial({ color: 0xffd700, emissive: 0xffa500, emissiveIntensity: 0.3, roughness: 0.2, metalness: 0.8 });
        const crown = new THREE.Mesh(crownGeo, crownMat);
        crown.rotation.x = Math.PI / 2; crown.position.y = 8;
        group.add(crown);

        const hpGeo = new THREE.PlaneGeometry(5, 0.4);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = 10;
        group.add(hpBar);

        group.position.set(x, 0, z);
        scene.add(group);
        return { mesh: group, crystal, crown, hpBar, hp: 200, maxHp: 200 };
    },

    // ── UTILITIES ──
    isNearLane(x, z, radius) {
        for (const wps of Object.values(this.scaledWaypoints)) {
            for (const wp of wps) {
                const dx = x - wp.x, dz = z - wp.z;
                if (dx * dx + dz * dz < radius * radius) return true;
            }
        }
        return false;
    },

    areTowersDown(lane, faction) {
        return this.towers.filter(t => t.lane === lane && t.faction === faction).every(t => t.hp <= 0);
    },

    updateTowerVisuals(time) {
        this.towers.forEach(t => {
            if (t.hp <= 0) {
                if (t.mesh.visible) t.mesh.visible = false;
                return;
            }
            const ratio = t.hp / t.maxHp;
            t.hpBar.scale.x = ratio;
            t.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);
            if (t.orb) t.orb.material.emissiveIntensity = 0.3 + Math.sin(time * 3) * 0.2;
        });

        for (const [faction, throne] of Object.entries(this.thrones)) {
            if (throne.hp <= 0) {
                if (throne.mesh.visible) throne.mesh.visible = false;
                continue;
            }
            const ratio = throne.hp / throne.maxHp;
            throne.hpBar.scale.x = ratio;
            throne.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);
            if (throne.crystal) {
                throne.crystal.rotation.y = time * 0.5;
                throne.crystal.position.y = 5 + Math.sin(time * 0.8) * 0.3;
            }
            if (throne.crown) throne.crown.rotation.z = time * 0.3;
        }
    },

    cleanup() {
        const disposeMesh = (mesh) => {
            if (mesh.geometry) mesh.geometry.dispose();
            if (mesh.material) {
                if (Array.isArray(mesh.material)) mesh.material.forEach(m => m.dispose());
                else mesh.material.dispose();
            }
        };
        const disposeGroup = (group) => { group.traverse(child => { disposeMesh(child); }); };

        for (const mesh of this.lanePaths) {
            if (mesh.parent) mesh.parent.remove(mesh);
            if (mesh.traverse) disposeGroup(mesh);
            else disposeMesh(mesh);
        }
        for (const t of this.towers) {
            if (t.mesh.parent) t.mesh.parent.remove(t.mesh);
            disposeGroup(t.mesh);
        }
        for (const throne of Object.values(this.thrones)) {
            if (throne.mesh.parent) throne.mesh.parent.remove(throne.mesh);
            disposeGroup(throne.mesh);
        }

        this.towers = [];
        this.thrones = {};
        this.lanePaths = [];
        this.lanes = [];
        this.scaledWaypoints = {};
    }
};
