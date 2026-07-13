// RAPPterverse Configuration
const REPO = 'kody-w/rappterverse';
const BRANCH = 'main';            // Canonical world state and Pages source
const RAW = `https://raw.githubusercontent.com/${REPO}/${BRANCH}`;
const POLL_INTERVAL = 15000;
const CLIENT_AUTHORITY = Object.freeze({
    world: 'canonical-main',
    gameplay: 'local-practice'
});

function escapeHTML(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function(char) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[char];
    });
}

const WORLDS = {
    hub: {
        name: 'RAPPverse Hub', biome: 'Terra',
        sky: 0x0a0a1a, floor: 0x1a1a2e, accent: 0x00d4ff, grid: 0x0066ff, fog: 0x0a0a1a,
        bounds: { x: 150, z: 150 },
        orbitRadius: 30, orbitSpeed: 0.3, planetColor: 0x4488ff,
        landingTerrain: { ground: 0x3a8c3a, sky: 0x87CEEB, fog: 0x87CEEB }
    },
    arena: {
        name: 'Battle Arena', biome: 'Volcanic',
        sky: 0x1a0a0a, floor: 0x2a1515, accent: 0xff4545, grid: 0xff2200, fog: 0x1a0a0a,
        bounds: { x: 120, z: 120 },
        orbitRadius: 45, orbitSpeed: 0.2, planetColor: 0xff4422,
        landingTerrain: { ground: 0x2a1a1a, sky: 0x330000, fog: 0x330000 }
    },
    marketplace: {
        name: 'RAPPcoin Marketplace', biome: 'Desert',
        sky: 0x0a0a1a, floor: 0x1a1a0a, accent: 0xffcc00, grid: 0xffaa00, fog: 0x0a0a1a,
        bounds: { x: 150, z: 150 },
        orbitRadius: 60, orbitSpeed: 0.15, planetColor: 0xffaa00,
        landingTerrain: { ground: 0xc2a060, sky: 0xffcc99, fog: 0xffcc99 }
    },
    gallery: {
        name: 'Agent Gallery', biome: 'Crystal',
        sky: 0x0a1a1a, floor: 0x1a2a2a, accent: 0x00ffaa, grid: 0x00ff88, fog: 0x0a1a1a,
        bounds: { x: 120, z: 150 },
        orbitRadius: 75, orbitSpeed: 0.1, planetColor: 0x00ddaa,
        landingTerrain: { ground: 0xe8f4f8, sky: 0xddeeff, fog: 0xddeeff }
    },
    dungeon: {
        name: 'Forgotten Dungeon', biome: 'Abyss',
        sky: 0x050508, floor: 0x0d0d12, accent: 0x6a0dad, grid: 0x3a0066, fog: 0x050508,
        bounds: { x: 120, z: 120 },
        orbitRadius: 90, orbitSpeed: 0.08, planetColor: 0x6a0dad,
        landingTerrain: { ground: 0x1a1020, sky: 0x0a0510, fog: 0x0a0510 }
    }
};

const WORLD_IDS = ['hub', 'arena', 'marketplace', 'gallery', 'dungeon'];

// Deterministic seeded random (used for procedural generation)
function seededRandom(seed) {
    let s = 0;
    for (let i = 0; i < seed.length; i++) s = ((s << 5) - s + seed.charCodeAt(i)) | 0;
    return function() {
        s = (s * 1103515245 + 12345) & 0x7fffffff;
        return s / 0x7fffffff;
    };
}

// ──── 2D Gradient Noise (Perlin-style) ────
function createNoise2D(seed) {
    const rng = seededRandom(String(seed));
    const perm = new Uint8Array(512);
    const gx = new Float32Array(256);
    const gy = new Float32Array(256);
    for (let i = 0; i < 256; i++) {
        perm[i] = i;
        const a = rng() * Math.PI * 2;
        gx[i] = Math.cos(a); gy[i] = Math.sin(a);
    }
    for (let i = 255; i > 0; i--) {
        const j = (rng() * (i + 1)) | 0;
        const t = perm[i]; perm[i] = perm[j]; perm[j] = t;
    }
    for (let i = 0; i < 256; i++) perm[i + 256] = perm[i];
    function fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }
    function noise(x, y) {
        const xi = Math.floor(x) & 255, yi = Math.floor(y) & 255;
        const xf = x - Math.floor(x), yf = y - Math.floor(y);
        const u = fade(xf), v = fade(yf);
        const p00 = perm[perm[xi] + yi], p10 = perm[perm[xi + 1] + yi];
        const p01 = perm[perm[xi] + yi + 1], p11 = perm[perm[xi + 1] + yi + 1];
        const d00 = gx[p00] * xf + gy[p00] * yf;
        const d10 = gx[p10] * (xf - 1) + gy[p10] * yf;
        const d01 = gx[p01] * xf + gy[p01] * (yf - 1);
        const d11 = gx[p11] * (xf - 1) + gy[p11] * (yf - 1);
        return (d00 + u * (d10 - d00)) + v * ((d01 + u * (d11 - d01)) - (d00 + u * (d10 - d00)));
    }
    return {
        noise: noise,
        fbm: function(x, y, oct, lac, gain) {
            oct = oct || 4; lac = lac || 2; gain = gain || 0.5;
            var s = 0, a = 1, f = 1, m = 0;
            for (var i = 0; i < oct; i++) { s += noise(x * f, y * f) * a; m += a; a *= gain; f *= lac; }
            return s / m;
        },
        ridged: function(x, y, oct, lac, gain) {
            oct = oct || 4; lac = lac || 2; gain = gain || 0.5;
            var s = 0, a = 1, f = 1, m = 0;
            for (var i = 0; i < oct; i++) { s += (1 - Math.abs(noise(x * f, y * f))) * a; m += a; a *= gain; f *= lac; }
            return s / m;
        }
    };
}

// ──── Biome Terrain Profiles ────
const BIOME_PROFILES = {
    Terra: {
        noiseScale: 8, octaves: 5, lacunarity: 2, gain: 0.45, heightScale: 7,
        color: function(t, h) {
            if (h < 0.3) return [0.12, 0.28, 0.15];
            if (t < 0.35) return [0.15, 0.38, 0.12];
            if (t < 0.55) return [0.22, 0.45, 0.16];
            if (t < 0.75) return [0.42, 0.34, 0.18];
            return [0.55, 0.52, 0.48];
        }
    },
    Volcanic: {
        noiseScale: 6, octaves: 4, lacunarity: 2.5, gain: 0.4, heightScale: 10,
        color: function(t, h) {
            if (h < 0.5) return [0.6, 0.12, 0.0];
            if (t < 0.3) return [0.12, 0.06, 0.04];
            if (t < 0.6) return [0.18, 0.1, 0.06];
            return [0.28, 0.14, 0.08];
        }
    },
    Desert: {
        noiseScale: 5, octaves: 3, lacunarity: 2, gain: 0.55, heightScale: 8,
        color: function(t, h) {
            if (t < 0.3) return [0.72, 0.56, 0.32];
            if (t < 0.5) return [0.82, 0.66, 0.4];
            if (t < 0.7) return [0.88, 0.72, 0.46];
            return [0.65, 0.5, 0.3];
        }
    },
    Crystal: {
        noiseScale: 7, octaves: 5, lacunarity: 2, gain: 0.5, heightScale: 6,
        color: function(t, h) {
            if (h < 0.3) return [0.45, 0.68, 0.78];
            if (t < 0.4) return [0.55, 0.75, 0.85];
            if (t < 0.7) return [0.72, 0.84, 0.92];
            return [0.88, 0.92, 0.97];
        }
    },
    Abyss: {
        noiseScale: 6, octaves: 4, lacunarity: 2.2, gain: 0.45, heightScale: 9,
        color: function(t, h) {
            if (h < -1) return [0.15, 0.0, 0.22];
            if (t < 0.3) return [0.06, 0.04, 0.1];
            if (t < 0.6) return [0.1, 0.06, 0.15];
            return [0.15, 0.08, 0.22];
        }
    }
};

// ──── World Seed System (data sloshing → terrain) ────
const WorldSeed = {
    _overrides: {},

    init: function() {
        try {
            var s = localStorage.getItem('rappterverse-seeds');
            if (s) this._overrides = JSON.parse(s);
        } catch(e) {}
    },

    _hash: function(str) {
        var h = 0;
        for (var i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
        return h;
    },

    getSeed: function(worldId) {
        if (this._overrides[worldId] !== undefined) return this._overrides[worldId];
        return this.compute(worldId);
    },

    compute: function(worldId) {
        var gs = GameState.data.gameState || {};
        var ws = gs.worlds && gs.worlds[worldId] ? gs.worlds[worldId] : {};
        var fc = GameState.data.frameCounter || {};
        var frame = fc.frame || 0;
        var pop = ws.population || 0;
        var trend = (gs.economy && gs.economy.market_trend) ? gs.economy.market_trend : 'stable';
        // Universe-level: frame epoch shifts all worlds
        var h = this._hash(worldId + '-terrain-v2');
        h = (h ^ ((Math.floor(frame / 12) * 2654435761) | 0)) | 0;
        // Planet-level: population shapes local terrain
        h = (h ^ ((Math.floor(pop / 5) * 40503) | 0)) | 0;
        // Economy-level: market trend shifts palette
        h = (h ^ this._hash(trend)) | 0;
        return Math.abs(h);
    },

    setSeed: function(worldId, seed) {
        this._overrides[worldId] = seed;
        try { localStorage.setItem('rappterverse-seeds', JSON.stringify(this._overrides)); } catch(e) {}
    },

    clearSeed: function(worldId) {
        delete this._overrides[worldId];
        try { localStorage.setItem('rappterverse-seeds', JSON.stringify(this._overrides)); } catch(e) {}
    },

    exportWorld: function(worldId) {
        var w = WORLDS[worldId];
        var gs = GameState.data.gameState || {};
        var fc = GameState.data.frameCounter || {};
        return {
            version: 1, worldId: worldId, seed: this.getSeed(worldId),
            name: w.name, biome: w.biome,
            exportedAt: new Date().toISOString(),
            state: {
                frame: fc.frame || 0,
                population: (gs.worlds && gs.worlds[worldId]) ? gs.worlds[worldId].population : 0,
                economy: (gs.economy && gs.economy.market_trend) ? gs.economy.market_trend : 'stable',
                weather: (gs.worlds && gs.worlds[worldId]) ? gs.worlds[worldId].weather : 'clear'
            }
        };
    },

    importWorld: function(json) {
        if (!json || !json.worldId || json.seed === undefined) return null;
        this.setSeed(json.worldId, json.seed);
        return json.worldId;
    }
};
