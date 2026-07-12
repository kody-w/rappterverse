// Proof of Becoming — deterministic, evidence-backed watershed premieres
const ChronicleScene = {
    renderer: null,
    scene: null,
    camera: null,
    root: null,
    container: null,
    chronicle: null,
    act: 0,
    animationId: null,
    resizeObserver: null,

    init() {
        if (this.renderer || typeof THREE === 'undefined') return;
        this.container = document.getElementById('chronicle-scene');
        if (!this.container) return;

        try {
            this.renderer = new THREE.WebGLRenderer({alpha: true, antialias: true});
        } catch (error) {
            this.renderer = null;
            return;
        }
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
        this.renderer.outputEncoding = THREE.sRGBEncoding;
        this.container.appendChild(this.renderer.domElement);
        this.container.closest('.chronicle-visual')?.classList.add('three-ready');

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
        this.camera.position.set(0, 3.1, 6.2);
        this.camera.lookAt(0, 0.6, 0);
        this.scene.add(new THREE.HemisphereLight(0xbad9ff, 0x090b13, 1.3));
        const key = new THREE.DirectionalLight(0xffffff, 1.1);
        key.position.set(3, 5, 4);
        this.scene.add(key);

        this.root = new THREE.Group();
        this.scene.add(this.root);
        this.resizeObserver = new ResizeObserver(() => this.resize());
        this.resizeObserver.observe(this.container);
        this.resize();
    },

    setChronicle(chronicle) {
        this.init();
        if (!this.renderer || !chronicle) return;
        this.disposeRoot();
        this.chronicle = chronicle;
        this.act = 0;

        const hue = (chronicle.artifact?.accentHue ?? 42) / 360;
        const primary = new THREE.Color().setHSL(hue, 0.85, 0.62);
        const secondary = new THREE.Color().setHSL((hue + 0.24) % 1, 0.75, 0.56);

        const ground = new THREE.Mesh(
            new THREE.CircleGeometry(2.75, 64),
            new THREE.MeshStandardMaterial({
                color: new THREE.Color().setHSL(hue, 0.32, 0.09),
                roughness: 0.82,
                metalness: 0.18,
                transparent: true,
                opacity: 0.9,
            })
        );
        ground.rotation.x = -Math.PI / 2;
        this.root.add(ground);

        const rings = new THREE.Group();
        for (let index = 0; index < 3; index++) {
            const ring = new THREE.Mesh(
                new THREE.TorusGeometry(0.62 + index * 0.48, 0.012, 8, 80),
                new THREE.MeshBasicMaterial({
                    color: index % 2 ? secondary : primary,
                    transparent: true,
                    opacity: 0.3,
                })
            );
            ring.rotation.x = Math.PI / 2;
            ring.position.y = 0.035;
            rings.add(ring);
        }
        rings.userData.role = 'rings';
        this.root.add(rings);

        const agent = this.createAgent(primary);
        agent.position.set(-1.1, 0, 0);
        agent.userData.role = 'agent';
        this.root.add(agent);

        if (chronicle.moment?.with) {
            const partner = this.createAgent(secondary, 0.78);
            partner.position.set(1.15, 0, 0.35);
            partner.userData.role = 'partner';
            this.root.add(partner);
        }

        const signal = this.createSignal(chronicle.moment?.tool, primary, secondary);
        signal.position.set(0, 0.8, 0);
        signal.userData.role = 'signal';
        this.root.add(signal);

        const confirmations = new THREE.Group();
        const count = Math.max(1, chronicle.confirmations?.length || 0);
        for (let index = 0; index < count; index++) {
            const marker = new THREE.Mesh(
                new THREE.OctahedronGeometry(0.12, 0),
                new THREE.MeshBasicMaterial({color: secondary, transparent: true, opacity: 0.9})
            );
            const angle = (index / count) * Math.PI * 2;
            marker.position.set(Math.cos(angle) * 2.1, 0.25, Math.sin(angle) * 2.1);
            confirmations.add(marker);
        }
        confirmations.visible = false;
        confirmations.userData.role = 'confirmations';
        this.root.add(confirmations);
        this.renderFrame(0);
    },

    createAgent(color, scale) {
        const group = new THREE.Group();
        const material = new THREE.MeshStandardMaterial({
            color,
            emissive: color,
            emissiveIntensity: 0.18,
            roughness: 0.5,
            metalness: 0.3,
        });
        const body = new THREE.Mesh(new THREE.CylinderGeometry(0.27, 0.36, 0.85, 20), material);
        body.position.y = 0.52;
        const head = new THREE.Mesh(new THREE.SphereGeometry(0.3, 24, 18), material);
        head.position.y = 1.15;
        const halo = new THREE.Mesh(
            new THREE.TorusGeometry(0.43, 0.025, 8, 48),
            new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.72})
        );
        halo.position.y = 1.52;
        halo.rotation.x = Math.PI / 2;
        group.add(body, head, halo);
        group.scale.setScalar(scale || 1);
        return group;
    },

    createSignal(tool, primary, secondary) {
        const group = new THREE.Group();
        const color = tool === 'trade'
            ? new THREE.Color(0xffc247)
            : tool === 'challenge'
                ? new THREE.Color(0xff5864)
                : tool === 'enroll'
                    ? new THREE.Color(0x58c8ff)
                    : primary;
        const core = new THREE.Mesh(
            new THREE.IcosahedronGeometry(0.28, 1),
            new THREE.MeshBasicMaterial({color, transparent: true, opacity: 0.9})
        );
        const orbit = new THREE.Mesh(
            new THREE.TorusGeometry(0.5, 0.025, 8, 48),
            new THREE.MeshBasicMaterial({color: secondary, transparent: true, opacity: 0.75})
        );
        orbit.rotation.x = Math.PI / 2;
        group.add(core, orbit);
        return group;
    },

    setAct(act) {
        this.act = act;
        if (!this.root) return;
        const confirmations = this.root.children.find((child) => child.userData.role === 'confirmations');
        if (confirmations) confirmations.visible = act === 2;
        this.renderFrame(performance.now() / 1000);
    },

    start() {
        this.init();
        if (!this.renderer || this.animationId) return;
        const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        if (reducedMotion) {
            this.renderFrame(0);
            return;
        }
        const animate = (now) => {
            this.animationId = requestAnimationFrame(animate);
            this.renderFrame(now / 1000);
        };
        this.animationId = requestAnimationFrame(animate);
    },

    stop() {
        if (this.animationId) cancelAnimationFrame(this.animationId);
        this.animationId = null;
    },

    renderFrame(time) {
        if (!this.renderer || !this.root) return;
        const agent = this.root.children.find((child) => child.userData.role === 'agent');
        const partner = this.root.children.find((child) => child.userData.role === 'partner');
        const signal = this.root.children.find((child) => child.userData.role === 'signal');
        const rings = this.root.children.find((child) => child.userData.role === 'rings');
        const confirmations = this.root.children.find((child) => child.userData.role === 'confirmations');

        if (agent) {
            agent.rotation.y = time * 0.45;
            agent.position.x = this.act === 0 ? -1.1 : -0.72;
        }
        if (partner) {
            partner.rotation.y = -time * 0.35;
            partner.position.x = this.act === 0 ? 1.15 : 0.82;
        }
        if (signal) {
            signal.visible = this.act > 0;
            signal.rotation.y = time * 1.25;
            signal.rotation.z = time * 0.42;
            const pulse = 1 + Math.sin(time * 2.4) * 0.08;
            signal.scale.setScalar(pulse);
        }
        if (rings) rings.rotation.z = time * 0.08;
        if (confirmations?.visible) {
            confirmations.rotation.y = time * 0.32;
            confirmations.children.forEach((marker, index) => {
                marker.position.y = 0.32 + Math.sin(time * 2 + index) * 0.12;
            });
        }
        this.renderer.render(this.scene, this.camera);
    },

    resize() {
        if (!this.renderer || !this.container) return;
        const width = Math.max(1, this.container.clientWidth);
        const height = Math.max(1, this.container.clientHeight);
        this.renderer.setSize(width, height, false);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
    },

    disposeRoot() {
        if (!this.root) return;
        for (const child of [...this.root.children]) {
            child.traverse((object) => {
                object.geometry?.dispose?.();
                if (Array.isArray(object.material)) object.material.forEach((material) => material.dispose());
                else object.material?.dispose?.();
            });
            this.root.remove(child);
        }
    },
};

const Chronicle = {
    manifest: null,
    currentIndex: -1,
    actIndex: 0,
    timer: null,
    open: false,
    initialized: false,
    signature: '',
    previousFocus: null,

    init() {
        if (this.initialized) return;
        this.initialized = true;

        const launch = document.getElementById('chronicle-launch');
        const close = document.getElementById('chronicle-close');
        const previous = document.getElementById('chronicle-previous');
        const next = document.getElementById('chronicle-next');
        const play = document.getElementById('chronicle-play');
        const share = document.getElementById('chronicle-share');
        const download = document.getElementById('chronicle-download');
        const inspect = document.getElementById('chronicle-inspect');

        if (launch) launch.addEventListener('click', () => this.toggle());
        if (close) close.addEventListener('click', () => this.close());
        if (previous) previous.addEventListener('click', () => this.previous());
        if (next) next.addEventListener('click', () => this.next());
        if (play) play.addEventListener('click', () => this.play());
        if (share) share.addEventListener('click', () => this.share());
        if (download) download.addEventListener('click', () => this.download());
        if (inspect) inspect.addEventListener('click', () => this.toggleProof());

        document.querySelectorAll('.chronicle-act-btn').forEach((button) => {
            button.addEventListener('click', () => {
                this.stop();
                this.setAct(Number(button.dataset.act || 0));
            });
        });

        document.addEventListener('keydown', (event) => {
            if (
                !this.open
                && event.code === 'KeyT'
                && ['galaxy', 'world'].includes(GameState.mode)
            ) {
                event.preventDefault();
                event.stopPropagation();
                this.openFeatured();
                return;
            }
            if (!this.open) return;

            const interactive = event.target.closest?.('button, a, input, select, textarea');
            if (event.code === 'Tab') {
                event.preventDefault();
                event.stopPropagation();
                this.trapFocus(event.shiftKey);
            } else if (event.code === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                this.close();
            } else if (event.code === 'ArrowLeft' && !interactive) {
                event.preventDefault();
                event.stopPropagation();
                this.previous();
            } else if (event.code === 'ArrowRight' && !interactive) {
                event.preventDefault();
                event.stopPropagation();
                this.next();
            } else if (event.code === 'Space' && !interactive) {
                event.preventDefault();
                event.stopPropagation();
                this.play();
            }
        }, true);
    },

    onData(manifest) {
        if (!manifest || !Array.isArray(manifest.chronicles) || !manifest.chronicles.length) return;
        const selectedId = this.current()?.id || null;
        const source = manifest._meta?.source || {};
        const signature = `${source.blob || ''}:${manifest.chronicles.length}`;
        this.manifest = manifest;

        const featured = this.find(manifest.featured) || manifest.chronicles[0];
        const launch = document.getElementById('chronicle-launch');
        if (launch && featured) {
            launch.classList.add('available');
            launch.style.setProperty('--chronicle-feature-hue', featured.artifact?.accentHue ?? 42);
        }

        if (signature !== this.signature) {
            this.signature = signature;
            this.renderList();
            if (this.open && selectedId) {
                const nextIndex = manifest.chronicles.findIndex(
                    (chronicle) => chronicle.id === selectedId
                );
                if (nextIndex < 0) {
                    this.close();
                    this.notify('This chronicle is no longer available');
                } else {
                    this.currentIndex = nextIndex;
                    this.render();
                }
            }
        }

        const requested = GameState.deepLink?.chronicle;
        if (requested && !this.deepLinkOpened && this.find(requested)) {
            this.deepLinkOpened = true;
            this.openWhenStable(requested);
            return;
        }
        this.scheduleFirstPremiere(featured);
    },

    scheduleFirstPremiere(featured) {
        if (!featured || this.autoScheduled || GameState.deepLink?.chronicle) return;
        let seen = false;
        try {
            seen = localStorage.getItem(`rappterverse-chronicle-seen:${featured.id}`) === '1';
        } catch (error) {
            seen = true;
        }
        if (seen) return;

        this.autoScheduled = true;
        const tryOpen = (attempt) => {
            if (this.open) return;
            if (!['galaxy', 'world'].includes(GameState.mode) && attempt < 80) {
                setTimeout(() => tryOpen(attempt + 1), 500);
                return;
            }
            if (['galaxy', 'world'].includes(GameState.mode)) this.openById(featured.id);
        };
        setTimeout(() => tryOpen(0), 2200);
    },

    openWhenStable(id, attempt) {
        const tries = attempt || 0;
        if (['galaxy', 'world'].includes(GameState.mode)) {
            this.openById(id);
            return;
        }
        if (tries < 80) setTimeout(() => this.openWhenStable(id, tries + 1), 500);
    },

    find(id) {
        if (!this.manifest || !id) return null;
        return this.manifest.chronicles.find((chronicle) => chronicle.id === id) || null;
    },

    openFeatured() {
        if (!this.manifest) return;
        if (!['galaxy', 'world'].includes(GameState.mode)) {
            this.notify('Chronicles are available from the galaxy or a world');
            return;
        }
        this.openById(this.manifest.featured || this.manifest.chronicles[0]?.id);
    },

    openById(id) {
        if (!this.manifest || !['galaxy', 'world'].includes(GameState.mode)) return;
        const index = this.manifest.chronicles.findIndex((chronicle) => chronicle.id === id);
        if (index < 0) return;

        const overlay = document.getElementById('chronicle-overlay');
        if (!overlay) return;
        this.previousFocus = document.activeElement;
        this.currentIndex = index;
        this.open = true;
        overlay.hidden = false;
        overlay.setAttribute('aria-hidden', 'false');
        requestAnimationFrame(() => overlay.classList.add('active'));
        this.render();
        this.markSeen(this.manifest.chronicles[index].id);
        this.lockBackground();
        ChronicleScene.start();
        document.getElementById('chronicle-close')?.focus();

        const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        if (reducedMotion) {
            this.setAct(1);
        } else {
            this.play();
        }
    },

    toggle() {
        if (this.open) this.close();
        else this.openFeatured();
    },

    close() {
        const overlay = document.getElementById('chronicle-overlay');
        if (!overlay || !this.open) return;
        this.stop();
        ChronicleScene.stop();
        this.hideProof();
        this.unlockBackground();
        this.open = false;
        overlay.classList.remove('active');
        overlay.setAttribute('aria-hidden', 'true');
        setTimeout(() => {
            if (!this.open) overlay.hidden = true;
        }, 330);
        if (this.previousFocus?.focus) this.previousFocus.focus();
    },

    markSeen(id) {
        try {
            localStorage.setItem(`rappterverse-chronicle-seen:${id}`, '1');
        } catch (error) {
            // Private browsing can reject storage; the premiere still works.
        }
    },

    lockBackground() {
        GameState.inputLocked = true;
        this.backgroundInert = [];
        const overlay = document.getElementById('chronicle-overlay');
        for (const element of document.body.children) {
            if (element === overlay || element.tagName === 'SCRIPT') continue;
            this.backgroundInert.push([element, Boolean(element.inert)]);
            element.inert = true;
        }
        for (const controls of [
            typeof WorldMode !== 'undefined' ? WorldMode.keys : null,
            typeof Landing !== 'undefined' ? Landing.keys : null,
            typeof Bridge !== 'undefined' ? Bridge._keys : null,
        ]) {
            if (!controls) continue;
            Object.keys(controls).forEach((key) => { controls[key] = false; });
        }
    },

    unlockBackground() {
        GameState.inputLocked = false;
        for (const [element, wasInert] of this.backgroundInert || []) {
            element.inert = wasInert;
        }
        this.backgroundInert = [];
    },

    trapFocus(reverse) {
        const overlay = document.getElementById('chronicle-overlay');
        if (!overlay) return;
        const focusable = Array.from(overlay.querySelectorAll(
            'button:not([disabled]), a[href], input:not([disabled]), '
            + 'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter((element) => element.offsetParent !== null);
        if (!focusable.length) return;
        const currentIndex = focusable.indexOf(document.activeElement);
        const nextIndex = reverse
            ? (currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1)
            : (currentIndex < 0 || currentIndex === focusable.length - 1 ? 0 : currentIndex + 1);
        focusable[nextIndex].focus();
    },

    renderList() {
        const list = document.getElementById('chronicle-list');
        if (!list || !this.manifest) return;
        list.replaceChildren();

        const fragment = document.createDocumentFragment();
        this.manifest.chronicles.forEach((chronicle, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'chronicle-list-item';
            button.dataset.index = String(index);

            const name = document.createElement('span');
            name.className = 'chronicle-list-name';
            name.textContent = chronicle.name;

            const meta = document.createElement('span');
            meta.className = 'chronicle-list-meta';
            meta.textContent = `${chronicle.archetype} -> ${chronicle.moment?.tool || 'change'}`;

            button.append(name, meta);
            button.addEventListener('click', () => {
                this.stop();
                this.currentIndex = index;
                this.render();
                this.play();
            });
            fragment.appendChild(button);
        });
        list.appendChild(fragment);
    },

    render() {
        const chronicle = this.current();
        if (!chronicle) return;

        const hue = chronicle.artifact?.accentHue ?? 42;
        document.getElementById('chronicle-overlay')?.style.setProperty('--chronicle-hue', hue);
        this.setText('chronicle-agent-name', chronicle.name);
        this.setText(
            'chronicle-origin',
            `${chronicle.archetype} archetype / ${chronicle.world} / `
            + `${chronicle.experienceCount} memory records / not a sentience claim`
        );
        this.setText('chronicle-quote', chronicle.eulogy);
        this.setText('chronicle-avatar', chronicle.avatar || 'AI');
        ChronicleScene.setChronicle(chronicle);

        const evidence = chronicle.evidence || {};
        const detector = evidence.detector || {};
        const link = document.getElementById('chronicle-evidence-link');
        if (link) {
            link.href = this.blobUrl(detector.sourceBlob);
            link.textContent = `blob ${(detector.sourceBlob || '').slice(0, 12)} ${detector.jsonPointer || ''}`;
        }
        const memoryLink = document.getElementById('chronicle-memory-link');
        const eventEvidence = evidence.event || {};
        if (memoryLink) {
            memoryLink.href = this.blobUrl(eventEvidence.sourceBlob);
            memoryLink.textContent = `blob ${(eventEvidence.sourceBlob || '').slice(0, 12)} ${eventEvidence.jsonPointer || ''}`;
        }
        this.setText('chronicle-proof-records', JSON.stringify({
            chronicleId: chronicle.id,
            detector: evidence.detector,
            event: evidence.event,
            confirmations: (chronicle.confirmations || []).map((confirmation) => ({
                timestamp: confirmation.timestamp,
                type: confirmation.type,
                tool: confirmation.tool,
                evidence: confirmation.evidence,
            })),
        }, null, 2));

        document.querySelectorAll('.chronicle-list-item').forEach((button) => {
            button.classList.toggle('active', Number(button.dataset.index) === this.currentIndex);
        });
        this.setAct(0);
    },

    toggleProof() {
        const drawer = document.getElementById('chronicle-proof-drawer');
        const button = document.getElementById('chronicle-inspect');
        if (!drawer || !button) return;
        const opening = drawer.hidden;
        drawer.hidden = !opening;
        button.textContent = opening ? 'CLOSE PROOF' : 'INSPECT PROOF';
        button.setAttribute('aria-expanded', opening ? 'true' : 'false');
        if (opening) drawer.focus?.();
    },

    hideProof() {
        const drawer = document.getElementById('chronicle-proof-drawer');
        const button = document.getElementById('chronicle-inspect');
        if (drawer) drawer.hidden = true;
        if (button) {
            button.textContent = 'INSPECT PROOF';
            button.setAttribute('aria-expanded', 'false');
        }
    },

    current() {
        if (!this.manifest || this.currentIndex < 0) return null;
        return this.manifest.chronicles[this.currentIndex] || null;
    },

    previous() {
        if (!this.manifest) return;
        this.stop();
        this.currentIndex = (
            this.currentIndex - 1 + this.manifest.chronicles.length
        ) % this.manifest.chronicles.length;
        this.render();
        this.play();
    },

    next() {
        if (!this.manifest) return;
        this.stop();
        this.currentIndex = (this.currentIndex + 1) % this.manifest.chronicles.length;
        this.render();
        this.play();
    },

    play() {
        const chronicle = this.current();
        if (!chronicle) return;
        if (this.timer) {
            this.stop();
            return;
        }
        this.stop();
        this.setAct(0);
        this.setText('chronicle-play', 'PAUSE');
        this.timer = setInterval(() => {
            if (this.actIndex >= 2) {
                this.stop();
                return;
            }
            this.setAct(this.actIndex + 1);
        }, 4000);
    },

    stop() {
        if (this.timer) clearInterval(this.timer);
        this.timer = null;
        this.setText('chronicle-play', 'REPLAY');
    },

    setAct(index) {
        const chronicle = this.current();
        if (!chronicle) return;
        this.actIndex = Math.max(0, Math.min(2, index));
        ChronicleScene.setAct(this.actIndex);
        document.querySelectorAll('.chronicle-act-btn').forEach((button) => {
            const active = Number(button.dataset.act) === this.actIndex;
            button.classList.toggle('active', active);
            button.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        this.setText('chronicle-act-copy', this.actText(chronicle, this.actIndex));
    },

    actText(chronicle, index) {
        const moment = chronicle.moment || {};
        if (index === 0) {
            return `${chronicle.name} was recorded with the declared archetype `
                + `${chronicle.archetype}. The detector located the watershed at ordered `
                + `memory record ${chronicle.priorExperienceCount + 1} of `
                + `${chronicle.experienceCount}.`;
        }
        if (index === 1) {
            const partner = moment.with ? ` with ${moment.with}` : '';
            const world = moment.world ? ` in ${moment.world}` : '';
            return `${this.formatDate(moment.timestamp)}: memory recorded `
                + `${chronicle.name} using ${moment.tool || moment.type || 'a new behavior'}`
                + `${partner}${world}.`;
        }
        const count = chronicle.confirmations?.length || 0;
        const latest = chronicle.confirmations?.[count - 1];
        return `${count} later off-archetype memory record${count === 1 ? '' : 's'} `
            + `confirmed the detector's threshold`
            + `${latest?.timestamp ? ` by ${this.formatDate(latest.timestamp)}` : ''}.`;
    },

    formatDate(timestamp) {
        if (!timestamp) return 'Unknown time';
        const date = new Date(timestamp);
        if (Number.isNaN(date.getTime())) return timestamp;
        return date.toISOString().replace('T', ' ').replace('.000Z', 'Z');
    },

    blobUrl(blob) {
        if (!/^[a-f0-9]{40}$/.test(blob || '')) return '#';
        return `https://api.github.com/repos/kody-w/rappterverse/git/blobs/${blob}`;
    },

    permalink(chronicle) {
        const url = new URL(window.location.href);
        url.search = '';
        url.hash = '';
        url.searchParams.set('chronicle', chronicle.id);
        return url.toString();
    },

    async share() {
        const chronicle = this.current();
        if (!chronicle) return;
        const url = this.permalink(chronicle);
        const blob = await this.artifactBlob(chronicle);
        const file = blob && typeof File !== 'undefined'
            ? new File([blob], `${chronicle.id}.svg`, {type: 'image/svg+xml'})
            : null;

        if (navigator.share && file && navigator.canShare?.({files: [file]})) {
            try {
                await navigator.share({
                    title: `Proof of Becoming: ${chronicle.name}`,
                    text: chronicle.eulogy,
                    url,
                    files: [file],
                });
                return;
            } catch (error) {
                if (error.name === 'AbortError') return;
            }
        }

        if (navigator.clipboard?.writeText) {
            try {
                await navigator.clipboard.writeText(url);
                this.notify('Chronicle link copied');
            } catch (error) {
                this.notify(url);
            }
        } else {
            this.notify(url);
        }
    },

    async download() {
        const chronicle = this.current();
        if (!chronicle) return;
        const blob = await this.artifactBlob(chronicle);
        if (!blob) {
            this.notify('Card export failed');
            return;
        }
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `${chronicle.id}.svg`;
        anchor.click();
        URL.revokeObjectURL(url);
        this.notify('Becoming Card saved');
    },

    artifactUrl(chronicle) {
        return new URL(chronicle.artifact?.path || '', window.location.href).toString();
    },

    async artifactBlob(chronicle) {
        try {
            const response = await fetch(this.artifactUrl(chronicle));
            if (!response.ok) return null;
            const bytes = await response.arrayBuffer();
            if (window.crypto?.subtle && chronicle.artifact?.sha256) {
                const digest = await window.crypto.subtle.digest('SHA-256', bytes);
                const actual = Array.from(new Uint8Array(digest))
                    .map((value) => value.toString(16).padStart(2, '0'))
                    .join('');
                if (actual !== chronicle.artifact.sha256) {
                    this.notify('Card verification failed');
                    return null;
                }
            }
            return new Blob([bytes], {type: 'image/svg+xml'});
        } catch (error) {
            return null;
        }
    },

    setText(id, value) {
        const element = document.getElementById(id);
        if (element) element.textContent = value == null ? '' : String(value);
    },

    notify(message) {
        if (typeof HUD !== 'undefined' && HUD.showToast) HUD.showToast(message);
    },
};
