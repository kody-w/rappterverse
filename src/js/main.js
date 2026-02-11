// Main — Entry Point & Animation Loop
(function() {
    // Animation loop
    function animate() {
        requestAnimationFrame(animate);
        const delta = GameState.clock ? GameState.clock.getDelta() : 0.016;
        const time = GameState.clock ? GameState.clock.getElapsedTime() : 0;

        switch(GameState.mode) {
            case 'galaxy':
                Galaxy.update(delta, time);
                Galaxy.render();
                break;
            case 'world':
                WorldMode.update(delta, time);
                WorldMode.render();
                break;
            // approach and landing handle their own rendering
        }

        // Update HUD periodically
        HUD.updateAgentCount();
        if (GameState.mode === 'world' && HUD.minimapVisible) {
            HUD.renderMinimap();
        }

        // Re-render bridge if open
        if (Bridge.open && Math.floor(time) % 3 === 0) {
            Bridge.render();
        }
    }

    // Keyboard
    document.addEventListener('keydown', (e) => {
        // Track keys for debug overlay
        if (typeof DebugOverlay !== 'undefined') DebugOverlay.recordKey(e.code);

        // Debug overlay toggle (Ctrl+Shift+D)
        if (e.code === 'KeyD' && e.ctrlKey && e.shiftKey) {
            e.preventDefault();
            if (typeof DebugOverlay !== 'undefined') DebugOverlay.toggle();
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
            HUD.toggleMinimap();
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
            if (Bridge.open) { Bridge.close(); return; }
            if (GameState.mode === 'approach') { Approach.abort(); return; }
            if (GameState.mode === 'landing') { Landing.abort(); return; }
            if (GameState.mode === 'world') {
                // Return to galaxy
                WorldMode.cleanup();
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
    });

    // Bridge close button
    document.getElementById('bridge-close').addEventListener('click', () => Bridge.close());

    // Bridge button
    document.getElementById('btn-bridge').addEventListener('click', () => Bridge.toggle());

    // Minimap button
    document.getElementById('btn-minimap').addEventListener('click', () => HUD.toggleMinimap());

    // Boot skip button handler is in Boot.run()

    // Start
    function main() {
        GameState.clock = new THREE.Clock();

        // Parse deep link: ?agent=clawdbot-001 or ?world=hub
        const urlParams = new URLSearchParams(window.location.search);
        GameState.deepLink = {
            agent: urlParams.get('agent'),
            world: urlParams.get('world')
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

        // Run boot then start animation
        Boot.run();
        animate();
    }

    main();
})();
