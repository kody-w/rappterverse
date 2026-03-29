// Replay System — Cinematic Battle Replay with Slow-Mo Kills
// Records combat events in real-time, replays with cinematic camera paths
// Toggle: R key | During replay: SPACE = pause, ESC = exit, ←/→ = speed

const ReplaySystem = {
    // Recording state
    recording: true,
    eventLog: [],       // { time, type, data }
    snapshots: [],      // { time, creeps[], projectiles[], momentum, wave, playerPos, heroPos, heroHp }
    maxEvents: 2000,
    maxSnapshots: 600,  // ~10 min at 1 snapshot/sec
    _lastSnapshotTime: 0,

    // Playback state
    playing: false,
    paused: false,
    playbackTime: 0,
    playbackSpeed: 1.0,
    playbackStartTime: 0,
    playbackDuration: 0,
    _savedCameraPos: null,
    _savedCameraTarget: null,
    _slowMoUntil: 0,
    _currentCameraMode: 'orbit',  // orbit, tracking, dramatic, topdown
    _cameraModeTimer: 0,
    _trackingTarget: null,
    _orbitAngle: 0,
    _killBannerTimeout: null,

    // Camera path keyframes for cinematic shots
    _cameraShots: [
        { name: 'orbit',    duration: 6,  height: 25, radius: 40, speed: 0.4 },
        { name: 'tracking', duration: 4,  height: 8,  offset: 6,  followDist: 12 },
        { name: 'dramatic', duration: 3,  height: 3,  radius: 8,  speed: 0.8 },
        { name: 'topdown',  duration: 5,  height: 60, radius: 0,  speed: 0 },
        { name: 'sweep',    duration: 5,  height: 15, radius: 50, speed: 0.2 },
    ],

    init() {
        this.eventLog = [];
        this.snapshots = [];
        this.recording = true;
        this.playing = false;
        this._lastSnapshotTime = 0;
        this._buildOverlay();
    },

    _buildOverlay() {
        if (document.getElementById('replay-overlay')) return;
        const el = document.createElement('div');
        el.id = 'replay-overlay';
        el.innerHTML = `
            <div class="replay-letterbox-top"></div>
            <div class="replay-letterbox-bot"></div>
            <div class="replay-scanlines"></div>
            <div class="replay-badge">&#9679; REPLAY</div>
            <div class="replay-timecode">00:00 / 00:00</div>
            <div class="replay-echo-panel" id="replay-echo-panel">
                <div class="replay-echo-frame" id="replay-echo-frame">F---</div>
                <div class="replay-echo-mood" id="replay-echo-mood"></div>
                <div class="replay-echo-tension-bar"><div class="replay-echo-tension-fill" id="replay-echo-tension-fill"></div></div>
                <div class="replay-echo-narrative" id="replay-echo-narrative"></div>
            </div>
            <div class="replay-kill-banner" id="replay-kill-banner"></div>
            <div class="replay-slowmo-flash" id="replay-slowmo-flash"></div>
            <div class="replay-ticker" id="replay-ticker"></div>
            <div class="replay-controls">R exit &middot; SPACE pause &middot; &larr;&rarr; speed</div>
        `;
        document.body.appendChild(el);
    },

    // === RECORDING ===

    logEvent(type, data) {
        if (!this.recording || this.playing) return;
        if (this.eventLog.length >= this.maxEvents) {
            this.eventLog.splice(0, 200); // trim oldest
        }
        this.eventLog.push({
            time: performance.now(),
            type: type,
            data: Object.assign({}, data)
        });
    },

    takeSnapshot() {
        if (!this.recording || this.playing) return;
        const now = performance.now();
        if (now - this._lastSnapshotTime < 1000) return; // 1 per second
        this._lastSnapshotTime = now;

        if (this.snapshots.length >= this.maxSnapshots) {
            this.snapshots.splice(0, 60);
        }

        const creepData = [];
        for (const c of WorldCombat.creeps) {
            if (!c.alive) continue;
            creepData.push({
                pos: { x: c.mesh.position.x, y: c.mesh.position.y, z: c.mesh.position.z },
                faction: c.faction,
                lane: c.lane,
                hp: c.hp,
                maxHp: c.maxHp,
                type: c.creepType,
                isBoss: !!c.isBoss,
                bossName: c.bossName || null,
                rotY: c.mesh.rotation.y
            });
        }

        const playerPos = WorldMode.player ? {
            x: WorldMode.player.mesh.position.x,
            y: WorldMode.player.mesh.position.y,
            z: WorldMode.player.mesh.position.z
        } : { x: 0, y: 0, z: 0 };

        const heroPos = (typeof EnemyHero !== 'undefined' && EnemyHero.mesh) ? {
            x: EnemyHero.mesh.position.x,
            y: EnemyHero.mesh.position.y,
            z: EnemyHero.mesh.position.z,
            hp: EnemyHero.state ? EnemyHero.state.hp : 0,
            alive: EnemyHero.state ? EnemyHero.state.alive : false
        } : null;

        // Capture echo state at this moment
        var echo = null;
        if (typeof EchoEngine !== 'undefined') {
            var ef = EchoEngine.getCurrentFrame();
            if (ef && ef.echoes) {
                echo = {
                    tension: ef.echoes.L3 ? ef.echoes.L3.tension : 0,
                    vitality: ef.echoes.L3 ? ef.echoes.L3.vitality : 0.5,
                    socialEnergy: ef.echoes.L3 ? ef.echoes.L3.socialEnergy : 0,
                    lightIntensity: ef.echoes.L3 ? ef.echoes.L3.lightIntensity : 1,
                    particleDensity: ef.echoes.L3 ? ef.echoes.L3.particleDensity : 0.5,
                    fogDensity: ef.echoes.L4 ? ef.echoes.L4.fogDensity : 0.002,
                    narrative: ef.echoes.L2 ? ef.echoes.L2.narrative : '',
                    dominantMood: ef.echoes.L2 ? ef.echoes.L2.dominantMood : 'neutral',
                    frame: ef.frame || 0,
                    popTrend: ef.echoes.L6 ? ef.echoes.L6.populationTrend : 'stable',
                    econArc: ef.echoes.L6 ? ef.echoes.L6.economicArc : 'steady'
                };
            }
        }

        this.snapshots.push({
            time: now,
            creeps: creepData,
            momentum: WorldCombat.momentum,
            wave: WorldCombat.waveNumber,
            playerPos: playerPos,
            heroPos: heroPos,
            creepCount: creepData.length,
            echo: echo
        });
    },

    // === PLAYBACK ===

    startReplay() {
        if (this.snapshots.length < 3) {
            if (typeof HUD !== 'undefined') HUD.showToast('Not enough combat data — fight some creeps first!');
            return;
        }

        this.playing = true;
        this.paused = false;
        this.recording = false;
        this.playbackSpeed = 1.0;
        this.playbackTime = 0;
        this._orbitAngle = 0;
        this._cameraModeTimer = 0;
        this._currentCameraMode = 'orbit';
        this._trackingTarget = null;

        // Save camera state
        this._savedCameraPos = WorldMode.camera.position.clone();

        // Calculate timeline
        const firstTime = this.snapshots[0].time;
        const lastTime = this.snapshots[this.snapshots.length - 1].time;
        this.playbackStartTime = firstTime;
        this.playbackDuration = (lastTime - firstTime) / 1000;

        // Build ghost creeps for replay visualization
        this._ghostCreeps = [];
        this._ghostProjectiles = [];

        // Pause echo engine live updates — replay will scrub echo state from snapshots
        if (typeof EchoEngine !== 'undefined') {
            this._wasEchoScrubbing = EchoEngine._scrubbing;
        }

        // Show overlay
        const overlay = document.getElementById('replay-overlay');
        if (overlay) overlay.classList.add('active');

        // Hide game HUD
        this._hideGameHUD(true);

        // Disable player input
        WorldMode.keys = {};

        if (typeof HUD !== 'undefined') HUD.showToast('REPLAY — R exit / SPACE pause / arrows speed');
    },

    stopReplay() {
        this.playing = false;
        this.recording = true;

        // Restore camera
        if (this._savedCameraPos) {
            WorldMode.camera.position.copy(this._savedCameraPos);
        }

        // Remove ghost meshes
        this._cleanupGhosts();

        // Hide overlay
        const overlay = document.getElementById('replay-overlay');
        if (overlay) overlay.classList.remove('active');

        // Show game HUD
        this._hideGameHUD(false);

        // Restore echo engine to live
        if (typeof EchoEngine !== 'undefined' && !this._wasEchoScrubbing) {
            EchoEngine.scrubToLive();
        }

        // Restore fog density
        if (WorldMode.scene && WorldMode.scene.fog) {
            WorldMode.scene.fog.density = 0.002;
        }

        // Clear timers
        if (this._shakeInterval) { clearInterval(this._shakeInterval); this._shakeInterval = null; }

        // Clear kill banner
        const banner = document.getElementById('replay-kill-banner');
        if (banner) banner.classList.remove('show');
        const flash = document.getElementById('replay-slowmo-flash');
        if (flash) flash.classList.remove('active');

        if (typeof HUD !== 'undefined') HUD.showToast('Replay ended');
    },

    toggleReplay() {
        if (this.playing) {
            this.stopReplay();
        } else {
            this.startReplay();
        }
    },

    // === UPDATE (called every frame from WorldMode.update) ===

    update(delta, time) {
        // Always take snapshots while recording
        if (this.recording && !this.playing && WorldCombat.active) {
            this.takeSnapshot();
        }

        if (!this.playing) return;
        if (this.paused) {
            this._updateReplayCamera(0, time);
            this._updateOverlay();
            return;
        }

        // Advance playback time
        var speed = this.playbackSpeed;
        if (performance.now() < this._slowMoUntil) {
            speed *= 0.15; // slow-mo
        }
        this.playbackTime += delta * speed;

        // Loop or end
        if (this.playbackTime >= this.playbackDuration) {
            this.playbackTime = 0; // loop
        }

        // Find current snapshot
        var targetTime = this.playbackStartTime + this.playbackTime * 1000;
        var snapIdx = this._findSnapshotIndex(targetTime);
        var snap = this.snapshots[snapIdx];

        // Check for kill events near this time window
        this._checkKillEvents(targetTime);

        // Update ghost creeps
        this._updateGhostCreeps(snap);

        // Update camera
        this._updateReplayCamera(delta * speed, time);

        // Update overlay
        this._updateOverlay();
    },

    _findSnapshotIndex(targetTime) {
        // Binary search for closest snapshot
        var lo = 0, hi = this.snapshots.length - 1;
        while (lo < hi) {
            var mid = (lo + hi + 1) >> 1;
            if (this.snapshots[mid].time <= targetTime) lo = mid;
            else hi = mid - 1;
        }
        return lo;
    },

    // === GHOST CREEPS (replay visualization) ===

    _updateGhostCreeps(snap) {
        if (!snap) return;
        var scene = WorldMode.scene;

        // Remove excess ghosts
        while (this._ghostCreeps.length > snap.creeps.length) {
            var g = this._ghostCreeps.pop();
            if (g.parent) g.parent.remove(g);
            g.traverse(function(child) {
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
            });
        }

        // Add/update ghosts
        for (var i = 0; i < snap.creeps.length; i++) {
            var cd = snap.creeps[i];
            var ghost = this._ghostCreeps[i];

            if (!ghost) {
                ghost = this._createGhostCreep(cd);
                scene.add(ghost);
                this._ghostCreeps.push(ghost);
            }

            // Smooth lerp to target position (skip when paused)
            if (!this.paused) {
                ghost.position.x += (cd.pos.x - ghost.position.x) * 0.15;
                ghost.position.y += (cd.pos.y - ghost.position.y) * 0.15;
                ghost.position.z += (cd.pos.z - ghost.position.z) * 0.15;
            }
            ghost.rotation.y = cd.rotY;

            // Update color based on faction/boss — echo-reactive glow
            var bodyMesh = ghost.children[0];
            if (bodyMesh && bodyMesh.material) {
                var c = cd.faction === 'explorer' ? 0x00ff88 : 0xff4488;
                if (cd.isBoss) c = 0xaa44ff;
                bodyMesh.material.color.setHex(c);
                bodyMesh.material.emissive.setHex(c);
                // Ghost glow — pulses faster with tension, brighter with vitality
                var echoT = (snap && snap.echo) ? snap.echo.tension : 0;
                var echoV = (snap && snap.echo) ? snap.echo.vitality : 0.5;
                var pulseSpeed = 0.003 + echoT * 0.006;
                var baseGlow = 0.3 + echoV * 0.3;
                bodyMesh.material.emissiveIntensity = baseGlow + Math.sin(performance.now() * pulseSpeed + i) * (0.15 + echoT * 0.15);
                bodyMesh.material.opacity = 0.7 + echoV * 0.2;
            }
        }
    },

    _createGhostCreep(cd) {
        var group = new THREE.Group();
        var size = cd.isBoss ? 1.5 : (cd.type === 'siege' ? 0.6 : 0.4);
        var geo;
        if (cd.isBoss) geo = new THREE.SphereGeometry(size, 10, 10);
        else if (cd.type === 'ranged') geo = new THREE.OctahedronGeometry(size, 0);
        else if (cd.type === 'siege') geo = new THREE.BoxGeometry(size * 1.5, size * 1.2, size * 1.5);
        else geo = new THREE.SphereGeometry(size, 8, 8);

        var color = cd.faction === 'explorer' ? 0x00ff88 : 0xff4488;
        if (cd.isBoss) color = 0xaa44ff;

        var mat = new THREE.MeshStandardMaterial({
            color: color,
            emissive: color,
            emissiveIntensity: 0.5,
            transparent: true,
            opacity: 0.8,
            roughness: 0.3
        });
        var body = new THREE.Mesh(geo, mat);
        body.position.y = size + 0.1;
        group.add(body);

        // Ghost trail ring
        var ringGeo = new THREE.RingGeometry(size * 0.8, size * 1.2, 16);
        var ringMat = new THREE.MeshBasicMaterial({
            color: color, transparent: true, opacity: 0.2, side: THREE.DoubleSide
        });
        var ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.05;
        group.add(ring);

        return group;
    },

    _cleanupGhosts() {
        for (var i = 0; i < this._ghostCreeps.length; i++) {
            var g = this._ghostCreeps[i];
            if (g.parent) g.parent.remove(g);
            g.traverse(function(child) {
                if (child.geometry) child.geometry.dispose();
                if (child.material) child.material.dispose();
            });
        }
        this._ghostCreeps = [];
    },

    // === CINEMATIC CAMERA ===

    _updateReplayCamera(delta, time) {
        if (!WorldMode.camera || !WorldMode.scene) return;

        this._cameraModeTimer -= delta;
        if (this._cameraModeTimer <= 0) {
            this._advanceCameraMode();
        }

        var cam = WorldMode.camera;
        var centerX = 0, centerZ = 0;

        // Find center of action from current snapshot
        var snapIdx = this._findSnapshotIndex(this.playbackStartTime + this.playbackTime * 1000);
        var snap = this.snapshots[snapIdx];
        if (snap && snap.creeps.length > 0) {
            for (var i = 0; i < snap.creeps.length; i++) {
                centerX += snap.creeps[i].pos.x;
                centerZ += snap.creeps[i].pos.z;
            }
            centerX /= snap.creeps.length;
            centerZ /= snap.creeps.length;
        }

        var isSlowMo = performance.now() < this._slowMoUntil;

        // Echo-reactive camera parameters
        var echoData = snap ? snap.echo : null;
        var tension = echoData ? echoData.tension : 0;
        var vitality = echoData ? echoData.vitality : 0.5;
        // High tension = tighter shots, faster cuts; low tension = wider, slower
        var tensionSpeedMod = 1 + tension * 0.6;
        var tensionRadiusMod = 1 - tension * 0.3; // tighter radius when tense
        var tensionHeightMod = 1 - tension * 0.2;  // lower camera when tense

        switch (this._currentCameraMode) {
            case 'orbit':
                this._orbitAngle += delta * 0.4 * tensionSpeedMod;
                var orbitR = 40 * tensionRadiusMod;
                var ox = centerX + Math.cos(this._orbitAngle) * orbitR;
                var oz = centerZ + Math.sin(this._orbitAngle) * orbitR;
                var targetPos = new THREE.Vector3(ox, 25 * tensionHeightMod, oz);
                cam.position.lerp(targetPos, 0.03);
                cam.lookAt(centerX, 2, centerZ);
                break;

            case 'tracking':
                // Follow the most interesting target (boss > hero > random creep)
                var trackPos = this._getTrackingTarget(snap);
                if (trackPos) {
                    var trackDist = 12 * tensionRadiusMod;
                    var tx = trackPos.x + 6 * tensionRadiusMod;
                    var ty = 8 * tensionHeightMod;
                    var tz = trackPos.z + trackDist;
                    cam.position.lerp(new THREE.Vector3(tx, ty, tz), isSlowMo ? 0.01 : 0.04 * tensionSpeedMod);
                    cam.lookAt(trackPos.x, 1.5, trackPos.z);
                }
                break;

            case 'dramatic':
                // Low angle, close to action, slow orbit — even tighter when tense
                this._orbitAngle += delta * 0.8 * tensionSpeedMod;
                var dr = (isSlowMo ? 5 : 8) * tensionRadiusMod;
                var dh = 3 * tensionHeightMod;
                var dx = centerX + Math.cos(this._orbitAngle) * dr;
                var dz = centerZ + Math.sin(this._orbitAngle) * dr;
                cam.position.lerp(new THREE.Vector3(dx, Math.max(1.5, dh), dz), 0.05);
                cam.lookAt(centerX, 1, centerZ);
                break;

            case 'topdown':
                var topH = 60 * (1 - tension * 0.15);
                cam.position.lerp(new THREE.Vector3(centerX, topH, centerZ + 5), 0.02);
                cam.lookAt(centerX, 0, centerZ);
                break;

            case 'sweep':
                // Wide sweeping arc across the battlefield
                this._orbitAngle += delta * 0.2 * tensionSpeedMod;
                var sweepR = 50 * tensionRadiusMod;
                var sx = Math.cos(this._orbitAngle) * sweepR;
                var sz = Math.sin(this._orbitAngle) * sweepR;
                cam.position.lerp(new THREE.Vector3(sx, 15 * tensionHeightMod, sz), 0.02);
                cam.lookAt(0, 0, 0);
                break;
        }
    },

    _advanceCameraMode() {
        var shots = this._cameraShots;
        var currentIdx = shots.findIndex(function(s) { return s.name === ReplaySystem._currentCameraMode; });
        var nextIdx = (currentIdx + 1) % shots.length;

        // On kills, force dramatic mode
        if (performance.now() < this._slowMoUntil) {
            nextIdx = shots.findIndex(function(s) { return s.name === 'dramatic'; });
        }

        this._currentCameraMode = shots[nextIdx].name;
        // Echo-reactive duration — high tension = faster cuts
        var baseDuration = shots[nextIdx].duration;
        var snapIdx = this._findSnapshotIndex(this.playbackStartTime + this.playbackTime * 1000);
        var snap = this.snapshots[snapIdx];
        var tension = (snap && snap.echo) ? snap.echo.tension : 0;
        this._cameraModeTimer = baseDuration * (1 - tension * 0.4); // Up to 40% faster cuts
    },

    _getTrackingTarget(snap) {
        if (!snap || snap.creeps.length === 0) return { x: 0, y: 0, z: 0 };

        // Prefer boss
        for (var i = 0; i < snap.creeps.length; i++) {
            if (snap.creeps[i].isBoss) return snap.creeps[i].pos;
        }

        // Prefer hero
        if (snap.heroPos && snap.heroPos.alive) return snap.heroPos;

        // Random creep that changes every few seconds
        var idx = Math.floor(performance.now() / 3000) % snap.creeps.length;
        return snap.creeps[idx].pos;
    },

    // === KILL EVENTS ===

    _checkKillEvents(targetTime) {
        var windowMs = 1500;
        for (var i = 0; i < this.eventLog.length; i++) {
            var evt = this.eventLog[i];
            if (evt._played) continue;
            if (Math.abs(evt.time - targetTime) > windowMs) continue;

            evt._played = true;

            if (evt.type === 'kill') {
                this._triggerSlowMo(evt.data);
            } else if (evt.type === 'boss_spawn') {
                this._showTicker('BOSS INCOMING: ' + (evt.data.name || 'Unknown'));
            } else if (evt.type === 'wave') {
                this._showTicker('WAVE ' + evt.data.number + (evt.data.siege ? ' [SIEGE]' : ''));
            } else if (evt.type === 'boss_kill') {
                this._triggerSlowMo({ name: evt.data.name + ' SLAIN', isBoss: true });
            } else if (evt.type === 'tower_destroy') {
                this._showTicker('TOWER DESTROYED');
            }
        }
    },

    _triggerSlowMo(data) {
        // Enter slow-mo for 2 seconds
        this._slowMoUntil = performance.now() + 2000;

        // Force dramatic camera
        this._currentCameraMode = 'dramatic';
        this._cameraModeTimer = 2.5;

        // Show kill banner — echo-tinted
        var banner = document.getElementById('replay-kill-banner');
        if (banner) {
            var text = data.isBoss ? data.name : 'ELIMINATED';
            if (data.name && !data.isBoss) text = data.name;
            banner.textContent = text;

            // Echo-reactive banner color
            var snapIdx = this._findSnapshotIndex(this.playbackStartTime + this.playbackTime * 1000);
            var snap = this.snapshots[snapIdx];
            var echoT = (snap && snap.echo) ? snap.echo.tension : 0;
            if (echoT > 0.5) {
                banner.style.color = '#ff2222';
                banner.style.textShadow = '0 0 30px rgba(255,34,34,0.9), 0 0 80px rgba(255,34,34,0.5)';
            } else if (data.isBoss) {
                banner.style.color = '#aa44ff';
                banner.style.textShadow = '0 0 30px rgba(170,68,255,0.9), 0 0 80px rgba(170,68,255,0.5)';
            } else {
                banner.style.color = '#ff4444';
                banner.style.textShadow = '0 0 30px rgba(255,68,68,0.9), 0 0 60px rgba(255,68,68,0.5)';
            }

            banner.classList.remove('show');
            void banner.offsetWidth; // reflow
            banner.classList.add('show');
        }

        // Flash vignette
        var flash = document.getElementById('replay-slowmo-flash');
        if (flash) {
            flash.classList.add('active');
            setTimeout(function() { flash.classList.remove('active'); }, 1800);
        }

        // Screen shake
        this._screenShake(data.isBoss ? 1.5 : 0.6);
    },

    _shakeInterval: null,
    _screenShake(intensity) {
        if (!WorldMode.camera) return;
        // Clear any existing shake
        if (this._shakeInterval) clearInterval(this._shakeInterval);
        var cam = WorldMode.camera;
        var origX = cam.position.x;
        var origY = cam.position.y;
        var shakeCount = 0;
        var maxShakes = 8;
        var self = this;
        this._shakeInterval = setInterval(function() {
            shakeCount++;
            var decay = 1 - (shakeCount / maxShakes);
            cam.position.x = origX + (Math.random() - 0.5) * intensity * decay;
            cam.position.y = origY + (Math.random() - 0.5) * intensity * 0.5 * decay;
            if (shakeCount >= maxShakes) {
                clearInterval(self._shakeInterval);
                self._shakeInterval = null;
            }
        }, 30);
    },

    _showTicker(msg) {
        var ticker = document.getElementById('replay-ticker');
        if (ticker) ticker.textContent = msg;
    },

    // === OVERLAY ===

    _updateOverlay() {
        // Timecode
        var tc = document.querySelector('.replay-timecode');
        if (tc) {
            var current = this._formatTime(this.playbackTime);
            var total = this._formatTime(this.playbackDuration);
            var speedStr = this.playbackSpeed !== 1.0 ? ' [' + this.playbackSpeed.toFixed(1) + 'x]' : '';
            var slowStr = performance.now() < this._slowMoUntil ? ' SLOW-MO' : '';
            var pauseStr = this.paused ? ' PAUSED' : '';
            tc.textContent = current + ' / ' + total + speedStr + slowStr + pauseStr;
        }

        // Echo panel — pull echo data from current snapshot
        var snapIdx = this._findSnapshotIndex(this.playbackStartTime + this.playbackTime * 1000);
        var snap = this.snapshots[snapIdx];
        var echo = snap ? snap.echo : null;

        if (echo) {
            var frameEl = document.getElementById('replay-echo-frame');
            if (frameEl) frameEl.textContent = 'F' + echo.frame + ' L' + Math.ceil(echo.tension * 6);

            var moodEl = document.getElementById('replay-echo-mood');
            if (moodEl) {
                var moodIcons = { neutral: '', thriving: '', content: '', anxious: '', desperate: '' };
                moodEl.textContent = echo.dominantMood.toUpperCase() + (echo.popTrend !== 'stable' ? ' / ' + echo.popTrend : '') + (echo.econArc !== 'steady' ? ' / econ ' + echo.econArc : '');
            }

            var tensionFill = document.getElementById('replay-echo-tension-fill');
            if (tensionFill) {
                tensionFill.style.width = (echo.tension * 100) + '%';
                // Color: green (low) → orange → red (high)
                if (echo.tension > 0.6) tensionFill.style.background = '#ff4444';
                else if (echo.tension > 0.3) tensionFill.style.background = '#ffaa00';
                else tensionFill.style.background = '#00ff88';
            }

            var narrEl = document.getElementById('replay-echo-narrative');
            if (narrEl && echo.narrative) {
                narrEl.textContent = echo.narrative;
            }

            // Apply echo atmosphere during replay — fog density, light intensity
            this._applyEchoAtmosphere(echo);
        }
    },

    _applyEchoAtmosphere(echo) {
        if (!echo || !WorldMode.scene) return;

        // Fog reacts to tension
        if (WorldMode.scene.fog) {
            var targetFog = echo.fogDensity || 0.002;
            WorldMode.scene.fog.density += (targetFog - WorldMode.scene.fog.density) * 0.05;
        }

        // Ambient light dims with tension
        if (WorldMode.scene.children) {
            for (var i = 0; i < WorldMode.scene.children.length; i++) {
                var child = WorldMode.scene.children[i];
                if (child.isAmbientLight) {
                    var targetIntensity = echo.lightIntensity * 0.6;
                    child.intensity += (targetIntensity - child.intensity) * 0.03;
                }
            }
        }

        // VFX ambient particles scaled by echo vitality + social energy
        if (typeof VFX !== 'undefined' && VFX.active) {
            // Spawn ambient echo particles around the action center based on atmosphere
            if (!this._echoEmitTimer) this._echoEmitTimer = 0;
            this._echoEmitTimer -= 0.016;
            if (this._echoEmitTimer <= 0) {
                var interval = Math.max(0.1, 1.0 - echo.particleDensity);
                this._echoEmitTimer = interval;

                // Tension sparks — red ambient particles when tension is high
                if (echo.tension > 0.3 && Math.random() < echo.tension) {
                    var snapIdx2 = this._findSnapshotIndex(this.playbackStartTime + this.playbackTime * 1000);
                    var s = this.snapshots[snapIdx2];
                    if (s && s.creeps.length > 0) {
                        var rc = s.creeps[Math.floor(Math.random() * s.creeps.length)];
                        VFX.burst(
                            { x: rc.pos.x + (Math.random() - 0.5) * 4, y: 2, z: rc.pos.z + (Math.random() - 0.5) * 4 },
                            'echoTension', { count: 2 }
                        );
                    }
                }

                // Vitality glow — green ambient when world is alive
                if (echo.vitality > 0.4 && Math.random() < echo.vitality * 0.3) {
                    var rx = (Math.random() - 0.5) * 60;
                    var rz = (Math.random() - 0.5) * 60;
                    VFX.burst({ x: rx, y: 0.5, z: rz }, 'echoVitality', { count: 1 });
                }

                // Social fireflies — golden sparks near agents when social energy is high
                if (echo.socialEnergy > 0.5 && Math.random() < echo.socialEnergy * 0.4) {
                    var sx = (Math.random() - 0.5) * 40;
                    var sz = (Math.random() - 0.5) * 40;
                    VFX.burst({ x: sx, y: 1 + Math.random() * 3, z: sz }, 'echoSocial', { count: 1 });
                }
            }
        }
    },

    _formatTime(seconds) {
        var m = Math.floor(seconds / 60);
        var s = Math.floor(seconds % 60);
        return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
    },

    _hideGameHUD(hide) {
        var ids = ['combat-hud', 'player-stats-bar', 'gold-kda-bar', 'level-badge', 'ability-bar', 'minimap-container'];
        for (var i = 0; i < ids.length; i++) {
            var el = document.getElementById(ids[i]);
            if (el) el.style.opacity = hide ? '0' : '1';
        }
    },

    // === INPUT ===

    handleKey(key) {
        if (!this.playing) return false;

        switch (key) {
            case 'Escape':
            case 'r':
                this.stopReplay();
                return true;
            case ' ':
                this.paused = !this.paused;
                return true;
            case 'ArrowRight':
                this.playbackSpeed = Math.min(4.0, this.playbackSpeed + 0.5);
                this._showTicker('Speed: ' + this.playbackSpeed.toFixed(1) + 'x');
                return true;
            case 'ArrowLeft':
                this.playbackSpeed = Math.max(0.25, this.playbackSpeed - 0.25);
                this._showTicker('Speed: ' + this.playbackSpeed.toFixed(1) + 'x');
                return true;
            case 'ArrowUp':
                // Skip forward 5 seconds
                this.playbackTime = Math.min(this.playbackDuration, this.playbackTime + 5);
                return true;
            case 'ArrowDown':
                // Skip backward 5 seconds
                this.playbackTime = Math.max(0, this.playbackTime - 5);
                return true;
        }
        return false;
    },

    cleanup() {
        if (this.playing) this.stopReplay();
        this._cleanupGhosts();
        // Reset played flags BEFORE clearing
        for (var i = 0; i < this.eventLog.length; i++) {
            delete this.eventLog[i]._played;
        }
        this.eventLog = [];
        this.snapshots = [];
    }
};
