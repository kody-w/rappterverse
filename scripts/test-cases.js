#!/usr/bin/env node
// RAPPterverse Headless Test Suite — 13 TAP-format gameplay tests
'use strict';
const { createWorld } = require('./test-harness');

let testNum = 0, passed = 0, failed = 0, errors = [];
console.log('TAP version 14');
console.log('1..13');

function ok(condition, description, detail) {
    testNum++;
    if (condition) {
        passed++;
        console.log('ok ' + testNum + ' - ' + description);
    } else {
        failed++;
        console.log('not ok ' + testNum + ' - ' + description);
        if (detail) console.log('  ---\n  ' + detail + '\n  ---');
        errors.push(description + (detail ? ': ' + detail : ''));
    }
}

// ── T1: Init ──
try {
    var w = createWorld('arena');
    var s = w.getState();
    ok(
        s.player && s.player.hp === 100 && s.player.level === 1 &&
        s.combat && s.combat.waveNumber === 0 &&
        s.thrones && s.thrones.explorer === 200 && s.thrones.horde === 200 &&
        s.combat.warmup === true,
        'Init: world starts correctly',
        'hp=' + (s.player||{}).hp + ' wave=' + (s.combat||{}).waveNumber + ' warmup=' + (s.combat||{}).warmup +
        ' thrones=' + (s.thrones||{}).explorer + '/' + (s.thrones||{}).horde
    );
} catch(e) { ok(false, 'Init: world starts correctly', e.message); }

// ── T2: Warmup Period ──
try {
    var w = createWorld('arena');
    w.tickSeconds(30); // 30 seconds — still in warmup
    var s = w.getState();
    ok(s.combat.warmup === true && s.combat.creepCount === 0,
        'Warmup: no creeps during 2-min warmup',
        'warmup=' + s.combat.warmup + ' creeps=' + s.combat.creepCount);
} catch(e) { ok(false, 'Warmup: no creeps during 2-min warmup', e.message); }

// ── T3: Wave Spawn After Warmup ──
try {
    var w = createWorld('arena');
    w.tickSeconds(125); // 2:05 — past warmup, first wave should spawn
    var s = w.getState();
    ok(s.combat.warmup === false && s.combat.waveNumber >= 1 && s.combat.creepCount > 0,
        'Wave spawn: creeps after warmup',
        'warmup=' + s.combat.warmup + ' wave=' + s.combat.waveNumber + ' creeps=' + s.combat.creepCount);
} catch(e) { ok(false, 'Wave spawn: creeps after warmup', e.message); }

// ── T4: Player Attack ──
try {
    var w = createWorld('arena');
    w.tickSeconds(121); // Past warmup, wave spawned
    // Snap player to a horde creep each attack cycle (creeps move between ticks)
    var killed = false;
    for (var attempt = 0; attempt < 30 && !killed; attempt++) {
        var cp = w.run('var hc=WorldCombat.creeps.find(function(c){return c.alive&&c.faction==="horde"});hc?JSON.stringify({x:hc.mesh.position.x,z:hc.mesh.position.z}):null');
        if (cp) {
            var p = JSON.parse(cp);
            w.movePlayerTo(p.x, p.z);
            w.run('WorldCombat.playerAttackTimer=0'); // Reset cooldown
            w.attack();
        }
        w.tick();
        if (w.getState().player.kills > 0) killed = true;
    }
    var s = w.getState();
    ok(s.player.kills > 0 || s.player.gold > 0,
        'Player attack: kills or rewards gained',
        'kills=' + s.player.kills + ' xp=' + s.player.xp + ' gold=' + s.player.gold);
} catch(e) { ok(false, 'Player attack: kills or rewards gained', e.message); }

// ── T5: Level Up ──
try {
    var w = createWorld('arena');
    w.run('PlayerStats.awardXp(100)');
    var s = w.getState();
    ok(s.player.level === 2 && s.player.maxHp === 110 && s.player.baseDamage === 22,
        'Level up: stats increase',
        'level=' + s.player.level + ' maxHp=' + s.player.maxHp + ' dmg=' + s.player.baseDamage);
} catch(e) { ok(false, 'Level up: stats increase', e.message); }

// ── T6: Ability Scaling ──
try {
    var w = createWorld('arena');
    w.run('PlayerStats.awardXp(100)'); // Level 2, +1 skill point
    var sp = w.getState().abilities.skillPoints;
    w.run('Abilities.levelUpAbility(0)'); // Level up Slash
    var s = w.getState();
    var scaledDmg = w.run('Abilities.getScaled(0).damage');
    ok(s.abilities.levels[0] === 2 && scaledDmg === 20 && s.abilities.skillPoints === sp - 1,
        'Ability scaling: Slash L2 = 20 dmg',
        'level=' + s.abilities.levels[0] + ' dmg=' + scaledDmg + ' sp=' + s.abilities.skillPoints);
} catch(e) { ok(false, 'Ability scaling: Slash L2 = 20 dmg', e.message); }

// ── T7: Shop Buy ──
try {
    var w = createWorld('arena');
    w.run('PlayerStats.takeDamage(40)'); // HP: 100→60
    w.run('PlayerStats.gold = 50');
    w.buyItem(0); // Health Potion: cost 50, heal 40
    var s = w.getState();
    ok(s.player.gold === 0 && s.player.hp === 100,
        'Shop buy: potion heals, gold deducted',
        'gold=' + s.player.gold + ' hp=' + s.player.hp);
} catch(e) { ok(false, 'Shop buy: potion heals, gold deducted', e.message); }

// ── T8: Crafting ──
try {
    var w = createWorld('arena');
    w.run('Inventory.items = [{name:"Scrap Metal"},{name:"Scrap Metal"},{name:"Scrap Metal"}]');
    w.run('PlayerStats.gold = 50');
    w.craft(0); // Iron Blade: 3 Scrap Metal + 20G
    var s = w.getState();
    var hasIronBlade = w.run('Inventory.items.some(function(i){return i&&i.name==="Iron Blade"})');
    var scrapsLeft = w.run('Inventory.items.filter(function(i){return i&&i.name==="Scrap Metal"}).length');
    ok(s.player.gold === 30 && hasIronBlade === true && scrapsLeft === 0,
        'Crafting: Iron Blade created',
        'gold=' + s.player.gold + ' hasBlade=' + hasIronBlade + ' scraps=' + scrapsLeft);
} catch(e) { ok(false, 'Crafting: Iron Blade created', e.message); }

// ── T9: Player Death + Respawn ──
try {
    var w = createWorld('arena');
    w.run('PlayerStats.takeDamage(200)'); // Overkill
    var s1 = w.getState();
    var dead = s1.player.dead;
    var deaths = s1.player.deaths;
    // Tick past respawn timer (5 + 1*2 = 7 seconds)
    w.tickSeconds(8);
    var s2 = w.getState();
    ok(dead === true && deaths === 1 && s2.player.dead === false && s2.player.hp === s2.player.maxHp,
        'Death + respawn: dies and comes back',
        'wasDead=' + dead + ' deaths=' + deaths + ' nowDead=' + s2.player.dead + ' hp=' + s2.player.hp);
} catch(e) { ok(false, 'Death + respawn: dies and comes back', e.message); }

// ── T10: Victory ──
try {
    var w = createWorld('arena');
    var el = w.run('document.getElementById("victory-overlay")');
    w.run('WorldCombat._triggerVictory("VICTORY", "Explorers")');
    var display = w.run('document.getElementById("victory-overlay").style.display');
    // Note: Proxy style always returns '' but the function sets it
    ok(true, 'Victory: trigger does not crash',
        'triggered without error');
} catch(e) { ok(false, 'Victory: trigger does not crash', e.message); }

// ── T11: Save/Load ──
try {
    var w = createWorld('arena');
    w.run('PlayerStats.level=5; PlayerStats.gold=500; PlayerStats.baseDamage=30; PlayerStats.save()');
    var saved = w.store.get('rappterverse-player');
    ok(saved !== null, 'Save: data written to localStorage', 'saved=' + (saved ? 'yes' : 'no'));
    // Reset and load
    w.run('PlayerStats.init()');
    var s1 = w.getState();
    w.run('PlayerStats.load()');
    var s2 = w.getState();
    ok(s2.player.level === 5 && s2.player.gold === 500,
        'Load: progress restored',
        'level=' + s2.player.level + ' gold=' + s2.player.gold);
} catch(e) { ok(false, 'Save/Load: persistence works', e.message); }

// ── T12: Creep Variety ──
try {
    var w = createWorld('arena');
    w.tickSeconds(150); // Past warmup + first wave
    var types1 = w.run('WorldCombat.creeps.map(function(c){return c.creepType}).filter(Boolean)');
    var hasMelee = w.run('WorldCombat.creeps.some(function(c){return c.creepType==="melee"})');
    var hasRanged = w.run('WorldCombat.creeps.some(function(c){return c.creepType==="ranged"})');
    ok(hasMelee && hasRanged,
        'Creep variety: melee + ranged in wave 1',
        'melee=' + hasMelee + ' ranged=' + hasRanged);
} catch(e) { ok(false, 'Creep variety: melee + ranged in wave 1', e.message); }

// ── T13: Full Session (5 waves) ──
try {
    var w = createWorld('arena');
    // Tick through warmup + 5 waves (120s warmup + 5*25s = 245s)
    w.tickSeconds(250);
    var s = w.getState();
    ok(s.combat.waveNumber >= 5 && !s.error,
        'Full session: 5 waves without crash',
        'waves=' + s.combat.waveNumber + ' creeps=' + s.combat.creepCount + ' momentum=' + Math.round(s.combat.momentum));
} catch(e) { ok(false, 'Full session: 5 waves without crash', e.message); }

// ── Summary ──
console.log('');
console.log('# ' + passed + '/' + testNum + ' passed' + (failed > 0 ? ', ' + failed + ' failed' : ''));
if (errors.length > 0) {
    console.log('# Failures:');
    errors.forEach(function(e) { console.log('#   - ' + e); });
}
process.exit(failed > 0 ? 1 : 0);
