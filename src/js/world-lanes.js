// World Lanes — Authentic MOBA Map: Organic Lanes, Natural River, Dense Jungle
// Mirrors real Dota 2 map geometry: L-shaped top/bot lanes, diagonal mid,
// curved river, Roshan pit, rune spots, dense treeline between lanes.

// Catmull-Rom spline interpolation for smooth organic curves
function _catmullRom(p0, p1, p2, p3, t) {
    var t2 = t * t, t3 = t2 * t;
    return 0.5 * (
        (2 * p1) +
        (-p0 + p2) * t +
        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
        (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    );
}

function _interpPoints(controls, count) {
    var pts = [];
    for (var i = 0; i <= count; i++) {
        var t = i / count;
        var idx = t * (controls.length - 1);
        var ci = Math.floor(idx);
        var ct = idx - ci;
        var p0 = controls[Math.max(0, ci - 1)];
        var p1 = controls[ci];
        var p2 = controls[Math.min(controls.length - 1, ci + 1)];
        var p3 = controls[Math.min(controls.length - 1, ci + 2)];
        pts.push({
            x: _catmullRom(p0.x, p1.x, p2.x, p3.x, ct),
            z: _catmullRom(p0.z, p1.z, p2.z, p3.z, ct)
        });
    }
    return pts;
}

// ── Lane definitions with organic curves ──
const LANE_DEFS = {
    top: {
        name: 'Boreal Reach', color: 0x4488ff,
        waypoints: [
            { x: -1, z: -1 },
            { x: -0.97, z: -0.80 },
            { x: -0.94, z: -0.58 },
            { x: -0.96, z: -0.34 },
            { x: -0.93, z: -0.10 },
            { x: -0.97, z: 0.14 },
            { x: -0.95, z: 0.38 },
            { x: -0.92, z: 0.58 },
            { x: -0.86, z: 0.76 },
            { x: -0.76, z: 0.86 },
            { x: -0.60, z: 0.92 },
            { x: -0.38, z: 0.95 },
            { x: -0.14, z: 0.93 },
            { x: 0.10, z: 0.96 },
            { x: 0.34, z: 0.94 },
            { x: 0.58, z: 0.97 },
            { x: 0.80, z: 0.94 },
            { x: 1, z: 1 }
        ],
        chokeIndex: 9
    },
    mid: {
        name: 'Nexus Spine', color: 0xffaa00,
        waypoints: [
            { x: -1, z: -1 },
            { x: -0.84, z: -0.86 },
            { x: -0.68, z: -0.72 },
            { x: -0.52, z: -0.56 },
            { x: -0.36, z: -0.40 },
            { x: -0.22, z: -0.26 },
            { x: -0.08, z: -0.10 },
            { x: 0.06, z: 0.04 },
            { x: 0.14, z: 0.18 },
            { x: 0.26, z: 0.30 },
            { x: 0.40, z: 0.42 },
            { x: 0.56, z: 0.54 },
            { x: 0.72, z: 0.68 },
            { x: 0.86, z: 0.84 },
            { x: 1, z: 1 }
        ],
        chokeIndex: 7
    },
    bot: {
        name: 'Verdant Trail', color: 0x44ff88,
        waypoints: [
            { x: -1, z: -1 },
            { x: -0.80, z: -0.97 },
            { x: -0.58, z: -0.94 },
            { x: -0.34, z: -0.96 },
            { x: -0.10, z: -0.93 },
            { x: 0.14, z: -0.97 },
            { x: 0.38, z: -0.95 },
            { x: 0.58, z: -0.92 },
            { x: 0.76, z: -0.86 },
            { x: 0.86, z: -0.76 },
            { x: 0.92, z: -0.60 },
            { x: 0.95, z: -0.38 },
            { x: 0.93, z: -0.14 },
            { x: 0.96, z: 0.10 },
            { x: 0.94, z: 0.34 },
            { x: 0.97, z: 0.58 },
            { x: 0.94, z: 0.80 },
            { x: 1, z: 1 }
        ],
        chokeIndex: 9
    }
};

// River control points (organic S-curve)
const RIVER_CONTROLS = [
    { x: -1.05, z: 0.95 },
    { x: -0.82, z: 0.74 },
    { x: -0.58, z: 0.50 },
    { x: -0.38, z: 0.32 },
    { x: -0.20, z: 0.18 },
    { x: -0.04, z: 0.04 },
    { x: 0.12, z: -0.10 },
    { x: 0.28, z: -0.24 },
    { x: 0.46, z: -0.40 },
    { x: 0.65, z: -0.58 },
    { x: 0.82, z: -0.74 },
    { x: 1.05, z: -0.95 }
];

const WorldLanes = {
    towers: [],
    thrones: {},
    lanePaths: [],
    lanes: [],
    scaledWaypoints: {},
    riverPoints: [],
    runeSpots: [],
    roshanPit: null,

    init(scene, w) {
        this.towers = [];
        this.thrones = {};
        this.lanePaths = [];
        this.lanes = [];
        this.scaledWaypoints = {};
        this.riverPoints = [];
        this.runeSpots = [];
        this.roshanPit = null;

        var sx = w.bounds.x * 0.9;
        var sz = w.bounds.z * 0.9;

        for (var laneKey in LANE_DEFS) {
            var lane = LANE_DEFS[laneKey];
            var scaled = lane.waypoints.map(function(wp) { return { x: wp.x * sx, z: wp.z * sz }; });
            this.scaledWaypoints[laneKey] = scaled;
            this.lanes.push({ name: lane.name, color: lane.color, key: laneKey, waypoints: scaled });
        }

        var rawRiver = _interpPoints(RIVER_CONTROLS, 60);
        this.riverPoints = rawRiver.map(function(p) { return { x: p.x * sx, z: p.z * sz }; });

        var runeIdx1 = Math.floor(this.riverPoints.length * 0.3);
        var runeIdx2 = Math.floor(this.riverPoints.length * 0.7);
        this.runeSpots = [
            { x: this.riverPoints[runeIdx1].x, z: this.riverPoints[runeIdx1].z },
            { x: this.riverPoints[runeIdx2].x, z: this.riverPoints[runeIdx2].z }
        ];

        this.roshanPit = { x: 0.18 * sx, z: 0.12 * sz };

        this.buildRiver(scene, sx, sz, w);
        this.buildRoads(scene, w, sx, sz);
        this.buildBrush(scene, sx, sz, w);

        for (var lk in LANE_DEFS) {
            this.createTowersForLane(scene, lk, LANE_DEFS[lk], sx, sz);
        }
        this.createThrones(scene, sx, sz);
    },

    buildRiver(scene, sx, sz, w) {
        var pts = this.riverPoints;
        var baseWidth = Math.max(sx, sz) * 0.10;
        var rng = typeof seededRandom !== 'undefined' ? seededRandom('river-organic') : Math.random;

        function riverWidth(i) {
            var t = i / (pts.length - 1);
            var center = 1 - Math.abs(t - 0.5) * 2;
            return baseWidth * (0.7 + center * 0.6);
        }

        // Muddy riverbanks
        for (var i = 0; i < pts.length - 1; i++) {
            var a = pts[i], b = pts[i + 1];
            var dx = b.x - a.x, dz = b.z - a.z;
            var len = Math.sqrt(dx * dx + dz * dz) || 1;
            var bw = riverWidth(i) * 1.4;
            var nx = -dz / len * bw, nz = dx / len * bw;
            var geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.01, a.z-nz, a.x+nx, 0.01, a.z+nz, b.x+nx, 0.01, b.z+nz,
                a.x-nx, 0.01, a.z-nz, b.x+nx, 0.01, b.z+nz, b.x-nx, 0.01, b.z-nz
            ]), 3));
            scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x3a2a15, roughness: 0.95, metalness: 0.05 })));
            this.lanePaths.push(scene.children[scene.children.length - 1]);
        }

        // Deep water
        for (var i = 0; i < pts.length - 1; i++) {
            var a = pts[i], b = pts[i + 1];
            var dx = b.x - a.x, dz = b.z - a.z;
            var len = Math.sqrt(dx * dx + dz * dz) || 1;
            var rw = riverWidth(i);
            var nx = -dz / len * rw, nz = dx / len * rw;
            var geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.03, a.z-nz, a.x+nx, 0.03, a.z+nz, b.x+nx, 0.03, b.z+nz,
                a.x-nx, 0.03, a.z-nz, b.x+nx, 0.03, b.z+nz, b.x-nx, 0.03, b.z-nz
            ]), 3));
            scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
                color: 0x1a4a70, roughness: 0.08, metalness: 0.6, transparent: true, opacity: 0.75
            })));
            this.lanePaths.push(scene.children[scene.children.length - 1]);
        }

        // Shallow highlight
        for (var i = 0; i < pts.length - 1; i++) {
            var a = pts[i], b = pts[i + 1];
            var dx = b.x - a.x, dz = b.z - a.z;
            var len = Math.sqrt(dx * dx + dz * dz) || 1;
            var hw = riverWidth(i) * 0.35;
            var nx = -dz / len * hw, nz = dx / len * hw;
            var geo = new THREE.BufferGeometry();
            geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                a.x-nx, 0.04, a.z-nz, a.x+nx, 0.04, a.z+nz, b.x+nx, 0.04, b.z+nz,
                a.x-nx, 0.04, a.z-nz, b.x+nx, 0.04, b.z+nz, b.x-nx, 0.04, b.z-nz
            ]), 3));
            scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({
                color: 0x3399bb, roughness: 0.05, metalness: 0.7, transparent: true, opacity: 0.45
            })));
            this.lanePaths.push(scene.children[scene.children.length - 1]);
        }

        // Rocks along riverbanks
        for (var r = 0; r < 60; r++) {
            var t = rng();
            var pi = Math.floor(t * (pts.length - 1));
            var p = pts[pi], next = pts[Math.min(pi + 1, pts.length - 1)];
            var lt = t * (pts.length - 1) - pi;
            var rx = p.x + (next.x - p.x) * lt;
            var rz = p.z + (next.z - p.z) * lt;
            var side = rng() > 0.5 ? 1 : -1;
            var ddx = next.x - p.x, ddz = next.z - p.z;
            var dlen = Math.sqrt(ddx * ddx + ddz * ddz) || 1;
            var bw = riverWidth(pi);
            var ox = (-ddz / dlen) * bw * (0.85 + rng() * 0.5) * side;
            var oz = (ddx / dlen) * bw * (0.85 + rng() * 0.5) * side;
            var s = 0.2 + rng() * 0.9;
            var rock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(s, 0),
                new THREE.MeshStandardMaterial({ color: 0x505050 + Math.floor(rng() * 0x282828), roughness: 0.92, flatShading: true })
            );
            rock.position.set(rx + ox, s * 0.25, rz + oz);
            rock.rotation.set(rng(), rng() * Math.PI, rng());
            scene.add(rock);
            this.lanePaths.push(rock);
        }

        // Water shimmer particles
        var count = 500;
        var pGeo = new THREE.BufferGeometry();
        var pos = new Float32Array(count * 3);
        for (var i = 0; i < count; i++) {
            var t = rng();
            var pi = Math.floor(t * (pts.length - 1));
            var p = pts[pi], next = pts[Math.min(pi + 1, pts.length - 1)];
            var lt = t * (pts.length - 1) - pi;
            var rw = riverWidth(pi);
            pos[i * 3] = p.x + (next.x - p.x) * lt + (rng() - 0.5) * rw * 2;
            pos[i * 3 + 1] = 0.06 + rng() * 0.15;
            pos[i * 3 + 2] = p.z + (next.z - p.z) * lt + (rng() - 0.5) * rw * 2;
        }
        pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
        var shimmer = new THREE.Points(pGeo, new THREE.PointsMaterial({
            color: 0xaaddff, size: 0.18, transparent: true, opacity: 0.35,
            blending: THREE.AdditiveBlending, sizeAttenuation: true
        }));
        scene.add(shimmer);
        this.lanePaths.push(shimmer);

        // Rune spots
        var self = this;
        this.runeSpots.forEach(function(rune) {
            var ring = new THREE.Mesh(
                new THREE.RingGeometry(1.2, 1.6, 16),
                new THREE.MeshBasicMaterial({ color: 0xffd700, side: THREE.DoubleSide, transparent: true, opacity: 0.25 })
            );
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(rune.x, 0.05, rune.z);
            scene.add(ring);
            self.lanePaths.push(ring);
            var glow = new THREE.Mesh(
                new THREE.CircleGeometry(0.8, 12),
                new THREE.MeshBasicMaterial({ color: 0xffcc00, transparent: true, opacity: 0.15, side: THREE.DoubleSide })
            );
            glow.rotation.x = -Math.PI / 2;
            glow.position.set(rune.x, 0.06, rune.z);
            scene.add(glow);
            self.lanePaths.push(glow);
        });

        // Roshan pit — rocky enclosure near river
        var rosh = this.roshanPit;
        var pitRing = new THREE.Mesh(
            new THREE.RingGeometry(4, 5.5, 20),
            new THREE.MeshStandardMaterial({ color: 0x3a2a1a, roughness: 0.95, side: THREE.DoubleSide, transparent: true, opacity: 0.6 })
        );
        pitRing.rotation.x = -Math.PI / 2;
        pitRing.position.set(rosh.x, 0.02, rosh.z);
        scene.add(pitRing);
        this.lanePaths.push(pitRing);
        for (var i = 0; i < 12; i++) {
            var angle = (i / 12) * Math.PI * 2;
            if (i >= 5 && i <= 6) continue;
            var rs = 0.8 + rng() * 0.6;
            var pitRock = new THREE.Mesh(
                new THREE.DodecahedronGeometry(rs, 0),
                new THREE.MeshStandardMaterial({ color: 0x2a1a0a, roughness: 0.95, flatShading: true })
            );
            pitRock.position.set(rosh.x + Math.cos(angle) * 4.8, rs * 0.6, rosh.z + Math.sin(angle) * 4.8);
            pitRock.rotation.set(rng(), rng() * Math.PI, rng());
            scene.add(pitRock);
            this.lanePaths.push(pitRock);
        }
    },

    buildRoads(scene, w, sx, sz) {
        var roadColor = 0x7B6345;
        for (var laneKey in LANE_DEFS) {
            var lane = LANE_DEFS[laneKey];
            var wps = this.scaledWaypoints[laneKey];
            if (!wps || wps.length < 2) continue;

            for (var i = 0; i < wps.length - 1; i++) {
                var a = wps[i], b = wps[i + 1];
                var dx = b.x - a.x, dz = b.z - a.z;
                var len = Math.sqrt(dx * dx + dz * dz);
                if (len < 0.1) continue;
                var roadWidth = 5 + Math.sin(i * 0.7) * 1.5;
                var nx = -dz / len * roadWidth, nz = dx / len * roadWidth;
                var geo = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                    a.x-nx, 0.04, a.z-nz, a.x+nx, 0.04, a.z+nz, b.x+nx, 0.04, b.z+nz,
                    a.x-nx, 0.04, a.z-nz, b.x+nx, 0.04, b.z+nz, b.x-nx, 0.04, b.z-nz
                ]), 3));
                geo.computeVertexNormals();
                scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: roadColor, roughness: 0.95, metalness: 0.05, transparent: true, opacity: 0.7 })));
                this.lanePaths.push(scene.children[scene.children.length - 1]);
            }

            for (var i = 0; i < wps.length - 1; i++) {
                var a = wps[i], b = wps[i + 1];
                var dx = b.x - a.x, dz = b.z - a.z;
                var len = Math.sqrt(dx * dx + dz * dz);
                if (len < 0.1) continue;
                var hw = 2 + Math.sin(i * 0.9) * 0.8;
                var nx = -dz / len * hw, nz = dx / len * hw;
                var geo = new THREE.BufferGeometry();
                geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array([
                    a.x-nx, 0.045, a.z-nz, a.x+nx, 0.045, a.z+nz, b.x+nx, 0.045, b.z+nz,
                    a.x-nx, 0.045, a.z-nz, b.x+nx, 0.045, b.z+nz, b.x-nx, 0.045, b.z-nz
                ]), 3));
                scene.add(new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: 0x9A8565, roughness: 0.9, metalness: 0.05, transparent: true, opacity: 0.5 })));
                this.lanePaths.push(scene.children[scene.children.length - 1]);
            }

            var points = wps.map(function(wp) { return new THREE.Vector3(wp.x, 0.08, wp.z); });
            var lineGeo = new THREE.BufferGeometry().setFromPoints(points);
            var line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: lane.color, transparent: true, opacity: 0.2 }));
            scene.add(line);
            this.lanePaths.push(line);
        }
    },

    buildBrush(scene, sx, sz, w) {
        var rng = typeof seededRandom !== 'undefined' ? seededRandom('brush-' + (GameState.currentWorld || 'hub')) : Math.random;
        var biome = w.biome || 'Terra';
        var laneCarveRadius = 10;
        var riverCarveRadius = 8;
        var baseCarveRadius = 20;
        var roshanCarveRadius = 8;
        var self = this;

        function riverDist(x, z) {
            var min = Infinity;
            for (var i = 0; i < self.riverPoints.length; i += 3) {
                var dx = x - self.riverPoints[i].x, dz = z - self.riverPoints[i].z;
                var d = dx * dx + dz * dz;
                if (d < min) min = d;
            }
            return Math.sqrt(min);
        }

        var gridStep = Math.max(sx, sz) * 2 / 22;
        for (var gx = -sx; gx <= sx; gx += gridStep) {
            for (var gz = -sz; gz <= sz; gz += gridStep) {
                var x = gx + (rng() - 0.5) * gridStep * 0.85;
                var z = gz + (rng() - 0.5) * gridStep * 0.85;
                if (this.isNearLane(x, z, laneCarveRadius)) continue;
                if (riverDist(x, z) < riverCarveRadius) continue;
                if (Math.sqrt((x+sx)*(x+sx)+(z+sz)*(z+sz)) < baseCarveRadius) continue;
                if (Math.sqrt((x-sx)*(x-sx)+(z-sz)*(z-sz)) < baseCarveRadius) continue;
                if (this.roshanPit) {
                    var rdx = x - this.roshanPit.x, rdz = z - this.roshanPit.z;
                    if (Math.sqrt(rdx*rdx+rdz*rdz) < roshanCarveRadius) continue;
                }

                var treeType = rng();
                var g = new THREE.Group();

                if (biome === 'Terra' || biome === 'Crystal') {
                    if (treeType < 0.45) {
                        var h = 4 + rng() * 5;
                        var trunk = new THREE.Mesh(
                            new THREE.CylinderGeometry(0.15 + rng() * 0.1, 0.25 + rng() * 0.15, h, 5),
                            new THREE.MeshStandardMaterial({ color: 0x2a1a08 + Math.floor(rng() * 0x101010), roughness: 0.95 })
                        );
                        trunk.position.y = h / 2;
                        g.add(trunk);
                        var layers = 2 + Math.floor(rng() * 2);
                        for (var li = 0; li < layers; li++) {
                            var lr = (2.5 - li * 0.6) * (0.8 + rng() * 0.4);
                            var canopy = new THREE.Mesh(
                                new THREE.ConeGeometry(lr, 2.5, 5),
                                new THREE.MeshStandardMaterial({ color: biome === 'Crystal' ? 0x1a4a3a : (0x0a3010 + Math.floor(rng() * 0x0a1a0a)), roughness: 0.9, flatShading: true })
                            );
                            canopy.position.y = h * 0.5 + li * 2;
                            g.add(canopy);
                        }
                    } else if (treeType < 0.75) {
                        var h = 3 + rng() * 3;
                        var r = 1.5 + rng() * 1.5;
                        g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.25, h, 5), new THREE.MeshStandardMaterial({ color: 0x3a2510, roughness: 0.95 })));
                        g.children[0].position.y = h / 2;
                        var canopy = new THREE.Mesh(new THREE.SphereGeometry(r, 5, 4), new THREE.MeshStandardMaterial({ color: biome === 'Crystal' ? 0x1a4a3a : (0x143a1a + Math.floor(rng() * 0x0a1a0a)), roughness: 0.88, flatShading: true }));
                        canopy.position.y = h + r * 0.2;
                        canopy.scale.y = 0.7 + rng() * 0.3;
                        g.add(canopy);
                    } else if (treeType < 0.88) {
                        var r = 0.6 + rng() * 0.8;
                        var bush = new THREE.Mesh(new THREE.SphereGeometry(r, 4, 3), new THREE.MeshStandardMaterial({ color: 0x1a3a18 + Math.floor(rng() * 0x0a0a0a), roughness: 0.95, flatShading: true }));
                        bush.position.y = r * 0.4;
                        bush.scale.y = 0.5 + rng() * 0.3;
                        g.add(bush);
                    } else {
                        var rs = 0.5 + rng() * 1;
                        var rock = new THREE.Mesh(new THREE.DodecahedronGeometry(rs, 0), new THREE.MeshStandardMaterial({ color: 0x444444 + Math.floor(rng() * 0x222222), roughness: 0.92, flatShading: true }));
                        rock.position.y = rs * 0.3;
                        g.add(rock);
                    }
                } else if (biome === 'Volcanic') {
                    var rock = new THREE.Mesh(new THREE.DodecahedronGeometry(1 + rng() * 2, 0), new THREE.MeshStandardMaterial({ color: 0x1a1010, roughness: 0.95, flatShading: true, emissive: 0xff2200, emissiveIntensity: 0.04 + rng() * 0.04 }));
                    rock.position.y = rock.geometry.parameters.radius * 0.5;
                    g.add(rock);
                } else if (biome === 'Desert') {
                    if (treeType < 0.3) {
                        var h = 2 + rng() * 3;
                        var cactus = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.4, h, 6), new THREE.MeshStandardMaterial({ color: 0x3a6a30, roughness: 0.9, flatShading: true }));
                        cactus.position.y = h / 2;
                        g.add(cactus);
                    } else {
                        var r = 1 + rng() * 2;
                        var dune = new THREE.Mesh(new THREE.SphereGeometry(r, 6, 4), new THREE.MeshStandardMaterial({ color: 0xaa8844, roughness: 0.95, flatShading: true }));
                        dune.position.y = r * 0.2; dune.scale.y = 0.3;
                        g.add(dune);
                    }
                } else {
                    var h = 3 + rng() * 5;
                    var pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.4, h, 5), new THREE.MeshStandardMaterial({ color: 0x0a0a12, roughness: 0.8, emissive: 0x330066, emissiveIntensity: 0.08, flatShading: true }));
                    pillar.position.y = h / 2;
                    g.add(pillar);
                }

                g.position.set(x, 0, z);
                g.rotation.y = rng() * Math.PI * 2;
                scene.add(g);
                this.lanePaths.push(g);
            }
        }

        // Undergrowth
        for (var u = 0; u < 300; u++) {
            var x = (rng() - 0.5) * sx * 2, z = (rng() - 0.5) * sz * 2;
            if (this.isNearLane(x, z, laneCarveRadius - 2)) continue;
            if (riverDist(x, z) < riverCarveRadius - 1) continue;
            if (Math.sqrt((x+sx)*(x+sx)+(z+sz)*(z+sz)) < baseCarveRadius - 5) continue;
            if (Math.sqrt((x-sx)*(x-sx)+(z-sz)*(z-sz)) < baseCarveRadius - 5) continue;
            var grassColor = biome === 'Volcanic' ? 0x1a0a0a : biome === 'Desert' ? 0x887744 : biome === 'Abyss' ? 0x0a0812 : (0x0a2a0a + Math.floor(rng() * 0x0a1a0a));
            var gs = 0.3 + rng() * 0.5;
            var grass = new THREE.Mesh(new THREE.ConeGeometry(gs, gs * 2, 3), new THREE.MeshStandardMaterial({ color: grassColor, roughness: 0.95, flatShading: true, transparent: true, opacity: 0.6 }));
            grass.position.set(x, gs * 0.5, z);
            grass.rotation.y = rng() * Math.PI;
            scene.add(grass);
            this.lanePaths.push(grass);
        }

        // Brush patches
        var brushPatches = [
            { cx: -0.55, cz: 0.35, r: 0.12 }, { cx: -0.40, cz: 0.60, r: 0.10 },
            { cx: -0.35, cz: -0.55, r: 0.10 }, { cx: -0.60, cz: -0.25, r: 0.12 }, { cx: -0.70, cz: 0.10, r: 0.10 },
            { cx: 0.55, cz: -0.35, r: 0.12 }, { cx: 0.40, cz: -0.60, r: 0.10 },
            { cx: 0.35, cz: 0.55, r: 0.10 }, { cx: 0.60, cz: 0.25, r: 0.12 }, { cx: 0.70, cz: -0.10, r: 0.10 }
        ];
        brushPatches.forEach(function(patch) {
            var bx = patch.cx * sx, bz = patch.cz * sz;
            var br = patch.r * Math.max(sx, sz);
            var bush = new THREE.Mesh(new THREE.CircleGeometry(br, 12), new THREE.MeshStandardMaterial({ color: biome === 'Volcanic' ? 0x1a0a0a : biome === 'Abyss' ? 0x0a0012 : 0x0a2a0a, roughness: 0.95, transparent: true, opacity: 0.5 }));
            bush.rotation.x = -Math.PI / 2; bush.position.set(bx, 0.03, bz);
            scene.add(bush); self.lanePaths.push(bush);
            for (var j = 0; j < 10; j++) {
                var angle = rng() * Math.PI * 2, dist = rng() * br * 0.8;
                var s = 0.5 + rng() * 1.2;
                var bushObj = new THREE.Mesh(new THREE.SphereGeometry(s, 4, 3), new THREE.MeshStandardMaterial({ color: biome === 'Volcanic' ? 0x221108 : biome === 'Abyss' ? 0x0a0016 : (0x183818 + Math.floor(rng() * 0x0a0a0a)), roughness: 0.92, flatShading: true, transparent: true, opacity: 0.65 }));
                bushObj.position.set(bx + Math.cos(angle) * dist, s * 0.35, bz + Math.sin(angle) * dist);
                bushObj.scale.y = 0.45 + rng() * 0.2;
                scene.add(bushObj); self.lanePaths.push(bushObj);
            }
        });

        // Ambient motes
        var moteCount = 200, moteGeo = new THREE.BufferGeometry(), motePos = new Float32Array(moteCount * 3);
        for (var m = 0; m < moteCount; m++) { motePos[m*3] = (rng()-0.5)*sx*1.8; motePos[m*3+1] = 1+rng()*4; motePos[m*3+2] = (rng()-0.5)*sz*1.8; }
        moteGeo.setAttribute('position', new THREE.BufferAttribute(motePos, 3));
        var moteColor = biome === 'Volcanic' ? 0xff6600 : biome === 'Abyss' ? 0x6600cc : biome === 'Crystal' ? 0x00ddcc : 0x88ff44;
        scene.add(new THREE.Points(moteGeo, new THREE.PointsMaterial({ color: moteColor, size: 0.12, transparent: true, opacity: 0.3, blending: THREE.AdditiveBlending, sizeAttenuation: true })));
        this.lanePaths.push(scene.children[scene.children.length - 1]);
    },

    createTowersForLane(scene, laneKey, lane, sx, sz) {
        var wps = this.scaledWaypoints[laneKey];
        var total = wps.length;
        var explorerIndices = [2, Math.floor(total * 0.22), Math.floor(total * 0.40)];
        var hordeIndices = [total - 3, Math.ceil(total * 0.78), Math.ceil(total * 0.60)];
        var self = this;
        explorerIndices.forEach(function(idx, i) { var wp = wps[Math.min(idx, total-1)]; self.createTower(scene, wp.x, wp.z, 'explorer', lane.color, laneKey, i); });
        hordeIndices.forEach(function(idx, i) { var wp = wps[Math.min(idx, total-1)]; self.createTower(scene, wp.x, wp.z, 'horde', 0xff4488, laneKey, i+3); });
    },

    createTower(scene, x, z, faction, color, lane, index) {
        var group = new THREE.Group();
        var teamColor = faction === 'explorer' ? 0x00ccff : 0xff4444;
        group.add(new THREE.Mesh(new THREE.CylinderGeometry(1.5, 2, 1.5, 8), new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 })));
        group.children[0].position.y = 0.75;
        var col = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.8, 5, 8), new THREE.MeshStandardMaterial({ color: teamColor, emissive: teamColor, emissiveIntensity: 0.15, roughness: 0.4, metalness: 0.6 }));
        col.position.y = 4; group.add(col);
        var orb = new THREE.Mesh(new THREE.SphereGeometry(0.8, 12, 12), new THREE.MeshStandardMaterial({ color: teamColor, emissive: teamColor, emissiveIntensity: 0.5, roughness: 0.2, metalness: 0.8 }));
        orb.position.y = 7; group.add(orb);
        var rangeRing = new THREE.Mesh(new THREE.RingGeometry(14.5, 15, 24), new THREE.MeshBasicMaterial({ color: teamColor, side: THREE.DoubleSide, transparent: true, opacity: 0.06 }));
        rangeRing.rotation.x = -Math.PI / 2; rangeRing.position.y = 0.02; group.add(rangeRing);
        var hpBar = new THREE.Mesh(new THREE.PlaneGeometry(3, 0.3), new THREE.MeshBasicMaterial({ color: 0x00ff00 }));
        hpBar.position.y = 8.5; group.add(hpBar);
        var offset = faction === 'explorer' ? -3 : 3;
        group.position.set(x + offset, 0, z);
        scene.add(group);
        this.towers.push({ mesh: group, orb: orb, hpBar: hpBar, hp: 100, maxHp: 100, lane: lane, faction: faction, index: index, attackTimer: 0, target: null, attackRange: 15, attackDamage: 12, attackCooldown: 1.5 });
    },

    createThrones(scene, sx, sz) {
        this.thrones.explorer = this._buildThrone(scene, -sx, -sz, 'explorer', 0x00ccff);
        this.thrones.horde = this._buildThrone(scene, sx, sz, 'horde', 0xff4444);
    },

    _buildThrone(scene, x, z, faction, color) {
        var group = new THREE.Group();
        group.add(new THREE.Mesh(new THREE.CylinderGeometry(4, 5, 1.5, 16), new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 })));
        group.children[0].position.y = 0.75;
        var ring = new THREE.Mesh(new THREE.TorusGeometry(3, 0.3, 8, 24), new THREE.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: 0.3, roughness: 0.3, metalness: 0.7 }));
        ring.rotation.x = Math.PI / 2; ring.position.y = 1.8; group.add(ring);
        var crystal = new THREE.Mesh(new THREE.OctahedronGeometry(2, 0), new THREE.MeshStandardMaterial({ color: color, emissive: color, emissiveIntensity: 0.5, roughness: 0.1, metalness: 0.9, transparent: true, opacity: 0.9 }));
        crystal.position.y = 5; group.add(crystal);
        for (var i = 0; i < 4; i++) { var a = (i/4)*Math.PI*2; var pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.7, 6, 8), new THREE.MeshStandardMaterial({ color: 0x222233, roughness: 0.5, metalness: 0.5 })); pillar.position.set(Math.cos(a)*3, 3, Math.sin(a)*3); group.add(pillar); }
        var crown = new THREE.Mesh(new THREE.TorusGeometry(1.5, 0.2, 8, 16), new THREE.MeshStandardMaterial({ color: 0xffd700, emissive: 0xffa500, emissiveIntensity: 0.3, roughness: 0.2, metalness: 0.8 }));
        crown.rotation.x = Math.PI / 2; crown.position.y = 8; group.add(crown);
        var hpBar = new THREE.Mesh(new THREE.PlaneGeometry(5, 0.4), new THREE.MeshBasicMaterial({ color: 0x00ff00 }));
        hpBar.position.y = 10; group.add(hpBar);
        group.position.set(x, 0, z);
        scene.add(group);
        return { mesh: group, crystal: crystal, crown: crown, hpBar: hpBar, hp: 200, maxHp: 200 };
    },

    isNearLane(x, z, radius) {
        for (var key in this.scaledWaypoints) { var wps = this.scaledWaypoints[key]; for (var i = 0; i < wps.length; i++) { var dx = x - wps[i].x, dz = z - wps[i].z; if (dx*dx+dz*dz < radius*radius) return true; } }
        return false;
    },

    areTowersDown(lane, faction) {
        return this.towers.filter(function(t) { return t.lane === lane && t.faction === faction; }).every(function(t) { return t.hp <= 0; });
    },

    updateTowerVisuals(time) {
        this.towers.forEach(function(t) {
            if (t.hp <= 0) { if (t.mesh.visible) t.mesh.visible = false; return; }
            var ratio = t.hp / t.maxHp;
            t.hpBar.scale.x = ratio;
            t.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);
            if (t.orb) t.orb.material.emissiveIntensity = 0.3 + Math.sin(time * 3) * 0.2;
        });
        for (var faction in this.thrones) {
            var throne = this.thrones[faction];
            if (throne.hp <= 0) { if (throne.mesh.visible) throne.mesh.visible = false; continue; }
            var ratio = throne.hp / throne.maxHp;
            throne.hpBar.scale.x = ratio;
            throne.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);
            if (throne.crystal) { throne.crystal.rotation.y = time * 0.5; throne.crystal.position.y = 5 + Math.sin(time * 0.8) * 0.3; }
            if (throne.crown) throne.crown.rotation.z = time * 0.3;
        }
    },

    cleanup() {
        var disposeMesh = function(mesh) { if (mesh.geometry) mesh.geometry.dispose(); if (mesh.material) { if (Array.isArray(mesh.material)) mesh.material.forEach(function(m){m.dispose();}); else mesh.material.dispose(); } };
        var disposeGroup = function(group) { group.traverse(function(child) { disposeMesh(child); }); };
        for (var i = 0; i < this.lanePaths.length; i++) { var mesh = this.lanePaths[i]; if (mesh.parent) mesh.parent.remove(mesh); if (mesh.traverse) disposeGroup(mesh); else disposeMesh(mesh); }
        for (var i = 0; i < this.towers.length; i++) { var t = this.towers[i]; if (t.mesh.parent) t.mesh.parent.remove(t.mesh); disposeGroup(t.mesh); }
        for (var faction in this.thrones) { var throne = this.thrones[faction]; if (throne.mesh.parent) throne.mesh.parent.remove(throne.mesh); disposeGroup(throne.mesh); }
        this.towers = []; this.thrones = {}; this.lanePaths = []; this.lanes = []; this.scaledWaypoints = {}; this.riverPoints = []; this.runeSpots = []; this.roshanPit = null;
    }
};
