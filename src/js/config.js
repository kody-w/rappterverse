// RAPPterverse Configuration
const REPO = 'kody-w/rappterverse';
const BRANCH = 'main';
const RAW = `https://raw.githubusercontent.com/${REPO}/${BRANCH}`;
const POLL_INTERVAL = 15000;

const WORLDS = {
    hub: {
        name: 'RAPPverse Hub', biome: 'Terra',
        sky: 0x0a0a1a, floor: 0x1a1a2e, accent: 0x00d4ff, grid: 0x0066ff, fog: 0x0a0a1a,
        bounds: { x: 15, z: 15 },
        orbitRadius: 30, orbitSpeed: 0.3, planetColor: 0x4488ff,
        landingTerrain: { ground: 0x3a8c3a, sky: 0x87CEEB, fog: 0x87CEEB }
    },
    arena: {
        name: 'Battle Arena', biome: 'Volcanic',
        sky: 0x1a0a0a, floor: 0x2a1515, accent: 0xff4545, grid: 0xff2200, fog: 0x1a0a0a,
        bounds: { x: 12, z: 12 },
        orbitRadius: 45, orbitSpeed: 0.2, planetColor: 0xff4422,
        landingTerrain: { ground: 0x2a1a1a, sky: 0x330000, fog: 0x330000 }
    },
    marketplace: {
        name: 'RAPPcoin Marketplace', biome: 'Desert',
        sky: 0x0a0a1a, floor: 0x1a1a0a, accent: 0xffcc00, grid: 0xffaa00, fog: 0x0a0a1a,
        bounds: { x: 15, z: 15 },
        orbitRadius: 60, orbitSpeed: 0.15, planetColor: 0xffaa00,
        landingTerrain: { ground: 0xc2a060, sky: 0xffcc99, fog: 0xffcc99 }
    },
    gallery: {
        name: 'Agent Gallery', biome: 'Crystal',
        sky: 0x0a1a1a, floor: 0x1a2a2a, accent: 0x00ffaa, grid: 0x00ff88, fog: 0x0a1a1a,
        bounds: { x: 12, z: 15 },
        orbitRadius: 75, orbitSpeed: 0.1, planetColor: 0x00ddaa,
        landingTerrain: { ground: 0xe8f4f8, sky: 0xddeeff, fog: 0xddeeff }
    },
    dungeon: {
        name: 'Forgotten Dungeon', biome: 'Abyss',
        sky: 0x050508, floor: 0x0d0d12, accent: 0x6a0dad, grid: 0x3a0066, fog: 0x050508,
        bounds: { x: 12, z: 12 },
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
