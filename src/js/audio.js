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
    document.addEventListener('click', resume);
    document.addEventListener('keydown', resume);
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

  // --- Integration ---
  onModeChange(newMode) {
    this._ensureCtx();
    switch (newMode) {
      case 'boot':
        this.stopAmbient(); this.setIntensity(0); break;
      case 'galaxy':
      case 'bridge':
        this.startAmbient('galaxy'); this.setIntensity(0); break;
      case 'approach':
        this.setIntensity(0.4); break;
      case 'landing':
        this.setIntensity(0); break;
      case 'world': {
        const biome = (typeof WORLDS !== 'undefined' && typeof GameState !== 'undefined'
          && WORLDS[GameState.currentWorld]) ? WORLDS[GameState.currentWorld].biome : 'Terra';
        this.startAmbient(biome); this.setIntensity(0); break;
      }
      default:
        this.startAmbient('galaxy'); this.setIntensity(0);
    }
  }
};
