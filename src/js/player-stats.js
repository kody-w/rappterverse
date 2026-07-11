// Browser-local practice stats — never canonical RAPPcoin or shared world state
const PlayerStats = {
  hp: 100, maxHp: 100,
  mp: 50, maxMp: 50,
  energy: 100, maxEnergy: 100,
  xp: 0, xpToLevel: 100,
  level: 1,
  baseDamage: 20,
  gold: 0,
  totalGold: 0,
  kills: 0, deaths: 0, assists: 0,
  hpRegen: 1,
  mpRegen: 2,
  energyRegen: 5,
  dead: false,
  shielded: false,
  respawnTimer: 0,
  damageFlashTimer: 0,
  _lastDeathDisplay: -1,

  init() {
    this.hp = this.maxHp = 100;
    this.mp = this.maxMp = 50;
    this.energy = this.maxEnergy = 100;
    this.xp = 0; this.xpToLevel = 100;
    this.level = 1; this.baseDamage = 20;
    this.gold = 0; this.totalGold = 0;
    this.kills = 0; this.deaths = 0; this.assists = 0;
    this.hpRegen = 1; this.mpRegen = 2; this.energyRegen = 5;
    this.dead = false; this.shielded = false;
    this.respawnTimer = 0; this.damageFlashTimer = 0; this._lastDeathDisplay = -1;
  },

  takeDamage(amount) {
    if (this.dead || this.shielded) return;
    let dmg = amount;
    if (typeof Equipment !== 'undefined') {
      const stats = Equipment.getStats();
      dmg = Math.max(1, dmg - (stats.defense || 0) * 0.3);
      if (stats.dodgeChance && Math.random() < stats.dodgeChance) {
        if (typeof HUD !== 'undefined') HUD.showToast('DODGED!');
        return;
      }
    }
    this.hp = Math.max(0, this.hp - dmg);
    this.damageFlashTimer = 0.3;
    if (typeof Audio !== 'undefined' && Audio.playHit) Audio.playHit();
    if (this.hp <= 0) this.die();
  },

  die() {
    this.dead = true;
    this.deaths++;
    // Respawn timer scales with level (5s base + 2s per level)
    this.respawnTimer = 5 + this.level * 2;
    const overlay = document.getElementById('death-overlay');
    if (overlay) overlay.style.display = 'flex';
    const timerEl = document.getElementById('death-timer');
    if (timerEl) timerEl.textContent = 'Respawning in ' + Math.ceil(this.respawnTimer) + '...';
    // Echo narrative on death screen
    var deathNarr = document.getElementById('death-narrative');
    if (!deathNarr) {
      deathNarr = document.createElement('div');
      deathNarr.id = 'death-narrative';
      deathNarr.style.cssText = 'font-size:12px;color:rgba(255,255,255,0.5);font-family:monospace;margin-top:8px;max-width:400px;text-align:center;line-height:1.4;';
      if (overlay) overlay.appendChild(deathNarr);
    }
    if (typeof EchoEngine !== 'undefined') {
      var ef = EchoEngine.getCurrentFrame();
      if (ef && ef.echoes) {
        var narr = ef.echoes.L2 ? ef.echoes.L2.narrative : '';
        var tension = ef.echoes.L3 ? ef.echoes.L3.tension : 0;
        var mood = ef.echoes.L2 ? ef.echoes.L2.dominantMood : 'neutral';
        var deathText = narr;
        if (tension > 0.5) deathText += ' The world trembles with conflict.';
        else if (tension < 0.2) deathText += ' A quiet moment broken.';
        if (mood === 'desperate') deathText += ' Desperation hangs in the air.';
        else if (mood === 'thriving') deathText += ' Life persists around you.';
        deathNarr.textContent = deathText;
      }
    }
    if (typeof VFX !== 'undefined' && typeof WorldMode !== 'undefined' && WorldMode.player) {
      VFX.burst(WorldMode.player.mesh.position, 'kill');
      VFX.screenFlash('#ff0000', 0.5);
    }
    if (typeof Audio !== 'undefined' && Audio.playDeath) Audio.playDeath();
  },

  awardGold(amount, source) {
    this.gold += amount;
    if (this.gold % 50 === 0) this.save(); // auto-save every 50 gold
    this.totalGold += amount;
    if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast('+' + amount + ' Practice Gold' + (source ? ' (' + source + ')' : ''));
  },

  respawn() {
    this.dead = false;
    this.hp = this.maxHp;
    this.mp = this.maxMp;
    this.energy = this.maxEnergy;
    this._echoXpBonus = 1; // Reset echo bonus on respawn
    const overlay = document.getElementById('death-overlay');
    if (overlay) overlay.style.display = 'none';
    // Echo-reactive spawn position — during tension, spawn near explorer base for safety
    var spawnX = 0, spawnZ = 5;
    if (typeof EchoEngine !== 'undefined') {
      var ef = EchoEngine.getCurrentFrame();
      if (ef && ef.echoes && ef.echoes.L3 && ef.echoes.L3.tension > 0.5) {
        // Spawn near explorer throne (safe zone)
        var w = typeof WORLDS !== 'undefined' && typeof GameState !== 'undefined' ? WORLDS[GameState.currentWorld] : null;
        if (w) { spawnX = -w.bounds.x * 0.7; spawnZ = -w.bounds.z * 0.7; }
      }
    }
    if (typeof WorldMode !== 'undefined' && WorldMode.player && WorldMode.player.mesh) {
      WorldMode.player.mesh.position.set(spawnX, 0, spawnZ);
    }
    // Respawn VFX
    if (typeof VFX !== 'undefined' && typeof WorldMode !== 'undefined' && WorldMode.player) {
      VFX.burst(WorldMode.player.mesh.position, 'levelUp', { count: 15 });
      VFX.screenFlash('#00ffff', 0.3);
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

  _echoXpBonus: 1,
  awardXp(amount) {
    var xp = Math.round(amount * this._echoXpBonus);
    this.xp += xp;
    var bonusStr = this._echoXpBonus > 1 ? ' (echo bonus!)' : '';
    if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast('+' + xp + ' Practice XP' + bonusStr);
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
    if (typeof VFX !== 'undefined' && typeof WorldMode !== 'undefined' && WorldMode.player) {
      VFX.burst(WorldMode.player.mesh.position, 'levelUp');
      VFX.screenFlash('#ffd700', 0.3);
    }
    if (typeof Audio !== 'undefined' && Audio.playWaveHorn) Audio.playWaveHorn();
    if (typeof Abilities !== 'undefined' && Abilities.awardSkillPoint) Abilities.awardSkillPoint();
    this.save();
  },

  update(delta) {
    if (this.dead) {
      this.respawnTimer -= delta;
      var displayVal = Math.ceil(this.respawnTimer);
      if (displayVal !== this._lastDeathDisplay) {
        this._lastDeathDisplay = displayVal;
        var timerEl = document.getElementById('death-timer');
        if (timerEl) timerEl.textContent = 'Respawning in ' + displayVal + '...';
      }
      if (this.respawnTimer <= 0) this.respawn();
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
    const energyText = document.getElementById('energy-text');
    if (energyText) energyText.textContent = `${Math.ceil(this.energy)}/${this.maxEnergy}`;
    const xpText = document.getElementById('xp-text');
    if (xpText) xpText.textContent = `${this.xp}/${this.xpToLevel}`;
    // Gold display
    const goldEl = document.getElementById('gold-display');
    if (goldEl) goldEl.textContent = this.gold + ' PG';
    // KDA
    const kdaEl = document.getElementById('kda-display');
    if (kdaEl) kdaEl.textContent = this.kills + '/' + this.deaths + '/' + this.assists;

    if (statsBar) {
      if (this.hp < this.maxHp * 0.25) statsBar.classList.add('low-hp');
      else statsBar.classList.remove('low-hp');
    }
    if (vignette) vignette.style.opacity = this.damageFlashTimer;
  },

  save() {
    try {
      localStorage.setItem('rappterverse-player', JSON.stringify({
        level: this.level, xp: this.xp, xpToLevel: this.xpToLevel,
        gold: this.gold, totalGold: this.totalGold,
        kills: this.kills, deaths: this.deaths, assists: this.assists,
        baseDamage: this.baseDamage, maxHp: this.maxHp, maxMp: this.maxMp,
        savedAt: new Date().toISOString()
      }));
    } catch(e) {}
  },

  load() {
    try {
      var s = localStorage.getItem('rappterverse-player');
      if (!s) return;
      var d = JSON.parse(s);
      this.level = d.level || 1;
      this.xp = d.xp || 0;
      this.xpToLevel = d.xpToLevel || 100;
      this.gold = d.gold || 0;
      this.totalGold = d.totalGold || 0;
      this.kills = d.kills || 0;
      this.deaths = d.deaths || 0;
      this.assists = d.assists || 0;
      this.baseDamage = d.baseDamage || 20;
      this.maxHp = d.maxHp || 100;
      this.maxMp = d.maxMp || 50;
      this.hp = this.maxHp;
      this.mp = this.maxMp;
      if (typeof HUD !== "undefined") HUD.showToast("Local practice profile loaded — Level " + this.level);
    } catch(e) {}
  },

  getDamage() {
    let dmg = this.baseDamage;
    if (typeof Equipment !== 'undefined') {
      const stats = Equipment.getStats();
      dmg += stats.damage || 0;
    }
    return dmg;
  },

  // Ability damage scales with level (base + 15% per level)
  getAbilityDamage(baseDmg) {
    return Math.round(baseDmg * (1 + (this.level - 1) * 0.15));
  },

  // GPM calculation
  getGPM() {
    if (!this._gameStartTime) this._gameStartTime = Date.now();
    const minutes = (Date.now() - this._gameStartTime) / 60000;
    return minutes > 0 ? Math.round(this.totalGold / minutes) : 0;
  }
};
