// Echo Events — Procedural world events triggered by echo thresholds
// Events emerge organically from the simulation's emotional state

const EchoEvents = {
    _timer: 0,
    _cooldown: 30,  // Min seconds between events
    _lastEvent: null,
    _activeEvent: null,
    _eventTimer: 0,

    // Event definitions — each triggers at specific echo conditions
    events: [
        {
            id: 'tension_spike',
            name: 'BATTLE FURY',
            condition: function(L3) { return L3.tension > 0.7; },
            duration: 15,
            onStart: function() {
                if (typeof HUD !== 'undefined') HUD.showToast('BATTLE FURY — All damage +30% for 15s!');
                if (typeof VFX !== 'undefined') VFX.screenFlash('#ff2222', 0.4);
                // Boost all damage
                if (typeof COMBAT_CONFIG !== 'undefined') {
                    if (COMBAT_CONFIG._origPlayerDmg === undefined) COMBAT_CONFIG._origPlayerDmg = COMBAT_CONFIG.playerDamage;
                    COMBAT_CONFIG.playerDamage = Math.round(COMBAT_CONFIG._origPlayerDmg * 1.3);
                }
            },
            onEnd: function() {
                if (typeof COMBAT_CONFIG !== 'undefined' && COMBAT_CONFIG._origPlayerDmg !== undefined) {
                    COMBAT_CONFIG.playerDamage = COMBAT_CONFIG._origPlayerDmg;
                    delete COMBAT_CONFIG._origPlayerDmg;
                }
                if (typeof HUD !== 'undefined') HUD.showToast('Battle Fury faded.');
            }
        },
        {
            id: 'social_bloom',
            name: 'SOCIAL BLOOM',
            condition: function(L3) { return L3.socialEnergy > 0.7 && L3.tension < 0.3; },
            duration: 20,
            onStart: function() {
                if (typeof HUD !== 'undefined') HUD.showToast('SOCIAL BLOOM — XP gain +50% for 20s!');
                if (typeof VFX !== 'undefined') VFX.screenFlash('#ffd700', 0.3);
                if (typeof PlayerStats !== 'undefined') {
                    PlayerStats._echoXpBonus = 1.5;
                }
            },
            onEnd: function() {
                if (typeof PlayerStats !== 'undefined') {
                    PlayerStats._echoXpBonus = 1;
                }
                if (typeof HUD !== 'undefined') HUD.showToast('Social Bloom faded.');
            }
        },
        {
            id: 'vitality_surge',
            name: 'VITALITY SURGE',
            condition: function(L3) { return L3.vitality > 0.7; },
            duration: 12,
            onStart: function() {
                if (typeof HUD !== 'undefined') HUD.showToast('VITALITY SURGE — HP regen 3x for 12s!');
                if (typeof VFX !== 'undefined') {
                    VFX.screenFlash('#00ff88', 0.3);
                    // Scatter healing particles
                    if (typeof WorldMode !== 'undefined' && WorldMode.player) {
                        VFX.burst(WorldMode.player.mesh.position, 'echoVitality', { count: 20 });
                    }
                }
                if (typeof PlayerStats !== 'undefined') {
                    if (PlayerStats._origHpRegen === undefined) PlayerStats._origHpRegen = PlayerStats.hpRegen;
                    PlayerStats.hpRegen = PlayerStats._origHpRegen * 3;
                }
            },
            onEnd: function() {
                if (typeof PlayerStats !== 'undefined' && PlayerStats._origHpRegen !== undefined) {
                    PlayerStats.hpRegen = PlayerStats._origHpRegen;
                    delete PlayerStats._origHpRegen;
                }
                if (typeof HUD !== 'undefined') HUD.showToast('Vitality Surge faded.');
            }
        },
        {
            id: 'echo_storm',
            name: 'ECHO STORM',
            condition: function(L3) { return L3.tension > 0.5 && L3.vitality > 0.5 && L3.socialEnergy > 0.3; },
            duration: 10,
            onStart: function() {
                if (typeof HUD !== 'undefined') HUD.showToast('ECHO STORM — All echoes amplified!');
                if (typeof VFX !== 'undefined') {
                    VFX.screenFlash('#aa44ff', 0.5);
                    // Massive particle burst
                    for (var i = 0; i < 5; i++) {
                        var rx = (Math.random() - 0.5) * 40;
                        var rz = (Math.random() - 0.5) * 40;
                        VFX.burst({ x: rx, y: 2, z: rz }, 'cosmic', { count: 8 });
                    }
                }
                // Amplify all echo effects
                EchoEvents._amplified = true;
            },
            onEnd: function() {
                EchoEvents._amplified = false;
                if (typeof HUD !== 'undefined') HUD.showToast('Echo Storm subsided.');
            }
        },
        {
            id: 'calm_before_storm',
            name: 'CALM BEFORE THE STORM',
            condition: function(L3) { return L3.tension < 0.1 && L3.vitality < 0.3; },
            duration: 8,
            onStart: function() {
                if (typeof HUD !== 'undefined') HUD.showToast('An eerie calm settles...');
                // Fog thickens
                if (typeof WorldMode !== 'undefined' && WorldMode.scene && WorldMode.scene.fog) {
                    EchoEvents._origFog = WorldMode.scene.fog.density;
                    WorldMode.scene.fog.density = 0.006;
                }
            },
            onEnd: function() {
                if (typeof WorldMode !== 'undefined' && WorldMode.scene && WorldMode.scene.fog && EchoEvents._origFog) {
                    WorldMode.scene.fog.density = EchoEvents._origFog;
                    delete EchoEvents._origFog;
                }
                if (typeof HUD !== 'undefined') HUD.showToast('The calm has passed.');
            }
        }
    ],

    _amplified: false,

    update(delta) {
        // Manage active event
        if (this._activeEvent) {
            this._eventTimer -= delta;
            // Ongoing VFX for active events
            if (this._activeEvent.id === 'echo_storm' && typeof VFX !== 'undefined') {
                if (Math.random() < 0.1) {
                    var rx = (Math.random() - 0.5) * 50;
                    var rz = (Math.random() - 0.5) * 50;
                    VFX.burst({ x: rx, y: 3 + Math.random() * 5, z: rz }, 'cosmic', { count: 2 });
                }
            }
            if (this._eventTimer <= 0) {
                this._activeEvent.onEnd();
                this._activeEvent = null;
            }
            return;
        }

        // Cooldown between events
        this._timer -= delta;
        if (this._timer > 0) return;
        this._timer = 5; // Check every 5 seconds

        // Check conditions
        if (typeof EchoEngine === 'undefined') return;
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var L3 = ef.echoes.L3;

        for (var i = 0; i < this.events.length; i++) {
            var evt = this.events[i];
            if (evt.id === this._lastEvent) continue; // Don't repeat last event
            if (evt.condition(L3)) {
                this._activeEvent = evt;
                this._eventTimer = evt.duration;
                this._lastEvent = evt.id;
                this._cooldown = 30 + Math.random() * 30; // 30-60s cooldown
                this._timer = this._cooldown;
                evt.onStart();
                break;
            }
        }
    },

    cleanup() {
        if (this._activeEvent) {
            this._activeEvent.onEnd();
            this._activeEvent = null;
        }
        this._amplified = false;
    }
};
