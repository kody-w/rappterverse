// Main — Entry Point & Animation Loop
(function() {
    // Animation loop
    function animate() {
        requestAnimationFrame(animate);
        const delta = GameState.clock ? GameState.clock.getDelta() : 0.016;
        const time = GameState.clock ? GameState.clock.getElapsedTime() : 0;

        // Bridge owns the renderer and simulation clock while open.
        if (Bridge.open) return;

        switch(GameState.mode) {
            case 'galaxy':
                if (!GameState.inputLocked) Galaxy.update(delta, time);
                Galaxy.render();
                break;
            case 'world':
                if (!GameState.inputLocked) WorldMode.update(delta, time);
                WorldMode.render();
                break;
            // approach and landing handle their own rendering
        }

        // Update HUD periodically
        HUD.updateAgentCount();
        if (GameState.mode === 'world' && HUD.minimapVisible) {
            HUD.renderMinimap();
        }

        // Update Rappterbook-style panels (~every second, not every frame)
        if (!HUD._lastPanelUpdate || time - HUD._lastPanelUpdate > 1) {
            HUD._lastPanelUpdate = time;
            HUD.updatePanels();
        }

    }

    // Keyboard
    document.addEventListener('keydown', (e) => {
        // Track keys for debug overlay
        if (typeof DebugOverlay !== 'undefined') DebugOverlay.recordKey(e.code);
        if (GameState.inputLocked) {
            e.stopPropagation();
            return;
        }
        if (Bridge.open) {
            if (e.code === 'KeyB' || e.code === 'Escape') {
                e.preventDefault();
                Bridge.close();
            }
            return;
        }

        // Replay system input intercept
        if (typeof ReplaySystem !== 'undefined' && ReplaySystem.playing) {
            if (ReplaySystem.handleKey(e.key)) { e.preventDefault(); return; }
        }

        // Replay toggle (R in world mode)
        if (e.code === 'KeyR' && GameState.mode === 'world') {
            if (typeof ReplaySystem !== 'undefined') ReplaySystem.toggleReplay();
            return;
        }

        // Debug overlay toggle (Ctrl+Shift+D)
        if (e.code === 'KeyD' && e.ctrlKey && e.shiftKey) {
            e.preventDefault();
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.toggle();
            return;
        }

        // Echo Dashboard toggle (backtick)
        if (e.code === 'Backquote' && GameState.mode === 'world') {
            if (typeof EchoDashboard !== 'undefined') EchoDashboard.toggle();
            return;
        }

        // Boot skip
        if (e.code === 'Space' && GameState.mode === 'boot') {
            e.preventDefault();
            Boot.skip();
            return;
        }

        // Bridge toggle
        if (e.code === 'KeyB' && GameState.mode !== 'boot') {
            Bridge.toggle();
            return;
        }

        // Minimap toggle
        if (e.code === 'KeyM' && GameState.mode === 'world') {
            if (e.shiftKey) HUD.toggleFullmap();
            else HUD.toggleMinimap();
            return;
        }

        // Interact
        if (e.code === 'KeyE' && GameState.mode === 'world') {
            WorldMode.interact();
            return;
        }

        // Poke agent
        if (e.code === 'KeyF' && GameState.mode === 'world') {
            WorldMode.pokeAgent();
            return;
        }

        // Equipment toggle
        if (e.code === 'KeyG' && GameState.mode === 'world') {
            if (typeof Equipment !== 'undefined') Equipment.toggle();
            return;
        }

        // Escape
        if (e.code === 'Escape') {
            if (typeof HUD !== 'undefined' && HUD.fullmapVisible) { HUD.toggleFullmap(); return; }
            if (typeof HelpOverlay !== 'undefined' && HelpOverlay.open) { HelpOverlay.close(); return; }
            if (Bridge.open) { Bridge.close(); return; }
            if (GameState.mode === 'approach') { Approach.abort(); return; }
            if (GameState.mode === 'landing') { Landing.abort(); return; }
            if (GameState.mode === 'world') {
                // Return to galaxy
                WorldMode.cleanup();
                if (typeof HUD !== 'undefined' && HUD.hideWorldPanels) HUD.hideWorldPanels();
                GameState.setMode('galaxy');
                Galaxy.show();
                return;
            }
        }

        // Galaxy planet browsing
        if (GameState.mode === 'galaxy' && !Bridge.open) {
            if (e.code === 'ArrowRight' || e.code === 'KeyD') Galaxy.browsePlanets(1);
            if (e.code === 'ArrowLeft' || e.code === 'KeyA') Galaxy.browsePlanets(-1);
            if (e.code === 'Enter' && Galaxy.selectedPlanetId) {
                const wid = Galaxy.selectedPlanetId;
                Warp.start(() => Approach.start(wid));
            }
        }

        // Abilities (1-5 in world mode)
        if (['Digit1','Digit2','Digit3','Digit4','Digit5'].includes(e.code) && GameState.mode === 'world') {
            const idx = parseInt(e.code.replace('Digit','')) - 1;
            if (typeof Abilities !== 'undefined') Abilities.useAbility(idx);
            return;
        }

        // Inventory toggle
        if (e.code === 'KeyI' && GameState.mode === 'world') {
            if (typeof Inventory !== 'undefined') Inventory.toggle();
            return;
        }

        // Fullscreen game mode (F11 or F)
        if (e.code === 'F11') {
            e.preventDefault();
            if (!document.fullscreenElement) {
                document.documentElement.requestFullscreen().catch(function(){});
            } else {
                document.exitFullscreen().catch(function(){});
            }
            return;
        }

        // Voice controls toggle
        if (e.code === 'KeyV' && GameState.mode !== 'boot') {
            if (typeof VoiceControls !== 'undefined') VoiceControls.toggle();
            return;
        }

        // Help overlay toggle
        if ((e.code === 'Slash' && e.shiftKey) || e.code === 'F1') {
            e.preventDefault();
            if (typeof HelpOverlay !== 'undefined') HelpOverlay.toggle();
            return;
        }

        // Gesture controls toggle
        if (e.code === 'KeyH' && GameState.mode !== 'boot') {
            if (typeof GestureControls !== 'undefined') GestureControls.toggle();
            return;
        }

        // Shop (P)
        if (e.code === 'KeyP' && GameState.mode === 'world') {
            if (typeof Shop !== 'undefined') Shop.toggle();
            return;
        }

        // Crafting (K)
        if (e.code === 'KeyK' && GameState.mode === 'world') {
            if (typeof Crafting !== 'undefined') Crafting.toggle();
            return;
        }

        // Cinematic mode
        if (e.code === 'KeyC' && GameState.mode === 'world') {
            document.body.classList.toggle('cinematic-active');
            return;
        }

        // Quick travel (Ctrl+1-4 for non-world modes)
        if (['Digit1','Digit2','Digit3','Digit4'].includes(e.code) && !Bridge.open && GameState.mode !== 'boot' && GameState.mode !== 'world') {
            const idx = parseInt(e.code.replace('Digit','')) - 1;
            const worldId = WORLD_IDS[idx];
            if (worldId) {
                if (GameState.mode === 'world') WorldMode.cleanup();
                if (GameState.mode === 'approach') Approach.abort();
                if (GameState.mode === 'landing') Landing.abort();
                if (GameState.mode === 'galaxy') Galaxy.hide();
                Approach.start(worldId);
            }
        }
    });

    // Resize
    window.addEventListener('resize', () => {
        if (GameState.renderer) {
            GameState.renderer.setSize(window.innerWidth, window.innerHeight);
        }
        Galaxy.onResize();
        WorldMode.onResize();
        if (typeof PostProcessing !== 'undefined') PostProcessing.onResize();
    });

    // Safe DOM event binding — prevents null crashes if elements are missing
    const _on = (id, evt, fn) => { const el = document.getElementById(id); if (el) el.addEventListener(evt, fn); };

    // Bridge close button
    _on('bridge-close', 'click', () => Bridge.close());

    // Bridge button
    _on('btn-bridge', 'click', () => Bridge.toggle());

    // Minimap button
    _on('btn-minimap', 'click', () => HUD.toggleMinimap());

    // ── Frame Timeline ──
    _on('timeline-slider', 'input', (e) => {
        if (typeof EchoEngine === 'undefined') return;
        var idx = parseInt(e.target.value);
        EchoEngine.scrubTo(idx);
        var f = EchoEngine.getCurrentFrame();
        var label = document.getElementById('timeline-label');
        var echoLabel = document.getElementById('timeline-echo');
        var narr = document.getElementById('timeline-narrative');
        var liveBtn = document.getElementById('timeline-live-btn');
        if (f && label) label.textContent = 'Frame ' + f.frame + ' · ' + (f.snapshot ? f.snapshot.world : '');
        if (f && echoLabel) {
            var L6 = f.echoes && f.echoes.L6;
            echoLabel.textContent = L6 ? 'L' + Math.round(L6.enrichableDetail.narrativeDepth) + ' ECHO' : 'L1';
        }
        if (f && f.echoes && f.echoes.L2 && narr) {
            narr.textContent = f.echoes.L2.narrative;
            narr.classList.add('visible');
        }
        if (liveBtn) liveBtn.classList.remove('active');
    });

    _on('timeline-live-btn', 'click', () => {
        if (typeof EchoEngine === 'undefined') return;
        EchoEngine.scrubToLive();
        var slider = document.getElementById('timeline-slider');
        if (slider) slider.value = slider.max;
        var echoLabel = document.getElementById('timeline-echo');
        if (echoLabel) echoLabel.textContent = 'LIVE';
        var narr = document.getElementById('timeline-narrative');
        if (narr) narr.classList.remove('visible');
        var liveBtn = document.getElementById('timeline-live-btn');
        if (liveBtn) liveBtn.classList.add('active');
        var label = document.getElementById('timeline-label');
        var f = EchoEngine.getCurrentFrame();
        if (f && label) label.textContent = 'Frame ' + f.frame + ' · LIVE';
    });

    // ── Fullmap close ──
    _on('fullmap-close', 'click', () => { if (typeof HUD !== 'undefined') HUD.toggleFullmap(); });

    // ── Fullscreen toggle ──
    _on('btn-fullscreen', 'click', () => {
        if (!document.fullscreenElement) {
            document.documentElement.requestFullscreen().catch(function(){});
        } else {
            document.exitFullscreen().catch(function(){});
        }
    });

    // ── Mute toggle ──
    _on('btn-mute', 'click', () => {
        if (typeof Audio === 'undefined' || !Audio.masterGain) return;
        var btn = document.getElementById('btn-mute');
        if (Audio.masterGain.gain.value > 0) {
            Audio._prevVolume = Audio.masterGain.gain.value;
            Audio.masterGain.gain.value = 0;
            if (btn) btn.textContent = '🔇';
        } else {
            Audio.masterGain.gain.value = Audio._prevVolume || 0.3;
            if (btn) btn.textContent = '🔊';
        }
    });

    // ── Screenshot / Share ──
    _on('btn-screenshot', 'click', () => {
        if (typeof Settings !== 'undefined') Settings.screenshot();
    });
    _on('btn-share', 'click', () => {
        if (typeof Settings !== 'undefined') Settings.shareLink();
    });

    // ── Voice / Gesture buttons ──
    _on('btn-voice', 'click', () => {
        if (typeof VoiceControls !== 'undefined') VoiceControls.toggle();
    });
    _on('btn-gesture', 'click', () => {
        if (typeof GestureControls !== 'undefined') GestureControls.toggle();
    });

    // ── Seed Export/Import ──
    _on('btn-export-seed', 'click', () => {
        if (GameState.mode !== 'world' || typeof WorldSeed === 'undefined') return;
        const worldId = GameState.currentWorld;
        const data = WorldSeed.exportWorld(worldId);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'rappterverse-' + worldId + '-seed.json';
        a.click();
        URL.revokeObjectURL(url);
        if (typeof HUD !== 'undefined') HUD.showToast('Exported ' + worldId + ' seed: ' + data.seed);
    });

    _on('btn-import-seed', 'click', () => {
        const inp = document.getElementById('seed-file-input');
        if (inp) inp.click();
    });

    _on('seed-file-input', 'change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            try {
                const json = JSON.parse(ev.target.result);
                const worldId = WorldSeed.importWorld(json);
                if (worldId) {
                    if (typeof HUD !== 'undefined') HUD.showToast('Imported seed ' + json.seed + ' for ' + worldId);
                    // Reload world if currently on it
                    if (worldId === GameState.currentWorld && GameState.mode === 'world') {
                        WorldMode.cleanup();
                        WorldMode.init(worldId);
                    }
                } else {
                    if (typeof HUD !== 'undefined') HUD.showToast('Invalid seed file');
                }
            } catch(err) {
                if (typeof HUD !== 'undefined') HUD.showToast('Failed to parse seed file');
            }
        };
        reader.readAsText(file);
        e.target.value = '';
    });

    // ── World Population quick-travel clicks ──
    _on('wp-list', 'click', (e) => {
        const item = e.target.closest('.wp-item');
        if (!item) return;
        const worldId = item.dataset.world;
        if (!worldId || worldId === GameState.currentWorld) return;
        if (GameState.mode === 'world') WorldMode.cleanup();
        if (GameState.mode === 'galaxy') Galaxy.hide();
        if (typeof HUD !== 'undefined' && HUD.hideWorldPanels) HUD.hideWorldPanels();
        Approach.start(worldId);
    });

    _on('btn-reset-seed', 'click', () => {
        if (GameState.mode !== 'world' || typeof WorldSeed === 'undefined') return;
        const worldId = GameState.currentWorld;
        WorldSeed.clearSeed(worldId);
        if (typeof HUD !== 'undefined') HUD.showToast('Reset seed for ' + worldId + ' — reloading terrain');
        WorldMode.cleanup();
        WorldMode.init(worldId);
    });

    // Boot skip button handler is in Boot.run()

    // Start
    function main() {
        GameState.clock = new THREE.Clock();
        try {
            localStorage.removeItem('rappterverse-token');
        } catch(e) {
            // Storage may be unavailable in privacy modes.
        }

        // Parse deep link: ?agent=clawdbot-001 or ?world=hub
        const urlParams = new URLSearchParams(window.location.search);
        GameState.deepLink = {
            agent: urlParams.get('agent'),
            world: urlParams.get('world'),
            chronicle: urlParams.get('chronicle')
        };

        // Init renderer
        const isMobile = /iphone|ipad|android/i.test(navigator.userAgent);
        GameState.renderer = new THREE.WebGLRenderer({
            antialias: !isMobile,
            powerPreference: isMobile ? 'low-power' : 'high-performance'
        });
        GameState.renderer.setSize(window.innerWidth, window.innerHeight);
        GameState.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        GameState.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        GameState.renderer.toneMappingExposure = 1.1;

        // Init optional systems
        if (typeof Settings !== 'undefined') Settings.init();
        if (typeof Chronicle !== 'undefined') Chronicle.init();
        if (typeof VoiceControls !== 'undefined') VoiceControls.init();
        if (typeof PostProcessing !== 'undefined') PostProcessing.init(GameState.renderer);

        // Run boot then start animation
        Boot.run();
        animate();
    }

    main();
})();
