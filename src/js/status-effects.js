/*  Status Effects – elemental debuffs applied to mobs (creeps / bosses)
    Three.js r128 compatible – no ES modules, no CapsuleGeometry, no ShaderMaterial  */

const STATUS_EFFECT_DEFS = {
    ice:    { name: 'Frozen',      duration: 3000, color: 0x88ccff, icon: '❄', speedMod: 0.3, tickDamage: 0, tickRate: 0 },
    fire:   { name: 'Burning',     duration: 4000, color: 0xff4400, icon: '🔥', speedMod: 1.0, tickDamage: 2, tickRate: 500 },
    void:   { name: 'Weakened',    duration: 5000, color: 0x8800ff, icon: '💜', speedMod: 1.0, tickDamage: 0, tickRate: 0, damageMod: 0.5 },
    cosmic: { name: 'Annihilated', duration: 3000, color: 0xffd700, icon: '✨', speedMod: 0.5, tickDamage: 5, tickRate: 250 }
};

const StatusEffects = (function () {

    // All mobs that currently carry at least one effect
    const _tracked = new Set();

    /* ── helpers ─────────────────────────────────────────────── */

    function _ensureStore(mob) {
        if (!mob.userData) mob.userData = {};
        if (!mob.userData.statusEffects) mob.userData.statusEffects = {};
    }

    function _storeOriginalEmissive(mob) {
        if (mob.userData._origEmissive !== undefined) return;
        var mat = mob.material;
        if (mat && mat.emissive) {
            mob.userData._origEmissive = mat.emissive.getHex();
        } else {
            mob.userData._origEmissive = 0x000000;
        }
    }

    function _refreshEmissive(mob) {
        var mat = mob.material;
        if (!mat || !mat.emissive) return;
        var effects = mob.userData.statusEffects;
        var keys = Object.keys(effects);
        if (keys.length === 0) {
            mat.emissive.setHex(mob.userData._origEmissive || 0x000000);
            return;
        }
        // Use the most recent effect's color
        var latest = null;
        for (var i = 0; i < keys.length; i++) {
            var e = effects[keys[i]];
            if (!latest || e.startTime >= latest.startTime) latest = e;
        }
        if (latest) mat.emissive.setHex(STATUS_EFFECT_DEFS[latest.element].color);
    }

    /* ── public API ──────────────────────────────────────────── */

    return {

        /** Apply (or refresh) an elemental effect on a mob. */
        applyEffect: function (mob, element) {
            var def = STATUS_EFFECT_DEFS[element];
            if (!def) return;
            _ensureStore(mob);
            _storeOriginalEmissive(mob);

            var existing = mob.userData.statusEffects[element];
            var now = performance.now();

            if (existing) {
                // Refresh duration
                existing.startTime = now;
                existing.lastTick = now;
            } else {
                mob.userData.statusEffects[element] = {
                    element: element,
                    startTime: now,
                    lastTick: now
                };
            }

            _tracked.add(mob);
            _refreshEmissive(mob);
        },

        /**
         * Tick every frame. Processes DoT and expiration.
         * Returns array of { mob, element, killed } events.
         */
        updateAll: function (delta, time) {
            var events = [];
            var now = performance.now();

            _tracked.forEach(function (mob) {
                var effects = mob.userData && mob.userData.statusEffects;
                if (!effects) return;

                var keys = Object.keys(effects);
                var dirty = false;

                for (var i = keys.length - 1; i >= 0; i--) {
                    var el = keys[i];
                    var eff = effects[el];
                    var def = STATUS_EFFECT_DEFS[el];

                    // Expiration check
                    if (now > eff.startTime + def.duration) {
                        delete effects[el];
                        dirty = true;
                        continue;
                    }

                    // DoT ticks
                    if (def.tickDamage > 0 && def.tickRate > 0) {
                        if (now - eff.lastTick >= def.tickRate) {
                            var ticks = Math.floor((now - eff.lastTick) / def.tickRate);
                            eff.lastTick += ticks * def.tickRate;
                            mob.userData.hp -= def.tickDamage * ticks;

                            if (mob.userData.hp <= 0) {
                                events.push({ mob: mob, element: el, killed: true });
                            } else {
                                events.push({ mob: mob, element: el, killed: false });
                            }
                        }
                    }
                }

                if (dirty) _refreshEmissive(mob);

                // Remove mob from tracking when no effects remain
                if (Object.keys(effects).length === 0) {
                    _tracked.delete(mob);
                }
            });

            return events;
        },

        /** Remove all effects from a mob and restore its original emissive. */
        clearEffects: function (mob) {
            if (!mob.userData) return;
            mob.userData.statusEffects = {};
            var mat = mob.material;
            if (mat && mat.emissive) {
                mat.emissive.setHex(mob.userData._origEmissive || 0x000000);
            }
            _tracked.delete(mob);
        },

        /** Return array of human-readable effect names for HUD display. */
        getActiveEffects: function (mob) {
            var out = [];
            if (!mob.userData || !mob.userData.statusEffects) return out;
            var effects = mob.userData.statusEffects;
            var keys = Object.keys(effects);
            for (var i = 0; i < keys.length; i++) {
                var def = STATUS_EFFECT_DEFS[keys[i]];
                if (def) out.push(def.icon + ' ' + def.name);
            }
            return out;
        },

        /** Combined speed multiplier (multiplicative). */
        getSpeedMultiplier: function (mob) {
            var mul = 1.0;
            if (!mob.userData || !mob.userData.statusEffects) return mul;
            var effects = mob.userData.statusEffects;
            var keys = Object.keys(effects);
            for (var i = 0; i < keys.length; i++) {
                var def = STATUS_EFFECT_DEFS[keys[i]];
                if (def) mul *= def.speedMod;
            }
            return mul;
        },

        /** Combined damage multiplier (for void debuff etc). */
        getDamageMultiplier: function (mob) {
            var mul = 1.0;
            if (!mob.userData || !mob.userData.statusEffects) return mul;
            var effects = mob.userData.statusEffects;
            var keys = Object.keys(effects);
            for (var i = 0; i < keys.length; i++) {
                var def = STATUS_EFFECT_DEFS[keys[i]];
                if (def && def.damageMod !== undefined) mul *= def.damageMod;
            }
            return mul;
        },

        /** Clear all tracked state. */
        cleanup: function () {
            _tracked.forEach(function (mob) {
                if (mob.userData) mob.userData.statusEffects = {};
            });
            _tracked.clear();
        }
    };

})();
