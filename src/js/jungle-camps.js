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
            // Idle bob + echo-reactive glow
            var echoGlow = 0.2;
            if (typeof EchoEngine !== 'undefined') {
                var ef = EchoEngine.getCurrentFrame();
                if (ef && ef.echoes && ef.echoes.L3) echoGlow = 0.2 + ef.echoes.L3.tension * 0.3;
            }
            if (camp.body && camp.body.material) camp.body.material.emissiveIntensity = echoGlow;
            if (camp.body) camp.body.position.y = (camp.size === 'medium' ? 1.2 : 0.8) + Math.sin(Date.now() * 0.002 + camp.x) * 0.1;
            // HP bar
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

    // Called by combat system when player attacks
    tryAttack(playerPos, damage) {
        // Check Titan first
        if (this.attackTitan(playerPos, damage)) return true;
        for (var i = 0; i < this.camps.length; i++) {
            var camp = this.camps[i];
            if (!camp.alive) continue;
            var dx = playerPos.x - camp.x, dz = playerPos.z - camp.z;
            var dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < 4) {
                camp.hp -= damage;
                // VFX hit spark
                if (typeof VFX !== 'undefined' && camp.mesh) VFX.burst(camp.mesh.position, 'hitSpark');
                if (camp.hp <= 0) {
                    camp.alive = false;
                    camp.respawnTimer = camp.respawnTime;
                    if (camp.mesh) camp.mesh.visible = false;
                    // Echo-scaled rewards: tension boosts gold/xp
                    var rewardMult = 1;
                    if (typeof EchoEngine !== 'undefined') {
                        var ef = EchoEngine.getCurrentFrame();
                        if (ef && ef.echoes && ef.echoes.L3) {
                            rewardMult = 1 + ef.echoes.L3.tension * 0.3; // Up to +30%
                        }
                    }
                    if (typeof PlayerStats !== 'undefined') {
                        PlayerStats.awardXp(Math.round(camp.xp * rewardMult));
                        PlayerStats.kills++;
                        PlayerStats.awardGold(Math.round(camp.gold * rewardMult), 'jungle');
                    }
                    // Death VFX
                    if (typeof VFX !== 'undefined' && camp.mesh) VFX.burst(camp.mesh.position, 'kill', { count: 10 });
                    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
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

    spawnTitan(scene, w) {
        if (this._titan && this._titan.alive) return;
        var titan = {
            x: 0, z: 0, // River center
            hp: 500, maxHp: 500,
            damage: 20, attackTimer: 0, attackCooldown: 1.2,
            alive: true, mesh: null, hpBar: null, body: null,
            gold: 200, xp: 150,
            respawnTime: 180, respawnTimer: 0
        };

        var g = new THREE.Group();
        // Massive body
        var bodyGeo = new THREE.IcosahedronGeometry(3, 1);
        var bodyMat = new THREE.MeshStandardMaterial({
            color: 0xff6600, emissive: 0xff4400, emissiveIntensity: 0.5,
            roughness: 0.3, metalness: 0.7, flatShading: true
        });
        var body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = 4;
        g.add(body);

        // Glowing eyes
        var eyeMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
        [-0.8, 0.8].forEach(function(offset) {
            var eye = new THREE.Mesh(new THREE.SphereGeometry(0.4, 6, 6), eyeMat);
            eye.position.set(offset, 4.5, 2.5);
            g.add(eye);
        });

        // Aura light
        var light = new THREE.PointLight(0xff4400, 3, 30);
        light.position.y = 5;
        g.add(light);

        // HP bar
        var hpGeo = new THREE.PlaneGeometry(6, 0.3);
        var hpBar = new THREE.Mesh(hpGeo, new THREE.MeshBasicMaterial({ color: 0xff0000 }));
        hpBar.position.y = 8;
        g.add(hpBar);

        // Crown/horns
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

        // VFX + announcement
        if (typeof VFX !== 'undefined') VFX.burst({ x: 0, y: 3, z: 0 }, 'bossKill');
        if (typeof VFX !== 'undefined') VFX.screenFlash('#ff6600', 0.5);
        if (typeof VFX !== 'undefined') VFX.emit({ x: 0, y: 2, z: 0 }, 'bossAura', 999);
        if (typeof HUD !== 'undefined') HUD.showToast('ECHO TITAN has awakened in the river!');
        if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();

        // Boss intro overlay
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;opacity:0;transition:opacity 0.5s;pointer-events:none;';
        overlay.innerHTML = '<div style="color:#ff6600;font-size:48px;font-family:monospace;text-transform:uppercase;letter-spacing:8px;text-shadow:0 0 30px #ff6600;">ECHO TITAN</div>';
        document.body.appendChild(overlay);
        requestAnimationFrame(function() { overlay.style.opacity = '1'; });
        setTimeout(function() { overlay.style.opacity = '0'; }, 1500);
        setTimeout(function() { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 2000);
    },

    updateTitan(delta, playerPos) {
        if (!this._titan) return;
        var titan = this._titan;

        if (!titan.alive) {
            titan.respawnTimer -= delta;
            if (titan.respawnTimer <= 0 && this._scene) {
                this.spawnTitan(this._scene, WORLDS[GameState.currentWorld]);
            }
            return;
        }

        if (!titan.mesh || !playerPos) return;

        // Idle animation — slow rotation + bob
        titan.body.rotation.y += delta * 0.3;
        titan.body.position.y = 4 + Math.sin(Date.now() * 0.001) * 0.5;

        // Echo-reactive glow
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3) {
                titan.body.material.emissiveIntensity = 0.5 + ef.echoes.L3.tension * 0.5;
            }
        }

        // HP bar
        var ratio = titan.hp / titan.maxHp;
        titan.hpBar.scale.x = ratio;
        titan.hpBar.material.color.setHex(ratio > 0.5 ? 0xff6600 : ratio > 0.25 ? 0xff0000 : 0x880000);

        // Damage player if close
        var dx = playerPos.x - titan.x;
        var dz = playerPos.z - titan.z;
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

    attackTitan(playerPos, damage) {
        if (!this._titan || !this._titan.alive) return false;
        var dx = playerPos.x - this._titan.x;
        var dz = playerPos.z - this._titan.z;
        if (Math.sqrt(dx * dx + dz * dz) > 8) return false;

        this._titan.hp -= damage;
        if (typeof VFX !== 'undefined') VFX.burst({ x: this._titan.x, y: 3, z: this._titan.z }, 'hitSpark');
        this.showDamageNumber(this._titan.mesh.position, damage);

        if (this._titan.hp <= 0) {
            this._titan.alive = false;
            this._titan.respawnTimer = this._titan.respawnTime;
            if (this._titan.mesh) this._titan.mesh.visible = false;

            // Massive rewards
            if (typeof PlayerStats !== 'undefined') {
                PlayerStats.awardXp(this._titan.xp);
                PlayerStats.awardGold(this._titan.gold, 'TITAN');
                PlayerStats.kills++;
            }

            // Epic VFX
            if (typeof VFX !== 'undefined') {
                VFX.burst({ x: 0, y: 3, z: 0 }, 'bossKill');
                VFX.burst({ x: 0, y: 5, z: 0 }, 'novaBlast');
                VFX.screenFlash('#ffd700', 0.5);
            }

            if (typeof HUD !== 'undefined') HUD.showToast('ECHO TITAN SLAIN! +' + this._titan.gold + ' gold, +' + this._titan.xp + ' XP');
            if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
            if (typeof ReplaySystem !== 'undefined') ReplaySystem.logEvent('boss_kill', { name: 'Echo Titan', isBoss: true });
            if (typeof GamepadControls !== 'undefined' && GamepadControls.rumble) GamepadControls.rumble(1.0, 0.5, 500);
        }
        return true;
    },

    showDamageNumber(pos, dmg) {
        if (typeof WorldCombat !== 'undefined' && WorldCombat.showDamageNumber) {
            WorldCombat.showDamageNumber(pos, dmg, '#ff6600');
        }
    },

    cleanup() {
        this.camps.forEach(function(c) {
            if (c.mesh && c.mesh.parent) c.mesh.parent.remove(c.mesh);
        });
        if (this._titan && this._titan.mesh && this._titan.mesh.parent) {
            this._titan.mesh.parent.remove(this._titan.mesh);
        }
        this._titan = null;
        this._titanSpawned = false;
        this.camps = [];
    }
};
