// Settings persistence + screenshot/share
const Settings = {
    _defaults: {
        bloom: true,
        masterVolume: 0.3,
        voiceEnabled: false,
        gestureEnabled: false,
        echoEffects: true,
    },

    _data: null,

    init() {
        try {
            const saved = localStorage.getItem('rappterverse-settings');
            this._data = saved ? JSON.parse(saved) : Object.assign({}, this._defaults);
        } catch(e) {
            this._data = Object.assign({}, this._defaults);
        }
        this._apply();
    },

    get(key) { return this._data ? this._data[key] : this._defaults[key]; },

    set(key, value) {
        if (!this._data) this._data = Object.assign({}, this._defaults);
        this._data[key] = value;
        try { localStorage.setItem('rappterverse-settings', JSON.stringify(this._data)); } catch(e) {}
    },

    _apply() {
        // Bloom
        if (typeof PostProcessing !== 'undefined') {
            PostProcessing.setEnabled(this.get('bloom') !== false);
        }
        // Volume
        if (typeof Audio !== 'undefined' && Audio.masterGain && Audio.ctx) {
            Audio.masterGain.gain.value = this.get('masterVolume') || 0.3;
        }
    },

    // ── Screenshot ──
    screenshot() {
        if (!GameState.renderer) return;
        // Render one frame to ensure fresh
        if (GameState.mode === 'world' && typeof WorldMode !== 'undefined') {
            WorldMode.render();
        }
        try {
            const canvas = GameState.renderer.domElement;
            canvas.toBlob(function(blob) {
                if (!blob) return;
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'rappterverse-' + (GameState.currentWorld || 'screenshot') + '-' + Date.now() + '.png';
                a.click();
                URL.revokeObjectURL(url);
                if (typeof HUD !== 'undefined') HUD.showToast('Screenshot saved');
            }, 'image/png');
        } catch(e) {
            if (typeof HUD !== 'undefined') HUD.showToast('Screenshot failed');
        }
    },

    // ── Share Link ──
    shareLink() {
        var worldId = GameState.currentWorld || 'hub';
        var url = window.location.origin + window.location.pathname + '?world=' + worldId;

        // Try clipboard API first
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(url).then(function() {
                if (typeof HUD !== 'undefined') HUD.showToast('Link copied: ' + url);
            }).catch(function() {
                if (typeof HUD !== 'undefined') HUD.showToast(url);
            });
        } else {
            // Fallback: show in toast
            if (typeof HUD !== 'undefined') HUD.showToast(url);
        }
    }
};
