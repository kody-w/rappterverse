/* enemy-hero.js — Primal Ravager Enemy Hero AI (Three.js r128) */

const HERO_CONFIG = {
    name: 'Primal Ravager',
    title: 'Alpha of the Wilds',
    baseStats: { maxHp: 120, maxMana: 80, baseDamage: 12, armor: 2, moveSpeed: 12, attackRange: 3.5, attackSpeed: 1.0 },
    perLevel: { hp: 20, mana: 12, damage: 2.5, armor: 0.4 },
    respawnBase: 12000,
    respawnPerLevel: 2000,
    killXpReward: 120,
    killGoldReward: 150,
    xpPerCreepKill: 15,
    xpToLevel: [0, 80, 200, 380, 620, 920, 1300, 1780, 2380, 3100],
    spawnOffset: { x: 80, z: 80 },
    ai: { aggressiveness: 0.6, retreatThreshold: 0.25, farmWeight: 0.4 }
};

const HERO_ABILITIES = {
    savageLeap:   { cooldown: 8000,  manaCost: 15, damage: 35, range: 10 },
    primalRoar:   { cooldown: 14000, manaCost: 25, damage: 25, radius: 8, damageBoost: 1.3, boostDuration: 4000 },
    thickHide:    { cooldown: 20000, manaCost: 20, damageReduction: 0.6, duration: 3500 },
    apexPredator: { cooldown: 55000, manaCost: 45, damageBoost: 1.8, lifesteal: 0.2, duration: 8000 }
};

const EnemyHero = {
    active: false, scene: null, worldBounds: null, mesh: null, state: null,

    init(scene, worldBounds) {
        this.scene = scene; this.worldBounds = worldBounds;
        const bs = HERO_CONFIG.baseStats;
        this.state = {
            hp: bs.maxHp, maxHp: bs.maxHp, mana: bs.maxMana, maxMana: bs.maxMana,
            damage: bs.baseDamage, armor: bs.armor, moveSpeed: bs.moveSpeed,
            level: 1, xp: 0, alive: true, aiState: 'pushing',
            target: null, targetPos: null, attackTimer: 0,
            laneKey: 'mid', waypointIdx: 0, kills: 0, deaths: 0, creepsKilled: 0,
            buffs: {}, cooldowns: { savageLeap: 0, primalRoar: 0, thickHide: 0, apexPredator: 0 },
            respawnTimer: 0
        };
        this.mesh = this.createMesh();
        this.mesh.position.set(HERO_CONFIG.spawnOffset.x, 0, HERO_CONFIG.spawnOffset.z);
        scene.add(this.mesh);
        this.active = true;
        this.updateHUD();
    },

    createMesh() {
        const g = new THREE.Group();
        const bodyMat = new THREE.MeshStandardMaterial({ color: 0x6b4226, roughness: 0.7 });
        const headMat = new THREE.MeshStandardMaterial({ color: 0x4a2e15, roughness: 0.7 });
        const eyeMat  = new THREE.MeshBasicMaterial({ color: 0xff2200 });
        const legMat  = new THREE.MeshStandardMaterial({ color: 0x5a3a1a, roughness: 0.8 });

        // Body
        const body = new THREE.Mesh(new THREE.BoxGeometry(2, 1.2, 1.4), bodyMat);
        body.position.y = 1.4;
        g.add(body);

        // Head
        const head = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.7, 0.9), headMat);
        head.position.set(1.2, 1.7, 0);
        g.add(head);

        // Eyes
        const eyeGeo = new THREE.SphereGeometry(0.12, 8, 8);
        const eyeL = new THREE.Mesh(eyeGeo, eyeMat);
        eyeL.position.set(1.55, 1.85, 0.25);
        const eyeR = new THREE.Mesh(eyeGeo, eyeMat);
        eyeR.position.set(1.55, 1.85, -0.25);
        g.add(eyeL, eyeR);

        // Legs (CylinderGeometry — r128 compatible)
        const legGeo = new THREE.CylinderGeometry(0.15, 0.15, 0.8, 8);
        const positions = [
            [0.6, 0.4, 0.45], [0.6, 0.4, -0.45],
            [-0.6, 0.4, 0.45], [-0.6, 0.4, -0.45]
        ];
        positions.forEach(p => {
            const leg = new THREE.Mesh(legGeo, legMat);
            leg.position.set(p[0], p[1], p[2]);
            g.add(leg);
        });

        // Aura ring
        const auraMat = new THREE.MeshBasicMaterial({ color: 0xff3300, transparent: true, opacity: 0.5 });
        const aura = new THREE.Mesh(new THREE.TorusGeometry(1.4, 0.12, 8, 24), auraMat);
        aura.rotation.x = Math.PI / 2;
        aura.position.y = 0.05;
        aura.name = 'aura';
        g.add(aura);

        // HP bar
        const hpCanvas = document.createElement('canvas');
        hpCanvas.width = 128; hpCanvas.height = 16;
        const hpTex = new THREE.CanvasTexture(hpCanvas);
        const hpBar = new THREE.Mesh(
            new THREE.PlaneGeometry(2, 0.25),
            new THREE.MeshBasicMaterial({ map: hpTex, transparent: true, depthTest: false })
        );
        hpBar.position.y = 3.0;
        hpBar.name = 'hpBar';
        hpBar.userData = { canvas: hpCanvas, texture: hpTex };
        g.add(hpBar);

        // Mana bar
        const manaCanvas = document.createElement('canvas');
        manaCanvas.width = 128; manaCanvas.height = 16;
        const manaTex = new THREE.CanvasTexture(manaCanvas);
        const manaBar = new THREE.Mesh(
            new THREE.PlaneGeometry(2, 0.18),
            new THREE.MeshBasicMaterial({ map: manaTex, transparent: true, depthTest: false })
        );
        manaBar.position.y = 2.7;
        manaBar.name = 'manaBar';
        manaBar.userData = { canvas: manaCanvas, texture: manaTex };
        g.add(manaBar);

        g.name = 'enemyHero';
        return g;
    },

    update(delta, time, playerPos) {
        if (!this.active || !this.state) return;
        const s = this.state;
        if (!s.alive) { s.respawnTimer -= delta * 1000; if (s.respawnTimer <= 0) this.respawn(); this.updateHUD(); return; }
        s.mana = Math.min(s.maxMana, s.mana + 2 * delta);
        this.updateAI(playerPos); this.updateMovement(delta);
        this.updateCombat(delta, time); this.updateAbilities(time);
        this.updateBuffs(time); this.updateVisuals(); this.updateHUD();
    },

    updateAI(playerPos) {
        const s = this.state;
        const hpRatio = s.hp / s.maxHp;
        const pos = this.mesh.position;

        if (hpRatio < HERO_CONFIG.ai.retreatThreshold) {
            s.aiState = 'retreating';
            s.targetPos = new THREE.Vector3(HERO_CONFIG.spawnOffset.x, 0, HERO_CONFIG.spawnOffset.z);
            s.target = null;
            return;
        }

        if (playerPos) {
            const dist = pos.distanceTo(new THREE.Vector3(playerPos.x, 0, playerPos.z));
            if (dist < 15 && hpRatio > 0.4) {
                s.aiState = 'fighting';
                s.targetPos = new THREE.Vector3(playerPos.x, 0, playerPos.z);
                s.target = 'player';
                return;
            }
        }

        // Farming
        if (Math.random() < HERO_CONFIG.ai.farmWeight * 0.02) {
            const creep = this._findNearestCreep('explorer');
            if (creep) {
                s.aiState = 'farming';
                s.targetPos = creep.mesh.position.clone();
                s.target = creep;
                return;
            }
        }

        // Pushing lane
        s.aiState = 'pushing';
        s.target = null;
        if (typeof WorldLanes !== 'undefined' && WorldLanes.scaledWaypoints) {
            const wps = WorldLanes.scaledWaypoints[s.laneKey];
            if (wps && wps.length > 0) {
                const idx = Math.min(s.waypointIdx, wps.length - 1);
                const wp = wps[idx];
                s.targetPos = new THREE.Vector3(wp.x, 0, wp.z);
                const d = pos.distanceTo(s.targetPos);
                if (d < 2 && s.waypointIdx < wps.length - 1) s.waypointIdx++;
            }
        }
    },

    updateMovement(delta) {
        const s = this.state;
        if (!s.targetPos) return;
        const dir = new THREE.Vector3().subVectors(s.targetPos, this.mesh.position);
        dir.y = 0;
        const dist = dir.length();
        if (dist < 0.5) return;
        dir.normalize();
        let speed = s.moveSpeed;
        if (s.buffs.apexPredator) speed *= 1.3;
        const step = speed * delta;
        this.mesh.position.addScaledVector(dir, Math.min(step, dist));
        this.mesh.rotation.y = Math.atan2(dir.x, dir.z);
    },

    updateCombat(delta, time) {
        const s = this.state;
        s.attackTimer -= delta;
        if (s.attackTimer > 0) return;
        if (s.aiState === 'fighting' && s.target === 'player') {
            const pPos = this.mesh.position;
            if (s.targetPos && pPos.distanceTo(s.targetPos) <= HERO_CONFIG.baseStats.attackRange) {
                this.performAttack('player', time);
                s.attackTimer = 1.0 / HERO_CONFIG.baseStats.attackSpeed;
            }
        } else if (s.aiState === 'farming' && s.target && s.target !== 'player') {
            const creep = s.target;
            if (creep.alive && creep.mesh) {
                const d = this.mesh.position.distanceTo(creep.mesh.position);
                if (d <= HERO_CONFIG.baseStats.attackRange) {
                    this.performAttack(creep, time);
                    s.attackTimer = 1.0 / HERO_CONFIG.baseStats.attackSpeed;
                }
            }
        }
    },

    performAttack(target, time) {
        const s = this.state;
        let dmg = s.damage;
        if (s.buffs.primalRoar) dmg *= HERO_ABILITIES.primalRoar.damageBoost;
        if (s.buffs.apexPredator) dmg *= HERO_ABILITIES.apexPredator.damageBoost;

        if (target === 'player') {
            // Pack Hunter passive: +50% to targets below 30% HP
            if (typeof PlayerStats !== 'undefined' && PlayerStats.hp / PlayerStats.maxHp < 0.3) dmg *= 1.5;
            if (typeof PlayerStats !== 'undefined') PlayerStats.takeDamage(dmg);
            if (s.buffs.apexPredator) {
                s.hp = Math.min(s.maxHp, s.hp + dmg * HERO_ABILITIES.apexPredator.lifesteal);
            }
        } else if (target && target.mesh && target.alive !== false) {
            if (target.hp / target.maxHp < 0.3) dmg *= 1.5;
            target.hp -= dmg;
            if (target.hp <= 0) {
                target.alive = false;
                if (target.mesh) target.mesh.visible = false;
                s.creepsKilled++;
                this.gainXp(HERO_CONFIG.xpPerCreepKill);
            }
            if (s.buffs.apexPredator) {
                s.hp = Math.min(s.maxHp, s.hp + dmg * HERO_ABILITIES.apexPredator.lifesteal);
            }
        }
    },

    updateAbilities(time) {
        const s = this.state;
        const now = time * 1000;
        const cd = s.cooldowns;
        const pos = this.mesh.position;
        const hpRatio = s.hp / s.maxHp;

        // Savage Leap
        if (cd.savageLeap <= now && s.mana >= HERO_ABILITIES.savageLeap.manaCost && s.targetPos) {
            const d = pos.distanceTo(s.targetPos);
            if (d > 6 && d <= HERO_ABILITIES.savageLeap.range) {
                s.mana -= HERO_ABILITIES.savageLeap.manaCost;
                cd.savageLeap = now + HERO_ABILITIES.savageLeap.cooldown;
                const dir = new THREE.Vector3().subVectors(s.targetPos, pos).normalize();
                this.mesh.position.addScaledVector(dir, Math.min(d, HERO_ABILITIES.savageLeap.range));
                if (s.target === 'player' && typeof PlayerStats !== 'undefined') {
                    PlayerStats.takeDamage(HERO_ABILITIES.savageLeap.damage);
                }
            }
        }

        // Primal Roar
        if (cd.primalRoar <= now && s.mana >= HERO_ABILITIES.primalRoar.manaCost && s.aiState === 'fighting') {
            if (s.targetPos && pos.distanceTo(s.targetPos) <= HERO_ABILITIES.primalRoar.radius) {
                s.mana -= HERO_ABILITIES.primalRoar.manaCost;
                cd.primalRoar = now + HERO_ABILITIES.primalRoar.cooldown;
                if (typeof PlayerStats !== 'undefined') PlayerStats.takeDamage(HERO_ABILITIES.primalRoar.damage);
                s.buffs.primalRoar = now + HERO_ABILITIES.primalRoar.boostDuration;
            }
        }

        // Thick Hide
        if (cd.thickHide <= now && hpRatio < 0.5 && s.mana >= HERO_ABILITIES.thickHide.manaCost) {
            s.mana -= HERO_ABILITIES.thickHide.manaCost;
            cd.thickHide = now + HERO_ABILITIES.thickHide.cooldown;
            s.buffs.thickHide = now + HERO_ABILITIES.thickHide.duration;
        }

        // Apex Predator (ultimate)
        if (cd.apexPredator <= now && hpRatio > 0.25 && hpRatio < 0.55
            && s.mana >= HERO_ABILITIES.apexPredator.manaCost) {
            s.mana -= HERO_ABILITIES.apexPredator.manaCost;
            cd.apexPredator = now + HERO_ABILITIES.apexPredator.cooldown;
            s.buffs.apexPredator = now + HERO_ABILITIES.apexPredator.duration;
        }
    },

    updateBuffs(time) {
        const now = time * 1000;
        const b = this.state.buffs;
        for (const key in b) {
            if (b[key] && b[key] <= now) delete b[key];
        }
    },

    updateVisuals() {
        const s = this.state;
        // HP bar
        const hpObj = this.mesh.getObjectByName('hpBar');
        if (hpObj) {
            const ctx = hpObj.userData.canvas.getContext('2d');
            ctx.clearRect(0, 0, 128, 16);
            ctx.fillStyle = '#333';
            ctx.fillRect(0, 0, 128, 16);
            ctx.fillStyle = '#cc2200';
            ctx.fillRect(0, 0, 128 * (s.hp / s.maxHp), 16);
            hpObj.userData.texture.needsUpdate = true;
        }
        // Mana bar
        const manaObj = this.mesh.getObjectByName('manaBar');
        if (manaObj) {
            const ctx = manaObj.userData.canvas.getContext('2d');
            ctx.clearRect(0, 0, 128, 16);
            ctx.fillStyle = '#222';
            ctx.fillRect(0, 0, 128, 16);
            ctx.fillStyle = '#2266ff';
            ctx.fillRect(0, 0, 128 * (s.mana / s.maxMana), 16);
            manaObj.userData.texture.needsUpdate = true;
        }
        // Billboard bars toward camera
        if (typeof WorldMode !== 'undefined' && WorldMode.camera) {
            const cam = WorldMode.camera;
            if (hpObj) hpObj.lookAt(cam.position);
            if (manaObj) manaObj.lookAt(cam.position);
        }
        // Aura color shift during buffs
        const aura = this.mesh.getObjectByName('aura');
        if (aura) {
            if (s.buffs.apexPredator) aura.material.color.setHex(0xff0000);
            else if (s.buffs.thickHide) aura.material.color.setHex(0x44aaff);
            else aura.material.color.setHex(0xff3300);
            aura.material.opacity = 0.35 + 0.15 * Math.sin(Date.now() * 0.004);
        }
    },

    damage(amount) {
        if (!this.state || !this.state.alive) return;
        let dmg = amount;
        if (this.state.buffs.thickHide) dmg *= (1 - HERO_ABILITIES.thickHide.damageReduction);
        dmg = Math.max(0, dmg - this.state.armor);
        this.state.hp -= dmg;
        if (this.state.hp <= 0) {
            this.state.hp = 0;
            this.die();
        }
    },

    die() {
        const s = this.state;
        s.alive = false; s.deaths++;
        this.mesh.visible = false;
        s.respawnTimer = HERO_CONFIG.respawnBase + HERO_CONFIG.respawnPerLevel * s.level;
        const xpReward = HERO_CONFIG.killXpReward + 15 * s.level;
        if (typeof PlayerStats !== 'undefined' && PlayerStats.awardXp) PlayerStats.awardXp(xpReward);
        if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast(`${HERO_CONFIG.name} slain! +${xpReward} XP`);
    },

    respawn() {
        const s = this.state;
        s.alive = true; s.hp = s.maxHp; s.mana = s.maxMana;
        s.buffs = {}; s.aiState = 'pushing'; s.waypointIdx = 0;
        s.target = null; s.targetPos = null;
        this.mesh.position.set(HERO_CONFIG.spawnOffset.x, 0, HERO_CONFIG.spawnOffset.z);
        this.mesh.visible = true;
    },

    gainXp(amount) {
        const s = this.state;
        s.xp += amount;
        const table = HERO_CONFIG.xpToLevel;
        while (s.level < table.length && s.xp >= table[s.level]) {
            this.levelUp();
        }
    },

    levelUp() {
        const s = this.state, pl = HERO_CONFIG.perLevel;
        s.level++; s.maxHp += pl.hp; s.maxMana += pl.mana;
        s.damage += pl.damage; s.armor += pl.armor;
        s.hp = s.maxHp; s.mana = s.maxMana;
    },

    updateHUD() {
        let el = document.getElementById('enemy-hero-hud');
        if (!el) return;
        if (!this.state) { el.style.display = 'none'; return; }
        if (!this.active) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        const s = this.state;
        const stateColors = { retreating: '#ffaa00', fighting: '#ff3333', farming: '#66cc66', pushing: '#6699ff' };
        const sc = stateColors[s.aiState] || '#aaa';
        const hpPct = Math.max(0, s.hp / s.maxHp) * 100;
        const manaPct = Math.max(0, s.mana / s.maxMana) * 100;

        const nameEl = el.querySelector('.hero-name');
        const levelEl = el.querySelector('.hero-level');
        const hpFill = el.querySelector('.hero-bar.hp .hero-bar-fill');
        const manaFill = el.querySelector('.hero-bar.mana .hero-bar-fill');
        const kdaEl = el.querySelector('.hero-kda');
        const stateEl = el.querySelector('.hero-ai-state');

        if (nameEl) nameEl.textContent = HERO_CONFIG.name;
        if (levelEl) levelEl.textContent = `Lv.${s.level}`;
        if (hpFill) hpFill.style.width = `${hpPct}%`;
        if (manaFill) manaFill.style.width = `${manaPct}%`;
        if (kdaEl) kdaEl.textContent = `K:${s.kills} D:${s.deaths} CS:${s.creepsKilled}`;
        if (stateEl) { stateEl.textContent = s.alive ? s.aiState.toUpperCase() : 'DEAD'; stateEl.style.color = sc; }
    },

    cleanup() {
        if (this.mesh && this.scene) this.scene.remove(this.mesh);
        this.mesh = null;
        this.state = null;
        this.active = false;
        const el = document.getElementById('enemy-hero-hud');
        if (el) el.style.display = 'none';
    },

    _findNearestCreep(faction) {
        if (typeof WorldCombat === 'undefined' || !WorldCombat.creeps) return null;
        let best = null, bestDist = Infinity;
        const pos = this.mesh.position;
        for (const c of WorldCombat.creeps) {
            if (!c.alive || c.faction !== faction || !c.mesh) continue;
            const d = pos.distanceTo(c.mesh.position);
            if (d < bestDist) { bestDist = d; best = c; }
        }
        return best;
    }
};
