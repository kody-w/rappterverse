// World Core — WorldMode Orchestrator (Player, Camera, Game Loop)
const WorldMode = {
    scene: null,
    camera: null,
    active: false,
    currentWorld: null,
    player: null,
    playerSpeed: 25,
    keys: {},
    cameraZoom: 1.0,      // 0.4 = close, 1.0 = default, 2.0 = far
    _cameraBaseY: 8,
    _cameraBaseZ: 12,

    init(worldId) {
        this.currentWorld = worldId;
        this.active = true;
        GameState.currentWorld = worldId;
        if (typeof WorldSeed !== 'undefined') WorldSeed.init();

        const w = WORLDS[worldId];

        // Scene
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(w.sky);
        this.scene.fog = new THREE.FogExp2(w.fog, 0.002);

        // Camera
        this.camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 2000);

        // Renderer
        const container = document.getElementById('world-container');
        container.innerHTML = '';
        container.appendChild(GameState.renderer.domElement);
        container.style.display = 'block';

        // Show combat HUD
        document.getElementById('combat-hud').style.display = 'flex';
        const statsBar = document.getElementById('player-stats-bar');
        if (statsBar) statsBar.style.display = 'flex';
        const goldBar = document.getElementById('gold-kda-bar');
        if (goldBar) goldBar.style.display = 'flex';
        const levelBadge = document.getElementById('level-badge');
        if (levelBadge) levelBadge.style.display = 'block';
        const abilityBar = document.getElementById('ability-bar');
        if (abilityBar) abilityBar.style.display = 'flex';

        // Build terrain, lanes, combat, agents
        WorldTerrain.build(this.scene, w, worldId);
        WorldLanes.init(this.scene, w);
        if (typeof VFX !== 'undefined') VFX.init(this.scene);
        WorldCombat.init(this.scene);
        if (typeof JungleCamps !== "undefined") JungleCamps.init(this.scene, w);
        if (typeof FogOfWar !== 'undefined') FogOfWar.init(this.scene, w);
        WorldAgents.loadObjects(this.scene, worldId);
        WorldAgents.syncAgents(this.scene, worldId);

        // Init RPG systems
        if (typeof PlayerStats !== 'undefined') { PlayerStats.init(); PlayerStats.load(); }
        if (typeof Abilities !== 'undefined') Abilities.init();
        if (typeof ComboSystem !== 'undefined') ComboSystem.reset();
        if (typeof Inventory !== 'undefined') Inventory.init();
        if (typeof Equipment !== 'undefined') Equipment.init();
        if (typeof StatusEffects !== 'undefined') StatusEffects.cleanup();
        if (typeof EnemyHero !== 'undefined') EnemyHero.init(this.scene, w.bounds);

        // Player
        this.createPlayer(w);

        // Deep link: teleport player to target agent
        if (GameState.deepLink?.agent) {
            const target = GameState.data.agents.find(a => a.id === GameState.deepLink.agent);
            if (target && target.position) {
                this.player.mesh.position.set(target.position.x + 2, 0, target.position.z + 2);
            }
            GameState.deepLink = null; // consume deep link
        }

        // Key listeners
        this.keyDown = (e) => {
            if (!GameState.inputLocked) this.keys[e.code] = true;
        };
        this.keyUp = (e) => { this.keys[e.code] = false; };
        window.addEventListener('keydown', this.keyDown);
        window.addEventListener('keyup', this.keyUp);

        // Scroll wheel zoom
        this._onWheel = (e) => {
            if (!this.active || GameState.mode !== 'world' || GameState.inputLocked) return;
            e.preventDefault();
            this.cameraZoom += e.deltaY * 0.001;
            this.cameraZoom = Math.max(0.4, Math.min(2.5, this.cameraZoom));
        };
        window.addEventListener('wheel', this._onWheel, { passive: false });

        // Set mode to world so main loop renders us
        GameState.setMode('world');

        // HUD
        if (typeof HUD !== 'undefined') {
            HUD.setWorld(worldId);
            HUD.showToast(`Landed on ${w.name} — SPACE to attack, WASD to move`);
            if (HUD.initChatFeed) HUD.initChatFeed();
            GameState.currentWorld = worldId;
        }
        // Show seed in HUD
        if (typeof WorldSeed !== 'undefined') {
            const seedEl = document.getElementById('seed-value');
            if (seedEl) seedEl.textContent = WorldSeed.getSeed(worldId);
        }
        // Show Rappterbook-style world panels + minimap
        if (typeof HUD !== 'undefined') {
            if (HUD.showWorldPanels) HUD.showWorldPanels();
            if (!HUD.minimapVisible) HUD.toggleMinimap();
        }
        // Show mobile touch controls
        if (typeof TouchControls !== 'undefined') { TouchControls.init(); TouchControls.show(); }
        // First-time tutorial
        if (typeof Tutorial !== 'undefined') Tutorial.start();
        // Quest tracker
        if (typeof QuestTracker !== 'undefined') QuestTracker.show();
        // Init Replay System
        if (typeof ReplaySystem !== 'undefined') ReplaySystem.init();

        // Init Echo Engine
        if (typeof EchoEngine !== 'undefined') {
            EchoEngine.init();
            EchoEngine.captureFrame();
            EchoEngine.applyEchoToWorld();
            // Show timeline
            var tl = document.getElementById('frame-timeline');
            if (tl) tl.classList.add('visible');
        }
        // Init Lispy VM
        // RappterOS available for agent compute (boots on demand)
        if (typeof RappterOS !== 'undefined' && RappterOS.registerVMFunctions) RappterOS.registerVMFunctions();
        if (typeof RappterVM !== 'undefined') {
            RappterVM.init();
            RappterVM.onFrameArrival(GameState.data);
            // Register echo shapers
            RappterVM.registerShaper('terrain', 4, function(d) { return typeof WorldSeed !== 'undefined' ? WorldSeed.getSeed(GameState.currentWorld) : 0; });
            RappterVM.registerShaper('weather', 4, function(d) { return typeof WorldTerrain !== 'undefined' ? WorldTerrain.weatherType : 'clear'; });
            RappterVM.registerShaper('mood-lighting', 4, function(d) {
                var gs = d.gameState || {};
                var trend = gs.economy ? gs.economy.market_trend : 'stable';
                return trend === 'bull' ? 1.2 : trend === 'bear' ? 0.7 : 1.0;
            });
        }
    },

    createPlayer(w) {
        const group = new THREE.Group();

        // Body
        const bodyGeo = new THREE.CylinderGeometry(0.35, 0.35, 1.05, 8);
        const bodyMat = new THREE.MeshStandardMaterial({
            color: 0x8888cc, emissive: 0x4444aa, emissiveIntensity: 0.2,
            roughness: 0.3, metalness: 0.7
        });
        const body = new THREE.Mesh(bodyGeo, bodyMat);
        body.position.y = 0.9;
        group.add(body);

        // Head
        const headGeo = new THREE.SphereGeometry(0.25, 8, 8);
        const headMat = new THREE.MeshStandardMaterial({
            color: 0xccccff, emissive: 0x6666cc, emissiveIntensity: 0.3,
            roughness: 0.2, metalness: 0.5
        });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.y = 1.65;
        group.add(head);

        // Eyes
        const eyeGeo = new THREE.SphereGeometry(0.05, 6, 6);
        const eyeMat = new THREE.MeshBasicMaterial({ color: 0x00ffff });
        const eyeL = new THREE.Mesh(eyeGeo, eyeMat);
        eyeL.position.set(-0.1, 1.68, 0.2);
        group.add(eyeL);
        const eyeR = new THREE.Mesh(eyeGeo, eyeMat);
        eyeR.position.set(0.1, 1.68, 0.2);
        group.add(eyeR);

        // Arms
        const armGeo = new THREE.BoxGeometry(0.12, 0.5, 0.12);
        const armMat = new THREE.MeshStandardMaterial({ color: 0x7777aa, metalness: 0.6, roughness: 0.4 });
        const armL = new THREE.Mesh(armGeo, armMat);
        armL.position.set(-0.5, 0.85, 0);
        group.add(armL);
        const armR = new THREE.Mesh(armGeo, armMat);
        armR.position.set(0.5, 0.85, 0);
        group.add(armR);

        // Legs
        const legGeo = new THREE.BoxGeometry(0.14, 0.45, 0.14);
        const legMat = new THREE.MeshStandardMaterial({ color: 0x6666aa, metalness: 0.6, roughness: 0.4 });
        const legL = new THREE.Mesh(legGeo, legMat);
        legL.position.set(-0.15, 0.22, 0);
        group.add(legL);
        const legR = new THREE.Mesh(legGeo, legMat);
        legR.position.set(0.15, 0.22, 0);
        group.add(legR);

        // Ground ring
        const ringGeo = new THREE.RingGeometry(0.4, 0.55, 16);
        const ringMat = new THREE.MeshBasicMaterial({
            color: 0x00ffff, side: THREE.DoubleSide, transparent: true, opacity: 0.3
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.01;
        group.add(ring);

        group.position.set(0, 0, 5);
        this.player = { mesh: group, velocity: new THREE.Vector3(), body, head, armL, armR, legL, legR, ring };
        this.scene.add(group);
    },

    update(delta, time) {
        if (!this.active || !this.player) return;
        const w = WORLDS[this.currentWorld];

        // Player movement
        const moveDir = new THREE.Vector3();
        if (this.keys['KeyW'] || this.keys['ArrowUp']) moveDir.z -= 1;
        if (this.keys['KeyS'] || this.keys['ArrowDown']) moveDir.z += 1;
        if (this.keys['KeyA'] || this.keys['ArrowLeft']) moveDir.x -= 1;
        if (this.keys['KeyD'] || this.keys['ArrowRight']) moveDir.x += 1;

        if (moveDir.length() > 0) {
            moveDir.normalize();
            this.player.mesh.position.x += moveDir.x * this.playerSpeed * delta;
            this.player.mesh.position.z += moveDir.z * this.playerSpeed * delta;
            this.player.mesh.rotation.y = Math.atan2(moveDir.x, moveDir.z);
            // Footstep sound + trail particles (throttled)
            if (!this._lastFootstep || time - this._lastFootstep > 0.3) {
                this._lastFootstep = time;
                if (typeof Audio !== 'undefined' && Audio.playFootstep) Audio.playFootstep();
                // Echo-reactive movement trail
                if (typeof VFX !== 'undefined') {
                    var trailPreset = 'dashTrail';
                    if (typeof EchoEngine !== 'undefined') {
                        var ef = EchoEngine.getCurrentFrame();
                        if (ef && ef.echoes && ef.echoes.L3 && ef.echoes.L3.tension > 0.5) trailPreset = 'echoTension';
                    }
                    VFX.burst(this.player.mesh.position, trailPreset, { count: 1 });
                }
            }

            // Walk animation
            const walkCycle = Math.sin(time * 8);
            this.player.armL.rotation.x = walkCycle * 0.4;
            this.player.armR.rotation.x = -walkCycle * 0.4;
            this.player.legL.rotation.x = -walkCycle * 0.3;
            this.player.legR.rotation.x = walkCycle * 0.3;
        } else {
            // Idle bob
            this.player.body.position.y = 0.9 + Math.sin(time * 2) * 0.05;
            this.player.head.position.y = 1.65 + Math.sin(time * 2) * 0.05;
            this.player.armL.rotation.x *= 0.9;
            this.player.armR.rotation.x *= 0.9;
            this.player.legL.rotation.x *= 0.9;
            this.player.legR.rotation.x *= 0.9;
        }

        // Player attack (SPACE)
        if (this.keys['Space']) {
            WorldCombat.playerAttack(this.player.mesh.position);
        }

        // Clamp to bounds
        this.player.mesh.position.x = Math.max(-w.bounds.x, Math.min(w.bounds.x, this.player.mesh.position.x));
        this.player.mesh.position.z = Math.max(-w.bounds.z, Math.min(w.bounds.z, this.player.mesh.position.z));

        // Follow terrain height
        if (typeof WorldTerrain !== 'undefined' && WorldTerrain.getHeight) {
            const terrainY = WorldTerrain.getHeight(this.player.mesh.position.x, this.player.mesh.position.z);
            this.player.mesh.position.y += (terrainY - this.player.mesh.position.y) * 0.15;
        }

        // Camera follow (skip during replay — ReplaySystem controls camera)
        if (typeof ReplaySystem === 'undefined' || !ReplaySystem.playing) {
            const camTarget = this.player.mesh.position.clone().add(new THREE.Vector3(0, this._cameraBaseY * this.cameraZoom, this._cameraBaseZ * this.cameraZoom));
            this.camera.position.lerp(camTarget, 0.1);
            this.camera.lookAt(this.player.mesh.position.x, 1, this.player.mesh.position.z);
            // Echo micro-shake: subtle camera tremor during high tension
            if (typeof EchoEngine !== 'undefined') {
                var ef = EchoEngine.getCurrentFrame();
                if (ef && ef.echoes && ef.echoes.L3 && ef.echoes.L3.tension > 0.4) {
                    var shakeAmt = (ef.echoes.L3.tension - 0.4) * 0.15;
                    this.camera.position.x += (Math.random() - 0.5) * shakeAmt;
                    this.camera.position.y += (Math.random() - 0.5) * shakeAmt * 0.5;
                }
            }
        }

        // Ground ring pulse — echo-reactive: faster + brighter with tension
        if (this.player.ring) {
            var ringSpeed = 3, ringBase = 0.2, ringAmp = 0.1;
            if (typeof EchoEngine !== 'undefined') {
                var ef = EchoEngine.getCurrentFrame();
                if (ef && ef.echoes && ef.echoes.L3) {
                    ringSpeed = 3 + ef.echoes.L3.tension * 4;
                    ringBase = 0.2 + ef.echoes.L3.vitality * 0.1;
                    ringAmp = 0.1 + ef.echoes.L3.tension * 0.1;
                    // Color shift: cyan when calm, red-shift when tense
                    if (ef.echoes.L3.tension > 0.5 && !this.player.ring._echoTinted) {
                        this.player.ring.material.color.setHex(0xff4444);
                        this.player.ring._echoTinted = true;
                    } else if (ef.echoes.L3.tension <= 0.5 && this.player.ring._echoTinted) {
                        this.player.ring.material.color.setHex(0x00ffff);
                        this.player.ring._echoTinted = false;
                    }
                }
            }
            this.player.ring.material.opacity = ringBase + Math.sin(time * ringSpeed) * ringAmp;
        }

        // Touch controls
        if (typeof TouchControls !== 'undefined') TouchControls.update(delta);

        // RappterVM tick — Lispy behaviors between frames
        if (typeof RappterVM !== 'undefined' && RappterVM._running) RappterVM.tick();

        // Sub-system updates
        WorldTerrain.update(time, delta);
        WorldLanes.updateTowerVisuals(time);
        WorldCombat.update(delta, time, this.player.mesh.position);
        if (typeof VFX !== 'undefined') VFX.update(delta);
        if (typeof ReplaySystem !== 'undefined') ReplaySystem.update(delta, time);
        if (typeof Audio !== 'undefined' && Audio.updateEchoAudio) Audio.updateEchoAudio(delta);
        if (typeof EchoEvents !== 'undefined') EchoEvents.update(delta);
        if (typeof JungleCamps !== "undefined") JungleCamps.update(delta, this.player.mesh.position);
        WorldAgents.updateAnimations(time);
        WorldAgents.checkInteractions(this.player.mesh.position);
        if (WorldAgents.updateEdges) WorldAgents.updateEdges(this.scene, time);
        if (typeof FogOfWar !== 'undefined') FogOfWar.update(this.player.mesh.position);
        if (WorldAgents.updateSpeechBubbles) WorldAgents.updateSpeechBubbles(delta);
        if (WorldAgents.updatePokeReactions) WorldAgents.updatePokeReactions(time, delta);
        if (WorldAgents.checkNewChats) WorldAgents.checkNewChats();

        // Update in-world chat screens every 5 seconds
        if (!this._lastScreenUpdate || time - this._lastScreenUpdate > 5) {
            this._lastScreenUpdate = time;
            if (WorldAgents.updateScreens) WorldAgents.updateScreens();
        }

        // Update HUD chat feed
        if (typeof HUD !== 'undefined' && HUD.updateChatFeed) HUD.updateChatFeed();

        // Debug overlay (only runs when active)
        if (typeof DebugOverlay !== 'undefined') DebugOverlay.update(this.player.mesh.position);

        // RPG system updates
        if (typeof PlayerStats !== 'undefined') {
            PlayerStats.update(delta);
            if (PlayerStats.dead) return; // Skip everything while dead
        }
        if (typeof Abilities !== 'undefined') Abilities.update(delta);
        if (typeof ComboSystem !== 'undefined') ComboSystem.update(delta);
        if (typeof Inventory !== 'undefined') {
            Inventory.collectNearby(this.player.mesh.position);
            Inventory.updateDrops(time);
        }

        // Skip ALL combat during warmup — no hero, no creep damage, no enemy anything
        if (!WorldCombat._warmupActive) {
            // Enemy hero update
            if (typeof EnemyHero !== 'undefined') {
                EnemyHero.update(delta, time, this.player.mesh.position);
            }

            // Creep damage to player
            if (typeof PlayerStats !== 'undefined' && !PlayerStats.dead) {
                for (const creep of WorldCombat.creeps) {
                    if (!creep.alive || creep.faction !== 'horde') continue;
                    const dx = this.player.mesh.position.x - creep.mesh.position.x;
                    const dz = this.player.mesh.position.z - creep.mesh.position.z;
                    if (Math.sqrt(dx*dx + dz*dz) < 2) {
                        PlayerStats.takeDamage(creep.isBoss ? 3 * delta : 1 * delta);
                    }
                }
            }
        } else {
            // During warmup: hide enemy hero far away so it can't interact
            if (typeof EnemyHero !== 'undefined' && EnemyHero.mesh) {
                EnemyHero.mesh.position.set(9999, 0, 9999);
            }
        }

        // Periodic agent sync
        if (Math.floor(time) % 5 === 0 && Math.floor(time) !== this._lastSync) {
            this._lastSync = Math.floor(time);
            WorldAgents.syncAgents(this.scene, this.currentWorld);
        }
    },

    interact() {
        const dest = WorldAgents.interact();
        if (dest) {
            this.cleanup();
            Approach.start(dest);
        }
    },

    pokeAgent() {
        WorldAgents.poke(this.currentWorld);
    },

    render() {
        if (!this.active) return;
        if (typeof PostProcessing !== 'undefined' && PostProcessing.enabled) {
            PostProcessing.render(GameState.renderer, this.scene, this.camera);
        } else {
            GameState.renderer.render(this.scene, this.camera);
        }
    },

    cleanup() {
        this.active = false;
        window.removeEventListener('keydown', this.keyDown);
        window.removeEventListener('keyup', this.keyUp);
        if (this._onWheel) window.removeEventListener('wheel', this._onWheel);
        this.keys = {};
        this.cameraZoom = 1.0;

        if (typeof ReplaySystem !== 'undefined') ReplaySystem.cleanup();
        if (typeof VFX !== 'undefined') VFX.cleanup();
        if (typeof EchoEvents !== 'undefined') EchoEvents.cleanup();
        WorldCombat.cleanup();
        if (typeof JungleCamps !== "undefined") JungleCamps.cleanup();
        WorldLanes.cleanup();
        if (typeof Abilities !== 'undefined') Abilities.cleanup();
        if (typeof Inventory !== 'undefined') Inventory.cleanup();
        if (typeof Equipment !== 'undefined') Equipment.cleanup();
        if (typeof StatusEffects !== 'undefined') StatusEffects.cleanup();
        if (typeof EnemyHero !== 'undefined') EnemyHero.cleanup();

        document.getElementById('world-container').style.display = 'none';
        document.getElementById('combat-hud').style.display = 'none';
        const interactionPrompt = document.getElementById('interaction-prompt');
        if (interactionPrompt) interactionPrompt.classList.remove('visible');
        const statsBar = document.getElementById('player-stats-bar');
        if (statsBar) statsBar.style.display = 'none';
        const levelBadge = document.getElementById('level-badge');
        if (levelBadge) levelBadge.style.display = 'none';
        const abilityBar = document.getElementById('ability-bar');
        if (abilityBar) abilityBar.style.display = 'none';
        const comboEl = document.getElementById('combo-display');
        if (comboEl) comboEl.style.display = 'none';
        const goldBar = document.getElementById('gold-kda-bar');
        if (goldBar) goldBar.style.display = 'none';
        const timeline = document.getElementById('frame-timeline');
        if (timeline) timeline.classList.remove('visible');
        const narr = document.getElementById('timeline-narrative');
        if (narr) narr.classList.remove('visible');
        // Save echo session summary
        if (typeof EchoEngine !== 'undefined' && EchoEngine.saveSessionSummary) EchoEngine.saveSessionSummary();
        // Stop VM
        if (typeof RappterVM !== 'undefined') RappterVM._running = false;
        // Hide quest tracker
        if (typeof QuestTracker !== 'undefined') QuestTracker.hide();
        // Hide touch controls
        if (typeof TouchControls !== 'undefined') TouchControls.hide();
    },

    onResize() {
        if (!this.camera) return;
        this.camera.aspect = window.innerWidth / window.innerHeight;
        this.camera.updateProjectionMatrix();
    }
};
