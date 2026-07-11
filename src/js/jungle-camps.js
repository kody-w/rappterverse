// Jungle Camps — Authentic neutral creep camps mirroring Dota 2 layout
// Small / Medium / Large / Ancient camps per jungle side + Echo Titan (Roshan-style river boss)

var CAMP_TYPES = {
    small:   { hp: 25, gold: 12, xp: 12, respawn: 60,  size: 0.6, neutrals: 2, color: 0x886644 },
    medium:  { hp: 50, gold: 22, xp: 22, respawn: 60,  size: 0.9, neutrals: 3, color: 0x996633 },
    large:   { hp: 80, gold: 35, xp: 35, respawn: 60,  size: 1.2, neutrals: 3, color: 0x774422 },
    ancient: { hp: 120, gold: 55, xp: 55, respawn: 90,  size: 1.5, neutrals: 4, color: 0x554433 }
};

var JungleCamps = {
    camps: [],
    _scene: null,

    init: function(scene, w) {
        this._scene = scene;
        this.camps = [];
        var sx = w.bounds.x * 0.9, sz = w.bounds.z * 0.9;

        // ── 14 camps mirroring Dota 2 layout ──
        var campDefs = [
            // Explorer safe-side jungle
            { x: -0.50, z: -0.78, type: 'small', label: 'Pull' },
            { x: -0.62, z: -0.50, type: 'medium', label: 'Medium' },
            { x: -0.42, z: -0.38, type: 'large', label: 'Hard' },
            { x: -0.78, z: -0.28, type: 'ancient', label: 'Ancient' },
            { x: -0.30, z: -0.22, type: 'small', label: 'Mid' },
            // Explorer off-side jungle
            { x: -0.72, z: 0.40, type: 'small', label: 'Offlane' },
            { x: -0.52, z: 0.58, type: 'medium', label: 'Offlane Med' },
            // Horde safe-side jungle
            { x: 0.50, z: 0.78, type: 'small', label: 'Pull' },
            { x: 0.62, z: 0.50, type: 'medium', label: 'Medium' },
            { x: 0.42, z: 0.38, type: 'large', label: 'Hard' },
            { x: 0.78, z: 0.28, type: 'ancient', label: 'Ancient' },
            { x: 0.30, z: 0.22, type: 'small', label: 'Mid' },
            // Horde off-side jungle
            { x: 0.72, z: -0.40, type: 'small', label: 'Offlane' },
            { x: 0.52, z: -0.58, type: 'medium', label: 'Offlane Med' }
        ];

        var self = this;
        campDefs.forEach(function(def) {
            var typeData = CAMP_TYPES[def.type];
            var camp = {
                x: def.x * sx, z: def.z * sz,
                type: def.type, label: def.label, size: typeData.size,
                gold: typeData.gold, xp: typeData.xp,
                alive: true, respawnTimer: 0, respawnTime: typeData.respawn,
                hp: typeData.hp, maxHp: typeData.hp,
                neutralCount: typeData.neutrals,
                mesh: null, hpBar: null, body: null
            };
            self._createCampMesh(scene, camp);
            self.camps.push(camp);
        });
    },

    _createCampMesh: function(scene, camp) {
        var g = new THREE.Group();
        var typeData = CAMP_TYPES[camp.type];
        var s = typeData.size;
        var rng = typeof seededRandom !== 'undefined' ? seededRandom('camp-' + camp.x + '-' + camp.z) : Math.random;
        var neutralCount = typeData.neutrals;
        var mainBody = null;

        for (var n = 0; n < neutralCount; n++) {
            var ns = s * (n === 0 ? 1 : 0.5 + rng() * 0.3);
            var angle = neutralCount > 1 ? (n / neutralCount) * Math.PI * 2 + rng() * 0.3 : 0;
            var dist = n === 0 ? 0 : 1 + rng() * 0.8;
            var creepColor = typeData.color + Math.floor(rng() * 0x111111);
            var creepGeo;
            if (camp.type === 'ancient') creepGeo = new THREE.OctahedronGeometry(ns, 0);
            else if (camp.type === 'large') creepGeo = new THREE.DodecahedronGeometry(ns, 0);
            else creepGeo = new THREE.SphereGeometry(ns, 6, 5);
            var creep = new THREE.Mesh(creepGeo, new THREE.MeshStandardMaterial({
                color: creepColor,
                emissive: camp.type === 'ancient' ? 0x443322 : 0x221100,
                emissiveIntensity: camp.type === 'ancient' ? 0.25 : 0.1,
                roughness: 0.8, flatShading: true
            }));
            creep.position.set(Math.cos(angle) * dist, ns * 0.8, Math.sin(angle) * dist);
            g.add(creep);
            if (n === 0) mainBody = creep;
            if (ns > 0.4) {
                var eMat = new THREE.MeshBasicMaterial({ color: 0xffaa00 });
                var eL = new THREE.Mesh(new THREE.SphereGeometry(ns * 0.12, 4, 4), eMat);
                eL.position.set(creep.position.x - ns * 0.3, creep.position.y + ns * 0.2, creep.position.z + ns * 0.7);
                g.add(eL);
                var eR = new THREE.Mesh(new THREE.SphereGeometry(ns * 0.12, 4, 4), eMat);
                eR.position.set(creep.position.x + ns * 0.3, creep.position.y + ns * 0.2, creep.position.z + ns * 0.7);
                g.add(eR);
            }
        }
        camp.body = mainBody;

        var circleRadius = s * 2;
        var circle = new THREE.Mesh(
            new THREE.CircleGeometry(circleRadius, 12),
            new THREE.MeshBasicMaterial({ color: 0x332211, transparent: true, opacity: 0.12, side: THREE.DoubleSide })
        );
        circle.rotation.x = -Math.PI / 2; circle.position.y = 0.01;
        g.add(circle);

        var hpBar = new THREE.Mesh(
            new THREE.PlaneGeometry(2, 0.2),
            new THREE.MeshBasicMaterial({ color: 0xffaa00 })
        );
        hpBar.position.y = s * 2 + 0.8;
        g.add(hpBar);

        g.position.set(camp.x, 0, camp.z);
        scene.add(g);
        camp.mesh = g;
        camp.hpBar = hpBar;
    },

    update: function(delta, playerPos) {
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
            if (camp.body) {
                var baseY = CAMP_TYPES[camp.type].size * 0.8;
                camp.body.position.y = baseY + Math.sin(Date.now() * 0.002 + camp.x * 3) * 0.08;
            }
            if (camp.hpBar) {
                var ratio = camp.hp / camp.maxHp;
                camp.hpBar.scale.x = ratio;
                camp.hpBar.material.color.setHex(ratio > 0.5 ? 0xffaa00 : 0xff4400);
            }
        });

        // Titan update
        this.updateTitan(delta, playerPos);

        // Spawn titan after wave 3 (if not already spawned)
        if (!this._titanSpawned && typeof WorldCombat !== 'undefined' && WorldCombat.waveNumber >= 3 && this._scene) {
            this.spawnTitan(this._scene, WORLDS[GameState.currentWorld]);
        }
    },

    tryAttack: function(playerPos, damage) {
        // Check Titan first
        if (this.attackTitan(playerPos, damage)) return true;
        var attackRange = 5;
        for (var i = 0; i < this.camps.length; i++) {
            var camp = this.camps[i];
            if (!camp.alive) continue;
            var dx = playerPos.x - camp.x, dz = playerPos.z - camp.z;
            var dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < attackRange) {
                camp.hp -= damage;
                if (typeof VFX !== 'undefined' && camp.mesh) VFX.burst(camp.mesh.position, 'hitSpark');
                if (camp.hp <= 0) {
                    camp.alive = false;
                    camp.respawnTimer = camp.respawnTime;
                    if (camp.mesh) camp.mesh.visible = false;
                    var rewardMult = 1;
                    if (typeof EchoEngine !== 'undefined') {
                        var ef = EchoEngine.getCurrentFrame();
                        if (ef && ef.echoes && ef.echoes.L3) rewardMult = 1 + ef.echoes.L3.tension * 0.3;
                    }
                    if (typeof PlayerStats !== 'undefined') {
                        PlayerStats.awardXp(Math.round(camp.xp * rewardMult));
                        PlayerStats.kills++;
                        PlayerStats.awardGold(Math.round(camp.gold * rewardMult), 'jungle');
                    }
                    if (typeof VFX !== 'undefined' && camp.mesh) VFX.burst(camp.mesh.position, 'kill', { count: 10 });
                    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
                    // Drop items from larger camps
                    if (typeof Inventory !== 'undefined' && camp.mesh) {
                        if (camp.type === 'large' || camp.type === 'ancient') {
                            Inventory.spawnDrop(camp.mesh.position.clone(), GameState.currentWorld, 0, i);
                        }
                    }
                }
                return true;
            }
        }
        return false;
    },

    // ── ECHO TITAN — Epic boss in the river (Roshan-style) ──
    _titan: null,
    _titanSpawnTimer: 0,
    _titanSpawned: false,

    spawnTitan: function(scene, w) {
        if (this._titan && this._titan.alive) return;
        var titan = {
            x: 0, z: 0,
            hp: 500, maxHp: 500,
            damage: 20, attackTimer: 0, attackCooldown: 1.2,
            alive: true, mesh: null, hpBar: null, body: null,
            gold: 200, xp: 150,
            respawnTime: 180, respawnTimer: 0
        };

        var g = new THREE.Group();
        var bodyGeo = new THREE.IcosahedronGeometry(3, 1);
        var bodyMat = new THREE.MeshStandardMaterial({ color: 0xff6600, emissive: 0xff4400, emissiveIntensity: 0.5, roughness: 0.3, metalness: 0.7, flatShading: true });
        var body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = 4;
        g.add(body);

        var eyeMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
        [-0.8, 0.8].forEach(function(offset) {
            var eye = new THREE.Mesh(new THREE.SphereGeometry(0.4, 6, 6), eyeMat);
            eye.position.set(offset, 4.5, 2.5);
            g.add(eye);
        });

        var light = new THREE.PointLight(0xff4400, 3, 30);
        light.position.y = 5;
        g.add(light);

        var hpGeo = new THREE.PlaneGeometry(6, 0.3);
        var hpBar = new THREE.Mesh(hpGeo, new THREE.MeshBasicMaterial({ color: 0xff0000 }));
        hpBar.position.y = 8;
        g.add(hpBar);

        var hornMat = new THREE.MeshStandardMaterial({ color: 0xffaa00, emissive: 0xff6600, emissiveIntensity: 0.3, flatShading: true });
        [-1.5, 1.5].forEach(function(offset) {
            var horn = new THREE.Mesh(new THREE.ConeGeometry(0.3, 2, 4), hornMat);
            horn.position.set(offset, 6.5, 0);
            horn.rotation.z = offset > 0 ? -0.3 : 0.3;
            g.add(horn);
        });

        g.position.set(0, 0, 0);
        scene.add(g);
        titan.mesh = g;
        titan.hpBar = hpBar;
        titan.body = body;
        this._titan = titan;
        this._titanSpawned = true;

        if (typeof VFX !== 'undefined') VFX.burst({ x: 0, y: 3, z: 0 }, 'bossKill');
        if (typeof VFX !== 'undefined') VFX.screenFlash('#ff6600', 0.5);
        if (typeof VFX !== 'undefined') VFX.emit({ x: 0, y: 2, z: 0 }, 'bossAura', 999);
        if (typeof HUD !== 'undefined') HUD.showToast('ECHO TITAN has awakened in the river!');
        if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();

        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;opacity:0;transition:opacity 0.5s;pointer-events:none;';
        overlay.innerHTML = '<div style="color:#ff6600;font-size:48px;font-family:monospace;text-transform:uppercase;letter-spacing:8px;text-shadow:0 0 30px #ff6600;">ECHO TITAN</div>';
        document.body.appendChild(overlay);
        requestAnimationFrame(function() { overlay.style.opacity = '1'; });
        setTimeout(function() { overlay.style.opacity = '0'; }, 1500);
        setTimeout(function() { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 2000);
    },

    updateTitan: function(delta, playerPos) {
        if (!this._titan) return;
        var titan = this._titan;
        if (!titan.alive) {
            titan.respawnTimer -= delta;
            if (titan.respawnTimer <= 0 && this._scene) this.spawnTitan(this._scene, WORLDS[GameState.currentWorld]);
            return;
        }
        if (!titan.mesh || !playerPos) return;
        titan.body.rotation.y += delta * 0.3;
        titan.body.position.y = 4 + Math.sin(Date.now() * 0.001) * 0.5;
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3) titan.body.material.emissiveIntensity = 0.5 + ef.echoes.L3.tension * 0.5;
        }
        var ratio = titan.hp / titan.maxHp;
        titan.hpBar.scale.x = ratio;
        titan.hpBar.material.color.setHex(ratio > 0.5 ? 0xff6600 : ratio > 0.25 ? 0xff0000 : 0x880000);
        var dx = playerPos.x - titan.x, dz = playerPos.z - titan.z;
        var dist = Math.sqrt(dx * dx + dz * dz);
        if (dist < 6) {
            titan.attackTimer -= delta;
            if (titan.attackTimer <= 0) {
                titan.attackTimer = titan.attackCooldown;
                if (typeof PlayerStats !== 'undefined' && !PlayerStats.dead) {
                    PlayerStats.takeDamage(titan.damage);
                    if (typeof VFX !== 'undefined') VFX.burst(playerPos, 'fire', { count: 6 });
                }
            }
        }
    },

    attackTitan: function(playerPos, damage) {
        if (!this._titan || !this._titan.alive) return false;
        var dx = playerPos.x - this._titan.x, dz = playerPos.z - this._titan.z;
        if (Math.sqrt(dx * dx + dz * dz) > 8) return false;
        this._titan.hp -= damage;
        if (typeof VFX !== 'undefined') VFX.burst({ x: this._titan.x, y: 3, z: this._titan.z }, 'hitSpark');
        this.showDamageNumber(this._titan.mesh.position, damage);
        if (this._titan.hp <= 0) {
            this._titan.alive = false;
            this._titan.respawnTimer = this._titan.respawnTime;
            if (this._titan.mesh) this._titan.mesh.visible = false;
            if (typeof PlayerStats !== 'undefined') { PlayerStats.awardXp(this._titan.xp); PlayerStats.awardGold(this._titan.gold, 'TITAN'); PlayerStats.kills++; }
            if (typeof VFX !== 'undefined') { VFX.burst({ x: 0, y: 3, z: 0 }, 'bossKill'); VFX.burst({ x: 0, y: 5, z: 0 }, 'novaBlast'); VFX.screenFlash('#ffd700', 0.5); }
            if (typeof HUD !== 'undefined') HUD.showToast('ECHO TITAN SLAIN! +' + this._titan.gold + ' Practice Gold, +' + this._titan.xp + ' Practice XP');
            if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
            if (typeof ReplaySystem !== 'undefined') ReplaySystem.logEvent('boss_kill', { name: 'Echo Titan', isBoss: true });
            if (typeof GamepadControls !== 'undefined' && GamepadControls.rumble) GamepadControls.rumble(1.0, 0.5, 500);
        }
        return true;
    },

    showDamageNumber: function(pos, dmg) {
        if (typeof WorldCombat !== 'undefined' && WorldCombat.showDamageNumber) WorldCombat.showDamageNumber(pos, dmg, '#ff6600');
    },

    cleanup: function() {
        this.camps.forEach(function(c) { if (c.mesh && c.mesh.parent) c.mesh.parent.remove(c.mesh); });
        if (this._titan && this._titan.mesh && this._titan.mesh.parent) this._titan.mesh.parent.remove(this._titan.mesh);
        this._titan = null;
        this._titanSpawned = false;
        this.camps = [];
    }
};
