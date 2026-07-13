// Abilities — DOTA-style ability system (Slash, Pulse Shot, Shield, Dash, Nova)
const Abilities = {
  defs: [
    { name: 'Slash', icon: '⚔️', key: 'Digit1', cooldown: 1, cost: 0, costType: 'none',
      range: 6, damage: 15, type: 'melee_aoe' },
    { name: 'Pulse Shot', icon: '🔵', key: 'Digit2', cooldown: 3, cost: 10, costType: 'mp',
      range: 30, damage: 25, type: 'projectile', speed: 40 },
    { name: 'Shield', icon: '🛡️', key: 'Digit3', cooldown: 12, cost: 20, costType: 'mp',
      duration: 2, type: 'buff_shield' },
    { name: 'Dash', icon: '💨', key: 'Digit4', cooldown: 8, cost: 15, costType: 'energy',
      distance: 15, type: 'dash' },
    { name: 'Nova', icon: '💥', key: 'Digit5', cooldown: 20, cost: 30, costType: 'mp',
      range: 15, damage: 50, type: 'aoe_burst' },
  ],
  cooldowns: [0, 0, 0, 0, 0],
  levels: [1, 1, 1, 1, 1],     // Ability levels (1-5)
  skillPoints: 0,
  shieldActive: false,
  shieldTimer: 0,
  projectiles: [],
  active: false,
  _effects: [],
  _novaShakeTimer: null,

  init() {
    this.cooldowns = [0, 0, 0, 0, 0];
    this.levels = [1, 1, 1, 1, 1];
    this.skillPoints = 0;
    this.projectiles = [];
    this.shieldActive = false;
    this.shieldTimer = 0;
    this._effects = [];
    this.active = true;
    this._slotEls = document.querySelectorAll('.ability-slot');
    this._slotListeners = [];
    this._slotEls.forEach((el, i) => {
      const handler = (e) => {
        if (e.shiftKey && this.skillPoints > 0) {
          this.levelUpAbility(i);
        } else {
          this.useAbility(i);
        }
      };
      this._slotListeners.push(handler);
      el.addEventListener('click', handler);
    });
  },

  // Level up an ability (Shift+Click or called by UI)
  levelUpAbility(idx) {
    if (this.skillPoints <= 0 || this.levels[idx] >= 5) return;
    this.skillPoints--;
    this.levels[idx]++;
    var def = this.defs[idx];
    if (typeof HUD !== 'undefined') HUD.showToast(def.name + ' → Level ' + this.levels[idx]);
    if (typeof Audio !== 'undefined' && Audio.playAbility) Audio.playAbility();
    this._updateSlotUI();
  },

  // Called by PlayerStats on level up
  awardSkillPoint() {
    this.skillPoints++;
    if (typeof HUD !== 'undefined') HUD.showToast('+1 Skill Point (Shift+Click ability to level up)');
    this._updateSlotUI();
  },

  // Get scaled stats for an ability based on its level
  getScaled(idx) {
    var def = this.defs[idx];
    var lvl = this.levels[idx];
    return {
      damage: def.damage ? Math.round(def.damage * (1 + (lvl - 1) * 0.3)) : 0,
      cooldown: def.cooldown ? Math.max(0.3, def.cooldown * (1 - (lvl - 1) * 0.08)) : 0,
      range: def.range ? def.range + (lvl - 1) * 1 : 0,
      duration: def.duration ? def.duration + (lvl - 1) * 0.5 : 0,
      distance: def.distance ? def.distance + (lvl - 1) * 2 : 0,
      cost: def.cost ? Math.max(0, def.cost - (lvl - 1) * 1) : 0
    };
  },

  _updateSlotUI() {
    this._slotEls.forEach((el, i) => {
      var lvlBadge = el.querySelector('.ability-level');
      if (!lvlBadge) {
        lvlBadge = document.createElement('span');
        lvlBadge.className = 'ability-level';
        lvlBadge.style.cssText = 'position:absolute;bottom:0;right:0;font-size:8px;color:#d29922;font-weight:700;background:rgba(0,0,0,0.5);padding:0 3px;border-radius:2px;';
        el.style.position = 'relative';
        el.appendChild(lvlBadge);
      }
      lvlBadge.textContent = this.levels[i] > 1 ? 'L' + this.levels[i] : '';
      // Skill point indicator
      if (this.skillPoints > 0 && this.levels[i] < 5) {
        el.style.borderColor = 'rgba(210,153,34,0.6)';
        el.style.boxShadow = '0 0 6px rgba(210,153,34,0.3)';
      } else {
        el.style.borderColor = '';
        el.style.boxShadow = '';
      }
    });
  },

  _playerPos() { return WorldMode.player.mesh.position; },
  _facing() {
    const r = WorldMode.player.mesh.rotation.y;
    return new THREE.Vector3(Math.sin(r), 0, Math.cos(r));
  },

  _damageCreep(creep, dmg) {
    creep.hp -= dmg;
    if (creep.hpBar) {
      const r = Math.max(0, creep.hp / creep.maxHp);
      creep.hpBar.scale.x = r;
      creep.hpBar.material.color.setHex(r > 0.5 ? 0x00ff00 : r > 0.25 ? 0xffaa00 : 0xff0000);
    }
    if (creep.hp > 0) return;
    creep.alive = false;
    const scale = creep.isBoss ? 5 : (1 + WorldCombat.waveNumber * 0.1);
    PlayerStats.awardXp(Math.floor(10 * scale));
    if (creep.isBoss) {
      WorldCombat.bossActive = false; WorldCombat.boss = null;
      WorldCombat.momentum = Math.min(100, WorldCombat.momentum + 20);
      if (typeof HUD !== 'undefined') HUD.showToast('BOSS DEFEATED!');
    } else {
      const mk = typeof COMBAT_CONFIG !== 'undefined' ? COMBAT_CONFIG.momentumPerKill : 3;
      if (creep.faction === 'horde') WorldCombat.momentum = Math.min(100, WorldCombat.momentum + mk);
      else WorldCombat.momentum = Math.max(0, WorldCombat.momentum - mk);
    }
  },
  _creepsInRange(pos, range) {
    return WorldCombat.creeps.filter(c => {
      if (!c.alive) return false;
      const dx = pos.x - c.mesh.position.x, dz = pos.z - c.mesh.position.z;
      return Math.sqrt(dx * dx + dz * dz) <= range;
    });
  },
  _addEffect(mesh, duration) {
    WorldMode.scene.add(mesh); this._effects.push({ mesh, life: 0, duration });
  },

  useAbility(index) {
    if (!this.active || index < 0 || index >= this.defs.length) return false;
    const def = this.defs[index];
    if (this.cooldowns[index] > 0) return false;
    if (def.costType === 'mp' && !PlayerStats.useMp(def.cost)) return false;
    if (def.costType === 'energy' && !PlayerStats.useEnergy(def.cost)) return false;
    this.cooldowns[index] = def.cooldown;

    const pos = this._playerPos();
    const dir = this._facing();

    if (def.type === 'melee_aoe') this._doSlash(pos, def);
    else if (def.type === 'projectile') this._doPulseShot(pos, dir, def);
    else if (def.type === 'buff_shield') this._doShield(def);
    else if (def.type === 'dash') this._doDash(pos, dir, def);
    else if (def.type === 'aoe_burst') this._doNova(pos, def);
    return true;
  },

  _scaledDmg(base) {
    var dmg = typeof PlayerStats !== 'undefined' && PlayerStats.getAbilityDamage ? PlayerStats.getAbilityDamage(base) : base;
    // Echo amplification: abilities deal up to 20% more during high tension
    if (typeof EchoEngine !== 'undefined') {
      var ef = EchoEngine.getCurrentFrame();
      if (ef && ef.echoes && ef.echoes.L3) {
        dmg *= (1 + ef.echoes.L3.tension * 0.2);
      }
    }
    // Echo Storm doubles ability damage
    if (typeof EchoEvents !== 'undefined' && EchoEvents._amplified) {
      dmg *= 1.5;
    }
    return Math.round(dmg);
  },
  _disposeOwnedMesh(mesh) {
    if (!mesh) return;
    if (mesh.parent) mesh.parent.remove(mesh);
    if (mesh.geometry && mesh.geometry.dispose) mesh.geometry.dispose();
    if (Array.isArray(mesh.material)) {
      mesh.material.forEach(material => material && material.dispose && material.dispose());
    } else if (mesh.material && mesh.material.dispose) {
      mesh.material.dispose();
    }
  },
  _doSlash(pos, def) {
    const element = (typeof Equipment !== 'undefined') ? Equipment.getEquippedElement() : null;
    const dmg = this._scaledDmg(def.damage);
    this._creepsInRange(pos, def.range).forEach(c => {
      this._damageCreep(c, dmg);
      if (element && typeof StatusEffects !== 'undefined') StatusEffects.applyEffect(c.mesh, element);
    });
    const geo = new THREE.RingGeometry(0.5, def.range, 24);
    const mat = new THREE.MeshBasicMaterial({ color: 0x00ffff, transparent: true, opacity: 0.6, side: THREE.DoubleSide });
    const ring = new THREE.Mesh(geo, mat);
    ring.rotation.x = -Math.PI / 2; ring.position.copy(pos); ring.position.y = 0.1;
    this._addEffect(ring, 0.3);
    if (typeof VFX !== 'undefined') VFX.burst(pos, 'slashArc');
    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
  },
  _doPulseShot(pos, dir, def) {
    const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.3, 8, 8), new THREE.MeshBasicMaterial({ color: 0x00ffff }));
    mesh.position.copy(pos); mesh.position.y = 1;
    WorldMode.scene.add(mesh);
    var projObj = { mesh, direction: dir.clone(), speed: def.speed, damage: this._scaledDmg(def.damage), life: 0 };
    if (typeof VFX !== 'undefined') projObj._trail = VFX.trail(mesh, 'pulseTrail');
    this.projectiles.push(projObj);
    if (typeof Audio !== 'undefined' && Audio.playTowerShot) Audio.playTowerShot();
  },
  _shieldBubble: null,
  _doShield(def) {
    this.shieldActive = true; this.shieldTimer = def.duration; PlayerStats.shielded = true;
    const ring = WorldMode.player.ring;
    if (ring) {
      ring._origColor = ring.material.color.getHex(); ring._origScale = ring.scale.clone();
      ring.material.color.setHex(0xffd700); ring.scale.set(2, 2, 2);
    }
    if (typeof VFX !== 'undefined') VFX.emit(WorldMode.player.mesh.position, 'shieldShimmer', def.duration);
    // Shield bubble dome
    if (WorldMode.scene && !this._shieldBubble) {
      var bubbleGeo = new THREE.SphereGeometry(2.5, 16, 12);
      var bubbleMat = new THREE.MeshStandardMaterial({
        color: 0xffd700, emissive: 0xffd700, emissiveIntensity: 0.3,
        transparent: true, opacity: 0.15, side: THREE.DoubleSide,
        roughness: 0.1, metalness: 0.8, wireframe: false
      });
      this._shieldBubble = new THREE.Mesh(bubbleGeo, bubbleMat);
      this._shieldBubble.position.copy(WorldMode.player.mesh.position);
      this._shieldBubble.position.y = 1;
      WorldMode.scene.add(this._shieldBubble);
    }
    if (typeof Audio !== 'undefined' && Audio.playClick) Audio.playClick();
  },
  _doDash(pos, dir, def) {
    pos.x += dir.x * def.distance; pos.z += dir.z * def.distance;
    if (WorldMode.currentWorld && typeof WORLDS !== 'undefined') {
      const b = WORLDS[WorldMode.currentWorld].bounds;
      pos.x = Math.max(-b.x, Math.min(b.x, pos.x)); pos.z = Math.max(-b.z, Math.min(b.z, pos.z));
    }
    for (let i = 0; i < 5; i++) {
      const p = new THREE.Mesh(new THREE.SphereGeometry(0.15, 4, 4),
        new THREE.MeshBasicMaterial({ color: 0x88ccff, transparent: true, opacity: 0.5 }));
      p.position.set(pos.x - dir.x * def.distance * (i / 5) + (Math.random() - 0.5), 0.5,
        pos.z - dir.z * def.distance * (i / 5) + (Math.random() - 0.5));
      this._addEffect(p, 0.4);
    }
    if (typeof VFX !== 'undefined') VFX.burst(pos, 'dashTrail', { count: 8 });
    if (typeof Audio !== 'undefined' && Audio.playClick) Audio.playClick();
  },
  _doNova(pos, def) {
    const element = (typeof Equipment !== 'undefined') ? Equipment.getEquippedElement() : null;
    const dmg = this._scaledDmg(def.damage);
    this._creepsInRange(pos, def.range).forEach(c => {
      this._damageCreep(c, dmg);
      if (element && typeof StatusEffects !== 'undefined') StatusEffects.applyEffect(c.mesh, element);
    });
    const mat = new THREE.MeshBasicMaterial({ color: 0xff4400, wireframe: true, transparent: true, opacity: 0.7 });
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 16), mat);
    sphere.position.copy(pos); sphere.position.y = 1; sphere._novaRange = def.range;
    this._addEffect(sphere, 0.5);
    if (typeof VFX !== 'undefined') { VFX.burst(pos, 'novaBlast'); VFX.screenFlash('#ff4400', 0.2); }
    const cam = WorldMode.camera;
    if (cam) {
      if (this._novaShakeTimer) clearInterval(this._novaShakeTimer);
      const ox = cam.position.x, oy = cam.position.y; let shakeT = 0;
      var self = this;
      this._novaShakeTimer = setInterval(() => {
        shakeT += 16;
        if (shakeT > 200) { cam.position.x = ox; cam.position.y = oy; clearInterval(self._novaShakeTimer); self._novaShakeTimer = null; return; }
        cam.position.x = ox + (Math.random() - 0.5) * 0.4;
        cam.position.y = oy + (Math.random() - 0.5) * 0.3;
      }, 16);
    }
    if (typeof Audio !== 'undefined' && Audio.playExplosion) Audio.playExplosion();
  },

  update(delta) {
    if (!this.active) return;

    // Cooldowns
    for (let i = 0; i < this.cooldowns.length; i++) {
      this.cooldowns[i] = Math.max(0, this.cooldowns[i] - delta);
    }

    // Projectiles
    for (let i = this.projectiles.length - 1; i >= 0; i--) {
      const p = this.projectiles[i];
      p.mesh.position.x += p.direction.x * p.speed * delta;
      p.mesh.position.z += p.direction.z * p.speed * delta;
      p.life += delta;
      let hit = false;
      for (const c of WorldCombat.creeps) {
        if (!c.alive) continue;
        const dx = p.mesh.position.x - c.mesh.position.x, dz = p.mesh.position.z - c.mesh.position.z;
        if (Math.sqrt(dx * dx + dz * dz) < 1.5) {
          this._damageCreep(c, p.damage);
          const element = (typeof Equipment !== 'undefined') ? Equipment.getEquippedElement() : null;
          if (element && typeof StatusEffects !== 'undefined') StatusEffects.applyEffect(c.mesh, element);
          hit = true; break;
        }
      }
      if (hit || p.life > 3) {
        if (hit && typeof VFX !== 'undefined') VFX.burst(p.mesh.position, 'towerImpact');
        if (p._trail && typeof VFX !== 'undefined') VFX.stopTrail(p._trail);
        this._disposeOwnedMesh(p.mesh); this.projectiles.splice(i, 1);
      }
    }
    // Shield + bubble
    if (this.shieldActive) {
      this.shieldTimer -= delta;
      // Animate shield bubble
      if (this._shieldBubble && WorldMode.player) {
        this._shieldBubble.position.copy(WorldMode.player.mesh.position);
        this._shieldBubble.position.y = 1;
        this._shieldBubble.rotation.y += delta * 2;
        this._shieldBubble.material.opacity = 0.1 + Math.sin(Date.now() * 0.005) * 0.08;
      }
      if (this.shieldTimer <= 0) {
        this.shieldActive = false; PlayerStats.shielded = false;
        const ring = WorldMode.player.ring;
        if (ring) {
          ring.material.color.setHex(ring._origColor || 0x00ffff);
          ring.scale.copy(ring._origScale || new THREE.Vector3(1, 1, 1));
        }
        // Remove shield bubble
        if (this._shieldBubble && WorldMode.scene) {
          this._disposeOwnedMesh(this._shieldBubble);
          this._shieldBubble = null;
        }
      }
    }
    // HUD
    (this._slotEls || []).forEach((el, i) => {
      const cd = this.cooldowns[i];
      let overlay = el.querySelector('.cd-overlay');
      if (cd > 0) {
        if (!overlay) {
          overlay = document.createElement('div');
          overlay.className = 'cd-overlay';
          overlay.style.cssText = 'position:absolute;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;pointer-events:none';
          el.style.position = 'relative';
          el.appendChild(overlay);
        }
        overlay.style.display = 'flex';
        overlay.textContent = Math.ceil(cd) + 's';
      } else if (overlay) {
        overlay.style.display = 'none';
      }
    });

    // Effects
    for (let i = this._effects.length - 1; i >= 0; i--) {
      const e = this._effects[i]; e.life += delta;
      const t = e.life / e.duration;
      e.mesh.material.opacity = Math.max(0, 1 - t);
      if (e.mesh._novaRange) { const s = 1 + (e.mesh._novaRange - 1) * t; e.mesh.scale.set(s, s, s); }
      if (e.life >= e.duration) {
        this._disposeOwnedMesh(e.mesh);
        this._effects.splice(i, 1);
      }
    }
  },
  cleanup() {
    this.active = false;
    if (this._slotEls && this._slotListeners) {
      this._slotEls.forEach((el, i) => {
        if (this._slotListeners[i]) el.removeEventListener('click', this._slotListeners[i]);
      });
    }
    this._slotListeners = [];
    this.projectiles.forEach(p => this._disposeOwnedMesh(p.mesh));
    this._effects.forEach(e => this._disposeOwnedMesh(e.mesh));
    this.projectiles = []; this._effects = [];
    this.shieldActive = false; PlayerStats.shielded = false;
    // Dispose shield bubble
    if (this._shieldBubble) {
      this._disposeOwnedMesh(this._shieldBubble);
      this._shieldBubble = null;
    }
    if (this._novaShakeTimer) {
      clearInterval(this._novaShakeTimer);
      this._novaShakeTimer = null;
    }
    this.cooldowns = [0, 0, 0, 0, 0];
  }
};
