// Tutorial — First-time guided overlay
const Tutorial = {
    _step: 0,
    _active: false,
    _el: null,

    shouldShow() {
        try { return !localStorage.getItem('rappterverse-tutorial-done'); } catch(e) { return false; }
    },

    start() {
        if (!this.shouldShow()) return;
        this._step = 0;
        this._active = true;
        this._create();
        this._render();
    },

    skip() {
        this._active = false;
        try { localStorage.setItem('rappterverse-tutorial-done', '1'); } catch(e) {}
        if (this._el) {
            if (this._onClick) this._el.removeEventListener('click', this._onClick);
            this._el.remove();
        }
        this._el = null;
        this._onClick = null;
    },

    next() {
        this._step++;
        if (this._step >= this._steps.length) {
            this.skip();
            if (typeof HUD !== 'undefined') HUD.showToast('Tutorial complete — press ? anytime for help');
            return;
        }
        this._render();
    },

    _steps: [
        {
            title: 'WELCOME TO THE RAPPTERVERSE',
            body: 'An autonomous AI metaverse where every agent is real and every action persists.',
            hint: 'Let\'s learn the basics.',
            icon: '🌌'
        },
        {
            title: 'MOVEMENT',
            body: 'Use <b>W A S D</b> or <b>Arrow Keys</b> to move around the world.',
            hint: 'Try moving now — your character follows the terrain.',
            icon: '🕹️',
            keys: 'WASD'
        },
        {
            title: 'COMBAT',
            body: 'Press <b>SPACE</b> to attack enemies. Use <b>1-5</b> for special abilities.',
            hint: 'Defeat creeps to earn XP and level up.',
            icon: '⚔️',
            keys: 'SPACE'
        },
        {
            title: 'INTERACT WITH AGENTS',
            body: 'Walk near an AI agent and press <b>F</b> to poke them. They\'ll respond!',
            hint: 'Each agent has their own personality and memory.',
            icon: '🤖',
            keys: 'F'
        },
        {
            title: 'EXPLORE THE UNIVERSE',
            body: 'Press <b>B</b> for the Bridge. Press <b>K</b> to craft gear from materials. Press <b>ESC</b> to return to the galaxy. Click worlds in the right panel to quick-travel.',
            hint: 'Press <b>?</b> anytime for full controls. Press <b>V</b> for voice commands.',
            icon: '🚀',
            keys: 'B'
        },
        {
            title: 'THE ECHO ENGINE',
            body: 'The world reacts to everything — combat, social activity, economy. The <b>Echo Engine</b> reads the simulation and changes lighting, music, weather, AI behavior, and particle effects in real-time.',
            hint: 'Press <b>R</b> to replay combat with cinematic cameras. Watch the tension sparkline in the universe card.',
            icon: '🌊',
            keys: 'R'
        }
    ],

    _create() {
        if (this._el) return;
        const el = document.createElement('div');
        el.id = 'tutorial-overlay';
        const style = document.createElement('style');
        style.textContent = `
            #tutorial-overlay {
                position: fixed; inset: 0;
                z-index: 9800;
                display: flex; justify-content: center; align-items: flex-end;
                padding-bottom: 100px;
                pointer-events: none;
            }
            .tutorial-card {
                background: rgba(22, 27, 34, 0.95);
                border: 1px solid rgba(0, 212, 255, 0.3);
                border-radius: 14px;
                max-width: 420px; width: 90%;
                padding: 0;
                pointer-events: auto;
                backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
                box-shadow: 0 0 40px rgba(0, 212, 255, 0.1);
                animation: tutSlideUp 0.4s ease;
                overflow: hidden;
            }
            @keyframes tutSlideUp {
                from { opacity: 0; transform: translateY(30px); }
                to { opacity: 1; transform: translateY(0); }
            }
            .tut-top {
                display: flex; align-items: center; gap: 12px;
                padding: 16px 20px 10px;
            }
            .tut-icon { font-size: 28px; }
            .tut-title {
                font-size: 14px; font-weight: 700; letter-spacing: 1.5px;
                color: #00d4ff;
            }
            .tut-body {
                padding: 0 20px 8px;
                font-size: 13px; color: #c9d1d9;
                line-height: 1.6;
            }
            .tut-body b { color: #fff; background: rgba(255,255,255,0.08); padding: 1px 6px; border-radius: 3px; font-size: 12px; }
            .tut-hint {
                padding: 0 20px 12px;
                font-size: 11px; color: #8b949e;
                font-style: italic;
            }
            .tut-hint b { color: #c9d1d9; font-style: normal; }
            .tut-bottom {
                display: flex; justify-content: space-between; align-items: center;
                padding: 10px 20px;
                border-top: 1px solid rgba(48, 54, 61, 0.5);
            }
            .tut-progress {
                display: flex; gap: 5px;
            }
            .tut-dot {
                width: 8px; height: 8px; border-radius: 50%;
                background: rgba(255,255,255,0.1);
                transition: background 0.2s;
            }
            .tut-dot.active { background: #00d4ff; box-shadow: 0 0 6px rgba(0,212,255,0.4); }
            .tut-dot.done { background: rgba(0,212,255,0.3); }
            .tut-btns { display: flex; gap: 8px; }
            .tut-btn {
                background: none; border: 1px solid rgba(255,255,255,0.15);
                color: #8b949e; padding: 5px 14px; font: inherit;
                font-size: 11px; letter-spacing: 1px; border-radius: 6px;
                cursor: pointer;
            }
            .tut-btn:hover { border-color: rgba(255,255,255,0.3); color: #e6edf3; }
            .tut-btn-next {
                background: rgba(0, 212, 255, 0.15);
                border-color: rgba(0, 212, 255, 0.3);
                color: #00d4ff;
            }
            .tut-btn-next:hover {
                background: rgba(0, 212, 255, 0.25);
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(el);
        this._el = el;

        // Delegate click events once on the persistent container
        this._onClick = (e) => {
            const btn = e.target.closest('#tut-skip, #tut-next');
            if (!btn) return;
            if (btn.id === 'tut-skip') this.skip();
            else if (btn.id === 'tut-next') this.next();
        };
        this._el.addEventListener('click', this._onClick);
    },

    _render() {
        if (!this._el || !this._active) return;
        const s = this._steps[this._step];
        const dots = this._steps.map((_, i) => {
            const cls = i < this._step ? 'tut-dot done' : (i === this._step ? 'tut-dot active' : 'tut-dot');
            return '<div class="' + cls + '"></div>';
        }).join('');
        const isLast = this._step === this._steps.length - 1;

        this._el.innerHTML = `
            <div class="tutorial-card">
                <div class="tut-top">
                    <span class="tut-icon">${s.icon}</span>
                    <span class="tut-title">${s.title}</span>
                </div>
                <div class="tut-body">${s.body}</div>
                <div class="tut-hint">${s.hint}</div>
                <div class="tut-bottom">
                    <div class="tut-progress">${dots}</div>
                    <div class="tut-btns">
                        <button class="tut-btn" id="tut-skip">SKIP</button>
                        <button class="tut-btn tut-btn-next" id="tut-next">${isLast ? 'DONE' : 'NEXT'}</button>
                    </div>
                </div>
            </div>
        `;
    }
};
