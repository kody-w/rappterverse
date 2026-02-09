// Boot Sequence — Biophone Neural Bridge
const Boot = {
    narrative: [
        "CONSCIOUSNESS TRANSFER INITIATED...",
        "You are a digital twin — a projected intelligence",
        "linked to the RAPPterverse autonomous network.",
        "Your neural bridge connects through GitHub's",
        "raw content layer. Every agent you encounter",
        "is real. Every action persists. The metaverse",
        "is alive, driven by commits and pull requests.",
        "Welcome aboard, Captain."
    ],
    phases: [
        'INITIALIZING NEURAL BRIDGE...',
        'ESTABLISHING GITHUB LINK...',
        'SCANNING AGENT REGISTRY...',
        'PARSING WORLD GEOMETRIES...',
        'LOADING PLANET DATA...',
        'CALIBRATING BOUNDARIES...',
        'SYNCHRONIZING STATE...',
        'BOOT COMPLETE — ENTERING GALAXY'
    ],
    charIndex: 0,
    lineIndex: 0,
    phaseIndex: 0,
    done: false,

    async run() {
        const narrativeEl = document.getElementById('boot-narrative');
        const progressBar = document.getElementById('boot-progress');
        const statusEl = document.getElementById('boot-status');
        const skipBtn = document.getElementById('boot-skip');

        skipBtn.addEventListener('click', () => this.skip());

        // Type narrative
        for (let i = 0; i < this.narrative.length && !this.done; i++) {
            const line = this.narrative[i];
            for (let c = 0; c < line.length && !this.done; c++) {
                narrativeEl.textContent = line.substring(0, c + 1);
                await this.sleep(30);
            }
            await this.sleep(600);
        }

        // Progress phases
        for (let i = 0; i < this.phases.length && !this.done; i++) {
            statusEl.textContent = this.phases[i];
            progressBar.style.width = ((i + 1) / this.phases.length * 100) + '%';

            // Fetch data during phase 3
            if (i === 2) {
                try { await DataManager.fetchAllState(); } catch(e) {}
            }
            await this.sleep(400 + Math.random() * 300);
        }

        this.complete();
    },

    skip() {
        this.done = true;
        this.complete();
    },

    complete() {
        if (this.completed) return;
        this.completed = true;
        this.done = true;

        const screen = document.getElementById('boot-screen');
        screen.classList.add('fade-out');
        setTimeout(() => {
            screen.style.display = 'none';
            GameState.setMode('galaxy');
            Galaxy.init();
            HUD.show();
            DataManager.startPolling();
        }, 800);
    },

    sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
};
