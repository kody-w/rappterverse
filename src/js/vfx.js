// VFX — GPU Particle System & Visual Effects
// Pooled particles, burst emitters, persistent emitters, screen effects
// Usage: VFX.burst(pos, preset) | VFX.emit(pos, preset) | VFX.trail(mesh, preset)

const VFX = {
    scene: null,
    active: false,
    _pools: {},       // { presetName: [particle...] }
    _emitters: [],    // active emitters
    _trails: [],      // mesh trail attachments
    _screenFlashes: [],
    _poolSize: 300,

    // ── Presets ──
    presets: {
        // Kill explosion — red/orange burst
        kill: {
            count: 24, life: 0.8, speed: 12, spread: 1.0,
            size: 0.3, sizeEnd: 0.05, gravity: -4,
            color: 0xff4444, colorEnd: 0xff8800,
            emissive: 0.8, fadeOut: true
        },
        // Boss kill — massive purple/gold explosion
        bossKill: {
            count: 60, life: 1.4, speed: 18, spread: 1.0,
            size: 0.5, sizeEnd: 0.1, gravity: -2,
            color: 0xaa44ff, colorEnd: 0xffd700,
            emissive: 1.0, fadeOut: true, ring: true
        },
        // Hit spark — small white/yellow flash
        hitSpark: {
            count: 8, life: 0.3, speed: 8, spread: 0.6,
            size: 0.15, sizeEnd: 0.02, gravity: -8,
            color: 0xffffcc, colorEnd: 0xff8800,
            emissive: 1.0, fadeOut: true
        },
        // Tower shot impact
        towerImpact: {
            count: 12, life: 0.5, speed: 6, spread: 0.8,
            size: 0.2, sizeEnd: 0.05, gravity: -6,
            color: 0x00ccff, colorEnd: 0x0044ff,
            emissive: 0.6, fadeOut: true
        },
        // Ability: Slash arc
        slashArc: {
            count: 16, life: 0.4, speed: 10, spread: 0.4,
            size: 0.2, sizeEnd: 0.08, gravity: 0,
            color: 0x00ffff, colorEnd: 0x0088ff,
            emissive: 0.9, fadeOut: true, arc: true
        },
        // Ability: Nova explosion
        novaBlast: {
            count: 40, life: 0.7, speed: 20, spread: 1.0,
            size: 0.35, sizeEnd: 0.05, gravity: 0,
            color: 0xff4400, colorEnd: 0xffdd00,
            emissive: 1.0, fadeOut: true, ring: true
        },
        // Ability: Dash trail
        dashTrail: {
            count: 3, life: 0.6, speed: 0.5, spread: 0.3,
            size: 0.25, sizeEnd: 0.1, gravity: 0,
            color: 0x88ccff, colorEnd: 0x4488ff,
            emissive: 0.5, fadeOut: true
        },
        // Ability: Shield shimmer
        shieldShimmer: {
            count: 6, life: 0.8, speed: 2, spread: 0.5,
            size: 0.15, sizeEnd: 0.08, gravity: 1,
            color: 0xffd700, colorEnd: 0xffaa00,
            emissive: 0.7, fadeOut: true
        },
        // Pulse Shot trail
        pulseTrail: {
            count: 2, life: 0.4, speed: 1, spread: 0.2,
            size: 0.12, sizeEnd: 0.04, gravity: 0,
            color: 0x00ffff, colorEnd: 0x0044ff,
            emissive: 0.8, fadeOut: true
        },
        // Creep spawn poof
        spawnPoof: {
            count: 10, life: 0.5, speed: 4, spread: 0.8,
            size: 0.25, sizeEnd: 0.0, gravity: 2,
            color: 0x88ff88, colorEnd: 0x44aa44,
            emissive: 0.4, fadeOut: true
        },
        // Gold pickup sparkle
        goldPickup: {
            count: 8, life: 0.6, speed: 5, spread: 0.5,
            size: 0.1, sizeEnd: 0.02, gravity: 3,
            color: 0xffd700, colorEnd: 0xffaa00,
            emissive: 1.0, fadeOut: true
        },
        // Level up column
        levelUp: {
            count: 30, life: 1.2, speed: 8, spread: 0.3,
            size: 0.2, sizeEnd: 0.05, gravity: 6,
            color: 0xffd700, colorEnd: 0xffffff,
            emissive: 1.0, fadeOut: true, column: true
        },
        // Fire element
        fire: {
            count: 10, life: 0.5, speed: 3, spread: 0.4,
            size: 0.2, sizeEnd: 0.05, gravity: 3,
            color: 0xff4400, colorEnd: 0xffdd00,
            emissive: 0.9, fadeOut: true
        },
        // Ice element
        ice: {
            count: 10, life: 0.6, speed: 2, spread: 0.5,
            size: 0.15, sizeEnd: 0.08, gravity: -1,
            color: 0x88ccff, colorEnd: 0xffffff,
            emissive: 0.6, fadeOut: true
        },
        // Void element
        void: {
            count: 10, life: 0.7, speed: 2, spread: 0.6,
            size: 0.2, sizeEnd: 0.1, gravity: -2,
            color: 0x8800ff, colorEnd: 0x4400aa,
            emissive: 0.8, fadeOut: true
        },
        // Cosmic element
        cosmic: {
            count: 12, life: 0.5, speed: 4, spread: 0.7,
            size: 0.15, sizeEnd: 0.03, gravity: 0,
            color: 0xffd700, colorEnd: 0xffffff,
            emissive: 1.0, fadeOut: true
        },
        // Boss aura — persistent emitter
        bossAura: {
            count: 3, life: 1.0, speed: 1.5, spread: 0.8,
            size: 0.3, sizeEnd: 0.1, gravity: 2,
            color: 0xaa44ff, colorEnd: 0x6600aa,
            emissive: 0.6, fadeOut: true
        },
        // Throne damage
        throneDamage: {
            count: 15, life: 0.6, speed: 8, spread: 0.7,
            size: 0.3, sizeEnd: 0.05, gravity: -8,
            color: 0xff8800, colorEnd: 0xff0000,
            emissive: 0.7, fadeOut: true
        },
        // Echo-reactive ambient particles
        echoTension: {
            count: 2, life: 1.2, speed: 1, spread: 0.8,
            size: 0.12, sizeEnd: 0.03, gravity: 0.5,
            color: 0xff2222, colorEnd: 0xff6600,
            emissive: 0.6, fadeOut: true
        },
        echoVitality: {
            count: 1, life: 2.0, speed: 0.5, spread: 0.3,
            size: 0.08, sizeEnd: 0.02, gravity: 1.5,
            color: 0x00ff44, colorEnd: 0x88ffaa,
            emissive: 0.4, fadeOut: true
        },
        echoSocial: {
            count: 1, life: 1.5, speed: 0.8, spread: 0.5,
            size: 0.06, sizeEnd: 0.02, gravity: 0.3,
            color: 0xffdd44, colorEnd: 0xffffaa,
            emissive: 0.9, fadeOut: true
        }
    },

    init(scene) {
        this.scene = scene;
        this.active = true;
        this._pools = {};
        this._emitters = [];
        this._trails = [];
        this._screenFlashes = [];
    },

    // ── Get echo intensity multiplier (1.0 = normal, up to ~1.6 at max tension) ──
    _echoIntensityCache: 1.0,
    _echoIntensityCacheTime: 0,
    _getEchoIntensity() {
        var now = performance.now();
        if (now - this._echoIntensityCacheTime < 500) return this._echoIntensityCache;
        this._echoIntensityCacheTime = now;
        if (typeof EchoEngine === 'undefined') { this._echoIntensityCache = 1.0; return 1.0; }
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) { this._echoIntensityCache = 1.0; return 1.0; }
        // Tension + vitality boost particle intensity
        this._echoIntensityCache = 1.0 + ef.echoes.L3.tension * 0.4 + ef.echoes.L3.vitality * 0.2;
        return this._echoIntensityCache;
    },

    // ── One-shot burst at position ──
    burst(pos, presetName, opts) {
        if (!this.active || !this.scene) return;
        var p = this.presets[presetName];
        if (!p) return;
        var echoMult = this._getEchoIntensity();
        var count = Math.round(((opts && opts.count) || p.count) * echoMult);
        var baseColor = new THREE.Color((opts && opts.color) || p.color);
        var endColor = new THREE.Color(p.colorEnd || p.color);

        for (var i = 0; i < count; i++) {
            var particle = this._getParticle(presetName);

            // Velocity — spherical spread
            var vx, vy, vz;
            if (p.arc) {
                // Arc pattern (for slash)
                var angle = (i / count) * Math.PI - Math.PI / 2;
                vx = Math.cos(angle) * p.speed;
                vy = Math.sin(angle) * p.speed * 0.3;
                vz = Math.sin(angle) * p.speed;
            } else if (p.column) {
                // Column pattern (upward)
                var ca = Math.random() * Math.PI * 2;
                var cr = Math.random() * 1.5;
                vx = Math.cos(ca) * cr;
                vy = p.speed * (0.5 + Math.random() * 0.5);
                vz = Math.sin(ca) * cr;
            } else if (p.ring) {
                // Ring pattern (outward from center)
                var ra = (i / count) * Math.PI * 2;
                vx = Math.cos(ra) * p.speed * (0.8 + Math.random() * 0.4);
                vy = (Math.random() - 0.3) * p.speed * 0.3;
                vz = Math.sin(ra) * p.speed * (0.8 + Math.random() * 0.4);
            } else {
                // Spherical spread
                var theta = Math.random() * Math.PI * 2;
                var phi = Math.random() * Math.PI * p.spread;
                vx = Math.sin(phi) * Math.cos(theta) * p.speed * (0.5 + Math.random() * 0.5);
                vy = Math.cos(phi) * p.speed * (0.3 + Math.random() * 0.7);
                vz = Math.sin(phi) * Math.sin(theta) * p.speed * (0.5 + Math.random() * 0.5);
            }

            particle.mesh.position.set(
                pos.x + (Math.random() - 0.5) * 0.5,
                (pos.y || 1) + (Math.random() - 0.5) * 0.5,
                pos.z + (Math.random() - 0.5) * 0.5
            );
            particle.vx = vx;
            particle.vy = vy;
            particle.vz = vz;
            particle.life = 0;
            particle.maxLife = p.life * (0.7 + Math.random() * 0.6);
            particle.gravity = p.gravity || 0;
            particle.startSize = p.size * (0.7 + Math.random() * 0.6) * Math.sqrt(echoMult);
            particle.endSize = p.sizeEnd * Math.sqrt(echoMult);
            particle.startColor = baseColor.clone();
            particle.endColor = endColor.clone();
            particle.fadeOut = p.fadeOut;
            particle.alive = true;
            particle.mesh.visible = true;
            particle.mesh.scale.setScalar(particle.startSize);
            particle.mesh.material.opacity = 1;
            particle.mesh.material.emissiveIntensity = p.emissive;

            if (!particle.mesh.parent) this.scene.add(particle.mesh);
        }
    },

    // ── Persistent emitter (returns handle to stop) ──
    emit(pos, presetName, duration) {
        if (!this.active) return null;
        var emitter = {
            pos: pos, preset: presetName,
            interval: 0.08, timer: 0,
            life: 0, duration: duration || 999,
            alive: true
        };
        this._emitters.push(emitter);
        return emitter;
    },

    stopEmitter(emitter) {
        if (emitter) emitter.alive = false;
    },

    // ── Trail attached to a mesh ──
    trail(mesh, presetName) {
        if (!this.active) return null;
        var t = { mesh: mesh, preset: presetName, timer: 0, interval: 0.05, alive: true };
        this._trails.push(t);
        return t;
    },

    stopTrail(trail) {
        if (trail) trail.alive = false;
    },

    // ── Screen flash (CSS overlay) ──
    screenFlash(color, duration) {
        var el = document.createElement('div');
        el.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:7999;opacity:0.5;background:' + color + ';transition:opacity ' + (duration || 0.3) + 's;';
        document.body.appendChild(el);
        requestAnimationFrame(function() { el.style.opacity = '0'; });
        setTimeout(function() { if (el.parentNode) el.parentNode.removeChild(el); }, (duration || 0.3) * 1000 + 100);
    },

    // ── Echo-driven ambient atmosphere ──
    _echoTimer: 0,
    updateEchoAtmosphere(delta) {
        if (!this.active || !this.scene) return;
        if (typeof EchoEngine === 'undefined') return;
        // Respect echo effects toggle
        if (typeof Settings !== 'undefined' && Settings.get('echoEffects') === false) return;
        var ef = EchoEngine.getCurrentFrame();
        if (!ef || !ef.echoes || !ef.echoes.L3) return;
        var L3 = ef.echoes.L3;

        this._echoTimer -= delta;
        if (this._echoTimer > 0) return;
        var interval = Math.max(0.15, 1.2 - L3.particleDensity);
        this._echoTimer = interval;

        // Tension sparks near combat
        if (L3.tension > 0.3 && Math.random() < L3.tension * 0.6) {
            var playerPos = (typeof WorldMode !== 'undefined' && WorldMode.player) ? WorldMode.player.mesh.position : null;
            if (playerPos) {
                VFX.burst(
                    { x: playerPos.x + (Math.random() - 0.5) * 20, y: 1 + Math.random() * 3, z: playerPos.z + (Math.random() - 0.5) * 20 },
                    'echoTension', { count: 1 }
                );
            }
        }

        // Vitality glow — subtle green life in the terrain
        if (L3.vitality > 0.5 && Math.random() < L3.vitality * 0.2) {
            VFX.burst(
                { x: (Math.random() - 0.5) * 80, y: 0.3, z: (Math.random() - 0.5) * 80 },
                'echoVitality', { count: 1 }
            );
        }

        // Social fireflies — golden sparkle near crowds
        if (L3.socialEnergy > 0.5 && Math.random() < L3.socialEnergy * 0.3) {
            VFX.burst(
                { x: (Math.random() - 0.5) * 50, y: 1.5 + Math.random() * 2, z: (Math.random() - 0.5) * 50 },
                'echoSocial', { count: 1 }
            );
        }
    },

    // ── Update all particles ──
    update(delta) {
        if (!this.active) return;

        // Echo atmosphere ambient particles
        this.updateEchoAtmosphere(delta);

        // Update particles in all pools
        for (var key in this._pools) {
            var pool = this._pools[key];
            for (var i = 0; i < pool.length; i++) {
                var p = pool[i];
                if (!p.alive) continue;

                p.life += delta;
                var t = p.life / p.maxLife;

                if (t >= 1) {
                    p.alive = false;
                    p.mesh.visible = false;
                    continue;
                }

                // Physics
                p.mesh.position.x += p.vx * delta;
                p.mesh.position.y += p.vy * delta;
                p.mesh.position.z += p.vz * delta;
                p.vy += p.gravity * delta;

                // Drag
                p.vx *= 0.98;
                p.vz *= 0.98;

                // Size interpolation
                var size = p.startSize + (p.endSize - p.startSize) * t;
                p.mesh.scale.setScalar(Math.max(0.01, size));

                // Color interpolation
                p.mesh.material.color.lerpColors(p.startColor, p.endColor, t);
                p.mesh.material.emissive.lerpColors(p.startColor, p.endColor, t);

                // Fade out
                if (p.fadeOut) {
                    p.mesh.material.opacity = t < 0.6 ? 1 : 1 - (t - 0.6) / 0.4;
                }
            }
        }

        // Update emitters
        for (var e = this._emitters.length - 1; e >= 0; e--) {
            var em = this._emitters[e];
            if (!em.alive) { this._emitters.splice(e, 1); continue; }
            em.life += delta;
            if (em.life >= em.duration) { em.alive = false; this._emitters.splice(e, 1); continue; }
            em.timer -= delta;
            if (em.timer <= 0) {
                em.timer = em.interval;
                this.burst(em.pos, em.preset, { count: 1 });
            }
        }

        // Update trails
        for (var tr = this._trails.length - 1; tr >= 0; tr--) {
            var trail = this._trails[tr];
            if (!trail.alive || !trail.mesh || !trail.mesh.parent) {
                this._trails.splice(tr, 1); continue;
            }
            trail.timer -= delta;
            if (trail.timer <= 0) {
                trail.timer = trail.interval;
                this.burst(trail.mesh.position, trail.preset, { count: 1 });
            }
        }
    },

    // ── Particle pool ──
    _getParticle(presetName) {
        if (!this._pools[presetName]) this._pools[presetName] = [];
        var pool = this._pools[presetName];

        // Find dead particle
        for (var i = 0; i < pool.length; i++) {
            if (!pool[i].alive) return pool[i];
        }

        // Create new if under limit
        if (pool.length < this._poolSize) {
            var preset = this.presets[presetName];
            var geo = new THREE.SphereGeometry(1, 4, 4); // unit sphere, scaled by .scale
            var mat = new THREE.MeshStandardMaterial({
                color: preset.color,
                emissive: preset.color,
                emissiveIntensity: preset.emissive || 0.5,
                transparent: true,
                opacity: 1,
                roughness: 0.3,
                depthWrite: false
            });
            var mesh = new THREE.Mesh(geo, mat);
            mesh.visible = false;
            var particle = {
                mesh: mesh,
                vx: 0, vy: 0, vz: 0,
                life: 0, maxLife: 1,
                gravity: 0,
                startSize: 0.2, endSize: 0.05,
                startColor: new THREE.Color(preset.color),
                endColor: new THREE.Color(preset.colorEnd || preset.color),
                fadeOut: true,
                alive: false
            };
            pool.push(particle);
            return particle;
        }

        // Pool full — reuse oldest (kill it first)
        var oldest = pool[0];
        oldest.alive = false;
        oldest.mesh.visible = false;
        return oldest;
    },

    cleanup() {
        for (var key in this._pools) {
            var pool = this._pools[key];
            for (var i = 0; i < pool.length; i++) {
                var p = pool[i];
                if (p.mesh.parent) p.mesh.parent.remove(p.mesh);
                p.mesh.geometry.dispose();
                p.mesh.material.dispose();
            }
        }
        this._pools = {};
        this._emitters = [];
        this._trails = [];
        this.active = false;
    }
};
