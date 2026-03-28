// Jungle Camps — neutral creep camps between lanes that respawn
const JungleCamps = {
    camps: [],
    _scene: null,

    init(scene, w) {
        this._scene = scene;
        this.camps = [];
        var sx = w.bounds.x * 0.9, sz = w.bounds.z * 0.9;

        // 6 camps: 3 per side, positioned between lanes
        var campDefs = [
            // Explorer jungle (bottom-left quadrant)
            { x: -0.5, z: -0.4, size: 'small', gold: 15, xp: 15 },
            { x: -0.7, z: 0.1, size: 'medium', gold: 25, xp: 25 },
            { x: -0.3, z: -0.7, size: 'small', gold: 15, xp: 15 },
            // Horde jungle (top-right quadrant)
            { x: 0.5, z: 0.4, size: 'small', gold: 15, xp: 15 },
            { x: 0.7, z: -0.1, size: 'medium', gold: 25, xp: 25 },
            { x: 0.3, z: 0.7, size: 'small', gold: 15, xp: 15 },
        ];

        var self = this;
        campDefs.forEach(function(def) {
            var camp = {
                x: def.x * sx, z: def.z * sz,
                size: def.size, gold: def.gold, xp: def.xp,
                alive: true, respawnTimer: 0, respawnTime: 45,
                hp: def.size === 'medium' ? 60 : 30,
                maxHp: def.size === 'medium' ? 60 : 30,
                mesh: null, hpBar: null
            };
            self._createCampMesh(scene, camp);
            self.camps.push(camp);
        });
    },

    _createCampMesh(scene, camp) {
        var g = new THREE.Group();
        var s = camp.size === 'medium' ? 1.2 : 0.8;
        // Neutral creep body
        var body = new THREE.Mesh(
            new THREE.DodecahedronGeometry(s, 0),
            new THREE.MeshStandardMaterial({
                color: 0x886644, emissive: 0x443322, emissiveIntensity: 0.2,
                roughness: 0.8, flatShading: true
            })
        );
        body.position.y = s;
        g.add(body);
        // Eyes
        var eyeMat = new THREE.MeshBasicMaterial({ color: 0xffaa00 });
        var eyeL = new THREE.Mesh(new THREE.SphereGeometry(0.12, 4, 4), eyeMat);
        eyeL.position.set(-0.3, s + 0.2, s * 0.8);
        g.add(eyeL);
        var eyeR = new THREE.Mesh(new THREE.SphereGeometry(0.12, 4, 4), eyeMat);
        eyeR.position.set(0.3, s + 0.2, s * 0.8);
        g.add(eyeR);
        // Ground circle
        var circle = new THREE.Mesh(
            new THREE.CircleGeometry(s * 2, 12),
            new THREE.MeshBasicMaterial({ color: 0x443322, transparent: true, opacity: 0.15, side: THREE.DoubleSide })
        );
        circle.rotation.x = -Math.PI / 2;
        circle.position.y = 0.01;
        g.add(circle);
        // HP bar
        var hpGeo = new THREE.PlaneGeometry(2, 0.2);
        var hpBar = new THREE.Mesh(hpGeo, new THREE.MeshBasicMaterial({ color: 0xffaa00 }));
        hpBar.position.y = s * 2 + 0.5;
        g.add(hpBar);

        g.position.set(camp.x, 0, camp.z);
        scene.add(g);
        camp.mesh = g;
        camp.hpBar = hpBar;
        camp.body = body;
    },

    update(delta, playerPos) {
        var self = this;
        this.camps.forEach(function(camp) {
            if (!camp.alive) {
                camp.respawnTimer -= delta;
                if (camp.respawnTimer <= 0) {
                    camp.alive = true;
                    camp.hp = camp.maxHp;
                    if (camp.mesh) camp.mesh.visible = true;
                }
                return;
            }
            if (!camp.mesh) return;
            // Idle bob
            if (camp.body) camp.body.position.y = (camp.size === 'medium' ? 1.2 : 0.8) + Math.sin(Date.now() * 0.002 + camp.x) * 0.1;
            // HP bar
            if (camp.hpBar) {
                var ratio = camp.hp / camp.maxHp;
                camp.hpBar.scale.x = ratio;
                camp.hpBar.material.color.setHex(ratio > 0.5 ? 0xffaa00 : 0xff4400);
            }
        });
    },

    // Called by combat system when player attacks
    tryAttack(playerPos, damage) {
        for (var i = 0; i < this.camps.length; i++) {
            var camp = this.camps[i];
            if (!camp.alive) continue;
            var dx = playerPos.x - camp.x, dz = playerPos.z - camp.z;
            var dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < 4) {
                camp.hp -= damage;
                if (camp.hp <= 0) {
                    camp.alive = false;
                    camp.respawnTimer = camp.respawnTime;
                    if (camp.mesh) camp.mesh.visible = false;
                    if (typeof PlayerStats !== 'undefined') {
                        PlayerStats.awardXp(camp.xp);
                        PlayerStats.kills++;
                        PlayerStats.awardGold(camp.gold, 'jungle');
                    }
                    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
                }
                return true;
            }
        }
        return false;
    },

    cleanup() {
        this.camps.forEach(function(c) {
            if (c.mesh && c.mesh.parent) c.mesh.parent.remove(c.mesh);
        });
        this.camps = [];
    }
};
