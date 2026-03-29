// Procedural audio system — Web Audio API only, no external files
const Audio = {
  ctx: null, masterGain: null, musicGain: null, sfxGain: null,
  initialized: false, _ambientOscs: [], _ambientGains: [],
  _intensityOsc: null, _currentBiome: null,

  _mtof(m) { return 440 * Math.pow(2, (m - 69) / 12); },

  init() {
    if (this.initialized) return;
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.value = 0.3;
    this.masterGain.connect(this.ctx.destination);
    this.musicGain = this.ctx.createGain();
    this.musicGain.gain.value = 0.2;
    this.musicGain.connect(this.masterGain);
    this.sfxGain = this.ctx.createGain();
    this.sfxGain.gain.value = 0.5;
    this.sfxGain.connect(this.masterGain);
    const resume = () => { if (this.ctx && this.ctx.state === 'suspended') this.ctx.resume(); };
    document.addEventListener('click', resume, { once: true });
    document.addEventListener('keydown', resume, { once: true });
    this.initialized = true;
  },

  _ensureCtx() { if (!this.initialized) this.init(); },

  _noiseBuffer(dur) {
    const len = this.ctx.sampleRate * dur;
    const buf = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return buf;
  },

  // --- Ambient Music ---
  _biomeChord(biome) {
    const chords = {
      Terra:    { notes: [48,52,55],    wave: 'triangle', filter: 0,   shimmer: false },
      Volcanic: { notes: [48,51,55],    wave: 'sawtooth', filter: 400, shimmer: false },
      Desert:   { notes: [50,55,57],    wave: 'sine',     filter: 0,   shimmer: false },
      Crystal:  { notes: [52,56,59,63], wave: 'sine',     filter: 0,   shimmer: true  },
      Abyss:    { notes: [48,51,54],    wave: 'triangle', filter: 250, shimmer: false },
    };
    return chords[biome] || { notes: [45,48,52], wave: 'triangle', filter: 0, shimmer: false };
  },

  startAmbient(biome) {
    this._ensureCtx();
    if (this._currentBiome === biome) return;
    this.stopAmbient();
    this._currentBiome = biome;
    const ch = this._biomeChord(biome), t = this.ctx.currentTime;

    ch.notes.forEach((midi, i) => {
      const osc = this.ctx.createOscillator();
      osc.type = ch.wave;
      osc.frequency.value = this._mtof(midi);
      // LFO tremolo
      const lfo = this.ctx.createOscillator();
      const lfoG = this.ctx.createGain();
      lfo.type = 'sine';
      lfo.frequency.value = 0.05 + i * 0.04;
      lfoG.gain.value = 0.15;
      lfo.connect(lfoG);
      const oscG = this.ctx.createGain();
      oscG.gain.value = 0.0;
      oscG.gain.linearRampToValueAtTime(0.5 / ch.notes.length, t + 2);
      lfoG.connect(oscG.gain);
      let dest = this.musicGain;
      if (ch.filter > 0) {
        const lpf = this.ctx.createBiquadFilter();
        lpf.type = 'lowpass';
        lpf.frequency.value = ch.filter;
        lpf.Q.value = 1;
        lpf.connect(this.musicGain);
        dest = lpf;
      }
      osc.connect(oscG); oscG.connect(dest);
      osc.start(t); lfo.start(t);
      this._ambientOscs.push(osc, lfo);
      this._ambientGains.push(oscG);
    });

    // Crystal shimmer: high quiet oscillator with fast LFO
    if (ch.shimmer) {
      const sh = this.ctx.createOscillator();
      sh.type = 'sine'; sh.frequency.value = this._mtof(76);
      const shG = this.ctx.createGain();
      shG.gain.value = 0.0;
      shG.gain.linearRampToValueAtTime(0.06, t + 2);
      const shLfo = this.ctx.createOscillator();
      shLfo.type = 'sine'; shLfo.frequency.value = 3;
      const shLG = this.ctx.createGain();
      shLG.gain.value = 0.06;
      shLfo.connect(shLG); shLG.connect(shG.gain);
      sh.connect(shG); shG.connect(this.musicGain);
      sh.start(t); shLfo.start(t);
      this._ambientOscs.push(sh, shLfo);
      this._ambientGains.push(shG);
    }
  },

  stopAmbient() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this._ambientGains.forEach(g => {
      g.gain.cancelScheduledValues(t);
      g.gain.setValueAtTime(g.gain.value, t);
      g.gain.linearRampToValueAtTime(0, t + 2);
    });
    const oscs = this._ambientOscs;
    setTimeout(() => oscs.forEach(o => { try { o.stop(); o.disconnect(); } catch(_){} }), 2200);
    this._ambientOscs = [];
    this._ambientGains = [];
    this._currentBiome = null;
  },

  setIntensity(level) {
    this._ensureCtx();
    const v = Math.max(0, Math.min(1, level));
    this.musicGain.gain.setTargetAtTime(0.2 + v * 0.15, this.ctx.currentTime, 0.3);
    if (v > 0.6 && !this._intensityOsc) {
      const osc = this.ctx.createOscillator();
      osc.type = 'square'; osc.frequency.value = 2;
      const g = this.ctx.createGain();
      g.gain.value = 0.04 * v;
      osc.connect(g); g.connect(this.musicGain); osc.start();
      this._intensityOsc = { osc, gain: g };
    } else if (v <= 0.6 && this._intensityOsc) {
      try { this._intensityOsc.osc.stop(); this._intensityOsc.osc.disconnect(); } catch(_){}
      this._intensityOsc = null;
    }
    if (this._intensityOsc)
      this._intensityOsc.gain.gain.setTargetAtTime(0.04 * v, this.ctx.currentTime, 0.2);
  },

  // --- SFX ---
  playClick() {
    this._ensureCtx();
    const t = this.ctx.currentTime, osc = this.ctx.createOscillator();
    osc.type = 'triangle'; osc.frequency.value = 800;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.4, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.05);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.05);
  },

  playWarp() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(200, t);
    osc.frequency.exponentialRampToValueAtTime(2000, t + 1.5);
    const lpf = this.ctx.createBiquadFilter();
    lpf.type = 'lowpass';
    lpf.frequency.setValueAtTime(400, t);
    lpf.frequency.exponentialRampToValueAtTime(4000, t + 1.5);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.3, t);
    g.gain.setValueAtTime(0.3, t + 1.2);
    g.gain.exponentialRampToValueAtTime(0.001, t + 1.5);
    osc.connect(lpf); lpf.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 1.5);
    // Noise burst at end
    const ns = this.ctx.createBufferSource();
    ns.buffer = this._noiseBuffer(0.3);
    const ng = this.ctx.createGain();
    ng.gain.setValueAtTime(0.0, t + 1.2);
    ng.gain.linearRampToValueAtTime(0.3, t + 1.3);
    ng.gain.exponentialRampToValueAtTime(0.001, t + 1.5);
    ns.connect(ng); ng.connect(this.sfxGain);
    ns.start(t + 1.2); ns.stop(t + 1.5);
  },

  playLanding() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = 'sine'; osc.frequency.value = 60;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.5, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.5);
    const ns = this.ctx.createBufferSource();
    ns.buffer = this._noiseBuffer(0.5);
    const ng = this.ctx.createGain();
    ng.gain.setValueAtTime(0.25, t);
    ng.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    ns.connect(ng); ng.connect(this.sfxGain);
    ns.start(t); ns.stop(t + 0.5);
  },

  playHit() {
    this._ensureCtx();
    const t = this.ctx.currentTime, osc = this.ctx.createOscillator();
    osc.type = 'square';
    osc.frequency.setValueAtTime(200, t);
    osc.frequency.exponentialRampToValueAtTime(80, t + 0.1);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.5, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.1);
  },

  playWaveHorn() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    [180, 185].forEach(freq => {
      const osc = this.ctx.createOscillator();
      osc.type = 'sawtooth'; osc.frequency.value = freq;
      const lpf = this.ctx.createBiquadFilter();
      lpf.type = 'lowpass'; lpf.frequency.value = 600;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0.001, t);
      g.gain.linearRampToValueAtTime(0.3, t + 0.1);
      g.gain.setValueAtTime(0.3, t + 0.5);
      g.gain.linearRampToValueAtTime(0.001, t + 0.8);
      osc.connect(lpf); lpf.connect(g); g.connect(this.sfxGain);
      osc.start(t); osc.stop(t + 0.8);
    });
  },

  playTowerShot() {
    this._ensureCtx();
    const t = this.ctx.currentTime, osc = this.ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(1000, t);
    osc.frequency.exponentialRampToValueAtTime(200, t + 0.15);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.4, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.15);
  },

  playExplosion() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const ns = this.ctx.createBufferSource();
    ns.buffer = this._noiseBuffer(0.3);
    const bpf = this.ctx.createBiquadFilter();
    bpf.type = 'bandpass'; bpf.frequency.value = 200; bpf.Q.value = 0.8;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.6, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.3);
    ns.connect(bpf); bpf.connect(g); g.connect(this.sfxGain);
    ns.start(t); ns.stop(t + 0.3);
  },

  playPoke() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    // Friendly two-tone chirp
    const osc = this.ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(600, t);
    osc.frequency.setValueAtTime(800, t + 0.06);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.35, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.15);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.15);
  },

  playAbility() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    // Rising chime
    const osc = this.ctx.createOscillator();
    osc.type = 'triangle';
    osc.frequency.setValueAtTime(400, t);
    osc.frequency.exponentialRampToValueAtTime(1200, t + 0.2);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.3, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.25);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.25);
  },

  playPickup() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    [523, 659, 784].forEach((freq, i) => {
      const osc = this.ctx.createOscillator();
      osc.type = 'sine'; osc.frequency.value = freq;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0, t + i * 0.05);
      g.gain.linearRampToValueAtTime(0.25, t + i * 0.05 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.001, t + i * 0.05 + 0.12);
      osc.connect(g); g.connect(this.sfxGain);
      osc.start(t + i * 0.05); osc.stop(t + i * 0.05 + 0.12);
    });
  },

  playFootstep() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const ns = this.ctx.createBufferSource();
    ns.buffer = this._noiseBuffer(0.04);
    const bpf = this.ctx.createBiquadFilter();
    bpf.type = 'bandpass'; bpf.frequency.value = 300 + Math.random() * 200; bpf.Q.value = 1;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.08, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.04);
    ns.connect(bpf); bpf.connect(g); g.connect(this.sfxGain);
    ns.start(t); ns.stop(t + 0.04);
  },

  playDeath() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = 'sawtooth';
    osc.frequency.setValueAtTime(400, t);
    osc.frequency.exponentialRampToValueAtTime(60, t + 0.8);
    const lpf = this.ctx.createBiquadFilter();
    lpf.type = 'lowpass'; lpf.frequency.value = 500;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.4, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.8);
    osc.connect(lpf); lpf.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.8);
  },

  playMenuOpen() {
    this._ensureCtx();
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(300, t);
    osc.frequency.exponentialRampToValueAtTime(500, t + 0.08);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.2, t);
    g.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
    osc.connect(g); g.connect(this.sfxGain);
    osc.start(t); osc.stop(t + 0.1);
  },

cleanup() {
    this.stopAmbient();
    this.stopEnvironment();
    if (this._intensityOsc) {
      try { this._intensityOsc.osc.stop(); this._intensityOsc.osc.disconnect(); } catch(_){}
      this._intensityOsc = null;
    }
    if (this.ctx) {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
    this.masterGain = null;
    this.musicGain = null;
    this.sfxGain = null;
    this.initialized = false;
    this._currentBiome = null;
  },

  // --- Environmental Layers ---
  _envNodes: [],

  startEnvironment(biome) {
    this._ensureCtx();
    this.stopEnvironment();
    const t = this.ctx.currentTime;

    if (biome === 'Terra') {
      this._addEnvNoise(0.06, 200, 800, 0.8);
      this._addEnvChirp(1200, 2400, 0.04, 3, 8);
      this._addEnvNoise(0.02, 2000, 4000, 0.3);
    } else if (biome === 'Volcanic') {
      this._addEnvNoise(0.08, 30, 120, 1.5);
      this._addEnvCrackle(0.04, 800, 2000);
      this._addEnvNoise(0.03, 3000, 6000, 0.4);
    } else if (biome === 'Desert') {
      this._addEnvNoise(0.07, 150, 600, 1.0);
      this._addEnvNoise(0.015, 4000, 8000, 0.3);
    } else if (biome === 'Crystal') {
      this._addEnvChirp(2000, 4000, 0.03, 2, 6);
      this._addEnvCrackle(0.025, 100, 400);
      this._addEnvNoise(0.04, 200, 500, 0.6);
    } else if (biome === 'Abyss') {
      const osc = this.ctx.createOscillator();
      osc.type = 'sine'; osc.frequency.value = 40;
      const g = this.ctx.createGain();
      g.gain.setValueAtTime(0, t);
      g.gain.linearRampToValueAtTime(0.06, t + 3);
      const lfo = this.ctx.createOscillator();
      lfo.type = 'sine'; lfo.frequency.value = 0.1;
      const lg = this.ctx.createGain(); lg.gain.value = 15;
      lfo.connect(lg); lg.connect(osc.frequency);
      osc.connect(g); g.connect(this.musicGain);
      osc.start(t); lfo.start(t);
      this._envNodes.push({ nodes: [osc, lfo], gain: g });
      this._addEnvCrackle(0.03, 300, 800);
      this._addEnvChirp(800, 1600, 0.02, 4, 12);
    }
  },

  _addEnvNoise(vol, loFreq, hiFreq, q) {
    const t = this.ctx.currentTime;
    const ns = this.ctx.createBufferSource();
    ns.buffer = this._noiseBuffer(30); ns.loop = true;
    const bpf = this.ctx.createBiquadFilter();
    bpf.type = 'bandpass'; bpf.frequency.value = (loFreq + hiFreq) / 2; bpf.Q.value = q || 1;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 3);
    const lfo = this.ctx.createOscillator();
    lfo.type = 'sine'; lfo.frequency.value = 0.08 + Math.random() * 0.1;
    const lg = this.ctx.createGain(); lg.gain.value = vol * 0.4;
    lfo.connect(lg); lg.connect(g.gain);
    ns.connect(bpf); bpf.connect(g); g.connect(this.musicGain);
    ns.start(t); lfo.start(t);
    this._envNodes.push({ nodes: [ns, lfo], gain: g });
  },

  _addEnvChirp(loFreq, hiFreq, vol, minInterval, maxInterval) {
    const self = this;
    function chirp() {
      if (!self.ctx || !self._envNodes) return;
      const t = self.ctx.currentTime;
      const freq = loFreq + Math.random() * (hiFreq - loFreq);
      const osc = self.ctx.createOscillator();
      osc.type = 'sine'; osc.frequency.value = freq;
      osc.frequency.setValueAtTime(freq, t);
      osc.frequency.exponentialRampToValueAtTime(freq * (0.8 + Math.random() * 0.4), t + 0.1);
      const g = self.ctx.createGain();
      g.gain.setValueAtTime(vol, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + 0.08 + Math.random() * 0.1);
      osc.connect(g); g.connect(self.musicGain);
      osc.start(t); osc.stop(t + 0.2);
      // Echo-reactive chirp interval: tension makes chirps more frequent and louder
      var echoMod = 1;
      if (typeof EchoEngine !== 'undefined') {
        var ef = EchoEngine.getCurrentFrame();
        if (ef && ef.echoes && ef.echoes.L3) echoMod = 1 - ef.echoes.L3.tension * 0.5; // Up to 50% faster
      }
      const next = (minInterval + Math.random() * (maxInterval - minInterval)) * 1000 * Math.max(0.3, echoMod);
      self._chirpTimer = setTimeout(chirp, next);
    }
    self._chirpTimer = setTimeout(chirp, minInterval * 1000);
    this._envNodes.push({ timer: true });
  },

  _addEnvCrackle(vol, loFreq, hiFreq) {
    const self = this;
    function crack() {
      if (!self.ctx || !self._envNodes) return;
      const t = self.ctx.currentTime;
      const ns = self.ctx.createBufferSource();
      ns.buffer = self._noiseBuffer(0.06);
      const bpf = self.ctx.createBiquadFilter();
      bpf.type = 'bandpass'; bpf.frequency.value = loFreq + Math.random() * (hiFreq - loFreq); bpf.Q.value = 2;
      const g = self.ctx.createGain();
      g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.06);
      ns.connect(bpf); bpf.connect(g); g.connect(self.musicGain);
      ns.start(t); ns.stop(t + 0.06);
      // Echo-reactive crackle: tension makes crackles more frequent
      var crackEcho = 1;
      if (typeof EchoEngine !== 'undefined') {
        var ef2 = EchoEngine.getCurrentFrame();
        if (ef2 && ef2.echoes && ef2.echoes.L3) crackEcho = 1 - ef2.echoes.L3.tension * 0.4;
      }
      self._crackleTimer = setTimeout(crack, (500 + Math.random() * 2000) * Math.max(0.3, crackEcho));
    }
    self._crackleTimer = setTimeout(crack, 1000);
    this._envNodes.push({ timer: true });
  },

  stopEnvironment() {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this._envNodes.forEach(e => {
      if (e.gain) {
        e.gain.gain.cancelScheduledValues(t);
        e.gain.gain.setValueAtTime(e.gain.gain.value, t);
        e.gain.gain.linearRampToValueAtTime(0, t + 1);
      }
      if (e.nodes) setTimeout(() => e.nodes.forEach(n => { try { n.stop(); n.disconnect(); } catch(_){} }), 1200);
    });
    this._envNodes = [];
    clearTimeout(this._chirpTimer);
    clearTimeout(this._crackleTimer);
  },

  // --- Echo-reactive audio modulation ---
  _echoAudioTimer: 0,
  updateEchoAudio(delta) {
    if (!this.initialized || !this.ctx) return;
    if (typeof EchoEngine === 'undefined') return;
    this._echoAudioTimer -= delta;
    if (this._echoAudioTimer > 0) return;
    this._echoAudioTimer = 0.5; // Update twice per second

    var ef = EchoEngine.getCurrentFrame();
    if (!ef || !ef.echoes || !ef.echoes.L3) return;
    var L3 = ef.echoes.L3;

    // Drive music intensity from echo tension
    this.setIntensity(L3.tension * 0.8 + L3.vitality * 0.2);

    // Modulate ambient LFO speeds — faster tremolo when tense
    var lfoSpeedMult = 1 + L3.tension * 3; // 1x calm → 4x tense
    for (var i = 0; i < this._ambientOscs.length; i++) {
      var osc = this._ambientOscs[i];
      // Even-indexed oscs are music, odd are LFOs
      if (i % 2 === 1 && osc.frequency) {
        var baseFreq = 0.05 + (Math.floor(i / 2)) * 0.04;
        osc.frequency.setTargetAtTime(baseFreq * lfoSpeedMult, this.ctx.currentTime, 0.5);
      }
    }

    // Modulate ambient gain by vitality (world alive = louder music)
    if (this.musicGain) {
      var targetGain = 0.15 + L3.vitality * 0.1 + L3.socialEnergy * 0.05;
      this.musicGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, 0.5);
    }
  },

  // --- Integration ---
  onModeChange(newMode) {
    this._ensureCtx();
    switch (newMode) {
      case 'boot':
        this.stopAmbient(); this.setIntensity(0); break;
      case 'galaxy':
      case 'bridge':
        this.stopEnvironment(); this.startAmbient('galaxy'); this.setIntensity(0); break;
      case 'approach':
        this.setIntensity(0.4); break;
      case 'landing':
        this.setIntensity(0); break;
      case 'world': {
        const biome = (typeof WORLDS !== 'undefined' && typeof GameState !== 'undefined'
          && WORLDS[GameState.currentWorld]) ? WORLDS[GameState.currentWorld].biome : 'Terra';
        this.startAmbient(biome); this.startEnvironment(biome); this.setIntensity(0); break;
      }
      default:
        this.startAmbient('galaxy'); this.setIntensity(0);
    }
  }
};
