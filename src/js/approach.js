// Planet Approach — 3-Phase Cinematic Camera Sequence
// Phases: approaching → orbiting → ready
const Approach = {
    active: false,
    targetWorld: null,
    phase: null,           // 'approaching' | 'orbiting' | 'ready'
    progress: 0,           // approach lerp progress 0→1
    orbitAngle: 0,         // camera orbit angle around planet
    startPos: null,        // camera position when approach began
    startLookAt: null,     // initial lookAt target
    animFrame: null,
    orbitRadius: 20,
    orbitHeight: 8,

    easeInOutCubic(t) {
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    },

    getOrbitCameraPosition(planetPos, angle) {
        const r = this.orbitRadius;
        const h = this.orbitHeight;
        return new THREE.Vector3(
            planetPos.x + Math.cos(angle) * r,
            planetPos.y + h + Math.sin(angle * 0.5) * 3,
            planetPos.z + Math.sin(angle) * r
        );
    },

    getPlanetPosition() {
        const group = Galaxy.planets[this.targetWorld];
        return group ? group.position.clone() : new THREE.Vector3();
    },

    start(worldId) {
        this.targetWorld = worldId;
        this.active = true;
        this.phase = 'approaching';
        this.progress = 0;
        this.orbitAngle = 0;
        GameState.setMode('approach');
        GameState.currentWorld = worldId;

        const planetGroup = Galaxy.planets[worldId];
        if (!planetGroup) { this.abort(); return; }

        // Capture starting camera state
        this.startPos = Galaxy.camera.position.clone();
        this.startLookAt = new THREE.Vector3(0, 0, 0);

        // Deselect planet panel so it doesn't overlap
        Galaxy.deselectPlanet();
        const label = document.querySelector('.galaxy-label');
        if (label) label.style.display = 'none';

        // Populate overlay with planet info
        const w = WORLDS[worldId];
        document.getElementById('approach-name').textContent = w.name;
        const biomeEl = document.getElementById('approach-biome');
        biomeEl.textContent = w.biome;
        biomeEl.style.background = `rgba(${Galaxy.hexToRgb(w.planetColor)}, 0.2)`;
        biomeEl.style.color = `#${w.planetColor.toString(16).padStart(6, '0')}`;

        // Show overlay and letterbox
        document.getElementById('approach-overlay').classList.add('active');
        setTimeout(() => {
            document.getElementById('letterbox-top').classList.add('active');
            document.getElementById('letterbox-bottom').classList.add('active');
        }, 200);

        // Hide landing button until ready phase
        const landBtn = document.getElementById('approach-land-btn');
        landBtn.style.display = 'none';
        landBtn.onclick = () => this.initiateLanding();
        document.getElementById('approach-skip-btn').onclick = () => this.abort();

        this.animate();
    },

    animate() {
        if (!this.active) return;
        this.animFrame = requestAnimationFrame(() => this.animate());

        const elapsed = performance.now();
        const pPos = this.getPlanetPosition();

        // --- Keep galaxy alive: slow planet orbits, star pulse, starfield ---
        Galaxy.planetMeshes.forEach((group, idx) => {
            const wc = WORLDS[WORLD_IDS[idx]];
            group.userData.orbitAngle += wc.orbitSpeed * 0.004;
            group.position.x = Math.cos(group.userData.orbitAngle) * wc.orbitRadius;
            group.position.z = Math.sin(group.userData.orbitAngle) * wc.orbitRadius;
            group.children[0].rotation.y += 0.003;
        });

        if (Galaxy.starMesh) {
            Galaxy.starMesh.scale.setScalar(1 + Math.sin(elapsed * 0.002) * 0.05);
        }

        if (Galaxy.starField) {
            Galaxy.starField.rotation.y += 0.00005;
        }

        // --- Phase logic ---
        if (this.phase === 'approaching') {
            this.progress = Math.min(this.progress + 0.008, 1);
            const t = this.easeInOutCubic(this.progress);

            // Target is orbit position around live planet position
            const orbitTarget = this.getOrbitCameraPosition(pPos, this.orbitAngle);
            Galaxy.camera.position.lerpVectors(this.startPos, orbitTarget, t);

            // Lerp lookAt from star center to planet
            const lookAt = new THREE.Vector3().lerpVectors(this.startLookAt, pPos, t);
            Galaxy.camera.lookAt(lookAt);

            if (this.progress >= 1) {
                this.phase = 'orbiting';
            }
        } else if (this.phase === 'orbiting') {
            this.orbitAngle += 0.008;

            const orbitTarget = this.getOrbitCameraPosition(pPos, this.orbitAngle);
            Galaxy.camera.position.lerp(orbitTarget, 0.1);
            Galaxy.camera.lookAt(pPos);

            if (this.orbitAngle > Math.PI * 0.5) {
                this.phase = 'ready';
                // Show landing button with pulse
                const landBtn = document.getElementById('approach-land-btn');
                landBtn.style.display = '';
            }
        } else if (this.phase === 'ready') {
            // Slow orbit continues
            this.orbitAngle += 0.005;

            const orbitTarget = this.getOrbitCameraPosition(pPos, this.orbitAngle);
            Galaxy.camera.position.lerp(orbitTarget, 0.1);
            Galaxy.camera.lookAt(pPos);
        }

        // --- Update HUD stats ---
        const approachFactor = this.phase === 'approaching' ? this.progress : 1;
        const distance = Math.max(0, (1 - approachFactor) * 1200).toFixed(0);
        const velocity = (8 + approachFactor * 12).toFixed(1);
        const eta = Math.max(0, (1 - approachFactor) * 4.5).toFixed(1);
        document.getElementById('approach-distance').textContent = distance + ' km';
        document.getElementById('approach-velocity').textContent = velocity + ' km/s';
        document.getElementById('approach-eta').textContent = eta + 's';

        // --- Render ---
        GameState.renderer.render(Galaxy.scene, Galaxy.camera);
    },

    initiateLanding() {
        Galaxy.hide();
        this.cleanup();
        Landing.start(this.targetWorld);
    },

    abort() {
        // Restore camera angle so Galaxy.update resumes smoothly
        Galaxy.cameraAngle = Math.atan2(Galaxy.camera.position.z, Galaxy.camera.position.x);
        this.cleanup();
        GameState.setMode('galaxy');
        Galaxy.show();
    },

    cleanup() {
        this.active = false;
        if (this.animFrame) cancelAnimationFrame(this.animFrame);
        this.animFrame = null;
        this.phase = null;
        document.getElementById('approach-overlay').classList.remove('active');
        document.getElementById('letterbox-top').classList.remove('active');
        document.getElementById('letterbox-bottom').classList.remove('active');
    }
};
