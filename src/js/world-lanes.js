// World Lanes — DOTA-Style Lane Definitions, Towers, Thrones
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
    towers: [],       // { mesh, hp, maxHp, lane, faction, index, attackTimer, target }
    thrones: {},      // { explorer: {mesh,hp,maxHp}, horde: {mesh,hp,maxHp} }
    lanePaths: [],    // visual lane path meshes
    scaledWaypoints: {}, // waypoints scaled to world bounds

    init(scene, w) {
        this.towers = [];
        this.thrones = {};
        this.lanePaths = [];
        this.scaledWaypoints = {};

        // Scale waypoints from ±1 to world bounds
        const sx = w.bounds.x * 0.9;
        const sz = w.bounds.z * 0.9;

        for (const [laneKey, lane] of Object.entries(LANE_DEFS)) {
            this.scaledWaypoints[laneKey] = lane.waypoints.map(wp => ({
                x: wp.x * sx, z: wp.z * sz
            }));

            this.renderLanePath(scene, laneKey, lane);
            this.createTowersForLane(scene, laneKey, lane, sx, sz);
        }

        this.createThrones(scene, sx, sz);
    },

    renderLanePath(scene, laneKey, lane) {
        const wps = this.scaledWaypoints[laneKey];
        const points = wps.map(wp => new THREE.Vector3(wp.x, 0.05, wp.z));
        const geo = new THREE.BufferGeometry().setFromPoints(points);
        const mat = new THREE.LineBasicMaterial({
            color: lane.color, transparent: true, opacity: 0.25
        });
        const line = new THREE.Line(geo, mat);
        scene.add(line);
        this.lanePaths.push(line);

        // Choke point marker
        const choke = wps[lane.chokeIndex];
        if (choke) {
            const ringGeo = new THREE.RingGeometry(1.5, 2, 16);
            const ringMat = new THREE.MeshBasicMaterial({
                color: lane.color, side: THREE.DoubleSide,
                transparent: true, opacity: 0.2
            });
            const ring = new THREE.Mesh(ringGeo, ringMat);
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(choke.x, 0.06, choke.z);
            scene.add(ring);
            this.lanePaths.push(ring);
        }
    },

    createTowersForLane(scene, laneKey, lane, sx, sz) {
        const wps = this.scaledWaypoints[laneKey];
        const total = wps.length;

        // 3 towers per side: explorer side (indices 1,2,3), horde side (last 3)
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

        // Base
        const baseGeo = new THREE.CylinderGeometry(1.5, 2, 1.5, 8);
        const baseMat = new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 });
        group.add(new THREE.Mesh(baseGeo, baseMat));
        group.children[0].position.y = 0.75;

        // Column
        const colGeo = new THREE.CylinderGeometry(0.6, 0.8, 5, 8);
        const colMat = new THREE.MeshStandardMaterial({
            color: teamColor, emissive: teamColor, emissiveIntensity: 0.15,
            roughness: 0.4, metalness: 0.6
        });
        const col = new THREE.Mesh(colGeo, colMat);
        col.position.y = 4;
        group.add(col);

        // Top orb
        const orbGeo = new THREE.SphereGeometry(0.8, 12, 12);
        const orbMat = new THREE.MeshStandardMaterial({
            color: teamColor, emissive: teamColor, emissiveIntensity: 0.5,
            roughness: 0.2, metalness: 0.8
        });
        const orb = new THREE.Mesh(orbGeo, orbMat);
        orb.position.y = 7;
        group.add(orb);

        // Attack range ring
        const rangeGeo = new THREE.RingGeometry(14.5, 15, 24);
        const rangeMat = new THREE.MeshBasicMaterial({
            color: teamColor, side: THREE.DoubleSide, transparent: true, opacity: 0.06
        });
        const rangeRing = new THREE.Mesh(rangeGeo, rangeMat);
        rangeRing.rotation.x = -Math.PI / 2;
        rangeRing.position.y = 0.02;
        group.add(rangeRing);

        // HP bar
        const hpGeo = new THREE.PlaneGeometry(3, 0.3);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = 8.5;
        hpBar.rotation.x = 0;
        group.add(hpBar);

        group.position.set(x + (faction === 'explorer' ? -2 : 2), 0, z);
        scene.add(group);

        this.towers.push({
            mesh: group, orb, hpBar,
            hp: 100, maxHp: 100,
            lane, faction, index,
            attackTimer: 0, target: null,
            attackRange: 15, attackDamage: 12, attackCooldown: 1.5
        });
    },

    createThrones(scene, sx, sz) {
        // Explorer throne at team A spawn (-1,-1 scaled)
        this.thrones.explorer = this._buildThrone(scene, -sx, -sz, 'explorer', 0x00ccff);
        // Horde throne at team B spawn (1,1 scaled)
        this.thrones.horde = this._buildThrone(scene, sx, sz, 'horde', 0xff4444);
    },

    _buildThrone(scene, x, z, faction, color) {
        const group = new THREE.Group();

        // Base platform
        const baseGeo = new THREE.CylinderGeometry(4, 5, 1.5, 16);
        const baseMat = new THREE.MeshStandardMaterial({ color: 0x333344, roughness: 0.6, metalness: 0.4 });
        group.add(new THREE.Mesh(baseGeo, baseMat));
        group.children[0].position.y = 0.75;

        // Ring
        const ringGeo = new THREE.TorusGeometry(3, 0.3, 8, 24);
        const ringMat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 0.3,
            roughness: 0.3, metalness: 0.7
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = Math.PI / 2;
        ring.position.y = 1.8;
        group.add(ring);

        // Crystal core
        const crystalGeo = new THREE.OctahedronGeometry(2, 0);
        const crystalMat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: 0.5,
            roughness: 0.1, metalness: 0.9, transparent: true, opacity: 0.9
        });
        const crystal = new THREE.Mesh(crystalGeo, crystalMat);
        crystal.position.y = 5;
        group.add(crystal);

        // 4 pillar supports
        for (let i = 0; i < 4; i++) {
            const a = (i / 4) * Math.PI * 2;
            const pillarGeo = new THREE.CylinderGeometry(0.5, 0.7, 6, 8);
            const pillarMat = new THREE.MeshStandardMaterial({ color: 0x222233, roughness: 0.5, metalness: 0.5 });
            const pillar = new THREE.Mesh(pillarGeo, pillarMat);
            pillar.position.set(Math.cos(a) * 3, 3, Math.sin(a) * 3);
            group.add(pillar);
        }

        // Crown
        const crownGeo = new THREE.TorusGeometry(1.5, 0.2, 8, 16);
        const crownMat = new THREE.MeshStandardMaterial({
            color: 0xffd700, emissive: 0xffa500, emissiveIntensity: 0.3,
            roughness: 0.2, metalness: 0.8
        });
        const crown = new THREE.Mesh(crownGeo, crownMat);
        crown.rotation.x = Math.PI / 2;
        crown.position.y = 8;
        group.add(crown);

        // HP bar
        const hpGeo = new THREE.PlaneGeometry(5, 0.4);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = 10;
        group.add(hpBar);

        group.position.set(x, 0, z);
        scene.add(group);

        return { mesh: group, crystal, crown, hpBar, hp: 200, maxHp: 200 };
    },

    // Check if position is near any lane path (for terrain object exclusion)
    isNearLane(x, z, radius) {
        for (const wps of Object.values(this.scaledWaypoints)) {
            for (const wp of wps) {
                const dx = x - wp.x, dz = z - wp.z;
                if (dx * dx + dz * dz < radius * radius) return true;
            }
        }
        return false;
    },

    // Check if all towers in a lane for a faction are destroyed
    areTowersDown(lane, faction) {
        return this.towers.filter(t => t.lane === lane && t.faction === faction).every(t => t.hp <= 0);
    },

    // Update tower HP bars
    updateTowerVisuals(time) {
        this.towers.forEach(t => {
            if (t.hp <= 0) {
                if (t.mesh.visible) {
                    t.mesh.visible = false;
                    // Show destruction particles
                }
                return;
            }
            // HP bar scale
            const ratio = t.hp / t.maxHp;
            t.hpBar.scale.x = ratio;
            t.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);
            // Orb pulse
            if (t.orb) t.orb.material.emissiveIntensity = 0.3 + Math.sin(time * 3) * 0.2;
        });

        // Throne visuals
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
            if (throne.crown) {
                throne.crown.rotation.z = time * 0.3;
            }
        }
    },

    cleanup() {
        this.towers = [];
        this.thrones = {};
        this.lanePaths = [];
        this.scaledWaypoints = {};
    }
};
