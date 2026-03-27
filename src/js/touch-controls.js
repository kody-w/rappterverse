// Touch Controls — Virtual joystick + tap actions for mobile
const TouchControls = {
    active: false,
    _joystickOuter: null,
    _joystickInner: null,
    _joystickOrigin: null,
    _moveVector: { x: 0, z: 0 },
    _touchId: null,
    _actionTouchId: null,
    _isMobile: false,

    init() {
        this._isMobile = /iphone|ipad|android|mobile/i.test(navigator.userAgent) ||
                          ('ontouchstart' in window && window.innerWidth < 1024);
        if (this._isMobile) this.enable();
    },

    enable() {
        if (this.active) return;
        this.active = true;
        this._createUI();
        this._bindEvents();
    },

    disable() {
        this.active = false;
        const el = document.getElementById('touch-controls');
        if (el) el.remove();
    },

    _createUI() {
        if (document.getElementById('touch-controls')) return;

        const container = document.createElement('div');
        container.id = 'touch-controls';
        container.innerHTML = `
            <div id="joystick-zone">
                <div id="joystick-outer">
                    <div id="joystick-inner"></div>
                </div>
            </div>
            <div id="touch-action-zone">
                <button id="touch-attack" class="touch-btn touch-btn-attack">ATK</button>
                <button id="touch-poke" class="touch-btn touch-btn-poke">POKE</button>
                <button id="touch-jump" class="touch-btn touch-btn-jump">MAP</button>
            </div>
        `;

        const style = document.createElement('style');
        style.textContent = `
            #touch-controls { position: fixed; inset: 0; pointer-events: none; z-index: 800; display: none; }
            #joystick-zone {
                position: absolute; bottom: 20px; left: 20px;
                width: 140px; height: 140px; pointer-events: auto;
            }
            #joystick-outer {
                width: 120px; height: 120px; border-radius: 50%;
                background: rgba(255,255,255,0.06); border: 2px solid rgba(0,212,255,0.25);
                position: relative; margin: 10px;
            }
            #joystick-inner {
                width: 44px; height: 44px; border-radius: 50%;
                background: rgba(0,212,255,0.35); border: 2px solid rgba(0,212,255,0.5);
                position: absolute; top: 50%; left: 50%;
                transform: translate(-50%, -50%);
                transition: none;
            }
            #touch-action-zone {
                position: absolute; bottom: 24px; right: 16px;
                display: flex; flex-direction: column; gap: 10px;
                pointer-events: auto;
            }
            .touch-btn {
                width: 56px; height: 56px; border-radius: 50%;
                border: 2px solid rgba(255,255,255,0.2);
                background: rgba(15,20,30,0.7);
                color: rgba(255,255,255,0.7);
                font: 700 11px/1 inherit; letter-spacing: 1px;
                backdrop-filter: blur(4px); -webkit-backdrop-filter: blur(4px);
                cursor: pointer; -webkit-tap-highlight-color: transparent;
            }
            .touch-btn:active { background: rgba(0,212,255,0.3); border-color: rgba(0,212,255,0.5); }
            .touch-btn-attack { border-color: rgba(255,68,68,0.4); color: rgba(255,100,100,0.8); }
            .touch-btn-poke { border-color: rgba(0,255,136,0.3); color: rgba(0,255,136,0.7); }
            .touch-btn-jump { border-color: rgba(255,187,0,0.3); color: rgba(255,187,0,0.7); }
        `;
        document.head.appendChild(style);
        document.body.appendChild(container);

        this._joystickOuter = document.getElementById('joystick-outer');
        this._joystickInner = document.getElementById('joystick-inner');
    },

    _bindEvents() {
        // Joystick touch
        const zone = document.getElementById('joystick-zone');
        if (!zone) return;

        zone.addEventListener('touchstart', (e) => {
            e.preventDefault();
            const t = e.changedTouches[0];
            this._touchId = t.identifier;
            const rect = this._joystickOuter.getBoundingClientRect();
            this._joystickOrigin = {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2
            };
        }, { passive: false });

        window.addEventListener('touchmove', (e) => {
            for (let i = 0; i < e.changedTouches.length; i++) {
                const t = e.changedTouches[i];
                if (t.identifier === this._touchId && this._joystickOrigin) {
                    e.preventDefault();
                    const dx = t.clientX - this._joystickOrigin.x;
                    const dy = t.clientY - this._joystickOrigin.y;
                    const maxR = 40;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    const clamped = Math.min(dist, maxR);
                    const angle = Math.atan2(dy, dx);
                    const cx = Math.cos(angle) * clamped;
                    const cy = Math.sin(angle) * clamped;

                    this._joystickInner.style.transform = `translate(calc(-50% + ${cx}px), calc(-50% + ${cy}px))`;
                    this._moveVector.x = cx / maxR;
                    this._moveVector.z = cy / maxR;
                }
            }
        }, { passive: false });

        window.addEventListener('touchend', (e) => {
            for (let i = 0; i < e.changedTouches.length; i++) {
                if (e.changedTouches[i].identifier === this._touchId) {
                    this._touchId = null;
                    this._joystickInner.style.transform = 'translate(-50%, -50%)';
                    this._moveVector.x = 0;
                    this._moveVector.z = 0;
                }
            }
        });

        // Action buttons
        document.getElementById('touch-attack').addEventListener('touchstart', (e) => {
            e.preventDefault();
            if (typeof WorldMode !== 'undefined' && WorldMode.keys) {
                WorldMode.keys['Space'] = true;
                setTimeout(() => { WorldMode.keys['Space'] = false; }, 200);
            }
        }, { passive: false });

        document.getElementById('touch-poke').addEventListener('touchstart', (e) => {
            e.preventDefault();
            if (typeof WorldMode !== 'undefined') WorldMode.pokeAgent();
        }, { passive: false });

        document.getElementById('touch-jump').addEventListener('touchstart', (e) => {
            e.preventDefault();
            if (typeof HUD !== 'undefined') HUD.toggleMinimap();
        }, { passive: false });
    },

    show() {
        const el = document.getElementById('touch-controls');
        if (el && this.active) el.style.display = 'block';
    },

    hide() {
        const el = document.getElementById('touch-controls');
        if (el) el.style.display = 'none';
    },

    update(delta) {
        if (!this.active || typeof WorldMode === 'undefined' || !WorldMode.keys) return;
        const dead = 0.15;
        const mx = this._moveVector.x;
        const mz = this._moveVector.z;

        WorldMode.keys['KeyD'] = mx > dead;
        WorldMode.keys['KeyA'] = mx < -dead;
        WorldMode.keys['KeyS'] = mz > dead;
        WorldMode.keys['KeyW'] = mz < -dead;
    }
};
