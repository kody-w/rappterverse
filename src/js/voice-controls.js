// Voice Controls — Web Speech API command recognition
const VoiceControls = {
    active: false,
    recognition: null,
    lastCommand: '',
    lastCommandTime: 0,
    _supported: false,

    init() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { this._supported = false; return; }
        this._supported = true;

        this.recognition = new SR();
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.lang = 'en-US';
        this.recognition.maxAlternatives = 1;

        this.recognition.onresult = (e) => this._onResult(e);
        this.recognition.onerror = (e) => this._onError(e);
        this.recognition.onend = () => { if (this.active) this._restart(); };
    },

    toggle() {
        if (!this._supported) {
            if (typeof HUD !== 'undefined') HUD.showToast('Voice commands not supported in this browser');
            return false;
        }
        this.active = !this.active;
        if (this.active) {
            this._start();
            if (typeof HUD !== 'undefined') HUD.showToast('Voice commands ON — try "move forward", "attack", "bridge"');
        } else {
            this._stop();
            if (typeof HUD !== 'undefined') HUD.showToast('Voice commands OFF');
        }
        this._updateUI();
        return this.active;
    },

    _start() {
        try { this.recognition.start(); } catch(e) {}
        this._updateUI();
    },

    _stop() {
        try { this.recognition.stop(); } catch(e) {}
        this._updateUI();
    },

    _restart() {
        // Restart after speech recognition ends (browser auto-stops after silence)
        setTimeout(() => {
            if (this.active) {
                try { this.recognition.start(); } catch(e) {}
            }
        }, 300);
    },

    _onError(e) {
        if (e.error === 'not-allowed') {
            this.active = false;
            if (typeof HUD !== 'undefined') HUD.showToast('Microphone access denied');
            this._updateUI();
        }
        // 'no-speech' is normal, just means silence — ignore
    },

    _onResult(event) {
        let final = '';
        let interim = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript.trim().toLowerCase();
            if (event.results[i].isFinal) {
                final = transcript;
            } else {
                interim = transcript;
            }
        }

        // Show interim text
        const feedbackEl = document.getElementById('voice-feedback');
        if (feedbackEl) {
            feedbackEl.textContent = interim || final || '';
            if (final) {
                feedbackEl.style.color = 'var(--accent-cyan)';
                setTimeout(() => { feedbackEl.style.color = ''; }, 500);
            }
        }

        if (final) this._processCommand(final);
    },

    _processCommand(text) {
        if (GameState.inputLocked) return;
        // Debounce — ignore if same command within 1s
        const now = Date.now();
        if (text === this.lastCommand && now - this.lastCommandTime < 1000) return;
        this.lastCommand = text;
        this.lastCommandTime = now;

        if (GameState.debug) console.log('[VOICE]', text);

        // Only process commands in world mode for movement/combat
        const inWorld = GameState.mode === 'world';

        // ── Movement commands ──
        if (inWorld && typeof WorldMode !== 'undefined') {
            if (this._match(text, ['forward', 'move forward', 'go forward', 'up', 'go up'])) {
                this._simulateKey('KeyW', 600); this._showAction('FORWARD'); return;
            }
            if (this._match(text, ['back', 'move back', 'go back', 'backward', 'reverse'])) {
                this._simulateKey('KeyS', 600); this._showAction('BACK'); return;
            }
            if (this._match(text, ['left', 'move left', 'go left'])) {
                this._simulateKey('KeyA', 600); this._showAction('LEFT'); return;
            }
            if (this._match(text, ['right', 'move right', 'go right'])) {
                this._simulateKey('KeyD', 600); this._showAction('RIGHT'); return;
            }
            if (this._match(text, ['run forward', 'sprint', 'run'])) {
                this._simulateKey('KeyW', 1200); this._showAction('SPRINT'); return;
            }
            if (this._match(text, ['stop', 'halt', 'wait'])) {
                // Release all keys
                WorldMode.keys = {};
                this._showAction('STOP'); return;
            }
        }

        // ── Combat commands ──
        if (inWorld) {
            if (this._match(text, ['attack', 'hit', 'strike', 'fight', 'slash'])) {
                this._simulateKey('Space', 300); this._showAction('ATTACK'); return;
            }
            if (this._match(text, ['poke', 'interact', 'talk', 'hello'])) {
                if (typeof WorldMode !== 'undefined') WorldMode.pokeAgent();
                this._showAction('POKE'); return;
            }
        }

        // ── Ability commands ──
        if (inWorld && typeof Abilities !== 'undefined') {
            if (this._match(text, ['ability one', 'ability 1', 'first ability', 'sword'])) {
                Abilities.useAbility(0); this._showAction('ABILITY 1'); return;
            }
            if (this._match(text, ['ability two', 'ability 2', 'second ability', 'shield'])) {
                Abilities.useAbility(1); this._showAction('ABILITY 2'); return;
            }
            if (this._match(text, ['ability three', 'ability 3', 'third ability'])) {
                Abilities.useAbility(2); this._showAction('ABILITY 3'); return;
            }
            if (this._match(text, ['ultimate', 'ability five', 'ability 5', 'ult'])) {
                Abilities.useAbility(4); this._showAction('ULTIMATE'); return;
            }
        }

        // ── Navigation commands (work in any mode) ──
        if (this._match(text, ['bridge', 'open bridge', 'command', 'ship'])) {
            if (typeof Bridge !== 'undefined') Bridge.toggle();
            this._showAction('BRIDGE'); return;
        }
        if (this._match(text, ['map', 'minimap', 'open map'])) {
            if (typeof HUD !== 'undefined') HUD.toggleMinimap();
            this._showAction('MAP'); return;
        }
        if (this._match(text, ['inventory', 'items', 'bag', 'open inventory'])) {
            if (typeof Inventory !== 'undefined') Inventory.toggle();
            this._showAction('INVENTORY'); return;
        }
        if (this._match(text, ['escape', 'back to galaxy', 'leave', 'exit'])) {
            if (inWorld) {
                WorldMode.cleanup();
                if (typeof HUD !== 'undefined' && HUD.hideWorldPanels) HUD.hideWorldPanels();
                GameState.setMode('galaxy');
                if (typeof Galaxy !== 'undefined') Galaxy.show();
            }
            this._showAction('EXIT'); return;
        }

        // ── World travel ──
        const travelMatch = text.match(/(?:travel to|go to|fly to|warp to|visit)\s+(.+)/);
        if (travelMatch) {
            const dest = travelMatch[1].trim();
            const worldId = this._matchWorld(dest);
            if (worldId) {
                if (inWorld) WorldMode.cleanup();
                if (GameState.mode === 'galaxy' && typeof Galaxy !== 'undefined') Galaxy.hide();
                if (typeof Approach !== 'undefined') Approach.start(worldId);
                this._showAction('TRAVEL: ' + WORLDS[worldId].name);
                return;
            }
        }

        // ── Seed commands ──
        if (this._match(text, ['boot linux', 'start os', 'boot os', 'start linux'])) {
            if (typeof RappterOS !== 'undefined') RappterOS.init();
            this._showAction('BOOT OS'); return;
        }
        if (this._match(text, ['export seed', 'save seed', 'export world'])) {
            document.getElementById('btn-export-seed').click();
            this._showAction('EXPORT SEED'); return;
        }
    },

    _match(text, phrases) {
        return phrases.some(p => text.includes(p));
    },

    _matchWorld(name) {
        const n = name.toLowerCase();
        if (n.includes('hub') || n.includes('home')) return 'hub';
        if (n.includes('arena') || n.includes('battle') || n.includes('fight')) return 'arena';
        if (n.includes('market') || n.includes('shop') || n.includes('trade')) return 'marketplace';
        if (n.includes('gallery') || n.includes('crystal') || n.includes('museum')) return 'gallery';
        if (n.includes('dungeon') || n.includes('dark') || n.includes('abyss')) return 'dungeon';
        return null;
    },

    _simulateKey(code, duration) {
        if (typeof WorldMode === 'undefined' || !WorldMode.keys) return;
        WorldMode.keys[code] = true;
        setTimeout(() => { if (WorldMode.keys) WorldMode.keys[code] = false; }, duration);
    },

    _showAction(label) {
        const el = document.getElementById('voice-action');
        if (!el) return;
        el.textContent = label;
        el.style.opacity = '1';
        el.style.transform = 'translateX(-50%) scale(1.1)';
        setTimeout(() => {
            el.style.opacity = '0.6';
            el.style.transform = 'translateX(-50%) scale(1)';
        }, 150);
        clearTimeout(this._actionTimeout);
        this._actionTimeout = setTimeout(() => {
            el.textContent = '';
            el.style.opacity = '0';
        }, 1500);
    },

    _updateUI() {
        const btn = document.getElementById('btn-voice');
        if (btn) {
            btn.classList.toggle('active', this.active);
            btn.title = this.active ? 'Voice ON (V)' : 'Voice OFF (V)';
        }
        const indicator = document.getElementById('voice-indicator');
        if (indicator) indicator.classList.toggle('visible', this.active);
    }
};
