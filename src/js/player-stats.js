// Player RPG Stats — HP, MP, Energy, XP, Leveling, Regen
const PlayerStats = {
  hp: 100, maxHp: 100,
  mp: 50, maxMp: 50,
  energy: 100, maxEnergy: 100,
  xp: 0, xpToLevel: 100,
  level: 1,
  baseDamage: 20,
  hpRegen: 1,
  mpRegen: 2,
  energyRegen: 5,
  dead: false,
  respawnTimer: 0,
  respawnDuration: 3,
  damageFlashTimer: 0,

  init() {
    this.hp = this.maxHp = 100;
    this.mp = this.maxMp = 50;
    this.energy = this.maxEnergy = 100;
    this.xp = 0; this.xpToLevel = 100;
    this.level = 1; this.baseDamage = 20;
    this.hpRegen = 1; this.mpRegen = 2; this.energyRegen = 5;
    this.dead = false; this.respawnTimer = 0;
    this.damageFlashTimer = 0;
  },

  takeDamage(amount) {
    if (this.dead) return;
    this.hp = Math.max(0, this.hp - amount);
    this.damageFlashTimer = 0.3;
    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
    if (this.hp <= 0) this.die();
  },

  die() {
    this.dead = true;
    this.respawnTimer = this.respawnDuration;
    const overlay = document.getElementById('death-overlay');
    if (overlay) overlay.style.display = 'flex';
    if (typeof Audio !== 'undefined' && Audio.playExplosion) Audio.playExplosion();
  },

  respawn() {
    this.dead = false;
    this.hp = this.maxHp;
    this.mp = this.maxMp;
    this.energy = this.maxEnergy;
    const overlay = document.getElementById('death-overlay');
    if (overlay) overlay.style.display = 'none';
    if (typeof WorldMode !== 'undefined' && WorldMode.player && WorldMode.player.mesh) {
      WorldMode.player.mesh.position.set(0, 0, 5);
    }
  },

  heal(amount) {
    this.hp = Math.min(this.maxHp, this.hp + amount);
  },

  restoreMp(amount) {
    this.mp = Math.min(this.maxMp, this.mp + amount);
  },

  useMp(amount) {
    if (this.mp < amount) return false;
    this.mp -= amount;
    return true;
  },

  useEnergy(amount) {
    if (this.energy < amount) return false;
    this.energy -= amount;
    return true;
  },

  awardXp(amount) {
    this.xp += amount;
    if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast(`+${amount} XP`);
    if (this.xp >= this.xpToLevel) this.levelUp();
  },

  levelUp() {
    this.level++;
    this.xp -= this.xpToLevel;
    this.xpToLevel = Math.floor(this.xpToLevel * 1.5);
    this.maxHp += 10;
    this.maxMp += 5;
    this.baseDamage += 2;
    this.hp = this.maxHp;
    this.mp = this.maxMp;
    if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast(`LEVEL UP! Level ${this.level}`);
    if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
  },

  update(delta) {
    if (this.dead) {
      this.respawnTimer -= delta;
      if (this.respawnTimer <= 0) {
        this.respawn();
      } else {
        const countdown = document.querySelector('#death-overlay .countdown');
        if (countdown) countdown.textContent = Math.ceil(this.respawnTimer);
      }
    } else {
      this.hp = Math.min(this.maxHp, this.hp + this.hpRegen * delta);
      this.mp = Math.min(this.maxMp, this.mp + this.mpRegen * delta);
      this.energy = Math.min(this.maxEnergy, this.energy + this.energyRegen * delta);
    }
    this.damageFlashTimer = Math.max(0, this.damageFlashTimer - delta);
    this.updateHUD();
  },

  updateHUD() {
    const hpFill = document.getElementById('hp-fill');
    const mpFill = document.getElementById('mp-fill');
    const xpFill = document.getElementById('xp-fill');
    const hpText = document.getElementById('hp-text');
    const mpText = document.getElementById('mp-text');
    const levelBadge = document.getElementById('level-badge');
    const energyFill = document.getElementById('energy-fill');
    const statsBar = document.getElementById('player-stats-bar');
    const vignette = document.getElementById('damage-vignette');

    if (hpFill) hpFill.style.width = `${(this.hp / this.maxHp) * 100}%`;
    if (mpFill) mpFill.style.width = `${(this.mp / this.maxMp) * 100}%`;
    if (xpFill) xpFill.style.width = `${(this.xp / this.xpToLevel) * 100}%`;
    if (hpText) hpText.textContent = `${Math.ceil(this.hp)}/${this.maxHp}`;
    if (mpText) mpText.textContent = `${Math.ceil(this.mp)}/${this.maxMp}`;
    if (levelBadge) levelBadge.textContent = this.level;
    if (energyFill) energyFill.style.width = `${(this.energy / this.maxEnergy) * 100}%`;

    if (statsBar) {
      if (this.hp < this.maxHp * 0.25) statsBar.classList.add('low-hp');
      else statsBar.classList.remove('low-hp');
    }
    if (vignette) vignette.style.opacity = this.damageFlashTimer;
  },

  getDamage() {
    return this.baseDamage;
  }
};
