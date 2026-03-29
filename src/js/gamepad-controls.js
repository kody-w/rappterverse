// Gamepad Controls — Standard Gamepad API for controller input
const GamepadControls = {
    active: false,
    _padIndex: null,
    _deadzone: 0.15,
    _lastButtons: {},

    init() {
        window.addEventListener('gamepadconnected', (e) => {
            this._padIndex = e.gamepad.index;
            this.active = true;
            if (typeof HUD !== 'undefined') HUD.showToast('Gamepad connected: ' + e.gamepad.id.substring(0, 30));
        });
        window.addEventListener('gamepaddisconnected', (e) => {
            if (e.gamepad.index === this._padIndex) {
                this._padIndex = null;
                this.active = false;
                if (typeof HUD !== 'undefined') HUD.showToast('Gamepad disconnected');
            }
        });
    },

    update() {
        if (!this.active || this._padIndex === null) return;
        var pads = navigator.getGamepads ? navigator.getGamepads() : [];
        var pad = pads[this._padIndex];
        if (!pad) return;
        if (typeof WorldMode === 'undefined' || !WorldMode.keys) return;

        // Left stick → movement
        var lx = pad.axes[0] || 0, ly = pad.axes[1] || 0;
        WorldMode.keys['KeyD'] = lx > this._deadzone;
        WorldMode.keys['KeyA'] = lx < -this._deadzone;
        WorldMode.keys['KeyS'] = ly > this._deadzone;
        WorldMode.keys['KeyW'] = ly < -this._deadzone;

        // Buttons (standard mapping)
        var btn = function(i) { return pad.buttons[i] && pad.buttons[i].pressed; };
        var wasBtn = function(i) { return GamepadControls._lastButtons[i]; };

        // A (0) = Attack
        WorldMode.keys['Space'] = btn(0);
        // B (1) = Poke
        if (btn(1) && !wasBtn(1) && typeof WorldMode !== 'undefined') WorldMode.pokeAgent();
        // X (2) = Ability 1
        if (btn(2) && !wasBtn(2) && typeof Abilities !== 'undefined') Abilities.useAbility(0);
        // Y (3) = Ability 5 (ultimate)
        if (btn(3) && !wasBtn(3) && typeof Abilities !== 'undefined') Abilities.useAbility(4);
        // LB (4) = Ability 2
        if (btn(4) && !wasBtn(4) && typeof Abilities !== 'undefined') Abilities.useAbility(1);
        // RB (5) = Ability 3
        if (btn(5) && !wasBtn(5) && typeof Abilities !== 'undefined') Abilities.useAbility(2);
        // Start (9) = Bridge
        if (btn(9) && !wasBtn(9) && typeof Bridge !== 'undefined') Bridge.toggle();
        // Select (8) = Map
        if (btn(8) && !wasBtn(8) && typeof HUD !== 'undefined') HUD.toggleFullmap();
        // DPad Up (12) = Inventory
        if (btn(12) && !wasBtn(12) && typeof Inventory !== 'undefined') Inventory.toggle();
        // DPad Down (13) = Equipment
        if (btn(13) && !wasBtn(13) && typeof Equipment !== 'undefined') Equipment.toggle();

        // Save button state for edge detection
        for (var i = 0; i < 17; i++) this._lastButtons[i] = btn(i);

        // Echo-reactive haptic rumble — tension drives background vibration
        this._updateEchoRumble(pad);
    },

    _rumbleTimer: 0,
    _updateEchoRumble(pad) {
        if (!pad.vibrationActuator) return;
        this._rumbleTimer -= 0.016;
        if (this._rumbleTimer > 0) return;
        this._rumbleTimer = 2; // Check every 2 seconds

        if (typeof EchoEngine === 'undefined') return;
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var tension = ef.echoes.L3.tension;

        if (tension > 0.5) {
            // Subtle rumble during tension — stronger as tension rises
            var strength = (tension - 0.5) * 0.3; // 0 to 0.15
            try {
                pad.vibrationActuator.playEffect('dual-rumble', {
                    duration: 200,
                    strongMagnitude: strength,
                    weakMagnitude: strength * 0.5
                });
            } catch(e) {}
        }
    },

    // Trigger a one-shot rumble (called by VFX/combat)
    rumble(strong, weak, duration) {
        if (!this.active || this._padIndex === null) return;
        var pads = navigator.getGamepads ? navigator.getGamepads() : [];
        var pad = pads[this._padIndex];
        if (!pad || !pad.vibrationActuator) return;
        try {
            pad.vibrationActuator.playEffect('dual-rumble', {
                duration: duration || 100,
                strongMagnitude: strong || 0.3,
                weakMagnitude: weak || 0.15
            });
        } catch(e) {}
    }
};
