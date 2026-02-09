// Planet Approach — 3D Cinematic Camera Zoom
const Approach = {
    active: false,
    targetWorld: null,
    startPos: null,
    targetPos: null,
    startLookAt: null,
    targetLookAt: null,
    progress: 0,
    duration: 4500,
    startTime: 0,
    animFrame: null,

    start(worldId) {
        this.targetWorld = worldId;
        this.active = true;
        this.progress = 0;
        this.startTime = Date.now();
        GameState.setMode('approach');
        GameState.currentWorld = worldId;

        const w = WORLDS[worldId];
        const planetGroup = Galaxy.planets[worldId];
        if (!planetGroup) { this.abort(); return; }

        // Capture camera start state
        this.startPos = Galaxy.camera.position.clone();
        this.startLookAt = new THREE.Vector3(0, 0, 0);

        // Compute target: close orbit around planet
        const pPos = planetGroup.position.clone();
        const camDir = pPos.clone().normalize();
        this.targetPos = pPos.clone().sub(camDir.multiplyScalar(12)).add(new THREE.Vector3(0, 5, 0));
        this.targetLookAt = pPos.clone();

        // Show HUD overlay (transparent — 3D renders behind it)
        const overlay = document.getElementById('approach-overlay');
        overlay.classList.add('active');
        setTimeout(() => {
            document.getElementById('letterbox-top').classList.add('active');
            document.getElementById('letterbox-bottom').classList.add('active');
        }, 200);

        // Planet info
        document.getElementById('approach-name').textContent = w.name;
        const biomeEl = document.getElementById('approach-biome');
        biomeEl.textContent = w.biome;
        biomeEl.style.background = `rgba(${Galaxy.hexToRgb(w.planetColor)}, 0.2)`;
        biomeEl.style.color = `#${w.planetColor.toString(16).padStart(6, '0')}`;

        // Deselect planet panel so it doesn't overlap
        Galaxy.deselectPlanet();
        document.querySelector('.galaxy-label').style.display = 'none';

        // Buttons
        document.getElementById('approach-land-btn').onclick = () => this.initiateLanding();
        document.getElementById('approach-skip-btn').onclick = () => this.abort();

        // Start render loop (we drive Galaxy camera + render ourselves)
        this.animate();
    },

    easeInOut(t) {
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    },

    animate() {
        if (!this.active) return;
        this.animFrame = requestAnimationFrame(() => this.animate());

        const elapsed = Date.now() - this.startTime;
        this.progress = Math.min(elapsed / this.duration, 1);
        const t = this.easeInOut(this.progress);

        // Track planet position (it orbits)
        const planetGroup = Galaxy.planets[this.targetWorld];
        if (planetGroup) {
            const pPos = planetGroup.position.clone();
            const camDir = pPos.clone().normalize();
            this.targetPos = pPos.clone().sub(camDir.multiplyScalar(12)).add(new THREE.Vector3(0, 5, 0));
            this.targetLookAt = pPos.clone();
        }

        // Lerp camera
        Galaxy.camera.position.lerpVectors(this.startPos, this.targetPos, t);
        const lookAt = new THREE.Vector3().lerpVectors(this.startLookAt, this.targetLookAt, t);
        Galaxy.camera.lookAt(lookAt);

        // Slow-orbit planets during zoom
        Galaxy.planetMeshes.forEach((group, idx) => {
            const wc = WORLDS[WORLD_IDS[idx]];
            group.userData.orbitAngle += wc.orbitSpeed * 0.004;
            group.position.x = Math.cos(group.userData.orbitAngle) * wc.orbitRadius;
            group.position.z = Math.sin(group.userData.orbitAngle) * wc.orbitRadius;
            group.children[0].rotation.y += 0.003;
        });

        // Pulse star
        if (Galaxy.starMesh) {
            Galaxy.starMesh.scale.setScalar(1 + Math.sin(elapsed * 0.002) * 0.05);
        }

        // Update HUD stats
        const distance = Math.max(0, (1 - this.progress) * 1200).toFixed(0);
        const velocity = (8 + this.progress * 12).toFixed(1);
        const eta = Math.max(0, ((1 - this.progress) * 4.5)).toFixed(1);
        document.getElementById('approach-distance').textContent = distance + ' km';
        document.getElementById('approach-velocity').textContent = velocity + ' km/s';
        document.getElementById('approach-eta').textContent = eta + 's';

        // Render galaxy scene with our animated camera
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
        document.getElementById('approach-overlay').classList.remove('active');
        document.getElementById('letterbox-top').classList.remove('active');
        document.getElementById('letterbox-bottom').classList.remove('active');
    }
};
