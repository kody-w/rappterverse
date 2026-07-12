// Gesture Controls — MediaPipe Hands for gesture-based interaction
const GestureControls = {
    active: false,
    _hands: null,
    _camera: null,
    _video: null,
    _canvas: null,
    _ctx: null,
    _lastGesture: '',
    _lastGestureTime: 0,
    _moveVector: { x: 0, z: 0 },
    _scriptsLoaded: false,
    _loading: false,

    // Gesture state
    gesture: 'none',       // none, point_left, point_right, point_up, point_down, fist, open, thumbs_up, peace
    confidence: 0,
    landmarks: null,

    toggle() {
        this.active = !this.active;
        if (this.active) {
            this._start();
        } else {
            this._stop();
        }
        this._updateUI();
        return this.active;
    },

    async _start() {
        if (typeof HUD !== 'undefined') HUD.showToast('Loading gesture controls...');

        // Create video + canvas if not exists
        if (!this._video) this._createElements();

        // Load MediaPipe scripts if needed
        if (!this._scriptsLoaded && !this._loading) {
            this._loading = true;
            try {
                await this._loadScripts();
                this._scriptsLoaded = true;
            } catch(e) {
                if (GameState.debug) console.warn('[GESTURE] Failed to load MediaPipe:', e);
                if (typeof HUD !== 'undefined') HUD.showToast('Failed to load gesture library');
                this.active = false;
                this._updateUI();
                this._loading = false;
                return;
            }
            this._loading = false;
        }

        // Init MediaPipe Hands
        if (!this._hands && window.Hands) {
            this._hands = new window.Hands({
                locateFile: (file) => 'https://cdn.jsdelivr.net/npm/@mediapipe/hands/' + file
            });
            this._hands.setOptions({
                maxNumHands: 1,
                modelComplexity: 0, // Lite model for performance
                minDetectionConfidence: 0.6,
                minTrackingConfidence: 0.5
            });
            this._hands.onResults((r) => this._onResults(r));
        }

        // Start camera
        if (!this._camera && window.Camera) {
            this._camera = new window.Camera(this._video, {
                onFrame: async () => {
                    if (this.active && this._hands) {
                        await this._hands.send({ image: this._video });
                    }
                },
                width: 320,
                height: 240
            });
        }

        try {
            await this._camera.start();
            var gp = document.getElementById('gesture-panel'); if (gp) gp.classList.add('visible');
            if (typeof HUD !== 'undefined') HUD.showToast('Gesture controls ON — show hand to camera');
        } catch(e) {
            if (GameState.debug) console.warn('[GESTURE] Camera access denied:', e);
            if (typeof HUD !== 'undefined') HUD.showToast('Camera access denied');
            this.active = false;
            this._updateUI();
        }
    },

    _stop() {
        if (this._camera) {
            try { this._camera.stop(); } catch(e) {}
        }
        var gp = document.getElementById('gesture-panel'); if (gp) gp.classList.remove('visible');
        this._moveVector = { x: 0, z: 0 };
        this.gesture = 'none';
        // Release keys
        if (typeof WorldMode !== 'undefined' && WorldMode.keys) {
            WorldMode.keys['KeyW'] = false;
            WorldMode.keys['KeyS'] = false;
            WorldMode.keys['KeyA'] = false;
            WorldMode.keys['KeyD'] = false;
        }
        if (typeof HUD !== 'undefined') HUD.showToast('Gesture controls OFF');
    },

    _createElements() {
        this._video = document.createElement('video');
        this._video.setAttribute('playsinline', '');
        this._video.style.display = 'none';
        document.body.appendChild(this._video);

        this._canvas = document.getElementById('gesture-canvas');
        if (this._canvas) this._ctx = this._canvas.getContext('2d');
    },

    _loadScripts() {
        return new Promise((resolve, reject) => {
            const scripts = [
                'https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js',
                'https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js'
            ];
            let loaded = 0;
            scripts.forEach(src => {
                const s = document.createElement('script');
                s.src = src;
                s.onload = () => { loaded++; if (loaded === scripts.length) resolve(); };
                s.onerror = () => reject(new Error('Failed to load ' + src));
                document.head.appendChild(s);
            });
        });
    },

    _onResults(results) {
        // Draw camera feed + landmarks
        if (this._ctx && this._canvas) {
            this._ctx.save();
            this._ctx.clearRect(0, 0, 200, 150);
            // Mirror the video
            this._ctx.scale(-1, 1);
            this._ctx.drawImage(results.image, -200, 0, 200, 150);
            this._ctx.restore();

            if (results.multiHandLandmarks && results.multiHandLandmarks.length > 0) {
                this._drawLandmarks(results.multiHandLandmarks[0]);
            }
        }

        if (!results.multiHandLandmarks || results.multiHandLandmarks.length === 0) {
            this.gesture = 'none';
            this.landmarks = null;
            this._applyGesture();
            return;
        }

        this.landmarks = results.multiHandLandmarks[0];
        this._classifyGesture();
        this._applyGesture();
    },

    _drawLandmarks(landmarks) {
        if (!this._ctx) return;
        const ctx = this._ctx;
        // Draw connections
        ctx.strokeStyle = 'rgba(0, 212, 255, 0.5)';
        ctx.lineWidth = 1;
        const connections = [
            [0,1],[1,2],[2,3],[3,4], // thumb
            [0,5],[5,6],[6,7],[7,8], // index
            [0,9],[9,10],[10,11],[11,12], // middle
            [0,13],[13,14],[14,15],[15,16], // ring
            [0,17],[17,18],[18,19],[19,20], // pinky
            [5,9],[9,13],[13,17] // palm
        ];
        connections.forEach(([a, b]) => {
            ctx.beginPath();
            ctx.moveTo((1 - landmarks[a].x) * 200, landmarks[a].y * 150);
            ctx.lineTo((1 - landmarks[b].x) * 200, landmarks[b].y * 150);
            ctx.stroke();
        });
        // Draw points
        landmarks.forEach(lm => {
            ctx.fillStyle = '#00d4ff';
            ctx.beginPath();
            ctx.arc((1 - lm.x) * 200, lm.y * 150, 2, 0, Math.PI * 2);
            ctx.fill();
        });
    },

    _classifyGesture() {
        const lm = this.landmarks;
        if (!lm) { this.gesture = 'none'; return; }

        // Key landmarks (normalized 0-1)
        const wrist = lm[0];
        const thumbTip = lm[4];
        const indexTip = lm[8];
        const indexMcp = lm[5];
        const middleTip = lm[12];
        const middleMcp = lm[9];
        const ringTip = lm[16];
        const ringMcp = lm[13];
        const pinkyTip = lm[20];
        const pinkyMcp = lm[17];

        // Finger extended checks (tip above MCP in y = extended, since y increases downward)
        const indexUp = indexTip.y < indexMcp.y - 0.04;
        const middleUp = middleTip.y < middleMcp.y - 0.04;
        const ringUp = ringTip.y < ringMcp.y - 0.04;
        const pinkyUp = pinkyTip.y < pinkyMcp.y - 0.04;
        const thumbOut = Math.abs(thumbTip.x - wrist.x) > 0.08;

        // Fist: all fingers curled
        if (!indexUp && !middleUp && !ringUp && !pinkyUp) {
            this.gesture = 'fist';
            return;
        }

        // Thumbs up: thumb extended, others curled
        if (thumbOut && thumbTip.y < wrist.y - 0.1 && !indexUp && !middleUp && !ringUp && !pinkyUp) {
            this.gesture = 'thumbs_up';
            return;
        }

        // Peace sign: index + middle up, others curled
        if (indexUp && middleUp && !ringUp && !pinkyUp) {
            this.gesture = 'peace';
            return;
        }

        // Open palm: all fingers extended
        if (indexUp && middleUp && ringUp && pinkyUp) {
            this.gesture = 'open';
            return;
        }

        // Point: only index extended — determine direction
        if (indexUp && !middleUp && !ringUp && !pinkyUp) {
            const dx = indexTip.x - wrist.x; // negative = pointing right (mirrored)
            const dy = indexTip.y - wrist.y; // negative = pointing up

            if (Math.abs(dy) > Math.abs(dx)) {
                this.gesture = dy < -0.08 ? 'point_up' : 'point_down';
            } else {
                // Mirrored: negative dx = user's right
                this.gesture = dx < -0.04 ? 'point_right' : 'point_left';
            }
            return;
        }

        this.gesture = 'none';
    },

    _applyGesture() {
        if (GameState.mode !== 'world' || typeof WorldMode === 'undefined') return;
        const keys = WorldMode.keys;
        if (!keys) return;
        if (GameState.inputLocked) {
            keys['KeyW'] = false;
            keys['KeyS'] = false;
            keys['KeyA'] = false;
            keys['KeyD'] = false;
            keys['Space'] = false;
            return;
        }

        // Update gesture label
        const labelEl = document.getElementById('gesture-label');
        if (labelEl) labelEl.textContent = this.gesture !== 'none' ? this.gesture.replace('_', ' ').toUpperCase() : '';

        // Reset movement keys
        keys['KeyW'] = false;
        keys['KeyS'] = false;
        keys['KeyA'] = false;
        keys['KeyD'] = false;

        const now = Date.now();

        switch (this.gesture) {
            case 'point_up':
                keys['KeyW'] = true;
                break;
            case 'point_down':
                keys['KeyS'] = true;
                break;
            case 'point_left':
                keys['KeyA'] = true;
                break;
            case 'point_right':
                keys['KeyD'] = true;
                break;
            case 'fist':
                // Attack (throttled)
                if (now - this._lastGestureTime > 500) {
                    keys['Space'] = true;
                    setTimeout(() => { keys['Space'] = false; }, 200);
                    this._lastGestureTime = now;
                    this._showGestureAction('ATTACK');
                }
                break;
            case 'thumbs_up':
                // Interact/poke (throttled)
                if (now - this._lastGestureTime > 1000) {
                    WorldMode.pokeAgent();
                    this._lastGestureTime = now;
                    this._showGestureAction('POKE');
                }
                break;
            case 'peace':
                // Toggle bridge (throttled)
                if (now - this._lastGestureTime > 1500) {
                    if (typeof Bridge !== 'undefined') Bridge.toggle();
                    this._lastGestureTime = now;
                    this._showGestureAction('BRIDGE');
                }
                break;
            case 'open':
                // Stop — all keys already released above
                break;
            case 'none':
                // No hand — stop
                break;
        }
    },

    _showGestureAction(label) {
        const el = document.getElementById('gesture-action');
        if (!el) return;
        el.textContent = label;
        el.style.opacity = '1';
        clearTimeout(this._actionTimeout);
        this._actionTimeout = setTimeout(() => { el.style.opacity = '0'; }, 1200);
    },

    _updateUI() {
        const btn = document.getElementById('btn-gesture');
        if (btn) {
            btn.classList.toggle('active', this.active);
            btn.title = this.active ? 'Gestures ON (H)' : 'Gestures OFF (H)';
        }
    }
};
