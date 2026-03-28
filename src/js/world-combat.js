// World Combat — Creep Waves, Tower Attacks, Momentum, Player Combat
const COMBAT_CONFIG = {
    waveInterval: 25000,
    creepsPerWave: 3,
    creepSpeed: 10,
    creepBaseHp: 30,
    creepDamage: 8,
    clashRange: 5,
    clashCooldown: 1.5,
    towerRange: 40,
    towerDamage: 12,
    towerCooldown: 1.5,
    playerDamage: 20,
    playerRange: 8,
    playerCooldown: 1,
    momentumDecay: 0.1,
    momentumPerKill: 3
};

const WorldCombat = {
    creeps: [],               // { mesh, hp, maxHp, faction, lane, waypointIdx, speed, attackTimer, alive }
    projectiles: [],          // { mesh, target, speed, damage }
    momentum: 50,             // 0=horde winning, 100=explorer winning
    waveNumber: 0,
    lastWaveTime: 0,
    playerAttackTimer: 0,
    active: false,
    scene: null,
    bossActive: false,
    boss: null,

    init(scene) {
        this.scene = scene;
        this.creeps = [];
        this.projectiles = [];
        this.momentum = 50;
        this.waveNumber = 0;
        this.lastWaveTime = performance.now();
        this.playerAttackTimer = 0;
        this.active = true;
        this.bossActive = false;
        this.boss = null;
    },

    update(delta, time, playerPos) {
        if (!this.active) return;

        const now = performance.now();

        // Spawn waves
        if (now - this.lastWaveTime >= COMBAT_CONFIG.waveInterval) {
            this.lastWaveTime = now;
            this.waveNumber++;
            this.spawnWave();
        }

        // Move creeps
        this.updateCreeps(delta);

        // Tower attacks
        this.updateTowers(delta);

        // Projectiles
        this.updateProjectiles(delta);

        // Status effects tick
        if (typeof StatusEffects !== 'undefined') {
            const events = StatusEffects.updateAll(delta, time);
            for (const evt of events) {
                if (evt.killed) {
                    const creep = this.creeps.find(c => c.mesh === evt.mob || c.mesh === evt.mob.parent);
                    if (creep && creep.alive) {
                        creep.alive = false;
                        if (typeof ComboSystem !== 'undefined') ComboSystem.registerKill();
                        if (typeof PlayerStats !== 'undefined') {
                            PlayerStats.awardXp(creep.isBoss ? 50 : 10);
                            PlayerStats.kills++;
                            PlayerStats.awardGold(creep.isBoss ? 50 : 8, 'creep');
                        }
                        if (typeof Inventory !== 'undefined') Inventory.spawnDrop(creep.mesh.position.clone(), GameState.currentWorld, this.waveNumber, 0);
                        if (creep.isBoss) {
                            this.bossActive = false; this.boss = null;
                            this.momentum = Math.min(100, this.momentum + 20);
                            if (typeof HUD !== 'undefined') HUD.showToast('BOSS DEFEATED by DoT!');
                        } else {
                            this.momentum = Math.min(100, this.momentum + COMBAT_CONFIG.momentumPerKill);
                        }
                    }
                }
            }
        }

        // Momentum decay toward 50
        if (this.momentum > 50) this.momentum -= COMBAT_CONFIG.momentumDecay * delta;
        if (this.momentum < 50) this.momentum += COMBAT_CONFIG.momentumDecay * delta;
        this.momentum = Math.max(0, Math.min(100, this.momentum));

        // Player attack cooldown
        if (this.playerAttackTimer > 0) this.playerAttackTimer -= delta;

        // Cleanup dead creeps
        this.creeps = this.creeps.filter(c => {
            if (!c.alive) {
                if (c.mesh.parent) c.mesh.parent.remove(c.mesh);
                return false;
            }
            return true;
        });

        // Cleanup finished projectiles
        this.projectiles = this.projectiles.filter(p => {
            if (!p.alive) {
                if (p.mesh.parent) p.mesh.parent.remove(p.mesh);
                return false;
            }
            return true;
        });

        // Update HUD
        this.updateCombatHUD();
    },

    spawnWave() {
        const scaleFactor = 1 + (this.waveNumber * 0.08);
        const isSiegeWave = this.waveNumber % 5 === 0;

        for (const [laneKey, lane] of Object.entries(LANE_DEFS)) {
            const wps = WorldLanes.scaledWaypoints[laneKey];
            if (!wps || wps.length < 2) continue;

            // Mix: 2 melee + 1 ranged per wave, +1 siege every 5th wave
            for (let i = 0; i < 2; i++) {
                this.createCreep('explorer', laneKey, 0, scaleFactor, i, 'melee');
                this.createCreep('horde', laneKey, wps.length - 1, scaleFactor, i, 'melee');
            }
            this.createCreep('explorer', laneKey, 0, scaleFactor, 2, 'ranged');
            this.createCreep('horde', laneKey, wps.length - 1, scaleFactor, 2, 'ranged');
            if (isSiegeWave) {
                this.createCreep('explorer', laneKey, 0, scaleFactor, 3, 'siege');
                this.createCreep('horde', laneKey, wps.length - 1, scaleFactor, 3, 'siege');
            }
        }

        var echoMsg = 'Wave ' + this.waveNumber + (isSiegeWave ? ' [SIEGE WAVE]' : '');
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes && ef.echoes.L3 && ef.echoes.L3.tension > 0.3) echoMsg += ' [HIGH TENSION]';
        }
        if (typeof HUD !== 'undefined') HUD.showToast(echoMsg);

        // Boss every 5 waves
        if (this.waveNumber % 5 === 0 && !this.bossActive) {
            this.spawnBoss();
        }
    },

    createCreep(faction, lane, startIdx, scale, offset, creepType) {
        creepType = creepType || 'melee';
        const isExplorer = faction === 'explorer';
        const baseColor = isExplorer ? 0x00ff88 : 0xff4488;
        // Type-specific stats
        var hpMult = 1, dmgMult = 1, speedMult = 1, size = 0.4, color = baseColor;
        if (creepType === 'melee') { hpMult = 1.2; size = 0.45; }
        else if (creepType === 'ranged') { hpMult = 0.6; dmgMult = 1.3; speedMult = 0.9; size = 0.3; color = isExplorer ? 0x44ffaa : 0xff88aa; }
        else if (creepType === 'siege') { hpMult = 2; dmgMult = 2.5; speedMult = 0.6; size = 0.6; color = isExplorer ? 0x00cc66 : 0xcc3366; }
        const hp = Math.floor(COMBAT_CONFIG.creepBaseHp * scale * hpMult);

        const group = new THREE.Group();

        // Body — shape varies by type
        var bodyGeo;
        if (creepType === 'melee') bodyGeo = new THREE.SphereGeometry(size, 8, 8);
        else if (creepType === 'ranged') bodyGeo = new THREE.OctahedronGeometry(size, 0);
        else bodyGeo = new THREE.BoxGeometry(size * 1.5, size * 1.2, size * 1.5);
        const bodyMat = new THREE.MeshStandardMaterial({
            color, emissive: color, emissiveIntensity: creepType === 'siege' ? 0.4 : 0.3, roughness: 0.4
        });
        group.add(new THREE.Mesh(bodyGeo, bodyMat));
        group.children[0].position.y = size + 0.1;

        // Eyes
        const eyeGeo = new THREE.SphereGeometry(0.08, 6, 6);
        const eyeMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
        const eyeL = new THREE.Mesh(eyeGeo, eyeMat);
        eyeL.position.set(-0.15, size + 0.2, size * 0.8);
        group.add(eyeL);
        const eyeR = new THREE.Mesh(eyeGeo, eyeMat);
        eyeR.position.set(0.15, size + 0.2, size * 0.8);
        group.add(eyeR);

        // HP bar
        const hpGeo = new THREE.PlaneGeometry(1, 0.12);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0x00ff00 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = 1.2;
        group.add(hpBar);

        const wps = WorldLanes.scaledWaypoints[lane];
        const start = wps[startIdx];
        // Offset creeps slightly so they don't stack
        const rng = seededRandom('wave-' + this.waveNumber + '-' + lane + '-' + faction);
        group.position.set(
            start.x + (rng() - 0.5) * 2,
            0,
            start.z + (rng() - 0.5) * 2 - offset * 1.5 * (isExplorer ? 1 : -1)
        );

        this.scene.add(group);
        this.creeps.push({
            mesh: group, hpBar,
            hp, maxHp: hp,
            faction, lane, creepType: creepType,
            waypointIdx: startIdx,
            direction: isExplorer ? 1 : -1,
            speed: (COMBAT_CONFIG.creepSpeed + rng() * 0.5) * speedMult,
            dmgMult: dmgMult,
            attackTimer: 0,
            alive: true
        });
    },

    spawnBoss() {
        const laneKeys = Object.keys(LANE_DEFS);
        const rng = seededRandom('boss-' + this.waveNumber);
        const laneKey = laneKeys[Math.floor(rng() * laneKeys.length)];
        const wps = WorldLanes.scaledWaypoints[laneKey];
        if (!wps || wps.length < 2) return;

        const isVoidColossus = (this.waveNumber / 5) % 2 === 1;
        const bossName = isVoidColossus ? 'Void Colossus' : 'Quantum Overseer';
        const bossColor = isVoidColossus ? 0x6600aa : 0x00ffcc;
        const bossHp = isVoidColossus ? 200 : 150;
        const bossSpeed = isVoidColossus ? 4 : 8;
        const bossDamage = isVoidColossus ? 25 : 15;

        const group = new THREE.Group();

        // Boss body
        let bodyGeo;
        if (isVoidColossus) {
            bodyGeo = new THREE.SphereGeometry(2, 12, 12);
        } else {
            bodyGeo = new THREE.OctahedronGeometry(1.5, 0);
        }
        const bodyMat = new THREE.MeshStandardMaterial({
            color: bossColor, emissive: bossColor, emissiveIntensity: 0.5,
            roughness: 0.3, metalness: 0.6
        });
        const body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = isVoidColossus ? 2.5 : 2;
        group.add(body);

        // Boss point light
        const lightColor = isVoidColossus ? 0x8800dd : 0x00ffcc;
        const bossLight = new THREE.PointLight(lightColor, 2, 20);
        bossLight.position.y = 3;
        group.add(bossLight);

        // Boss HP bar (wider)
        const hpGeo = new THREE.PlaneGeometry(3, 0.2);
        const hpMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
        const hpBar = new THREE.Mesh(hpGeo, hpMat);
        hpBar.position.y = isVoidColossus ? 5 : 4;
        group.add(hpBar);

        // Spawn at end of lane (horde side)
        const startIdx = wps.length - 1;
        const start = wps[startIdx];
        group.position.set(start.x, 0, start.z);

        this.scene.add(group);

        const creep = {
            mesh: group, hpBar,
            hp: bossHp, maxHp: bossHp,
            faction: 'horde', lane: laneKey,
            waypointIdx: startIdx,
            direction: -1,
            speed: bossSpeed,
            damage: bossDamage,
            attackTimer: 0,
            alive: true,
            isBoss: true,
            bossName: bossName
        };
        this.creeps.push(creep);
        this.bossActive = true;
        this.boss = creep;

        // Boss intro overlay
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;opacity:0;transition:opacity 0.5s;pointer-events:none;';
        overlay.innerHTML = `<div style="color:${isVoidColossus ? '#aa44ff' : '#00ffcc'};font-size:48px;font-family:monospace;text-transform:uppercase;letter-spacing:8px;text-shadow:0 0 30px currentColor;">${bossName}</div>`;
        document.body.appendChild(overlay);
        requestAnimationFrame(() => { overlay.style.opacity = '1'; });
        setTimeout(() => { overlay.style.opacity = '0'; }, 1500);
        setTimeout(() => { if (overlay.parentNode) overlay.parentNode.removeChild(overlay); }, 2000);

        if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
    },

    updateCreeps(delta) {
        for (const creep of this.creeps) {
            if (!creep.alive) continue;

            const wps = WorldLanes.scaledWaypoints[creep.lane];
            if (!wps) continue;

            // Find nearby enemy creep
            let enemy = null;
            let enemyDist = COMBAT_CONFIG.clashRange;

            for (const other of this.creeps) {
                if (!other.alive || other.faction === creep.faction) continue;
                const dx = creep.mesh.position.x - other.mesh.position.x;
                const dz = creep.mesh.position.z - other.mesh.position.z;
                const dist = Math.sqrt(dx * dx + dz * dz);
                if (dist < enemyDist) {
                    enemy = other;
                    enemyDist = dist;
                }
            }

            if (enemy) {
                // Fight
                creep.attackTimer -= delta;
                if (creep.attackTimer <= 0) {
                    creep.attackTimer = COMBAT_CONFIG.clashCooldown;
                    enemy.hp -= COMBAT_CONFIG.creepDamage;
                    if (enemy.hp <= 0) {
                        enemy.alive = false;
                        // Boss death
                        if (enemy.isBoss) {
                            this.bossActive = false;
                            this.boss = null;
                            this.momentum = Math.min(100, this.momentum + 20);
                            if (typeof HUD !== 'undefined') HUD.showToast('BOSS DEFEATED!');
                        } else if (enemy.faction === 'horde') {
                            this.momentum = Math.min(100, this.momentum + COMBAT_CONFIG.momentumPerKill);
                        } else {
                            this.momentum = Math.max(0, this.momentum - COMBAT_CONFIG.momentumPerKill);
                        }
                    }
                }
                // Face enemy
                const angle = Math.atan2(
                    enemy.mesh.position.x - creep.mesh.position.x,
                    enemy.mesh.position.z - creep.mesh.position.z
                );
                creep.mesh.rotation.y = angle;
            } else {
                // March along waypoints
                const nextIdx = creep.waypointIdx + creep.direction;
                if (nextIdx < 0 || nextIdx >= wps.length) {
                    // Reached enemy throne — attack it
                    const targetThrone = creep.faction === 'explorer' ? 'horde' : 'explorer';
                    const throne = WorldLanes.thrones[targetThrone];
                    if (throne && throne.hp > 0) {
                        creep.attackTimer -= delta;
                        if (creep.attackTimer <= 0) {
                            creep.attackTimer = COMBAT_CONFIG.clashCooldown;
                            throne.hp -= COMBAT_CONFIG.creepDamage;
                            if (throne.hp <= 0) {
                                const winner = creep.faction === 'explorer' ? 'Explorers' : 'Horde';
                                this._triggerVictory(winner === 'Explorers' ? 'VICTORY' : 'DEFEAT', winner);
                            }
                        }
                    }
                    continue;
                }

                const target = wps[nextIdx];
                const dx = target.x - creep.mesh.position.x;
                const dz = target.z - creep.mesh.position.z;
                const dist = Math.sqrt(dx * dx + dz * dz);

                if (dist < 1) {
                    creep.waypointIdx = nextIdx;
                } else {
                    let spd = creep.speed;
                    if (typeof StatusEffects !== 'undefined') spd *= StatusEffects.getSpeedMultiplier(creep.mesh);
                    const mx = (dx / dist) * spd * delta;
                    const mz = (dz / dist) * spd * delta;
                    creep.mesh.position.x += mx;
                    creep.mesh.position.z += mz;
                    creep.mesh.rotation.y = Math.atan2(dx, dz);
                }
            }

            // Update HP bar
            const ratio = Math.max(0, creep.hp / creep.maxHp);
            creep.hpBar.scale.x = ratio;
            creep.hpBar.material.color.setHex(ratio > 0.5 ? 0x00ff00 : ratio > 0.25 ? 0xffaa00 : 0xff0000);

            // Bob animation
            creep.mesh.children[0].position.y = 0.5 + Math.sin(performance.now() * 0.005 + creep.mesh.position.x) * 0.1;
        }
    },

    updateTowers(delta) {
        for (const tower of WorldLanes.towers) {
            if (tower.hp <= 0) continue;

            tower.attackTimer -= delta;
            if (tower.attackTimer > 0) continue;

            // Find nearest enemy creep in range
            let target = null;
            let targetDist = tower.attackRange;
            const tPos = tower.mesh.position;

            for (const creep of this.creeps) {
                if (!creep.alive) continue;
                // Explorer towers attack horde, horde towers attack explorers
                if (creep.faction === tower.faction) continue;

                const dx = tPos.x - creep.mesh.position.x;
                const dz = tPos.z - creep.mesh.position.z;
                const dist = Math.sqrt(dx * dx + dz * dz);
                if (dist < targetDist) {
                    target = creep;
                    targetDist = dist;
                }
            }

            // Also target player if near horde tower
            if (tower.faction === 'horde' && WorldMode.player) {
                const pp = WorldMode.player.mesh.position;
                const dx = tPos.x - pp.x;
                const dz = tPos.z - pp.z;
                const dist = Math.sqrt(dx * dx + dz * dz);
                if (dist < targetDist) {
                    // Don't actually damage player directly, just shoot near them as warning
                }
            }

            if (target) {
                tower.attackTimer = tower.attackCooldown;
                this.fireProjectile(tPos.clone().setY(7), target, tower.attackDamage,
                    tower.faction === 'explorer' ? 0x00ccff : 0xff4444);
            }
        }
    },

    fireProjectile(from, target, damage, color) {
        const geo = new THREE.SphereGeometry(0.2, 6, 6);
        const mat = new THREE.MeshBasicMaterial({ color });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.copy(from);
        this.scene.add(mesh);

        this.projectiles.push({
            mesh, target, damage, color,
            speed: 25, alive: true
        });
    },

    updateProjectiles(delta) {
        for (const proj of this.projectiles) {
            if (!proj.alive) continue;

            if (!proj.target || !proj.target.alive) {
                proj.alive = false;
                continue;
            }

            const targetPos = proj.target.mesh.position;
            const dx = targetPos.x - proj.mesh.position.x;
            const dy = (targetPos.y + 0.5) - proj.mesh.position.y;
            const dz = targetPos.z - proj.mesh.position.z;
            const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);

            if (dist < 1) {
                // Hit
                proj.target.hp -= proj.damage;
                if (proj.target.hp <= 0) {
                    proj.target.alive = false;
                    if (proj.target.isBoss) {
                        this.bossActive = false;
                        this.boss = null;
                        this.momentum = Math.min(100, this.momentum + 20);
                        if (typeof HUD !== 'undefined') HUD.showToast('BOSS DEFEATED!');
                    } else if (proj.target.faction === 'horde') {
                        this.momentum = Math.min(100, this.momentum + 1);
                    } else {
                        this.momentum = Math.max(0, this.momentum - 1);
                    }
                }
                proj.alive = false;
            } else {
                const mx = (dx / dist) * proj.speed * delta;
                const my = (dy / dist) * proj.speed * delta;
                const mz = (dz / dist) * proj.speed * delta;
                proj.mesh.position.x += mx;
                proj.mesh.position.y += my;
                proj.mesh.position.z += mz;
            }
        }
    },

    // Player attacks nearest horde creep (SPACE key)
    playerAttack(playerPos) {
        if (this.playerAttackTimer > 0) return false;

        let nearest = null;
        let nearDist = COMBAT_CONFIG.playerRange;

        for (const creep of this.creeps) {
            if (!creep.alive || creep.faction !== 'horde') continue;
            const dx = playerPos.x - creep.mesh.position.x;
            const dz = playerPos.z - creep.mesh.position.z;
            const dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < nearDist) {
                nearest = creep;
                nearDist = dist;
            }
        }

        // Also check towers
        if (!nearest) {
            for (const tower of WorldLanes.towers) {
                if (tower.hp <= 0 || tower.faction !== 'horde') continue;
                const dx = playerPos.x - tower.mesh.position.x;
                const dz = playerPos.z - tower.mesh.position.z;
                const dist = Math.sqrt(dx * dx + dz * dz);
                if (dist < nearDist) {
                    nearest = tower;
                    nearDist = dist;
                }
            }
        }

        // Also check enemy hero
        if (typeof EnemyHero !== 'undefined' && EnemyHero.active && EnemyHero.state && EnemyHero.state.alive && EnemyHero.mesh) {
            const dx = playerPos.x - EnemyHero.mesh.position.x;
            const dz = playerPos.z - EnemyHero.mesh.position.z;
            const dist = Math.sqrt(dx * dx + dz * dz);
            if (dist < nearDist) {
                nearest = 'enemyHero';
                nearDist = dist;
            }
        }

        if (!nearest) return false;

        this.playerAttackTimer = COMBAT_CONFIG.playerCooldown;
        const dmg = (typeof PlayerStats !== 'undefined') ? PlayerStats.getDamage() : COMBAT_CONFIG.playerDamage;
        const comboMult = (typeof ComboSystem !== 'undefined') ? ComboSystem.getMultiplier() : 1;

        // Check if target is enemy hero
        if (nearest === 'enemyHero') {
            if (typeof EnemyHero !== 'undefined') {
                EnemyHero.damage(dmg * comboMult);
                const element = (typeof Equipment !== 'undefined') ? Equipment.getEquippedElement() : null;
                if (element && EnemyHero.mesh) StatusEffects.applyEffect(EnemyHero.mesh, element);
            }
            return true;
        }

        nearest.hp -= dmg * comboMult;
        this.showDamageNumber(nearest.mesh.position, dmg * comboMult, '#ff4444');

        // Apply status effect from equipped weapon
        if (typeof StatusEffects !== 'undefined' && typeof Equipment !== 'undefined') {
            const element = Equipment.getEquippedElement();
            if (element && nearest.mesh) StatusEffects.applyEffect(nearest.mesh, element);
        }

        if (nearest.hp <= 0) {
            nearest.alive = false;
            if (typeof ComboSystem !== 'undefined') ComboSystem.registerKill();
            if (typeof PlayerStats !== 'undefined') {
                PlayerStats.awardXp(nearest.isBoss ? 50 : 10);
                PlayerStats.kills++;
                var _goldAmt = nearest.isBoss ? 50 : (8 + Math.floor(Math.random() * 5));
                PlayerStats.awardGold(_goldAmt, nearest.isBoss ? 'boss' : 'creep');
                if (typeof HUD !== 'undefined' && HUD.showKill) HUD.showKill(nearest.isBoss ? 'BOSS' : 'Creep', _goldAmt);
                if (typeof HUD !== 'undefined' && HUD.showKill) HUD.showKill('Player', nearest.isBoss ? 'BOSS' : 'Creep', _goldAmt);
            }
            if (typeof Inventory !== 'undefined' && nearest.mesh) {
                Inventory.spawnDrop(nearest.mesh.position.clone(), GameState.currentWorld, this.waveNumber, this.creeps.indexOf(nearest));
            }
            if (nearest.isBoss) {
                this.bossActive = false;
                this.boss = null;
                this.momentum = Math.min(100, this.momentum + 20);
                if (typeof HUD !== 'undefined') HUD.showToast('BOSS DEFEATED! +50 gold');
            } else {
                this.momentum = Math.min(100, this.momentum + COMBAT_CONFIG.momentumPerKill * 2);
            }
        }

        // Visual flash
        this.createAttackFlash(playerPos, nearest.mesh.position);
        // Also hit jungle camps
        if (typeof JungleCamps !== "undefined") JungleCamps.tryAttack(playerPos, dmg * comboMult);
        return true;
    },

    showDamageNumber(pos, dmg, color) {
        if (!WorldMode.scene) return;
        var canvas = document.createElement('canvas');
        canvas.width = 128; canvas.height = 48;
        var ctx = canvas.getContext('2d');
        ctx.font = 'bold 32px monospace';
        ctx.textAlign = 'center';
        ctx.fillStyle = color || '#ff4444';
        ctx.fillText(Math.round(dmg), 64, 36);
        var sprite = new THREE.Sprite(new THREE.SpriteMaterial({
            map: new THREE.CanvasTexture(canvas), transparent: true
        }));
        sprite.position.copy(pos);
        sprite.position.y += 2;
        sprite.scale.set(1.5, 0.6, 1);
        WorldMode.scene.add(sprite);
        var age = 0;
        var interval = setInterval(function() {
            age += 16;
            sprite.position.y += 0.03;
            sprite.material.opacity = Math.max(0, 1 - age / 800);
            if (age > 800) {
                clearInterval(interval);
                if (sprite.parent) sprite.parent.remove(sprite);
                sprite.material.dispose();
            }
        }, 16);
    },

    createAttackFlash(from, to) {
        const points = [
            new THREE.Vector3(from.x, from.y + 1.5, from.z),
            new THREE.Vector3(to.x, to.y + 0.5, to.z)
        ];
        const geo = new THREE.BufferGeometry().setFromPoints(points);
        const mat = new THREE.LineBasicMaterial({ color: 0x00ffff, transparent: true, opacity: 0.8 });
        const line = new THREE.Line(geo, mat);
        this.scene.add(line);

        // Fade and remove
        setTimeout(() => {
            if (line.parent) line.parent.remove(line);
            geo.dispose();
            mat.dispose();
        }, 150);
    },

    updateCombatHUD() {
        const momEl = document.getElementById('combat-momentum-fill');
        const momVal = document.getElementById('combat-momentum-val');
        const waveEl = document.getElementById('combat-wave-num');

        if (momEl) momEl.style.width = this.momentum + '%';
        if (momVal) momVal.textContent = Math.round(this.momentum);
        if (waveEl) waveEl.textContent = this.waveNumber;

        // Color momentum bar
        if (momEl) {
            if (this.momentum > 65) momEl.style.background = '#00ff88';
            else if (this.momentum < 35) momEl.style.background = '#ff4488';
            else momEl.style.background = '#ffaa00';
        }
    },

    _triggerVictory(result, winner) {
        const overlay = document.getElementById('victory-overlay');
        const title = document.getElementById('victory-title');
        const stats = document.getElementById('victory-stats');
        const btn = document.getElementById('victory-btn');
        if (!overlay) return;
        if (title) {
            title.textContent = result;
            title.style.color = result === 'VICTORY' ? '#00ff88' : '#ff4444';
        }
        if (stats && typeof PlayerStats !== 'undefined') {
            stats.textContent = 'KDA: ' + PlayerStats.kills + '/' + PlayerStats.deaths + '/' + PlayerStats.assists +
                ' | Gold: ' + PlayerStats.gold + ' | GPM: ' + PlayerStats.getGPM() +
                ' | Level: ' + PlayerStats.level + ' | Wave: ' + this.waveNumber;
        }
        overlay.style.display = 'flex';
        if (btn) {
            btn.onclick = function() {
                overlay.style.display = 'none';
                if (typeof WorldMode !== 'undefined') WorldMode.cleanup();
                if (typeof HUD !== 'undefined' && HUD.hideWorldPanels) HUD.hideWorldPanels();
                GameState.setMode('galaxy');
                if (typeof Galaxy !== 'undefined') Galaxy.show();
            };
        }
        if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
    },

    cleanup() {
        const disposeMesh = (mesh) => {
            if (mesh.geometry) mesh.geometry.dispose();
            if (mesh.material) {
                if (Array.isArray(mesh.material)) mesh.material.forEach(m => m.dispose());
                else mesh.material.dispose();
            }
        };
        const disposeGroup = (group) => {
            group.traverse(child => { disposeMesh(child); });
        };

        // Dispose creep groups (body, eyes, HP bar geometries/materials)
        this.creeps.forEach(c => {
            if (c.mesh.parent) c.mesh.parent.remove(c.mesh);
            disposeGroup(c.mesh);
        });

        // Dispose projectile meshes
        this.projectiles.forEach(p => {
            if (p.mesh.parent) p.mesh.parent.remove(p.mesh);
            disposeMesh(p.mesh);
        });

        // Dispose boss if active
        if (this.boss && this.boss.mesh) {
            if (this.boss.mesh.parent) this.boss.mesh.parent.remove(this.boss.mesh);
            disposeGroup(this.boss.mesh);
        }

        // Remove any lingering boss overlay elements
        document.querySelectorAll('div[style*="z-index:9999"]').forEach(el => {
            if (el.parentNode) el.parentNode.removeChild(el);
        });

        this.creeps = [];
        this.projectiles = [];
        this.active = false;
        this.bossActive = false;
        this.boss = null;
    }
};
